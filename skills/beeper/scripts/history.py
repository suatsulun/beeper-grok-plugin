"""Bounded history reads using only pagination tokens supplied by Server.

CLI 0.6.2 sends message IDs as opaque cursors. Do not synthesize a cursor from
an ID, timestamp, or sortKey. Walk real pages and locate the requested ID.
"""
import argparse
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
import time
from urllib.parse import quote, urlencode

from beeper import Failure, write_json


class Parser(argparse.ArgumentParser):
    def error(self, message):
        # argparse errors can contain submitted values. Keep them out of output.
        raise Failure("Invalid compatibility-command options. Check command --help.", "invalid_arguments")


def parser(name):
    result = Parser(prog=name, allow_abbrev=False)
    for flag in ("read-only", "json", "quiet", "full", "yes"):
        result.add_argument("--" + flag, action="store_true")
    result.add_argument("--timeout", type=int, default=30000)
    result.add_argument("--max-pages", type=int, default=20)
    return result


def bounds(flags):
    if not 1 <= flags.max_pages <= 200 or not 1 <= flags.timeout <= 300000:
        raise Failure("Use --max-pages 1..200 and --timeout 1..300000 (milliseconds).", "invalid_arguments")


def chat_id(runtime, selector, pick=None, timeout=None):
    if selector.startswith("!"):
        return selector
    args = ["chats", "show", "--chat", selector, "--read-only"]
    if pick is not None:
        args += ["--pick", str(pick)]
    chat = runtime.cli(args, **({"timeout": timeout} if timeout is not None else {}))
    if not isinstance(chat, dict) or not isinstance(chat.get("id"), str):
        raise Failure("Chat lookup did not return an ID.", "invalid_response")
    return chat["id"]


def timestamp(row):
    try:
        value = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
        if value.tzinfo is None:
            raise ValueError()
        return value
    except (KeyError, ValueError, TypeError, AttributeError):
        raise Failure("History contains an invalid timestamp; coverage cannot be established.", "invalid_history") from None


def rows(runtime, chat, max_pages=20, timeout=30000):
    """Yield unique rows newest first, retaining the server's order for ties.

    Invalid order, missing cursors and loops fail rather than claiming complete
    history. Duplicate boundary rows are ignored only while pagination advances.
    """
    path = "/v1/chats/" + quote(chat, safe="") + "/messages"
    seen, cursors = set(), set()
    cursor, last_time, account = None, None, None
    deadline = time.monotonic() + timeout / 1000
    for _ in range(max_pages):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise Failure("History read reached its time budget. Narrow the request or increase --timeout.", "history_budget")
        query = "?" + urlencode({"cursor": cursor, "direction": "before"}) if cursor is not None else ""
        page = runtime.api("GET", path + query, timeout=min(30, remaining))
        if not isinstance(page, dict) or not isinstance(page.get("items"), list) or not isinstance(page.get("hasMore"), bool):
            raise Failure("Server returned an invalid history page.", "invalid_history")
        progress = False
        for row in page["items"]:
            if (not isinstance(row, dict) or not isinstance(row.get("id"), str)
                    or not row["id"] or row.get("chatID") != chat
                    or not isinstance(row.get("accountID"), str)):
                raise Failure("History returned an invalid message or a different chat. For merged conversations, select an explicit network member chat.", "invalid_history")
            account = account if account is not None else row["accountID"]
            if account != row["accountID"]:
                raise Failure("History crossed account boundaries.", "invalid_history")
            key = (account, chat, row["id"])
            if key in seen:
                continue
            moment = timestamp(row)
            if last_time is not None and moment > last_time:
                raise Failure("History is not chronological. Do not use this result as a complete window.", "invalid_history")
            seen.add(key)
            last_time, progress = moment, True
            yield row
        if not page["hasMore"]:
            return
        next_cursor = page.get("oldestCursor")
        if not progress or not isinstance(next_cursor, str) or not next_cursor or next_cursor in cursors:
            raise Failure("Server history pagination did not advance. No cursor was guessed or retried.", "pagination_stalled")
        cursors.add(next_cursor)
        cursor = next_cursor
    raise Failure("History needs more pages. Narrow the request or explicitly increase --max-pages (up to 200).", "history_budget")


def matches_sender(row, sender):
    if sender is None:
        return True
    if sender == "me":
        return row.get("isSender") is True
    if sender == "others":
        return row.get("isSender") is False
    return row.get("senderID") == sender


