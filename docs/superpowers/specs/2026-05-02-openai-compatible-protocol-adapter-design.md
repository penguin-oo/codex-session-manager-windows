# OpenAI-Compatible Protocol Adapter Design

**Date:** 2026-05-02

**Goal**

Extend the existing `openai_compatible` backend so one saved `Base URL + API key + Model` can work against upstreams that support either `/responses` or `/chat/completions`, while leaving `codex_auth` and `built_in_token_pool` unchanged.

**Scope**

- Only modify the `openai_compatible` backend path.
- Detect the upstream protocol during save time.
- Reject saving when neither protocol is usable.
- Keep Codex pointed at a local `responses`-compatible provider regardless of upstream protocol.
- Support the common request types already used in normal Codex conversations:
  - text input/output
  - image input
  - streaming output
  - OpenAI-style tool calls and tool results

**Out of Scope**

- No changes to `codex_auth`.
- No changes to `built_in_token_pool`.
- No runtime auto-switching between protocols.
- No attempt to normalize vendor-specific private fields beyond the common OpenAI-style surface.

## Architecture

### Settings and detection

`token_pool_settings.py` remains the single settings store. It gains:

- `openai_protocol`
- optional validation metadata for UI/status reporting

Saving a custom backend now performs protocol detection before persistence:

1. probe `/responses`
2. if unsupported, probe `/chat/completions`
3. if both fail, surface a concrete error and do not save

The detected protocol is persisted with the rest of the backend settings.

### Local adapter boundary

Codex cannot speak anything except `wire_api="responses"` for custom providers, so the project must expose a local `responses` endpoint even when the upstream only supports `/chat/completions`.

A new local module, `custom_provider_proxy.py`, becomes that boundary:

- For `responses` upstreams, it mostly forwards through.
- For `chat/completions` upstreams, it translates:
  - incoming Codex `responses` request payloads
  - outgoing non-stream and stream responses

This module is only used when `backend_mode=openai_compatible`.

### Launch flow

Desktop launches and mobile portal launches keep using the existing provider override approach, but the provider `base_url` changes from the user-entered upstream URL to the new local adapter URL.

The adapter receives:

- the saved upstream base URL
- the detected upstream protocol
- the upstream API key
- the local provider API key that Codex uses to authenticate against the adapter

This preserves the current launch shape and keeps Codex unaware of the upstream protocol mismatch.

## Request/response translation

### Save-time probes

The save-time probe is intentionally minimal and deterministic.

- `/responses` probe:
  - small JSON request with one text input and `stream=false`
- `/chat/completions` probe:
  - small JSON request with one user message

Success means an HTTP 2xx response with parseable JSON. Explicit `404/405/501` or structurally invalid responses count as unsupported for that protocol.

### Translation rules

For `chat/completions` upstreams:

- `responses.input` text items map to `messages`
- image input items map to content arrays in OpenAI-compatible chat-completions shape
- tool definitions map to `tools`
- tool call outputs map back into assistant/output items that Codex expects
- streaming chunks map back into `responses`-style SSE events

The translation stays conservative:

- keep only fields that have a clear mapping
- drop unsupported vendor-private fields
- return explicit errors when a required mapping is impossible

## Error handling

- Save-time detection failure:
  - report the actual failure
  - do not persist the new backend config
  - do not switch backend mode
- Runtime upstream `401/403`:
  - surface authentication failure directly
- Runtime protocol mismatch after a previously successful save:
  - fail clearly and instruct the user to re-save the backend config
- Streaming interruption:
  - keep already emitted chunks
  - emit a terminal failure event instead of pretending success

## Testing

Add regression coverage for:

- protocol detection success for `/responses`
- protocol detection fallback to `/chat/completions`
- refusal to save when neither protocol works
- request translation for text, image, and tool payloads
- response translation for non-stream and stream chat-completions output
- desktop and mobile launch plumbing using the local adapter URL
- no regressions in token-pool behavior
