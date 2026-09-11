import contextlib
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/beeper/scripts"))
from beeper import Runtime, Failure, write_json
from browser_login import Handoff, prepare, node_call
from test_onboarding import FakeBeeper, TOKEN

REPO = Path(__file__).resolve().parents[1]
SECRET = "synthetic-browser-session-only"


class BrowserLoginTests(unittest.TestCase):
    def setUp(self):
        cache = Path.home() / ".cache/beeper-plugin-tests"
        cache.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=cache)
        self.root = Path(self.temp.name)
        self.runtime = Runtime(self.root)
        self.api = FakeBeeper()
        write_json(self.runtime.target_file, {"id":"grok-bot", "type":"server", "baseURL":self.api.base, "auth":{"accessToken":TOKEN}})
        self.runtime.connect("test-bridge", "password-flow")
        self.api.network.update(status="waiting_for_cookies", currentStep={"stepID":"cookies", "type":"cookies", "url":"https://www.instagram.com/", "fields":[{"id":"sessionid", "type":"cookie"}]})

    def tearDown(self):
        self.api.close()
        self.temp.cleanup()

    @contextlib.contextmanager
    def handoff(self, ttl=600):
        plan, snapshot = prepare(self.runtime)
        with Handoff(self.runtime, plan, snapshot, ttl) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                yield server
            finally:
                server.shutdown()
                thread.join()

    def envelope(self, server, payload=None, descriptor=None):
        data = {"descriptor":descriptor or server.descriptor, "payload":payload or {"fields":{"sessionid":SECRET}, "lastURL":"https://www.instagram.com/"}}
        source = "import {encrypt} from './browser-extension/protocol.mjs'; let raw=''; for await(const c of process.stdin) raw+=c; const d=JSON.parse(raw); process.stdout.write(JSON.stringify(await encrypt(d.descriptor,d.payload)));"
        result = subprocess.run(["node", "--input-type=module", "-e", source], input=json.dumps(data), text=True, capture_output=True, cwd=REPO, timeout=10, check=True)
        self.assertNotIn(SECRET, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def post(self, server, envelope, capability=None):
        request = urllib.request.Request(f"http://127.0.0.1:{server.server_port}/handoff/{server.descriptor['id']}", data=json.dumps(envelope).encode(), headers={"Content-Type":"application/json", "Origin":"chrome-extension://" + "a" * 32, "X-Beeper-Pairing":capability or server.descriptor["capability"]})
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as response:
            with response:
                return response.code, json.load(response)

    def submissions(self):
        return [b for m,p,b,_ in self.api.requests if m == "POST" and "/steps/" in p]

    def test_encrypted_handoff_submits_once_without_persisting_session(self):
        with self.handoff() as server:
            envelope = self.envelope(server)
            self.assertEqual(self.post(server, envelope), (200, {"submitted":True}))
            self.assertEqual(self.post(server, envelope)[0], 410)
            self.assertEqual(len(self.submissions()), 1)
            self.assertEqual(self.submissions()[0]["source"], "browser_extension")
            self.assertEqual(self.submissions()[0]["fields"], {"sessionid":SECRET})
            self.assertNotIn(SECRET, json.dumps(server.result))
            self.assertIsNone(server.private_key)
        self.assertNotIn(SECRET, self.runtime.state_file.read_text())

    def test_wrong_capability_and_tampering_do_not_consume_handoff(self):
        with self.handoff() as server:
            envelope = self.envelope(server)
            self.assertEqual(self.post(server, envelope, "wrong")[0], 403)
            tampered = {**envelope, "iv":"AAAAAAAAAAAAAAAA"}
            self.assertEqual(self.post(server, tampered)[0], 400)
            changed = copy.deepcopy(server.descriptor)
            changed["origin"] = "https://different.trycloudflare.com"
            self.assertEqual(self.post(server, self.envelope(server, descriptor=changed))[0], 400)
            self.assertFalse(server.used)
            self.assertEqual(self.post(server, envelope)[0], 200)

    def test_storage_key_reordering_preserves_authenticated_descriptor(self):
        with self.handoff() as server:
            reordered = json.loads(json.dumps(server.descriptor, sort_keys=True))
            self.assertEqual(self.post(server, self.envelope(server, descriptor=reordered))[0], 200)

    def test_expired_changed_and_cancelled_sessions_never_submit(self):
        with self.handoff(ttl=-1) as server:
            self.assertEqual(self.post(server, self.envelope(server))[0], 410)
        with self.handoff() as server:
            self.api.network["currentStep"]["stepID"] = "new-step"
            self.assertEqual(self.post(server, self.envelope(server))[0], 409)
        with self.handoff() as server:
            self.runtime.update(network=None)
            self.assertEqual(self.post(server, self.envelope(server))[0], 409)
        self.assertEqual(self.submissions(), [])

    def test_wrong_domain_extra_fields_and_missing_required_fields_rejected(self):
        with self.handoff() as server:
            for payload in [
                {"fields":{"sessionid":SECRET}, "lastURL":"https://instagram.com.evil.example/"},
                {"fields":{"sessionid":SECRET, "unrequested":"other-secret"}, "lastURL":"https://www.instagram.com/"},
                {"fields":{}, "lastURL":"https://www.instagram.com/"},
            ]:
                self.assertEqual(self.post(server, self.envelope(server, payload))[0], 400)
        self.assertEqual(self.submissions(), [])

    def test_api_timeout_consumes_handoff_and_reports_uncertainty(self):
        with self.handoff() as server:
            original = self.runtime.api
            def api(method, *args, **kwargs):
                if method == "POST":
                    raise Failure("Inspect accounts before retrying.", "unreachable")
                return original(method, *args, **kwargs)
            with patch.object(self.runtime, "api", side_effect=api):
                envelope = self.envelope(server)
                self.assertEqual(self.post(server, envelope)[0], 409)
                self.assertEqual(self.post(server, envelope)[0], 410)
                self.assertEqual(server.result["error"]["code"], "unreachable")

    def test_provider_families_and_supported_sources(self):
        for domain in ["instagram.com", "facebook.com", "messenger.com", "linkedin.com", "x.com", "twitter.com", "discord.com", "slack.com"]:
            plan = node_call({"action":"plan", "step":{"type":"cookies", "url":"https://www." + domain + "/", "fields":[
                {"id":"session", "sources":[{"type":"cookie", "name":"session"}]},
                {"id":"storage", "sources":[{"type":"local_storage", "name":"token"}]},
                {"id":"header", "sources":[{"type":"request_header", "name":"Authorization", "requestURLRegex":"/api/"}]},
            ]}})
            self.assertEqual(plan["fields"][0]["sources"][0]["domain"], domain)
        for changes in [
            {"url":"https://instagram.com.evil.example/"},
            {"url":"http://instagram.com/"},
            {"fields":[{"id":"session", "sources":[{"type":"cookie", "name":"session", "cookieDomain":"google.com"}]}]},
            {"fields":[{"id":"session", "sources":[{"type":"special", "name":"eval"}]}], "extractJS":"alert('do not run')"},
        ]:
            step = {**self.api.network["currentStep"], **changes}
            with self.assertRaises(Failure): node_call({"action":"plan", "step":step})

    def test_cloud_choice_persists_and_resumes_without_duplicate_login(self):
        self.runtime.update(network=None)
        self.runtime.connect("test-bridge", "password-flow", browser="cloud")
        self.runtime.connect("test-bridge", "password-flow")
        self.assertEqual(self.runtime.state()["network"]["browser"], "cloud")
        self.assertEqual(sum(m == "POST" and p.endswith("/login-sessions") for m,p,_,_ in self.api.requests), 2)

    def test_extension_permission_cancel_and_header_scope(self):
        result = subprocess.run(["node", str(REPO / "tests/extension-events.mjs")], text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("EXTENSION_EVENT_TESTS_OK", result.stdout)

    @unittest.skipUnless(os.environ.get("BEEPER_BROWSER_TEST") == "1", "optional Chromium browser test")
    def test_real_chromium_cloud_collector(self):
        self.browser_test("cloud")

    @unittest.skipUnless(os.environ.get("BEEPER_BROWSER_TEST") == "1", "optional Chromium extension test")
    def test_real_chromium_extension_to_server(self):
        self.api.network["currentStep"]["fields"].extend([
            {"id":"storage", "type":"local_storage", "name":"test_storage"},
        ])
        with self.handoff() as server:
            try:
                self.browser_test("extension", server.link())
            except AssertionError as exc:
                raise AssertionError(str(exc) + "\nReceiver result: " + json.dumps(server.result)) from None
            self.assertEqual(self.submissions()[0]["fields"], {"sessionid":SECRET, "storage":"synthetic-storage"})
            self.assertEqual(self.submissions()[0]["source"], "browser_extension")

    def browser_test(self, mode, link=None):
        binary = os.environ.get("BEEPER_TEST_CHROME", "/usr/bin/google-chrome")
        result = subprocess.run(["node", str(REPO / "tests/browser-smoke.mjs")], input=json.dumps({"mode":mode, "root":str(self.root), "link":link, "binary":binary}), text=True, capture_output=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn(SECRET, result.stdout + result.stderr)
        self.assertIn("SMOKE_OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
