# Built-in Token Pool Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a desktop-only built-in token pool backend that imports token JSON files from `C:\Users\MECHREVO\.cli-proxy-api\`, runs an internal local proxy, and lets newly launched Codex terminals use pooled token quota instead of Codex auth.

**Architecture:** Keep existing account-slot auth intact and add a second global backend mode managed by the desktop tool. Implement a small internal proxy service plus desktop settings, then wire terminal launch to inject the proxy endpoint when token-pool mode is active.

**Tech Stack:** Python 3.11, Tkinter desktop UI, local HTTP server/proxy code, unittest, existing desktop helper layer in `app.py`.

---

### Task 1: Add failing tests for token-pool settings and token import helpers

**Files:**
- Create: `tests/test_token_pool_proxy.py`
- Modify: `tests/test_app_helpers.py`
- Create: `token_pool_settings.py`

**Step 1: Write the failing tests**

Add tests that expect:
- token directory creation when missing
- multi-file token import into `C:\Users\MECHREVO\.cli-proxy-api\`
- overwrite-on-conflict behavior
- backend mode persistence defaults to `codex_auth`

**Step 2: Run test to verify it fails**

Run:
```powershell
$env:PYTHONNOUSERSITE='1'; conda run -n codex-accel python -m unittest D:\codex\manger\tests\test_token_pool_proxy.py D:\codex\manger\tests\test_app_helpers.py
```
Expected: FAIL because helper module/functions do not exist yet.

**Step 3: Write minimal implementation**

Create `token_pool_settings.py` with helpers for:
- default token dir path
- mode load/save
- ensuring token dir exists
- importing token files

**Step 4: Run test to verify it passes**

Run the same unittest command.
Expected: PASS for the new helper tests.

**Step 5: Commit**

```powershell
git add tests/test_token_pool_proxy.py tests/test_app_helpers.py token_pool_settings.py
git commit -m "feat: add token pool settings helpers"
```

### Task 2: Add failing tests for token selection and cooldown behavior

**Files:**
- Modify: `tests/test_token_pool_proxy.py`
- Create: `token_pool_proxy.py`

**Step 1: Write the failing test**

Add tests for:
- round-robin selection across token files
- cooldown when a token gets an auth/quota failure
- retry selecting the next token on retryable failures

**Step 2: Run test to verify it fails**

Run:
```powershell
$env:PYTHONNOUSERSITE='1'; conda run -n codex-accel python -m unittest D:\codex\manger\tests\test_token_pool_proxy.py
```
Expected: FAIL because the proxy/token-pool logic is not implemented yet.

**Step 3: Write minimal implementation**

Implement core token-pool classes in `token_pool_proxy.py`:
- token file loading
- per-token state
- round-robin cursor
- cooldown tracking

**Step 4: Run test to verify it passes**

Run the same unittest command.
Expected: PASS for selection/cooldown tests.

**Step 5: Commit**

```powershell
git add tests/test_token_pool_proxy.py token_pool_proxy.py
git commit -m "feat: add token pool selection logic"
```

### Task 3: Add failing tests for local proxy request forwarding

**Files:**
- Modify: `tests/test_token_pool_proxy.py`
- Modify: `token_pool_proxy.py`

**Step 1: Write the failing test**

Add tests with mocked upstream HTTP responses that verify:
- request forwarding uses the selected token
- retryable upstream failure advances to next token
- auth/quota failure marks token cooldown
- no raw token is leaked in returned error text

**Step 2: Run test to verify it fails**

Run:
```powershell
$env:PYTHONNOUSERSITE='1'; conda run -n codex-accel python -m unittest D:\codex\manger\tests\test_token_pool_proxy.py
```
Expected: FAIL because forwarding and retry logic is incomplete.

**Step 3: Write minimal implementation**

Extend `token_pool_proxy.py` with:
- lightweight HTTP forwarding helpers
- retry loop across tokens
- sanitized error summaries

**Step 4: Run test to verify it passes**

Run the same unittest command.
Expected: PASS.

**Step 5: Commit**

```powershell
git add tests/test_token_pool_proxy.py token_pool_proxy.py
git commit -m "feat: add token pool proxy forwarding"
```

### Task 4: Add failing tests for desktop launch environment switching

**Files:**
- Modify: `tests/test_app_helpers.py`
- Modify: `app.py`
- Modify: `token_pool_settings.py`

**Step 1: Write the failing test**

Add tests that verify desktop terminal launch env behaves as follows:
- `codex_auth` mode does not inject local proxy base URL
- `built_in_token_pool` mode injects local proxy base URL and local API key
- clear error when token-pool mode is selected but proxy is unavailable

**Step 2: Run test to verify it fails**

Run:
```powershell
$env:PYTHONNOUSERSITE='1'; conda run -n codex-accel python -m unittest D:\codex\manger\tests\test_app_helpers.py
```
Expected: FAIL because launch helpers do not know about backend modes yet.

**Step 3: Write minimal implementation**

Modify `app.py` and helper module(s) so launch command/env generation supports both backend modes.

**Step 4: Run test to verify it passes**

Run the same unittest command.
Expected: PASS.

**Step 5: Commit**

```powershell
git add tests/test_app_helpers.py app.py token_pool_settings.py
git commit -m "feat: wire desktop launch to token pool mode"
```

### Task 5: Add failing tests for desktop Accounts dialog token-pool actions

**Files:**
- Modify: `tests/test_app_helpers.py`
- Modify: `app.py`

**Step 1: Write the failing test**

Add tests that expect desktop Accounts actions for:
- ensuring token dir exists
- importing multiple token files
- overwriting existing file names
- opening token folder path
- rendering mode/status summary text

**Step 2: Run test to verify it fails**

Run:
```powershell
$env:PYTHONNOUSERSITE='1'; conda run -n codex-accel python -m unittest D:\codex\manger\tests\test_app_helpers.py
```
Expected: FAIL because the dialog actions do not exist yet.

**Step 3: Write minimal implementation**

Modify `app.py` Accounts dialog to add the `Token Pool` section and its button actions.

**Step 4: Run test to verify it passes**

Run the same unittest command.
Expected: PASS.

**Step 5: Commit**

```powershell
git add tests/test_app_helpers.py app.py
git commit -m "feat: add desktop token pool controls"
```

### Task 6: Add failing tests for proxy process lifecycle management

**Files:**
- Modify: `tests/test_token_pool_proxy.py`
- Modify: `token_pool_proxy.py`
- Modify: `token_pool_settings.py`

**Step 1: Write the failing test**

Add tests for:
- start proxy
- stop proxy
- restart proxy
- detect running state
- deterministic handling when desired port is unavailable

**Step 2: Run test to verify it fails**

Run:
```powershell
$env:PYTHONNOUSERSITE='1'; conda run -n codex-accel python -m unittest D:\codex\manger\tests\test_token_pool_proxy.py
```
Expected: FAIL because lifecycle control is incomplete.

**Step 3: Write minimal implementation**

Implement proxy lifecycle helpers in `token_pool_proxy.py` and persist runtime state in `token_pool_settings.py` if needed.

**Step 4: Run test to verify it passes**

Run the same unittest command.
Expected: PASS.

**Step 5: Commit**

```powershell
git add tests/test_token_pool_proxy.py token_pool_proxy.py token_pool_settings.py
git commit -m "feat: add token pool proxy lifecycle controls"
```

### Task 7: Verify end-to-end desktop workflow

**Files:**
- Modify: `README.md`
- Test: manual validation against desktop workflow

**Step 1: Write the failing test or validation checklist**

Document a manual checklist covering:
- import token files
- switch to token-pool mode
- start proxy
- open new Codex terminal
- confirm injected environment uses local proxy base URL

**Step 2: Run validation to verify current behavior fails or is incomplete**

Run the documented manual sequence before docs are finalized.
Expected: discover any remaining gaps.

**Step 3: Write minimal implementation/doc updates**

Update `README.md` with:
- token folder path
- import flow
- mode switch flow
- operational limits

**Step 4: Run tests and validation to verify it passes**

Run:
```powershell
$env:PYTHONNOUSERSITE='1'; conda run -n codex-accel python -m unittest D:\codex\manger\tests\test_auth_slots.py D:\codex\manger\tests\test_mobile_portal.py D:\codex\manger\tests\test_app_helpers.py D:\codex\manger\tests\test_token_pool_proxy.py
```
Then manually verify the desktop flow.
Expected: PASS and successful manual workflow.

**Step 5: Commit**

```powershell
git add README.md tests/test_token_pool_proxy.py tests/test_app_helpers.py token_pool_proxy.py token_pool_settings.py app.py
git commit -m "feat: integrate built-in token pool mode"
```
