# Cloudflare Public URL Design

## Goal
Make the mobile portal surface Cloudflare or other public entry URLs directly inside the project instead of leaving them only in an external dashboard.

## Constraints
- Do not depend on Cloudflare API credentials.
- Keep the existing Tailscale and LAN flow unchanged.
- Reuse existing portal settings storage instead of creating another config file.
- Preserve existing proxy settings when users update only proxy state.

## Options Considered
1. Cloudflare API auto-discovery
   - Pro: no manual URL entry after setup.
   - Con: requires API tokens, zone/account mapping, and more failure modes.
2. Config-backed public URLs in existing portal settings
   - Pro: simple, stable, works with Cloudflare Tunnel or any reverse proxy.
   - Con: user must provide the public hostname once.
3. Hardcode the current hostname in repo
   - Pro: fastest for one machine.
   - Con: wrong for every other machine and unsafe to publish.

## Selected Design
Use option 2.

Store public base URLs in `%USERPROFILE%\.codex\mobile_portal_settings.json` under `public_urls`. At runtime the portal appends the current access token, then exposes those URLs in:
- startup console output
- `/api/bootstrap`
- the mobile portal web header

## Behavior
- Accept only absolute `http` or `https` URLs.
- Strip stale `token` query parameters and fragments from stored values.
- Preserve configured `public_urls` when proxy settings are updated.
- Render public URLs before Tailscale and LAN because they are the broadest access path.

## Testing
- parse and normalize configured public URLs
- preserve `public_urls` across proxy-settings updates
- include public URLs in startup groups
- include startup URL groups in bootstrap payload
