import contextlib
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import urllib.error
import urllib.parse
import urllib.request

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/beeper/scripts"
sys.path.insert(0, str(SCRIPTS))
from beeper import Failure, Runtime, read_json, redact, write_json
from install import download
from private_input import make_server

TOKEN = "synthetic-private-access-token"
EMAIL_CODE = "synthetic-private-email-code"
PASSWORD = "synthetic-private-network-password"


class FakeBeeper:
    def __init__(self):
        self.requests = []
        self.signed_in = False
        self.register = False
        self.verification = {"id": "verify-1", "state": "sas_ready", "availableActions": ["sas.confirm", "cancel"], "sas": {"emojis": "👍 🌽 🌽 📁 📎 🐙 🔑"}}
        self.network = None
        api = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def handle_api(self):
                payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                api.requests.append((self.command, self.path, payload, self.headers.get("Authorization")))
                status, result = api.respond(self.command, self.path, payload)
                self.send_response(status)
                if self.path == "/redirect":
                    self.send_header("Location", api.base + "/should-not-receive-token")
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(result).encode())

            do_GET = handle_api
            do_POST = handle_api
            do_DELETE = handle_api

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def respond(self, method, path, body):
        setup = "/v1/app/setup"
        if path == "/redirect":
            return 302, {}
        if path == "/secret-error":
            return 400, {"message": "Echoed submitted password: " + PASSWORD}
        if path == setup:
            data = {"state": "needs-verification" if self.signed_in else "needs-login", "e2ee": {"verified": False, "firstSyncDone": False, "secrets": {"masterKey": False}}}
            if self.signed_in:
                data["matrix"] = {"userID": "@test:example.org", "deviceID": "device"}
            return 200, data
        if path == setup + "/start":
            return 200, {"setupRequestID": "email-request-1"}
        if path == setup + "/email":
            return 200, {}
        if path == setup + "/response":
            if body.get("response") != EMAIL_CODE:
                return 400, {"message": body.get("response")}
            if self.register:
                return 200, {"registrationRequired": True, "leadToken": TOKEN, "setupRequestID": "email-request-1"}
            self.signed_in = True
            return 200, {"matrix": {"accessToken": TOKEN}, "session": {"state": "needs-verification"}}
        if path == setup + "/register":
            if not body.get("acceptTerms"):
                return 400, {}
            self.signed_in = True
            return 200, {"matrix": {"accessToken": TOKEN}}
        if path.startswith(setup + "/verifications"):
            if path.endswith("/sas/confirm"):
                self.verification["state"] = "done"
                self.verification["availableActions"] = []
            if path.endswith("/cancel"):
                self.verification["state"] = "cancelled"
                self.verification["availableActions"] = []
            return 200, {"verification": self.verification}
        if path == "/v1/bridges":
            return 200, {"items": [{"id": "test-bridge", "status": "available", "displayName": "Test network"}, {"id": "disabled", "status": "disabled"}]}
        if path.endswith("/login-flows"):
            return 200, {"items": [{"id": "password-flow", "name": "Password"}]}
        if path.endswith("/login-sessions") and method == "POST":
            self.network = {"bridgeID": "test-bridge", "loginSessionID": "network-1", "status": "waiting_for_input", "currentStep": {"stepID": "phone", "type": "user_input", "fields": [{"id": "phone", "label": "Phone number", "type": "text"}]}}
            return 200, self.network
        if "/steps/" in path:
            if path.endswith("/phone"):
                self.network["currentStep"] = {"stepID": "otp", "type": "user_input", "fields": [{"id": "otp", "label": "Two-factor code"}]}
            else:
                self.network.update(status="complete", accountID="account-1", currentStep={"type": "complete"})
            return 200, self.network
        if "/login-sessions/" in path:
            if method == "DELETE":
                self.network["status"] = "cancelled"
            return 200, self.network
        if path == "/v1/accounts":
            return 200, [{"accountID": "account-1", "status": "connected"}] if self.network and self.network["status"] == "complete" else []
        return 404, {}


