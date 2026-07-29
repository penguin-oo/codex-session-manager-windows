# Explorer Location Links Design

## Goal

Change local links rendered by the separate Codex CLI build so that:

- A file link opens Windows File Explorer at its parent directory and selects
  the file.
- A directory link opens that directory in Windows File Explorer.
- Android, mobile portal, presets, conversations, providers, and network
  routing remain unchanged.

## Selected Approach

Add an explicit `explorer` value to the patched Codex `file_opener` enum. Local
Markdown links rendered under that mode will use a private local URI scheme:

```text
codex-location:///D:/path/to/item
```

A small Windows protocol handler will decode the URI, validate the local path,
and launch File Explorer. The handler will be installed only for the current
user under `HKCU\Software\Classes`; it will not require administrator rights.

This is preferable to `file://` because Windows normally opens a file with its
associated application instead of revealing and selecting it. It is preferable
to reusing `vscode://` because doing so would hijack the real VS Code protocol.

## Codex TUI Changes

The existing clickable-link patch will be extended rather than replaced.

- `file_opener = "explorer"` selects the local location protocol.
- File line and column suffixes are removed from Explorer destinations.
- Visible Markdown text remains unchanged.
- Relative links continue to resolve against the conversation working
  directory.
- Existing `vscode`, `vscode-insiders`, `cursor`, `windsurf`, and `none`
  behavior remains available.
- Model-provided protocol links cannot invoke the local handler. Only a URI
  produced internally from a parsed local Markdown path is eligible.

## Windows Protocol Handler

The repository will contain generic public scripts for installing and handling
the protocol. Local installation will copy the handler below the user's Codex
home and register a command for the current user.

The handler will:

1. Accept exactly one `codex-location` URI.
2. Percent-decode its path without environment-variable or shell expansion.
3. Normalize separators and require a drive-letter absolute path.
4. Reject UNC paths, Windows device namespaces, quotes, control characters,
   and malformed URIs.
5. For an existing directory, launch File Explorer with that directory.
6. For an existing file, launch File Explorer with `/select` for that file.
7. For a missing file target, open its existing parent without executing the
   target.
8. Invoke only the system File Explorer executable and never evaluate command
   text.

If the URI handler is unavailable, the terminal may report that the protocol
cannot be opened. The visible local path remains available for manual use.

## Activation and Rollback

Before activation:

- Back up the current Codex config.
- Export any existing current-user `codex-location` registry key.
- Record the installed custom binary hash.

Activation will:

- Install the handler under the local Codex bin directory.
- Register the current-user URI protocol.
- Set `file_opener = "explorer"` in the local Codex config.
- Install the rebuilt CLI under a new separate filename and update the local
  `codex_executable` override only after the new binary passes health checks.
  Existing Codex processes and the previous separate binary remain untouched.

The official Codex installation will not be modified. The desktop manager's
existing health check and fallback remain in place.

Rollback will restore the config backup, unregister or restore the previous
current-user protocol key, and point `codex_executable` back to the previous
separate custom binary.

## Testing

Rust tests will cover:

- Parsing `explorer` as a supported opener.
- File, directory, relative, spaced, and non-ASCII local paths.
- Removing line and column suffixes from Explorer URIs.
- Rejecting UNC, device-namespace, arbitrary-scheme, and malformed paths.
- Preserving all existing editor URI behavior.
- Rendering OSC 8 metadata while keeping visible path text unchanged.

Handler tests will cover:

- URI decoding and path normalization.
- File selection and directory opening command construction.
- Missing-target fallback.
- Rejection of network, device, quoted, and control-character paths.
- No command execution during parser tests.

Final verification will include the complete project test suite, focused and
full Codex TUI tests compared with the unmodified baseline, a release build,
custom and official CLI health checks, protocol registration inspection, and a
manual Ctrl+click check for one file and one directory.

