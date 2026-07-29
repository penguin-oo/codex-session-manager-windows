# Explorer Location Links Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make Codex CLI local file links reveal and select files in Windows File Explorer while directory links open the directory directly.

**Architecture:** Extend the separate Codex 0.144.3 build with an explicit `file_opener = "explorer"` mode that emits internally trusted `codex-location:///...` OSC 8 links. Register a current-user Windows URI handler that validates drive-letter local paths and launches only File Explorer. Install the rebuilt CLI under a new filename so existing Codex processes and the official installation remain untouched.

**Tech Stack:** Rust 1.94, Cargo, Ratatui, OSC 8 terminal hyperlinks, PowerShell 5.1+, Windows HKCU URI protocol registration, Python 3.11 `unittest`.

---

### Task 1: Record Baselines and Back Up Local State

**Files:**
- Worktree: `D:\codex\codex-session-manager-windows\.worktrees\explorer-location-links`
- Read locally: `%USERPROFILE%\.codex\config.toml`
- Read locally: `%USERPROFILE%\.codex\mobile_portal_settings.json`
- Read locally: `%USERPROFILE%\.codex\bin\codex-clickable.exe`
- Create locally: `%USERPROFILE%\.codex\private_backups\explorer-location-links-<timestamp>`

**Step 1: Verify the isolated branch**

Run:

```powershell
git status --short --branch
git log -3 --oneline
```

Expected: clean `feature/explorer-location-links` worktree containing the
approved design commits.

**Step 2: Back up important local configuration**

Copy `config.toml` and `mobile_portal_settings.json` into the timestamped
private backup directory. Do not print their contents.

**Step 3: Back up the existing separate custom binary**

Copy `codex-clickable.exe` to the same private backup directory and record its
length, version, and SHA-256 digest.

**Step 4: Record the current official fallback**

Resolve `codex.cmd`, its package binary, and any local application binary it
dispatches to. Record path, version, length, and SHA-256 only. Treat the current
official state as the baseline; do not install, remove, upgrade, or downgrade
the official package.

**Step 5: Back up current protocol registration**

Check:

```powershell
reg query "HKCU\Software\Classes\codex-location"
```

If it exists, export it to the private backup directory. If it does not exist,
write a small marker file stating that no previous registration existed.

**Step 6: Back up private Codex source files that will change**

Copy these files into the private backup directory while preserving their
relative paths:

```text
codex-rs\config\src\types.rs
codex-rs\tui\src\markdown_render.rs
codex-rs\tui\src\markdown_render_tests.rs
```

### Task 2: Add Failing Tests for the Windows Location Handler

**Files:**
- Create: `D:\codex\codex-session-manager-windows\.worktrees\explorer-location-links\tests\test_codex_location_handler.py`
- Create later: `D:\codex\codex-session-manager-windows\.worktrees\explorer-location-links\tools\codex-clickable\codex-location-handler.ps1`

**Step 1: Write the failing handler tests**

Use temporary files and directories. Invoke the future script with
`powershell.exe -NoProfile -NonInteractive -File ... -Uri <uri> -DryRun` and
parse its JSON output.

Cover:

```python
def test_existing_file_is_selected(self) -> None:
    result = self.run_handler(self.file_uri, dry_run=True)
    self.assertEqual("select-file", result["action"])
    self.assertEqual(str(self.file_path), result["path"])


def test_existing_directory_is_opened(self) -> None:
    result = self.run_handler(self.directory_uri, dry_run=True)
    self.assertEqual("open-directory", result["action"])


def test_missing_file_opens_existing_parent(self) -> None:
    result = self.run_handler(self.missing_file_uri, dry_run=True)
    self.assertEqual("open-parent", result["action"])


def test_network_device_and_command_text_are_rejected(self) -> None:
    for uri in self.unsafe_uris:
        completed = self.invoke_handler(uri, dry_run=True)
        self.assertNotEqual(0, completed.returncode)
```

Also cover spaces, non-ASCII characters, encoded quotes, control characters,
extra URI hosts, query strings, fragments, alternate data stream colons, and a
missing parent.

**Step 2: Run tests and verify RED**

Run:

