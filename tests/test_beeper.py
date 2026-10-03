"""Behavior tests with synthetic data; no Beeper account or network access."""
from contextlib import redirect_stdout
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import http.client
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "skills/beeper/scripts"))
from beeper import Failure, Runtime, emit, read_json, write_json
from install import InstallError, RELEASES, install_cli, latest
from signin import make_server

FAKE_CLI = r'''
import json,os,sys
from pathlib import Path
args=sys.argv[1:]
root=Path(os.environ['BEEPER_CLI_CONFIG_DIR']).parent
config=root/'config'
target_file=config/'targets/grok-bot.json'
with (root/'calls.jsonl').open('a') as out: out.write(json.dumps(args)+'\n')
def load(path): return json.loads(path.read_text()) if path.exists() else {}
def save(path,data):
 path.parent.mkdir(parents=True,exist_ok=True)
 path.write_text(json.dumps(data))
data={}
if args[0]=='version': data={'version':'0.6.2'}
elif args[:2]==['install','server']:
 program=root/'cache/server-build/beeper-server'; program.parent.mkdir(parents=True,exist_ok=True);program.write_text('old program')
 save(config/'installations.json',{'server':{'version':'4.3.115','path':str(program)}})
elif args[:3]==['targets','add','server']:
 port=int(args[args.index('--port')+1])
 save(target_file,{'id':'grok-bot','type':'server','managed':True,'serverEnv':'production','dataDir':str(config/'profiles/server/grok-bot'),'port':port,'baseURL':'http://127.0.0.1:'+str(port)})
elif args[:2]==['targets','stop']:
 if (root/'stopped').exists() or (root/'fail-stop').exists():
  print(json.dumps({'success':False,'error':'Profile could not be stopped'}),file=sys.stderr);sys.exit(1)
 (root/'stopped').touch()
elif args[:2]==['targets','start']:
 (root/'stopped').unlink(missing_ok=True)
elif args[0]=='update':
 if '--check' in args: data=[{'kind':'server','available':not (root/'up-to-date').exists()}]
 elif (root/'fail-update').exists():
  print(json.dumps({'success':False,'error':{'code':'http_error','message':'SYNTHETIC_SECRET'}}));sys.exit(1)
 else:
  installed=load(config/'installations.json');installed['server']['version']='4.3.156';save(config/'installations.json',installed)
elif args[0]=='status': data={'target':load(target_file),'readiness':{'state':'initializing'}}
elif args[:2]==['verify','show']: data=load(root/'verification.fixture.json') or None
elif args[:2]==['targets','status']: data={'running':True,'reachable':True}
elif args[:2]==['accounts','list']: data=[{'id':'synthetic-network'}]
elif args[:2]==['chats','list']: data=[{'id':'chat-1','title':'Synthetic chat'}]
elif args[:2]==['chats','show']: data={'id':'!chat:synthetic','title':'Synthetic chat'}
elif args[:2]==['messages','list']:
 data={'tokenUsed':os.environ.get('BEEPER_ACCESS_TOKEN'),'config':os.environ['BEEPER_CLI_CONFIG_DIR'],'envTarget':os.environ['BEEPER_TARGET']}
elif args[:2]==['messages','export']:
 Path(args[args.index('--output')+1]).write_text('[]');sys.exit(0)
elif args[0]=='export':
 out=Path(args[args.index('--out')+1]);save(out/'manifest.json',{'chatCount':1,'messageCount':2,'attachmentCount':0});save(out/'.beeper-export-state.json',{'chats':{}});print('Exported synthetic data');sys.exit(0)
elif args[0]=='watch':
 if (root/'fail-watch').exists():sys.exit(1)
 if (root/'child-watch').exists():
  import subprocess
  child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'])
  (root/'child.pid').write_text(str(child.pid))
 print(json.dumps({'type':'message.upserted','chatID':'chat-1','messageID':'message-1'}),flush=True)
 import time;time.sleep(5)
print(json.dumps({'success':True,'data':data}))
'''


class RuntimeFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix=".test-", dir=PROJECT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runtime = Runtime(self.root)
        self.runtime.binary.parent.mkdir()
        self.runtime.binary.write_text(f"#!{sys.executable}\n" + FAKE_CLI)
        self.runtime.binary.chmod(0o700)
        running = patch.object(self.runtime, "server_running", side_effect=lambda: not (self.root / "stopped").exists())
        running.start()
        self.addCleanup(running.stop)

    def existing(self, authenticated=True):
        self.runtime.cli(["install", "server"])
        self.runtime.cli(["targets", "add", "server", "grok-bot", "--port", "23374"])
        target = read_json(self.runtime.target_file)
        if authenticated:
            target["auth"] = {"accessToken": "SYNTHETIC_SECRET"}
        write_json(self.runtime.target_file, target)
        profile = self.root / "config/profiles/server/grok-bot"
        profile.mkdir(parents=True)
        (profile / "keys.fixture").write_text("synthetic encryption state")
        return profile

    def calls(self):
        return [json.loads(line) for line in (self.root / "calls.jsonl").read_text().splitlines()]

    def helper(self, *args):
        return subprocess.run([sys.executable, str(PROJECT / "skills/beeper/scripts/beeper.py"), *args],
                              env={**os.environ, "BEEPER_PLUGIN_HOME": str(self.root)},
                              capture_output=True, text=True, timeout=5)


