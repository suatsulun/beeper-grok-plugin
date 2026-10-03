"""Writes occur once; accepted requests are not fabricated confirmations."""
from copy import deepcopy
import json
import os
import subprocess
from unittest.mock import patch

from test_beeper import RuntimeFixture
from beeper import Failure, read_json, write_json

CHAT = "!self:synthetic"


class OutcomeTests(RuntimeFixture):
    def setUp(self):
        super().setUp()
        self.row = {"id": "final-1", "chatID": CHAT, "accountID": "network", "isSender": True,
                    "text": "hello", "sendStatus": {"status": "SUCCESS"}}
        self.accounts = [{"accountID": "network", "user": {"id": "own-user", "isSelf": True}}]
        self.chat = {"id": CHAT, "accountID": "network", "participants": {"hasMore": False, "items": [
            {"id": "own-user", "isSelf": True}, {"id": "other-user", "isSelf": False}]}}
        delays = patch("outcomes.OBSERVATION_DELAYS", (0,))
        delays.start()
        self.addCleanup(delays.stop)

    def write(self, args, data=None, rows=None):
        result = data if data is not None else {"accepted": True, "pendingMessageID": "pending-1", "chatID": CHAT}
        with patch("outcomes.dispatch", return_value=result) as dispatch, \
                patch.object(self.runtime, "cli") as cli, \
                patch.object(self.runtime, "api", side_effect=rows or [deepcopy(self.row)]) as api:
            output = self.runtime.command(args)
        dispatch.assert_called_once()
        cli.assert_not_called()
        return output["writeOutcome"], api

    def test_send_readback_and_reply_link_must_match(self):
        args = ["send", "text", "--to", CHAT, "--message", "hello", "--reply-to", "parent"]
        outcome, _ = self.write(args)
        self.assertEqual(outcome["state"], "unknown")
        self.row["linkedMessageID"] = "parent"
        outcome, _ = self.write(args)
        self.assertEqual(outcome["state"], "confirmed")
        self.assertFalse(outcome["retrySafe"])

    def test_pending_failure_and_resolved_without_status_are_distinct(self):
        for status, expected in [("PENDING", "pending"), ("FAIL_PERMANENT", "failed"), (None, "confirmed")]:
            with self.subTest(status=status):
                self.row["sendStatus"] = {"status": status}
                outcome, _ = self.write(["send", "text", "--to", CHAT, "--message", "hello"])
                self.assertEqual(outcome["state"], expected)

    def test_edit_requires_matching_body_and_author(self):
        args = ["messages", "edit", "--chat", CHAT, "--id", "final-1", "--message", "edited"]
        outcome, _ = self.write(args)
        self.assertEqual(outcome["state"], "unknown")
        self.row["text"] = "edited"
        outcome, _ = self.write(args)
        self.assertEqual(outcome["state"], "confirmed")
        self.row["isSender"] = False
        outcome, _ = self.write(args)
        self.assertEqual(outcome["state"], "unknown")

    def test_deleted_tombstone_reports_retained_text_not_erasure(self):
        self.row["isDeleted"] = True
        outcome, _ = self.write(["messages", "delete", "--chat", CHAT, "--id", "final-1", "--for-everyone"])
        self.assertEqual(outcome["state"], "confirmed")
        self.assertTrue(outcome["textRetained"])
        self.assertFalse(outcome["remoteErasureVerified"])

    def test_failed_readback_does_not_retry_or_lose_native_result(self):
        args = ["send", "text", "--to", CHAT, "--message", "hello"]
        outcome, api = self.write(args, rows=[Failure("unreachable")])
        self.assertEqual(outcome["state"], "unknown")
        self.assertEqual(api.call_count, 1)
        with patch("outcomes.dispatch", side_effect=Failure("timeout", "timeout")) as dispatch:
            with self.assertRaises(Failure) as error:
                self.runtime.command(args)
        self.assertEqual(dispatch.call_count, 1)
        self.assertEqual(error.exception.write_outcome["state"], "unknown")

    def test_reactions_require_own_identity_and_key(self):
        self.row["reactions"] = [{"participantID": "other-user", "reactionKey": "👍"}]
        args = ["send", "react", "--to", CHAT, "--id", "final-1", "--reaction", "👍"]
        outcome, _ = self.write(args, rows=[self.row, self.chat, self.accounts])
        self.assertEqual(outcome["state"], "unknown")
        self.row["reactions"].append({"participantID": "own-user", "reactionKey": "👍"})
        outcome, _ = self.write(args, rows=[self.row, self.chat, self.accounts])
        self.assertEqual(outcome["state"], "confirmed")
        args[1] = "unreact"
        outcome, _ = self.write(args, rows=[self.row, self.chat, self.accounts])
        self.assertEqual(outcome["state"], "unknown")
        self.row["reactions"] = []
        outcome, _ = self.write(args, rows=[self.row, self.chat, self.accounts])
        self.assertEqual(outcome["state"], "confirmed")

    def reaction(self, operation="react"):
        return self.write(["send", operation, "--to", CHAT, "--id", "final-1", "--reaction", "👍"],
                          rows=[self.row, self.chat, self.accounts])

    def test_reaction_uses_explicit_chat_self_despite_distinct_account_id(self):
        # Sanitized shape observed on WhatsApp message 18720: ID-1 != ID-2.
        self.accounts[0]["user"]["id"] = "ID-2"
        self.chat["participants"]["items"] = [{"id": "ID-1", "isSelf": True}, {"id": "ID-3", "isSelf": False}]
        self.row["reactions"] = [{"id": "ID-1", "participantID": "ID-1", "reactionKey": "👍", "emoji": True}]
        outcome, api = self.reaction()
        self.assertEqual(outcome["state"], "confirmed")
        self.assertTrue(outcome["checks"]["chatSelfIdentityMatches"])
        self.assertFalse(outcome["checks"]["accountIdentityMatches"])
        self.assertEqual(outcome["readAttempts"], 1)
        self.assertEqual(api.call_count, 3)
        self.assertTrue(all(call.args[0] == "GET" for call in api.call_args_list))
        self.assertNotIn("ID-1", json.dumps(outcome))
        self.assertNotIn("ID-2", json.dumps(outcome))

    def test_unreact_cannot_confirm_while_either_self_identity_still_reacts(self):
        self.chat["participants"]["items"][0]["id"] = "room-self"
        for actor in ("room-self", "own-user"):
            with self.subTest(actor=actor):
                self.row["reactions"] = [{"participantID": actor, "reactionKey": "👍"}]
                outcome, _ = self.reaction("unreact")
                self.assertEqual(outcome["state"], "unknown")
                self.assertTrue(outcome["checks"]["ownReactionPresent"])
        self.row["reactions"] = [{"participantID": "other-user", "reactionKey": "👍"}]
        outcome, _ = self.reaction("unreact")
        self.assertEqual(outcome["state"], "confirmed")

    def test_same_name_or_phone_and_wrong_emoji_do_not_confirm(self):
        for actor, key in (("other-user", "👍"), ("own-user", "👎"), ("own-user", "👍\ufe0f")):
            with self.subTest(actor=actor, key=key):
                for member in self.chat["participants"]["items"]:
                    member.update(fullName="Same name", phoneNumber="+10000000000")
                self.row["reactions"] = [{"participantID": actor, "reactionKey": key}]
                outcome, _ = self.reaction()
                self.assertEqual(outcome["state"], "unknown")

    def test_reaction_identity_scope_must_match_chat_and_account(self):
        self.row["reactions"] = [{"participantID": "own-user", "reactionKey": "👍"}]
        for field, value in (("id", "!other:synthetic"), ("accountID", "other-account"), ("accountID", None)):
            with self.subTest(field=field):
                chat = {**self.chat, field: value}
                outcome, api = self.write(["send", "react", "--to", CHAT, "--id", "final-1", "--reaction", "👍"],
                                          rows=[self.row, chat])
                self.assertEqual(outcome["state"], "unknown")
                self.assertTrue(outcome["scopeMismatch"])
                self.assertFalse(outcome["observationExhausted"])
                self.assertEqual(api.call_count, 2)

    def test_reaction_does_not_use_another_accounts_identity(self):
        self.accounts = [{"accountID": "other-network", "user": {"id": "other-user", "isSelf": True}}]
        self.row["reactions"] = [{"participantID": "other-user", "reactionKey": "👍"}]
        outcome, _ = self.reaction()
        self.assertEqual(outcome["state"], "unknown")
        self.assertFalse(outcome["checks"]["accountIdentityAvailable"])

    def test_conflicting_self_flags_do_not_confirm_add_or_removal(self):
        for actor in ("own-user", "room-self"):
            for operation in ("react", "unreact"):
                with self.subTest(actor=actor, operation=operation):
                    self.chat["participants"]["items"] = [{"id": "room-self", "isSelf": True}, {"id": actor, "isSelf": False}]
                    self.row["reactions"] = [{"participantID": actor, "reactionKey": "👍"}]
                    outcome, _ = self.reaction(operation)
                    self.assertEqual(outcome["state"], "unknown")
                    self.assertFalse(outcome["observationExhausted"])

    def test_missing_room_self_cannot_falsely_confirm_alias_removal(self):
        self.chat["participants"] = {"hasMore": True, "items": [{"id": "other-user", "isSelf": False}]}
        self.row["reactions"] = [{"participantID": "unresolved-room-user", "reactionKey": "👍"}]
        outcome, _ = self.reaction("unreact")
        self.assertEqual(outcome["state"], "unknown")
        self.row["reactions"] = [{"participantID": "own-user", "reactionKey": "👍"}]
        outcome, _ = self.reaction()
        self.assertEqual(outcome["state"], "confirmed")
        self.row["reactions"] = []
        outcome, _ = self.reaction("unreact")
        self.assertEqual(outcome["state"], "confirmed")

    def test_reaction_missing_or_malformed_state_is_not_removal(self):
        for reactions in (None, {}, [None], [{"participantID": "own-user"}], [{"participantID": "", "reactionKey": "👍"}]):
            with self.subTest(reactions=reactions):
                self.row["reactions"] = reactions
                outcome, _ = self.reaction("unreact")
                self.assertEqual(outcome["state"], "unknown")
                self.assertFalse(outcome["checks"]["reactionStateAvailable"])
        self.chat["participants"] = None
        self.row["reactions"] = []
        outcome, _ = self.reaction("unreact")
        self.assertEqual(outcome["state"], "unknown")

    def test_delayed_reaction_caches_identity_and_never_repeats_write(self):
        self.chat["participants"]["items"][0]["id"] = "room-self"
        self.row["reactions"] = []
        updated = {**self.row, "reactions": [{"participantID": "room-self", "reactionKey": "👍"}]}
        with patch("outcomes.OBSERVATION_DELAYS", (0, 0, 0, 0)):
            outcome, api = self.write(["send", "react", "--to", CHAT, "--id", "final-1", "--reaction", "👍"],
                                      rows=[self.row, self.chat, self.accounts, updated])
        self.assertEqual(outcome["state"], "confirmed")
        self.assertEqual(outcome["readAttempts"], 2)
        self.assertEqual(api.call_count, 4)
        self.assertTrue(all(call.args[0] == "GET" for call in api.call_args_list))

    def test_reaction_can_be_reconciled_without_dispatching_another_write(self):
        from outcomes import observe
        self.chat["participants"]["items"][0]["id"] = "room-self"
        self.row["reactions"] = [{"participantID": "room-self", "reactionKey": "👍"}]
        with patch.dict(os.environ, {"BEEPER_READONLY": "1"}), patch.object(self.runtime, "cli") as cli, \
                patch.object(self.runtime, "api", side_effect=[self.row, self.chat, self.accounts]) as api:
            result = observe(self.runtime, "react", CHAT, {}, {"id": "final-1", "reaction": "👍"})
        self.assertEqual(result["state"], "confirmed")
        cli.assert_not_called()
        self.assertTrue(all(call.args[0] == "GET" for call in api.call_args_list))

    def test_attachment_presence_does_not_prove_file_identity(self):
        self.row["attachments"] = [{"id": "mxc://synthetic/file"}]
        outcome, _ = self.write(["send", "file", "--to", CHAT, "--file", "/not-opened.txt"])
        self.assertEqual(outcome["state"], "accepted")

    def test_different_message_or_chat_cannot_confirm(self):
        self.row["id"] = "wrong-message"
        outcome, _ = self.write(["messages", "edit", "--chat", CHAT, "--id", "final-1", "--message", "hello"])
        self.assertEqual(outcome["state"], "unknown")
        outcome, _ = self.write(["send", "text", "--to", CHAT, "--message", "hello"],
                               data={"chatID": CHAT, "message": {"id": "final-1"}})
        self.assertEqual(outcome["state"], "unknown")
        outcome, api = self.write(["send", "text", "--to", CHAT, "--message", "hello"], data={"chatID": "!wrong:chat"})
        self.assertEqual(outcome["state"], "unknown")
        api.assert_not_called()

    def test_read_only_and_invalid_write_options_do_not_dispatch(self):
        args = ["send", "text", "--to", CHAT, "--message", "hello"]
        with patch.object(self.runtime, "cli") as cli:
            with patch.dict(os.environ, {"BEEPER_READONLY": "1"}), self.assertRaises(Failure):
                self.runtime.command(args)
            with self.assertRaises(Failure):
                self.runtime.command(args + ["--read-only"])
            with self.assertRaises(Failure):
                self.runtime.command(args + ["--message", "second"])
            cli.assert_not_called()

    def test_delayed_edit_rechecks_without_repeating_write(self):
        args = ["messages", "edit", "--chat", CHAT, "--id", "final-1", "--message", "edited"]
        with patch("outcomes.OBSERVATION_DELAYS", (0, 0, 0, 0)):
            outcome, api = self.write(args, rows=[self.row, {**self.row, "text": "edited"}])
        self.assertEqual(outcome["state"], "confirmed")
        self.assertEqual(outcome["readAttempts"], 2)
        self.assertEqual(api.call_count, 2)
        self.assertTrue(all(c.args[0] == "GET" for c in api.call_args_list))
        self.assertFalse(outcome["deliveryVerified"])

    def test_temporary_not_found_then_pending_then_observed(self):
        with patch("outcomes.OBSERVATION_DELAYS", (0, 0, 0, 0)):
            outcome, api = self.write(["send", "text", "--to", CHAT, "--message", "hello"], rows=[
                Failure("not yet visible", 404), {**self.row, "sendStatus": {"status": "PENDING"}}, self.row])
        self.assertEqual(outcome["state"], "confirmed")
        self.assertEqual(api.call_count, 3)
        self.assertEqual(len({call.args[1] for call in api.call_args_list}), 1)

    def test_permanent_failure_or_auth_failure_stops_read_retries(self):
        for row, state in [({**self.row, "sendStatus": {"status": "FAIL_PERMANENT"}}, "failed"),
                           (Failure("denied", 403), "unknown")]:
            with patch("outcomes.OBSERVATION_DELAYS", (0, 0, 0, 0)):
                outcome, api = self.write(["send", "text", "--to", CHAT, "--message", "hello"], rows=[row])
            self.assertEqual(outcome["state"], state)
            self.assertEqual(api.call_count, 1)

    def test_exhausted_observation_preserves_identity_and_never_resends(self):
        with patch("outcomes.OBSERVATION_DELAYS", (0, 0, 0)):
            outcome, api = self.write(["messages", "edit", "--chat", CHAT, "--id", "final-1", "--message", "edited"], rows=[self.row] * 3)
        self.assertEqual(outcome["state"], "unknown")
        self.assertEqual(outcome["messageID"], "final-1")
        self.assertTrue(outcome["observationExhausted"])
        self.assertEqual(api.call_count, 3)

    def test_deadline_stops_rechecks_and_bounds_api_timeout(self):
        with patch("outcomes.OBSERVATION_DELAYS", (0, 0, 0)), patch("outcomes.time.monotonic", side_effect=[0, 0, 1, 9]):
            outcome, api = self.write(["messages", "edit", "--chat", CHAT, "--id", "final-1", "--message", "edited"])
        self.assertEqual(api.call_count, 1)
        self.assertLessEqual(api.call_args.kwargs["timeout"], 2)
        self.assertTrue(outcome["observationExhausted"])

    def test_missing_optional_bridge_status_does_not_hide_observed_content(self):
        self.row.pop("sendStatus")
        outcome, _ = self.write(["send", "text", "--to", CHAT, "--message", "hello"])
        self.assertEqual(outcome["state"], "confirmed")
        self.assertEqual(outcome["bridgeSendStatus"], "unavailable")
        self.assertTrue(outcome["contentVerified"])
        self.assertFalse(outcome["deliveryVerified"])

    def test_flag_like_message_is_data_and_real_overrides_are_blocked(self):
        for body in ("--reply-to=literal", "--help", "--read-only", "--target=other", "-qtother", "a\n$HOME `cmd` \\"):
            self.row["text"] = body
            def api_reply(method, *args, **kwargs):
                return {"pendingMessageID": "pending", "chatID": CHAT} if method == "POST" else self.row
            with patch.object(self.runtime, "cli", return_value={"pendingMessageID": "pending"}) as cli, patch.object(self.runtime, "api", side_effect=api_reply) as api:
                result = self.runtime.command(["send", "text", "--to", CHAT, "--message", body])
            self.assertEqual(result["writeOutcome"]["state"], "confirmed")
            writes = [c for c in api.call_args_list if c.args[0] != "GET"]
            self.assertEqual(cli.call_count + len(writes), 1)
            if writes:
                self.assertEqual(writes[0].args[2]["text"], body)
            else:
                self.assertIn("--message=" + body, cli.call_args.args[0])
            self.assertNotIn("replyMatches", result["writeOutcome"]["checks"])
        for tail in (["--target=other"], ["-qtother"], ["--base-url", "http://example.invalid"], ["--pick", "0"]):
            with patch.object(self.runtime, "cli") as cli, self.assertRaises(Failure):
                self.runtime.command(["send", "text", "--to", CHAT, "--message", "hello", *tail])
            cli.assert_not_called()

    def test_literal_text_api_path_keeps_reply_mentions_and_never_retries_a_write(self):
        args = ["send", "text", "--to", CHAT, "--message", "--read-only", "--reply-to", "parent",
                "--mention", "one", "--mention", "two", "--no-preview"]
        row = {**self.row, "text": "--read-only", "linkedMessageID": "parent", "mentions": ["one", "two"]}
        with patch.object(self.runtime, "cli") as cli, patch.object(self.runtime, "api", side_effect=[{"pendingMessageID": "pending"}, row]) as api:
            result = self.runtime.command(args)
        cli.assert_not_called()
        self.assertEqual(api.call_args_list[0].args[2], {"text": "--read-only", "replyToMessageID": "parent", "mentions": ["one", "two"], "disableLinkPreview": True})
        self.assertEqual(result["writeOutcome"]["state"], "confirmed")
        with patch.object(self.runtime, "cli") as cli, patch.object(self.runtime, "api", side_effect=Failure("timeout", "timeout")) as api:
            with self.assertRaises(Failure) as error:
                self.runtime.command(args)
        cli.assert_not_called()
        self.assertEqual(api.call_count, 1)
        self.assertEqual(error.exception.write_outcome["state"], "unknown")

    def test_formatted_text_and_mentions_are_never_lossily_compared(self):
        self.row.update(text="**Hello**\n@alice", mentions=["alice"])
        args = ["send", "text", "--to", CHAT, "--message", "**Hello**\r\n@alice", "--mention", "alice"]
        outcome, _ = self.write(args)
        self.assertEqual(outcome["state"], "confirmed")
        self.row["text"] = "<strong>Hello</strong>\n@alice"
        outcome, _ = self.write(args)
        self.assertEqual(outcome["state"], "unknown")
        self.assertFalse(outcome["contentVerified"])
        self.row["text"] = "**Hello**\n@alice"
        self.row["mentions"] = ["different-user"]
        outcome, _ = self.write(args)
        self.assertEqual(outcome["state"], "unknown")

    def test_voice_sticker_caption_and_local_hide_have_distinct_evidence(self):
        self.row["attachments"] = [{"isVoiceNote": True}]
        outcome, _ = self.write(["send", "voice", "--to", CHAT, "--file", "/synthetic.ogg"])
        self.assertEqual(outcome["state"], "accepted")
        self.assertFalse(outcome["fileIdentityVerified"])
        outcome, _ = self.write(["send", "sticker", "--to", CHAT, "--file", "/synthetic.webp"])
        self.assertEqual(outcome["state"], "unknown")
        outcome, _ = self.write(["send", "file", "--to", CHAT, "--file", "/synthetic", "--caption", "wrong"])
        self.assertEqual(outcome["state"], "unknown")
        self.row["isHidden"] = True
        outcome, _ = self.write(["messages", "delete", "--chat", CHAT, "--id", "final-1"])
        self.assertEqual(outcome["state"], "confirmed")
        outcome, _ = self.write(["messages", "delete", "--chat", CHAT, "--id", "final-1", "--for-everyone"])
        self.assertEqual(outcome["state"], "unknown")