class OnboardingTests(unittest.TestCase):
    def setUp(self):
        cache = Path.home() / ".cache/beeper-plugin-tests"
        cache.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=cache)
        self.root = Path(self.temp.name)
        self.api = FakeBeeper()
        self.runtime = Runtime(self.root)
        write_json(self.runtime.target_file, {"id": "grok-bot", "type": "server", "managed": True, "baseURL": self.api.base})

    def tearDown(self):
        self.api.close()
        self.temp.cleanup()

    def authenticate(self):
        self.runtime.finish_login({"matrix": {"accessToken": TOKEN}})
        self.api.signed_in = True

    def command(self, *arguments, success=True):
        env = dict(os.environ, BEEPER_PLUGIN_HOME=str(self.root), BEEPER_ACCESS_TOKEN="wrong-unrelated-desktop-token")
        result = subprocess.run([sys.executable, str(SCRIPTS / "beeper.py"), *arguments], env=env, text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
        for secret in (TOKEN, EMAIL_CODE, PASSWORD):
            self.assertNotIn(secret, result.stdout + result.stderr)
        return json.loads(result.stdout)

    @contextlib.contextmanager
    def form(self, kind):
        server = make_server(self.runtime, kind)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield server
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def submit_form(self, server, values, origin=None, csrf=None, host=None):
        with urllib.request.urlopen(server.url) as response:
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            self.assertEqual(response.headers["Referrer-Policy"], "same-origin")
            page = response.read().decode()
        csrf = csrf if csrf is not None else re.search('name="_csrf" value="([^"]+)"', page)[1]
        body = urllib.parse.urlencode(dict(values, _csrf=csrf)).encode()
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        if origin != "":
            headers["Origin"] = "http://" + server.address if origin is None else origin
        if host is not None:
            headers["Host"] = host
        request = urllib.request.Request(server.url, data=body, headers=headers)
        try:
            with urllib.request.urlopen(request) as response:
                output = response.read().decode()
        except urllib.error.HTTPError as exc:
            exc.close()
            raise
        for secret in (TOKEN, EMAIL_CODE, PASSWORD):
            self.assertNotIn(secret, page + output)
        return output

    def test_fresh_status_does_not_install_or_sign_in(self):
        self.runtime.target_file.unlink()
        data = self.command("status")["data"]
        self.assertFalse(data["cliInstalled"])
        self.assertFalse(data["targetConfigured"])
        self.assertEqual(self.api.requests, [])

    def test_email_resume_across_processes_and_private_token_storage(self):
        self.command("login", "--email", "test@example.org")
        self.command("login", "--email", "test@example.org")
        self.assertEqual(sum(p == "/v1/app/setup/email" for _, p, _, _ in self.api.requests), 1)
        with self.form("email") as form:
            self.submit_form(form, {"code": EMAIL_CODE})
            self.assertTrue(form.done)
        self.assertEqual(self.runtime.token(), TOKEN)
        self.assertEqual(self.runtime.target_file.stat().st_mode & 0o777, 0o600)
        self.assertNotIn(EMAIL_CODE, self.runtime.state_file.read_text())
        status = self.command("status")["data"]
        self.assertTrue(status["authenticated"])
        self.assertFalse(status["pendingEmail"])
        self.assertEqual(self.api.requests[-1][3], "Bearer " + TOKEN)

    def test_private_form_rejects_untrusted_origin_host_and_bad_csrf(self):
        self.runtime.login("test@example.org")
        with self.form("email") as form:
            for kwargs in ({"origin": "https://unrelated.example"}, {"origin": "null"},
                           {"origin": ""}, {"host": "unrelated.example"}, {"csrf": "incorrect"}):
                with self.subTest(**kwargs):
                    with self.assertRaises(urllib.error.HTTPError) as caught:
                        self.submit_form(form, {"code": EMAIL_CODE}, **kwargs)
                    self.assertEqual(caught.exception.code, 403)
            self.assertFalse(form.done)
        self.assertFalse(any(p.endswith("/response") for _, p, _, _ in self.api.requests))

    @unittest.skipUnless(os.environ.get("BEEPER_BROWSER_TEST") == "1", "Opt-in Chrome form test")
    def test_private_email_form_in_chrome(self):
        # Reuse the pipe-based browser driver so this test also runs on Node 20.
        chrome = os.environ.get("BEEPER_TEST_CHROME") or shutil.which("google-chrome") or shutil.which("chromium")
        node = shutil.which("node")
        self.assertTrue(chrome and node, "Browser test requires existing Chrome/Chromium and Node 20+")
        self.runtime.login("test@example.org")
        with self.form("email") as form:
            options = {"mode":"form", "root":str(self.root), "binary":chrome, "url":form.url, "code":EMAIL_CODE}
            result = subprocess.run([node, str(Path(__file__).with_name("browser-smoke.mjs"))],
                                    input=json.dumps(options), capture_output=True, text=True, timeout=25)
            self.assertEqual(result.returncode, 0, result.stderr)
            body = json.loads(result.stdout)["body"]
            self.assertIn("Submitted", body)
            for secret in (TOKEN, EMAIL_CODE, PASSWORD):
                self.assertNotIn(secret, body)
            self.assertTrue(form.done)
            self.assertTrue(self.api.signed_in)
            self.assertEqual(self.runtime.token(), TOKEN)

    def test_registration_requires_terms_and_preserves_pending_state(self):
        self.api.register = True
        self.runtime.login("new@example.org")
        with self.form("email") as form:
            self.submit_form(form, {"code": EMAIL_CODE})
        self.assertIsNone(self.runtime.token())
        self.assertTrue(self.command("status")["data"]["registrationRequired"])
        with self.form("register") as form:
            with self.assertRaises(urllib.error.HTTPError):
                self.submit_form(form, {"username": "new-user"})
            self.assertFalse(form.done)
            self.submit_form(form, {"username": "new-user", "acceptTerms": "on"})
        self.assertEqual(self.runtime.token(), TOKEN)

    def test_stale_email_form_cannot_submit_another_transaction(self):
        self.runtime.login("test@example.org")
        with self.form("email") as form:
            self.runtime.update(email={"address": "changed@example.org", "setupRequestID": "different-request"})
            with self.assertRaises(urllib.error.HTTPError):
                self.submit_form(form, {"code": EMAIL_CODE})
        self.assertFalse(any(p.endswith("/response") for _, p, _, _ in self.api.requests))

    def test_verification_rejects_changed_comparison_then_confirms_exact_one(self):
        self.authenticate()
        original = self.command("verify-start")["data"]["sas"]
        self.api.verification["sas"] = {"emojis": "🐶 🐱 🐭 🐹 🐰 🦊 🐻"}
        error = self.command("verify-confirm", "--matches", success=False)["error"]
        self.assertEqual(error["code"], "confirmation_required")
        self.assertFalse(any(p.endswith("/sas/confirm") for _, p, _, _ in self.api.requests))
        shown = self.command("verify-show")["data"]["sas"]
        self.assertNotEqual(shown, original)
        self.assertEqual(self.command("verify-confirm", "--matches")["data"]["state"], "done")
        self.assertNotIn("verification", self.runtime.state())

    def test_verification_cancel_never_confirms(self):
        self.authenticate()
        self.command("verify-start")
        self.assertEqual(self.command("verify-cancel")["data"]["state"], "cancelled")
        self.assertFalse(any(p.endswith("/sas/confirm") for _, p, _, _ in self.api.requests))

    def test_network_login_resumes_across_turns_and_handles_multiple_inputs(self):
        self.authenticate()
        self.command("connect", "test-bridge", "--flow", "password-flow")
        self.command("connect", "test-bridge", "--flow", "password-flow")
        self.assertEqual(sum(m == "POST" and p.endswith("/login-sessions") for m, p, _, _ in self.api.requests), 1)
        with self.form("network") as form:
            self.submit_form(form, {"phone": "+15550100000"})
        self.assertEqual(self.command("network-show")["data"]["step"]["stepID"], "otp")
        with self.form("network") as form:
            self.submit_form(form, {"otp": EMAIL_CODE})
        self.assertFalse(self.command("status")["data"]["pendingNetwork"])
        self.assertEqual(self.command("accounts")["data"][0]["accountID"], "account-1")
        for secret in (PASSWORD, EMAIL_CODE):
            self.assertNotIn(secret, self.runtime.state_file.read_text())

    def test_network_does_not_accept_stale_input_step(self):
        self.authenticate()
        self.runtime.connect("test-bridge", "password-flow")
        with self.form("network") as form:
            self.api.network["currentStep"]["stepID"] = "new-phone-step"
            with self.assertRaises(urllib.error.HTTPError):
                self.submit_form(form, {"phone": "+15550100000"})
        self.assertFalse(any("/steps/" in p for _, p, _, _ in self.api.requests))

    def test_disabled_bridge_and_unknown_flow_do_not_create_sessions(self):
        self.authenticate()
        self.command("connect", "disabled", success=False)
        self.command("connect", "test-bridge", "--flow", "invented", success=False)
        self.assertFalse(any(m == "POST" and p.endswith("/login-sessions") for m, p, _, _ in self.api.requests))

    def test_read_only_blocks_authentication_and_network_mutations(self):
        self.authenticate()
        with patch.dict(os.environ, {"BEEPER_READONLY": "true"}):
            with self.assertRaises(Failure) as caught:
                self.runtime.api("POST", "/v1/bridges/test-bridge/login-sessions", {})
        self.assertEqual(caught.exception.code, "read_only")
        self.assertEqual(self.api.requests, [])

    def test_bearer_token_is_not_forwarded_on_redirect(self):
        self.authenticate()
        with self.assertRaises(Failure) as caught:
            self.runtime.api("GET", "/redirect")
        self.assertEqual(caught.exception.code, "http_302")
        self.assertEqual([r[1] for r in self.api.requests], ["/redirect"])

    def test_server_error_does_not_echo_submitted_secrets(self):
        self.authenticate()
        with self.assertRaises(Failure) as caught:
            self.runtime.api("GET", "/secret-error")
        self.assertNotIn(PASSWORD, str(caught.exception))
        self.assertEqual(caught.exception.code, "http_400")

    def test_cli_uses_isolated_auth_and_rejects_endpoint_override(self):
        self.authenticate()
        with patch.dict(os.environ, {"BEEPER_ACCESS_TOKEN": "wrong", "BEEPER_CLI_CONFIG_DIR": "/wrong", "BEEPER_SERVER_BIN": "/wrong", "BEEPER_READONLY": "true"}):
            env = self.runtime.env()
        self.assertEqual(env["BEEPER_ACCESS_TOKEN"], TOKEN)
        self.assertEqual(env["BEEPER_CLI_CONFIG_DIR"], str(self.runtime.config))
        self.assertNotIn("BEEPER_SERVER_BIN", env)
        self.assertEqual(env["BEEPER_READONLY"], "true")
        self.command("cli", "--", "chats", "list", "--base-url=https://example.org", success=False)
        self.command("cli", "--", "install", "desktop", success=False)

    def test_operation_lock_prevents_concurrent_setup(self):
        with self.runtime.lock():
            self.assertEqual(self.command("login", "--email", "test@example.org", success=False)["error"]["code"], "busy")
        self.assertEqual(self.api.requests, [])

    def test_target_rejects_non_loopback_or_desktop(self):
        for target in ({"type": "server", "baseURL": "https://example.org"}, {"type": "desktop", "baseURL": self.api.base}):
            write_json(self.runtime.target_file, target)
            with self.assertRaises(Failure):
                self.runtime.api("GET", "/v1/accounts")
        self.assertEqual(self.api.requests, [])

    def test_download_refuses_wrong_checksum(self):
        with patch("urllib.request.urlopen", return_value=io.BytesIO(b"modified executable")):
            with self.assertRaisesRegex(RuntimeError, "checksum"):
                download("https://example.org/release", hashlib.sha256(b"expected executable").hexdigest())

    def test_redaction_includes_nested_credentials(self):
        output = json.dumps(redact({"auth": {"accessToken": TOKEN}, "password": PASSWORD, "items": [{"initialValue": EMAIL_CODE}], "recoveryKey": EMAIL_CODE}))
        for secret in (TOKEN, PASSWORD, EMAIL_CODE):
            self.assertNotIn(secret, output)

    def test_bootstrap_reuses_existing_installation_and_authenticated_target(self):
        self.authenticate()
        binary = self.root / "existing-server"
        binary.touch()
        write_json(self.runtime.config / "installations.json", {"server": {"path": str(binary), "version": "test-version", "channel": "nightly"}})
        before = self.runtime.target_file.read_bytes()
        with patch("install.install_tools", return_value={"cliVersion": "0.6.2"}), patch.object(self.runtime, "start") as start, patch.object(self.runtime, "cli") as cli:
            result = self.runtime.bootstrap()
        start.assert_called_once()
        cli.assert_not_called()
        self.assertEqual(self.runtime.target_file.read_bytes(), before)
        self.assertEqual(result["server"]["version"], "test-version")

    def test_bootstrap_restores_lost_executable_without_replacing_auth(self):
        self.authenticate()
        write_json(self.runtime.config / "installations.json", {"server": {"path": str(self.root / "missing-server")}})
        before = self.runtime.target_file.read_bytes()
        with patch("install.install_tools", return_value={}), patch.object(self.runtime, "start"), patch.object(self.runtime, "cli", return_value={"version": "restored"}) as cli:
            self.runtime.bootstrap()
        cli.assert_called_once_with(["install", "server", "--server-env", "production"], timeout=600)
        self.assertEqual(self.runtime.target_file.read_bytes(), before)

    def test_cli_only_bootstrap_does_not_install_or_start_server(self):
        with patch("install.install_tools", return_value={}), patch.object(self.runtime, "start") as start, patch.object(self.runtime, "cli") as cli:
            result = self.runtime.bootstrap(cli_only=True)
        start.assert_not_called()
        cli.assert_not_called()
        self.assertFalse(result["serverInstalled"])

    def test_cookie_fields_cannot_use_private_form(self):
        self.authenticate()
        self.runtime.connect("test-bridge", "password-flow")
        self.api.network["status"] = "waiting_for_cookies"
        self.api.network["currentStep"] = {"stepID": "cookies", "type": "cookies", "url": "https://provider.example/login", "fields": [{"id": "session", "type": "cookie"}]}
        with self.assertRaises(Failure) as caught:
            make_server(self.runtime, "network")
        self.assertEqual(caught.exception.code, "browser_login_required")
        self.assertFalse(any("/steps/" in p for _, p, _, _ in self.api.requests))

    def test_cookie_step_directs_to_provider_browser(self):
        self.authenticate()
        self.runtime.connect("test-bridge", "password-flow")
        self.api.network["status"] = "waiting_for_cookies"
        self.api.network["currentStep"] = {"stepID": "cookies", "type": "cookies", "url": "https://provider.example/login", "fields": [{"id": "session", "type": "cookie"}]}
        result = self.runtime.network_view(self.api.network)
        self.assertEqual(result["next"], "browser-start")
        self.assertEqual(result["browserMode"], "auto")
        self.assertEqual(result["step"]["url"], "https://provider.example/login")
        self.assertEqual(self.runtime.state()["network"]["loginSessionID"], "network-1")
        self.assertFalse(any("/steps/" in path for _, path, _, _ in self.api.requests))

    def test_missing_browser_backend_has_safe_specific_error(self):
        self.authenticate()
        self.runtime.binary.parent.mkdir(parents=True, exist_ok=True)
        self.runtime.binary.touch()
        output = json.dumps({"success": False, "error": "Bun.WebView is not available in this Bun runtime. " + TOKEN})
        process = subprocess.CompletedProcess([], 1, output, PASSWORD)
        with patch("beeper.subprocess.run", return_value=process):
            with self.assertRaises(Failure) as caught:
                self.runtime.cli(["accounts", "add", "test-bridge", "--webview"])
        self.assertEqual(caught.exception.code, "browser_unavailable")
        for secret in (TOKEN, PASSWORD):
            self.assertNotIn(secret, str(caught.exception))

    def test_network_display_poll_advances_and_removes_old_qr(self):
        self.authenticate()
        self.runtime.connect("test-bridge", "password-flow")
        self.api.network["status"] = "waiting_for_display"
        self.api.network["currentStep"] = {"stepID": "qr", "type": "display_and_wait", "display": {"type": "qr", "data": "private-qr-payload"}}
        (self.root / "network-qr.png").write_bytes(b"old-qr")
        result = self.command("network-poll")["data"]
        self.assertEqual(result["status"], "complete")
        self.assertFalse((self.root / "network-qr.png").exists())
        self.assertFalse(self.runtime.state().get("network"))

    def test_network_password_form_is_blocked(self):
        self.authenticate()
        self.runtime.connect("test-bridge", "password-flow")
        self.api.network["currentStep"] = {"type": "user_input", "stepID": "password", "fields": [{"id": "password", "type": "password"}]}
        self.assertEqual(self.runtime.network_view(self.api.network)["next"], "choose-supported-flow")
        with self.assertRaises(Failure) as caught:
            self.runtime.input_fields("network")
        self.assertEqual(caught.exception.code, "browser_unsupported")


if __name__ == "__main__":
    unittest.main()