class RuntimeTests(RuntimeFixture):
    def test_update_checks_share_release_cache_and_skip_native_cli_check(self):
        self.existing()
        release = {"version": "0.6.2", "source": "release-manifest", "cached": True, "checkedAt": 100}
        with patch("install.latest", return_value=release) as lookup:
            data = self.runtime.check_updates()
        lookup.assert_called_once_with(self.root)
        self.assertTrue(data[0]["checked"])
        self.assertTrue(data[0]["cached"])
        self.assertFalse(data[0]["available"])
        self.assertEqual(self.calls()[-1], ["update", "--check", "--server", "--json"])

    def test_failed_cli_lookup_does_not_hide_server_check_or_claim_up_to_date(self):
        self.existing()
        with patch("install.latest", side_effect=InstallError("GitHub unavailable", "github_unreachable")):
            data = self.runtime.check_updates()
        self.assertFalse(data[0]["checked"])
        self.assertIsNone(data[0]["available"])
        self.assertEqual(data[0]["error"]["code"], "github_unreachable")
        self.assertEqual(data[1]["kind"], "server")
        self.assertTrue(data[1]["available"])

    def test_lookup_failure_before_setup_preserves_existing_installation(self):
        self.existing()
        before = self.runtime.target_file.read_bytes()
        calls = len(self.calls())
        with patch("install.latest", side_effect=InstallError("Bad manifest", "invalid_release_metadata")):
            with self.assertRaises(InstallError):
                self.runtime.setup(update=True)
        self.assertEqual(self.runtime.target_file.read_bytes(), before)
        self.assertEqual(len(self.calls()), calls)

    def test_setup_reuses_existing_profile_without_network_or_reinstallation(self):
        profile = self.existing()
        before = self.runtime.target_file.read_bytes()
        with patch("install.latest", side_effect=AssertionError("unexpected download")):
            self.runtime.setup()
            self.runtime.setup()
        self.assertEqual(before, self.runtime.target_file.read_bytes())
        self.assertEqual((profile / "keys.fixture").read_text(), "synthetic encryption state")
        self.assertEqual(sum(c[:2] == ["install", "server"] for c in self.calls()), 1)
        self.assertEqual(self.runtime.command(["chats", "list"])[0]["id"], "chat-1")

    def test_missing_target_does_not_overwrite_existing_profile(self):
        self.existing()
        self.runtime.target_file.unlink()
        with self.assertRaisesRegex(Failure, "existing profile"):
            self.runtime.setup()
        self.assertFalse(self.runtime.target_file.exists())

    def test_inherited_credentials_and_target_are_ignored(self):
        self.existing()
        with patch.dict(os.environ, {"BEEPER_ACCESS_TOKEN": "OTHER_SECRET", "BEEPER_TARGET": "another-target", "BEEPER_CLI_CONFIG_DIR": "/wrong"}):
            data = self.runtime.cli(["messages", "list", "--chat", "chat-1"])
        self.assertEqual(data["tokenUsed"], "SYNTHETIC_SECRET")
        self.assertEqual(data["envTarget"], "grok-bot")
        self.assertEqual(data["config"], str(self.runtime.config))

    def test_status_output_does_not_leak_auth(self):
        self.existing()
        output = io.StringIO()
        with redirect_stdout(output):
            emit(self.runtime.status())
        self.assertNotIn("SYNTHETIC_SECRET", output.getvalue())
        self.assertIn("initializing", output.getvalue())

    def test_target_validation_prevents_credential_forwarding(self):
        self.existing()
        for url in ("https://example.com", "http://127.0.0.1:80@evil.example", "http://127.0.0.1:23374/?remote=x"):
            write_json(self.runtime.target_file, {"type": "server", "baseURL": url})
            with self.assertRaises(Failure):
                self.runtime.env()

    def test_network_login_and_target_overrides_are_out_of_scope(self):
        for args in (["accounts", "add"], ["accounts", "remove", "network"], ["api", "post", "/v1/reset"],
                     ["chats", "list", "--base-url=https://example.com"], ["chats", "list", "-tother"],
                     ["chats", "list", "--target=other"], ["chats", "list", "--target", "other"],
                     ["chats", "list", "-qtother"], ["chats", "list", "-ytother"],
                     ["chats", "list", "-qyt", "other"], ["chats", "list", "--debug"]):
            with self.subTest(args=args), self.assertRaises(Failure):
                self.runtime.command(args)

    def test_update_stops_backs_up_and_preserves_keys(self):
        profile = self.existing()
        original = self.runtime.target_file.read_bytes()
        with patch("install.latest", return_value={"version": "0.6.2"}):
            result = self.runtime.setup(update=True)
        backup = Path(result["backup"])
        with tarfile.open(backup / "config.tar.gz") as archive:
            self.assertEqual(archive.extractfile("profile/keys.fixture").read(), b"synthetic encryption state")
            self.assertNotIn("config/profiles/server/grok-bot/keys.fixture", archive.getnames())
            self.assertEqual(archive.extractfile("config/targets/grok-bot.json").read(), original)
        self.assertEqual((backup / "server-program/beeper-server").read_text(), "old program")
        self.assertEqual((profile / "keys.fixture").read_text(), "synthetic encryption state")
        self.assertEqual(self.runtime.target_file.read_bytes(), original)
        self.assertEqual(read_json(self.runtime.config / "installations.json")["server"]["version"], "4.3.156")
        calls = self.calls()
        self.assertLess(next(i for i,c in enumerate(calls) if c[:2] == ["targets", "stop"]),
                        next(i for i,c in enumerate(calls) if c[:2] == ["update", "--server"] and "--check" not in c))
        self.assertEqual(backup.stat().st_mode & 0o777, 0o700)

    def test_start_cannot_bypass_an_update_or_signin_lock(self):
        self.existing()
        before = self.calls()
        with self.runtime.lock():
            result = self.helper("start")
        self.assertEqual(result.returncode, 1)
        self.assertIn("running", json.loads(result.stdout)["error"])
        self.assertEqual(self.calls(), before)
        self.assertEqual(self.helper("start").returncode, 0)

    def test_stopped_profile_updates_without_stop_and_stop_failure_aborts(self):
        self.existing()
        (self.root / "stopped").touch()
        with patch("install.latest", return_value={"version": "0.6.2"}):
            result = self.runtime.setup(update=True)
        self.assertTrue(Path(result["backup"]).is_dir())
        self.assertFalse(any(c[:2] == ["targets", "stop"] for c in self.calls()))
        (self.root / "fail-stop").touch()
        before = len(self.calls())
        with patch("install.latest", return_value={"version": "0.6.2"}), self.assertRaises(Failure):
            self.runtime.setup(update=True)
        self.assertFalse(any(c == ["update", "--server", "--json"] for c in self.calls()[before:]))

    def test_live_pid_listener_and_stale_pid_checks(self):
        self.existing()
        receiver = HTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
        target = self.runtime.target()
        target.update(port=receiver.server_port, baseURL=f"http://127.0.0.1:{receiver.server_port}")
        write_json(self.runtime.target_file, target)
        try:
            self.assertTrue(Runtime.server_running(self.runtime))
        finally:
            receiver.server_close()
        run_file = self.runtime.config / "run/profiles/grok-bot.json"
        write_json(run_file, {"pid": os.getpid()})
        self.assertTrue(Runtime.server_running(self.runtime))
        with subprocess.Popen([sys.executable, "-c", "pass"]) as child:
            child.wait(timeout=5)
        write_json(run_file, {"pid": child.pid})
        self.assertFalse(Runtime.server_running(self.runtime))
        run_file.unlink()
        self.assertFalse(Runtime.server_running(self.runtime))

    def test_server_must_be_stopped_before_backup(self):
        self.existing()
        with patch.object(self.runtime, "server_running", return_value=True), \
                patch("install.latest", return_value={"version": "0.6.2"}), self.assertRaisesRegex(Failure, "still running"):
            self.runtime.setup(update=True)
        self.assertFalse((self.root / "private-backups").exists())
        self.assertFalse(any(c == ["update", "--server", "--json"] for c in self.calls()))

    def test_external_profile_and_symlinked_root_are_backed_up(self):
        profile = self.existing()
        external = self.root / "external-profile"
        profile.rename(external)
        profile.symlink_to(external, target_is_directory=True)
        target = self.runtime.target()
        for data_dir in (str(external), str(profile)):
            with self.subTest(data_dir=data_dir):
                target["dataDir"] = data_dir
                write_json(self.runtime.target_file, target)
                with patch("install.latest", return_value={"version": "0.6.2"}), \
                        patch("beeper.time.strftime", return_value=str(len(self.calls()))):
                    result = self.runtime.setup(update=True)
                backup = Path(result["backup"])
                with tarfile.open(backup / "config.tar.gz") as archive:
                    self.assertEqual(archive.extractfile("profile/keys.fixture").read(), b"synthetic encryption state")
                layout = read_json(backup / "profile.json")
                self.assertEqual(layout["resolvedDataDir"], str(external))
                self.assertEqual(layout["dataDir"], data_dir)

    def test_linked_profile_subdirectory_stops_update_without_recursing(self):
        profile = self.existing()
        (profile / "loop").symlink_to(profile, target_is_directory=True)
        with patch("install.latest", return_value={"version": "0.6.2"}), self.assertRaisesRegex(Failure, "linked directory"):
            self.runtime.setup(update=True)
        self.assertFalse(any(c == ["update", "--server", "--json"] for c in self.calls()))

    def test_update_failure_restarts_profile_and_withholds_raw_error(self):
        self.existing()
        (self.root / "fail-update").touch()
        with patch("install.latest", return_value={"version": "0.6.2"}):
            with self.assertRaises(Failure) as caught:
                self.runtime.setup(update=True)
        self.assertNotIn("SYNTHETIC_SECRET", str(caught.exception))
        self.assertIn("http_error", str(caught.exception))
        self.assertEqual(self.calls()[-1][:2], ["targets", "start"])

    def test_failed_backup_never_runs_updater(self):
        self.existing()
        with patch("install.latest", return_value={"version": "0.6.2"}), patch("beeper.shutil.copytree", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.runtime.setup(update=True)
        self.assertFalse(any(c[:2] == ["update", "--server"] and "--check" not in c for c in self.calls()))
        self.assertEqual(self.calls()[-1][:2], ["targets", "start"])

    def test_up_to_date_server_is_not_stopped_or_backed_up(self):
        self.existing()
        (self.root / "up-to-date").touch()
        with patch("install.latest", return_value={"version": "0.6.2"}):
            self.runtime.setup(update=True)
        self.assertFalse((self.root / "private-backups").exists())
        self.assertFalse(any(c[:2] == ["targets", "stop"] for c in self.calls()))

    def test_read_only_blocks_setup_and_secret_submission(self):
        self.existing(False)
        with patch.dict(os.environ, {"BEEPER_READONLY": "1"}):
            with self.assertRaises(Failure): self.runtime.setup()
            with self.assertRaises(Failure): make_server(self.runtime, "signin")
            with self.assertRaises(Failure): self.runtime.api("POST", "/v1/app/setup/start", public=True)

    def test_exports_handle_native_non_json_success(self):
        self.existing()
        output = self.root / "messages.json"
        self.assertTrue(self.runtime.cli(["messages", "export", "--chat", "chat-1", "--output", str(output)])["completed"])
        self.assertEqual(output.read_text(), "[]")
        self.assertTrue(self.runtime.command(["export", "--out", str(self.root / "export")])["completed"])

    def test_structured_stderr_failure_is_classified_without_echoing_it(self):
        failure = {"success": False, "error": "The operation timed out. PRIVATE_VALUE", "exitCode": 1, "kind": "bug"}
        result = subprocess.CompletedProcess([], 1, b"", json.dumps(failure).encode())
        with patch.object(self.runtime, "run", return_value=(result, False)):
            with self.assertRaises(Failure) as caught:
                self.runtime.cli(["install", "server"])
        self.assertIn("code timeout", str(caught.exception))
        self.assertNotIn("PRIVATE_VALUE", str(caught.exception))

    def test_unreachable_target_status_keeps_its_diagnostic(self):
        diagnostic = {"reachable": False, "error": "Could not reach target"}
        result = subprocess.CompletedProcess([], 1, json.dumps({"success": True, "data": diagnostic}).encode(), b"")
        with patch.object(self.runtime, "run", return_value=(result, False)):
            self.assertEqual(self.runtime.cli(["targets", "status", "grok-bot"]), diagnostic)

    def test_watch_returns_events_on_deadline_and_reports_connection_failure(self):
        self.existing()
        data = self.runtime.watch(1, "chat-1")
        self.assertFalse(data["streamEndedEarly"])
        self.assertEqual(data["events"][0]["messageID"], "message-1")
        (self.root / "fail-watch").touch()
        with self.assertRaisesRegex(Failure, "connection failed"):
            self.runtime.watch(1)

    def test_verification_requires_explicit_match_of_current_comparison(self):
        self.existing()
        comparison = {"id": "verification-1", "state": "sas", "sas": {"decimals": [1234, 5678, 9012]}}
        path = self.root / "verification.fixture.json"
        write_json(path, comparison)
        self.runtime.verify("show")
        with self.assertRaises(Failure): self.runtime.verify("sas-confirm")
        changed = {**comparison, "id": "verification-2"}
        write_json(path, changed)
        with self.assertRaises(Failure): self.runtime.verify("sas-confirm", matches=True)
        self.runtime.verify("show")
        self.runtime.verify("sas-confirm", matches=True)
        self.assertEqual(self.calls()[-1][:2], ["verify", "sas-confirm"])

    def test_verification_start_resumes_existing_request(self):
        self.existing()
        write_json(self.root / "verification.fixture.json", {"id": "active", "state": "requested"})
        self.assertEqual(self.runtime.verify("start")["id"], "active")
        self.assertFalse(any(c[:2] == ["verify", "start"] for c in self.calls()))

    def test_incoming_verification_accepts_only_current_available_request(self):
        self.existing()
        path = self.root / "verification.fixture.json"
        write_json(path, {"id": "incoming-1", "state": "requested", "availableActions": ["accept", "cancel"]})
        self.assertEqual(self.runtime.verify("start")["id"], "incoming-1")
        result = self.helper("verify", "approve")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.calls()[-1], ["verify", "approve", "--id", "incoming-1", "--json"])
        write_json(path, {"id": "incoming-2", "state": "ready", "availableActions": ["sas.start"]})
        with self.assertRaisesRegex(Failure, "not waiting for acceptance"):
            self.runtime.verify("approve")

    def test_script_entry_preserves_expected_signin_errors(self):
        self.existing()
        result = self.helper("signin")
        self.assertEqual(result.returncode, 1)
        self.assertIn("already signed in", json.loads(result.stdout)["error"])
        target = self.runtime.target()
        target.pop("auth")
        write_json(self.runtime.target_file, target)
        result = self.helper("recovery")
        self.assertEqual(result.returncode, 1)
        self.assertIn("Sign in by email", json.loads(result.stdout)["error"])

    def test_watch_deadline_also_stops_cli_child_process(self):
        self.existing()
        (self.root / "child-watch").touch()
        start = time.monotonic()
        self.runtime.watch(1)
        self.assertLess(time.monotonic() - start, 4)
        pid = int((self.root / "child.pid").read_text())
        stat = Path(f"/proc/{pid}/stat")
        try:
            state = stat.read_text().split()[2]
        except (FileNotFoundError, ProcessLookupError):
            # A killed child can be reaped between opening and reading /proc.
            return
        self.assertEqual(state, "Z")

    def test_program_backup_follows_official_launcher_symlink(self):
        self.existing()
        install_file = self.runtime.config / "installations.json"
        installed = read_json(install_file)
        program = Path(installed["server"]["path"])
        link = self.root / "bin/beeper-server"
        link.symlink_to(program)
        installed["server"]["path"] = str(link)
        write_json(install_file, installed)
        with patch("install.latest", return_value={"version": "0.6.2"}):
            result = self.runtime.setup(update=True)
        self.assertEqual((Path(result["backup"]) / "server-program/beeper-server").read_text(), "old program")

    def test_archive_uses_supported_endpoint_after_resolving_chat(self):
        self.existing()
        with patch.object(self.runtime, "api", return_value={}) as api:
            self.runtime.command(["chats", "archive", "--chat", "Synthetic chat"])
            api.assert_called_once_with("POST", "/v1/chats/%21chat%3Asynthetic/archive", {"archived": True})
        with patch.object(self.runtime, "api") as api:
            with self.assertRaises(Failure):
                self.runtime.command(["chats", "unarchive", "--chat", "chat-1", "--read-only"])
            api.assert_not_called()


