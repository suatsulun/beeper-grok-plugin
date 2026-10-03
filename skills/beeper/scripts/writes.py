"""Non-retrying message mutations using the official HTTP contract."""
import os
from pathlib import Path
import re
import secrets
import stat
from urllib.parse import quote

from beeper import Failure

MAX_FILE_BYTES = 500 * 1024 * 1024


def validate(flags):
    # Validate before uploading or sending; CLI parsing no longer does it for us.
    for key in ("wait-timeout", "duration"):
        if key in flags:
            if not re.fullmatch(r"\d+", flags[key]):
                raise Failure("Use integer milliseconds for --wait-timeout and seconds for --duration.", "invalid_arguments")
            flags[key] = int(flags[key])
    if "wait-timeout" in flags and not 1 <= flags["wait-timeout"] <= 300000:
        raise Failure("Use --wait-timeout 1..300000 milliseconds.", "invalid_arguments")
    timeout = 30
    if "timeout" in flags:
        match = re.fullmatch(r"(\d+(?:\.\d+)?)(ms|s|m|h)?", flags["timeout"])
        if not match:
            raise Failure("Use --timeout such as 30000, 30s or 2m.", "invalid_arguments")
        timeout = float(match[1]) * {None: .001, "ms": .001, "s": 1, "m": 60, "h": 3600}[match[2]]
        if not 0 < timeout <= 300:
            raise Failure("Write --timeout must be above zero and at most five minutes.", "invalid_arguments")
    return timeout


def upload(runtime, flags, operation, timeout):
    path = Path(flags["file"]).expanduser()
    mime = flags.get("mime", {"voice": "audio/ogg", "sticker": "image/webp"}.get(operation))
    boundary = "beeper-" + secrets.token_hex(24)
    fields = {"fileName": flags.get("filename", path.name)}
    if mime is not None:
        fields["mimeType"] = mime
    prefix = b"".join((f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n'
                       + value + "\r\n").encode() for key, value in fields.items())
    # The real UTF-8 filename is a form value, never interpolated into a header.
    prefix += (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="upload"\r\n'
               'Content-Type: application/octet-stream\r\n\r\n').encode()
    suffix = f"\r\n--{boundary}--\r\n".encode()
    try:
        if not path.is_file():
            raise Failure("The attachment must be a readable regular file.", "invalid_attachment")
        with path.open("rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_FILE_BYTES:
                raise Failure("The attachment must be a regular file of at most 500 MiB.", "invalid_attachment")

            def chunks():
                yield prefix
                remaining = info.st_size
                while remaining:
                    chunk = stream.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise Failure("Attachment changed during upload. No message was sent.", "attachment_changed")
                    remaining -= len(chunk)
                    yield chunk
                if stream.read(1):
                    raise Failure("Attachment changed during upload. No message was sent.", "attachment_changed")
                yield suffix

            result = runtime.api_request("POST", "/v1/assets/upload", data=chunks(), timeout=timeout,
                                         content_type="multipart/form-data; boundary=" + boundary,
                                         content_length=len(prefix) + info.st_size + len(suffix))
    except OSError:
        raise Failure("Attachment could not be read. No message was sent.", "invalid_attachment") from None
    if not isinstance(result, dict) or not isinstance(result.get("uploadID"), str) or not result["uploadID"]:
        raise Failure("Upload did not return an upload ID. No message was sent.", "invalid_upload_response")
    attachment = {key: result[key] for key in ("uploadID", "fileName", "mimeType", "duration") if result.get(key) is not None}
    if mime is not None:
        attachment["mimeType"] = mime
    if "duration" in flags:
        attachment["duration"] = flags["duration"]
    if result.get("width") and result.get("height"):
        attachment["size"] = {"width": result["width"], "height": result["height"]}
    if operation in ("voice", "sticker"):
        attachment["type"] = {"voice": "voice-note", "sticker": "sticker"}[operation]
    return attachment


def dispatch(runtime, operation, chat, flags, timeout):
    path = "/v1/chats/" + quote(chat, safe="") + "/messages"
    if operation in ("text", "file", "voice", "sticker"):
        body = {"text": flags.get("message", flags.get("caption", ""))}
        if operation != "text":
            body["attachment"] = upload(runtime, flags, operation, timeout)
        for option, field in (("reply-to", "replyToMessageID"), ("mention", "mentions")):
            if option in flags:
                body[field] = flags[option]
        if flags.get("no-preview"):
            body["disableLinkPreview"] = True
        ack = runtime.api("POST", path, body, timeout=timeout)
        return {"accepted": True, "state": "accepted", **ack} if isinstance(ack, dict) else ack
    path += "/" + quote(flags["id"], safe="")
    if operation == "edit":
        return runtime.api("PUT", path, {"text": flags["message"]}, timeout=timeout)
    if operation == "delete":
        everyone = bool(flags.get("for-everyone"))
        runtime.api("DELETE", path + ("?forEveryone=true" if everyone else ""), timeout=timeout)
        return {"chatID": chat, "messageID": flags["id"], "forEveryone": everyone}
    if operation == "react":
        body = {"reactionKey": flags["reaction"]}
        if "transaction" in flags:
            body["transactionID"] = flags["transaction"]
        return runtime.api("POST", path + "/reactions", body, timeout=timeout)
    # The official removal endpoint has no transaction-ID parameter.
    return runtime.api("DELETE", path + "/reactions/" + quote(flags["reaction"], safe=""), timeout=timeout)
