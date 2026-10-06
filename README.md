# Beeper for Grok

**Install the plugin, approve one cloud setup, and use Beeper from every device on your Grok account.** On activation or first use, Grok checks the shared cloud installation. If it is missing, Grok asks permission before installing Beeper CLI and Server, then helps you sign in to your existing Beeper account. If it already exists, Grok reuses its connected accounts. You do not need to learn or request a separate setup command.

Your PC and phone are interfaces to that same account-owned cloud computer. The plugin, five skills, and account profile are not reinstalled per device or conversation. The plugin supplies the onboarding flow; automatic execution at the instant of marketplace installation requires a host install callback, which has not been verified for Grok Bot. Where skills load on demand, the first Beeper request starts this same flow.

Sign in with your Beeper email code, then approve the session on a trusted Beeper device or use your existing recovery key. Codes and keys go into a private browser page on Grok's computer. The plugin needs Grok's private browser takeover for those steps; it never asks for secrets in chat. It does not require changes to your PC or Chrome.

Try:

- “Show my latest received WhatsApp messages.”
- “Reply to Alice on Instagram: I'll be there at six.”
- “Summarize today's project chat and list the decisions.”
- “Find the PDF Sam sent last week.”
- “Mute this group until tomorrow.”
- “Export my conversation with Alex.”

This version deliberately covers **existing accounts**. Adding networks, provider login, browser-cookie transfers, account registration, and recovery-key resets are not included. Only cloud-connected accounts and features exposed by your running Beeper Server are available; device-local connections and complete historical sync are not guaranteed.

## What's inside

Five skills: Beeper routing, setup, messages, chats, and reports. Nine Python standard-library modules install the official CLI, preserve one cloud profile, provide private sign-in, and repair specific messaging compatibility issues. Native CLI commands remain available through the helper; bounded history, search, contact-detail reads, and message mutations use the authenticated loopback API directly. No JavaScript browser stack, MCP service, package dependencies, or unattended install hooks.

Data stays outside the plugin at `/workspace/.beeper-grok`. Existing `grok-bot` profiles from the 0.6.x plugin are reused. Updating this source alone does not change Server or sign anyone out. “Update Beeper” checks official releases, keeps the old CLI, backs up a stopped Server's profile and program, and runs the official updater. It never patches Beeper binaries or resets account data.

**v0.7.2 introduced the earlier setup safeguards.** It blocks hidden target overrides, coordinates startup with updates, backs up the configured profile even outside the config directory, and updates an already-stopped Server. Sign-in supports code resend, email correction, and cancellation on the same private page. Incoming trusted-device requests can be accepted, and expected sign-in errors keep their useful explanations. Later releases retain these safeguards.

**v0.7.1 removes the GitHub API requirement from setup and CLI update checks.** It reads Beeper's public release manifest, caches release details for 15 minutes, and verifies the downloaded archive's SHA-256. Users need no GitHub token and don't have to wait for a shared API quota to reset. Ordinary download restrictions or Beeper Server download failures can still occur; the helper reports them separately. The checksum comes from Beeper's release manifest, so it verifies agreement with the publisher's release, not independent authenticity.

As checked on **28 September 2026**, the latest published CLI is **0.6.2**. The CLI's Server nightly feed reports **4.3.156**; the separate stable feed reports **4.3.152**. Beeper's installer currently uses the nightly feed for Server while the account still signs into production. These are release checks, not a claim that a user's cloud installation has already been updated.

## Install and development

### v0.7.8 read-only reconciliation and accurate task reports

`cli messages reconcile` performs bounded GET-only checks of an earlier send, edit, reaction/removal, media send, or deletion, including in read-only mode. Supply `--chat`, `--operation`, and either a final `--id` or a send's `--pending-message-id`, plus the original expected fields. Use `--help` without an installed CLI to see options. Reconciliation never submits a write or creates a new acknowledgement.

Outcomes retain each read's decision in `observations`, with field-state summaries in `readBack`. Missing, null, empty and malformed reactions are distinguishable; a valid reactions list with established identity can confirm absence, while an omitted field cannot. Deleted parents cannot establish an earlier removal. An edit acknowledgement can contain old text while subsequent checks confirm the requested edit. Server deletion markers remain confirmed when text is retained; `remoteErasureVerified: false` describes unavailable remote-erasure evidence. Attachment visibility remains separate from file-byte identity. These summaries omit message bodies, participant IDs, attachment URLs, and receipt maps; they are not complete raw read payloads.

Reports preserve the action and object stated in a completion message. Completing preparation leaves the promised downstream action pending; an explicit completion remains self-reported complete even without external verification. The five saved private skills were updated on Grok Bot, and a fresh synthetic reporting holdout passed 12/12 content checks on the supplied provenance. See [validation](tests/README.md) for evidence scope and remaining live checks.

