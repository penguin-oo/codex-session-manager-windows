# Android Mobile IM Client Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Turn the current Android prototype into a polished IM-style mobile client for the local Codex portal, with a home hub, full chat list, guided new-chat flow, and a chat screen that behaves like a mature messaging app.

**Architecture:** Keep the Python portal as the execution backend and evolve the Android app into a native client. Reuse the existing transport/data models where possible, add a few small presentation helpers for testability, and move configuration-heavy controls out of the chat screen into the new-chat flow.

**Tech Stack:** Java 17, Android SDK 36, AppCompat, RecyclerView, view binding, Robolectric/JUnit for JVM-side tests.

---

### Task 1: Add Android test support and shared presentation helpers

**Files:**
- Modify: `android-app/app/build.gradle.kts`
- Create: `android-app/app/src/main/java/com/penguinoo/codexmobile/SessionCollections.java`
- Create: `android-app/app/src/test/java/com/penguinoo/codexmobile/SessionCollectionsTest.java`
- Create: `android-app/app/src/test/java/com/penguinoo/codexmobile/PortalEndpointTest.java`

**Step 1: Write the failing tests**

```java
@Test
public void recentChats_returnsNewestSessionsFirst_andCapsList() {
    List<SessionSummary> sessions = Arrays.asList(
            new SessionSummary("a", 10L, "Older", "", "", "", "", ""),
            new SessionSummary("b", 50L, "Newest", "", "", "", "", ""),
            new SessionSummary("c", 30L, "Middle", "", "", "", "", "")
    );

    List<SessionSummary> recent = SessionCollections.recentChats(sessions, 2);

    assertEquals(Arrays.asList("b", "c"), idsOf(recent));
}
```

```java
@Test
public void parse_rejectsPortalUrlWithoutToken() {
    PortalEndpoint.parse("http://192.168.1.8:8765/");
}
```

**Step 2: Run test to verify it fails**

Run: `gradle -p android-app testDebugUnitTest --tests com.penguinoo.codexmobile.SessionCollectionsTest --tests com.penguinoo.codexmobile.PortalEndpointTest`
Expected: FAIL because `SessionCollections` does not exist yet and the portal parsing assertion is incomplete.

**Step 3: Write minimal implementation**

```java
public final class SessionCollections {
    public static List<SessionSummary> recentChats(List<SessionSummary> sessions, int limit) {
        List<SessionSummary> copy = new ArrayList<>(sessions);
        copy.sort((left, right) -> Long.compare(right.timestamp, left.timestamp));
        return copy.subList(0, Math.min(limit, copy.size()));
    }
}
```

Add test dependencies to `android-app/app/build.gradle.kts`:

```kotlin
testImplementation("junit:junit:4.13.2")
testImplementation("org.robolectric:robolectric:4.14.1")
testImplementation("androidx.test:core:1.6.1")
```

**Step 4: Run test to verify it passes**

Run: `gradle -p android-app testDebugUnitTest --tests com.penguinoo.codexmobile.SessionCollectionsTest --tests com.penguinoo.codexmobile.PortalEndpointTest`
Expected: PASS.

**Step 5: Commit**

```bash
git add android-app/app/build.gradle.kts android-app/app/src/main/java/com/penguinoo/codexmobile/SessionCollections.java android-app/app/src/test/java/com/penguinoo/codexmobile/SessionCollectionsTest.java android-app/app/src/test/java/com/penguinoo/codexmobile/PortalEndpointTest.java
git commit -m "test: add Android presentation helper coverage"
```

### Task 2: Rebuild the home screen as a lightweight launcher hub

**Files:**
- Modify: `android-app/app/src/main/java/com/penguinoo/codexmobile/MainActivity.java`
- Modify: `android-app/app/src/main/res/layout/activity_main.xml`
- Modify: `android-app/app/src/main/res/values/strings.xml`
- Modify: `android-app/app/src/main/res/values/colors.xml`
- Modify: `android-app/app/src/main/res/drawable/bg_card.xml`
- Create: `android-app/app/src/main/res/drawable/bg_home_action.xml`
- Create: `android-app/app/src/main/res/layout/item_recent_session.xml`
- Create: `android-app/app/src/main/java/com/penguinoo/codexmobile/RecentSessionAdapter.java`
- Test: `android-app/app/src/test/java/com/penguinoo/codexmobile/SessionCollectionsTest.java`

**Step 1: Write the failing test**

Extend `SessionCollectionsTest` with home-focused expectations:

```java
@Test
public void recentChats_usesSessionTitleFallbackWhenTextMissing() {
    SessionSummary session = new SessionSummary("abc123", 99L, "", "", "D:/repo", "", "", "");

    String title = SessionCollections.displayTitle(session);

    assertEquals("abc123", title);
}
```

