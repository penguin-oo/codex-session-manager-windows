# Clickable CLI File Links Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make Ctrl+left-click open Codex CLI file and directory references in the editor selected by `file_opener`, without modifying the official Codex installation.

**Architecture:** Build a separately named Codex 0.144.3 executable whose TUI preserves safe local-link destinations as OSC 8 editor hyperlinks. Add a generic, locally configured executable override to the desktop manager, guarded by a cached `--version` health check and an automatic fallback to the official `codex.cmd`.

**Tech Stack:** Python 3.11+, `unittest`, Rust 1.94, Cargo, Ratatui, OSC 8 terminal hyperlinks, TOML, PowerShell.

---

### Task 1: Isolate Work and Record the Official Baseline

**Files:**
- Create worktree: `D:\codex\codex-session-manager-windows\.worktrees\clickable-cli-links`
- Record locally: `%USERPROFILE%\.codex\private_backups\clickable-cli-links-<timestamp>\official-hashes.json`

**Step 1: Verify the repository is clean**

Run:

```powershell
git status --short --branch
```

Expected: no worktree changes; `main` is ahead only by the existing local commits.

**Step 2: Create an isolated feature worktree**

Run:

```powershell
git worktree add "D:\codex\codex-session-manager-windows\.worktrees\clickable-cli-links" -b feature/clickable-cli-links
```

Expected: a new worktree based on the approved design and plan commits.

**Step 3: Record official executable hashes**

Resolve `codex.cmd` and every native executable it dispatches to, then store only
absolute paths, versions, lengths, and SHA-256 hashes in the private backup
directory. Do not print configuration or environment secrets.

**Step 4: Verify the official CLI**

Run the official command with `--version`.

Expected:

```text
codex-cli 0.144.3
```

### Task 2: Add a Safe Desktop Executable Override

**Files:**
- Modify: `D:\codex\codex-session-manager-windows\.worktrees\clickable-cli-links\app.py`
- Modify: `D:\codex\codex-session-manager-windows\.worktrees\clickable-cli-links\tests\test_desktop_window_launch.py`

**Step 1: Write failing selection tests**

Add tests for a helper that resolves terminal Codex arguments:

```python
def test_configured_healthy_codex_executable_is_selected(self) -> None:
    manager = make_manager()
    with (
        mock.patch.object(app, "configured_codex_executable", return_value=Path("C:/local/codex-clickable.exe")),
        mock.patch.object(app, "codex_executable_is_healthy", return_value=True),
    ):
        resolved = manager._resolve_terminal_codex_args(["codex.cmd", "resume", "session-id"])
    self.assertEqual("C:\\local\\codex-clickable.exe", resolved[0])


def test_invalid_custom_codex_executable_falls_back_to_official(self) -> None:
    manager = make_manager()
    with (
        mock.patch.object(app, "configured_codex_executable", return_value=Path("C:/local/broken.exe")),
        mock.patch.object(app, "codex_executable_is_healthy", return_value=False),
        mock.patch.object(app.shutil, "which", return_value="C:\\official\\codex.cmd"),
    ):
        resolved = manager._resolve_terminal_codex_args(["codex.cmd"])
    self.assertEqual("C:\\official\\codex.cmd", resolved[0])
```

Also cover a missing setting, malformed JSON, a missing file, timeout, nonzero
exit, and version output that is not a Codex CLI version.

**Step 2: Run tests and verify RED**

Run:

```powershell
py -3 -m unittest tests.test_desktop_window_launch -v
```

Expected: new tests fail because the configuration and health-check helpers do
not exist.

**Step 3: Implement minimal configuration loading**

Add:

```python
PORTAL_SETTINGS_FILE = CODEX_HOME / "mobile_portal_settings.json"


def configured_codex_executable(
    settings_file: Path = PORTAL_SETTINGS_FILE,
) -> Path | None:
    try:
        payload = json.loads(settings_file.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    raw = payload.get("codex_executable") if isinstance(payload, dict) else None
    if not isinstance(raw, str) or not raw.strip():
        return None
    return Path(os.path.expandvars(raw.strip())).expanduser()
```

