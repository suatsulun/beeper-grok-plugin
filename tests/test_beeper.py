"""Behavior tests with synthetic data; no Beeper account or network access."""
from contextlib import redirect_stdout
import hashlib
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
import unittest
from unittest.mock import patch
from urllib.parse import urlencode, urlsplit

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "skills/beeper/scripts"))
from beeper import Failure, Runtime, emit, read_json, write_json
from install import install_cli
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
 save(target_file,{'type':'server','managed':True,'serverEnv':'production','baseURL':'http://127.0.0.1:'+args[args.index('--port')+1]})
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
elif args[0]=='export': print('Exported synthetic data');sys.exit(0)
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


class RuntimeTests(RuntimeFixture):
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
            data = self.runtime.command(["messages", "list", "--chat", "chat-1"])
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
                     ["chats", "list", "--debug"]):
            with self.subTest(args=args), self.assertRaises(Failure):
                self.runtime.command(args)

    def test_update_stops_backs_up_and_preserves_keys(self):
        profile = self.existing()
        original = self.runtime.target_file.read_bytes()
        with patch("install.latest", return_value={"version": "0.6.2"}):
            result = self.runtime.setup(update=True)
        backup = Path(result["backup"])
        with tarfile.open(backup / "config.tar.gz") as archive:
            self.assertEqual(archive.extractfile("config/profiles/server/grok-bot/keys.fixture").read(), b"synthetic encryption state")
            self.assertEqual(archive.extractfile("config/targets/grok-bot.json").read(), original)
        self.assertEqual((backup / "server-program/beeper-server").read_text(), "old program")
        self.assertEqual((profile / "keys.fixture").read_text(), "synthetic encryption state")
        self.assertEqual(self.runtime.target_file.read_bytes(), original)
        self.assertEqual(read_json(self.runtime.config / "installations.json")["server"]["version"], "4.3.156")
        calls = self.calls()
        self.assertLess(next(i for i,c in enumerate(calls) if c[:2] == ["targets", "stop"]),
                        next(i for i,c in enumerate(calls) if c[:2] == ["update", "--server"] and "--check" not in c))
        self.assertEqual(backup.stat().st_mode & 0o777, 0o700)

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
        self.assertTrue(self.runtime.command(["messages", "export", "--chat", "chat-1", "--output", str(output)])["completed"])
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

    def test_watch_deadline_also_stops_cli_child_process(self):
        self.existing()
        (self.root / "child-watch").touch()
        start = time.monotonic()
        self.runtime.watch(1)
        self.assertLess(time.monotonic() - start, 4)
        pid = int((self.root / "child.pid").read_text())
        stat = Path(f"/proc/{pid}/stat")
        if stat.exists():
            self.assertEqual(stat.read_text().split()[2], "Z")

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
        with patch.object(self.runtime, "api", side_effect=[Failure("upstream echoed PRIVATE_KEY"), {}]) as api:
            status, body, _ = self.request(server, self.fields(server, "PRIVATE_KEY"))
            self.assertNotIn("PRIVATE_KEY", body)
            self.assertFalse(server.done)
            self.request(server, self.fields(server, "PRIVATE_KEY"))
        self.assertTrue(server.result["recoverySubmitted"])
        self.assertNotIn("PRIVATE_KEY", json.dumps(server.result))
        self.assertEqual(api.call_args.args[1], "/v1/app/setup/verification/recovery-key")


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
