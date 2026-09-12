import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/beeper/scripts"))
from beeper import Runtime, Failure, read_json, write_json
from browser_login import prepare
from local_transfer import prepare_transfer, finish_transfer, cancel_transfer
from test_onboarding import FakeBeeper, TOKEN

REPO = Path(__file__).resolve().parents[1]
SECRET = "synthetic-local-session"


class LocalTransferTests(unittest.TestCase):
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
        with self.runtime.lock():
            self.info = prepare_transfer(self.runtime, *prepare(self.runtime))
        self.state_file = self.root / "browser-transfer.json"
        self.state = read_json(self.state_file)

    def tearDown(self):
        self.api.close()
        self.temp.cleanup()

    def encrypted(self, request=None):
        data = {"request":request or self.state["request"], "payload":{"fields":{"sessionid":SECRET}, "lastURL":"https://www.instagram.com/"}}
        script = "import {seal} from './skills/beeper/scripts/browser_transfer.mjs'; let s=''; for await (const c of process.stdin) s+=c; const x=JSON.parse(s); process.stdout.write(JSON.stringify(seal(x.request,x.payload)));"
        result = subprocess.run(["node", "--input-type=module", "-e", script], input=json.dumps(data), cwd=REPO, text=True, capture_output=True, timeout=10, check=True)
        self.assertNotIn(SECRET, result.stdout + result.stderr)
        destination = self.root / "encrypted.json"
        destination.write_text(result.stdout)
        return destination

    def submissions(self):
        return [body for method, path, body, _ in self.api.requests if method == "POST" and "/steps/" in path]

    def finish_command(self, envelope):
        result = subprocess.run([sys.executable, str(REPO / "skills/beeper/scripts/beeper.py"), "browser-finish", "--file", str(envelope)],
                                env={**os.environ, "BEEPER_PLUGIN_HOME":str(self.root)}, text=True, capture_output=True, timeout=10)
        self.assertNotIn(SECRET, result.stdout + result.stderr)
        return result.returncode, json.loads(result.stdout)

    def test_cli_finish_reports_success_and_specific_replay_error(self):
        envelope = self.encrypted()
        code, result = self.finish_command(envelope)
        self.assertEqual(code, 0, result)
        self.assertEqual(result["data"]["status"], "complete")
        code, result = self.finish_command(envelope)
        self.assertEqual(code, 1)
        self.assertEqual(result["error"]["code"], "stale_input")
        self.assertEqual(len(self.submissions()), 1)

    def test_cli_finish_preserves_expired_and_invalid_transfer_errors(self):
        envelope = self.encrypted()
        envelope.write_text("{}")
        code, result = self.finish_command(envelope)
        self.assertEqual(code, 1)
        self.assertEqual(result["error"]["code"], "invalid_transfer")
        self.state["request"]["expires"] = int(time.time() * 1000) - 1
        write_json(self.state_file, self.state)
        code, result = self.finish_command(envelope)
        self.assertEqual(code, 1)
        self.assertEqual(result["error"]["code"], "browser_timeout")
        self.assertEqual(self.submissions(), [])

    def test_package_contains_only_public_request_and_verified_plugin_files(self):
        package = read_json(Path(self.info["localPackage"]))
        self.assertNotIn(self.state["privateKey"], json.dumps(package))
        self.assertNotIn(TOKEN, json.dumps(package))
        request = json.loads(base64.b64decode(package["files"]["request.json"]["base64"]))
        self.assertEqual(request, self.state["request"])
        for name, entry in package["files"].items():
            data = base64.b64decode(entry["base64"])
            self.assertEqual(hashlib.sha256(data).hexdigest(), entry["sha256"])
            if name != "request.json": self.assertEqual(data, (REPO / "skills/beeper/scripts" / name).read_bytes())
        self.assertEqual(self.state_file.stat().st_mode & 0o777, 0o600)

    def test_repeat_prepare_resumes_request_without_replacing_private_key(self):
        with self.runtime.lock(): prepare_transfer(self.runtime, *prepare(self.runtime))
        self.assertEqual(read_json(self.state_file), self.state)

    def test_updated_cookie_defaults_replace_old_request_without_restarting_login(self):
        self.api.network["currentStep"]["fields"] += [{"id": "shbid"}, {"id": "shbts"}]
        with self.runtime.lock(): prepare_transfer(self.runtime, *prepare(self.runtime))
        old = read_json(self.state_file)
        # Simulate a still-valid v0.6.0 request that marked every cookie required.
        for field in old["request"]["plan"]["fields"]: field["required"] = True
        write_json(self.state_file, old)
        with self.runtime.lock(): result = prepare_transfer(self.runtime, *prepare(self.runtime))
        current = read_json(self.state_file)
        self.assertNotEqual(current["request"]["id"], old["request"]["id"])
        self.assertNotEqual(current["privateKey"], old["privateKey"])
        self.assertEqual(current["snapshot"], old["snapshot"])
        self.assertEqual(result["requiredFields"], ["sessionid"])
        self.assertEqual(result["optionalFields"], ["shbid", "shbts"])
        self.assertEqual(sum(m == "POST" and p.endswith("/login-sessions") for m, p, _, _ in self.api.requests), 1)
        self.assertEqual(self.submissions(), [])

    def test_encrypted_delivery_succeeds_once_without_persisting_session(self):
        envelope = self.encrypted()
        result = finish_transfer(self.runtime, envelope)
        self.assertEqual(self.submissions()[0]["fields"], {"sessionid":SECRET})
        self.assertNotIn(SECRET, json.dumps(result) + self.runtime.state_file.read_text())
        self.assertFalse(self.state_file.exists())
        with self.assertRaises(Failure): finish_transfer(self.runtime, envelope)
        self.assertEqual(len(self.submissions()), 1)

    def test_tampering_and_descriptor_changes_do_not_submit(self):
        envelope = self.encrypted()
        original = json.loads(envelope.read_text())
        envelope.write_text(json.dumps({**original, "tag":"AAAAAAAAAAAAAAAAAAAAAA"}))
        with self.assertRaises(Failure): finish_transfer(self.runtime, envelope)
        changed = copy.deepcopy(self.state["request"])
        changed["plan"]["expectedFinalURLRegex"] = ".*"
        with self.assertRaises(Failure): finish_transfer(self.runtime, self.encrypted(changed))
        self.assertEqual(self.submissions(), [])
        self.assertIn("privateKey", read_json(self.state_file))
        envelope.write_text(json.dumps(original))
        finish_transfer(self.runtime, envelope)
        self.assertEqual(len(self.submissions()), 1)

    def test_expired_and_cancelled_transfers_never_submit(self):
        envelope = self.encrypted()
        self.state["request"]["expires"] = int(time.time() * 1000) - 1
        write_json(self.state_file, self.state)
        with self.assertRaises(Failure) as caught: finish_transfer(self.runtime, envelope)
        self.assertEqual(caught.exception.code, "browser_timeout")
        self.assertFalse(self.state_file.exists())
        with self.runtime.lock(): prepare_transfer(self.runtime, *prepare(self.runtime))
        cancel_transfer(self.runtime)
        with self.assertRaises(Failure): finish_transfer(self.runtime, envelope)
        self.assertTrue(self.runtime.state()["network"])
        self.assertEqual(self.submissions(), [])

    def test_changed_step_and_network_cancel_invalidate_private_key(self):
        envelope = self.encrypted()
        self.api.network["currentStep"]["stepID"] = "next"
        with self.assertRaises(Failure): finish_transfer(self.runtime, envelope)
        self.assertFalse(self.state_file.exists())
        with self.runtime.lock(): prepare_transfer(self.runtime, *prepare(self.runtime))
        self.runtime.update(network=None)
        self.assertFalse(self.state_file.exists())
        self.assertEqual(self.submissions(), [])

    def test_ambiguous_api_failure_consumes_transfer_without_retry(self):
        envelope = self.encrypted()
        original = self.runtime.api
        attempts = []
        def api(method, *args, **kwargs):
            if method == "POST":
                attempts.append(1)
                raise Failure("Ambiguous response.", "unreachable")
            return original(method, *args, **kwargs)
        with patch.object(self.runtime, "api", side_effect=api):
            with self.assertRaises(Failure): finish_transfer(self.runtime, envelope)
            with self.assertRaises(Failure): finish_transfer(self.runtime, envelope)
        self.assertEqual(len(attempts), 1)
        self.assertEqual(read_json(self.state_file), {"consumed":True, "id":self.state["request"]["id"]})

    @unittest.skipUnless(os.environ.get("BEEPER_BROWSER_TEST") == "1", "optional real Chromium local browser test")
    def test_existing_pc_browser_and_fresh_login_require_real_form_approval(self):
        self.api.network["currentStep"]["fields"] = [{"id": name, "type": "cookie"} for name in
            ("sessionid", "csrftoken", "ds_user_id", "rur", "shbid", "shbts", "mid", "ig_did")]
        with self.runtime.lock(): prepare_transfer(self.runtime, *prepare(self.runtime))
        self.state = read_json(self.state_file)
        binary = os.environ.get("BEEPER_TEST_CHROME", "/usr/bin/google-chrome")
        result = subprocess.run(["node", "--experimental-websocket", str(REPO / "tests/local-browser-smoke.mjs")],
                                input=json.dumps({"root":str(self.root), "binary":binary, "request":self.state["request"]}),
                                text=True, capture_output=True, timeout=90)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn(SECRET, result.stdout + result.stderr)
        data = json.loads(result.stdout)
        self.assertTrue(data["freshApproved"])
        self.assertTrue(data["existingApproved"])
        self.assertTrue(data["deniedWithoutTransfer"])
        envelope = self.root / "encrypted.json"
        envelope.write_text(json.dumps(data["envelope"]))
        finish_transfer(self.runtime, envelope)
        self.assertEqual(self.submissions()[0]["fields"], {"sessionid": SECRET, "csrftoken": "synthetic-csrf", "ds_user_id": "123"})


if __name__ == "__main__":
    unittest.main()