class SigninTests(RuntimeFixture):
    def setUp(self):
        super().setUp()
        self.existing(False)

    def server(self, kind="signin"):
        server = make_server(self.runtime, kind)
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(lambda: thread.join(timeout=2))
        self.addCleanup(server.shutdown)
        return server

    def request(self, server, fields=None, origin=True, host=None):
        conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
        self.addCleanup(conn.close)
        headers = {"Host": host or server.address}
        if fields is None:
            conn.request("GET", urlsplit(server.url).path, headers=headers)
        else:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            if origin: headers["Origin"] = "http://" + server.address
            conn.request("POST", urlsplit(server.url).path, urlencode(fields), headers)
        response = conn.getresponse()
        return response.status, response.read().decode(), dict(response.getheaders())

    def fields(self, server, value):
        status, body, _ = self.request(server)
        self.assertEqual(status, 200)
        return {"csrf": re.search(r'name="csrf" value="([^"]+)"', body)[1], "step": server.step, "value": value}

    def test_private_email_flow_saves_token_without_returning_secrets(self):
        server = self.server()
        with patch.object(self.runtime, "api", side_effect=[{"setupRequestID": "req-1"}, {}, {"matrix": {"accessToken": "NEW_SYNTHETIC_TOKEN"}}]) as api:
            fields = self.fields(server, "person@example.test")
            status, body, headers = self.request(server, fields)
            self.assertEqual(status, 200)
            self.assertEqual(server.step, "code")
            self.assertEqual(headers["Cache-Control"], "no-store")
            status, body, _ = self.request(server, self.fields(server, "SECRET_EMAIL_CODE"))
        self.assertIn("You can close this window now", body)
        self.assertNotIn("SECRET_EMAIL_CODE", body)
        self.assertTrue(server.result["signedIn"])
        self.assertNotIn("NEW_SYNTHETIC_TOKEN", json.dumps(server.result))
        self.assertEqual(read_json(self.runtime.target_file)["auth"]["accessToken"], "NEW_SYNTHETIC_TOKEN")
        self.assertEqual(self.runtime.target_file.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.request(server, fields)[0], 403)
        self.assertEqual(api.call_count, 3)

    def test_csrf_origin_host_and_stale_step_are_rejected(self):
        server = self.server()
        fields = self.fields(server, "person@example.test")
        with patch.object(self.runtime, "api") as api:
            self.assertEqual(self.request(server, fields, origin=False)[0], 403)
            self.assertEqual(self.request(server, fields, host="attacker.test")[0], 403)
            self.assertEqual(self.request(server, {**fields, "csrf": "wrong"})[0], 400)
            self.assertEqual(self.request(server, {**fields, "step": "code"})[0], 400)
            server.deadline = time.monotonic() - 1
            self.assertEqual(self.request(server, fields)[0], 403)
            api.assert_not_called()

    def test_registration_is_not_accepted(self):
        server = self.server()
        with patch.object(self.runtime, "api", side_effect=[{"setupRequestID": "req"}, {}, {"registrationRequired": True, "leadToken": "PRIVATE"}]) as api:
            self.request(server, self.fields(server, "missing@example.test"))
            status, body, _ = self.request(server, self.fields(server, "code"))
        self.assertFalse(server.result["signedIn"])
        self.assertTrue(server.result["registrationRequired"])
        self.assertNotIn("auth", read_json(self.runtime.target_file))
        self.assertFalse(any("register" in call.args[1] for call in api.call_args_list))
        self.assertNotIn("PRIVATE", body)

    def test_recovery_stays_private_and_upstream_errors_never_echo_key(self):
        target = self.runtime.target()
        target["auth"] = {"accessToken": "SYNTHETIC_SECRET"}
        write_json(self.runtime.target_file, target)
        server = self.server("recovery")
        with patch.object(self.runtime, "api", side_effect=[Failure("upstream echoed PRIVATE_KEY", code=400), {}]) as api:
            status, body, _ = self.request(server, self.fields(server, "PRIVATE_KEY"))
            self.assertNotIn("PRIVATE_KEY", body)
            self.assertFalse(server.done)
            self.request(server, self.fields(server, "PRIVATE_KEY"))
        self.assertTrue(server.result["recoverySubmitted"])
        self.assertNotIn("PRIVATE_KEY", json.dumps(server.result))
        self.assertEqual(api.call_args.args[1], "/v1/app/setup/verification/recovery-key")

    def test_expired_code_can_be_resent_and_old_form_cannot_replay(self):
        server = self.server()
        responses = [{"setupRequestID": "old-request"}, {}, Failure("private rejection", code=400),
                     {"setupRequestID": "new-request"}, {}, {"matrix": {"accessToken": "SYNTHETIC_NEW"}}]
        with patch.object(self.runtime, "api", side_effect=responses) as api:
            self.request(server, self.fields(server, "person@example.test"))
            old_form = self.fields(server, "old-code")
            _, body, _ = self.request(server, old_form)
            self.assertIn("Send a new code", body)
            self.assertNotIn("start sign-in again", body)
            self.request(server, {**self.fields(server, ""), "action": "resend"})
            self.assertEqual(self.request(server, old_form)[0], 400)
            self.request(server, self.fields(server, "new-code"))
        self.assertTrue(server.result["signedIn"])
        self.assertEqual(api.call_args_list[4].args[2]["email"], "person@example.test")
        self.assertEqual(api.call_args_list[-1].args[2]["setupRequestID"], "new-request")

    def test_email_can_be_corrected_without_replacing_private_job(self):
        server = self.server()
        with patch.object(self.runtime, "api", side_effect=[{"setupRequestID": "first"}, {}, {"setupRequestID": "second"}, {}]) as api:
            self.request(server, self.fields(server, "wrong@example.test"))
            old_form = self.fields(server, "stale-code")
            self.request(server, {**old_form, "action": "restart"})
            self.assertEqual(server.step, "email")
            self.request(server, self.fields(server, "right@example.test"))
            self.assertEqual(self.request(server, old_form)[0], 400)
        self.assertEqual(api.call_args.args[2]["email"], "right@example.test")
        self.assertEqual(server.request_id, "second")

    def test_ambiguous_authentication_stops_instead_of_replaying(self):
        server = self.server()
        with patch.object(self.runtime, "api", side_effect=[{"setupRequestID": "req"}, {}, Failure("PRIVATE_TIMEOUT")]) as api:
            self.request(server, self.fields(server, "person@example.test"))
            fields = self.fields(server, "private-code")
            _, body, _ = self.request(server, fields)
            self.assertEqual(self.request(server, fields)[0], 403)
        self.assertTrue(server.done)
        self.assertIsInstance(server.error, Failure)
        self.assertIn("uncertain", str(server.error))
        self.assertNotIn("PRIVATE_TIMEOUT", body)
        self.assertNotIn("private-code", body)
        self.assertEqual(api.call_count, 3)

    def test_cancelling_real_private_job_releases_lock_immediately(self):
        command = [sys.executable, str(PROJECT / "skills/beeper/scripts/beeper.py"), "signin"]
        # Two consecutive jobs prove cancellation permits an immediate replacement.
        for _ in range(2):
            with subprocess.Popen(command, env={**os.environ, "BEEPER_PLUGIN_HOME": str(self.root)},
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as child:
                try:
                    first = json.loads(child.stdout.readline())
                    url = first["data"]["privateURL"]
                    parsed = urlsplit(url)
                    server = SimpleNamespace(url=url, address=parsed.netloc, server_port=parsed.port, step="email")
                    with self.assertRaises(Failure):
                        with self.runtime.lock():
                            pass
                    fields = {**self.fields(server, ""), "action": "cancel"}
                    with patch.object(self.runtime, "api") as api:
                        self.assertEqual(self.request(server, {**fields, "csrf": "wrong"})[0], 400)
                        self.assertEqual(self.request(server, fields, origin=False)[0], 403)
                        self.assertEqual(self.request(server, fields)[0], 200)
                        api.assert_not_called()
                    stdout, stderr = child.communicate(timeout=5)
                    self.assertEqual(child.returncode, 1)
                    self.assertIn("cancelled", json.loads(stdout)["error"])
                    self.assertEqual(stderr, "")
                    with self.runtime.lock():
                        pass
                finally:
                    if child.poll() is None:
                        child.kill()
                        child.wait(timeout=5)


@unittest.skipUnless(os.environ.get("BEEPER_TEST_CLI"), "Set BEEPER_TEST_CLI to an isolated published CLI")
class PublishedCLITests(RuntimeFixture):
    def setUp(self):
        super().setUp()
        self.existing()
        self.received = []
        received = self.received
        verification = {"id": "incoming-native", "state": "requested", "availableActions": ["accept", "cancel"]}
        self.request_bodies = []
        self.respond = lambda method, path, body: ({"state": "needs-verification", "verification": verification}
                                                  if path == "/v1/app/setup" else [])
        owner = self

        class Receiver(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                received.append((self.command, self.path, self.headers.get("Authorization")))
                length = int(self.headers.get("Content-Length", 0))
                submitted = json.loads(self.rfile.read(length)) if length else None
                if submitted is not None:
                    owner.request_bodies.append((self.command, self.path, submitted))
                body = owner.respond(self.command, self.path, submitted)
                payload = json.dumps(body).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            do_POST = do_GET
            do_PUT = do_GET
            do_DELETE = do_GET

        self.receiver = HTTPServer(("127.0.0.1", 0), Receiver)
        thread = threading.Thread(target=self.receiver.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.receiver.server_close)
        self.addCleanup(lambda: thread.join(timeout=2))
        self.addCleanup(self.receiver.shutdown)
        self.runtime.binary = Path(os.environ["BEEPER_TEST_CLI"]).resolve()
        env = self.runtime.env()
        if os.environ.get("BEEPER_TEST_CLI_CACHE"):
            env["BEEPER_CLI_BINARY_CACHE_DIR"] = os.environ["BEEPER_TEST_CLI_CACHE"]
        environment = patch.object(self.runtime, "env", return_value=env)
        environment.start()
        self.addCleanup(environment.stop)

    def point_primary_at_receiver(self):
        target = self.runtime.target()
        target.update(port=self.receiver.server_port, baseURL=f"http://127.0.0.1:{self.receiver.server_port}")
        write_json(self.runtime.target_file, target)

    def test_target_override_cannot_forward_token_but_normal_read_works(self):
        write_json(self.runtime.config / "targets/other.json", {
            "id": "other", "type": "remote", "baseURL": f"http://127.0.0.1:{self.receiver.server_port}"})
        for flags in (["-qtother"], ["-ytother"], ["-qyt", "other"], ["--target=other"],
                      ["--base-url", f"http://127.0.0.1:{self.receiver.server_port}"]):
            with self.subTest(flags=flags), self.assertRaises(Failure):
                self.runtime.command(["accounts", "list", *flags])
        self.assertEqual(self.received, [])
        self.point_primary_at_receiver()
        self.assertEqual(self.runtime.command(["accounts", "list", "--quiet"]), [])
        self.assertEqual(self.received, [("GET", "/v1/accounts", "Bearer SYNTHETIC_SECRET")])

    def test_incoming_accept_uses_the_published_endpoint_and_explicit_id(self):
        self.point_primary_at_receiver()
        self.runtime.verify("approve")
        self.assertEqual([item[:2] for item in self.received], [
            ("GET", "/v1/app/setup"), ("POST", "/v1/app/setup/verifications/incoming-native/accept")])

    def test_message_option_values_reach_dispatch_verbatim_with_official_cli(self):
        self.point_primary_at_receiver()
        chat = "!self:synthetic"
        current = {}

        def respond(method, path, body):
            if method == "POST" and path.endswith("/messages"):
                current.update(body)
                return {"chatID": chat, "pendingMessageID": "pending"}
            if method == "GET" and "/messages/" in path:
                return {"id": "final", "chatID": chat, "accountID": "network", "isSender": True, "text": current["text"]}
            return {"state": "ready"}

        self.respond = respond
        for body in ("--reply-to=literal", "--help", "--read-only", "--target=other", "-qtother", "hello\n$HOME `not-a-command`"):
            with self.subTest(body=body):
                before = len(self.request_bodies)
                result = self.runtime.command(["send", "text", "--to", chat, "--message", body])
                self.assertEqual(len(self.request_bodies), before + 1)
                self.assertEqual(self.request_bodies[-1][2]["text"], body)
                self.assertEqual(result["writeOutcome"]["state"], "confirmed")
                self.assertEqual(result["writeOutcome"]["bridgeSendStatus"], "unavailable")

    def test_edit_with_official_cli_observes_stale_then_updated_body(self):
        self.point_primary_at_receiver()
        chat = "!self:synthetic"
        reads = []
        row = {"id": "final", "chatID": chat, "accountID": "network", "isSender": True}

        def respond(method, path, body):
            if method == "PUT":
                return {**row, "text": "edited"}
            if method == "GET" and "/messages/" in path:
                reads.append(path)
                return {**row, "text": "old" if len(reads) == 1 else "edited"}
            return {"state": "ready"}

        self.respond = respond
        with patch("outcomes.OBSERVATION_DELAYS", (0, 0, 0)):
            result = self.runtime.command(["messages", "edit", "--chat", chat, "--id", "final", "--message", "edited"])
        self.assertEqual(result["writeOutcome"]["state"], "confirmed")
        self.assertEqual(len(reads), 2)
        self.assertEqual(len([r for r in self.request_bodies if r[0] == "PUT"]), 1)

    def test_react_and_unreact_with_distinct_account_and_chat_self_ids(self):
        self.point_primary_at_receiver()
        chat = "!self:synthetic"
        reactions = []

        def respond(method, path, body):
            if method == "POST" and path.endswith("/reactions"):
                reactions.append({"id": "room-self", "participantID": "room-self", "reactionKey": body["reactionKey"]})
                return {"chatID": chat, "messageID": "final", "reactionKey": body["reactionKey"], "success": True, "transactionID": "synthetic"}
            if method == "DELETE" and "/reactions/" in path:
                reactions.clear()
                return {"chatID": chat, "messageID": "final", "reactionKey": "👍", "success": True}
            if path == "/v1/accounts":
                return [{"accountID": "network", "user": {"id": "account-self", "isSelf": True}}]
            if method == "GET" and "/messages/" in path:
                return {"id": "final", "chatID": chat, "accountID": "network", "reactions": reactions}
            return {"id": chat, "accountID": "network", "participants": {
                "items": [{"id": "room-self", "isSelf": True}], "hasMore": False, "total": 1}}

        self.respond = respond
        for operation in ("react", "unreact"):
            result = self.runtime.command(["send", operation, "--to", chat, "--id", "final", "--reaction", "👍"])
            self.assertEqual(result["writeOutcome"]["state"], "confirmed")
            self.assertEqual(result["writeOutcome"]["checks"]["chatSelfIdentityMatches"], operation == "react")
            self.assertFalse(result["writeOutcome"]["checks"]["accountIdentityMatches"])
        self.assertEqual([method for method, _, _ in self.received if method != "GET"], ["POST", "DELETE"])

    def test_full_export_readonly_scope_changes_and_explicit_rebuild(self):
        self.point_primary_at_receiver()
        chat = "!self:synthetic"
        detail = {"id": chat, "accountID": "network", "title": "Synthetic", "type": "single", "participants": {"items": []}}
        def respond(method, path, body):
            route = urlsplit(path).path
            if route == "/v1/accounts":
                return [{"accountID": "network", "user": {"id": "self"}}]
            if route == "/v1/chats":
                return {"items": [detail], "hasMore": False}
            if route.endswith("/messages"):
                return {"items": [{"id": str(i), "chatID": chat, "accountID": "network", "isSender": True,
                                   "text": "synthetic", "sortKey": str(i), "timestamp": "2026-10-04T10:00:00Z"}
                                  for i in range(6, 0, -1)], "hasMore": False}
            return detail
        self.respond = respond
        output = self.root / "snapshot"
        args = ["export", "--out", str(output), "--no-attachments", "--quiet"]
        with patch.dict(os.environ, {"BEEPER_READONLY": "1"}), self.assertRaises(Failure):
            self.runtime.command(args)
        with self.assertRaises(Failure):
            self.runtime.command([*args, "--read-only"])
        self.assertEqual(self.received, [])
        self.assertFalse(output.exists())
        limited = self.runtime.command([*args, "--limit-messages", "2"])
        self.assertEqual(limited["messageCount"], 2)
        self.assertTrue(limited["coverage"]["limitReached"])
        before = len(self.received)
        with self.assertRaises(Failure) as error:
            self.runtime.command(args)
        self.assertEqual(error.exception.code, "export_scope_changed")
        self.assertEqual(len(self.received), before)
        full = self.runtime.command([*args, "--force"])
        self.assertEqual(full["messageCount"], 6)
        self.assertFalse(full["coverage"]["limitsApplied"])
        files = list((output / "chats").glob("*/messages.json"))
        self.assertEqual(len(files), 1)
        self.assertEqual(len(json.loads(files[0].read_text())), 6)


class Response(io.BytesIO):
    def __init__(self, body=b"", url=""):
        super().__init__(body)
        self.url = url

    def geturl(self):
        return self.url


class ReleaseLookupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix=".test-", dir=PROJECT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manifest = {"version": "0.6.2", "artifacts": [{
            "file": "beeper-cli-0.6.2-linux-x64.tar.gz", "platform": "linux-x64", "sha256": "a" * 64}]}
        self.cache = self.root / "cache/cli-release-linux-x64.json"
        for name, value in (("machine", "x86_64"), ("system", "Linux")):
            mock = patch("install.platform." + name, return_value=value)
            mock.start()
            self.addCleanup(mock.stop)

    def response(self, url):
        if url == RELEASES + "/latest":
            return Response(url=RELEASES + "/tag/v0.6.2")
        if url == RELEASES + "/download/v0.6.2/binaries.json":
            return Response(json.dumps(self.manifest).encode())
        raise AssertionError("Unexpected URL: " + url)

    def test_release_lookup_works_with_api_blocked_and_never_sends_token(self):
        calls = []

        def open_request(req, timeout):
            calls.append(req.full_url)
            self.assertIsNone(req.get_header("Authorization"))
            if req.full_url.startswith("https://api.github.com/"):
                raise HTTPError(req.full_url, 403, "rate limit", {"X-RateLimit-Remaining": "0"}, None)
            return self.response(req.full_url)

        with patch.dict(os.environ, {"GITHUB_TOKEN": "PRIVATE_TOKEN", "GH_TOKEN": "OTHER_PRIVATE_TOKEN"}), patch("install.urllib.request.urlopen", side_effect=open_request):
            release = latest(self.root)
        self.assertEqual(release["version"], "0.6.2")
        self.assertEqual(release["source"], "release-manifest")
        self.assertEqual(release["sha256"], "a" * 64)
        self.assertFalse(release["cached"])
        self.assertEqual(len(calls), 2)
        self.assertNotIn("PRIVATE_TOKEN", json.dumps(release) + self.cache.read_text())

    def test_warm_cache_needs_no_network(self):
        with patch("install.request", side_effect=self.response):
            original = latest(self.root)
        with patch("install.request", side_effect=AssertionError("Unexpected network request")):
            cached = latest(self.root)
        self.assertTrue(cached["cached"])
        self.assertEqual(original["sha256"], cached["sha256"])
        self.assertEqual(self.cache.stat().st_mode & 0o777, 0o600)

    def test_arm64_selects_its_own_archive_and_cache(self):
        self.manifest["artifacts"] = [{"file": "beeper-cli-0.6.2-linux-arm64.tar.gz",
                                       "platform": "linux-arm64", "sha256": "b" * 64}]
        with patch("install.platform.machine", return_value="aarch64"), patch("install.request", side_effect=self.response):
            result = latest(self.root)
        self.assertEqual(result["platform"], "linux-arm64")
        self.assertTrue(result["url"].endswith("-linux-arm64.tar.gz"))
        self.assertTrue((self.root / "cache/cli-release-linux-arm64.json").exists())
        self.assertFalse(self.cache.exists())

    def test_expired_future_and_tampered_caches_are_not_used(self):
        with patch("install.request", side_effect=self.response):
            original = latest(self.root)
        variants = [{**original, "checkedAt": time.time() - 901},
                    {**original, "checkedAt": time.time() + 3600},
                    {**original, "url": "https://attacker.example/binary"},
                    {**original, "platform": "linux-arm64"}]
        for data in variants:
            with self.subTest(data=data):
                self.cache.write_text(json.dumps(data))
                with patch("install.request", side_effect=self.response) as download:
                    result = latest(self.root)
                self.assertFalse(result["cached"])
                self.assertEqual(download.call_count, 2)

    def test_manifest_must_have_matching_version_platform_and_one_digest(self):
        original = json.loads(json.dumps(self.manifest))
        invalid = [
            {**original, "version": "0.6.1"},
            {**original, "artifacts": []},
            {**original, "artifacts": original["artifacts"] * 2},
            {**original, "artifacts": [{**original["artifacts"][0], "sha256": "bad"}]},
            {**original, "artifacts": [{**original["artifacts"][0], "sha256": None}]},
            {**original, "artifacts": [{**original["artifacts"][0], "platform": "linux-arm64"}]},
            {**original, "artifacts": [{**original["artifacts"][0], "file": "../../beeper"}]},
        ]
        for manifest in invalid:
            with self.subTest(manifest=manifest), patch("install.request", side_effect=self.response):
                self.manifest = manifest
                with self.assertRaises(InstallError) as caught:
                    latest(self.root)
                self.assertEqual(caught.exception.info["code"], "invalid_release_metadata")
                self.assertFalse(self.cache.exists())
                self.assertFalse((self.root / "bin/beeper").exists())

    def test_unexpected_latest_redirect_is_rejected_before_manifest_download(self):
        for url in (RELEASES + "/tag/v1.2.3-beta", RELEASES + "/tag/v0.6.2?other=1", "https://attacker.example/tag/v0.6.2"):
            with self.subTest(url=url), patch("install.request", return_value=Response(url=url)) as download:
                with self.assertRaises(InstallError): latest(self.root)
                self.assertEqual(download.call_count, 1)

    def test_http_rate_limit_has_structured_reset_and_no_raw_response(self):
        headers = {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1801132500", "Retry-After": "60"}
        for status in (403, 429):
            error = HTTPError(RELEASES + "/latest", status, "PRIVATE_DIAGNOSTIC", headers, io.BytesIO(b"PRIVATE_BODY"))
            with self.subTest(status=status), patch("install.urllib.request.urlopen", side_effect=error):
                with self.assertRaises(InstallError) as caught: latest(self.root)
                data = caught.exception.info
                self.assertEqual(data["code"], "github_rate_limited")
                self.assertEqual(data["retryAfterSeconds"], 60)
                self.assertTrue(data["resetAt"].endswith("+00:00"))
                self.assertNotIn("PRIVATE", json.dumps(data))

    def test_plain_403_is_not_mislabeled_as_a_rate_limit(self):
        error = HTTPError(RELEASES + "/latest", 403, "Forbidden", {}, None)
        with patch("install.urllib.request.urlopen", side_effect=error):
            with self.assertRaises(InstallError) as caught: latest(self.root)
        self.assertEqual(caught.exception.info["code"], "github_http_error")
        self.assertEqual(caught.exception.info["httpStatus"], 403)


class InstallerTests(unittest.TestCase):
    def bundle(self, symlink=False):
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode="w:gz") as archive:
            entry = tarfile.TarInfo("../beeper")
            if symlink:
                entry.type, entry.linkname = tarfile.SYMTYPE, "/etc/passwd"
                archive.addfile(entry)
            else:
                entry.size = len(b"synthetic binary")
                archive.addfile(entry, io.BytesIO(b"synthetic binary"))
        return data.getvalue()

    def test_checksum_failure_preserves_installed_cli(self):
        with tempfile.TemporaryDirectory(prefix=".test-", dir=PROJECT) as temp:
            root = Path(temp)
            (root / "bin").mkdir()
            (root / "bin/beeper").write_bytes(b"old")
            with patch("install.request", return_value=io.BytesIO(self.bundle())):
                with self.assertRaisesRegex(RuntimeError, "checksum"):
                    install_cli(root, {"version": "1.2.3", "url": "synthetic", "sha256": "0" * 64})
            self.assertEqual((root / "bin/beeper").read_bytes(), b"old")

    def test_public_manifest_to_verified_install_without_api(self):
        content = self.bundle()
        name = "beeper-cli-0.6.2-linux-x64.tar.gz"
        manifest = {"version": "0.6.2", "artifacts": [{"file": name, "platform": "linux-x64",
                                                       "sha256": hashlib.sha256(content).hexdigest()}]}
        visited = []

        def download(url):
            visited.append(url)
            if url == RELEASES + "/latest": return Response(url=RELEASES + "/tag/v0.6.2")
            if url == RELEASES + "/download/v0.6.2/binaries.json": return Response(json.dumps(manifest).encode())
            if url == RELEASES + "/download/v0.6.2/" + name: return Response(content)
            raise AssertionError("Unexpected API or download URL")

        with tempfile.TemporaryDirectory(prefix=".test-", dir=PROJECT) as temp, patch("install.request", side_effect=download), patch("install.platform.machine", return_value="x86_64"), patch("install.platform.system", return_value="Linux"):
            root = Path(temp)
            release = latest(root)
            install_cli(root, release)
            self.assertEqual((root / "bin/beeper").read_bytes(), b"synthetic binary")
            self.assertEqual(len(visited), 3)

    def test_only_binary_bytes_are_extracted_and_old_cli_is_retained(self):
        content = self.bundle()
        with tempfile.TemporaryDirectory(prefix=".test-", dir=PROJECT) as temp:
            root = Path(temp)
            (root / "bin").mkdir()
            (root / "bin/beeper").write_bytes(b"old")
            with patch("install.request", return_value=io.BytesIO(content)):
                install_cli(root, {"version": "1.2.3", "url": "synthetic", "sha256": hashlib.sha256(content).hexdigest()})
            self.assertEqual((root / "bin/beeper").read_bytes(), b"synthetic binary")
            self.assertEqual((root / "bin/beeper.previous").read_bytes(), b"old")
            self.assertFalse((root / "beeper").exists())
            self.assertEqual((root / "bin/beeper").stat().st_mode & 0o777, 0o700)

    def test_symlink_cannot_be_installed_as_binary(self):
        content = self.bundle(symlink=True)
        with tempfile.TemporaryDirectory(prefix=".test-", dir=PROJECT) as temp, patch("install.request", return_value=io.BytesIO(content)):
            with self.assertRaisesRegex(RuntimeError, "layout"):
                install_cli(Path(temp), {"version": "1.2.3", "url": "synthetic", "sha256": hashlib.sha256(content).hexdigest()})


if __name__ == "__main__":
    unittest.main()
