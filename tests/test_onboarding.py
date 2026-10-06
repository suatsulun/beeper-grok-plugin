"""First-run consent and account-cloud reuse, with no real downloads/accounts."""
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

from test_beeper import FAKE_CLI, PROJECT, RuntimeFixture
from beeper import Failure, INSTALL_SCOPE, Runtime, VERSION, read_json, write_json


class OnboardingTests(RuntimeFixture):
    def fresh(self):
        return Runtime(self.root / "fresh-cloud")

    def install_fake(self, root, release):
        binary = root / "bin/beeper"
        binary.parent.mkdir(parents=True, exist_ok=True)
        binary.write_text(f"#!{sys.executable}\n" + FAKE_CLI)
        binary.chmod(0o700)

    def test_onboard_is_read_only_and_missing_setup_proposes_consent(self):
        runtime = self.fresh()
        with patch.dict(os.environ, {"BEEPER_READONLY": "1"}), patch.object(runtime, "cli") as cli, \
                patch("install.latest") as latest:
            result = runtime.onboard()
        self.assertEqual(result["state"], "needs_approval")
        self.assertTrue(result["approvalRequired"])
        self.assertIn("shared Grok cloud computer", result["approvalPrompt"])
        self.assertEqual(result["actions"], ["install_official_cli", "install_official_server", "create_cloud_target", "start_server"])
        self.assertFalse(runtime.root.exists())
        cli.assert_not_called()
        latest.assert_not_called()

    def test_setup_and_update_cannot_install_without_approval(self):
        runtime = self.fresh()
        with patch("install.latest") as latest, patch("install.install_cli") as install, patch.object(runtime, "cli") as cli:
            for update in (False, True):
                with self.subTest(update=update), self.assertRaises(Failure) as caught:
                    runtime.setup(update=update)
                self.assertEqual(caught.exception.code, "approval_required")
        latest.assert_not_called()
        install.assert_not_called()
        cli.assert_not_called()
        self.assertFalse(runtime.root.exists())

    def test_approved_setup_installs_once_and_new_runtime_reuses_profile(self):
        runtime = self.fresh()
        with patch("install.latest", return_value={"version": "0.6.2"}) as latest, \
                patch("install.install_cli", side_effect=self.install_fake) as install:
            runtime.setup(approved=True)
        latest.assert_called_once()
        install.assert_called_once()
        consent_file = runtime.root / "setup-consent.json"
        self.assertTrue(read_json(consent_file)["approved"])
        self.assertEqual(consent_file.stat().st_mode & 0o777, 0o600)
        target_before = runtime.target_file.read_bytes()
        consent_before = consent_file.read_bytes()
        other_conversation = Runtime(runtime.root)
        self.assertEqual(other_conversation.onboard()["state"], "configured")
        with patch("install.latest", side_effect=AssertionError("second download")), \
                patch.object(other_conversation, "server_running", return_value=True):
            other_conversation.setup()
        self.assertEqual(runtime.target_file.read_bytes(), target_before)
        self.assertEqual(consent_file.read_bytes(), consent_before)
        calls = [json.loads(line) for line in (runtime.root / "calls.jsonl").read_text().splitlines()]
        self.assertEqual(sum(c[:2] == ["install", "server"] for c in calls), 1)
        self.assertEqual(sum(c[:3] == ["targets", "add", "server"] for c in calls), 1)
        self.assertEqual(sum(c[:2] == ["targets", "start"] for c in calls), 1)

    def test_partial_approved_install_resumes_without_second_prompt_or_cli_download(self):
        runtime = self.fresh()
        with patch("install.latest", return_value={"version": "0.6.2"}), \
                patch("install.install_cli", side_effect=self.install_fake), \
                patch.object(runtime, "cli", side_effect=Failure("synthetic install interruption")):
            with self.assertRaises(Failure):
                runtime.setup(approved=True)
        self.assertEqual(runtime.onboard()["state"], "setup_incomplete")
        self.assertFalse(runtime.onboard()["approvalRequired"])
        with patch("install.latest", side_effect=AssertionError("already installed CLI")):
            runtime.setup()
        self.assertEqual(runtime.onboard()["state"], "configured")

    def test_consent_from_another_root_scope_or_target_is_not_reused(self):
        runtime = self.fresh()
        valid = {"approved": True, "scope": INSTALL_SCOPE, "dataDirectory": str(runtime.root), "target": "grok-bot"}
        for key, value in (("approved", False), ("scope", "something-else"), ("dataDirectory", "/other"), ("target", "other-bot")):
            with self.subTest(key=key):
                write_json(runtime.root / "setup-consent.json", {**valid, key: value})
                self.assertTrue(runtime.onboard()["approvalRequired"])

    def test_read_only_blocks_approved_setup_without_recording_consent(self):
        runtime = self.fresh()
        with patch.dict(os.environ, {"BEEPER_READONLY": "1"}), self.assertRaises(Failure):
            runtime.setup(approved=True)
        self.assertFalse(runtime.root.exists())

    def test_existing_accounts_are_reused_without_new_consent_or_start(self):
        profile = self.existing()
        before = self.runtime.target_file.read_bytes()
        consent = self.root / "setup-consent.json"
        with patch.object(self.runtime, "cli") as cli:
            plan = self.runtime.onboard()
        cli.assert_not_called()
        self.assertEqual(plan["state"], "configured")
        self.assertFalse(plan["approvalRequired"])
        self.assertFalse(plan["readinessChecked"])
        self.assertNotIn("SYNTHETIC_SECRET", json.dumps(plan))
        index = len(self.calls())
        self.runtime.setup()
        self.assertFalse(consent.exists())
        self.assertEqual(self.runtime.target_file.read_bytes(), before)
        self.assertEqual((profile / "keys.fixture").read_text(), "synthetic encryption state")
        self.assertFalse(any(c[:2] == ["targets", "start"] for c in self.calls()[index:]))

    def test_stopped_existing_server_starts_without_reinstallation(self):
        self.existing()
        (self.root / "stopped").touch()
        index = len(self.calls())
        with patch("install.latest", side_effect=AssertionError("unexpected download")):
            self.runtime.setup()
        self.assertFalse((self.root / "stopped").exists())
        self.assertEqual(sum(c[:2] == ["targets", "start"] for c in self.calls()[index:]), 1)

    def test_orphaned_profile_is_detected_before_any_download_even_with_approval(self):
        runtime = self.fresh()
        profile = runtime.config / "profiles/server/grok-bot"
        profile.mkdir(parents=True)
        (profile / "keys.fixture").write_text("preserve")
        with patch("install.latest") as latest, self.assertRaises(Failure) as caught:
            runtime.setup(approved=True)
        self.assertEqual(caught.exception.code, "setup_requires_repair")
        latest.assert_not_called()
        self.assertEqual((profile / "keys.fixture").read_text(), "preserve")
        self.assertFalse(runtime.target_file.exists())
        self.assertFalse((runtime.root / "setup-consent.json").exists())

    def test_missing_saved_server_or_invalid_target_never_triggers_fresh_install(self):
        self.existing()
        program = Path(read_json(self.runtime.config / "installations.json")["server"]["path"])
        program.unlink()
        with patch("install.latest") as latest, self.assertRaises(Failure):
            self.runtime.setup(approved=True)
        latest.assert_not_called()
        self.assertEqual(self.runtime.onboard()["state"], "repair_required")
        program.write_text("synthetic")
        target = read_json(self.runtime.target_file)
        target["baseURL"] = "https://another-host.invalid"
        write_json(self.runtime.target_file, target)
        with patch.object(self.runtime, "cli") as cli:
            self.assertEqual(self.runtime.onboard()["state"], "repair_required")
        cli.assert_not_called()

    def test_other_setup_lock_does_not_record_approval_or_install(self):
        runtime = self.fresh()
        with runtime.lock(), patch("install.latest") as latest, self.assertRaises(Failure):
            runtime.setup(approved=True)
        latest.assert_not_called()
        self.assertFalse((runtime.root / "setup-consent.json").exists())

    def test_default_profile_does_not_depend_on_client_home_or_current_directory(self):
        with patch.dict(os.environ, {"BEEPER_PLUGIN_HOME": "", "HOME": "/another-client-home"}):
            self.assertEqual(Runtime().root, Path("/workspace/.beeper-grok"))
        with patch.dict(os.environ, {"BEEPER_PLUGIN_HOME": str(self.root)}):
            self.assertEqual(Runtime().root, self.root)

    def test_script_onboard_and_unapproved_setup_have_no_side_effects(self):
        before = sorted(str(p.relative_to(self.root)) for p in self.root.rglob("*"))
        observed = self.helper("onboard")
        self.assertEqual(observed.returncode, 0, observed.stderr)
        self.assertEqual(json.loads(observed.stdout)["data"]["state"], "needs_approval")
        denied = self.helper("setup")
        self.assertEqual(denied.returncode, 1)
        self.assertEqual(json.loads(denied.stdout)["errorCode"], "approval_required")
        self.assertEqual(sorted(str(p.relative_to(self.root)) for p in self.root.rglob("*")), before)

    def test_helper_and_manifest_versions_match(self):
        self.assertEqual(VERSION, read_json(PROJECT / ".grok-plugin/plugin.json")["version"])
