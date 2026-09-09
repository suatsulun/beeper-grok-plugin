<p align="center">
  <img src="assets/beeper-icon.png" alt="Beeper" width="96" height="96">
</p>

# Beeper for Grok Build

Connect Grok Build to [Beeper Desktop](https://www.beeper.com) to search chats, read messages, and send replies across your connected chat networks.

Like Beeper's Claude Desktop extension, this plugin connects to Beeper Desktop's [built-in MCP server](https://developers.beeper.com/desktop-api/mcp/). Grok provides the HTTP transport and OAuth authentication directly.

## Installation

1. Install and sign in to [Beeper Desktop](https://www.beeper.com/download). Keep it running on the same device as Grok Build.
2. Enable the API/MCP connection in Beeper's **Settings → Integrations**.
3. From this plugin directory, run:

   ```sh
   grok plugin install . --trust
   grok plugin enable beeper
   ```

4. Start Grok, open `/mcps`, and complete authorization in Beeper. Allow read and write access to use both reading and sending tools.

The connection uses `http://localhost:23373/v0/mcp`. If you change Beeper Desktop's port, update [`.mcp.json`](.mcp.json) to match.

## Usage

```text
Summarize my unread Beeper chats.
Find my conversation with Alex about the trip.
Draft a reply to Alex's latest message without sending it.
Send Alex on Beeper: "I'm running five minutes late."
```

Grok discovers the available tools from Beeper Desktop. Available messages depend on your connected networks and synced history. Messages returned by Beeper enter your Grok session; sending delivers content to the selected conversation.

## Support

- [Beeper MCP setup](https://developers.beeper.com/desktop-api/mcp/)
- [Beeper authentication](https://developers.beeper.com/desktop-api/auth/)
- [Report a plugin issue](https://github.com/suatsulun/beeper-grok-plugin/issues)

## License

Plugin files: [MIT](LICENSE). The [Beeper icon](https://www.beeper.com/wp-content/uploads/2026/05/beeper-favicon.png) is sourced from Beeper's official website; Beeper branding belongs to its respective owners and is not covered by this plugin's MIT license.