### v0.7.7 message transport and export fixes

- Sends (including files, voice and stickers), edits, reactions/removals, and message deletes use the helper's non-retrying HTTP transport. CLI 0.6.2's SDK could retry a single CLI invocation up to three HTTP submissions; invoking that CLI only once did not prevent duplicate sends. File uploads stream multipart data without loading the entire file into memory. No CLI or Server binary is patched.
- A successful send acknowledgement, including its pending message ID, remains in the result while read-back runs. A read timeout returns `writeOutcome: unknown` with that ID; it never resends. Default observation is up to four reads/eight seconds. `--wait` permits continued reads for up to 30 seconds, adjustable with `--wait-timeout` (milliseconds, maximum 300000). `--timeout` controls each write request (default 30 seconds, maximum five minutes).
- Full export enforces `BEEPER_READONLY` and `--read-only` before any output creation or CLI/API call. The helper records export scope, serializes writes to the same output, checks the manifest, and returns counts and coverage.
- Changing export limits/content options cannot silently reuse completed native checkpoints. Use a new output directory, or explicitly rebuild the same account/chat selection with `--force`. Changed account/chat selection or a legacy directory with no scope record requires a new directory. Same-scope interrupted exports remain resumable. `--force` resets the known checkpoint so old counts are not carried into a rebuilt snapshot.

These fixes retain the existing account scope. No login/logout or provider-connection flows were added. HTTP fault tests and the official CLI export test use synthetic data only; live deployment and acceptance are separate.

### v0.7.6 shared cloud onboarding

- Activation/first use checks `onboard`, a read-only local installation plan. New installations require consent before downloads or filesystem changes. `setup --approved` records that consent and installs official CLI and Server; an interrupted installation can resume without a second prompt.
- Every skill uses the same `/workspace/.beeper-grok` home and `grok-bot` target. There is no automatic local-home fallback. Older installations and their account state are reused without another installation prompt, and an already-running Server is not started again. Missing files associated with an existing profile stop for repair before downloads.
- Helper and manifest now report the same version; a regression test checks they stay aligned. The remaining host acceptance checks are saved-skill discovery and onboarding invocation on activation/first use. The source alone cannot register itself in Grok Bot or create an unsupported install-time callback.

### v0.7.5 reaction identity fix

- WhatsApp acceptance found an own reaction whose `participantID` matched the chat member marked `isSelf`, but differed from the account's `user.id`. The reaction was visible on the phone; the 0.7.4 matcher still returned `unknown`. This was an identity comparison defect, not evidence that opening the phone was required.
- Reaction observation now checks both exact identities, with chat/account scope validation. It never infers identity from names, phone numbers, or ID suffixes. Boolean `checks` show whether the account or chat identity matched, without exposing participant identifiers.
- Removal remains unconfirmed while either own identity still has the requested reaction. Missing/malformed state, conflicting identity evidence, and an unresolved possible self reaction stay unknown. Chat and account reads are cached within the existing observation deadline; the write is never repeated.

The 0.7.5 matcher was verified against the already-present WhatsApp reaction using one message, chat, and account read. That check does not establish live removal/deletion or full plugin acceptance. Existing-account scope is unchanged: this version does not add the earlier PC-browser provider-cookie login flow. See [the acceptance handoff](GROK-TEST.txt) for checking the current candidate without resetting the working account.

### v0.7.4 review fixes

- Contact IDs are exact and case-sensitive, including with an original `--query` hint. A colliding name/phone/handle cannot substitute for the requested person. Name/phone/handle lookup remains available through explicit `--by-label`; multiple matches require disambiguation.
- The helper invokes each write once; v0.7.7 also prevents retries inside the HTTP transport. An immediate read can finish quickly; pending/stale effects receive up to three read-only rechecks within an eight-second observation budget. Results keep message IDs, attempt counts, content evidence, bridge status, and receipt limitations separate. Missing optional `sendStatus` does not prevent confirmation of matching Server content.
- Message search uses whole-second API queries widened around the requested timezone-aware dates, then filters the exact fractional-second boundaries locally. `--after` and `--before` are inclusive; `--before-exclusive` supports daily `[start, next midnight)` windows. Results are now `{items, coverage}` inside `data`, including effective filters, index exhaustion, and truncation. Search includes low-priority and muted chats unless explicitly excluded.
- Write argument parsing understands option arity, repeated mentions, and literal values that look like flags. The official CLI rejects some flag-like text values, so those text sends/edits use one JSON API write selected before dispatch. Target overrides remain blocked. Rich text is never flattened to fabricate a match; differing Server representations remain explicitly unverified. Merged-chat scope mismatches stop safely; select an explicit network member chat.

### v0.7.3 audit fixes

