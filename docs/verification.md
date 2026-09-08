# Verification

Reviewed 2026-09-08 against [Beeper CLI 0.6.2](https://github.com/beeper/cli/tree/950271522abc23b3d658314ecf5fc87059b2341e) and [xAI marketplace tooling](https://github.com/xai-org/plugin-marketplace/tree/b73728bb3a7413703b47f9336dd0e5fc23dfefa6). Both checkouts still matched upstream HEAD at review time.

## Results

- Grok 1.0.13 manifest validation and skill validation passed.
- The official catalog generator and validator discover one skill and three commands; generated-index freshness and package links pass.
- Sixteen command examples parse against the built CLI; both inline help references resolve to real commands.
- Twelve CLI invocations against a local mock API pass: inbox/history/search, context plus central-message lookup, older-history pagination, ambiguous-recipient rejection, both read-only controls, a literal-text send, pending-message lookup, and a wait that times out after acceptance.
- Separate routing checks pass for default accounts, explicit all-account filters, network selectors, and named/environment targets.

The review preserved the corrected verification command (`beeper verify`), contact lookup limitations, and environment precedence. It also made central-message retrieval explicit and ensured the inbox shortcut includes all accounts when no narrower scope is requested. Shared instructions now live in one skill.

To repeat the checks from the development workspace root:

```sh
python3 work/verify-package.py
bun work/check-command-parser.mjs
bun work/check-routing.mjs
python3 work/mock-beeper-smoke.py
```

## Limits

These checks validate package structure and the CLI behavior the instructions rely on. They do not establish that Grok follows every instruction or prove real-network delivery. Tests use the built source entrypoint, synthetic data, and isolated profiles; no real Beeper messages were sent. Live Grok discovery, authentication, and messaging remain the account-backed checks in [marketplace.md](marketplace.md).
