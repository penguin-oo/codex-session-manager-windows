import base64
import functools
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import threading
import tomllib
import tkinter as tk
import webbrowser
import auth_slots
import custom_provider_proxy
import mobile_portal
import process_singleton
import remote_ssh
import token_pool_proxy
import token_pool_settings
import window_runtime
from dataclasses import dataclass, replace
from datetime import datetime
import uuid
from pathlib import Path
from tkinter import font
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Callable, Iterable
from urllib import error as url_error
from urllib import parse as url_parse
from urllib import request as url_request


APP_TITLE = "Codex+"
CODEX_HOME = Path(os.environ.get("USERPROFILE", "")) / ".codex"
HISTORY_FILE = CODEX_HOME / "history.jsonl"
NOTES_FILE = CODEX_HOME / "session_notes.json"
SESSIONS_DIR = CODEX_HOME / "sessions"
CONFIG_FILE = CODEX_HOME / "config.toml"
PORTAL_SETTINGS_FILE = CODEX_HOME / "mobile_portal_settings.json"
MODELS_CACHE_FILE = CODEX_HOME / "models_cache.json"
SKILLS_DIR = CODEX_HOME / "skills"
PORTAL_TOKEN_FILE = CODEX_HOME / "mobile_portal_token.txt"
DESKTOP_REFRESH_SIGNAL_FILE = CODEX_HOME / "desktop_refresh_signal.json"
TOKEN_POOL_PROXY_STATE_FILE = CODEX_HOME / "token_pool_proxy_state.json"
PORTAL_BASE_URL = "http://127.0.0.1:8765"
APP_DIR = Path(__file__).resolve().parent
AUTO_REFRESH_MS = 2500
DESKTOP_SIGNAL_POLL_MS = 500
PORTAL_TIMEOUT_SECONDS = 0.25
read_token_pool_token_quota = mobile_portal.read_token_pool_token_quota
PORTAL_BACKOFF_SECONDS = 5.0
MAX_DESKTOP_STATUS_CHARS = 180
ACCOUNT_STATUS_DISPLAY_LIMIT = 72
LOGIN_PROGRESS_IS_MODAL = False
TERMINAL_PROXY_SCHEMES = ("http", "socks5", "socks5h")
DEFAULT_NO_PROXY = "localhost,127.0.0.1,::1,.local,.ts.net"
TOKEN_POOL_PROVIDER_NAME = "built_in_token_pool"
TOKEN_POOL_ENV_KEY_NAME = "CODEX_TOKEN_POOL_API_KEY"
OPENAI_COMPAT_PROVIDER_NAME = "openai_compatible"
DERIVED_SESSION_FILE_MARKERS = (
    ".context-overflow-backup-",
    ".restore-current-backup-",
    ".merged-restore-candidate-",
    ".full-restored-archive-",
    ".lightweight-memory-candidate-",
    ".memory-recovery-",
)
OPENAI_COMPAT_ENV_KEY_NAME = "CODEX_OPENAI_COMPATIBLE_API_KEY"
CODEX_OFFICIAL_PROVIDER_NAME = "openai"
CODEX_API_ENV_KEY_NAMES = (
    "CODEX_API_KEY",
    "OPENAI_API_KEY",
    TOKEN_POOL_ENV_KEY_NAME,
    OPENAI_COMPAT_ENV_KEY_NAME,
)
OPENAI_API_KEY_ENTRY_SHOW = ""
DEFAULT_PRIMARY_MODEL = "gpt-5.6-sol"
DEFAULT_LAUNCH_MODEL = DEFAULT_PRIMARY_MODEL
DEFAULT_LAUNCH_APPROVAL = "never"
DEFAULT_LAUNCH_SANDBOX = "danger-full-access"
DEFAULT_LAUNCH_REASONING_EFFORT = "max"
DEFAULT_LAUNCH_ADMIN = False
CODEX_VERSION_PATTERN = re.compile(r"^codex-cli\s+\d+\.\d+\.\d+(?:[-+][^\s]+)?$")
CODEX_FILE_OPENERS = frozenset(
    {"vscode", "vscode-insiders", "windsurf", "cursor", "explorer", "none"}
)
FALLBACK_MODEL_OPTIONS = (
    DEFAULT_PRIMARY_MODEL,
    "gpt-5.6-luna",
    "gpt-5.6-terra",
    "gpt-5.5",
    "gpt-5.4",
    "gpt-5.3-codex",
    "gpt-5.2",
    "gpt-5",
)


NOTE_URL_RE = re.compile(r"https?://[^\s<>'\"，。；、）)]+" )
NOTE_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")
LOGIN_AUTH_URL_RE = re.compile(r"https://auth\.openai\.com/[^\s]+")
LOGIN_DEVICE_CODE_RE = re.compile(r"\b[A-Z0-9]{4}-[A-Z0-9]{5}\b")


def default_launch_options() -> dict[str, str]:
    return {
        "model": DEFAULT_LAUNCH_MODEL,
        "approval": DEFAULT_LAUNCH_APPROVAL,
        "sandbox": DEFAULT_LAUNCH_SANDBOX,
        "reasoning_effort": DEFAULT_LAUNCH_REASONING_EFFORT,
    }


def default_launch_model_choice(values: list[str] | tuple[str, ...]) -> str:
    return DEFAULT_LAUNCH_MODEL if DEFAULT_LAUNCH_MODEL in values else "default"


def find_note_references(text: str) -> list[dict[str, object]]:
    references: list[dict[str, object]] = []
    occupied: list[tuple[int, int]] = []
    for match in NOTE_URL_RE.finditer(text or ""):
        value = match.group(0).rstrip(".,;:!?")
        start = match.start()
        end = start + len(value)
        references.append({"kind": "url", "value": value, "start": start, "end": end})
        occupied.append((start, end))
    for match in NOTE_EMAIL_RE.finditer(text or ""):
        start, end = match.span()
        if any(start < occupied_end and end > occupied_start for occupied_start, occupied_end in occupied):
            continue
        references.append({"kind": "email", "value": match.group(0), "start": start, "end": end})
    return sorted(references, key=lambda item: int(item["start"]))


