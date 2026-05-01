# OpenAI Compatible Backend Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an `openai_compatible` backend mode with `base URL + API key + model discovery`, and remove account slots that do not currently provide usable quota data.

**Architecture:** Extend the existing backend settings store instead of creating a second config file, reuse the current Codex provider override mechanism for launches, and surface the new backend config in the desktop account dialog. Model discovery is a small HTTP helper that fetches OpenAI-compatible `/models` once and caches the resulting IDs for later selection.

**Tech Stack:** Python, Tkinter, local JSON settings, urllib HTTP calls, unittest.

---

## Chunk 1: Backend settings and provider plumbing

### Task 1: Add failing tests for `openai_compatible` settings persistence

**Files:**
- Modify: `tests/test_app_helpers.py`
- Modify: `tests/test_mobile_portal.py`
- Modify: `token_pool_settings.py`

- [ ] **Step 1: Write the failing tests**
- [ ] **Step 2: Run the focused tests to verify they fail**
  Run: `python -m unittest tests.test_app_helpers.AppHelperTests tests.test_mobile_portal.PortalAccountSlotsTests -v`
- [ ] **Step 3: Add minimal settings persistence and provider/env helpers**
- [ ] **Step 4: Re-run the focused tests to verify they pass**

### Task 2: Add failing tests for OpenAI-compatible model discovery

**Files:**
- Modify: `tests/test_app_helpers.py`
- Modify: `tests/test_mobile_portal.py`
- Modify: `app.py`
- Modify: `mobile_portal.py`

- [ ] **Step 1: Write tests for `/models` fetch success and failure parsing**
- [ ] **Step 2: Run the focused tests to verify they fail**
  Run: `python -m unittest tests.test_app_helpers.AppHelperTests tests.test_mobile_portal.LoadMessagesTests -v`
- [ ] **Step 3: Implement shared discovery helpers and cache merge logic**
- [ ] **Step 4: Re-run the focused tests to verify they pass**

## Chunk 2: Desktop backend UI and slot cleanup

### Task 3: Add failing tests for desktop backend UI helpers

**Files:**
- Modify: `tests/test_app_helpers.py`
- Modify: `app.py`

- [ ] **Step 1: Write tests for loading models from the new backend cache and for new launch overrides**
- [ ] **Step 2: Run the focused tests to verify they fail**
  Run: `python -m unittest tests.test_app_helpers.AppHelperTests -v`
- [ ] **Step 3: Implement desktop backend controls for base URL, key, model, and refresh**
- [ ] **Step 4: Re-run the focused tests to verify they pass**

### Task 4: Remove non-usable slots and verify resulting state

**Files:**
- Modify: runtime data under `%USERPROFILE%\\.codex\\account_slots`

- [ ] **Step 1: Delete all slots except `slot-3`, `slot-4`, and `slot-6`**
- [ ] **Step 2: Re-list slots and verify only the expected three remain**
- [ ] **Step 3: Re-check quota visibility for the remaining slots**

## Chunk 3: Regression verification

### Task 5: Run targeted and broader regression

**Files:**
- Modify: none

- [ ] **Step 1: Run focused regression**
  Run: `python -m unittest tests.test_app_helpers.AppHelperTests tests.test_mobile_portal.PortalAccountSlotsTests -v`
- [ ] **Step 2: Run broader regression**
  Run: `python -m unittest tests.test_mobile_portal tests.test_token_pool_proxy tests.test_app_helpers tests.test_auth_slots -v`
- [ ] **Step 3: Run syntax verification**
  Run: `python -m py_compile app.py mobile_portal.py token_pool_settings.py tests/test_app_helpers.py tests/test_mobile_portal.py tests/test_auth_slots.py`
