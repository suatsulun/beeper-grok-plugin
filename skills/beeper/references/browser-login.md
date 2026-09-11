# Sign in on a provider website

Use the `cookies` step returned by this Server, with its existing saved login session. Do not invent flow IDs or convert a password/mobile-API flow into a cookie flow.

## Default: the user's own browser

```sh
python3 HELPER browser-start
```

Keep the command running in a yielding/background tool. It starts a temporary encrypted handoff and prints `pairingURL`. Give that link to the user to open **on their own PC**, where their password manager and signed-in accounts live. The pairing capability is temporary; share it only in this private conversation. Do not fetch/log its fragment or expose it in public messages.

If the companion extension is not installed, provide the plugin ZIP or the `browser-extension` folder. The user enables Developer mode at `chrome://extensions` or `edge://extensions`, chooses **Load unpacked**, and selects that folder. Installation is a one-time user step; do not claim the plugin can silently install extensions into their local browser.

On the pairing page, they open **Beeper Browser Connect**, review the provider/destination, and click **Open website and connect**. The extension asks for the selected site's permissions and opens its real website. It uses the account already signed in there, or waits for the user to finish password/MFA sign-in. It automatically transfers only the requested session fields, encrypted to the receiver. No cookie copy/paste or password-manager transfer to Grok is needed.

The command returns the next network step after submission. Check `network-show` if a session remains, then `accounts`. A successful handoff means fields were submitted; only a connected account and a scoped read establish that messaging works.

## Alternative: Grok's computer

Only when the user chooses it:

```sh
python3 HELPER browser-start --browser cloud
```

This resumes the same pending login and opens the provider website in a dedicated Chrome/Chromium window on the Bot computer. Let the user take over that window for sign-in and MFA. The helper collects the required session fields and submits them directly to the local Beeper API. It needs Node.js 22+, Chrome/Chromium, and a graphical desktop. `BEEPER_CHROME_BINARY` may select the installed Chrome executable. It does not depend on CLI 0.6.2's `Bun.WebView` support.

The browser uses a private persistent profile under `browser-profiles/PROVIDER` in the plugin data directory. Chrome debugging uses private process pipes, not a network port. The owned browser closes when done or cancelled. The user's PC clipboard/password manager is still separate from this cloud browser. Default to the local-browser option when that separation prevents sign-in; never collect passwords in chat.

`connect BRIDGE --flow FLOW --browser cloud` saves this choice for that transaction. `webview-connect BRIDGE --flow FLOW` remains a compatibility alias for connecting and starting this cloud option.

## Compatibility

The provider registry covers Instagram, Facebook/Messenger, LinkedIn, X/Twitter, Discord, and Slack domains. Both browser options support named cookies (including HttpOnly), named local-storage entries, and named HTTP request headers from the selected provider's login tab. The live Server must offer a `cookies` step with compatible field sources. These domain adapters are not a claim of live-tested network support.

Required `special` sources or arbitrary `extractJS` are unsupported unless the same field has a supported alternative source. Domain escapes, malformed requirements and unsupported regular expressions are rejected. There is no generic password/cookie-form fallback. If only direct username/password API login exists, explain that this bridge needs upstream website-login support and stop that connection. QR/device-code/phone-code flows retain their native steps; Beeper email/registration/recovery uses its existing private forms.

## Transport and recovery

The default cloud handoff uses checksum-pinned cloudflared 2026.9.1 and a temporary `trycloudflare.com` address. Only the separate handoff receiver is exposed; the Beeper API remains on loopback. Session fields use ECDH P-256, HKDF-SHA-256, and AES-256-GCM, with the pairing descriptor bound as authenticated context. Cloudflare carries ciphertext and metadata; only the receiver has the private key. Links expire in ten minutes and are consumed before submitting to Beeper. The receiver checks that the pending login step is still the same.

Cloudflare Quick Tunnels are a **testing transport**, without an uptime guarantee. Production distribution needs a supported relay service. The helper uses HTTP/2 and requires outbound TCP 7844 to Cloudflare, as well as HTTPS for the pairing page. It waits for a registered tunnel connection before issuing the link. If a relay cannot start, explain the error; offer the cloud-browser option without silently switching.

For local Grok CLI testing where browser and Server are on the same PC, `browser-start --loopback` avoids the relay. Do not use this flag when the user's browser is on another computer.

Cancel in the extension to stop collection. Use `network-cancel` in the helper to cancel the Server transaction and stop its waiting handoff. Close/cancel the running helper to end only the handoff. On expiry, use `network-show` before starting a fresh handoff. A failed/uncertain delivery is never automatically repeated: inspect `network-show` and `accounts` first. Site permission denial collects nothing. The user can revoke granted site permissions or remove the extension through their browser's extension settings.

If the pairing page shows a certificate warning or a router page, stop that handoff. The network may be redirecting or filtering the relay hostname. Do not disable TLS verification, bypass a certificate warning, or change the user's DNS/router controls automatically. Report the observed failure; local-browser transfer needs a relay that the user's browser can reach with a valid HTTPS certificate. The explicitly chosen cloud-browser option does not use this relay.

Sources: [Chrome cookies API](https://developer.chrome.com/docs/extensions/reference/api/cookies), [Chrome optional permissions](https://developer.chrome.com/docs/extensions/reference/api/permissions), [Beeper login step API](https://github.com/beeper/desktop-api-js/blob/next/src/resources/bridges/login-sessions/steps.ts), [Cloudflare Quick Tunnels](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/).
