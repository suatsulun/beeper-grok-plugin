"""Guard native full exports with read-only enforcement and explicit resume scope."""
import fcntl
from pathlib import Path

from beeper import Failure, read_json, write_json
from history import Parser

MARKER = ".beeper-plugin-export.json"
CHECKPOINT = ".beeper-export-state.json"


def command(runtime, args):
    # Upstream full export omits ensureWritable. Enforce before even discovery.
    runtime.writable()
    options = Parser(prog="export", allow_abbrev=False)
    for flag in ("read-only", "json", "quiet", "full", "yes", "force", "no-attachments"):
        options.add_argument("--" + flag, action="store_true")
    for flag in ("account", "chat"):
        options.add_argument("--" + flag, action="append", nargs="+")
    for flag, default in (("limit-chats", None), ("limit-messages", None), ("max-participants", 500), ("pick", None)):
        options.add_argument("--" + flag, type=int, default=default)
    options.add_argument("--out", default="beeper-export")
    options.add_argument("--timeout")
    flags = options.parse_args(args[1:])
    if flags.read_only:
        raise Failure("Read-only mode prevents writing an export.", "read_only")
    if any(value is not None and value < 1 for value in (flags.limit_chats, flags.limit_messages, flags.pick)) or flags.max_participants < 0:
        raise Failure("Export limits and --pick must be positive; --max-participants may be zero.", "invalid_arguments")
    destination = Path(flags.out).expanduser().resolve()
    protected = [runtime.config.resolve(), runtime.root / "bin", runtime.root / "cache", runtime.root / "private-backups"]
    if runtime.target_file.exists():
        protected.append(Path(runtime.target()["dataDir"]).resolve())
    if runtime.root.is_relative_to(destination) or any(destination.is_relative_to(p) or p.is_relative_to(destination) for p in protected):
        raise Failure("Export outside Beeper configuration, profiles, binaries and backups.", "invalid_arguments")
    scope = {
        "accounts": sorted({v for group in (flags.account or []) for v in group}),
        "chats": sorted({v for group in (flags.chat or []) for v in group}),
        "pick": flags.pick, "limitChats": flags.limit_chats, "limitMessages": flags.limit_messages,
        "maxParticipants": flags.max_participants, "attachments": not flags.no_attachments,
    }
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    for name in (MARKER, CHECKPOINT, ".beeper-plugin-export.lock", "manifest.json"):
        if (destination / name).is_symlink():
            raise Failure("Export metadata must not be symlinked. Use a new private output directory.", "invalid_export_state")
    with (destination / ".beeper-plugin-export.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Failure("Another export is using this output directory.", "export_busy") from None
        marker = destination / MARKER
        previous = read_json(marker)
        if not marker.exists() and any(p.name != ".beeper-plugin-export.lock" for p in destination.iterdir()):
            raise Failure("This directory has no trusted export scope record. Preserve it and choose a new output directory.", "export_scope_unknown")
        if marker.exists():
            if (not isinstance(previous, dict) or previous.get("version") != 1
                    or previous.get("dataDirectory") != str(runtime.root) or not isinstance(previous.get("scope"), dict)):
                raise Failure("Export scope metadata is invalid or belongs to another profile. Use a new output directory.", "invalid_export_state")
            old = previous["scope"]
            if any(old.get(key) != scope[key] for key in ("accounts", "chats", "pick")):
                raise Failure("Export account/chat selection changed. Use a new output directory to avoid mixing scopes.", "export_scope_changed")
            if old != scope and not flags.force:
                raise Failure("Export limits or content options changed. Use a new directory, or explicitly use --force to rebuild this selection.", "export_scope_changed")
        # Force is an explicit request to rebuild. Discard only our known native
        # checkpoint so old message/attachment counts cannot contaminate the run.
        if flags.force:
            (destination / CHECKPOINT).unlink(missing_ok=True)
        record = {"version": 1, "dataDirectory": str(runtime.root), "scope": scope, "completed": False}
        write_json(marker, record)  # Also identifies the scope of an interrupted run.
        (destination / "manifest.json").unlink(missing_ok=True)
        native = ["export", "--out", str(destination)]
        for name, values in (("account", scope["accounts"]), ("chat", scope["chats"])):
            for value in values:
                native += ["--" + name, value]
        for name in ("limit-chats", "limit-messages", "max-participants", "pick", "timeout"):
            value = getattr(flags, name.replace("-", "_"))
            if value is not None:
                native += ["--" + name, str(value)]
        native += ["--" + name for name in ("force", "no-attachments", "quiet", "full", "yes")
                   if getattr(flags, name.replace("-", "_"))]
        runtime.cli(native, timeout=900)
        manifest = read_json(destination / "manifest.json")
        counts = ("chatCount", "messageCount", "attachmentCount")
        if not isinstance(manifest, dict) or any(type(manifest.get(key)) is not int or manifest[key] < 0 for key in counts):
            raise Failure("Export returned without a valid manifest. Keep the output for inspection; completion is unverified.", "invalid_export_result")
        state = read_json(destination / CHECKPOINT)
        chats = state.get("chats", {}) if isinstance(state, dict) else {}
        if not isinstance(chats, dict):
            raise Failure("Export checkpoint is invalid. Completion is unverified.", "invalid_export_result")
        limit_reached = ((flags.limit_chats is not None and manifest["chatCount"] >= flags.limit_chats)
                         or (flags.limit_messages is not None and any(
                             isinstance(c, dict) and isinstance(c.get("messageCount"), int) and c["messageCount"] >= flags.limit_messages
                             for c in chats.values())))
        write_json(marker, {**record, "completed": True})
        return {"completed": True, "output": str(destination), **{key: manifest[key] for key in counts},
                "coverage": {"scope": scope, "limitReached": bool(limit_reached),
                             "limitsApplied": flags.limit_chats is not None or flags.limit_messages is not None,
                             "historyComplete": False, "snapshotCreatedAt": manifest.get("createdAt"),
                             "note": "Native checkpoints can reuse completed chats. Use --force for a refreshed snapshot. Only history exposed by Server is available."}}
