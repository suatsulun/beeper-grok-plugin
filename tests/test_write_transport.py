"""Count real HTTP requests under faults; no live account or external network."""
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import socket
import threading
from urllib.parse import urlsplit
from unittest.mock import patch

from test_beeper import RuntimeFixture, write_json
from beeper import Failure

CHAT = "!self:synthetic"


class WriteTransportTests(RuntimeFixture):
    def setUp(self):
        super().setUp()
        self.existing()
        self.requests = []
        self.row = {"id": "final", "chatID": CHAT, "accountID": "network", "isSender": True, "text": "hello"}
        self.respond = lambda method, path, body: (200, {"chatID": CHAT, "pendingMessageID": "pending"} if method == "POST" else self.row)
        owner = self

        class Receiver(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                body = raw
                if raw and self.headers.get("Content-Type") == "application/json":
                    body = json.loads(raw)
                owner.requests.append((self.command, self.path, body, dict(self.headers)))
                status, result = owner.respond(self.command, self.path, body)
                if status is None:
                    self.connection.shutdown(socket.SHUT_RDWR)
                    self.connection.close()
                    return
                payload = json.dumps(result).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("retry-after-ms", "1")
                self.end_headers()
                self.wfile.write(payload)

            do_POST = do_GET
            do_PUT = do_GET
            do_DELETE = do_GET

        server = HTTPServer(("127.0.0.1", 0), Receiver)
        worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
        worker.start()
        self.addCleanup(server.server_close)
        self.addCleanup(lambda: worker.join(timeout=2))
        self.addCleanup(server.shutdown)
        target = self.runtime.target()
        target.update(port=server.server_port, baseURL=f"http://127.0.0.1:{server.server_port}")
        write_json(self.runtime.target_file, target)
        delays = patch("outcomes.OBSERVATION_DELAYS", (0, 0, 0, 0))
        delays.start()
        self.addCleanup(delays.stop)

    def test_every_mutation_has_one_http_attempt_on_retryable_failure_or_disconnect(self):
        commands = [
            ["send", "text", "--to", CHAT, "--message", "hello"],
            ["messages", "edit", "--chat", CHAT, "--id", "final", "--message", "edited"],
            ["messages", "delete", "--chat", CHAT, "--id", "final", "--for-everyone"],
            ["send", "react", "--to", CHAT, "--id", "final", "--reaction", "👍"],
            ["send", "unreact", "--to", CHAT, "--id", "final", "--reaction", "👍"],
        ]
        for status in (500, 503, 429, 408, None):
            for args in commands:
                with self.subTest(status=status, operation=args[:2]):
                    self.requests.clear()
                    self.respond = lambda *_: (status, {"error": "SYNTHETIC_PRIVATE_BODY"})
                    with self.assertRaises(Failure) as error, patch.object(self.runtime, "cli") as cli:
                        self.runtime.command(args)
                    cli.assert_not_called()
                    self.assertEqual(len(self.requests), 1)
                    self.assertEqual(error.exception.write_outcome["state"], "unknown")
                    self.assertFalse(error.exception.write_outcome["retrySafe"])
                    self.assertNotIn("SYNTHETIC_PRIVATE_BODY", str(error.exception))
                    self.assertEqual(self.requests[0][3]["Authorization"], "Bearer SYNTHETIC_SECRET")

    def test_acknowledged_send_keeps_pending_id_when_wait_expires(self):
        self.respond = lambda method, *_: ((200, {"chatID": CHAT, "pendingMessageID": "pending-accepted"})
                                          if method == "POST" else (404, {"error": "not visible yet"}))
        result = self.runtime.command(["send", "text", "--to", CHAT, "--message", "hello", "--wait", "--wait-timeout", "30"])
        self.assertTrue(result["accepted"])
        self.assertEqual(result["pendingMessageID"], "pending-accepted")
        outcome = result["writeOutcome"]
        self.assertEqual(outcome["messageID"], "pending-accepted")
        self.assertEqual(outcome["state"], "unknown")
        self.assertTrue(outcome["observationExhausted"])
        self.assertGreater(outcome["readAttempts"], 0)
        self.assertEqual(sum(r[0] == "POST" for r in self.requests), 1)

    def test_delayed_read_keeps_ack_and_resolves_final_id_without_resending(self):
        reads = []
        def respond(method, path, body):
            if method == "POST":
                return 200, {"chatID": CHAT, "pendingMessageID": "pending", "transactionID": "synthetic-tx"}
            reads.append(path)
            return (404, {}) if len(reads) == 1 else (200, self.row)
        self.respond = respond
        result = self.runtime.command(["send", "text", "--to", CHAT, "--message", "hello", "--wait"])
        self.assertEqual(result["pendingMessageID"], "pending")
        self.assertEqual(result["transactionID"], "synthetic-tx")
        self.assertEqual(result["writeOutcome"]["messageID"], "final")
        self.assertEqual(result["writeOutcome"]["state"], "confirmed")
        self.assertEqual(len(reads), 2)
        self.assertEqual(sum(r[0] == "POST" for r in self.requests), 1)

    def test_message_reaction_and_delete_parameters_reach_correct_endpoints(self):
        self.runtime.command(["send", "text", "--to", CHAT, "--message", "--help\n$HOME", "--reply-to", "parent",
                              "--mention", "one", "--mention", "two", "--no-preview"])
        self.assertEqual(self.requests[0][2], {"text": "--help\n$HOME", "replyToMessageID": "parent",
                                             "mentions": ["one", "two"], "disableLinkPreview": True})
        self.requests.clear()
        self.runtime.command(["send", "react", "--to", CHAT, "--id", "id/1", "--reaction", "👍", "--transaction", "tx"])
        self.assertTrue(self.requests[0][1].endswith("/id%2F1/reactions"))
        self.assertEqual(self.requests[0][2], {"reactionKey": "👍", "transactionID": "tx"})
        self.requests.clear()
        self.runtime.command(["send", "unreact", "--to", CHAT, "--id", "final", "--reaction", "x/y"])
        self.assertTrue(self.requests[0][1].endswith("/reactions/x%2Fy"))
        self.requests.clear()
        self.runtime.command(["messages", "delete", "--chat", CHAT, "--id", "final", "--for-everyone"])
        self.assertTrue(self.requests[0][1].endswith("/messages/final?forEveryone=true"))

    def test_upload_bytes_metadata_and_subtypes_survive_direct_send(self):
        path = self.root / "attachment.dat"
        content = b"\x00\xffsynthetic attachment\r\n" * 50000
        path.write_bytes(content)
        def respond(method, url, body):
            if url.endswith("/upload"):
                return 200, {"uploadID": "uploaded", "fileName": 'şüphe".dat', "mimeType": "application/example",
                             "duration": 11, "width": 512, "height": 512}
            if method == "POST":
                return 200, {"chatID": CHAT, "pendingMessageID": "pending"}
            return 200, {**self.row, "text": "caption", "attachments": [{"isVoiceNote": True, "isSticker": True}]}
        self.respond = respond
        for operation, extras, subtype, mime in (
            ("file", ["--caption", "caption"], None, "application/example"),
            ("voice", ["--duration", "7"], "voice-note", "audio/ogg"),
            ("sticker", [], "sticker", "image/webp"),
        ):
            with self.subTest(operation=operation):
                self.requests.clear()
                self.runtime.command(["send", operation, "--to", CHAT, "--file", str(path), "--filename", 'şüphe".dat', *extras])
                writes = [r for r in self.requests if r[0] == "POST"]
                self.assertEqual(len(writes), 2)
                _, url, raw, headers = writes[0]
                self.assertEqual(url, "/v1/assets/upload")
                multipart = BytesParser(policy=policy.default).parsebytes(
                    ("Content-Type: " + headers["Content-Type"] + "\r\n\r\n").encode() + raw)
                parts = {part.get_param("name", header="content-disposition"): part.get_payload(decode=True)
                         for part in multipart.iter_parts()}
                self.assertEqual(parts["file"], content)
                self.assertEqual(parts["fileName"].decode(), 'şüphe".dat')
                attachment = writes[1][2]["attachment"]
                self.assertEqual(attachment["uploadID"], "uploaded")
                self.assertEqual(attachment.get("type"), subtype)
                self.assertEqual(attachment["mimeType"], mime)
                self.assertEqual(attachment["duration"], 7 if operation == "voice" else 11)

    def test_failed_upload_or_missing_upload_id_never_sends_message(self):
        path = self.root / "attachment.dat"
        path.write_bytes(b"synthetic")
        for response in ((500, {}), (200, {}), (None, {})):
            self.requests.clear()
            self.respond = lambda *_: response
            with self.assertRaises(Failure):
                self.runtime.command(["send", "file", "--to", CHAT, "--file", str(path)])
            self.assertEqual(len(self.requests), 1)
            self.assertEqual(self.requests[0][1], "/v1/assets/upload")

    def test_failed_media_send_never_reuploads_or_reposts(self):
        path = self.root / "attachment.dat"
        path.write_bytes(b"synthetic")
        def respond(method, url, body):
            return (200, {"uploadID": "uploaded"}) if url.endswith("/upload") else (503, {})
        self.respond = respond
        for operation in ("file", "voice", "sticker"):
            with self.subTest(operation=operation), patch.object(self.runtime, "cli") as cli:
                self.requests.clear()
                with self.assertRaises(Failure) as error:
                    self.runtime.command(["send", operation, "--to", CHAT, "--file", str(path)])
                self.assertEqual([urlsplit(r[1]).path for r in self.requests], [
                    "/v1/assets/upload", "/v1/chats/%21self%3Asynthetic/messages"])
                self.assertFalse(error.exception.write_outcome["retrySafe"])
                cli.assert_not_called()

    def test_invalid_numeric_options_fail_before_any_http(self):
        for flags in (["--wait-timeout", "wrong"], ["--wait-timeout", "0"], ["--timeout", "infinite"]):
            with self.assertRaises(Failure):
                self.runtime.command(["send", "text", "--to", CHAT, "--message", "hello", *flags])
        self.assertEqual(self.requests, [])
