# Mobile Global Proxy Settings Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add mobile-managed global proxy settings for `mobile_portal.py` with enable/disable and port control.

**Architecture:** Persist a tiny JSON settings file on the computer, expose it via portal APIs, and let the Android home screen read/write it. `mobile_portal.py` will keep using the existing fixed `socks5h://127.0.0.1:<port>` shape so the UI only edits the state that actually matters.

**Tech Stack:** Python, JSON file storage, Android Java, unittest, Gradle unit tests.

---

### Task 1: Add backend settings storage and validation

**Files:**
- Modify: `mobile_portal.py`
- Test: `tests/test_mobile_portal.py`

**Step 1: Write failing tests**
- Add tests for default settings when file is missing.
- Add tests for saving valid settings.
- Add tests for rejecting invalid ports.

**Step 2: Run test to verify it fails**
Run: `conda run -n codex-accel python -m unittest D:\codex\manger\tests\test_mobile_portal.py`
Expected: FAIL for missing proxy settings helpers.

**Step 3: Write minimal implementation**
- Add settings file helpers.
- Add fixed proxy summary builder.
- Use saved settings when building child-process proxy env.

**Step 4: Run test to verify it passes**
Run: `conda run -n codex-accel python -m unittest D:\codex\manger\tests\test_mobile_portal.py`
Expected: PASS.

**Step 5: Commit**
```bash
git add mobile_portal.py tests/test_mobile_portal.py
git commit -m "feat: add portal proxy settings storage"
```

### Task 2: Expose proxy settings APIs to Android

**Files:**
- Modify: `mobile_portal.py`
- Modify: `android-app/app/src/main/java/com/penguinoo/codexmobile/PortalApiClient.java`
- Test: `android-app/app/src/test/java/com/penguinoo/codexmobile/PortalProxySettingsParsingTest.java`

**Step 1: Write failing tests**
- Add Android-side parsing/build tests for proxy settings payload.

**Step 2: Run test to verify it fails**
Run: `D:\android-tools\gradle-8.13\bin\gradle.bat -p D:\codex\manger\android-app testDebugUnitTest`
Expected: FAIL for missing proxy settings payload/model.

**Step 3: Write minimal implementation**
- Add GET/POST proxy settings endpoints.
- Add Android API client methods and payload model.

**Step 4: Run test to verify it passes**
Run: `D:\android-tools\gradle-8.13\bin\gradle.bat -p D:\codex\manger\android-app testDebugUnitTest`
Expected: PASS.

**Step 5: Commit**
```bash
git add mobile_portal.py android-app/app/src/main/java/com/penguinoo/codexmobile/PortalApiClient.java android-app/app/src/test/java/com/penguinoo/codexmobile/PortalProxySettingsParsingTest.java
git commit -m "feat: add portal proxy settings api"
```

### Task 3: Add Android home-screen proxy settings dialog

**Files:**
- Modify: `android-app/app/src/main/java/com/penguinoo/codexmobile/MainActivity.java`
- Modify: `android-app/app/src/main/res/values/strings.xml`
- Create: `android-app/app/src/main/java/com/penguinoo/codexmobile/PortalProxySettings.java`

**Step 1: Write failing test**
- Add payload/state test for proxy settings model.

**Step 2: Run test to verify it fails**
Run: `D:\android-tools\gradle-8.13\bin\gradle.bat -p D:\codex\manger\android-app testDebugUnitTest`
Expected: FAIL for missing model/dialog wiring.

**Step 3: Write minimal implementation**
- Add `Proxy settings` menu action.
- Load current settings from portal.
- Save enable/port back to portal.

**Step 4: Run test to verify it passes**
Run: `D:\android-tools\gradle-8.13\bin\gradle.bat -p D:\codex\manger\android-app testDebugUnitTest`
Expected: PASS.

**Step 5: Commit**
```bash
git add android-app/app/src/main/java/com/penguinoo/codexmobile/MainActivity.java android-app/app/src/main/java/com/penguinoo/codexmobile/PortalProxySettings.java android-app/app/src/main/res/values/strings.xml
git commit -m "feat: add mobile proxy settings dialog"
```

### Task 4: Final verification and APK rebuild

**Files:**
- Modify: `release/codex-mobile-debug.apk`

**Step 1: Run Python verification**
Run: `conda run -n codex-accel python -m unittest D:\codex\manger\tests\test_mobile_portal.py`
Expected: PASS.

**Step 2: Run compile verification**
Run: `conda run -n codex-accel python -m py_compile D:\codex\manger\mobile_portal.py`
Expected: PASS.

**Step 3: Run Android verification and rebuild**
Run: `D:\android-tools\gradle-8.13\bin\gradle.bat -p D:\codex\manger\android-app testDebugUnitTest assembleDebug`
Expected: PASS.

**Step 4: Commit**
```bash
git add release/codex-mobile-debug.apk
git commit -m "build: refresh mobile apk for proxy settings"
```
