---
name: beeper-setup
description: Install or update Beeper CLI and Server on Grok's cloud computer, sign in to an existing Beeper account, verify with a trusted device or recovery key, and diagnose access.
---

# Set up Beeper

Read [Beeper](../beeper/SKILL.md) for the shared rules and resolve `HELPER` to `../beeper/scripts/beeper.py` from this directory. “Set up Beeper” authorizes installation and startup. Run everything on the Grok cloud computer; leave the user's PC alone.

## Install and resume

```sh
python3 "$HELPER" status
python3 "$HELPER" setup
```

Run `setup` if the tools, target, or running process are missing. It installs the latest official standalone CLI with a SHA-256 check, asks that CLI to install official Server, creates a production target only when absent, and starts it. It preserves an existing target, accounts, and keys. Repeating setup does not replace an existing installation. If only the process stopped, `start` is enough.

Since v0.7.1, CLI discovery uses GitHub's public release redirect and Beeper's `binaries.json`, without GitHub's REST API. Setup needs no GitHub account, token, or secret prompt. Do not wait for an API quota reset before trying this helper. It caches validated release metadata for 15 minutes, shared by setup and update checks; results include `source`, `checkedAt`, and `cached`. The archive's SHA-256 is still checked before installation. That digest is supplied by Beeper with the release; it checks the downloaded bytes against the publisher's manifest, not an independent security audit.

Wait for the same installation job instead of launching duplicates. Check status again if Server is still starting. Existing credentials mean resume verification or reads, not sign in again. If credentials expired or a saved executable disappeared, explain that exact condition before attempting a repair; do not silently replace the profile.

For a download failure, read the structured `error.code`. `github_rate_limited` includes a reset time in UTC or retry delay when GitHub supplies one; convert it to the user's timezone and avoid repeated retries. `github_http_error` with HTTP 403 alone does not prove a rate limit. `invalid_release_metadata` or `checksum_mismatch` must stop installation; never skip verification. Downloads can still fail independently of the API quota. A Beeper Server CDN failure is a separate problem. Don't reset accounts or schedule a fresh profile just to retry a download.

## Sign in privately

When no Beeper account is signed in:

```sh
python3 "$HELPER" signin
```

Keep this job running. It prints one `privateURL`; open that URL in **Grok's cloud computer browser**, then hand browser control to the user. It is a loopback URL on that computer, not a link to open on their phone or PC. The same page takes their Beeper email and emailed code. Don't ask for either secret in chat, inspect what they type, take credential screenshots, or put values in tool arguments. Await the same job after submission; the page says it can be closed, and the job returns the next step. It expires after ten minutes. Cancellation or expiry is not success.

If the current Grok interface cannot provide private cloud-browser takeover, explain that limitation and keep setup pending; don't substitute chat for secret entry. An existing recovery key unlocks encryption **after email sign-in**; it is not a replacement for account authentication. This flow never accepts registration terms or creates a Beeper account.

## Verify the new device

Prefer a Beeper device the user already trusts. Check existing progress before starting another request:

```sh
python3 "$HELPER" verify show
python3 "$HELPER" verify start
python3 "$HELPER" verify show
```

Run `start` only when no active request exists. Ask the user to approve the new session in their signed-in Beeper app. Resume from the returned state and `availableActions`. When `sas.start` is offered, run `verify sas`, then `verify show`. Present the returned emoji sequence or numbers exactly. Confirm only after the user explicitly says both devices match:

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

`check-updates` uses the same cached release manifest for CLI, and native `update --check --server` only for Server. Don't replace it with native `update --check --cli`, which still calls GitHub's API. A result with `checked: false` or `available: null` means unknown, not up to date; the other component's result can still be useful. If a delayed setup job was already scheduled for an old API quota reset, inspect its current state and update that same job to use the new helper. Do not start competing setup jobs or assume the scheduled job never ran.

Afterward repeat the account/chat/message checks above and compare account IDs with the pre-update result. Don't claim success from an updater exit code alone. No automatic rollback: an updated database may be incompatible with an old executable. Preserve the backup and report any regression.

Checked on 28 September 2026: published CLI **0.6.2**; its Server nightly feed **4.3.156** (26 September). The separate stable feed reports 4.3.152. CLI 0.6.2 installs from the nightly feed even with production authentication. Read actual installed versions; do not invent a CLI upgrade or confuse the download channel with the account environment.
