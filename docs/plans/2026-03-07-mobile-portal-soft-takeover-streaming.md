# Mobile Portal Soft Takeover And Streaming Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix mobile chat resume reliability by replacing fragile per-session job locks with owned sessions plus stale-lock recovery, and add live Codex output rendering in the Android chat UI.

**Architecture:** Keep the Python portal as the coordination point for managed session ownership and live job state. Extend the desktop manager to consult the portal before opening managed sessions, and extend the Android client to render richer job payloads with a temporary streaming assistant bubble.

**Tech Stack:** Python 3.11, `ThreadingHTTPServer`, Tkinter desktop manager, Android Java client, JUnit, existing portal test harness under `tests/`.

---

### Task 1: Add failing portal tests for stale locks and live job payloads

**Files:**
- Modify: `tests/test_mobile_portal.py`
- Test: `tests/test_mobile_portal.py`

**Step 1: Write the failing test**

Add coverage for stale lock release:

```python
def test_start_resume_job_releases_stale_lock_when_job_is_gone():
    store = mobile_portal.CodexDataStore()
    runner = mobile_portal.JobRunner(store)
    runner.active_sessions.add("session-1")
    runner.jobs["dead"] = {
        "job_id": "dead",
        "status": "running",
        "session_id": "session-1",
        "heartbeat_at": 0,
        "pid": 999999,
    }

    runner._recover_stale_session("session-1")

    assert "session-1" not in runner.active_sessions
```

Add coverage for live output accumulation:

```python
def test_job_payload_contains_live_text_updates():
    store = mobile_portal.CodexDataStore()
    runner = mobile_portal.JobRunner(store)
    runner.jobs["job-1"] = {
        "job_id": "job-1",
        "status": "running",
        "session_id": "session-1",
        "live_text": "",
        "live_chunks_version": 0,
        "log_tail": [],
    }

    runner._append_live_text("job-1", "hello")

    job = runner.get_job("job-1")
    assert job["live_text"] == "hello"
    assert job["live_chunks_version"] == 1
```

**Step 2: Run test to verify it fails**

Run: `conda run -n codex-accel python -m unittest D:\codex\manger\tests\test_mobile_portal.py`
Expected: FAIL because stale-lock recovery and live-text helpers do not exist yet.

**Step 3: Write minimal implementation**

Add helper methods and richer job fields in `mobile_portal.py` only as needed to satisfy the tests.

**Step 4: Run test to verify it passes**

Run: `conda run -n codex-accel python -m unittest D:\codex\manger\tests\test_mobile_portal.py`
Expected: PASS.

**Step 5: Commit**

```bash
git add tests/test_mobile_portal.py mobile_portal.py
git commit -m "test: cover portal lock recovery and live output"
```

### Task 2: Implement owned managed sessions and stale-lock recovery in the portal

**Files:**
- Modify: `mobile_portal.py`
- Test: `tests/test_mobile_portal.py`

**Step 1: Write the failing test**

Add an ownership conflict test:

```python
def test_start_resume_job_rejects_other_managed_owner():
    store = mobile_portal.CodexDataStore()
    runner = mobile_portal.JobRunner(store)
    runner.register_owner("session-1", "desktop_manager", "Desktop Manager", mode="write")

    with self.assertRaisesRegex(RuntimeError, "Desktop Manager"):
        runner.start_resume_job("session-1", "hello", "default", "default", "default")
```

**Step 2: Run test to verify it fails**

Run: `conda run -n codex-accel python -m unittest D:\codex\manger\tests\test_mobile_portal.py`
Expected: FAIL because ownership registration and conflict messaging do not exist yet.

**Step 3: Write minimal implementation**

In `mobile_portal.py`:
- add managed ownership registry
- add stale-lock recovery based on heartbeat and missing child process
- enrich job state with:
  - `owner_kind`
  - `owner_label`
  - `heartbeat_at`
  - `pid`
  - `live_text`
  - `live_chunks_version`
- add a small ownership endpoint for desktop manager use
- add a recovery endpoint for explicit stuck-lock release

**Step 4: Run test to verify it passes**

Run: `conda run -n codex-accel python -m unittest D:\codex\manger\tests\test_mobile_portal.py`
Expected: PASS.

