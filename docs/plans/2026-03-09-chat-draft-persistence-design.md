# Chat Draft Persistence Design

**Goal:** Persist unsent chat text and selected image per session so leaving and re-entering a chat restores the draft and lets the user send it.

**Scope:** Android mobile client only. Persist by `session_id`. Restore on chat open. Clear on successful send. Keep draft on failed send. Preserve selected image via persisted document `Uri` when available.

**Approach:** Add a small `SharedPreferences`-backed `ChatDraftStore` next to the existing `PortalConfigStore`. `ChatActivity` will save text changes and selected image metadata per session, restore them during activity startup, and clear the saved draft only after the backend accepts the send request. For image persistence, switch picker usage to a persistable document flow and rehydrate the attachment from the saved `Uri` on re-entry.

**Files:**
- Add `android-app/app/src/main/java/com/penguinoo/codexmobile/ChatDraftStore.java`
- Add `android-app/app/src/test/java/com/penguinoo/codexmobile/ChatDraftStoreTest.java`
- Modify `android-app/app/src/main/java/com/penguinoo/codexmobile/ChatActivity.java`
- Optionally modify `android-app/app/src/main/res/values/strings.xml` if a restore banner is needed
