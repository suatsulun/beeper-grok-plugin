# Server installation and authentication

`HELPER` is the absolute path to `../scripts/beeper.py` relative to this file's directory. Invoke it with `python3`.

## Install and start

```sh
python3 HELPER bootstrap
python3 HELPER status
```

Bootstrap installs checksum-pinned Beeper CLI 0.6.2 and qrcode 8.2 into the private data directory, downloads Server through Beeper's official CLI, chooses an unused loopback port, creates the isolated `grok-bot` target, and starts it. No system package installation or root permission is needed. It requires network access to GitHub, Python's package CDN, and Beeper's download/authentication services. Downloads and extraction may take several minutes; run the tool as a background/yielding command and report progress while it works.

Keep durable data in `/workspace/.beeper-grok` on Grok Bot. Starting a process is not a guarantee it survives computer replacement. When a fresh runtime is detected or a read fails, run `status`, then `start` or `bootstrap` as necessary. Successful routine reads do not need another preflight. Existing target/profile/authentication files are reused. Do not choose a new data directory to get past an authentication problem.

`bootstrap --cli-only` restores the CLI and QR renderer without installing or starting Server. `stop` stops only this plugin's managed Server.

## Sign in to Beeper

Get the user's Beeper email address if missing:

```sh
python3 HELPER login --email 'USER_EMAIL'
python3 HELPER input email
```

The second command prints a private input URL and stays running. Open that URL in the **Bot computer's browser**, then let the user take over to enter the email code. The form sends the code directly to the local Server; the token returned by Beeper is saved in the private target file. Do not read or reproduce either value.

After submission:

```sh
python3 HELPER status
```

If `registrationRequired` is true, explain that this email requires a new account and run `input register`. The user chooses the username and accepts Beeper's terms themselves. Then check `status` again.

Repeated `login` with the same email resumes the saved request without sending another email. If the request expires, or the user corrects the email, `login-cancel` clears only the pending local sign-in state; then start a fresh login. It does not delete the account, revoke a signed-in session, or reset keys.

## Verify the Server device

For `needs-verification`, start one verification:

```sh
python3 HELPER verify-start
```

Ask the user to accept the new-device request in an already trusted Beeper device, then use:

```sh
python3 HELPER verify-show
```

Follow the returned `availableActions`: `verify-accept` for `accept`, and `verify-sas` for `sas.start`. Display the returned `sas.emojis` exactly, with `sas.decimals` if useful. Obtain an explicit match/mismatch response. Only after a match:

```sh
python3 HELPER verify-confirm --matches
python3 HELPER status
```

The helper checks that the comparison still matches the one it last displayed and uses the setup-scoped confirmation API. For a mismatch, use `verify-cancel`; never confirm to advance setup.

For `needs-secrets`, or if the user chooses their existing recovery key instead, use `input recovery`. Do not reset a key. For `needs-first-sync` or `initializing`, check status at reasonable intervals, report progress, and stop after a few minutes of no change to diagnose. `needs-cross-signing-setup` is an explicit unsupported setup state until Beeper provides a suitable headless procedure; do not invent a reset-based workaround.

## Connect a network

Discover actual accounts, bridge IDs, and login flows from this Server:

```sh
python3 HELPER accounts
python3 HELPER networks
python3 HELPER flows 'BRIDGE_ID'
python3 HELPER connect 'BRIDGE_ID' --flow 'FLOW_ID'
```

Use exact returned IDs. Reuse a connected account. Multiple matching bridges or multiple accounts may require the user to choose. Respect unavailable/disabled/limit-reached statuses. For reauthentication, use `connect ... --login-id 'EXISTING_LOGIN_ID'`, with an ID returned by Beeper. Never remove the existing account merely to sign in again.

Read the returned flow names and descriptions before choosing. The helper prefers an unambiguous website/cookie flow and defaults to the user's own browser; QR/device-code flows keep their native steps. Flow IDs and bridge implementations vary: do not invent an Instagram cookie flow or assume a browser login can replace a mobile-API credentials flow. If only direct username/password input is available, explain that this bridge needs upstream website-login support. The plugin does not open a generic network password form.

`connect` saves the login session and returns its current step. Only one pending network login is managed at a time:

