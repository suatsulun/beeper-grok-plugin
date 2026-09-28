# Beeper for Grok

Say **“Set up Beeper.”** Grok installs Beeper CLI and Server on its cloud computer, helps you sign in to your existing Beeper account, and uses the chat accounts already connected there. The same cloud setup is available when you use your Grok account from another device.

Sign in with your Beeper email code, then approve the session on a trusted Beeper device or use your existing recovery key. Codes and keys go into a private browser page on Grok's computer. The plugin needs Grok's private browser takeover for those steps; it never asks for secrets in chat. It does not require changes to your PC or Chrome.

Try:

- “Show my latest received WhatsApp messages.”
- “Reply to Alice on Instagram: I'll be there at six.”
- “Summarize today's project chat and list the decisions.”
- “Find the PDF Sam sent last week.”
- “Mute this group until tomorrow.”
- “Export my conversation with Alex.”

This version deliberately covers **existing accounts**. Adding networks, provider login, browser-cookie transfers, account registration, and recovery-key resets are not included. Only cloud-connected accounts and features exposed by your running Beeper Server are available; device-local connections and complete historical sync are not guaranteed.

## What's inside

Five short skills: Beeper routing, setup, messages, chats, and reports. Three Python standard-library files install the official CLI, preserve one cloud profile, keep credentials out of tool output, and provide private sign-in. Messaging uses native CLI commands, with small compatibility fixes for 0.6.2's verification IDs and archive endpoint. No JavaScript browser stack, MCP service, package dependencies, or install hooks.

Data stays outside the plugin at `/workspace/.beeper-grok`. Existing `grok-bot` profiles from the 0.6.x plugin are reused. Updating this source alone does not change Server or sign anyone out. “Update Beeper” checks official releases, keeps the old CLI, backs up a stopped Server's profile and program, and runs the official updater. It never patches Beeper binaries or resets account data.

**v0.7.2 fixes the seven code-review findings.** It blocks hidden target overrides, coordinates startup with updates, backs up the configured profile even outside the config directory, and updates an already-stopped Server. Sign-in supports code resend, email correction, and cancellation on the same private page. Incoming trusted-device requests can be accepted, and expected sign-in errors keep their useful explanations. The project still has five skills, three standard-library Python helpers, and no added dependencies.

**v0.7.1 removes the GitHub API requirement from setup and CLI update checks.** It reads Beeper's public release manifest, caches release details for 15 minutes, and verifies the downloaded archive's SHA-256. Users need no GitHub token and don't have to wait for a shared API quota to reset. Ordinary download restrictions or Beeper Server download failures can still occur; the helper reports them separately. The checksum comes from Beeper's release manifest, so it verifies agreement with the publisher's release, not independent authenticity.

As checked on **28 September 2026**, the latest published CLI is **0.6.2**. The CLI's Server nightly feed reports **4.3.156**; the separate stable feed reports **4.3.152**. Beeper's installer currently uses the nightly feed for Server while the account still signs into production. These are release checks, not a claim that a user's cloud installation has already been updated.

## Install and development

This is a Grok plugin with `.grok-plugin/plugin.json` and `skills/`. For local development, Grok's CLI accepts `grok plugin install /absolute/path/to/project`. Distribution through a marketplace requires its own review and a published source revision; this local rewrite is not a marketplace release. Plugin installation itself is passive. Official binaries are downloaded only when the user asks Grok to set up or update Beeper.

Grok's Linux cloud computer needs its existing Python 3.10+ runtime, internet access to official Beeper/GitHub downloads, and private browser takeover for sign-in. Automatic CLI installation supports x64 and arm64. No npm, pip, Node, or browser installation is needed.

```sh
python3 -m unittest discover -s tests -v
grok plugin validate .
git diff --check
```

Tests use synthetic accounts, a fake CLI/API, and temporary disk-backed data. See [validation](tests/README.md) for scope and live acceptance. Follow the host's resource instructions before running suites or installations.

Official references: [Beeper CLI](https://github.com/beeper/cli), [CLI releases](https://github.com/beeper/cli/releases), [Grok plugin format](https://github.com/xai-org/plugin-marketplace), [Grok skills](https://docs.x.ai/grok-bot/skills-routines-and-automations).

Plugin code is [MIT licensed](LICENSE). Beeper software keeps its upstream license and terms. The bundled [Beeper icon](https://www.beeper.com/wp-content/uploads/2026/05/beeper-favicon.png) belongs to Beeper and is not covered by this project's MIT license.
