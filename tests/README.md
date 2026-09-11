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
BEEPER_BROWSER_TEST=1 BEEPER_TEST_CHROME=/path/to/chrome python3 -m unittest discover -s tests -p test_local_transfer.py -v
```

Run with **Node 20.19.2 on PATH** to cover the reported Grok image. The owned browser and form tests use private Chrome pipes. The optional imported-browser receiver uses Node's built-in WebSocket with `--experimental-websocket`, which works on this runtime; no npm library or Node upgrade is required. `browser-check` checks existing runtime capabilities without network or account access.

Browser test cases run sequentially with disposable profiles. Provider requests are intercepted and fulfilled with synthetic pages, cookies, local storage, and headers. The native-receiver test preloads synthetic cookies into a disposable loopback Chrome, then attaches the collector through its actual CDP endpoint. It verifies that only requested fields are returned and other tabs/the receiving browser survive. No user browser profile or real account is used.

The local helper test exercises existing-session reuse and a separate login window through real Chromium form submissions. It checks origin rejection, waiting for fresh transfer approval, collecting the session again after approval, cancellation without an envelope, and leaving unrelated tabs open. The encrypted result then goes through the cloud receiver to the fake Beeper API. Separate tests cover package checksums, keeping the private key off the PC, authentication failures, expiry, changed login steps, cancellation, and one-use delivery even when the API response is ambiguous. The fixture's disposable debugging endpoint does **not** exercise Chrome's actual existing-profile permission dialog, Grok local-tool approvals, or real provider authentication.

Checks also cover invalid domains, unrequested/missing fields, stale/cancelled sessions, saved browser preferences, absent native capability, and endpoint restrictions. API errors must not cause automatic retries. The companion extension, encrypted public relay, and their tests were removed in v0.5.0.

To test native browser form submission with the existing Chrome/Chromium and Node runtime, run this optional test from the repository root:

```sh
BEEPER_BROWSER_TEST=1 python3 -m unittest discover -s tests -p test_onboarding.py -k test_private_email_form_in_chrome -v
```

It uses a fresh headless browser profile and synthetic credentials against the fake API. The browser generates the request headers itself. This reproduces the v0.3.0 sign-in rejection: `Referrer-Policy: no-referrer` caused native form POSTs to send `Origin: null`, which the strict origin check rejected. Version 0.3.1 uses `same-origin`, retaining the origin on same-page POSTs and withholding referrers from other origins. Host, origin, and CSRF-token checks remain enforced.

The real tool download can be checked independently with `bootstrap --cli-only` in an isolated `BEEPER_PLUGIN_HOME`. This downloads CLI and QR support but never installs/starts Server. Delete that test directory afterward if a clean machine is required.

Validated locally on 2026-09-11: **48 tests passed** on Node **20.19.2**, including real Chromium forms, existing/fresh local collection, denial before and after collection, encrypted delivery, and the existing cloud/native collectors. Manifest and skill validation passed.

The local execution tool names were confirmed by the user's Bot: `ListMachines`, `Shell` with `machineId`, `AwaitShell`, `Read`, `CopyFromBox`, and `CopyToBox`, with approval for each local action. The public package was reconstructed and its standalone helper passed preflight using the installed Linux Grok 0.44.0 executable's embedded Node 24.15.0. No additional runtime was installed. The complete live Grok-to-PC flow remains an acceptance check.

## Acceptance in a fresh Grok Bot computer

Install the plugin through the Bot account's supported plugin/skill distribution, enable it for the Bot, and confirm `/beeper` appears. Start without a preinstalled Beeper Server or credentials. Record the actual Bot runtime, CLI version, Server version/channel, selected bridge IDs, and observed outcomes without credentials or private message bodies.

1. Ask: **“Set up Beeper and connect my WhatsApp account.”** Grok should install the CLI and Server in its own computer, then ask only for missing user inputs. Confirm no Desktop dependency and no request to set up a local MCP connection.
2. Complete Beeper email sign-in through the private browser form. Confirm codes/tokens never appear in tool output or chat. For a new account, verify that account creation waits for the user's username and terms acceptance.
3. Complete device verification. Test a mismatched comparison first: it must cancel, not confirm. On a new matching request, confirm the exact displayed emojis and verify `verified` plus encryption/sync state.
4. Connect a QR-based network. Confirm Grok displays a scannable image, handles refresh/expiry, and discovers the resulting account's connection state.
5. Connect a native code-based network and a browser/cookie-based network available on this Server. Confirm Node 20.19.2 works without an upgrade or companion installation. Default to `--browser local`: select the correct PC with `ListMachines`, copy the public package with `CopyFromBox`, and run the helper with machine-targeted `Shell` using the existing Grok runtime. Exercise existing Chrome-session reuse after the user enables Chrome's setting and approves its prompt, then a separate local website sign-in/MFA with the PC clipboard. Both must wait for the user's fresh **Approve this transfer** click. Return only the encrypted file with `CopyToBox`; check `browser-finish` and the resulting account. Deny an action, deny a transfer, let one expire, and reconnect: no denial/expiry may submit a session, and no previous approval may carry over. Test explicit `--browser cloud` separately only if requested. Confirm direct network password/cookie forms are blocked. Record unsupported bridges/extraction sources; a QR test does not validate all networks.
6. Interrupt the chat after an email request and during network login. Resume from saved state without creating duplicate requests or accounts. Repeat after a Server stop/start and after normal Bot computer recovery if available.
7. Ask for a small chat/message read from the connected network. Confirm expected chats are available and decrypted. Empty results for a known nonempty inbox require diagnosis; installation/authentication alone is not a passing result.
8. With an explicit user-selected recipient and text, request one test message. Check its returned state and observed receipt. A timeout must not trigger automatic duplicate sends.

## What is not yet established by local tests

The fake API checks protocol handling and local invariants, not the live Server's correctness. CLI packaging validation does not prove Bot marketplace import, private browser takeover, long-running process durability, provider anti-automation behavior, every network's sign-in, or delivery. Record a real result for each applicable acceptance step before labeling the plugin ready for submission.

The default local helper depends on the exposed Grok desktop execution tools and existing Chrome. It does not depend on Grok's optional native cookie-import feature. Do not bypass feature gates, inspect app secrets, or enable Chrome's debugging setting for the user; they must enable it and approve Chrome's prompt themselves. If the local route is unavailable or denied, explain the exact limitation and stop it. Never silently substitute a cloud browser or install an extension, relay, browser, or runtime. Linux is tested locally; macOS/Windows and the Chrome 144+ permission UI require live acceptance testing.

For marketplace submission, Beeper's maintainers should review and approve the Server bootstrap and publish the source under the appropriate official organization. The [marketplace contribution guide](https://github.com/xai-org/plugin-marketplace/blob/main/CONTRIBUTING.md) flags downloading and executing binaries for review. Checksums and an explicit user-requested setup flow make this implementation inspectable; they do not establish marketplace approval.
