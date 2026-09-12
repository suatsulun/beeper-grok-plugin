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
            for mode in ("native",):
                with self.assertRaises(Failure) as caught: serve(self.runtime, mode)
                self.assertEqual(caught.exception.code, "native_browser_unavailable")
            cloud.assert_not_called()
        self.assertFalse((self.root / "bin").exists())

    def test_default_and_explicit_browser_routing(self):
        with patch("browser_login.cloud", return_value=0) as cloud:
            with patch("browser_login.emit") as emit:
                self.assertEqual(serve(self.runtime), 0)
                self.assertEqual(emit.call_args.args[0]["data"]["state"], "local-browser-required")
            cloud.assert_not_called()
            self.assertEqual(self.runtime.state()["network"]["browser"], "local")
            self.assertEqual(serve(self.runtime, "cloud"), 0)
            self.assertIsNone(cloud.call_args.args[-1])
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

    def test_instagram_optional_cookies_do_not_block_but_core_cookies_still_do(self):
        required = ["sessionid", "csrftoken", "ds_user_id"]
        optional = ["rur", "shbid", "shbts", "mid", "ig_did"]
        self.api.network["currentStep"]["fields"] = [{"id": name, "type": "cookie"} for name in required + optional]
        plan, snapshot = prepare(self.runtime)
        self.assertEqual([f["id"] for f in plan["fields"] if f["required"]], required)
        self.assertEqual([f["id"] for f in plan["fields"] if not f["required"]], optional)
        fields = {"sessionid": SECRET, "csrftoken": "synthetic-csrf", "ds_user_id": "123"}
        for name in required:
            with self.subTest(missing=name), self.assertRaises(Failure):
                submit(self.runtime, snapshot, {"fields": {k: v for k, v in fields.items() if k != name}, "lastURL": plan["url"]}, plan)
        self.assertEqual(self.submissions(), [])
        node_call({"action": "validate", "plan": plan, "payload": {"fields": {**fields, "shbid": "synthetic-optional"}, "lastURL": plan["url"]}})
        submit(self.runtime, snapshot, {"fields": fields, "lastURL": plan["url"]}, plan)
        self.assertEqual(self.submissions()[0]["fields"], fields)
        self.assertNotIn("shbid", self.submissions()[0]["fields"])
        self.assertNotIn("shbts", self.submissions()[0]["fields"])

    def test_explicit_cookie_flags_override_provider_defaults(self):
        for flags, expected in [({}, False), ({"required": True}, True), ({"required": False}, False),
                                ({"optional": False}, True), ({"optional": True}, False),
                                ({"required": True, "optional": True}, True),
                                ({"required": False, "optional": False}, False)]:
            with self.subTest(flags=flags):
                step = {**self.api.network["currentStep"], "fields": [{"id": "sessionid"}, {"id": "shbid", **flags}]}
                plan = node_call({"action": "plan", "step": step})
                self.assertIs(plan["fields"][1]["required"], expected)
                payload = {"fields": {"sessionid": SECRET}, "lastURL": plan["url"]}
                if expected:
                    with self.assertRaises(Failure): node_call({"action": "validate", "plan": plan, "payload": payload})
                else:
                    node_call({"action": "validate", "plan": plan, "payload": payload})
        for flags in ({"required": "false"}, {"optional": "true"}):
            with self.assertRaises(Failure):
                node_call({"action": "plan", "step": {**self.api.network["currentStep"], "fields": [{"id": "sessionid", **flags}]}})

    def test_instagram_defaults_are_scoped_to_known_cookie_sources(self):
        for url, field, required in [
            ("https://www.facebook.com/", {"id": "shbid"}, True),
            ("https://www.instagram.com/", {"id": "unknown_cookie"}, True),
            ("https://www.instagram.com/", {"id": "shbid", "type": "local_storage"}, True),
            ("https://www.instagram.com/", {"id": "shbid", "type": "header"}, True),
            ("https://www.instagram.com/", {"id": "shbid", "name": "other_cookie"}, True),
            ("https://www.instagram.com/", {"id": "routing", "sources": [{"type": "cookie", "name": "shbid"}]}, False),
        ]:
            with self.subTest(url=url, field=field):
                plan = node_call({"action": "plan", "step": {"type": "cookies", "url": url, "fields": [{"id": "sessionid"}, field]}})
                self.assertIs(plan["fields"][1]["required"], required)

    def test_network_summary_preserves_flags_and_plan_reports_effective_requirements(self):
        self.api.network["currentStep"]["fields"] = [
            {"id": "sessionid", "required": True}, {"id": "shbid", "required": False}, {"id": "shbts"}]
        view = self.runtime.network_view(self.api.network)
        self.assertIs(view["step"]["fields"][1]["required"], False)
        self.assertNotIn("required", view["step"]["fields"][2])
        plan = describe(self.runtime)
        self.assertEqual(plan["requiredFields"], ["sessionid"])
        self.assertEqual(plan["optionalFields"], ["shbid", "shbts"])
        self.assertIn("browser-plan", view["instruction"])

    def test_all_providers_accept_missing_optional_sources_and_validate_present_values(self):
        for domain in ("instagram.com", "facebook.com", "messenger.com", "linkedin.com", "x.com", "twitter.com", "discord.com", "discordapp.com", "slack.com"):
            for source_type in ("cookie", "local_storage", "request_header"):
                with self.subTest(domain=domain, source=source_type):
                    step = {"type": "cookies", "url": "https://" + domain + "/", "fields": [
                        {"id": "session", "required": True, "sources": [{"type": source_type, "name": "session"}]},
                        {"id": "extra", "required": False, "pattern": "^valid-", "sources": [{"type": source_type, "name": "extra"}]},
                        {"id": "unsupported_extra", "optional": True, "sources": [{"type": "special", "name": "unimplemented"}]},
                    ]}
                    plan = node_call({"action": "plan", "step": step})
                    self.assertEqual([f["id"] for f in plan["fields"]], ["session", "extra"])
                    for fields in ({"session": SECRET}, {"session": SECRET, "extra": "valid-optional"}):
                        node_call({"action": "validate", "plan": plan, "payload": {"fields": fields, "lastURL": plan["url"]}})
                    for fields in ({"extra": "valid-optional"}, {"session": SECRET, "extra": "invalid"}, {"session": SECRET, "extra": ""}):
                        with self.assertRaises(Failure):
                            node_call({"action": "validate", "plan": plan, "payload": {"fields": fields, "lastURL": plan["url"]}})

    def test_twitter_optional_browser_inputs_do_not_waive_authentication(self):
        step = {"type": "cookies", "url": "https://x.com/", "fields": [
            {"id": "auth_token"}, {"id": "ct0"}, {"id": "guest_id"},
            {"id": "browser_user_agent", "type": "header", "name": "User-Agent"},
            {"id": "browser_hint", "type": "header", "name": "Sec-CH-UA"},
            {"id": "castle_token", "sources": [{"type": "local_storage", "name": "fi.mau.twitter.castle_token"}]},
            {"id": "castle_token_2", "sources": [{"type": "local_storage", "name": "fi.mau.twitter.castle_token_2"}]},
            {"id": "guest_from_storage", "sources": [{"type": "local_storage", "name": "fi.mau.twitter.cookie.guest_id"}]},
        ]}
        plan = node_call({"action": "plan", "step": step})
        required = [f["id"] for f in plan["fields"] if f["required"]]
        self.assertEqual(required, ["auth_token", "ct0", "browser_user_agent", "castle_token"])
        fields = {name: "synthetic-required" for name in required}
        node_call({"action": "validate", "plan": plan, "payload": {"fields": fields, "lastURL": plan["url"]}})
        for name in required:
            with self.subTest(missing=name), self.assertRaises(Failure):
                node_call({"action": "validate", "plan": plan, "payload": {"fields": {k: v for k, v in fields.items() if k != name}, "lastURL": plan["url"]}})
        step["fields"][2]["required"] = True
        strict = node_call({"action": "plan", "step": step})
        self.assertTrue(strict["fields"][2]["required"])
        step["url"] = "https://www.facebook.com/"
        other = node_call({"action": "plan", "step": step})
        self.assertTrue(all(f["required"] for f in other["fields"]))

    def test_documented_facebook_and_linkedin_requirements_remain_required(self):
        for domain, fields in [
            ("facebook.com", [{"id": name} for name in ("xs", "c_user", "datr")]),
            ("messenger.com", [{"id": name} for name in ("xs", "c_user", "datr")]),
            ("linkedin.com", [{"id": name, "type": "header", "name": name} for name in ("Cookie", "X-LI-Track", "X-LI-Page-Instance")]),
        ]:
            with self.subTest(domain=domain):
                plan = node_call({"action": "plan", "step": {"type": "cookies", "url": "https://" + domain + "/", "fields": fields}})
                self.assertTrue(all(f["required"] for f in plan["fields"]))
                with self.assertRaises(Failure):
                    node_call({"action": "validate", "plan": plan, "payload": {"fields": {}, "lastURL": plan["url"]}})

    def test_unsupported_extraction_is_rejected_instead_of_guessed_as_a_cookie(self):
        for field in [
            {"id": "auth_token", "required": True, "sources": [{"type": "special", "name": "fi.mau.slack.auth_token"}, {"type": "request_body", "name": "token"}]},
            {"id": "future", "type": "future_storage"},
            {"id": "special", "type": "special"},
        ]:
            with self.subTest(field=field), self.assertRaises(Failure):
                node_call({"action": "plan", "step": {"type": "cookies", "url": "https://slack.com/signin", "fields": [field], "extractJS": "throw new Error('never execute')"}})

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
