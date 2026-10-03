"""Contact lookup without CLI 0.6.2's ten-item, list-only resolution."""
import time
from urllib.parse import quote, urlencode

from beeper import Failure
from history import bounds, parser


def values(contact):
    return {str(contact[key]).casefold() for key in
            ("fullName", "name", "displayName", "phoneNumber", "username", "email")
            if contact.get(key) is not None}


def show(runtime, args):
    options = parser("contacts show")
    options.add_argument("id")
    options.add_argument("--account", action="append", nargs="+")
    options.add_argument("--query", help="Original search text when a network cannot look up opaque IDs")
    flags = options.parse_args(args[2:])
    bounds(flags)
    deadline = time.monotonic() + flags.timeout / 1000
    requests = 0

    def get(path):
        nonlocal requests
        remaining = deadline - time.monotonic()
        if requests >= flags.max_pages or remaining <= 0:
            raise Failure("Contact lookup reached its budget. Specify an account and the original --query, or increase --max-pages.", "contact_lookup_incomplete")
        requests += 1
        return runtime.api("GET", path, timeout=min(30, remaining))

    accounts = get("/v1/accounts")
    accounts = accounts.get("items", []) if isinstance(accounts, dict) else accounts
    if not isinstance(accounts, list) or any(not isinstance(a, dict) for a in accounts):
        raise Failure("Server returned an invalid account list.", "invalid_response")
    selected = {}
    selectors = [s for group in (flags.account or []) for s in group]
    for selector in selectors:
        matches = []
        exact_accounts = [a for a in accounts if a.get("accountID", a.get("id")) == selector]
        if exact_accounts:
            for account in exact_accounts:
                selected[selector] = account
            continue
        for account in accounts:
            labels = values(account) | values(account.get("user") or {})
            labels |= {str(v).casefold() for v in [account.get("network"),
                       (account.get("bridge") or {}).get("id"), (account.get("bridge") or {}).get("type")] if v is not None}
            if selector.casefold() in labels:
                matches.append(account)
        if not matches:
            raise Failure("Account selector did not resolve. Use an ID from accounts list.", "account_not_found")
        for account in matches:
            selected[account.get("accountID", account.get("id"))] = account
    if not selectors:
        selected = {a.get("accountID", a.get("id")): a for a in accounts}
    matches = {}

    def collect(items, account):
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            raise Failure("Server returned invalid contacts.", "invalid_response")
        for item in items:
            if flags.id in (item.get("id"), item.get("userID")) or flags.id.casefold() in values(item):
                ident = item.get("id", item.get("userID"))
                if not ident:
                    raise Failure("Matching contact has no identifier.", "invalid_response")
                matches[(account, ident)] = {"accountID": account, "contact": item}

    for account in selected:
        if not isinstance(account, str) or not account:
            raise Failure("Server returned an invalid account ID.", "invalid_response")
        path = "/v1/accounts/" + quote(account, safe="") + "/contacts"
        response = get(path + "?" + urlencode({"query": flags.query or flags.id}))
        collect(response.get("items"), account)
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
            collect(page.get("items"), account)
            if not isinstance(page.get("hasMore"), bool):
                raise Failure("Contact pagination metadata is missing.", "invalid_response")
            # Only an exact ID is intrinsically unique. A name may match on later pages.
            if any(key[0] == account and key[1] == flags.id for key in matches) or not page["hasMore"]:
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