**Step 2: Run test to verify it fails**

Run: `gradle -p android-app testDebugUnitTest --tests com.penguinoo.codexmobile.SessionCollectionsTest`
Expected: FAIL because `displayTitle` does not exist yet.

**Step 3: Write minimal implementation**

Add the helper:

```java
public static String displayTitle(SessionSummary session) {
    return session.text == null || session.text.isEmpty() ? session.sessionId : session.text;
}
```

Then redesign `MainActivity` and `activity_main.xml` to show:
- connection status card
- recent chats strip/list
- `Recent Chats`, `All Chats`, `New Chat` action cards
- settings entry instead of a heavy always-open form

**Step 4: Run test to verify it passes**

Run: `gradle -p android-app testDebugUnitTest --tests com.penguinoo.codexmobile.SessionCollectionsTest`
Expected: PASS.

Manual check:
- launch app
- verify no configured portal shows onboarding card
- verify configured portal lands on launcher-style home screen instead of full list

**Step 5: Commit**

```bash
git add android-app/app/src/main/java/com/penguinoo/codexmobile/MainActivity.java android-app/app/src/main/res/layout/activity_main.xml android-app/app/src/main/res/values/strings.xml android-app/app/src/main/res/values/colors.xml android-app/app/src/main/res/drawable/bg_card.xml android-app/app/src/main/res/drawable/bg_home_action.xml android-app/app/src/main/res/layout/item_recent_session.xml android-app/app/src/main/java/com/penguinoo/codexmobile/RecentSessionAdapter.java android-app/app/src/main/java/com/penguinoo/codexmobile/SessionCollections.java android-app/app/src/test/java/com/penguinoo/codexmobile/SessionCollectionsTest.java
git commit -m "feat: redesign Android home hub"
```

### Task 3: Add a dedicated All Chats screen with richer session rows

**Files:**
- Create: `android-app/app/src/main/java/com/penguinoo/codexmobile/AllChatsActivity.java`
- Create: `android-app/app/src/main/res/layout/activity_all_chats.xml`
- Modify: `android-app/app/src/main/java/com/penguinoo/codexmobile/SessionListAdapter.java`
- Modify: `android-app/app/src/main/res/layout/item_session.xml`
- Modify: `android-app/app/src/main/AndroidManifest.xml`
- Create: `android-app/app/src/test/java/com/penguinoo/codexmobile/SessionRowModelTest.java`

**Step 1: Write the failing test**

```java
@Test
public void subtitle_prefersNotePreview_overWorkingDirectory() {
    SessionSummary session = new SessionSummary("id", 1L, "Chat", "Pinned idea", "D:/repo", "gpt-5", "", "");

    assertEquals("Pinned idea", SessionCollections.primarySubtitle(session));
}
```

**Step 2: Run test to verify it fails**

Run: `gradle -p android-app testDebugUnitTest --tests com.penguinoo.codexmobile.SessionRowModelTest`
Expected: FAIL because the subtitle helper does not exist yet.

**Step 3: Write minimal implementation**

Add row helpers in `SessionCollections`:

```java
public static String primarySubtitle(SessionSummary session) {
    if (session.note != null && !session.note.isEmpty()) {
        return session.note;
    }
    return session.cwd == null ? "" : session.cwd;
}
```

Then implement `AllChatsActivity` and update `SessionListAdapter` so rows show:
- title
- last-message/note-or-cwd summary
- time
- compact metadata

Also add long-press or overflow wiring for note/delete actions.

**Step 4: Run test to verify it passes**

Run: `gradle -p android-app testDebugUnitTest --tests com.penguinoo.codexmobile.SessionRowModelTest`
Expected: PASS.

Manual check:
- from home, open `All Chats`
- confirm rows scan cleanly on phone width
- confirm tapping a row opens the chat directly

**Step 5: Commit**

```bash
git add android-app/app/src/main/java/com/penguinoo/codexmobile/AllChatsActivity.java android-app/app/src/main/res/layout/activity_all_chats.xml android-app/app/src/main/java/com/penguinoo/codexmobile/SessionListAdapter.java android-app/app/src/main/res/layout/item_session.xml android-app/app/src/main/AndroidManifest.xml android-app/app/src/test/java/com/penguinoo/codexmobile/SessionRowModelTest.java android-app/app/src/main/java/com/penguinoo/codexmobile/SessionCollections.java
git commit -m "feat: add Android all chats screen"
```

### Task 4: Add the new chat flow with one-time launch options

