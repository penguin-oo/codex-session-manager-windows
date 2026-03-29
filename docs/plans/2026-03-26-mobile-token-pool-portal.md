# Mobile Portal Token Pool + Message Sanitizing Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add mobile assistant-message sanitizing and make the mobile portal able to use and control the built-in token pool backend directly.

**Architecture:** Extend the existing mobile portal backend instead of adding a new backend abstraction. Reuse the current token-pool settings/proxy modules, add portal-side backend status/control helpers, and minimally expose them through the Android accounts flow. Implement with TDD.

**Tech Stack:** Python 3, unittest, Android Java client, existing mobile portal HTTP API.

---

### Task 1: Assistant message sanitizing

**Files:**
- Modify: `mobile_portal.py`
- Test: `tests/test_mobile_portal.py`

**Step 1: Write the failing test**
- Add tests for protocol-only assistant text being hidden.
- Add tests for valid assistant text with protocol suffix being trimmed.

**Step 2: Run test to verify it fails**
Run: `python -m unittest tests.test_mobile_portal -v`
Expected: new sanitizing tests fail.

**Step 3: Write minimal implementation**
- Add protocol-pattern detection and assistant text sanitizing helper.
- Apply it while loading session messages.

**Step 4: Run test to verify it passes**
Run: `python -m unittest tests.test_mobile_portal -v`
Expected: new sanitizing tests pass.

### Task 2: Mobile token-pool backend auto-start and APIs

**Files:**
- Modify: `mobile_portal.py`
- Test: `tests/test_mobile_portal.py`
- Reuse: `token_pool_settings.py`, `token_pool_proxy.py`

**Step 1: Write the failing test**
- Add tests for backend status payload.
- Add tests that mobile new-chat/resume auto-start the proxy in token-pool mode.
- Add tests for backend API endpoints.

**Step 2: Run test to verify it fails**
Run: `python -m unittest tests.test_mobile_portal -v`
Expected: backend tests fail.

**Step 3: Write minimal implementation**
- Add portal backend status helpers.
- Add start/stop/restart backend helpers.
- Ensure token-pool mode auto-starts backend before mobile-launched jobs.
- Add `/api/backend`, `/api/backend/start`, `/api/backend/stop`, `/api/backend/restart`.

**Step 4: Run test to verify it passes**
Run: `python -m unittest tests.test_mobile_portal -v`
Expected: backend tests pass.

### Task 3: Android minimal backend integration

**Files:**
- Create: `android-app/app/src/main/java/com/penguinoo/codexmobile/BackendStatusPayload.java`
- Modify: `android-app/app/src/main/java/com/penguinoo/codexmobile/AccountSlotsPayload.java`
- Modify: `android-app/app/src/main/java/com/penguinoo/codexmobile/PortalApiClient.java`
- Modify: `android-app/app/src/main/java/com/penguinoo/codexmobile/MainActivity.java`
- Modify: `android-app/app/src/main/java/com/penguinoo/codexmobile/ChatActivity.java`
- Modify: `android-app/app/src/main/res/values/strings.xml`
- Test: `android-app/app/src/test/java/com/penguinoo/codexmobile/AccountSlotsPayloadParsingTest.java`
- Create: `android-app/app/src/test/java/com/penguinoo/codexmobile/BackendStatusPayloadParsingTest.java`

**Step 1: Write the failing test**
- Extend account payload parsing test for backend object.
- Add backend payload parsing test.

**Step 2: Run test to verify it fails**
Run: Gradle/JUnit parsing tests when available; otherwise verify compile-level consistency by code inspection and targeted tests already in repo.
Expected: parsing tests fail before implementation.

**Step 3: Write minimal implementation**
- Add backend payload model.
- Parse backend object in `PortalApiClient`.
- Show backend status/actions from the existing accounts dialogs.

**Step 4: Run test to verify it passes**
Run: targeted Android tests if available.
Expected: parsing tests pass.
