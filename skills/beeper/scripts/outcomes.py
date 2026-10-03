"""Dispatch one write and observe its effect using bounded, read-only rechecks."""
import time
from urllib.parse import quote

from beeper import Failure
from history import chat_id

OBSERVATION_DELAYS = (0, .5, 1, 2)
OBSERVATION_SECONDS = 8
GLOBAL_VALUES = {"timeout"}
GLOBAL_SWITCHES = {"json", "quiet", "full", "yes", "read-only", "help"}
SCHEMAS = {
    ("send", "text"): ({"to", "message", "pick", "reply-to", "mention", "wait-timeout"}, {"wait", "no-preview"}, {"to", "message"}),
    ("send", "file"): ({"to", "file", "caption", "filename", "mime", "pick", "reply-to", "wait-timeout"}, {"wait"}, {"to", "file"}),
    ("send", "voice"): ({"to", "file", "filename", "mime", "duration", "pick", "reply-to", "wait-timeout"}, {"wait"}, {"to", "file"}),
    ("send", "sticker"): ({"to", "file", "filename", "mime", "pick", "reply-to", "wait-timeout"}, {"wait"}, {"to", "file"}),
    ("send", "react"): ({"to", "id", "reaction", "pick", "transaction"}, set(), {"to", "id", "reaction"}),
    ("send", "unreact"): ({"to", "id", "reaction", "pick", "transaction"}, set(), {"to", "id", "reaction"}),
    ("messages", "edit"): ({"chat", "id", "message", "pick"}, set(), {"chat", "id", "message"}),
    ("messages", "delete"): ({"chat", "id", "pick"}, {"for-everyone"}, {"chat", "id"}),
}


def is_message_write(args):
    return tuple(args[:2]) in SCHEMAS


def write_options(args):
    """Parse option positions, preserving flag-like values and rejecting overrides."""
    values, switches, required = SCHEMAS[tuple(args[:2])]
    values, switches = values | GLOBAL_VALUES, switches | GLOBAL_SWITCHES
    flags, native = {}, list(args[:2])
    index = 2
    while index < len(args):
        token = args[index]
        name, equals, value = token[2:].partition("=") if token.startswith("--") else ("", "", "")
        if name not in values | switches:
            raise Failure("Unsupported write option. Use long options from command --help; target overrides are disabled.", "invalid_arguments")
        if name in flags and name != "mention":
            raise Failure("Supply each write option once (only --mention is repeatable).", "invalid_arguments")
        if name in switches:
            if equals and value not in ("true", "false"):
                raise Failure("Boolean options accept only true or false.", "invalid_arguments")
            flags[name] = value != "false"
            if flags[name]:
                native.append("--" + name)
        else:
            if not equals:
                index += 1
                if index >= len(args):
                    raise Failure("A write option is missing its value.", "invalid_arguments")
                value = args[index]
            if name == "mention":
                flags.setdefault(name, []).append(value)
            else:
                flags[name] = value
            native.append("--" + name + "=" + value)
        index += 1
    if not flags.get("help"):
        if any(key not in flags for key in required):
            raise Failure("Required write options are missing. Check command --help.", "invalid_arguments")
        if any(not flags.get(key) for key in required - {"message"}):
            raise Failure("Identifiers and file paths must not be empty.", "invalid_arguments")
        if "pick" in flags and (not flags["pick"].isdecimal() or int(flags["pick"]) < 1):
            raise Failure("Use a positive --pick index.", "invalid_arguments")
    return flags, native


def observation(state, reason, **details):
    return {"state": state, "reason": reason, "retrySafe": False,
            "scope": "Server-observed state; delivery and recipient reads are not verified",
            "deliveryVerified": False, **details}