Add a cached health check that requires an existing file, executes
`<candidate> --version` with a short timeout and no shell, and accepts only exit
code zero with output matching `codex-cli <version>`.

Update `_resolve_terminal_codex_args()` to prefer the healthy configured
executable and retain its current `shutil.which("codex.cmd")` fallback.

**Step 4: Run focused tests and verify GREEN**

Run:

```powershell
py -3 -m unittest tests.test_desktop_window_launch -v
```

Expected: all desktop launch tests pass.

**Step 5: Commit the manager protection**

```powershell
git add app.py tests/test_desktop_window_launch.py
git commit -m "feat: support a guarded local Codex executable"
```

### Task 3: Prepare an Exact-Version Codex Source Copy

**Files:**
- Create locally: `%USERPROFILE%\.codex\build\codex-clickable-0.144.3\source`
- Create locally: `%USERPROFILE%\.codex\build\codex-clickable-0.144.3\target`
- Create: `D:\codex\codex-session-manager-windows\.worktrees\clickable-cli-links\tools\codex-clickable\codex-0.144.3-clickable-links.patch`

**Step 1: Download the pinned source**

Use the official `rust-v0.144.3` source archive. Try direct access first and
retry through `socks5h://127.0.0.1:7897` only on connection failure.

Expected SHA-256:

```text
261198AB903588F238EE87744E7AAA5914BE7FD39DF5B9F6CCB88884C3C2C058
```

Abort if the digest differs.

**Step 2: Extract safely**

Reject absolute archive entries and entries containing `..`. Extract into the
private build directory without following archive links outside that directory.

**Step 3: Confirm the source version**

Inspect the workspace version and run a lightweight Cargo metadata command.

Expected: source package version `0.144.3`.

### Task 4: Add Failing Rust Tests for Editor URIs

**Files:**
- Modify locally: `%USERPROFILE%\.codex\build\codex-clickable-0.144.3\source\codex-rust-v0.144.3\codex-rs\tui\src\markdown_render.rs`
- Modify locally: `%USERPROFILE%\.codex\build\codex-clickable-0.144.3\source\codex-rust-v0.144.3\codex-rs\tui\src\terminal_hyperlinks.rs`

**Step 1: Add URI-construction tests**

Test these behaviors with explicit `UriBasedFileOpener` arguments:

- `C:\repo\src\main.rs:42:7` becomes a `vscode://file/...:42:7` URI.
- Spaces and non-ASCII path characters are percent encoded.
- A relative target resolves against the supplied conversation cwd.
- A directory target produces the same safe editor URI shape without a line.
- `UriBasedFileOpener::None` produces no destination.

**Step 2: Add rendering tests**

Render a Markdown local link and assert:

- Visible text remains the normalized local path.
- The corresponding `HyperlinkLine` carries one editor destination.
- OSC 8 output wraps only the visible path.
- A literal model-provided `vscode://` Markdown destination does not bypass
  local-path parsing.

**Step 3: Run tests and verify RED**

From the extracted `codex-rs` directory, run:

```powershell
cargo test -p codex-tui terminal_hyperlinks --lib
cargo test -p codex-tui markdown_render_file_link --lib
```

Expected: the new tests fail because local links have no terminal destination.

### Task 5: Implement the Minimal Codex TUI Fix

**Files:**
- Modify locally: `codex-rs\tui\src\lib.rs`
- Modify locally: `codex-rs\tui\src\markdown_render.rs`
- Modify locally: `codex-rs\tui\src\terminal_hyperlinks.rs`

**Step 1: Configure the startup-only opener**

Initialize a process-local opener once from `initial_config.file_opener` before
the Ratatui application begins rendering. The official config object remains
authoritative.

**Step 2: Construct safe editor destinations**

Resolve local link targets against the conversation cwd, preserve optional line
and column suffixes, and create an editor URI using only
`UriBasedFileOpener::get_scheme()`.

**Step 3: Preserve local-link annotations**

When `markdown_render` emits the code-styled visible local path, attach the
internally generated editor destination to its `HyperlinkLine`. Apply the same
behavior inside and outside Markdown tables.

**Step 4: Extend terminal destination validation**

Keep arbitrary rendered destinations restricted to `http` and `https`. Permit
editor schemes only for destinations produced by the local-link constructor,
with control characters stripped and URL parsing required.

