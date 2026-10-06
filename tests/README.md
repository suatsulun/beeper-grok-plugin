# Validation

## v0.7.8 reconciliation and reporting acceptance

`test_reconciliation.py` reproduces the saved 0.7.7 manual-response shapes with synthetic identifiers and text. It distinguishes missing/null/empty/malformed reactions before deletion, refuses to infer removal after parent deletion, confirms later Server deletion markers with retained or missing text, and keeps media bytes unverified. It also checks GET-only reconciliation in read-only mode, final-versus-pending ID handling, required expected fields, flag-like text, timeout bounds, stale edit acknowledgements, and retained per-read decisions after a later read failure. No private message data or credentials from the manual run are included in these fixtures.

`cli messages reconcile` is a helper command, not a native CLI write. Keep its result separate from the original operation and record that it observes current state. It cannot recover historical responses that were never saved, verify remote erasure or file bytes, or prove removal once a parent is deleted. The supplied manual run's reaction removal remains unknown; the three later `isDeleted: true` rows confirm Server deletion markers. Later read-only reconciles confirmed the same markers without writes. Voice/sticker sends, deletion for everyone, removal of the older existing reaction, and observation of first-install UI remain unrun. A second-device reuse check was reported; the returned JSON does not independently record physical device identity.

All five native private skills were updated in place on Grok Bot with the reconciliation helper; the reports completion rule was then updated and read back separately. The activation artifact's embedded reports body matches the intended source, and its hash and single occurrence of the new paragraph were checked. This verifies supplied activation evidence, rather than directly querying Grok's registry. These observations used the 0.7.7 reconciliation candidate plus the reports override; publishing 0.7.8 does not itself upgrade a working cloud installation.

The independently prepared [completion transcript](report-evaluation/completion-transcript.json) exercises completed preparation, a different object/recipient, actual downstream completion, unanswered requests, midnight dates and duplicate tuple identities. The saved first answer passed 12/12 content checks; freshness, hidden expected answers and absence of live/helper calls are satisfied by the supplied provenance. The fixture fingerprint and loaded skill-file hash matched. The model's completed upload was explicitly recognized as complete, though also listed under unfinished work; an editorial copy removed that redundant entry and corrected a full-file hash labeled as a body hash. The original answer and score were preserved. This holdout is separate from unit tests and does not establish all report behavior.

Use [the completion prompt](report-evaluation/completion-prompt.txt) in a fresh conversation and keep [the evaluator-only rubric](report-evaluation/completion-rubric.json) hidden until the first answer is saved. No production transcripts, identifiers or credential files are included in these evaluation fixtures.

## v0.7.7 transport and full-export regressions

`test_write_transport.py` counts actual loopback HTTP requests under 500/503/429/408 responses and dropped connections, across sends, edits, deletions, and reactions/removals. It checks retained pending IDs after read-back expiry; delayed read resolution without resending; endpoint encoding and text/reply/mention/transaction options; multipart upload bytes, UTF-8 filename metadata, voice/sticker subtype metadata; and no message submission after a failed upload. These tests do not need an installed CLI.

`test_exports.py` checks read-only rejection before CLI/API/filesystem effects, changed limits/content scope, legacy unknown checkpoints, explicit rebuilds without stale counts, same-scope interrupted resumes, manifest validation, profile protection, and concurrent-output locking. The additional `PublishedCLITests` case runs official CLI 0.6.2 against a synthetic receiver: export two of six messages, reject an unsafe unlimited resume, then explicitly rebuild and verify all six JSON records. The optional published-CLI class now has six tests; skipped tests remain untested, not passes.

Message writes now bypass the CLI transport. Earlier observer fixtures still test read-back decisions separately; counting one mocked dispatch is not evidence that the HTTP layer sends once. The new fault tests check that boundary directly. No login/logout flow was added or changed by this release.

## v0.7.6 onboarding regressions

`test_onboarding.py` exercises missing-installation consent with zero pre-approval filesystem/process/network effects; a synthetic approved CLI/Server install; resumption after an interrupted install; another runtime reusing the same target; legacy account/profile preservation without a consent marker; stopped-versus-running Server behavior; consent scope/root matching; concurrent setup locks; repair checks before downloads; script entry-point output; a fixed cloud home independent of client home or working directory; and helper/manifest version alignment. Installer and network dependencies are synthetic. A passing fixture cannot prove that Grok Bot emits an install-time event, registers the five skills, or discovers them in a fresh conversation. Record those host checks separately.

## v0.7.5 reaction identity regressions

The sanitized WhatsApp reproduction uses different account and chat self IDs. Tests check confirmation through the explicitly marked chat self, legacy account-ID matching, exact emoji keys, other people's reactions, wrong chat/account scope, contradictory self flags, missing/malformed state, delayed reactions with cached identity reads, and removal while either own identity still reacts. When the chat self is unavailable, an unmatched reaction with the requested key cannot establish removal. An empty valid reaction list can establish absence with a known account identity.

