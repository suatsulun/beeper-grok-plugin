#!/usr/bin/env python3
"""Beeper Server onboarding for agents. JSON output never includes stored credentials."""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib

TARGET = "grok-bot"
SETUP = "/v1/app/setup"
TERMINAL = {"complete", "cancelled", "failed"}


class Failure(Exception):
    def __init__(self, message, code="operation_failed"):
        super().__init__(message)
        self.code = code


def read_json(path, default=None):
    if not path.exists():
        return {} if default is None else default
    return json.loads(path.read_text())


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_suffix(".part")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    temp.chmod(0o600)
    temp.replace(path)


def redact(value):
    if isinstance(value, dict):
        return {k: ("[redacted]" if any(s in k.lower().replace("_", "") for s in
                ("token", "password", "authorization", "cookie", "initialvalue")) or
                (k.lower().replace("_", "") == "recoverykey" and isinstance(v, str)) else redact(v))
                for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def emit(data):
    print(json.dumps(data, ensure_ascii=False), flush=True)


def segment(value):
    return urllib.parse.quote(value, safe="")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Runtime:
    def __init__(self, root=None):
        os.umask(0o077)
        default = Path("/workspace/.beeper-grok") if Path("/workspace").is_dir() else Path.home() / ".local/share/beeper-grok-plugin"
        self.root = Path(root or os.environ.get("BEEPER_PLUGIN_HOME", default)).expanduser().resolve()
        self.config = self.root / "config"
        self.target_file = self.config / "targets" / f"{TARGET}.json"
        self.state_file = self.root / "onboarding.json"
        self.binary = self.root / "bin/beeper"

    @contextmanager
    def lock(self):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (self.root / "operation.lock").open("a") as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise Failure("Another Beeper operation is running. Resume after it finishes.", "busy")
            yield

    def writable(self):
        if os.environ.get("BEEPER_READONLY", "").lower() in ("1", "true", "yes"):
            raise Failure("BEEPER_READONLY prevents this operation.", "read_only")

    def state(self):
        return read_json(self.state_file)

    def update(self, **values):
        data = self.state()
        for key, value in values.items():
            if value is None:
                data.pop(key, None)
            else:
                data[key] = value
        write_json(self.state_file, data)

    def target(self):
        target = read_json(self.target_file)
        if not target:
            raise Failure("Run bootstrap to install and configure Beeper Server.", "not_installed")
        url = urllib.parse.urlsplit(target.get("baseURL", ""))
        if target.get("type") != "server" or url.scheme != "http" or url.hostname != "127.0.0.1" or not url.port or url.username or url.path not in ("", "/"):
            raise Failure("Expected the plugin's managed loopback Server target.", "invalid_target")
        return target

    def token(self):
        return self.target().get("auth", {}).get("accessToken")

    def env(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith("BEEPER_") or k == "BEEPER_READONLY"}
        env.update({"BEEPER_CLI_CONFIG_DIR": str(self.config), "BEEPER_TARGET": TARGET,
                    "BEEPER_CLI_BINARY_CACHE_DIR": str(self.root / "cache/binary"),
                    "XDG_CACHE_HOME": str(self.root / "cache"), "TMPDIR": str(self.root / "tmp")})
        for p in (self.root / "cache/binary", self.root / "tmp"):
            p.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.target_file.exists() and self.token():
            # CLI 0.6.2 diagnostics can discard target auth when resolving baseURL.
            env["BEEPER_ACCESS_TOKEN"] = self.token()
        return env

    def cli(self, arguments, timeout=90):
        if not self.binary.exists():
            raise Failure("Run bootstrap to install the Beeper CLI.", "not_installed")
        try:
            result = subprocess.run([str(self.binary), *arguments, "--json"], env=self.env(),
                                    capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise Failure("Beeper timed out. Inspect status before retrying a write.", "timeout")
        if result.returncode and "--webview" in arguments and "Bun.WebView is not available" in result.stdout + result.stderr:
            raise Failure("This Beeper CLI build cannot open the provider login browser because Bun.WebView is unavailable. Check accounts before retrying; do not substitute a password or cookie form.", "browser_unavailable")
        if "--help" in arguments and result.returncode == 0:
            return {"help": result.stdout}
        try:
            output = json.loads(result.stdout)
        except ValueError:
            raise Failure(f"Beeper returned a non-JSON result (exit {result.returncode}); raw output was withheld.", "cli_error")
        if result.returncode or output.get("success") is False:
            # Raw error text may contain credentials, cookies, or submitted fields.
            error = output.get("error") or {}
            code = error.get("code") if isinstance(error, dict) else None
            raise Failure(f"Beeper command failed (exit {result.returncode}, code {code or 'unknown'}). Check status and the command help.", "cli_error")
        return output.get("data", output)

    def api(self, method, path, body=None, public=False, timeout=30):
        if method != "GET":
            self.writable()
        target = self.target()
        headers = {"Accept": "application/json"}
        token = self.token()
        if not public and not token:
            raise Failure("Sign in to Beeper first.", "needs_login")
        if not public:
            headers["Authorization"] = "Bearer " + token
        payload = None
        if body is not None:
            payload = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(target["baseURL"].rstrip("/") + path, data=payload, headers=headers, method=method)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        try:
            with opener.open(request, timeout=timeout) as response:
                data = response.read()
            return json.loads(data) if data else {}
        except urllib.error.HTTPError as exc:
            code = exc.code
            exc.close()
            raise Failure(f"Beeper API returned HTTP {code}. Submitted values and response body were withheld.", f"http_{code}") from None
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            raise Failure("Beeper Server is unreachable or timed out. Check status before retrying.", "unreachable") from None

    def bootstrap(self, cli_only=False):
        self.writable()
        from install import install_tools
        tools = install_tools(self.root)
        if cli_only:
            return {"tools": tools, "serverInstalled": False}
        installation_file = self.config / "installations.json"
        installation = read_json(installation_file).get("server", {})
        if not installation.get("path") or not Path(installation["path"]).exists():
            installation = self.cli(["install", "server", "--server-env", "production"], timeout=600)
        if not self.target_file.exists():
            port = None
            for candidate in range(23374, 23574):
                with socket.socket() as probe:
                    try:
                        probe.bind(("127.0.0.1", candidate))
                        port = candidate
                        break
                    except OSError:
                        pass
            if port is None:
                raise Failure("No free loopback port for Beeper Server.")
            self.cli(["targets", "add", "server", TARGET, "--port", str(port), "--server-env", "production"])
        self.start()
        return {"tools": tools, "server": {k: installation.get(k) for k in ("version", "channel", "serverEnv")},
                "status": self.status(), "note": "CLI 0.6.2 currently downloads a nightly Server artifact; the target uses production authentication."}

    def start(self):
        self.writable()
        self.target()
        self.cli(["targets", "start", TARGET])
        deadline = time.monotonic() + 25
        while True:
            try:
                self.api("GET", SETUP, public=not bool(self.token()), timeout=2)
                return {"running": True}
            except Failure as exc:
                if exc.code.startswith("http_"):
                    return {"running": True, "authentication": exc.code}
                if time.monotonic() >= deadline:
                    raise Failure("Server started but did not become reachable within 25 seconds.", "startup_pending")
                time.sleep(1)

    def status(self):
        state = self.state()
        result = {"dataDirectory": str(self.root), "cliInstalled": self.binary.exists(),
                  "targetConfigured": self.target_file.exists(),
                  "pendingEmail": bool(state.get("email")), "registrationRequired": bool(state.get("registration")),
                  "pendingNetwork": bool(state.get("network"))}
        if not self.target_file.exists():
            return result
        result["baseURL"] = self.target()["baseURL"]
        try:
            setup = self.api("GET", SETUP, public=not bool(self.token()))
        except Failure as exc:
            result.update(reachable=exc.code.startswith("http_"), error=exc.code)
            return result
        e2ee = setup.get("e2ee", {})
        result.update(reachable=True, state=setup.get("state"), authenticated=bool(setup.get("matrix") and self.token()),
                      verified=e2ee.get("verified", False), firstSyncDone=e2ee.get("firstSyncDone", False),
                      secretsAvailable={k: v for k, v in e2ee.get("secrets", {}).items() if isinstance(v, bool)})
        if state.get("verification"):
            result["verificationID"] = state["verification"]["id"]
        return result

    def login(self, email):
        self.writable()
        if self.token():
            raise Failure("This target already has credentials. Check status; do not replace the account during setup.", "already_signed_in")
        pending = self.state().get("email")
        if pending:
            if pending.get("address") != email:
                raise Failure("An email sign-in is pending for another address. Use login-cancel before changing it.")
            return {"pendingEmail": True, "next": "input email"}
        data = self.api("POST", SETUP + "/start", public=True)
        self.api("POST", SETUP + "/email", {"setupRequestID": data["setupRequestID"], "email": email}, public=True)
        self.update(email={"address": email, "setupRequestID": data["setupRequestID"]})
        return {"pendingEmail": True, "next": "input email"}

    def finish_login(self, output):
        if output.get("registrationRequired"):
            self.update(registration=output, email=None)
            return {"registrationRequired": True, "next": "input register"}
        token = output.get("matrix", {}).get("accessToken")
        if not token:
            raise Failure("Beeper did not return an access token.", "login_incomplete")
        target = self.target()
        target["auth"] = {"accessToken": token, "tokenType": "Bearer", "source": "manual"}
        write_json(self.target_file, target)
        self.update(email=None, registration=None)
        return {"signedIn": True, "next": "status"}

    def verification(self, action, matches=False):
        pending = self.state().get("verification")
        if action == "start" and not pending:
            data = self.api("POST", SETUP + "/verifications", {"purpose": "login"})
            verification = data["verification"]
        elif pending:
            verification = self.api("GET", SETUP + "/verifications/" + segment(pending["id"]))["verification"]
        else:
            raise Failure("No verification started by this plugin. Use verify-start.")
        path = SETUP + "/verifications/" + segment(verification["id"])
        if action in ("accept", "sas", "confirm", "cancel"):
            name = {"accept": "accept", "sas": "sas.start", "confirm": "sas.confirm", "cancel": "cancel"}[action]
            if name not in verification.get("availableActions", []):
                raise Failure("That verification action is not available. Show the current state again.", "stale_verification")
            if action == "confirm":
                fingerprint = self.sas_fingerprint(verification)
                if not matches or not fingerprint or fingerprint != pending.get("shownSAS"):
                    raise Failure("Show the current comparison and obtain the user's exact match confirmation first.", "confirmation_required")
            suffix = {"accept": "/accept", "sas": "/sas/start", "confirm": "/sas/confirm", "cancel": "/cancel"}[action]
            verification = self.api("POST", path + suffix, {} if action == "cancel" else None)["verification"]
        self.update(verification=None if verification["state"] in ("done", "cancelled", "error") else
                    {"id": verification["id"], "shownSAS": self.sas_fingerprint(verification)})
        return {k: verification[k] for k in ("id", "state", "availableActions", "otherDevice", "sas") if k in verification}

    @staticmethod
    def sas_fingerprint(verification):
        sas = verification.get("sas")
        if not sas or not (sas.get("emojis") or sas.get("decimals")):
            return None
        return hashlib.sha256(json.dumps([verification["id"], sas], sort_keys=True).encode()).hexdigest()

    def network_path(self):
        pending = self.state().get("network")
        if not pending:
            raise Failure("No network login is pending. Use networks, flows, then connect.")
        return "/v1/bridges/" + segment(pending["bridgeID"]) + "/login-sessions/" + segment(pending["loginSessionID"])

    def network_session(self):
        return self.api("GET", self.network_path())

    def connect(self, bridge, flow=None, login_id=None):
        if self.state().get("network"):
            if self.state()["network"]["bridgeID"] != bridge:
                raise Failure("Another network login is pending. Finish or cancel it before connecting another.", "pending_network")
            return self.network_view(self.network_session())
        bridges = self.api("GET", "/v1/bridges").get("items", [])
        found = next((b for b in bridges if b["id"] == bridge), None)
        if not found or found.get("status") not in ("available", "connected"):
            raise Failure("Choose an available exact bridge ID from networks.", "bridge_unavailable")
        flows = self.api("GET", f"/v1/bridges/{segment(bridge)}/login-flows").get("items", [])
        if flow and not any(f["id"] == flow for f in flows):
            raise Failure("Choose a flow ID returned by flows.", "unknown_flow")
        if not flow and len(flows) > 1:
            return {"chooseFlow": True, "flows": flows}
        body = {"flowID": flow or flows[0]["id"]} if flows else {}
        if login_id:
            body["loginID"] = login_id
        session = self.api("POST", f"/v1/bridges/{segment(bridge)}/login-sessions", body)
        self.update(network={"bridgeID": bridge, "loginSessionID": session["loginSessionID"]})
        return self.network_view(session)

    def webview_connect(self, bridge, flow):
        self.writable()
        if self.state().get("network"):
            raise Failure("Finish or cancel the pending network flow before starting a browser login.", "pending_network")
        bridges = self.api("GET", "/v1/bridges").get("items", [])
        if not any(b["id"] == bridge and b["status"] in ("available", "connected") for b in bridges):
            raise Failure("Choose an available exact bridge ID from networks.", "bridge_unavailable")
        flows = self.api("GET", f"/v1/bridges/{segment(bridge)}/login-flows").get("items", [])
        if not any(f["id"] == flow for f in flows):
            raise Failure("Choose a flow ID returned by flows.", "unknown_flow")
        # The official CLI owns the provider's browser-cookie extraction. No
        # extracted cookies, passwords, or raw browser console output are printed.
        session = self.cli(["accounts", "add", bridge, "--flow", flow, "--webview", "--webview-backend", "chrome", "--webview-timeout", "600", "--non-interactive", "--target", TARGET], timeout=660)
        if not session.get("loginSessionID"):
            raise Failure("The CLI browser flow did not return a login session. Check accounts before retrying.", "browser_login_incomplete")
        self.update(network={"bridgeID": bridge, "loginSessionID": session["loginSessionID"]})
        return self.network_view(session)

    def network_view(self, session):
        step = session.get("currentStep") or {}
        result = {k: session[k] for k in ("bridgeID", "loginSessionID", "status", "accountID", "loginID") if k in session}
        result["step"] = {k: step[k] for k in ("type", "stepID", "instructions") if k in step}
        if step.get("fields"):
            result["step"]["fields"] = [{k: f[k] for k in ("id", "label", "type", "optional") if k in f} for f in step["fields"]]
            result["next"] = "input network"
        if step.get("url"):
            result["step"]["url"] = step["url"]
        if step.get("type") == "cookies":
            result["next"] = "webview-connect"
            result["instruction"] = "Use the provider's website through the official CLI browser flow. If this session was started with connect, cancel the pending login before restarting with webview-connect and the chosen flow ID. Do not ask the user to copy cookies."
        display = step.get("display", {})
        if display.get("type") == "qr":
            result["qrImage"] = str(self.render_qr(display["data"]))
        elif display:
            self.clear_qr()
            result["display"] = display
        else:
            self.clear_qr()
        if session["status"] in TERMINAL:
            self.update(network=None)
            self.clear_qr()
            result["next"] = "accounts, then check the connected account and read chats" if session["status"] == "complete" else "Explain the failed/cancelled login; start another only when appropriate."
        return result

    def network_poll(self):
        session = self.network_session()
        step = session.get("currentStep") or {}
        if session["status"] not in TERMINAL and step.get("type") == "display_and_wait":
            # Some bridges advance only through the display acknowledgement POST.
            # On timeout, retrieve state next time before acknowledging again.
            session = self.api("POST", self.network_path() + "/steps/" + segment(step["stepID"]), {"type": "display_and_wait"}, timeout=35)
        return self.network_view(session)

    def clear_qr(self):
        (self.root / "network-qr.png").unlink(missing_ok=True)

    def render_qr(self, data):
        sys.path.insert(0, str(self.root / "lib"))
        try:
            import qrcode
        except ImportError:
            raise Failure("QR renderer missing. Run bootstrap --cli-only to restore tools.")
        qr = qrcode.QRCode(border=4)
        qr.add_data(data)
        qr.make(fit=True)
        matrix = qr.get_matrix()
        scale = 6
        rows = b"".join((b"\0" + bytes(0 if cell else 255 for cell in row for _ in range(scale))) * scale for row in matrix)
        size = len(matrix) * scale
        def chunk(kind, content):
            return struct.pack(">I", len(content)) + kind + content + struct.pack(">I", zlib.crc32(kind + content) & 0xffffffff)
        png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 0, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")
        path = self.root / "network-qr.png"
        path.write_bytes(png)
        path.chmod(0o600)
        return path

    def input_fields(self, kind):
        state = self.state()
        if kind == "email" and state.get("email"):
            return [{"id": "code", "label": "Beeper email verification code"}], state["email"]["setupRequestID"]
        if kind == "register" and state.get("registration"):
            return [{"id": "username", "label": "Choose a Beeper username", "type": "text"}, {"id": "acceptTerms", "label": "I agree to Beeper's Terms of Use and acknowledge its Privacy Policy", "type": "checkbox"}], state["registration"]["setupRequestID"]
        if kind == "recovery":
            return [{"id": "recoveryKey", "label": "Existing Beeper recovery key"}], None
        if kind == "network":
            session = self.network_session()
            step = session.get("currentStep") or {}
            if step.get("type") in ("user_input", "cookies"):
                return step["fields"], (session["loginSessionID"], step["stepID"])
        raise Failure("There is no matching input step pending. Check status.", "no_pending_input")

    def submit_input(self, kind, fields, snapshot):
        self.writable()
        expected, current = self.input_fields(kind)
        if snapshot != current:
            raise Failure("This form is stale. Open a new form for the current step.", "stale_input")
        allowed = {field["id"] for field in expected}
        fields = {k: v for k, v in fields.items() if k in allowed}
        if any(not f.get("optional") and not fields.get(f["id"]) for f in expected):
            raise Failure("Complete all required fields.", "missing_fields")
        if kind == "email":
            return self.finish_login(self.api("POST", SETUP + "/response", {"setupRequestID": current, "response": fields["code"]}, public=True))
        if kind == "register":
            registration = self.state()["registration"]
            if fields.get("acceptTerms") != "on":
                raise Failure("Accept the displayed terms to create an account.")
            return self.finish_login(self.api("POST", SETUP + "/register", {"setupRequestID": current, "leadToken": registration["leadToken"], "username": fields["username"], "acceptTerms": True}, public=True))
        if kind == "recovery":
            self.api("POST", SETUP + "/verification/recovery-key", {"recoveryKey": fields["recoveryKey"]})
            return {"submitted": True}
        session = self.network_session()
        step = session["currentStep"]
        if (session["loginSessionID"], step["stepID"]) != current:
            raise Failure("The network advanced to another step. Open a new form.", "stale_input")
        result = self.api("POST", self.network_path() + "/steps/" + segment(step["stepID"]), {"type": step["type"], "fields": fields, "source": "api"})
        if result["status"] in TERMINAL:
            self.update(network=None)
            self.clear_qr()
        return {"submitted": True, "networkStatus": result["status"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("bootstrap", help="Install CLI, QR renderer, and managed Server")
    p.add_argument("--cli-only", action="store_true")
    for name in ("status", "start", "stop", "accounts", "networks", "login-cancel", "verify-start", "verify-show", "verify-accept", "verify-sas", "verify-cancel", "network-show", "network-poll", "network-cancel"):
        commands.add_parser(name)
    p = commands.add_parser("login")
    p.add_argument("--email", required=True)
    p = commands.add_parser("verify-confirm")
    p.add_argument("--matches", action="store_true", required=True, help="Use only after the user confirms the displayed SAS matches")
    p = commands.add_parser("flows")
    p.add_argument("bridge")
    p = commands.add_parser("connect")
    p.add_argument("bridge")
    p.add_argument("--flow")
    p.add_argument("--login-id")
    p = commands.add_parser("webview-connect", help="Use the official CLI's Chrome webview for a browser login flow")
    p.add_argument("bridge")
    p.add_argument("--flow", required=True)
    p = commands.add_parser("input", help="Run a temporary private browser form; leave the process running")
    p.add_argument("kind", choices=("email", "register", "recovery", "network"))
    p = commands.add_parser("cli", help="Messaging commands on the plugin's Server target")
    p.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    runtime = Runtime()
    try:
        if args.command == "input":
            from private_input import serve
            serve(runtime, args.kind)
            return
        with runtime.lock():
            c = args.command
            if c == "bootstrap":
                result = runtime.bootstrap(args.cli_only)
            elif c == "status":
                result = runtime.status()
            elif c == "start":
                result = runtime.start()
            elif c == "stop":
                runtime.writable()
                runtime.cli(["targets", "stop", TARGET])
                result = {"stopped": True}
            elif c == "login":
                result = runtime.login(args.email)
            elif c == "login-cancel":
                runtime.writable()
                runtime.update(email=None, registration=None)
                result = {"localLoginStateCleared": True}
            elif c.startswith("verify-"):
                result = runtime.verification(c.removeprefix("verify-"), getattr(args, "matches", False))
            elif c in ("accounts", "networks"):
                result = runtime.api("GET", "/v1/accounts" if c == "accounts" else "/v1/bridges")
            elif c == "flows":
                result = runtime.api("GET", f"/v1/bridges/{segment(args.bridge)}/login-flows")
            elif c == "connect":
                result = runtime.connect(args.bridge, args.flow, args.login_id)
            elif c == "webview-connect":
                result = runtime.webview_connect(args.bridge, args.flow)
            elif c == "network-show":
                result = runtime.network_view(runtime.network_session())
            elif c == "network-poll":
                result = runtime.network_poll()
            elif c == "network-cancel":
                runtime.api("DELETE", runtime.network_path())
                runtime.update(network=None)
                runtime.clear_qr()
                result = {"cancelled": True}
            else:
                arguments = args.arguments
                if arguments[:1] == ["--"]:
                    arguments = arguments[1:]
                if not arguments or arguments[0] not in ("chats", "messages", "contacts", "send", "media", "status", "doctor", "man", "version"):
                    raise Failure("Use cli for messaging or diagnostics; use the onboarding commands for setup.", "usage")
                if any(a.startswith(("--target", "--base-url", "--debug", "--log-level")) or a == "-t" or (a.startswith("-t") and not a.startswith("--")) for a in arguments):
                    raise Failure("Target and debug overrides are not supported.", "usage")
                result = runtime.cli([*arguments, "--target", TARGET])
        emit({"success": True, "data": redact(result)})
    except Failure as exc:
        emit({"success": False, "error": {"code": exc.code, "message": str(exc)}})
        sys.exit(1)
    except Exception as exc:
        # Avoid exposing server responses, URLs carrying secrets, or credential files.
        emit({"success": False, "error": {"code": "unexpected_error", "message": f"Operation failed ({type(exc).__name__}). Check installed versions and the documented prerequisites."}})
        sys.exit(1)


if __name__ == "__main__":
    main()
