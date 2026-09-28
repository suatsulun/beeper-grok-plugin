"""One short-lived private page for Beeper email sign-in or recovery-key unlock."""
import html
from http.server import BaseHTTPRequestHandler, HTTPServer
import secrets
import time
from urllib.parse import parse_qs

from beeper import Failure, SETUP, emit, write_json


def make_server(runtime, kind, lifetime=600):
    runtime.writable()
    signed_in = bool(runtime.target().get("auth", {}).get("accessToken"))
    if kind == "signin" and signed_in:
        raise Failure("This profile is already signed in. Check status; do not replace its account.")
    if kind == "recovery" and not signed_in:
        raise Failure("Sign in by email before unlocking encrypted messages.")
    path = "/" + secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def log_message(self, *_):
            pass

        def reply(self, status, content):
            body = ('<!doctype html><html lang="en"><meta charset="utf-8">'
                    '<meta name="viewport" content="width=device-width,initial-scale=1">'
                    '<title>Beeper sign-in</title><style>body{font:18px system-ui;max-width:480px;'
                    'margin:12vh auto;padding:24px;color:#16202b;background:#f8fafc}'
                    'input,button{font:inherit;padding:12px;margin-top:16px;box-sizing:border-box;width:100%}'
                    'button{background:#214bd6;color:white;border:0;border-radius:8px}</style>'
                    + content + '</html>').encode()
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "same-origin")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(body)

        def valid(self):
            return (self.path == path and self.headers.get("Host") == self.server.address
                    and time.monotonic() < self.server.deadline and not self.server.done)

        def page(self, error=""):
            label, input_type, autocomplete = {
                "email": ("Beeper account email", "email", "email"),
                "code": ("Code from Beeper's email", "password", "one-time-code"),
                "recovery": ("Your existing Beeper recovery key", "password", "off"),
            }[self.server.step]
            self.reply(200, '<h1>Sign in to Beeper</h1><p>Enter this privately. It goes to Beeper Server on your Grok computer.</p>'
                       + (f'<p>{html.escape(error)}</p>' if error else "")
                       + f'<form method="post" action="{path}"><input type="hidden" name="csrf" value="{csrf}">'
                       + f'<input type="hidden" name="step" value="{self.server.step}">'
                       + f'<label>{label}<input name="value" type="{input_type}" autocomplete="{autocomplete}" required autofocus maxlength="4096"></label>'
                       + '<button>Continue</button></form>')

        def do_GET(self):
            if not self.valid():
                self.reply(404, "<p>This sign-in page is unavailable or expired.</p>")
                return
            self.page()

        def do_POST(self):
            if not self.valid() or self.headers.get("Origin") != "http://" + self.server.address:
                self.reply(403, "<p>Return to the private sign-in page.</p>")
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 16384 or self.headers.get("Content-Type", "").split(";")[0] != "application/x-www-form-urlencoded":
                    raise ValueError()
                fields = parse_qs(self.rfile.read(length).decode(), strict_parsing=True)
                if any(len(values) != 1 for values in fields.values()):
                    raise ValueError()
                if not secrets.compare_digest(fields.get("csrf", [""])[0], csrf):
                    raise ValueError()
                if fields.get("step", [""])[0] != self.server.step:
                    raise ValueError()
                value = fields.get("value", [""])[0].strip()
                if not value or len(value) > 4096:
                    raise ValueError()
            except (ValueError, UnicodeDecodeError, TimeoutError):
                self.reply(400, "<p>Invalid or expired form. Reload this page.</p>")
                return
            try:
                if self.server.step == "email":
                    request = runtime.api("POST", SETUP + "/start", public=True)
                    runtime.api("POST", SETUP + "/email", {"setupRequestID": request["setupRequestID"], "email": value}, public=True)
                    self.server.request_id = request["setupRequestID"]
                    self.server.step = "code"
                    self.page()
                    return
                if self.server.step == "code":
                    data = runtime.api("POST", SETUP + "/response", {"setupRequestID": self.server.request_id, "response": value}, public=True)
                    if data.get("registrationRequired"):
                        self.server.result = {"signedIn": False, "registrationRequired": True}
                        self.server.done = True
                        self.reply(200, "<h1>No existing account found</h1><p>Use the email for your existing Beeper account. This plugin does not create accounts. You can close this window.</p>")
                        return
                    token = data.get("matrix", {}).get("accessToken")
                    if not token:
                        raise Failure("Beeper returned no account token.")
                    target = runtime.target()
                    target["auth"] = {"accessToken": token, "source": "manual", "tokenType": "Bearer"}
                    write_json(runtime.target_file, target)
                    self.server.result = {"signedIn": True, "next": "verify"}
                else:
                    runtime.api("POST", SETUP + "/verification/recovery-key", {"recoveryKey": value})
                    self.server.result = {"recoverySubmitted": True, "next": "status"}
            except Exception:
                self.page("Beeper could not complete this step. Check the value. If the code expired, close this page and ask Grok to start sign-in again.")
                return
            self.server.done = True
            self.reply(200, "<h1>You can close this window now</h1><p>Grok will check your account and finish setup. Device verification may still be needed.</p>")

    server = HTTPServer(("127.0.0.1", 0), Handler)
    server.address = f"127.0.0.1:{server.server_port}"
    server.url = "http://" + server.address + path
    server.step = "email" if kind == "signin" else "recovery"
    server.deadline = time.monotonic() + lifetime
    server.done, server.result = False, None
    server.timeout = 1
    return server


def serve(runtime, kind, lifetime=600):
    with runtime.lock(), make_server(runtime, kind, lifetime) as server:
        emit({"success": True, "data": {"privateURL": server.url, "expiresInSeconds": lifetime,
              "instruction": "Open in Grok's cloud computer browser and hand control to the user. Await this same job; never read the entered values."}})
        while not server.done and time.monotonic() < server.deadline:
            server.handle_request()
        if not server.done:
            raise Failure("The private sign-in page expired. No completed sign-in was reported.")
        return server.result
