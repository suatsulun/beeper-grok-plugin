# Marketplace handoff

The Beeper team can publish this directory at a public repository root or in a repository subdirectory. Set the approved author and actual repository in `.grok-plugin/plugin.json` before release; both are currently omitted.

Follow the current [xAI submission instructions](https://github.com/xai-org/plugin-marketplace/blob/main/CONTRIBUTING.md):

1. Check the catalog for an existing Beeper entry.
2. Publish the reviewed plugin files under the chosen Beeper-owned repository.
3. Copy [marketplace-entry.local.json](marketplace-entry.local.json) into the catalog's `plugins` array. For a remote source, replace its `source` with the shape below; use the commit containing the plugin, not merely the CLI dependency's commit.
4. Generate and validate the marketplace index, then submit the PR through the Beeper team's process.

Remote source template (replace every placeholder; omit `path` for a repository-root plugin):

```json
{
  "source": "url",
  "url": "<public HTTPS Git repository URL>",
  "sha": "<full 40-character lowercase commit SHA>",
  "path": "<relative plugin directory>"
}
```

Alternatively, vendor this package into `external_plugins/beeper` and use the local entry unchanged. In the marketplace checkout:

```sh
python3 scripts/generate-plugin-index.py
python3 scripts/validate-catalog.py
python3 scripts/generate-plugin-index.py --check
```

Never hand-edit the generated index. For updates, bump the plugin version and update the existing entry's pinned commit.

Before release, test in Grok with a designated Beeper test account: setup, an unchanged inbox review, a draft that stays unsent, an explicitly requested send to the correct chat, ambiguous-recipient clarification, and refusal under `BEEPER_READONLY=1`. See [verification](verification.md) for the checks already performed.
