# Beeper for Grok

Say **“Set up Beeper.”** Grok installs Beeper CLI and Server on its cloud computer, helps you sign in to your existing Beeper account, and uses the chat accounts already connected there. The same cloud setup is available when you use your Grok account from another device.

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

Five skills: Beeper routing, setup, messages, chats, and reports. Seven Python standard-library modules install the official CLI, preserve one cloud profile, provide private sign-in, and repair specific messaging compatibility issues. Native CLI commands remain available through the helper; bounded history, search, and contact-detail reads use the authenticated loopback API directly. No JavaScript browser stack, MCP service, package dependencies, or install hooks.

Data stays outside the plugin at `/workspace/.beeper-grok`. Existing `grok-bot` profiles from the 0.6.x plugin are reused. Updating this source alone does not change Server or sign anyone out. “Update Beeper” checks official releases, keeps the old CLI, backs up a stopped Server's profile and program, and runs the official updater. It never patches Beeper binaries or resets account data.

**v0.7.2 introduced the earlier setup safeguards.** It blocks hidden target overrides, coordinates startup with updates, backs up the configured profile even outside the config directory, and updates an already-stopped Server. Sign-in supports code resend, email correction, and cancellation on the same private page. Incoming trusted-device requests can be accepted, and expected sign-in errors keep their useful explanations. Later releases retain these safeguards.

**v0.7.1 removes the GitHub API requirement from setup and CLI update checks.** It reads Beeper's public release manifest, caches release details for 15 minutes, and verifies the downloaded archive's SHA-256. Users need no GitHub token and don't have to wait for a shared API quota to reset. Ordinary download restrictions or Beeper Server download failures can still occur; the helper reports them separately. The checksum comes from Beeper's release manifest, so it verifies agreement with the publisher's release, not independent authenticity.

As checked on **28 September 2026**, the latest published CLI is **0.6.2**. The CLI's Server nightly feed reports **4.3.156**; the separate stable feed reports **4.3.152**. Beeper's installer currently uses the nightly feed for Server while the account still signs into production. These are release checks, not a claim that a user's cloud installation has already been updated.

## Install and development

### v0.7.5 reaction identity fix — candidate

- WhatsApp acceptance found an own reaction whose `participantID` matched the chat member marked `isSelf`, but differed from the account's `user.id`. The reaction was visible on the phone; the 0.7.4 matcher still returned `unknown`. This was an identity comparison defect, not evidence that opening the phone was required.
- Reaction observation now checks both exact identities, with chat/account scope validation. It never infers identity from names, phone numbers, or ID suffixes. Boolean `checks` show whether the account or chat identity matched, without exposing participant identifiers.
- Removal remains unconfirmed while either own identity still has the requested reaction. Missing/malformed state, conflicting identity evidence, and an unresolved possible self reaction stay unknown. Chat and account reads are cached within the existing observation deadline; the write is never repeated.

This is a source candidate until the exact revision passes live acceptance and is installed/reloaded on Grok. Tests and a source archive do not activate a plugin. Existing-account scope is unchanged: this version does not add the earlier PC-browser provider-cookie login flow. See [the acceptance handoff](GROK-TEST.txt) for rechecking the existing reaction without sending another one or resetting the working account.

### v0.7.4 review fixes

- Contact IDs are exact and case-sensitive, including with an original `--query` hint. A colliding name/phone/handle cannot substitute for the requested person. Name/phone/handle lookup remains available through explicit `--by-label`; multiple matches require disambiguation.
- Message writes execute once. An immediate read can finish quickly; pending/stale effects receive up to three read-only rechecks within an eight-second observation budget. Results keep message IDs, attempt counts, content evidence, bridge status, and receipt limitations separate. Missing optional `sendStatus` does not prevent confirmation of matching Server content.
- Message search uses whole-second API queries widened around the requested timezone-aware dates, then filters the exact fractional-second boundaries locally. `--after` and `--before` are inclusive; `--before-exclusive` supports daily `[start, next midnight)` windows. Results are now `{items, coverage}` inside `data`, including effective filters, index exhaustion, and truncation. Search includes low-priority and muted chats unless explicitly excluded.
- Write argument parsing understands option arity, repeated mentions, and literal values that look like flags. The official CLI rejects some flag-like text values, so those text sends/edits use one JSON API write selected before dispatch. Target overrides remain blocked. Rich text is never flattened to fabricate a match; differing Server representations remain explicitly unverified. Merged-chat scope mismatches stop safely; select an explicit network member chat.

### v0.7.3 audit fixes

