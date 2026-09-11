# Sign in on a provider website

Use the current `cookies` step returned by Server. Do not invent flow IDs or turn a password/mobile-API flow into a cookie flow. Keep the existing login transaction.

## Check the existing environment

```sh
python3 HELPER browser-check
python3 HELPER browser-plan
```

`browser-check` reports the PATH Node version, browser-module readiness, built-in WebSocket availability, and an existing Chrome executable. It makes no downloads or account requests. Grok's **Node 20.19.2 is supported**; the helper enables its built-in WebSocket flag when needed. There are no npm dependencies or Node installers. Beeper Server's embedded Node is separate. If the check fails, report the specific missing capability; do not ask users to install runtimes, browsers, extensions, or relays.

`browser-plan` validates the pending step and returns its provider, login URL, and scoped origins. It returns no credentials and does not start another login.

## Prefer native Grok import when available

First check the actual capabilities exposed to this Bot. Grok must provide **both** a supported cookie approval/import facility for the user's browser and access to the **receiving cloud Chrome's loopback CDP endpoint**. Native import is platform/account dependent and may be feature-gated. A desktop app containing import code is not proof that this Bot can call it. Do not invent a tool name, invoke private desktop RPCs, enable hidden feature gates, or inspect protected app credentials.

When both capabilities are available:

1. Ask Grok's native facility to import only the selected provider origins from `browser-plan`. Let the user choose the browser/profile and approve access. Honor denial or cancellation. Do not collect raw cookie values into tool output or chat.
2. Use the receiving browser endpoint supplied by Grok's supported browser environment. Never guess or scan ports, attach to a browser on the user's PC, copy its profile, or launch their browser with debugging enabled.
3. After approved import, run the following, substituting the **actual supplied port**:

```sh
python3 HELPER browser-start --browser native --cdp-url http://127.0.0.1:PORT
```

This opens a new provider tab in that receiving browser, waits for the required fields, and submits them privately to Beeper Server. It closes its own tab when finished and leaves Grok's browser and other tabs open. The endpoint is not persisted. Existing cookies can restore website sessions; native import does not promise transfer of local storage, hardware-bound credentials, or MFA. Further website sign-in may be necessary.

This is a conditional integration point, not a built-in replacement for Grok's import facility. If either capability is unavailable, say so and offer website sign-in below. If the user requires their own PC only, stop that connection with this specific limitation. Do not reintroduce extension installation or cookie-file uploads.

## Provider website on Grok's computer

```sh
python3 HELPER browser-start --browser cloud
```

Keep the command running in a yielding/background tool. It opens the provider website in a dedicated Chrome/Chromium window on the Bot computer. Hand over that window for sign-in and MFA. The helper automatically submits only the requested fields directly to Server; it never asks for a network password in a plugin form.

The helper uses the existing Chrome, a graphical desktop, and Node. `BEEPER_CHROME_BINARY` can select an already installed executable. Chrome uses a private persistent profile under `browser-profiles/PROVIDER` in the plugin data directory, with private debugging pipes. It closes on completion or cancellation. No relay or extension is involved.

For a new transaction, plain `browser-start` opens this website unless given a native endpoint. The skill checks native-import availability first. `connect BRIDGE --flow FLOW --browser native|cloud` saves a preference. A saved native preference always requires the endpoint; it never silently falls back. Legacy `local` preferences map to native import, preserving pending v0.4 sessions without reinstalling the old companion. `webview-connect BRIDGE --flow FLOW` is a compatibility alias for the cloud website option.

Grok's cloud browser cannot automatically use the PC's clipboard or password manager. Use a supported Grok paste/secret-input facility only when exposed for this interaction; otherwise explain the limitation. Never ask for passwords, cookies, or recovery keys in ordinary chat. The plugin alone cannot supply cross-computer clipboard transport.

## Compatibility and recovery

The provider registry covers Instagram, Facebook/Messenger, LinkedIn, X/Twitter, Discord, and Slack domains. The live Server must offer a compatible `cookies` step. Domain adapters do not establish live-tested network support. The collector supports named cookies (including HttpOnly), local-storage entries, and request headers from the new selected-provider tab, with domain/URL and field checks before submission. Required custom `special` extraction is unsupported unless the field has a supported alternative. Bridge-supplied `extractJS` never runs.

If only username/password API login exists, explain that the bridge needs upstream website-login support. QR/device-code/phone-code flows keep their native steps. Beeper email/registration/recovery keeps its private forms.

Browser collection expires after ten minutes. `network-cancel` ends the saved Server login and stops the waiting helper. On error, cancellation, expiry, or uncertain API delivery, inspect `network-show` and `accounts` before retrying; never automatically repeat a submission. The helper verifies the pending step has not changed before sending fields. A successful submission is not proof of a connected network: check the account state and a scoped chat read.

Source: [Beeper login step API](https://github.com/beeper/desktop-api-js/blob/next/src/resources/bridges/login-sessions/steps.ts).
