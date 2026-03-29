# Stop Reply Design

**Goal:** Add a mobile Stop button that cancels the current reply, preserves generated text, and keeps the session usable.

## Approach
- Add a backend cancel endpoint for running jobs.
- Cancel by terminating the active `codex exec` subprocess for that job.
- Keep `live_text` and `last_message` intact, mark the job `cancelled`, and release the session lock.
- Show a `Stop` button beside `Send` only while the current job is running.

## UX
- Tapping `Stop` freezes the partial assistant reply where it is.
- Banner changes to `Reply stopped.`
- Input immediately becomes usable again.
- Reopening the chat should show the partial text and no `replying` state.