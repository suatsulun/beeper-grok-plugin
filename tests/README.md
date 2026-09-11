# Validation and Grok Bot acceptance

## Automated local checks

From the repository root:

```sh
python3 -m unittest discover -s tests -v
grok plugin validate .
git diff --check
```

Tests use temporary directories under the user's disk-backed cache and a fake loopback Beeper API. They do not install Server, authenticate a real account, read conversations, or send messages.

To test native browser form submission, install Chrome/Chromium and Node 22+ on the test machine, then run this optional test from the repository root:

```sh
BEEPER_BROWSER_TEST=1 python3 -m unittest discover -s tests -p test_onboarding.py -k test_private_email_form_in_chrome -v
```

It uses a fresh headless browser profile and synthetic credentials against the fake API. The browser generates the request headers itself. This reproduces the v0.3.0 sign-in rejection: `Referrer-Policy: no-referrer` caused native form POSTs to send `Origin: null`, which the strict origin check rejected. Version 0.3.1 uses `same-origin`, retaining the origin on same-page POSTs and withholding referrers from other origins. Host, origin, and CSRF-token checks remain enforced.

When updating an existing Bot test to v0.3.1, replace the plugin source files, stop only the old private-input command, and run `input email` again to open a fresh page. Reuse `/workspace/.beeper-grok` and the pending login request. Do not rerun bootstrap or delete authentication state for this form fix. If Beeper reports that the email request expired, use the normal cancel-and-restart login flow.

The real tool download can be checked independently with `bootstrap --cli-only` in an isolated `BEEPER_PLUGIN_HOME`. This downloads CLI and QR support but never installs/starts Server. Delete that test directory afterward if a clean machine is required.

## Acceptance in a fresh Grok Bot computer

Install the plugin through the Bot account's supported plugin/skill distribution, enable it for the Bot, and confirm `/beeper` appears. Start without a preinstalled Beeper Server or credentials. Record the actual Bot runtime, CLI version, Server version/channel, selected bridge IDs, and observed outcomes without credentials or private message bodies.

1. Ask: **“Set up Beeper and connect my WhatsApp account.”** Grok should install the CLI and Server in its own computer, then ask only for missing user inputs. Confirm no Desktop dependency and no request to set up a local MCP connection.
2. Complete Beeper email sign-in through the private browser form. Confirm codes/tokens never appear in tool output or chat. For a new account, verify that account creation waits for the user's username and terms acceptance.
3. Complete device verification. Test a mismatched comparison first: it must cancel, not confirm. On a new matching request, confirm the exact displayed emojis and verify `verified` plus encryption/sync state.
4. Connect a QR-based network. Confirm Grok displays a scannable image, handles refresh/expiry, and discovers the resulting account's connection state.
5. Connect an input-based network and a browser/cookie-based network actually available on this Server. Verify multi-step input, MFA, Chrome WebView availability, failure reporting, and reconnection. Record unsupported cases explicitly; a QR test does not validate all networks.
6. Interrupt the chat after an email request and during network login. Resume from saved state without creating duplicate requests or accounts. Repeat after a Server stop/start and after normal Bot computer recovery if available.
7. Ask for a small chat/message read from the connected network. Confirm expected chats are available and decrypted. Empty results for a known nonempty inbox require diagnosis; installation/authentication alone is not a passing result.
8. With an explicit user-selected recipient and text, request one test message. Check its returned state and observed receipt. A timeout must not trigger automatic duplicate sends.

## What is not yet established by local tests

The fake API checks protocol handling and local invariants, not the live Server's correctness. CLI packaging validation does not prove Bot marketplace import, private browser takeover, long-running process durability, WebView support, every network's sign-in, or delivery. Record a real result for each applicable acceptance step before labeling the plugin ready for submission.

For marketplace submission, Beeper's maintainers should review and approve the Server bootstrap and publish the source under the appropriate official organization. The [marketplace contribution guide](https://github.com/xai-org/plugin-marketplace/blob/main/CONTRIBUTING.md) flags downloading and executing binaries for review. Checksums and an explicit user-requested setup flow make this implementation inspectable; they do not establish marketplace approval.
