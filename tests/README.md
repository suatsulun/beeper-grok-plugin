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

The legacy reviewed helper test exercises existing-session reuse and a separate login window through real Chromium form submissions. It checks origin rejection, fresh transfer approval, collecting again after approval, cancellation without an envelope, and preserving unrelated tabs. The v0.6.2 direct-window fixture now explicitly selects `profileMode: separate`; it tests delayed login, automatic encryption, completion text and delivery while completion remains open, plus cancellation/close/expiry. That explicit separate mode uses no Chrome setting or Beeper page.

The v0.6.3 normal-profile fixture omits the profile selector to exercise the new default. A disposable existing Chrome profile supplies a saved synthetic session. The helper creates a new window in its ordinary context, collects automatically with a saved session or delayed login, preserves unrelated cookies/tabs and the original browser, and cleans up only its own target on cancel/close/expiry. A disconnected connection stops without reconnecting; the test owner closes the remaining fixture target. Separate no-browser cases cover missing connection metadata and a rejected WebSocket upgrade through the real CLI parent/worker, preserving specific errors and never emitting ciphertext or falling back to a fresh profile. No user profile or real Chrome permission dialog is touched.

The encrypted result then goes through the cloud receiver to the fake Beeper API. Separate subprocess tests cover stdin delivery, malformed/oversized input, expiry, replay and selecting exactly one input source. Real child-process/IPC tests check that the result process exits before the completion worker, and that interruption or an early worker exit produces no envelope and cleans up. Package checksums, keeping the private key off the PC, authentication failures, changed login steps and one-use delivery on ambiguous API responses remain covered. These fixtures do **not** exercise Grok’s actual local-tool approval/transport policy, Chrome’s normal-profile permission dialog, real password-manager extensions/autofill or live provider authentication.

Checks also cover invalid domains, unrequested/missing fields, stale/cancelled sessions, saved browser preferences, absent native capability, and endpoint restrictions. API errors must not cause automatic retries. The companion extension, encrypted public relay, and their tests were removed in v0.5.0.

Version 0.6.1 adds the reported Instagram regression: the live descriptor can list optional cookies without flags. The real local-browser fixture now requests all eight upstream Instagram cookies while issuing only the three core cookies, and must reach fresh approval in both browser modes. Unit cases verify omission of optional fields on submission, rejection of missing core cookies, precedence of explicit bridge flags, provider/source scoping, visible requirements in `network-show`/`browser-plan`, and replacement of old transfer keys when effective requirements change. No test reads a real provider session.

The wider 0.6.1 audit covers all nine registered domains/aliases across cookie, local-storage and request-header sources; X's optional extras; required Facebook/LinkedIn fields; unsupported Slack extraction; native optional form fields and terminal transactions; and CLI subprocess error identity. Real browser checks cover safe progress events and optional omissions in local, cloud and native collectors. See [the complete login audit](../skills/beeper/references/login-audit.md).

To test native browser form submission with the existing Chrome/Chromium and Node runtime, run this optional test from the repository root:

```sh
BEEPER_BROWSER_TEST=1 python3 -m unittest discover -s tests -p test_onboarding.py -k test_private_email_form_in_chrome -v
```

It uses a fresh headless browser profile and synthetic credentials against the fake API. The browser generates the request headers itself. This reproduces the v0.3.0 sign-in rejection: `Referrer-Policy: no-referrer` caused native form POSTs to send `Origin: null`, which the strict origin check rejected. Version 0.3.1 uses `same-origin`, retaining the origin on same-page POSTs and withholding referrers from other origins. Host, origin, and CSRF-token checks remain enforced.

The real tool download can be checked independently with `bootstrap --cli-only` in an isolated `BEEPER_PLUGIN_HOME`. This downloads CLI and QR support but never installs/starts Server. Delete that test directory afterward if a clean machine is required.

Validated locally on 2026-09-11: **48 tests passed** on Node **20.19.2**, including real Chromium forms, existing/fresh local collection, denial before and after collection, encrypted delivery, and the existing cloud/native collectors. Manifest and skill validation passed.

Validated v0.6.1 on 2026-09-12: **64 tests passed in 89.878 seconds**, including all optional real-browser cases, using Python **3.14.7**, Node **26.8.2** and Chrome **153.0.8010.36** on Linux. The full run was sequential under the host's resource lock. The native-receiver fixture compares page tabs during cleanup because Chrome can create its own service-worker/background targets asynchronously. Manifest validation and `git diff --check` passed. This run did not repeat the earlier Node 20 compatibility validation.

Validated v0.6.2 on 2026-09-13: **70 tests passed in 92.440 seconds**, with every optional real-Chrome case enabled, using Python **3.14.7**, Node **26.8.2** and the installed Chrome on Linux. This includes the direct provider window, automatic return with completion still open, cancellation/expiry, IPC lifecycle and stdin submission tests described above. The full run was sequential under the host resource lock. These tests use synthetic accounts; the new direct-login flow still needs acceptance through Grok's actual approved local tools and a live provider.

The direct browser fixture's five cases and the three real-process IPC lifecycle cases also passed separately with the already installed Grok Desktop runtime, embedded Node **24.15.0**, scoped `ELECTRON_RUN_AS_NODE=1`, and the same installed Chrome. No runtime was downloaded. The earlier Node 20.19.2 run remains historical; this change did not rerun that runtime.

