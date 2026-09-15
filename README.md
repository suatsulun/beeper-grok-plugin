<p align="center">
  <img src="assets/logo.png" alt="Beeper" width="96" height="96">
</p>

# Beeper for Grok Bot

Connect your chat networks to Beeper and work with your messages through Grok. This plugin guides setup, account verification, network login, reading, searching, drafting, and sending through Beeper Server.

**Version 0.6.4 uses the official Beeper CLI. No modified CLI is required.** Server runs on Grok Bot's cloud computer. Supported website logins open in a separate Chrome window on your PC after your approval, then return the session to Server automatically through an encrypted handoff.

```text
Set up Beeper and connect my WhatsApp account.
Connect Instagram to Beeper.
Continue my Beeper setup.
Summarize my unread WhatsApp chats.
Find Alex's message about Friday's meeting.
Draft a reply to Alex's latest message.
```

This repository contains the Server-based plugin. The earlier Desktop MCP implementation remains in Git history. Installing this plugin does not require Beeper Desktop or a local MCP connection.

## How it works

| Component | Location | Role |
| --- | --- | --- |
| Grok skill and Python helper | Grok's cloud computer | Guide setup, protect credentials, run messaging commands |
| Official Beeper CLI and Server | Grok's cloud computer | Maintain accounts, network connections, and message access |
| Bundled browser helper | Your PC, through Grok's approved local tools | Open the provider, collect the requested session fields, return encrypted data |
| Separate provider profile | Your PC | Keep that provider's sign-in separate from your normal browser data |

The plugin uses available Python, Node, and Chrome/Chromium runtimes. It does not ask you to manually install an extension, browser, or runtime. Initial Beeper setup automatically downloads the CLI, Server, and QR support. If the required runtimes or Grok local tools are unavailable, Grok reports the limitation.

## Install

### Grok Bot

Install and enable the plugin through the plugin distribution supported by your Grok Bot account. This source repository is not a claim of public marketplace availability. A local Grok CLI installation does not install the plugin on Grok Bot's cloud computer.