- Message list, context, and per-chat export follow **opaque cursors returned by Server**. CLI 0.6.2 passes message IDs as cursors; the helper instead locates the ID while walking real pages. It retains Server ordering for timestamp ties, removes duplicate boundary rows, and rejects stalled or non-chronological pagination. Context includes the center and nearest messages on each side.
- Known full chat IDs avoid a CLI process for history reads. Recent windows usually need one HTTP request. Deep anchors require scanning from the newest page; this is a correctness tradeoff, not constant-time random access. Default bounds are 20 pages/30 seconds, explicitly adjustable to 200 pages/300 seconds. A budget failure is never returned as empty or complete history.
- Contact details use search and bounded enumeration, recognize full names/phones/usernames, and reject ambiguous matches. `--query ORIGINAL_SEARCH_TEXT` resolves a returned opaque ID when the network cannot search it directly. Limited enumeration can still leave a contact unresolved.
- Errors retain safe classifications and fixed explanations without printing identifiers or upstream free-form text. Idle verification checks no longer write null snapshots; confirmation still validates the live comparison.
- Message writes run once and return `writeOutcome` after bounded read-back: accepted, pending, confirmed, failed, or unknown. Confirmation covers observed Server state, not delivery/read receipts or remote erasure. Tombstones report retained text. Attachment bytes/subtypes and failed read-backs stay unverified. Native result fields remain present.
- Skills avoid repeated discovery calls, distinguish unanswered questions from unfinished work, and preserve uncertainty about timestamp ties, capability support, and diagnostic health.

These changes use official CLI/Server installations without binary patches. The separate native multi-chat export retains upstream behavior; a successful export cannot establish that Server has all historical messages. Tests use synthetic data, including a real loopback HTTP receiver; live account acceptance must still be performed on Grok. See [validation](tests/README.md) and [the Grok handoff](GROK-TEST.txt).

The API contract is documented by [Beeper's message endpoint](https://developers.beeper.com/desktop-api-reference/php/resources/messages/methods/list/), [pagination implementation](https://github.com/beeper/desktop-api-js/blob/next/src/core/pagination.ts), and [contact endpoints](https://github.com/beeper/desktop-api-js/blob/next/src/resources/accounts/contacts.ts). IDs and sort keys are not substituted for opaque page tokens.

### Installing the plugin source

This source has `.grok-plugin/plugin.json` and `skills/`. **Grok Bot and Grok Build have different activation mechanisms.** A verified ZIP and successful helper calls establish that the code works on the computer; they do not register skills for future sessions.

For **Grok Bot**, use the app's native skill management if available. [The Bot documentation](https://docs.x.ai/grok-bot/skills-routines-and-automations) describes saving private skills and checking them under Marketplace → Your plugins → Manage plugins and skills. Update existing Beeper skills instead of creating duplicates. Retain the verified source directory, preserve the links among its five skills, and make helper references resolve to that exact source. Private skills can be shared across Bots; this does not establish that the helper files or Beeper profile exist on another computer. If the native mechanism cannot save these instructions or references, report that limitation and leave persistent activation pending. See [the activation handoff](GROK-ACTIVATE.txt).

For **Grok Build development**, the [CLI supports](https://docs.x.ai/build/cli/reference) `grok plugin install /absolute/path/to/project`; follow its displayed trust and reload requirements. This registers the plugin in that Build environment. Do not install or search the whole cloud computer for Grok Build just to activate a Bot skill. Distribution through a marketplace is a separate process requiring catalog review and a published source revision. Beeper binaries are downloaded only when the user asks to set up or update Beeper.

Grok's Linux cloud computer needs its existing Python 3.10+ runtime, internet access to official Beeper/GitHub downloads, and private browser takeover for sign-in. Automatic CLI installation supports x64 and arm64. No npm, pip, Node, or browser installation is needed.

```sh
python3 -m unittest discover -s tests -v
grok plugin validate .
git diff --check
```

Tests use synthetic accounts, a fake CLI/API, and temporary disk-backed data. See [validation](tests/README.md) for scope and live acceptance. Follow the host's resource instructions before running suites or installations.

Official references: [Beeper CLI](https://github.com/beeper/cli), [CLI releases](https://github.com/beeper/cli/releases), [Grok plugin format](https://github.com/xai-org/plugin-marketplace), [Grok skills](https://docs.x.ai/grok-bot/skills-routines-and-automations).

Plugin code is [MIT licensed](LICENSE). Beeper software keeps its upstream license and terms. The bundled [Beeper icon](https://www.beeper.com/wp-content/uploads/2026/05/beeper-favicon.png) belongs to Beeper and is not covered by this project's MIT license.
