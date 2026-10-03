"""Search contract tests: exact windows, account scope, and explicit coverage."""
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from test_beeper import RuntimeFixture
from beeper import Failure

CHAT = "!room:synthetic"


def message(ident, stamp, **extra):
    return {"id": ident, "chatID": CHAT, "accountID": "network", "timestamp": stamp, **extra}


def page(items, more=False, cursor=None):
    return {"items": items, "hasMore": more, "oldestCursor": cursor}


class SearchTests(RuntimeFixture):
    def search(self, args, pages):
        with patch.object(self.runtime, "api", side_effect=pages) as api, patch.object(self.runtime, "cli") as cli:
            result = self.runtime.command(["messages", "search", *args])
        cli.assert_not_called()
        return result, api.call_args_list

    def test_fractional_bounds_are_widened_then_filtered_exactly(self):
        rows = [message(str(i), f"2026-10-03T10:00:00.{i}00000Z") for i in (9, 8, 5, 2, 1)]
        result, calls = self.search(["--chat", CHAT, "--after", "2026-10-03T10:00:00.200Z",
                                    "--before", "2026-10-03T10:00:00.800Z"], [page(rows)])
        self.assertEqual([r["id"] for r in result["items"]], ["8", "5", "2"])
        query = parse_qs(urlsplit(calls[0].args[1]).query)
        self.assertEqual(query["dateAfter"], ["2026-10-03T09:59:59+00:00"])
        self.assertEqual(query["dateBefore"], ["2026-10-03T10:00:01+00:00"])
        self.assertEqual(result["coverage"]["dateBounds"], "[after, before]")
        self.assertTrue(result["coverage"]["sourceExhausted"])

    def test_zero_fraction_and_whole_seconds_produce_same_query_and_result(self):
        outputs = []
        for suffix in ("Z", ".000Z"):
            outputs.append(self.search(["--after", "2026-10-03T10:00:00" + suffix],
                                      [page([message("boundary", "2026-10-03T10:00:00Z")])]))
        self.assertEqual(outputs[0][0]["items"], outputs[1][0]["items"])
        self.assertEqual([call.args for call in outputs[0][1]], [call.args for call in outputs[1][1]])

    def test_midnight_timezone_and_exclusive_report_end(self):
        rows = [message("tomorrow", "2026-10-03T21:00:00Z"), message("today", "2026-10-03T20:59:59.999Z"),
                message("midnight", "2026-10-02T21:00:00Z"), message("yesterday", "2026-10-02T20:59:59.999Z")]
        result, _ = self.search(["--after", "2026-10-03T00:00:00+03:00", "--before", "2026-10-04T00:00:00+03:00",
                                 "--before-exclusive"], [page(rows)])
        self.assertEqual([r["id"] for r in result["items"]], ["today", "midnight"])

    def test_post_filtering_does_not_consume_result_limit(self):
        outside = message("outside", "2026-10-03T10:00:00.900Z")
        wanted = message("wanted", "2026-10-03T10:00:00.500Z")
        result, calls = self.search(["--before", "2026-10-03T10:00:00.800Z", "--limit", "1"],
                                    [page([outside], True, "opaque/+"), page([wanted])])
        self.assertEqual([r["id"] for r in result["items"]], ["wanted"])
        self.assertEqual(parse_qs(urlsplit(calls[1].args[1]).query)["cursor"], ["opaque/+"])
        self.assertTrue(result["coverage"]["limitReached"])

    def test_low_priority_and_muted_chats_are_included_unless_explicitly_excluded(self):
        candidates = [("normal", False, False), ("muted", False, True), ("low", True, False), ("both", True, True)]

        def api(_method, path, **_):
            params = parse_qs(urlsplit(path).query)
            return page([message(ident, "2026-10-03T10:00:00Z") for ident, low, muted in candidates
                         if not (low and params["excludeLowPriority"] == ["true"])
                         and not (muted and params["includeMuted"] == ["false"])])

        for flags, wanted in [([], ["normal", "muted", "low", "both"]),
                              (["--exclude-low-priority"], ["normal", "muted"]),
                              (["--no-include-muted"], ["normal", "low"]),
                              (["--exclude-low-priority", "--no-include-muted"], ["normal"])]:
            with patch.object(self.runtime, "api", side_effect=api):
                result = self.runtime.command(["messages", "search", "synthetic", *flags])
            self.assertEqual([r["id"] for r in result["items"]], wanted)

    def test_repeated_account_filters_use_sdk_query_encoding_and_enforce_scope(self):
        accounts = [{"accountID": "network", "network": "Example"}, {"accountID": "network-2", "network": "Other"}]
        result, calls = self.search(["--account", "Example", "--account", "network-2"],
                                   [accounts, page([message("ok", "2026-10-03T10:00:00Z")])])
        self.assertEqual(parse_qs(urlsplit(calls[1].args[1]).query)["accountIDs"], ["network", "network-2"])
        with self.assertRaises(Failure) as error:
            self.search(["--account", "network"], [accounts, page([message("wrong", "2026-10-03T10:00:00Z", accountID="different")])])
        self.assertEqual(error.exception.code, "search_scope_mismatch")

    def test_duplicates_and_equal_timestamps_preserve_order_without_inventing_causality(self):
        a, b, c = [message(x, "2026-10-03T10:00:00Z") for x in "abc"]
        result, _ = self.search(["synthetic"], [page([a, b], True, "next"), page([b, c])])
        self.assertEqual([r["id"] for r in result["items"]], ["a", "b", "c"])

    def test_budget_and_stalled_pages_are_errors_not_partial_success(self):
        row = message("one", "2026-10-03T10:00:00Z")
        for args, pages, code in [(["--max-pages", "1"], [page([row], True, "next")], "search_budget"),
                                  ([], [page([row], True, "next"), page([row], True, "other")], "pagination_stalled")]:
            with self.assertRaises(Failure) as error:
                self.search(["synthetic", *args], pages)
            self.assertEqual(error.exception.code, code)

    def test_invalid_dates_zero_limit_and_scope_mismatch(self):
        for args in (["--after", "2026-10-03"], ["--after", "2026-10-04T00:00:00Z", "--before", "2026-10-03T00:00:00Z"],
                     ["--before-exclusive"], ["--limit", "-1"]):
            with patch.object(self.runtime, "api") as api, self.assertRaises(Failure):
                self.runtime.command(["messages", "search", "synthetic", *args])
            api.assert_not_called()
        result, calls = self.search(["synthetic", "--limit", "0"], [])
        self.assertEqual(result["items"], [])
        self.assertEqual(calls, [])
        with self.assertRaises(Failure) as error:
            self.search(["--chat", CHAT], [page([message("one", "2026-10-03T10:00:00Z", chatID="!member:synthetic")])])
        self.assertEqual(error.exception.code, "search_scope_mismatch")

    def test_limit_truncation_is_explicit_even_without_more_server_pages(self):
        result, _ = self.search(["synthetic", "--limit", "1"], [page([
            message("one", "2026-10-03T10:00:00Z"), message("two", "2026-10-03T09:00:00Z")])])
        self.assertFalse(result["coverage"]["sourceExhausted"])
        self.assertTrue(result["coverage"]["limitReached"])
