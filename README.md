# Beeper for Grok

Read, search, send, and manage Beeper chats through the [official Beeper CLI](https://github.com/beeper/cli). This Grok plugin contains one skill and three shortcuts: `beeper-setup`, `beeper-inbox`, and `beeper-send`. It invokes the CLI through Grok's shell; it adds no MCP server, hooks, or background service.

## Install

You need Grok with plugin/shell support and a reachable, signed-in Beeper Desktop or Server. Install the CLI in the environment where Grok runs, using one option:

```sh
brew install beeper/tap/cli
```

Or `npm install -g beeper-cli`. For local Desktop, open and sign in to Beeper, then run:

```sh
beeper setup --local
beeper doctor --read-only --json
```

From this plugin directory:

```sh
grok plugin validate .
grok plugin install . --trust
grok plugin enable beeper
```

Reload plugins or start a new session. Choose a Beeper command from the slash menu, or ask “Review my unread Beeper chats,” “Draft a reply to Alice,” or “Send Alice: I'll be there at 6.” A clear send request authorizes sending once the recipient is resolved; drafts and reviews do not send messages.

## Connection and data

The default API is `http://127.0.0.1:23373` on the CLI's machine. A cloud runtime needs a user-configured remote endpoint, normally HTTPS, connected with `beeper setup --remote`. Authentication uses the CLI's sign-in flow or an existing `BEEPER_ACCESS_TOKEN`; the plugin stores no credentials.

Retrieved messages enter the Grok session. Sends and uploads share the selected content through Beeper; requested exports/downloads write local files. The plugin adds no telemetry. Installing the CLI uses its package registry and Beeper's GitHub release assets; Beeper manages its own authentication and network traffic.

## Development and publication

Version **0.1.0**, checked against Beeper CLI **0.6.2**. See [verification](docs/verification.md) for evidence and limits, and [marketplace handoff](docs/marketplace.md) for Beeper team publication. The package is not published. Instructions guide the agent; they do not add a technical permissions layer.

License: [MIT](LICENSE).