```powershell
$env:PYTHONNOUSERSITE = "1"
conda run --no-capture-output -n codex-accel python -m unittest tests.test_codex_location_handler -v
```

Expected: tests fail because `codex-location-handler.ps1` does not exist.

### Task 3: Implement the Minimal Safe Location Handler

**Files:**
- Create: `D:\codex\codex-session-manager-windows\.worktrees\explorer-location-links\tools\codex-clickable\codex-location-handler.ps1`
- Test: `D:\codex\codex-session-manager-windows\.worktrees\explorer-location-links\tests\test_codex_location_handler.py`

**Step 1: Parse only the private URI format**

The script must accept:

```powershell
param(
    [Parameter(Mandatory = $true)]
    [string] $Uri,
    [switch] $DryRun
)
```

Use `System.Uri` and require:

- Scheme exactly `codex-location`.
- Empty host, user info, query, and fragment.
- A decoded path matching `^/[A-Za-z]:/`.
- No quotes, control characters, UNC prefixes, device namespace, or additional
  colon after the drive prefix.

Normalize with `System.IO.Path.GetFullPath()` after converting `/` to `\`.
Never use `Invoke-Expression`, `cmd.exe`, environment expansion, or a shell
string assembled from the URI.

**Step 2: Classify the target**

Return these actions:

- Existing leaf: `select-file`, target is the file.
- Existing container: `open-directory`, target is the directory.
- Missing leaf with existing parent: `open-parent`, target is the parent.
- Anything else: terminate nonzero without launching a process.

**Step 3: Add dry-run JSON**

`-DryRun` must output one compact JSON object containing only:

```json
{
  "action": "select-file",
  "path": "D:\\example\\file.txt",
  "executable": "C:\\Windows\\explorer.exe",
  "arguments": ["/select,\"D:\\example\\file.txt\""]
}
```

Do not launch Explorer in dry-run mode.

**Step 4: Launch Explorer without a command shell**

For a directory or parent, pass one quoted path argument. For a file, pass one
`/select,"<path>"` argument. Use `Start-Process` with the system Explorer path.

**Step 5: Run handler tests and verify GREEN**

Run the Task 2 command.

Expected: all handler tests pass.

**Step 6: Commit the handler**

```powershell
git add tests/test_codex_location_handler.py tools/codex-clickable/codex-location-handler.ps1
git commit -m "feat: add safe Explorer location handler"
```

### Task 4: Add the Current-User Protocol Installer

**Files:**
- Create: `D:\codex\codex-session-manager-windows\.worktrees\explorer-location-links\tools\codex-clickable\install-codex-location-handler.ps1`
- Modify: `D:\codex\codex-session-manager-windows\.worktrees\explorer-location-links\tests\test_codex_location_handler.py`

**Step 1: Add failing installer dry-run tests**

Test that the installer:

- Copies the handler below a caller-supplied temporary install root.
- Produces a registry command using `powershell.exe`, `-NoProfile`,
  `-NonInteractive`, `-WindowStyle Hidden`, and a quoted `%1`.
- Uses only `HKCU\Software\Classes\codex-location`.
- Supports a dry run without touching the real registry.
- Refuses to remove a registration it does not own.

**Step 2: Run tests and verify RED**

Run the focused Python test module and expect installer tests to fail because
the installer does not exist.

**Step 3: Implement install, inspect, and uninstall modes**

Default installation root:

```text
%USERPROFILE%\.codex\bin
```

Registry command shape:

```text
powershell.exe -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "<handler>" -Uri "%1"
```

Registration must be current-user only. Uninstall must verify that the current
command points to the installed handler before removing the key.

**Step 4: Run tests and verify GREEN**

Run the focused Python test module.

Expected: all handler and installer tests pass without changing the real
protocol key.

**Step 5: Commit the installer**

```powershell
git add tests/test_codex_location_handler.py tools/codex-clickable/install-codex-location-handler.ps1
git commit -m "feat: install Explorer links for the current user"
```

### Task 5: Add Failing Rust Tests for Explorer URIs

**Files:**
- Modify privately: `%USERPROFILE%\.codex\build\codex-clickable-0.144.3\source\codex-rust-v0.144.3\codex-rs\config\src\types.rs`
- Modify privately: `%USERPROFILE%\.codex\build\codex-clickable-0.144.3\source\codex-rust-v0.144.3\codex-rs\tui\src\markdown_render_tests.rs`

**Step 1: Add a config deserialization test**

Add a focused test proving that `"explorer"` deserializes to
`UriBasedFileOpener::Explorer`.

**Step 2: Add Markdown URI tests**

Add tests proving:

- `D:/workspace/src/main.rs:42:7` produces
  `codex-location:///D:/workspace/src/main.rs`.
