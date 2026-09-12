"""Provider website login using existing runtimes; session fields stay in private pipes."""
import fcntl
import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path
from beeper import Failure, TERMINAL, emit, segment

SCRIPTS = Path(__file__).resolve().parent


def node_call(data):
    node = shutil.which("node")
    if not node:
        raise Failure("The Server computer's node executable is unavailable. Grok's existing Node 20 is supported; no Node upgrade is required.", "browser_runtime_unavailable")
    try:
        result = subprocess.run([node, "--experimental-websocket", str(SCRIPTS / "browser_runtime.mjs")], input=json.dumps(data),
                                capture_output=True, text=True, timeout=15)
    except subprocess.TimeoutExpired:
        raise Failure("Browser helper timed out.", "browser_timeout") from None
    if result.returncode:
        if data.get("action") == "probe":
            raise Failure("The existing runtime could not complete the browser runtime check. Inspect the Bot environment; the plugin does not install or upgrade Node.", "browser_runtime_unavailable")
        raise Failure("This login requires unsupported browser extraction or has invalid session data. Run browser-check to distinguish runtime readiness from an unsupported login flow.", "browser_unsupported")
    return json.loads(result.stdout)


def readiness():
    result = node_call({"action": "probe"})
    candidates = [shutil.which("google-chrome"), shutil.which("google-chrome-stable"), shutil.which("chromium"), shutil.which("chromium-browser")]
    # Match the browser helper's explicit executable override without reading
    # credentials or starting either Chrome or Beeper Server.
    import os
    override = os.environ.get("BEEPER_CHROME_BINARY")
    if override:
        candidates.insert(0, override)
    result["cloudBrowserAvailable"] = any(path and Path(path).is_file() and os.access(path, os.X_OK) for path in candidates)
    result["downloadsPerformed"] = False
    return result


def fingerprint(session):
    return hashlib.sha256(json.dumps(session.get("currentStep"), sort_keys=True).encode()).hexdigest()


def prepare(runtime):
    runtime.writable()
    session = runtime.network_session()
    if session.get("status") in TERMINAL:
        raise Failure("This network login has ended. Inspect accounts before starting another.", "stale_input")
    plan = node_call({"action": "plan", "step": session.get("currentStep")})
    snapshot = (runtime.network_path(), fingerprint(session))
    return plan, snapshot


def submit(runtime, snapshot, payload, plan):
    node_call({"action": "validate", "plan": plan, "payload": payload})
    with runtime.lock():
        return submit_locked(runtime, snapshot, payload)


def submit_locked(runtime, snapshot, payload):
    session = runtime.network_session()
    if snapshot != (runtime.network_path(), fingerprint(session)) or session.get("status") in TERMINAL:
        raise Failure("The network login changed. This browser handoff cannot be reused.", "stale_input")
    result = runtime.api("POST", snapshot[0] + "/steps/" + segment(session["currentStep"]["stepID"]),
                         {"type": "cookies", "fields": payload["fields"], "lastURL": payload["lastURL"], "source": "webview"})
    return runtime.network_view(result)


def stop_process(process):
    if process and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def describe(runtime):
    plan, _ = prepare(runtime)
    from urllib.parse import urlsplit
    origins = {"https://" + urlsplit(plan["url"]).hostname}
    origins.update("https://" + source["domain"] for field in plan["fields"]
                   for source in field["sources"] if source["type"] == "cookie")
    return {"provider": plan["provider"], "loginURL": plan["url"], "origins": sorted(origins),
            "requiredFields": [field["id"] for field in plan["fields"] if field["required"]],
            "optionalFields": [field["id"] for field in plan["fields"] if not field["required"]],
            "fieldInstruction": "Only requiredFields block readiness. Collect optionalFields when present; never invent values or ask the user to browse/re-login just to obtain them. Explicit bridge requirements take precedence over provider defaults.",
            "next": "browser-start --browser local",
            "localRequirements": "Grok Desktop local execution and existing Chrome; Chrome 144+ approval for session reuse. Every transfer needs fresh approval.",
            "cloudAlternative": "Only if the user explicitly chooses browser-start --browser cloud"}


def serve(runtime, browser=None, cdp_url=None):
    runtime.root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (runtime.root / "browser.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Failure("A browser login is already running. Finish or cancel it first.", "busy")
        with runtime.lock():
            plan, snapshot = prepare(runtime)
            pending = runtime.state()["network"]
            browser = browser or pending.get("browser", "auto")
            if browser == "auto":
                browser = "native" if cdp_url else "local"
            if browser == "local":
                if cdp_url:
                    raise Failure("Local browser discovery runs on the PC; do not pass a cloud endpoint.", "invalid_browser")
                from local_transfer import prepare_transfer
                runtime.update(network={**pending, "browser": browser})
                emit({"success": True, "data": prepare_transfer(runtime, plan, snapshot)})
                return 0
            if browser == "native" and not cdp_url:
                raise Failure("Native import needs Grok's built-in cookie approval/import and its receiving cloud browser endpoint. Use browser-start --browser local for the bundled PC helper when native import is unavailable. No extension or relay is installed.", "native_browser_unavailable")
            if browser == "cloud" and cdp_url:
                raise Failure("Use --browser native with a Grok-provided browser endpoint.", "invalid_browser")
            if cdp_url:
                from urllib.parse import urlsplit
                try:
                    url = urlsplit(cdp_url)
                    valid = url.scheme == "http" and url.hostname == "127.0.0.1" and url.port and not url.username and not url.password and url.path in ("", "/") and not url.query and not url.fragment
                except ValueError:
                    valid = False
                if not valid:
                    raise Failure("Use the exact http://127.0.0.1:PORT endpoint provided by Grok for its cloud browser.", "invalid_browser")
            runtime.update(network={**pending, "browser": browser})
        return cloud(runtime, plan, snapshot, cdp_url)


def cloud(runtime, plan, snapshot, cdp_url=None):
    node = shutil.which("node")
    if not node:
        raise Failure("The Server computer's node executable is unavailable. Grok's existing Node 20 is supported; no Node upgrade is required.", "browser_runtime_unavailable")
    emit({"success": True, "data": {"state": "using-grok-browser" if cdp_url else "opening-provider-website", "provider": plan["provider"], "instruction": "The provider website will open on this computer. Use Grok takeover if sign-in is needed. Requested required fields and any optional fields present go directly to Beeper Server; missing optional fields do not block sign-in."}})
    process = subprocess.Popen([node, "--experimental-websocket", str(SCRIPTS / "cloud_browser.mjs")], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    data = json.dumps({"plan": plan, "root": str(runtime.root), "timeout": 600, "cdpURL": cdp_url})
    deadline = time.monotonic() + 630
    try:
        while True:
            try:
                output, _ = process.communicate(input=data, timeout=1)
                break
            except subprocess.TimeoutExpired:
                data = None
                if not runtime.state().get("network") or runtime.network_path() != snapshot[0]:
                    raise Failure("Network login was cancelled or changed.", "stale_input")
                if time.monotonic() >= deadline:
                    raise Failure("Provider browser timed out. Inspect network-show before retrying.", "browser_timeout")
    finally:
        stop_process(process)
    if process.returncode:
        raise Failure("Provider browser could not complete sign-in. Run browser-check and check Chrome/Chromium and the graphical desktop. Grok's Node 20 is supported. Inspect network-show before retrying.", "browser_unavailable")
    payload = json.loads(output)
    emit({"success": True, "data": submit(runtime, snapshot, payload, plan)})
    return 0
