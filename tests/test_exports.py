"""Full-export guard tests; native CLI integration lives in PublishedCLITests."""
import fcntl
import json
import os
from unittest.mock import patch

from test_beeper import RuntimeFixture, write_json
from beeper import Failure
from exports import MARKER, CHECKPOINT


class ExportTests(RuntimeFixture):
    def setUp(self):
        super().setUp()
        self.existing()
        self.output = self.root / "exports/snapshot"

    def export(self, *flags):
        return self.runtime.command(["export", "--out", str(self.output), *flags])

    def test_read_only_blocks_before_cli_api_or_output_creation(self):
        for flag, environment in ((["--read-only"], {}), ([], {"BEEPER_READONLY": "1"})):
            with patch.dict(os.environ, environment), patch.object(self.runtime, "cli") as cli, \
                    patch.object(self.runtime, "api") as api, self.assertRaises(Failure):
                self.export(*flag)
            cli.assert_not_called()
            api.assert_not_called()
            self.assertFalse(self.output.exists())
        for flags, environment in ((["--read-only"], {}), ([], {"BEEPER_READONLY": "1"})):
            with patch.dict(os.environ, environment), patch.object(self.runtime, "run") as run, self.assertRaises(Failure):
                self.runtime.cli(["export", "--out", str(self.output), *flags])
            run.assert_not_called()

    def test_changed_limits_fail_before_cli_and_preserve_prior_output(self):
        self.export("--limit-messages", "2")
        before = {p.name: p.read_bytes() for p in self.output.iterdir() if p.is_file()}
        with patch.object(self.runtime, "cli") as cli, self.assertRaises(Failure) as error:
            self.export()
        self.assertEqual(error.exception.code, "export_scope_changed")
        cli.assert_not_called()
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.output.iterdir() if p.is_file()})

    def test_force_rebuilds_changed_limits_without_reusing_native_counts(self):
        self.export("--limit-messages", "2")
        def native(args, **kwargs):
            self.assertIn("--force", args)
            self.assertFalse((self.output / CHECKPOINT).exists())
            write_json(self.output / "manifest.json", {"chatCount": 1, "messageCount": 6, "attachmentCount": 0})
            write_json(self.output / CHECKPOINT, {"chats": {"self": {"messageCount": 6}}})
        with patch.object(self.runtime, "cli", side_effect=native):
            result = self.export("--force")
        self.assertEqual(result["messageCount"], 6)
        self.assertFalse(result["coverage"]["limitsApplied"])
        self.assertTrue(json.loads((self.output / MARKER).read_text())["completed"])

    def test_different_source_or_content_scope_cannot_silently_reuse_checkpoints(self):
        self.export("--account", "one", "--no-attachments")
        for flags in (("--account", "two", "--force"), ("--account", "one")):
            with patch.object(self.runtime, "cli") as cli, self.assertRaises(Failure) as error:
                self.export(*flags)
            self.assertEqual(error.exception.code, "export_scope_changed")
            cli.assert_not_called()

    def test_legacy_unknown_state_requires_new_output_even_with_force(self):
        write_json(self.output / CHECKPOINT, {"chats": {"self": {"complete": True, "messageCount": 2}}})
        original = (self.output / CHECKPOINT).read_bytes()
        with patch.object(self.runtime, "cli") as cli, self.assertRaises(Failure) as error:
            self.export("--force")
        self.assertEqual(error.exception.code, "export_scope_unknown")
        self.assertEqual((self.output / CHECKPOINT).read_bytes(), original)
        self.assertFalse((self.output / MARKER).exists())
        cli.assert_not_called()

    def test_same_scope_resumes_failed_run_and_reports_limits(self):
        def failing(*_, **__):
            write_json(self.output / CHECKPOINT, {"chats": {"self": {"complete": False, "cursor": "real-token", "messageCount": 1}}})
            raise Failure("synthetic interruption")
        with patch.object(self.runtime, "cli", side_effect=failing), self.assertRaises(Failure):
            self.export("--limit-messages", "2")
        self.assertFalse(json.loads((self.output / MARKER).read_text())["completed"])
        def resume(*_, **__):
            self.assertEqual(json.loads((self.output / CHECKPOINT).read_text())["chats"]["self"]["cursor"], "real-token")
            write_json(self.output / CHECKPOINT, {"chats": {"self": {"complete": True, "messageCount": 2}}})
            write_json(self.output / "manifest.json", {"chatCount": 1, "messageCount": 2, "attachmentCount": 0})
        with patch.object(self.runtime, "cli", side_effect=resume):
            result = self.export("--limit-messages", "2")
        self.assertTrue(result["coverage"]["limitReached"])
        self.assertFalse(result["coverage"]["historyComplete"])

    def test_missing_manifest_cannot_reuse_previous_success(self):
        self.export()
        with patch.object(self.runtime, "cli", return_value={"completed": True}), self.assertRaises(Failure) as error:
            self.export()
        self.assertEqual(error.exception.code, "invalid_export_result")
        self.assertFalse(json.loads((self.output / MARKER).read_text())["completed"])

    def test_protected_destination_invalid_flags_and_parallel_export_do_not_dispatch(self):
        for output in (self.runtime.root, self.runtime.config, self.runtime.config / "profiles/server/grok-bot"):
            with patch.object(self.runtime, "cli") as cli, self.assertRaises(Failure):
                self.runtime.command(["export", "--out", str(output)])
            cli.assert_not_called()
        for flags in (("--limit-messages", "0"), ("--limit-chats", "-2"), ("--pick", "0")):
            with patch.object(self.runtime, "cli") as cli, self.assertRaises(Failure):
                self.export(*flags)
            cli.assert_not_called()
        self.output.mkdir(parents=True)
        with (self.output / ".beeper-plugin-export.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with patch.object(self.runtime, "cli") as cli, self.assertRaises(Failure) as error:
                self.export()
            self.assertEqual(error.exception.code, "export_busy")
            cli.assert_not_called()
