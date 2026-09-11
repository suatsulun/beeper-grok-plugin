# Provider sign-in on the user's PC

Default to the user's PC for supported network website logins. Reuse their approved existing Chrome session or open a separate provider login window there. **Every local session transfer requires a fresh approval.** Do not substitute Grok's cloud browser because local access is unavailable.

Use the existing `cookies` step returned by Server. Keep its saved login transaction. Do not invent flow IDs or convert password/mobile-API flows into cookie flows.

## Check both computers

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

## Prepare and copy the bundled helper

On the cloud computer:

```sh
python3 HELPER browser-start --browser local
```

It returns `localPackage`: a JSON package containing five plugin modules and `request.json`, each base64-encoded with a SHA-256. The request identifies the provider, permitted fields, receiver public key, and ten-minute expiry. The private decryption key remains on the cloud computer. Repeated preparation resumes an unexpired request; it does not approve a transfer.

Use **CopyFromBox** according to its exposed schema to copy this public cloud package to the selected PC, then the approved machine-targeted **Shell** to decode that package into a private, disk-backed directory on the PC, such as `~/.cache/beeper-browser/REQUEST_ID` (the platform equivalent on Windows). Verify every SHA-256 and allow only these filenames: `local_browser.mjs`, `cloud_browser.mjs`, `browser_protocol.mjs`, `browser_transfer.mjs`, `providers.mjs`, `request.json`. Create files with private permissions where supported. This is executing the plugin's bundled code, not installing an application or extension. The agent performs this step; do not ask the user to download dependencies, reconstruct files, or copy session values.

If no file-copy tool exists, the public package can be carried as base64 in approved local command input and decoded with Node's built-in `fs` and `crypto`. Keep command arguments as data, honor shell size limits, and never include the cloud `browser-transfer.json`, target/config files, or private key. Do not use `/tmp` for the helper or browser profiles.

Run on the **PC**, keeping the local tool/process alive:

```sh
env ELECTRON_RUN_AS_NODE=1 '/opt/Grok Bot/grok-bot' LOCAL_DIR/local_browser.mjs connect LOCAL_DIR/request.json
```

Use the same verified local runtime as the preflight. The helper opens its approval page in the PC's Chrome and returns a local `approvalURL`. If the page did not open, open that URL **on the PC**. The Bot must never click either approval button for the user.

## User interaction

The local page offers two choices:

- **Use my open Chrome profile:** Chrome 144+ can expose an existing session after the user enables its built-in setting at `chrome://inspect/#remote-debugging` and approves Chrome's connection prompt. The helper opens that settings page when needed but never enables it itself. Chrome selects the shared profile; ask the user to check the account on the provider website. Chrome's connection permission covers the browser, while this helper reads only requested fields from its own selected-provider tab. No cookie database, password vault, profile copy, or extension is used.
- **Open a separate login window on this PC:** the provider site opens in an owned Chrome profile under `~/.beeper-browser/profiles/PROVIDER`. The user signs in there with their PC clipboard. Their usual browser extensions/autofill are not automatically copied into this separate profile.

Both paths open the actual provider website locally. Once the necessary session is available, the approval page asks **“Approve this transfer.”** Let the user review the provider account and click it themselves. No saved permission, earlier login, previous transfer, or chat response replaces this click. Denial/expiry sends no session. The collector refreshes and re-reads the session after approval so it does not submit a pre-approval account snapshot.

The helper then closes its provider tab, leaving an existing browser and unrelated tabs open; an owned browser closes. It returns an encrypted envelope and saves `request.json.encrypted.json`. The helper does not return raw cookies, tokens, local storage, headers, or passwords. The small local HTTP approval server binds only to loopback and closes at completion.

## Deliver the encrypted session

Use **CopyToBox** to return the encrypted file from that same PC, or carry the encrypted envelope returned by the local **Shell/AwaitShell** result. Check the actual copy-tool schema for source and destination arguments. Never return the browser profile or any plaintext session file. Save it as an ordinary JSON file on the cloud computer, then run:

```sh
python3 HELPER browser-finish --file ENCRYPTED_FILE.json
```

The cloud helper authenticates/decrypts it, checks the same pending login step, consumes the request before submission, and sends the required fields directly to Beeper Server. Encryption uses X25519, HKDF-SHA-256, and AES-256-GCM with the full request bound as authenticated context. No Cloudflare tunnel or public receiver is needed. Grok handles the ciphertext, not session plaintext in its transcript.

Check `network-show` and `accounts` afterward, then a scoped chat read. An encrypted transfer being ready is not proof of Beeper accepting it or of messaging readiness. If delivery fails or times out, inspect the current state before requesting a new approval; never replay or automatically repeat submission.

`browser-cancel` invalidates the transfer while preserving the pending network login. `network-cancel` cancels that login and invalidates its transfer. Cancellation on the PC closes collection without a payload. After cancellation or expiry, prepare a new request and require approval again. Remove temporary public packages and encrypted output after completion; retain the user's owned browser profile unless they request its removal.

## Other supported modes

Grok's native cookie import remains optional when exposed. It requires a new user approval for this transfer and the receiving cloud browser endpoint, then `browser-start --browser native --cdp-url http://127.0.0.1:PORT`. Do not rely on a standing import grant. The bundled local path above does not depend on this feature.

Only when the user explicitly chooses to sign in on Grok's computer, `browser-start --browser cloud` opens a provider window there. It cannot supply the PC's clipboard/password manager. `webview-connect` is a compatibility alias for that explicit cloud choice. On new transactions, the helper defaults to `local`; pass it explicitly to override a previously saved cloud preference.

## Supported login requirements

The shared collector covers Instagram, Facebook/Messenger, LinkedIn, X/Twitter, Discord, and Slack provider domains when the live Server offers a compatible `cookies` step. It supports named cookies (including HttpOnly), local-storage entries, and request headers from the selected provider tab. Reuse and fresh local sign-in share those adapters. Required `special` extraction without a supported alternative is rejected; bridge-supplied `extractJS` never runs. These adapters are not a claim that every provider flow has been tested with real accounts.

Beeper account email/registration/recovery inputs and network QR/device-code/phone-code flows retain their native workflows. They are not interchangeable with website-session login. If a bridge only offers direct username/password API login, explain the missing upstream website-login support; never substitute a generic password form or invent an OAuth/cookie flow.

Sources: [Chrome's approved existing-session connection](https://developer.chrome.com/docs/devtools/agents/get-started/configuration), [Grok local execution](https://docs.x.ai/grok-bot/settings-and-notifications), [Beeper login step API](https://github.com/beeper/desktop-api-js/blob/next/src/resources/bridges/login-sessions/steps.ts).