- A directory preserves its trailing slash.
- Relative paths resolve against the conversation cwd.
- Spaces and non-ASCII characters are percent encoded.
- UNC and device paths remain visible but have no hyperlink.
- Existing VS Code links still preserve line and column suffixes.

**Step 3: Run tests and verify RED**

Run:

```powershell
$env:CARGO_TARGET_DIR = "%USERPROFILE%\.codex\build\codex-clickable-0.144.3\target-msvc"
cargo test -p codex-config UriBasedFileOpener --lib
cargo test -p codex-tui explorer_location --lib
```

Expected: compilation or tests fail because the `Explorer` variant and URI
branch do not exist.

### Task 6: Implement Explorer URI Generation

**Files:**
- Modify privately: `codex-rs\config\src\types.rs`
- Modify privately: `codex-rs\tui\src\markdown_render.rs`
- Test privately: `codex-rs\tui\src\markdown_render_tests.rs`

**Step 1: Add the explicit config variant**

Add:

```rust
#[serde(rename = "explorer")]
Explorer,
```

Keep all existing variants unchanged.

**Step 2: Generate a location URI only from parsed local paths**

In `editor_uri_for_local_link`, branch on
`UriBasedFileOpener::Explorer` after existing local-path parsing and absolute
normalization:

- Reject UNC and device paths.
- Require a Windows drive-letter absolute path.
- Omit line and column suffixes.
- Build `codex-location:///...` with `url::Url` percent encoding.

All editor variants continue using their existing URI construction and location
suffix behavior.

**Step 3: Run focused Rust tests and verify GREEN**

Run the Task 5 commands.

Expected: all new tests pass.

**Step 4: Run existing clickable-link tests**

Run:

```powershell
cargo test -p codex-tui markdown_render_file_link --lib
cargo test -p codex-tui terminal_hyperlinks --lib
```

Expected: no regression in existing editor links or OSC 8 rendering.

### Task 7: Regenerate and Review the Public Codex Patch

**Files:**
- Modify: `D:\codex\codex-session-manager-windows\.worktrees\explorer-location-links\tools\codex-clickable\codex-0.144.3-clickable-links.patch`
- Modify: `D:\codex\codex-session-manager-windows\.worktrees\explorer-location-links\tools\codex-clickable\README.md`

**Step 1: Prepare a fresh official source comparison**

Verify the official source archive SHA-256 remains:

```text
261198AB903588F238EE87744E7AAA5914BE7FD39DF5B9F6CCB88884C3C2C058
```

Extract to a new private temporary directory with path traversal checks.

**Step 2: Generate one reproducible patch**

Compare the modified private source against the fresh official source. Include
only the config and TUI source files required by the original clickable-link
feature plus Explorer mode.

**Step 3: Reapply the patch to another fresh copy**

Run `git apply --check` and apply it. Compare normalized content hashes for
every patched file with the private build source.

Expected: all files match.

**Step 4: Update public documentation**

Document:

- `explorer` behavior.
- Current-user protocol installation and removal.
- No Android or network service requirement.
- Separate binary and automatic manager fallback.
- Security restrictions and manual rollback.

Do not include local keys, tokens, provider names, installation IDs, machine
identifiers, or literal user profile paths.

**Step 5: Commit the patch and docs**

```powershell
git add tools/codex-clickable
git commit -m "feat: add Explorer location links to Codex CLI"
```

### Task 8: Run Rust Verification and Build the New Binary

**Files:**
- Build privately: `%USERPROFILE%\.codex\build\codex-clickable-0.144.3\target-msvc\release\codex.exe`
- Install later: `%USERPROFILE%\.codex\bin\codex-clickable-explorer.exe`

