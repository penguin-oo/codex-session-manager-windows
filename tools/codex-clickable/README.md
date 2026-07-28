# Clickable Codex CLI file links

This optional patch adds OSC 8 editor links to local file and directory links rendered by the
Codex TUI. It is intentionally separate from the official Codex installation.

## Compatibility

- Upstream source tag: `rust-v0.144.3`
- Patch file: `codex-0.144.3-clickable-links.patch`
- Supported `file_opener` values: `vscode`, `vscode-insiders`, `windsurf`, `cursor`, and `none`

The visible path text is unchanged. Relative paths are resolved against the conversation working
directory, and `:line[:column]` locations are preserved in the editor URI.

## Security boundary

Only editor URIs generated internally from parsed local paths are trusted. A model-provided
`vscode://`, `cursor://`, or similar URI is not promoted to a clickable terminal link. Existing
`http` and `https` handling remains unchanged. UNC network shares and Windows device namespace
paths remain visible text but are not promoted to editor links.

## Build

Apply the patch from the upstream `codex-rs` directory:

```powershell
git apply --unidiff-zero C:\absolute\path\to\codex-0.144.3-clickable-links.patch
cargo +1.95.0-x86_64-pc-windows-msvc test -p codex-tui markdown_render --lib
cargo +1.95.0-x86_64-pc-windows-msvc test -p codex-tui terminal_hyperlinks --lib
cargo +1.95.0-x86_64-pc-windows-msvc build -p codex-cli --bin codex --release
```

On Windows, run the commands from an x64 Visual Studio developer shell. Keep `CARGO_TARGET_DIR`
on the same drive as the source tree because the `v8` build script otherwise requires cross-drive
symbolic-link privileges.

## Local activation

Keep the custom executable outside the repository, for example:

```text
%USERPROFILE%\.codex\bin\codex-clickable.exe
```

Set the root-level Codex option:

```toml
file_opener = "vscode"
```

Then add the executable override to the local, ignored
`%USERPROFILE%\.codex\mobile_portal_settings.json`:

```json
{
  "codex_executable": "%USERPROFILE%\\.codex\\bin\\codex-clickable.exe"
}
```

The session manager checks `<custom executable> --version` before each cached selection. A missing,
timed-out, or invalid custom executable falls back to the official `codex.cmd`.
