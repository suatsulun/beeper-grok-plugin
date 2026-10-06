"""Offline reproductions of the saved 0.7.7 manual evidence, with synthetic IDs/text."""
from copy import deepcopy
import json
import os
from unittest.mock import patch

from test_beeper import RuntimeFixture
from beeper import Failure

CHAT = "!self:synthetic"


class ReconciliationTests(RuntimeFixture):
    def setUp(self):
        super().setUp()
        # The live run used different account and explicitly marked chat-self IDs.
        self.row = {"id": "parent", "chatID": CHAT, "accountID": "network", "isSender": True,
                    "text": "synthetic ping", "isDeleted": False, "mentions": None}
        self.chat = {"id": CHAT, "accountID": "network", "participants": {"hasMore": False, "items": [
            {"id": "chat-self", "isSelf": True}]}}
        self.accounts = [{"accountID": "network", "user": {"id": "account-self", "isSelf": True}}]
        delays = patch("outcomes.OBSERVATION_DELAYS", (0,))
        delays.start()
        self.addCleanup(delays.stop)

    def reconcile(self, operation, extra=(), rows=None, identifier=("--id", "parent")):
        with patch.dict(os.environ, {"BEEPER_READONLY": "1"}), \
                patch("outcomes.dispatch") as dispatch, patch.object(self.runtime, "cli") as cli, \
                patch.object(self.runtime, "api", side_effect=rows or [deepcopy(self.row)]) as api:
            result = self.runtime.command(["messages", "reconcile", "--chat", CHAT,
                                           "--operation", operation, *identifier, *extra])
        dispatch.assert_not_called()
        cli.assert_not_called()
        self.assertTrue(result["reconciliation"])
        self.assertFalse(result["writePerformed"])
        self.assertNotIn("accepted", result)
        self.assertTrue(all(call.args[0] == "GET" for call in api.call_args_list))
        return result["writeOutcome"], api

    def test_predelete_missing_reactions_stays_unknown_and_is_distinct_from_null_and_empty(self):
        for field, value, state in (("missing", None, "unknown"), ("null", None, "unknown"),
                                    ("empty", [], "confirmed"), ("invalid", {}, "unknown"),
                                    ("invalid", [None], "unknown")):
            with self.subTest(field=field, value=value):
                row = deepcopy(self.row)
                if field != "missing":
                    row["reactions"] = value
                outcome, _ = self.reconcile("unreact", ["--reaction", "👍"], rows=[row, self.chat, self.accounts])
                self.assertEqual(outcome["state"], state)
                self.assertEqual(outcome["readBack"]["reactionsField"], field)
                self.assertEqual(outcome["checks"]["reactionStateAvailable"], field == "empty")
                self.assertEqual(outcome["readBack"]["isDeleted"], False)
                if field == "empty":
                    self.assertEqual(outcome["readBack"]["reactionCount"], 0)
                    self.assertFalse(outcome["checks"]["ownReactionPresent"])
                else:
                    self.assertNotIn("ownReactionPresent", outcome["checks"])
                    self.assertNotIn("reactionCount", outcome["readBack"])
                    self.assertIn("missing" if field == "missing" else "null" if field == "null" else "malformed", outcome["reason"])

    def test_chat_self_reaction_still_confirms_despite_different_account_identity(self):
        row = {**self.row, "reactions": [{"participantID": "chat-self", "reactionKey": "👍"}]}
        outcome, _ = self.reconcile("react", ["--reaction", "👍"], rows=[row, self.chat, self.accounts])
        self.assertEqual(outcome["state"], "confirmed")
        self.assertFalse(outcome["checks"]["accountIdentityMatches"])
        self.assertTrue(outcome["checks"]["chatSelfIdentityMatches"])
        self.assertEqual(outcome["readBack"]["reactionCount"], 1)
        self.assertNotIn("chat-self", json.dumps(outcome))
        self.assertNotIn("account-self", json.dumps(outcome))

    def test_postdelete_missing_reactions_cannot_confirm_removal(self):
        self.row["isDeleted"] = True
        outcome, api = self.reconcile("unreact", ["--reaction", "👍"])
        self.assertEqual(outcome["state"], "unknown")
        self.assertTrue(outcome["readBack"]["isDeleted"])
        self.assertEqual(outcome["readBack"]["reactionsField"], "missing")
        self.assertEqual(api.call_count, 1)

    def test_later_deletion_rows_confirm_markers_with_retained_or_missing_text(self):
        for message, text, field in (("parent", "synthetic ping", "present"),
                                     ("reply", None, "missing"), ("file", "synthetic caption", "present")):
            with self.subTest(message=message):
                row = {**self.row, "id": message, "isDeleted": True, "isHidden": False}
                row.pop("text")
                if text is not None:
                    row["text"] = text
                if message == "file":
                    row["type"] = "FILE"
                    row["seen"] = {"synthetic-self": "2026-10-04T15:21:05.609Z"}
                outcome, _ = self.reconcile("delete", rows=[row], identifier=("--id", message))
                self.assertEqual(outcome["state"], "confirmed")
                self.assertTrue(outcome["deleted"])
                self.assertFalse(outcome["hidden"])
                self.assertFalse(outcome["remoteErasureVerified"])
                self.assertEqual(outcome["textRetained"], text is not None)
                self.assertEqual(outcome["readBack"]["textField"], field)
                self.assertNotIn("synthetic-self", json.dumps(outcome))
                self.assertNotIn("synthetic caption", json.dumps(outcome))

    def test_local_hide_does_not_confirm_delete_for_everyone(self):
        self.row["isHidden"] = True
        outcome, _ = self.reconcile("delete")
        self.assertEqual(outcome["state"], "confirmed")
        outcome, _ = self.reconcile("delete", ["--for-everyone"])
        self.assertEqual(outcome["state"], "unknown")

    def test_file_fields_remain_accepted_with_bytes_unverified(self):
        self.row.update(text="synthetic caption", attachments=[{"id": "mxc://synthetic/file"}])
        outcome, _ = self.reconcile("file", ["--caption", "synthetic caption"])
        self.assertEqual(outcome["state"], "accepted")
        self.assertTrue(outcome["checks"]["attachmentVisible"])
        self.assertFalse(outcome["fileIdentityVerified"])
        self.assertNotIn("mxc://", json.dumps(outcome))

    def test_pending_send_resolves_without_claiming_a_new_acknowledgement(self):
        outcome, api = self.reconcile("text", ["--message", "synthetic ping"],
                                      identifier=("--pending-message-id", "~pending"))
        self.assertEqual(outcome["state"], "confirmed")
        self.assertEqual(outcome["messageID"], "parent")
        self.assertTrue(api.call_args.args[1].endswith("/messages/~pending"))
        self.row["id"] = "wrong-final"
        outcome, _ = self.reconcile("text", ["--message", "synthetic ping"])
        self.assertEqual(outcome["state"], "unknown")

    def test_invalid_expectations_and_identifiers_fail_before_lookup(self):
        commands = [
            ["--operation", "edit", "--id", "parent"],
            ["--operation", "unreact", "--id", "parent", "--reaction", ""],
            ["--operation", "delete", "--id", "parent", "--message", "private"],
            ["--operation", "delete", "--id", "parent", "--id", "other"],
            ["--operation", "delete", "--id", "parent", "--target", "other"],
            ["--operation", "delete", "--pending-message-id", "~pending"],
            ["--operation", "delete", "--id", "parent", "--pending-message-id", "~pending"],
            ["--operation", "text", "--id", "", "--pending-message-id", "~pending", "--message", "hello"],
            ["--operation", "delete", "--id", ""],
            ["--operation", "delete"],
            ["--operation", "other", "--id", "parent"],
            ["--operation", "delete", "--id", "parent", "--timeout", "301s"],
        ]
        with patch.object(self.runtime, "cli") as cli, patch.object(self.runtime, "api") as api, patch("outcomes.dispatch") as dispatch:
            for options in commands:
                with self.subTest(options=options), self.assertRaises(Failure) as error:
                    self.runtime.command(["messages", "reconcile", "--chat", "selector", *options])
                self.assertEqual(error.exception.code, "invalid_arguments")
            cli.assert_not_called()
            api.assert_not_called()
            dispatch.assert_not_called()

    def test_literal_flag_like_text_and_mentions_remain_data(self):
        self.row.update(text="--target", linkedMessageID="reply-parent", mentions=["one", "two"])
        outcome, _ = self.reconcile("text", ["--message", "--target", "--reply-to", "reply-parent",
                                              "--mention", "one", "--mention", "two"])
        self.assertEqual(outcome["state"], "confirmed")

    def test_help_needs_no_cli_or_account(self):
        with patch.object(self.runtime, "cli") as cli, patch.object(self.runtime, "api") as api:
            result = self.runtime.command(["messages", "reconcile", "--help"])
        self.assertIn("GET-only", result["help"])
        cli.assert_not_called()
        api.assert_not_called()

    def test_custom_timeout_bounds_each_get_and_total_observation(self):
        with patch("outcomes.time.monotonic", side_effect=[0, 0, .001, .02]):
            outcome, api = self.reconcile("edit", ["--message", "edited", "--timeout", "10"])
        self.assertEqual(outcome["state"], "unknown")
        self.assertEqual(api.call_count, 1)
        self.assertLessEqual(api.call_args.kwargs["timeout"], .01)
        self.assertTrue(outcome["observationExhausted"])

    def test_write_acknowledgement_and_each_observation_are_retained(self):
        ack = {**self.row, "success": True}
        edited = {**self.row, "text": "synthetic edited"}
        with patch("outcomes.dispatch", return_value=ack) as dispatch, \
                patch.object(self.runtime, "api", side_effect=[self.row, edited]), \
                patch("outcomes.OBSERVATION_DELAYS", (0, 0)):
            result = self.runtime.command(["messages", "edit", "--chat", CHAT, "--id", "parent",
                                           "--message", "synthetic edited"])
        dispatch.assert_called_once()
        self.assertEqual(result["text"], "synthetic ping")
        self.assertEqual(result["writeOutcome"]["state"], "confirmed")
        observations = result["writeOutcome"]["observations"]
        self.assertEqual([o["state"] for o in observations], ["unknown", "confirmed"])
        self.assertEqual([o["checks"]["textMatches"] for o in observations], [False, True])
        self.assertEqual([o["attempt"] for o in observations], [1, 2])
        self.assertNotIn("synthetic ping", json.dumps(observations))
        self.assertNotIn("synthetic edited", json.dumps(observations))

    def test_later_read_error_does_not_erase_previous_observation(self):
        with patch("outcomes.OBSERVATION_DELAYS", (0, 0)):
            outcome, _ = self.reconcile("edit", ["--message", "edited"], rows=[self.row, Failure("PRIVATE", 403)])
        self.assertEqual(outcome["state"], "unknown")
        self.assertEqual(outcome["readErrorCode"], 403)
        self.assertFalse(outcome["observations"][0]["checks"]["textMatches"])
        self.assertEqual(outcome["observations"][1]["readErrorCode"], 403)
        self.assertNotIn("PRIVATE", json.dumps(outcome))
