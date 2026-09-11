"""Scoped browser-session handoff. Secrets stay in memory and private child pipes."""
import base64
import fcntl
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import hmac
import json
import re
import secrets
import shutil
import subprocess
import threading
import time
from pathlib import Path
from beeper import Failure, TERMINAL, emit, segment

SCRIPTS = Path(__file__).resolve().parent


def node_call(data):
    node = shutil.which("node")
    if not node:
        raise Failure("Browser sign-in requires Node.js 22 or newer on the Server computer.", "browser_unavailable")
    try:
        result = subprocess.run([node, str(SCRIPTS / "browser_crypto.mjs")], input=json.dumps(data),
                                capture_output=True, text=True, timeout=15)
    except subprocess.TimeoutExpired:
        raise Failure("Browser helper timed out.", "browser_timeout") from None
    if result.returncode:
        raise Failure("This login requires unsupported browser extraction, has invalid session data, or needs Node.js 22+. Use a supported website/QR flow; no password form will be substituted.", "browser_unsupported")
    return json.loads(result.stdout)


def fingerprint(session):
    return hashlib.sha256(json.dumps(session.get("currentStep"), sort_keys=True).encode()).hexdigest()


def prepare(runtime):
    runtime.writable()
    session = runtime.network_session()
    if session.get("status") in TERMINAL:
        raise Failure("This network login has ended. Inspect accounts before starting another.", "stale_input")
    plan = node_call({"action": "plan", "step": session.get("currentStep")})
    snapshot = (runtime.network_path(), fingerprint(session))
    return plan, snapshot


def submit(runtime, snapshot, payload, source):
    with runtime.lock():
        session = runtime.network_session()
        if snapshot != (runtime.network_path(), fingerprint(session)) or session.get("status") in TERMINAL:
            raise Failure("The network login changed. This browser handoff cannot be reused.", "stale_input")
        result = runtime.api("POST", snapshot[0] + "/steps/" + segment(session["currentStep"]["stepID"]),
                             {"type": "cookies", "fields": payload["fields"], "lastURL": payload["lastURL"], "source": source})
        return runtime.network_view(result)


