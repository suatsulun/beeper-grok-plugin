"""Install pinned, checksum-verified tools into the plugin's private data directory."""
import hashlib
import io
import platform
import tarfile
import urllib.request
import zipfile

CLI_VERSION = "0.6.2"
CLI_SHA256 = {
    "x86_64": "a881e1d2bc91e31218b251716644ec5f8d161d5ccb30e7eab66cf2ba6410511d",
    "aarch64": "2bd37043a4ed863621edc59e28aaa652e8193e55abca0e9477f5aeae1c65d629",
}
QR_URL = "https://files.pythonhosted.org/packages/dd/b8/d2d6d731733f51684bbf76bf34dab3b70a9148e8f2cef2bb544fccec681a/qrcode-8.2-py3-none-any.whl"
QR_SHA256 = "16e64e0716c14960108e85d853062c9e8bba5ca8252c0b4d0231b9df4060ff4f"


def download(url, checksum):
    request = urllib.request.Request(url, headers={"User-Agent": "beeper-grok-plugin/0.6.1"})
    with urllib.request.urlopen(request, timeout=120) as response:
        content = response.read(200 * 1024 * 1024 + 1)
    if len(content) > 200 * 1024 * 1024:
        raise RuntimeError("Download exceeded the size limit.")
    if hashlib.sha256(content).hexdigest() != checksum:
        raise RuntimeError("Download checksum mismatch; nothing was installed.")
    return content


def install_tools(root):
    arch = platform.machine()
    if platform.system() != "Linux" or arch not in CLI_SHA256:
        raise RuntimeError("Automatic installation supports Linux x86_64 and aarch64.")
    binary = root / "bin" / "beeper"
    if not binary.exists():
        release_arch = "x64" if arch == "x86_64" else "arm64"
        name = f"beeper-cli-{CLI_VERSION}-linux-{release_arch}.tar.gz"
        content = download(f"https://github.com/beeper/cli/releases/download/v{CLI_VERSION}/{name}", CLI_SHA256[arch])
        with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz") as archive:
            candidates = [m for m in archive.getmembers() if m.isfile() and m.name.rsplit("/", 1)[-1] in ("beeper", f"beeper-linux-{release_arch}")]
            if len(candidates) != 1:
                raise RuntimeError("CLI archive has an unexpected layout.")
            member = archive.extractfile(candidates[0])
            binary.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            temporary = binary.with_suffix(".part")
            temporary.write_bytes(member.read())
            temporary.chmod(0o700)
            temporary.replace(binary)
    # qrcode's SVG/PNG renderers use only the standard library. Keep its wheel
    # metadata and license; no pip, system packages, or online QR service needed.
    if not (root / "lib" / "qrcode" / "__init__.py").exists():
        content = download(QR_URL, QR_SHA256)
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            for name in archive.namelist():
                if name.startswith("/") or ".." in name.split("/"):
                    raise RuntimeError("QR wheel has an unsafe path.")
                dest = root / "lib" / name
                if name.endswith("/"):
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                dest.write_bytes(archive.read(name))
    return {"cliVersion": CLI_VERSION, "qrVersion": "8.2"}
