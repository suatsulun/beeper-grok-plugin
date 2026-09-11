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

Grok installs Server, guides Beeper email sign-in and device verification, and connects the selected networks. **Your own browser is the default for compatible website logins.** The companion extension opens the provider website, uses its existing session or your normal sign-in/password manager, and sends only the requested session fields to Beeper Server through an encrypted, temporary handoff.

You can instead choose **Grok's computer**: a dedicated Chrome window opens the provider website and transfers the required session directly to Server. QR/device-code flows keep their native steps. The plugin no longer presents generic network password or cookie forms. Browser login must be offered by the live Server bridge; domain support alone does not establish that a network can connect.

## Connect your browser

Install the companion extension once in Chrome or Edge on your own PC:

1. Open `chrome://extensions` (or `edge://extensions`) and enable Developer mode.
2. Choose **Load unpacked** and select this repository's `browser-extension` folder, or that folder from the extracted plugin ZIP.
3. Ask Grok to connect a network. Open its pairing link **on your own PC**, open **Beeper Browser Connect** from Extensions, review the selected network, and click **Open website and connect**.

Site permissions are requested for the selected provider and the temporary handoff destination. Finish sign-in/MFA on the provider's website. The extension submits the requested session automatically and tells you to return to Grok. See [browser login and compatibility](skills/beeper/references/browser-login.md).

## Install the plugin

For local development in Grok CLI:

```sh
grok plugin install /absolute/path/to/beeper-grok-plugin --trust
grok plugin enable beeper
```

Restart Grok, open `/skills`, or invoke `/beeper`. The skill is also discoverable from natural-language Beeper requests. Installing the plugin only installs its files; Server installation happens when you ask Grok to set up Beeper.

For Grok Bot, install and enable the packaged skill through the plugin distribution available to your account. Private installed skills can be enabled under **Settings → Plugins → Yours**. The public marketplace submission remains a separate step; installing into your local CLI does not install into Grok Bot's cloud computer. See [Grok Bot skills](https://docs.x.ai/grok-bot/skills-routines-and-automations).

## Requirements

- Python 3.10+ and Linux x86_64/aarch64 for automatic installation.
- Network access to Beeper, GitHub releases, and the Python package CDN.
- Node.js 22+ on the Server computer for browser-session handoff; no npm dependencies.
- Chrome/Edge and the companion extension on your PC for the default browser option. Chrome/Chromium plus a graphical desktop on the Server computer for the Grok-computer option.
- Browser takeover for Beeper account codes and native network code steps.
- Beeper CLI 0.6.2 and qrcode 8.2 are downloaded from their official releases with pinned SHA-256 checksums. Server is installed through Beeper's official CLI.

## Authentication and data

Data lives in `/workspace/.beeper-grok` on Grok Bot, or `~/.local/share/beeper-grok-plugin` elsewhere. `BEEPER_PLUGIN_HOME` can select another persistent location. Credentials, Server data, and pending login state stay outside the plugin files, with private filesystem permissions. All Bots on the same Grok account share the cloud computer. See [Grok Bot's computer model](https://docs.x.ai/grok-bot/computer-and-apps).

The plugin uses your Beeper sign-in and the session fields required by each selected network. The extension reads only the chosen provider's requested cookies, named local-storage entries, and named request headers from its login tab. It never reads the browser's cookie database or password vault. Beeper Server necessarily receives the decrypted session. Pairing and private input expire after ten minutes; submitted values stay out of chat and command arguments. Cloud browser profiles persist in the private data directory. Messages you ask Grok to retrieve enter the conversation. Sending delivers the requested content to the selected recipient.

The plugin uses the [official Beeper CLI and API](https://github.com/beeper/cli). It includes no Desktop installer or Desktop MCP connection. Grok executes the skill's Server setup and messaging commands directly.

The helper downloads tools from `github.com/beeper/cli/releases` and `files.pythonhosted.org`. Local-browser handoff additionally downloads checksum-pinned cloudflared 2026.9.1 from `github.com/cloudflare/cloudflared/releases`. Its temporary Quick Tunnel exposes only the one-use handoff receiver, never the Beeper API. Session values are encrypted in the extension with ECDH P-256, HKDF-SHA-256 and AES-256-GCM; Cloudflare carries ciphertext and connection metadata. The receiver closes after submission, cancellation or expiry. **Quick Tunnels are a testing transport, without an uptime guarantee; production distribution needs a supported relay service.** See [Cloudflare Quick Tunnels](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/). Same-computer testing can use `browser-start --loopback` without Cloudflare.

The Beeper API stays at `http://127.0.0.1:<port>`. Beeper CLI downloads Server through `api.beeper-staging.com` and its release-CDN redirects. Server then connects to Beeper's production authentication/sync services and your selected networks. The plugin adds no telemetry; Beeper's own software is governed by its [privacy policy](https://www.beeper.com/privacy).

## Validation status

Automated tests cover Server onboarding, encrypted handoff, replay/expiry/stale-step rejection, provider scoping, and browser collection against synthetic provider pages. **A full run with actual network accounts in Grok Bot is still required before marketplace submission.** See the [test procedure](tests/README.md).

Beeper's current Server installer downloads a nightly artifact. Upstream issues affecting device verification and headless chat availability are documented in the [setup guide](skills/beeper/references/setup.md#known-upstream-limits), along with the implemented verification workaround. Network support depends on the bridges available on the Server and the login facilities in the Bot computer; the plugin does not claim every network is tested.

## Support

- [Beeper CLI](https://github.com/beeper/cli)
- [Setup and troubleshooting](skills/beeper/references/setup.md)
- [Report a plugin issue](https://github.com/suatsulun/beeper-grok-plugin/issues)

## License

Plugin files: [MIT](LICENSE). Beeper CLI, qrcode and cloudflared retain their upstream licenses and terms when downloaded. The [Beeper icon](https://www.beeper.com/wp-content/uploads/2026/05/beeper-favicon.png) comes from Beeper's website; Beeper branding belongs to its owners and is not covered by the plugin's MIT license.
