# Provider sign-in on the user's PC

Default to opening a new provider window in the user’s **normal Chrome profile** on their PC, preserving its sign-ins, extensions and saved-password tools. Chrome 144+ requires the user to enable its connection setting and approve its connection prompt. No Beeper page precedes login. **Every session transfer still requires fresh local approval for the exact connect-and-transfer action.** Obtain it through Grok’s normal local command prompt, identifying the provider and Beeper Server on Grok as the destination. Never approve for the user, use a standing grant, enable Chrome’s setting yourself or switch local execution to always allowed. If approval or Chrome access is unavailable, stop and report the limitation. Never silently open a separate profile or cloud browser.

Use the existing `cookies` step returned by Server. Keep its saved login transaction. Do not invent flow IDs or convert password/mobile-API flows into cookie flows.

## Instagram cookie requirements

The upstream bridge defines **`sessionid`, `csrftoken`, and `ds_user_id` as required**, and **`rur`, `shbid`, `shbts`, `mid`, and `ig_did` as optional**. Some valid signed-in sessions omit optional cookies. Do not describe missing `shbid`/`shbts` as failed sign-in or ask the user to browse more, switch profiles, or log in again solely to obtain them. Never synthesize missing values, copy cookies from another account, or populate absent fields with placeholders.

Run `browser-plan` and use its `requiredFields` / `optionalFields` (also returned by `browser-start`). `network-show` preserves any raw `required` and `optional` flags. **Absence of an `optional` flag alone does not mean required.** The upstream cookie-field model uses `required`; this differs from the native user-input model's `optional` field. The public Beeper SDK's simplified cookie-field type can omit requirement metadata entirely.

The helper honors a boolean `required` first, then a boolean `optional`. If both are absent, v0.6.1 recognizes the five documented optional Instagram cookie names, including a cookie source with a different field ID. This fallback applies only to named cookies on the Instagram provider; it does not make similarly named headers, local storage, unknown fields, or another provider optional. Other unspecified fields retain the required default. Only requested fields are collected, and absent optional fields are omitted from submission.

If the live bridge explicitly returns `required: true` (or `optional: false`) for one of these optional cookies, report the conflicting requirement as a bridge compatibility issue. Preserve that explicit requirement rather than silently weakening it. A home feed proves website sign-in, not that Server accepted the session or that chats are ready. Confirm `accounts` after an approved submission.

When updating from v0.6.0, stop only the old waiting helper, keep the provider session, and use `browser-cancel` to invalidate its transfer while preserving the pending Beeper login. Run the updated helper's `browser-plan` and `browser-start --browser local`, copy the new public package, and request fresh approval. Preparing again also replaces a saved request whose effective field requirements changed; never edit an existing authenticated request or reuse its ciphertext. Do not cancel/recreate a valid network login just to apply this fix.

