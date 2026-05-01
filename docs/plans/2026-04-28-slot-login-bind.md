# Slot Login Bind Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a backend-only account-slot flow that opens a fresh Codex login in the current `.codex` home, then saves the resulting login into an existing slot.

**Architecture:** Keep the feature inside `mobile_portal.py` so the portal owns the blocking login flow, slot existence checks, and desktop refresh signal. Reuse existing slot helpers from `auth_slots.py` and expose a single new HTTP route for future Android/Desktop wiring.

**Tech Stack:** Python, `subprocess`, existing `auth_slots` helpers, `unittest`

---

### Task 1: Define the backend contract

**Files:**
- Modify: `mobile_portal.py`
- Test: `tests/test_mobile_portal.py`

- [ ] **Step 1: Write the failing tests**

Cover:
- successful `login-bind` service flow
- reject when active replies are running
- reject when the target slot does not exist
- reject when login exits successfully but current auth fingerprint does not change
- route dispatch for `POST /api/accounts/{slot_id}/login-bind`

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: `python -m unittest tests.test_mobile_portal.PortalAccountSlotsTests tests.test_mobile_portal.PortalBrowserControlTests -v`

- [ ] **Step 3: Add the minimal backend implementation**

Implement:
- a helper that runs `codex login` with the portal proxy environment
- `PortalService.login_and_bind_account(slot_id)`
- `POST /api/accounts/{slot_id}/login-bind`

- [ ] **Step 4: Re-run focused tests**

Run the same focused test command and verify all new tests pass.

### Task 2: Verify regression safety

**Files:**
- Modify: `mobile_portal.py`
- Test: `tests/test_mobile_portal.py`

- [ ] **Step 1: Run broader regression**

Run: `python -m unittest tests.test_mobile_portal tests.test_token_pool_proxy tests.test_app_helpers tests.test_auth_slots -v`

- [ ] **Step 2: Run syntax verification**

Run: `python -m py_compile mobile_portal.py tests/test_mobile_portal.py tests/test_auth_slots.py`