| Step | What Grok does |
| --- | --- |
| `display_and_wait` with QR | Attach the returned `qrImage` PNG, explain the phone app's scanning step, and call `network-poll` after the user scans. |
| `display_and_wait` with code/emoji/instructions | Present the display and instructions, then `network-poll`. |
| `user_input` | For native phone/code steps, run `input network` and hand over the Bot-local page. Password/cookie inputs are blocked with an explanation. |
| `cookies` | Complete provider sign-in using the browser workflow below. Do not request cookies or passwords in chat. |
| `complete` | Check `accounts` and the returned account's status; then test a scoped chat/message read. |
| `failed` / `cancelled` | Explain the result and inspect accounts before another attempt. |

After each input use `network-show`. A terminal input submission may clear the pending session immediately; in that case check `accounts`. `network-poll` retrieves current state before acknowledging a display step and waits at most 35 seconds per request. On timeout, use `network-show` to find out whether it advanced. Attach a refreshed QR if Beeper replaced it. `network-cancel` cancels only the pending login session and deletes its local QR image.

### Browser and cookie-based authentication

For a returned `cookies` step, keep the current session and read [browser-login.md](browser-login.md). Check the runtime and selected provider:

```sh
python3 HELPER browser-check
python3 HELPER browser-plan
```

Run `browser-start --browser local` and follow the browser guide. Obtain fresh local approval for the exact provider connection and encrypted return, then run `local_browser.mjs connect REQUEST.json --transfer-on-login` on the user's PC. It opens the provider directly in a dedicated window; no Chrome settings or additional Beeper approval page are needed. Submit the returned envelope automatically using `browser-finish --stdin`. Reusing an ordinary Chrome profile is an explicit alternative with its own Chrome permission and review prompts. If local tools or fresh approval are unavailable, report that limit; use a cloud browser only if the user explicitly chooses it. No extension, relay or Node upgrade is needed; the helper does not depend on `Bun.WebView`.

Both local browser choices resume the saved login and submit required fields plus supported optional fields that are present to Server. Do not cancel and recreate a login merely to switch browser modes. If a browser attempt fails or times out, inspect `network-show` and `accounts` before another attempt. Unsupported fields or providers produce explicit errors. Connected accounts and a scoped read establish successful network setup.

### Clipboard and password managers

The Bot's Chrome runs on a different computer from the user's desktop browser. Opening the provider's website there does not transfer the user's local clipboard, browser extension, or saved session. The plugin's private forms do not disable pasting, and changing their HTML cannot provide Grok's missing clipboard transport.

If the user's takeover UI provides a clipboard/paste control, try it first with harmless text. If Grok provides a supported masked secret request for this connection, use that facility; do not invent a tool, claim arbitrary fields are supported, or route the value through ordinary chat. [Grok's credential handoff documentation](https://docs.x.ai/grok-bot/approvals-security-and-privacy) distinguishes secure requests from normal messages.

For compatible network logins, use the [bundled local browser helper](browser-login.md) through Grok Desktop's approved local tools. It reuses an approved Chrome session or opens the provider website on the PC, so there is no clipboard transfer to the cloud for that website login. A separate local Chrome profile does not inherit the user's normal browser extensions or autofill. Beeper email/recovery and native phone/code steps still use private input on Grok's computer. If those inputs cannot be entered, explain the limitation and pause that step. Do not sync a password vault, read browser cookie databases, or upload cookie files into chat.

## Known upstream limits

Reviewed against Beeper CLI 0.6.2 and the official API SDK's `next` branch on 2026-09-11:

- [Server installer](https://github.com/beeper/cli/blob/main/packages/cli/src/lib/installations.ts) currently forces the staging download feed/nightly artifact. The managed target here still authenticates against production. Report this distinction and the actual version.
- [SAS confirmation issue #28](https://github.com/beeper/cli/issues/28): this helper uses `/v1/app/setup/verifications/{id}/sas/confirm`, after checking the comparison and available action.
- CLI diagnostics can lose the selected target's token when resolving a base URL. The helper sets the token from this isolated target in the child environment; it never adopts credentials from another installation.
- [Headless empty-chat issue #31](https://github.com/beeper/cli/issues/31) reports synced/verified accounts whose chat APIs remain empty. An empty response cannot prove this particular defect; confirm account state, sync, requested scope, and whether known chats should exist. Report reproducible failures to the user for Beeper's review rather than patching the binary automatically.

Official sources: [Beeper CLI](https://github.com/beeper/cli), [setup API types](https://github.com/beeper/desktop-api-js/tree/next/src/resources/app), [network login API types](https://github.com/beeper/desktop-api-js/tree/next/src/resources/bridges), [Grok Bot computer and secure takeover](https://docs.x.ai/grok-bot/computer-and-apps).
