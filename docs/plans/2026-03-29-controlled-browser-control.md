# Controlled Browser Control Layer Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a reusable project-owned browser control layer that can attach to the logged-in controlled Edge and Chrome instances and expose basic browser actions through the mobile portal.

**Architecture:** Create a new `controlled_browser.py` module that speaks CDP over the page-level DevTools WebSocket, then expose short-lived per-request browser action APIs from `mobile_portal.py`. Reuse the existing fixed-port page-discovery helpers to resolve the page before every action.

**Tech Stack:** Python 3.11+, `json`, `urllib`, `websocket-client` if available in `codex-accel`, `unittest` with mocks.

---

### Task 1: Create the failing transport tests

**Files:**
- Create: `tests/test_controlled_browser.py`
- Create: `controlled_browser.py`

**Step 1: Write the failing test**
Add tests for:
- opening a WebSocket to a page URL
- sending a CDP command envelope with increasing ids
- receiving a success response and returning `result`
- surfacing a protocol error

**Step 2: Run test to verify it fails**
Run:
```powershell
$env:PYTHONNOUSERSITE='1'; conda run -n codex-accel python -m unittest tests.test_controlled_browser -v
```
Expected: FAIL because `controlled_browser.py` does not exist or transport functions are missing.

**Step 3: Write minimal implementation**
Implement:
- connection wrapper
- `send_command(method, params)`
- response id matching

**Step 4: Run test to verify it passes**
Run the same command and expect PASS.

### Task 2: Add failing action tests

**Files:**
- Modify: `tests/test_controlled_browser.py`
- Modify: `controlled_browser.py`

**Step 1: Write the failing test**
Add tests for:
- `get_page_info()`
- `navigate(url)`
- `evaluate(js)`
- `click(selector)`
- `type(selector, text)`
- `press(key)`

Mock the transport so tests assert the correct CDP method sequence.

**Step 2: Run test to verify it fails**
Run the same focused test command and expect FAIL.

**Step 3: Write minimal implementation**
Add only the command sequence needed to satisfy each test.

**Step 4: Run test to verify it passes**
Run the focused test command again and expect PASS.

### Task 3: Add failing wait-for-text tests

**Files:**
- Modify: `tests/test_controlled_browser.py`
- Modify: `controlled_browser.py`

**Step 1: Write the failing test**
Cover:
- success when target text appears
- timeout when target text never appears

**Step 2: Run test to verify it fails**
Run the focused test command and expect FAIL.

**Step 3: Write minimal implementation**
Implement polling with `Runtime.evaluate` until text appears or timeout expires.

**Step 4: Run test to verify it passes**
Run the focused test command and expect PASS.

### Task 4: Add failing portal API tests

**Files:**
- Modify: `tests/test_mobile_portal.py`
- Modify: `mobile_portal.py`
- Modify: `controlled_browser.py`

**Step 1: Write the failing test**
Add tests for portal routes:
- attach status route
- navigate route
- click route
- type route
- press route
- wait-text route

Use mocked `controlled_browser` actions and existing handler helpers.

**Step 2: Run test to verify it fails**
Run:
```powershell
$env:PYTHONNOUSERSITE='1'; conda run -n codex-accel python -m unittest tests.test_mobile_portal tests.test_controlled_browser -v
```
Expected: FAIL because routes do not exist yet.

**Step 3: Write minimal implementation**
Add the new `/api/browser/*` routes and small portal helper wrappers.

**Step 4: Run test to verify it passes**
Run the same command and expect PASS.

### Task 5: Document usage

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md`

**Step 1: Update docs**
Document:
- fixed supported browsers
- manual login then attach workflow
- example API behavior and verification commands

**Step 2: Verify docs**
Read the changed sections and confirm they match real behavior.

### Task 6: Full verification

**Files:**
- Modify: none

**Step 1: Focused tests**
```powershell
$env:PYTHONNOUSERSITE='1'; conda run -n codex-accel python -m unittest tests.test_controlled_browser tests.test_mobile_portal.ControlledBrowserAttachTests -v
```

**Step 2: Regression tests**
```powershell
$env:PYTHONNOUSERSITE='1'; conda run -n codex-accel python -m unittest tests.test_mobile_portal tests.test_token_pool_proxy tests.test_controlled_browser -v
```

**Step 3: Manual validation**
1. Start `启动受控Edge.cmd`.
2. Log in to a target site manually.
3. Call the attach API and confirm the logged-in page is selected.
4. Call navigate/click/type on a safe test page.
5. Repeat with `启动代理Chrome.cmd`.
