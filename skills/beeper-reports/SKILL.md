---
name: beeper-reports
description: Summarize Beeper conversations, report activity or unanswered messages, extract decisions and tasks, and export messages from existing accounts.
---

# Reports and exports

Read [Beeper](../beeper/SKILL.md) and [Messages](../beeper-messages/SKILL.md). `HELPER` is `../beeper/scripts/beeper.py`, resolved from this directory.

Use the requested accounts, chats, dates, and timezone. Infer them from conversation context when clear. For “what did I miss today,” use today in the user's timezone and report that scope. Start with a bounded read; don't export the whole account to answer a small question.

```sh
python3 "$HELPER" cli messages search --account 'ACCOUNT_ID' --after 'ISO_START' --before 'ISO_END' --limit 200
python3 "$HELPER" cli messages list --chat 'CHAT_ID' --limit 100
```

For decisions, tasks, and unanswered questions, read surrounding conversation, including the user's replies. Received-only data cannot establish whether they answered. Attribute each item to its speaker and date, include chat/message IDs or returned links for traceability, and distinguish explicit commitments from inference. Don't invent attachment contents or summarize inaccessible messages.

A useful report gives the main developments, requested counts, open questions, and next actions, followed by its coverage and any gaps. Counts apply only to retrieved data. If a limit is reached, page further within the requested scope or label the result partial. Sort by actual timestamps and de-duplicate account/chat/message IDs. Don't imply a search index contains all historical messages.

For exact date-bound exports of one chat:

```sh
python3 "$HELPER" cli messages export --chat 'CHAT_ID' --after 'ISO_START' --before 'ISO_END' --output '/private/output/chat.json'
```

For a requested multi-chat archive:

```sh
python3 "$HELPER" cli export --account 'ACCOUNT_ID' --out '/private/output/beeper-export' --no-attachments --quiet
```

The full export produces transcripts, message JSON, a manifest, and resumable checkpoints. Omit `--no-attachments` only when attachments are wanted. Use `--chat` to narrow it and `--limit-chats` / `--limit-messages` for an explicitly partial export. Full export has no date flags in CLI 0.6.2; use per-chat exports when dates matter. An interrupted export is incomplete; resume the same output directory and inspect the manifest. A completed command does not establish complete history beyond what Server exposes.

Keep reports and exports in a private persistent output directory, outside the plugin checkout. Attach only the requested report or export through Grok's normal user-facing file tools. Never include Server backups, authentication files, or keys. Generating a report does not authorize sending it to another person or marking its chats read.

For recurring reports, use Grok's actual scheduler only when requested. Store the agreed scope, timezone, and last completed window with the task, use overlapping windows and de-duplication, and report failures as failures. Don't silently send summaries to a chat or external service.
