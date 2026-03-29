# Mobile Portal Soft Takeover And Streaming Design

**Date:** 2026-03-07  
**Status:** Approved  
**Scope:** Fix mobile chat execution reliability, add manager-scoped soft takeover, and show live Codex output in the Android client.

## Goal

Turn the current phone flow from "submit job, wait, refresh" into a usable chat control path:
- the mobile client can open a session and continue it reliably
- stale session locks no longer block later messages
- the Android chat screen can show live Codex output while a job is running
- the desktop manager and mobile portal coordinate ownership for sessions they launch

## Problem Summary

The current implementation has two separate gaps:

1. **Job ownership is too coarse**
   `mobile_portal.py` tracks `active_sessions` only in memory, without heartbeats, owner metadata, or recovery. If a mobile job hangs or the process state gets out of sync, the session remains blocked and later sends fail with `A job is already running for this session.`

2. **Chat output is not live**
   The Android app sends a message, polls the job until completion, and only reloads the full session after the job ends. This feels unlike a chat client and makes debugging invisible when Codex is actually working.

## Non-Goals

- Full machine-wide takeover of arbitrary hand-opened Codex terminals
- Killing unknown local Codex processes by PID guessing
- WebSocket migration in this iteration
- Editing session model, approval, or sandbox after a session already exists

## Product Rules

1. **Soft takeover is manager scoped**
   Only sessions started by the desktop manager or the mobile portal participate in coordinated ownership. Manual terminals outside the manager stay out of scope for now.

2. **One writer per managed session**
   A managed session may have multiple viewers, but only one active writer. If mobile owns the session, the desktop manager must not launch a writable terminal for that same session.

3. **Different sessions remain independent**
   Session A and Session B can still run in parallel. Ownership is keyed by `session_id`, not global process state.

4. **Live output before final transcript**
   The Android chat screen should show live progress and text fragments from the active job before the final assistant message lands in session history.

## Architecture

### Ownership model

Add a lightweight session ownership registry inside `mobile_portal.py`:
- `session_id`
- `owner_kind` such as `mobile` or `desktop_manager`
- `owner_label` for display
- `job_id`
- `started_at`
- `heartbeat_at`
- `mode` such as `write` or `view`

The registry remains in process memory for the first version. It is enough for manager-scoped takeover because both the Android app and desktop manager already depend on the same local portal backend.

### Desktop manager integration

The desktop manager should stop launching `codex resume` directly. Instead it should:
- call the local portal for a "desktop launch" reservation
- receive a go/no-go result plus a generated launch token or ownership result
- if mobile already owns the session in write mode, open the terminal as read-only metadata view or refuse writable launch with a clear message

This keeps ownership decisions in one place instead of duplicating them in `app.py`.

### Live output transport

Use incremental HTTP polling for the first version instead of WebSockets:
- extend `/api/jobs/{id}` to return:
  - `status`
  - `session_id`
  - `error`
  - `last_message`
  - `log_tail`
  - `live_text`
  - `live_chunks_version`
  - `owner`
- the Android app polls more frequently while a job is active
- each poll updates a temporary streaming bubble in the chat UI

This is not as elegant as server push, but it is much simpler, works with the current architecture, and still produces the UX the user asked for.

## Data Flow

### Mobile message send

1. Android opens a session
2. Android requests write ownership for that session
3. Portal grants mobile ownership if the session is free or already owned by the same mobile client
4. Android submits the prompt
5. Portal starts `codex exec resume ... --json`
6. Portal captures:
   - structured JSON events
   - live text from `item.completed`
   - log tail for diagnostics
   - heartbeat updates while the process is alive
7. Android polls the job endpoint and updates a live bubble
8. When completed, Android reloads the session payload and replaces the temporary live bubble with the persisted final message

### Stale lock recovery

Session locks should be released if:
- the tracked job exits
- the job fails
- the portal notices no heartbeat for a configured timeout and no child process remains attached

Expose a narrow administrative endpoint to release a stuck session lock explicitly for debugging and recovery.

## Android UX

### Chat page

When a message is sent:
- composer disables
- a transient system banner shows `Codex is thinking`
- a temporary assistant bubble appears and grows with `live_text`
- if the job fails, the bubble is removed and the error stays in the banner
- if the job completes, the full session reload replaces the temporary bubble

### Soft takeover feedback

If mobile owns the session:
- show a subtle banner like `Mobile is controlling this session`

If another managed owner already holds it:
- show a human-readable message such as `This session is currently controlled by Desktop Manager`
- do not silently submit

## Error Handling

### Portal failures

- return explicit ownership conflict messages
- distinguish stale-lock recovery from true active conflict
- never leave a completed or failed job in `running` state

### Android failures

- keep errors out of the transcript
- keep the composer recoverable after a failed send
- if the portal reports conflict, present the owner name rather than a generic job-running message

## Testing Strategy

### Python

Add unit coverage for:
- ownership acquisition and release
- stale lock cleanup
- live output accumulation from Codex events
- conflict responses for active managed sessions

### Android

Add JVM tests for:
- parsing richer job payloads
- chat state updates from incremental live output
- takeover/conflict banner mapping

### Manual verification

- reproduce the old failing test session path
- verify a second message can be sent after a completed job
- verify two different sessions can run independently
- verify a managed desktop-opened session becomes read-only once mobile takes ownership

## Success Criteria

The feature is successful when:
- a previously failing mobile resume session can send and receive replies reliably
- a finished mobile job no longer leaves the session blocked
- the Android chat screen shows live incremental assistant output while Codex runs
- mobile and desktop manager coordinate writable ownership for the same managed session
- separate sessions continue to operate independently