**Step 1: Check formatting**

Run:

```powershell
cargo fmt --all --check
```

Expected: exit zero. Stable-toolchain warnings are acceptable only if formatting
still exits zero.

**Step 2: Run the complete patched TUI suite**

Run:

```powershell
cargo test -p codex-tui --lib
```

Record pass, fail, and ignored counts.

**Step 3: Compare with a pure official baseline**

Run the same TUI suite from a fresh unpatched official source copy with a
separate target directory. Any failures must have exactly the same test names
as the patched suite. New or missing failures block installation.

**Step 4: Build release**

Run:

```powershell
cargo build -p codex-cli --bin codex --release
```

Allow the ThinLTO link to finish naturally. Do not stop active Codex processes.

**Step 5: Health-check the build**

Run:

```powershell
<built-codex.exe> --version
<built-codex.exe> --help
<built-codex.exe> features list
```

Expected: all commands exit zero and report `codex-cli 0.144.3`.

### Task 9: Activate Locally Without Touching Existing Sessions

**Files:**
- Install locally: `%USERPROFILE%\.codex\bin\codex-clickable-explorer.exe`
- Install locally: `%USERPROFILE%\.codex\bin\codex-location-handler.ps1`
- Modify locally: `%USERPROFILE%\.codex\config.toml`
- Modify locally: `%USERPROFILE%\.codex\mobile_portal_settings.json`
- Modify locally: `HKCU\Software\Classes\codex-location`

**Step 1: Install the new binary atomically under a new name**

Copy to a temporary sibling, run `--version`, then rename it to
`codex-clickable-explorer.exe`. Do not replace or delete
`codex-clickable.exe`.

**Step 2: Install the current-user protocol**

Run the installer after the Task 1 registry backup. Inspect the resulting
registry command and verify it points to the copied handler.

**Step 3: Test the registered handler without Codex**

Use one temporary file and one temporary directory:

- Invoke their `codex-location` URIs.
- Verify Explorer selects the file and opens the directory.
- Remove the temporary targets afterward.

**Step 4: Update Codex config structurally**

Parse TOML, change only the root property:

```toml
file_opener = "explorer"
```

Verify the complete config still parses. Do not print provider or credential
values.

**Step 5: Update the manager override structurally**

Parse JSON and change only:

```json
"codex_executable": "%USERPROFILE%\\.codex\\bin\\codex-clickable-explorer.exe"
```

Preserve every other property and compare the before/after structure without
printing private values.

**Step 6: Verify resolver selection and fallback**

Verify the manager selects the new healthy binary. In a mocked or temporary
test context, verify that an unhealthy new path still falls back to the current
official `codex.cmd`.

### Task 10: Complete Verification and Integrate

**Files:**
- Verify all changed repository files.
- Do not modify Android files.

**Step 1: Run all project tests**

Run:

```powershell
$env:PYTHONNOUSERSITE = "1"
conda run --no-capture-output -n codex-accel python -m unittest discover -s tests -v
```

Expected: all existing 65 tests plus new handler tests pass.

**Step 2: Run static repository checks**

Run:

```powershell
git diff --check
git status --short --branch
```

Scan the exact branch diff for long API keys, bearer tokens, provider URLs,
installation IDs, machine identifiers, private provider names, and literal
user profile paths.

Expected: no private values and no uncommitted generated files.

**Step 3: Recheck binaries**

Verify:

- New custom binary hash matches the completed build.
- Previous custom binary remains unchanged.
- Current official fallback matches the Task 1 baseline.
- No build process remains running.

**Step 4: Open a new manager-launched Codex session**

Existing sessions remain on the previous executable. Only a newly launched
session should use `codex-clickable-explorer.exe`.

Render one absolute file link and one absolute directory link. The user
Ctrl+clicks each and confirms:

- File Explorer opens the parent and selects the file.
- File Explorer opens the directory.

**Step 5: Merge locally**

After automated and manual verification, merge
`feature/explorer-location-links` into local `main` without rewriting history.
Do not push GitHub, synchronize another computer, or build an APK unless the
user separately requests it.

