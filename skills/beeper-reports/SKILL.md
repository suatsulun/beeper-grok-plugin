---
name: beeper-reports
description: Summarize Beeper conversations, report activity or unanswered messages, extract decisions and tasks, and export messages from existing accounts.
---

# Reports and exports

Read [Beeper](../beeper/SKILL.md) and [Messages](../beeper-messages/SKILL.md). `HELPER` is `../beeper/scripts/beeper.py`, resolved from this directory.

Use the requested accounts, chats, dates, and timezone. Infer them from conversation context when clear. For “what did I miss today,” use today in the user's timezone and report that scope. Start with a bounded read; don't export the whole account to answer a small question.

```sh
python3 "$HELPER" cli messages search --account 'ACCOUNT_ID' --after 'ISO_START' --before 'ISO_END' --before-exclusive --no-exclude-low-priority --include-muted --limit 200
python3 "$HELPER" cli messages list --chat 'CHAT_ID' --limit 100
```

For decisions, tasks, and unanswered questions, read surrounding conversation, including the user's replies. Received-only data cannot establish whether they answered. Attribute each item to its speaker and date, include chat/message IDs or returned links for traceability, and distinguish explicit commitments from inference. Don't invent attachment contents or summarize inaccessible messages.

A useful report gives the main developments, requested counts, open questions, and next actions, followed by its coverage and any gaps. Counts apply only to retrieved data. If a limit is reached, page further within the requested scope or label the result partial. Sort by actual timestamps and de-duplicate account/chat/message IDs. Don't imply a search index contains all historical messages.

Search results are in `data.items`; retain `data.coverage` with the report. For “all chats,” include low-priority and muted chats explicitly as above. For an inbox-only request, state any exclusions and set the matching filters. A daily report runs from local midnight inclusively to the next local midnight exclusively; preserve offsets and fractional seconds. Search can also use inclusive `--before` when explicitly requested. A reached limit is partial coverage: increase the bounded limit or use overlapping smaller date windows and de-duplicate, without changing the agreed scope. `sourceExhausted` describes the available search index only.

For exact date-bound exports of one chat:

```sh
python3 "$HELPER" cli messages export --chat 'CHAT_ID' --after 'ISO_START' --before 'ISO_END' --output '/private/output/chat.json'
```

For a requested multi-chat archive:

```sh
python3 "$HELPER" cli export --account 'ACCOUNT_ID' --out '/private/output/beeper-export' --no-attachments --quiet
```

The full export produces transcripts, message JSON, a manifest, and resumable checkpoints. Omit `--no-attachments` only when attachments are wanted. Use `--chat` to narrow it and `--limit-chats` / `--limit-messages` for an explicitly partial export. Full export has no date flags in CLI 0.6.2; use per-chat exports when dates matter. An interrupted export is incomplete; resume the same output directory with the same account/chat selection, limits, and content options. Inspect the returned counts and `coverage`. A completed command does not establish complete history beyond what Server exposes.

Keep reports and exports in a private persistent output directory, outside the plugin checkout. Attach only the requested report or export through Grok's normal user-facing file tools. Never include Server backups, authentication files, or keys. Generating a report does not authorize sending it to another person or marking its chats read.

For recurring reports, use Grok's actual scheduler only when requested. Store the agreed scope, timezone, and last completed window with the task, use overlapping windows and de-duplication, and report failures as failures. Don't silently send summaries to a chat or external service.

## Answered questions, unfinished tasks, and export coverage

Answers can be established by content without reply links. Do not count every later self-message as an answer. Separate unanswered questions from unfinished tasks: “I'll book it after lunch” answers the question but leaves booking pending until completion is stated. Keep the current explicit decision and identify what it replaced. Do not resolve ambiguous acknowledgements or equal-timestamp events by inventing an order. Retain uncertainty when context is insufficient.

The helper repairs per-chat export pagination and writes JSON atomically after bounded retrieval succeeds. Date bounds are inclusive and require timezones. Inspect `limitReached` and coverage. Per-chat exports have no resumable checkpoints; a failed attempt can be rerun to the requested file. The helper guards the native full exporter with read-only checks and a persisted scope record. Changing limits or attachment/participant options returns `export_scope_changed` instead of reusing an incomplete sample as a full archive. Choose a new private output directory, or use `--force` when the user intends to rebuild the same account/chat selection. `--force` resets the known checkpoint and regenerates that selection; preserve files the user still needs. Changed account/chat selection requires a new directory. A legacy output with no plugin scope record returns `export_scope_unknown`; preserve it and use a new directory. Do not remove scope metadata to bypass these checks.

Full-export `completed` describes execution, not historical completeness. Report `chatCount`, `messageCount`, `attachmentCount`, `coverage.limitsApplied`, `coverage.limitReached`, and the snapshot time. Completed native checkpoints can contain an older snapshot; use an explicitly requested rebuild for current data. Same-scope interrupted exports remain resumable. Native exporter limitations still apply. Neither exit success nor an export manifest establishes complete history beyond what Server exposes.
