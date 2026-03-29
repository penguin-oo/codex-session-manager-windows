# Controlled Browser Attach Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a deterministic project-owned attach layer for the two supported controlled browsers so the user can log in first and the project can later inspect and continue from that exact logged-in browser instance.

**Architecture:** Add a small DevTools JSON client for the fixed controlled-browser ports (`9222` for Edge direct and `9223` for Chrome proxy), then expose helper functions that discover pages and choose the best attach candidate without depending on whichever browser an external MCP tool happens to be using.

**Tech Stack:** Python 3.11+, standard library `urllib`/`json`, existing `unittest` suite.

---

### Task 1: Add failing tests for controlled-browser discovery

**Files:**
- Modify: `tests/test_mobile_portal.py`
- Modify: `mobile_portal.py`

**Step 1: Write the failing test**

Add tests covering:

```python
def test_get_controlled_browser_debug_url_returns_expected_ports():
    self.assertEqual('http://127.0.0.1:9222', mobile_portal.get_controlled_browser_debug_url('edge'))
    self.assertEqual('http://127.0.0.1:9223', mobile_portal.get_controlled_browser_debug_url('chrome'))


def test_list_controlled_browser_pages_filters_only_page_entries():
    payload = json.dumps([
        {'type': 'page', 'url': 'https://example.com', 'title': 'Example', 'id': '1'},
        {'type': 'iframe', 'url': 'https://ignored.example', 'title': 'Ignored', 'id': '2'},
    ])
    with mock.patch('mobile_portal.fetch_json_text', return_value=payload):
        pages = mobile_portal.list_controlled_browser_pages('edge')
    self.assertEqual(1, len(pages))
    self.assertEqual('https://example.com', pages[0]['url'])
```

**Step 2: Run test to verify it fails**

Run:

```bash
set PYTHONNOUSERSITE=1 && conda run -n codex-accel python -m unittest tests.test_mobile_portal.ControlledBrowserAttachTests -v
```

Expected: FAIL because the helper functions do not exist yet.

**Step 3: Write minimal implementation**

Add:

- `get_controlled_browser_debug_url(browser_name)`
- `fetch_json_text(url, timeout_seconds=...)`
- `list_controlled_browser_pages(browser_name)`

Keep the implementation small and standard-library based.

**Step 4: Run test to verify it passes**

Run the same command and expect PASS.

**Step 5: Commit**

```bash
git add tests/test_mobile_portal.py mobile_portal.py
git commit -m "feat: add controlled browser page discovery"
```

### Task 2: Add failing tests for page matching behavior

**Files:**
- Modify: `tests/test_mobile_portal.py`
- Modify: `mobile_portal.py`

**Step 1: Write the failing test**

Add tests covering:

```python
def test_select_controlled_browser_page_prefers_url_prefix_match():
    pages = [
        {'type': 'page', 'url': 'https://example.com/login', 'title': 'Login'},
        {'type': 'page', 'url': 'https://dash.cloudflare.com/one/', 'title': 'Cloudflare'},
    ]
    selected = mobile_portal.select_controlled_browser_page(pages, url_prefix='https://dash.cloudflare.com/')
    self.assertEqual('https://dash.cloudflare.com/one/', selected['url'])


def test_select_controlled_browser_page_falls_back_to_first_non_blank_page():
    pages = [
        {'type': 'page', 'url': 'about:blank', 'title': ''},
        {'type': 'page', 'url': 'https://example.com', 'title': 'Example'},
    ]
    selected = mobile_portal.select_controlled_browser_page(pages)
    self.assertEqual('https://example.com', selected['url'])
```

Also add a failure test for the no-candidate case.

**Step 2: Run test to verify it fails**

Run:

```bash
set PYTHONNOUSERSITE=1 && conda run -n codex-accel python -m unittest tests.test_mobile_portal.ControlledBrowserAttachTests -v
```

Expected: FAIL because matching logic does not exist yet.

**Step 3: Write minimal implementation**

Add:

