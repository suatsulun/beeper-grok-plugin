# Changelog

## 0.6.4

- Restore the accepted 0.6.2 default: fresh local approval, a separate provider browser window, automatic encrypted handoff, and a completion screen. The later normal-profile default is removed.
- Keep official Beeper CLI 0.6.2 compatibility. No custom CLI binary, persistent RPC extension, or Server patch is included.
- Add bounded read-only batches for independent chat/message/contact reads through the standard CLI RPC protocol. Preserve ordinary commands for single reads and writes.
- Handle CLI help, version, ID-only results, and structured stderr errors without masking failures or exposing credentials.
- Avoid repeated setup diagnostics during successful reads; distinguish account connection errors, global setup/E2EE state, and actual message freshness.
- Preserve existing binaries during bootstrap and avoid reporting the pinned version as the installed version when reusing a binary.
- Document installation, source updates, permissions, runtime requirements, provider limitations, troubleshooting, and plugin-only packaging.

## 0.6.3

Introduced ordinary-profile browser connection. This default is superseded by 0.6.4's separate-window flow.

## 0.6.2

Added direct separate-profile login, automatic encrypted return, completion-worker lifecycle, and stdin submission.

## 0.6.1

Corrected optional provider fields, login progress, and CLI error identity.

## 0.6.0

Added approved local browser login through Grok Desktop.
