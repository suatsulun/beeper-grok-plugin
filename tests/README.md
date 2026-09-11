# Validation and Grok Bot acceptance

## Automated local checks

From the repository root:

```sh
python3 -m unittest discover -s tests -v
grok plugin validate .
git diff --check
```

Tests use temporary directories under the user's disk-backed cache and a fake loopback Beeper API. They do not install Server, authenticate a real account, read conversations, or send messages.

Browser unit tests require an existing Node runtime. For actual browser collection, use an installed Chrome/Chromium build:

```sh
BEEPER_BROWSER_TEST=1 BEEPER_TEST_CHROME=/path/to/chrome python3 -m unittest discover -s tests -p test_browser_login.py -v
```

Run with **Node 20.19.2 on PATH** to cover the reported Grok image. The owned browser and form tests use private Chrome pipes. The optional imported-browser receiver uses Node's built-in WebSocket with `--experimental-websocket`, which works on this runtime; no npm library or Node upgrade is required. `browser-check` checks existing runtime capabilities without network or account access.

Tests launch one fresh profile at a time. Provider requests are intercepted and fulfilled with synthetic pages, cookies, local storage, and headers. The native-receiver test preloads synthetic cookies into a disposable loopback Chrome, then attaches the collector through its actual CDP endpoint. It verifies that only requested fields are returned and other tabs/the receiving browser survive. **This does not exercise Grok's own cookie approval/import UI or prove the feature is exposed to an account.** No user browser profile or real account is used.

Checks also cover invalid domains, unrequested/missing fields, stale/cancelled sessions, saved browser preferences, absent native capability, and endpoint restrictions. API errors must not cause automatic retries. The companion extension, encrypted public relay, and their tests were removed in v0.5.0.

To test native browser form submission with the existing Chrome/Chromium and Node runtime, run this optional test from the repository root:

```sh
BEEPER_BROWSER_TEST=1 python3 -m unittest discover -s tests -p test_onboarding.py -k test_private_email_form_in_chrome -v
```

It uses a fresh headless browser profile and synthetic credentials against the fake API. The browser generates the request headers itself. This reproduces the v0.3.0 sign-in rejection: `Referrer-Policy: no-referrer` caused native form POSTs to send `Origin: null`, which the strict origin check rejected. Version 0.3.1 uses `same-origin`, retaining the origin on same-page POSTs and withholding referrers from other origins. Host, origin, and CSRF-token checks remain enforced.

When updating an existing Bot test to v0.3.1, replace the plugin source files, stop only the old private-input command, and run `input email` again to open a fresh page. Reuse `/workspace/.beeper-grok` and the pending login request. Do not rerun bootstrap or delete authentication state for this form fix. If Beeper reports that the email request expired, use the normal cancel-and-restart login flow.

The real tool download can be checked independently with `bootstrap --cli-only` in an isolated `BEEPER_PLUGIN_HOME`. This downloads CLI and QR support but never installs/starts Server. Delete that test directory afterward if a clean machine is required.

Validated locally on 2026-09-11: **40 tests passed** with Node **20.19.2**, including the real Chromium form, owned-browser collector, and imported-browser receiver. Manifest validation and skill validation also passed. Live Grok approval/import and real network authentication remain acceptance checks.

## Acceptance in a fresh Grok Bot computer

Install the plugin through the Bot account's supported plugin/skill distribution, enable it for the Bot, and confirm `/beeper` appears. Start without a preinstalled Beeper Server or credentials. Record the actual Bot runtime, CLI version, Server version/channel, selected bridge IDs, and observed outcomes without credentials or private message bodies.

1. Ask: **“Set up Beeper and connect my WhatsApp account.”** Grok should install the CLI and Server in its own computer, then ask only for missing user inputs. Confirm no Desktop dependency and no request to set up a local MCP connection.
2. Complete Beeper email sign-in through the private browser form. Confirm codes/tokens never appear in tool output or chat. For a new account, verify that account creation waits for the user's username and terms acceptance.
3. Complete device verification. Test a mismatched comparison first: it must cancel, not confirm. On a new matching request, confirm the exact displayed emojis and verify `verified` plus encryption/sync state.
4. Connect a QR-based network. Confirm Grok displays a scannable image, handles refresh/expiry, and discovers the resulting account's connection state.
5. Connect a native code-based network and a browser/cookie-based network available on this Server. Confirm Node 20.19.2 works without an upgrade or companion installation. Test `--browser cloud` with provider-site takeover. If Grok exposes native cookie approval/import and the receiving browser endpoint, also test `--browser native --cdp-url ...` after scoped approval. Record unavailable/denied capabilities honestly. Verify existing sessions, new sign-in/MFA, cancellation, expiry, and reconnection. Confirm direct network password/cookie forms are blocked. Record unsupported bridges/extraction sources; a QR test does not validate all networks.
6. Interrupt the chat after an email request and during network login. Resume from saved state without creating duplicate requests or accounts. Repeat after a Server stop/start and after normal Bot computer recovery if available.
7. Ask for a small chat/message read from the connected network. Confirm expected chats are available and decrypted. Empty results for a known nonempty inbox require diagnosis; installation/authentication alone is not a passing result.
8. With an explicit user-selected recipient and text, request one test message. Check its returned state and observed receipt. A timeout must not trigger automatic duplicate sends.

## What is not yet established by local tests

The fake API checks protocol handling and local invariants, not the live Server's correctness. CLI packaging validation does not prove Bot marketplace import, private browser takeover, long-running process durability, provider anti-automation behavior, every network's sign-in, or delivery. Record a real result for each applicable acceptance step before labeling the plugin ready for submission.

Native Grok import remains conditional on platform/account/tool availability. Do not bypass feature gates, inspect app secrets, or enable debugging on the user's PC browser to make acceptance pass. If import is unavailable, verify that the Bot explains the limitation and offers provider-site takeover without installing an extension, relay, browser, or runtime. An explicit local-only preference must be respected.

For marketplace submission, Beeper's maintainers should review and approve the Server bootstrap and publish the source under the appropriate official organization. The [marketplace contribution guide](https://github.com/xai-org/plugin-marketplace/blob/main/CONTRIBUTING.md) flags downloading and executing binaries for review. Checksums and an explicit user-requested setup flow make this implementation inspectable; they do not establish marketplace approval.