**Step 5: Commit**

```bash
git add mobile_portal.py tests/test_mobile_portal.py
git commit -m "feat: add managed session ownership to portal"
```

### Task 3: Capture and expose live output from running Codex jobs

**Files:**
- Modify: `mobile_portal.py`
- Test: `tests/test_mobile_portal.py`

**Step 1: Write the failing test**

Add a parser-focused test:

```python
def test_run_event_updates_last_message_and_live_text():
    job = {"job_id": "job-1", "status": "running", "live_text": "", "live_chunks_version": 0, "last_message": ""}
    runner.jobs["job-1"] = job

    runner._handle_codex_event("job-1", {"type": "item.completed", "item": {"type": "agent_message", "text": "partial"}})

    assert runner.jobs["job-1"]["live_text"] == "partial"
    assert runner.jobs["job-1"]["last_message"] == "partial"
```

**Step 2: Run test to verify it fails**

Run: `conda run -n codex-accel python -m unittest D:\codex\manger\tests\test_mobile_portal.py`
Expected: FAIL because event handling is still inline and does not expose live text cleanly.

**Step 3: Write minimal implementation**

Refactor process-event parsing into helper methods so job polling returns live incremental content without waiting for process completion.

**Step 4: Run test to verify it passes**

Run: `conda run -n codex-accel python -m unittest D:\codex\manger\tests\test_mobile_portal.py`
Expected: PASS.

**Step 5: Commit**

```bash
git add mobile_portal.py tests/test_mobile_portal.py
git commit -m "feat: stream live codex output from portal jobs"
```

### Task 4: Make the desktop manager respect managed session ownership

**Files:**
- Modify: `app.py`
- Test: manual verification plus any small helper test if practical

**Step 1: Write the failing test**

If adding a unit-testable helper in `app.py`, cover the launch decision:

```python
def test_launch_mode_becomes_read_only_when_mobile_owns_session():
    payload = {"ok": False, "owner_label": "Mobile", "mode": "write"}
    assert choose_launch_mode(payload) == "read_only"
```

**Step 2: Run test to verify it fails**

Run the targeted helper test if created, or note that this task remains manual-only because `app.py` is Tkinter-heavy.
Expected: FAIL or missing helper.

**Step 3: Write minimal implementation**

In `app.py`:
- call the portal ownership endpoint before launching a managed session
- if mobile owns the session, do not open a writable terminal
- show a clear status string and keep the existing “Open File/Open Folder” behavior intact
- for now, “soft takeover” means refuse writable launch rather than killing a window

**Step 4: Run test to verify it passes**

Manual check:
- start portal
- mark a session as mobile-owned
- attempt desktop manager open
- confirm the manager reports mobile ownership and does not start writable resume

**Step 5: Commit**

```bash
git add app.py
git commit -m "feat: enforce portal session ownership in desktop manager"
```

### Task 5: Extend Android job models and client parsing for live updates

**Files:**
- Modify: `android-app/app/src/main/java/com/penguinoo/codexmobile/PortalJob.java`
- Modify: `android-app/app/src/main/java/com/penguinoo/codexmobile/PortalApiClient.java`
- Create: `android-app/app/src/test/java/com/penguinoo/codexmobile/PortalJobParsingTest.java`

**Step 1: Write the failing test**

```java
@Test
public void fetchJob_parsesLiveTextAndOwnerLabel() throws Exception {
    JSONObject json = new JSONObject()
            .put("job_id", "job-1")
            .put("status", "running")
            .put("session_id", "session-1")
            .put("live_text", "thinking...")
            .put("live_chunks_version", 3)
            .put("owner_label", "Mobile");

    PortalJob job = PortalApiClient.parseJob(json);

    assertEquals("thinking...", job.liveText);
    assertEquals(3, job.liveChunksVersion);
    assertEquals("Mobile", job.ownerLabel);
}
```

**Step 2: Run test to verify it fails**

Run: `D:\android-tools\gradle-8.13\bin\gradle.bat -p D:\codex\manger\android-app testDebugUnitTest --tests com.penguinoo.codexmobile.PortalJobParsingTest`
Expected: FAIL because `PortalJob` and parsing do not yet expose the richer fields.

