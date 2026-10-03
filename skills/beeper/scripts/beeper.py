#!/usr/bin/env python3
"""A small, private launcher for Beeper on Grok's cloud computer."""
import argparse
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

TARGET = "grok-bot"
VERSION = "0.7.6"
SETUP = "/v1/app/setup"
INSTALL_SCOPE = "beeper-cloud-install-v1"
INSTALL_PROMPT = ("May I install Beeper CLI and Beeper Server on your shared Grok cloud computer? "
                  "All your devices will use this same setup. Nothing will be installed on your PC or phone.")


class Failure(Exception):
    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


def cli_failure(decoded, exit_code):
    """Classify errors using fixed explanations; never echo free-form CLI text.

    Error strings can include contact IDs, message bodies and credentials, so
    pattern-based redaction of the raw string is not a sufficient boundary.
    """
    decoded = decoded if isinstance(decoded, dict) else {}
    error = decoded.get("error", {})
    message = error.get("message", "") if isinstance(error, dict) else error
    message = message if isinstance(message, str) else ""
    reason = "Check command --help and the requested scope."
    kind = decoded.get("kind")
    code = kind if isinstance(kind, str) and kind in {"abort", "auth", "validation", "network", "bug", "usage"} else "cli_error"
    supplied_code = error.get("code") if isinstance(error, dict) else None
    if isinstance(supplied_code, str) and supplied_code in {"http_error", "network_error", "timeout", "not_found", "unauthorized",
                         "forbidden", "conflict", "unsupported", "rate_limited", "invalid_arguments"}:
        code = supplied_code
    elif isinstance(supplied_code, str) and re.fullmatch(r"http_[45]\d\d", supplied_code):
        code = supplied_code
    for prefix, category, explanation in (
        ("contact not found", "contact_not_found", "The contact lookup did not resolve that selector. Use contact search and verify its account."),
        ("message not found", "message_not_found", "The message is not currently available on the selected chat."),
        ("chat not found", "chat_not_found", "The chat lookup did not resolve that selector."),
    ):
        if message.lower().startswith(prefix):
            code, reason = category, explanation
            break
    if "timed out" in message.lower():
        code, reason = "timeout", "The outcome may be unknown. Read back the result before retrying a write."
    http = re.search(r"(?:HTTP|returned) ([45]\d\d)\b", message, re.I)
    if http:
        code, reason = "http_" + http[1], "Server rejected the request. Check access and the requested operation."
    return Failure(f"Beeper command failed (exit {exit_code}, code {code}). {reason}", code)


def read_json(path):
    return json.loads(path.read_text()) if path.exists() else {}


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(data, stream, ensure_ascii=False)
        stream.write("\n")
    temporary.replace(path)


def redact(data):
    if isinstance(data, dict):
        return {key: "[redacted]" if re.search(
            r"token|password|recovery.?key|authorization|cookie|secret", key, re.I)
            and not isinstance(value, (dict, bool)) else redact(value)
            for key, value in data.items()}
    if isinstance(data, list):
        return [redact(value) for value in data]
    return data


def emit(data):
    print(json.dumps(redact(data), ensure_ascii=False), flush=True)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_):
        return None


