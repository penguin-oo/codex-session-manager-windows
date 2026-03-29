# Controlled Browser Control Layer Design

**Date:** 2026-03-29

## Goal
Add a project-owned browser control layer that can operate on the already logged-in controlled browsers started by the fixed launchers:

- `C:\Users\MECHREVO\Desktop\启动受控Edge.cmd` -> `9222`
- `C:\Users\MECHREVO\Desktop\启动代理Chrome.cmd` -> `9223`

The user flow is:
1. Start the controlled browser manually.
2. Log in manually to a site.
3. Let the project inspect that instance and continue operating on the same logged-in page.

## Problem
The project can now discover controlled browser pages reliably, but it still cannot act on them. The missing piece is a project-local control layer that can connect to the page-level DevTools WebSocket and issue generic browser actions without depending on whichever browser an external MCP session happens to be attached to.

## Scope
In scope:
- fixed-browser support for `edge` and `chrome`
- page discovery reuse from `mobile_portal.py`
- WebSocket connection to `webSocketDebuggerUrl`
- generic actions: inspect page metadata, navigate, evaluate script, click, type, press key, wait for text
- HTTP API exposure through `mobile_portal.py`
- enough capability to drive Cloudflare configuration later

Out of scope:
- arbitrary browser takeover
- multi-user locking across different operators
- screenshots, tracing, downloads, and file uploads in the first version
- replacing all external browser tooling immediately

## Recommended Architecture
### 1. New module: `controlled_browser.py`
Create a dedicated module instead of stuffing CDP state into `mobile_portal.py`.

Responsibilities:
- manage DevTools WebSocket sessions
- send CDP commands with incrementing ids
- translate a small set of high-level actions into CDP calls
- return plain Python dict payloads for the portal API

### 2. Reuse existing browser discovery helpers
Keep page discovery in `mobile_portal.py` for now:
- `get_controlled_browser_debug_url`
- `list_controlled_browser_pages`
- `select_controlled_browser_page`
- `describe_controlled_browser_attach`

The new module accepts a `webSocketDebuggerUrl` or page descriptor produced by those helpers.

### 3. Minimal CDP action set
The first version should expose only the smallest useful set:
- `connect(page_ws_url)`
- `get_page_info()`
- `navigate(url)`
- `evaluate(js)`
- `get_html()`
- `click(selector)`
- `type(selector, text)`
- `press(key)`
- `wait_for_text(text, timeout_ms)`

Implementation approach:
- use `Page.enable`, `Runtime.enable`, `DOM.enable`, `Input.*`, `Runtime.evaluate`, `Page.navigate`
- prefer DOM query + `DOM.getBoxModel` + `Input.dispatchMouseEvent` for click
- prefer `Runtime.evaluate` to focus a selector and `Input.insertText` for type

### 4. Portal API surface
Add new routes under `mobile_portal.py`:
- `GET /api/browser/attach?browser=edge&hostname=dash.cloudflare.com`
- `POST /api/browser/navigate`
- `POST /api/browser/evaluate`
- `POST /api/browser/click`
- `POST /api/browser/type`
- `POST /api/browser/press`
- `POST /api/browser/wait-text`

These routes should:
- validate `browser` is `edge` or `chrome`
- resolve the selected page from discovery helpers
- create a short-lived controller connection
- perform one action
- return structured JSON

Short-lived per-request connections are recommended for the first version. This keeps state simple and avoids building a daemon.

### 5. Error handling
Return explicit errors for:
- browser port unavailable
- no matching page
- websocket connect failure
- selector not found
- text wait timeout
- CDP command failure

### 6. Testing
Use TDD and mock the WebSocket transport.

Test areas:
- CDP command envelope generation
- response id correlation
- navigation action command sequence
- selector lookup / click sequence
- text input sequence
- portal API validation and dispatch

## Trade-offs
### Option A: Use Playwright against the existing browser profile
Pros:
- high-level browser API
Cons:
- does not reliably attach to the already running logged-in fixed browser instance
- wrong abstraction for this exact problem

### Option B: Project-owned CDP layer
Pros:
- exact fit for the current workflow
- deterministic with fixed ports
- reusable across sites
Cons:
- more low-level than Playwright

### Option C: Full daemon
Pros:
- strongest long-term control model
Cons:
- overbuilt for current needs

## Recommendation
Implement Option B.

## Validation
The first completion bar should be:
- can attach to `edge` or `chrome`
- can read the current page title and URL from the logged-in page
- can navigate to a new URL
- can click and type on a simple page
- can be called through `mobile_portal.py` HTTP routes
