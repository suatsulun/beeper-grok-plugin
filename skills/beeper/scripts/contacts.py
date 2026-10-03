"""Contact lookup without CLI 0.6.2's ten-item, list-only resolution."""
import time
from urllib.parse import quote, urlencode

from beeper import Failure
from history import bounds, parser


def values(contact):
    return {str(contact[key]).casefold() for key in
            ("fullName", "name", "displayName", "phoneNumber", "username", "email")
            if contact.get(key) is not None}


def select_accounts(accounts, selectors):
    accounts = accounts.get("items", []) if isinstance(accounts, dict) else accounts
    if not isinstance(accounts, list) or any(not isinstance(a, dict) for a in accounts):
        raise Failure("Server returned an invalid account list.", "invalid_response")
    selected = {}
    for selector in selectors:
        exact = [a for a in accounts if a.get("accountID", a.get("id")) == selector]
        matches = exact or [a for a in accounts if selector.casefold() in (
            values(a) | values(a.get("user") or {}) | {str(v).casefold() for v in (
                a.get("network"), (a.get("user") or {}).get("id"),
                (a.get("bridge") or {}).get("id"), (a.get("bridge") or {}).get("type")) if v is not None})]
        if not matches:
            raise Failure("Account selector did not resolve. Use an ID from accounts list.", "account_not_found")
        for account in matches:
            selected[account.get("accountID", account.get("id"))] = account
    if not selectors:
        selected = {a.get("accountID", a.get("id")): a for a in accounts}
    if any(not isinstance(key, str) or not key for key in selected):
        raise Failure("Server returned an invalid account ID.", "invalid_response")
    return selected


def show(runtime, args):
    options = parser("contacts show")
    options.add_argument("id")
    options.add_argument("--account", action="append", nargs="+")
    options.add_argument("--query", help="Original search text when a network cannot look up opaque IDs")
    options.add_argument("--by-label", action="store_true", help="Explicitly resolve a name, phone or handle instead of an exact ID")
    flags = options.parse_args(args[2:])
    bounds(flags)
    if flags.by_label and flags.query is not None:
        raise Failure("--query is an exact-ID search hint; do not combine it with --by-label.", "invalid_arguments")
    deadline = time.monotonic() + flags.timeout / 1000
    requests = 0

    def get(path):
        nonlocal requests
        remaining = deadline - time.monotonic()
        if requests >= flags.max_pages or remaining <= 0:
            raise Failure("Contact lookup reached its budget. Specify an account and the original --query, or increase --max-pages.", "contact_lookup_incomplete")
        requests += 1
        return runtime.api("GET", path, timeout=min(30, remaining))

    selectors = [s for group in (flags.account or []) for s in group]
    selected = select_accounts(get("/v1/accounts"), selectors)
    matches = {}

    def collect(items, account):
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            raise Failure("Server returned invalid contacts.", "invalid_response")
        for item in items:
            matched = (flags.id.casefold() in values(item) if flags.by_label else
                       flags.id in (item.get("id"), item.get("userID")))
            if matched:
                ident = item.get("id") or item.get("userID")
                if not isinstance(ident, str) or not ident:
                    raise Failure("Matching contact has no identifier.", "invalid_response")
                matches[(account, ident)] = {"accountID": account, "contact": item}

    for account in selected:
        if not isinstance(account, str) or not account:
            raise Failure("Server returned an invalid account ID.", "invalid_response")
        path = "/v1/accounts/" + quote(account, safe="") + "/contacts"
        query, visited = {"query": flags.query or flags.id}, set()
        while True:
            response = get(path + "?" + urlencode(query))
            if not isinstance(response, dict):
                raise Failure("Server returned invalid contacts.", "invalid_response")
            collect(response.get("items"), account)
            if (not flags.by_label and any(key[0] == account for key in matches)) or not response.get("hasMore"):
                break
            cursor = response.get("oldestCursor")
            if not isinstance(cursor, str) or not cursor or cursor in visited:
                raise Failure("Contact search pagination did not advance.", "pagination_stalled")
            visited.add(cursor)
            query.update(cursor=cursor, direction="before")
        if any(key[0] == account for key in matches):
            continue
        # Some providers do not search opaque IDs. Enumerate bounded real pages,
        # rather than filtering the list endpoint with an unsupported identifier.
        cursor, visited = None, set()
        while True:
            query = {"limit": 100}
            if cursor is not None:
                query.update(cursor=cursor, direction="before")
            page = get(path + "/list?" + urlencode(query))
            if not isinstance(page, dict):
                raise Failure("Server returned invalid contacts.", "invalid_response")
            collect(page.get("items"), account)
            if not isinstance(page.get("hasMore"), bool):
                raise Failure("Contact pagination metadata is missing.", "invalid_response")
            # Only an exact ID is intrinsically unique. A name may match on later pages.
            if (not flags.by_label and any(key[0] == account for key in matches)) or not page["hasMore"]:
                break
            cursor = page.get("oldestCursor")
            if not isinstance(cursor, str) or not cursor or cursor in visited:
                raise Failure("Contact pagination did not advance.", "pagination_stalled")
            visited.add(cursor)
    if len(matches) > 1:
        raise Failure("More than one contact matches. Use an exact contact ID and account from search.", "ambiguous_contact")
    if not matches:
        raise Failure("Contact could not be resolved from available data. Supply --account and --query with the original search text; enumeration may be limited.", "contact_unresolved")
    return next(iter(matches.values()))
