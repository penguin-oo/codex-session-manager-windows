from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import struct
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


RUNTIME_ROOT_NAME = "window_profiles"
MARKER_FILE_NAME = ".launch-id"
MANIFEST_FILE_NAME = "manifest.json"
PID_FILE_NAME = "owner.pid"
DEFAULT_PENDING_GRACE_SECONDS = 60.0
SNAPSHOT_FILE_NAMES = (
    ".codex-global-state.json",
    ".personality_migration",
    "config.toml",
    "models_cache.json",
    "AGENTS.md",
    "session_settings.json",
    "version.json",
)
SHARED_DIRECTORY_NAMES = (
    ".sandbox",
    ".sandbox-bin",
    ".tmp",
    "browser-control",
    "cache",
    "generated_images",
    "log",
    "node_repl",
    "sessions",
    "skills",
    "plugins",
    "rules",
    "memories",
    "prompts",
    "vendor_imports",
)
SHARED_FILE_NAMES = (
    "history.jsonl",
    "memory.jsonl",
    "session_index.jsonl",
)
FILE_ATTRIBUTE_REPARSE_POINT = 0x400
IO_REPARSE_TAG_MOUNT_POINT = 0xA0000003
FSCTL_SET_REPARSE_POINT = 0x000900A4


class WindowRuntimeError(RuntimeError):
    pass


class SessionAlreadyOpenError(WindowRuntimeError):
    def __init__(self, session_id: str) -> None:
        super().__init__(f"Session {session_id} is already open in another writable terminal.")
        self.session_id = session_id


@dataclass(frozen=True)
class WindowRuntime:
    launch_id: str
    runtime_root: Path
    runtime_dir: Path
    codex_home: Path
    sqlite_home: Path
    isolated: bool
    session_id: str

    @property
    def marker_file(self) -> Path:
        return self.runtime_dir / MARKER_FILE_NAME

    @property
    def manifest_file(self) -> Path:
        return self.runtime_dir / MANIFEST_FILE_NAME

    @property
    def pid_file(self) -> Path:
        return self.runtime_dir / PID_FILE_NAME


