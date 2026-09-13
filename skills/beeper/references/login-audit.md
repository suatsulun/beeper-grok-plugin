# Login requirements audit — 12 September 2026

This audit covers all six bundled browser provider adapters and the native login methods handled by this plugin. Source definitions and synthetic tests establish requirement handling; they do not establish successful authentication with every live provider. The user's Grok report confirms one Instagram account connected after a fresh bridge login and approved local transfer. That is a reported live result, separate from these automated checks.

## Shared rules

For browser fields, honor a boolean `required` first, then the inverse of a boolean `optional`. Missing `optional` alone is not evidence that a cookie is required: [the upstream cookie model uses `required`](https://github.com/mautrix/go/blob/dc9b2d7a77fb933dd8732d52b8a7c71d9a4e193d/bridgev2/login.go), while [the Beeper SDK's simplified cookie model omits this metadata](https://github.com/beeper/desktop-api-js/blob/next/src/resources/bridges/bridges.ts). Invalid flag types are rejected.

When both flags are absent, only the documented Instagram and X source names below receive optional defaults. These defaults are scoped to the provider and source kind, not merely a matching field ID. Other unspecified fields remain required. An explicit conflicting requirement is a bridge compatibility issue; do not edit it away. `browser-plan` and `browser-start` expose the effective required and optional field IDs.

Missing optional values are omitted from submission. Present values still must match the requested source, domain and pattern. An unsupported required source is rejected; it is not guessed to be a cookie. Optional unsupported sources can be omitted. No bridge `extractJS` runs.

## Browser providers

| Provider | Required in the inspected upstream definition | Optional / compatibility handling |
| --- | --- | --- |
| Instagram | `sessionid`, `csrftoken`, `ds_user_id` | Cookies `rur`, `shbid`, `shbts`, `mid`, `ig_did` are optional. Use provider defaults if flags were lost. Missing extras must not prompt more browsing or another sign-in. [Cookie definitions](https://github.com/mautrix/meta/blob/857f87f7f57d1a036550d77116def663a061c541/pkg/messagix/cookies/cookies.go), [login fields](https://github.com/mautrix/meta/blob/5e6cae0f42d10d8a2ca7a0e981e8ad4625fcfc0c/pkg/igconnector/login.go). |
| Facebook / Messenger | Cookies `xs`, `c_user`, `datr` | No extra optional defaults established by this login descriptor. Keep these required; honor optional flags on any additional live fields. [Login definition](https://github.com/mautrix/meta/blob/5e6cae0f42d10d8a2ca7a0e981e8ad4625fcfc0c/pkg/connector/login.go). |
| LinkedIn | Request headers `Cookie`, `X-LI-Track`, `X-LI-Page-Instance`, including their validation patterns | These are required request headers, not interchangeable with individual cookies. They must be observed in the helper's provider tab. No provider optional defaults added. [Login definition](https://github.com/mautrix/linkedin/blob/a289af49386a34e1a7f3680f1a7119c382b921b2/pkg/connector/login.go). |
| X / Twitter | Basic cookie step: `auth_token`, `ct0`. Advanced challenge step: first `castle_token` and `browser_user_agent` | Extra challenge tokens 2–8, three client hints, and seven auxiliary cookies are optional; exact sources are below. A required challenge token still blocks readiness if absent. The plugin never executes the bridge's challenge-generation JavaScript, so advanced login is not guaranteed compatible. [Login definition](https://github.com/mautrix/twitter/blob/975e471a8c6fd9b72ed60f0ee0a9484e0359240a/pkg/connector/login.go). |
| Slack | `auth_token` plus cookie `d` (`cookie_token`) | The inspected `auth_token` requires `special` or `request_body` extraction, which this helper does not implement. Report this flow as unsupported rather than waiting or making the token optional. Registry coverage applies only if the live Server supplies a different compatible descriptor. [Token login definition](https://github.com/mautrix/slack/blob/d8e7fe02d2dd3c5988609f293ef9371a913219dd/pkg/connector/login-cookie.go). |
| Discord | Determined by the live flow | The public legacy bridge documents QR/token authentication but does not establish a current Server cookie-field schema. No optional defaults inferred. Preserve native QR where offered; browser collection requires an actual compatible live descriptor. [Bridge documentation](https://github.com/mautrix/discord/blob/c62165a46109d7c824bc0b4bb067ba02ea6528f1/README.md), [authentication guide](https://docs.mau.fi/bridges/go/discord/authentication.html). |

X's fallback optional sources are cookies `__cf_bm`, `__cuid`, `gt`, `guest_id`, `guest_id_ads`, `guest_id_marketing`, `personalization_id`; request headers `sec-ch-ua`, `sec-ch-ua-platform`, `sec-ch-ua-mobile`; local-storage entries `fi.mau.twitter.castle_token_2` through `_8` and `fi.mau.twitter.cookie.NAME` for those seven cookies. These are collected only when the live step asks for them and they exist. The first challenge token and user-agent are not in the optional defaults.

## Native methods

| Method | Handling |
| --- | --- |
| Beeper email code | Required; private form, transaction binding and secret redaction retained. |
| Beeper registration | Username and the user's terms acceptance remain required. |
| Existing recovery key | Required; private input, no new key or reset. |
| Device verification | The exact comparison must be confirmed by the user; mismatch/cancellation cannot confirm. |
| Network phone / code inputs | Optional flags are honored, optional labels shown, blank optional values omitted. Missing required values, malformed flags and stale/ended transactions are rejected. |
| QR / device-code display and wait | Show the live challenge and use native polling/acknowledgement. Cookie defaults do not apply. |
| Direct network passwords | Unsupported by the generic private form; use a live supported provider website or native alternative. Do not invent a flow. |

## Keep connection recovery simple

1. Check `accounts` first. An already connected requested account does not need another login to test an update.
2. Check the existing PC runtime and Grok local tools before starting a time-sensitive bridge transaction. Keep one active helper and one selected pending login.
3. Use `browser-plan` before packaging. Obtain a fresh local approval naming this provider, automatic encrypted transfer and Beeper Server on Grok as destination. Run `connect REQUEST.json --transfer-on-login`; the provider opens directly in its dedicated profile without a Beeper interstitial or Chrome setting change. Do not edit the request or generate placeholder cookies. Safe progress includes required field names only; optional omissions are not blockers. The legacy `phase: ready` approval screen belongs only to explicitly requested existing-profile/review mode.
4. Await the same local job. Once `encrypted-transfer-ready` arrives, pass its envelope JSON to `browser-finish --stdin` once without another confirmation or local file-copy action. Do not wait for the completion window to close. The user has already approved this exact local connect-and-transfer operation. Use `--file` only when the tool cannot return ciphertext directly.
5. Distinguish the ten-minute transfer request from the bridge's own login lifetime. A fresh transfer does not renew an old bridge transaction. A website home feed does not prove the bridge transaction still exists, and a quick approval cannot guarantee acceptance.
6. If a transfer expires, keep the provider signed in and prepare a new approved transfer against a still-valid pending login. If the bridge reports its login missing/expired, inspect accounts first; if the requested connection is absent, retire only that failed pending transaction and create one new login using the same supported flow. Preserve Server data, keys and the browser profile. Require fresh approval; never replay old ciphertext.
7. After an ambiguous or noisy finish, inspect `network-show` and `accounts`. Do not submit again automatically. A matching connected account confirms connection; lack of a pending login alone does not. Report any helper error separately from the observed account state. Do not pressure the user to rush or promise that a new session will definitely succeed.

The user's reported `M_NOT_FOUND` on an hours-old Instagram login is separate from missing optional cookies. Do not generalize every HTTP 500 into expiry or a cookie problem. Preserve a credential-free error code for diagnosis. Version 0.6.1 also fixes CLI module identity so imported helper failures retain their specific codes instead of becoming `unexpected_error: Operation failed (Failure)`; the old generic error cannot reveal its original cause after the fact.

## Test coverage and limits

The requirement matrix covers all nine registered domains/aliases and cookie, local-storage and header sources, with absent and present optional values, validation patterns and required-field failures. Separate tests cover provider defaults, required Facebook/LinkedIn fields, unsupported Slack extraction, native optional inputs and ended transactions. Real Chromium fixtures exercise the three required Instagram cookies with all five optional cookies absent in both local browser choices, safe progress events, fresh approval, cancellation and encrypted submission. Existing cloud/native collectors also exercise omitted optional sources. CLI subprocess tests cover successful finish, rejected replay and specific expired/invalid transfer errors.

These fixtures intercept provider requests and use synthetic values. They do not read user accounts or prove live MFA, anti-automation, challenge generation, Chrome's actual permission prompt, Grok's file-copy lifecycle, or macOS/Windows behavior.
