# Codex App and CLI SQLite Isolation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Give every manager-launched Codex CLI a stable, explicitly configured SQLite directory that is isolated from Codex App while preserving normal CLI upgrades.

**Architecture:** Parse local ignored Codex launch settings once into an immutable launch snapshot. Use that same snapshot to select the executable, file opener, runtime SQLite directory, environment, and final command-line overrides. Keep SQLite isolation independent of custom executable health so the official CLI fallback cannot reconnect to the App database.

**Tech Stack:** Python 3.11+, Tkinter desktop manager, PowerShell process launch wrappers, pytest/unittest, JSON local settings.

---

### Task 1: Define local SQLite isolation behavior

**Files:**
- Modify: `tests/test_desktop_window_launch.py`
- Modify: `app.py`

**Step 1: Write failing configuration tests**

Add tests proving that:

```python
settings = {
    "codex_cli_sqlite_isolation": True,
    "codex_cli_sqlite_home": "%USERPROFILE%\\.codex\\cli-clickable-sqlite",
}
```

- isolation defaults off;
- enabled isolation defaults to `CODEX_HOME / "cli-clickable-sqlite"`;
- an explicit absolute path is expanded and accepted;
- a relative path is rejected;
- a path equal to `CODEX_HOME` is rejected.

**Step 2: Run tests to verify RED**

Run:

```powershell
$env:PYTHONNOUSERSITE='1'
conda run -n codex-accel python -m pytest tests/test_desktop_window_launch.py -k "sqlite_isolation" -q
```

Expected: FAIL because the explicit isolation parser does not exist.

**Step 3: Implement pure configuration parsing**

In `app.py`:

- add an immutable local launch-settings structure;
- read `mobile_portal_settings.json` once;
- parse `codex_executable`, `codex_file_opener`,
  `codex_cli_sqlite_isolation`, and `codex_cli_sqlite_home` from the same JSON
  object;
- validate the optional SQLite path without creating or modifying it.

Keep the existing `configured_codex_executable()` and
`configured_codex_file_opener()` helpers as compatibility wrappers around the
new parser.

**Step 4: Run tests to verify GREEN**

Run the command from Step 2. Expected: PASS.

### Task 2: Resolve one immutable CLI launch snapshot

**Files:**
- Modify: `tests/test_desktop_window_launch.py`
- Modify: `app.py`

**Step 1: Write failing snapshot tests**

Add tests proving that one resolved snapshot contains:

```python
CodexTerminalLaunch(
    executable="C:/.../codex-clickable.exe",
    uses_custom_executable=True,
    file_opener="explorer",
    sqlite_home=Path("C:/.../cli-clickable-sqlite"),
    sqlite_isolated=True,
)
```

Also prove that:

- executable health is checked once;
- official fallback clears `file_opener`;
- official fallback retains the isolated CLI SQLite directory.

**Step 2: Run tests to verify RED**

Run:

```powershell
conda run -n codex-accel python -m pytest tests/test_desktop_window_launch.py -k "launch_snapshot or official_fallback" -q
```

Expected: FAIL because the snapshot resolver does not exist.

**Step 3: Implement the snapshot resolver**

Add `CodexTerminalLaunch` and `_resolve_terminal_codex_launch()` to `app.py`.
Resolve the configured executable and its health once. Resolve the SQLite path
independently from custom executable selection.

**Step 4: Run tests to verify GREEN**

Run the command from Step 2. Expected: PASS.

### Task 3: Make command-line SQLite isolation authoritative

**Files:**
- Modify: `tests/test_desktop_window_launch.py`
- Modify: `app.py`

**Step 1: Write failing command tests**

Require `_resolve_terminal_codex_args()` to append overrides in this order:

```text
...existing resume/provider arguments...
-c file_opener="explorer"
-c sqlite_home="C:/Users/.../.codex/cli-clickable-sqlite"
```

Prove that the SQLite override is also appended for the official CLI fallback
when isolation is enabled.

**Step 2: Run tests to verify RED**

Run:

```powershell
conda run -n codex-accel python -m pytest tests/test_desktop_window_launch.py -k "sqlite_override or opener_after_resume" -q
```

Expected: FAIL because `sqlite_home` is not yet added to CLI arguments.

**Step 3: Implement final overrides**

Use forward slashes in the TOML path passed through `-c` so Windows backslashes
cannot be interpreted as TOML escapes. Keep `CODEX_SQLITE_HOME` in the runtime
wrapper as a matching lower-precedence fallback.

**Step 4: Run tests to verify GREEN**

Run the command from Step 2. Expected: PASS.

### Task 4: Thread one snapshot through the window launch

**Files:**
- Modify: `tests/test_desktop_window_launch.py`
- Modify: `app.py`
- Preserve existing changes in: `window_runtime.py`
- Preserve existing tests in: `tests/test_window_runtime.py`

**Step 1: Write failing flow tests**

For both new chat and resume flows, assert that:

- `_resolve_terminal_codex_launch()` is called once;
- the same snapshot is passed to `_prepare_window_runtime()` and
  `_build_terminal_ps_command()`;
- `runtime.sqlite_home` equals the snapshot SQLite directory.

**Step 2: Run tests to verify RED**

Run:

```powershell
conda run -n codex-accel python -m pytest tests/test_desktop_window_launch.py -k "entire_launch or same_launch_snapshot" -q
```

Expected: FAIL because the current flow independently resolves runtime and
executable behavior.

**Step 3: Implement snapshot plumbing**

Extend `_prepare_window_runtime()` and `_build_terminal_ps_command()` with a
required launch snapshot for production launch flows. Preserve optional fallback
resolution only for direct unit-level helper calls.

**Step 4: Run focused regression tests**

Run:

```powershell
conda run -n codex-accel python -m pytest tests/test_desktop_window_launch.py tests/test_window_runtime.py -q
```

Expected: PASS.

### Task 5: Enable isolation in the ignored local configuration

**Files:**
- Modify locally only: `%USERPROFILE%\.codex\mobile_portal_settings.json`

**Step 1: Confirm the timestamped backup exists**

Verify a backup matching:

```text
%USERPROFILE%\.codex\backups\mobile_portal_settings.before-cli-sqlite-isolation-*.json
```

**Step 2: Update the JSON structurally**

Set only:

```json
"codex_cli_sqlite_isolation": true,
"codex_cli_sqlite_home": "%USERPROFILE%\\.codex\\cli-clickable-sqlite"
```

Preserve every unrelated local field and never print secret values.

**Step 3: Verify effective launch values without printing credentials**

Report only booleans, executable basename, opener name, and resolved SQLite
path.

### Task 6: Final verification

**Files:**
- Verify: `app.py`
- Verify: `window_runtime.py`
- Verify: `tests/test_desktop_window_launch.py`
- Verify: `tests/test_window_runtime.py`

**Step 1: Compile**

```powershell
$env:PYTHONNOUSERSITE='1'
conda run -n codex-accel python -m compileall -q app.py window_runtime.py tests
```

Expected: exit code 0.

**Step 2: Run the complete Python suite**

```powershell
conda run -n codex-accel python -m pytest -q
```

Expected: all tests pass.

**Step 3: Validate the working tree**

Run `git diff --check`, inspect the final diff, and scan added lines for API
keys, bearer tokens, installation IDs, private URLs, and local usernames.

**Step 4: Verify real CLI parsing without starting a session**

Run the resolved custom executable with the generated overrides plus `--help`.
Expected: exit code 0 and resume help output.