Validated v0.6.3 on 2026-09-13: **72 tests passed in 116.074 seconds**, with all optional real-Chrome cases enabled, using Python **3.14.7**, Node **26.8.2** and Chrome **153.0.8010.36** on Linux. The new normal-profile fixture and the missing/denied-permission CLI cases passed alongside the separate-profile, legacy approval, cloud/native and onboarding tests. The full run was sequential under the host resource lock. These are synthetic profiles/sessions; they do not validate Chrome's real permission UI, third-party password-manager behavior or a live provider through Grok's tools.

The two new v0.6.3 test methods (six browser scenarios plus missing setup and the actual CLI worker's denied connection) also passed with Grok's existing embedded Node **24.15.0** in **15.190 seconds**. The process-scoped runtime test used a temporary disk-backed Node symlink and `ELECTRON_RUN_AS_NODE=1`, installed nothing and cleaned its fixtures afterward. No Node 20 compatibility rerun was performed.

The local execution tool names were confirmed by the user's Bot: `ListMachines`, `Shell` with `machineId`, `AwaitShell`, `Read`, `CopyFromBox`, and `CopyToBox`, with approval for each local action. The public package was reconstructed and its standalone helper passed preflight using the installed Linux Grok 0.44.0 executable's embedded Node 24.15.0. No additional runtime was installed. The complete live Grok-to-PC flow remains an acceptance check.

## Acceptance in a fresh Grok Bot computer

Install the plugin through the Bot account's supported plugin/skill distribution, enable it for the Bot, and confirm `/beeper` appears. Start without a preinstalled Beeper Server or credentials. Record the actual Bot runtime, CLI version, Server version/channel, selected bridge IDs, and observed outcomes without credentials or private message bodies.

1. Ask: **“Set up Beeper and connect my WhatsApp account.”** Grok should install the CLI and Server in its own computer, then ask only for missing user inputs. Confirm no Desktop dependency and no request to set up a local MCP connection.
2. Complete Beeper email sign-in through the private browser form. Confirm codes/tokens never appear in tool output or chat. For a new account, verify that account creation waits for the user's username and terms acceptance.
3. Complete device verification. Test a mismatched comparison first: it must cancel, not confirm. On a new matching request, confirm the exact displayed emojis and verify `verified` plus encryption/sync state.
4. Connect a QR-based network. Confirm Grok displays a scannable image, handles refresh/expiry, and discovers the resulting account's connection state.
5. Connect a native code-based network and a browser/cookie-based network available on this Server. Default to `--browser local`: select the PC and prepare its usual Chrome profile/connection setting before a time-sensitive login. The user enables the setting and approves Chrome’s prompt; never do those actions for them. Deliver the verified public package through actual local tools and obtain fresh Grok approval identifying the provider/profile and automatic encrypted return. Run `local_browser.mjs connect REQUEST.json --transfer-on-login`. Confirm a new provider window opens in the approved normal profile with expected extensions/password tools and existing sign-ins, no Beeper interstitial, and no new empty profile. The user handles provider login/MFA if needed. Verify ciphertext returns while the window says **You can close this window now**; submit through `browser-finish --stdin` immediately without another confirmation/file-copy action and inspect the account. Test denied access, window closure and expiry: none may transfer. Verify original Chrome/tabs remain open. Every transfer needs fresh local approval even when signed in. Test `--separate-profile`, legacy post-login review or explicit cloud mode only when requested. A QR test does not validate all networks.
6. Interrupt the chat after an email request and during network login. Resume from saved state without creating duplicate requests or accounts. Repeat after a Server stop/start and after normal Bot computer recovery if available.
7. Ask for a small chat/message read from the connected network. Confirm expected chats are available and decrypted. Empty results for a known nonempty inbox require diagnosis; installation/authentication alone is not a passing result.
8. With an explicit user-selected recipient and text, request one test message. Check its returned state and observed receipt. A timeout must not trigger automatic duplicate sends.

## What is not yet established by local tests

The fake API checks protocol handling and local invariants, not the live Server's correctness. CLI packaging validation does not prove Bot marketplace import, private browser takeover, long-running process durability, provider anti-automation behavior, every network's sign-in, or delivery. Record a real result for each applicable acceptance step before labeling the plugin ready for submission.

The default local helper depends on the exposed Grok desktop execution tools and existing Chrome. It does not depend on Grok's optional native cookie-import feature. Do not bypass feature gates, inspect app secrets, or enable Chrome's debugging setting for the user; they must enable it and approve Chrome's prompt themselves. If the local route is unavailable or denied, explain the exact limitation and stop it. Never silently substitute a cloud browser or install an extension, relay, browser, or runtime. Linux is tested locally; macOS/Windows and the Chrome 144+ permission UI require live acceptance testing.

The v0.6.3 default normal-profile route requires Chrome’s connection setting and permission UI. The optional `--separate-profile` route does not; it lacks normal extensions/autofill. Grok’s fresh local-action approval remains required in both modes. A CLI flag is an execution choice, not proof of consent. If the real tool cannot obtain a fresh approval scoped to this provider/session transfer, direct mode must not be used.

For marketplace submission, Beeper's maintainers should review and approve the Server bootstrap and publish the source under the appropriate official organization. The [marketplace contribution guide](https://github.com/xai-org/plugin-marketplace/blob/main/CONTRIBUTING.md) flags downloading and executing binaries for review. Checksums and an explicit user-requested setup flow make this implementation inspectable; they do not establish marketplace approval.
