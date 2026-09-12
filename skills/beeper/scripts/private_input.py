"""Short-lived loopback form for user takeover; never prints submitted values."""
import html
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import secrets
import time
from urllib.parse import parse_qs


def make_server(runtime, kind):
    with runtime.lock():
        runtime.writable()
        fields, snapshot = runtime.input_fields(kind)
        for field in fields:
            runtime.input_field_required(field)
    nonce = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32)
    path = "/" + nonce

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def log_message(self, *_):
            pass

        def reply(self, status, body):
            encoded = body.encode()
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            # no-referrer makes native form POSTs send Origin: null, which our
            # origin check must reject. Keep same-origin POSTs identifiable
            # while withholding the private URL from other origins.
            self.send_header("Referrer-Policy", "same-origin")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(encoded)

        def valid_location(self):
            return self.path == path and self.headers.get("Host") == self.server.address

        def do_GET(self):
            if not self.valid_location():
                self.reply(404, "Not found")
                return
            controls = []
            for field in fields:
                ident = html.escape(field["id"], quote=True)
                is_required = runtime.input_field_required(field)
                label = html.escape(field.get("label") or field["id"]) + ("" if is_required else " (optional)")
                field_type = "checkbox" if field.get("type") == "checkbox" else ("text" if kind == "register" else "password")
                required = "required" if is_required else ""
                controls.append(f'<label>{label}<input name="{ident}" type="{field_type}" {required} autocomplete="off"></label>')
            terms = '<p><a href="https://www.beeper.com/terms" target="_blank" rel="noreferrer">Beeper Terms of Use</a> · <a href="https://www.beeper.com/privacy" target="_blank" rel="noreferrer">Privacy Policy</a></p>' if kind == "register" else ""
            self.reply(200, '<!doctype html><html lang="en"><meta charset="utf-8"><title>Beeper sign-in</title>'
                       '<meta name="viewport" content="width=device-width, initial-scale=1">'
                       '<style>body{font:18px system-ui;max-width:520px;margin:60px auto;padding:24px;background:#f7f8fa;color:#15202b}'
                       'label{display:block;margin:24px 0}input{display:block;margin-top:8px;padding:12px;width:90%;font:inherit}'
                       'input[type=checkbox]{width:auto}button{padding:12px 24px;font:inherit}</style>'
                       '<h1>Beeper sign-in</h1><p>Enter the requested values here. They are sent to Beeper Server on this computer and are not printed in the chat.</p>'
                       f'{terms}<form method="post" action="{path}"><input type="hidden" name="_csrf" value="{csrf}">'
                       + ''.join(controls) + '<button type="submit">Continue</button></form></html>')

        def do_POST(self):
            if not self.valid_location() or self.headers.get("Origin") != "http://" + self.server.address:
                self.reply(403, "This request did not come from the sign-in page.")
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0
            if not 0 < length <= 65536 or self.headers.get("Content-Type", "").split(";")[0] != "application/x-www-form-urlencoded":
                self.reply(400, "Invalid form.")
                return
            try:
                values = parse_qs(self.rfile.read(length).decode(), keep_blank_values=True)
            except (UnicodeDecodeError, TimeoutError):
                self.reply(400, "Invalid form encoding or incomplete request.")
                return
            if not secrets.compare_digest(values.get("_csrf", [""])[0], csrf):
                self.reply(403, "This sign-in page has expired.")
                return
            submitted = {k: v[0] for k, v in values.items() if k != "_csrf"}
            try:
                with runtime.lock():
                    result = runtime.submit_input(kind, submitted, snapshot)
            except Exception as exc:
                # Even an upstream error can echo the user's submitted secret.
                code = getattr(exc, "code", "operation_failed")
                self.reply(400, f'<p>Beeper could not complete this step ({html.escape(code)}). Check the value or return to Grok to refresh the step.</p><p><a href="{path}">Try again</a></p>')
                return
            self.server.result = result
            self.reply(200, "<h1>Submitted</h1><p>Return to Grok to continue setup. You can close this page.</p>")
            self.server.done = True

    server = HTTPServer(("127.0.0.1", 0), Handler)
    server.address = f"127.0.0.1:{server.server_port}"
    server.url = "http://" + server.address + path
    server.done = False
    server.result = None
    server.timeout = 1
    return server


def serve(runtime, kind, lifetime=600):
    with make_server(runtime, kind) as server:
        print(json.dumps({"success": True, "data": {"privateInputURL": server.url, "expiresInSeconds": lifetime,
              "instruction": "Open this URL in Grok Bot's computer browser and let the user take over. Do not ask them to paste the secret into chat."}}), flush=True)
        deadline = time.monotonic() + lifetime
        while not server.done and time.monotonic() < deadline:
            server.handle_request()
        print(json.dumps({"success": server.done, "data": server.result or {"expired": True}}), flush=True)
