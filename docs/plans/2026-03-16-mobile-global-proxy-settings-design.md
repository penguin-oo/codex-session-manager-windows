# Mobile Global Proxy Settings Design

**Goal**
Let the mobile app manage the computer-side global proxy used by `mobile_portal.py`, limited to enabling/disabling proxy usage and changing the port while keeping `host=127.0.0.1` and `scheme=socks5h` fixed.

## Scope
- Add a global mobile-managed proxy settings store on the computer.
- Expose read/write API endpoints in `mobile_portal.py`.
- Add a mobile entry point at `⋮ -> Proxy settings` on the home screen.
- Keep chat/session settings read-only for proxy summary.

## Storage
- Add `C:\Users\MECHREVO\.codex\mobile_portal_settings.json`.
- Fields:
  - `proxy_enabled`
  - `proxy_port`
- If missing, defaults are:
  - `proxy_enabled = true`
  - `proxy_port = 7897`

## Behavior
- Mobile saves settings through portal APIs.
- All later `codex exec` jobs started by `mobile_portal.py` use the saved settings.
- Existing running replies are unaffected.
- Proxy summary shown in chat headers remains read-only.

## Validation
- Port must be an integer in `1..65535`.
- Empty or invalid input is rejected.
- `scheme` and `host` are fixed and not user-editable.

## UI
- Home screen menu adds `Proxy settings`.
- Dialog contains:
  - enable switch or checkbox
  - port input
  - save button
- Success banner confirms the saved state.

## Testing
- Backend tests for default settings, save/load, validation, and environment injection.
- Android tests for parsing settings payload and save request building.