One additional published-CLI test sends and removes a synthetic reaction through official CLI 0.6.2 against a loopback HTTP receiver. A read-only reconciliation test calls the same observer without dispatching any write. These tests do not contact WhatsApp. The earlier 0.7.5 acceptance used a GET-only recheck for the already-present live reaction; repeating a send is not needed for acceptance of this matcher fix.

## v0.7.4 review regressions

Contacts must never substitute a label for an exact ID, even with `--query` or cross-account collisions. Explicit `--by-label` retains name/phone/handle lookup and checks all search pages before treating a label as unique.

Write tests cover delayed edits, temporary 404s, pending-to-observed sends, missing optional bridge status, permanent failures, bounded observation time, unchanged write counts, literal flag-like text, repeated mentions, formatting uncertainty, captions, media subtype evidence, local hiding versus deletion for everyone, and unexpected member-chat routing. The official-CLI receiver also checks normal text sends and edits through the real published parser. Some flag-like text is incompatible with that parser: the helper selects a JSON API text/edit path before dispatch, never as a retry.

Search tests cover fractional precision, inclusive boundaries, exclusive next-midnight report ends, timezone conversion, post-filter pagination, repeated SDK-style account parameters, duplicates/ties, low-priority and muted combinations, stalled pages, budget errors, wrong scope, and explicit truncation.

CI runs the synthetic suite on Python 3.10 and 3.13, then the published-CLI integration suite. `tests/prepare_official_cli.py --root /absolute/disk-backed/isolated-directory` downloads and checks the pinned Linux x64 CLI 0.6.2 archive and binary and warms its standalone cache; it never installs a Server or signs in. Follow the host resource checks and heavy-job lock before preparation/tests. Set `BEEPER_TEST_CLI` to that directory's `bin/beeper` and `BEEPER_TEST_CLI_CACHE` to its `cache` for local integration tests. Preparation rejects `/tmp` and an existing targets directory. No account token is needed.

## v0.7.3 audit regressions

The additional suites exercise real cursor tokens instead of IDs or sort keys, anchors within/between pages, nearest newer messages, context on both sides, timestamp ties, boundary duplicates, cursor cycles, wrong accounts/chats, and bounded failures. One test drives the helper as a subprocess against a synthetic loopback HTTP server and verifies its authenticated requests. No real account is used.

Contact tests cover exact identity, original-search hints, contacts after page one, ambiguous names/accounts, and incomplete enumeration. Outcome tests check reply linkage, changed text, own reactions, pending/failed sends, read-back failures, and retained deletion text, with exactly one CLI write invocation and no retry. Export tests cover inclusive timezone-aware bounds, atomic replacement, private permissions, budget failures, and profile/read-only protection. Verification tests preserve live-comparison guards while checking idle/read-only cache behavior. Existing setup/update/sign-in tests must still pass.

These tests do not prove that the user's bridge implements every feature. In particular, a fixture passing does not establish real delivery, message history completeness, media-byte identity, or a model's summary accuracy. The optional official-CLI integration tests are counted as skipped when no isolated published CLI is supplied. See `GROK-TEST.txt` for bounded live acceptance of the candidate source without updating or resetting the account.

For report-skill evaluation, give the model an independently prepared transcript and request a real summary. Score answers without reply links, ambiguous answers, corrections, equal timestamps, duplicates, pending tasks versus completed tasks, unreadable attachments, and embedded instructions. Record whether the model saw expected answers and whether the session was fresh. Assertions in a custom summarizing script are not a model evaluation.

Run `python3 -m unittest discover -s tests -v` with the existing Python runtime. Fixtures live in temporary disk-backed directories under the repository and are removed afterward. No real credentials, browser profiles, account changes, or message sends are involved.

The tests cover credential isolation, private sign-in, failed or duplicate form submissions, recovery, registration refusal, download integrity, preserving an existing profile, update backups/restart behavior, command scope, and bounded message events. They test behavior at CLI/HTTP boundaries, not every upstream network capability.

The review regressions cover short-option target overrides, cross-process lifecycle locking, stopped/stale/live process checks, failed stops, external and symlinked profile backups, incoming verification acceptance, code resend/email correction, ambiguous authentication, cancellation releasing the real job's lock, and errors from the actual Python script entry point. Fake targets now include the real CLI's identity and data-directory fields; stopping an already-stopped fake profile fails just like the published CLI.

The optional published-CLI tests exercise an existing isolated official CLI against a local synthetic HTTP receiver. Set `BEEPER_TEST_CLI` to its executable and `BEEPER_TEST_CLI_CACHE` to its already-populated standalone cache, then run the same suite. They check target isolation, normal reads, incoming verification approval, text arguments, and delayed edit observation. The tests themselves do not download a CLI, install/start a Server, or contact a real account. Without those variables they are skipped; CI has a separate preparation step so its integration job cannot silently skip them.

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
