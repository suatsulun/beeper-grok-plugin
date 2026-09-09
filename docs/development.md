# Development and verification notes

The published plugin uses `http://localhost:23373/v0/mcp` for either local Desktop or local Server. The earlier tests below ran both at once on separate ports. The `BEEPER_MCP_URL` override shown in the historical commands has been removed; use a private client configuration for alternate-port testing.

## Beeper team handoff

This is a community contribution prepared for Beeper's review and adoption. Before publication, update the manifest's author and repository and the README issue link to reflect the Beeper team's chosen source. Follow the [xAI submission guide](https://github.com/xai-org/plugin-marketplace/blob/main/CONTRIBUTING.md), pin the published plugin commit, and regenerate the marketplace index.

Recorded package structure and xAI catalog checks passed for a local test catalog. Grok CLI `1.0.24` validated and loaded the installed plugin with the default Desktop URL and, before its removal, the Server URL override. With the saved server token, Grok completes the MCP handshake and discovers 12 tools from Beeper Server `4.3.104`. An authenticated `get_accounts` MCP call also succeeds. With the token unset, Grok still attempts OAuth discovery. Device verification and encryption-key transfer completed, but the server still reports `needs-first-sync` and chat/message searches return no results. Reading messages and sending remain unverified; no messages have been sent during testing.

The Beeper CLI `0.6.2` installer currently downloads a nightly Server artifact even when stable is requested. The local test uses that nightly build with its runtime explicitly set to production. See the [official installer implementation](https://github.com/beeper/cli/blob/main/packages/cli/src/lib/installations.ts).

The reviewed Beeper Claude Desktop extension (package version `0.0.1`) connects a Node stdio proxy to the same `/v0/mcp` endpoint and explicitly requests OAuth scopes `read write`. This plugin uses Grok's native HTTP transport and OAuth discovery. Before release, verify both a read and one explicitly requested send, and check the granted permissions if either fails. The extension's proxy, Node requirement, debug flag, and credential directory are specific to its packaging and are not needed here.

## Earlier dual-instance test setup

[Beeper CLI](https://github.com/beeper/cli) can install and manage the headless Beeper Server. It has the same `/v0/mcp` endpoint as Desktop. For a separate server on port `23374`:

```sh
beeper targets add server server --port 23374
beeper install server --target server --yes
beeper targets start server
beeper setup --target server --email YOUR_BEEPER_EMAIL
beeper verify --target server
```

Create the target only once and complete account verification on another signed-in Beeper device. On Server `4.3.104`, OAuth approval waits for an app prompt that is unavailable headlessly. Use that server's valid access token instead: provide it through the `BEEPER_ACCESS_TOKEN` environment variable, then launch Grok with:

```sh
BEEPER_MCP_URL=http://127.0.0.1:23374/v0/mcp grok
```

The token saved by Beeper CLI after email sign-in works with MCP. Keep it in private local configuration, outside this plugin; never commit it. Keep both environment variables available when launching Grok against Server. The default remains Desktop on port `23373`. Stop the managed server with `beeper targets stop server`.

Beeper CLI `0.6.2` has a separate target-resolution bug: `doctor --target server` can send the default Desktop target's token to Server and incorrectly report `401 Invalid token`. Supplying the correct server token through `BEEPER_ACCESS_TOKEN` works around this. An `authenticated` result from `auth status` only confirms that a token was saved; it does not validate it. Device verification is still required for encrypted messages.

If emoji confirmation returns `409` even though `sas.confirm` is available, see [Beeper CLI issue #28](https://github.com/beeper/cli/issues/28). After comparing the emojis on both devices, calling the setup API's `/v1/app/setup/verifications/{id}/sas/confirm` endpoint directly completed verification in the local test.