def run_write(runtime, args):
    flags, native = write_options(args)
    if flags.get("help"):
        return runtime.cli(native)
    runtime.writable()
    if flags.get("read-only"):
        raise Failure("Read-only mode prevents message changes.", "read_only")
    key = "to" if args[0] == "send" else "chat"
    chat = chat_id(runtime, flags[key], int(flags["pick"]) if flags.get("pick") else None)
    native = ["--" + key + "=" + chat if token.startswith("--" + key + "=") else token for token in native]
    try:
        # Oclif 0.6.2 rejects some option-looking text even in --message=VALUE.
        # Select this path before any write; never retry a failed CLI request.
        if args[1] in {"text", "edit"} and flags["message"].startswith("-"):
            path = "/v1/chats/" + quote(chat, safe="") + "/messages"
            body = {"text": flags["message"]}
            if args[1] == "edit":
                data = runtime.api("PUT", path + "/" + quote(flags["id"], safe=""), body)
            else:
                if "reply-to" in flags:
                    body["replyToMessageID"] = flags["reply-to"]
                if "mention" in flags:
                    body["mentions"] = flags["mention"]
                if flags.get("no-preview"):
                    body["disableLinkPreview"] = True
                reply = runtime.api("POST", path, body)
                data = {"accepted": True, "state": "accepted", **reply} if isinstance(reply, dict) else reply
        else:
            data = runtime.cli(native)
    except Failure as error:
        error.write_outcome = observation("unknown", "Command did not establish its final outcome. Reconcile before retrying.",
                                          chatID=chat, messageID=flags.get("id"))
        raise
    result = dict(data) if isinstance(data, dict) else {"result": data}
    result["writeOutcome"] = observe(runtime, args[1], chat, data, flags)
    return result


def observe(runtime, operation, chat, data, expected):
    data = data if isinstance(data, dict) else {}
    if data.get("chatID", chat) != chat:
        return observation("unknown", "Returned chat differs from the request. Resolve an explicit network member chat before further writes.",
                           chatID=chat, observedChatID=data.get("chatID"), scopeMismatch=True, readAttempts=0)
    message = data.get("message") if isinstance(data.get("message"), dict) else {}
    sending = operation in {"text", "file", "voice", "sticker"}
    ident = (message.get("id") or data.get("pendingMessageID") or data.get("id")) if sending else expected.get("id")
    if not isinstance(ident, str) or not ident:
        return observation("accepted", "Command returned without a message identifier for observation.", chatID=chat, readAttempts=0)
    known_final_id = (message.get("id") or data.get("id")) if sending else ident
    deadline = time.monotonic() + OBSERVATION_SECONDS
    attempts = 0
    accounts_cache = None
    last = observation("unknown", "Read-back has not established the effect.", chatID=chat, messageID=ident)

    def get(path):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise Failure("Observation time budget expired.", "timeout")
        return runtime.api("GET", path, timeout=min(2, remaining))

    def accounts():
        nonlocal accounts_cache
        if accounts_cache is None:
            accounts_cache = get("/v1/accounts")
        return accounts_cache

    for delay in OBSERVATION_DELAYS:
        if time.monotonic() + delay >= deadline:
            break
        if delay:
            time.sleep(delay)
        attempts += 1
        try:
            row = get("/v1/chats/" + quote(chat, safe="") + "/messages/" + quote(ident, safe=""))
            last, retry = assess(operation, chat, known_final_id, row, expected, accounts)
        except Failure as error:
            last = observation("unknown", "Read-back was unavailable after the write. No write was repeated.",
                               chatID=chat, messageID=ident, readErrorCode=error.code)
            retry = error.code not in (401, 403, "http_401", "http_403", "unauthorized", "forbidden")
        except Exception:
            last = observation("unknown", "Read-back had an unexpected shape; no write was repeated.", chatID=chat, messageID=ident)
            retry = False
        if not retry:
            return {**last, "readAttempts": attempts, "observationExhausted": False}
    return {**last, "readAttempts": attempts, "observationExhausted": True}


def text_matches(actual, expected):
    # Only equivalent transport newlines are normalized. Stripping Markdown/HTML
    # could falsely confirm changed content, links, mentions or formatting.
    return isinstance(actual, str) and actual.replace("\r\n", "\n") == expected.replace("\r\n", "\n")


