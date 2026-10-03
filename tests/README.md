# Validation

## v0.7.3 audit regressions

The additional suites exercise real cursor tokens instead of IDs or sort keys, anchors within/between pages, nearest newer messages, context on both sides, timestamp ties, boundary duplicates, cursor cycles, wrong accounts/chats, and bounded failures. One test drives the helper as a subprocess against a synthetic loopback HTTP server and verifies its authenticated requests. No real account is used.

Contact tests cover exact identity, original-search hints, contacts after page one, ambiguous names/accounts, and incomplete enumeration. Outcome tests check reply linkage, changed text, own reactions, pending/failed sends, read-back failures, and retained deletion text, with exactly one CLI write invocation and no retry. Export tests cover inclusive timezone-aware bounds, atomic replacement, private permissions, budget failures, and profile/read-only protection. Verification tests preserve live-comparison guards while checking idle/read-only cache behavior. Existing setup/update/sign-in tests must still pass.

These tests do not prove that the user's bridge implements every feature. In particular, a fixture passing does not establish real delivery, message history completeness, media-byte identity, or a model's summary accuracy. The optional official-CLI integration tests are counted as skipped when no isolated published CLI is supplied. See `GROK-TEST.txt` for bounded live acceptance of the candidate source without updating or resetting the account.

For report-skill evaluation, give the model an independently prepared transcript and request a real summary. Score answers without reply links, ambiguous answers, corrections, equal timestamps, duplicates, pending tasks versus completed tasks, unreadable attachments, and embedded instructions. Record whether the model saw expected answers and whether the session was fresh. Assertions in a custom summarizing script are not a model evaluation.

Run `python3 -m unittest discover -s tests -v` with the existing Python runtime. Fixtures live in temporary disk-backed directories under the repository and are removed afterward. No real credentials, browser profiles, account changes, or message sends are involved.

The tests cover credential isolation, private sign-in, failed or duplicate form submissions, recovery, registration refusal, download integrity, preserving an existing profile, update backups/restart behavior, command scope, and bounded message events. They test behavior at CLI/HTTP boundaries, not every upstream network capability.

The review regressions cover short-option target overrides, cross-process lifecycle locking, stopped/stale/live process checks, failed stops, external and symlinked profile backups, incoming verification acceptance, code resend/email correction, ambiguous authentication, cancellation releasing the real job's lock, and errors from the actual Python script entry point. Fake targets now include the real CLI's identity and data-directory fields; stopping an already-stopped fake profile fails just like the published CLI.

Two optional tests exercise an existing isolated official CLI against a local synthetic HTTP receiver. Set `BEEPER_TEST_CLI` to its executable and `BEEPER_TEST_CLI_CACHE` to its already-populated standalone cache, then run the same suite. They check that target overrides cannot forward the synthetic token, a normal accounts read still works, and incoming approval reaches the correct endpoint and request ID. These tests do not download a CLI, install/start a Server, or contact a real account. Without those variables they are skipped.

Release lookup tests cover operation without GitHub's API, no authorization header even when token variables exist, the 15-minute cache, stale/invalid cache rejection, exact release/architecture/filename/digest matching, structured rate-limit/reset information, and ordinary HTTP 403 errors. Update-check tests verify that the native CLI is asked to check Server only, and that a failed CLI lookup is not reported as “up to date.”

Also run `grok plugin validate .` and `git diff --check`. An isolated official CLI can be used to validate help flags and output parsing without logging in. A Server download or unauthenticated start does not prove that an existing account will sync.

For live acceptance on Grok's cloud computer:

1. Record plugin/CLI/Server versions, target, account IDs, and bounded chat/message reads. Keep identifiers private and don't copy message bodies into development notes.
2. On an existing installation, run `update`; verify the backup exists and the same production profile/account IDs remain. Confirm actual versions afterward.
3. On a new user-owned installation, run `setup`, complete private email sign-in, and verify using a trusted device or an existing recovery key. Never reset a working profile to simulate this.
4. Check chats and received messages on each requested connected account. Compare the actual API results even if setup reports `initializing`.
5. Try a small report, an authorized media download/export, and a bounded watch. Clearly state coverage and feature limitations.
6. Test a send only if the user explicitly supplies an exact recipient and text. Read access does not establish send success.
7. Resume from another device using the same Grok account; confirm the existing cloud target is reused. No PC installation or provider login should appear.

Don't classify an empty inbox, a passed fixture, or the old patched 4.3.115 trial as proof that the new official Server works with the current account. Keep those evidence sources separate.
