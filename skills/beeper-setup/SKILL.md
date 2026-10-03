---
name: beeper-setup
description: Complete permission-based first-run setup of Beeper CLI and Server on the shared Grok cloud computer, reuse an existing installation across devices, sign in privately, verify, update, or diagnose access.
---

# Set up Beeper

Read [Beeper](../beeper/SKILL.md) for default onboarding and resolve `HELPER` to `../beeper/scripts/beeper.py` from this directory. First-run installation requires the user's approval for CLI and Server on their shared Grok cloud computer. An explicit approval already given for that exact scope is sufficient; do not repeat the question. Run everything on that cloud computer; leave the user's PC alone.

## Install and resume

```sh
python3 "$HELPER" onboard
# Only after the user approves the initial cloud installation:
python3 "$HELPER" setup --approved
# Resume a previously approved incomplete setup, or reuse an existing target:
python3 "$HELPER" setup
```

`onboard` returns a local installation plan without process launches, downloads, or writes. Follow its state as described in the main skill. `setup` refuses a new installation without approval, before creating even the data directory or a lock file. `setup --approved` records the consent in that profile and installs the latest official standalone CLI with a SHA-256 check, asks that CLI to install official Server, creates one production target, and starts it. A declined or unanswered prompt means do not run it.

Existing installations from older plugin versions are reused without an approval marker or another installation prompt. Repeating setup preserves the target, accounts, and keys and does not start an already-running Server again. If only the process stopped, `start` is enough. Invalid/missing files belonging to an existing profile are a repair case, detected before downloads. Client-device changes never authorize a new profile. Updates remain a separate user-requested action; install consent does not authorize future upgrades, message sends, or account changes.

Since v0.7.1, CLI discovery uses GitHub's public release redirect and Beeper's `binaries.json`, without GitHub's REST API. Setup needs no GitHub account, token, or secret prompt. Do not wait for an API quota reset before trying this helper. It caches validated release metadata for 15 minutes, shared by setup and update checks; results include `source`, `checkedAt`, and `cached`. The archive's SHA-256 is still checked before installation. That digest is supplied by Beeper with the release; it checks the downloaded bytes against the publisher's manifest, not an independent security audit.

Wait for the same installation job instead of launching duplicates. Check status again if Server is still starting. Existing credentials mean resume verification or reads, not sign in again. If credentials expired or a saved executable disappeared, explain that exact condition before attempting a repair; do not silently replace the profile.

For a download failure, read the structured `error.code`. `github_rate_limited` includes a reset time in UTC or retry delay when GitHub supplies one; convert it to the user's timezone and avoid repeated retries. `github_http_error` with HTTP 403 alone does not prove a rate limit. `invalid_release_metadata` or `checksum_mismatch` must stop installation; never skip verification. Downloads can still fail independently of the API quota. A Beeper Server CDN failure is a separate problem. Don't reset accounts or schedule a fresh profile just to retry a download.

## Sign in privately

When no Beeper account is signed in:

```sh
python3 "$HELPER" signin
```

Keep this job running. It prints one `privateURL`; open that URL in **Grok's cloud computer browser**, then hand browser control to the user. It is a loopback URL on that computer, not a link to open on their phone or PC. The same page takes their Beeper email and emailed code. Don't ask for either secret in chat, inspect what they type, take credential screenshots, or put values in tool arguments. Await the same job after submission; the page says it can be closed, and the job returns the next step. It expires after ten minutes. Cancellation or expiry is not success.

The page can resend a code, change the email, or cancel without creating a second job. Cancel releases the job's lock; closing the browser alone does not. Await the cancelled or expired job before replacing it. If the result says authentication is uncertain, check Server status first and do not resubmit the code/key or start another sign-in blindly.

If the current Grok interface cannot provide private cloud-browser takeover, explain that limitation and keep setup pending; don't substitute chat for secret entry. An existing recovery key unlocks encryption **after email sign-in**; it is not a replacement for account authentication. This flow never accepts registration terms or creates a Beeper account.

## Verify the new device

Prefer a Beeper device the user already trusts. Check existing progress before starting another request:

