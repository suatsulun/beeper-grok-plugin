"""One write, one bounded read-back, and an honest description of the outcome.

No retries, cleanup deletes, receipts, or stored message bodies. A confirmed
outcome describes Server-observed state, never delivery/read on another device.
"""
from urllib.parse import quote

from beeper import Failure
from history import chat_id


def is_message_write(args):
    return (args[:1] == ["send"] and len(args) > 1 and args[1] in
            {"text", "file", "voice", "sticker", "react", "unreact"}) or args[:2] in (
                ["messages", "edit"], ["messages", "delete"])


def option(args, name):
    values = []
    for index, arg in enumerate(args):
        if arg == name and index + 1 < len(args):
            values.append(args[index + 1])
        elif arg.startswith(name + "="):
            values.append(arg[len(name) + 1:])
    if len(values) > 1:
        raise Failure("Repeated write options are ambiguous; supply each option once.", "invalid_arguments")
    return values[0] if values else None


def replace_option(args, name, value):
    result = list(args)
    for index, arg in enumerate(result):
        if arg == name:
            result[index + 1] = value
        elif arg.startswith(name + "="):
            result[index] = name + "=" + value
    return result


def observation(state, reason, **details):
    return {"state": state, "reason": reason, "retrySafe": False,
            "scope": "Server-observed state; delivery and recipient reads are not verified", **details}


def run_write(runtime, args):
    key = "--to" if args[0] == "send" else "--chat"
    selector = option(args, key)
    if not selector:
        raise Failure("A write needs an explicit chat.", "invalid_arguments")
    pick = option(args, "--pick")
    if pick is not None and not pick.isdecimal():
        raise Failure("Use a positive --pick index.", "invalid_arguments")
    chat = chat_id(runtime, selector, int(pick) if pick else None)
    args = replace_option(args, key, chat)
    # Read expected values before dispatch; invalid repeated options must not fail
    # only after the write has already happened.
    expected = {name: option(args, "--" + name) for name in ("id", "message", "reply-to", "reaction", "caption")}
    try:
        data = runtime.cli(args)
    except Failure as error:
        error.write_outcome = observation("unknown", "Command did not establish its final outcome. Reconcile before retrying.")
        raise
    result = dict(data) if isinstance(data, dict) else {"result": data}
    try:
        result["writeOutcome"] = verify(runtime, args[1], chat, data, expected)
    except Exception:
        # A failed GET must not turn an accepted write into a safe-to-retry failure.
        result["writeOutcome"] = observation("unknown", "Read-back failed after the command returned. Do not repeat the write blindly.")
    return result


def verify(runtime, operation, chat, data, expected):
    data = data if isinstance(data, dict) else {}
    if data.get("chatID", chat) != chat:
        return observation("unknown", "Server routed to a different chat; inspect the returned result before continuing.")
    message = data.get("message") if isinstance(data.get("message"), dict) else {}
    sending = operation in {"text", "file", "voice", "sticker"}
    ident = (message.get("id") or data.get("pendingMessageID") or data.get("id")) if sending else expected["id"]
    if not isinstance(ident, str) or not ident:
        return observation("accepted", "Command returned, but no message identifier is available for read-back.")
    row = runtime.api("GET", "/v1/chats/" + quote(chat, safe="") + "/messages/" + quote(ident, safe=""), timeout=10)
    if not isinstance(row, dict) or row.get("chatID") != chat or not row.get("id"):
        return observation("unknown", "Read-back did not identify a message in the requested chat.")
    # Pending IDs can resolve to a final ID for sends. Existing-message operations
    # must not validate an unrelated row returned by a misbehaving backend.
    known_final_id = message.get("id") or data.get("id") if sending else ident
    if known_final_id and row["id"] != known_final_id:
        return observation("unknown", "Read-back returned a different message.")
    details = {"chatID": chat, "messageID": row["id"]}
    status = (row.get("sendStatus") or {}).get("status")
    if sending and status in {"FAIL_PERMANENT", "FAIL_RETRIABLE", "FAILED"}:
        return observation("failed", "Server reports a send failure. No automatic retry was made.", **details)
    if sending and status in {"PENDING", "IN_PROGRESS"}:
        return observation("pending", "Server still reports the send as pending.", **details)
    if operation == "delete":
        deleted = row.get("isDeleted") is True
        hidden = row.get("isHidden") is True
        return observation("confirmed" if deleted else "unknown",
            "Deletion marker observed; remote erasure is not established." if deleted else "No deletion marker was observed.",
            deleted=deleted, hidden=hidden, textRetained=bool(row.get("text")), remoteErasureVerified=False, **details)
    if row.get("isDeleted") or row.get("isHidden"):
        return observation("unknown", "Message is deleted or hidden; the requested content cannot be confirmed.", **details)
    if operation in {"react", "unreact"}:
        accounts = runtime.api("GET", "/v1/accounts", timeout=10)
        accounts = accounts.get("items", []) if isinstance(accounts, dict) else accounts
        account = next((a for a in accounts if a.get("accountID", a.get("id")) == row.get("accountID")), {})
        actor = (account.get("user") or {}).get("id")
        reactions = row.get("reactions")
        if not actor or not isinstance(reactions, list):
            return observation("unknown", "Own reaction identity or reaction state is unavailable.", **details)
        present = any(r.get("participantID") == actor and r.get("reactionKey") == expected["reaction"] for r in reactions)
        matched = present if operation == "react" else not present
        return observation("confirmed" if matched else "unknown", "Own reaction state observed." if matched else "Own reaction state does not yet match.", **details)
    checks = {"ownMessage": row.get("isSender") is True}
    if expected["message"] is not None:
        checks["textMatches"] = row.get("text") == expected["message"]
    if expected["reply-to"] is not None:
        checks["replyMatches"] = row.get("linkedMessageID") == expected["reply-to"]
    if operation in {"file", "voice", "sticker"}:
        checks["attachmentVisible"] = bool(row.get("attachments"))
        if expected["caption"] is not None:
            checks["captionMatches"] = row.get("text") == expected["caption"]
        # Presence alone does not verify the file bytes or voice/sticker semantics.
        return observation("accepted" if all(checks.values()) else "unknown",
            "Attachment state checked; file identity and media subtype remain unverified.", checks=checks, **details)
    if not all(checks.values()):
        return observation("unknown", "Read-back does not establish the requested text, author, or reply linkage.", checks=checks, **details)
    state = "confirmed" if operation == "edit" or status == "SUCCESS" else "accepted"
    return observation(state, "Requested message fields observed; no recipient receipt is inferred.", checks=checks, **details)
