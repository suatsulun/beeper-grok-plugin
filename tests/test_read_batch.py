import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/beeper/scripts"
sys.path.insert(0, str(SCRIPTS))
from beeper import Failure, Runtime, write_json
from read_batch import validate


class ReadBatchTests(unittest.TestCase):
    def setUp(self):
        cache = Path.home() / ".cache/beeper-plugin-tests"
        cache.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=cache)
        self.root = Path(self.temp.name)
        self.runtime = Runtime(self.root)
        write_json(self.runtime.target_file, {"id": "grok-bot", "type": "server", "baseURL": "http://127.0.0.1:1",
                                            "auth": {"accessToken": "synthetic-secret"}})
        self.runtime.binary.parent.mkdir(parents=True)
        self.runtime.binary.write_text('#!' + sys.executable + '\n' + '''
import json, os, sys
assert sys.argv[1:] == ['rpc']
assert os.environ['BEEPER_READONLY'] == '1'
assert os.environ['BEEPER_ACCESS_TOKEN'] == 'synthetic-secret'
for line in sys.stdin:
    request = json.loads(line)
    assert request['args'][-4:] == ['--target', 'grok-bot', '--read-only', '--json']
    fail = request['id'] == 'failure'
    output = {'success': not fail, 'data': [{'id': '1'}], 'error': 'synthetic-secret' if fail else None}
    print(json.dumps({'id': request['id'], 'ok': not fail, 'code': 2 if fail else 0, 'signal': None,
                      'stdout': '' if fail else json.dumps(output), 'stderr': json.dumps(output) if fail else ''}))
''')
        self.runtime.binary.chmod(0o700)

    def tearDown(self):
        self.temp.cleanup()

    def test_batch_runs_one_rpc_with_isolated_target_and_individual_errors(self):
        result = self.runtime.cli_batch([
            {"id": "good", "args": ["messages", "list", "--chat", "!synthetic:local", "--limit", "1"]},
            {"id": "failure", "args": ["chats", "list"]},
            {"id": "after", "args": ["version"]},
        ])
        self.assertFalse(result["allSucceeded"])
        self.assertEqual([row["success"] for row in result["results"]], [True, False, True])
        self.assertNotIn("synthetic-secret", json.dumps(result))

    def test_rejects_entire_batch_before_process_start(self):
        for invalid in [
            [{"args": ["send", "text", "--message", "no"]}],
            [{"args": ["chats", "list", "--base-url=http://example.org"]}],
            [{"args": ["chats", "list", "-tother"]}],
            [{"args": ["chats", "list", "--"]}],
            [{"id": "x", "args": ["version"]}, {"id": "x", "args": ["version"]}],
            [{"args": ["version", 1]}], [{"id": True, "args": ["version"]}],
            [{"args": ["version"], "env": {}}], [], [{}], {}, [{"args": ["version"]}] * 33,
        ]:
            with self.subTest(invalid=invalid), patch("read_batch.subprocess.Popen") as spawn:
                with self.assertRaises(Failure):
                    self.runtime.cli_batch(invalid)
                spawn.assert_not_called()

    def test_cli_entrypoint_accepts_stdin_batch(self):
        result = subprocess.run([sys.executable, str(SCRIPTS / "beeper.py"), "batch"],
                                input=json.dumps([{"args": ["version"]}]), text=True, capture_output=True,
                                env=dict(os.environ, BEEPER_PLUGIN_HOME=str(self.root)), timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertTrue(json.loads(result.stdout)["data"]["allSucceeded"])

    def test_cli_ids_version_and_stderr_errors(self):
        decode = self.runtime.cli_result
        self.assertEqual(decode(["--ids"], subprocess.CompletedProcess([], 0, "1\n2\n", "")), {"ids": ["1", "2"]})
        self.assertEqual(decode(["--ids"], subprocess.CompletedProcess([], 0, "1115\n", "")), {"ids": ["1115"]})
        self.assertEqual(decode(["--ids"], subprocess.CompletedProcess([], 0, "", "")), {"ids": []})
        self.assertEqual(decode(["--version"], subprocess.CompletedProcess([], 0, "0.6.2\n", "")), {"version": "0.6.2"})
        self.assertEqual(decode(["-h"], subprocess.CompletedProcess([], 0, "help\n", "")), {"help": "help\n"})
        with self.assertRaises(Failure) as caught:
            decode([], subprocess.CompletedProcess([], 2, "", '{"success":false,"error":"synthetic-secret"}'))
        self.assertNotIn("synthetic-secret", str(caught.exception))
        self.assertEqual(caught.exception.code, "cli_error")
        with self.assertRaises(Failure):
            decode([], subprocess.CompletedProcess([], 0, "[]", ""))

    def test_incomplete_rpc_is_not_retried(self):
        self.runtime.binary.write_text('#!' + sys.executable + '\nprint("{}")\n')
        with self.assertRaises(Failure) as caught:
            self.runtime.cli_batch([{"args": ["version"]}])
        self.assertEqual(caught.exception.code, "cli_error")

    def test_timeout_stops_rpc_group(self):
        self.runtime.binary.write_text('#!' + sys.executable + '\nimport time\ntime.sleep(10)\n')
        with self.assertRaises(Failure) as caught:
            self.runtime.cli_batch([{"args": ["version"]}], timeout=0.1)
        self.assertEqual(caught.exception.code, "timeout")

    def test_readonly_on_is_enforced(self):
        with patch.dict(os.environ, BEEPER_READONLY="on"), self.assertRaises(Failure):
            self.runtime.writable()

    def test_bootstrap_preserves_a_custom_cli_without_claiming_the_pinned_version(self):
        from install import install_tools
        qr = self.root / "lib/qrcode/__init__.py"
        qr.parent.mkdir(parents=True)
        qr.touch()
        before = self.runtime.binary.read_bytes()
        with patch("install.download", side_effect=AssertionError("No downloads for existing tools")):
            result = install_tools(self.root)
        self.assertIsNone(result["cliVersion"])
        self.assertTrue(result["cliPreserved"])
        self.assertEqual(self.runtime.binary.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
