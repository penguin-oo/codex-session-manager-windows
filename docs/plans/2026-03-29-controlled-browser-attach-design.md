# Controlled Browser Attach Design

**Date:** 2026-03-29

## Goal

Make the project reliably continue work in the already logged-in controlled browsers started by:

- `C:\Users\MECHREVO\Desktop\启动受控Edge.cmd` on `http://127.0.0.1:9222`
- `C:\Users\MECHREVO\Desktop\启动代理Chrome.cmd` on `http://127.0.0.1:9223`

The target behavior is:

1. The user manually starts the controlled browser.
2. The user manually logs in to a target site.
3. The project can later re-attach to that exact controlled instance and continue operating on the existing logged-in tab state.

## Problem Statement

The current workflow relies on an external browser-control path plus the current MCP browser attachment state. In practice, this creates a mismatch:

- the controlled browser can be running correctly on `9222` or `9223`
- the user can already be logged in
- but the automation path available in the current session may still be attached to a different browser instance

This is not a website-login problem. It is an attach-to-the-right-browser problem.

## Scope

This design only covers the two supported controlled-browser endpoints:

- Edge direct mode on port `9222`
- Chrome proxy mode on port `9223`

It does not try to support:

- arbitrary user-opened browsers
- browser discovery beyond these two fixed ports
- a new always-on browser management daemon

## Recommended Approach

Add a project-owned controlled-browser attachment layer that talks directly to the fixed DevTools JSON endpoints for the two supported browsers.

Instead of depending on whichever browser the current MCP browser tool happens to be attached to, the project should be able to:

- probe `http://127.0.0.1:9222/json/list` for Edge
- probe `http://127.0.0.1:9223/json/list` for Chrome
- inspect open pages in those instances
- find the tab the user already opened and logged into
- continue work by targeting that browser instance explicitly

## Architecture

### 1. Fixed browser target model

Introduce a small abstraction for the two supported controlled browsers:

- `edge`
  - debug URL: `http://127.0.0.1:9222`
  - mode: direct
- `chrome`
  - debug URL: `http://127.0.0.1:9223`
  - mode: proxy

This should stay hard-coded and simple.

### 2. DevTools discovery helper

Add helper logic that:

- requests `/json/version`
- requests `/json/list`
- parses page entries
- filters to top-level `type == "page"`

This gives deterministic visibility into the actual controlled browser state.

### 3. Page matching rules

When asked to attach to a site, the helper should:

- prefer exact URL prefix match when provided
- otherwise prefer hostname match
- otherwise prefer the first visible page candidate that is not `about:blank`

If multiple pages match, the helper should return all candidates in stable order so the caller can pick the best one.

### 4. Clear failure modes

The attach layer must produce explicit user-facing failures:

- browser not running on the expected port
- debug endpoint unavailable
- no matching page open in that browser
- only blank pages found

This replaces the current ambiguous situation where the user is logged in but the tool appears disconnected.

### 5. Integration path

The initial integration goal is modest:

- add the helper to the project backend
- expose enough data for manual workflows and future automation
- use it first for browser-state inspection and attach verification

This keeps the change small and avoids pretending we can fully replace the current MCP browser control in one step.

## Trade-offs

### Option A: Keep current behavior

Pros:
- no code changes

Cons:
- still non-deterministic
- still fails when MCP is attached elsewhere

### Option B: Add direct fixed-port attachment helpers

Pros:
- deterministic for the two supported launchers
- matches actual user workflow
- low implementation risk
- easy to test with mocked DevTools JSON responses

Cons:
- only supports the two known controlled browsers
- not a universal browser automation layer

### Option C: Build a full browser-control service

Pros:
- most complete long-term model

Cons:
- too much machinery for the current problem
- adds maintenance cost without solving a real immediate need beyond Option B

## Recommendation

Implement Option B.

It directly solves the real failure mode without introducing a broader browser orchestration system.

## Testing Strategy

Use TDD with focused unit tests for:

- endpoint unavailable
- endpoint returns non-JSON or empty pages
- page filtering keeps only top-level pages
- match by URL prefix
- match by hostname
- fallback to first non-blank page
- no candidate found

## Documentation Impact

Update `README.md` to explain the supported workflow:

1. Start the controlled Edge or Chrome launcher.
2. Log in manually in that browser.
3. Use the attach helper / inspection path to continue from the same instance.

## Out of Scope

- arbitrary browser takeover
- auto-login
- Cloudflare-specific logic
- replacing existing MCP browser tooling entirely