For a source handoff, give Grok the plugin-only ZIP and the accompanying `SEND-TO-GROK.txt` produced by [the packaging command](#package-for-grok). Grok can extract the files on its cloud computer and follow `skills/beeper/SKILL.md`. The alternative JSON bundle contains the same files and checksums; it is a source-transfer format, not an official plugin-import format. See [Grok Bot's skill documentation](https://docs.x.ai/grok-bot/skills-routines-and-automations) for the account's supported installation route.

Once the skill is available, ask **“Set up Beeper and connect my WhatsApp account.”** Plugin installation itself only adds source files; it does not start account login or authorize sending messages.

### Grok CLI / local development

With Grok CLI already installed:

```sh
grok plugin install suatsulun/beeper-grok-plugin
grok plugin enable beeper
```

Or install a local checkout:

```sh
grok plugin install /absolute/path/to/beeper-grok-plugin
grok plugin enable beeper
```

Review Grok's plugin trust prompt, then invoke `/beeper` in a session where the skill is loaded. Running setup from a local CLI runs the helper on that computer; the cloud/PC split described here applies to Grok Bot.

## First setup

1. **Install and start Server.** Grok runs the bundled bootstrap on its cloud computer and creates the isolated `grok-bot` target.
2. **Sign in to Beeper.** Enter your email code in the private form through Grok's browser takeover. New account creation requires your chosen username and acceptance of Beeper's terms.
3. **Verify the device.** Compare the displayed emojis with a trusted Beeper device, or enter your existing recovery key in the private form. Grok waits for your comparison; it does not reset keys.
4. **Connect your selected network.** Grok discovers the live bridge's supported methods. QR and device-code methods keep their native steps; website login uses the local flow below.
5. **Check the connection.** Grok checks the selected account and a scoped chat/message read. A successful login is not permission to send a test message.

Passwords, codes, recovery keys, and cookie values do not belong in chat. Detailed setup and recovery commands are in [the setup guide](skills/beeper/references/setup.md).

## Website login on your PC

For supported cookie-based bridge flows:

1. Grok prepares the login request and asks for **fresh local approval to open the named provider and return its encrypted session to Beeper Server on Grok**.
2. After you approve, the provider opens directly in a separate local Chrome window. No Chrome setting changes or extra Beeper review page are required for this default flow.
3. You log in and complete any provider MFA or CAPTCHA. The profile may already have its own valid sign-in from an earlier connection.
4. The helper collects the required session fields and any supported optional fields present, encrypts them, and returns the result automatically.
5. The browser shows **“You can close this window now.”** Grok immediately submits the result and checks the account; you do not need to say “done” or close the window first.

This profile contains none of your normal Chrome cookies, extensions, or saved passwords. It can retain its own provider sign-in under `~/.beeper-browser/profiles`. Your local clipboard is available for the provider website; this does not add clipboard synchronization to Grok's cloud takeover forms.

The completion screen confirms that the local handoff is ready. Grok's account check confirms whether Server accepted it. The completion worker exits when the window closes or after at most five minutes.

Every transfer needs new approval, even with a saved sign-in. Grok must never approve its own action or switch local execution to always allowed. There is no automatic cloud-browser fallback. Advanced browser alternatives and their additional requirements are documented in [browser login](skills/beeper/references/browser-login.md); they are not prerequisites for the default separate-window flow.

### Network compatibility

Network names, bridge IDs, login methods, and required fields come from your running Server. A provider adapter does not guarantee that every bridge or account supports website login.

- WhatsApp-style QR flows use the provider's native linked-device procedure.
- Instagram cookie login supports the three core cookies and collects optional extras only when present, unless the live bridge explicitly requires otherwise.
- The bundled registry covers Instagram, X/Twitter, Facebook/Messenger, LinkedIn, Discord, and Slack domain adapters. Some live flows still require unsupported extraction or challenge generation, including the inspected Slack token flow and some X challenges.
- Beeper email/recovery and native phone/code inputs use private forms on Grok's cloud computer.

See [the provider audit](skills/beeper/references/login-audit.md) for exact scope. Unsupported flows produce an explanation instead of inventing credentials or silently switching browsers.

## Messaging and performance

Ask for messages in natural language. Grok should use the already established account/chat IDs and perform routine reads directly, without repeating setup, status, version, and help checks each time. It resolves ambiguous recipients before sending. Drafts stay in the conversation until you ask to send them.

The helper preserves ordinary CLI messaging commands and adds bounded read-only batches for independent reads. Batching reduces separate Grok tool/helper invocations; the standard CLI still incurs its own subprocess startup cost. This plugin does not claim to eliminate Grok reasoning/tool latency or provider sync delays.

For manual development, set the helper path:

```sh
HELPER="$PWD/skills/beeper/scripts/beeper.py"
python3 "$HELPER" cli -- chats list --unread --limit 20 --read-only
python3 "$HELPER" cli -- messages list --chat 'CHAT_ID' --limit 20 --read-only
```

Replace `CHAT_ID` with a returned chat ID. For several already known chats:

```sh
python3 "$HELPER" batch <<'JSON'
[
  {"id":"first","args":["messages","list","--chat","FIRST_CHAT_ID","--limit","20"]},
  {"id":"second","args":["messages","list","--chat","SECOND_CHAT_ID","--limit","20"]}
]
JSON
```

Batches accept 1–32 requests and at most 256 KiB of JSON input. Requests run sequentially through official CLI 0.6.2's RPC protocol, with fixed target and read-only settings. Each result reports its own success/error; `allSucceeded` reports aggregate success. Writes and endpoint/target overrides are rejected before execution. No requests are automatically retried after a timeout.

For search, pagination, sending, attachment commands, and output formats, see [the messaging guide](skills/beeper/references/messaging.md). CLI help remains available through `python3 "$HELPER" cli -- messages list --help`.

## Update an existing installation

Replace only the plugin source and point Grok at its new `skills/beeper/SKILL.md`. Preserve the existing `BEEPER_PLUGIN_HOME` and `grok-bot` target. Updating plugin source does not require replacing the CLI, reinstalling or restarting Server, reconnecting healthy accounts, or changing encryption keys.

In particular, keep `/workspace/.beeper-grok` when updating a Grok Bot installation. Do not run bootstrap merely because the helper version changed. Check the installed plugin version in `.grok-plugin/plugin.json`; use one scoped read on a known chat to verify an already working installation. See [the changelog](CHANGELOG.md) for 0.6.4 changes.

## Runtime, downloads, and data

The cloud helper requires Linux x86_64/aarch64 and Python 3.10+. Browser work uses an existing compatible Node runtime and Chrome/Chromium. On the PC, the helper can also use Node embedded in an already installed Grok Desktop app. Linux is tested; macOS/Windows discovery paths exist but end-to-end support is unverified. Earlier Node 20.19.2 compatibility checks are recorded in [the test guide](tests/README.md); they are not a claim of a fresh test on every runtime.

`browser-check` checks existing runtime/browser availability on the computer running it without installing software or starting Server. The PC helper has a separate local `check` command.

| Location | Contents |
| --- | --- |
| `/workspace/.beeper-grok` on Grok Bot | CLI, Server profile, target credentials, pending setup state, QR support |
| `~/.local/share/beeper-grok-plugin` elsewhere | Default data location outside a Grok workspace |
| `BEEPER_PLUGIN_HOME` | Optional override; keep this stable across updates |
| `~/.beeper-browser/profiles` on the PC | Separate provider browser profiles |

Credentials and pending login state use private filesystem permissions and stay outside the plugin checkout. The helper communicates with Server only through its fixed loopback target. `BEEPER_READONLY=1` blocks helper mutations; read commands and batches also use CLI read-only mode.

Bootstrap pins official Beeper CLI 0.6.2 and qrcode 8.2 downloads by SHA-256. It preserves an existing CLI binary. The CLI obtains Server through Beeper's installer; the plugin does not pin or patch Server binaries. Downloads require GitHub, Python's package CDN, and Beeper services. This is not an offline bundle. See [setup limits](skills/beeper/references/setup.md#known-upstream-limits) for the reviewed nightly/production distinction.

## Privacy and permissions

- Website collection is restricted to supported named cookies, local-storage entries, and request headers requested by the selected provider. The helper never executes bridge-supplied arbitrary `extractJS`, reads browser cookie databases/password vaults, or copies your ordinary profile.
- Each ten-minute transfer uses ephemeral X25519, HKDF-SHA-256, and AES-256-GCM. The receiver's private key stays on the cloud computer. Grok's local-tool transport carries ciphertext; no public receiver or relay is used.
- Transfers are bound to the pending login step and consumed before submission. Ambiguous failures require checking account state instead of replaying the same encrypted session.
- The plugin adds no telemetry. Beeper and the connected networks have their own service terms and privacy practices; see [Beeper's privacy policy](https://www.beeper.com/privacy).
- Requested message content enters your Grok conversation. A user request to send authorizes sending the specified content to the selected recipient; installation, drafting, and diagnostics do not.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Server says `initializing`, but reads work | Global setup/E2EE state is separate from network freshness. Check the requested account and timestamps; do not reset keys or reconnect solely for this flag. |
| WhatsApp or another account says `reconnect_required` | Reauthenticate that existing account using its returned login ID. An account error takes precedence over a generic bridge “Connected” label. |
| Chats appear old or missing | Walk pagination, verify returned account IDs, and compare timestamps in a known conversation. A server-side account filter may still return mixed networks. |
| Browser never opens | Check the selected PC, actual available Grok local tools, runtime preflight, and fresh approval. Do not change Chrome settings or silently fall back to cloud. |
| Browser waits for cookies | Inspect required versus optional fields with `browser-plan`. Missing optional cookies do not justify another sign-in. |
| Completion page appears but connection fails | Check `network-show` and `accounts`. Local transfer completion is separate from bridge acceptance; an expired bridge transaction needs diagnosis. |
| Reads fail or are empty | Treat failures as errors, and verify account, scope, and sync. Do not patch Server or reconnect as an automatic repair. |
| Grok feels slow | Avoid repeated diagnostics, fetch only the requested scope, and batch independent reads. Measure CLI/API, tool latency, and provider ingestion separately. |

Start with [setup](skills/beeper/references/setup.md) or [browser recovery](skills/beeper/references/browser-login.md). Do not attach raw config, session envelopes, credentials, private message bodies, or unsanitized logs to issues.

## Develop and validate

```sh
python3 -m unittest discover -s tests -v
grok plugin validate .
git diff --check
```

To include optional synthetic Chrome cases, set `BEEPER_BROWSER_TEST=1`; use `BEEPER_TEST_CHROME` if Chrome is not discovered automatically. Run sequentially and follow your host's resource/lock requirements. Tests use disposable profiles and a fake API; they do not authenticate real accounts or send messages. See [tests/README.md](tests/README.md) for coverage and acceptance limits.

The code lives in `skills/beeper/scripts/`; Grok's entry point is `skills/beeper/SKILL.md`, with detailed workflow references next to it. There are no npm dependencies or custom CLI sources in this plugin.

### Package for Grok

From a clean Git checkout:

```sh
python3 scripts/package_plugin.py --output dist
```

This creates a plugin-only ZIP, an equivalent JSON source bundle, `SEND-TO-GROK.txt`, and `SHA256SUMS`. Packaging uses committed Git files, excludes runtime state, and records the source commit. It does not install, upload, or publish anything.

## Support and license

Report reproducible plugin problems in [this repository's issues](https://github.com/suatsulun/beeper-grok-plugin/issues), with plugin/CLI/Server versions, the operation, and a sanitized error. Upstream CLI/API behavior belongs in [Beeper CLI](https://github.com/beeper/cli).

Plugin source is [MIT licensed](LICENSE). Downloaded Beeper CLI and qrcode retain their upstream licenses and terms. Beeper branding belongs to its owners and is not covered by this project's MIT license. This is an independent integration, not an official Beeper or xAI product.