- Message list, context, and per-chat export follow **opaque cursors returned by Server**. CLI 0.6.2 passes message IDs as cursors; the helper instead locates the ID while walking real pages. It retains Server ordering for timestamp ties, removes duplicate boundary rows, and rejects stalled or non-chronological pagination. Context includes the center and nearest messages on each side.
- Known full chat IDs avoid a CLI process for history reads. Recent windows usually need one HTTP request. Deep anchors require scanning from the newest page; this is a correctness tradeoff, not constant-time random access. Default bounds are 20 pages/30 seconds, explicitly adjustable to 200 pages/300 seconds. A budget failure is never returned as empty or complete history.
- Contact details use search and bounded enumeration, recognize full names/phones/usernames, and reject ambiguous matches. `--query ORIGINAL_SEARCH_TEXT` resolves a returned opaque ID when the network cannot search it directly. Limited enumeration can still leave a contact unresolved.
- Errors retain safe classifications and fixed explanations without printing identifiers or upstream free-form text. Idle verification checks no longer write null snapshots; confirmation still validates the live comparison.
- Message writes return `writeOutcome` after bounded read-back: accepted, pending, confirmed, failed, or unknown. Confirmation covers observed Server state, not delivery/read receipts or remote erasure. Tombstones report retained text. Attachment bytes/subtypes and failed read-backs stay unverified. Native result fields remain present.
- Skills avoid repeated discovery calls, distinguish unanswered questions from unfinished work, and preserve uncertainty about timestamp ties, capability support, and diagnostic health.

These changes use official CLI/Server installations without binary patches. The guarded multi-chat export still uses the native exporter; a successful export cannot establish that Server has all historical messages. Tests use synthetic data, including a real loopback HTTP receiver; live account acceptance must still be performed on Grok. See [validation](tests/README.md) and [the Grok handoff](GROK-TEST.txt).

The API contract is documented by [Beeper's message endpoint](https://developers.beeper.com/desktop-api-reference/php/resources/messages/methods/list/), [pagination implementation](https://github.com/beeper/desktop-api-js/blob/next/src/core/pagination.ts), and [contact endpoints](https://github.com/beeper/desktop-api-js/blob/next/src/resources/accounts/contacts.ts). IDs and sort keys are not substituted for opaque page tokens.

### Installing the plugin source

This source has `.grok-plugin/plugin.json` and `skills/`. **Grok Bot and Grok Build have different activation mechanisms.** A verified ZIP and successful helper calls establish that the code works on the computer; they do not register skills for future sessions.

For **Grok Bot**, register/update the bundled five skills together using the app's supported plugin or native skill management, and start the main skill's onboarding flow as part of activation. This is installer work; users should not have to copy skills or run helper commands individually. [The Bot documentation](https://docs.x.ai/grok-bot/skills-routines-and-automations) describes saving private skills and checking them under Marketplace → Your plugins → Manage plugins and skills. Update existing Beeper entries instead of creating duplicates. Retain the source directory and preserve the links among its skills and helper. The [shared cloud computer](https://docs.x.ai/grok-bot/computer-and-apps) belongs to the account; changing your PC or phone does not create another cloud home. If the host cannot register the bundle or invoke onboarding at installation, report the exact limitation; first use runs the same onboarding flow once skills are available. See [the activation handoff](GROK-ACTIVATE.txt).

For **Grok Build development**, the [CLI supports](https://docs.x.ai/build/cli/reference) `grok plugin install /absolute/path/to/project`; follow its displayed trust and reload requirements. This registers the plugin in that Build environment, not the user's Bot account. Do not install or search the whole cloud computer for Grok Build to activate Bot skills. Distribution through a marketplace is a separate process requiring catalog review and a published source revision. Beeper binaries are downloaded after the user approves cloud onboarding or explicitly requests an update.

Grok's Linux cloud computer needs its existing Python 3.10+ runtime, internet access to official Beeper/GitHub downloads, and private browser takeover for sign-in. Automatic CLI installation supports x64 and arm64. No npm, pip, Node, or browser installation is needed.

```sh
python3 -m unittest discover -s tests -v
grok plugin validate .
git diff --check
```

Tests use synthetic accounts, a fake CLI/API, and temporary disk-backed data. See [validation](tests/README.md) for scope and live acceptance. Follow the host's resource instructions before running suites or installations.

Official references: [Beeper CLI](https://github.com/beeper/cli), [CLI releases](https://github.com/beeper/cli/releases), [Grok plugin format](https://github.com/xai-org/plugin-marketplace), [Grok skills](https://docs.x.ai/grok-bot/skills-routines-and-automations).

Plugin code is [MIT licensed](LICENSE). Beeper software keeps its upstream license and terms. The bundled [Beeper icon](https://www.beeper.com/wp-content/uploads/2026/05/beeper-favicon.png) belongs to Beeper and is not covered by this project's MIT license.
