# Release Packaging Design

**Goal:** Publish the full project to GitHub while keeping local-only noise out of the repository and providing detailed usage documentation.

**Approach:** Use a hybrid release layout. Track the source tree, documentation, screenshots, tests, and only the current release artifacts in `release/`. Ignore local build caches, temp files, logs, MCP scratch data, and shortcuts.

**Decisions**
- Keep in repo: desktop app source, mobile portal source, Android app source, tests, assets, workflows, docs, current `release/` artifacts.
- Keep out of repo: `.mcp_data/`, `logs/`, `testchat/`, temp images/text, `.lnk`, build caches.
- Expand `README.md` to cover desktop use, mobile portal use, Android use, Tailscale, source builds, and repo layout.
- Regenerate the Windows zip before push so `release/` reflects the current code.
