# Stop Reply Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Let the mobile client stop the current reply without losing already generated text.

**Architecture:** Add job cancellation to `mobile_portal.py`, expose it through a new API endpoint, then wire an Android `Stop` action to that endpoint. Preserve `live_text`/`last_message` and treat `cancelled` as a terminal state in the chat UI.

**Tech Stack:** Python 3, Android Java, local HTTP API, JUnit, unittest.

---

### Task 1: Backend cancellation state
**Files:**
- Modify: `mobile_portal.py`
- Test: `tests/test_mobile_portal.py`

1. Write failing tests for cancelling a running job.
2. Run the failing Python tests.
3. Implement `cancel_job` and terminal `cancelled` status handling.
4. Run the targeted Python tests.

### Task 2: Cancel API
**Files:**
- Modify: `mobile_portal.py`
- Test: `tests/test_mobile_portal.py`

1. Write failing test coverage for the cancel endpoint behavior.
2. Run the failing Python tests.
3. Add `POST /api/jobs/{job_id}/cancel`.
4. Run the targeted Python tests.

### Task 3: Android stop action
**Files:**
- Modify: `android-app/app/src/main/java/com/penguinoo/codexmobile/PortalApiClient.java`
- Modify: `android-app/app/src/main/java/com/penguinoo/codexmobile/ChatActivity.java`
- Modify: `android-app/app/src/main/res/layout/activity_chat.xml`
- Modify: `android-app/app/src/main/res/values/strings.xml`
- Test: `android-app/app/src/test/java/com/penguinoo/codexmobile/...`

1. Write failing Android tests for stop-button state / cancelled terminal state.
2. Run the failing Android tests.
3. Implement the button and cancel flow.
4. Run Android unit tests.

### Task 4: Verification
**Files:**
- Modify: `release/codex-mobile-debug.apk` (build artifact)

1. Run Python compile/tests.
2. Run Android unit tests and assemble debug APK.
3. Copy the APK to `release/codex-mobile-debug.apk`.