Sources checked on 12 September 2026: [upstream required/optional cookie lists and missing-cookie check](https://github.com/mautrix/meta/blob/857f87f7f57d1a036550d77116def663a061c541/pkg/messagix/cookies/cookies.go), [bridge cookie-field model](https://github.com/mautrix/go/blob/main/bridgev2/login.go), [Beeper SDK cookie-field and input-field models](https://github.com/beeper/desktop-api-js/blob/next/src/resources/bridges/bridges.ts).

## Check both computers

See the [complete login audit](login-audit.md) for all browser providers and native methods. X also has documented optional challenge extras; Facebook/LinkedIn's required values remain required, and the inspected Slack token flow needs unsupported extraction. A provider in the registry is not proof that every live login method is compatible.

On Grok's cloud computer:

```sh
python3 HELPER browser-check
python3 HELPER browser-plan
```

The cloud helper supports the existing Node **20.19.2**. No Node upgrade, npm package, browser extension, or public relay is required. Server's embedded Node is separate from the helper runtime.

For the PC, call **ListMachines** and select the user's registered desktop. Use **Shell** with that exact `machineId`; **AwaitShell** must address the same local job/machine. The Bot account in acceptance testing exposes these tools plus machine-targeted **Read**, **CopyFromBox**, and **CopyToBox**, each requiring local-action approval. Read their actual schemas before calling them; do not guess arguments or invoke private desktop RPCs. If several desktops match, ask which PC the user wants. If local execution is disabled, explain that Grok's **Settings → General → Agent → Execution on Local Computer** must allow the operation. Keep per-command approval; do not switch it to always allowed. If the account exposes no local tool, stop this path and report that Grok integration limit. Opening a loopback URL in the cloud does not open a page on the user's PC.

The local helper can use an existing compatible Node or the runtime inside the **already installed Grok Desktop app**. The installed Linux Grok 0.44.0 runtime was verified as Node 24.15.0. Do not download another runtime. For example, on the user's Linux PC, with the actual installed path:

```sh
env ELECTRON_RUN_AS_NODE=1 '/opt/Grok Bot/grok-bot' LOCAL_DIR/local_browser.mjs check
```

On macOS/Windows, find the actual installed Grok executable and set `ELECTRON_RUN_AS_NODE=1` only for that helper process. Do not change global environment variables or relaunch the desktop app. Alternatively, an already installed Node can run `node --experimental-websocket LOCAL_DIR/local_browser.mjs check`. If the installed app disables this runtime mode and no suitable Node exists, report that limitation rather than asking for an installation. Linux is tested; macOS/Windows paths and native UI require acceptance testing.

Prepare Chrome access before starting a new time-sensitive bridge login. Ask the user to open the normal Chrome profile they want to use and enable its connection setting at `chrome://inspect/#remote-debugging`. The helper’s read-only `check` reports `existingChromeMetadata`; this only means connection metadata exists, not that it is live or permission has been granted. It does not inspect passwords/cookies or change settings. Chrome’s permission prompt appears when the approved local command connects. Chrome chooses the shared profile; do not assume another open profile is included. A saved provider session can transfer immediately, so identify the intended account/profile before the local action. Grok’s scoped transfer approval and Chrome’s browser-debugging permission are distinct.

## Prepare and copy the bundled helper

On the cloud computer:

```sh
python3 HELPER browser-start --browser local
```

It returns `localPackage`: a JSON package containing five plugin modules and `request.json`, each base64-encoded with a SHA-256. The request identifies the provider, permitted fields, receiver public key, and ten-minute expiry. The private decryption key remains on the cloud computer. Repeated preparation resumes an unexpired request; it does not approve a transfer.

Use **CopyFromBox** according to its exposed schema to copy this public cloud package to the selected PC, then the approved machine-targeted **Shell** to decode that package into a private, disk-backed directory on the PC, such as `~/.cache/beeper-browser/REQUEST_ID` (the platform equivalent on Windows). Verify every SHA-256 and allow only these filenames: `local_browser.mjs`, `cloud_browser.mjs`, `browser_protocol.mjs`, `browser_transfer.mjs`, `providers.mjs`, `request.json`. Create files with private permissions where supported. This is executing the plugin's bundled code, not installing an application or extension. The agent performs this step; do not ask the user to download dependencies, reconstruct files, or copy session values.

Reuse the machine/runtime already confirmed in this session when nothing has changed. Where the real Shell tool supports carrying this public package as input, combine verification, unpacking and launch in one approved local action instead of asking for separate unpack/start actions. Keep the connect-and-transfer scope explicit. Never change tool approval settings to reduce prompts.

If no file-copy tool exists, the public package can be carried as base64 in approved local command input and decoded with Node's built-in `fs` and `crypto`. Keep command arguments as data, honor shell size limits, and never include the cloud `browser-transfer.json`, target/config files, or private key. Do not use `/tmp` for the helper or browser profiles.

Describe the local action as opening this provider in the user’s approved normal Chrome profile and automatically returning its encrypted sign-in session to Beeper Server on Grok for this one request. `browser-start` returns `approvalScope` with the provider, destination, request ID and expiry. The command flag does not prove approval; Grok must obtain a fresh local approval before executing it, including when the profile already has a saved sign-in.

Run on the **PC** after that approval, using the same verified runtime:

```sh
env ELECTRON_RUN_AS_NODE=1 '/opt/Grok Bot/grok-bot' LOCAL_DIR/local_browser.mjs connect LOCAL_DIR/request.json --transfer-on-login
```

The same command works with an existing Node executable instead of the Grok runtime. Keep the local action’s job ID and await its result on the same PC. If Chrome connection metadata is missing, the helper opens Chrome’s connection settings page and emits `phase: chrome-setup`; the user enables the setting. At `phase: chrome-permission`, the user approves Chrome’s prompt. Once connected, the helper creates a new provider window in the shared normal profile without a Beeper form. It does not attach to an unrelated existing tab or create an incognito context. Denial/unavailable transport returns `chrome_connection_failed`; setup expiry returns `chrome_setup_required`. Do not retry a denied connection automatically or substitute a separate profile. The normal-profile route uses Chrome’s approved loopback connection, not private-pipe launch flags on the default data directory.

## User interaction

The provider opens in the approved normal profile, where the user’s usual clipboard, extensions and saved-password tools remain available according to their own settings. The helper does not copy or read a password vault. The user handles any password autofill unlock, MFA, passkey or CAPTCHA required by Chrome/the provider. A retained signed-in account may complete immediately, which must be clear in the approved local action.

The collector detects the required fields and final page, encrypts the session and returns it automatically. Missing optional fields do not delay it. There is no second Beeper transfer click and the user need not return to chat to say “done.” Closing the provider window before completion, cancellation or expiry stops the transfer.

After returning ciphertext, the same window displays **You can close this window now**. This means the local handoff is ready, not that Server has accepted it. The parent command finishes immediately while a detached worker keeps only that completion window alive until it is closed, for at most five minutes. Do not await window closure before submission. Cleanup closes only the helper-created target and disconnects, preserving normal Chrome and unrelated tabs. If Chrome revokes/disconnects access, stop without reconnecting; a remaining helper tab can be closed by the user. This is not a persistent service.

## Deliver the encrypted session

The final **Shell/AwaitShell** result has `data.state: encrypted-transfer-ready` and an `envelope`. Pass just that envelope object as JSON on stdin to this command on the cloud computer:

```sh
python3 HELPER browser-finish --stdin
```

Use the cloud tool's supported stdin input or write the returned ciphertext to a cloud file as data. Do not interpolate values into shell code, include progress records in the envelope, or ask the user to copy anything. The result already contains the ciphertext, so no extra local Read/CopyToBox action is needed. Submit immediately once; the fresh local approval covered this transfer.

If the local tool cannot return the envelope, use its saved `request.json.encrypted.json` through the actual **CopyToBox** schema and finish with the retained file interface:

```sh
python3 HELPER browser-finish --file ENCRYPTED_FILE.json
```

The cloud helper authenticates/decrypts it, checks the same pending login step, consumes the request before submission, and sends the required fields directly to Beeper Server. Encryption uses X25519, HKDF-SHA-256, and AES-256-GCM with the full request bound as authenticated context. No Cloudflare tunnel or public receiver is needed. Grok handles the ciphertext, not session plaintext in its transcript.

Check `network-show` and `accounts` afterward, then a scoped chat read. An encrypted transfer being ready is not proof of Beeper accepting it or of messaging readiness. If delivery fails or times out, inspect the current state before requesting a new approval; never replay or automatically repeat submission. Follow the [recovery sequence](login-audit.md#keep-connection-recovery-simple) to distinguish transfer expiry from an expired bridge transaction. Direct mode emits safe `opening`/`collecting` progress, then the result. Only the explicitly selected reviewed alternative below waits at `phase: ready` for a transfer click.

`browser-cancel` invalidates the transfer while preserving the pending network login. `network-cancel` cancels that login and invalidates its transfer. Cancellation on the PC closes collection without a payload. After cancellation or expiry, prepare a new request and require approval again. Remove temporary public packages and encrypted output after completion; retain the user's owned browser profile unless they request its removal.

## Other supported modes

Only if the user requests a separate profile, add `--separate-profile` to `connect REQUEST.json --transfer-on-login`. This retains v0.6.2’s private-pipe browser under `~/.beeper-browser/profiles/PROVIDER`, with no Chrome setting or connection prompt. It lacks the user’s ordinary extensions and saved passwords; explain that difference before choosing it. It keeps its own provider sign-in. A completion window can occupy that dedicated profile until closed or the five-minute limit; never copy a profile to bypass its lock.

If the user explicitly wants to review the provider account and approve again after login, omit `--transfer-on-login`. The legacy local page offers existing-profile reuse or a separate window and requires **Approve this transfer**. Existing-profile reuse still requires Chrome’s setting/prompt. The collector refreshes after transfer approval and preserves unrelated tabs. This extra Beeper review is not the default.

Grok's native cookie import remains optional when exposed. It requires a new user approval for this transfer and the receiving cloud browser endpoint, then `browser-start --browser native --cdp-url http://127.0.0.1:PORT`. Do not rely on a standing import grant. The bundled local path above does not depend on this feature.

Only when the user explicitly chooses to sign in on Grok's computer, `browser-start --browser cloud` opens a provider window there. It cannot supply the PC's clipboard/password manager. `webview-connect` is a compatibility alias for that explicit cloud choice. On new transactions, the helper defaults to `local`; pass it explicitly to override a previously saved cloud preference.

## Supported login requirements

The shared collector covers Instagram, Facebook/Messenger, LinkedIn, X/Twitter, Discord, and Slack provider domains when the live Server offers a compatible `cookies` step. It supports named cookies (including HttpOnly), local-storage entries, and request headers from the selected provider tab. Reuse and fresh local sign-in share those adapters. Required `special` extraction without a supported alternative is rejected; bridge-supplied `extractJS` never runs. These adapters are not a claim that every provider flow has been tested with real accounts.

Beeper account email/registration/recovery inputs and network QR/device-code/phone-code flows retain their native workflows. They are not interchangeable with website-session login. If a bridge only offers direct username/password API login, explain the missing upstream website-login support; never substitute a generic password form or invent an OAuth/cookie flow.

Sources: [Chrome's approved existing-session connection](https://developer.chrome.com/docs/devtools/agents/get-started/configuration), [Grok local execution](https://docs.x.ai/grok-bot/settings-and-notifications), [Beeper login step API](https://github.com/beeper/desktop-api-js/blob/next/src/resources/bridges/login-sessions/steps.ts).
