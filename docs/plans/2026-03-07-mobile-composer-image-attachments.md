# Mobile Chat Composer And Image Attachments Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Improve the Android chat screen so outgoing user messages appear immediately, the composer stays above the keyboard and grows naturally, and a single image can be attached to a resumed Codex turn.

**Architecture:** Keep the transport simple: Android sends one optional image in the existing `/api/sessions/{id}/message` request as base64 JSON, the portal materializes it into a temp file, and the Codex CLI receives it via `codex exec resume -i <file>`. On the client, treat pending user text and streaming assistant text as transient display state layered on top of persisted session history.

**Tech Stack:** Python stdlib HTTP server, Android Java with ViewBinding, Android Photo Picker, local unit tests with `unittest` and JUnit/Robolectric.

---

### Task 1: Lock the expected behavior in tests

**Files:**
- Modify: `tests/test_mobile_portal.py`
- Create: `android-app/app/src/test/java/com/penguinoo/codexmobile/ChatConversationStateTest.java`

**Step 1: Write the failing test**
- Add a portal test proving resume args include `-i <file>` when an image path is supplied.
- Add an Android test proving a pending user message is appended before a streaming assistant bubble.

**Step 2: Run test to verify it fails**
- Run: `python -m unittest D:\codex\manger\tests\test_mobile_portal.py`
- Run: `D:\android-tools\gradle-8.13\bin\gradle.bat -p D:\codex\manger\android-app testDebugUnitTest`

**Step 3: Write minimal implementation**
- Add a helper to build resume args.
- Add a helper to combine persisted messages, local pending user message, and live assistant text.

**Step 4: Run test to verify it passes**
- Re-run both commands above.

### Task 2: Add portal-side image attachment support

**Files:**
- Modify: `mobile_portal.py`
- Test: `tests/test_mobile_portal.py`

**Step 1: Write the failing test**
- Verify a JSON image payload can be decoded to a temp file and cleaned up after the job finishes.

**Step 2: Run test to verify it fails**
- Run: `python -m unittest D:\codex\manger\tests\test_mobile_portal.py`

**Step 3: Write minimal implementation**
- Accept one optional image object on `/api/sessions/{id}/message`.
- Decode base64 into a temp file with the right suffix.
- Pass the temp file to `codex exec resume -i`.
- Always delete the temp file after the job ends.

**Step 4: Run test to verify it passes**
- Re-run the Python unit test command.

### Task 3: Refresh the Android composer UX

**Files:**
- Modify: `android-app/app/src/main/java/com/penguinoo/codexmobile/ChatActivity.java`
- Modify: `android-app/app/src/main/java/com/penguinoo/codexmobile/PortalApiClient.java`
- Modify: `android-app/app/src/main/java/com/penguinoo/codexmobile/ChatMessageAdapter.java`
- Create: `android-app/app/src/main/java/com/penguinoo/codexmobile/ChatConversationState.java`
- Modify: `android-app/app/src/main/res/layout/activity_chat.xml`
- Modify: `android-app/app/src/main/res/layout/item_message_user.xml`
- Modify: `android-app/app/src/main/res/layout/item_message_assistant.xml`
- Modify: `android-app/app/src/main/res/values/strings.xml`
- Modify: `android-app/app/build.gradle.kts`

**Step 1: Write the failing test**
- Add/adjust tests for the transient conversation state helper.

**Step 2: Run test to verify it fails**
- Run: `D:\android-tools\gradle-8.13\bin\gradle.bat -p D:\codex\manger\android-app testDebugUnitTest`

**Step 3: Write minimal implementation**
- Add an attachment button and preview row.
- Use the Android photo picker to select one image.
- Read the selected image into the request payload.
- Echo the outgoing user message immediately.
- Apply IME/window inset padding so the composer sits above the keyboard.
- Keep the input field multi-line with a reasonable max height.

**Step 4: Run test to verify it passes**
- Re-run the Android unit test command.

### Task 4: Rebuild and verify the whole flow

**Files:**
- Output: `release/codex-mobile-debug.apk`

**Step 1: Run verification**
- Run: `python -m py_compile D:\codex\manger\mobile_portal.py D:\codex\manger\app.py`
- Run: `python -m unittest D:\codex\manger\tests\test_mobile_portal.py`
- Run: `D:\android-tools\gradle-8.13\bin\gradle.bat -p D:\codex\manger\android-app testDebugUnitTest`
- Run: `D:\android-tools\gradle-8.13\bin\gradle.bat -p D:\codex\manger\android-app assembleDebug`

**Step 2: Copy the APK**
- Copy `android-app/app/build/outputs/apk/debug/app-debug.apk` to `release/codex-mobile-debug.apk`.

**Step 3: Smoke test locally**
- Confirm the portal still starts.
- Confirm a message request can be queued with and without an image.
- Confirm the APK launches and connects.
