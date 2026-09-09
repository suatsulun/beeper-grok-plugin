<p align="center">
  <img src="assets/beeper-icon.png" alt="Beeper" width="96" height="96">
</p>

# Beeper MCP for Grok Build

Connect [Beeper](https://www.beeper.com) to Grok Build to search conversations, review messages, draft replies, and send messages across your connected chat networks.

This plugin connects to Beeper Desktop's [official built-in MCP server](https://developers.beeper.com/desktop-api/mcp/) or a local Beeper Server over Streamable HTTP with OAuth. With Desktop, no Beeper CLI, Node.js, or additional server is required.

## What you can do

Ask Grok in plain language:

```text
Summarize my unread Beeper chats.
Find my conversation with Alex about the trip.
What time did we agree to meet in the family chat?
Draft a reply to Alex's latest message without sending it.
Send Alex on Beeper: "I'm running five minutes late."
```

Available tools depend on your Beeper version and connected networks. Message history is limited to what Beeper has synced and indexed. Grok discovers the tools directly from Beeper; this package adds no custom skills or slash commands.

## Installation

1. Install and sign in to [Beeper Desktop](https://www.beeper.com/download). Keep it running on the same machine as Grok Build's MCP client.
2. Enable the API/MCP connection in Beeper's **Settings → Integrations**. Older versions call this **Settings → Developers**. See [Beeper's setup instructions](https://developers.beeper.com/desktop-api/mcp/).
3. From this plugin directory, validate and install it:

   ```sh
   grok plugin validate .
   grok plugin install . --trust
   grok plugin enable beeper
   ```

4. Start a new Grok session. Use `/mcps` to inspect the connection and complete Beeper's OAuth authorization when prompted.

Once published in the xAI marketplace, the plugin can be installed through `/plugins` in Grok Build.

### Using local Beeper Server

[Beeper CLI](https://github.com/beeper/cli) can install and manage the headless Beeper Server. It has the same `/v0/mcp` endpoint as Desktop. For a separate server on port `23374`:

```sh
beeper targets add server server --port 23374
beeper install server --target server --yes
beeper targets start server
beeper setup --target server --email YOUR_BEEPER_EMAIL
BEEPER_MCP_URL=http://127.0.0.1:23374/v0/mcp grok
```

Create the target only once. Complete the email and account verification prompts, then authorize Grok through `/mcps`. Keep `BEEPER_MCP_URL` set whenever launching Grok against this server. The default remains Desktop on port `23373`. Stop the managed server with `beeper targets stop server`.

## Connection, authentication, and data

- The default MCP endpoint is `http://localhost:23373/v0/mcp`. Set `BEEPER_MCP_URL` to use another endpoint. OAuth uses the authorization endpoints advertised by the local Beeper server. No API key or environment variable is required by the default configuration.
- `localhost` refers to the machine or container running the MCP client. Cloud sessions and isolated containers cannot reach your desktop through this URL automatically. Grok supports the environment variable fallback used in [`.mcp.json`](.mcp.json); see its [MCP configuration guide](https://docs.x.ai/build/features/mcp-servers).
- If authorization fails, check `/mcps` and Beeper's approved connections. If reads succeed but sending is denied, check that the connection has write access and renew authorization as needed. Beeper also supports manually created tokens; follow its [authentication guide](https://developers.beeper.com/desktop-api/auth/) and keep credentials in the client's private configuration. Authorize Grok separately from Claude; do not copy Claude's saved credentials.
- Data returned by Beeper enters your Grok session. Sending a message shares its content with the selected conversation through Beeper and the connected chat network. Beeper and Grok process data under their own terms and privacy policies.
- The client and Beeper control tool access and approvals. This package does not enforce read-only access. Resolve the intended recipient and content before sending; a draft request should remain unsent.
- This package contains no executable helper, dependency installer, lifecycle hook, or telemetry.

If the connection is refused, check that Beeper is running, its API is enabled, and the configured host and port are reachable from Grok.

## Beeper team handoff

This is a community contribution prepared for Beeper's review and adoption. Before publication, update the manifest's author and repository and the issue link below to reflect the Beeper team's chosen source. Follow the [xAI submission guide](https://github.com/xai-org/plugin-marketplace/blob/main/CONTRIBUTING.md), pin the published plugin commit, and regenerate the marketplace index.

Package structure and xAI catalog checks pass for a local test catalog. Grok CLI `1.0.24` validates and loads the installed plugin, including both the default Desktop URL and the Server URL override. Beeper Server `4.3.104` exposes MCP and OAuth discovery, and Grok's connection diagnostic reaches it but reports authentication required. Account sign-in, Grok OAuth authorization, and authenticated tool access still need verification; no messages have been sent during testing.

The Beeper CLI `0.6.2` installer currently downloads a nightly Server artifact even when stable is requested. The local test uses that nightly build with its runtime explicitly set to production. See the [official installer implementation](https://github.com/beeper/cli/blob/main/packages/cli/src/lib/installations.ts).

The reviewed Beeper Claude Desktop extension (package version `0.0.1`) connects a Node stdio proxy to the same `/v0/mcp` endpoint and explicitly requests OAuth scopes `read write`. This plugin uses Grok's native HTTP transport and OAuth discovery. Before release, verify both a read and one explicitly requested send, and check the granted permissions if either fails. The extension's proxy, Node requirement, debug flag, and credential directory are specific to its packaging and are not needed here.

## Support and resources

- [Beeper MCP documentation](https://developers.beeper.com/desktop-api/mcp/)
- [Desktop API limitations](https://developers.beeper.com/desktop-api/)
- [Report a plugin issue](https://github.com/suatsulun/beeper-grok-plugin/issues)

## License

Plugin files: [MIT](LICENSE). The [Beeper icon](https://www.beeper.com/wp-content/uploads/2026/05/beeper-favicon.png) is sourced from Beeper's official website; Beeper branding belongs to its respective owners and is not covered by this plugin's MIT license.