**Step 3: Write minimal implementation**

Add the new fields and parsing logic only:
- `liveText`
- `liveChunksVersion`
- `ownerKind`
- `ownerLabel`

**Step 4: Run test to verify it passes**

Run: `D:\android-tools\gradle-8.13\bin\gradle.bat -p D:\codex\manger\android-app testDebugUnitTest --tests com.penguinoo.codexmobile.PortalJobParsingTest`
Expected: PASS.

**Step 5: Commit**

```bash
git add android-app/app/src/main/java/com/penguinoo/codexmobile/PortalJob.java android-app/app/src/main/java/com/penguinoo/codexmobile/PortalApiClient.java android-app/app/src/test/java/com/penguinoo/codexmobile/PortalJobParsingTest.java
git commit -m "test: parse richer portal job payloads on Android"
```

### Task 6: Render live streaming output and takeover state in Android chat

**Files:**
- Modify: `android-app/app/src/main/java/com/penguinoo/codexmobile/ChatActivity.java`
- Modify: `android-app/app/src/main/java/com/penguinoo/codexmobile/ChatMessageAdapter.java`
- Modify: `android-app/app/src/main/java/com/penguinoo/codexmobile/ChatMessage.java`
- Modify: `android-app/app/src/main/res/layout/activity_chat.xml`
- Modify: `android-app/app/src/test/java/com/penguinoo/codexmobile/ChatHeaderModelTest.java`

**Step 1: Write the failing test**

Add a small state reducer helper test:

```java
@Test
public void streamingPreview_replacesTemporaryAssistantBubble() {
    List<ChatMessage> messages = new ArrayList<>();

    messages = ChatStreamingState.applyLiveText(messages, "partial");

    assertEquals("partial", messages.get(messages.size() - 1).text);
    assertTrue(messages.get(messages.size() - 1).isEphemeral);
}
```

**Step 2: Run test to verify it fails**

Run: `D:\android-tools\gradle-8.13\bin\gradle.bat -p D:\codex\manger\android-app testDebugUnitTest --tests com.penguinoo.codexmobile.ChatHeaderModelTest`
Expected: FAIL because the temporary streaming message helper does not exist yet.

**Step 3: Write minimal implementation**

In the Android client:
- poll running jobs more frequently
- update a temporary assistant message with `job.liveText`
- remove the temporary message and reload the full session once the job completes
- show friendly ownership conflict text when another managed owner holds the session

**Step 4: Run test to verify it passes**

Run: `D:\android-tools\gradle-8.13\bin\gradle.bat -p D:\codex\manger\android-app testDebugUnitTest`
Expected: PASS.

**Step 5: Commit**

```bash
git add android-app/app/src/main/java/com/penguinoo/codexmobile/ChatActivity.java android-app/app/src/main/java/com/penguinoo/codexmobile/ChatMessageAdapter.java android-app/app/src/main/java/com/penguinoo/codexmobile/ChatMessage.java android-app/app/src/main/res/layout/activity_chat.xml
git commit -m "feat: show live portal streaming in Android chat"
```

### Task 7: Verify the full repro path locally

**Files:**
- Modify: `README.md` if behavior or testing notes need updates

**Step 1: Run Python tests**

Run: `conda run -n codex-accel python -m unittest D:\codex\manger\tests\test_mobile_portal.py`
Expected: PASS.

**Step 2: Run Android unit tests**

Run: `D:\android-tools\gradle-8.13\bin\gradle.bat -p D:\codex\manger\android-app testDebugUnitTest`
Expected: PASS.

**Step 3: Build the APK**

Run: `D:\android-tools\gradle-8.13\bin\gradle.bat -p D:\codex\manger\android-app assembleDebug`
Expected: `BUILD SUCCESSFUL`.

**Step 4: Manual repro verification**

Run the portal and verify:
- the old failing test session can send a second message
- the session no longer gets stuck in fake `running` state
- live assistant text appears on the phone while the job runs
- a mobile-owned session is blocked from writable desktop-manager launch
- a different session still runs independently

**Step 5: Commit**

```bash
git add README.md
git commit -m "docs: document managed mobile streaming behavior"
```
