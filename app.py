import json
import os
import shutil
import subprocess
import sys
import time
import threading
import tomllib
import tkinter as tk
import auth_slots
import custom_provider_proxy
import token_pool_proxy
import token_pool_settings
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from tkinter import font
from tkinter import filedialog, messagebox, simpledialog, ttk
from urllib import error as url_error
from urllib import parse as url_parse
from urllib import request as url_request


APP_TITLE = "Codex Session Manager"
CODEX_HOME = Path(os.environ.get("USERPROFILE", "")) / ".codex"
HISTORY_FILE = CODEX_HOME / "history.jsonl"
NOTES_FILE = CODEX_HOME / "session_notes.json"
SESSIONS_DIR = CODEX_HOME / "sessions"
CONFIG_FILE = CODEX_HOME / "config.toml"
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
PORTAL_BACKOFF_SECONDS = 5.0
TERMINAL_PROXY_SCHEMES = ("http", "socks5", "socks5h")
DEFAULT_NO_PROXY = "localhost,127.0.0.1,::1,.local,.ts.net"
TOKEN_POOL_PROVIDER_NAME = "built_in_token_pool"
TOKEN_POOL_ENV_KEY_NAME = "CODEX_TOKEN_POOL_API_KEY"
OPENAI_COMPAT_PROVIDER_NAME = "openai_compatible"
OPENAI_COMPAT_ENV_KEY_NAME = "CODEX_OPENAI_COMPATIBLE_API_KEY"
DEFAULT_PRIMARY_MODEL = "gpt-5.5"
FALLBACK_MODEL_OPTIONS = (
    DEFAULT_PRIMARY_MODEL,
    "gpt-5.4",
    "gpt-5.3-codex",
    "gpt-5.2",
    "gpt-5",
)
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


def build_start_process_command(ps_command: str, run_as_admin: bool) -> str:
    args = ["-NoProfile", "-NoExit", "-Command", ps_command]
    start_process = "Start-Process powershell "
    if run_as_admin:
        start_process += "-Verb RunAs "
    arg_items = ["'" + value.replace("'", "''") + "'" for value in args]
    start_process += f"-ArgumentList @({','.join(arg_items)})"
    return start_process


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
) -> list[str]:
    clean_provider = provider_name.strip() or OPENAI_COMPAT_PROVIDER_NAME
    clean_env_key = env_key_name.strip() or OPENAI_COMPAT_ENV_KEY_NAME
    clean_model = model.strip()
    clean_base_url = base_url.strip().rstrip("/")
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
        f'model_providers.{clean_provider}.wire_api="responses"',
        "-c",
        f'model_providers.{clean_provider}.requires_openai_auth=false',
        "-c",
        f'model_providers.{clean_provider}.supports_websockets=false',
    ]


def save_openai_compatible_backend_settings(
    *,
    settings_file: Path = token_pool_settings.DEFAULT_SETTINGS_FILE,
    token_dir: Path = token_pool_settings.DEFAULT_TOKEN_POOL_DIR,
    proxy_port: int = token_pool_settings.DEFAULT_PROXY_PORT,
    proxy_api_key: str = "",
    base_url: str = token_pool_settings.DEFAULT_OPENAI_BASE_URL,
    api_key: str = "",
    model: str = "",
) -> dict[str, object]:
    resolved = token_pool_settings.resolve_openai_compatible_backend_config(
        base_url,
        api_key,
        model,
    )
    return token_pool_settings.save_backend_settings(
        backend_mode=token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE,
        settings_file=settings_file,
        token_dir=token_dir,
        proxy_port=proxy_port,
        proxy_api_key=proxy_api_key,
        openai_base_url=str(resolved.get("openai_base_url", base_url)),
        openai_api_key=str(resolved.get("openai_api_key", api_key)),
        openai_model=str(resolved.get("openai_model", model)),
        openai_models=resolved.get("openai_models", []),
        openai_protocol=str(resolved.get("openai_protocol", "")),
    )


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
            command = [executable, app_path]
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
    model_ids: list[str],
    frozen: bool,
) -> list[str]:
    if not frozen:
        conda_executable = shutil.which("conda")
        if conda_executable:
            command = [conda_executable, "run", "--no-capture-output", "-n", "codex-accel", "python", app_path]
        else:
            command = [executable, app_path]
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
            upstream_protocol.strip(),
        ]
    )
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