def command(runtime, args):
    options = parser("messages " + args[1])
    options.add_argument("--chat", required=True)
    options.add_argument("--pick", type=int)
    exporting = args[1] == "export"
    if args[1] in ("list", "export"):
        cursor = options.add_mutually_exclusive_group()
        cursor.add_argument("--before-cursor")
        cursor.add_argument("--after-cursor")
        if not exporting:
            options.add_argument("--sender")
        else:
            options.set_defaults(sender=None)
            options.add_argument("--after")
            options.add_argument("--before")
            options.add_argument("--output", default="-")
        options.add_argument("--asc", action="store_true")
        options.add_argument("--limit", type=int, default=None if exporting else 50)
    else:
        options.add_argument("--id", required=True)
        options.add_argument("--before", type=int, default=10)
        options.add_argument("--after", type=int, default=10)
    flags = options.parse_args(args[2:])
    bounds(flags)
    limits = [flags.limit] if args[1] in ("list", "export") else [flags.before, flags.after]
    if any(n is not None and (n < 0 or n > 10000) for n in limits):
        raise Failure("Message limits must be between 0 and 10000.", "invalid_arguments")
    if args[1] == "list" and flags.limit == 0:
        return []
    chat = chat_id(runtime, flags.chat, flags.pick)
    lower = upper = None
    if exporting:
        lower = timestamp({"timestamp": flags.after}) if flags.after else None
        upper = timestamp({"timestamp": flags.before}) if flags.before else None
        if lower and upper and lower > upper:
            raise Failure("Export start must not be after its end.", "invalid_arguments")
        if flags.output != "-":
            runtime.writable()
            if flags.read_only:
                raise Failure("Read-only mode prevents writing an export file.", "read_only")
            destination = Path(flags.output).expanduser().resolve()
            if destination.is_relative_to(runtime.config) or destination == runtime.root / "verification-comparison.json":
                raise Failure("Export outside the Beeper configuration and profile.", "invalid_arguments")
            if runtime.target_file.exists() and destination.is_relative_to(Path(runtime.target()["dataDir"]).resolve()):
                raise Failure("Export outside the Beeper profile.", "invalid_arguments")
    stream = rows(runtime, chat, flags.max_pages, flags.timeout)
    if args[1] == "context":
        newer = deque(maxlen=flags.after)
        older, center = [], None
        for row in stream:
            if center is None:
                if row["id"] != flags.id:
                    newer.append(row)
                    continue
                center = row
            else:
                older.append(row)
            if center is not None and len(older) >= flags.before:
                break
        if center is None:
            raise Failure("Message was not found in the available history.", "message_not_found")
        return {"chatID": chat, "messageID": flags.id, "message": center,
                "before": older, "after": list(reversed(newer)),
                "order": "nearest first on each side; timestamp ties retain Server order"}

    anchor = flags.before_cursor or flags.after_cursor
    found = anchor is None
    selected = deque(maxlen=flags.limit) if flags.after_cursor else []
    for row in (() if flags.limit == 0 else stream):
        eligible = matches_sender(row, flags.sender)
        if exporting:
            moment = timestamp(row)
            eligible = eligible and (lower is None or moment >= lower) and (upper is None or moment <= upper)
        if not found:
            if row["id"] == anchor:
                found = True
                if flags.after_cursor:
                    break
                continue
            if flags.after_cursor and eligible:
                selected.append(row)
            continue
        if exporting and lower is not None and moment < lower:
            break
        if eligible:
            selected.append(row)
            if flags.limit is not None and len(selected) >= flags.limit:
                break
    if not found and flags.limit != 0:
        raise Failure("Cursor message was not found in the available history.", "message_not_found")
    result = list(selected)
    result = list(reversed(result)) if flags.asc else result
    if not exporting:
        return result
    data = {"exportedAt": datetime.now(timezone.utc).isoformat(), "chatID": chat,
            "after": flags.after, "before": flags.before, "count": len(result), "messages": result,
            "limitReached": flags.limit is not None and len(result) >= flags.limit,
            "coverage": "Only history exposed by this Server; a reached limit may truncate the requested window."}
    if flags.output == "-":
        return data
    write_json(destination, data)
    return {"completed": True, "output": str(destination), "count": len(result),
            "limitReached": data["limitReached"], "coverage": data["coverage"]}
