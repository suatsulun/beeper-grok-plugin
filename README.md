<p align="center">
  <img src="assets/logo.png" alt="Beeper" width="96" height="96">
</p>

# Beeper for Grok Bot

Ask Grok to install Beeper Server, sign in to Beeper, connect your chat networks, and work with your messages. The plugin includes a `/beeper` skill and helpers that run the setup workflow on Grok Bot's cloud computer.

```text
Set up Beeper and connect my WhatsApp account.
Continue my Beeper setup.
Connect Telegram to Beeper.
Summarize my unread Beeper chats.
Draft a reply to Alex's latest message.
```

Grok installs Server, guides Beeper sign-in and device verification, and connects your selected networks. **No companion extension, Node upgrade, or manual dependency installation is required on the normal Grok Bot image.** The plugin uses the Python, Node, and Chrome already there. Grok automatically downloads the Beeper CLI, Server, and QR support when you ask it to set up Beeper.

**Website login defaults to your PC.** Grok Desktop runs the plugin's bundled helper there, using its approved local execution and file-copy tools. Choose your existing Chrome session, or sign in on the provider's actual website in a separate local window. You review the provider account and click **Approve this transfer** each time. Only an encrypted session returns to Beeper Server on Grok's computer.

Existing-session reuse uses Chrome 144+'s built-in connection permission. Enable it yourself at `chrome://inspect/#remote-debugging`, then approve Chrome's prompt. No extension, cookie-database reader, or extra application is needed. Grok must expose its local execution/copy tools and you must approve the local actions. If those are unavailable, the plugin reports that limitation. A cloud browser is used only if you explicitly choose it. QR/device-code flows keep their native steps. The plugin does not collect network passwords in generic forms. Browser login must be offered by the live Server bridge. See [browser login and compatibility](skills/beeper/references/browser-login.md).

