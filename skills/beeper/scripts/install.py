"""Install the official standalone CLI; Python's standard library is enough."""
import hashlib
import json
import platform
import re
import shutil
import tarfile
import tempfile
import urllib.request
from pathlib import Path

RELEASE = "https://api.github.com/repos/beeper/cli/releases/latest"
MAX_DOWNLOAD = 250 * 1024 * 1024


def request(url):
    return urllib.request.urlopen(urllib.request.Request(
        url, headers={"User-Agent": "beeper-grok-plugin/0.7.0"}), timeout=120)


def latest():
    arch = {"x86_64": "x64", "aarch64": "arm64"}.get(platform.machine())
    if platform.system() != "Linux" or not arch:
        raise RuntimeError("Run setup on Grok's Linux cloud computer (x64 or arm64).")
    with request(RELEASE) as response:
        release = json.load(response)
    version = release["tag_name"].removeprefix("v")
    if not re.fullmatch(r"\d+\.\d+\.\d+", version) or release.get("prerelease"):
        raise RuntimeError("The official CLI release is not a stable version.")
    name = f"beeper-cli-{version}-linux-{arch}.tar.gz"
    asset = next(a for a in release["assets"] if a["name"] == name)
    digest = asset.get("digest", "")
    url = f"https://github.com/beeper/cli/releases/download/v{version}/{name}"
    if asset["browser_download_url"] != url or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise RuntimeError("The official CLI asset has no verifiable SHA-256 digest.")
    return {"version": version, "url": url, "sha256": digest[7:]}


def install_cli(root, release):
    binary = root / "bin/beeper"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    # A disk-backed temporary directory keeps both large downloads and extraction
    # out of the host's shared RAM-backed /tmp. Never extract arbitrary tar paths.
    with tempfile.TemporaryDirectory(prefix="install-", dir=root) as temporary:
        archive = Path(temporary) / "cli.tar.gz"
        digest = hashlib.sha256()
        size = 0
        with request(release["url"]) as response, archive.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_DOWNLOAD:
                    raise RuntimeError("CLI download exceeded its size limit.")
                digest.update(chunk)
                output.write(chunk)
        if digest.hexdigest() != release["sha256"]:
            raise RuntimeError("CLI checksum mismatch; the installed CLI was left unchanged.")
        candidate = Path(temporary) / "beeper"
        with tarfile.open(archive) as bundle:
            members = [m for m in bundle.getmembers() if m.isfile()
                       and Path(m.name).name in ("beeper", "beeper-linux-x64", "beeper-linux-arm64")]
            if len(members) != 1 or not 0 < members[0].size <= MAX_DOWNLOAD:
                raise RuntimeError("Unexpected CLI archive layout.")
            with bundle.extractfile(members[0]) as source, candidate.open("wb") as output:
                shutil.copyfileobj(source, output)
        candidate.chmod(0o700)
        binary.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if binary.exists():
            shutil.copy2(binary, binary.with_name("beeper.previous"))
        candidate.replace(binary)
    return release["version"]
