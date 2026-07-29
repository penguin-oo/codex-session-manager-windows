# Clickable Codex CLI file links

This optional patch adds OSC 8 links for local files and directories rendered
by the Codex TUI. It remains separate from the official Codex installation.

## Compatibility

- Upstream source tag: `rust-v0.144.3`
- Patch file: `codex-0.144.3-clickable-links.patch`
- Supported `file_opener` values: `vscode`, `vscode-insiders`, `windsurf`,
  `cursor`, `explorer`, and `none`

Editor modes preserve `:line[:column]` locations. The Windows-only `explorer`
mode instead removes line and column suffixes, reveals a file in its parent
folder, and opens a directory directly.

## Security boundary

Only links generated internally from parsed local paths are trusted. Explorer
mode accepts local fixed-drive paths through a private `codex-location` URI
handler. It rejects URI hosts, queries, fragments, UNC paths, device paths,
alternate data streams, control characters, shell expansion, and unowned
protocol registrations. Existing `http` and `https` handling is unchanged.

The protocol is registered only for the current Windows user. It launches
Windows File Explorer directly without `cmd.exe` or `Invoke-Expression`.

## Build

Apply the patch from an upstream `codex-rs` directory:

```powershell
git apply --unidiff-zero C:\absolute\path\to\codex-0.144.3-clickable-links.patch
cargo +1.95.0-x86_64-pc-windows-msvc test -p codex-config UriBasedFileOpener --lib
cargo +1.95.0-x86_64-pc-windows-msvc test -p codex-tui markdown_render --lib
cargo +1.95.0-x86_64-pc-windows-msvc test -p codex-tui terminal_hyperlinks --lib
cargo +1.95.0-x86_64-pc-windows-msvc build -p codex-cli --bin codex --release
```

Use an x64 Visual Studio developer shell. Keep `CARGO_TARGET_DIR` on the same
drive as the source tree when the `v8` build script cannot create cross-drive
symbolic links.

## Explorer activation

Install the handler from this directory:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install-codex-location-handler.ps1
```

Then set the root-level Codex option:

```toml
file_opener = "explorer"
```

Keep the custom executable outside the repository and point the session
manager's local ignored settings at it. The manager health-checks the override
and falls back to the official `codex.cmd` when it is unavailable or invalid.
Existing Codex processes keep their current executable.

Inspect or remove the current-user protocol registration with:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install-codex-location-handler.ps1 -Mode Inspect
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install-codex-location-handler.ps1 -Mode Uninstall
```

Explorer links require no Android change, mobile service, network port, or
remote API. To roll back, set `file_opener` to the previous value, restore the
previous custom executable override, and uninstall the protocol handler.
