# Mobile Portal Token Pool + Message Sanitizing Design

**Goal:** Add assistant-protocol sanitizing to the mobile portal and make the mobile client able to use and control the built-in token pool backend without requiring the desktop UI to manually start it first.

**Architecture:** Keep the current repository structure. Extend `mobile_portal.py` to (1) sanitize assistant text during session loading, (2) auto-start the built-in token pool proxy before mobile-launched jobs when token-pool mode is enabled, and (3) expose backend status/control APIs. Extend the Android client only far enough to read and invoke those APIs from the existing accounts entry point.

**Scope:** No new parallel `token_pool_backend.py` module. Reuse `token_pool_settings.py` and `token_pool_proxy.py`.

## Decisions

1. Reuse current backend settings storage and proxy runner instead of introducing a second shared module.
2. Treat auto-start as launch-time behavior: if backend mode is `built_in_token_pool`, mobile new-chat/resume ensures the proxy is ready before invoking Codex.
3. Keep Android UI incremental: expose backend status/actions inside the current accounts flow first.
4. Add tests first for each new behavior.
