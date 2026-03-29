# Codex Session Manager Project Notes

## Scope
This repository is a Windows-first Codex session manager with an optional mobile portal and Android client.

Primary entry points:
- `app.py`: desktop session manager UI
- `mobile_portal.py`: local HTTP portal for browser/mobile control
- `token_pool_proxy.py`: built-in local token-pool proxy
- `android-app/`: Android client project
- `run.bat`: desktop launcher
- `run-mobile.bat`: mobile portal launcher

## Current Implemented Capabilities

### Desktop manager
- Browse local Codex sessions.
- Show model, approval, sandbox, cwd, notes, MCP, and Skills.
- Open a selected session in a terminal.
- Create a new session with selected launch settings.
- Open the working directory or session history file.
- Delete local sessions.

### Mobile portal and Android flow
- Browse sessions from phone.
- Continue a session through real `codex exec resume`.
- Create a new session from a chosen folder.
- View MCP and Skills.
- Save per-session notes.
- Stop a reply in progress.
- Track reply status.
- Restore unsent draft text and selected image state in the Android client.

### Account and auth model
- Standard Codex auth account slots remain supported.
- Mobile account center uses the same slot model under `~/.codex/account_slots`.
- Built-in token pool mode is implemented inside this repo.
- Token pool reads JSON token files from `%USERPROFILE%\.cli-proxy-api\`.
- Token pool proxy exposes a local OpenAI-compatible endpoint for Codex.
- Startup prefers `conda run -n codex-accel python ...` when available, otherwise falls back to the current Python.

### Token pool robustness already implemented
- Round-robin token selection.
- Retry/failover across tokens.
- Quota/auth cooldown handling.
- Cooldown persistence in `.token-pool-state`.
- Startup diagnostics surfaced to the user instead of generic timeout-only failure.
- `requests` missing fallback path for proxy forwarding.

### Proxy model
- Desktop/mobile backend requests can use local proxy settings.
- Default proxy scheme is `socks5h://127.0.0.1:7897` when enabled.
- Phone/browser -> portal traffic is separate from portal -> upstream traffic.
- Tailscale or Cloudflare entry paths do not imply the backend itself is bypassing or using the same route.
- Public mobile-portal entry URLs can now be configured in `%USERPROFILE%\.codex\mobile_portal_settings.json` under `public_urls`.
- The portal injects the live `?token=...` into those configured public URLs at runtime.

### Controlled browser attach helpers
Implemented in `mobile_portal.py`:
- `get_controlled_browser_debug_url(browser_name)`
- `list_controlled_browser_pages(browser_name)`
- `select_controlled_browser_page(pages, url_prefix='', hostname='')`
- `describe_controlled_browser_attach(browser_name, url_prefix='', hostname='')`

Supported fixed browser targets only:
- `edge` -> `http://127.0.0.1:9222`
- `chrome` -> `http://127.0.0.1:9223`

Supported workflow:
1. User starts the controlled browser launcher manually.
2. User logs in manually to the target site.
3. The project inspects and re-attaches to that exact running browser instance later.

### Controlled browser action layer
Implemented in `controlled_browser.py` and exposed through `mobile_portal.py`.

Supported actions:
- inspect page info
- fetch HTML
- navigate
- evaluate JavaScript
- click by CSS selector
- type by CSS selector
- press a key
- wait for text

Portal routes:
- `GET /api/browser/attach`
- `POST /api/browser/info`
- `POST /api/browser/html`
- `POST /api/browser/navigate`
- `POST /api/browser/evaluate`
- `POST /api/browser/click`
- `POST /api/browser/type`
- `POST /api/browser/press`
- `POST /api/browser/wait-text`

Dependency note:
- real DevTools actions require `websocket-client`
- discovery helpers do not require that package

Launcher scripts outside this repo but currently used:
- `C:\Users\MECHREVO\Desktop\启动受控Edge.cmd`
- `C:\Users\MECHREVO\Desktop\启动代理Chrome.cmd`

## Current Known Boundaries
- Controlled browser attach supports only the fixed `9222` and `9223` launchers.
- Arbitrary user-opened browsers are not supported.
- The helper layer can reliably inspect the running controlled browser state, but this does not automatically fix any external MCP browser tool attaching to a different instance.
- Cloudflare/custom public URLs are config-backed, not Cloudflare-API-discovered.
- Built-in startup URL groups now render `Public (Cloudflare/custom)`, `Tailscale (cross-network)`, and `LAN` when available.

## Verification Commands
Use these commands before claiming behavior is working.

### Controlled browser attach
```powershell
python -c "import mobile_portal; print(mobile_portal.describe_controlled_browser_attach('edge', hostname='dash.cloudflare.com'))"
python -c "import mobile_portal; print(mobile_portal.describe_controlled_browser_attach('chrome', hostname='github.com'))"
```

### Focused tests
```powershell
$env:PYTHONNOUSERSITE='1'; conda run -n codex-accel python -m unittest tests.test_mobile_portal.ControlledBrowserAttachTests -v
```

### Broader regression
```powershell
$env:PYTHONNOUSERSITE='1'; conda run -n codex-accel python -m unittest tests.test_mobile_portal tests.test_token_pool_proxy -v
```

## Editing Guardrails
- Do not revert unrelated local user changes.
- Ignore local-only folders such as `logs/`, `output/`, `tmp/`, and token-pool smoke directories unless the task explicitly requires them.
- Treat `release/` as packaged output; only change it when the user explicitly asks for repackaging or release updates.
- Prefer adding tests before behavior changes in `mobile_portal.py` and `token_pool_proxy.py`.

## Recent Design Docs
- `docs/plans/2026-03-24-built-in-token-pool-design.md`
- `docs/plans/2026-03-26-mobile-account-center-design.md`
- `docs/plans/2026-03-29-controlled-browser-attach-design.md`
- `docs/plans/2026-03-29-controlled-browser-attach.md`
