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

Grok installs Server, guides email sign-in and device verification, and presents the network's next login step. It prefers the network's own website or QR login when the Server offers one; browser-cookie login uses Beeper's CLI WebView to transfer the required session fields. For Beeper account codes, recovery keys, and network input steps, Grok can open a private form on its computer for user takeover. Availability of a browser login must be checked for each network, including Instagram.

Grok's browser runs on its cloud computer. Your local clipboard and password manager are not automatically available there. See [credential handoff options](skills/beeper/references/setup.md#clipboard-and-password-managers); the plugin does not implement clipboard synchronization or a local-browser session transfer.

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
- Browser access and user takeover for sensitive authentication steps. Some networks additionally require the CLI's Chrome WebView backend.
- Beeper CLI 0.6.2 and qrcode 8.2 are downloaded from their official releases with pinned SHA-256 checksums. Server is installed through Beeper's official CLI.

## Authentication and data

Data lives in `/workspace/.beeper-grok` on Grok Bot, or `~/.local/share/beeper-grok-plugin` elsewhere. `BEEPER_PLUGIN_HOME` can select another persistent location. Credentials, Server data, and pending login state stay outside the plugin files, with private filesystem permissions. All Bots on the same Grok account share the cloud computer. See [Grok Bot's computer model](https://docs.x.ai/grok-bot/computer-and-apps).

The plugin uses your Beeper sign-in and the credentials required by each selected network. Private input pages bind only to `127.0.0.1`, expire after ten minutes, and keep submitted values out of chat and command arguments. Messages you ask Grok to retrieve enter the conversation. Sending delivers the requested content to the selected recipient.

The plugin uses the [official Beeper CLI and API](https://github.com/beeper/cli). It includes no Desktop installer or Desktop MCP connection. Grok executes the skill's Server setup and messaging commands directly.

The helper downloads tools from `github.com/beeper/cli/releases` and `files.pythonhosted.org`, then calls only its Server API at `http://127.0.0.1:<port>`. Beeper CLI downloads Server through `api.beeper-staging.com` and its release-CDN redirects. Server then connects to Beeper's production authentication/sync services and your selected networks. The plugin adds no telemetry; Beeper's own software is governed by its [privacy policy](https://www.beeper.com/privacy).

## Validation status

This version implements the Server onboarding workflow. Automated tests cover authentication state, verification, private input, network login transitions, and installation recovery. An optional Chrome test checks native browser form submission. **A full run in an actual Grok Bot computer is still required before marketplace submission.** See the [test procedure](tests/README.md).

Beeper's current Server installer downloads a nightly artifact. Upstream issues affecting device verification and headless chat availability are documented in the [setup guide](skills/beeper/references/setup.md#known-upstream-limits), along with the implemented verification workaround. Network support depends on the bridges available on the Server and the login facilities in the Bot computer; the plugin does not claim every network is tested.

## Support

- [Beeper CLI](https://github.com/beeper/cli)
- [Setup and troubleshooting](skills/beeper/references/setup.md)
- [Report a plugin issue](https://github.com/suatsulun/beeper-grok-plugin/issues)

## License

Plugin files: [MIT](LICENSE). Beeper CLI and qrcode retain their upstream licenses when downloaded. The [Beeper icon](https://www.beeper.com/wp-content/uploads/2026/05/beeper-favicon.png) comes from Beeper's website; Beeper branding belongs to its owners and is not covered by the plugin's MIT license.
