"""Bounded, sequential CLI reads. No daemon, credentials on disk, or write retries."""
import json
import os
import signal
import subprocess

from beeper import Failure, TARGET

READS = {
    ("chats", "list"), ("chats", "search"), ("chats", "show"),
    ("messages", "list"), ("messages", "search"), ("messages", "show"),
    ("contacts", "list"), ("contacts", "search"), ("contacts", "show"),
    ("version",),
}


def validate(requests):
    if not isinstance(requests, list) or not 1 <= len(requests) <= 32:
        raise Failure("Provide between 1 and 32 independent read requests.", "usage")
    prepared = []
    ids = set()
    for index, request in enumerate(requests):
        if not isinstance(request, dict) or set(request) - {"id", "args"}:
            raise Failure("Each read request accepts only id and args.", "usage")
        ident = request.get("id", index)
        if type(ident) not in (str, int) or ident in ids:
            raise Failure("Read request IDs must be unique strings or integers.", "usage")
        ids.add(ident)
        args = request.get("args")
        if not isinstance(args, list) or not args or any(not isinstance(a, str) or "\0" in a for a in args):
            raise Failure("Read request args must be a nonempty string array.", "usage")
        if tuple(args[:2]) not in READS and tuple(args[:1]) != ("version",):
            raise Failure("Batch supports only chats/messages/contacts list, search, show, and version. Use cli for other commands.", "usage")
        if any(a == "--" or a.startswith(("--target", "--base-url", "--debug", "--log-level")) or (a.startswith("-t") and not a.startswith("--")) for a in args):
            raise Failure("Target, debug overrides, and argument terminators are not supported in a batch.", "usage")
        prepared.append({"id": ident, "args": [*args, "--target", TARGET, "--read-only", "--json"]})
    return prepared


def execute(runtime, requests, timeout):
    prepared = validate(requests)  # Validate the entire batch before launching anything.
    if not runtime.binary.exists():
        raise Failure("Run bootstrap to install the Beeper CLI.", "not_installed")
    env = runtime.env()
    # Use the official CLI RPC protocol without requiring a modified binary.
    env.update(BEEPER_READONLY="1", BEEPER_SKIP_NEW_VERSION_CHECK="true")
    child = subprocess.Popen([str(runtime.binary), "rpc"], env=env, stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        stdout, stderr = child.communicate("".join(json.dumps(row) + "\n" for row in prepared), timeout=timeout)
    except subprocess.TimeoutExpired:
        # Kill the RPC process and any fallback subprocess, without touching Server.
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        child.communicate()
        raise Failure("Read batch timed out; no requests were retried.", "timeout") from None
    try:
        replies = [json.loads(line) for line in stdout.splitlines() if line.strip()]
        if child.returncode or len(replies) != len(prepared):
            raise ValueError()
        output = []
        for request, reply in zip(prepared, replies):
            if not isinstance(reply, dict) or reply.get("id") != request["id"]:
                raise ValueError()
            if not isinstance(reply.get("stdout"), str) or not isinstance(reply.get("stderr"), str) or type(reply.get("code")) is not int:
                raise ValueError()
            result = subprocess.CompletedProcess([], reply["code"], reply["stdout"], reply["stderr"])
            try:
                data = runtime.cli_result(request["args"], result)
                output.append({"id": request["id"], "success": True, "data": data})
            except Failure as exc:
                output.append({"id": request["id"], "success": False, "error": {"code": exc.code, "message": str(exc)}})
        return {"results": output, "allSucceeded": all(row["success"] for row in output)}
    except (ValueError, TypeError):
        raise Failure("CLI returned an incomplete or invalid RPC response; raw output was withheld and nothing was retried.", "cli_error") from None
