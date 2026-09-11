import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/beeper/scripts"))
from beeper import Runtime, Failure, write_json
from browser_login import prepare, node_call, submit, serve, describe
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

    def submissions(self):
        return [b for m,p,b,_ in self.api.requests if m == "POST" and "/steps/" in p]

    def test_browser_submission_is_scoped_and_does_not_persist_secrets(self):
        plan, snapshot = prepare(self.runtime)
        payload = {"fields":{"sessionid":SECRET}, "lastURL":"https://www.instagram.com/"}
        result = submit(self.runtime, snapshot, payload, plan)
        self.assertEqual(self.submissions()[0]["source"], "webview")
        self.assertEqual(self.submissions()[0]["fields"], payload["fields"])
        self.assertNotIn(SECRET, json.dumps(result) + self.runtime.state_file.read_text())
        with self.assertRaises(Failure): submit(self.runtime, snapshot, payload, plan)
        self.assertEqual(len(self.submissions()), 1)

    def test_wrong_domain_extra_fields_and_missing_required_fields_rejected(self):
        plan, snapshot = prepare(self.runtime)
        for payload in [
            {"fields":{"sessionid":SECRET}, "lastURL":"https://instagram.com.evil.example/"},
            {"fields":{"sessionid":SECRET, "unrequested":"other-secret"}, "lastURL":"https://www.instagram.com/"},
            {"fields":{}, "lastURL":"https://www.instagram.com/"},
        ]:
            with self.assertRaises(Failure): submit(self.runtime, snapshot, payload, plan)
        self.assertEqual(self.submissions(), [])

    def test_changed_and_cancelled_sessions_never_submit(self):
        plan, snapshot = prepare(self.runtime)
        payload = {"fields":{"sessionid":SECRET}, "lastURL":"https://www.instagram.com/"}
        self.api.network["currentStep"]["stepID"] = "new-step"
        with self.assertRaises(Failure): submit(self.runtime, snapshot, payload, plan)
        self.runtime.update(network=None)
        with self.assertRaises(Failure): submit(self.runtime, snapshot, payload, plan)
        self.assertEqual(self.submissions(), [])

    def test_native_requires_endpoint_and_never_installs_companion(self):
        with patch("browser_login.cloud") as cloud:
            for mode in ("native", "local"):
                with self.assertRaises(Failure) as caught: serve(self.runtime, mode)
                self.assertEqual(caught.exception.code, "native_browser_unavailable")
            cloud.assert_not_called()
        self.assertFalse((self.root / "bin").exists())

    def test_default_and_explicit_browser_routing(self):
        with patch("browser_login.cloud", return_value=0) as cloud:
            self.assertEqual(serve(self.runtime), 0)
            self.assertIsNone(cloud.call_args.args[-1])
            self.assertEqual(self.runtime.state()["network"]["browser"], "cloud")
            self.assertEqual(serve(self.runtime, "native", "http://127.0.0.1:9222"), 0)
            self.assertEqual(cloud.call_args.args[-1], "http://127.0.0.1:9222")
            for endpoint in ("http://192.168.1.10:9222", "https://example.com", "http://user:secret@127.0.0.1:9222", "http://127.0.0.1:9222/path", "http://127.0.0.1:9222/?token=secret"):
                with self.assertRaises(Failure) as caught: serve(self.runtime, "native", endpoint)
                self.assertEqual(caught.exception.code, "invalid_browser")

    def test_native_transport_rejects_redirects_and_remote_websockets(self):
        source = """
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {attachBrowser} from './skills/beeper/scripts/cloud_browser.mjs';
const server = createServer((req, res) => { res.writeHead(302, {Location:'http://example.invalid/json/version'}); res.end(); });
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
try { await assert.rejects(attachBrowser('http://127.0.0.1:' + server.address().port)); }
finally { await new Promise(resolve => server.close(resolve)); }
let fetched = false;
globalThis.fetch = async () => { fetched = true; throw Error(); };
for (const url of ['http://example.com:9222', 'http://127.0.0.1:9222/path', 'http://user:secret@127.0.0.1:9222']) await assert.rejects(attachBrowser(url));
assert.equal(fetched, false);
for (const url of ['ws://example.com:9222/devtools/browser/id', 'ws://127.0.0.1:9223/devtools/browser/id', 'ws://user:secret@127.0.0.1:9222/devtools/browser/id', 'ws://127.0.0.1:9222/devtools/browser/id?token=secret']) {
  globalThis.fetch = async () => ({ok:true, json:async () => ({webSocketDebuggerUrl:url})});
  await assert.rejects(attachBrowser('http://127.0.0.1:9222'));
}
"""
        result = subprocess.run(["node", "--experimental-websocket", "--input-type=module", "-e", source], cwd=REPO, text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_plan_reports_only_selected_provider_origins(self):
        result = describe(self.runtime)
        self.assertEqual(result["origins"], ["https://instagram.com", "https://www.instagram.com"])
        self.assertEqual(result["provider"], "instagram")
        self.assertNotIn(SECRET, json.dumps(result))

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

    def test_browser_check_uses_existing_runtime_without_download_or_account(self):
        destination = self.root / "no-install"
        before = len(self.api.requests)
        result = subprocess.run([sys.executable, str(REPO / "skills/beeper/scripts/beeper.py"), "browser-check"],
                                env={**os.environ, "BEEPER_PLUGIN_HOME":str(destination)}, text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        data = json.loads(result.stdout)["data"]
        version = subprocess.check_output(["node", "--version"], text=True).strip().removeprefix("v")
        self.assertEqual(data["nodeVersion"], version)
        self.assertTrue(data["browserRuntimeReady"])
        self.assertTrue(data["nativeBrowserTransportReady"])
        self.assertFalse(data["downloadsPerformed"])
        self.assertFalse(destination.exists())
        self.assertEqual(len(self.api.requests), before)

    def test_missing_runtime_is_distinct_from_unsupported_login(self):
        with patch("browser_login.shutil.which", return_value=None):
            with self.assertRaises(Failure) as caught:
                node_call({"action":"probe"})
        self.assertEqual(caught.exception.code, "browser_runtime_unavailable")
        self.assertTrue(node_call({"action":"probe"})["browserRuntimeReady"])
        with self.assertRaises(Failure) as caught:
            node_call({"action":"plan", "step":{"type":"user_input"}})
        self.assertEqual(caught.exception.code, "browser_unsupported")

    @unittest.skipUnless(os.environ.get("BEEPER_BROWSER_TEST") == "1", "optional Chromium browser test")
    def test_real_chromium_cloud_collector(self):
        self.browser_test("cloud")

    @unittest.skipUnless(os.environ.get("BEEPER_BROWSER_TEST") == "1", "optional Chromium browser test")
    def test_real_chromium_native_import_receiver(self):
        self.browser_test("native")

    def browser_test(self, mode):
        binary = os.environ.get("BEEPER_TEST_CHROME", "/usr/bin/google-chrome")
        result = subprocess.run(["node", "--experimental-websocket", str(REPO / "tests/browser-smoke.mjs")], input=json.dumps({"mode":mode, "root":str(self.root), "binary":binary}), text=True, capture_output=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn(SECRET, result.stdout + result.stderr)
        self.assertIn("SMOKE_OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