```sh
python3 "$HELPER" verify show
python3 "$HELPER" verify start
python3 "$HELPER" verify show
```

Run `start` only when no active request exists. Ask the user to approve the new session in their signed-in Beeper app. Resume from the returned state and `availableActions`. For an incoming request the user initiated on their trusted device, run `verify approve` when `accept` is offered. This accepts the request; it does not confirm a comparison. When `sas.start` is offered, run `verify sas`, then `verify show`. Present the returned emoji sequence or numbers exactly. Confirm only after the user explicitly says both devices match:

```sh
python3 "$HELPER" verify sas-confirm --matches
```

Never infer a match from a screenshot of one side or accept it for them. If they do not match, use `verify cancel`. If the live flow needs an unsupported action, report it; do not reset verification or invent a QR code.

When the user chooses their **existing recovery key**, use:

```sh
python3 "$HELPER" recovery
```

Open the returned private URL in the cloud browser and hand control to the user, as above. Don't ask them to paste the key into chat. Do not create or reset a key.

## Check access

```sh
python3 "$HELPER" status
python3 "$HELPER" cli accounts list
python3 "$HELPER" cli chats list --limit 10
python3 "$HELPER" cli messages list --chat 'RETURNED_CHAT_ID' --limit 1
```

Read a message only when a chat was returned. Use each requested account ID to check network-specific access. Report Server version/running state, Beeper authentication/verification, visible accounts, and whether chat/message reads worked. Beeper's existing cloud-connected accounts should sync; accounts tied only to another local device may not be available here. Don't promise every historical message or every network feature.

An empty response is not proof of an empty inbox or successful message access. An `initializing` flag alone is not proof that reads fail. Try a bounded recheck during initial sync, then report the observed state. Do not loop indefinitely, reset profiles or keys, reconnect accounts, reinstall repeatedly, edit databases, or patch Server binaries to force readiness.

## Updates

When the user asks to update:

```sh
python3 "$HELPER" check-updates
python3 "$HELPER" update
```

The update command checks the official CLI release, replaces it only if its version changed, and retains `bin/beeper.previous`. For an available Server update it stops the profile, makes a private config/profile and program backup under `private-backups/`, uses official `beeper update --server`, and starts the same target. Leave backups private; never attach them. A shared installation with other Server profiles needs separate review, so the helper stops before changing that Server.

An already-stopped Server can be updated. Setup, update, start, and private sign-in share one lock. The backup contains `config/` and the actual data directory under `profile/` in `config.tar.gz`; `profile.json` records its original and resolved paths. External data directories and a symlinked profile root are supported. Linked directories inside a profile require backup review before an update; the helper stops instead of following a possible loop. No automatic restore is performed.

`check-updates` uses the same cached release manifest for CLI, and native `update --check --server` only for Server. Don't replace it with native `update --check --cli`, which still calls GitHub's API. A result with `checked: false` or `available: null` means unknown, not up to date; the other component's result can still be useful. If a delayed setup job was already scheduled for an old API quota reset, inspect its current state and update that same job to use the new helper. Do not start competing setup jobs or assume the scheduled job never ran.

Afterward repeat the account/chat/message checks above and compare account IDs with the pre-update result. Don't claim success from an updater exit code alone. No automatic rollback: an updated database may be incompatible with an old executable. Preserve the backup and report any regression.

Checked on 28 September 2026: published CLI **0.6.2**; its Server nightly feed **4.3.156** (26 September). The separate stable feed reports 4.3.152. CLI 0.6.2 installs from the nightly feed even with production authentication. Read actual installed versions; do not invent a CLI upgrade or confuse the download channel with the account environment.

## Verification cache and diagnostic interpretation

An idle or finished `verify show` does not write a cache. An active comparison caches only its ID and comparison values. With `BEEPER_READONLY=1`, even an active show does not refresh that cache and verification changes are blocked; display the comparison again outside audit mode before obtaining confirmation. Confirm re-reads live state and rejects missing, changed, or completed requests.

A successful `doctor` command can return `ok: false`: execution succeeded but a health check failed. Preserve both facts and assess actual message access separately. Never change health flags to make a report look successful.