- `select_controlled_browser_page(pages, url_prefix='', hostname='')`

Rules:

- exact `url_prefix` match first
- hostname match second
- first non-blank page third
- raise a clear error if no usable page exists

**Step 4: Run test to verify it passes**

Run the same command and expect PASS.

**Step 5: Commit**

```bash
git add tests/test_mobile_portal.py mobile_portal.py
git commit -m "feat: add controlled browser page selection"
```

### Task 3: Add failing tests for attach status reporting

**Files:**
- Modify: `tests/test_mobile_portal.py`
- Modify: `mobile_portal.py`

**Step 1: Write the failing test**

Add tests for a helper that reports attach status in a single object:

```python
def test_describe_controlled_browser_attach_returns_running_match_status():
    pages = [
        {'type': 'page', 'url': 'https://dash.cloudflare.com/one/', 'title': 'Cloudflare', 'id': 'abc'}
    ]
    with mock.patch('mobile_portal.list_controlled_browser_pages', return_value=pages):
        result = mobile_portal.describe_controlled_browser_attach('edge', url_prefix='https://dash.cloudflare.com/')
    self.assertTrue(result['running'])
    self.assertTrue(result['matched'])
    self.assertEqual('https://dash.cloudflare.com/one/', result['selected_page']['url'])
```

Also add tests for:

- browser not running
- browser running but no matching page

**Step 2: Run test to verify it fails**

Run:

```bash
set PYTHONNOUSERSITE=1 && conda run -n codex-accel python -m unittest tests.test_mobile_portal.ControlledBrowserAttachTests -v
```

Expected: FAIL because status helper does not exist yet.

**Step 3: Write minimal implementation**

Add:

- `describe_controlled_browser_attach(browser_name, url_prefix='', hostname='')`

Return a dict with:

- `browser`
- `debug_url`
- `running`
- `matched`
- `page_count`
- `selected_page`
- `candidate_pages`
- `error`

**Step 4: Run test to verify it passes**

Run the same command and expect PASS.

**Step 5: Commit**

```bash
git add tests/test_mobile_portal.py mobile_portal.py
git commit -m "feat: add controlled browser attach status"
```

### Task 4: Surface the feature in project docs

**Files:**
- Modify: `README.md`

**Step 1: Write the failing test**

No automated test required for this doc-only step.

**Step 2: Update documentation**

Add a short section describing:

- supported browsers: `Edge 9222`, `Chrome 9223`
- exact startup scripts
- the supported workflow: start browser, log in manually, then attach later
- limitation: only these two controlled browsers are supported

**Step 3: Verify documentation reads cleanly**

Open `README.md` and confirm the steps are concrete and accurate.

**Step 4: Commit**

```bash
git add README.md
git commit -m "docs: document controlled browser attach workflow"
```

### Task 5: Full verification

**Files:**
- Modify: none

**Step 1: Run focused tests**

```bash
set PYTHONNOUSERSITE=1 && conda run -n codex-accel python -m unittest tests.test_mobile_portal.ControlledBrowserAttachTests -v
```

Expected: PASS.

**Step 2: Run broader regression coverage**

```bash
set PYTHONNOUSERSITE=1 && conda run -n codex-accel python -m unittest tests.test_mobile_portal tests.test_token_pool_proxy -v
```

Expected: PASS.

**Step 3: Manual validation**

1. Close all Edge and Chrome windows.
2. Run `C:\Users\MECHREVO\Desktop\启动受控Edge.cmd`.
3. Log in manually to a target site.
4. Confirm the helper reports the existing logged-in tab from port `9222`.
5. Repeat with `C:\Users\MECHREVO\Desktop\启动代理Chrome.cmd` and port `9223`.

**Step 4: Final commit**

```bash
git add mobile_portal.py tests/test_mobile_portal.py README.md docs/plans/2026-03-29-controlled-browser-attach-design.md docs/plans/2026-03-29-controlled-browser-attach.md
git commit -m "feat: add controlled browser attach helpers"
```
