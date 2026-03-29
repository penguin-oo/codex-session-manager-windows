# Release Packaging Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Prepare the repository for a clean GitHub push with detailed usage documentation and only necessary tracked assets.

**Architecture:** Update ignore rules first so local noise stays out, then rewrite the README to match the actual desktop/mobile release flow, rebuild the Windows package, verify the Android APK path, and finally stage only the intended files for push.

**Tech Stack:** Git, PowerShell, PyInstaller, Android Gradle build outputs, Markdown docs.

---

### Task 1: Define tracked vs ignored files

**Files:**
- Modify: `D:\codex\manger\.gitignore`

**Steps:**
1. Add local-only folders and temp patterns to `.gitignore`.
2. Keep `release/` tracked.
3. Verify `git status` drops ignored noise.

### Task 2: Document the release layout and usage

**Files:**
- Modify: `D:\codex\manger\README.md`
- Create: `D:\codex\manger\docs\plans\2026-03-10-release-packaging-design.md`

**Steps:**
1. Rewrite `README.md` with clear install and usage sections.
2. Document desktop, mobile portal, Android app, and Tailscale flows.
3. Explain what is committed to `release/` and what is only in GitHub Releases.

### Task 3: Refresh current release artifacts

**Files:**
- Modify: `D:\codex\manger\release\codex-session-manager-windows-x64.zip`
- Keep: `D:\codex\manger\release\codex-mobile-debug.apk`

**Steps:**
1. Rebuild the Windows executable with PyInstaller.
2. Repack the Windows zip with the current executable, launcher, README, and assets.
3. Confirm the Android APK path still points to the newest build.

### Task 4: Verify and push

**Files:**
- Stage only intended files

**Steps:**
1. Run targeted verification for packaging and repo state.
2. Review staged files to ensure no local noise is included.
3. Commit with a release-packaging message.
4. Push to `origin/main`.
