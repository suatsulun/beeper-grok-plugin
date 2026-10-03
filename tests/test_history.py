"""History contract regressions: opaque tokens, chronology and real HTTP routing."""
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
import threading
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from test_beeper import RuntimeFixture
from beeper import Failure, write_json

CHAT = "!history:synthetic"


def message(ident, minute, own=False):
    return {"id": ident, "chatID": CHAT, "accountID": "test-network", "isSender": own,
            "senderID": "self" if own else "other", "sortKey": "not-a-cursor-" + ident,
            "timestamp": f"2026-10-03T12:{minute:02d}:00Z", "text": "synthetic"}


def page(items, cursor=None):
    return {"items": items, "hasMore": cursor is not None,
            "oldestCursor": cursor, "newestCursor": "unused-newer-token"}


class HistoryTests(RuntimeFixture):
    def setUp(self):
        super().setUp()
        # Intentionally non-monotonic message IDs and tied timestamps. Server
        # cursor values also differ from both IDs and sort keys.
        self.messages = [message("99", 9), message("3", 8, True), message("400", 8),
                         message("2", 7), message("900", 6), message("1", 5, True)]
        self.pages = [page(self.messages[:3], "opaque+/token=one"),
                      page([self.messages[2], *self.messages[3:5]], "opaque-two"),
                      page(self.messages[5:])]

    def run_history(self, args, pages=None):
        with patch.object(self.runtime, "api", side_effect=deepcopy(pages or self.pages)) as api:
            result = self.runtime.command(["messages", *args, "--chat", CHAT])
        return result, api.call_args_list

    def test_newest_known_chat_uses_one_get_and_no_cli(self):
        with patch.object(self.runtime, "cli", side_effect=AssertionError("CLI started")):
            result, calls = self.run_history(["list", "--limit", "2"])
        self.assertEqual([r["id"] for r in result], ["99", "3"])
        self.assertEqual(len(calls), 1)

    def test_before_id_uses_opaque_tokens_and_preserves_ties(self):
        result, calls = self.run_history(["list", "--before-cursor", "3", "--limit", "4"])
        self.assertEqual([r["id"] for r in result], ["400", "2", "900", "1"])
        queries = [parse_qs(urlsplit(c.args[1]).query) for c in calls]
        self.assertEqual(queries, [{}, {"cursor": ["opaque+/token=one"], "direction": ["before"]},
                                  {"cursor": ["opaque-two"], "direction": ["before"]}])

    def test_after_returns_nearest_newer_rows_not_newest_chat_rows(self):
        result, _ = self.run_history(["list", "--after-cursor", "900", "--limit", "2"])
        self.assertEqual([r["id"] for r in result], ["400", "2"])

    def test_context_spans_page_boundary_with_center_and_nearest_sides(self):
        result, _ = self.run_history(["context", "--id", "2", "--before", "2", "--after", "2"])
        self.assertEqual(result["message"]["id"], "2")
        self.assertEqual([r["id"] for r in result["before"]], ["900", "1"])
        self.assertEqual([r["id"] for r in result["after"]], ["400", "3"])

    def test_sender_filter_scans_more_pages_and_asc_reverses_selected_rows(self):
        result, _ = self.run_history(["list", "--sender", "me", "--limit", "2", "--asc"])
        self.assertEqual([r["id"] for r in result], ["1", "3"])
        result, _ = self.run_history(["list", "--after-cursor", "1", "--sender", "me", "--limit", "1"])
        self.assertEqual([r["id"] for r in result], ["3"])

    def test_missing_anchor_and_page_budget_are_failures_not_empty_success(self):
        for args, code in [(["list", "--before-cursor", "absent"], "message_not_found"),
                           (["context", "--id", "absent"], "message_not_found"),
                           (["list", "--before-cursor", "1", "--max-pages", "1"], "history_budget")]:
            with self.subTest(args=args), self.assertRaises(Failure) as error:
                self.run_history(args)
            self.assertEqual(error.exception.code, code)

    def test_cursor_cycles_and_duplicate_only_pages_stop(self):
        pages = [page(self.messages[:2], "loop"), page(self.messages[2:4], "loop")]
        with self.assertRaises(Failure) as error:
            self.run_history(["list", "--limit", "20"], pages)
        self.assertEqual(error.exception.code, "pagination_stalled")
        pages = [self.pages[0], page(self.messages[:3], "different-but-no-progress")]
        with self.assertRaises(Failure):
            self.run_history(["list", "--limit", "20"], pages)

    def test_missing_cursor_bad_order_wrong_chat_and_bad_timestamp_fail(self):
        variants = [page([self.messages[1], self.messages[0]]),
                    page([{**self.messages[0], "chatID": "!wrong:test"}]),
                    page([{**self.messages[0], "timestamp": "2026-10-03T12:00:00"}]),
                    {**page(self.messages[:1]), "hasMore": True},
                    page([self.messages[0], {**self.messages[1], "accountID": "wrong-account"}])]
        for variant in variants:
            with self.subTest(page=variant), self.assertRaises(Failure):
                self.run_history(["list", "--limit", "20"], [variant])

    def test_limit_zero_and_invalid_arguments_never_fetch(self):
        with patch.object(self.runtime, "api", side_effect=AssertionError("unexpected GET")):
            self.assertEqual(self.runtime.command(["messages", "list", "--chat", CHAT, "--limit", "0"]), [])
            for args in (["--limit", "-1"], ["--limit", "private-invalid-value"],
                         ["--before-cursor", "1", "--after-cursor", "2"], ["--max-pages", "0"],
                         ["--base", "https://evil.test"]):
                with self.assertRaises(Failure) as error:
                    self.runtime.command(["messages", "list", "--chat", CHAT, *args])
                self.assertNotIn("private-invalid-value", str(error.exception))

    def test_deadline_stops_before_next_request(self):
        with patch("history.time.monotonic", side_effect=[0, 0, 31]), self.assertRaises(Failure) as error:
            self.run_history(["list", "--limit", "50"])
        self.assertEqual(error.exception.code, "history_budget")

    def test_alias_resolution_preserves_pick_without_changing_target(self):
        with patch.object(self.runtime, "cli", return_value={"id": CHAT}) as cli, \
                patch.object(self.runtime, "api", return_value=self.pages[0]):
            result = self.runtime.command(["messages", "list", "--chat", "Example", "--pick", "2", "--limit", "1"])
        self.assertEqual(result[0]["id"], "99")
        cli.assert_called_once_with(["chats", "show", "--chat", "Example", "--read-only", "--pick", "2"])

    def test_actual_loopback_http_uses_server_cursors_and_auth(self):
        self.existing()
        requests = []
        pages = self.pages

        class Receiver(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                query = parse_qs(urlsplit(self.path).query)
                token = query.get("cursor", [None])[0]
                index = {None: 0, "opaque+/token=one": 1, "opaque-two": 2}.get(token)
                requests.append((self.path, self.headers.get("Authorization")))
                self.send_response(200 if index is not None else 400)
                self.end_headers()
                self.wfile.write(json.dumps(pages[index] if index is not None else {}).encode())

        server = HTTPServer(("127.0.0.1", 0), Receiver)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        target = self.runtime.target()
        target.update(port=server.server_port, baseURL=f"http://127.0.0.1:{server.server_port}")
        write_json(self.runtime.target_file, target)
        try:
            result = self.helper("cli", "messages", "context", "--chat", CHAT, "--id", "2", "--before", "2", "--after", "2")
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertEqual(json.loads(result.stdout)["data"]["message"]["id"], "2")
            self.assertEqual(len(requests), 3)
            self.assertTrue(all(auth == "Bearer SYNTHETIC_SECRET" for _, auth in requests))
            self.assertTrue(all(path.startswith("/v1/chats/%21history%3Asynthetic/messages") for path, _ in requests))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_export_uses_inclusive_dates_and_atomic_private_output(self):
        output = self.root / "exports/result.json"
        with patch.object(self.runtime, "api", side_effect=deepcopy(self.pages)):
            result = self.runtime.command(["messages", "export", "--chat", CHAT,
                "--after", "2026-10-03T15:06:00+03:00", "--before", "2026-10-03T12:08:00Z", "--output", str(output)])
        data = json.loads(output.read_text())
        self.assertTrue(result["completed"])
        self.assertFalse(result["limitReached"])
        self.assertEqual([m["id"] for m in data["messages"]], ["3", "400", "2", "900"])
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)

    def test_failed_export_preserves_prior_output_and_reports_partial_limit(self):
        output = self.root / "result.json"
        output.write_text("previous export")
        with patch.object(self.runtime, "api", return_value=self.pages[0]), self.assertRaises(Failure):
            self.runtime.command(["messages", "export", "--chat", CHAT, "--max-pages", "1", "--output", str(output)])
        self.assertEqual(output.read_text(), "previous export")
        result, _ = self.run_history(["export", "--limit", "2", "--before-cursor", "3", "--asc"])
        self.assertEqual([m["id"] for m in result["messages"]], ["2", "400"])
        self.assertTrue(result["limitReached"])

    def test_export_read_only_and_profile_destination_blocked(self):
        profile = self.existing()
        for output, extra in [(profile / "keys.fixture", []), (self.root / "result.json", ["--read-only"])]:
            with patch.object(self.runtime, "api") as api, self.assertRaises(Failure):
                self.runtime.command(["messages", "export", "--chat", CHAT, "--output", str(output), *extra])
            api.assert_not_called()
        with patch.dict(os.environ, {"BEEPER_READONLY": "1"}), self.assertRaises(Failure):
            self.runtime.command(["messages", "export", "--chat", CHAT, "--output", str(self.root / "result.json")])