class Runtime:
    def __init__(self, root=None):
        os.umask(0o077)
        # One account's cloud workspace, never a new home-directory installation
        # selected just because a client device or working directory changed.
        default = "/workspace/.beeper-grok"
        self.root = Path(root or os.environ.get("BEEPER_PLUGIN_HOME") or default).expanduser().resolve()
        self.config = self.root / "config"
        self.binary = self.root / "bin/beeper"
        self.target_file = self.config / "targets" / f"{TARGET}.json"

    def writable(self):
        if os.environ.get("BEEPER_READONLY", "").lower() in ("1", "true", "yes", "on"):
            raise Failure("BEEPER_READONLY prevents changes.")

    @contextmanager
    def lock(self):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (self.root / "operation.lock").open("a") as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise Failure("Another setup, update, or private sign-in is running. Await that job or cancel its private page.") from None
            yield

    def target(self):
        target = read_json(self.target_file)
        url = urllib.parse.urlsplit(target.get("baseURL", ""))
        if (target.get("id") != TARGET or target.get("type") != "server" or not target.get("managed")
                or not isinstance(target.get("dataDir"), str) or not target["dataDir"]
                or target.get("serverEnv", "production") != "production"
                or url.scheme != "http" or url.hostname != "127.0.0.1" or not url.port
                or url.port != (target.get("port") or target.get("runtime", {}).get("port") or url.port)
                or url.username or url.password or url.query or url.fragment or url.path not in ("", "/")):
            raise Failure("Expected the existing production, loopback grok-bot Server target. Run setup if missing.")
        return target

    def env(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith("BEEPER_") or k == "BEEPER_READONLY"}
        for folder in ("cache", "tmp"):
            (self.root / folder).mkdir(parents=True, exist_ok=True, mode=0o700)
        env.update(BEEPER_CLI_CONFIG_DIR=str(self.config), BEEPER_TARGET=TARGET,
                   XDG_CACHE_HOME=str(self.root / "cache"), TMPDIR=str(self.root / "tmp"),
                   BEEPER_CLI_BINARY_CACHE_DIR=str(self.root / "cache/binary"))
        if self.target_file.exists():
            token = self.target().get("auth", {}).get("accessToken")
            if token:
                # CLI 0.6.2 readiness checks can lose target auth when resolving a URL.
                env["BEEPER_ACCESS_TOKEN"] = token
        return env

    def run(self, args, timeout):
        if not self.binary.is_file():
            raise Failure("Beeper CLI is missing. Run setup.")
        # The standalone CLI starts a Bun child. Kill the whole command group
        # on timeout, otherwise a watch or failed command can keep running.
        with subprocess.Popen([str(self.binary), *args], env=self.env(), stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, start_new_session=True) as process:
            expired = False
            try:
                output, errors = process.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                expired = True
                os.killpg(process.pid, signal.SIGKILL)
                output, errors = process.communicate()
        return subprocess.CompletedProcess(args, process.returncode, output, errors), expired

    def cli(self, args, timeout=90):
        result, expired = self.run([*args, "--json"], timeout)
        if expired:
            raise Failure("Beeper timed out. Check the result before retrying any write.", "timeout")
        result.stdout = result.stdout.decode("utf-8", errors="replace")
        if result.returncode:
            # Upstream errors may echo a submitted secret or message. Keep diagnostics
            # useful without printing raw stderr, credentials, or configuration.
            try:
                # Released CLI failures are JSON on stderr, unlike success data.
                decoded = json.loads(result.stdout or result.stderr)
                # These diagnostics deliberately exit nonzero when not ready/reachable.
                if isinstance(decoded, dict) and (args[0] == "doctor" or args[:2] == ["targets", "status"]) and decoded.get("success") is True:
                    return decoded["data"]
            except ValueError:
                decoded = {}
            raise cli_failure(decoded, result.returncode)
        if "--help" in args:
            return {"help": result.stdout}
        if args[0] == "export" or (args[:2] == ["messages", "export"] and not result.stdout.strip()):
            return {"completed": True, "note": "Export command finished. Inspect the requested output and its coverage."}
        try:
            output = json.loads(result.stdout)
        except ValueError:
            raise Failure("Beeper returned unexpected output. Raw output was withheld.") from None
        if isinstance(output, dict) and output.get("success") is False:
            raise cli_failure(output, result.returncode)
        return output.get("data", output) if isinstance(output, dict) else output

    def api(self, method, path, body=None, public=False, timeout=30):
        if method != "GET":
            self.writable()
        target = self.target()
        headers = {"Content-Type": "application/json"}
        if not public:
            token = target.get("auth", {}).get("accessToken")
            if not token:
                raise Failure("Sign in to Beeper first.")
            headers["Authorization"] = "Bearer " + token
        request = urllib.request.Request(target["baseURL"].rstrip("/") + path,
            data=json.dumps(body).encode() if body is not None else None, headers=headers, method=method)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        try:
            with opener.open(request, timeout=timeout) as response:
                data = response.read()
            return json.loads(data) if data else {}
        except urllib.error.HTTPError as error:
            code = error.code
            error.close()
            raise Failure(f"Beeper API returned HTTP {code}. No response body or submitted value was printed.", code=code) from None
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            raise Failure("Beeper Server is unreachable or timed out. Check status before retrying.") from None

    def status(self):
        result = {"pluginVersion": VERSION, "dataDirectory": str(self.root),
                  "cliInstalled": self.binary.exists(), "targetConfigured": self.target_file.exists()}
        if self.binary.exists():
            result["cli"] = self.cli(["version"])
        if self.target_file.exists():
            result["server"] = self.cli(["targets", "status", TARGET])
            result["setup"] = self.cli(["status"])
        return result

    def onboard(self):
        """Inspect installation and consent without launching a process or writing."""
        cli = self.binary.is_file()
        target_exists = self.target_file.exists()
        installed = read_json(self.config / "installations.json").get("server", {})
        server = isinstance(installed, dict) and isinstance(installed.get("path"), str) and Path(installed["path"]).is_file()
        result = {"pluginVersion": VERSION, "dataDirectory": str(self.root), "target": TARGET,
                  "executionLocation": "Grok account's shared cloud computer",
                  "reuseAcrossDevices": True, "cliInstalled": cli, "serverInstalled": server,
                  "targetConfigured": target_exists, "approvalRequired": False,
                  "readinessChecked": False, "actions": []}
        reason = None
        if target_exists:
            try:
                self.target()
            except Failure as error:
                reason = str(error)
            if not cli or not server:
                reason = "The existing target has missing installation files. Preserve its profile and inspect before repairing."
        elif (self.config / "profiles/server" / TARGET).exists():
            reason = "An existing profile has no target file. Restore its target; do not create another profile."
        if installed and not server:
            reason = "The saved Server executable is missing or invalid. Preserve the profile and inspect before repairing."
        if reason:
            return {**result, "state": "repair_required", "reason": reason, "nextAction": "inspect_existing_installation"}
        if cli and server and target_exists:
            return {**result, "state": "configured", "nextAction": "status",
                    "note": "Reuse the existing installation. This local check does not establish sign-in or live Server readiness."}
        consent = read_json(self.root / "setup-consent.json")
        approved = (isinstance(consent, dict) and consent.get("approved") is True
                    and consent.get("scope") == INSTALL_SCOPE and consent.get("dataDirectory") == str(self.root)
                    and consent.get("target") == TARGET)
        actions = (["install_official_cli"] if not cli else []) + (["install_official_server"] if not server else [])
        if not target_exists:
            actions.append("create_cloud_target")
        actions.append("start_server")
        return {**result, "state": "setup_incomplete" if approved else "needs_approval",
                "approvalRequired": not approved, "approvalPrompt": None if approved else INSTALL_PROMPT,
                "actions": actions, "nextAction": "setup" if approved else "await_user_approval"}

    def setup(self, update=False, approved=False):
        self.writable()
        from install import install_cli, latest

        def preflight():
            plan = self.onboard()
            if plan["state"] == "repair_required":
                raise Failure(plan["reason"], "setup_requires_repair")
            if plan["approvalRequired"] and not approved:
                raise Failure("Cloud installation needs your approval. Run onboard to see the plan; use setup --approved only after consent.", "approval_required")
            return plan

        preflight()  # No directory, lock, download, or process before approval.
        with self.lock():
            plan = preflight()  # Another conversation may have finished setup.
            if approved and plan["state"] != "configured":
                write_json(self.root / "setup-consent.json", {"approved": True, "scope": INSTALL_SCOPE,
                           "dataDirectory": str(self.root), "target": TARGET, "approvedAt": time.time()})
            release = None
            if not self.binary.exists() or update:
                release = latest(self.root)
                current = self.cli(["version"], timeout=180)["version"] if self.binary.exists() else None
                if current != release["version"]:
                    install_cli(self.root, release)
            installed = read_json(self.config / "installations.json").get("server", {})
            if not installed:
                self.cli(["install", "server", "--server-env", "production"], timeout=900)
            elif not Path(installed["path"]).exists():
                raise Failure("The saved Server executable is missing. Preserve the profile; inspect the installation before repairing it.")
            if not self.target_file.exists():
                # A missing target beside an existing profile is a recovery task,
                # never permission to overwrite the user's account or keys.
                if (self.config / "profiles/server" / TARGET).exists():
                    raise Failure("An existing profile has no target file. Restore its target; do not create another profile.")
                with socket.socket() as probe:
                    probe.bind(("127.0.0.1", 0))
                    port = probe.getsockname()[1]
                self.cli(["targets", "add", "server", TARGET, "--port", str(port), "--server-env", "production"])
            self.target()
            backup = None
            if update and installed:
                check = self.cli(["update", "--server", "--check"])
                if any(item.get("available") for item in check):
                    backup = self.update_server(installed)
            if backup is None and not self.server_running():
                self.cli(["targets", "start", TARGET])
        return {"backup": backup, "cliRelease": release, "status": self.status()}

    def check_updates(self):
        from install import InstallError, latest
        current = self.cli(["version"])["version"] if self.binary.exists() else None
        try:
            release = latest(self.root)
            results = [{"kind": "cli", "checked": True, "currentVersion": current,
                        "latestVersion": release["version"], "available": current != release["version"],
                        "source": release["source"], "cached": release["cached"], "checkedAt": release["checkedAt"]}]
        except InstallError as error:
            results = [{"kind": "cli", "checked": False, "currentVersion": current,
                        "available": None, "error": error.info}]
        if not read_json(self.config / "installations.json").get("server"):
            results.append({"kind": "server", "installed": False, "action": "Run setup."})
        elif not self.binary.exists():
            results.append({"kind": "server", "checked": False, "available": None, "error": "CLI is missing."})
        else:
            try:
                # --server prevents the native updater from checking GitHub's API.
                results.extend(self.cli(["update", "--check", "--server"]))
            except Failure as error:
                results.append({"kind": "server", "checked": False, "available": None, "error": str(error)})
        return results

    def update_server(self, installed):
        targets = list((self.config / "targets").glob("*.json"))
        if any(p != self.target_file and read_json(p).get("type") == "server" for p in targets):
            raise Failure("This installation serves another Server profile. Review all profiles before updating the shared program.")
        profile = Path(self.target()["dataDir"]).resolve(strict=True)
        if not profile.is_dir() or self.root.is_relative_to(profile) or self.config.resolve().is_relative_to(profile):
            raise Failure("The profile must be a separate data directory. Preserve it and review its location before updating.")
        if self.server_running():
            self.cli(["targets", "stop", TARGET])
        if self.server_running():
            raise Failure("Server is still running. No backup or update was attempted.")
        backup = self.root / "private-backups" / ("before-update-" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()))
        try:
            backup.mkdir(parents=True, mode=0o700)
            # Keep one copy of the actual profile, including an external or linked root.
            with tarfile.open(backup / "config.tar.gz", "w:gz") as archive:
                archive.add(self.config, arcname="config", filter=lambda item: None
                    if (self.config / Path(item.name).relative_to("config")).resolve() == profile else item)
                archive.dereference = True
                def profile_entry(item):
                    source = profile / Path(item.name).relative_to("profile")
                    if source.is_symlink() and item.isdir():
                        raise Failure("The profile contains a linked directory. Review its backup layout before updating.")
                    return item
                archive.add(profile, arcname="profile", filter=profile_entry)
            write_json(backup / "profile.json", {"dataDir": self.target()["dataDir"],
                       "resolvedDataDir": str(profile), "archive": "config.tar.gz", "prefix": "profile"})
            program = Path(installed["path"]).resolve()
            if program.is_dir():
                shutil.copytree(program, backup / "server-program", symlinks=True)
            else:
                shutil.copytree(program.parent, backup / "server-program", symlinks=True)
            write_json(backup / "installation.json", installed)
            self.cli(["update", "--server"], timeout=900)
        finally:
            # An update failure must not deliberately leave a working profile stopped.
            self.cli(["targets", "start", TARGET])
        return str(backup)

    def server_running(self):
        # A listening port or a live managed PID prevents an offline backup.
        pid = read_json(self.config / "run/profiles" / f"{TARGET}.json").get("pid")
        if isinstance(pid, int) and pid > 0:
            try:
                os.kill(pid, 0)
                return True
            except ProcessLookupError:
                pass
        try:
            with socket.create_connection(("127.0.0.1", urllib.parse.urlsplit(self.target()["baseURL"]).port), timeout=1):
                return True
        except ConnectionRefusedError:
            return False

    def command(self, args):
        allowed = {"accounts", "chats", "messages", "send", "contacts", "media", "presence", "export", "version", "doctor", "man"}
        if not args or args[0] not in allowed:
            raise Failure("Use a messaging command, or setup/status/verify for Beeper account setup.")
        if args[0] == "accounts" and (len(args) < 2 or args[1] not in ("list", "show", "--help")):
            raise Failure("Only existing accounts are supported. Adding, reconnecting, and removing accounts are outside this plugin.")
        from outcomes import is_message_write, run_write
        if is_message_write(args):
            return run_write(self, args)
        blocked = ("--target", "--base-url", "--debug", "--no-json", "--events", "--ids")
        # Only long options: short clusters such as -qtother can hide a target override.
        if any(a.split("=", 1)[0] in blocked or re.match(r"^-[A-Za-z]", a) for a in args):
            raise Failure("Use long options. Target overrides, debug output, and non-JSON output are disabled.")
        if "--help" not in args:
            if args[:2] == ["messages", "search"]:
                from search import command
                return command(self, args)
            if args[:2] in (["messages", "list"], ["messages", "context"], ["messages", "export"]):
                from history import command
                return command(self, args)
            if args[:2] == ["contacts", "show"]:
                from contacts import show
                return show(self, args)
        if args[:2] in (["chats", "archive"], ["chats", "unarchive"]) and "--help" not in args:
            # CLI 0.6.2 uses the wrong archive endpoint; this is the official
            # endpoint already used by the SDK and the unreleased upstream fix.
            options = argparse.ArgumentParser(prog="chats " + args[1], exit_on_error=False)
            options.add_argument("--chat", required=True)
            options.add_argument("--read-only", action="store_true")
            flags = options.parse_args(args[2:])
            self.writable()
            if flags.read_only:
                raise Failure("Read-only mode prevents archiving.")
            chat = self.cli(["chats", "show", "--chat", flags.chat])
            chat_id = chat["id"]
            archived = args[1] == "archive"
            self.api("POST", "/v1/chats/" + urllib.parse.quote(chat_id, safe="") + "/archive", {"archived": archived})
            return {"chatID": chat_id, "archived": archived}
        data = self.cli(args, timeout=900 if "export" in args else 90)
        if "--help" in args and isinstance(data, dict):
            if args[:2] in (["messages", "list"], ["messages", "context"], ["messages", "export"]):
                data["compatibilityNotes"] = "Plugin reads use Server cursors. --max-pages defaults to 20 (maximum 200); --timeout is milliseconds, default 30000. Message cursor flags still accept message IDs. Context sides are nearest first. Timestamp ties retain Server order."
            elif args[:2] == ["contacts", "show"]:
                data["compatibilityNotes"] = "Contact selectors are exact IDs by default. Use --by-label for name/phone/handle lookup; --query ORIGINAL_SEARCH_TEXT is an exact-ID hint and cannot combine with --by-label. --max-pages defaults to 20 (200 maximum including account/search reads)."
            elif args[:2] == ["messages", "search"]:
                data["compatibilityNotes"] = "Returns data.items plus data.coverage. Dates require timezones and support fractional seconds: --after/--before are inclusive; --before-exclusive makes the upper bound exclusive. Includes low-priority and muted chats by default; --exclude-low-priority/--no-include-muted narrow scope. --max-pages defaults to 20 (maximum 200); --timeout is milliseconds (default 30000)."
        return data

    def verify(self, step, matches=False):
        comparison_file = self.root / "verification-comparison.json"
        current = self.cli(["verify", "show"])
        if step == "show":
            if (isinstance(current, dict) and current.get("id") and current.get("sas")
                    and current.get("state") not in ("done", "cancelled", "error")
                    and os.environ.get("BEEPER_READONLY", "").lower() not in ("1", "true", "yes", "on")):
                write_json(comparison_file, {"id": current["id"], "sas": current["sas"]})
            return current
        self.writable()
        if step == "start" and current and current.get("state") not in ("done", "cancelled", "error"):
            return current
        if step == "approve" and (not current or "accept" not in current.get("availableActions", [])):
            raise Failure("The current verification is not waiting for acceptance. Show its available actions.")
        if step == "sas-confirm":
            shown = read_json(comparison_file) or {}
            if (not matches or not current or not current.get("sas")
                    or current.get("state") in ("done", "cancelled", "error")
                    or ("availableActions" in current and "sas.confirm" not in current["availableActions"])
                    or current.get("id") != shown.get("id") or current.get("sas") != shown.get("sas")):
                raise Failure("Show the current comparison and obtain the user's match confirmation before confirming it.")
        args = ["verify", step]
        if step != "start":
            if not current or not current.get("id"):
                raise Failure("No active verification. Start one before continuing.")
            # Published CLI 0.6.2 can resolve the wrong ID when --id is omitted.
            args += ["--id", current["id"]]
        return self.cli(args)

    def watch(self, seconds, chat=None):
        args = ["watch", "--json", "--include-type", "message.upserted"]
        if chat:
            args += ["--chat", chat]
        result, expired = self.run(args, seconds)
        if result.returncode and not expired:
            raise Failure("The message event connection failed. Reconcile with a message read.")
        events = []
        for line in result.stdout.splitlines():
            try:
                events.append(json.loads(line))
            except ValueError:
                raise Failure("Incomplete event output. Reconcile with a message read.") from None
        return {"events": events, "windowSeconds": seconds, "streamEndedEarly": not expired,
                "note": "Events are live updates, not a complete inbox. Fetch messages to confirm sender and content."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    setup = actions.add_parser("setup")
    setup.add_argument("--approved", action="store_true", help="Use only after the user approves installation on the Grok cloud computer")
    for name in ("onboard", "update", "status", "start", "check-updates", "signin", "recovery"):
        actions.add_parser(name)
    cli = actions.add_parser("cli", help="Run a native Beeper messaging command")
    cli.add_argument("arguments", nargs=argparse.REMAINDER)
    verify = actions.add_parser("verify")
    verify.add_argument("step", choices=("start", "show", "approve", "sas", "sas-confirm", "cancel"))
    verify.add_argument("--matches", action="store_true", help="Use only after the user confirms the displayed comparison matches")
    watch = actions.add_parser("watch")
    watch.add_argument("--seconds", type=int, choices=range(1, 61), default=30, metavar="1..60")
    watch.add_argument("--chat")
    args = parser.parse_args()
    runtime = Runtime()
    try:
        if args.action in ("setup", "update"):
            data = runtime.setup(update=args.action == "update", approved=getattr(args, "approved", False))
        elif args.action == "onboard":
            data = runtime.onboard()
        elif args.action == "status":
            data = runtime.status()
        elif args.action == "start":
            runtime.writable()
            with runtime.lock():
                data = runtime.cli(["targets", "start", TARGET])
        elif args.action == "check-updates":
            data = runtime.check_updates()
        elif args.action in ("signin", "recovery"):
            from signin import serve
            data = serve(runtime, args.action)
        elif args.action == "verify":
            data = runtime.verify(args.step, args.matches)
        elif args.action == "watch":
            data = runtime.watch(args.seconds, args.chat)
        else:
            data = runtime.command(args.arguments)
        emit({"success": True, "data": data})
    except Exception as error:
        from install import InstallError
        if isinstance(error, InstallError):
            emit({"success": False, "error": error.info})
            return 1
        message = str(error) if isinstance(error, Failure) else f"{type(error).__name__}: operation failed; raw details withheld. Check status before retrying."
        result = {"success": False, "error": message}
        if isinstance(error, Failure) and error.code is not None:
            result["errorCode"] = error.code
        if isinstance(error, Failure) and getattr(error, "write_outcome", None):
            result["writeOutcome"] = error.write_outcome
        emit(result)
        return 1
    return 0


if __name__ == "__main__":
    # signin imports beeper; script execution must share the same Failure class.
    sys.modules["beeper"] = sys.modules[__name__]
    sys.exit(main())