**Files:**
- Create: `android-app/app/src/main/java/com/penguinoo/codexmobile/NewChatActivity.java`
- Create: `android-app/app/src/main/java/com/penguinoo/codexmobile/DirectoryEntry.java`
- Create: `android-app/app/src/main/java/com/penguinoo/codexmobile/DirectoryListing.java`
- Create: `android-app/app/src/main/java/com/penguinoo/codexmobile/DirectoryAdapter.java`
- Create: `android-app/app/src/main/res/layout/activity_new_chat.xml`
- Create: `android-app/app/src/main/res/layout/item_directory.xml`
- Modify: `android-app/app/src/main/java/com/penguinoo/codexmobile/PortalApiClient.java`
- Modify: `android-app/app/src/main/java/com/penguinoo/codexmobile/MainActivity.java`
- Modify: `android-app/app/src/main/AndroidManifest.xml`
- Create: `android-app/app/src/test/java/com/penguinoo/codexmobile/NewChatFormStateTest.java`

**Step 1: Write the failing test**

```java
@Test
public void isReady_requiresCwdAndPrompt() {
    assertFalse(NewChatFormState.isReady("", "hello"));
    assertFalse(NewChatFormState.isReady("D:/repo", ""));
    assertTrue(NewChatFormState.isReady("D:/repo", "hello"));
}
```

**Step 2: Run test to verify it fails**

Run: `gradle -p android-app testDebugUnitTest --tests com.penguinoo.codexmobile.NewChatFormStateTest`
Expected: FAIL because `NewChatFormState` does not exist yet.

**Step 3: Write minimal implementation**

Add a small readiness helper:

```java
public final class NewChatFormState {
    public static boolean isReady(String cwd, String prompt) {
        return cwd != null && !cwd.isBlank() && prompt != null && !prompt.isBlank();
    }
}
```

Then extend `PortalApiClient` with:
- `listDirectory(...)` for `/api/fs`
- `createChat(...)` for `/api/chats`

Build `NewChatActivity` so the user can:
- browse or enter a working directory
- type the opening prompt
- choose model, approval, sandbox once
- create the session
- transition straight to `ChatActivity`

**Step 4: Run test to verify it passes**

Run: `gradle -p android-app testDebugUnitTest --tests com.penguinoo.codexmobile.NewChatFormStateTest`
Expected: PASS.

Manual check:
- from home, tap `New Chat`
- choose a folder and launch options
- create chat successfully
- confirm the app opens the newly created conversation immediately

**Step 5: Commit**

```bash
git add android-app/app/src/main/java/com/penguinoo/codexmobile/NewChatActivity.java android-app/app/src/main/java/com/penguinoo/codexmobile/DirectoryEntry.java android-app/app/src/main/java/com/penguinoo/codexmobile/DirectoryListing.java android-app/app/src/main/java/com/penguinoo/codexmobile/DirectoryAdapter.java android-app/app/src/main/res/layout/activity_new_chat.xml android-app/app/src/main/res/layout/item_directory.xml android-app/app/src/main/java/com/penguinoo/codexmobile/PortalApiClient.java android-app/app/src/main/java/com/penguinoo/codexmobile/MainActivity.java android-app/app/src/main/AndroidManifest.xml android-app/app/src/test/java/com/penguinoo/codexmobile/NewChatFormStateTest.java
git commit -m "feat: add Android new chat flow"
```

### Task 5: Simplify the chat screen into a real IM view

**Files:**
- Modify: `android-app/app/src/main/java/com/penguinoo/codexmobile/ChatActivity.java`
- Modify: `android-app/app/src/main/res/layout/activity_chat.xml`
- Modify: `android-app/app/src/main/res/layout/item_message_user.xml`
- Modify: `android-app/app/src/main/res/layout/item_message_assistant.xml`
- Modify: `android-app/app/src/main/res/drawable/bg_user_bubble.xml`
- Modify: `android-app/app/src/main/res/drawable/bg_assistant_bubble.xml`
- Modify: `android-app/app/src/main/res/menu/menu_chat.xml`
- Create: `android-app/app/src/test/java/com/penguinoo/codexmobile/ChatHeaderModelTest.java`

**Step 1: Write the failing test**

```java
@Test
public void metadataLine_prefersNoteSummary_thenWorkingDirectory() {
    SessionSummary withNote = new SessionSummary("id", 1L, "Chat", "Remember this", "D:/repo", "gpt-5", "never", "workspace-write");
    SessionSummary withoutNote = new SessionSummary("id", 1L, "Chat", "", "D:/repo", "gpt-5", "never", "workspace-write");

    assertEquals("Remember this", ChatHeaderModel.metadataLine(withNote));
    assertEquals("D:/repo", ChatHeaderModel.metadataLine(withoutNote));
}
```

