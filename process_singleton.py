import json
import os
import subprocess
from pathlib import Path
from typing import Iterable


DEFAULT_MARKERS = (
    "app.py",
    "mobile_portal.py",
    "custom_provider_proxy.py",
    "--custom-provider-proxy",
)


def _normalize_text(value: object) -> str:
    return str(value or "").replace("/", "\\").lower()


def should_cleanup_process(
    *,
    process_id: object,
    command_line: object,
    app_dir: Path,
    current_pid: int,
    protected_pids: Iterable[int] = (),
    markers: Iterable[str] = DEFAULT_MARKERS,
) -> bool:
    try:
        pid = int(process_id)
    except (TypeError, ValueError):
        return False
    if pid == int(current_pid) or pid in {int(item) for item in protected_pids}:
        return False

    normalized_cmd = _normalize_text(command_line)
    if not normalized_cmd:
        return False
    normalized_app_dir = _normalize_text(str(Path(app_dir).resolve()))
    if normalized_app_dir not in normalized_cmd:
        return False

    return any(_normalize_text(marker) in normalized_cmd for marker in markers)


def _list_windows_processes() -> list[dict[str, object]]:
    command = [
        "powershell.exe",
        "-NoProfile",
        "-Command",
        "Get-CimInstance Win32_Process | "
        "Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress",
    ]
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
        creationflags=creationflags,
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        return []
    payload = json.loads(completed.stdout)
    if isinstance(payload, dict):
        return [payload]
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


def cleanup_previous_project_instances(
    *,
    app_dir: Path,
    current_pid: int | None = None,
    protected_pids: Iterable[int] = (),
    markers: Iterable[str] = DEFAULT_MARKERS,
) -> list[int]:
    if os.name != "nt":
        return []
    if os.environ.get("CODEX_SESSION_MANAGER_SKIP_STARTUP_CLEANUP") == "1":
        return []

    current = int(current_pid or os.getpid())
    protected = {int(pid) for pid in protected_pids}
    if hasattr(os, "getppid"):
        protected.add(int(os.getppid()))

    killed: list[int] = []
    for process in _list_windows_processes():
        pid = process.get("ProcessId")
        if not should_cleanup_process(
            process_id=pid,
            command_line=process.get("CommandLine", ""),
            app_dir=app_dir,
            current_pid=current,
            protected_pids=protected,
            markers=markers,
        ):
            continue
        try:
            clean_pid = int(pid)
        except (TypeError, ValueError):
            continue
        subprocess.run(
            ["taskkill.exe", "/PID", str(clean_pid), "/F", "/T"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
        killed.append(clean_pid)
    return killed