**Instagram does not need every optional cookie to reach approval.** Its upstream bridge requires `sessionid`, `csrftoken`, and `ds_user_id`; `shbid`, `shbts`, `rur`, `mid`, and `ig_did` are optional. Version 0.6.1 recognizes those optional cookies when the Server omits requirement flags, collects them if present, and does not ask you to browse more or sign in again just to create them. Explicit bridge requirements still take precedence. See the [cookie requirements guide](skills/beeper/references/browser-login.md#instagram-cookie-requirements) for the source and limitations.

Version 0.6.1 also handles X's optional browser inputs, labels optional native form fields, and shows clearer progress before and after approval. Grok receives required-field diagnostics without session values, and CLI errors retain their specific cause. The [login audit](skills/beeper/references/login-audit.md) covers all six provider adapters, native methods, and recovery without unnecessary sign-ins. Slack's inspected token flow needs extraction this helper does not support; advanced X challenges can also require unsupported generation. Neither limitation is fixed by skipping required fields.

## Install the plugin

For local development in Grok CLI:

```sh
grok plugin install /absolute/path/to/beeper-grok-plugin --trust
grok plugin enable beeper
```

Restart Grok, open `/skills`, or invoke `/beeper`. The skill is also discoverable from natural-language Beeper requests. Installing the plugin only installs its files; Server installation happens when you ask Grok to set up Beeper.

For Grok Bot, install and enable the packaged skill through the plugin distribution available to your account. Private installed skills can be enabled under **Settings → Plugins → Yours**. The public marketplace submission remains a separate step; installing into your local CLI does not install into Grok Bot's cloud computer. See [Grok Bot skills](https://docs.x.ai/grok-bot/skills-routines-and-automations).

## Runtime and downloads

The helper runs on Linux x86_64/aarch64 with Python 3.10+, Node, and Chrome/Chromium. **Grok's Node 20.19.2 works**; version 0.4.0's Node 22+ requirement was unnecessary. On the PC, the helper uses an existing compatible Node or the Node runtime inside the already installed Grok Desktop app. Linux Grok 0.44.0's embedded Node 24.15.0 was verified. There are no npm dependencies, runtime installers, browser-extension packages, or public relays. If a custom Bot image lacks a required runtime, the plugin reports the environment limitation instead of asking users to install components.

```sh
python3 skills/beeper/scripts/beeper.py browser-check
```

This checks the existing runtime and browser availability without downloading software, accessing accounts, or starting Server. This cloud check does not check the PC. The local helper has its own `check` command, run on the selected desktop through Grok.

Automatic setup downloads Beeper CLI 0.6.2 and qrcode 8.2 from their official releases with pinned SHA-256 checksums. The CLI downloads Server through Beeper's installer. This is automatic setup, **not an offline bundle**. Beeper account code forms still use takeover. Network website sign-in occurs on the PC, where its clipboard is available. Separate local Chrome profiles do not automatically inherit normal browser extensions/autofill. No cross-computer clipboard sync is supplied.

## Authentication and data

Data lives in `/workspace/.beeper-grok` on Grok Bot, or `~/.local/share/beeper-grok-plugin` elsewhere. `BEEPER_PLUGIN_HOME` selects another persistent location. Credentials and pending login state stay outside the plugin files with private filesystem permissions. All Bots on one Grok account share its cloud computer. See [Grok Bot's computer model](https://docs.x.ai/grok-bot/computer-and-apps).

The browser helper collects only fields requested by the selected provider: required fields and any optional fields present, from named cookies, local-storage entries, and request headers in its own provider tab. It never runs bridge-supplied JavaScript or reads the browser's cookie database or password vault. Chrome grants a browser debugging connection; the helper limits its collection to that provider. Existing-session reuse still depends on the provider accepting that session; MFA or fresh sign-in may be required.

The helper binds its temporary approval page to loopback on the PC. It discovers existing Chrome only through its user-enabled `DevToolsActivePort` metadata; it does not scan ports or enable Chrome permissions itself. It closes its own provider tab and preserves other tabs and an existing browser. Separate local login profiles persist under `~/.beeper-browser/profiles` and use private debugging pipes.

Each ten-minute transfer uses an ephemeral X25519 key exchange, HKDF-SHA-256, and AES-256-GCM. The receiver's private key stays in the cloud data directory; Grok's normal local-tool/file transport carries ciphertext. Requests are bound to the pending Beeper step and consumed before submission to prevent replay after ambiguous failures. No public receiver or relay is needed. Submitted values stay out of chat and command arguments. Messages requested by the user enter the conversation; sending delivers content to the selected recipient.

The plugin uses the [official Beeper CLI and API](https://github.com/beeper/cli). It includes no Beeper Desktop installer or Desktop MCP connection. The API stays at `http://127.0.0.1:<port>`. Tool downloads use GitHub releases and the Python package CDN; Server downloads use `api.beeper-staging.com` and Beeper's release CDN. Server then connects to Beeper's production services and the selected networks. The plugin adds no telemetry; Beeper software follows its [privacy policy](https://www.beeper.com/privacy).

## Validation status

Automated checks cover onboarding, scoped collection, both local browser choices, real Chromium approval forms, denial, encryption, expiry, stale requests, and replay protection with synthetic credentials. The local helper also runs using the installed Grok Desktop runtime without downloads. Actual Grok machine-targeted execution, Chrome's existing-profile permission prompt, and real provider accounts still need user acceptance testing. Linux is tested; macOS/Windows paths and UI remain unverified. See the [test procedure](tests/README.md).

Beeper's installer currently downloads a nightly Server artifact. Device-verification and headless chat-availability limits are documented in the [setup guide](skills/beeper/references/setup.md#known-upstream-limits). Local checks do not establish marketplace approval or support for every network.

## Support

- [Beeper CLI](https://github.com/beeper/cli)
- [Setup and troubleshooting](skills/beeper/references/setup.md)
- [Report a plugin issue](https://github.com/suatsulun/beeper-grok-plugin/issues)

## License

Plugin files: [MIT](LICENSE). Beeper CLI and qrcode retain their upstream licenses and terms when downloaded. The [Beeper icon](https://www.beeper.com/wp-content/uploads/2026/05/beeper-favicon.png) comes from Beeper's website; Beeper branding belongs to its owners and is not covered by the plugin's MIT license.
