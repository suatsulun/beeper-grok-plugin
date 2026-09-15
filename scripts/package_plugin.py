#!/usr/bin/env python3
"""Package committed plugin source for transfer; never include local runtime data."""
import argparse
import base64
import hashlib
import io
import json
from pathlib import Path
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    if git("status", "--porcelain").strip():
        parser.error("Commit or set aside source changes before packaging a reproducible revision.")
    revision = git("rev-parse", "HEAD").decode().strip()
    archive = git("archive", "--format=zip", "HEAD")
    with zipfile.ZipFile(io.BytesIO(archive)) as source:
        manifest = json.loads(source.read(".grok-plugin/plugin.json"))
        rows = []
        for name in sorted(source.namelist()):
            if name.endswith("/"):
                continue
            data = source.read(name)
            try:
                content, encoding = data.decode("utf-8"), "utf-8"
            except UnicodeDecodeError:
                content, encoding = base64.b64encode(data).decode("ascii"), "base64"
            rows.append({"path": name, "encoding": encoding, "content": content,
                         "sha256": hashlib.sha256(data).hexdigest()})
    version = manifest["version"]
    name = f"beeper-grok-plugin-{version}"
    destination = f"/workspace/beeper-plugin-{version}"
    bundle = {"format": "beeper-plugin-test-bundle-v1",
              "purpose": "Plugin-only source transfer; not an official plugin-import format or marketplace release.",
              "plugin": manifest["name"], "version": version, "sourceRevision": revision,
              "suggestedDirectory": destination, "entryPoint": "skills/beeper/SKILL.md", "files": rows}
    instructions = f"""Update only my Beeper Grok plugin to {version} from the attached source ZIP (or equivalent JSON source bundle).

Source commit: {revision}

Extract into a new source directory, preferably {destination}. For the JSON alternative, reconstruct only safe relative paths inside that directory and verify each file's SHA-256; it is a source bundle, not an official plugin import. Do not print file contents or secrets. If the destination already exists, compare it and use a new source directory if it differs rather than overwriting an active checkout.

Read README.md and skills/beeper/SKILL.md. Follow the supported plugin installation route if available; otherwise use that SKILL.md and its absolute helper path for this conversation. Report which route you used; do not claim a persistent plugin installation merely because files were extracted.

Keep my existing BEEPER_PLUGIN_HOME, /workspace/.beeper-grok, grok-bot target, CLI, Server build, accounts, keys, and any existing Server repairs unchanged. This package needs no CLI replacement. Do not run bootstrap, restart, reconnect, reset, reinstall, patch Server, or send a message to validate this update.

Keep the accepted website login flow: fresh local approval BEFORE opening the named provider in its separate local profile, then automatic encrypted return and the completion page. Preserve QR and native code flows. No Chrome settings, extra installations, ordinary-profile copying, or automatic cloud-browser fallback. Do not initiate a login just to test the new source.

Verify the plugin manifest and source commit. If an already known chat is available, perform one read-only message read with limit 1 without quoting the body, and report success/error plus account type. Do not run a broad chat scan or repeated diagnostics. Report the new helper path and version, whether the scoped read succeeded, and any remaining limitation. A global initializing/E2EE flag alone is not grounds to change a working account or Server.
"""
    args.output.mkdir(parents=True, exist_ok=True)
    outputs = {name + ".zip": archive,
               name + ".json": (json.dumps(bundle, ensure_ascii=False, indent=2) + "\n").encode(),
               "SEND-TO-GROK.txt": instructions.encode()}
    for filename, data in outputs.items():
        (args.output / filename).write_bytes(data)
    (args.output / "SHA256SUMS").write_text("".join(
        f"{hashlib.sha256(data).hexdigest()}  {filename}\n" for filename, data in outputs.items()))
    print(json.dumps({"version": version, "sourceRevision": revision, "files": len(rows),
                      "output": str(args.output.resolve())}, indent=2))


if __name__ == "__main__":
    main()