def start_codex_browser_login_process() -> subprocess.Popen[str]:
    try:
        return subprocess.Popen(
            ["codex.cmd", "login"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="ignore",
        )
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
    return f"Auth: {format_account_slot_name(active_slot, slot_info)} | {identity}"


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


def account_dialog_dimensions(screen_width: int, screen_height: int) -> tuple[int, int]:
    usable_width = max(360, int(screen_width) - 80)
    usable_height = max(360, int(screen_height) - 80)
    return min(720, usable_width), min(820, usable_height)


class SessionManagerApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("1280x760")
        self.root.minsize(1020, 620)

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

        self._build_ui()
        self._init_fonts()
        self._refresh_account_status()
        self._bind_shortcuts()
        self.refresh()
        self._schedule_auto_refresh()
        self._schedule_desktop_signal_watch()

    def _build_ui(self) -> None:
        top = ttk.Frame(self.root, padding=8)
        top.pack(fill=tk.X)

        ttk.Button(top, text="Refresh", command=self.refresh).pack(side=tk.LEFT)
        ttk.Button(top, text="Open Terminal", command=self.open_selected_admin).pack(side=tk.LEFT, padx=6)
        ttk.Button(top, text="New Chat", command=self.open_new_chat).pack(side=tk.LEFT)
        ttk.Button(top, text="Open Folder", command=self.open_selected_folder).pack(side=tk.LEFT)
        ttk.Button(top, text="Open File", command=self.open_selected_file).pack(side=tk.LEFT, padx=6)
        ttk.Button(top, text="Delete", command=self.delete_selected).pack(side=tk.LEFT)

        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(top, textvariable=self.status_var).pack(side=tk.RIGHT)
        ttk.Button(top, text="Accounts", command=self.open_accounts_dialog).pack(side=tk.RIGHT, padx=(8, 0))
        ttk.Label(top, textvariable=self.account_var).pack(side=tk.RIGHT)

        launch = ttk.LabelFrame(self.root, text="Launch Options (Only This Terminal)", padding=8)
        launch.pack(fill=tk.X, padx=8, pady=(0, 8))

        self.model_var = tk.StringVar(value="")
        self.approval_var = tk.StringVar(value="default")
        self.sandbox_var = tk.StringVar(value="default")
        self.search_var = tk.BooleanVar(value=False)
        self.admin_var = tk.BooleanVar(value=True)
        self.show_last_text_var = tk.BooleanVar(value=True)
        self.use_global_defaults_var = tk.BooleanVar(value=True)
        self.use_proxy_var = tk.BooleanVar(value=True)
        self.proxy_scheme_var = tk.StringVar(value="socks5h")
        self.proxy_host_var = tk.StringVar(value="127.0.0.1")
        self.proxy_port_var = tk.StringVar(value="7897")

        ttk.Label(launch, text="Model").grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.model_box = ttk.Combobox(launch, textvariable=self.model_var, state="readonly", width=24)
        self.model_box["values"] = ("default",)
        self.model_box.current(0)
        self.model_box.grid(row=0, column=1, sticky="ew", padx=(0, 10))

        ttk.Label(launch, text="Approval").grid(row=0, column=2, sticky="w", padx=(0, 6))
        self.approval_box = ttk.Combobox(launch, textvariable=self.approval_var, state="readonly", width=12)
        self.approval_box["values"] = ("default", "untrusted", "on-request", "never")
        self.approval_box.grid(row=0, column=3, sticky="w", padx=(0, 10))

        ttk.Label(launch, text="Sandbox").grid(row=0, column=4, sticky="w", padx=(0, 6))
        self.sandbox_box = ttk.Combobox(launch, textvariable=self.sandbox_var, state="readonly", width=14)
        self.sandbox_box["values"] = ("default", "read-only", "workspace-write", "danger-full-access")
        self.sandbox_box.grid(row=0, column=5, sticky="w", padx=(0, 10))

        self.search_check = ttk.Checkbutton(launch, text="Search", variable=self.search_var)
        self.search_check.grid(row=0, column=6, sticky="w", padx=(0, 10))
        ttk.Checkbutton(launch, text="Admin", variable=self.admin_var).grid(row=0, column=7, sticky="w")
        ttk.Checkbutton(
            launch,
            text="Show Last Text",
            variable=self.show_last_text_var,
            command=self._toggle_last_text_column,
        ).grid(row=0, column=8, sticky="w", padx=(10, 0))
        ttk.Checkbutton(
            launch,
            text="Use Global Defaults",
            variable=self.use_global_defaults_var,
            command=self._toggle_launch_overrides,
        ).grid(row=0, column=9, sticky="w", padx=(10, 0))

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

        launch.grid_columnconfigure(1, weight=1)
        launch.grid_columnconfigure(4, weight=1)

        table_wrap = ttk.Frame(self.root, padding=(8, 0, 8, 0))
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

        detail_frame = ttk.LabelFrame(self.root, text="Details / MCP / Skills", padding=8)
        detail_frame.pack(fill=tk.BOTH, expand=False, padx=8, pady=(8, 8))

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
        style.configure("Treeview", rowheight=30, font=default_font)
        style.configure("Treeview.Heading", font=heading_font)
        self.details_text.configure(font=text_font, relief=tk.FLAT, bd=0, padx=8, pady=8)
        self.tree.tag_configure("odd", background="#f7f9fc")
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
        note_has_focus = self.root.focus_get() == self.note_entry
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
            openai_models = settings.get("openai_models", [])
            if isinstance(openai_models, list) and openai_models:
                return merge_available_models([str(item).strip() for item in openai_models if str(item).strip()])
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
                            if slug:
                                models.append(slug)
            except Exception:
                models = []
        return merge_available_models(models)

    def _render_models(self) -> None:
        values = ["default", *self.available_models]
        self.model_box["values"] = values
        current = self.model_var.get().strip()
        if not current or current not in values:
            self.model_var.set("default")

    def _find_session_file(self, session_id: str) -> str | None:
        if not SESSIONS_DIR.exists():
            return None
        for root, _dirs, files in os.walk(SESSIONS_DIR):
            for name in files:
                if session_id in name and name.endswith(".jsonl"):
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

    def _build_codex_override_args(self) -> list[str]:
        if self.use_global_defaults_var.get():
            return []
        args: list[str] = []
        model = self.model_var.get().strip()
        if model and model != "default":
            args.extend(["-m", model])

        approval = self.approval_var.get().strip()
        if approval and approval != "default":
            args.extend(["-a", approval])

        sandbox = self.sandbox_var.get().strip()
        if sandbox and sandbox != "default":
            args.extend(["-s", sandbox])

        if self.search_var.get():
            args.append("--search")
        return args

    def _build_codex_resume_args(self, item: SessionItem) -> list[str]:
        args: list[str] = ["codex.cmd", "resume", item.session_id]
        args.extend(self._build_codex_override_args())
        backend_model = item.model.strip() or self._configured_backend_model() or DEFAULT_PRIMARY_MODEL
        args.extend(self._build_backend_override_args(backend_model))
        return args

    def _build_codex_new_args(self) -> list[str]:
        args: list[str] = ["codex.cmd"]
        args.extend(self._build_codex_override_args())
        selected_model = self.model_var.get().strip()
        backend_model = selected_model if selected_model and selected_model != "default" else self._configured_backend_model() or DEFAULT_PRIMARY_MODEL
        args.extend(
            self._build_backend_override_args(backend_model)
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
        self.search_check.configure(state="disabled" if self.use_global_defaults_var.get() else "normal")

    def _to_ps_arg_string(self, args: list[str]) -> str:
        escaped: list[str] = []
        for a in args:
            escaped.append("'" + a.replace("'", "''") + "'")
        return " ".join(escaped)

    def _build_proxy_ps_prefix(self) -> str:
        return build_proxy_environment_ps_prefix(
            enabled=self.use_proxy_var.get(),
            scheme=self.proxy_scheme_var.get(),
            host=self.proxy_host_var.get(),
            port_text=self.proxy_port_var.get(),
        )

    def _reload_backend_settings(self) -> dict[str, object]:
        self.backend_settings = token_pool_settings.load_backend_settings()
        return self.backend_settings

    def _token_pool_settings(self) -> dict[str, object]:
        return self._reload_backend_settings()

    def _configured_backend_model(self) -> str:
        settings = self._token_pool_settings()
        if settings.get("backend_mode") == token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE:
            return str(settings.get("openai_model", "")).strip()
        return ""

    def _build_token_pool_ps_prefix(self) -> str:
        settings = self._token_pool_settings()
        return build_token_pool_environment_ps_prefix(
            env_key_name=TOKEN_POOL_ENV_KEY_NAME,
            api_key_value=str(settings.get("proxy_api_key", "")),
        )

    def _build_openai_compatible_ps_prefix(self) -> str:
        settings = self._token_pool_settings()
        return build_openai_compatible_environment_ps_prefix(
            env_key_name=OPENAI_COMPAT_ENV_KEY_NAME,
            api_key_value=str(settings.get("proxy_api_key", "")),
        )

    def _token_pool_health(self, port: int | None = None) -> dict[str, object] | None:
        settings = self._token_pool_settings()
        health_port = int(port or settings.get("proxy_port", token_pool_settings.DEFAULT_PROXY_PORT))
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
        return payload if isinstance(payload, dict) else None

    def _build_token_pool_proxy_env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["PYTHONNOUSERSITE"] = "1"
        if self.use_proxy_var.get():
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

    def _start_token_pool_proxy(self) -> None:
        settings = self._token_pool_settings()
        if settings.get("backend_mode") == token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE:
            self._start_openai_compatible_proxy()
            return
        token_dir = Path(str(settings.get("token_dir", token_pool_settings.DEFAULT_TOKEN_POOL_DIR)))
        token_pool_settings.ensure_token_pool_dir(token_dir)
        token_files = token_pool_settings.list_token_files(token_dir)
        if not token_files:
            raise RuntimeError(f"No token files found in {token_dir}")
        port = int(settings.get("proxy_port", token_pool_settings.DEFAULT_PROXY_PORT))
        if self._token_pool_health(port):
            return
        command = build_token_pool_proxy_command(
            executable=sys.executable,
            app_path=str(Path(__file__).resolve()),
            port=port,
            api_key=str(settings.get("proxy_api_key", "")),
            token_dir=str(token_dir),
            frozen=getattr(sys, "frozen", False),
        )
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        proc = subprocess.Popen(
            command,
            cwd=str(APP_DIR),
            env=self._build_token_pool_proxy_env(),
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
            if self._token_pool_health(port):
                return
            time.sleep(0.2)
        raise RuntimeError("Built-in token pool proxy did not become ready.")

    def _start_openai_compatible_proxy(self) -> None:
        settings = self._token_pool_settings()
        port = int(settings.get("proxy_port", token_pool_settings.DEFAULT_PROXY_PORT))
        health = self._token_pool_health(port)
        if health:
            return
        upstream_base_url = str(settings.get("openai_base_url", token_pool_settings.DEFAULT_OPENAI_BASE_URL)).strip()
        upstream_api_key = str(settings.get("openai_api_key", "")).strip()
        upstream_protocol = str(settings.get("openai_protocol", "")).strip()
        model_ids = [str(item).strip() for item in settings.get("openai_models", []) if str(item).strip()]
        if not upstream_base_url or not upstream_api_key or not upstream_protocol:
            raise RuntimeError("Save the OpenAI-Compatible API settings before using this backend.")
        command = build_custom_provider_proxy_command(
            executable=sys.executable,
            app_path=str(Path(__file__).resolve()),
            port=port,
            api_key=str(settings.get("proxy_api_key", "")),
            upstream_base_url=upstream_base_url,
            upstream_api_key=upstream_api_key,
            upstream_protocol=upstream_protocol,
            model_ids=model_ids,
            frozen=getattr(sys, "frozen", False),
        )
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        proc = subprocess.Popen(
            command,
            cwd=str(APP_DIR),
            env=self._build_token_pool_proxy_env(),
            creationflags=creationflags,
        )
        save_token_pool_proxy_state(
            {
                "pid": proc.pid,
                "port": port,
                "backend_mode": token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE,
                "upstream_protocol": upstream_protocol,
                "started_at": time.time(),
            }
        )
        deadline = time.time() + 6.0
        while time.time() < deadline:
            if self._token_pool_health(port):
                return
            time.sleep(0.2)
        raise RuntimeError("OpenAI-compatible backend proxy did not become ready.")

    def _stop_token_pool_proxy(self) -> None:
        state = load_token_pool_proxy_state()
        pid = int(state.get("pid", 0) or 0)
        if pid > 0:
            try:
                subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, check=False)
            except OSError:
                pass
        clear_token_pool_proxy_state()

    def _restart_token_pool_proxy(self) -> None:
        self._stop_token_pool_proxy()
        time.sleep(0.2)
        self._start_token_pool_proxy()

    def _token_pool_status_summary(self) -> str:
        settings = self._token_pool_settings()
        token_dir = Path(str(settings.get("token_dir", token_pool_settings.DEFAULT_TOKEN_POOL_DIR)))
        token_count = len(token_pool_settings.list_token_files(token_dir))
        port = int(settings.get("proxy_port", token_pool_settings.DEFAULT_PROXY_PORT))
        health = self._token_pool_health(port)
        mode = str(settings.get("backend_mode", token_pool_settings.BACKEND_MODE_CODEX_AUTH))
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
        return f"Mode: {mode}\nToken files: {token_count}\nPort: {port}\nProxy: {running}"

    def _build_backend_override_args(self, fallback_model: str) -> list[str]:
        settings = self._token_pool_settings()
        mode = settings.get("backend_mode")
        if mode == token_pool_settings.BACKEND_MODE_TOKEN_POOL:
            return build_token_pool_provider_override_args(
                model=fallback_model,
                proxy_port=int(settings.get("proxy_port", token_pool_settings.DEFAULT_PROXY_PORT)),
                provider_name=TOKEN_POOL_PROVIDER_NAME,
                env_key_name=TOKEN_POOL_ENV_KEY_NAME,
            )
        if mode == token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE:
            return build_openai_compatible_provider_override_args(
                model=fallback_model,
                base_url=f"http://127.0.0.1:{int(settings.get('proxy_port', token_pool_settings.DEFAULT_PROXY_PORT))}",
                provider_name=OPENAI_COMPAT_PROVIDER_NAME,
                env_key_name=OPENAI_COMPAT_ENV_KEY_NAME,
            )
        return []

    def _ensure_backend_ready(self) -> None:
        settings = self._token_pool_settings()
        if settings.get("backend_mode") == token_pool_settings.BACKEND_MODE_TOKEN_POOL:
            self._start_token_pool_proxy()
        elif settings.get("backend_mode") == token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE:
            self._start_openai_compatible_proxy()

    def _toggle_proxy_controls(self) -> None:
        proxy_controls_enabled = self.use_proxy_var.get()
        state = "readonly" if proxy_controls_enabled else "disabled"
        entry_state = "normal" if proxy_controls_enabled else "disabled"
        self.proxy_scheme_box.configure(state=state)
        self.proxy_host_entry.configure(state=entry_state)
        self.proxy_port_entry.configure(state=entry_state)
        self.use_proxy_check.configure(state="normal")

    def _build_terminal_ps_command(self, cwd: str, codex_args: list[str]) -> str:
        cwd_escaped = cwd.replace("'", "''")
        proxy_prefix = self._build_proxy_ps_prefix()
        token_pool_prefix = ""
        openai_compatible_prefix = ""
        settings = self._token_pool_settings()
        if settings.get("backend_mode") == token_pool_settings.BACKEND_MODE_TOKEN_POOL:
            token_pool_prefix = self._build_token_pool_ps_prefix()
        elif settings.get("backend_mode") == token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE:
            openai_compatible_prefix = self._build_openai_compatible_ps_prefix()
        return (
            "chcp 65001 > $null; "
            "$utf8 = [System.Text.UTF8Encoding]::new($false); "
            "[Console]::InputEncoding = $utf8; "
            "[Console]::OutputEncoding = $utf8; "
            "$OutputEncoding = $utf8; "
            f"{proxy_prefix}"
            f"{token_pool_prefix}"
            f"{openai_compatible_prefix}"
            f"Set-Location -LiteralPath '{cwd_escaped}'; "
            f"& {self._to_ps_arg_string(codex_args)}"
        )

    def _refresh_account_status(self) -> None:
        auth_info = auth_slots.current_auth_info()
        active_slot = auth_slots.detect_active_slot()
        slots = auth_slots.list_account_slots()
        self.account_var.set(format_account_status_label(active_slot, auth_info, find_slot_info(active_slot, slots)))

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

        openai_base_url_row = ttk.Frame(token_pool_frame)
        openai_base_url_row.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(openai_base_url_row, text="Base URL", width=16).pack(side=tk.LEFT)
        ttk.Entry(openai_base_url_row, textvariable=openai_base_url_var).pack(side=tk.LEFT, fill=tk.X, expand=True)

        openai_api_key_row = ttk.Frame(token_pool_frame)
        openai_api_key_row.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(openai_api_key_row, text="API Key", width=16).pack(side=tk.LEFT)
        ttk.Entry(openai_api_key_row, textvariable=openai_api_key_var, show="*").pack(side=tk.LEFT, fill=tk.X, expand=True)

        openai_model_row = ttk.Frame(token_pool_frame)
        openai_model_row.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(openai_model_row, text="Model", width=16).pack(side=tk.LEFT)
        openai_model_box = ttk.Combobox(openai_model_row, textvariable=openai_model_var, state="readonly")
        openai_model_box.pack(side=tk.LEFT, fill=tk.X, expand=True)

        ttk.Label(token_pool_frame, text="OpenAI status", font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(10, 0))
        ttk.Label(token_pool_frame, textvariable=openai_status_var, justify=tk.LEFT, wraplength=540).pack(anchor="w", pady=(4, 8))

        openai_button_row = ttk.Frame(token_pool_frame)
        openai_button_row.pack(fill=tk.X)
        ttk.Button(openai_button_row, text="Save / Refresh Models", command=lambda: save_openai_compatible_settings_dialog()).pack(side=tk.LEFT)

        def refresh_token_pool_section() -> None:
            settings = self._token_pool_settings()
            token_dir = Path(str(settings.get("token_dir", token_pool_settings.DEFAULT_TOKEN_POOL_DIR)))
            token_pool_settings.ensure_token_pool_dir(token_dir)
            backend_mode_var.set(str(settings.get("backend_mode", token_pool_settings.BACKEND_MODE_CODEX_AUTH)))
            token_dir_var.set(str(token_dir))
            token_pool_status_var.set(self._token_pool_status_summary())
            openai_base_url_var.set(str(settings.get("openai_base_url", token_pool_settings.DEFAULT_OPENAI_BASE_URL)).strip())
            openai_api_key_var.set(str(settings.get("openai_api_key", "")).strip())
            openai_models = [str(item).strip() for item in settings.get("openai_models", []) if str(item).strip()]
            openai_model_values = openai_models or merge_available_models([])
            saved_openai_model = str(settings.get("openai_model", "")).strip()
            if saved_openai_model and saved_openai_model not in openai_model_values:
                openai_model_values = [saved_openai_model, *openai_model_values]
            openai_model_box["values"] = openai_model_values
            if saved_openai_model:
                openai_model_var.set(saved_openai_model)
            elif openai_model_values:
                openai_model_var.set(openai_model_values[0])
            else:
                openai_model_var.set("")
            openai_status_var.set(
                f"Discovered models: {len(openai_models)}\n"
                f"API key: {'configured' if str(settings.get('openai_api_key', '')).strip() else 'missing'}"
            )
            dialog.after_idle(update_scroll_region)

        def apply_backend_mode() -> None:
            settings = self._token_pool_settings()
            token_dir = Path(str(settings.get("token_dir", token_pool_settings.DEFAULT_TOKEN_POOL_DIR)))
            updated = token_pool_settings.save_backend_settings(
                backend_mode=backend_mode_var.get(),
                token_dir=token_dir,
                proxy_port=int(settings.get("proxy_port", token_pool_settings.DEFAULT_PROXY_PORT)),
                proxy_api_key=str(settings.get("proxy_api_key", "")),
                openai_base_url=openai_base_url_var.get(),
                openai_api_key=openai_api_key_var.get(),
                openai_model=openai_model_var.get(),
                openai_models=settings.get("openai_models", []),
            )
            self.backend_settings = updated
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
                )
            except Exception as exc:
                messagebox.showerror("OpenAI-Compatible API", str(exc), parent=dialog)
                return
            self.backend_settings = updated
            backend_mode_var.set(token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE)
            self.available_models = self._load_available_models()
            self._render_models()
            refresh_token_pool_section()
            saved_models = list(updated.get("openai_models", []) or [])
            self.status_var.set(f"Saved OpenAI-compatible backend settings ({len(saved_models)} model(s))")

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

        def login_bind_slot(slot_id: str) -> None:
            initial_slot_info = auth_slots.get_slot_info(slot_id)
            slot_name = format_account_slot_name(slot_id, initial_slot_info)
            progress = tk.Toplevel(dialog)
            progress.title("Login Here")
            progress.transient(dialog)
            progress.resizable(False, False)
            ttk.Label(
                progress,
                text=(
                    f"Waiting for Codex login for {slot_name}.\n\n"
                    "If you close the browser or want to stop waiting, click Cancel."
                ),
                justify=tk.LEFT,
                padding=12,
            ).pack(anchor="w")
            action_row = ttk.Frame(progress, padding=(12, 0, 12, 12))
            action_row.pack(fill=tk.X)
            state: dict[str, object] = {"cancelled": False, "process": None}

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
                    process = start_codex_browser_login_process()
                    state["process"] = process
                    stdout_text, _ = process.communicate()
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

        try:
            self._ensure_backend_ready()
            codex_args = self._build_codex_resume_args(item)
            ps_command = self._build_terminal_ps_command(cwd, codex_args)
        except (RuntimeError, ValueError) as exc:
            messagebox.showerror("Invalid Proxy", str(exc))
            return

        start_process = build_start_process_command(ps_command, self.admin_var.get())

        try:
            subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", start_process])
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
        try:
            self._ensure_backend_ready()
            codex_args = self._build_codex_new_args()
            ps_command = self._build_terminal_ps_command(target_dir, codex_args)
        except (RuntimeError, ValueError) as exc:
            messagebox.showerror("Invalid Proxy", str(exc))
            return
        start_process = build_start_process_command(ps_command, self.admin_var.get())

        try:
            subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", start_process])
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
    if "--token-pool-proxy" in sys.argv[1:]:
        marker_index = sys.argv.index("--token-pool-proxy")
        return token_pool_proxy.main(sys.argv[marker_index + 1 :])

    root = tk.Tk()
    style = ttk.Style(root)
    if "vista" in style.theme_names():
        style.theme_use("vista")
    SessionManagerApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
