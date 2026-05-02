# OpenAI-Compatible Protocol Adapter Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add save-time protocol detection plus a local `responses` adapter so the existing `openai_compatible` backend can work against either `/responses` or `/chat/completions` upstreams.

**Architecture:** Persist the detected upstream protocol in `token_pool_settings.py`, reject invalid saves before settings are written, and route `openai_compatible` launches through a new local adapter process that always exposes a `responses` surface to Codex. Keep `codex_auth` and `built_in_token_pool` logic unchanged.

**Tech Stack:** Python, local JSON settings, `urllib`/optional `requests`, Tkinter, Android portal HTTP API, `unittest`.

---

## File structure

- Create: `custom_provider_proxy.py`
  - Local adapter for `openai_compatible` only.
  - Handles upstream protocol probing helpers, request translation, response translation, and local HTTP serving.
- Modify: `token_pool_settings.py`
  - Persist detected protocol and validation metadata.
  - Add save-time protocol probing.
- Modify: `app.py`
  - Save custom backend config only after successful detection.
  - Launch the custom provider adapter and point Codex provider override at it.
- Modify: `mobile_portal.py`
  - Mirror desktop backend save validation.
  - Launch and monitor the custom provider adapter for mobile-triggered Codex runs.
- Modify: `tests/test_app_helpers.py`
  - Desktop helper coverage for detection, save behavior, and launch overrides.
- Modify: `tests/test_mobile_portal.py`
  - Portal save behavior, env/override wiring, and adapter launch coverage.
- Modify: `tests/test_token_pool_proxy.py`
  - Keep existing token-pool regressions untouched if any shared helper changes are needed.
- Create: `tests/test_custom_provider_proxy.py`
  - Unit tests for protocol detection and translation behavior.

## Chunk 1: Detection and settings persistence

### Task 1: Add failing tests for protocol persistence and detection fallback

**Files:**
- Modify: `tests/test_app_helpers.py`
- Modify: `tests/test_mobile_portal.py`
- Modify: `token_pool_settings.py`

- [ ] **Step 1: Write failing tests for `openai_protocol` persistence and save refusal when no protocol works**
- [ ] **Step 2: Run focused tests to verify they fail**
  Run: `python -m unittest tests.test_app_helpers.AppHelperTests tests.test_mobile_portal.PortalAccountSlotsTests -v`
  Expected: FAIL on missing protocol field or missing save-time validation behavior.
- [ ] **Step 3: Implement protocol fields plus save-time detection helpers in `token_pool_settings.py`**
- [ ] **Step 4: Re-run focused tests to verify they pass**
  Run: `python -m unittest tests.test_app_helpers.AppHelperTests tests.test_mobile_portal.PortalAccountSlotsTests -v`
  Expected: PASS.

### Task 2: Add failing tests for `/responses` then `/chat/completions` probe order

**Files:**
- Modify: `tests/test_app_helpers.py`
- Modify: `tests/test_mobile_portal.py`
- Modify: `token_pool_settings.py`

- [ ] **Step 1: Write tests that prove probe order is `responses` first, `chat/completions` second**
- [ ] **Step 2: Run focused tests to verify they fail**
  Run: `python -m unittest tests.test_app_helpers.AppHelperTests tests.test_mobile_portal.PortalAccountSlotsTests -v`
  Expected: FAIL because probe helper or order is missing.
- [ ] **Step 3: Implement minimal probing and error messages**
- [ ] **Step 4: Re-run focused tests to verify they pass**

## Chunk 2: Local adapter and translation

### Task 3: Add failing tests for adapter request/response translation

**Files:**
- Create: `tests/test_custom_provider_proxy.py`
- Create: `custom_provider_proxy.py`

- [ ] **Step 1: Write failing tests for text request translation**
- [ ] **Step 2: Run focused tests to verify they fail**
  Run: `python -m unittest tests.test_custom_provider_proxy -v`
  Expected: FAIL because module or translation helpers do not exist.
- [ ] **Step 3: Implement minimal text translation for `responses -> chat/completions` and back**
- [ ] **Step 4: Re-run focused tests to verify they pass**

### Task 4: Extend adapter coverage to image, streaming, and tool calls

**Files:**
- Modify: `tests/test_custom_provider_proxy.py`
- Modify: `custom_provider_proxy.py`

- [ ] **Step 1: Write failing tests for image input mapping**
- [ ] **Step 2: Run the targeted test to verify it fails**
- [ ] **Step 3: Implement image mapping**
- [ ] **Step 4: Re-run the targeted test to verify it passes**
- [ ] **Step 5: Write failing tests for tool-call translation**
- [ ] **Step 6: Run the targeted tests to verify they fail**
- [ ] **Step 7: Implement tool-call and tool-result mapping**
- [ ] **Step 8: Re-run the targeted tests to verify they pass**
- [ ] **Step 9: Write failing tests for streaming event translation**
- [ ] **Step 10: Run the targeted tests to verify they fail**
- [ ] **Step 11: Implement streaming event translation**
- [ ] **Step 12: Re-run the targeted tests to verify they pass**

## Chunk 3: Desktop and portal launch plumbing

### Task 5: Add failing tests for desktop adapter launch wiring

**Files:**
- Modify: `tests/test_app_helpers.py`
- Modify: `app.py`

- [ ] **Step 1: Write failing tests that desktop `openai_compatible` launches point Codex at the local adapter URL instead of the upstream URL**
- [ ] **Step 2: Run focused tests to verify they fail**
  Run: `python -m unittest tests.test_app_helpers.AppHelperTests -v`
  Expected: FAIL on provider override args or adapter command helpers.
- [ ] **Step 3: Implement adapter startup/override wiring in `app.py`**
- [ ] **Step 4: Re-run focused tests to verify they pass**

### Task 6: Add failing tests for mobile portal adapter launch wiring

**Files:**
- Modify: `tests/test_mobile_portal.py`
- Modify: `mobile_portal.py`

- [ ] **Step 1: Write failing tests that mobile portal launches the adapter and injects the correct local auth/env**
- [ ] **Step 2: Run focused tests to verify they fail**
  Run: `python -m unittest tests.test_mobile_portal.ProxyEnvTests tests.test_mobile_portal.MobileBackendLaunchTests -v`
  Expected: FAIL because adapter launch helpers do not exist.
- [ ] **Step 3: Implement portal-side adapter startup and override wiring**
- [ ] **Step 4: Re-run focused tests to verify they pass**

## Chunk 4: Full verification

### Task 7: Run regression and compile checks

**Files:**
- Modify: none

- [ ] **Step 1: Run adapter-focused regression**
  Run: `python -m unittest tests.test_custom_provider_proxy tests.test_app_helpers.AppHelperTests tests.test_mobile_portal.PortalAccountSlotsTests tests.test_mobile_portal.ProxyEnvTests tests.test_mobile_portal.MobileBackendLaunchTests -v`
- [ ] **Step 2: Run broader regression**
  Run: `python -m unittest tests.test_mobile_portal tests.test_token_pool_proxy tests.test_app_helpers tests.test_auth_slots tests.test_custom_provider_proxy -v`
- [ ] **Step 3: Run syntax verification**
  Run: `python -m py_compile app.py mobile_portal.py token_pool_settings.py custom_provider_proxy.py tests/test_app_helpers.py tests/test_mobile_portal.py tests/test_auth_slots.py tests/test_custom_provider_proxy.py`
