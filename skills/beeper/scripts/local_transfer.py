"""Public local-browser requests and one-use encrypted session delivery."""
import base64
import hashlib
import json
import secrets
import time
from pathlib import Path
from beeper import Failure, TERMINAL, read_json, write_json
from browser_login import SCRIPTS, fingerprint, node_call, submit_locked

LOCAL_FILES = ("local_browser.mjs", "cloud_browser.mjs", "browser_protocol.mjs", "browser_transfer.mjs", "providers.mjs")


def prepare_transfer(runtime, plan, snapshot):
    now = int(time.time() * 1000)
    state_file = runtime.root / "browser-transfer.json"
    previous = read_json(state_file)
    if (previous.get("snapshot") == list(snapshot) and previous.get("request", {}).get("expires", 0) > now
            and previous["request"].get("plan") == plan and not previous.get("consumed")):
        request = previous["request"]
    else:
        pair = node_call({"action": "transfer-keypair"})
        request = {"version": 1, "id": secrets.token_urlsafe(24), "expires": now + 600000,
                   "destination": "Beeper Server on Grok", "publicKey": pair["publicKey"], "plan": plan}
        write_json(state_file, {"request": request, "privateKey": pair["privateKey"], "snapshot": list(snapshot)})
    # The package contains plugin code plus a public request. Never include the
    # receiver state, Server credentials or private key in a local package.
    files = {}
    for name in LOCAL_FILES:
        data = (SCRIPTS / name).read_bytes()
        files[name] = {"base64": base64.b64encode(data).decode(), "sha256": hashlib.sha256(data).hexdigest()}
    data = json.dumps(request).encode()
    files["request.json"] = {"base64": base64.b64encode(data).decode(), "sha256": hashlib.sha256(data).hexdigest()}
    package = runtime.root / "local-browser-package.json"
    write_json(package, {"format": "beeper-local-browser-package-v1", "id": request["id"], "files": files})
    return {"state": "local-browser-required", "provider": plan["provider"], "expires": request["expires"],
            "requiredFields": [field["id"] for field in plan["fields"] if field["required"]],
            "optionalFields": [field["id"] for field in plan["fields"] if not field["required"]],
            "localPackage": str(package), "approval": "Required on the PC for every transfer",
            "instruction": "Run the bundled local_browser.mjs through Grok Desktop's approved LOCAL execution, using existing Node or Grok's embedded Node. Copy only this public package to the PC. The user chooses an existing Chrome session or a separate local login window, then approves this transfer. Return only the encrypted envelope via browser-finish --file. Never substitute a cloud browser automatically."}


def finish_transfer(runtime, envelope_file):
    with runtime.lock():
        runtime.writable()
        state_file = runtime.root / "browser-transfer.json"
        state = read_json(state_file)
        request = state.get("request")
        if not request or state.get("consumed"):
            raise Failure("This browser transfer is missing or already consumed. Inspect network-show before requesting fresh approval.", "stale_input")
        if request["expires"] <= int(time.time() * 1000):
            state_file.unlink(missing_ok=True)
            raise Failure("Browser approval expired. Start a fresh transfer for the pending login.", "browser_timeout")
        session = runtime.network_session()
        snapshot = (runtime.network_path(), fingerprint(session))
        if list(snapshot) != state["snapshot"] or session.get("status") in TERMINAL:
            state_file.unlink(missing_ok=True)
            raise Failure("The pending login changed. This transfer cannot be submitted.", "stale_input")
        with Path(envelope_file).open("rb") as stream:
            data = stream.read(200001)
        if len(data) > 200000:
            raise Failure("Encrypted transfer exceeded the size limit.", "invalid_transfer")
        try:
            envelope = json.loads(data)
            payload = node_call({"action": "transfer-open", "request": request, "privateKey": state["privateKey"], "envelope": envelope})
        except (ValueError, Failure):
            raise Failure("Encrypted transfer was invalid, changed, or expired. Nothing was sent to Beeper.", "invalid_transfer") from None
        # Consume and erase the stored private key before API submission. An
        # ambiguous timeout cannot cause a replay of the same approved session.
        write_json(state_file, {"consumed": True, "id": request["id"]})
        try:
            return submit_locked(runtime, snapshot, payload)
        finally:
            payload.clear()


def cancel_transfer(runtime):
    runtime.writable()
    (runtime.root / "browser-transfer.json").unlink(missing_ok=True)
    (runtime.root / "local-browser-package.json").unlink(missing_ok=True)
    return {"cancelled": True, "networkLoginPreserved": True}