**Step 2: Run test to verify it fails**

Run: `gradle -p android-app testDebugUnitTest --tests com.penguinoo.codexmobile.ChatHeaderModelTest`
Expected: FAIL because `ChatHeaderModel` does not exist yet.

**Step 3: Write minimal implementation**

```java
public final class ChatHeaderModel {
    public static String metadataLine(SessionSummary session) {
        if (session.note != null && !session.note.isEmpty()) {
            return session.note;
        }
        return session.cwd == null ? "" : session.cwd;
    }
}
```

Then remove the editable spinners from `ChatActivity` and `activity_chat.xml`. The chat screen should keep:
- title and metadata only
- message list
- bottom composer
- overflow menu for refresh, note, delete

When sending a message, continue to pass the locked session values already attached to the session summary instead of exposing editable controls.

**Step 4: Run test to verify it passes**

Run: `gradle -p android-app testDebugUnitTest --tests com.penguinoo.codexmobile.ChatHeaderModelTest`
Expected: PASS.

Manual check:
- open any existing chat
- confirm no editable model/approval/sandbox controls exist
- confirm newest message is visible on entry and after sending
- confirm scrolling upward reveals earlier messages naturally

**Step 5: Commit**

```bash
git add android-app/app/src/main/java/com/penguinoo/codexmobile/ChatActivity.java android-app/app/src/main/res/layout/activity_chat.xml android-app/app/src/main/res/layout/item_message_user.xml android-app/app/src/main/res/layout/item_message_assistant.xml android-app/app/src/main/res/drawable/bg_user_bubble.xml android-app/app/src/main/res/drawable/bg_assistant_bubble.xml android-app/app/src/main/res/menu/menu_chat.xml android-app/app/src/test/java/com/penguinoo/codexmobile/ChatHeaderModelTest.java android-app/app/src/main/java/com/penguinoo/codexmobile/ChatHeaderModel.java
git commit -m "feat: simplify Android chat screen"
```

### Task 6: Tighten connection, loading, and failure states; then verify the build

**Files:**
- Modify: `android-app/app/src/main/java/com/penguinoo/codexmobile/MainActivity.java`
- Modify: `android-app/app/src/main/java/com/penguinoo/codexmobile/AllChatsActivity.java`
- Modify: `android-app/app/src/main/java/com/penguinoo/codexmobile/NewChatActivity.java`
- Modify: `android-app/app/src/main/java/com/penguinoo/codexmobile/ChatActivity.java`
- Modify: `android-app/app/src/main/res/values/strings.xml`
- Modify: `README.md`

**Step 1: Write the failing test**

Add one last focused state test, for example in `ChatHeaderModelTest` or a new `ConnectionStateTest`:

```java
@Test
public void connectionMessage_prefersFriendlyText_forPortalFailures() {
    assertEquals("Unable to reach your Codex portal.", ConnectionStateModel.userFacingMessage(new IOException("Connection refused")));
}
```

**Step 2: Run test to verify it fails**

Run: `gradle -p android-app testDebugUnitTest --tests com.penguinoo.codexmobile.ConnectionStateTest`
Expected: FAIL because `ConnectionStateModel` does not exist yet.

**Step 3: Write minimal implementation**

```java
public final class ConnectionStateModel {
    public static String userFacingMessage(Exception exception) {
        return "Unable to reach your Codex portal.";
    }
}
```

Then unify banners/loading strings across the app so that:
- connection failures are short and human-readable
- job errors are concise
- loading states are brief and not injected into the transcript

Finally, update `README.md` with the Android app flow and build/run steps.

**Step 4: Run test to verify it passes**

Run: `gradle -p android-app testDebugUnitTest`
Expected: PASS.

Run: `gradle -p android-app assembleDebug`
Expected: BUILD SUCCESSFUL and a debug APK under `android-app/app/build/outputs/apk/debug/`.

Manual check:
- connect from the phone
- open home
- open all chats
- open a chat and send a message
- create a new chat and confirm the session parameters stay locked afterward

**Step 5: Commit**

```bash
git add android-app/app/src/main/java/com/penguinoo/codexmobile/MainActivity.java android-app/app/src/main/java/com/penguinoo/codexmobile/AllChatsActivity.java android-app/app/src/main/java/com/penguinoo/codexmobile/NewChatActivity.java android-app/app/src/main/java/com/penguinoo/codexmobile/ChatActivity.java android-app/app/src/main/res/values/strings.xml README.md
git commit -m "feat: polish Android mobile chat client"
```
