---
name: beeper-chats
description: Find Beeper contacts, start conversations on existing accounts, and organize chats with archive, mute, pin, priority, read state, drafts, reminders, names, or descriptions.
---

# Contacts and chats

Read [Beeper](../beeper/SKILL.md) first. `HELPER` is `../beeper/scripts/beeper.py`, resolved from this skill's directory. Discover the account and exact chat before making changes.

```sh
python3 "$HELPER" cli accounts list
python3 "$HELPER" cli contacts search 'Alice' --account 'ACCOUNT_ID'
python3 "$HELPER" cli chats search 'Project'
python3 "$HELPER" cli chats show --chat 'CHAT_ID'
python3 "$HELPER" cli chats list --unread --limit 30
```

Contact enumeration may be limited by the network. Distinguish a contact from a chat, and show enough account/context to disambiguate people with the same name. `contacts list` and `contacts show` provide additional detail; use `--help` for exact flags.

For a new conversation the user requested, use `chats start 'RETURNED_USER_ID' --account 'ACCOUNT_ID'`. Always choose the account explicitly; the CLI otherwise may choose Matrix. Creating a conversation does not authorize sending text. To add a network account, tell the user to do that in Beeper; this plugin doesn't perform network sign-in.

Use `python3 "$HELPER" cli COMMAND --help` for the selected command, then perform the requested change:

| Action | Native command |
| --- | --- |
| Archive / restore | `chats archive`, `chats unarchive` |
| Pin / unpin | `chats pin`, `chats unpin` |
| Mute / unmute | `chats mute`, `chats unmute` |
| Mark read / unread | `chats mark-read`, `chats mark-unread` |
| Inbox / low priority | `chats priority --level inbox`, `chats priority --level low` |
| Rename / describe / change avatar | `chats rename`, `chats description`, `chats avatar` |
| Save or clear a draft | `chats draft` |
| Set / remove a Beeper reminder | `chats remind`, `chats unremind` |
| Set disappearing messages | `chats disappear` |
| Override quiet notifications | `chats notify-anyway` |

Each command takes `--chat CHAT_ID`; other flags come from its help. Confirm scope when “all” could affect more chats than the user intended. Keep reads read-only: don't mark chats read, archive, or mute them just because you summarized them. Renaming, avatar changes, disappearing-message settings, and read receipts can affect other people; use only the action the user requested.

Check the returned chat state after a mutation. Network support varies. Desktop UI actions such as `chats focus` do not provide a useful UI on a headless cloud Server; return the chat details or available link instead. A Beeper reminder is separate from a Grok scheduled notification. Do not claim either one schedules the other.

## Reliable contact lookup and reversible tests

The helper's `contacts show ID --account ACCOUNT_ID` always requires an exact, case-sensitive ID. If a network cannot search an opaque ID, add `--query 'ORIGINAL_SEARCH_TEXT'` from the search that returned it. The query is only a search hint; a name, phone, or handle can never replace that ID. For an intentional label lookup, use `contacts show 'NAME_OR_PHONE' --by-label --account ACCOUNT_ID` instead. Do not combine `--by-label` with `--query`. Duplicate labels or cross-account matches require disambiguation. `contact_unresolved` and `contact_lookup_incomplete` do not mean the person does not exist. Do not repeatedly discover accounts or substitute a different recipient to conceal a lookup failure.

For merged conversations, resolve and show the exact network member chat and account before a write. The helper deliberately stops on a different returned chat or mixed-account history. Do not remove the scope check or follow an unexpected routed chat automatically.

For an authorized reversible test, capture original settings immediately before changing them and restore those exact values. Defaults such as unmuted, unpinned, inbox priority, and empty draft are not a restoration. If the original value cannot be expressed by the CLI, skip that test. Read receipts and externally visible changes may not be reversible.
