# Chat Draft Persistence Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Persist unsent text and selected image per session in the Android chat screen and restore them when re-entering the session.

**Architecture:** Add a lightweight `SharedPreferences` store keyed by `session_id`. `ChatActivity` writes draft state on text/image changes, restores it on load, and clears it only after send succeeds.

**Tech Stack:** Android Java, SharedPreferences, Activity Result API, Robolectric, JUnit 4

---

### Task 1: Add draft store tests and implementation

**Files:**
- Create: `android-app/app/src/main/java/com/penguinoo/codexmobile/ChatDraftStore.java`
- Test: `android-app/app/src/test/java/com/penguinoo/codexmobile/ChatDraftStoreTest.java`

**Step 1: Write the failing test**
- Verify save/load returns text + image metadata for a session.
- Verify clear removes saved draft.

**Step 2: Run test to verify it fails**
Run: `gradle -p D:\codex\manger\android-app testDebugUnitTest --tests com.penguinoo.codexmobile.ChatDraftStoreTest`
Expected: FAIL because `ChatDraftStore` does not exist yet.

**Step 3: Write minimal implementation**
- Add `ChatDraftStore` with `saveDraft`, `loadDraft`, and `clearDraft`.

**Step 4: Run test to verify it passes**
Run same command.
Expected: PASS.

### Task 2: Wire draft persistence into chat lifecycle

**Files:**
- Modify: `android-app/app/src/main/java/com/penguinoo/codexmobile/ChatActivity.java`

**Step 1: Write the failing test / add coverage where practical**
- Add or extend tests for draft restore state if it can be covered with helper logic.

**Step 2: Implement minimal code**
- Restore draft text on open.
- Switch image picker to persistable document access.
- Restore saved image `Uri` and rehydrate attachment.
- Save draft on text change, image select, and image clear.
- Clear draft only after send request succeeds.
- On send failure, keep/restores the draft.

**Step 3: Verify**
Run: `gradle -p D:\codex\manger\android-app testDebugUnitTest`
Expected: PASS.

### Task 3: Final verification

**Files:**
- Verify only

**Step 1: Build APK**
Run: `gradle -p D:\codex\manger\android-app assembleDebug`
Expected: BUILD SUCCESSFUL.

**Step 2: Smoke check behavior manually**
- Type text, leave chat, re-enter: draft restored.
- Select image, leave chat, re-enter: image restored.
- Send successfully: draft cleared.
- Send fails: draft remains.
