"""Prepare the pinned official CLI for synthetic integration tests, never a Server.

Run under the host's heavy-job lock. --root must be a private disk-backed test
directory, outside the working Beeper profile. No dependencies are installed.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/beeper/scripts"))
from install import install_cli

VERSION = "0.6.2"
ARCHIVE_SHA256 = "a881e1d2bc91e31218b251716644ec5f8d161d5ccb30e7eab66cf2ba6410511d"
BINARY_SHA256 = "723cc3a6c556fa21b6ba11db8377d6a29776aca1660da48f0072883d6452ae3d"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    root = parser.parse_args().root.expanduser().resolve()
    if root.is_relative_to(Path("/tmp")) or (root / "config/targets").exists():
        parser.error("Use a disk-backed isolated directory with no existing targets.")
    if os.uname().sysname != "Linux" or os.uname().machine != "x86_64":
        parser.error("This pinned integration fixture is Linux x64 only.")
    os.umask(0o077)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    binary = root / "bin/beeper"
    if not binary.exists() or hashlib.sha256(binary.read_bytes()).hexdigest() != BINARY_SHA256:
        install_cli(root, {"version": VERSION, "sha256": ARCHIVE_SHA256,
                          "url": f"https://github.com/beeper/cli/releases/download/v{VERSION}/beeper-cli-{VERSION}-linux-x64.tar.gz"})
    if hashlib.sha256(binary.read_bytes()).hexdigest() != BINARY_SHA256:
        raise RuntimeError("Published CLI binary checksum mismatch.")
    env = {k: v for k, v in os.environ.items() if not k.startswith("BEEPER_")}
    env.update(BEEPER_CLI_CONFIG_DIR=str(root / "config"), BEEPER_CLI_BINARY_CACHE_DIR=str(root / "cache"),
               XDG_CACHE_HOME=str(root / "cache"), TMPDIR=str(root))
    with (root / "bootstrap.log").open("wb") as log, subprocess.Popen(
            [str(binary), "version", "--json"], env=env, stdout=subprocess.PIPE,
            stderr=log, start_new_session=True) as process:
        try:
            output, _ = process.communicate(timeout=120)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            raise RuntimeError("CLI preparation timed out; its process group was stopped.") from None
    if process.returncode or json.loads(output).get("data", {}).get("version") != VERSION:
        raise RuntimeError("Official CLI did not report the pinned version; inspect the isolated bootstrap log.")
    print(json.dumps({"version": VERSION, "binary": str(binary), "cache": str(root / "cache"),
                      "binarySha256": BINARY_SHA256}))


if __name__ == "__main__":
    main()
