"""Bounded message searches with exact local date filtering.

Server search accepts exclusive whole-second bounds on some supported builds.
Query a slightly wider window, then apply the user's precise bounds locally.
"""
from datetime import timedelta, timezone
import time
from urllib.parse import urlencode

from beeper import Failure
from contacts import select_accounts
from history import bounds, chat_id, parser, timestamp


def command(runtime, args):
    options = parser("messages search")
    options.add_argument("query", nargs="?")
    options.add_argument("--account", action="append", nargs="+")
    options.add_argument("--chat", action="append", nargs="+")
    options.add_argument("--chat-type", choices=("single", "group"))
    options.add_argument("--sender")
    options.add_argument("--media", action="append", nargs="+", choices=("any", "video", "image", "link", "file"))
    options.add_argument("--after")
    options.add_argument("--before")
    options.add_argument("--before-exclusive", action="store_true")
    options.add_argument("--limit", type=int, default=50)
    for flag, default in (("exclude-low-priority", False), ("include-muted", True)):
        group = options.add_mutually_exclusive_group()
        group.add_argument("--" + flag, dest=flag.replace("-", "_"), action="store_true")
        group.add_argument("--no-" + flag, dest=flag.replace("-", "_"), action="store_false")
        options.set_defaults(**{flag.replace("-", "_"): default})
    flags = options.parse_args(args[2:])
    bounds(flags)
    if not 0 <= flags.limit <= 10000:
        raise Failure("Use --limit 0..10000.", "invalid_arguments")
    if not any((flags.query, flags.account, flags.chat, flags.chat_type, flags.sender, flags.media, flags.after, flags.before)):
        raise Failure("Supply search text or a scope filter.", "invalid_arguments")
    if flags.before_exclusive and not flags.before:
        raise Failure("--before-exclusive requires --before.", "invalid_arguments")
    try:
        lower = timestamp({"timestamp": flags.after}).astimezone(timezone.utc) if flags.after else None
        upper = timestamp({"timestamp": flags.before}).astimezone(timezone.utc) if flags.before else None
        if lower and upper and lower > upper:
            raise ValueError()
        # Widen, never truncate the user's requested instant. Apply exact bounds
        # after fetching, including when the widened boundary consumes a page.
        date_after = (lower.replace(microsecond=0) - timedelta(seconds=1)).isoformat(timespec="seconds") if lower else None
        date_before = (upper.replace(microsecond=0) + timedelta(seconds=1)).isoformat(timespec="seconds") if upper else None
    except (Failure, ValueError, OverflowError):
        raise Failure("Use valid timezone-aware dates with start no later than end.", "invalid_arguments") from None
    deadline = time.monotonic() + flags.timeout / 1000
    requests = 0

    def get(path):
        nonlocal requests
        remaining = deadline - time.monotonic()
        if remaining <= 0 or requests >= flags.max_pages:
            raise Failure("Search reached its budget; narrow the window or explicitly increase --max-pages/--timeout. No complete result was returned.", "search_budget")
        requests += 1
        return runtime.api("GET", path, timeout=min(30, remaining))

    accounts = None
    chats = None
    if flags.limit:
        if flags.account:
            accounts = list(select_accounts(get("/v1/accounts"), [x for group in flags.account for x in group]))
        if flags.chat:
            chats = list(dict.fromkeys(chat_id(runtime, value, timeout=max(.001, deadline - time.monotonic()))
                                      for group in flags.chat for value in group))
    query = {"query": flags.query, "accountIDs": accounts, "chatIDs": chats,
             "chatType": flags.chat_type, "sender": flags.sender,
             "mediaTypes": [x for group in flags.media for x in group] if flags.media else None,
             "dateAfter": date_after, "dateBefore": date_before,
             "excludeLowPriority": str(flags.exclude_low_priority).lower(),
             "includeMuted": str(flags.include_muted).lower()}
    query = {key: value for key, value in query.items() if value is not None}
    items, seen, cursors = [], set(), set()
    exhausted = False
    while len(items) < flags.limit:
        query["limit"] = min(100, flags.limit - len(items))
        page = get("/v1/messages/search?" + urlencode(query, doseq=True))
        if not isinstance(page, dict) or not isinstance(page.get("items"), list) or not isinstance(page.get("hasMore"), bool):
            raise Failure("Server returned an invalid search page.", "invalid_response")
        progress = False
        consumed = 0
        for row in page["items"]:
            consumed += 1
            if not isinstance(row, dict) or any(not isinstance(row.get(key), str) or not row[key] for key in ("accountID", "chatID", "id")):
                raise Failure("Server returned an invalid search message.", "invalid_response")
            key = tuple(row[field] for field in ("accountID", "chatID", "id"))
            if key in seen:
                continue
            seen.add(key)
            progress = True
            moment = timestamp(row)
            if accounts is not None and row["accountID"] not in accounts:
                raise Failure("Search returned a different account; its scope cannot be trusted.", "search_scope_mismatch")
            if chats is not None and row["chatID"] not in chats:
                raise Failure("Search returned a different chat. Use an explicit member chat for merged conversations.", "search_scope_mismatch")
            if lower is not None and moment < lower:
                continue
            if upper is not None and (moment > upper or (flags.before_exclusive and moment == upper)):
                continue
            items.append(row)
            if len(items) == flags.limit:
                break
        exhausted = not page["hasMore"] and consumed == len(page["items"])
        if exhausted or len(items) == flags.limit:
            break
        cursor = page.get("oldestCursor")
        if not progress or not isinstance(cursor, str) or not cursor or cursor in cursors:
            raise Failure("Search pagination did not advance; no cursor was guessed.", "pagination_stalled")
        cursors.add(cursor)
        query.update(cursor=cursor, direction="before")
    items.sort(key=timestamp, reverse=True)  # Stable: tied timestamps do not imply causal order.
    return {"items": items, "coverage": {
        "count": len(items), "limitReached": len(items) >= flags.limit, "sourceExhausted": exhausted,
        "apiRequests": requests, "after": flags.after, "before": flags.before,
        "dateBounds": "[after, before)" if flags.before_exclusive else "[after, before]",
        "accountIDs": accounts, "chatIDs": chats, "query": flags.query,
        "chatType": flags.chat_type, "sender": flags.sender, "mediaTypes": query.get("mediaTypes"),
        "excludeLowPriority": flags.exclude_low_priority, "includeMuted": flags.include_muted,
        "note": "Only this Server's search index was inspected; source exhaustion does not prove complete historical sync."}}