def _private_browser_executable() -> Path | None:
    candidates = [
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        Path(os.environ.get("ProgramFiles", "")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        Path(os.environ.get("ProgramFiles", "")) / "Google" / "Chrome" / "Application" / "chrome.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Google" / "Chrome" / "Application" / "chrome.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "Application" / "chrome.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def build_private_browser_login_env(base_env: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(base_env or os.environ)
    browser = _private_browser_executable()
    private_root = Path(tempfile.mkdtemp(prefix="codex-login-private-"))
    profile_dir = private_root / "profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    launcher = private_root / "open-private-browser.cmd"
    if browser is not None:
        private_flag = "--inprivate" if "edge" in browser.name.lower() or "msedge" in browser.name.lower() else "--incognito"
        browser_command = f'"{browser}"'
    else:
        private_flag = "--inprivate"
        browser_command = "msedge"
    launcher.write_text(
        "\n".join(
            [
                "@echo off",
                f"set CODEX_PRIVATE_PROFILE={profile_dir}",
                f'start "" {browser_command} {private_flag} --user-data-dir="%CODEX_PRIVATE_PROFILE%" --no-first-run --disable-first-run-ui %*',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    env["BROWSER"] = str(launcher)
    env["CODEX_LOGIN_PRIVATE_PROFILE_DIR"] = str(profile_dir)
    env["CODEX_LOGIN_PRIVATE_LAUNCHER"] = str(launcher)
    env["CODEX_LOGIN_PRIVATE_BROWSER"] = "1"
    return env


def normalize_proxy_for_codex_device_auth(proxy_url: str) -> str:
    clean = str(proxy_url or "").strip()
    if clean.lower().startswith(("socks5h://", "socks5://")):
        return "http://" + clean.split("://", 1)[1]
    return clean


def apply_login_proxy_env(env: dict[str, str], *, enabled: bool, scheme: str, host: str, port_text: str) -> None:
    if not enabled:
        return
    clean_scheme = (scheme or "").strip().lower() or "http"
    clean_host = (host or "").strip() or "127.0.0.1"
    try:
        clean_port = int(str(port_text).strip())
    except ValueError:
        clean_port = 7897
    proxy_url = normalize_proxy_for_codex_device_auth(f"{clean_scheme}://{clean_host}:{clean_port}")
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        env[key] = proxy_url
    env["NO_PROXY"] = DEFAULT_NO_PROXY
    env["no_proxy"] = DEFAULT_NO_PROXY


def strip_ansi(text: str) -> str:
    return ANSI_ESCAPE_RE.sub("", text or "")


def find_login_auth_url(text: str) -> str:
    match = LOGIN_AUTH_URL_RE.search(strip_ansi(text))
    return match.group(0) if match else ""


def find_login_device_code(text: str) -> str:
    match = LOGIN_DEVICE_CODE_RE.search(strip_ansi(text))
    return match.group(0) if match else ""


def launch_private_login_url(url: str, env: dict[str, str] | None) -> None:
    if not url or not env:
        return
    launcher = str(env.get("CODEX_LOGIN_PRIVATE_LAUNCHER", "") or "").strip()
    if not launcher:
        return
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW") else 0
    try:
        if os.name == "nt":
            subprocess.Popen(["cmd.exe", "/c", launcher, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=creationflags)
        else:
            subprocess.Popen([launcher, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


def collect_login_process_output(
    process: subprocess.Popen[str],
    *,
    private_env: dict[str, str] | None = None,
    on_update: Callable[[str, str], None] | None = None,
) -> str:
    chunks: list[str] = []
    opened_url = False
    stream = process.stdout
    if stream is None:
        return ""
    for line in stream:
        chunks.append(line)
        clean_line = strip_ansi(line)
        if on_update is not None:
            on_update("line", clean_line)
        if private_env and not opened_url:
            url = find_login_auth_url(clean_line)
            if url:
                launch_private_login_url(url, private_env)
                opened_url = True
                if on_update is not None:
                    on_update("url", url)
        code = find_login_device_code(clean_line)
        if code and on_update is not None:
            on_update("code", code)
    process.wait()
    return "".join(chunks)


def cleanup_private_browser_login_env(env: dict[str, str] | None) -> None:
    if not env:
        return
    launcher_raw = str(env.get("CODEX_LOGIN_PRIVATE_LAUNCHER", "") or "").strip()
    profile_raw = str(env.get("CODEX_LOGIN_PRIVATE_PROFILE_DIR", "") or "").strip()
    launcher = Path(launcher_raw) if launcher_raw else None
    profile_root = Path(profile_raw).parent if profile_raw else None
    for target in (launcher, profile_root):
        if not target:
            continue
        try:
            if target.is_file():
                target.unlink()
            elif target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
        except OSError:
            pass


_INSTALLATION_ID_PATH = Path.home() / ".codex" / "installation_id"
_INSTALLATION_ID_ORIGINAL_PATH = Path.home() / ".codex" / "installation_id.original"


def _swap_installation_id_for_preset(preset: dict[str, object]) -> None:
    """Apply or restore ~/.codex/installation_id from preset metadata."""
    target_id = str(preset.get("installation_id", "")).strip()
    try:
        if target_id:
            if _INSTALLATION_ID_PATH.is_file() and not _INSTALLATION_ID_ORIGINAL_PATH.is_file():
                shutil.copy2(str(_INSTALLATION_ID_PATH), str(_INSTALLATION_ID_ORIGINAL_PATH))
            _INSTALLATION_ID_PATH.write_text(target_id, encoding="utf-8")
        else:
            if _INSTALLATION_ID_ORIGINAL_PATH.is_file():
                shutil.copy2(str(_INSTALLATION_ID_ORIGINAL_PATH), str(_INSTALLATION_ID_PATH))
    except OSError:
        pass


_CLAUDE_SETTINGS_PATH = Path.home() / ".claude" / "settings.json"
_CLAUDE_MANAGED_ENV_PATH = Path.home() / ".codex" / "claude_managed_env_keys.json"


def _patch_claude_settings_for_preset(preset: dict[str, object]) -> None:
    """Apply preset-managed Claude env vars and remove previous managed keys."""
    raw_target_env = preset.get("claude_env", {})
    target_env = token_pool_settings.normalize_string_map(raw_target_env)
    try:
        if not _CLAUDE_SETTINGS_PATH.is_file():
            return
        raw = _CLAUDE_SETTINGS_PATH.read_text(encoding="utf-8-sig")
        settings = json.loads(raw)
        env = settings.get("env")
        if not isinstance(env, dict):
            env = {}
            settings["env"] = env
        changed = False
        managed_keys: list[str] = []
        if _CLAUDE_MANAGED_ENV_PATH.is_file():
            try:
                loaded = json.loads(_CLAUDE_MANAGED_ENV_PATH.read_text(encoding="utf-8-sig"))
                if isinstance(loaded, list):
                    managed_keys = [str(item).strip() for item in loaded if str(item).strip()]
            except (OSError, json.JSONDecodeError):
                managed_keys = []
        for k in managed_keys:
            if k not in target_env and env.get(k) is not None:
                if k in env:
                    del env[k]
                    changed = True
        for k, v in target_env.items():
            if env.get(k) != v:
                env[k] = v
                changed = True
        if changed:
            _CLAUDE_SETTINGS_PATH.write_text(
                json.dumps(settings, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        _CLAUDE_MANAGED_ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
        if target_env:
            _CLAUDE_MANAGED_ENV_PATH.write_text(json.dumps(sorted(target_env), indent=2), encoding="utf-8")
        elif _CLAUDE_MANAGED_ENV_PATH.exists():
            _CLAUDE_MANAGED_ENV_PATH.unlink()
    except (OSError, json.JSONDecodeError):
        pass


_CODEX_CONFIG_PATH = Path.home() / ".codex" / "config.toml"


def _patch_image_generation_for_preset(preset: dict[str, object]) -> None:
    _patch_image_generation_disabled(bool(preset.get("disable_image_generation", False)))


def _patch_image_generation_for_backend_mode(backend_mode: str) -> None:
    if backend_mode != token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE:
        _patch_image_generation_disabled(False)


def _patch_image_generation_disabled(should_disable: bool) -> None:
    try:
        if not _CODEX_CONFIG_PATH.exists():
            if not should_disable:
                return
            _CODEX_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            _CODEX_CONFIG_PATH.write_text("[features]\nimage_generation = false\n", encoding="utf-8")
            return
        text = _CODEX_CONFIG_PATH.read_text(encoding="utf-8-sig")
        lines = text.splitlines(keepends=True)
        has_line = any(line.strip().startswith("image_generation") for line in lines)
        if should_disable:
            new_lines = []
            added = False
            for line in lines:
                stripped = line.strip()
                if stripped.startswith("image_generation"):
                    continue
                new_lines.append(line)
                if not added and stripped == "[features]":
                    new_lines.append("image_generation = false\n")
                    added = True
            if not added:
                suffix = "" if not text or text.endswith(("\n", "\r")) else "\n"
                new_lines = [f"{text}{suffix}", "[features]\n", "image_generation = false\n"]
            new_text = "".join(new_lines)
            if new_text != text:
                _CODEX_CONFIG_PATH.write_text(new_text, encoding="utf-8")
        elif not should_disable and has_line:
            new_lines = [line for line in lines if not line.strip().startswith("image_generation")]
            _CODEX_CONFIG_PATH.write_text("".join(new_lines), encoding="utf-8")
    except OSError:
        pass


@dataclass
class SessionItem:
    session_id: str
    ts: int
    text: str
    note: str
    history_count: int
    cwd: str
    model: str
    approval_policy: str
    sandbox_mode: str
    turn_id: str
    session_file: str


@dataclass
class McpItem:
    name: str
    command: str
    timeout: str
    env_count: int
    args: str


@dataclass
class SkillItem:
    name: str
    path: str
    has_scripts: bool
    summary: str


def path_signature(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return (stat.st_mtime_ns, stat.st_size)


def is_primary_session_jsonl_name(file_name: str) -> bool:
    name = str(file_name)
    if not name.endswith(".jsonl"):
        return False
    return not any(marker in name for marker in DERIVED_SESSION_FILE_MARKERS)


def apply_session_notes(items: list[SessionItem], notes: dict[str, str]) -> list[SessionItem]:
    return [replace(item, note=notes.get(item.session_id, item.note)) for item in items]


def iso_to_ts(value: str) -> int:
    if not value:
        return 0
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return 0


def flatten_message_content(content: list[dict[str, object]]) -> str:
    parts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if isinstance(text, str) and text.strip():
            parts.append(text.strip())
    return "\n\n".join(parts).strip()


def _quote_ps_single(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _preferred_interactive_shell_executable() -> str:
    if shutil.which("pwsh.exe"):
        return "pwsh.exe"
    if shutil.which("powershell.exe"):
        return "powershell.exe"
    return "powershell.exe"


def _preferred_terminal_executable() -> str | None:
    if shutil.which("wt.exe"):
        return "wt.exe"
    return None


def _encode_powershell_command(ps_command: str) -> str:
    return base64.b64encode(ps_command.encode("utf-16le")).decode("ascii")


def _windows_terminal_args(ps_command: str) -> list[str]:
    return [
        "new-tab",
        "--title",
        "Codex",
        "--",
        _preferred_interactive_shell_executable(),
        "-NoLogo",
        "-NoProfile",
        "-NoExit",
        "-EncodedCommand",
        _encode_powershell_command(ps_command),
    ]


def build_start_process_command(ps_command: str, run_as_admin: bool) -> str:
    terminal = _preferred_terminal_executable()
    if terminal:
        target = terminal
        args = _windows_terminal_args(ps_command)
    else:
        target = _preferred_interactive_shell_executable()
        args = ["-NoLogo", "-NoProfile", "-NoExit", "-Command", ps_command]
    start_process = f"Start-Process {_quote_ps_single(target)} "
    if run_as_admin:
        start_process += "-Verb RunAs "
    arg_items = [_quote_ps_single(value) for value in args]
    start_process += f"-ArgumentList @({','.join(arg_items)})"
    return start_process


def launch_terminal_command(ps_command: str, run_as_admin: bool) -> subprocess.Popen[bytes]:
    if run_as_admin:
        start_process = build_start_process_command(ps_command, True)
        return subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", start_process],
        )
    terminal = _preferred_terminal_executable()
    if terminal:
        try:
            return subprocess.Popen([terminal, *_windows_terminal_args(ps_command)])
        except OSError:
            pass
    return subprocess.Popen(
        [_preferred_interactive_shell_executable(), "-NoLogo", "-NoProfile", "-NoExit", "-Command", ps_command],
        creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
    )


def build_proxy_environment_ps_prefix(enabled: bool, scheme: str, host: str, port_text: str) -> str:
    if not enabled:
        return (
            "$env:HTTP_PROXY=$null; $env:HTTPS_PROXY=$null; $env:ALL_PROXY=$null; "
            "$env:http_proxy=$null; $env:https_proxy=$null; $env:all_proxy=$null; "
            f"$env:NO_PROXY='{DEFAULT_NO_PROXY}'; $env:no_proxy=$env:NO_PROXY; "
        )
    clean_scheme = scheme.strip().lower() or "http"
    clean_host = host.strip() or "127.0.0.1"
    if not port_text.isdigit():
        raise ValueError("Proxy port must be an integer.")
    port = int(port_text)
    if port < 1 or port > 65535:
        raise ValueError("Proxy port must be between 1 and 65535.")
    proxy_url = f"{clean_scheme}://{clean_host}:{port}"
    proxy_escaped = proxy_url.replace("'", "''")
    no_proxy_escaped = DEFAULT_NO_PROXY.replace("'", "''")
    return (
        f"$proxy='{proxy_escaped}'; "
        "$env:HTTP_PROXY=$proxy; $env:HTTPS_PROXY=$proxy; $env:ALL_PROXY=$proxy; "
        "$env:http_proxy=$proxy; $env:https_proxy=$proxy; $env:all_proxy=$proxy; "
        f"$env:NO_PROXY='{no_proxy_escaped}'; $env:no_proxy=$env:NO_PROXY; "
    )


def build_token_pool_environment_ps_prefix(env_key_name: str, api_key_value: str) -> str:
    clean_name = env_key_name.strip()
    if not clean_name:
        raise ValueError("Token pool env key name is required.")
    escaped_value = api_key_value.replace("'", "''")
    return f"$env:{clean_name}='{escaped_value}'; "


def build_openai_compatible_environment_ps_prefix(env_key_name: str, api_key_value: str) -> str:
    return build_token_pool_environment_ps_prefix(env_key_name=env_key_name, api_key_value=api_key_value)


def build_clear_api_environment_ps_prefix(env_key_names: tuple[str, ...] = CODEX_API_ENV_KEY_NAMES) -> str:
    parts: list[str] = []
    for name in env_key_names:
        clean_name = str(name).strip()
        if clean_name:
            parts.append(f"$env:{clean_name}=$null; ")
    return "".join(parts)


def build_codex_auth_provider_override_args(provider_name: str = CODEX_OFFICIAL_PROVIDER_NAME) -> list[str]:
    clean_provider = provider_name.strip() or CODEX_OFFICIAL_PROVIDER_NAME
    return ["-c", f'model_provider="{clean_provider}"']


def is_windowsapps_python_shim(path: str) -> bool:
    clean_path = str(path).strip().replace("/", "\\").lower()
    if not clean_path or "windowsapps" not in clean_path:
        return False
    name = Path(clean_path).name
    return name.startswith("python") and name.endswith(".exe")


def build_source_python_command(executable: str, app_path: str) -> list[str]:
    clean_executable = str(executable).strip()
    clean_app_path = str(app_path).strip()
    if not is_windowsapps_python_shim(clean_executable):
        return [clean_executable, clean_app_path]
    python_executable = shutil.which("python")
    if python_executable and not is_windowsapps_python_shim(python_executable):
        return [python_executable, clean_app_path]
    py_launcher = shutil.which("py")
    if py_launcher:
        return [py_launcher, "-3", clean_app_path]
    return [clean_executable, clean_app_path]


def configured_codex_executable(
    settings_file: Path = PORTAL_SETTINGS_FILE,
) -> Path | None:
    try:
        payload = json.loads(settings_file.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    raw_path = payload.get("codex_executable")
    if not isinstance(raw_path, str) or not raw_path.strip():
        return None
    expanded = os.path.expandvars(raw_path.strip())
    executable = Path(expanded).expanduser()
    return executable if executable.is_absolute() else None


def configured_codex_file_opener(
    settings_file: Path = PORTAL_SETTINGS_FILE,
) -> str | None:
    try:
        payload = json.loads(settings_file.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    raw_opener = payload.get("codex_file_opener")
    if not isinstance(raw_opener, str):
        return None
    opener = raw_opener.strip().lower()
    return opener if opener in CODEX_FILE_OPENERS else None


@functools.lru_cache(maxsize=16)
def _cached_codex_executable_health_check(
    executable: str,
    size: int,
    modified_ns: int,
) -> bool:
    del size, modified_ns
    try:
        result = subprocess.run(
            [executable, "--version"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=3,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return False
    if result.returncode != 0:
        return False
    version = (result.stdout or result.stderr or "").strip()
    return CODEX_VERSION_PATTERN.fullmatch(version) is not None


def codex_executable_is_healthy(executable: Path) -> bool:
    try:
        stat = executable.stat()
    except OSError:
        return False
    if not executable.is_file():
        return False
    return _cached_codex_executable_health_check(
        str(executable),
        stat.st_size,
        stat.st_mtime_ns,
    )


def build_token_pool_provider_override_args(
    model: str,
    proxy_port: int,
    provider_name: str = TOKEN_POOL_PROVIDER_NAME,
    env_key_name: str = TOKEN_POOL_ENV_KEY_NAME,
) -> list[str]:
    clean_provider = provider_name.strip() or TOKEN_POOL_PROVIDER_NAME
    clean_env_key = env_key_name.strip() or TOKEN_POOL_ENV_KEY_NAME
    clean_model = model.strip()
    if not clean_model:
        raise ValueError("A model is required for token pool launches.")
    return [
        "-c",
        f'model_provider="{clean_provider}"',
        "-c",
        f'model_providers.{clean_provider}.name="Built-in Token Pool"',
        "-c",
        f'model_providers.{clean_provider}.base_url="http://127.0.0.1:{int(proxy_port)}"',
        "-c",
        f'model_providers.{clean_provider}.env_key="{clean_env_key}"',
        "-c",
        f'model_providers.{clean_provider}.wire_api="responses"',
        "-c",
        f'model_providers.{clean_provider}.requires_openai_auth=false',
        "-c",
        f'model_providers.{clean_provider}.supports_websockets=false',
    ]


def build_openai_compatible_provider_override_args(
    model: str,
    base_url: str,
    provider_name: str = OPENAI_COMPAT_PROVIDER_NAME,
    env_key_name: str = OPENAI_COMPAT_ENV_KEY_NAME,
    wire_api: str = "responses",
) -> list[str]:
    clean_provider = provider_name.strip() or OPENAI_COMPAT_PROVIDER_NAME
    clean_env_key = env_key_name.strip() or OPENAI_COMPAT_ENV_KEY_NAME
    clean_model = model.strip()
    clean_base_url = base_url.strip().rstrip("/")
    clean_wire_api = wire_api.strip() if wire_api and wire_api.strip() in ("responses", "chat") else "responses"
    if not clean_model:
        raise ValueError("A model is required for OpenAI-compatible launches.")
    if not clean_base_url:
        raise ValueError("A base URL is required for OpenAI-compatible launches.")
    return [
        "-c",
        f'model_provider="{clean_provider}"',
        "-c",
        f'model_providers.{clean_provider}.name="OpenAI Compatible"',
        "-c",
        f'model_providers.{clean_provider}.base_url="{clean_base_url}"',
        "-c",
        f'model_providers.{clean_provider}.env_key="{clean_env_key}"',
        "-c",
        f'model_providers.{clean_provider}.wire_api="{clean_wire_api}"',
        "-c",
        f'model_providers.{clean_provider}.requires_openai_auth=false',
        "-c",
        f'model_providers.{clean_provider}.supports_websockets=false',
    ]


def openai_preset_form_values(preset: dict[str, object]) -> dict[str, object]:
    raw_proxy_preference = str(preset.get("proxy_preference", "")).strip()
    return {
        "openai_base_url": (
            str(preset.get("openai_base_url", token_pool_settings.DEFAULT_OPENAI_BASE_URL)).strip()
            or token_pool_settings.DEFAULT_OPENAI_BASE_URL
        ),
        "openai_api_key": str(preset.get("openai_api_key", "")).strip(),
        "openai_model": str(preset.get("openai_model", "")).strip(),
        "openai_models": unique_model_ids(preset.get("openai_models", [])),
        "openai_protocol": (
            str(preset.get("openai_protocol", "")).strip()
            or token_pool_settings.OPENAI_PROTOCOL_RESPONSES
        ),
        "proxy_preference": (
            raw_proxy_preference
            if raw_proxy_preference in {"auto", "direct", "proxy"}
            else "direct"
        ),
    }


def openai_model_form_state(
    form_values: dict[str, object],
    *,
    fallback_models: Iterable[object] = (),
    allow_fallback: bool = False,
) -> tuple[list[str], str]:
    model_values = unique_model_ids(form_values.get("openai_models", []))
    selected_model = str(form_values.get("openai_model", "")).strip()
    if selected_model and selected_model not in model_values:
        model_values = [selected_model, *model_values]
    if allow_fallback and not model_values:
        model_values = unique_model_ids(fallback_models)
    if allow_fallback and not selected_model and model_values:
        selected_model = model_values[0]
    return model_values, selected_model


def openai_account_form_values(settings: dict[str, object]) -> dict[str, object]:
    """Return the OpenAI-compatible values shown in the Accounts dialog."""
    values = openai_preset_form_values(settings)
    presets = settings.get("openai_presets", [])
    active_id = str(settings.get("active_openai_preset_id", "")).strip()
    if not isinstance(presets, list) or not active_id:
        return values
    active_preset = next(
        (
            item
            for item in presets
            if isinstance(item, dict) and str(item.get("id", "")).strip() == active_id
        ),
        None,
    )
    if not isinstance(active_preset, dict):
        return values
    return openai_preset_form_values(active_preset)


def _find_openai_preset(settings: dict[str, object], preset_id: str) -> dict[str, object]:
    clean_id = preset_id.strip()
    if not clean_id:
        return {}
    for item in settings.get("openai_presets", []) or []:
        if isinstance(item, dict) and str(item.get("id", "")).strip() == clean_id:
            return item
    return {}


def _merge_openai_models(models: object, extras: list[str], selected_model: str) -> list[str]:
    merged = unique_model_ids(models)
    clean_selected = selected_model.strip()
    if clean_selected and clean_selected not in merged:
        merged.insert(0, clean_selected)
    for extra in extras:
        if extra and extra not in merged:
            merged.append(extra)
    return merged


def _resolve_disable_image_generation(existing_preset: dict[str, object], override: bool | None) -> bool:
    if override is None:
        return bool(existing_preset.get("disable_image_generation", False))
    return bool(override)


def _resolved_manual_openai_protocol(protocol_override: str, fallback: str) -> str:
    clean_override = protocol_override.strip()
    if clean_override and clean_override in token_pool_settings.VALID_OPENAI_PROTOCOLS:
        return clean_override
    clean_fallback = fallback.strip()
    if clean_fallback in token_pool_settings.VALID_OPENAI_PROTOCOLS:
        return clean_fallback
    return ""


def save_openai_compatible_backend_settings(
    *,
    settings_file: Path = token_pool_settings.DEFAULT_SETTINGS_FILE,
    token_dir: Path = token_pool_settings.DEFAULT_TOKEN_POOL_DIR,
    proxy_port: int = token_pool_settings.DEFAULT_PROXY_PORT,
    proxy_api_key: str = "",
    base_url: str = token_pool_settings.DEFAULT_OPENAI_BASE_URL,
    api_key: str = "",
    model: str = "",
    manual_extra_models: list[str] | tuple[str, ...] | None = None,
    preset_id: str = "",
    preset_name: str = "",
    create_new_preset: bool = False,
    proxy_preference: str = "direct",
    protocol_override: str = "",
    disable_image_generation: bool | None = None,
) -> dict[str, object]:
    existing = token_pool_settings.load_backend_settings(settings_file)
    existing_preset = _find_openai_preset(existing, preset_id) if preset_id.strip() and not create_new_preset else {}
    resolved_disable_image_generation = _resolve_disable_image_generation(existing_preset, disable_image_generation)
    skip_validation = bool(existing_preset.get("skip_validation", False))
    if manual_extra_models is None:
        extra_source = existing_preset.get("openai_manual_extra_models", existing.get("openai_manual_extra_models", []))
        extras = [str(m).strip() for m in extra_source or [] if str(m).strip()]
    else:
        extras = [str(m).strip() for m in manual_extra_models if str(m).strip()]

    if skip_validation:
        selected_model = model.strip() or str(existing_preset.get("openai_model", existing.get("openai_model", ""))).strip()
        merged = _merge_openai_models(existing_preset.get("openai_models", existing.get("openai_models", [])), extras, selected_model)
        final_protocol = _resolved_manual_openai_protocol(
            protocol_override,
            str(existing_preset.get("openai_protocol", existing.get("openai_protocol", ""))),
        )
        resolved = {
            "openai_base_url": base_url.strip() or str(existing_preset.get("openai_base_url", existing.get("openai_base_url", token_pool_settings.DEFAULT_OPENAI_BASE_URL))),
            "openai_api_key": api_key.strip() or str(existing_preset.get("openai_api_key", existing.get("openai_api_key", ""))),
            "openai_model": selected_model,
            "openai_models": merged,
            "openai_protocol": final_protocol,
        }
    else:
        resolved = token_pool_settings.resolve_openai_compatible_backend_config(
            base_url,
            api_key,
            model,
        )
        upstream_models = list(resolved.get("openai_models", []) or [])
        merged = _merge_openai_models(upstream_models, extras, "")
        selected_model = str(resolved.get("openai_model", model))
        if selected_model not in merged and merged:
            selected_model = merged[0]
        final_protocol = protocol_override.strip() if protocol_override and protocol_override.strip() in token_pool_settings.VALID_OPENAI_PROTOCOLS else str(resolved.get("openai_protocol", ""))

    updated = token_pool_settings.save_backend_settings(
        backend_mode=token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE,
        settings_file=settings_file,
        token_dir=token_dir,
        proxy_port=proxy_port,
        proxy_api_key=proxy_api_key,
        openai_base_url=str(resolved.get("openai_base_url", base_url)),
        openai_api_key=str(resolved.get("openai_api_key", api_key)),
        openai_model=selected_model,
        openai_models=merged,
        openai_protocol=final_protocol,
        openai_manual_extra_models=extras,
    )
    if preset_id.strip() or preset_name.strip():
        updated = token_pool_settings.save_openai_preset(
            settings_file=settings_file,
            preset_id=preset_id.strip(),
            name=preset_name.strip() or preset_id.strip() or token_pool_settings.DEFAULT_OPENAI_PRESET_NAME,
            openai_base_url=str(updated.get("openai_base_url", token_pool_settings.DEFAULT_OPENAI_BASE_URL)),
            openai_api_key=str(updated.get("openai_api_key", "")),
            openai_model=str(updated.get("openai_model", "")),
            openai_models=updated.get("openai_models", []),
            openai_protocol=str(updated.get("openai_protocol", "")),
            openai_manual_extra_models=updated.get("openai_manual_extra_models", []),
            proxy_preference=proxy_preference,
            upstream_proxy_url=str(existing_preset.get("upstream_proxy_url", updated.get("upstream_proxy_url", ""))),
            skip_validation=bool(existing_preset.get("skip_validation", False)),
            installation_id=str(existing_preset.get("installation_id", "")),
            claude_env=existing_preset.get("claude_env", {}),
            disable_image_generation=resolved_disable_image_generation,
            set_active=True,
            create_new=create_new_preset,
        )
    _patch_image_generation_for_backend_mode(token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE)
    return updated


def save_openai_compatible_preset_settings(
    *,
    settings_file: Path = token_pool_settings.DEFAULT_SETTINGS_FILE,
    base_url: str = token_pool_settings.DEFAULT_OPENAI_BASE_URL,
    api_key: str = "",
    model: str = "",
    manual_extra_models: list[str] | tuple[str, ...] | None = None,
    preset_id: str = "",
    preset_name: str = "",
    create_new_preset: bool = False,
    proxy_preference: str = "direct",
    protocol_override: str = "",
    disable_image_generation: bool | None = None,
) -> dict[str, object]:
    existing = token_pool_settings.load_backend_settings(settings_file)
    existing_preset = _find_openai_preset(existing, preset_id) if preset_id.strip() and not create_new_preset else {}
    resolved_disable_image_generation = _resolve_disable_image_generation(existing_preset, disable_image_generation)
    skip_validation = bool(existing_preset.get("skip_validation", False))
    if manual_extra_models is None:
        extra_source = existing_preset.get("openai_manual_extra_models", existing.get("openai_manual_extra_models", []))
        extras = [str(m).strip() for m in extra_source or [] if str(m).strip()]
    else:
        extras = [str(m).strip() for m in manual_extra_models if str(m).strip()]

    if skip_validation:
        selected_model = model.strip() or str(existing_preset.get("openai_model", existing.get("openai_model", ""))).strip()
        merged = _merge_openai_models(existing_preset.get("openai_models", existing.get("openai_models", [])), extras, selected_model)
        final_protocol = _resolved_manual_openai_protocol(
            protocol_override,
            str(existing_preset.get("openai_protocol", existing.get("openai_protocol", ""))),
        )
        resolved = {
            "openai_base_url": base_url.strip() or str(existing_preset.get("openai_base_url", existing.get("openai_base_url", token_pool_settings.DEFAULT_OPENAI_BASE_URL))),
            "openai_api_key": api_key.strip() or str(existing_preset.get("openai_api_key", existing.get("openai_api_key", ""))),
            "openai_model": selected_model,
            "openai_models": merged,
            "openai_protocol": final_protocol,
        }
    else:
        resolved = token_pool_settings.resolve_openai_compatible_backend_config(
            base_url,
            api_key,
            model,
        )
        upstream_models = list(resolved.get("openai_models", []) or [])
        merged = _merge_openai_models(upstream_models, extras, "")
        selected_model = str(resolved.get("openai_model", model))
        if selected_model not in merged and merged:
            selected_model = merged[0]
        final_protocol = (
            protocol_override.strip()
            if protocol_override and protocol_override.strip() in token_pool_settings.VALID_OPENAI_PROTOCOLS
            else str(resolved.get("openai_protocol", ""))
        )

    # Auto-detect proxy preference by testing actual connections
    final_proxy_pref = proxy_preference
    if proxy_preference == "auto" and not skip_validation:
        final_base_url = str(resolved.get("openai_base_url", base_url))
        final_api_key = str(resolved.get("openai_api_key", api_key))
        detected = token_pool_settings.detect_proxy_preference(final_base_url, final_api_key)
        final_proxy_pref = detected if detected in ("direct", "proxy") else "direct"
    return token_pool_settings.save_openai_preset(
        settings_file=settings_file,
        preset_id=preset_id.strip(),
        name=preset_name.strip() or preset_id.strip() or token_pool_settings.DEFAULT_OPENAI_PRESET_NAME,
        openai_base_url=str(resolved.get("openai_base_url", base_url)),
        openai_api_key=str(resolved.get("openai_api_key", api_key)),
        openai_model=selected_model,
        openai_models=merged,
        openai_protocol=final_protocol,
        openai_manual_extra_models=extras,
        proxy_preference=final_proxy_pref,
        upstream_proxy_url=str(existing_preset.get("upstream_proxy_url", "")),
        skip_validation=bool(existing_preset.get("skip_validation", False)),
        installation_id=str(existing_preset.get("installation_id", "")),
        claude_env=existing_preset.get("claude_env", {}),
        disable_image_generation=resolved_disable_image_generation,
        set_active=True,
        create_new=create_new_preset,
    )


def refresh_openai_compatible_models_from_upstream(
    settings_file: Path = token_pool_settings.DEFAULT_SETTINGS_FILE,
) -> dict[str, object]:
    """Refresh `openai_models` from the upstream `/v1/models` and persist.

    Auto-sync + manual-extras semantics: the upstream list becomes the base,
    then any entries in `openai_manual_extra_models` (e.g. unlisted models like
    `gpt-5.6-luna`) are appended on top. Network or HTTP errors fall back to the
    current saved settings.
    """
    settings = token_pool_settings.load_backend_settings(settings_file)
    if str(settings.get("backend_mode", "")) != token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE:
        return settings
    base_url = str(settings.get("openai_base_url", "")).strip()
    api_key = str(settings.get("openai_api_key", "")).strip()
    if not base_url or not api_key:
        return settings
    try:
        upstream_models = token_pool_settings.fetch_openai_compatible_models(base_url, api_key)
    except Exception:
        return settings
    if not upstream_models:
        return settings
    # Filter out image-generation models – most key-mode providers don't support them
    upstream_models = [m for m in upstream_models if not str(m).strip().startswith("gpt-image")]
    extras = [
        str(m).strip()
        for m in settings.get("openai_manual_extra_models", []) or []
        if str(m).strip()
    ]
    merged: list[str] = list(upstream_models)
    for extra in extras:
        if extra not in merged:
            merged.append(extra)
    current_model = str(settings.get("openai_model", "")).strip()
    selected = current_model if current_model in merged else merged[0]
    return token_pool_settings.save_backend_settings(
        backend_mode=token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE,
        settings_file=settings_file,
        token_dir=Path(str(settings.get("token_dir", token_pool_settings.DEFAULT_TOKEN_POOL_DIR))),
        proxy_port=int(settings.get("proxy_port", token_pool_settings.DEFAULT_PROXY_PORT)),
        proxy_api_key=str(settings.get("proxy_api_key", "")),
        openai_base_url=base_url,
        openai_api_key=api_key,
        openai_model=selected,
        openai_models=merged,
        openai_protocol=str(settings.get("openai_protocol", "")),
        openai_manual_extra_models=extras,
    )


def apply_backend_mode_settings(
    *,
    backend_mode: str,
    settings_file: Path = token_pool_settings.DEFAULT_SETTINGS_FILE,
    token_dir: Path = token_pool_settings.DEFAULT_TOKEN_POOL_DIR,
    proxy_port: int = token_pool_settings.DEFAULT_PROXY_PORT,
    proxy_api_key: str = "",
    openai_base_url: str = token_pool_settings.DEFAULT_OPENAI_BASE_URL,
    openai_api_key: str = "",
    openai_model: str = "",
    openai_models: list[str] | tuple[str, ...] = (),
    openai_protocol: str = "",
) -> dict[str, object]:
    clean_mode = str(backend_mode).strip() or token_pool_settings.BACKEND_MODE_CODEX_AUTH
    if clean_mode == token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE:
        existing = token_pool_settings.load_backend_settings(settings_file)
        active_preset_id = str(existing.get("active_openai_preset_id", "")).strip()
        active_preset = _find_openai_preset(existing, active_preset_id) if active_preset_id else {}
        use_active_skip_preset = (
            isinstance(active_preset, dict)
            and bool(active_preset.get("skip_validation", False))
        )
        return save_openai_compatible_backend_settings(
            settings_file=settings_file,
            token_dir=token_dir,
            proxy_port=proxy_port,
            proxy_api_key=proxy_api_key,
            base_url=openai_base_url,
            api_key=openai_api_key,
            model=openai_model,
            preset_id=active_preset_id if use_active_skip_preset else "",
            preset_name=str(active_preset.get("name", "")).strip() if use_active_skip_preset else "",
            proxy_preference=str(active_preset.get("proxy_preference", "direct")) if use_active_skip_preset else "direct",
            protocol_override=openai_protocol,
        )
    updated = token_pool_settings.save_backend_settings(
        backend_mode=clean_mode,
        settings_file=settings_file,
        token_dir=token_dir,
        proxy_port=proxy_port,
        proxy_api_key=proxy_api_key,
        openai_base_url=openai_base_url,
        openai_api_key=openai_api_key,
        openai_model=openai_model,
        openai_models=list(openai_models),
        openai_protocol=openai_protocol,
    )
    _patch_image_generation_for_backend_mode(clean_mode)
    _swap_installation_id_for_preset({})
    return updated


def build_token_pool_proxy_command(
    *,
    executable: str,
    app_path: str,
    port: int,
    api_key: str,
    token_dir: str,
    frozen: bool,
) -> list[str]:
    if not frozen:
        conda_executable = shutil.which("conda")
        if conda_executable:
            command = [conda_executable, "run", "--no-capture-output", "-n", "codex-accel", "python", app_path]
        else:
            command = build_source_python_command(executable, app_path)
    else:
        command = [executable]
    command.extend(
        [
            "--token-pool-proxy",
            "--port",
            str(int(port)),
            "--api-key",
            api_key,
            "--token-dir",
            token_dir,
        ]
    )
    return command


def build_custom_provider_proxy_command(
    *,
    executable: str,
    app_path: str,
    port: int,
    api_key: str,
    upstream_base_url: str,
    upstream_api_key: str,
    upstream_protocol: str,
    upstream_proxy_url: str = "",
    model_ids: list[str],
    frozen: bool,
) -> list[str]:
    if not frozen:
        conda_executable = shutil.which("conda")
        if conda_executable:
            command = [conda_executable, "run", "--no-capture-output", "-n", "codex-accel", "python", app_path]
        else:
            command = build_source_python_command(executable, app_path)
    else:
        command = [executable]
    command.extend(
        [
            "--custom-provider-proxy",
            "--port",
            str(int(port)),
            "--api-key",
            api_key,
            "--upstream-base-url",
            upstream_base_url.strip(),
            "--upstream-api-key",
            upstream_api_key,
            "--upstream-protocol",
            upstream_protocol.strip() or token_pool_settings.OPENAI_PROTOCOL_RESPONSES,
        ]
    )
    clean_upstream_proxy = upstream_proxy_url.strip()
    if clean_upstream_proxy:
        command.extend(["--upstream-proxy-url", clean_upstream_proxy])
    for model_id in model_ids:
        clean_model = str(model_id).strip()
        if clean_model:
            command.extend(["--model", clean_model])
    return command


def load_token_pool_proxy_state(state_file: Path = TOKEN_POOL_PROXY_STATE_FILE) -> dict[str, object]:
    if not state_file.exists():
        return {}
    try:
        payload = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def save_token_pool_proxy_state(state: dict[str, object], state_file: Path = TOKEN_POOL_PROXY_STATE_FILE) -> None:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def clear_token_pool_proxy_state(state_file: Path = TOKEN_POOL_PROXY_STATE_FILE) -> None:
    try:
        state_file.unlink()
    except OSError:
        pass


def read_current_weekly_quota(timeout_seconds: float = 4.0) -> dict[str, str]:
    try:
        result = subprocess.run(
            ["codex.cmd", "/status"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return {"state": "unavailable", "summary": "Quota unavailable"}
    if result.returncode != 0:
        return {"state": "unavailable", "summary": "Quota unavailable"}
    output = (result.stdout or "").strip()
    if not output:
        return {"state": "unavailable", "summary": "Quota unavailable"}
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if "weekly quota" in line.lower():
            return {"state": "ok", "summary": line}
    first_line = output.splitlines()[0].strip()
    return {"state": "ok", "summary": first_line or "Quota unavailable"}


def run_codex_browser_login() -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["codex.cmd", "login"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="ignore",
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError("Failed to start Codex login.") from exc


def start_codex_browser_login_process(private_browser: bool = False, env: dict[str, str] | None = None) -> subprocess.Popen[str]:
    kwargs: dict[str, object] = {}
    if private_browser:
        kwargs["env"] = env or build_private_browser_login_env()
    login_args = ["codex.cmd", "login", "--device-auth"] if private_browser else ["codex.cmd", "login"]
    try:
        process = subprocess.Popen(
            login_args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="ignore",
            **kwargs,
        )
        if private_browser:
            setattr(process, "_codex_private_browser_env", kwargs.get("env"))
        return process
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError("Failed to start Codex login.") from exc


def summarize_login_failure(result: subprocess.CompletedProcess[str]) -> str:
    lines = [line.strip() for line in str(result.stdout or "").splitlines() if line.strip()]
    if lines:
        return lines[-1]
    return f"Codex login failed with exit code {result.returncode}."


def ensure_account_slot_exists(slot_id: str) -> None:
    registry = auth_slots.load_slot_registry()
    if not any(str(item.get("slot_id", "")).strip() == slot_id for item in registry):
        raise FileNotFoundError(f"Account slot '{slot_id}' not found.")


def finalize_login_and_bind_account_slot(
    slot_id: str,
    before_fingerprint: str,
    result: subprocess.CompletedProcess[str],
) -> dict[str, str]:
    if result.returncode != 0:
        raise RuntimeError(summarize_login_failure(result))
    after_fingerprint = str(auth_slots.current_auth_info().get("fingerprint", "")).strip()
    if not after_fingerprint or after_fingerprint == before_fingerprint:
        raise RuntimeError("Codex login finished but did not produce a new login.")
    return auth_slots.save_current_auth_to_slot(slot_id)


def login_and_bind_account_slot(slot_id: str) -> dict[str, str]:
    ensure_account_slot_exists(slot_id)
    before_fingerprint = str(auth_slots.current_auth_info().get("fingerprint", "")).strip()
    result = run_codex_browser_login()
    return finalize_login_and_bind_account_slot(slot_id, before_fingerprint, result)


def format_account_slot_name(slot_id: str | None, slot_info: dict[str, str] | None = None) -> str:
    if not slot_id:
        return "Unbound"
    if slot_info:
        label = str(slot_info.get("label", "")).strip()
        if label:
            return label
    return auth_slots.LEGACY_SLOT_LABELS.get(slot_id, slot_id)


def find_slot_info(slot_id: str | None, slots: list[dict[str, str]]) -> dict[str, str]:
    if not slot_id:
        return {}
    for item in slots:
        if item.get("slot_id") == slot_id:
            return item
    return {}


def format_account_status_label(active_slot: str | None, auth_info: dict[str, str], slot_info: dict[str, str] | None = None) -> str:
    email = auth_info.get("email", "").strip()
    account_id = auth_info.get("account_id", "").strip()
    if not email and not account_id:
        return "Auth: not logged in"
    identity = email or account_id or "logged in"
    label = f"Auth: {format_account_slot_name(active_slot, slot_info)} | {identity}"
    return compact_status_message(label, ACCOUNT_STATUS_DISPLAY_LIMIT)


def format_account_slot_summary(slot_id: str, slot_info: dict[str, str], active_slot: str | None) -> str:
    slot_label = format_account_slot_name(slot_id, slot_info)
    if not slot_info.get("fingerprint"):
        return f"{slot_label}\nNot bound yet."
    identity = slot_info.get("email", "").strip() or slot_info.get("account_id", "").strip() or "saved login"
    mode = slot_info.get("auth_mode", "").strip() or "unknown"
    active_text = "Active now" if slot_id == active_slot else "Inactive"
    return f"{slot_label}\n{identity}\nMode: {mode}\n{active_text}"


def format_account_quota_summary(quota: dict[str, str]) -> str:
    summary = str(quota.get("summary", "")).strip()
    if summary:
        return summary
    return "Quota unavailable"


def slot_supports_direct_login(slot_info: dict[str, str]) -> bool:
    return not bool(str(slot_info.get("fingerprint", "")).strip())


def merge_available_models(models: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for model in (DEFAULT_PRIMARY_MODEL, *models, *FALLBACK_MODEL_OPTIONS[1:]):
        clean_model = str(model).strip()
        if not clean_model or clean_model in seen:
            continue
        seen.add(clean_model)
        merged.append(clean_model)
    return merged


def unique_model_ids(models: object) -> list[str]:
    if not isinstance(models, (list, tuple)):
        return []
    unique: list[str] = []
    seen: set[str] = set()
    for item in models:
        clean_model = str(item).strip()
        if not clean_model or clean_model in seen:
            continue
        seen.add(clean_model)
        unique.append(clean_model)
    return unique


def backend_health_matches(health: object, expected_backend_mode: str) -> bool:
    if not isinstance(health, dict):
        return False
    clean_expected = str(expected_backend_mode).strip()
    if not clean_expected:
        return True
    return str(health.get("backend_mode", "")).strip() == clean_expected


def openai_compatible_proxy_config_fingerprint_for_settings(settings: dict[str, object]) -> str:
    return token_pool_settings.openai_compatible_proxy_config_fingerprint(
        local_api_key=str(settings.get("proxy_api_key", "")),
        upstream_base_url=str(settings.get("openai_base_url", token_pool_settings.DEFAULT_OPENAI_BASE_URL)),
        upstream_api_key=str(settings.get("openai_api_key", "")),
        upstream_protocol=str(settings.get("openai_protocol", "")),
        model_ids=unique_model_ids(settings.get("openai_models", [])),
    )


def _is_proxy_needed_for_openai_compatible(settings: dict[str, object]) -> bool:
    """
    Detect if proxy is needed for openai_compatible mode.

    The local proxy is only needed for a protocol mismatch. Network proxy
    selection is handled independently through the launch environment.

    Returns:
        True if proxy is needed, False for direct connection
    """
    upstream_protocol = str(settings.get("openai_protocol", "")).strip()
    return upstream_protocol == token_pool_settings.OPENAI_PROTOCOL_CHAT_COMPLETIONS


def openai_compatible_proxy_health_matches_settings(health: object, settings: dict[str, object]) -> bool:
    if not backend_health_matches(health, token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE):
        return False
    if not isinstance(health, dict):
        return False
    expected = openai_compatible_proxy_config_fingerprint_for_settings(settings)
    return str(health.get("config_fingerprint", "")).strip() == expected


def expected_backend_mode_for_settings(settings: dict[str, object]) -> str:
    mode = settings.get("backend_mode")
    if mode == token_pool_settings.BACKEND_MODE_TOKEN_POOL:
        return token_pool_settings.BACKEND_MODE_TOKEN_POOL
    if mode == token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE:
        return token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE
    return ""


def run_taskkill_tree_silently(pid: int, timeout_seconds: int = 5) -> bool:
    if pid <= 0:
        return False
    try:
        result = subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def account_dialog_dimensions(screen_width: int, screen_height: int) -> tuple[int, int]:
    usable_width = max(360, int(screen_width) - 80)
    usable_height = max(360, int(screen_height) - 80)
    return min(720, usable_width), min(820, usable_height)


def compact_status_message(message: str, limit: int = MAX_DESKTOP_STATUS_CHARS) -> str:
    clean = str(message or "")
    if len(clean) <= limit:
        return clean
    if limit <= 3:
        return clean[:limit]
    return clean[: limit - 3].rstrip() + "..."


def desktop_window_geometry(screen_width: int, screen_height: int) -> tuple[int, int]:
    usable_width = max(940, int(screen_width) - 120)
    usable_height = max(620, int(screen_height) - 120)
    return min(1040, usable_width), min(760, usable_height)


def desktop_window_placement(screen_width: int, screen_height: int) -> tuple[int, int, int, int]:
    width, height = desktop_window_geometry(screen_width, screen_height)
    return width, height, 40, 40


class SessionManagerApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(APP_TITLE)
        window_width, window_height, window_x, window_y = desktop_window_placement(
            root.winfo_screenwidth(),
            root.winfo_screenheight(),
        )
        self.root.geometry(f"{window_width}x{window_height}+{window_x}+{window_y}")
        self.root.minsize(940, 620)

        self.items: list[SessionItem] = []
        self.item_by_id: dict[str, SessionItem] = {}
        self.session_notes: dict[str, str] = {}
        self.mcp_items: list[McpItem] = []
        self.skill_items: list[SkillItem] = []
        self.available_models: list[str] = []
        self._mcp_item_map: dict[str, McpItem] = {}
        self._skill_item_map: dict[str, SkillItem] = {}
        self._auto_refresh_id: str | None = None
        self._portal_retry_after = 0.0
        self._desktop_signal_id: str | None = None
        self._desktop_signal_mtime = DESKTOP_REFRESH_SIGNAL_FILE.stat().st_mtime if DESKTOP_REFRESH_SIGNAL_FILE.exists() else 0.0
        self._history_signature: tuple[int, int] | None = None
        self.account_var = tk.StringVar(value="Auth: checking...")
        self.backend_settings = token_pool_settings.load_backend_settings()

        self.font_scale = 1.0
        self._base_fonts: dict[str, int] = {}
        self._col_fixed = {"time": 160, "count": 72, "model": 120, "approval": 95, "sandbox": 120}
        self._col_flex_weight = {"session_id": 2, "cwd": 2, "text": 4}

        self._init_styles()
        self._build_ui()
        self._init_fonts()
        self._refresh_account_status()
        self._bind_shortcuts()
        self.refresh()
        self._schedule_auto_refresh()
        self._schedule_desktop_signal_watch()

    def _init_styles(self) -> None:
        style = ttk.Style(self.root)
        try:
            self.root.configure(bg="#f8fafc")
        except tk.TclError:
            pass
        style.configure("App.TFrame", background="#f8fafc")
        style.configure("Toolbar.TFrame", background="#f8fafc")
        style.configure("Surface.TFrame", background="#ffffff")
        style.configure("Status.TLabel", background="#f8fafc", foreground="#475569")
        style.configure("Toolbar.TLabel", background="#f8fafc", foreground="#334155")
        style.configure("Primary.TButton", foreground="#052e2b", padding=(12, 7))
        style.configure("Secondary.TButton", padding=(12, 7))
        style.configure("Danger.TButton", foreground="#b42318", padding=(12, 7))
        style.configure(
            "Inspector.TLabelframe",
            background="#f8fafc",
            bordercolor="#d8dee8",
            lightcolor="#d8dee8",
            darkcolor="#d8dee8",
        )
        style.configure(
            "Inspector.TLabelframe.Label",
            background="#f8fafc",
            foreground="#334155",
            font=("Segoe UI", 10, "bold"),
        )
        style.map(
            "Primary.TButton",
            background=[("active", "#5bd2ba"), ("pressed", "#35a892")],
        )
        style.map(
            "Danger.TButton",
            foreground=[("active", "#912018"), ("pressed", "#912018")],
        )

    def _build_ui(self) -> None:
        top = ttk.Frame(self.root, padding=(10, 8), style="Toolbar.TFrame")
        top.pack(fill=tk.X)
        top.grid_columnconfigure(0, weight=1)

        toolbar_actions = ttk.Frame(top, style="Toolbar.TFrame")
        toolbar_actions.grid(row=0, column=0, sticky="w")
        ttk.Button(toolbar_actions, text="Refresh", command=self.refresh, style="Secondary.TButton").pack(side=tk.LEFT)
        ttk.Button(toolbar_actions, text="Open Terminal", command=self.open_selected_admin, style="Primary.TButton").pack(side=tk.LEFT, padx=6)
        ttk.Button(toolbar_actions, text="New Chat", command=self.open_new_chat, style="Primary.TButton").pack(side=tk.LEFT)
        ttk.Button(toolbar_actions, text="Open Folder", command=self.open_selected_folder, style="Secondary.TButton").pack(side=tk.LEFT, padx=(14, 0))
        ttk.Button(toolbar_actions, text="Open File", command=self.open_selected_file, style="Secondary.TButton").pack(side=tk.LEFT, padx=6)
        ttk.Button(toolbar_actions, text="Delete", command=self.delete_selected, style="Danger.TButton").pack(side=tk.LEFT)
        ttk.Button(toolbar_actions, text="Remote SSH", command=self.open_remote_ssh_dialog, style="Secondary.TButton").pack(side=tk.LEFT, padx=(6, 0))

        self.status_var = tk.StringVar(value="Ready")
        toolbar_context = ttk.Frame(top, style="Toolbar.TFrame")
        toolbar_context.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        ttk.Label(toolbar_context, textvariable=self.status_var, style="Status.TLabel", width=34, anchor=tk.W).pack(side=tk.LEFT)
        ttk.Button(toolbar_context, text="Accounts", command=self.open_accounts_dialog, style="Secondary.TButton").pack(side=tk.RIGHT, padx=(8, 0))
        ttk.Label(toolbar_context, textvariable=self.account_var, style="Toolbar.TLabel", width=42, anchor=tk.E).pack(side=tk.RIGHT)

        launch = ttk.LabelFrame(self.root, text="Launch Options (Only This Terminal)", padding=10, style="Inspector.TLabelframe")
        launch.pack(fill=tk.X, padx=10, pady=(0, 8))

        launch_defaults = default_launch_options()
        self.model_var = tk.StringVar(value=launch_defaults["model"])
        self.approval_var = tk.StringVar(value=launch_defaults["approval"])
        self.sandbox_var = tk.StringVar(value=launch_defaults["sandbox"])
        self.reasoning_effort_var = tk.StringVar(value=launch_defaults["reasoning_effort"])
        self.search_var = tk.BooleanVar(value=False)
        self.admin_var = tk.BooleanVar(value=DEFAULT_LAUNCH_ADMIN)
        self.show_last_text_var = tk.BooleanVar(value=True)
        self.use_global_defaults_var = tk.BooleanVar(value=True)
        self.use_proxy_var = tk.BooleanVar(value=True)
        self.proxy_scheme_var = tk.StringVar(value="socks5h")
        self.proxy_host_var = tk.StringVar(value="127.0.0.1")
        self.proxy_port_var = tk.StringVar(value="7897")

        ttk.Label(launch, text="Model").grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.model_box = ttk.Combobox(launch, textvariable=self.model_var, state="readonly", width=24)
        self.model_box["values"] = ("default", launch_defaults["model"])
        self.model_box.grid(row=0, column=1, sticky="ew", padx=(0, 10))

        ttk.Label(launch, text="Approval").grid(row=0, column=2, sticky="w", padx=(0, 6))
        self.approval_box = ttk.Combobox(launch, textvariable=self.approval_var, state="readonly", width=12)
        self.approval_box["values"] = ("default", "untrusted", "on-request", "never")
        self.approval_box.grid(row=0, column=3, sticky="w", padx=(0, 10))

        ttk.Label(launch, text="Sandbox").grid(row=0, column=4, sticky="w", padx=(0, 6))
        self.sandbox_box = ttk.Combobox(launch, textvariable=self.sandbox_var, state="readonly", width=14)
        self.sandbox_box["values"] = ("default", "read-only", "workspace-write", "danger-full-access")
        self.sandbox_box.grid(row=0, column=5, sticky="w", padx=(0, 10))

        self.use_proxy_check = ttk.Checkbutton(
            launch,
            text="Use Proxy",
            variable=self.use_proxy_var,
            command=self._toggle_proxy_controls,
        )
        self.use_proxy_check.grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Label(launch, text="Type").grid(row=1, column=1, sticky="e", padx=(0, 6), pady=(8, 0))
        self.proxy_scheme_box = ttk.Combobox(launch, textvariable=self.proxy_scheme_var, state="readonly", width=10)
        self.proxy_scheme_box["values"] = TERMINAL_PROXY_SCHEMES
        self.proxy_scheme_box.grid(row=1, column=2, sticky="w", pady=(8, 0))
        ttk.Label(launch, text="Host").grid(row=1, column=3, sticky="e", padx=(0, 6), pady=(8, 0))
        self.proxy_host_entry = ttk.Entry(launch, textvariable=self.proxy_host_var, width=20)
        self.proxy_host_entry.grid(row=1, column=4, sticky="ew", pady=(8, 0))
        ttk.Label(launch, text="Port").grid(row=1, column=5, sticky="e", padx=(0, 6), pady=(8, 0))
        self.proxy_port_entry = ttk.Entry(launch, textvariable=self.proxy_port_var, width=8)
        self.proxy_port_entry.grid(row=1, column=6, sticky="w", pady=(8, 0))

        ttk.Label(launch, text="Reasoning").grid(row=2, column=0, sticky="w", padx=(0, 6), pady=(8, 0))
        self.reasoning_box = ttk.Combobox(launch, textvariable=self.reasoning_effort_var, state="readonly", width=10)
        self.reasoning_box["values"] = ("max", "default", "low", "medium", "high", "xhigh")
        self.reasoning_box.grid(row=2, column=1, sticky="w", pady=(8, 0))
        self.search_check = ttk.Checkbutton(launch, text="Search", variable=self.search_var)
        self.search_check.grid(row=2, column=2, sticky="w", padx=(14, 0), pady=(8, 0))
        ttk.Checkbutton(launch, text="Admin", variable=self.admin_var).grid(row=2, column=3, sticky="w", padx=(10, 0), pady=(8, 0))
        self.show_last_text_check = ttk.Checkbutton(
            launch,
            text="Show Last Text",
            variable=self.show_last_text_var,
            command=self._toggle_last_text_column,
        )
        self.show_last_text_check.grid(row=2, column=4, sticky="w", padx=(10, 0), pady=(8, 0))
        self.use_global_defaults_check = ttk.Checkbutton(
            launch,
            text="Use Global Defaults",
            variable=self.use_global_defaults_var,
            command=self._toggle_launch_overrides,
        )
        self.use_global_defaults_check.grid(row=2, column=5, sticky="w", padx=(10, 0), pady=(8, 0))

        for column in range(6):
            launch.grid_columnconfigure(column, weight=0)

        table_wrap = ttk.Frame(self.root, padding=(10, 0, 10, 0), style="App.TFrame")
        table_wrap.pack(fill=tk.BOTH, expand=True)

        columns = ("time", "session_id", "count", "model", "approval", "sandbox", "cwd", "text")
        self.tree = ttk.Treeview(table_wrap, columns=columns, show="headings")
        self.tree.heading("time", text="Time")
        self.tree.heading("session_id", text="Session ID")
        self.tree.heading("count", text="Records")
        self.tree.heading("model", text="Model")
        self.tree.heading("approval", text="Approval")
        self.tree.heading("sandbox", text="Sandbox")
        self.tree.heading("cwd", text="CWD")
        self.tree.heading("text", text="Last Text")

        self.tree.column("time", width=160, anchor=tk.W, stretch=False)
        self.tree.column("session_id", width=260, anchor=tk.W, stretch=True)
        self.tree.column("count", width=72, anchor=tk.CENTER, stretch=False)
        self.tree.column("model", width=120, anchor=tk.W, stretch=False)
        self.tree.column("approval", width=95, anchor=tk.W, stretch=False)
        self.tree.column("sandbox", width=120, anchor=tk.W, stretch=False)
        self.tree.column("cwd", width=220, anchor=tk.W, stretch=True)
        self.tree.column("text", width=360, anchor=tk.W, stretch=True)

        yscroll = ttk.Scrollbar(table_wrap, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=yscroll.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        yscroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree.bind("<Double-1>", lambda _e: self.open_selected_admin())
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._update_details_panel())
        self.tree.bind("<Configure>", self._on_tree_resize)
        self.tree.bind("<Button-3>", self._show_context_menu)

        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="Open Terminal", command=self.open_selected_admin)
        self.menu.add_command(label="Open File", command=self.open_selected_file)
        self.menu.add_command(label="Open Folder", command=self.open_selected_folder)
        self.menu.add_separator()
        self.menu.add_command(label="Delete", command=self.delete_selected)

        detail_frame = ttk.LabelFrame(self.root, text="Details / MCP / Skills", padding=10, style="Inspector.TLabelframe")
        detail_frame.pack(fill=tk.BOTH, expand=False, padx=10, pady=(8, 10))

        self.detail_tabs = ttk.Notebook(detail_frame)
        self.detail_tabs.pack(fill=tk.BOTH, expand=True)
        self._toggle_launch_overrides()
        self._toggle_proxy_controls()

        detail_page = ttk.Frame(self.detail_tabs)
        self.detail_tabs.add(detail_page, text="Session Details")
        note_row = ttk.Frame(detail_page)
        note_row.pack(fill=tk.X, pady=(6, 0))
        ttk.Label(note_row, text="Note").pack(side=tk.LEFT)
        self.note_var = tk.StringVar(value="")
        self.note_entry = ttk.Entry(note_row, textvariable=self.note_var)
        self.note_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 6))
        ttk.Button(note_row, text="Save Note", command=self.save_selected_note).pack(side=tk.LEFT)
        ttk.Button(note_row, text="Clear", command=self.clear_selected_note).pack(side=tk.LEFT, padx=(6, 0))
        self.note_entry.bind("<Return>", lambda _e: self.save_selected_note())
        self.details_text = tk.Text(detail_page, height=16, wrap=tk.WORD)
        self.details_text.pack(fill=tk.BOTH, expand=True, pady=(6, 0))
        self.details_text.configure(state=tk.DISABLED)

        mcp_page = ttk.Frame(self.detail_tabs)
        self.detail_tabs.add(mcp_page, text="MCP")
        self.mcp_tree = ttk.Treeview(mcp_page, columns=("name", "command", "timeout", "env", "args"), show="headings", height=8)
        self.mcp_tree.heading("name", text="Name")
        self.mcp_tree.heading("command", text="Command")
        self.mcp_tree.heading("timeout", text="Timeout")
        self.mcp_tree.heading("env", text="Env")
        self.mcp_tree.heading("args", text="Args")
        self.mcp_tree.column("name", width=150, anchor=tk.W)
        self.mcp_tree.column("command", width=120, anchor=tk.W)
        self.mcp_tree.column("timeout", width=70, anchor=tk.CENTER)
        self.mcp_tree.column("env", width=60, anchor=tk.CENTER)
        self.mcp_tree.column("args", width=700, anchor=tk.W)
        mcp_scroll = ttk.Scrollbar(mcp_page, orient=tk.VERTICAL, command=self.mcp_tree.yview)
        self.mcp_tree.configure(yscrollcommand=mcp_scroll.set)
        self.mcp_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        mcp_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.mcp_tree.bind("<<TreeviewSelect>>", lambda _e: self._update_mcp_details())

        self.mcp_details_text = tk.Text(mcp_page, height=5, wrap=tk.WORD)
        self.mcp_details_text.pack(fill=tk.X, expand=False, pady=(6, 0))
        self.mcp_details_text.configure(state=tk.DISABLED)

        skills_page = ttk.Frame(self.detail_tabs)
        self.detail_tabs.add(skills_page, text="Skills")
        self.skills_tree = ttk.Treeview(skills_page, columns=("name", "scripts", "path", "summary"), show="headings", height=8)
        self.skills_tree.heading("name", text="Name")
        self.skills_tree.heading("scripts", text="Scripts")
        self.skills_tree.heading("path", text="Path")
        self.skills_tree.heading("summary", text="Summary")
        self.skills_tree.column("name", width=160, anchor=tk.W)
        self.skills_tree.column("scripts", width=70, anchor=tk.CENTER)
        self.skills_tree.column("path", width=430, anchor=tk.W)
        self.skills_tree.column("summary", width=450, anchor=tk.W)
        skills_scroll = ttk.Scrollbar(skills_page, orient=tk.VERTICAL, command=self.skills_tree.yview)
        self.skills_tree.configure(yscrollcommand=skills_scroll.set)
        self.skills_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        skills_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.skills_tree.bind("<<TreeviewSelect>>", lambda _e: self._update_skill_details())
        self.skills_tree.bind("<Double-1>", lambda _e: self._open_selected_skill_path())

        self.skill_details_text = tk.Text(skills_page, height=5, wrap=tk.WORD)
        self.skill_details_text.pack(fill=tk.X, expand=False, pady=(6, 0))
        self.skill_details_text.configure(state=tk.DISABLED)

    def _init_fonts(self) -> None:
        style = ttk.Style(self.root)
        default_font = font.nametofont("TkDefaultFont")
        heading_font = font.nametofont("TkHeadingFont")
        text_font = font.nametofont("TkTextFont")
        self._base_fonts = {
            "default": int(default_font.cget("size")),
            "heading": int(heading_font.cget("size")),
            "text": int(text_font.cget("size")),
        }
        style.configure(
            "Treeview",
            rowheight=30,
            font=default_font,
            background="#ffffff",
            fieldbackground="#ffffff",
            foreground="#172033",
            bordercolor="#d8dee8",
            lightcolor="#d8dee8",
            darkcolor="#d8dee8",
        )
        style.configure(
            "Treeview.Heading",
            font=heading_font,
            background="#eef2f7",
            foreground="#334155",
            relief=tk.FLAT,
        )
        style.map("Treeview", background=[("selected", "#c7f3eb")], foreground=[("selected", "#0f172a")])
        for text_widget in (self.details_text, self.mcp_details_text, self.skill_details_text):
            text_widget.configure(
                font=text_font,
                relief=tk.FLAT,
                bd=0,
                padx=10,
                pady=10,
                bg="#ffffff",
                fg="#172033",
                insertbackground="#172033",
                selectbackground="#c7f3eb",
            )
        self.tree.tag_configure("odd", background="#f8fafc")
        self.tree.tag_configure("even", background="#ffffff")

    def _bind_shortcuts(self) -> None:
        self.root.bind_all("<Control-MouseWheel>", self._on_ctrl_wheel_windows)
        self.root.bind_all("<Control-Button-4>", self._on_ctrl_wheel_linux_up)
        self.root.bind_all("<Control-Button-5>", self._on_ctrl_wheel_linux_down)

    def _on_ctrl_wheel_windows(self, event: tk.Event) -> str:
        delta = 1 if getattr(event, "delta", 0) > 0 else -1
        self._apply_zoom(delta)
        return "break"

    def _on_ctrl_wheel_linux_up(self, _event: tk.Event) -> str:
        self._apply_zoom(1)
        return "break"

    def _on_ctrl_wheel_linux_down(self, _event: tk.Event) -> str:
        self._apply_zoom(-1)
        return "break"

    def _apply_zoom(self, delta: int) -> None:
        new_scale = max(0.8, min(1.8, self.font_scale + (0.1 * delta)))
        if abs(new_scale - self.font_scale) < 1e-6:
            return
        self.font_scale = new_scale
        style = ttk.Style(self.root)
        default_font = font.nametofont("TkDefaultFont")
        heading_font = font.nametofont("TkHeadingFont")
        text_font = font.nametofont("TkTextFont")
        default_font.configure(size=max(9, int(round(self._base_fonts["default"] * self.font_scale))))
        heading_font.configure(size=max(9, int(round(self._base_fonts["heading"] * self.font_scale))))
        text_font.configure(size=max(9, int(round(self._base_fonts["text"] * self.font_scale))))
        style.configure("Treeview", rowheight=max(24, int(round(30 * self.font_scale))), font=default_font)
        style.configure("Treeview.Heading", font=heading_font)
        self.details_text.configure(font=text_font)
        self.status_var.set(f"Zoom {int(self.font_scale * 100)}%")

    def _on_tree_resize(self, event: tk.Event) -> None:
        total = max(300, int(getattr(event, "width", 0)))
        fixed = sum(self._col_fixed.values())
        available = max(300, total - fixed - 28)
        flex_weights = dict(self._col_flex_weight)
        if not self.show_last_text_var.get():
            flex_weights["text"] = 0
        weight_sum = max(1, sum(flex_weights.values()))
        for name, weight in flex_weights.items():
            if name == "text" and not self.show_last_text_var.get():
                self.tree.column("text", width=0, minwidth=0, stretch=False)
                continue
            width = int(available * (weight / weight_sum))
            self.tree.column(name, width=max(120, width))

    def _toggle_last_text_column(self) -> None:
        if self.show_last_text_var.get():
            self.tree.heading("text", text="Last Text")
            self.tree.column("text", width=360, minwidth=80, stretch=True)
        else:
            self.tree.heading("text", text="")
            self.tree.column("text", width=0, minwidth=0, stretch=False)
        # Re-run layout after toggling the column.
        class E:
            width = self.tree.winfo_width()
        self._on_tree_resize(E())

    def _show_context_menu(self, event: tk.Event) -> None:
        row = self.tree.identify_row(event.y)
        if row:
            self.tree.selection_set(row)
            self.menu.tk_popup(event.x_root, event.y_root)

    def refresh(self, auto: bool = False) -> None:
        selected_session_id = self.tree.selection()[0] if self.tree.selection() else ""
        note_text = self.note_var.get()
        try:
            note_has_focus = self.root.focus_get() == self.note_entry
        except (KeyError, tk.TclError):
            # ttk.Combobox popdown can transiently appear in focus_get() lookup
            # without being registered as a Tk widget, raising KeyError('popdown').
            note_has_focus = False
        try:
            self.session_notes = self._load_session_notes()
            self.items = self._load_sessions(force=not auto)
            self.item_by_id = {i.session_id: i for i in self.items}
            if not auto or not self.mcp_items:
                self.mcp_items = self._load_mcp_items()
                self.skill_items = self._load_skill_items()
                self.available_models = self._load_available_models()
                self._render_mcp_items()
                self._render_skill_items()
                self._render_models()
            self._render_items(selected_session_id)
            self._refresh_account_status()
            if note_has_focus:
                self.note_var.set(note_text)
            if not auto:
                self.status_var.set(
                    f"Loaded sessions={len(self.items)} mcp={len(self.mcp_items)} skills={len(self.skill_items)}"
                )
        except Exception as exc:
            self.status_var.set("Load failed")
            if not auto:
                messagebox.showerror("Error", f"Failed to load data:\n{exc}")

    def _schedule_auto_refresh(self) -> None:
        self._auto_refresh_id = self.root.after(AUTO_REFRESH_MS, self._auto_refresh_tick)

    def _auto_refresh_tick(self) -> None:
        try:
            try:
                window_runtime.cleanup_stale_window_runtimes(CODEX_HOME)
            except OSError:
                pass
            self.refresh(auto=True)
        finally:
            if self.root.winfo_exists():
                self._schedule_auto_refresh()

    def _schedule_desktop_signal_watch(self) -> None:
        self._desktop_signal_id = self.root.after(DESKTOP_SIGNAL_POLL_MS, self._desktop_signal_tick)

    def _desktop_signal_tick(self) -> None:
        try:
            current_mtime = DESKTOP_REFRESH_SIGNAL_FILE.stat().st_mtime if DESKTOP_REFRESH_SIGNAL_FILE.exists() else 0.0
            if current_mtime and current_mtime > self._desktop_signal_mtime:
                self._desktop_signal_mtime = current_mtime
                self.refresh(auto=True)
            elif current_mtime:
                self._desktop_signal_mtime = current_mtime
        except OSError:
            pass
        finally:
            if self.root.winfo_exists():
                self._schedule_desktop_signal_watch()

    def _load_session_notes(self) -> dict[str, str]:
        if not NOTES_FILE.exists():
            return {}
        try:
            raw = NOTES_FILE.read_text(encoding="utf-8-sig", errors="ignore")
            obj = json.loads(raw)
            if not isinstance(obj, dict):
                return {}
            out: dict[str, str] = {}
            for k, v in obj.items():
                key = str(k).strip()
                if not key:
                    continue
                out[key] = str(v)
            return out
        except Exception:
            return {}

    def _save_session_notes(self) -> None:
        NOTES_FILE.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps(self.session_notes, ensure_ascii=False, indent=2)
        NOTES_FILE.write_text(content, encoding="utf-8")

    def _load_sessions(self, force: bool = False) -> list[SessionItem]:
        if not HISTORY_FILE.exists():
            raise FileNotFoundError(f"history file not found: {HISTORY_FILE}")
        current_signature = path_signature(HISTORY_FILE)
        if not force and self.items and current_signature == self._history_signature:
            return apply_session_notes(self.items, self.session_notes)

        latest: dict[str, dict[str, int | str]] = {}
        with HISTORY_FILE.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                session_id = obj.get("session_id")
                ts = int(obj.get("ts", 0))
                text = str(obj.get("text", ""))
                if not session_id:
                    continue
                prev = latest.get(session_id)
                if prev is None:
                    latest[session_id] = {"ts": ts, "text": text, "count": 1}
                else:
                    prev["count"] = int(prev["count"]) + 1
                    if ts >= int(prev["ts"]):
                        prev["ts"] = ts
                        prev["text"] = text

        items: list[SessionItem] = []
        for sid, data in latest.items():
            ts = int(data["ts"])
            text = str(data["text"])
            count = int(data["count"])
            session_file = self._find_session_file(sid)
            details = self._extract_session_details(session_file) if session_file else {}
            items.append(
                SessionItem(
                    session_id=sid,
                    ts=ts,
                    text=text,
                    note=self.session_notes.get(sid, ""),
                    history_count=count,
                    cwd=str(details.get("cwd", "")),
                    model=str(details.get("model", "")),
                    approval_policy=str(details.get("approval_policy", "")),
                    sandbox_mode=str(details.get("sandbox_mode", "")),
                    turn_id=str(details.get("turn_id", "")),
                    session_file=session_file or "",
                )
            )

        items.sort(key=lambda i: i.ts, reverse=True)
        self._history_signature = current_signature
        return items

    def _load_mcp_items(self) -> list[McpItem]:
        items: list[McpItem] = []
        if not CONFIG_FILE.exists():
            return items
        try:
            raw = CONFIG_FILE.read_text(encoding="utf-8-sig", errors="ignore")
            conf = tomllib.loads(raw)
        except Exception:
            return self._load_mcp_items_fallback()

        servers = conf.get("mcp_servers", {})
        if not isinstance(servers, dict):
            return items

        for name, cfg in servers.items():
            if not isinstance(cfg, dict):
                continue
            command = str(cfg.get("command", ""))
            timeout = str(cfg.get("startup_timeout_sec", ""))
            args_cfg = cfg.get("args", [])
            args = " ".join(str(x) for x in args_cfg) if isinstance(args_cfg, list) else str(args_cfg)
            env_cfg = cfg.get("env", {})
            env_count = len(env_cfg) if isinstance(env_cfg, dict) else 0
            items.append(
                McpItem(
                    name=str(name),
                    command=command,
                    timeout=timeout,
                    env_count=env_count,
                    args=args,
                )
            )

        items.sort(key=lambda x: x.name.lower())
        return items

    def _load_mcp_items_fallback(self) -> list[McpItem]:
        # Fallback parser for non-strict TOML files; extracts MCP blocks by headers.
        text = CONFIG_FILE.read_text(encoding="utf-8-sig", errors="ignore")
        lines = text.splitlines()
        block: dict[str, dict[str, object]] = {}
        current = ""
        in_env = False
        for raw in lines:
            line = raw.strip()
            if not line:
                continue
            if line.startswith("[") and line.endswith("]"):
                header = line[1:-1].strip()
                in_env = False
                current = ""
                if header.startswith("mcp_servers."):
                    parts = header.split(".")
                    if len(parts) >= 2:
                        current = parts[1]
                        in_env = len(parts) >= 3 and parts[2] == "env"
                        if current not in block:
                            block[current] = {
                                "command": "",
                                "timeout": "",
                                "args": "",
                                "env_count": 0,
                            }
                continue
            if not current or current not in block:
                continue
            item = block[current]
            if in_env:
                if "=" in line and not line.startswith("#"):
                    item["env_count"] = int(item["env_count"]) + 1
                continue
            if line.startswith("command"):
                item["command"] = line.split("=", 1)[1].strip().strip('"').strip("'")
            elif line.startswith("startup_timeout_sec"):
                item["timeout"] = line.split("=", 1)[1].strip()
            elif line.startswith("args"):
                item["args"] = line.split("=", 1)[1].strip()

        items: list[McpItem] = []
        for name, obj in block.items():
            items.append(
                McpItem(
                    name=name,
                    command=str(obj.get("command", "")),
                    timeout=str(obj.get("timeout", "")),
                    env_count=int(obj.get("env_count", 0)),
                    args=str(obj.get("args", "")),
                )
            )
        items.sort(key=lambda x: x.name.lower())
        return items

    def _load_skill_items(self) -> list[SkillItem]:
        items: list[SkillItem] = []
        if not SKILLS_DIR.exists():
            return items

        for skill_md in SKILLS_DIR.rglob("SKILL.md"):
            skill_dir = skill_md.parent
            name = skill_dir.name
            has_scripts = (skill_dir / "scripts").exists()
            summary = ""
            try:
                with skill_md.open("r", encoding="utf-8") as f:
                    for line in f:
                        t = line.strip()
                        if t and not t.startswith("#"):
                            summary = t
                            break
            except Exception:
                summary = ""

            items.append(
                SkillItem(
                    name=name,
                    path=str(skill_dir),
                    has_scripts=has_scripts,
                    summary=summary,
                )
            )

        items.sort(key=lambda x: x.name.lower())
        return items

    def _load_available_models(self) -> list[str]:
        settings_loader = getattr(self, "_reload_backend_settings", None)
        settings = settings_loader() if callable(settings_loader) else getattr(self, "backend_settings", {})
        if isinstance(settings, dict) and settings.get("backend_mode") == token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE:
            openai_models = unique_model_ids([DEFAULT_PRIMARY_MODEL, *unique_model_ids(settings.get("openai_models", []))])
            saved_openai_model = str(settings.get("openai_model", "")).strip()
            if saved_openai_model and saved_openai_model not in openai_models:
                openai_models.insert(0, saved_openai_model)
            if openai_models:
                return openai_models
        models: list[str] = []
        if MODELS_CACHE_FILE.exists():
            try:
                with MODELS_CACHE_FILE.open("r", encoding="utf-8-sig", errors="ignore") as f:
                    data = json.load(f)
                raw_models = data.get("models", [])
                if isinstance(raw_models, list):
                    for item in raw_models:
                        if not isinstance(item, dict):
                            continue
                        visibility = str(item.get("visibility", ""))
                        if visibility and visibility != "list":
                            continue
                        slug = str(item.get("slug", "")).strip()
                        if slug and not slug.startswith("gpt-image"):
                            models.append(slug)
            except Exception:
                models = []
        return merge_available_models(models)

    def _render_models(self) -> None:
        values = ["default", *self.available_models]
        self.model_box["values"] = values
        current = self.model_var.get().strip()
        if not current or current not in values:
            self.model_var.set(default_launch_model_choice(values))

    def _find_session_file(self, session_id: str) -> str | None:
        if not SESSIONS_DIR.exists():
            return None
        for root, _dirs, files in os.walk(SESSIONS_DIR):
            for name in files:
                if session_id in name and is_primary_session_jsonl_name(name):
                    return str(Path(root) / name)
        return None

    def _extract_session_details(self, session_file: str) -> dict[str, str]:
        if not session_file:
            return {}
        details: dict[str, str] = {
            "cwd": "",
            "model": "",
            "approval_policy": "",
            "sandbox_mode": "",
            "turn_id": "",
        }
        try:
            with open(session_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if obj.get("type") == "turn_context":
                        payload = obj.get("payload", {})
                        details["cwd"] = str(payload.get("cwd", details["cwd"]))
                        details["model"] = str(payload.get("model", details["model"]))
                        details["approval_policy"] = str(payload.get("approval_policy", details["approval_policy"]))
                        sandbox_policy = payload.get("sandbox_policy", {})
                        if isinstance(sandbox_policy, dict):
                            details["sandbox_mode"] = str(sandbox_policy.get("type", details["sandbox_mode"]))
                        details["turn_id"] = str(payload.get("turn_id", details["turn_id"]))
        except OSError:
            return {}
        return details

    def _render_items(self, selected_session_id: str = "") -> None:
        for iid in self.tree.get_children():
            self.tree.delete(iid)

        for idx, item in enumerate(self.items):
            timestr = datetime.fromtimestamp(item.ts).strftime("%Y-%m-%d %H:%M:%S") if item.ts else ""
            tag = "even" if idx % 2 == 0 else "odd"
            self.tree.insert(
                "",
                tk.END,
                iid=item.session_id,
                values=(
                    timestr,
                    item.session_id,
                    item.history_count,
                    item.model,
                    item.approval_policy,
                    item.sandbox_mode,
                    item.cwd,
                    item.text.replace("\n", " "),
                ),
                tags=(tag,),
            )
        if selected_session_id and selected_session_id in self.item_by_id:
            self.tree.selection_set(selected_session_id)
            self.tree.focus(selected_session_id)
            self.tree.see(selected_session_id)
        self._update_details_panel()

    def _render_mcp_items(self) -> None:
        for iid in self.mcp_tree.get_children():
            self.mcp_tree.delete(iid)
        self._mcp_item_map.clear()
        for idx, item in enumerate(self.mcp_items):
            tag = "even" if idx % 2 == 0 else "odd"
            iid = f"mcp_{idx}"
            self.mcp_tree.insert(
                "",
                tk.END,
                iid=iid,
                values=(item.name, item.command, item.timeout, item.env_count, item.args),
                tags=(tag,),
            )
            self._mcp_item_map[iid] = item
        self.mcp_tree.tag_configure("odd", background="#f7f9fc")
        self.mcp_tree.tag_configure("even", background="#ffffff")
        self._update_mcp_details()

    def _render_skill_items(self) -> None:
        for iid in self.skills_tree.get_children():
            self.skills_tree.delete(iid)
        self._skill_item_map.clear()
        for idx, item in enumerate(self.skill_items):
            tag = "even" if idx % 2 == 0 else "odd"
            iid = f"skill_{idx}"
            self.skills_tree.insert(
                "",
                tk.END,
                iid=iid,
                values=(item.name, "yes" if item.has_scripts else "no", item.path, item.summary),
                tags=(tag,),
            )
            self._skill_item_map[iid] = item
        self.skills_tree.tag_configure("odd", background="#f7f9fc")
        self.skills_tree.tag_configure("even", background="#ffffff")
        self._update_skill_details()

    def _update_mcp_details(self) -> None:
        sel = self.mcp_tree.selection()
        if not sel:
            text = "Select an MCP row to view details."
        else:
            item = self._mcp_item_map.get(sel[0])
            if not item:
                text = "No details."
            else:
                text = (
                    f"Name: {item.name}\n"
                    f"Command: {item.command or '-'}\n"
                    f"Timeout: {item.timeout or '-'}\n"
                    f"Env Vars: {item.env_count}\n"
                    f"Args: {item.args or '-'}\n"
                )
        self.mcp_details_text.configure(state=tk.NORMAL)
        self.mcp_details_text.delete("1.0", tk.END)
        self.mcp_details_text.insert("1.0", text)
        self.mcp_details_text.configure(state=tk.DISABLED)

    def _update_skill_details(self) -> None:
        sel = self.skills_tree.selection()
        if not sel:
            text = "Select a skill row to view details. Double-click to open its folder."
        else:
            item = self._skill_item_map.get(sel[0])
            if not item:
                text = "No details."
            else:
                text = (
                    f"Name: {item.name}\n"
                    f"Path: {item.path}\n"
                    f"Has scripts/: {'yes' if item.has_scripts else 'no'}\n"
                    f"Summary: {item.summary or '-'}\n"
                )
        self.skill_details_text.configure(state=tk.NORMAL)
        self.skill_details_text.delete("1.0", tk.END)
        self.skill_details_text.insert("1.0", text)
        self.skill_details_text.configure(state=tk.DISABLED)

    def _open_selected_skill_path(self) -> None:
        sel = self.skills_tree.selection()
        if not sel:
            return
        item = self._skill_item_map.get(sel[0])
        if not item:
            return
        p = Path(item.path)
        if p.exists():
            os.startfile(str(p))  # type: ignore[attr-defined]

    def _update_details_panel(self) -> None:
        item = self._selected_session()
        if not item:
            self.note_entry.configure(state="disabled")
            self.note_var.set("")
            self.details_text.configure(state=tk.NORMAL)
            self.details_text.delete("1.0", tk.END)
            self.details_text.insert("1.0", "Select a session to view detailed metadata.")
            self.details_text.configure(state=tk.DISABLED)
            return

        self.note_entry.configure(state="normal")
        note = self.session_notes.get(item.session_id, item.note)
        item.note = note
        try:
            note_has_focus = self.root.focus_get() == self.note_entry
        except Exception:
            note_has_focus = False
        if not note_has_focus:
            self.note_var.set(note)
        time_str = datetime.fromtimestamp(item.ts).strftime("%Y-%m-%d %H:%M:%S") if item.ts else ""
        content = (
            f"Session ID: {item.session_id}\n"
            f"Last Time: {time_str}\n"
            f"History Records: {item.history_count}\n"
            f"Model: {item.model or '-'}\n"
            f"Approval Policy: {item.approval_policy or '-'}\n"
            f"Sandbox Mode: {item.sandbox_mode or '-'}\n"
            f"Turn ID: {item.turn_id or '-'}\n"
            f"CWD: {item.cwd or '-'}\n"
            f"Note: {note or '-'}\n"
            f"Session File: {item.session_file or '-'}\n"
            f"Last Text:\n{item.text or '-'}\n"
        )
        self.details_text.configure(state=tk.NORMAL)
        self.details_text.delete("1.0", tk.END)
        self.details_text.insert("1.0", content)
        self.details_text.configure(state=tk.DISABLED)

    def save_selected_note(self) -> None:
        item = self._selected_session()
        if not item:
            messagebox.showinfo("Info", "Please select a session first.")
            return

        note = self.note_var.get().strip()
        if note:
            self.session_notes[item.session_id] = note
        else:
            self.session_notes.pop(item.session_id, None)
        item.note = note
        self._save_session_notes()
        self._update_details_panel()
        self.status_var.set(f"Saved note for {item.session_id}")

    def clear_selected_note(self) -> None:
        item = self._selected_session()
        if not item:
            messagebox.showinfo("Info", "Please select a session first.")
            return

        self.note_var.set("")
        self.session_notes.pop(item.session_id, None)
        item.note = ""
        self._save_session_notes()
        self._update_details_panel()
        self.status_var.set(f"Cleared note for {item.session_id}")

    def _selected_session(self) -> SessionItem | None:
        selected = self.tree.selection()
        if not selected:
            return None
        sid = selected[0]
        return self.item_by_id.get(sid)

    def _build_codex_override_args(self, settings: dict[str, object] | None = None) -> list[str]:
        resolved_settings = settings if settings is not None else self._token_pool_settings()
        args: list[str] = []
        use_launch_defaults = self.use_global_defaults_var.get()
        if use_launch_defaults:
            launch_defaults = default_launch_options()
            model = launch_defaults["model"]
            approval = launch_defaults["approval"]
            sandbox = launch_defaults["sandbox"]
            reasoning = launch_defaults["reasoning_effort"]
            search_enabled = False
        else:
            model = self.model_var.get().strip()
            approval = self.approval_var.get().strip()
            sandbox = self.sandbox_var.get().strip()
            reasoning_var = getattr(self, "reasoning_effort_var", None)
            reasoning = reasoning_var.get().strip() if reasoning_var is not None else "default"
            search_enabled = self.search_var.get()

        if (
            model
            and model != "default"
            and not self._is_openai_compatible_backend_enabled(resolved_settings)
        ):
            args.extend(["-m", model])

        if approval and approval != "default":
            args.extend(["-a", approval])

        if sandbox and sandbox != "default":
            args.extend(["-s", sandbox])

        if reasoning and reasoning != "default":
            args.extend(["-c", f'model_reasoning_effort="{reasoning}"'])

        if search_enabled:
            args.append("--search")
        return args

    def _is_openai_compatible_backend_enabled(
        self,
        settings: dict[str, object] | None = None,
    ) -> bool:
        resolved_settings = settings if settings is not None else self._token_pool_settings()
        return resolved_settings.get("backend_mode") == token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE

    def _selected_launch_model(self) -> str:
        use_global_defaults_var = getattr(self, "use_global_defaults_var", None)
        if use_global_defaults_var is None or use_global_defaults_var.get():
            return ""
        selected = self.model_var.get().strip()
        return selected if selected and selected != "default" else ""

    def _resolve_openai_compatible_launch_model(
        self,
        *candidates: str,
        settings: dict[str, object] | None = None,
    ) -> str:
        resolved_settings = settings if settings is not None else self._token_pool_settings()
        allowed_models = unique_model_ids(resolved_settings.get("openai_models", []))
        for candidate in candidates:
            clean_candidate = str(candidate).strip()
            if (
                clean_candidate
                and clean_candidate != "default"
                and (
                    clean_candidate == DEFAULT_PRIMARY_MODEL
                    or not allowed_models
                    or clean_candidate in allowed_models
                )
            ):
                return clean_candidate
        configured_model = str(resolved_settings.get("openai_model", "")).strip()
        if configured_model and (not allowed_models or configured_model in allowed_models):
            return configured_model
        if allowed_models:
            return allowed_models[0]
        return configured_model or DEFAULT_PRIMARY_MODEL

    def _ensure_openai_compatible_launch_model_metadata(self, settings: dict[str, object], model: str) -> None:
        if settings.get("backend_mode") != token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE:
            return
        model_ids = unique_model_ids(settings.get("openai_models", []))
        clean_model = str(model).strip()
        if clean_model:
            model_ids = unique_model_ids([clean_model, *model_ids])
        if not model_ids:
            configured_model = str(settings.get("openai_model", "")).strip()
            if configured_model:
                model_ids = [configured_model]
        token_pool_settings.ensure_openai_compatible_model_metadata(
            model_ids,
            models_cache_file=token_pool_settings.DEFAULT_MODELS_CACHE_FILE,
        )

    def _build_codex_resume_args(
        self,
        item: SessionItem,
        settings: dict[str, object] | None = None,
    ) -> list[str]:
        resolved_settings = settings if settings is not None else self._token_pool_settings()
        args: list[str] = ["codex.cmd", "resume", item.session_id]
        args.extend(self._build_codex_override_args(resolved_settings))
        if self._is_openai_compatible_backend_enabled(resolved_settings):
            backend_model = self._resolve_openai_compatible_launch_model(
                self._selected_launch_model(),
                settings=resolved_settings,
            )
            self._ensure_openai_compatible_launch_model_metadata(resolved_settings, backend_model)
            args.extend(["-m", backend_model])
        else:
            backend_model = (
                item.model.strip()
                or self._configured_backend_model(resolved_settings)
                or DEFAULT_PRIMARY_MODEL
            )
        args.extend(self._build_backend_override_args(backend_model, resolved_settings))
        return args

    def _build_codex_new_args(
        self,
        settings: dict[str, object] | None = None,
    ) -> list[str]:
        resolved_settings = settings if settings is not None else self._token_pool_settings()
        args: list[str] = ["codex.cmd"]
        args.extend(self._build_codex_override_args(resolved_settings))
        selected_model = self.model_var.get().strip()
        if self._is_openai_compatible_backend_enabled(resolved_settings):
            backend_model = self._resolve_openai_compatible_launch_model(
                self._selected_launch_model(),
                settings=resolved_settings,
            )
            self._ensure_openai_compatible_launch_model_metadata(resolved_settings, backend_model)
            args.extend(["-m", backend_model])
        else:
            backend_model = (
                selected_model
                if selected_model and selected_model != "default"
                else self._configured_backend_model(resolved_settings) or DEFAULT_PRIMARY_MODEL
            )
        args.extend(
            self._build_backend_override_args(backend_model, resolved_settings)
        )
        return args

    def _toggle_launch_overrides(self) -> None:
        if self.use_global_defaults_var.get():
            state = "disabled"
        else:
            state = "readonly"
        self.model_box.configure(state=state)
        self.approval_box.configure(state=state)
        self.sandbox_box.configure(state=state)
        self.reasoning_box.configure(state=state)
        self.search_check.configure(state="disabled" if self.use_global_defaults_var.get() else "normal")

    def _to_ps_arg_string(self, args: list[str]) -> str:
        escaped: list[str] = []
        for a in args:
            escaped.append("'" + a.replace("'", "''") + "'")
        return " ".join(escaped)

    def _resolve_terminal_codex_args(self, codex_args: list[str]) -> list[str]:
        if not codex_args:
            return codex_args
        if codex_args[0].lower() != "codex.cmd":
            return codex_args
        configured = configured_codex_executable()
        if configured is not None and codex_executable_is_healthy(configured):
            opener = configured_codex_file_opener()
            opener_args = (
                ["-c", f'file_opener="{opener}"']
                if opener is not None
                else []
            )
            return [str(configured), *opener_args, *codex_args[1:]]
        resolved = shutil.which("codex.cmd")
        if not resolved:
            return codex_args
        return [resolved, *codex_args[1:]]

    def _build_proxy_ps_prefix(self, settings: dict[str, object] | None = None) -> str:
        resolved_settings = settings if settings is not None else self._token_pool_settings()
        mode = resolved_settings.get("backend_mode", "")
        if mode == token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE:
            pref = token_pool_settings.effective_openai_proxy_preference(resolved_settings)
        else:
            # For token_pool and codex_auth modes, use UI checkbox
            pref = "proxy" if self.use_proxy_var.get() else "direct"
        enabled = pref == "proxy"
        return build_proxy_environment_ps_prefix(
            enabled=enabled,
            scheme=self.proxy_scheme_var.get(),
            host=self.proxy_host_var.get(),
            port_text=self.proxy_port_var.get(),
        )

    def _reload_backend_settings(self) -> dict[str, object]:
        self.backend_settings = token_pool_settings.load_backend_settings()
        return self.backend_settings

    def _token_pool_settings(self) -> dict[str, object]:
        return self._reload_backend_settings()

    def _configured_backend_model(self, settings: dict[str, object] | None = None) -> str:
        resolved_settings = settings if settings is not None else self._token_pool_settings()
        if resolved_settings.get("backend_mode") == token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE:
            return str(resolved_settings.get("openai_model", "")).strip()
        return ""

    def _build_token_pool_ps_prefix(self, settings: dict[str, object] | None = None) -> str:
        resolved_settings = settings if settings is not None else self._token_pool_settings()
        return build_token_pool_environment_ps_prefix(
            env_key_name=TOKEN_POOL_ENV_KEY_NAME,
            api_key_value=str(resolved_settings.get("proxy_api_key", "")),
        )

    def _build_openai_compatible_ps_prefix(
        self,
        settings: dict[str, object] | None = None,
    ) -> str:
        resolved_settings = settings if settings is not None else self._token_pool_settings()
        # Use proxy API key when proxy is running (protocol translation)
        # Use upstream API key for direct connection (no proxy)
        if _is_proxy_needed_for_openai_compatible(resolved_settings):
            api_key = str(resolved_settings.get("proxy_api_key", ""))
        else:
            api_key = str(resolved_settings.get("openai_api_key", ""))
        if not api_key.strip():
            api_key = str(resolved_settings.get("proxy_api_key", ""))
        return build_openai_compatible_environment_ps_prefix(
            env_key_name=OPENAI_COMPAT_ENV_KEY_NAME,
            api_key_value=api_key,
        )

    def _token_pool_health(
        self,
        port: int | None = None,
        expected_backend_mode: str = "",
        settings: dict[str, object] | None = None,
    ) -> dict[str, object] | None:
        resolved_settings = settings if settings is not None else self._token_pool_settings()
        health_port = int(
            port or resolved_settings.get("proxy_port", token_pool_settings.DEFAULT_PROXY_PORT)
        )
        req = url_request.Request(
            f"http://127.0.0.1:{health_port}/health",
            headers={"Accept": "application/json"},
            method="GET",
        )
        try:
            with url_request.urlopen(req, timeout=0.5) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except (OSError, ValueError, url_error.URLError):
            return None
        if not isinstance(payload, dict):
            return None
        if expected_backend_mode and not backend_health_matches(payload, expected_backend_mode):
            return None
        return payload

    def _build_token_pool_proxy_env(
        self,
        settings: dict[str, object] | None = None,
    ) -> dict[str, str]:
        env = os.environ.copy()
        env["PYTHONNOUSERSITE"] = "1"
        resolved_settings = settings if settings is not None else self._token_pool_settings()
        mode = resolved_settings.get("backend_mode", "")
        if mode == token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE:
            pref = token_pool_settings.effective_openai_proxy_preference(resolved_settings)
        else:
            # For token_pool and codex_auth modes, use UI checkbox
            pref = "proxy" if self.use_proxy_var.get() else "direct"
        use_proxy = pref == "proxy"
        if use_proxy:
            proxy_prefix = build_proxy_environment_ps_prefix(
                enabled=True,
                scheme=self.proxy_scheme_var.get(),
                host=self.proxy_host_var.get(),
                port_text=self.proxy_port_var.get(),
            )
            proxy_map = {
                "HTTP_PROXY": None,
                "HTTPS_PROXY": None,
                "ALL_PROXY": None,
                "http_proxy": None,
                "https_proxy": None,
                "all_proxy": None,
                "NO_PROXY": DEFAULT_NO_PROXY,
                "no_proxy": DEFAULT_NO_PROXY,
            }
            clean_scheme = self.proxy_scheme_var.get().strip().lower() or "http"
            clean_host = self.proxy_host_var.get().strip() or "127.0.0.1"
            clean_port = int(self.proxy_port_var.get())
            proxy_url = f"{clean_scheme}://{clean_host}:{clean_port}"
            for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
                env[key] = proxy_url
            env["NO_PROXY"] = DEFAULT_NO_PROXY
            env["no_proxy"] = DEFAULT_NO_PROXY
            _ = proxy_prefix
        else:
            for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
                env.pop(key, None)
            env["NO_PROXY"] = DEFAULT_NO_PROXY
            env["no_proxy"] = DEFAULT_NO_PROXY
        return env

    def _start_token_pool_proxy(
        self,
        settings: dict[str, object] | None = None,
    ) -> None:
        resolved_settings = settings if settings is not None else self._token_pool_settings()
        if resolved_settings.get("backend_mode") == token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE:
            # Only start proxy if protocol translation is needed
            if _is_proxy_needed_for_openai_compatible(resolved_settings):
                self._start_openai_compatible_proxy(resolved_settings)
            return
        if resolved_settings.get("backend_mode") != token_pool_settings.BACKEND_MODE_TOKEN_POOL:
            return
        token_dir = Path(
            str(resolved_settings.get("token_dir", token_pool_settings.DEFAULT_TOKEN_POOL_DIR))
        )
        token_pool_settings.ensure_token_pool_dir(token_dir)
        token_files = token_pool_settings.list_token_files(token_dir)
        if not token_files:
            raise RuntimeError(f"No token files found in {token_dir}")
        port = int(resolved_settings.get("proxy_port", token_pool_settings.DEFAULT_PROXY_PORT))
        if self._token_pool_health(
            port,
            token_pool_settings.BACKEND_MODE_TOKEN_POOL,
            resolved_settings,
        ):
            return
        if self._token_pool_health(port, settings=resolved_settings):
            self._stop_token_pool_proxy()
            time.sleep(0.2)
            if self._token_pool_health(port, settings=resolved_settings):
                raise RuntimeError(f"Port {port} is already used by a different backend proxy.")
        command = build_token_pool_proxy_command(
            executable=sys.executable,
            app_path=str(Path(__file__).resolve()),
            port=port,
            api_key=str(resolved_settings.get("proxy_api_key", "")),
            token_dir=str(token_dir),
            frozen=getattr(sys, "frozen", False),
        )
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        proc = subprocess.Popen(
            command,
            cwd=str(APP_DIR),
            env=self._build_token_pool_proxy_env(resolved_settings),
            creationflags=creationflags,
        )
        save_token_pool_proxy_state(
            {
                "pid": proc.pid,
                "port": port,
                "token_dir": str(token_dir),
                "started_at": time.time(),
            }
        )
        deadline = time.time() + 6.0
        while time.time() < deadline:
            if self._token_pool_health(
                port,
                token_pool_settings.BACKEND_MODE_TOKEN_POOL,
                resolved_settings,
            ):
                return
            time.sleep(0.2)
        raise RuntimeError("Built-in token pool proxy did not become ready.")

    def _start_openai_compatible_proxy(
        self,
        settings: dict[str, object] | None = None,
    ) -> None:
        if settings is None:
            # Manual proxy starts retain the existing model refresh behavior.
            try:
                refreshed = refresh_openai_compatible_models_from_upstream()
                self.backend_settings = refreshed
            except Exception:
                pass
            resolved_settings = self._token_pool_settings()
        else:
            resolved_settings = settings
        port = int(resolved_settings.get("proxy_port", token_pool_settings.DEFAULT_PROXY_PORT))
        upstream_base_url = str(
            resolved_settings.get(
                "openai_base_url",
                token_pool_settings.DEFAULT_OPENAI_BASE_URL,
            )
        ).strip()
        upstream_api_key = str(resolved_settings.get("openai_api_key", "")).strip()
        upstream_protocol = str(resolved_settings.get("openai_protocol", "")).strip()
        upstream_proxy_url = str(resolved_settings.get("upstream_proxy_url", "")).strip()
        model_ids = [
            str(item).strip()
            for item in resolved_settings.get("openai_models", [])
            if str(item).strip()
        ]
        if not upstream_base_url or not upstream_api_key or not upstream_protocol:
            raise RuntimeError("Save the OpenAI-Compatible API settings before using this backend.")
        health = self._token_pool_health(
            port,
            token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE,
            resolved_settings,
        )
        if health and openai_compatible_proxy_health_matches_settings(health, resolved_settings):
            return
        if health:
            self._stop_token_pool_proxy()
            time.sleep(0.2)
            if self._token_pool_health(port, settings=resolved_settings):
                raise RuntimeError(f"Port {port} is already used by a stale OpenAI-compatible backend proxy.")
        elif self._token_pool_health(port, settings=resolved_settings):
            self._stop_token_pool_proxy()
            time.sleep(0.2)
            if self._token_pool_health(port, settings=resolved_settings):
                raise RuntimeError(f"Port {port} is already used by a different backend proxy.")
        command = build_custom_provider_proxy_command(
            executable=sys.executable,
            app_path=str(Path(__file__).resolve()),
            port=port,
            api_key=str(resolved_settings.get("proxy_api_key", "")),
            upstream_base_url=upstream_base_url,
            upstream_api_key=upstream_api_key,
            upstream_protocol=upstream_protocol,
            upstream_proxy_url=upstream_proxy_url,
            model_ids=model_ids,
            frozen=getattr(sys, "frozen", False),
        )
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        proc = subprocess.Popen(
            command,
            cwd=str(APP_DIR),
            env=self._build_token_pool_proxy_env(resolved_settings),
            creationflags=creationflags,
        )
        save_token_pool_proxy_state(
            {
                "pid": proc.pid,
                "port": port,
                "backend_mode": token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE,
                "upstream_protocol": upstream_protocol,
                "upstream_proxy_url": upstream_proxy_url,
                "started_at": time.time(),
            }
        )
        deadline = time.time() + 6.0
        while time.time() < deadline:
            if self._token_pool_health(
                port,
                token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE,
                resolved_settings,
            ):
                return
            time.sleep(0.2)
        raise RuntimeError("OpenAI-compatible backend proxy did not become ready.")

    def _stop_token_pool_proxy(self) -> None:
        state = load_token_pool_proxy_state()
        pid = int(state.get("pid", 0) or 0)
        if pid > 0:
            run_taskkill_tree_silently(pid)
        clear_token_pool_proxy_state()

    def _restart_token_pool_proxy(self) -> None:
        self._stop_token_pool_proxy()
        time.sleep(0.2)
        settings = self._token_pool_settings()
        if settings.get("backend_mode") == token_pool_settings.BACKEND_MODE_CODEX_AUTH:
            return
        self._start_token_pool_proxy()

    def _token_pool_status_summary(self) -> str:
        settings = self._token_pool_settings()
        token_dir = Path(str(settings.get("token_dir", token_pool_settings.DEFAULT_TOKEN_POOL_DIR)))
        token_files = token_pool_settings.list_token_files(token_dir)
        token_count = len(token_files)
        port = int(settings.get("proxy_port", token_pool_settings.DEFAULT_PROXY_PORT))
        mode = str(settings.get("backend_mode", token_pool_settings.BACKEND_MODE_CODEX_AUTH))
        expected_mode = expected_backend_mode_for_settings(settings)
        raw_health = self._token_pool_health(port) if expected_mode else None
        health = raw_health if backend_health_matches(raw_health, expected_mode) else None
        if mode == token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE:
            base_url = str(settings.get("openai_base_url", token_pool_settings.DEFAULT_OPENAI_BASE_URL)).strip()
            model = str(settings.get("openai_model", "")).strip() or "default"
            model_count = len(settings.get("openai_models", []) or [])
            has_key = bool(str(settings.get("openai_api_key", "")).strip())
            protocol = str(settings.get("openai_protocol", "")).strip() or "unverified"
            running = "running" if health else "stopped"
            return (
                f"Mode: {mode}\n"
                f"Base URL: {base_url}\n"
                f"Protocol: {protocol}\n"
                f"Saved model: {model}\n"
                f"Discovered models: {model_count}\n"
                f"API key: {'configured' if has_key else 'missing'}\n"
                f"Proxy: {running}"
            )
        running = "running" if health else "stopped"
        summary = f"Mode: {mode}\nToken files: {token_count}\nPort: {port}\nProxy: {running}"
        current_token_file = ""
        if isinstance(health, dict):
            current_token_file = str(health.get("current_token_file", "")).strip()
        if not current_token_file and token_count == 1:
            current_token_file = token_files[0].name
        if current_token_file:
            quota = read_token_pool_token_quota(token_dir / current_token_file)
            summary += f"\nCurrent token: {current_token_file}"
            email = str(quota.get("email", "")).strip()
            if email:
                summary += f"\nCurrent token email: {email}"
            quota_summary = str(quota.get("summary", "")).strip()
            if quota_summary:
                summary += f"\nCurrent token quota: {quota_summary}"
        return summary

    def _apply_openai_compatible_preset_settings(
        self,
        preset_id: str,
        *,
        settings_file: Path = token_pool_settings.DEFAULT_SETTINGS_FILE,
        preset_name: str | None = None,
        openai_base_url: str | None = None,
        openai_api_key: str | None = None,
        openai_model: str | None = None,
        openai_protocol: str | None = None,
        proxy_preference: str | None = None,
        disable_image_generation: bool | None = None,
    ) -> dict[str, object]:
        existing = token_pool_settings.load_backend_settings(settings_file)
        existing_preset = _find_openai_preset(existing, preset_id)
        resolved_disable_image_generation = _resolve_disable_image_generation(existing_preset, disable_image_generation)
        resolved_name = (
            preset_name.strip()
            if preset_name is not None and preset_name.strip()
            else str(existing_preset.get("name", preset_id)).strip() or preset_id.strip()
        )
        resolved_base_url = (
            openai_base_url.strip()
            if openai_base_url is not None and openai_base_url.strip()
            else str(existing_preset.get("openai_base_url", token_pool_settings.DEFAULT_OPENAI_BASE_URL))
        )
        resolved_api_key = (
            openai_api_key.strip()
            if openai_api_key is not None and openai_api_key.strip()
            else str(existing_preset.get("openai_api_key", ""))
        )
        selected_model = (
            openai_model.strip()
            if openai_model is not None
            else str(existing_preset.get("openai_model", "")).strip()
        )
        manual_extra_models = [
            str(item).strip()
            for item in existing_preset.get("openai_manual_extra_models", []) or []
            if str(item).strip()
        ]
        candidate_models = _merge_openai_models(
            existing_preset.get("openai_models", []),
            manual_extra_models,
            selected_model,
        )
        candidate_protocol = _resolved_manual_openai_protocol(
            openai_protocol or "",
            str(existing_preset.get("openai_protocol", "")),
        )
        raw_proxy_preference = (
            proxy_preference.strip()
            if proxy_preference is not None and proxy_preference.strip()
            else str(existing_preset.get("proxy_preference", "direct")).strip()
        )
        candidate_proxy_preference = (
            raw_proxy_preference
            if raw_proxy_preference in {"auto", "direct", "proxy"}
            else "direct"
        )
        upstream_proxy_url = str(existing_preset.get("upstream_proxy_url", ""))
        skip_validation = bool(existing_preset.get("skip_validation", False))
        previous_proxy_preference = token_pool_settings.get_active_proxy_preference()
        if skip_validation:
            resolved: dict[str, object] = {
                "openai_base_url": resolved_base_url,
                "openai_api_key": resolved_api_key,
                "openai_model": selected_model,
                "openai_models": candidate_models,
                "openai_protocol": candidate_protocol,
            }
        else:
            token_pool_settings.set_active_proxy_preference(candidate_proxy_preference)
            try:
                resolved = token_pool_settings.resolve_openai_compatible_backend_config(
                    resolved_base_url,
                    resolved_api_key,
                    selected_model,
                    upstream_proxy_url=upstream_proxy_url,
                )
            except Exception:
                token_pool_settings.set_active_proxy_preference(previous_proxy_preference)
                raise
        try:
            final_base_url = str(resolved.get("openai_base_url", resolved_base_url))
            final_api_key = str(resolved.get("openai_api_key", resolved_api_key))
            final_model = str(resolved.get("openai_model", selected_model))
            final_models = resolved.get("openai_models", candidate_models)
            final_protocol = _resolved_manual_openai_protocol(
                candidate_protocol,
                str(resolved.get("openai_protocol", candidate_protocol)),
            )
            updated = token_pool_settings.save_and_activate_openai_preset(
                settings_file=settings_file,
                preset_id=preset_id.strip(),
                name=resolved_name,
                openai_base_url=final_base_url,
                openai_api_key=final_api_key,
                openai_model=final_model,
                openai_models=final_models,
                openai_protocol=final_protocol,
                openai_manual_extra_models=manual_extra_models,
                proxy_preference=candidate_proxy_preference,
                upstream_proxy_url=upstream_proxy_url,
                skip_validation=skip_validation,
                installation_id=str(existing_preset.get("installation_id", "")),
                claude_env=existing_preset.get("claude_env", {}),
                disable_image_generation=resolved_disable_image_generation,
            )
        except Exception:
            if not skip_validation:
                token_pool_settings.set_active_proxy_preference(previous_proxy_preference)
            raise
        self.backend_settings = updated
        active_preset = next((item for item in updated.get("openai_presets", []) if isinstance(item, dict) and str(item.get("id", "")).strip() == preset_id.strip()), {})
        _swap_installation_id_for_preset(active_preset)
        _patch_claude_settings_for_preset(active_preset)
        _patch_image_generation_for_preset(active_preset)
        self._stop_token_pool_proxy()
        time.sleep(0.2)
        # Only start proxy if protocol translation is needed
        if _is_proxy_needed_for_openai_compatible(updated):
            self._start_openai_compatible_proxy()
        self.available_models = self._load_available_models()
        self._render_models()
        return updated

    def _delete_openai_compatible_preset_settings(
        self,
        preset_id: str,
        *,
        settings_file: Path = token_pool_settings.DEFAULT_SETTINGS_FILE,
    ) -> dict[str, object]:
        previous = self._token_pool_settings()
        updated = token_pool_settings.delete_openai_preset(preset_id, settings_file=settings_file)
        self.backend_settings = updated
        previous_mode = str(previous.get("backend_mode", token_pool_settings.BACKEND_MODE_CODEX_AUTH))
        updated_mode = str(updated.get("backend_mode", token_pool_settings.BACKEND_MODE_CODEX_AUTH))
        if previous_mode == token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE or updated_mode == token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE:
            _patch_image_generation_for_backend_mode(updated_mode)
            self._stop_token_pool_proxy()
            time.sleep(0.2)
            # Only start proxy if protocol translation is needed
            if _is_proxy_needed_for_openai_compatible(updated):
                self._start_openai_compatible_proxy()
        self.available_models = self._load_available_models()
        self._render_models()
        return updated

    def _build_backend_override_args(
        self,
        fallback_model: str,
        settings: dict[str, object] | None = None,
    ) -> list[str]:
        resolved_settings = settings if settings is not None else self._token_pool_settings()
        mode = resolved_settings.get("backend_mode")
        if mode == token_pool_settings.BACKEND_MODE_TOKEN_POOL:
            return build_token_pool_provider_override_args(
                model=fallback_model,
                proxy_port=int(
                    resolved_settings.get(
                        "proxy_port",
                        token_pool_settings.DEFAULT_PROXY_PORT,
                    )
                ),
                provider_name=TOKEN_POOL_PROVIDER_NAME,
                env_key_name=TOKEN_POOL_ENV_KEY_NAME,
            )
        if mode == token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE:
            # Detect if proxy is needed based on protocol mismatch
            # Codex uses 'responses' by default, proxy only needed for 'chat_completions' upstream
            if _is_proxy_needed_for_openai_compatible(resolved_settings):
                # Protocol mismatch: use proxy for translation
                # Proxy always presents as 'responses' to Codex, translates to upstream's protocol
                base_url = (
                    "http://127.0.0.1:"
                    f"{int(resolved_settings.get('proxy_port', token_pool_settings.DEFAULT_PROXY_PORT))}"
                )
                wire_api = "responses"
            else:
                # Protocol match: direct connection to upstream (no proxy needed)
                # Use upstream's actual protocol
                base_url = str(
                    resolved_settings.get(
                        "openai_base_url",
                        token_pool_settings.DEFAULT_OPENAI_BASE_URL,
                    )
                ).strip()
                wire_api = (
                    str(resolved_settings.get("openai_protocol", "responses")).strip()
                    or "responses"
                )
            return build_openai_compatible_provider_override_args(
                model=fallback_model,
                base_url=base_url,
                provider_name=OPENAI_COMPAT_PROVIDER_NAME,
                env_key_name=OPENAI_COMPAT_ENV_KEY_NAME,
                wire_api=wire_api,
            )
        return build_codex_auth_provider_override_args()

    def _ensure_backend_ready(
        self,
        settings: dict[str, object] | None = None,
    ) -> None:
        resolved_settings = settings if settings is not None else self._token_pool_settings()
        if resolved_settings.get("backend_mode") == token_pool_settings.BACKEND_MODE_TOKEN_POOL:
            self._start_token_pool_proxy(resolved_settings)
        elif resolved_settings.get("backend_mode") == token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE:
            _patch_image_generation_for_backend_mode(token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE)
            token_pool_settings.ensure_openai_compatible_model_metadata(
                unique_model_ids(resolved_settings.get("openai_models", []))
                or [str(resolved_settings.get("openai_model", "")).strip()]
            )
            # Only start proxy if protocol translation is needed
            if _is_proxy_needed_for_openai_compatible(resolved_settings):
                self._start_openai_compatible_proxy(resolved_settings)

    def _toggle_proxy_controls(self) -> None:
        proxy_controls_enabled = self.use_proxy_var.get()
        state = "readonly" if proxy_controls_enabled else "disabled"
        entry_state = "normal" if proxy_controls_enabled else "disabled"
        self.proxy_scheme_box.configure(state=state)
        self.proxy_host_entry.configure(state=entry_state)
        self.proxy_port_entry.configure(state=entry_state)
        self.use_proxy_check.configure(state="normal")

    def _prepare_window_runtime(
        self,
        settings: dict[str, object],
        *,
        session_id: str,
    ) -> window_runtime.WindowRuntime:
        mode = str(
            settings.get(
                "backend_mode",
                token_pool_settings.BACKEND_MODE_CODEX_AUTH,
            )
        )
        isolate_home = mode != token_pool_settings.BACKEND_MODE_CODEX_AUTH
        installation_id = (
            str(settings.get("installation_id", "")).strip()
            if mode == token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE
            else ""
        )
        return window_runtime.prepare_window_runtime(
            base_home=CODEX_HOME,
            isolate_home=isolate_home,
            session_id=session_id,
            installation_id=installation_id,
        )

    def _runtime_cleanup_command(self) -> list[str | Path]:
        if getattr(sys, "frozen", False):
            return [sys.executable, "--window-runtime-cleanup"]
        source_command = build_source_python_command(
            sys.executable,
            str(APP_DIR / "window_runtime.py"),
        )
        return [*source_command, "cleanup"]

    def _build_terminal_ps_command(
        self,
        cwd: str,
        codex_args: list[str],
        settings: dict[str, object] | None = None,
        runtime: window_runtime.WindowRuntime | None = None,
    ) -> str:
        resolved_settings = settings if settings is not None else self._token_pool_settings()
        cwd_escaped = cwd.replace("'", "''")
        codex_args = self._resolve_terminal_codex_args(codex_args)
        proxy_prefix = self._build_proxy_ps_prefix(resolved_settings)
        clear_api_prefix = build_clear_api_environment_ps_prefix()
        token_pool_prefix = ""
        openai_compatible_prefix = ""
        if resolved_settings.get("backend_mode") == token_pool_settings.BACKEND_MODE_TOKEN_POOL:
            token_pool_prefix = self._build_token_pool_ps_prefix(resolved_settings)
        elif resolved_settings.get("backend_mode") == token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE:
            openai_compatible_prefix = self._build_openai_compatible_ps_prefix(
                resolved_settings
            )
        inner_command = (
            "chcp 65001 > $null; "
            "$utf8 = [System.Text.UTF8Encoding]::new($false); "
            "[Console]::InputEncoding = $utf8; "
            "[Console]::OutputEncoding = $utf8; "
            "$OutputEncoding = $utf8; "
            f"{proxy_prefix}"
            f"{clear_api_prefix}"
            f"{token_pool_prefix}"
            f"{openai_compatible_prefix}"
            f"Set-Location -LiteralPath '{cwd_escaped}'; "
            f"& {self._to_ps_arg_string(codex_args)}"
        )
        if runtime is None:
            return inner_command
        return window_runtime.build_runtime_powershell_wrapper(
            inner_command,
            runtime=runtime,
            cleanup_command=self._runtime_cleanup_command(),
        )

    def _launch_terminal_with_runtime(
        self,
        ps_command: str,
        runtime: window_runtime.WindowRuntime,
    ) -> subprocess.Popen[bytes]:
        try:
            return launch_terminal_command(ps_command, self.admin_var.get())
        except Exception:
            try:
                window_runtime.cleanup_window_runtime(
                    runtime.runtime_dir,
                    runtime.runtime_root,
                )
            except (OSError, window_runtime.WindowRuntimeError):
                pass
            raise

    def _refresh_account_status(self) -> None:
        auth_info = auth_slots.current_auth_info()
        active_slot = auth_slots.detect_active_slot()
        slots = auth_slots.list_account_slots()
        self.account_var.set(format_account_status_label(active_slot, auth_info, find_slot_info(active_slot, slots)))

    def open_remote_ssh_dialog(self) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("Remote SSH")
        dialog.transient(self.root)
        dialog.resizable(False, False)
        dialog.grab_set()

        host_var = tk.StringVar(value="")
        user_var = tk.StringVar(value=os.environ.get("USERNAME", ""))
        password_var = tk.StringVar(value="")
        identity_var = tk.StringVar(value="")
        status_var = tk.StringVar(value="Use a Tailscale IP or MagicDNS host. Password mode requires plink.exe.")

        frame = ttk.Frame(dialog, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="Tailscale host").grid(row=0, column=0, sticky="w", pady=(0, 8))
        host_entry = ttk.Entry(frame, textvariable=host_var, width=48)
        host_entry.grid(row=0, column=1, sticky="ew", pady=(0, 8))

        ttk.Label(frame, text="SSH user").grid(row=1, column=0, sticky="w", pady=(0, 8))
        ttk.Entry(frame, textvariable=user_var, width=48).grid(row=1, column=1, sticky="ew", pady=(0, 8))

        ttk.Label(frame, text="Password").grid(row=2, column=0, sticky="w", pady=(0, 8))
        ttk.Entry(frame, textvariable=password_var, width=48, show="*").grid(row=2, column=1, sticky="ew", pady=(0, 8))

        ttk.Label(frame, text="Identity file").grid(row=3, column=0, sticky="w", pady=(0, 8))
        identity_row = ttk.Frame(frame)
        identity_row.grid(row=3, column=1, sticky="ew", pady=(0, 8))
        ttk.Entry(identity_row, textvariable=identity_var, width=38).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(identity_row, text="Browse", command=lambda: browse_identity_file()).pack(side=tk.LEFT, padx=(6, 0))

        ttk.Label(frame, textvariable=status_var, justify=tk.LEFT, wraplength=420).grid(row=4, column=0, columnspan=2, sticky="w", pady=(4, 10))

        button_row = ttk.Frame(frame)
        button_row.grid(row=5, column=0, columnspan=2, sticky="e")
        ttk.Button(button_row, text="Cancel", command=dialog.destroy).pack(side=tk.RIGHT)
        restart_button = ttk.Button(button_row, text="Restart Computer", command=lambda: restart_remote())
        restart_button.pack(side=tk.RIGHT, padx=(0, 8))

        frame.columnconfigure(1, weight=1)
        host_entry.focus_set()

        def browse_identity_file() -> None:
            selected = filedialog.askopenfilename(parent=dialog, title="Select SSH identity file")
            if selected:
                identity_var.set(selected)

        def finish_restart(result: subprocess.CompletedProcess[str] | Exception) -> None:
            restart_button.configure(state="normal")
            if isinstance(result, Exception):
                messagebox.showerror("Remote SSH", str(result), parent=dialog)
                status_var.set("Restart command failed.")
                return
            output = (result.stdout or "").strip()
            if result.returncode == 0:
                status_var.set("Restart command sent.")
                self.status_var.set(f"Remote restart sent to {host_var.get().strip()}")
                return
            message = output or f"ssh exited with code {result.returncode}"
            messagebox.showerror("Remote SSH", message, parent=dialog)
            status_var.set("Restart command failed.")

        def restart_remote() -> None:
            host = host_var.get().strip()
            user = user_var.get().strip()
            password = password_var.get().strip()
            identity_file = identity_var.get().strip()
            if not host or not user:
                messagebox.showerror("Remote SSH", "Tailscale host and SSH user are required.", parent=dialog)
                return
            if not messagebox.askyesno("Remote SSH", f"Restart {user}@{host} now?", parent=dialog):
                return
            restart_button.configure(state="disabled")
            status_var.set("Sending restart command...")

            def worker() -> None:
                try:
                    result = remote_ssh.restart_computer(
                        user=user,
                        host=host,
                        identity_file=identity_file,
                        password=password,
                    )
                except Exception as exc:
                    dialog.after(0, lambda: finish_restart(exc))
                    return
                dialog.after(0, lambda: finish_restart(result))

            threading.Thread(target=worker, daemon=True).start()

    def open_accounts_dialog(self) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("Accounts")
        dialog.transient(self.root)
        dialog.resizable(True, True)
        dialog.grab_set()
        width, height = account_dialog_dimensions(dialog.winfo_screenwidth(), dialog.winfo_screenheight())
        dialog.geometry(f"{width}x{height}")
        dialog.minsize(min(560, width), min(360, height))

        body = ttk.Frame(dialog)
        body.pack(fill=tk.BOTH, expand=True)
        canvas = tk.Canvas(body, highlightthickness=0)
        scrollbar = ttk.Scrollbar(body, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        container = ttk.Frame(canvas, padding=12)
        container_window = canvas.create_window((0, 0), window=container, anchor="nw")

        def update_scroll_region(_event: tk.Event | None = None) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))

        def resize_container(event: tk.Event) -> None:
            canvas.itemconfigure(container_window, width=event.width)

        def scroll_with_wheel(event: tk.Event) -> None:
            if event.delta:
                canvas.yview_scroll(int(-event.delta / 120), "units")

        container.bind("<Configure>", update_scroll_region)
        canvas.bind("<Configure>", resize_container)
        canvas.bind("<Enter>", lambda _event: canvas.bind_all("<MouseWheel>", scroll_with_wheel))
        canvas.bind("<Leave>", lambda _event: canvas.unbind_all("<MouseWheel>"))
        dialog.bind("<Destroy>", lambda event: canvas.unbind_all("<MouseWheel>") if event.widget == dialog else None)

        current_var = tk.StringVar(value="")
        quota_var = tk.StringVar(value="Quota unavailable")
        ttk.Label(container, text="Current login", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        ttk.Label(container, textvariable=current_var, justify=tk.LEFT).pack(anchor="w", pady=(4, 10))
        ttk.Label(container, text="Current weekly quota", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        ttk.Label(container, textvariable=quota_var, justify=tk.LEFT).pack(anchor="w", pady=(4, 10))
        ttk.Label(
            container,
            text=(
                "Bind each slot once, then switch with one click. Only future requests use the new account. "
                "Running Codex terminals or replies keep their current auth until restarted."
            ),
            wraplength=560,
            justify=tk.LEFT,
        ).pack(anchor="w", pady=(0, 10))

        slots_frame = ttk.Frame(container)
        slots_frame.pack(fill=tk.BOTH, expand=True)

        action_row = ttk.Frame(container)
        action_row.pack(fill=tk.X, pady=(0, 10))
        ttk.Button(action_row, text="New Slot", command=lambda: create_slot()).pack(side=tk.LEFT)

        backend_mode_var = tk.StringVar(value=str(self._token_pool_settings().get("backend_mode", token_pool_settings.BACKEND_MODE_CODEX_AUTH)))
        token_dir_var = tk.StringVar(value="")
        token_pool_status_var = tk.StringVar(value="")
        openai_base_url_var = tk.StringVar(value="")
        openai_api_key_var = tk.StringVar(value="")
        openai_model_var = tk.StringVar(value="")
        openai_preset_var = tk.StringVar(value="")
        openai_preset_id_var = tk.StringVar(value="")
        openai_preset_name_var = tk.StringVar(value="")
        openai_proxy_preference_var = tk.StringVar(value="direct")
        openai_protocol_var = tk.StringVar(value="responses")
        openai_disable_image_generation_var = tk.BooleanVar(value=False)
        openai_status_var = tk.StringVar(value="")

        token_pool_frame = ttk.LabelFrame(container, text="Backend", padding=10)
        token_pool_frame.pack(fill=tk.X, pady=(0, 10))

        mode_row = ttk.Frame(token_pool_frame)
        mode_row.pack(fill=tk.X)
        ttk.Radiobutton(mode_row, text="Use Codex Auth", variable=backend_mode_var, value=token_pool_settings.BACKEND_MODE_CODEX_AUTH).pack(side=tk.LEFT)
        ttk.Radiobutton(mode_row, text="Use Built-in Token Pool", variable=backend_mode_var, value=token_pool_settings.BACKEND_MODE_TOKEN_POOL).pack(side=tk.LEFT, padx=(12, 0))
        ttk.Radiobutton(mode_row, text="Use OpenAI-Compatible API", variable=backend_mode_var, value=token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE).pack(side=tk.LEFT, padx=(12, 0))
        ttk.Button(mode_row, text="Apply Mode", command=lambda: apply_backend_mode()).pack(side=tk.RIGHT)

        ttk.Label(token_pool_frame, text="Token folder", font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(10, 0))
        ttk.Label(token_pool_frame, textvariable=token_dir_var, justify=tk.LEFT, wraplength=540).pack(anchor="w", pady=(4, 8))
        ttk.Label(token_pool_frame, text="Status", font=("Segoe UI", 9, "bold")).pack(anchor="w")
        ttk.Label(token_pool_frame, textvariable=token_pool_status_var, justify=tk.LEFT, wraplength=540).pack(anchor="w", pady=(4, 8))

        token_pool_button_row = ttk.Frame(token_pool_frame)
        token_pool_button_row.pack(fill=tk.X)
        ttk.Button(token_pool_button_row, text="Import Token Files", command=lambda: import_token_files_dialog()).pack(side=tk.LEFT)
        ttk.Button(token_pool_button_row, text="Open Token Folder", command=lambda: open_token_folder()).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(token_pool_button_row, text="Start Proxy", command=lambda: start_token_pool_proxy_dialog()).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(token_pool_button_row, text="Stop Proxy", command=lambda: stop_token_pool_proxy_dialog()).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(token_pool_button_row, text="Restart Proxy", command=lambda: restart_token_pool_proxy_dialog()).pack(side=tk.LEFT, padx=(8, 0))

        ttk.Separator(token_pool_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=(12, 10))
        ttk.Label(token_pool_frame, text="OpenAI-Compatible API", font=("Segoe UI", 9, "bold")).pack(anchor="w")

        openai_preset_row = ttk.Frame(token_pool_frame)
        openai_preset_row.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(openai_preset_row, text="Preset", width=16).pack(side=tk.LEFT)
        openai_preset_box = ttk.Combobox(openai_preset_row, textvariable=openai_preset_var, state="readonly")
        openai_preset_box.pack(side=tk.LEFT, fill=tk.X, expand=True)

        openai_preset_id_row = ttk.Frame(token_pool_frame)
        ttk.Label(openai_preset_id_row, text="Preset ID", width=16).pack(side=tk.LEFT)
        ttk.Entry(openai_preset_id_row, textvariable=openai_preset_id_var).pack(side=tk.LEFT, fill=tk.X, expand=True)

        openai_preset_name_row = ttk.Frame(token_pool_frame)
        openai_preset_name_row.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(openai_preset_name_row, text="Preset name", width=16).pack(side=tk.LEFT)
        ttk.Entry(openai_preset_name_row, textvariable=openai_preset_name_var).pack(side=tk.LEFT, fill=tk.X, expand=True)

        openai_base_url_row = ttk.Frame(token_pool_frame)
        openai_base_url_row.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(openai_base_url_row, text="Base URL", width=16).pack(side=tk.LEFT)
        ttk.Entry(openai_base_url_row, textvariable=openai_base_url_var).pack(side=tk.LEFT, fill=tk.X, expand=True)

        openai_api_key_row = ttk.Frame(token_pool_frame)
        openai_api_key_row.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(openai_api_key_row, text="API Key", width=16).pack(side=tk.LEFT)
        ttk.Entry(openai_api_key_row, textvariable=openai_api_key_var, show=OPENAI_API_KEY_ENTRY_SHOW).pack(side=tk.LEFT, fill=tk.X, expand=True)

        openai_model_row = ttk.Frame(token_pool_frame)
        openai_model_row.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(openai_model_row, text="Model", width=16).pack(side=tk.LEFT)
        openai_model_box = ttk.Combobox(openai_model_row, textvariable=openai_model_var, state="readonly")
        openai_model_box.pack(side=tk.LEFT, fill=tk.X, expand=True)

        openai_proxy_row = ttk.Frame(token_pool_frame)
        openai_proxy_row.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(openai_proxy_row, text="Proxy mode", width=16).pack(side=tk.LEFT)
        openai_proxy_box = ttk.Combobox(openai_proxy_row, textvariable=openai_proxy_preference_var, state="readonly", values=("auto", "direct", "proxy"))
        openai_proxy_box.pack(side=tk.LEFT, fill=tk.X, expand=True)

        openai_protocol_row = ttk.Frame(token_pool_frame)
        openai_protocol_row.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(openai_protocol_row, text="Protocol", width=16).pack(side=tk.LEFT)
        openai_protocol_box = ttk.Combobox(openai_protocol_row, textvariable=openai_protocol_var, state="readonly", values=("responses", "chat_completions"))
        openai_protocol_box.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Checkbutton(
            openai_protocol_row,
            text="Disable image generation",
            variable=openai_disable_image_generation_var,
        ).pack(side=tk.LEFT, padx=(8, 0))

        ttk.Label(token_pool_frame, text="OpenAI status", font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(10, 0))
        ttk.Label(token_pool_frame, textvariable=openai_status_var, justify=tk.LEFT, wraplength=540).pack(anchor="w", pady=(4, 8))

        openai_button_row = ttk.Frame(token_pool_frame)
        openai_button_row.pack(fill=tk.X)
        ttk.Button(openai_button_row, text="Save / Refresh Models", command=lambda: save_openai_compatible_settings_dialog()).pack(side=tk.LEFT)
        ttk.Button(openai_button_row, text="Save as Preset", command=lambda: save_openai_compatible_preset_dialog()).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(openai_button_row, text="Apply Preset", command=lambda: apply_openai_preset_dialog()).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(openai_button_row, text="Delete Preset", command=lambda: delete_openai_preset_dialog()).pack(side=tk.LEFT, padx=(8, 0))

        def refresh_token_pool_section() -> None:
            # Pure auto-sync: pull /v1/models when opening or refreshing the dialog.
            try:
                refreshed = refresh_openai_compatible_models_from_upstream()
                self.backend_settings = refreshed
            except Exception:
                pass
            settings = self._token_pool_settings()
            token_dir = Path(str(settings.get("token_dir", token_pool_settings.DEFAULT_TOKEN_POOL_DIR)))
            token_pool_settings.ensure_token_pool_dir(token_dir)
            backend_mode_var.set(str(settings.get("backend_mode", token_pool_settings.BACKEND_MODE_CODEX_AUTH)))
            token_dir_var.set(str(token_dir))
            openai_form_values = openai_account_form_values(settings)
            openai_base_url_var.set(str(openai_form_values.get("openai_base_url", token_pool_settings.DEFAULT_OPENAI_BASE_URL)).strip())
            openai_api_key_var.set(str(openai_form_values.get("openai_api_key", "")).strip())
            raw_pref = str(openai_form_values.get("proxy_preference", "direct")).strip()
            openai_proxy_preference_var.set(raw_pref if raw_pref in {"auto", "direct", "proxy"} else "direct")
            raw_proto = str(openai_form_values.get("openai_protocol", "responses")).strip()
            openai_protocol_var.set(raw_proto if raw_proto in {"responses", "chat_completions"} else "responses")
            openai_presets = [
                item
                for item in settings.get("openai_presets", []) or []
                if isinstance(item, dict) and str(item.get("id", "")).strip()
            ]
            preset_labels = [
                f"{str(item.get('id', '')).strip()} | {str(item.get('name', '')).strip() or str(item.get('id', '')).strip()}"
                for item in openai_presets
            ]
            openai_preset_box["values"] = preset_labels
            active_preset_id = str(settings.get("active_openai_preset_id", token_pool_settings.DEFAULT_OPENAI_PRESET_ID)).strip()
            active_preset = next((item for item in openai_presets if str(item.get("id", "")).strip() == active_preset_id), None)
            active_label = (
                f"{active_preset_id} | {str(active_preset.get('name', '')).strip() or active_preset_id}"
                if active_preset is not None
                else ""
            )
            openai_preset_var.set(active_label)
            openai_preset_id_var.set(active_preset_id)
            openai_preset_name_var.set(str(active_preset.get("name", "")).strip() if active_preset is not None else active_preset_id)
            openai_disable_image_generation_var.set(
                bool(active_preset.get("disable_image_generation", False)) if active_preset is not None else bool(settings.get("disable_image_generation", False))
            )
            openai_models = [str(item).strip() for item in openai_form_values.get("openai_models", []) if str(item).strip()]
            openai_model_values, saved_openai_model = openai_model_form_state(
                openai_form_values,
                fallback_models=merge_available_models([]),
                allow_fallback=active_preset is None,
            )
            openai_model_box["values"] = openai_model_values
            openai_model_var.set(saved_openai_model)
            openai_status_var.set(
                f"Discovered models: {len(openai_models)}\n"
                f"Protocol: {str(openai_form_values.get('openai_protocol', '')).strip() or 'unverified'}\n"
                f"Proxy mode: {openai_proxy_preference_var.get()}\n"
                f"Image generation: {'disabled' if openai_disable_image_generation_var.get() else 'enabled'}\n"
                f"Active preset: {active_preset_id or '-'}\n"
                f"API key: {'configured' if str(openai_form_values.get('openai_api_key', '')).strip() else 'missing'}"
            )
            try:
                token_pool_status_var.set(self._token_pool_status_summary())
            except Exception as exc:
                token_pool_status_var.set(f"Status unavailable: {exc}")
            dialog.after_idle(update_scroll_region)

        def selected_openai_preset_id() -> str:
            raw = openai_preset_var.get().strip()
            if " | " in raw:
                return raw.split(" | ", 1)[0].strip()
            return raw

        def update_openai_preset_fields_from_selection(_event: object | None = None) -> None:
            settings = self._token_pool_settings()
            preset_id = selected_openai_preset_id()
            presets = settings.get("openai_presets", [])
            preset = next(
                (
                    item
                    for item in presets
                    if isinstance(item, dict) and str(item.get("id", "")).strip() == preset_id
                ),
                None,
            ) if isinstance(presets, list) else None
            openai_preset_id_var.set(preset_id)
            if isinstance(preset, dict):
                openai_preset_name_var.set(str(preset.get("name", "")).strip() or preset_id)
                preset_values = openai_preset_form_values(preset)
                openai_base_url_var.set(str(preset_values["openai_base_url"]))
                openai_api_key_var.set(str(preset_values["openai_api_key"]))
                model_values, preset_model = openai_model_form_state(
                    preset_values,
                    allow_fallback=False,
                )
                openai_model_box["values"] = model_values
                openai_model_var.set(preset_model)
                openai_proxy_preference_var.set(str(preset_values["proxy_preference"]))
                raw_proto = str(preset_values["openai_protocol"])
                openai_protocol_var.set(raw_proto if raw_proto in {"responses", "chat_completions"} else "responses")
                openai_disable_image_generation_var.set(bool(preset.get("disable_image_generation", False)))

        openai_preset_box.bind("<<ComboboxSelected>>", update_openai_preset_fields_from_selection)

        def apply_backend_mode() -> None:
            settings = self._token_pool_settings()
            previous_backend_mode = str(settings.get("backend_mode", token_pool_settings.BACKEND_MODE_CODEX_AUTH))
            token_dir = Path(str(settings.get("token_dir", token_pool_settings.DEFAULT_TOKEN_POOL_DIR)))
            try:
                updated = apply_backend_mode_settings(
                    backend_mode=backend_mode_var.get(),
                    settings_file=token_pool_settings.DEFAULT_SETTINGS_FILE,
                    token_dir=token_dir,
                    proxy_port=int(settings.get("proxy_port", token_pool_settings.DEFAULT_PROXY_PORT)),
                    proxy_api_key=str(settings.get("proxy_api_key", "")),
                    openai_base_url=openai_base_url_var.get(),
                    openai_api_key=openai_api_key_var.get(),
                    openai_model=openai_model_var.get(),
                    openai_models=settings.get("openai_models", []),
                    openai_protocol=openai_protocol_var.get().strip(),
                )
            except Exception as exc:
                messagebox.showerror("Backend Mode", str(exc), parent=dialog)
                return
            self.backend_settings = updated
            updated_backend_mode = str(updated.get("backend_mode", token_pool_settings.BACKEND_MODE_CODEX_AUTH))
            if (
                updated_backend_mode == token_pool_settings.BACKEND_MODE_CODEX_AUTH
                or (
                    previous_backend_mode in {
                        token_pool_settings.BACKEND_MODE_TOKEN_POOL,
                        token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE,
                    }
                    and previous_backend_mode != updated_backend_mode
                )
            ):
                self._stop_token_pool_proxy()
            self.available_models = self._load_available_models()
            self._render_models()
            refresh_token_pool_section()
            self.status_var.set(f"Auth backend set to {updated.get('backend_mode')}")

        def save_openai_compatible_settings_dialog() -> None:
            settings = self._token_pool_settings()
            token_dir = Path(str(settings.get("token_dir", token_pool_settings.DEFAULT_TOKEN_POOL_DIR)))
            base_url = openai_base_url_var.get().strip() or token_pool_settings.DEFAULT_OPENAI_BASE_URL
            api_key = openai_api_key_var.get().strip()
            selected_model = openai_model_var.get().strip()
            try:
                updated = save_openai_compatible_backend_settings(
                    settings_file=token_pool_settings.DEFAULT_SETTINGS_FILE,
                    token_dir=token_dir,
                    proxy_port=int(settings.get("proxy_port", token_pool_settings.DEFAULT_PROXY_PORT)),
                    proxy_api_key=str(settings.get("proxy_api_key", "")),
                    base_url=base_url,
                    api_key=api_key,
                    model=selected_model,
                    preset_id=selected_openai_preset_id(),
                    preset_name=openai_preset_name_var.get().strip(),
                    proxy_preference=openai_proxy_preference_var.get().strip(),
                    protocol_override=openai_protocol_var.get().strip(),
                    disable_image_generation=openai_disable_image_generation_var.get(),
                )
            except Exception as exc:
                messagebox.showerror("OpenAI-Compatible API", str(exc), parent=dialog)
                return
            self.backend_settings = updated
            backend_mode_var.set(token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE)
            self.available_models = self._load_available_models()
            self._render_models()
            refresh_token_pool_section()
            # Show auto-selected model when user didn't pick one.
            if not selected_model:
                auto_model = str(updated.get("openai_model", "")).strip()
                if auto_model:
                    openai_model_var.set(auto_model)
            saved_models = list(updated.get("openai_models", []) or [])
            self.status_var.set(f"Saved OpenAI-compatible backend settings ({len(saved_models)} model(s))")

        def save_openai_compatible_preset_dialog() -> None:
            settings = self._token_pool_settings()
            base_url = openai_base_url_var.get().strip() or token_pool_settings.DEFAULT_OPENAI_BASE_URL
            api_key = openai_api_key_var.get().strip()
            selected_model = openai_model_var.get().strip()
            preset_name = openai_preset_name_var.get().strip()
            if not preset_name:
                messagebox.showerror("OpenAI-Compatible API", "Enter a preset name before saving a new preset.", parent=dialog)
                return
            try:
                updated = save_openai_compatible_preset_settings(
                    settings_file=token_pool_settings.DEFAULT_SETTINGS_FILE,
                    base_url=base_url,
                    api_key=api_key,
                    model=selected_model,
                    preset_id="",
                    preset_name=preset_name,
                    create_new_preset=True,
                    proxy_preference=openai_proxy_preference_var.get().strip(),
                    protocol_override=openai_protocol_var.get().strip(),
                    disable_image_generation=openai_disable_image_generation_var.get(),
                )
            except Exception as exc:
                messagebox.showerror("OpenAI-Compatible API", str(exc), parent=dialog)
                return
            self.backend_settings = updated
            backend_mode_var.set(str(updated.get("backend_mode", token_pool_settings.BACKEND_MODE_CODEX_AUTH)))
            self.available_models = self._load_available_models()
            self._render_models()
            refresh_token_pool_section()
            saved_models = list(updated.get("openai_models", []) or [])
            active_id = str(updated.get("active_openai_preset_id", "")).strip()
            self.status_var.set(f"Saved new OpenAI preset: {active_id} ({len(saved_models)} model(s))")

        def apply_openai_preset_dialog() -> None:
            preset_id = selected_openai_preset_id()
            if not preset_id:
                messagebox.showerror("OpenAI-Compatible API", "Select an OpenAI preset first.", parent=dialog)
                return
            try:
                updated = self._apply_openai_compatible_preset_settings(
                    preset_id,
                    preset_name=openai_preset_name_var.get().strip(),
                    openai_base_url=openai_base_url_var.get().strip(),
                    openai_api_key=openai_api_key_var.get().strip(),
                    openai_model=openai_model_var.get().strip(),
                    openai_protocol=openai_protocol_var.get().strip(),
                    proxy_preference=openai_proxy_preference_var.get().strip(),
                    disable_image_generation=openai_disable_image_generation_var.get(),
                )
            except Exception as exc:
                messagebox.showerror("OpenAI-Compatible API", str(exc), parent=dialog)
                return
            self.backend_settings = updated
            refresh_token_pool_section()
            self.status_var.set(f"Applied OpenAI preset: {preset_id}")

        def delete_openai_preset_dialog() -> None:
            preset_id = selected_openai_preset_id()
            if not preset_id:
                messagebox.showerror("OpenAI-Compatible API", "Select an OpenAI preset first.", parent=dialog)
                return
            if not messagebox.askyesno("OpenAI-Compatible API", f"Delete preset '{preset_id}'?", parent=dialog):
                return
            try:
                updated = self._delete_openai_compatible_preset_settings(preset_id)
            except Exception as exc:
                messagebox.showerror("OpenAI-Compatible API", str(exc), parent=dialog)
                return
            self.backend_settings = updated
            refresh_token_pool_section()
            self.status_var.set(f"Deleted OpenAI preset: {preset_id}")

        def import_token_files_dialog() -> None:
            settings = self._token_pool_settings()
            token_dir = Path(str(settings.get("token_dir", token_pool_settings.DEFAULT_TOKEN_POOL_DIR)))
            token_pool_settings.ensure_token_pool_dir(token_dir)
            selected = filedialog.askopenfilenames(
                parent=dialog,
                title="Import token JSON files",
                filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            )
            if not selected:
                return
            try:
                imported = token_pool_settings.import_token_files([Path(path) for path in selected], token_dir=token_dir)
            except Exception as exc:
                messagebox.showerror("Import Token Files", str(exc), parent=dialog)
                return
            refresh_token_pool_section()
            self.status_var.set(f"Imported {len(imported)} token file(s)")

        def open_token_folder() -> None:
            settings = self._token_pool_settings()
            token_dir = token_pool_settings.ensure_token_pool_dir(Path(str(settings.get("token_dir", token_pool_settings.DEFAULT_TOKEN_POOL_DIR))))
            try:
                os.startfile(str(token_dir))  # type: ignore[attr-defined]
            except Exception as exc:
                messagebox.showerror("Open Token Folder", str(exc), parent=dialog)

        def start_token_pool_proxy_dialog() -> None:
            try:
                self._start_token_pool_proxy()
            except Exception as exc:
                messagebox.showerror("Start Proxy", str(exc), parent=dialog)
                return
            refresh_token_pool_section()
            self.status_var.set("Built-in token pool proxy started")

        def stop_token_pool_proxy_dialog() -> None:
            self._stop_token_pool_proxy()
            refresh_token_pool_section()
            self.status_var.set("Built-in token pool proxy stopped")

        def restart_token_pool_proxy_dialog() -> None:
            try:
                self._restart_token_pool_proxy()
            except Exception as exc:
                messagebox.showerror("Restart Proxy", str(exc), parent=dialog)
                return
            refresh_token_pool_section()
            self.status_var.set("Built-in token pool proxy restarted")

        def refresh_dialog() -> None:
            refresh_token_pool_section()
            auth_info = auth_slots.current_auth_info()
            active_slot = auth_slots.detect_active_slot()
            slots = auth_slots.list_account_slots()
            active_slot_info = find_slot_info(active_slot, slots)
            identity = auth_info.get("email", "").strip() or auth_info.get("account_id", "").strip() or "Not logged in"
            mode = auth_info.get("auth_mode", "").strip() or "unknown"
            current_var.set(
                f"{identity}\nMode: {mode}\nActive slot: {format_account_slot_name(active_slot, active_slot_info)}"
            )
            quota_var.set(format_account_quota_summary(read_current_weekly_quota()))
            for child in slots_frame.winfo_children():
                child.destroy()
            if not slots:
                ttk.Label(slots_frame, text="No account slots yet. Create one, then bind the current login.").pack(anchor="w")
                refresh_token_pool_section()
                dialog.after_idle(update_scroll_region)
                return
            for index, slot_info in enumerate(slots):
                slot_id = str(slot_info.get("slot_id", ""))
                card = ttk.LabelFrame(slots_frame, text=format_account_slot_name(slot_id, slot_info), padding=10)
                card.grid(row=index, column=0, sticky="ew", pady=(0, 8))
                ttk.Label(
                    card,
                    text=format_account_slot_summary(slot_id, slot_info, active_slot),
                    justify=tk.LEFT,
                    wraplength=520,
                ).pack(anchor="w")
                button_row = ttk.Frame(card)
                button_row.pack(fill=tk.X, pady=(10, 0))
                ttk.Button(button_row, text="Bind Current Here", command=lambda value=slot_id: bind_slot(value)).pack(side=tk.LEFT)
                if slot_supports_direct_login(slot_info):
                    ttk.Button(button_row, text="Login Here", command=lambda value=slot_id: login_bind_slot(value)).pack(side=tk.LEFT, padx=(8, 0))
                ttk.Button(
                    button_row,
                    text="Switch Here",
                    command=lambda value=slot_id: switch_slot(value),
                    state=("normal" if slot_info.get("fingerprint") else "disabled"),
                ).pack(side=tk.LEFT, padx=(8, 0))
                ttk.Button(button_row, text="Rename", command=lambda value=slot_id, label=slot_info.get("label", ""): rename_slot(value, label)).pack(side=tk.LEFT, padx=(8, 0))
                ttk.Button(
                    button_row,
                    text="Note",
                    command=lambda value=slot_id, label=slot_info.get("label", ""), note=slot_info.get("note", ""): open_slot_note(value, label, note),
                ).pack(side=tk.LEFT, padx=(8, 0))
                ttk.Button(button_row, text="Delete", command=lambda value=slot_id, label=slot_info.get("label", ""): delete_slot(value, label)).pack(side=tk.LEFT, padx=(8, 0))
            slots_frame.grid_columnconfigure(0, weight=1)
            refresh_token_pool_section()
            dialog.after_idle(update_scroll_region)

        def create_slot() -> None:
            label = simpledialog.askstring("New Slot", "Slot label:", parent=dialog)
            if label is None:
                return
            try:
                created = auth_slots.create_account_slot(label)
            except Exception as exc:
                messagebox.showerror("New Slot", str(exc), parent=dialog)
                return
            refresh_dialog()
            self.status_var.set(f"Created {format_account_slot_name(created.get('slot_id'), created)}")

        def rename_slot(slot_id: str, current_label: str) -> None:
            label = simpledialog.askstring("Rename Slot", "Slot label:", initialvalue=current_label, parent=dialog)
            if label is None:
                return
            try:
                updated = auth_slots.rename_account_slot(slot_id, label)
            except Exception as exc:
                messagebox.showerror("Rename Slot", str(exc), parent=dialog)
                return
            refresh_dialog()
            self.status_var.set(f"Renamed slot to {updated.get('label', slot_id)}")

        def open_slot_note(slot_id: str, current_label: str, current_note: str) -> None:
            note_window = tk.Toplevel(dialog)
            note_window.title(f"Note - {current_label or slot_id}")
            note_window.transient(dialog)
            note_window.geometry("720x520")
            note_window.minsize(420, 260)
            note_window.columnconfigure(0, weight=1)
            note_window.rowconfigure(0, weight=1)

            editor_frame = ttk.Frame(note_window, padding=10)
            editor_frame.grid(row=0, column=0, sticky="nsew")
            editor_frame.columnconfigure(0, weight=1)
            editor_frame.rowconfigure(0, weight=1)

            text_widget = tk.Text(editor_frame, wrap=tk.WORD, undo=True)
            note_font = font.Font(font=text_widget.cget("font"))
            text_widget.configure(font=note_font)
            scrollbar = ttk.Scrollbar(editor_frame, orient=tk.VERTICAL, command=text_widget.yview)
            text_widget.configure(yscrollcommand=scrollbar.set)
            text_widget.grid(row=0, column=0, sticky="nsew")
            scrollbar.grid(row=0, column=1, sticky="ns")
            text_widget.insert("1.0", current_note or "")
            text_widget.focus_set()
            text_widget.tag_configure("note_url", foreground="#0563c1", underline=True)
            text_widget.tag_configure("note_email", foreground="#0563c1", underline=True)

            reference_by_tag: dict[str, dict[str, object]] = {}
            retag_after_id: str | None = None

            def set_clipboard(value: str) -> None:
                note_window.clipboard_clear()
                note_window.clipboard_append(value)
                self.status_var.set("Copied to clipboard")

            def open_url(value: str) -> None:
                webbrowser.open(value)
                self.status_var.set(f"Opened {value}")

            def clear_reference_tags() -> None:
                text_widget.tag_remove("note_url", "1.0", "end")
                text_widget.tag_remove("note_email", "1.0", "end")
                for tag in list(text_widget.tag_names()):
                    if tag.startswith("note_ref_"):
                        text_widget.tag_delete(tag)
                reference_by_tag.clear()

            def retag_note_references() -> None:
                clear_reference_tags()
                text = text_widget.get("1.0", "end-1c")
                for index, reference in enumerate(find_note_references(text)):
                    tag = f"note_ref_{index}"
                    kind = str(reference["kind"])
                    value = str(reference["value"])
                    start = f"1.0+{int(reference['start'])}c"
                    end = f"1.0+{int(reference['end'])}c"
                    text_widget.tag_add(tag, start, end)
                    text_widget.tag_add("note_url" if kind == "url" else "note_email", start, end)
                    reference_by_tag[tag] = reference
                    text_widget.tag_bind(tag, "<Enter>", lambda _event: text_widget.configure(cursor="hand2"))
                    text_widget.tag_bind(tag, "<Leave>", lambda _event: text_widget.configure(cursor=""))
                    if kind == "url":
                        text_widget.tag_bind(tag, "<Button-1>", lambda _event, url=value: open_url(url))

            def schedule_retag(_event: tk.Event | None = None) -> None:
                nonlocal retag_after_id
                if retag_after_id is not None:
                    note_window.after_cancel(retag_after_id)
                retag_after_id = note_window.after(250, retag_note_references)

            def reference_at_event(event: tk.Event) -> dict[str, object] | None:
                index = text_widget.index(f"@{event.x},{event.y}")
                for tag in text_widget.tag_names(index):
                    if tag.startswith("note_ref_") and tag in reference_by_tag:
                        return reference_by_tag[tag]
                return None

            def show_reference_menu(event: tk.Event) -> str | None:
                reference = reference_at_event(event)
                if reference is None:
                    return None
                kind = str(reference["kind"])
                value = str(reference["value"])
                menu = tk.Menu(note_window, tearoff=False)
                if kind == "url":
                    menu.add_command(label="Open Link", command=lambda url=value: open_url(url))
                    menu.add_command(label="Copy Link", command=lambda url=value: set_clipboard(url))
                else:
                    menu.add_command(label="Copy Email", command=lambda email=value: set_clipboard(email))
                menu.tk_popup(event.x_root, event.y_root)
                return "break"

            def zoom_note_font(event: tk.Event) -> str:
                delta = 1 if getattr(event, "delta", 0) > 0 else -1
                current_size = abs(int(note_font.cget("size") or 10))
                next_size = max(6, min(48, current_size + delta))
                note_font.configure(size=next_size)
                return "break"

            action_row = ttk.Frame(note_window, padding=(10, 0, 10, 10))
            action_row.grid(row=1, column=0, sticky="ew")

            def save_note() -> bool:
                note = text_widget.get("1.0", "end-1c")
                try:
                    auth_slots.update_account_slot_note(slot_id, note)
                except Exception as exc:
                    messagebox.showerror("Save Note", str(exc), parent=note_window)
                    return False
                refresh_dialog()
                self.status_var.set(f"Saved note for {current_label or slot_id}")
                return True

            def save_and_close() -> None:
                if save_note() and note_window.winfo_exists():
                    note_window.destroy()

            ttk.Button(action_row, text="Save", command=save_note).pack(side=tk.RIGHT)
            ttk.Button(action_row, text="Save && Close", command=save_and_close).pack(side=tk.RIGHT, padx=(0, 8))
            ttk.Button(action_row, text="Close", command=note_window.destroy).pack(side=tk.RIGHT, padx=(0, 8))
            note_window.bind("<Control-s>", lambda _event: (save_note(), "break")[1])
            text_widget.bind("<Control-MouseWheel>", zoom_note_font)
            text_widget.bind("<KeyRelease>", schedule_retag)
            text_widget.bind("<<Paste>>", lambda _event: note_window.after_idle(retag_note_references))
            text_widget.bind("<Button-3>", show_reference_menu)
            retag_note_references()

        def delete_slot(slot_id: str, current_label: str) -> None:
            ok = messagebox.askyesno(
                "Delete Slot",
                f"Delete saved auth slot '{current_label or slot_id}'?\n\nThis removes only the backup slot, not the current login in .codex.",
                parent=dialog,
            )
            if not ok:
                return
            try:
                auth_slots.delete_account_slot(slot_id)
            except Exception as exc:
                messagebox.showerror("Delete Slot", str(exc), parent=dialog)
                return
            refresh_dialog()
            self.status_var.set(f"Deleted slot {current_label or slot_id}")

        def bind_slot(slot_id: str) -> None:
            try:
                slot_info = auth_slots.save_current_auth_to_slot(slot_id)
            except FileNotFoundError as exc:
                messagebox.showerror("Bind Account", str(exc), parent=dialog)
                return
            refresh_dialog()
            self._refresh_account_status()
            self.status_var.set(f"Saved current login to {format_account_slot_name(slot_id, slot_info)}")

        def choose_login_browser_mode(slot_name: str) -> bool | None:
            choice: dict[str, bool | None] = {"private": None}
            chooser = tk.Toplevel(dialog)
            chooser.title("Login Browser")
            chooser.transient(dialog)
            chooser.resizable(False, False)
            ttk.Label(
                chooser,
                text=(
                    f"Choose browser mode for {slot_name}:\n\n"
                    "1. Normal browser: same as before.\n"
                    "2. Private/InPrivate browser: opens the login in a private window when supported."
                ),
                justify=tk.LEFT,
                padding=12,
            ).pack(anchor="w")
            row = ttk.Frame(chooser, padding=(12, 0, 12, 12))
            row.pack(fill=tk.X)

            def finish(value: bool | None) -> None:
                choice["private"] = value
                try:
                    chooser.grab_release()
                except tk.TclError:
                    pass
                chooser.destroy()

            ttk.Button(row, text="1 Normal Browser", command=lambda: finish(False)).pack(side=tk.LEFT)
            ttk.Button(row, text="2 Private Browser", command=lambda: finish(True)).pack(side=tk.LEFT, padx=(8, 0))
            ttk.Button(row, text="Cancel", command=lambda: finish(None)).pack(side=tk.RIGHT)
            chooser.protocol("WM_DELETE_WINDOW", lambda: finish(None))
            chooser.grab_set()
            chooser.wait_window()
            return choice["private"]

        def login_bind_slot(slot_id: str) -> None:
            initial_slot_info = auth_slots.get_slot_info(slot_id)
            slot_name = format_account_slot_name(slot_id, initial_slot_info)
            private_browser = choose_login_browser_mode(slot_name)
            if private_browser is None:
                return
            progress = tk.Toplevel(dialog)
            progress.title("Login Here")
            progress.transient(dialog)
            progress.resizable(False, False)
            progress_text = tk.StringVar(
                value=(
                    f"Waiting for Codex login for {slot_name}.\n\n"
                    "If you close the browser or want to stop waiting, click Cancel."
                )
            )
            ttk.Label(
                progress,
                textvariable=progress_text,
                justify=tk.LEFT,
                padding=12,
                wraplength=520,
            ).pack(anchor="w")
            action_row = ttk.Frame(progress, padding=(12, 0, 12, 12))
            action_row.pack(fill=tk.X)
            state: dict[str, object] = {"cancelled": False, "process": None}
            device_code_var = tk.StringVar(value="")
            code_row = ttk.Frame(progress, padding=(12, 0, 12, 8))
            if private_browser:
                code_row.pack(fill=tk.X)
                ttk.Label(code_row, text="Device code:").pack(side=tk.LEFT)
                ttk.Entry(code_row, textvariable=device_code_var, width=16, state="readonly").pack(side=tk.LEFT, padx=(8, 0))

            def copy_device_code() -> None:
                code = device_code_var.get().strip()
                if not code:
                    return
                progress.clipboard_clear()
                progress.clipboard_append(code)
                self.status_var.set(f"Copied login code {code}")

            copy_code_button = ttk.Button(code_row, text="Copy Code", command=copy_device_code, state="disabled")
            if private_browser:
                copy_code_button.pack(side=tk.LEFT, padx=(8, 0))

            def close_progress() -> None:
                if not progress.winfo_exists():
                    return
                try:
                    progress.grab_release()
                except tk.TclError:
                    pass
                progress.destroy()

            def cancel_login() -> None:
                state["cancelled"] = True
                process = state.get("process")
                if isinstance(process, subprocess.Popen) and process.poll() is None:
                    try:
                        process.terminate()
                    except OSError:
                        pass
                self.status_var.set(f"Cancelled login for {slot_name}")
                close_progress()

            ttk.Button(action_row, text="Cancel", command=cancel_login).pack(side=tk.RIGHT)
            progress.protocol("WM_DELETE_WINDOW", cancel_login)
            if LOGIN_PROGRESS_IS_MODAL:
                progress.grab_set()
            self.status_var.set(f"Waiting for Codex login to bind {slot_name}...")
            progress.update_idletasks()

            def on_success(bound_slot_info: dict[str, str]) -> None:
                close_progress()
                if dialog.winfo_exists():
                    refresh_dialog()
                self._refresh_account_status()
                self.status_var.set(f"Logged in and bound {format_account_slot_name(slot_id, bound_slot_info)}")

            def on_error(exc: Exception) -> None:
                if state.get("cancelled"):
                    return
                close_progress()
                if dialog.winfo_exists():
                    refresh_dialog()
                messagebox.showerror("Login Here", str(exc), parent=dialog if dialog.winfo_exists() else None)
                self.status_var.set(str(exc))

            def worker() -> None:
                try:
                    ensure_account_slot_exists(slot_id)
                    before_fingerprint = str(auth_slots.current_auth_info().get("fingerprint", "")).strip()
                    login_env = None
                    if private_browser:
                        login_env = build_private_browser_login_env()
                        apply_login_proxy_env(
                            login_env,
                            enabled=self.use_proxy_var.get(),
                            scheme=self.proxy_scheme_var.get(),
                            host=self.proxy_host_var.get(),
                            port_text=self.proxy_port_var.get(),
                        )
                    process = start_codex_browser_login_process(private_browser=private_browser, env=login_env)
                    state["process"] = process

                    def on_login_output(kind: str, value: str) -> None:
                        if state.get("cancelled"):
                            return
                        if kind == "url":
                            try:
                                self.root.after(
                                    0,
                                    lambda: progress_text.set(
                                        f"Private login window opened for {slot_name}.\n\n"
                                        "If a normal browser also appeared, ignore/close it and use the private window."
                                    ),
                                )
                            except tk.TclError:
                                pass
                        elif kind == "code":
                            try:
                                self.root.after(
                                    0,
                                    lambda code=value: progress_text.set(
                                        f"Private device login for {slot_name}.\n\n"
                                        f"Enter this code in the private browser:\n\n{code}\n\n"
                                        "You can still open Note and copy anything while this waits."
                                    ),
                                )
                                self.root.after(
                                    0,
                                    lambda code=value: (
                                        device_code_var.set(code),
                                        copy_code_button.configure(state="normal"),
                                        copy_device_code(),
                                    ),
                                )
                            except tk.TclError:
                                pass

                    try:
                        if private_browser:
                            stdout_text = collect_login_process_output(
                                process,
                                private_env=login_env,
                                on_update=on_login_output,
                            )
                        else:
                            stdout_text, _ = process.communicate()
                    finally:
                        cleanup_private_browser_login_env(getattr(process, "_codex_private_browser_env", None))
                    result = subprocess.CompletedProcess(
                        process.args,
                        process.returncode if process.returncode is not None else 1,
                        stdout=stdout_text or "",
                    )
                    if state.get("cancelled"):
                        return
                    bound_slot_info = finalize_login_and_bind_account_slot(slot_id, before_fingerprint, result)
                except Exception as exc:
                    try:
                        self.root.after(0, lambda error=exc: on_error(error))
                    except tk.TclError:
                        pass
                    return
                try:
                    self.root.after(0, lambda info=bound_slot_info: on_success(info))
                except tk.TclError:
                    pass

            threading.Thread(target=worker, daemon=True).start()

        def switch_slot(slot_id: str) -> None:
            slot_info = auth_slots.get_slot_info(slot_id)
            if not slot_info.get("fingerprint"):
                messagebox.showinfo("Switch Account", f"{format_account_slot_name(slot_id, slot_info)} is not bound yet.", parent=dialog)
                return
            ok = messagebox.askyesno(
                "Switch Account",
                f"Switch future requests to {format_account_slot_name(slot_id, slot_info)}?\n\n"
                "Existing running Codex terminals or replies keep their current auth until restarted.",
                parent=dialog,
            )
            if not ok:
                return
            auth_slots.switch_to_auth_slot(slot_id)
            refresh_dialog()
            self._refresh_account_status()
            self.status_var.set(f"Switched future requests to {format_account_slot_name(slot_id, slot_info)}")
            messagebox.showinfo(
                "Account Switched",
                f"Future requests now use {format_account_slot_name(slot_id, slot_info)}.\n\n"
                "For a clean cutover, stop any running Codex replies and reopen existing Codex terminals.",
                parent=dialog,
            )
        ttk.Button(container, text="Close", command=dialog.destroy).pack(anchor="e", pady=(12, 0))
        refresh_dialog()

    def _portal_json(self, path: str) -> dict[str, object] | None:
        if time.monotonic() < self._portal_retry_after:
            return None
        if not PORTAL_TOKEN_FILE.exists():
            return None
        token = PORTAL_TOKEN_FILE.read_text(encoding="utf-8", errors="ignore").strip()
        if not token:
            return None
        req = url_request.Request(
            f"{PORTAL_BASE_URL}{path}",
            headers={"X-Access-Token": token, "Accept": "application/json"},
            method="GET",
        )
        try:
            with url_request.urlopen(req, timeout=PORTAL_TIMEOUT_SECONDS) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except (OSError, ValueError, url_error.URLError):
            self._portal_retry_after = time.monotonic() + PORTAL_BACKOFF_SECONDS
            return None
        self._portal_retry_after = 0.0
        return payload if isinstance(payload, dict) else None

    def _portal_owner(self, session_id: str) -> dict[str, str] | None:
        encoded_session_id = url_parse.quote(session_id, safe="")
        payload = self._portal_json(f"/api/sessions/{encoded_session_id}/owner")
        if payload is None:
            return None
        owner = payload.get("owner")
        if not isinstance(owner, dict):
            return None
        return {str(key): str(value) for key, value in owner.items()}

    def open_selected_admin(self) -> None:
        item = self._selected_session()
        if not item:
            messagebox.showinfo("Info", "Please select a session first.")
            return
        owner = self._portal_owner(item.session_id)
        if owner and owner.get("owner_kind") == "mobile":
            owner_label = owner.get("owner_label") or "Mobile"
            messagebox.showinfo(
                "Session Controlled",
                f"This session is currently controlled by {owner_label}.\n\n"
                "Wait until the mobile client releases it before opening a writable terminal here.",
            )
            self.status_var.set(f"Blocked writable launch for {item.session_id}: owner={owner_label}")
            return

        cwd = item.cwd or str(Path.home())
        runtime: window_runtime.WindowRuntime | None = None
        try:
            settings = dict(self._token_pool_settings())
            self._ensure_backend_ready(settings)
            codex_args = self._build_codex_resume_args(item, settings)
            runtime = self._prepare_window_runtime(
                settings,
                session_id=item.session_id,
            )
            ps_command = self._build_terminal_ps_command(
                cwd,
                codex_args,
                settings,
                runtime,
            )
        except window_runtime.SessionAlreadyOpenError:
            messagebox.showinfo(
                "Session Already Open",
                "This session is already open in another writable terminal.\n\n"
                "Close that terminal before opening the same session again.",
            )
            self.status_var.set(f"Blocked duplicate writable launch for {item.session_id}")
            return
        except (OSError, RuntimeError, ValueError) as exc:
            if runtime is not None:
                try:
                    window_runtime.cleanup_window_runtime(
                        runtime.runtime_dir,
                        runtime.runtime_root,
                    )
                except (OSError, window_runtime.WindowRuntimeError):
                    pass
            messagebox.showerror("Invalid Configuration", str(exc))
            return

        try:
            self._launch_terminal_with_runtime(ps_command, runtime)
            if self.use_proxy_var.get():
                net_text = "net=proxy"
            else:
                net_text = "net=direct"
            self.status_var.set(f"Started codex resume cwd={cwd} ({net_text})")
        except Exception as exc:
            messagebox.showerror("Error", f"Failed to start terminal:\n{exc}")

    def open_new_chat(self) -> None:
        target_dir = filedialog.askdirectory(
            title="Select working folder for new chat",
            initialdir=str(Path.home()),
            mustexist=True,
        )
        if not target_dir:
            return
        runtime: window_runtime.WindowRuntime | None = None
        try:
            settings = dict(self._token_pool_settings())
            self._ensure_backend_ready(settings)
            codex_args = self._build_codex_new_args(settings)
            runtime = self._prepare_window_runtime(settings, session_id="")
            ps_command = self._build_terminal_ps_command(
                target_dir,
                codex_args,
                settings,
                runtime,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            if runtime is not None:
                try:
                    window_runtime.cleanup_window_runtime(
                        runtime.runtime_dir,
                        runtime.runtime_root,
                    )
                except (OSError, window_runtime.WindowRuntimeError):
                    pass
            messagebox.showerror("Invalid Configuration", str(exc))
            return
        try:
            self._launch_terminal_with_runtime(ps_command, runtime)
            mode_text = "global defaults" if self.use_global_defaults_var.get() else "custom options"
            if self.use_proxy_var.get():
                net_text = "net=proxy"
            else:
                net_text = "net=direct"
            self.status_var.set(f"Started new chat in {target_dir} ({mode_text}, {net_text})")
        except Exception as exc:
            messagebox.showerror("Error", f"Failed to start new chat:\n{exc}")

    def open_selected_file(self) -> None:
        item = self._selected_session()
        if not item:
            messagebox.showinfo("Info", "Please select a session first.")
            return
        if not item.session_file:
            messagebox.showwarning("Warning", "Session file not found.")
            return
        try:
            os.startfile(item.session_file)  # type: ignore[attr-defined]
        except Exception as exc:
            messagebox.showerror("Error", f"Failed to open file:\n{exc}")

    def open_selected_folder(self) -> None:
        item = self._selected_session()
        if not item:
            messagebox.showinfo("Info", "Please select a session first.")
            return

        if item.cwd and Path(item.cwd).exists():
            folder = item.cwd
        elif item.session_file and Path(item.session_file).exists():
            folder = str(Path(item.session_file).parent)
        else:
            folder = str(APP_DIR)

        try:
            os.startfile(folder)  # type: ignore[attr-defined]
        except Exception as exc:
            messagebox.showerror("Error", f"Failed to open folder:\n{exc}")

    def delete_selected(self) -> None:
        item = self._selected_session()
        if not item:
            messagebox.showinfo("Info", "Please select a session first.")
            return

        ok = messagebox.askyesno(
            "Confirm Delete",
            f"Delete session {item.session_id}?\n\nThis removes it from history and deletes matching session files.",
        )
        if not ok:
            return

        try:
            self._delete_session(item.session_id)
            self.refresh()
            self.status_var.set(f"Deleted {item.session_id}")
        except Exception as exc:
            messagebox.showerror("Error", f"Failed to delete session:\n{exc}")

    def _delete_session(self, session_id: str) -> None:
        if session_id in self.session_notes:
            self.session_notes.pop(session_id, None)
            self._save_session_notes()

        if HISTORY_FILE.exists():
            lines_out: list[str] = []
            with HISTORY_FILE.open("r", encoding="utf-8") as f:
                for line in f:
                    if session_id not in line:
                        lines_out.append(line)
            with HISTORY_FILE.open("w", encoding="utf-8", newline="") as f:
                f.writelines(lines_out)

        if SESSIONS_DIR.exists():
            for root, _dirs, files in os.walk(SESSIONS_DIR):
                for name in files:
                    if session_id in name and name.endswith(".jsonl"):
                        p = Path(root) / name
                        try:
                            p.unlink()
                        except OSError:
                            pass


def main() -> int:
    if "--window-runtime-cleanup" in sys.argv[1:]:
        marker_index = sys.argv.index("--window-runtime-cleanup")
        return window_runtime.main(["cleanup", *sys.argv[marker_index + 1 :]])
    if "--token-pool-proxy" in sys.argv[1:]:
        marker_index = sys.argv.index("--token-pool-proxy")
        return token_pool_proxy.main(sys.argv[marker_index + 1 :])
    if "--custom-provider-proxy" in sys.argv[1:]:
        marker_index = sys.argv.index("--custom-provider-proxy")
        return custom_provider_proxy.main(sys.argv[marker_index + 1 :])

    process_singleton.cleanup_previous_project_instances(app_dir=APP_DIR)
    root = tk.Tk()
    style = ttk.Style(root)
    if "vista" in style.theme_names():
        style.theme_use("vista")
    SessionManagerApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
