# Clickable CLI File Links Design

## Goal

Make local file and directory references in Codex CLI responses open in the
configured editor when the user presses Ctrl and left-clicks the rendered path.
File references with a line and column must open at that location. Directory
references must open the directory.

## Safety Boundaries

- Do not replace, modify, rename, or delete the official `codex.cmd` or
  `codex.exe`.
- Do not stop or alter existing Codex processes.
- Build a separate executable from the exact installed Codex source version.
- Validate the separate executable before selecting it. Fall back to the
  official `codex.cmd` if it is missing, invalid, or cannot report its version.
- Do not start an HTTP service or open a network port.
- Do not store local executable paths, credentials, provider URLs, tokens,
  installation IDs, or machine identifiers in the repository.

## Architecture

The Codex TUI patch will preserve the destination of a local Markdown file link
as a semantic terminal hyperlink. It will convert the normalized absolute path
and optional line and column into the URI scheme selected by `file_opener`.

Only editor schemes represented by Codex's existing `file_opener` allowlist are
eligible: `vscode`, `vscode-insiders`, `cursor`, and `windsurf`. `none` produces
plain path text. Arbitrary model-provided URI schemes remain blocked.

The patched binary will be installed outside the repository at:

`%USERPROFILE%\.codex\bin\codex-clickable.exe`

The desktop manager will support a generic local `codex_executable` override in:

`%USERPROFILE%\.codex\mobile_portal_settings.json`

The manager will use that executable only after a local health check succeeds.
Otherwise, its existing `shutil.which("codex.cmd")` resolution remains the
fallback. Public source code contains only the generic override mechanism, not
the local path.

## Link Behavior

- An absolute file path opens the file in the selected editor.
- `:line` and `:line:column` suffixes open the matching location.
- A directory path opens the directory in the selected editor.
- Relative link targets are resolved against the conversation working
  directory before creating the editor URI.
- Visible response text remains a normal local path; the editor URI exists only
  in the terminal hyperlink metadata.

## Tests

Codex Rust tests will prove that:

- Windows and POSIX file paths produce the expected editor URI.
- Line and column suffixes are preserved.
- Directory targets use the same safe editor URI path.
- `none` disables the hyperlink.
- Unsupported or model-supplied URI schemes are not accepted.
- The rendered terminal output contains OSC 8 metadata while preserving visible
  path text.

Project Python tests will prove that:

- A healthy configured executable is selected.
- A missing, invalid, or failing executable falls back to official
  `codex.cmd`.
- No private executable path is embedded in the repository.

Final verification will include the focused Rust and Python tests, a release
build, `--version` health checks for both executables, the complete project test
suite, and inspection of generated OSC 8 bytes. The official executable hashes
will be recorded before and after the work and must remain unchanged.