class Handoff(HTTPServer):
    allow_reuse_address = False

    def __init__(self, runtime, plan, snapshot, ttl=600):
        self.runtime, self.snapshot = runtime, snapshot
        pair = node_call({"action": "keypair"})
        self.private_key = pair["privateKey"]
        self.done = threading.Event()
        self.result = None
        self.used = False
        self.started = time.monotonic()
        self.ttl = ttl
        super().__init__(("127.0.0.1", 0), Handler)
        self.timeout = 1
        self.descriptor = {"version": 1, "id": secrets.token_urlsafe(24), "capability": secrets.token_urlsafe(32),
                           "origin": f"http://127.0.0.1:{self.server_port}", "expires": int((time.time() + ttl) * 1000),
                           "publicKey": pair["publicKey"], "plan": plan}

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(5)
        return connection, address

    def handle_error(self, *_):
        pass  # Never log request bodies or exception values.

    def link(self):
        encoded = base64.urlsafe_b64encode(json.dumps(self.descriptor, separators=(",", ":"), ensure_ascii=False).encode()).decode().rstrip("=")
        return self.descriptor["origin"] + "/connect#" + encoded


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def respond(self, status, body, html=False):
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8" if html else "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        origin = self.headers.get("Origin", "")
        if re.fullmatch(r"chrome-extension://[a-p]{32}", origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Beeper-Pairing")
        self.end_headers()
        self.wfile.write(body.encode() if html else json.dumps(body).encode())

    def do_GET(self):
        if self.path != "/connect":
            return self.respond(404, {"error": "not_found"})
        self.respond(200, "<!doctype html><meta charset=utf-8><title>Connect to Beeper</title><h1>Connect your browser to Beeper</h1><p>Open the Beeper Browser Connect extension using the Extensions button in this browser.</p><p>It will show the selected network and open that network's website. Use the account you want to connect.</p><p>This page never asks for a password. The pairing link expires after ten minutes.</p>", html=True)

    def do_OPTIONS(self):
        self.respond(204, {})

    def do_POST(self):
        server = self.server
        descriptor = server.descriptor
        if self.path != "/handoff/" + descriptor["id"] or not hmac.compare_digest(self.headers.get("X-Beeper-Pairing", ""), descriptor["capability"]):
            return self.respond(403, {"error": "invalid_pairing"})
        if server.used or time.monotonic() - server.started >= server.ttl:
            return self.respond(410, {"error": "expired_or_used"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if self.headers.get_content_type() != "application/json" or not 0 < length <= 131072 or self.headers.get("Transfer-Encoding"):
                return self.respond(400, {"error": "invalid_request"})
            envelope = json.loads(self.rfile.read(length))
            payload = node_call({"action": "decrypt", "descriptor": descriptor, "privateKey": server.private_key, "envelope": envelope})
        except (Failure, ValueError, TimeoutError):
            return self.respond(400, {"error": "invalid_session"})
        # Consume before Beeper submission: an ambiguous API timeout must never
        # trigger an automatic repeat. Ask the agent to inspect the login state.
        server.used = True
        try:
            server.result = {"success": True, "data": submit(server.runtime, server.snapshot, payload, "browser_extension")}
            self.respond(200, {"submitted": True})
        except Failure as exc:
            server.result = {"success": False, "error": {"code": exc.code, "message": str(exc)}}
            self.respond(409, {"error": "check_network_status"})
        except Exception:
            server.result = {"success": False, "error": {"code": "handoff_failed", "message": "Inspect network-show and accounts before retrying."}}
            self.respond(409, {"error": "check_network_status"})
        finally:
            payload.clear()
            server.private_key = None
            server.done.set()


def start_tunnel(runtime, port):
    from install import install_tunnel
    binary = install_tunnel(runtime.root)
    # An explicit private config prevents adopting another installation's tunnel.
    config = runtime.root / "tunnel-config.yml"
    config.write_text("{}\n")
    config.chmod(0o600)
    process = subprocess.Popen([str(binary), "tunnel", "--config", str(config), "--no-autoupdate", "--protocol", "http2", "--url", f"http://127.0.0.1:{port}"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    ready = threading.Event()
    result = []
    connected = threading.Event()

    def read():
        for line in process.stderr:
            match = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com\b", line)
            if match and not result:
                result.append(match.group(0))
            if "Registered tunnel connection" in line:
                connected.set()
            if result and connected.is_set():
                ready.set()
        ready.set()

    threading.Thread(target=read, daemon=True).start()
    try:
        if not ready.wait(45) or not result or not connected.is_set():
            raise Failure("The temporary browser relay could not connect. Check outbound TCP 7844 to Cloudflare or use browser-start --browser cloud.", "relay_unavailable")
    except BaseException:
        stop_process(process)
        raise
    return process, result[0]


def stop_process(process):
    if process and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def serve(runtime, browser=None, loopback=False):
    runtime.root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (runtime.root / "browser.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Failure("A browser handoff is already running. Use its link or cancel it first.", "busy")
        with runtime.lock():
            plan, snapshot = prepare(runtime)
            pending = runtime.state()["network"]
            browser = browser or pending.get("browser", "local")
            runtime.update(network={**pending, "browser": browser})
        if browser == "cloud":
            return cloud(runtime, plan, snapshot)
        tunnel = None
        with Handoff(runtime, plan, snapshot) as server:
            try:
                if not loopback:
                    emit({"success": True, "data": {"state": "starting-browser-relay", "provider": plan["provider"]}})
                    tunnel, origin = start_tunnel(runtime, server.server_port)
                    server.descriptor["origin"] = origin
                emit({"success": True, "data": {"state": "waiting-for-local-browser", "pairingURL": server.link(), "expiresInSeconds": max(0, int(server.ttl - (time.monotonic() - server.started))),
                                                 "instruction": "Open this link on your own PC, then open Beeper Browser Connect. Approve the selected network and sign in on its website. Keep this process running."}})
                while not server.done.is_set() and time.monotonic() - server.started < server.ttl:
                    if runtime.state().get("network") != {**pending, "browser": browser}:
                        raise Failure("Network login was cancelled or changed.", "stale_input")
                    if tunnel and tunnel.poll() is not None:
                        raise Failure("Browser relay stopped. Check network-show before retrying.", "relay_unavailable")
                    server.handle_request()
                if not server.result:
                    raise Failure("Browser handoff expired. Start a new browser handoff for the pending login.", "browser_timeout")
                emit(server.result)
                return 0 if server.result["success"] else 1
            finally:
                server.private_key = None
                stop_process(tunnel)


def cloud(runtime, plan, snapshot):
    node = shutil.which("node")
    if not node:
        raise Failure("Browser sign-in requires Node.js 22 or newer.", "browser_unavailable")
    emit({"success": True, "data": {"state": "opening-provider-website", "provider": plan["provider"], "instruction": "Use takeover to sign in on the provider website in the new Chrome window. Session fields go directly to Beeper Server."}})
    process = subprocess.Popen([node, str(SCRIPTS / "cloud_browser.mjs")], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    data = json.dumps({"plan": plan, "root": str(runtime.root), "timeout": 600})
    deadline = time.monotonic() + 630
    try:
        while True:
            try:
                output, _ = process.communicate(input=data, timeout=1)
                break
            except subprocess.TimeoutExpired:
                data = None
                if not runtime.state().get("network") or runtime.network_path() != snapshot[0]:
                    raise Failure("Network login was cancelled or changed.", "stale_input")
                if time.monotonic() >= deadline:
                    raise Failure("Provider browser timed out. Inspect network-show before retrying.", "browser_timeout")
    finally:
        stop_process(process)
    if process.returncode:
        raise Failure("Provider browser could not complete sign-in. It requires Node.js 22+, Chrome/Chromium and a graphical desktop. Inspect network-show before retrying; no password form was substituted.", "browser_unavailable")
    payload = json.loads(output)
    emit({"success": True, "data": submit(runtime, snapshot, payload, "webview")})
    return 0
