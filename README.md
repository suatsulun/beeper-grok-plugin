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

For website sign-in, the skill first checks whether Grok exposes its built-in, user-approved browser-cookie import **and** access to the receiving cloud browser. When both are available, it can reuse your own browser's session without an extension. Availability depends on Grok's platform, account features, and tool access; the plugin cannot enable that feature itself.

Otherwise, Grok opens the provider's actual website on its computer for takeover sign-in. QR/device-code flows keep their native steps. The plugin does not collect network passwords in generic forms. Browser login must be offered by the live Server bridge. See [browser login and compatibility](skills/beeper/references/browser-login.md).

## Install the plugin

For local development in Grok CLI:

```sh
grok plugin install /absolute/path/to/beeper-grok-plugin --trust
grok plugin enable beeper
```

Restart Grok, open `/skills`, or invoke `/beeper`. The skill is also discoverable from natural-language Beeper requests. Installing the plugin only installs its files; Server installation happens when you ask Grok to set up Beeper.

For Grok Bot, install and enable the packaged skill through the plugin distribution available to your account. Private installed skills can be enabled under **Settings → Plugins → Yours**. The public marketplace submission remains a separate step; installing into your local CLI does not install into Grok Bot's cloud computer. See [Grok Bot skills](https://docs.x.ai/grok-bot/skills-routines-and-automations).

## Runtime and downloads

The helper runs on Linux x86_64/aarch64 with Python 3.10+, Node, and Chrome/Chromium. **Grok's Node 20.19.2 works**; version 0.4.0's Node 22+ requirement was unnecessary. There are no npm dependencies, runtime installers, browser-extension packages, or public relays. If a custom Bot image lacks a required runtime, the plugin reports the environment limitation instead of asking users to install components.

```sh
python3 skills/beeper/scripts/beeper.py browser-check
```

This checks the existing runtime and browser availability without downloading software, accessing accounts, or starting Server. It does not establish whether Grok has enabled native cookie import.

Automatic setup downloads Beeper CLI 0.6.2 and qrcode 8.2 from their official releases with pinned SHA-256 checksums. The CLI downloads Server through Beeper's installer. This is automatic setup, **not an offline bundle**. Browser takeover is needed for Beeper account codes and for website sign-in when native import is unavailable. A working cloud clipboard or password-manager transfer is not supplied by this plugin.

## Authentication and data

Data lives in `/workspace/.beeper-grok` on Grok Bot, or `~/.local/share/beeper-grok-plugin` elsewhere. `BEEPER_PLUGIN_HOME` selects another persistent location. Credentials and pending login state stay outside the plugin files with private filesystem permissions. All Bots on one Grok account share its cloud computer. See [Grok Bot's computer model](https://docs.x.ai/grok-bot/computer-and-apps).

The browser helper submits only the session fields required by the selected provider, through private process pipes to the local Beeper API. It supports named cookies, local-storage entries, and request headers; it never runs bridge-supplied JavaScript or reads the user's local cookie database or password vault. Native cookie access is handled by Grok's own approval/import feature. A cookie import may not restore local storage or other device-bound credentials, so further provider sign-in may be necessary.

Owned Chrome profiles persist in the private data directory and use private debugging pipes. Optional native import uses an explicitly supplied loopback endpoint for Grok's receiving cloud browser. The helper creates and closes its own tab there; other tabs and the browser remain open. It does not open a public endpoint or scan for browsers. Submitted values stay out of chat and command arguments. Messages requested by the user enter the conversation; sending delivers content to the selected recipient.

The plugin uses the [official Beeper CLI and API](https://github.com/beeper/cli). It includes no Beeper Desktop installer or Desktop MCP connection. The API stays at `http://127.0.0.1:<port>`. Tool downloads use GitHub releases and the Python package CDN; Server downloads use `api.beeper-staging.com` and Beeper's release CDN. Server then connects to Beeper's production services and the selected networks. The plugin adds no telemetry; Beeper software follows its [privacy policy](https://www.beeper.com/privacy).

## Validation status

Automated checks cover onboarding, provider scoping, stale/cancelled requests, private forms, and both browser transports with synthetic credentials on Node 20.19.2. Native import's **receiving browser** is tested; Grok's live approval/import integration and real network accounts still require acceptance testing. See the [test procedure](tests/README.md).

Beeper's installer currently downloads a nightly Server artifact. Device-verification and headless chat-availability limits are documented in the [setup guide](skills/beeper/references/setup.md#known-upstream-limits). Local checks do not establish marketplace approval or support for every network.

## Support

- [Beeper CLI](https://github.com/beeper/cli)
- [Setup and troubleshooting](skills/beeper/references/setup.md)
- [Report a plugin issue](https://github.com/suatsulun/beeper-grok-plugin/issues)

## License

Plugin files: [MIT](LICENSE). Beeper CLI and qrcode retain their upstream licenses and terms when downloaded. The [Beeper icon](https://www.beeper.com/wp-content/uploads/2026/05/beeper-favicon.png) comes from Beeper's website; Beeper branding belongs to its owners and is not covered by the plugin's MIT license.
