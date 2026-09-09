<p align="center">
  <img src="assets/beeper-icon.png" alt="Beeper" width="96" height="96">
</p>

# Beeper MCP for Grok Build

Connect [Beeper](https://www.beeper.com) to Grok Build to search conversations, review messages, draft replies, and send messages across your connected chat networks.

This plugin connects to Beeper Desktop's [official built-in MCP server](https://developers.beeper.com/desktop-api/mcp/) or a local Beeper Server over Streamable HTTP. Desktop uses OAuth; a supplied bearer token is also supported. With Desktop, no Beeper CLI, Node.js, or additional server is required.

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
3. From this plugin directory, install and enable it:

   ```sh
   grok plugin install . --trust
   grok plugin enable beeper
   ```

4. Start a new Grok session. Use `/mcps` to inspect the connection and complete Beeper's OAuth authorization when prompted.

Once published in the xAI marketplace, the plugin can be installed through `/plugins` in Grok Build.

### Using local Beeper Server

If you use Beeper Server instead of Desktop, follow the [Beeper CLI setup guide](https://github.com/beeper/cli#2-local-beeper-server-self-hosted-managed-by-the-cli) to install it, sign in, and complete device verification. Keep it running on the same machine as Grok, using its standard port `23373`, then install and enable this plugin as shown above. The plugin uses the same URL for Desktop and Server; no URL configuration is needed.

For headless authentication, make your Server's access token available to Grok through the `BEEPER_ACCESS_TOKEN` environment variable. Keep the token in private local configuration, outside this plugin. Desktop users can use the normal OAuth prompt.

## Connection, authentication, and data

- The MCP endpoint is `http://localhost:23373/v0/mcp` for either local Desktop or local Server. If `BEEPER_ACCESS_TOKEN` is set, Grok sends it as a bearer token; otherwise it uses OAuth discovery. No API key or environment variable is required for Desktop's default OAuth configuration.
- `localhost` refers to the machine or container running the MCP client. Cloud sessions and isolated containers cannot reach your desktop through this URL automatically.
- If authorization fails, check `/mcps` and Beeper's approved connections. If reads succeed but sending is denied, check that the connection has write access and renew authorization as needed. Beeper also supports manually created tokens; follow its [authentication guide](https://developers.beeper.com/desktop-api/auth/) and keep credentials in the client's private configuration.
- Data returned by Beeper enters your Grok session. Sending a message shares its content with the selected conversation through Beeper and the connected chat network. Beeper and Grok process data under their own terms and privacy policies.
- The client and Beeper control tool access and approvals. This package does not enforce read-only access. Resolve the intended recipient and content before sending; a draft request should remain unsent.
- This package contains no executable helper, dependency installer, lifecycle hook, or telemetry.

If the connection is refused, check that Beeper is running, its API is enabled, and port `23373` is reachable from Grok.

## Support and resources

- [Beeper MCP documentation](https://developers.beeper.com/desktop-api/mcp/)
- [Desktop API limitations](https://developers.beeper.com/desktop-api/)
- [Development and verification notes](docs/development.md)
- [Report a plugin issue](https://github.com/suatsulun/beeper-grok-plugin/issues)

## License

Plugin files: [MIT](LICENSE). The [Beeper icon](https://www.beeper.com/wp-content/uploads/2026/05/beeper-favicon.png) is sourced from Beeper's official website; Beeper branding belongs to its respective owners and is not covered by this plugin's MIT license.