def _absolute_path(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _is_reparse_point(path: Path) -> bool:
    try:
        attributes = int(getattr(os.lstat(path), "st_file_attributes", 0))
    except OSError:
        return False
    return bool(attributes & FILE_ATTRIBUTE_REPARSE_POINT)


def _validate_runtime_dir(runtime_dir: Path, runtime_root: Path, *, require_marker: bool) -> tuple[Path, Path]:
    root = _absolute_path(runtime_root)
    candidate = _absolute_path(runtime_dir)
    if _is_reparse_point(root):
        raise WindowRuntimeError(f"Runtime root cannot be a reparse point: {root}")
    if candidate.parent != root or candidate == root:
        raise WindowRuntimeError(f"Runtime path is outside the managed root: {candidate}")
    if _is_reparse_point(candidate):
        raise WindowRuntimeError(f"Runtime directory cannot be a reparse point: {candidate}")
    if require_marker:
        marker = candidate / MARKER_FILE_NAME
        try:
            marker_value = marker.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise WindowRuntimeError(f"Runtime marker is missing: {candidate}") from exc
        if marker_value != candidate.name:
            raise WindowRuntimeError(f"Runtime marker does not match its directory: {candidate}")
    return candidate, root


def _remove_tree_without_following_links(path: Path) -> None:
    if not path.exists() and not path.is_symlink():
        return
    if path.is_symlink():
        path.unlink()
        return
    if _is_reparse_point(path):
        os.rmdir(path)
        return
    if path.is_dir():
        with os.scandir(path) as entries:
            children = [Path(entry.path) for entry in entries]
        for child in children:
            _remove_tree_without_following_links(child)
        try:
            path.rmdir()
        except PermissionError:
            path.chmod(stat.S_IWRITE)
            path.rmdir()
        return
    try:
        path.unlink()
    except PermissionError:
        path.chmod(stat.S_IWRITE)
        path.unlink()


def cleanup_window_runtime(runtime_dir: Path, runtime_root: Path) -> None:
    candidate, _root = _validate_runtime_dir(runtime_dir, runtime_root, require_marker=True)
    _remove_tree_without_following_links(candidate)


def is_process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        process_query_limited_information = 0x1000
        still_active = 259
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            return ctypes.get_last_error() == 5
        try:
            exit_code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == still_active
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _read_manifest(runtime_dir: Path) -> dict[str, object] | None:
    try:
        payload = json.loads((runtime_dir / MANIFEST_FILE_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _read_owner_pid(runtime_dir: Path) -> int:
    try:
        return int((runtime_dir / PID_FILE_NAME).read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return 0


def cleanup_stale_window_runtimes(
    base_home: Path,
    *,
    now: float | None = None,
    process_alive: Callable[[int], bool] = is_process_alive,
    pending_grace_seconds: float = DEFAULT_PENDING_GRACE_SECONDS,
) -> list[Path]:
    runtime_root = _absolute_path(base_home) / RUNTIME_ROOT_NAME
    if not runtime_root.exists():
        return []
    current_time = time.time() if now is None else float(now)
    removed: list[Path] = []
    for runtime_dir in list(runtime_root.iterdir()):
        if not runtime_dir.is_dir() or _is_reparse_point(runtime_dir):
            continue
        manifest = _read_manifest(runtime_dir)
        if manifest is None:
            continue
        try:
            created_at = float(manifest.get("created_at", 0.0))
        except (TypeError, ValueError):
            created_at = 0.0
        pid = _read_owner_pid(runtime_dir)
        if pid > 0:
            stale = not process_alive(pid)
        else:
            stale = current_time - created_at > pending_grace_seconds
        if not stale:
            continue
        try:
            cleanup_window_runtime(runtime_dir, runtime_root)
        except (OSError, WindowRuntimeError):
            continue
        removed.append(runtime_dir)
    return removed


def _active_session_ids(
    runtime_root: Path,
    *,
    now: float,
    process_alive: Callable[[int], bool],
    pending_grace_seconds: float,
) -> set[str]:
    active: set[str] = set()
    if not runtime_root.exists():
        return active
    for runtime_dir in runtime_root.iterdir():
        if not runtime_dir.is_dir() or _is_reparse_point(runtime_dir):
            continue
        manifest = _read_manifest(runtime_dir)
        if manifest is None:
            continue
        session_id = str(manifest.get("session_id", "")).strip()
        if not session_id:
            continue
        pid = _read_owner_pid(runtime_dir)
        try:
            created_at = float(manifest.get("created_at", 0.0))
        except (TypeError, ValueError):
            created_at = 0.0
        if (pid > 0 and process_alive(pid)) or (
            pid <= 0 and now - created_at <= pending_grace_seconds
        ):
            active.add(session_id)
    return active


def _copy_snapshot_files(base_home: Path, private_home: Path) -> None:
    for file_name in SNAPSHOT_FILE_NAMES:
        source = base_home / file_name
        if source.is_file():
            shutil.copy2(source, private_home / file_name)


def _share_files(base_home: Path, private_home: Path) -> None:
    for file_name in SHARED_FILE_NAMES:
        source = base_home / file_name
        if not source.is_file():
            continue
        destination = private_home / file_name
        os.link(source, destination)


def _create_windows_junction(link: Path, target: Path) -> None:
    """Create a directory junction without starting a shell process."""
    import ctypes
    from ctypes import wintypes

    target_text = os.fspath(_absolute_path(target))
    if target_text.startswith("\\\\"):
        substitute_name = "\\??\\UNC" + target_text[1:]
    else:
        substitute_name = "\\??\\" + target_text
    substitute_bytes = substitute_name.encode("utf-16-le")
    print_bytes = target_text.encode("utf-16-le")
    path_buffer = substitute_bytes + b"\x00\x00" + print_bytes + b"\x00\x00"
    reparse_buffer = struct.pack(
        "<LHHHHHH",
        IO_REPARSE_TAG_MOUNT_POINT,
        8 + len(path_buffer),
        0,
        0,
        len(substitute_bytes),
        len(substitute_bytes) + 2,
        len(print_bytes),
    ) + path_buffer

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.DeviceIoControl.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    ]
    kernel32.DeviceIoControl.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    generic_write = 0x40000000
    open_existing = 3
    file_flag_open_reparse_point = 0x00200000
    file_flag_backup_semantics = 0x02000000
    invalid_handle_value = ctypes.c_void_p(-1).value
    link.mkdir()
    handle = kernel32.CreateFileW(
        os.fspath(link),
        generic_write,
        0,
        None,
        open_existing,
        file_flag_open_reparse_point | file_flag_backup_semantics,
        None,
    )
    if handle == invalid_handle_value:
        error_code = ctypes.get_last_error()
        link.rmdir()
        raise ctypes.WinError(error_code)
    try:
        input_buffer = ctypes.create_string_buffer(reparse_buffer)
        bytes_returned = wintypes.DWORD()
        succeeded = kernel32.DeviceIoControl(
            handle,
            FSCTL_SET_REPARSE_POINT,
            input_buffer,
            len(reparse_buffer),
            None,
            0,
            ctypes.byref(bytes_returned),
            None,
        )
        if not succeeded:
            raise ctypes.WinError(ctypes.get_last_error())
    except Exception:
        kernel32.CloseHandle(handle)
        link.rmdir()
        raise
    kernel32.CloseHandle(handle)


def _create_windows_junctions_with_cmd(pairs: list[tuple[Path, Path]], private_home: Path) -> None:
    batch_file = private_home.parent / "create-directory-links.cmd"
    lines = ["@echo off"]
    for link, target in pairs:
        link_text = os.fspath(link).replace("%", "%%")
        target_text = os.fspath(target).replace("%", "%%")
        lines.append(f'mklink /J "{link_text}" "{target_text}" >nul || exit /b 1')
    batch_file.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
    try:
        result = subprocess.run(
            [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", os.fspath(batch_file)],
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        batch_file.unlink(missing_ok=True)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise WindowRuntimeError(f"Unable to create shared runtime directories: {detail}")


def _create_directory_links(base_home: Path, private_home: Path) -> None:
    pairs = [
        (private_home / name, base_home / name)
        for name in SHARED_DIRECTORY_NAMES
        if (base_home / name).is_dir()
    ]
    if not pairs:
        return
    if os.name != "nt":
        for link, target in pairs:
            os.symlink(target, link, target_is_directory=True)
        return
    created: list[Path] = []
    try:
        for link, target in pairs:
            _create_windows_junction(link, target)
            created.append(link)
        return
    except OSError:
        for link in reversed(created):
            os.rmdir(link)
    _create_windows_junctions_with_cmd(pairs, private_home)


def _baseline_installation_id(base_home: Path, explicit_id: str) -> str:
    clean_explicit = str(explicit_id or "").strip()
    if clean_explicit:
        return clean_explicit
    for file_name in ("installation_id.original", "installation_id"):
        try:
            value = (base_home / file_name).read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if value:
            return value
    generated = str(uuid.uuid4())
    installation_file = base_home / "installation_id"
    try:
        with installation_file.open("x", encoding="utf-8") as handle:
            handle.write(generated + "\n")
    except FileExistsError:
        try:
            existing = installation_file.read_text(encoding="utf-8").strip()
        except OSError:
            existing = ""
        if existing:
            return existing
    except OSError:
        pass
    return generated


def _write_manifest(runtime: WindowRuntime, created_at: float) -> None:
    payload = {
        "launch_id": runtime.launch_id,
        "session_id": runtime.session_id,
        "created_at": created_at,
        "isolated": runtime.isolated,
    }
    temporary = runtime.manifest_file.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    temporary.replace(runtime.manifest_file)


def prepare_window_runtime(
    base_home: Path,
    *,
    isolate_home: bool,
    sqlite_home: Path | None = None,
    session_id: str = "",
    installation_id: str = "",
    launch_id: str | None = None,
    now: float | None = None,
    process_alive: Callable[[int], bool] = is_process_alive,
    pending_grace_seconds: float = DEFAULT_PENDING_GRACE_SECONDS,
) -> WindowRuntime:
    base_home = _absolute_path(base_home)
    base_home.mkdir(parents=True, exist_ok=True)
    sqlite_home_path = _absolute_path(sqlite_home) if sqlite_home is not None else base_home
    sqlite_home_path.mkdir(parents=True, exist_ok=True)
    runtime_root = base_home / RUNTIME_ROOT_NAME
    runtime_root.mkdir(parents=True, exist_ok=True)
    if _is_reparse_point(runtime_root):
        raise WindowRuntimeError(f"Runtime root cannot be a reparse point: {runtime_root}")
    current_time = time.time() if now is None else float(now)
    cleanup_stale_window_runtimes(
        base_home,
        now=current_time,
        process_alive=process_alive,
        pending_grace_seconds=pending_grace_seconds,
    )
    clean_session_id = str(session_id or "").strip()
    if clean_session_id and clean_session_id in _active_session_ids(
        runtime_root,
        now=current_time,
        process_alive=process_alive,
        pending_grace_seconds=pending_grace_seconds,
    ):
        raise SessionAlreadyOpenError(clean_session_id)

    clean_launch_id = str(launch_id or uuid.uuid4()).strip()
    if not clean_launch_id or clean_launch_id in {".", ".."}:
        raise WindowRuntimeError("Launch ID cannot be empty.")
    runtime_dir = runtime_root / clean_launch_id
    if _absolute_path(runtime_dir).parent != _absolute_path(runtime_root):
        raise WindowRuntimeError("Launch ID must be a single path component.")
    runtime_dir.mkdir()
    runtime = WindowRuntime(
        launch_id=clean_launch_id,
        runtime_root=runtime_root,
        runtime_dir=runtime_dir,
        codex_home=runtime_dir / "home" if isolate_home else base_home,
        sqlite_home=sqlite_home_path,
        isolated=bool(isolate_home),
        session_id=clean_session_id,
    )
    try:
        runtime.marker_file.write_text(clean_launch_id + "\n", encoding="utf-8")
        _write_manifest(runtime, current_time)
        if runtime.isolated:
            runtime.codex_home.mkdir()
            _copy_snapshot_files(base_home, runtime.codex_home)
            _share_files(base_home, runtime.codex_home)
            _create_directory_links(base_home, runtime.codex_home)
            (runtime.codex_home / "installation_id").write_text(
                _baseline_installation_id(base_home, installation_id) + "\n",
                encoding="utf-8",
            )
        return runtime
    except Exception:
        try:
            cleanup_window_runtime(runtime_dir, runtime_root)
        except (OSError, WindowRuntimeError):
            pass
        raise


def _powershell_quote(value: str | Path) -> str:
    return "'" + os.fspath(value).replace("'", "''") + "'"


def build_runtime_powershell_wrapper(
    inner_command: str,
    *,
    runtime: WindowRuntime,
    python_executable: Path | None = None,
    helper_path: Path | None = None,
    cleanup_command: list[str | Path] | None = None,
) -> str:
    pid_file = _powershell_quote(runtime.pid_file)
    codex_home = _powershell_quote(runtime.codex_home)
    sqlite_home = _powershell_quote(runtime.sqlite_home)
    if cleanup_command is None:
        if python_executable is None or helper_path is None:
            raise ValueError("A cleanup command or Python helper paths are required.")
        command_parts: list[str | Path] = [python_executable, helper_path, "cleanup"]
    else:
        command_parts = list(cleanup_command)
    command_parts.extend(
        [
            "--runtime-root",
            runtime.runtime_root,
            "--runtime-dir",
            runtime.runtime_dir,
        ]
    )
    cleanup_args = " ".join(_powershell_quote(part) for part in command_parts)
    return (
        f"[System.IO.File]::WriteAllText({pid_file}, [string]$PID); "
        f"$env:CODEX_HOME = {codex_home}; "
        f"$env:CODEX_SQLITE_HOME = {sqlite_home}; "
        f"try {{ {inner_command} }} "
        f"finally {{ & {cleanup_args} | Out-Null }}"
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    cleanup = subparsers.add_parser("cleanup")
    cleanup.add_argument("--runtime-root", required=True, type=Path)
    cleanup.add_argument("--runtime-dir", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "cleanup":
        cleanup_window_runtime(args.runtime_dir, args.runtime_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
