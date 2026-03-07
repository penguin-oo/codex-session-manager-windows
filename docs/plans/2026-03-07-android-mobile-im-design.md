# Android Mobile IM Client Design

**Date:** 2026-03-07  
**Status:** Approved  
**Scope:** Native Android client for the local Codex mobile portal, focused on polished mobile chat UX and simple operation.

## Goal

Build an Android app that feels closer to a mature IM client than a management panel:
- open app
- land on a lightweight home screen
- jump into a chat list or recent chat quickly
- tap a session and land directly in the conversation
- see newest messages at the bottom and scroll upward for history
- create new chats with launch options selected once before creation
- lock session parameters after the chat exists

The Android app remains a client of the local computer-hosted portal. The computer still runs the actual Codex sessions and the mobile app controls them through HTTP APIs.

## Non-Goals

- Running Codex locally on the phone
- Offline chat when the computer portal is unavailable
- Full tablet-first admin dashboard behavior inside the mobile app
- Editing model, approval, or sandbox after a chat has been created
- Shipping cross-device cloud sync in this iteration

## Product Principles

1. **Chat first**
   The conversation view must look and behave like a messaging client, not like a settings page.

2. **Simple default path**
   The user should be able to open the app and reach a chat in at most two taps from the home screen.

3. **Advanced controls only at the edge**
   Model, approval, and sandbox are chosen only during new chat creation and then become read-only session metadata.

4. **State should feel local and immediate**
   Loading, submitting, and error states should be concise and visible without polluting the conversation transcript.

## Architecture

### Runtime topology

The system stays split into two layers:

- **Desktop/host layer:** `mobile_portal.py` running on the computer, exposing token-protected HTTP APIs and invoking `codex exec`.
- **Android layer:** native app under `android-app/`, using the portal as its backend.

This keeps Android responsibilities limited to connection management, list rendering, chat rendering, and job polling. All session discovery, file-system access, Codex execution, note persistence, and deletion continue to live on the host.

### Android app structure

The Android app should be restructured around four screens/flows:

1. **Home**
   Entry dashboard with connection health, recent chats, shortcuts, and settings.
2. **All Chats**
   Full session list optimized for scanning and quick entry.
3. **Chat**
   Dedicated IM-style conversation screen.
4. **New Chat**
   Guided creation flow with one-time launch options.

## Information Architecture

### Home screen

Purpose: provide a light landing surface instead of dropping the user into a dense management list.

Sections:
- connection summary card
- recent chats card/list
- three primary action cards:
  - `Recent Chats`
  - `All Chats`
  - `New Chat`
- settings entry

Behavior:
- if portal URL is not configured, the connection card expands into the onboarding form
- if connected, the home screen becomes a launcher rather than a settings form
- recent chats should be a small curated subset, not the full list

### All Chats screen

Purpose: dedicated list view for browsing every session.

Each row should show:
- session title
- last message summary
- updated time
- optional note indicator or note excerpt

Interaction:
- tap: open chat immediately
- long press or overflow action: note, delete, open details

### Chat screen

Purpose: uninterrupted conversation experience.

Structure:
- app bar with back navigation, title, and overflow menu
- optional subtle metadata line under title for cwd or note summary
- message list filling the screen
- fixed bottom composer

Behavior:
- entering a chat scrolls to the newest message
- scrolling upward reveals older history
- conversation actions stay out of the transcript
- no editable model/approval/sandbox controls on the main screen

### New Chat flow

Purpose: collect required creation settings once, before chat exists.

Steps:
- choose working directory
- choose model
- choose approval policy
- choose sandbox mode
- create session
- immediately transition into the newly created chat

After creation:
- launch options are locked for that session in the mobile app
- the chat screen may show them as read-only metadata later, but never editable controls

## Visual Direction

### Overall look

Use a dark, calm, message-centric visual language. Avoid the feeling of a control panel.

Visual goals:
- stronger hierarchy on home cards
- lower chrome density in chat
- more breathing room around list items and bubbles
- clear distinction between primary action surfaces and passive metadata

### Chat styling

- user and assistant bubbles remain distinct
- newest messages appear near the composer, like mainstream IM apps
- timestamps stay secondary and visually quiet
- status banners should be compact and transient
- note preview, if present, should appear as subtle metadata, not as a warning box

### Layout priorities

- thumb-friendly spacing
- stable bottom composer
- large tap targets on home cards and session rows
- hidden or deferred advanced actions

## Data Flow

### Bootstrap

App launch should still fetch portal bootstrap data once connection succeeds:
- sessions
- available models
- available approval options
- available sandbox options
- MCP/skills summaries if later reused in settings or diagnostics

The bootstrap response seeds:
- home recent chats
- all chat list
- new chat launch options

### Chat loading

Opening a chat should fetch session payload data:
- session summary
- note
- message list

The activity should render the full message list and scroll to the end after binding.

### Sending messages

Message send flow remains portal-job based:
1. submit message to portal
2. receive queued job id
3. poll job endpoint until completion or failure
4. reload session payload
5. update transcript and keep focus on newest content

### New session creation

New chat should use the existing backend capability to start a session with selected cwd and launch options, then navigate directly into the returned session id.

## Error Handling

### Connection errors

If portal URL is invalid or host is unavailable:
- show a dedicated connection state on home
- do not dump raw stack traces into the chat view
- keep retry and edit-url actions obvious

### Job execution errors

If a resume/new-chat job fails:
- keep the error out of the transcript body
- surface a concise banner or inline system state
- allow immediate retry from the composer or creation action

### Noisy Codex logs

Portal/backend should continue filtering non-actionable stderr noise. The Android app should only receive clean error strings suitable for direct display.

## Testing Strategy

The Android client needs better safety rails before UI iteration continues.

Planned coverage:
- parser/config tests for portal URL persistence and validation
- mapping/filtering tests for home/recent/all chat presentation logic
- activity/controller tests around empty/loading/connected states
- message send state tests to verify composer disable/enable and refresh behavior

Manual verification still remains necessary for:
- perceived visual polish
- scroll behavior in long chats
- keyboard/composer interaction on device
- transition feel between home, list, and chat

## Migration Strategy

The existing Android prototype already provides the transport layer and basic session/chat rendering. The redesign should therefore preserve these lower-level pieces where possible:
- `PortalApiClient`
- `PortalEndpoint`
- data models for sessions, messages, and jobs

The following layers should be redesigned first:
- screen structure and navigation
- session list presentation
- chat screen layout
- new chat flow
- transient status and connection handling

## Success Criteria

The first usable Android build is successful when all of the following hold:
- app opens to a clean home screen instead of a dense management page
- user can reach an existing chat in two taps or fewer from home
- opening a chat lands at the newest message
- scrolling upward reveals prior messages naturally
- sending a message refreshes the conversation correctly
- new chat creation requires one-time model/approval/sandbox selection
- existing chats never expose editable launch options
- the UI feels closer to an IM client than a tooling dashboard
