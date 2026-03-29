# Built-in Token Pool Design

**Date:** 2026-03-24

**Goal**

Integrate a built-in token pool mode into the desktop tool so Codex can use token JSON files from `C:\Users\MECHREVO\.cli-proxy-api\` without depending on `codex-launcher.ps1` or `cliproxyapi.exe`.

**Problem Statement**

The current external flow depends on a separate project and launcher script. That adds operational overhead and splits account-backed Codex auth from token-backed quota usage. The user wants this project to own the workflow directly: import token files into the standard token directory, switch the desktop tool into token-pool mode, and have newly opened Codex terminals use the pooled tokens automatically.

**Design Summary**

The desktop app keeps the existing Codex-auth account-slot system untouched and adds a second, global auth backend mode: `codex_auth` or `built_in_token_pool`. In token-pool mode, the app starts an internal local OpenAI-compatible proxy service implemented inside this repository. New Codex terminals point at that local proxy via `OPENAI_BASE_URL` and a local placeholder API key. The proxy loads token JSON files from `C:\Users\MECHREVO\.cli-proxy-api\`, selects a token using a CLIProxyAPI-compatible round-robin strategy, forwards requests to the upstream API, and handles token failures/cooldowns.

## Scope

**In scope**
- Desktop-only integration in the `Accounts` dialog.
- Import one or more token JSON files into `C:\Users\MECHREVO\.cli-proxy-api\`.
- Auto-create the token directory when missing.
- New global backend mode switch: `Codex Auth` vs `Built-in Token Pool`.
- Internal proxy process management from this project.
- New desktop-launched Codex terminals inherit the selected backend mode.
- Status display for token count, active mode, local port, and recent proxy error summary.

**Out of scope for this phase**
- Mobile UI for token-pool mode.
- Replacing or importing every CLIProxyAPI implementation detail.
- Editing or deleting token files beyond import/overwrite.
- Hot-switching already-running Codex terminals.
- Full quota dashboard beyond basic mode/status reporting.

## Architecture

### 1. Backend mode model

Add a persistent desktop setting describing which auth backend is active:
- `codex_auth`
- `built_in_token_pool`

This setting should live in a small JSON file under `.codex`, alongside other tool-owned settings. It is independent from the existing account-slot metadata. Account slots remain the source of truth for Codex-native auth. Token-pool mode is a separate execution backend.

### 2. Token storage

Use `C:\Users\MECHREVO\.cli-proxy-api\` as the fixed token pool directory.

Behavior:
- If the directory does not exist, create it when the Accounts dialog opens or when token import is requested.
- Imported files must be `.json` files only.
- Import supports multi-select.
- If a selected file name already exists in the target directory, overwrite it.
- The tool does not mutate token JSON payloads; it only copies them.

### 3. Internal proxy service

Add a new local service module, for example `token_pool_proxy.py`, that exposes a small OpenAI-compatible HTTP surface sufficient for Codex requests.

Responsibilities:
- Bind to a local port such as `127.0.0.1:<configured-port>`.
- Load token files from the token directory.
- Parse the token JSON format needed to build upstream auth headers.
- Forward Codex requests to upstream OpenAI-compatible endpoints.
- Stream responses back to Codex.
- Track token health.

This service is started and stopped by the desktop tool, not by a separate script.

### 4. Token selection strategy

Follow a CLIProxyAPI-compatible strategy at the compatibility level, not at the source-code level.

Initial strategy:
- Maintain a deterministic round-robin cursor across currently usable token files.
- On success, advance the cursor.
- On retry-worthy network or upstream `5xx` failures, try the next token.
- On explicit auth/quota failures, mark the token as cooling down for a fixed interval (initially 30 minutes).
- Keep the token file on disk; do not delete it automatically.

This provides parity with the external token-pool usage model without depending on the external binary.

### 5. Desktop launch integration

When the desktop tool launches a new Codex terminal:
- If backend mode is `codex_auth`, preserve existing behavior.
- If backend mode is `built_in_token_pool`:
  - Ensure the internal proxy is running.
  - Inject `OPENAI_BASE_URL=http://127.0.0.1:<proxy-port>`.
  - Inject a local placeholder `OPENAI_API_KEY` accepted by the internal proxy.
  - Then launch Codex normally.

Existing open terminals are not migrated. Only future terminals use the selected mode.

### 6. Desktop UI

Extend the existing `Accounts` dialog with a new `Token Pool` section.

Controls:
- Backend mode selector:
  - `Use Codex Auth`
  - `Use Built-in Token Pool`
- `Import Token Files`
- `Open Token Folder`
- `Start Proxy`
- `Stop Proxy`
- `Restart Proxy`

Status text shows:
- Current mode.
- Token directory path.
- Number of token files detected.
- Proxy port.
- Whether the internal proxy is running.
- Last proxy error summary, if any.

The existing account-slot controls remain visible and unchanged.

## Error Handling

- No token files present: token-pool mode can be selected, but launch should fail fast with a clear error.
- Invalid token JSON: skip the bad file and surface an error summary; do not crash the proxy.
- Upstream auth or quota failures: mark token unavailable for cooldown, then continue with remaining tokens.
- Proxy start failure: desktop launch should surface a direct error and avoid launching Codex with a broken base URL.
- Port in use: either fail clearly or auto-select the next available port, but the chosen behavior must be deterministic and surfaced in the UI.

## Security Notes

- Token files are sensitive and must never be displayed in full in the UI.
- Status should only show file names/counts and coarse health state.
- Logs must avoid printing raw token values.
- The placeholder local API key is not a real credential and should only gate local proxy access.

## Testing Strategy

- Unit tests for token directory creation and token import overwrite behavior.
- Unit tests for backend mode persistence.
- Unit tests for token selection, cooldown, and retry decisions.
- Unit tests for launch-environment generation in both backend modes.
- Integration-style tests for local proxy request forwarding with mocked upstream responses.
- Desktop helper tests for Accounts dialog actions that manipulate token-pool settings.

## Migration and Compatibility

- Existing account-slot files remain untouched.
- Existing desktop auth switching continues to work exactly as before.
- The new token-pool mode is additive.
- No migration is needed for `.codex/account_slots`.
- If `.cli-proxy-api` already exists, reuse it directly.

## Open Questions Resolved

- The feature is desktop-only in this phase.
- Token import is file-based, multi-select, overwrite-on-conflict.
- The implementation is an internal compatibility layer, not a dependency on `codex-launcher.ps1` or `cliproxyapi.exe`.
