# Mobile Account Center Design

**Date:** 2026-03-26

## Goal
Make the Android account center readable on phone screens and make normal account-slot switching usable even when the token pool backend is disabled.

## Scope
- Keep the existing backend API and slot model.
- Improve the Android account-center presentation.
- Make account-slot actions obvious and always available from mobile.
- Do not change desktop account-slot behavior.
- Do not redesign token-pool storage.

## Confirmed Behavior
- Mobile account switching continues to use `~/.codex/account_slots`.
- When token pool is disabled, slot switching must still work.
- If no saved slots exist, the UI must clearly guide the user to create one and bind the current login.

## Approach
1. Preserve `/api/accounts` as the source of truth.
2. Replace the cramped dialog layout with clearer stacked sections and high-contrast cards.
3. Show a dedicated current-account summary at the top.
4. Show each saved slot as its own card with explicit `Bind`, `Switch`, `Rename`, and `Delete` actions.
5. Keep backend controls visible but secondary to normal account switching.

## Risks
- Android dialog layout work is hard to verify without a full Gradle build.
- Existing local modifications in chat/account files must not be reverted.

## Validation
- Add or update unit coverage for account-center helper logic where practical.
- Run backend regression tests already covering `/api/accounts` payload behavior.
- Compile-check changed Android Java where possible.
