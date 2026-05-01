# OpenAI Compatible Backend Design

**Date:** 2026-05-01

**Goal**

Add a third backend mode that lets the desktop app and mobile portal launch Codex against a user-configured OpenAI-compatible `base URL + API key`, while preserving the existing `codex_auth` and `built_in_token_pool` modes.

**Scope**

- Keep only the three account slots that currently expose live quota data.
- Add a new backend mode named `openai_compatible`.
- Persist `base URL`, `API key`, selected model, and fetched model list in backend settings.
- On first save of a configured key, request `GET /models` and cache the returned model IDs.
- Reuse the existing provider override path for Codex launches instead of adding a separate launch flow.

**Architecture**

- `token_pool_settings.py` remains the single backend-settings store, but it grows additional fields for the new direct mode.
- `app.py` and `mobile_portal.py` both reuse provider-override helpers that configure a custom `model_provider` with `wire_api="responses"` and `requires_openai_auth=false`.
- The desktop account dialog becomes the primary UI for configuring the direct backend.
- Available-model loading merges the configured OpenAI-compatible model cache when that backend mode is active.

**Error Handling**

- Saving the backend config should still persist `base URL` and `API key` if model discovery fails.
- Model-refresh failures must surface a concrete error string instead of silently falling back.
- Empty or malformed `/models` responses should be treated as discovery failures, not as success with an empty list.

**Testing**

- Unit tests for backend-settings persistence of the new fields.
- Unit tests for provider override/environment generation in the new mode.
- Unit tests for model discovery parsing and failure handling.
- Unit tests for desktop helper/model-loading behavior with the new backend mode.
