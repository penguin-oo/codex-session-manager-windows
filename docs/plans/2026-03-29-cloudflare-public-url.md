# Cloudflare Public URL Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Surface Cloudflare/custom public mobile-portal URLs from local settings so the portal prints and returns those links automatically.

**Architecture:** Reuse `%USERPROFILE%\.codex\mobile_portal_settings.json` as the single portal settings source. Normalize configured public base URLs, inject the live token at runtime, then expose the resulting URLs through startup output and bootstrap payload for the browser UI.

**Tech Stack:** Python 3.11+, stdlib `urllib.parse`, `unittest`, existing portal HTML template.

---

### Task 1: Add failing tests for public URL settings

**Files:**
- Modify: `tests/test_mobile_portal.py`
- Test: `tests/test_mobile_portal.py`

**Step 1: Write the failing test**

Add tests for:
- `load_proxy_settings()` returning `public_urls`
- normalization and dedupe of configured public URLs
- startup groups including a `Public (Cloudflare/custom)` section
- bootstrap payload returning serialized startup URL groups
- proxy settings updates preserving `public_urls`

**Step 2: Run test to verify it fails**

Run:

```powershell
$env:PYTHONNOUSERSITE='1'
$env:PYTHONIOENCODING='utf-8'
& 'D:\CONDA\envs\codex-accel\python.exe' -m unittest tests.test_mobile_portal.ProxySettingsTests tests.test_mobile_portal.PortalServiceBootstrapTests -v
```

Expected: failures for missing `public_urls` and missing `startup_url_groups`.

### Task 2: Implement public URL normalization and exposure

**Files:**
- Modify: `mobile_portal.py`
- Test: `tests/test_mobile_portal.py`

**Step 1: Write minimal implementation**

Implement:
- `normalize_public_urls(...)`
- `build_public_access_url(...)`
- `public_urls` persistence in `load_proxy_settings()` and `save_proxy_settings()`
- `PortalService.public_urls()`
- `startup_url_groups()` public section
- `bootstrap_payload()` serialized startup groups
- `proxy_settings_payload()` public URL passthrough

**Step 2: Run targeted tests**

Run the same unittest command again.

Expected: all tests in those two classes pass.

### Task 3: Surface links in the browser UI and startup docs

**Files:**
- Modify: `mobile_portal.py`
- Modify: `README.md`
- Modify: `AGENTS.md`

**Step 1: Update browser UI**

Expose startup/public links in the portal hero section so browser users can see the active entry URLs.

**Step 2: Update docs**

Document:
- `public_urls` config location
- expected JSON shape
- that the portal injects `?token=...` automatically

### Task 4: Final verification

**Files:**
- Verify only

**Step 1: Run focused regressions**

```powershell
$env:PYTHONNOUSERSITE='1'
$env:PYTHONIOENCODING='utf-8'
& 'D:\CONDA\envs\codex-accel\python.exe' -m unittest tests.test_mobile_portal.ProxySettingsTests tests.test_mobile_portal.PortalServiceBootstrapTests tests.test_controlled_browser -v
```

**Step 2: Run broader regressions**

```powershell
$env:PYTHONNOUSERSITE='1'
$env:PYTHONIOENCODING='utf-8'
& 'D:\CONDA\envs\codex-accel\python.exe' -m unittest tests.test_mobile_portal tests.test_controlled_browser -v
```

**Step 3: Manually verify public route**

```powershell
curl.exe -L --max-time 20 https://chat.pyguin.us.ci
```

Expected: portal HTML page loads through Cloudflare.
