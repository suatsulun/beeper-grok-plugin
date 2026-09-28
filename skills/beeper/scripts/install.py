"""Install the official standalone CLI; Python's standard library is enough."""
import hashlib
import json
import platform
import re
import shutil
import tarfile
import tempfile
import time
from datetime import datetime, timezone
import urllib.error
import urllib.request
from pathlib import Path

RELEASES = "https://github.com/beeper/cli/releases"
CACHE_SECONDS = 15 * 60
MAX_DOWNLOAD = 250 * 1024 * 1024


class InstallError(RuntimeError):
    def __init__(self, message, code, **details):
        super().__init__(message)
        self.info = {"code": code, "message": message, **details}


def request(url):
    # Public release downloads need no API call or GitHub credential.
    try:
        return urllib.request.urlopen(urllib.request.Request(
            url, headers={"User-Agent": "beeper-grok-plugin/0.7.2"}), timeout=120)
    except urllib.error.HTTPError as error:
        status, headers = error.code, error.headers
        error.close()
        details = {"httpStatus": status}
        limited = status == 429 or (status == 403 and (
            headers.get("X-RateLimit-Remaining") == "0" or headers.get("Retry-After")))
        if limited:
            try:
                reset = int(headers.get("X-RateLimit-Reset", ""))
                details["resetAt"] = datetime.fromtimestamp(reset, timezone.utc).isoformat()
            except (ValueError, OverflowError, OSError):
                pass
            try:
                details["retryAfterSeconds"] = max(0, int(headers.get("Retry-After", "")))
            except ValueError:
                pass
            hint = " Retry after " + details["resetAt"] + "." if "resetAt" in details else ""
            raise InstallError("GitHub is rate-limiting this download." + hint + " Do not retry repeatedly.",
                               "github_rate_limited", **details) from None
        raise InstallError(f"GitHub release download returned HTTP {status}. This alone does not establish a rate limit.",
                           "github_http_error", **details) from None
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        raise InstallError("GitHub release download is unavailable or timed out.", "github_unreachable") from None


def valid_release(data, arch):
    if not isinstance(data, dict):
        return False
    version = data.get("version")
    if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", version):
        return False
    name = f"beeper-cli-{version}-linux-{arch}.tar.gz"
    return (data.get("url") == f"{RELEASES}/download/v{version}/{name}"
            and isinstance(data.get("sha256"), str) and re.fullmatch(r"[0-9a-f]{64}", data["sha256"])
            and data.get("platform") == f"linux-{arch}" and data.get("source") == "release-manifest")


def latest(root=None):
    arch = {"x86_64": "x64", "aarch64": "arm64"}.get(platform.machine())
    if platform.system() != "Linux" or not arch:
        raise InstallError("Run setup on Grok's Linux cloud computer (x64 or arm64).", "unsupported_platform")
    cache = Path(root) / "cache" / f"cli-release-linux-{arch}.json" if root is not None else None
    if cache and cache.exists():
        try:
            data = json.loads(cache.read_text())
            age = time.time() - float(data["checkedAt"])
            if 0 <= age < CACHE_SECONDS and valid_release(data, arch):
                return {**data, "cached": True}
        except (OSError, ValueError, TypeError, KeyError):
            pass
    # Resolve GitHub's stable-release redirect, then use that immutable tag for
    # both the manifest and archive. Never scrape a page or guess a checksum.
    with request(RELEASES + "/latest") as response:
        match = re.fullmatch(re.escape(RELEASES) + r"/tag/v(\d+\.\d+\.\d+)", response.geturl())
    if not match:
        raise InstallError("GitHub did not resolve to an official stable Beeper CLI release.", "invalid_release_metadata")
    version = match[1]
    name = f"beeper-cli-{version}-linux-{arch}.tar.gz"
    with request(f"{RELEASES}/download/v{version}/binaries.json") as response:
        raw = response.read(1024 * 1024 + 1)
    try:
        manifest = json.loads(raw) if len(raw) <= 1024 * 1024 else None
        if not isinstance(manifest, dict) or manifest.get("version") != version:
            raise ValueError()
        artifacts = manifest.get("artifacts")
        if not isinstance(artifacts, list):
            raise ValueError()
        matches = [a for a in artifacts if isinstance(a, dict) and a.get("file") == name]
        if len(matches) != 1:
            raise ValueError()
        asset = matches[0]
        data = {"version": version, "url": f"{RELEASES}/download/v{version}/{name}",
                "sha256": asset.get("sha256"), "platform": asset.get("platform"),
                "source": "release-manifest", "checkedAt": int(time.time())}
        if not valid_release(data, arch):
            raise ValueError()
    except (ValueError, TypeError):
        raise InstallError("The official release manifest has no unique matching archive with a valid SHA-256. Nothing was installed.",
                           "invalid_release_metadata") from None
    if cache:
        cache.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with tempfile.NamedTemporaryFile(mode="w", dir=cache.parent, delete=False) as stream:
            json.dump(data, stream)
            temporary = Path(stream.name)
        temporary.replace(cache)
    return {**data, "cached": False}


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
            raise InstallError("CLI checksum mismatch; the installed CLI was left unchanged.", "checksum_mismatch")
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