def assess(operation, chat, known_final_id, row, expected, accounts):
    sending = operation in {"text", "file", "voice", "sticker"}
    if not isinstance(row, dict) or row.get("chatID") != chat or not isinstance(row.get("id"), str) or not row["id"]:
        return observation("unknown", "Read-back did not identify a message in the requested chat. Resolve merged chats to a network member.",
                           chatID=chat, messageID=known_final_id, scopeMismatch=True), False
    if known_final_id and row["id"] != known_final_id:
        return observation("unknown", "Read-back returned a different message.", chatID=chat, messageID=known_final_id), False
    details = {"chatID": chat, "messageID": row["id"]}
    status = (row.get("sendStatus") or {}).get("status")
    details["bridgeSendStatus"] = status or "unavailable"
    if sending and status in {"FAIL_PERMANENT", "FAIL_RETRIABLE", "FAILED"}:
        return observation("failed", "Server reports a send failure. No automatic retry was made.", **details), False
    if sending and status in {"PENDING", "IN_PROGRESS"}:
        return observation("pending", "Server still reports the send as pending.", **details), True
    if operation == "delete":
        deleted, hidden = row.get("isDeleted") is True, row.get("isHidden") is True
        matched = deleted or (hidden and not expected.get("for-everyone"))
        return observation("confirmed" if matched else "unknown",
            "Deletion or local hiding marker observed; remote erasure is not established." if matched else "No requested deletion marker was observed.",
            deleted=deleted, hidden=hidden, textRetained=bool(row.get("text")), remoteErasureVerified=False, **details), not matched
    if row.get("isDeleted") or row.get("isHidden"):
        return observation("unknown", "Message is deleted or hidden; requested content cannot be confirmed.", **details), False
    if operation in {"react", "unreact"}:
        listed = accounts()
        listed = listed.get("items", []) if isinstance(listed, dict) else listed
        account = next((a for a in listed if a.get("accountID", a.get("id")) == row.get("accountID")), {})
        actor = (account.get("user") or {}).get("id")
        reactions = row.get("reactions")
        if not actor or not isinstance(reactions, list):
            return observation("unknown", "Own reaction identity or reaction state is unavailable.", **details), True
        present = any(r.get("participantID") == actor and r.get("reactionKey") == expected.get("reaction") for r in reactions)
        matched = present if operation == "react" else not present
        return observation("confirmed" if matched else "unknown", "Own reaction state observed." if matched else "Own reaction state does not yet match.", **details), not matched
    checks = {"ownMessage": row.get("isSender") is True}
    if expected.get("message") is not None:
        checks["textMatches"] = text_matches(row.get("text"), expected["message"])
    if expected.get("reply-to") is not None:
        checks["replyMatches"] = row.get("linkedMessageID") == expected["reply-to"]
    if expected.get("mention"):
        checks["mentionsMatch"] = isinstance(row.get("mentions"), list) and set(row["mentions"]) == set(expected["mention"])
    if operation in {"file", "voice", "sticker"}:
        attachments = row.get("attachments") or []
        checks["attachmentVisible"] = bool(attachments)
        if expected.get("caption") is not None:
            checks["captionMatches"] = text_matches(row.get("text"), expected["caption"])
        if operation in {"voice", "sticker"}:
            checks["mediaSubtypeMatches"] = row.get("type") == {"voice": "VOICE", "sticker": "STICKER"}[operation] or any(
                a.get("isVoiceNote" if operation == "voice" else "isSticker") is True for a in attachments)
        matched = all(checks.values())
        return observation("accepted" if matched else "unknown", "Attachment fields checked; file bytes remain unverified.",
                           checks=checks, fileIdentityVerified=False, **details), not matched
    if not all(checks.values()):
        return observation("unknown", "Requested text, author, mentions or reply linkage is not yet established. Rich-text conversion may prevent exact text comparison.",
                           checks=checks, contentVerified=False, **details), True
    return observation("confirmed", "Requested message fields observed on Server; bridge status is reported separately from recipient receipts.",
                       checks=checks, contentVerified=True, **details), False