class DiagnosticTests(RuntimeFixture):
    def test_contact_string_error_is_useful_without_identifiers(self):
        failure = {"success": False, "error": "Contact not found: SECRET_ID other-private-text", "exitCode": 5, "kind": "abort"}
        result = subprocess.CompletedProcess([], 5, b"", json.dumps(failure).encode())
        with patch.object(self.runtime, "run", return_value=(result, False)), self.assertRaises(Failure) as error:
            self.runtime.cli(["contacts", "show", "SECRET_ID"])
        self.assertEqual(error.exception.code, "contact_not_found")
        self.assertNotIn("SECRET_ID", str(error.exception))
        self.assertNotIn("other-private-text", str(error.exception))

    def test_nonzero_doctor_health_remains_successful_diagnostic(self):
        data = {"ok": False, "checks": [{"state": "initializing"}]}
        result = subprocess.CompletedProcess([], 1, json.dumps({"success": True, "data": data}).encode(), b"")
        with patch.object(self.runtime, "run", return_value=(result, False)):
            self.assertEqual(self.runtime.cli(["doctor", "--read-only"]), data)

    def test_zero_exit_failure_and_malformed_json_are_classified_safely(self):
        for payload, status in [(json.dumps({"success": False, "error": "Contact not found: SECRET"}).encode(), 0),
                                (b"SECRET not json", 1),
                                (b'{"kind":[],"error":{"code":{},"message":"SECRET"}}', 1),
                                (b'[]', 1)]:
            with patch.object(self.runtime, "run", return_value=(subprocess.CompletedProcess([], status, payload, b""), False)):
                with self.assertRaises(Failure) as error:
                    self.runtime.cli(["contacts", "show", "SECRET"])
            self.assertNotIn("SECRET", str(error.exception))

    def test_idle_show_leaves_cache_unchanged_and_done_cannot_confirm(self):
        profile = self.existing()
        cache = self.root / "verification-comparison.json"
        self.runtime.verify("show")
        self.assertFalse(cache.exists())
        current = {"id": "v1", "state": "sas_ready", "sas": {"decimals": "123"}, "extra": "not-cached"}
        write_json(self.root / "verification.fixture.json", current)
        self.runtime.verify("show")
        self.assertEqual(read_json(cache), {"id": "v1", "sas": {"decimals": "123"}})
        before = (cache.read_bytes(), cache.stat().st_mtime_ns)
        write_json(self.root / "verification.fixture.json", {})
        self.runtime.verify("show")
        self.assertEqual((cache.read_bytes(), cache.stat().st_mtime_ns), before)
        with self.assertRaises(Failure):
            self.runtime.verify("sas-confirm", matches=True)
        for state in ("done", "cancelled", "error"):
            write_json(self.root / "verification.fixture.json", {**current, "state": state})
            with self.assertRaises(Failure):
                self.runtime.verify("sas-confirm", matches=True)
        self.assertTrue((profile / "keys.fixture").exists())

    def test_read_only_show_does_not_cache_and_confirmation_is_blocked(self):
        self.existing()
        write_json(self.root / "verification.fixture.json", {"id": "v1", "sas": {"decimals": "123"}})
        with patch.dict(os.environ, {"BEEPER_READONLY": "1"}):
            self.runtime.verify("show")
            self.assertFalse((self.root / "verification-comparison.json").exists())
            with self.assertRaises(Failure):
                self.runtime.verify("sas-confirm", matches=True)
