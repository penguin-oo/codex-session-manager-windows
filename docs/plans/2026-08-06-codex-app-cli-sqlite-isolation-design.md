# Codex App and CLI SQLite Isolation Design

## Context

Codex App and the locally patched Codex CLI can carry different SQLite
migration histories. Sharing one SQLite directory allowed the App to migrate
the databases beyond what the CLI understood, which caused migration checksum
and compatibility failures. The user does not require goals, memories, logs,
or other SQLite-backed runtime state to be shared between the App and CLI.

Session JSONL files, authentication, skills, and other file-backed Codex state
remain governed by the existing `CODEX_HOME` behavior. This change isolates
only SQLite-backed runtime state.

## Goals

- Keep Codex App on its normal SQLite location.
- Give every CLI process launched by the session manager one stable CLI-only
  SQLite location.
- Preserve ordinary forward CLI upgrades without version-specific directories.
- Make isolation explicit in local ignored configuration instead of inferring
  it from the presence of a custom executable.
- Keep the custom executable, file opener, and SQLite location fixed for the
  lifetime of one window launch.
- Prevent a global `config.toml` `sqlite_home` value from overriding the
  manager's per-launch CLI isolation.

## Non-Goals

- Synchronizing App and CLI goals, memories, logs, or SQLite metadata.
- Copying or merging App SQLite databases into the CLI database.
- Creating a new SQLite directory for every CLI version.
- Changing Android, mobile portal runtime behavior, remote machines, or GitHub
  release behavior.

## Configuration

The ignored local `mobile_portal_settings.json` supports:

```json
{
  "codex_cli_sqlite_isolation": true,
  "codex_cli_sqlite_home": "%USERPROFILE%\\.codex\\cli-clickable-sqlite"
}
```

Isolation defaults off for public users. When enabled and no explicit path is
set, the manager uses `CODEX_HOME / "cli-clickable-sqlite"`. An explicit path
must resolve to an absolute directory and must differ from the normal
`CODEX_HOME`.

## Launch Architecture

The desktop manager resolves one immutable launch snapshot before creating a
window runtime. The snapshot contains:

- selected executable (healthy custom executable or official fallback);
- configured file opener, only when the custom executable is selected;
- CLI SQLite directory, based only on the explicit isolation setting.

Both runtime creation and command construction consume the same snapshot. This
avoids separate health checks selecting different executable and SQLite
behavior during one launch.

When isolation is enabled, every manager-launched CLI, including the official
fallback, receives the CLI SQLite directory through both:

- `CODEX_SQLITE_HOME` in the process environment;
- a final `-c sqlite_home="..."` command-line override.

The command-line override is authoritative when the user's global
`config.toml` contains a different `sqlite_home`. The stable directory is
reused across normal forward CLI upgrades.

## Existing Data

The current CLI directory is retained as-is. The implementation does not copy,
rename, delete, downgrade, or merge SQLite files. App data remains in the
normal Codex home and CLI data remains in the configured CLI directory.

## Error Handling

- Invalid or relative explicit SQLite paths block the launch with an actionable
  configuration error.
- A path equal to `CODEX_HOME` is rejected when isolation is enabled.
- If the custom executable is unavailable, the manager uses the official CLI
  with the same CLI SQLite isolation.
- Existing runtime cleanup remains responsible only for temporary window
  profiles and never deletes the persistent CLI SQLite directory.

## Testing

- Configuration parsing: default off, enabled default path, explicit absolute
  path, and invalid path rejection.
- Snapshot behavior: one custom executable health decision per launch.
- Fallback behavior: official CLI still receives CLI SQLite isolation.
- Command precedence: `file_opener` and `sqlite_home` overrides are appended
  after existing resume/provider overrides.
- Runtime behavior: `CODEX_SQLITE_HOME` matches the snapshot path.
- Full Python regression suite and secret scan before completion.