**Step 5: Run tests and verify GREEN**

Run:

```powershell
cargo test -p codex-tui terminal_hyperlinks --lib
cargo test -p codex-tui markdown_render_file_link --lib
```

Expected: all new and existing focused tests pass.

**Step 6: Generate the reproducible patch**

Generate a patch containing only the three TUI source changes and store it at:

`tools\codex-clickable\codex-0.144.3-clickable-links.patch`

Review it for local paths, credentials, and unrelated source changes.

### Task 6: Build and Install the Separate Binary

**Files:**
- Build locally: `%USERPROFILE%\.codex\build\codex-clickable-0.144.3\target\release\codex.exe`
- Install locally: `%USERPROFILE%\.codex\bin\codex-clickable.exe`

**Step 1: Run the complete TUI test package**

```powershell
cargo test -p codex-tui --lib
```

Expected: all tests pass.

**Step 2: Build the release binary**

```powershell
cargo build -p codex-cli --bin codex --release
```

Use a private `CARGO_TARGET_DIR` on drive `D:` if necessary. Do not overwrite an
official installation path.

**Step 3: Health-check the built binary**

Run:

```powershell
<built-codex.exe> --version
```

Expected:

```text
codex-cli 0.144.3
```

**Step 4: Install atomically**

Copy to a temporary sibling in `%USERPROFILE%\.codex\bin`, run the health
check again, then atomically replace only
`%USERPROFILE%\.codex\bin\codex-clickable.exe`.

### Task 7: Enable the Local Override Safely

**Files:**
- Back up: `%USERPROFILE%\.codex\mobile_portal_settings.json`
- Modify locally: `%USERPROFILE%\.codex\mobile_portal_settings.json`

**Step 1: Back up the settings file**

Copy it to a timestamped directory below:

`%USERPROFILE%\.codex\private_backups`

**Step 2: Add one structured property**

Using JSON parsing rather than text replacement, add:

```json
"codex_executable": "C:\\Users\\MECHREVO\\.codex\\bin\\codex-clickable.exe"
```

Preserve every existing property and do not print the file contents.

**Step 3: Verify manager resolution**

Call the resolver in a local test process and verify that it selects the custom
binary. Rename or mock the custom path temporarily in a test-only context and
verify automatic fallback to official `codex.cmd`.

### Task 8: Full Verification and Integration

**Files:**
- Modify: `D:\codex\codex-session-manager-windows\.worktrees\clickable-cli-links\tools\codex-clickable\README.md`

**Step 1: Document the optional local build**

Document the exact upstream version, source archive hash, patch application,
build command, local installation path, fallback behavior, and removal steps.
Do not include private configuration values.

**Step 2: Run project verification**

```powershell
py -3 -m unittest discover -s tests -v
py -3 -m compileall app.py tests
git diff --check
```

Expected: all tests pass, compilation succeeds, and diff checking reports no
errors.

**Step 3: Verify terminal metadata**

Run the focused Rust test that renders a Windows file and a directory link.
Confirm the captured output contains OSC 8 destinations beginning with
`vscode://file/` while visible text remains a normal absolute path.

**Step 4: Recheck official hashes**

Recompute every official hash recorded in Task 1.

Expected: all paths, lengths, versions, and hashes are unchanged.

**Step 5: Scan repository changes**

Scan the exact changed files for API keys, tokens, provider URLs, installation
IDs, machine identifiers, and the local custom executable path.

Expected: no private values or machine-local path are present.

**Step 6: Commit source integration**

```powershell
git add app.py tests/test_desktop_window_launch.py tools/codex-clickable
git commit -m "feat: enable safe clickable Codex CLI file links"
```

**Step 7: Merge without rewriting history**

Merge the feature branch back into local `main` with a normal non-interactive
merge. Do not push or synchronize another machine unless the user requests it.

**Step 8: Final manual check**

Open one new Codex terminal through the manager and render:

- A file reference with a line number.
- A directory reference.

The user presses Ctrl+left-click on each. Existing terminals remain untouched;
if manual clicking fails, remove the local `codex_executable` property and the
manager immediately returns to the official CLI.
