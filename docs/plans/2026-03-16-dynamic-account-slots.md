# Dynamic Account Slots Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the fixed two-slot account switcher with dynamic account slots and show the current account's weekly quota from `codex /status`.

**Architecture:** Backend slot management remains file-backed under `auth-slots/`, but moves from hardcoded `account-a/account-b` constants to metadata-driven dynamic slots with a compatibility migration. Desktop and Android both consume the same backend payload shape and render a variable-length slot list while quota display is read-only and scoped to the active account.

**Tech Stack:** Python, Tkinter, Android Java, JSON metadata, unittest, Gradle unit tests.

---

### Task 1: Add dynamic slot metadata and migration in backend helpers

**Files:**
- Modify: `auth_slots.py`
- Test: `tests/test_auth_slots.py`

**Step 1: Write failing tests**
- Add tests for migrating legacy `account-a/account-b` into `slots.json`.
- Add tests for create/rename/delete/list dynamic slots.

**Step 2: Run tests to verify failure**
Run: `conda run -n codex-accel python -m unittest D:\codex\manger\tests\test_auth_slots.py`
Expected: FAIL for missing dynamic slot behaviors.

**Step 3: Implement minimal backend changes**
- Introduce `slots.json` metadata helpers.
- Add migration from legacy directories.
- Replace fixed slot listing with metadata-driven listing.

**Step 4: Run tests to verify pass**
Run: `conda run -n codex-accel python -m unittest D:\codex\manger\tests\test_auth_slots.py`
Expected: PASS.

**Step 5: Commit**
```bash
git add auth_slots.py tests/test_auth_slots.py
git commit -m "feat: support dynamic auth slot metadata"
```

### Task 2: Add current-account quota reading and backend APIs

**Files:**
- Modify: `mobile_portal.py`
- Test: `tests/test_mobile_portal.py`

**Step 1: Write failing tests**
- Add tests for account payload quota field.
- Add tests for create/rename/delete slot API flows.
- Add tests for parsing representative `codex /status` weekly quota text.

**Step 2: Run tests to verify failure**
Run: `conda run -n codex-accel python -m unittest D:\codex\manger\tests\test_mobile_portal.py`
Expected: FAIL for missing payload fields/endpoints.

**Step 3: Implement minimal backend changes**
- Extend account payload to dynamic slots.
- Add create/rename/delete slot endpoints.
- Add quota reader with timeout and graceful fallback.

**Step 4: Run tests to verify pass**
Run: `conda run -n codex-accel python -m unittest D:\codex\manger\tests\test_mobile_portal.py`
Expected: PASS.

**Step 5: Commit**
```bash
git add mobile_portal.py tests/test_mobile_portal.py
git commit -m "feat: expose dynamic account slots and quota"
```

### Task 3: Update desktop account dialog

**Files:**
- Modify: `app.py`
- Test: `tests/test_app_helpers.py`

**Step 1: Write failing tests**
- Add helper tests for dynamic slot label formatting and quota summary text.

**Step 2: Run tests to verify failure**
Run: `conda run -n codex-accel python -m unittest D:\codex\manger\tests\test_app_helpers.py`
Expected: FAIL for old fixed-slot assumptions.

**Step 3: Implement minimal UI changes**
- Replace fixed A/B cards with generated slot rows.
- Add New/Rename/Delete controls.
- Show current quota above the slot list.

**Step 4: Run tests to verify pass**
Run: `conda run -n codex-accel python -m unittest D:\codex\manger\tests\test_app_helpers.py`
Expected: PASS.

**Step 5: Commit**
```bash
git add app.py tests/test_app_helpers.py
git commit -m "feat: support dynamic account slots in desktop UI"
```

### Task 4: Update Android account dialogs

**Files:**
- Modify: `android-app/app/src/main/java/com/penguinoo/codexmobile/MainActivity.java`
- Modify: `android-app/app/src/main/java/com/penguinoo/codexmobile/ChatActivity.java`
- Modify: `android-app/app/src/main/java/com/penguinoo/codexmobile/PortalApiClient.java`
- Modify: `android-app/app/src/main/java/com/penguinoo/codexmobile/AccountSlotSummary.java`
- Modify: `android-app/app/src/main/java/com/penguinoo/codexmobile/AccountSlotsPayload.java`
- Modify: `android-app/app/src/main/res/values/strings.xml`
- Test: `android-app/app/src/test/java/com/penguinoo/codexmobile/AccountSlotsPayloadParsingTest.java`

**Step 1: Write failing tests**
- Add parsing assertions for dynamic slot labels and quota field.

**Step 2: Run tests to verify failure**
Run: `D:\android-tools\gradle-8.13\bin\gradle.bat -p D:\codex\manger\android-app testDebugUnitTest`
Expected: FAIL for payload/model mismatch.

**Step 3: Implement minimal Android changes**
- Render dynamic slot list.
- Add create/rename/delete actions.
- Show current quota text in account dialogs.

**Step 4: Run tests to verify pass**
Run: `D:\android-tools\gradle-8.13\bin\gradle.bat -p D:\codex\manger\android-app testDebugUnitTest`
Expected: PASS.

**Step 5: Commit**
```bash
git add android-app/app/src/main/java/com/penguinoo/codexmobile android-app/app/src/main/res/values/strings.xml android-app/app/src/test/java/com/penguinoo/codexmobile/AccountSlotsPayloadParsingTest.java
git commit -m "feat: support dynamic account slots in mobile UI"
```

### Task 5: Final verification and packaging

**Files:**
- Modify: `release/codex-mobile-debug.apk` (rebuilt artifact)
- Modify: `README.md` if usage text changes are needed

**Step 1: Run Python verification**
Run: `conda run -n codex-accel python -m unittest D:\codex\manger\tests\test_auth_slots.py D:\codex\manger\tests\test_mobile_portal.py D:\codex\manger\tests\test_app_helpers.py`
Expected: PASS.

**Step 2: Run compile verification**
Run: `conda run -n codex-accel python -m py_compile D:\codex\manger\auth_slots.py D:\codex\manger\mobile_portal.py D:\codex\manger\app.py`
Expected: PASS.

**Step 3: Run Android verification and rebuild APK**
Run: `D:\android-tools\gradle-8.13\bin\gradle.bat -p D:\codex\manger\android-app testDebugUnitTest assembleDebug`
Expected: PASS and updated APK.

**Step 4: Commit**
```bash
git add release/codex-mobile-debug.apk README.md
git commit -m "build: refresh mobile client for dynamic account slots"
```
