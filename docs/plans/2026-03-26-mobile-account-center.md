# Mobile Account Center Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make the Android mobile account center readable and keep normal account-slot switching usable even when the token pool backend is disabled.

**Architecture:** Keep `mobile_portal.py` and `auth_slots.py` as the account data source. Refactor Android-side account-center presentation into clearer, testable helper methods, then wire the updated dialog back into `MainActivity` and `ChatActivity` without changing API contracts.

**Tech Stack:** Python 3.11 backend, Android Java UI, JUnit-style local Java tests, existing unittest backend suite.

---

### Task 1: Add testable account-center text/action helpers

**Files:**
- Modify: `android-app/app/src/main/java/com/penguinoo/codexmobile/AccountCenterDialogSupport.java`
- Test: `android-app/app/src/test/java/com/penguinoo/codexmobile/AccountCenterDialogSupportTest.java`

**Step 1: Write the failing test**
- Add tests for current-account summary, backend summary, and slot action visibility labels.

**Step 2: Run test to verify it fails**
Run: Java/JUnit compile-and-run command for the new test class.
Expected: FAIL because helper methods do not exist yet.

**Step 3: Write minimal implementation**
- Extract pure helper methods in `AccountCenterDialogSupport` for display summaries and action availability.

**Step 4: Run test to verify it passes**
Run the same Java/JUnit command.
Expected: PASS.

### Task 2: Rebuild the dialog layout for phone readability

**Files:**
- Modify: `android-app/app/src/main/java/com/penguinoo/codexmobile/AccountCenterDialogSupport.java`
- Modify: `android-app/app/src/main/res/values/strings.xml`

**Step 1: Write/update the failing test**
- Cover slot-state labels for bound/unbound/current-active rows if needed.

**Step 2: Run test to verify it fails**
Run the same local Java/JUnit command.
Expected: FAIL on missing summary/state logic.

**Step 3: Write minimal implementation**
- Replace cramped horizontal rows with stacked sections and high-contrast cards.
- Make each slot card show fixed action buttons with clearer labels.
- Keep backend controls available but visually secondary.

**Step 4: Run test to verify it passes**
Run the same Java/JUnit command.
Expected: PASS.

### Task 3: Reconnect updated dialog in activities and verify backend compatibility

**Files:**
- Modify: `android-app/app/src/main/java/com/penguinoo/codexmobile/MainActivity.java`
- Modify: `android-app/app/src/main/java/com/penguinoo/codexmobile/ChatActivity.java`
- Verify: `mobile_portal.py`
- Verify: `tests/test_mobile_portal.py`

**Step 1: Write the failing test**
- Reuse backend/account payload regression tests already in repo; extend only if activity wiring needs new helper coverage.

**Step 2: Run test to verify it fails**
- Only if a new regression test is added.

**Step 3: Write minimal implementation**
- Ensure refreshed dialog behavior still reloads correctly after bind/switch/rename/delete/backend actions.
- Keep non-token-pool switching path intact.

**Step 4: Run test to verify it passes**
Run: `conda run -n codex-accel python -m unittest tests.test_mobile_portal -v`
Expected: PASS.

### Task 4: Final verification

**Files:**
- Verify changed Android files
- Verify `tests/test_token_pool_proxy.py`

**Step 1: Run backend regression tests**
Run: `conda run -n codex-accel python -m unittest tests.test_mobile_portal tests.test_token_pool_proxy -v`
Expected: PASS.

**Step 2: Run Android local compile/test check**
Run the manual `javac` + JUnit command for account-center related sources.
Expected: PASS.
