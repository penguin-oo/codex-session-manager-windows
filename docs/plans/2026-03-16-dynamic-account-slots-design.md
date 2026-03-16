# Dynamic Account Slots Design

**Goal**
Allow the tool to manage any number of saved Codex login slots instead of a fixed `Account A` / `Account B`, while preserving the existing login data and exposing the current account's weekly quota from `codex /status`.

## Scope
- Replace fixed slot enumeration with dynamic slot metadata.
- Migrate existing `account-a` / `account-b` directories without changing their auth contents.
- Keep shared session/history/settings behavior unchanged.
- Show only the currently active account's weekly quota.

## Storage Model
- Continue using `D:\codex\auth-slots\` as the root.
- Add `slots.json` under that root to store slot metadata:
  - `slot_id`
  - `label`
  - `created_at`
  - `updated_at`
  - `sort_order`
- Keep each slot directory storing only:
  - `auth.json`
  - `cap_sid`

## Migration
- On first load, detect legacy `account-a` and `account-b` directories.
- Create matching `slots.json` entries with labels `Account A` and `Account B`.
- Do not rewrite auth payloads.
- If `slots.json` already exists, do not alter user-managed labels/order.

## Desktop UI
- Keep the existing `Accounts` dialog entry point.
- Replace fixed cards with a generated list from `slots.json`.
- Add actions:
  - `New Slot`
  - `Rename`
  - `Delete`
  - `Bind Current Here`
  - `Switch Here`
- Deleting a slot removes only the slot backup, not the currently active auth in `.codex`.
- Show current-account weekly quota at the top of the dialog.

## Mobile UI
- Reuse the existing `Accounts` dialog entry points in `MainActivity` and `ChatActivity`.
- Render dynamic slot rows instead of hardcoded A/B labels.
- Support create, rename, delete, bind, switch.
- Show current-account weekly quota at the top of the dialog.

## Quota Source
- Read current-account weekly quota from `codex /status`.
- Treat this as read-only display state.
- If parsing fails or the command times out, show `Quota unavailable`.

## Error Handling
- Block switching while jobs are running, preserving the existing safeguard.
- Creating, renaming, or deleting a slot must not affect the active auth files in `.codex`.
- Quota lookup failure must not block slot management actions.

## Verification
- Migration tests for legacy A/B directories.
- Dynamic slot CRUD tests in backend helpers.
- Quota parsing tests from representative `/status` output.
- Desktop helper tests for dynamic labels/summaries.
- Android parsing tests for dynamic account-slot payloads.
