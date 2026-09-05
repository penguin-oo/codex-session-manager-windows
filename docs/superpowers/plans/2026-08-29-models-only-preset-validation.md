# Models-Only Preset Validation Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a visible, preset-scoped models-only validation option that never sends a conversation request and is shared by desktop and mobile workflows.

**Architecture:** Persist `models_only_validation` in normalized presets and route validation through one pure orchestration function in `token_pool_settings.py`. Desktop and mobile services validate before writing, while their UIs expose and submit the same field.

**Tech Stack:** Python 3, `unittest`, Tkinter/ttk, embedded HTML/CSS/JavaScript.

---

## Chunk 1: Shared Validation And Persistence

### Task 1: Define models-only resolution behavior

**Files:**
- Modify: `tests/test_proxy_routing.py`
- Modify: `token_pool_settings.py`

- [x] Add failing tests proving the resolver calls model discovery but not protocol detection.
- [x] Add failing tests for empty results and model-selection precedence.
- [x] Run the targeted tests and confirm they fail because the resolver is missing.
- [x] Implement `resolve_openai_compatible_models_only_config` using URL normalization and `fetch_openai_compatible_models` only.
- [x] Run the targeted tests and confirm they pass.

### Task 2: Persist the explicit preset option

**Files:**
- Modify: `tests/test_proxy_routing.py`
- Modify: `token_pool_settings.py`

- [x] Add failing tests for `models_only_validation` round-trip persistence and legacy `skip_validation` migration.
- [x] Run the tests and verify the expected field is absent or incorrect.
- [x] Add the field to preset normalization, payload conversion, top-level synchronization, and `save_openai_preset`.
- [x] Stop writing the hidden `skip_validation` field while retaining migration reads.
- [x] Run the tests and confirm they pass.

## Chunk 2: Desktop Integration

### Task 3: Route desktop operations through the selected validation mode

**Files:**
- Modify: `tests/test_proxy_routing.py`
- Modify: `app.py`

- [x] Add failing tests for desktop save and apply in models-only mode.
- [x] Add a failure test proving the settings file is byte-for-byte unchanged after validation failure.
- [x] Run the targeted tests and confirm the old hidden-bypass behavior fails them.
- [x] Add `models_only_validation` parameters to desktop save and apply services.
- [x] Validate before any settings write.
- [x] Preserve the selected protocol in models-only mode and retain full validation when disabled.
- [x] Run the desktop tests and confirm they pass.

### Task 4: Expose the desktop checkbox

**Files:**
- Modify: `tests/test_proxy_routing.py`
- Modify: `app.py`

- [x] Add a failing source-level UI wiring test for the visible checkbox and callback arguments.
- [x] Add the Tkinter variable and checkbox next to the API preset controls.
- [x] Load its value whenever preset selection changes.
- [x] Pass it to refresh, save, and apply callbacks.
- [x] Run the UI wiring test and confirm it passes.

## Chunk 3: Mobile Integration

### Task 5: Route mobile operations through the selected validation mode

**Files:**
- Modify: `tests/test_proxy_routing.py`
- Modify: `mobile_portal.py`

- [x] Add failing service and route tests for mobile save and apply.
- [x] Add a failure test proving validation errors do not mutate the settings file.
- [x] Add `models_only_validation` to service signatures and `/api/backend` payload handling.
- [x] Use the shared resolver before writes and preserve protocol when enabled.
- [x] Run the mobile tests and confirm they pass.

### Task 6: Expose the mobile checkbox

**Files:**
- Modify: `tests/test_proxy_routing.py`
- Modify: `mobile_portal.py`

- [x] Add a failing markup/JavaScript test for the visible checkbox.
- [x] Add the checkbox to the backend panel with readable existing styles.
- [x] Populate it from the selected preset and submit it for save and apply.
- [x] Run the UI wiring test and confirm it passes.

## Chunk 4: Verification

### Task 7: Regression verification

**Files:**
- Verify only.

- [x] Run focused API preset tests.
- [x] Run `python -m py_compile app.py mobile_portal.py token_pool_settings.py`.
- [x] Run the complete test suite.
- [x] Inspect `git diff --check` and `git diff` to ensure existing unrelated changes remain intact.
