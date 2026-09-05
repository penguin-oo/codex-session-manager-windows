import argparse
import auth_slots
import base64
import controlled_browser
import custom_provider_proxy
import process_singleton
import ipaddress
import json
import mimetypes
import os
import queue
import re
import signal
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, parse_qsl, quote, urlencode, urlparse, urlsplit, urlunsplit
from urllib import error as url_error
from urllib import request as url_request

import remote_ssh
import token_pool_proxy
import token_pool_settings

try:
    import tomllib
except ModuleNotFoundError:
    tomllib = None


APP_TITLE = "Codex+"
DEFAULT_PROXY_URL = "socks5h://127.0.0.1:7897"
DEFAULT_NO_PROXY = "localhost,127.0.0.1,::1"
DEFAULT_REASONING_EFFORT = "max"
REASONING_EFFORT_OPTIONS = [DEFAULT_REASONING_EFFORT, "default", "low", "medium", "high", "xhigh"]
CODEX_HOME = Path(os.environ.get("USERPROFILE", "")) / ".codex"
AUTH_FILE = CODEX_HOME / "auth.json"
HISTORY_FILE = CODEX_HOME / "history.jsonl"
NOTES_FILE = CODEX_HOME / "session_notes.json"
SETTINGS_FILE = CODEX_HOME / "session_settings.json"
PORTAL_SETTINGS_FILE = CODEX_HOME / "mobile_portal_settings.json"
BACKEND_SETTINGS_FILE = CODEX_HOME / "token_pool_settings.json"
SESSIONS_DIR = CODEX_HOME / "sessions"
CONFIG_FILE = CODEX_HOME / "config.toml"
MODELS_CACHE_FILE = CODEX_HOME / "models_cache.json"
SKILLS_DIR = CODEX_HOME / "skills"
PORTAL_TOKEN_FILE = CODEX_HOME / "mobile_portal_token.txt"
DESKTOP_REFRESH_SIGNAL_FILE = CODEX_HOME / "desktop_refresh_signal.json"
RELEASES_DIR = Path(__file__).resolve().parent / "release"
APP_DIR = Path(__file__).resolve().parent
TOKEN_POOL_PROXY_STATE_FILE = CODEX_HOME / "token_pool_proxy_state.json"
CODEX_BIN = "codex.cmd" if os.name == "nt" else "codex"
RUNNING_JOB_GRACE_SECONDS = 8
INTERRUPTED_REPLY_MESSAGE = "Reply interrupted. The response may be incomplete."
DERIVED_SESSION_FILE_MARKERS = (
    ".context-overflow-backup-",
    ".restore-current-backup-",
    ".merged-restore-candidate-",
    ".full-restored-archive-",
    ".lightweight-memory-candidate-",
    ".memory-recovery-",
    ".goal-clear-backup-",
)
OWNER_HEARTBEAT_TIMEOUT_SECONDS = 30
PROCESS_EXIT_GRACE_SECONDS = 1.0
PROCESS_STARTUP_NO_OUTPUT_TIMEOUT_SECONDS = 300.0
PROCESS_MAX_RUNTIME_SECONDS = 0.0
INCOMPLETE_REPLY_PLACEHOLDER = "This reply ended without a final answer. Please continue or retry."
DEFAULT_PRIMARY_MODEL = "gpt-6-astra"
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
TAILSCALE_WINDOWS_PATH = Path(r"C:\Program Files\Tailscale\tailscale.exe")
FILE_SHARE_TTL_SECONDS = 30 * 60
SUPPORTED_SHARED_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".pdf"}
ALLOWED_DOWNLOAD_FILES: set[str] = set()
DEFAULT_PROXY_ENABLED = True
DEFAULT_PROXY_PORT = 7897
TOKEN_POOL_PROVIDER_NAME = "built_in_token_pool"
TOKEN_POOL_ENV_KEY_NAME = "CODEX_TOKEN_POOL_API_KEY"
OPENAI_COMPAT_PROVIDER_NAME = "openai_compatible"
OPENAI_COMPAT_ENV_KEY_NAME = "CODEX_OPENAI_COMPATIBLE_API_KEY"
CODEX_OFFICIAL_PROVIDER_NAME = "openai"
CODEX_OFFICIAL_API_KEY_ENV_NAMES = ("CODEX_API_KEY", "OPENAI_API_KEY")
WHAM_USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"
OPENAI_AUTH_REFRESH_URL = "https://auth.openai.com/oauth/token"
OPENAI_CHATGPT_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
INTERNAL_ASSISTANT_PROTOCOL_RE = re.compile(
    r"(?im)^\s*(?:user|assistant)\s+to=(?:functions|multi_tool_use|all|web|shell|commentary)\b.*$"
)
CONTROLLED_BROWSER_DEBUG_URLS = {
    "edge": "http://127.0.0.1:9222",
    "chrome": "http://127.0.0.1:9223",
}

# Per-preset installation_id swap (mirrors app.py logic)
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


# Per-preset Claude Code settings.json patch (mirrors app.py logic)
_CLAUDE_SETTINGS_PATH = Path.home() / ".claude" / "settings.json"
_CLAUDE_MANAGED_ENV_PATH = Path.home() / ".codex" / "claude_managed_env_keys.json"


def _patch_claude_settings_for_preset(preset: dict[str, object]) -> None:
    """Apply preset-managed Claude env vars and remove previous managed keys."""
    target_env = token_pool_settings.normalize_string_map(preset.get("claude_env", {}))
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
    reasoning_effort: str = ""


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


def now_ts() -> int:
    return int(time.time())


def path_signature(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return (stat.st_mtime_ns, stat.st_size)


def load_session_settings_file(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    try:
        raw = path.read_text(encoding="utf-8-sig", errors="ignore")
        obj = json.loads(raw)
    except Exception:
        return {}
    if not isinstance(obj, dict):
        return {}
    out: dict[str, dict[str, str]] = {}
    for key, value in obj.items():
        sid = str(key).strip()
        if not sid or not isinstance(value, dict):
            continue
        entry: dict[str, str] = {}
        for field_name in ("model", "approval_policy", "sandbox_mode", "reasoning_effort", "cwd"):
            field_value = str(value.get(field_name, "")).strip()
            if field_value:
                entry[field_name] = field_value
        if entry:
            out[sid] = entry
    return out


def is_primary_session_jsonl_name(file_name: str) -> bool:
    name = str(file_name)
    if not name.endswith(".jsonl"):
        return False
    return not any(marker in name for marker in DERIVED_SESSION_FILE_MARKERS)


def directory_glob_signature(root: Path, pattern: str) -> tuple[tuple[str, int, int], ...] | None:
    if not root.exists():
        return None
    entries: list[tuple[str, int, int]] = []
    for candidate in root.rglob(pattern):
        try:
            stat = candidate.stat()
        except OSError:
            continue
        entries.append((candidate.relative_to(root).as_posix(), stat.st_mtime_ns, stat.st_size))
    entries.sort()
    return tuple(entries)


def apply_session_notes(items: list["SessionItem"], notes: dict[str, str]) -> list["SessionItem"]:
    return [replace(item, note=notes.get(item.session_id, item.note)) for item in items]


def apply_session_overrides(items: list["SessionItem"], overrides: dict[str, dict[str, str]]) -> list["SessionItem"]:
    updated: list[SessionItem] = []
    for item in items:
        override = overrides.get(item.session_id, {})
        updated.append(
            replace(
                item,
                model=str(override.get("model", item.model)),
                approval_policy=str(override.get("approval_policy", item.approval_policy)),
                sandbox_mode=str(override.get("sandbox_mode", item.sandbox_mode)),
                reasoning_effort=str(override.get("reasoning_effort", item.reasoning_effort)),
                cwd=str(override.get("cwd", item.cwd)),
            )
        )
    return updated


def copy_message_list(messages: list[dict[str, object]]) -> list[dict[str, object]]:
    return [dict(item) for item in messages]


def reconcile_completed_job_message(
    messages: list[dict[str, object]],
    job: dict[str, object],
) -> list[dict[str, object]]:
    reconciled = copy_message_list(messages)
    if str(job.get("status", "")) != "completed":
        return reconciled
    final_text = str(job.get("last_message", "")).strip()
    if not final_text:
        return reconciled

    finished_at = int(job.get("finished_at", 0) or 0)
    last_user_index = -1
    last_user_ts = 0
    for index, message in enumerate(reconciled):
        if str(message.get("role", "")) != "user":
            continue
        last_user_index = index
        last_user_ts = int(message.get("ts", 0) or 0)
    if finished_at and last_user_ts > finished_at:
        return reconciled

    if last_user_index < 0:
        if any(
            str(message.get("role", "")) == "assistant"
            and normalize_message_text(str(message.get("text", ""))) == normalize_message_text(final_text)
            for message in reconciled
        ):
            return reconciled
        return [
            *reconciled,
            {
                "role": "assistant",
                "ts": finished_at or int(job.get("created_at", 0) or 0),
                "text": final_text,
            },
        ]

    trailing_start = last_user_index + 1
    for message in reconciled[trailing_start:]:
        if str(message.get("role", "")) != "assistant":
            continue
        if finished_at and int(message.get("ts", 0) or 0) > finished_at:
            return reconciled
        if normalize_message_text(str(message.get("text", ""))) == normalize_message_text(final_text):
            return reconciled

    retained = [
        message
        for message in reconciled[trailing_start:]
        if str(message.get("role", "")) != "assistant"
    ]
    return [
        *reconciled[:trailing_start],
        *retained,
        {
            "role": "assistant",
            "ts": finished_at or int(job.get("created_at", 0) or 0),
            "text": final_text,
        },
    ]


def iso_to_ts(value: str) -> int:
    if not value:
        return 0
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return 0


def ensure_working_directory(current_path: str) -> Path:
    target = Path(current_path).expanduser()
    if not target.exists():
        target.mkdir(parents=True, exist_ok=True)
    if not target.is_dir():
        raise NotADirectoryError("Path is not a directory.")
    return target


def normalize_existing_file_path(raw_path: str, cwd: str = "") -> Path:
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        clean_cwd = cwd.strip()
        if not clean_cwd:
            raise FileNotFoundError("Path not found.")
        candidate = Path(clean_cwd).expanduser() / candidate
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise FileNotFoundError("Path not found.") from exc
    if not resolved.is_file():
        raise FileNotFoundError("File not found.")
    return resolved


def path_is_within_root(target: Path, root: Path) -> bool:
    try:
        target.relative_to(root)
    except ValueError:
        return False
    return True


def guess_shared_file_content_type(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(str(path))
    if guessed:
        return guessed
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return "application/pdf"
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".png":
        return "image/png"
    if suffix == ".webp":
        return "image/webp"
    if suffix == ".gif":
        return "image/gif"
    return "application/octet-stream"


def guess_release_file_content_type(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(str(path))
    if guessed:
        return guessed
    if path.suffix.lower() == ".apk":
        return "application/vnd.android.package-archive"
    if path.suffix.lower() == ".zip":
        return "application/zip"
    return "application/octet-stream"


def build_inline_content_disposition(file_name: str) -> str:
    clean_name = (file_name or "download").replace("\r", "").replace("\n", "")
    ascii_name = "".join(ch if 32 <= ord(ch) < 127 and ch not in {'"', "\\"} else "_" for ch in clean_name).strip()
    if not ascii_name:
        suffix = Path(clean_name).suffix or ""
        ascii_name = f"download{suffix}"
    encoded_name = quote(clean_name, safe="")
    return f"inline; filename=\"{ascii_name}\"; filename*=UTF-8''{encoded_name}"


def flatten_message_content(content: list[dict[str, object]]) -> str:
    parts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if isinstance(text, str) and text.strip():
            parts.append(text.strip())
    return "\n\n".join(parts).strip()


def normalize_message_text(text: str) -> str:
    return " ".join(text.split()).strip()


def is_duplicate_user_message(
    seen_user_messages: dict[str, list[int]],
    text: str,
    ts: int,
    tolerance_ms: int = 10_000,
) -> bool:
    normalized = normalize_message_text(text)
    if not normalized:
        return False
    existing = seen_user_messages.get(normalized, [])
    if not existing:
        return False
    if ts <= 0:
        return True
    for existing_ts in existing:
        if existing_ts <= 0 or abs(existing_ts - ts) <= tolerance_ms:
            return True
    return False


def is_internal_session_user_text(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    internal_prefixes = (
        "# AGENTS.md instructions for ",
        "<environment_context>",
        "<permissions instructions>",
        "<collaboration_mode>",
        "<personality_spec>",
        "<skills_instructions>",
        "<turn_aborted>",
        "<codex_internal_context",
        "**Handoff Summary**",
        "Handoff Summary",
    )
    return any(stripped.startswith(prefix) for prefix in internal_prefixes)


def resolve_portal_token(explicit_token: str, token_file: Path = PORTAL_TOKEN_FILE) -> str:
    clean_token = explicit_token.strip()
    if clean_token:
        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text(clean_token, encoding="utf-8")
        return clean_token

    if token_file.exists():
        saved_token = token_file.read_text(encoding="utf-8", errors="ignore").strip()
        if saved_token:
            return saved_token

    generated_token = secrets.token_urlsafe(18)
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(generated_token, encoding="utf-8")
    return generated_token


def tokens_match(candidate: str, expected: str) -> bool:
    if not candidate or not expected:
        return False
    try:
        return secrets.compare_digest(candidate.encode("utf-8"), expected.encode("utf-8"))
    except Exception:
        return False


def resolve_launch_model_for_backend(model: str, backend_settings: dict[str, object]) -> str:
    clean_model = str(model).strip()
    mode = backend_settings.get("backend_mode")
    if mode != token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE:
        if clean_model and clean_model != "default":
            return clean_model
        return DEFAULT_PRIMARY_MODEL

    allowed_models = unique_model_ids(backend_settings.get("openai_models", []))
    if (
        clean_model
        and clean_model != "default"
        and (not allowed_models or clean_model in allowed_models)
    ):
        return clean_model

    configured_model = str(backend_settings.get("openai_model", "")).strip()
    if configured_model and (not allowed_models or configured_model in allowed_models):
        return configured_model
    if DEFAULT_PRIMARY_MODEL:
        return DEFAULT_PRIMARY_MODEL
    if allowed_models:
        return allowed_models[0]
    return configured_model


def ensure_openai_compatible_launch_model_metadata(backend_settings: dict[str, object], model: str) -> None:
    if backend_settings.get("backend_mode") != token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE:
        return
    model_ids = unique_model_ids(backend_settings.get("openai_models", []))
    clean_model = str(model).strip()
    if clean_model:
        model_ids = unique_model_ids([clean_model, *model_ids])
    if not model_ids:
        configured_model = str(backend_settings.get("openai_model", "")).strip()
        if configured_model:
            model_ids = [configured_model]
    token_pool_settings.ensure_openai_compatible_model_metadata(
        model_ids,
        models_cache_file=token_pool_settings.DEFAULT_MODELS_CACHE_FILE,
    )


def build_resume_args(
    output_file: Path,
    session_id: str,
    prompt: str,
    model: str,
    sandbox: str,
    approval: str,
    reasoning_effort: str,
    image_paths: list[Path] | None = None,
    backend_settings_file: Path = BACKEND_SETTINGS_FILE,
) -> list[str]:
    args = [CODEX_BIN, "exec", "--json", "-o", str(output_file), "--skip-git-repo-check"]
    args.extend(token_pool_settings.build_codex_context_override_args())
    backend_settings = token_pool_settings.load_backend_settings(backend_settings_file)
    resolved_model = resolve_launch_model_for_backend(model, backend_settings)
    token_pool_settings.ensure_codex_model_context_metadata([resolved_model])
    ensure_openai_compatible_launch_model_metadata(backend_settings, resolved_model)
    if resolved_model and resolved_model != "default":
        args.extend(["-m", resolved_model])
    if sandbox and sandbox != "default":
        args.extend(["-s", sandbox])
    if approval and approval != "default":
        args.extend(["-c", f'approval_policy="{approval}"'])
    if reasoning_effort and reasoning_effort != "default":
        args.extend(["-c", f'model_reasoning_effort="{reasoning_effort}"'])
    args.extend(build_backend_override_args(backend_settings_file=backend_settings_file))
    args.append("resume")
    for image_path in image_paths or []:
        args.extend(["-i", str(image_path)])
    args.append(session_id)
    clean_prompt = prompt.strip()
    if clean_prompt:
        args.append("-")
    return args


def build_new_chat_args(
    output_file: Path,
    prompt: str,
    model: str,
    sandbox: str,
    approval: str,
    reasoning_effort: str,
    backend_settings_file: Path = BACKEND_SETTINGS_FILE,
) -> list[str]:
    args = [CODEX_BIN, "exec", "--json", "-o", str(output_file)]
    args.extend(token_pool_settings.build_codex_context_override_args())
    backend_settings = token_pool_settings.load_backend_settings(backend_settings_file)
    resolved_model = resolve_launch_model_for_backend(model, backend_settings)
    token_pool_settings.ensure_codex_model_context_metadata([resolved_model])
    ensure_openai_compatible_launch_model_metadata(backend_settings, resolved_model)
    if resolved_model and resolved_model != "default":
        args.extend(["-m", resolved_model])
    if sandbox and sandbox != "default":
        args.extend(["-s", sandbox])
    if approval and approval != "default":
        args.extend(["-c", f'approval_policy="{approval}"'])
    if reasoning_effort and reasoning_effort != "default":
        args.extend(["-c", f'model_reasoning_effort="{reasoning_effort}"'])
    args.extend(build_backend_override_args(backend_settings_file=backend_settings_file))
    args.append("--skip-git-repo-check")
    if prompt.strip():
        args.append("-")
    return args


def _detect_image_suffix(raw_bytes: bytes) -> str:
    if raw_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if raw_bytes.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if raw_bytes.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if len(raw_bytes) >= 12 and raw_bytes.startswith(b"RIFF") and raw_bytes[8:12] == b"WEBP":
        return ".webp"
    if len(raw_bytes) >= 12 and raw_bytes[4:8] == b"ftyp" and raw_bytes[8:12] in {b"heic", b"heix", b"heif", b"hevc", b"mif1", b"msf1"}:
        return ".heic"
    return ""


def _image_suffix(name: str, mime_type: str, raw_bytes: bytes | None = None) -> str:
    suffix = Path(name).suffix.lower()
    if suffix:
        return suffix
    detected = _detect_image_suffix(raw_bytes or b"")
    if detected:
        return detected
    guessed = mimetypes.guess_extension(mime_type, strict=False) or ".img"
    if guessed == ".jpe":
        return ".jpg"
    return guessed


def materialize_image_attachment(image_payload: dict[str, object] | None) -> Path | None:
    if not image_payload:
        return None
    encoded = str(image_payload.get("data_base64", "")).strip()
    if not encoded:
        return None
    try:
        raw_bytes = base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise ValueError("Invalid image attachment payload.") from exc
    if not raw_bytes:
        raise ValueError("Image attachment is empty.")

    name = str(image_payload.get("name", "image")).strip() or "image"
    mime_type = str(image_payload.get("mime_type", "")).strip()
    suffix = _image_suffix(name, mime_type, raw_bytes)
    handle, temp_name = tempfile.mkstemp(prefix="codex-mobile-image-", suffix=suffix)
    os.close(handle)
    temp_path = Path(temp_name)
    temp_path.write_bytes(raw_bytes)
    return temp_path


def extract_tailscale_ipv4_addresses(output: str) -> list[str]:
    addresses: list[str] = []
    seen: set[str] = set()
    for raw_line in output.splitlines():
        value = raw_line.strip()
        if not value:
            continue
        try:
            parsed = ipaddress.ip_address(value)
        except ValueError:
            continue
        if parsed.version != 4:
            continue
        normalized = str(parsed)
        if normalized in seen:
            continue
        seen.add(normalized)
        addresses.append(normalized)
    return addresses


def extract_tailscale_dns_name(status_json_text: str) -> str:
    try:
        payload = json.loads(status_json_text)
    except json.JSONDecodeError:
        return ""
    if not isinstance(payload, dict):
        return ""
    self_payload = payload.get("Self")
    if not isinstance(self_payload, dict):
        return ""
    dns_name = str(self_payload.get("DNSName", "")).strip().rstrip(".")
    return dns_name


def find_tailscale_cli() -> str:
    candidate = shutil.which("tailscale")
    if candidate:
        return candidate
    if TAILSCALE_WINDOWS_PATH.exists():
        return str(TAILSCALE_WINDOWS_PATH)
    return ""


def get_controlled_browser_debug_url(browser_name: str) -> str:
    key = str(browser_name).strip().lower()
    try:
        return CONTROLLED_BROWSER_DEBUG_URLS[key]
    except KeyError as exc:
        raise ValueError("Unsupported controlled browser.") from exc


def fetch_json_text(url: str, timeout_seconds: float = 2.0) -> str:
    request = url_request.Request(url, headers={"Accept": "application/json"})
    with url_request.urlopen(request, timeout=timeout_seconds) as response:
        return response.read().decode("utf-8", errors="ignore")


def list_controlled_browser_pages(browser_name: str, timeout_seconds: float = 2.0) -> list[dict[str, object]]:
    debug_url = get_controlled_browser_debug_url(browser_name)
    payload = json.loads(fetch_json_text(f"{debug_url}/json/list", timeout_seconds=timeout_seconds))
    if not isinstance(payload, list):
        return []
    pages: list[dict[str, object]] = []
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("type", "")).strip().lower() != "page":
            continue
        pages.append(dict(entry))
    return pages


def select_controlled_browser_page(
    pages: list[dict[str, object]],
    url_prefix: str = "",
    hostname: str = "",
) -> dict[str, object]:
    clean_prefix = str(url_prefix).strip()
    clean_hostname = str(hostname).strip().lower()
    candidates = [dict(page) for page in pages if isinstance(page, dict)]

    if clean_prefix:
        for page in candidates:
            page_url = str(page.get("url", "")).strip()
            if page_url.startswith(clean_prefix):
                return page

    if clean_hostname:
        for page in candidates:
            page_url = str(page.get("url", "")).strip()
            parsed = urlparse(page_url)
            if parsed.hostname and parsed.hostname.lower() == clean_hostname:
                return page

    for page in candidates:
        page_url = str(page.get("url", "")).strip()
        if page_url and page_url.lower() != "about:blank":
            return page

    raise RuntimeError("No usable controlled browser page found.")


def describe_controlled_browser_attach(
    browser_name: str,
    url_prefix: str = "",
    hostname: str = "",
    timeout_seconds: float = 2.0,
) -> dict[str, object]:
    debug_url = get_controlled_browser_debug_url(browser_name)
    try:
        pages = list_controlled_browser_pages(browser_name, timeout_seconds=timeout_seconds)
    except Exception as exc:
        return {
            "browser": str(browser_name).strip().lower(),
            "debug_url": debug_url,
            "running": False,
            "matched": False,
            "page_count": 0,
            "selected_page": None,
            "candidate_pages": [],
            "error": str(exc) or "Controlled browser is unavailable.",
        }

    result = {
        "browser": str(browser_name).strip().lower(),
        "debug_url": debug_url,
        "running": True,
        "matched": False,
        "page_count": len(pages),
        "selected_page": None,
        "candidate_pages": pages,
        "error": "",
    }
    try:
        result["selected_page"] = select_controlled_browser_page(pages, url_prefix=url_prefix, hostname=hostname)
        result["matched"] = True
    except Exception as exc:
        result["error"] = str(exc) or "No usable controlled browser page found."
    return result


BROWSER_ACTION_ROUTE_MAP = {
    "/api/browser/info": "info",
    "/api/browser/html": "html",
    "/api/browser/navigate": "navigate",
    "/api/browser/evaluate": "evaluate",
    "/api/browser/click": "click",
    "/api/browser/type": "type",
    "/api/browser/press": "press",
    "/api/browser/wait-text": "wait_text",
}


def run_text_command(args: list[str], timeout_seconds: float = 3.0) -> str:
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if result.returncode != 0:
        return ""
    return (result.stdout or "").strip()


def run_codex_browser_login(
    settings_file: Path = PORTAL_SETTINGS_FILE,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            [CODEX_BIN, "login"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="ignore",
            check=False,
            env=build_codex_subprocess_env(settings_file=settings_file),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError("Failed to start Codex login.") from exc


def summarize_login_failure(result: subprocess.CompletedProcess[str]) -> str:
    lines = [line.strip() for line in str(result.stdout or "").splitlines() if line.strip()]
    if lines:
        return lines[-1]
    return f"Codex login failed with exit code {result.returncode}."


def parse_weekly_quota_summary(status_output: str) -> dict[str, str]:
    text = (status_output or "").strip()
    if not text:
        return {"state": "unavailable", "summary": "Quota unavailable"}
    five_hour_line = ""
    weekly_line = ""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        lower_line = line.lower()
        if not five_hour_line and ("5h" in lower_line or "5 h" in lower_line or "5-hour" in lower_line or "5 hour" in lower_line):
            five_hour_line = line
        if not weekly_line and "weekly quota" in lower_line:
            weekly_line = line
    summary_lines = [line for line in (five_hour_line, weekly_line) if line]
    if summary_lines:
        return {"state": "ok", "summary": "\n".join(summary_lines)}
    first_line = text.splitlines()[0].strip()
    if first_line:
        return {"state": "ok", "summary": first_line}
    return {"state": "unavailable", "summary": "Quota unavailable"}


def _compact_duration_text(total_seconds: object) -> str:
    try:
        remaining = max(0, int(total_seconds))
    except (TypeError, ValueError):
        return ""
    if remaining < 60:
        return "<1m"
    parts: list[str] = []
    for suffix, unit_seconds in (("d", 86400), ("h", 3600), ("m", 60)):
        value, remaining = divmod(remaining, unit_seconds)
        if value <= 0:
            continue
        parts.append(f"{value}{suffix}")
        if len(parts) >= 2:
            break
    return " ".join(parts) or "<1m"


def _rate_limit_window_label(default_label: str, window: dict[str, object]) -> str:
    try:
        window_seconds = int(window.get("limit_window_seconds"))
    except (TypeError, ValueError):
        return default_label
    if 4 * 3600 <= window_seconds <= 6 * 3600:
        return "5h quota"
    if 6 * 24 * 3600 <= window_seconds <= 8 * 24 * 3600:
        return "Weekly quota"
    return default_label


def _format_rate_limit_window(label: str, window: object) -> str:
    if not isinstance(window, dict):
        return ""
    try:
        used_percent = int(window.get("used_percent"))
    except (TypeError, ValueError):
        return ""
    label = _rate_limit_window_label(label, window)
    summary = f"{label}: {used_percent}% used"
    reset_after_text = _compact_duration_text(window.get("reset_after_seconds"))
    if reset_after_text:
        summary += f" (resets in {reset_after_text})"
    return summary


def parse_wham_usage_summary(payload: object) -> dict[str, str]:
    if not isinstance(payload, dict):
        return {"state": "unavailable", "summary": "Quota unavailable"}
    rate_limit = payload.get("rate_limit")
    if not isinstance(rate_limit, dict):
        return {"state": "unavailable", "summary": "Quota unavailable"}
    summary_lines = [
        _format_rate_limit_window("5h quota", rate_limit.get("primary_window")),
        _format_rate_limit_window("Weekly quota", rate_limit.get("secondary_window")),
    ]
    summary_lines = [line for line in summary_lines if line]
    if not summary_lines:
        return {"state": "unavailable", "summary": "Quota unavailable"}
    return {"state": "ok", "summary": "\n".join(summary_lines)}


def load_auth_payload(auth_file: Path = AUTH_FILE) -> dict[str, object]:
    try:
        payload = json.loads(auth_file.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def load_auth_access_token(auth_file: Path = AUTH_FILE) -> str:
    payload = load_auth_payload(auth_file)
    tokens = payload.get("tokens")
    if not isinstance(tokens, dict):
        return ""
    return str(tokens.get("access_token", "")).strip()


def build_proxy_aware_opener(settings_file: Path = PORTAL_SETTINGS_FILE) -> object:
    proxy_settings = load_proxy_settings(settings_file)
    proxies: dict[str, str] = {}
    if bool(proxy_settings.get("proxy_enabled", DEFAULT_PROXY_ENABLED)):
        proxy_port = int(proxy_settings.get("proxy_port", DEFAULT_PROXY_PORT))
        proxy_url = f"socks5h://127.0.0.1:{proxy_port}"
        proxies = {"http": proxy_url, "https": proxy_url}
    return url_request.build_opener(url_request.ProxyHandler(proxies))


def _utc_now_iso_z() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _refresh_error_message(response_text: str) -> str:
    try:
        payload = json.loads(response_text)
    except (ValueError, json.JSONDecodeError):
        payload = {}
    if isinstance(payload, dict):
        error_code = str(payload.get("error", "")).strip().lower()
        if error_code in {
            "invalid_grant",
            "refresh_token_expired",
            "refresh_token_invalidated",
            "refresh_token_inused",
            "unauthorized_client",
        }:
            return "Current login needs re-login."
        description = str(payload.get("error_description", "")).strip()
        if description:
            return description
    lowered = response_text.lower()
    if "refresh_token" in lowered or "invalid_grant" in lowered:
        return "Current login needs re-login."
    return "Failed to refresh current login."


def refresh_current_chatgpt_auth(
    timeout_seconds: float = 8.0,
    auth_file: Path = AUTH_FILE,
    settings_file: Path = PORTAL_SETTINGS_FILE,
    refresh_url: str = "",
) -> dict[str, str]:
    payload = load_auth_payload(auth_file)
    if not payload:
        raise RuntimeError("Current login credentials are missing. Re-login required.")
    auth_mode = str(payload.get("auth_mode", "")).strip().lower()
    if auth_mode and auth_mode != "chatgpt":
        raise RuntimeError("Current login is not using ChatGPT auth.")
    tokens = payload.get("tokens")
    if not isinstance(tokens, dict):
        raise RuntimeError("Current login token data is missing. Re-login required.")
    refresh_token = str(tokens.get("refresh_token", "")).strip()
    if not refresh_token:
        raise RuntimeError("Current login needs re-login.")

    body = json.dumps(
        {
            "grant_type": "refresh_token",
            "client_id": OPENAI_CHATGPT_CLIENT_ID,
            "refresh_token": refresh_token,
        }
    ).encode("utf-8")
    target_url = str(refresh_url or os.environ.get("CODEX_REFRESH_TOKEN_URL_OVERRIDE", OPENAI_AUTH_REFRESH_URL)).strip()
    opener = build_proxy_aware_opener(settings_file)
    request = url_request.Request(
        target_url,
        data=body,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "codex-session-manager-mobile-portal",
        },
        method="POST",
    )
    try:
        with opener.open(request, timeout=timeout_seconds) as response:
            response_text = response.read().decode("utf-8", errors="ignore")
    except url_error.HTTPError as exc:
        response_text = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(_refresh_error_message(response_text)) from exc
    except (OSError, ValueError, url_error.URLError) as exc:
        raise RuntimeError("Failed to refresh current login.") from exc
    try:
        refreshed = json.loads(response_text)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Invalid refresh response from auth server.") from exc
    if not isinstance(refreshed, dict):
        raise RuntimeError("Invalid refresh response from auth server.")
    new_access_token = str(refreshed.get("access_token", "")).strip()
    new_refresh_token = str(refreshed.get("refresh_token", refresh_token)).strip()
    new_id_token = str(refreshed.get("id_token", tokens.get("id_token", ""))).strip()
    if not new_access_token or not new_refresh_token or not new_id_token:
        raise RuntimeError("Invalid refresh response from auth server.")

    updated_tokens = dict(tokens)
    updated_tokens["access_token"] = new_access_token
    updated_tokens["refresh_token"] = new_refresh_token
    updated_tokens["id_token"] = new_id_token
    payload["tokens"] = updated_tokens
    payload["last_refresh"] = _utc_now_iso_z()
    auth_file.parent.mkdir(parents=True, exist_ok=True)
    auth_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"status": "ok"}


def read_current_usage_quota(
    timeout_seconds: float = 4.0,
    auth_file: Path = AUTH_FILE,
    settings_file: Path = PORTAL_SETTINGS_FILE,
) -> dict[str, str]:
    access_token = load_auth_access_token(auth_file)
    if not access_token:
        return {"state": "unavailable", "summary": "Quota unavailable"}
    opener = build_proxy_aware_opener(settings_file)
    request = url_request.Request(
        WHAM_USAGE_URL,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "User-Agent": "codex-session-manager-mobile-portal",
        },
    )
    try:
        with opener.open(request, timeout=timeout_seconds) as response:
            response_text = response.read().decode("utf-8", errors="ignore")
    except (OSError, ValueError, url_error.URLError):
        return {"state": "unavailable", "summary": "Quota unavailable"}
    try:
        payload = json.loads(response_text)
    except json.JSONDecodeError:
        return {"state": "unavailable", "summary": "Quota unavailable"}
    return parse_wham_usage_summary(payload)


def read_token_pool_token_quota(
    token_file: Path,
    timeout_seconds: float = 4.0,
    settings_file: Path = PORTAL_SETTINGS_FILE,
) -> dict[str, str]:
    try:
        payload = json.loads(token_file.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {"state": "unavailable", "summary": "Quota unavailable", "token_file": token_file.name}
    if not isinstance(payload, dict):
        return {"state": "unavailable", "summary": "Quota unavailable", "token_file": token_file.name}
    access_token = str(payload.get("access_token") or payload.get("token") or "").strip()
    if not access_token:
        return {"state": "unavailable", "summary": "Quota unavailable", "token_file": token_file.name}
    opener = build_proxy_aware_opener(settings_file)
    request = url_request.Request(
        WHAM_USAGE_URL,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "User-Agent": "codex-session-manager-mobile-portal",
        },
    )
    try:
        with opener.open(request, timeout=timeout_seconds) as response:
            response_text = response.read().decode("utf-8", errors="ignore")
    except (OSError, ValueError, url_error.URLError):
        return {"state": "unavailable", "summary": "Quota unavailable", "token_file": token_file.name}
    try:
        usage_payload = json.loads(response_text)
    except json.JSONDecodeError:
        return {"state": "unavailable", "summary": "Quota unavailable", "token_file": token_file.name}
    summary = parse_wham_usage_summary(usage_payload)
    summary["token_file"] = token_file.name
    if isinstance(usage_payload, dict):
        email = str(usage_payload.get("email", "")).strip() or str(payload.get("email", "")).strip()
        plan_type = str(usage_payload.get("plan_type", "")).strip()
        if email:
            summary["email"] = email
        if plan_type:
            summary["plan_type"] = plan_type
    return summary


def read_current_weekly_quota(
    timeout_seconds: float = 4.0,
    auth_file: Path = AUTH_FILE,
    settings_file: Path = PORTAL_SETTINGS_FILE,
) -> dict[str, str]:
    usage_quota = read_current_usage_quota(
        timeout_seconds=timeout_seconds,
        auth_file=auth_file,
        settings_file=settings_file,
    )
    if usage_quota.get("state") == "ok":
        return usage_quota
    output = run_text_command([CODEX_BIN, "status"], timeout_seconds=timeout_seconds)
    return parse_weekly_quota_summary(output)


def build_history_entry_text(prompt: str, image_paths: list[Path] | None = None) -> str:
    clean_prompt = prompt.strip()
    labels = [f"[Image] {path.name}" for path in image_paths or [] if path.name]
    if clean_prompt and labels:
        return clean_prompt + "\n\n" + "\n".join(labels)
    if clean_prompt:
        return clean_prompt
    return "\n".join(labels).strip()


def normalize_public_urls(raw_urls: object) -> list[str]:
    if isinstance(raw_urls, str):
        candidates = [raw_urls]
    elif isinstance(raw_urls, (list, tuple, set)):
        candidates = list(raw_urls)
    else:
        candidates = []
    normalized: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        text = str(candidate or "").strip()
        if not text:
            continue
        parsed = urlsplit(text)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        filtered_query = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True) if key.lower() != "token"]
        normalized_url = urlunsplit(
            (
                parsed.scheme,
                parsed.netloc,
                parsed.path or "/",
                urlencode(filtered_query, doseq=True),
                "",
            )
        )
        if normalized_url in seen:
            continue
        seen.add(normalized_url)
        normalized.append(normalized_url)
    return normalized


def build_public_access_url(base_url: str, token: str) -> str:
    parsed = urlsplit(base_url)
    filtered_query = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True) if key.lower() != "token"]
    filtered_query.append(("token", token))
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path or "/",
            urlencode(filtered_query, doseq=True),
            "",
        )
    )


def load_proxy_settings(settings_file: Path = PORTAL_SETTINGS_FILE) -> dict[str, object]:
    if settings_file.exists():
        try:
            raw = json.loads(settings_file.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError, json.JSONDecodeError):
            raw = {}
        if isinstance(raw, dict):
            enabled = bool(raw.get("proxy_enabled", DEFAULT_PROXY_ENABLED))
            try:
                port = int(raw.get("proxy_port", DEFAULT_PROXY_PORT))
            except (TypeError, ValueError):
                port = DEFAULT_PROXY_PORT
            if 1 <= port <= 65535:
                return {
                    "proxy_enabled": enabled,
                    "proxy_port": port,
                    "public_urls": normalize_public_urls(raw.get("public_urls", [])),
                    "remote_restart": raw.get("remote_restart", {}) if isinstance(raw.get("remote_restart", {}), dict) else {},
                    "default_portal_urls": normalize_public_urls(raw.get("default_portal_urls", [])),
                }
    return {
        "proxy_enabled": DEFAULT_PROXY_ENABLED,
        "proxy_port": DEFAULT_PROXY_PORT,
        "public_urls": [],
        "remote_restart": {},
        "default_portal_urls": [],
    }


def save_proxy_settings(
    proxy_enabled: bool,
    proxy_port: int,
    settings_file: Path = PORTAL_SETTINGS_FILE,
    public_urls: list[str] | None = None,
) -> dict[str, object]:
    port = int(proxy_port)
    if port < 1 or port > 65535:
        raise ValueError("Proxy port must be between 1 and 65535.")
    existing = load_proxy_settings(settings_file)
    payload: dict[str, object] = {}
    if settings_file.exists():
        try:
            raw_payload = json.loads(settings_file.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError, json.JSONDecodeError):
            raw_payload = {}
        if isinstance(raw_payload, dict):
            payload.update(raw_payload)
    payload.update(
        {
            "proxy_enabled": bool(proxy_enabled),
            "proxy_port": port,
            "public_urls": normalize_public_urls(existing.get("public_urls", []) if public_urls is None else public_urls),
            "remote_restart": existing.get("remote_restart", {}) if isinstance(existing.get("remote_restart", {}), dict) else {},
            "default_portal_urls": normalize_public_urls(existing.get("default_portal_urls", [])),
        }
    )
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    settings_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def apply_proxy_settings_to_env(base_env: dict[str, str] | None, proxy_settings: dict[str, object]) -> dict[str, str]:
    env = dict(base_env or os.environ)
    no_proxy_value = env.get("NO_PROXY") or env.get("no_proxy") or DEFAULT_NO_PROXY
    env["NO_PROXY"] = no_proxy_value
    env["no_proxy"] = no_proxy_value
    if not bool(proxy_settings.get("proxy_enabled", DEFAULT_PROXY_ENABLED)):
        for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
            env.pop(key, None)
        return env
    try:
        port = int(proxy_settings.get("proxy_port", DEFAULT_PROXY_PORT))
    except (TypeError, ValueError):
        port = DEFAULT_PROXY_PORT
    proxy_value = f"socks5h://127.0.0.1:{port}"
    env["HTTP_PROXY"] = proxy_value
    env["HTTPS_PROXY"] = proxy_value
    env["ALL_PROXY"] = proxy_value
    env["http_proxy"] = proxy_value
    env["https_proxy"] = proxy_value
    env["all_proxy"] = proxy_value
    return env


def build_token_pool_provider_override_args(
    proxy_port: int,
    provider_name: str = TOKEN_POOL_PROVIDER_NAME,
    env_key_name: str = TOKEN_POOL_ENV_KEY_NAME,
) -> list[str]:
    clean_provider = provider_name.strip() or TOKEN_POOL_PROVIDER_NAME
    clean_env_key = env_key_name.strip() or TOKEN_POOL_ENV_KEY_NAME
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
    base_url: str,
    provider_name: str = OPENAI_COMPAT_PROVIDER_NAME,
    env_key_name: str = OPENAI_COMPAT_ENV_KEY_NAME,
) -> list[str]:
    clean_provider = provider_name.strip() or OPENAI_COMPAT_PROVIDER_NAME
    clean_env_key = env_key_name.strip() or OPENAI_COMPAT_ENV_KEY_NAME
    clean_base_url = base_url.strip().rstrip("/")
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


def build_codex_auth_provider_override_args(provider_name: str = CODEX_OFFICIAL_PROVIDER_NAME) -> list[str]:
    clean_provider = provider_name.strip() or CODEX_OFFICIAL_PROVIDER_NAME
    return ["-c", f'model_provider="{clean_provider}"']


def build_backend_override_args(
    backend_settings_file: Path = BACKEND_SETTINGS_FILE,
) -> list[str]:
    settings = token_pool_settings.load_backend_settings(backend_settings_file)
    mode = settings.get("backend_mode")
    if mode == token_pool_settings.BACKEND_MODE_TOKEN_POOL:
        return build_token_pool_provider_override_args(
            proxy_port=int(settings.get("proxy_port", token_pool_settings.DEFAULT_PROXY_PORT)),
            provider_name=TOKEN_POOL_PROVIDER_NAME,
            env_key_name=TOKEN_POOL_ENV_KEY_NAME,
        )
    if mode == token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE:
        if openai_compatible_requires_local_proxy(settings):
            return build_openai_compatible_provider_override_args(
                base_url=f"http://127.0.0.1:{int(settings.get('proxy_port', token_pool_settings.DEFAULT_PROXY_PORT))}",
                provider_name=OPENAI_COMPAT_PROVIDER_NAME,
                env_key_name=OPENAI_COMPAT_ENV_KEY_NAME,
            )
        upstream_url = str(settings.get("openai_base_url", token_pool_settings.DEFAULT_OPENAI_BASE_URL)).strip().rstrip("/")
        return build_openai_compatible_provider_override_args(
            base_url=upstream_url or token_pool_settings.DEFAULT_OPENAI_BASE_URL,
            provider_name=OPENAI_COMPAT_PROVIDER_NAME,
            env_key_name=OPENAI_COMPAT_ENV_KEY_NAME,
        )
    return build_codex_auth_provider_override_args()


def build_codex_subprocess_env(
    base_env: dict[str, str] | None = None,
    settings_file: Path = PORTAL_SETTINGS_FILE,
    backend_settings_file: Path = BACKEND_SETTINGS_FILE,
) -> dict[str, str]:
    backend_settings = token_pool_settings.load_backend_settings(backend_settings_file)
    proxy_settings = load_proxy_settings(settings_file)
    if backend_settings.get("backend_mode") == token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE:
        proxy_preference = token_pool_settings.effective_openai_proxy_preference(backend_settings)
        if proxy_preference == "proxy":
            env = apply_proxy_settings_to_env(base_env, proxy_settings)
        else:
            env = dict(base_env or os.environ)
            for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
                env.pop(key, None)
            env["NO_PROXY"] = DEFAULT_NO_PROXY
            env["no_proxy"] = DEFAULT_NO_PROXY
    else:
        env = apply_proxy_settings_to_env(base_env, proxy_settings)
    for key in CODEX_OFFICIAL_API_KEY_ENV_NAMES:
        env.pop(key, None)
    if backend_settings.get("backend_mode") == token_pool_settings.BACKEND_MODE_TOKEN_POOL:
        env[TOKEN_POOL_ENV_KEY_NAME] = str(backend_settings.get("proxy_api_key", "")).strip()
        env.pop(OPENAI_COMPAT_ENV_KEY_NAME, None)
    elif backend_settings.get("backend_mode") == token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE:
        if openai_compatible_requires_local_proxy(backend_settings):
            api_key = str(backend_settings.get("proxy_api_key", "")).strip()
        else:
            api_key = str(backend_settings.get("openai_api_key", "")).strip()
        env[OPENAI_COMPAT_ENV_KEY_NAME] = api_key
        env.pop(TOKEN_POOL_ENV_KEY_NAME, None)
    else:
        env.pop(TOKEN_POOL_ENV_KEY_NAME, None)
        env.pop(OPENAI_COMPAT_ENV_KEY_NAME, None)
    return env


def current_proxy_summary_from_settings(proxy_settings: dict[str, object]) -> str:
    if not bool(proxy_settings.get("proxy_enabled", DEFAULT_PROXY_ENABLED)):
        return "direct"
    try:
        port = int(proxy_settings.get("proxy_port", DEFAULT_PROXY_PORT))
    except (TypeError, ValueError):
        port = DEFAULT_PROXY_PORT
    return f"socks5h://127.0.0.1:{port}"


def current_proxy_summary(settings_file: Path = PORTAL_SETTINGS_FILE) -> str:
    return current_proxy_summary_from_settings(load_proxy_settings(settings_file))


def sanitize_assistant_message_text(text: str) -> str:
    clean = text.strip()
    if not clean:
        return ""
    matches = list(INTERNAL_ASSISTANT_PROTOCOL_RE.finditer(clean))
    if not matches:
        return clean
    first_match = matches[0]
    if first_match.start() == 0:
        return ""
    return clean[: first_match.start()].rstrip()


def conda_env_available(conda_executable: str, env_name: str = "codex-accel") -> bool:
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        result = subprocess.run(
            [conda_executable, "env", "list", "--json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=4.0,
            creationflags=creationflags,
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        return False
    if result.returncode != 0:
        return False
    try:
        payload = json.loads(result.stdout or "{}")
    except (ValueError, TypeError, json.JSONDecodeError):
        return False
    envs = payload.get("envs", []) if isinstance(payload, dict) else []
    if not isinstance(envs, list):
        return False
    target = env_name.strip().lower()
    return any(Path(str(item)).name.strip().lower() == target for item in envs)


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


def build_token_pool_proxy_command(
    *,
    executable: str,
    app_path: str,
    port: int,
    api_key: str,
    token_dir: str,
) -> list[str]:
    conda_executable = shutil.which("conda")
    if conda_executable and conda_env_available(conda_executable):
        command = [conda_executable, "run", "--no-capture-output", "-n", "codex-accel", "python", app_path]
    else:
        command = build_source_python_command(executable, app_path)
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
) -> list[str]:
    conda_executable = shutil.which("conda")
    if conda_executable and conda_env_available(conda_executable):
        command = [conda_executable, "run", "--no-capture-output", "-n", "codex-accel", "python", app_path]
    else:
        command = build_source_python_command(executable, app_path)
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
        upstream_proxy_url=str(settings.get("upstream_proxy_url", "")),
    )


def openai_compatible_requires_local_proxy(settings: dict[str, object]) -> bool:
    return str(settings.get("openai_protocol", "")).strip() == token_pool_settings.OPENAI_PROTOCOL_CHAT_COMPLETIONS


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


def token_pool_proxy_is_healthy(
    port: int,
    timeout_seconds: float = 0.5,
    expected_backend_mode: str = "",
) -> dict[str, object] | None:
    req = url_request.Request(
        f"http://127.0.0.1:{int(port)}/health",
        headers={"Accept": "application/json"},
        method="GET",
    )
    try:
        with url_request.urlopen(req, timeout=timeout_seconds) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (OSError, ValueError, url_error.URLError):
        return None
    if not isinstance(payload, dict):
        return None
    if expected_backend_mode and not backend_health_matches(payload, expected_backend_mode):
        return None
    return payload


def resolve_current_token_pool_file(
    token_dir: Path,
    health: dict[str, object] | None,
) -> Path | None:
    token_files = token_pool_settings.list_token_files(token_dir)
    current_file_name = ""
    if isinstance(health, dict):
        current_file_name = str(health.get("current_token_file", "")).strip()
    if current_file_name:
        candidate = token_dir / current_file_name
        if candidate.is_file():
            return candidate
    if len(token_files) == 1:
        return token_files[0]
    return None


def start_token_pool_backend(
    backend_settings_file: Path = BACKEND_SETTINGS_FILE,
    proxy_settings_file: Path = PORTAL_SETTINGS_FILE,
) -> dict[str, object]:
    settings = token_pool_settings.load_backend_settings(backend_settings_file)
    token_dir = Path(str(settings.get("token_dir", token_pool_settings.DEFAULT_TOKEN_POOL_DIR)))
    token_pool_settings.ensure_token_pool_dir(token_dir)
    token_files = token_pool_settings.list_token_files(token_dir)
    if not token_files:
        raise RuntimeError(f"No token files found in {token_dir}")
    port = int(settings.get("proxy_port", token_pool_settings.DEFAULT_PROXY_PORT))
    health = token_pool_proxy_is_healthy(port, expected_backend_mode=token_pool_settings.BACKEND_MODE_TOKEN_POOL)
    if health:
        return health
    if token_pool_proxy_is_healthy(port):
        stop_token_pool_backend()
        time.sleep(0.2)
        if token_pool_proxy_is_healthy(port):
            raise RuntimeError(f"Port {port} is already used by a different backend proxy.")
    command = build_token_pool_proxy_command(
        executable=sys.executable,
        app_path=str(Path(__file__).resolve()),
        port=port,
        api_key=str(settings.get("proxy_api_key", "")),
        token_dir=str(token_dir),
    )
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.Popen(
        command,
        cwd=str(APP_DIR),
        env=build_codex_subprocess_env(settings_file=proxy_settings_file, backend_settings_file=backend_settings_file),
        creationflags=creationflags,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
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
        health = token_pool_proxy_is_healthy(port, expected_backend_mode=token_pool_settings.BACKEND_MODE_TOKEN_POOL)
        if health:
            return health
        return_code = proc.poll()
        if return_code is not None:
            output = ""
            if proc.stdout is not None:
                try:
                    output = (proc.stdout.read() or "").strip()
                except OSError:
                    output = ""
            message = f"Built-in token pool proxy exited early with code {return_code}."
            if output:
                message = f"{message} {output}"
            raise RuntimeError(message)
        time.sleep(0.2)
    raise RuntimeError("Built-in token pool proxy did not become ready.")


def stop_token_pool_backend(state_file: Path = TOKEN_POOL_PROXY_STATE_FILE) -> None:
    state = load_token_pool_proxy_state(state_file)
    pid = int(state.get("pid", 0) or 0)
    if pid > 0:
        run_taskkill_tree_silently(pid)
    clear_token_pool_proxy_state(state_file)


def restart_token_pool_backend(
    backend_settings_file: Path = BACKEND_SETTINGS_FILE,
    proxy_settings_file: Path = PORTAL_SETTINGS_FILE,
) -> dict[str, object]:
    stop_token_pool_backend()
    time.sleep(0.2)
    return start_token_pool_backend(
        backend_settings_file=backend_settings_file,
        proxy_settings_file=proxy_settings_file,
    )


def ensure_token_pool_backend_ready(
    backend_settings_file: Path = BACKEND_SETTINGS_FILE,
    proxy_settings_file: Path = PORTAL_SETTINGS_FILE,
) -> None:
    settings = token_pool_settings.load_backend_settings(backend_settings_file)
    if settings.get("backend_mode") != token_pool_settings.BACKEND_MODE_TOKEN_POOL:
        return
    start_token_pool_backend(
        backend_settings_file=backend_settings_file,
        proxy_settings_file=proxy_settings_file,
    )


def start_openai_compatible_backend(
    backend_settings_file: Path = BACKEND_SETTINGS_FILE,
    proxy_settings_file: Path = PORTAL_SETTINGS_FILE,
) -> dict[str, object]:
    settings = token_pool_settings.load_backend_settings(backend_settings_file)
    port = int(settings.get("proxy_port", token_pool_settings.DEFAULT_PROXY_PORT))
    upstream_base_url = str(settings.get("openai_base_url", token_pool_settings.DEFAULT_OPENAI_BASE_URL)).strip()
    upstream_api_key = str(settings.get("openai_api_key", "")).strip()
    upstream_protocol = str(settings.get("openai_protocol", "")).strip()
    upstream_proxy_url = str(settings.get("upstream_proxy_url", "")).strip()
    model_ids = [str(item).strip() for item in settings.get("openai_models", []) if str(item).strip()]
    if not upstream_base_url or not upstream_api_key or not upstream_protocol:
        raise RuntimeError("Save the OpenAI-Compatible API settings before using this backend.")
    health = token_pool_proxy_is_healthy(port, expected_backend_mode=token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE)
    if health and openai_compatible_proxy_health_matches_settings(health, settings):
        return health
    if health:
        stop_token_pool_backend()
        time.sleep(0.2)
        if token_pool_proxy_is_healthy(port):
            raise RuntimeError(f"Port {port} is already used by a stale OpenAI-compatible backend proxy.")
    elif token_pool_proxy_is_healthy(port):
        stop_token_pool_backend()
        time.sleep(0.2)
        if token_pool_proxy_is_healthy(port):
            raise RuntimeError(f"Port {port} is already used by a different backend proxy.")
    command = build_custom_provider_proxy_command(
        executable=sys.executable,
        app_path=str(Path(__file__).resolve()),
        port=port,
        api_key=str(settings.get("proxy_api_key", "")),
        upstream_base_url=upstream_base_url,
        upstream_api_key=upstream_api_key,
        upstream_protocol=upstream_protocol,
        upstream_proxy_url=upstream_proxy_url,
        model_ids=model_ids,
    )
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.Popen(
        command,
        cwd=str(APP_DIR),
        env=build_codex_subprocess_env(settings_file=proxy_settings_file, backend_settings_file=backend_settings_file),
        creationflags=creationflags,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
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
        health = token_pool_proxy_is_healthy(port, expected_backend_mode=token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE)
        if health:
            return health
        return_code = proc.poll()
        if return_code is not None:
            output = ""
            if proc.stdout is not None:
                try:
                    output = (proc.stdout.read() or "").strip()
                except OSError:
                    output = ""
            message = f"OpenAI-compatible backend proxy exited early with code {return_code}."
            if output:
                message = f"{message} {output}"
            raise RuntimeError(message)
        time.sleep(0.2)
    raise RuntimeError("OpenAI-compatible backend proxy did not become ready.")


def ensure_backend_proxy_ready(
    backend_settings_file: Path = BACKEND_SETTINGS_FILE,
    proxy_settings_file: Path = PORTAL_SETTINGS_FILE,
) -> None:
    settings = token_pool_settings.load_backend_settings(backend_settings_file)
    mode = settings.get("backend_mode")
    if mode == token_pool_settings.BACKEND_MODE_TOKEN_POOL:
        start_token_pool_backend(
            backend_settings_file=backend_settings_file,
            proxy_settings_file=proxy_settings_file,
        )
        return
    if mode == token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE:
        _patch_image_generation_for_backend_mode(token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE)
        token_pool_settings.ensure_openai_compatible_model_metadata(
            unique_model_ids(settings.get("openai_models", [])) or [str(settings.get("openai_model", "")).strip()]
        )
        if openai_compatible_requires_local_proxy(settings):
            start_openai_compatible_backend(
                backend_settings_file=backend_settings_file,
                proxy_settings_file=proxy_settings_file,
            )
        else:
            stop_token_pool_backend()


def list_windows_process_rows() -> list[dict[str, object]]:
    if os.name != "nt":
        return []
    script = (
        "$items = Get-CimInstance Win32_Process | "
        "Select-Object ProcessId,Name,CommandLine; "
        "$items | ConvertTo-Json -Compress"
    )
    output = run_text_command(["powershell.exe", "-NoProfile", "-Command", script], timeout_seconds=5.0)
    if not output:
        return []
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        return []
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        return [payload]
    return []


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


def default_model_options(models: list[str]) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for model in (DEFAULT_PRIMARY_MODEL, "default", *models, *FALLBACK_MODEL_OPTIONS[1:]):
        clean_model = str(model).strip()
        if not clean_model or clean_model in seen:
            continue
        seen.add(clean_model)
        values.append(clean_model)
    return values


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


def _find_openai_preset(settings: dict[str, object], preset_id: str) -> dict[str, object]:
    clean_id = preset_id.strip()
    if not clean_id:
        return {}
    for item in settings.get("openai_presets", []) or []:
        if isinstance(item, dict) and str(item.get("id", "")).strip() == clean_id:
            return item
    return {}


def _merge_openai_models(models: object, extras: object, selected_model: str) -> list[str]:
    merged = unique_model_ids(models)
    clean_selected = selected_model.strip()
    if clean_selected and clean_selected not in merged:
        merged.insert(0, clean_selected)
    for item in extras or []:
        extra = str(item).strip()
        if extra and extra not in merged:
            merged.append(extra)
    return merged


def _resolved_manual_openai_protocol(protocol_override: str, fallback: str) -> str:
    clean_override = protocol_override.strip()
    if clean_override and clean_override in token_pool_settings.VALID_OPENAI_PROTOCOLS:
        return clean_override
    clean_fallback = fallback.strip()
    if clean_fallback in token_pool_settings.VALID_OPENAI_PROTOCOLS:
        return clean_fallback
    return ""


def _models_only_validation_value(
    preset: dict[str, object] | None,
    fallback: bool = False,
) -> bool:
    values = preset if isinstance(preset, dict) else {}
    return bool(
        values.get(
            "models_only_validation",
            values.get("skip_validation", fallback),
        )
    )


def _resolve_openai_compatible_input(
    *,
    existing: dict[str, object],
    existing_preset: dict[str, object],
    base_url: str,
    api_key: str,
    model: str,
    extras: list[str],
    protocol_override: str,
    models_only_validation: bool,
    upstream_proxy_url: str,
) -> dict[str, object]:
    """Validate mobile API form values before any settings file is written."""
    effective_base_url = (
        base_url.strip()
        or str(existing_preset.get("openai_base_url", "")).strip()
        or str(existing.get("openai_base_url", token_pool_settings.DEFAULT_OPENAI_BASE_URL)).strip()
    )
    effective_api_key = (
        api_key.strip()
        or str(existing_preset.get("openai_api_key", "")).strip()
        or str(existing.get("openai_api_key", "")).strip()
    )
    effective_model = (
        model.strip()
        or str(existing_preset.get("openai_model", "")).strip()
        or str(existing.get("openai_model", "")).strip()
    )
    effective_upstream_proxy_url = (
        upstream_proxy_url.strip()
        or str(existing_preset.get("upstream_proxy_url", "")).strip()
        or str(existing.get("upstream_proxy_url", "")).strip()
    )
    resolver = (
        token_pool_settings.resolve_openai_compatible_models_only_config
        if models_only_validation
        else token_pool_settings.resolve_openai_compatible_backend_config
    )
    resolved = resolver(
        effective_base_url,
        effective_api_key,
        effective_model,
        upstream_proxy_url=effective_upstream_proxy_url,
    )
    upstream_models = list(resolved.get("openai_models", []) or [])
    merged = _merge_openai_models(upstream_models, extras, "")
    resolved_model = str(resolved.get("openai_model", "")).strip()
    if effective_model and effective_model in merged:
        selected_model = effective_model
    elif resolved_model and resolved_model in merged:
        selected_model = resolved_model
    elif merged:
        selected_model = merged[0]
    else:
        raise RuntimeError("No models returned by the configured endpoint.")
    if selected_model not in merged:
        merged.insert(0, selected_model)
    configured_protocol = _resolved_manual_openai_protocol(
        protocol_override,
        str(existing_preset.get("openai_protocol", existing.get("openai_protocol", ""))),
    )
    final_protocol = configured_protocol or str(resolved.get("openai_protocol", "")).strip()
    if models_only_validation and not final_protocol:
        final_protocol = token_pool_settings.OPENAI_PROTOCOL_RESPONSES
    return {
        "openai_base_url": str(resolved.get("openai_base_url", effective_base_url)).strip()
        or effective_base_url,
        "openai_api_key": str(resolved.get("openai_api_key", effective_api_key)).strip()
        or effective_api_key,
        "openai_model": selected_model,
        "openai_models": merged,
        "openai_protocol": final_protocol,
        "upstream_proxy_url": effective_upstream_proxy_url,
    }


def _normalize_process_match_text(value: object) -> str:
    return str(value or "").strip().lower().replace("/", "\\")


def find_running_mobile_job_pid(job: dict[str, object], processes: list[dict[str, object]]) -> int:
    output_file = _normalize_process_match_text(job.get("output_file", ""))
    session_id = str(job.get("session_id", "")).strip().lower()
    if not output_file and not session_id:
        return 0
    best_pid = 0
    best_score = -1
    best_priority = -1
    for item in processes:
        try:
            pid = int(item.get("ProcessId", 0))
        except (TypeError, ValueError):
            continue
        if not pid or pid == os.getpid():
            continue
        command_line = _normalize_process_match_text(item.get("CommandLine", ""))
        if not command_line:
            continue
        if "codex" not in command_line or "exec --json" not in command_line:
            continue
        score = 0
        if output_file and output_file in command_line:
            score += 100
        if session_id and session_id in command_line:
            score += 10
        if score <= 0:
            continue
        name = str(item.get("Name", "")).strip().lower()
        priority = 0
        if name == "node.exe":
            priority = 3
        elif name == "codex.exe":
            priority = 2
        elif name == "cmd.exe":
            priority = 1
        if score > best_score or (score == best_score and priority > best_priority):
            best_pid = pid
            best_score = score
            best_priority = priority
    return best_pid


def find_conflicting_interactive_session_pids(session_id: str, processes: list[dict[str, object]]) -> list[int]:
    clean_session_id = session_id.strip()
    if not clean_session_id:
        return []
    pids: list[int] = []
    seen: set[int] = set()
    for item in processes:
        try:
            pid = int(item.get("ProcessId", 0))
        except (TypeError, ValueError):
            continue
        command_line = str(item.get("CommandLine", ""))
        lowered = command_line.lower()
        if not pid or pid == os.getpid():
            continue
        if clean_session_id not in command_line:
            continue
        if "codex" not in lowered:
            continue
        if "exec --json" in lowered:
            continue
        if pid in seen:
            continue
        seen.add(pid)
        pids.append(pid)
    return pids


class CodexDataStore:
    def __init__(self) -> None:
        self.notes_lock = threading.Lock()
        self.settings_lock = threading.Lock()
        self.cache_lock = threading.Lock()
        self._sessions_signature: tuple[tuple[int, int] | None, tuple[int, int] | None, tuple[int, int] | None] | None = None
        self._sessions_cache: list[SessionItem] = []
        self._mcp_signature: tuple[int, int] | None = None
        self._mcp_cache: list[McpItem] = []
        self._skills_signature: tuple[tuple[str, int, int], ...] | None = None
        self._skills_cache: list[SkillItem] = []
        self._models_signature: tuple[int, int] | None = None
        self._models_cache: list[str] = []
        self._messages_cache: dict[str, tuple[tuple[tuple[int, int] | None, tuple[int, int] | None], list[dict[str, object]]]] = {}

    def load_session_notes(self) -> dict[str, str]:
        if not NOTES_FILE.exists():
            return {}
        try:
            raw = NOTES_FILE.read_text(encoding="utf-8-sig", errors="ignore")
            obj = json.loads(raw)
        except Exception:
            return {}
        if not isinstance(obj, dict):
            return {}
        out: dict[str, str] = {}
        for key, value in obj.items():
            sid = str(key).strip()
            if sid:
                out[sid] = str(value)
        return out

    def save_session_notes(self, notes: dict[str, str]) -> None:
        with self.notes_lock:
            NOTES_FILE.parent.mkdir(parents=True, exist_ok=True)
            NOTES_FILE.write_text(json.dumps(notes, ensure_ascii=False, indent=2), encoding="utf-8")

    def load_session_settings(self) -> dict[str, dict[str, str]]:
        return load_session_settings_file(SETTINGS_FILE)

    def save_session_settings(self, settings: dict[str, dict[str, str]]) -> None:
        with self.settings_lock:
            SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
            SETTINGS_FILE.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")

    def append_history_entry(
        self,
        session_id: str,
        text: str,
        ts: int | None = None,
        history_file: Path = HISTORY_FILE,
    ) -> None:
        clean_session_id = session_id.strip()
        clean_text = text.strip()
        if not clean_session_id or not clean_text:
            return
        payload = {
            "session_id": clean_session_id,
            "ts": int(ts or now_ts()),
            "text": clean_text,
        }
        history_file.parent.mkdir(parents=True, exist_ok=True)
        with history_file.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def find_session_file(self, session_id: str) -> str:
        if not SESSIONS_DIR.exists():
            return ""
        for root, _dirs, files in os.walk(SESSIONS_DIR):
            for name in files:
                if session_id in name and is_primary_session_jsonl_name(name):
                    return str(Path(root) / name)
        return ""

    def latest_task_complete_message(self, session_id: str, since_ts: int = 0) -> tuple[int, str]:
        session_file = self.find_session_file(session_id)
        if not session_file:
            return 0, ""
        latest_ts = 0
        latest_message = ""
        try:
            with open(session_file, "r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if str(obj.get("type", "")) != "event_msg":
                        continue
                    payload = obj.get("payload", {})
                    if not isinstance(payload, dict) or str(payload.get("type", "")) != "task_complete":
                        continue
                    ts = iso_to_ts(str(obj.get("timestamp", "")))
                    if since_ts and ts and ts < since_ts:
                        continue
                    raw_message = payload.get("last_agent_message")
                    if isinstance(raw_message, str) and raw_message.strip():
                        latest_ts = ts
                        latest_message = raw_message.strip()
        except OSError:
            return 0, ""
        return latest_ts, latest_message

    def latest_partial_assistant_message(self, session_id: str, since_ts: int = 0) -> tuple[int, str]:
        session_file = self.find_session_file(session_id)
        if not session_file:
            return 0, ""
        latest_ts = 0
        latest_message = ""
        has_final_answer = False
        try:
            with open(session_file, "r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    ts = iso_to_ts(str(obj.get("timestamp", "")))
                    if since_ts and ts and ts < since_ts:
                        continue
                    obj_type = str(obj.get("type", ""))
                    payload = obj.get("payload", {})
                    if not isinstance(payload, dict):
                        continue
                    if obj_type == "event_msg":
                        event_type = str(payload.get("type", ""))
                        if event_type == "agent_message":
                            message = sanitize_assistant_message_text(str(payload.get("message", "")))
                            if message:
                                latest_ts = ts
                                latest_message = message
                        elif event_type == "task_complete":
                            final_message = payload.get("last_agent_message")
                            if isinstance(final_message, str) and final_message.strip():
                                has_final_answer = True
                        continue
                    if obj_type != "response_item" or payload.get("type") != "message":
                        continue
                    role = str(payload.get("role", ""))
                    if role == "user":
                        latest_ts = 0
                        latest_message = ""
                        has_final_answer = False
                        continue
                    if role != "assistant":
                        continue
                    content = payload.get("content", [])
                    if not isinstance(content, list):
                        continue
                    message = sanitize_assistant_message_text(flatten_message_content(content))
                    if payload.get("phase") == "final_answer":
                        if message:
                            has_final_answer = True
                        continue
                    if message:
                        latest_ts = ts
                        latest_message = message
        except OSError:
            return 0, ""
        if has_final_answer:
            return 0, ""
        return latest_ts, latest_message

    def extract_session_details(self, session_file: str) -> dict[str, str]:
        if not session_file:
            return {}
        details: dict[str, str] = {
            "cwd": "",
            "model": "",
            "approval_policy": "",
            "sandbox_mode": "",
            "turn_id": "",
            "reasoning_effort": "",
        }
        try:
            with open(session_file, "r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if obj.get("type") != "turn_context":
                        continue
                    payload = obj.get("payload", {})
                    if not isinstance(payload, dict):
                        continue
                    details["cwd"] = str(payload.get("cwd", details["cwd"]))
                    details["model"] = str(payload.get("model", details["model"]))
                    details["approval_policy"] = str(payload.get("approval_policy", details["approval_policy"]))
                    details["reasoning_effort"] = str(payload.get("model_reasoning_effort", details["reasoning_effort"]))
                    sandbox_policy = payload.get("sandbox_policy", {})
                    if isinstance(sandbox_policy, dict):
                        details["sandbox_mode"] = str(sandbox_policy.get("type", details["sandbox_mode"]))
                    details["turn_id"] = str(payload.get("turn_id", details["turn_id"]))
        except OSError:
            return {}
        return details

    def load_sessions(self) -> list[SessionItem]:
        notes = self.load_session_notes()
        overrides = self.load_session_settings()
        if not HISTORY_FILE.exists():
            return []
        history_signature = (path_signature(HISTORY_FILE), path_signature(NOTES_FILE), path_signature(SETTINGS_FILE))
        with self.cache_lock:
            if history_signature == self._sessions_signature and self._sessions_cache:
                return apply_session_overrides(apply_session_notes(self._sessions_cache, notes), overrides)

        latest: dict[str, dict[str, int | str]] = {}

        with HISTORY_FILE.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                session_id = str(obj.get("session_id", "")).strip()
                if not session_id:
                    continue
                ts = int(obj.get("ts", 0))
                text = str(obj.get("text", ""))
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
            session_file = self.find_session_file(sid)
            details = self.extract_session_details(session_file) if session_file else {}
            items.append(
                SessionItem(
                    session_id=sid,
                    ts=int(data["ts"]),
                    text=str(data["text"]),
                    note=notes.get(sid, ""),
                    history_count=int(data["count"]),
                    cwd=str(details.get("cwd", "")),
                    model=str(details.get("model", "")),
                    approval_policy=str(details.get("approval_policy", "")),
                    sandbox_mode=str(details.get("sandbox_mode", "")),
                    turn_id=str(details.get("turn_id", "")),
                    session_file=session_file,
                )
            )
        items.sort(key=lambda item: item.ts, reverse=True)
        with self.cache_lock:
            self._sessions_signature = history_signature
            self._sessions_cache = items
        return apply_session_overrides(apply_session_notes(items, notes), overrides)

    def load_messages(self, session_id: str) -> list[dict[str, object]]:
        history_signature = path_signature(HISTORY_FILE)
        session_file = self.find_session_file(session_id)
        session_signature = path_signature(Path(session_file)) if session_file else None
        cache_signature = (history_signature, session_signature)
        with self.cache_lock:
            cached = self._messages_cache.get(session_id)
            if cached and cached[0] == cache_signature:
                return copy_message_list(cached[1])

        messages: list[dict[str, object]] = []
        seen_user_messages: dict[str, list[int]] = {}
        current_turn: dict[str, object] | None = None

        def flush_pending_assistant(task_complete_ts: int = 0, explicit_text: str = "") -> None:
            nonlocal current_turn
            if not current_turn:
                return
            if not bool(current_turn.get("has_final_answer")):
                fallback_text = explicit_text.strip() or str(current_turn.get("last_assistant_text", "")).strip()
                fallback_ts = int(current_turn.get("last_assistant_ts", 0) or task_complete_ts)
                if fallback_text:
                    messages.append(
                        {
                            "role": "assistant",
                            "ts": fallback_ts or task_complete_ts,
                            "text": fallback_text,
                        }
                    )
            current_turn = None

        def begin_turn() -> None:
            nonlocal current_turn
            flush_pending_assistant()
            current_turn = {
                "has_final_answer": False,
                "last_assistant_ts": 0,
                "last_assistant_text": "",
                "saw_assistant_progress": False,
            }

        if HISTORY_FILE.exists():
            with HISTORY_FILE.open("r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if str(obj.get("session_id", "")).strip() != session_id:
                        continue
                    text = str(obj.get("text", ""))
                    ts = int(obj.get("ts", 0))
                    messages.append({"role": "user", "ts": ts, "text": text})
                    normalized = normalize_message_text(text)
                    if normalized:
                        seen_user_messages.setdefault(normalized, []).append(ts)

        if session_file:
            try:
                with open(session_file, "r", encoding="utf-8") as handle:
                    for line in handle:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            obj = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        obj_type = str(obj.get("type", ""))
                        ts = iso_to_ts(str(obj.get("timestamp", "")))
                        if obj_type == "event_msg":
                            payload = obj.get("payload", {})
                            if not isinstance(payload, dict):
                                continue
                            event_type = str(payload.get("type", ""))
                            if event_type == "agent_message" and current_turn is not None:
                                progress_text = sanitize_assistant_message_text(str(payload.get("message", "")))
                                if progress_text:
                                    current_turn["last_assistant_ts"] = ts
                                    current_turn["last_assistant_text"] = progress_text
                                    current_turn["saw_assistant_progress"] = True
                            elif event_type == "task_complete":
                                raw_last_message = payload.get("last_agent_message")
                                explicit_text = raw_last_message if isinstance(raw_last_message, str) else ""
                                flush_pending_assistant(task_complete_ts=ts, explicit_text=explicit_text)
                            continue
                        if obj_type != "response_item":
                            continue
                        payload = obj.get("payload", {})
                        if not isinstance(payload, dict):
                            continue
                        if payload.get("type") != "message":
                            continue
                        role = str(payload.get("role", ""))
                        content = payload.get("content", [])
                        if not isinstance(content, list):
                            continue
                        text = flatten_message_content(content)
                        if not text:
                            continue
                        if role == "user":
                            if is_internal_session_user_text(text):
                                continue
                            duplicate_user = is_duplicate_user_message(seen_user_messages, text, ts)
                            begin_turn()
                            if duplicate_user:
                                continue
                            messages.append({"role": "user", "ts": ts, "text": text})
                            normalized = normalize_message_text(text)
                            if normalized:
                                seen_user_messages.setdefault(normalized, []).append(ts)
                            continue
                        if role != "assistant":
                            continue
                        if payload.get("phase") != "final_answer":
                            if current_turn is not None:
                                current_turn["last_assistant_ts"] = ts
                                current_turn["last_assistant_text"] = sanitize_assistant_message_text(text)
                                current_turn["saw_assistant_progress"] = True
                            continue
                        if current_turn is not None:
                            current_turn["has_final_answer"] = True
                        messages.append(
                            {
                                "role": "assistant",
                                "ts": ts,
                                "text": text,
                            }
                        )
                flush_pending_assistant()
            except OSError:
                pass

        messages.sort(key=lambda item: (int(item.get("ts", 0)), 0 if item.get("role") == "user" else 1))
        with self.cache_lock:
            self._messages_cache[session_id] = (cache_signature, copy_message_list(messages))
        return messages

    def invalidate_messages_cache(self, session_id: str) -> None:
        clean_session_id = session_id.strip()
        if not clean_session_id:
            return
        with self.cache_lock:
            self._messages_cache.pop(clean_session_id, None)

    def load_mcp_items(self) -> list[McpItem]:
        if not CONFIG_FILE.exists():
            return []
        config_signature = path_signature(CONFIG_FILE)
        with self.cache_lock:
            if config_signature == self._mcp_signature and self._mcp_cache:
                return list(self._mcp_cache)
        if tomllib is None:
            return self.load_mcp_items_fallback()
        try:
            raw = CONFIG_FILE.read_text(encoding="utf-8-sig", errors="ignore")
            conf = tomllib.loads(raw)
        except Exception:
            return self.load_mcp_items_fallback()

        servers = conf.get("mcp_servers", {})
        if not isinstance(servers, dict):
            return []

        items: list[McpItem] = []
        for name, cfg in servers.items():
            if not isinstance(cfg, dict):
                continue
            args_cfg = cfg.get("args", [])
            args = " ".join(str(item) for item in args_cfg) if isinstance(args_cfg, list) else str(args_cfg)
            env_cfg = cfg.get("env", {})
            env_count = len(env_cfg) if isinstance(env_cfg, dict) else 0
            items.append(
                McpItem(
                    name=str(name),
                    command=str(cfg.get("command", "")),
                    timeout=str(cfg.get("startup_timeout_sec", "")),
                    env_count=env_count,
                    args=args,
                )
            )
        items.sort(key=lambda item: item.name.lower())
        with self.cache_lock:
            self._mcp_signature = config_signature
            self._mcp_cache = list(items)
        return items

    def load_mcp_items_fallback(self) -> list[McpItem]:
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
                            block[current] = {"command": "", "timeout": "", "args": "", "env_count": 0}
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
        for name, item in block.items():
            items.append(
                McpItem(
                    name=name,
                    command=str(item.get("command", "")),
                    timeout=str(item.get("timeout", "")),
                    env_count=int(item.get("env_count", 0)),
                    args=str(item.get("args", "")),
                )
            )
        items.sort(key=lambda value: value.name.lower())
        with self.cache_lock:
            self._mcp_signature = path_signature(CONFIG_FILE)
            self._mcp_cache = list(items)
        return items

    def load_skill_items(self) -> list[SkillItem]:
        if not SKILLS_DIR.exists():
            return []
        skills_signature = directory_glob_signature(SKILLS_DIR, "SKILL.md")
        with self.cache_lock:
            if skills_signature == self._skills_signature and self._skills_cache:
                return list(self._skills_cache)
        items: list[SkillItem] = []
        for skill_md in SKILLS_DIR.rglob("SKILL.md"):
            skill_dir = skill_md.parent
            summary = ""
            try:
                with skill_md.open("r", encoding="utf-8") as handle:
                    for line in handle:
                        stripped = line.strip()
                        if stripped and not stripped.startswith("#"):
                            summary = stripped
                            break
            except OSError:
                pass
            items.append(
                SkillItem(
                    name=skill_dir.name,
                    path=str(skill_dir),
                    has_scripts=(skill_dir / "scripts").exists(),
                    summary=summary,
                )
            )
        items.sort(key=lambda item: item.name.lower())
        with self.cache_lock:
            self._skills_signature = skills_signature
            self._skills_cache = list(items)
        return items

    def load_available_models(self) -> list[str]:
        models_signature = path_signature(MODELS_CACHE_FILE)
        backend_settings_signature = path_signature(BACKEND_SETTINGS_FILE)
        backend_settings = token_pool_settings.load_backend_settings(BACKEND_SETTINGS_FILE)
        if backend_settings.get("backend_mode") == token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE:
            unique = unique_model_ids(backend_settings.get("openai_models", []))
            saved_openai_model = str(backend_settings.get("openai_model", "")).strip()
            if saved_openai_model and saved_openai_model not in unique:
                unique.insert(0, saved_openai_model)
            if unique:
                with self.cache_lock:
                    self._models_signature = (backend_settings_signature[0], backend_settings_signature[1]) if backend_settings_signature else None
                    self._models_cache = list(unique)
                return unique
        with self.cache_lock:
            if models_signature == self._models_signature and self._models_cache:
                return list(self._models_cache)
        models: list[str] = []
        if MODELS_CACHE_FILE.exists():
            try:
                with MODELS_CACHE_FILE.open("r", encoding="utf-8-sig", errors="ignore") as handle:
                    data = json.load(handle)
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
        unique = merge_available_models(models)
        with self.cache_lock:
            self._models_signature = models_signature
            self._models_cache = list(unique)
        return unique

    def session_payload(self, session_id: str) -> dict[str, object] | None:
        for item in self.load_sessions():
            if item.session_id == session_id:
                return {
                    "session": asdict(item),
                    "messages": self.load_messages(session_id),
                }
        return None

    def set_note(self, session_id: str, note: str) -> None:
        notes = self.load_session_notes()
        clean_note = note.strip()
        if clean_note:
            notes[session_id] = clean_note
        else:
            notes.pop(session_id, None)
        self.save_session_notes(notes)

    def set_session_settings(
        self,
        session_id: str,
        model: str,
        approval_policy: str,
        sandbox_mode: str,
        reasoning_effort: str,
    ) -> dict[str, str]:
        settings = self.load_session_settings()
        payload = {
            "model": model.strip(),
            "approval_policy": approval_policy.strip(),
            "sandbox_mode": sandbox_mode.strip(),
            "reasoning_effort": reasoning_effort.strip(),
        }
        cleaned = {key: value for key, value in payload.items() if value and value != "default"}
        existing_cwd = str(settings.get(session_id, {}).get("cwd", "")).strip()
        if existing_cwd:
            cleaned["cwd"] = existing_cwd
        if cleaned:
            settings[session_id] = cleaned
        else:
            settings.pop(session_id, None)
        self.save_session_settings(settings)
        return cleaned

    def delete_session(self, session_id: str) -> None:
        notes = self.load_session_notes()
        if session_id in notes:
            notes.pop(session_id, None)
            self.save_session_notes(notes)
        settings = self.load_session_settings()
        if session_id in settings:
            settings.pop(session_id, None)
            self.save_session_settings(settings)

        if HISTORY_FILE.exists():
            lines_out: list[str] = []
            with HISTORY_FILE.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if session_id not in line:
                        lines_out.append(line)
            with HISTORY_FILE.open("w", encoding="utf-8", newline="") as handle:
                handle.writelines(lines_out)

        if SESSIONS_DIR.exists():
            for root, _dirs, files in os.walk(SESSIONS_DIR):
                for name in files:
                    if session_id in name and name.endswith(".jsonl"):
                        try:
                            (Path(root) / name).unlink()
                        except OSError:
                            pass

    def clear_session_goal_context(self, session_id: str) -> dict[str, object]:
        clean_session_id = session_id.strip()
        if not clean_session_id:
            raise ValueError("Session id is required.")
        session_file = self.find_session_file(clean_session_id)
        if not session_file:
            raise FileNotFoundError("Session not found.")

        source_path = Path(session_file)
        lines = source_path.read_text(encoding="utf-8").splitlines(keepends=True)
        kept_lines: list[str] = []
        removed = 0
        for line in lines:
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                kept_lines.append(line)
                continue
            if self._is_goal_context_session_row(obj):
                removed += 1
                continue
            kept_lines.append(line)

        if removed <= 0:
            return {"ok": True, "session_id": clean_session_id, "removed": 0, "backup_file": ""}

        backup_name = f"{source_path.name}.goal-clear-backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}.jsonl"
        backup_path = source_path.with_name(backup_name)
        shutil.copy2(source_path, backup_path)
        source_path.write_text("".join(kept_lines), encoding="utf-8", newline="")
        with self.cache_lock:
            self._messages_cache.pop(clean_session_id, None)
            self._sessions_signature = None
            self._sessions_cache = None
        return {
            "ok": True,
            "session_id": clean_session_id,
            "removed": removed,
            "backup_file": str(backup_path),
        }

    def _is_goal_context_session_row(self, obj: dict[str, object]) -> bool:
        if str(obj.get("type", "")) != "response_item":
            return False
        payload = obj.get("payload", {})
        if not isinstance(payload, dict):
            return False
        if payload.get("type") != "message" or str(payload.get("role", "")) != "user":
            return False
        content = payload.get("content", [])
        if not isinstance(content, list):
            return False
        text = flatten_message_content(content)
        stripped = text.strip()
        return stripped.startswith("<codex_internal_context") and 'source="goal"' in stripped

    def list_directory(self, current_path: str) -> dict[str, object]:
        if os.name == "nt" and not current_path:
            drives: list[dict[str, str]] = []
            for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
                drive = f"{letter}:\\"
                if os.path.exists(drive):
                    drives.append({"name": drive, "path": drive})
            return {"path": "", "parent": "", "directories": drives}

        target = Path(current_path).expanduser()
        if not target.exists():
            raise FileNotFoundError("Path not found.")
        if not target.is_dir():
            raise NotADirectoryError("Path is not a directory.")

        directories: list[dict[str, str]] = []
        for child in sorted(target.iterdir(), key=lambda item: item.name.lower()):
            if child.is_dir():
                directories.append({"name": child.name, "path": str(child)})
        parent = str(target.parent) if target.parent != target else ""
        return {"path": str(target), "parent": parent, "directories": directories}

    def create_directory(self, current_path: str) -> dict[str, object]:
        if not current_path.strip():
            raise FileNotFoundError("Path not found.")
        target = ensure_working_directory(current_path)
        return self.list_directory(str(target))


class JobRunner:
    def __init__(
        self,
        data_store: CodexDataStore,
        *,
        proxy_settings_file: Path = PORTAL_SETTINGS_FILE,
        backend_settings_file: Path = BACKEND_SETTINGS_FILE,
    ) -> None:
        self.data_store = data_store
        self.proxy_settings_file = proxy_settings_file
        self.backend_settings_file = backend_settings_file
        self.lock = threading.Lock()
        self.jobs: dict[str, dict[str, object]] = {}
        self.active_sessions: set[str] = set()
        self.session_owners: dict[str, dict[str, object]] = {}

    def list_recent_cwds(self) -> list[str]:
        cwds: list[str] = []
        for item in self.data_store.load_sessions():
            if item.cwd and item.cwd not in cwds:
                cwds.append(item.cwd)
        return cwds[:20]


    def get_job(self, job_id: str) -> dict[str, object] | None:
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                return None
            session_id = str(job.get("session_id", ""))
            if session_id:
                self._recover_stale_session_locked(session_id)
                job = self.jobs.get(job_id)
                if not job:
                    return None
            return json.loads(json.dumps(job))

    def cancel_job(self, job_id: str) -> dict[str, object]:
        clean_job_id = job_id.strip()
        if not clean_job_id:
            raise ValueError("Job id is required.")
        pid = 0
        session_id = ""
        created_at = 0
        with self.lock:
            job = self.jobs.get(clean_job_id)
            if not job:
                raise FileNotFoundError("Job not found.")
            if str(job.get("status", "")) != "running":
                raise RuntimeError("Job is not running.")
            pid = int(job.get("pid", 0) or 0)
            session_id = str(job.get("session_id", ""))
            created_at = int(job.get("created_at", 0) or 0)
        if pid > 0:
            self._terminate_pid(pid)
        partial_text = ""
        if session_id:
            _partial_ts, partial_text = self.data_store.latest_partial_assistant_message(
                session_id,
                since_ts=created_at,
            )
        with self.lock:
            job = self.jobs.get(clean_job_id)
            if not job:
                raise FileNotFoundError("Job not found.")
            if str(job.get("status", "")) == "running":
                retained_text = (
                    str(job.get("last_message", "")).strip()
                    or str(job.get("live_text", "")).strip()
                    or partial_text
                )
                job["last_message"] = retained_text
                job["live_text"] = retained_text
                job["status"] = "cancelled"
                job["error"] = ""
                job["finished_at"] = now_ts()
                job["pid"] = 0
                if session_id:
                    self.active_sessions.discard(session_id)
            return json.loads(json.dumps(job))

    def active_job_for_session(self, session_id: str) -> dict[str, object] | None:
        clean_session_id = session_id.strip()
        if not clean_session_id:
            return None
        with self.lock:
            self._recover_stale_session_locked(clean_session_id)
            job_id = self._running_job_id_locked(clean_session_id)
            if not job_id:
                return None
            job = self.jobs.get(job_id)
            if not job:
                return None
            return json.loads(json.dumps(job))

    def latest_failed_job_for_session(self, session_id: str) -> dict[str, object] | None:
        clean_session_id = session_id.strip()
        if not clean_session_id:
            return None
        with self.lock:
            latest: dict[str, object] | None = None
            latest_ts = -1
            latest_completed_ts = -1
            for job in self.jobs.values():
                if str(job.get("session_id", "")) != clean_session_id:
                    continue
                finished_at = int(job.get("finished_at", 0) or 0)
                created_at = int(job.get("created_at", 0) or 0)
                sort_ts = max(finished_at, created_at)
                if str(job.get("status", "")) == "completed":
                    latest_completed_ts = max(latest_completed_ts, sort_ts)
                    continue
                if str(job.get("status", "")) != "failed":
                    continue
                if sort_ts >= latest_ts:
                    latest = job
                    latest_ts = sort_ts
            if not latest:
                return None
            if latest_completed_ts >= latest_ts:
                return None
            return json.loads(json.dumps(latest))

    def latest_completed_job_for_session(self, session_id: str) -> dict[str, object] | None:
        clean_session_id = session_id.strip()
        if not clean_session_id:
            return None
        with self.lock:
            latest: dict[str, object] | None = None
            latest_ts = -1
            for job in self.jobs.values():
                if str(job.get("session_id", "")) != clean_session_id:
                    continue
                finished_at = int(job.get("finished_at", 0) or 0)
                created_at = int(job.get("created_at", 0) or 0)
                sort_ts = max(finished_at, created_at)
                if sort_ts < latest_ts:
                    continue
                latest = job
                latest_ts = sort_ts
            if not latest or str(latest.get("status", "")) != "completed":
                return None
            return json.loads(json.dumps(latest))

    def claim_session(
        self,
        session_id: str,
        owner_kind: str,
        owner_label: str,
        mode: str = "write",
        lease_id: str = "",
    ) -> dict[str, object]:
        with self.lock:
            payload = self._claim_session_locked(session_id, owner_kind, owner_label, mode=mode, lease_id=lease_id)
            return json.loads(json.dumps(payload))

    def _claim_session_locked(
        self,
        session_id: str,
        owner_kind: str,
        owner_label: str,
        mode: str = "write",
        lease_id: str = "",
    ) -> dict[str, object]:
        clean_session_id = session_id.strip()
        if not clean_session_id:
            raise ValueError("Session id is required.")
        clean_owner_kind = owner_kind.strip() or "mobile"
        clean_owner_label = owner_label.strip() or clean_owner_kind.replace("_", " ").title()
        clean_mode = mode.strip() or "write"
        clean_lease_id = lease_id.strip()

        self._recover_stale_session_locked(clean_session_id)
        owner = self._get_live_owner_locked(clean_session_id)
        if owner:
            same_lease = clean_lease_id and clean_lease_id == str(owner.get("lease_id", ""))
            same_owner = (
                str(owner.get("owner_kind", "")) == clean_owner_kind
                and str(owner.get("owner_label", "")) == clean_owner_label
            )
            if not same_lease and not same_owner:
                raise RuntimeError(f"Session is currently controlled by {owner.get('owner_label', 'another client')}.")
            if same_owner and not clean_lease_id:
                clean_lease_id = str(owner.get("lease_id", ""))
        if not clean_lease_id:
            clean_lease_id = secrets.token_hex(8)

        payload = {
            "ok": True,
            "session_id": clean_session_id,
            "owner_kind": clean_owner_kind,
            "owner_label": clean_owner_label,
            "mode": clean_mode,
            "lease_id": clean_lease_id,
            "heartbeat_at": now_ts(),
        }
        self.session_owners[clean_session_id] = payload
        return payload

    def heartbeat_session(self, session_id: str, lease_id: str) -> dict[str, object]:
        clean_session_id = session_id.strip()
        clean_lease_id = lease_id.strip()
        if not clean_session_id or not clean_lease_id:
            raise ValueError("Session id and lease id are required.")

        with self.lock:
            owner = self._get_live_owner_locked(clean_session_id)
            if not owner or str(owner.get("lease_id", "")) != clean_lease_id:
                raise RuntimeError("Session lease is no longer active.")
            owner["heartbeat_at"] = now_ts()
            self.session_owners[clean_session_id] = owner
            return json.loads(json.dumps(owner))

    def release_session(self, session_id: str, lease_id: str) -> dict[str, object]:
        clean_session_id = session_id.strip()
        clean_lease_id = lease_id.strip()
        if not clean_session_id or not clean_lease_id:
            raise ValueError("Session id and lease id are required.")

        with self.lock:
            owner = self._get_live_owner_locked(clean_session_id)
            if not owner or str(owner.get("lease_id", "")) != clean_lease_id:
                return {"ok": False, "session_id": clean_session_id}
            self.session_owners.pop(clean_session_id, None)
            return {"ok": True, "session_id": clean_session_id}

    def current_owner(self, session_id: str) -> dict[str, object] | None:
        clean_session_id = session_id.strip()
        if not clean_session_id:
            return None
        with self.lock:
            owner = self._get_live_owner_locked(clean_session_id)
            if not owner:
                return None
            return json.loads(json.dumps(owner))

    def start_resume_job(
        self,
        session_id: str,
        prompt: str,
        model: str,
        sandbox: str,
        approval: str,
        reasoning_effort: str,
        lease_id: str = "",
        owner_kind: str = "mobile",
        owner_label: str = "Mobile",
        image_payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        if not prompt.strip() and not image_payload:
            raise ValueError("Prompt or image is required.")
        sessions = {item.session_id: item for item in self.data_store.load_sessions()}
        item = sessions.get(session_id)
        if not item:
            raise FileNotFoundError("Session not found.")
        image_paths: list[Path] = []
        image_path = materialize_image_attachment(image_payload)
        if image_path is not None:
            image_paths.append(image_path)
        conflicting_pids = find_conflicting_interactive_session_pids(session_id, list_windows_process_rows())
        if conflicting_pids:
            raise RuntimeError("This session is currently open in a desktop Codex terminal. Close that terminal before sending from mobile.")
        with self.lock:
            self._recover_stale_session_locked(session_id)
            owner = self._get_live_owner_locked(session_id)
            if owner:
                owner_lease_id = str(owner.get("lease_id", ""))
                same_lease = lease_id.strip() and lease_id.strip() == owner_lease_id
                same_owner = (
                    str(owner.get("owner_kind", "")) == owner_kind
                    and str(owner.get("owner_label", "")) == owner_label
                )
                if not same_lease and not same_owner:
                    raise RuntimeError(f"Session is currently controlled by {owner.get('owner_label', 'another client')}.")
                if not lease_id.strip():
                    lease_id = owner_lease_id
                owner["heartbeat_at"] = now_ts()
                self.session_owners[session_id] = owner
            else:
                owner = self._claim_session_locked(session_id, owner_kind, owner_label, lease_id=lease_id.strip())
                lease_id = str(owner.get("lease_id", ""))
            if session_id in self.active_sessions:
                raise RuntimeError("A job is already running for this session.")
            self.active_sessions.add(session_id)
            created_at = now_ts()
            job_id = secrets.token_hex(8)
            self.jobs[job_id] = {
                "job_id": job_id,
                "status": "running",
                "kind": "resume",
                "session_id": session_id,
                "created_at": created_at,
                "heartbeat_at": created_at,
                "pid": 0,
                "error": "",
                "last_message": "",
                "log_tail": [],
                "live_text": "",
                "live_chunks_version": 0,
                "has_final_answer": False,
                "owner_kind": str(owner.get("owner_kind", owner_kind)),
                "owner_label": str(owner.get("owner_label", owner_label)),
                "lease_id": lease_id.strip(),
            }
        thread = threading.Thread(
            target=self._run_resume_job,
            args=(job_id, item.cwd or str(Path.home()), session_id, prompt, model, sandbox, approval, reasoning_effort, image_paths),
            daemon=True,
        )
        try:
            thread.start()
        except Exception:
            for image_path in image_paths:
                image_path.unlink(missing_ok=True)
            raise
        return self.get_job(job_id) or {"job_id": job_id, "lease_id": lease_id.strip(), "status": "running"}

    def start_new_chat_job(
        self,
        cwd: str,
        prompt: str,
        model: str,
        sandbox: str,
        approval: str,
        reasoning_effort: str,
        note: str,
    ) -> dict[str, object]:
        if not cwd.strip():
            raise ValueError("Working directory is required.")
        if not prompt.strip():
            raise ValueError("Prompt is required.")
        target = ensure_working_directory(cwd)

        job_id = secrets.token_hex(8)
        with self.lock:
            created_at = now_ts()
            self.jobs[job_id] = {
                "job_id": job_id,
                "status": "running",
                "kind": "new_chat",
                "session_id": "",
                "created_at": created_at,
                "heartbeat_at": created_at,
                "pid": 0,
                "error": "",
                "last_message": "",
                "log_tail": [],
                "live_text": "",
                "live_chunks_version": 0,
                "has_final_answer": False,
                "note": note.strip(),
                "opening_prompt": prompt.strip(),
                "opening_prompt_recorded": False,
            }

        thread = threading.Thread(
            target=self._run_new_chat_job,
            args=(job_id, str(target), prompt, model, sandbox, approval, reasoning_effort),
            daemon=True,
        )
        thread.start()
        return self.get_job(job_id) or {"job_id": job_id, "status": "running"}

    def _append_log(self, job_id: str, line: str) -> None:
        if "failed to refresh available models" in line:
            return
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                return
            log_tail = list(job.get("log_tail", []))
            log_tail.append(line[-500:])
            job["log_tail"] = log_tail[-12:]
            job["heartbeat_at"] = now_ts()

    def _append_live_text(self, job_id: str, text: str) -> None:
        clean_text = text.strip()
        if not clean_text:
            return
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                return
            previous = str(job.get("live_text", ""))
            if clean_text == previous:
                return
            if previous and clean_text.startswith(previous):
                merged = clean_text
            elif not previous:
                merged = clean_text
            else:
                merged = f"{previous}\n{clean_text}"
            job["live_text"] = merged[-4000:]
            job["live_chunks_version"] = int(job.get("live_chunks_version", 0)) + 1
            job["heartbeat_at"] = now_ts()

    def _job_last_message(self, job_id: str) -> str:
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                return ""
            return str(job.get("last_message", "")).strip()

    def _finish_job(
        self,
        job_id: str,
        status: str,
        session_id: str,
        last_message: str,
        error: str = "",
        release_session: str = "",
    ) -> None:
        recovered_partial = ""
        if status == "failed" and session_id and not last_message.strip():
            with self.lock:
                existing_job = self.jobs.get(job_id, {})
                created_at = int(existing_job.get("created_at", 0) or 0)
            _partial_ts, recovered_partial = self.data_store.latest_partial_assistant_message(
                session_id,
                since_ts=created_at,
            )
        with self.lock:
            job = self.jobs.get(job_id)
            if job:
                current_status = str(job.get("status", ""))
                if current_status == "cancelled" and status != "cancelled":
                    if session_id:
                        job["session_id"] = session_id
                    if last_message and not str(job.get("last_message", "")).strip():
                        job["last_message"] = last_message
                    job["finished_at"] = int(job.get("finished_at", now_ts()) or now_ts())
                else:
                    job["status"] = status
                    job["session_id"] = session_id
                    retained_message = (
                        last_message.strip()
                        or str(job.get("last_message", "")).strip()
                        or str(job.get("live_text", "")).strip()
                        or recovered_partial
                    )
                    job["last_message"] = retained_message
                    if status == "completed" and retained_message:
                        job["live_text"] = retained_message
                    if retained_message and not str(job.get("live_text", "")).strip():
                        job["live_text"] = retained_message
                    if status == "failed":
                        diagnostic_error = str(job.get("diagnostic_error", "")).strip() or error.strip()
                        job["error"] = INTERRUPTED_REPLY_MESSAGE
                        if diagnostic_error:
                            job["diagnostic_error"] = diagnostic_error
                    else:
                        job["error"] = error
                    job["finished_at"] = now_ts()
            if release_session:
                self.active_sessions.discard(release_session)
        if status == "completed" and session_id:
            invalidate_cache = getattr(self.data_store, "invalidate_messages_cache", None)
            if callable(invalidate_cache):
                invalidate_cache(session_id)

    def _run_resume_job(
        self,
        job_id: str,
        cwd: str,
        session_id: str,
        prompt: str,
        model: str,
        sandbox: str,
        approval: str,
        reasoning_effort: str,
        image_paths: list[Path] | None = None,
    ) -> None:
        output_file = Path(tempfile.mkstemp(prefix="codex-mobile-out-", suffix=".txt")[1])
        with self.lock:
            job = self.jobs.get(job_id)
            if job:
                job["output_file"] = str(output_file)
        ensure_backend_proxy_ready(
            backend_settings_file=self.backend_settings_file,
            proxy_settings_file=self.proxy_settings_file,
        )
        args = build_resume_args(
            output_file,
            session_id,
            prompt,
            model,
            sandbox,
            approval,
            reasoning_effort,
            image_paths or [],
            backend_settings_file=self.backend_settings_file,
        )
        queued_at = now_ts()
        with self.lock:
            job = self.jobs.get(job_id)
            if job:
                queued_at = int(job.get("created_at", queued_at))

        try:
            stdin_text = prompt if prompt.strip() else None
            detected_session = self._run_codex_process(job_id, args, cwd, session_id, stdin_text=stdin_text)
            history_text = build_history_entry_text(prompt, image_paths or [])
            target_session = detected_session or session_id
            if history_text and target_session:
                self.data_store.append_history_entry(target_session, history_text, ts=queued_at)
            last_message = output_file.read_text(encoding="utf-8", errors="ignore").strip() if output_file.exists() else ""
            if not last_message:
                last_message = self._job_last_message(job_id)
            self._finish_job(job_id, "completed", detected_session or session_id, last_message, release_session=session_id)
        except Exception as exc:
            self._finish_job(job_id, "failed", session_id, "", str(exc), release_session=session_id)
        finally:
            try:
                output_file.unlink(missing_ok=True)
            except OSError:
                pass
            for image_path in image_paths or []:
                try:
                    image_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def _run_new_chat_job(
        self,
        job_id: str,
        cwd: str,
        prompt: str,
        model: str,
        sandbox: str,
        approval: str,
        reasoning_effort: str,
    ) -> None:
        output_file = Path(tempfile.mkstemp(prefix="codex-mobile-out-", suffix=".txt")[1])
        with self.lock:
            job = self.jobs.get(job_id)
            if job:
                job["output_file"] = str(output_file)
        ensure_backend_proxy_ready(
            backend_settings_file=self.backend_settings_file,
            proxy_settings_file=self.proxy_settings_file,
        )
        args = build_new_chat_args(
            output_file,
            prompt,
            model,
            sandbox,
            approval,
            reasoning_effort,
            backend_settings_file=self.backend_settings_file,
        )
        queued_at = now_ts()
        with self.lock:
            job = self.jobs.get(job_id)
            if job:
                queued_at = int(job.get("created_at", queued_at))

        try:
            session_id = self._run_codex_process(job_id, args, cwd, "", stdin_text=prompt)
            opening_prompt_recorded = False
            last_message = output_file.read_text(encoding="utf-8", errors="ignore").strip() if output_file.exists() else ""
            if not last_message:
                last_message = self._job_last_message(job_id)
            note = ""
            with self.lock:
                job = self.jobs.get(job_id)
                if job:
                    note = str(job.get("note", ""))
                    opening_prompt_recorded = bool(job.get("opening_prompt_recorded", False))
            if session_id and prompt.strip() and not opening_prompt_recorded:
                self.data_store.append_history_entry(session_id, prompt.strip(), ts=queued_at)
            if session_id and note:
                self.data_store.set_note(session_id, note)
            self._finish_job(job_id, "completed", session_id, last_message)
        except Exception as exc:
            self._finish_job(job_id, "failed", "", "", str(exc))
        finally:
            try:
                output_file.unlink(missing_ok=True)
            except OSError:
                pass

    def _run_codex_process(
        self,
        job_id: str,
        args: list[str],
        cwd: str,
        fallback_session_id: str,
        stdin_text: str | None = None,
    ) -> str:
        process = subprocess.Popen(
            args,
            cwd=cwd,
            stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=build_codex_subprocess_env(
                settings_file=self.proxy_settings_file,
                backend_settings_file=self.backend_settings_file,
            ),
        )
        detected_session_id = fallback_session_id
        if stdin_text is not None and process.stdin is not None:
            try:
                process.stdin.write(stdin_text)
            except BrokenPipeError:
                pass
            finally:
                try:
                    process.stdin.close()
                except OSError:
                    pass
        if process.stdout is None:
            raise RuntimeError("Failed to open Codex process output.")
        with self.lock:
            job = self.jobs.get(job_id)
            if job:
                job["pid"] = int(process.pid)
                job["heartbeat_at"] = now_ts()

        line_queue: queue.Queue[str | None] = queue.Queue()
        stdout_finished = threading.Event()

        def pump_stdout() -> None:
            try:
                for raw_line in process.stdout:
                    line_queue.put(raw_line)
            finally:
                stdout_finished.set()
                line_queue.put(None)

        pump_thread = threading.Thread(target=pump_stdout, daemon=True)
        pump_thread.start()

        started_at = time.monotonic()
        startup_no_output_deadline = started_at + PROCESS_STARTUP_NO_OUTPUT_TIMEOUT_SECONDS
        max_runtime_deadline = (
            started_at + PROCESS_MAX_RUNTIME_SECONDS
            if PROCESS_MAX_RUNTIME_SECONDS > 0
            else 0.0
        )
        completion_deadline = 0.0
        saw_any_output = False
        while True:
            timeout = 0.2
            if completion_deadline > 0.0:
                remaining = completion_deadline - time.monotonic()
                if remaining <= 0:
                    break
                timeout = min(timeout, max(remaining, 0.01))
            try:
                raw_line = line_queue.get(timeout=timeout)
            except queue.Empty:
                if stdout_finished.is_set():
                    break
                if completion_deadline > 0.0:
                    break
                now_mono = time.monotonic()
                if not saw_any_output and now_mono >= startup_no_output_deadline:
                    self._append_log(job_id, "Codex produced no startup output for too long; terminating job.")
                    exit_code = self._stop_process_after_grace(process)
                    raise RuntimeError(
                        f"Codex produced no startup output for {int(PROCESS_STARTUP_NO_OUTPUT_TIMEOUT_SECONDS)} seconds (exit {exit_code})."
                    )
                if max_runtime_deadline > 0.0 and now_mono >= max_runtime_deadline:
                    self._append_log(job_id, "Codex job exceeded max runtime; terminating job.")
                    exit_code = self._stop_process_after_grace(process)
                    raise RuntimeError(
                        f"Codex job exceeded {int(PROCESS_MAX_RUNTIME_SECONDS)} seconds (exit {exit_code})."
                    )
                continue
            if raw_line is None:
                break
            line = raw_line.strip()
            if not line:
                continue
            saw_any_output = True
            self._append_log(job_id, line)
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                if completion_deadline > 0.0:
                    completion_deadline = time.monotonic() + PROCESS_EXIT_GRACE_SECONDS
                continue
            if not isinstance(event, dict):
                continue
            try:
                detected_session_id, completion_seen = self._handle_codex_event(job_id, event, detected_session_id)
            except Exception:
                self._terminate_pid(int(process.pid))
                raise
            if completion_seen or completion_deadline > 0.0:
                completion_deadline = time.monotonic() + PROCESS_EXIT_GRACE_SECONDS

        if completion_deadline > 0.0 and not stdout_finished.is_set():
            return_code = self._stop_process_after_grace(process)
        else:
            return_code = process.wait()
        if return_code != 0:
            raise RuntimeError(f"Codex exited with code {return_code}.")
        with self.lock:
            job = self.jobs.get(job_id)
            has_final_answer = bool(job and job.get("has_final_answer"))
        if not has_final_answer:
            raise RuntimeError(
                "Codex exited without a final answer. This is usually an upstream/model empty completion; retry or switch provider."
            )
        return detected_session_id

    def _stop_process_after_grace(self, process: subprocess.Popen[str]) -> int:
        try:
            return process.wait(timeout=PROCESS_EXIT_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            process.terminate()
        try:
            return process.wait(timeout=PROCESS_EXIT_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            process.kill()
            return process.wait(timeout=PROCESS_EXIT_GRACE_SECONDS)

    def _handle_codex_event(self, job_id: str, event: object, detected_session_id: str) -> tuple[str, bool]:
        if not isinstance(event, dict):
            return detected_session_id, False
        event_type = str(event.get("type", ""))
        if event_type == "error":
            error_message = str(event.get("message", "")).strip()
            raw_error = event.get("error")
            if not error_message and isinstance(raw_error, dict):
                error_message = str(raw_error.get("message", "")).strip()
            if error_message:
                with self.lock:
                    job = self.jobs.get(job_id)
                    if job:
                        job["diagnostic_error"] = error_message
                        job["heartbeat_at"] = now_ts()
            return detected_session_id, False

        if event_type == "thread.started":
            next_session_id = str(event.get("thread_id", detected_session_id))
            opening_prompt = ""
            created_at = now_ts()
            should_record_opening_prompt = False
            with self.lock:
                job = self.jobs.get(job_id)
                if job:
                    job["session_id"] = next_session_id
                    created_at = int(job.get("created_at", created_at))
                    if str(job.get("kind", "")) == "new_chat":
                        opening_prompt = str(job.get("opening_prompt", "")).strip()
                        should_record_opening_prompt = bool(opening_prompt) and not bool(job.get("opening_prompt_recorded", False))
                        if should_record_opening_prompt:
                            job["opening_prompt_recorded"] = True
            if next_session_id and should_record_opening_prompt:
                self.data_store.append_history_entry(next_session_id, opening_prompt, ts=created_at)
            return next_session_id, False

        if event_type == "turn.completed":
            completion_seen = False
            with self.lock:
                job = self.jobs.get(job_id)
                if job:
                    job["heartbeat_at"] = now_ts()
                    if str(job.get("last_message", "")).strip():
                        job["has_final_answer"] = True
                        completion_seen = True
            return detected_session_id, completion_seen

        if event_type == "event_msg":
            payload = event.get("payload", {})
            if isinstance(payload, dict) and str(payload.get("type", "")) == "task_complete":
                last_agent_message = payload.get("last_agent_message")
                if isinstance(last_agent_message, str) and last_agent_message.strip():
                    clean_text = last_agent_message.strip()
                    self._append_live_text(job_id, clean_text)
                    with self.lock:
                        job = self.jobs.get(job_id)
                        if job:
                            job["last_message"] = clean_text
                            job["has_final_answer"] = True
                    return detected_session_id, True
                return detected_session_id, False

        text = self._extract_event_text(event)
        if text:
            self._append_live_text(job_id, text)
            completion_seen = False
            with self.lock:
                job = self.jobs.get(job_id)
                if job:
                    job["last_message"] = text
                    if event_type == "response_item":
                        payload = event.get("payload", {})
                        if isinstance(payload, dict) and payload.get("phase") == "final_answer":
                            job["has_final_answer"] = True
                            completion_seen = True
            return detected_session_id, completion_seen
        return detected_session_id, False

    def _extract_event_text(self, event: dict[str, object]) -> str:
        direct_text = str(event.get("text", "")).strip()
        if direct_text:
            return direct_text
        for key in ("item", "payload"):
            item = event.get(key)
            if not isinstance(item, dict):
                continue
            if key == "payload" and str(item.get("type", "")) == "agent_message":
                message = sanitize_assistant_message_text(str(item.get("message", "")))
                if message:
                    return message
            item_text = str(item.get("text", "")).strip()
            if item_text:
                return item_text
            content = item.get("content", [])
            if isinstance(content, list):
                return flatten_message_content(content)
        return ""

    def _running_job_id_locked(self, session_id: str) -> str:
        for job_id, job in self.jobs.items():
            if str(job.get("status", "")) != "running":
                continue
            if str(job.get("session_id", "")) == session_id:
                return job_id
        return ""

    def _get_live_owner_locked(self, session_id: str) -> dict[str, object] | None:
        owner = self.session_owners.get(session_id)
        if not owner:
            return None
        heartbeat_at = int(owner.get("heartbeat_at", 0) or 0)
        if heartbeat_at and now_ts() - heartbeat_at <= OWNER_HEARTBEAT_TIMEOUT_SECONDS:
            return owner
        job_id = self._running_job_id_locked(session_id)
        if job_id:
            job = self.jobs.get(job_id, {})
            if self._job_is_alive_locked(job):
                return owner
        self.session_owners.pop(session_id, None)
        return None

    def _recover_stale_session_locked(self, session_id: str) -> None:
        job_id = self._running_job_id_locked(session_id)
        if not job_id:
            self.active_sessions.discard(session_id)
            self._get_live_owner_locked(session_id)
            return
        job = self.jobs.get(job_id)
        if not job:
            self.active_sessions.discard(session_id)
            return
        completed_ts, completed_message = self.data_store.latest_task_complete_message(
            session_id,
            since_ts=int(job.get("created_at", 0) or 0),
        )
        if completed_message:
            pid = int(job.get("pid", 0) or 0)
            if pid > 0 and self._is_pid_running(pid):
                self._terminate_pid(pid)
            job["status"] = "completed"
            job["last_message"] = completed_message
            job["live_text"] = completed_message
            job["has_final_answer"] = True
            job["finished_at"] = completed_ts or now_ts()
            job["pid"] = 0
            self.active_sessions.discard(session_id)
            return
        if self._job_is_alive_locked(job):
            return
        partial_text = str(job.get("last_message", "")).strip() or str(job.get("live_text", "")).strip()
        if not partial_text:
            _partial_ts, partial_text = self.data_store.latest_partial_assistant_message(
                session_id,
                since_ts=int(job.get("created_at", 0) or 0),
            )
        job["status"] = "failed"
        job["last_message"] = partial_text
        job["live_text"] = partial_text
        job["error"] = INTERRUPTED_REPLY_MESSAGE
        job["diagnostic_error"] = str(job.get("diagnostic_error", "")).strip() or "Codex process ended unexpectedly."
        job["finished_at"] = now_ts()
        job["pid"] = 0
        self.active_sessions.discard(session_id)

    def _job_is_alive_locked(self, job: dict[str, object]) -> bool:
        pid = int(job.get("pid", 0) or 0)
        heartbeat_at = int(job.get("heartbeat_at", 0) or 0)
        created_at = int(job.get("created_at", 0) or 0)
        latest_activity = max(created_at, heartbeat_at)
        if pid > 0 and self._is_pid_running(pid):
            return True
        if latest_activity and now_ts() - latest_activity < RUNNING_JOB_GRACE_SECONDS:
            return True
        if os.name == "nt":
            # codex.cmd can exit before the real node/codex worker finishes.
            recovered_pid = find_running_mobile_job_pid(job, list_windows_process_rows())
            if recovered_pid > 0:
                job["pid"] = recovered_pid
                job["heartbeat_at"] = now_ts()
                return True
        return False

    def _is_pid_running(self, pid: int) -> bool:
        if pid <= 0:
            return False
        if os.name == "nt":
            import ctypes

            process_handle = ctypes.windll.kernel32.OpenProcess(0x100000, False, pid)
            if process_handle == 0:
                return False
            ctypes.windll.kernel32.CloseHandle(process_handle)
            return True
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True

    def _terminate_pid(self, pid: int) -> bool:
        if pid <= 0:
            return False
        if os.name == "nt":
            return run_taskkill_tree_silently(pid)
        try:
            os.kill(pid, signal.SIGTERM)
            return True
        except OSError:
            return False


class PortalService:
    def __init__(self, host: str, port: int, token: str) -> None:
        self.host = host
        self.port = port
        self.token = token
        self.proxy_settings_file = PORTAL_SETTINGS_FILE
        self.backend_settings_file = BACKEND_SETTINGS_FILE
        self.data_store = CodexDataStore()
        self.jobs = JobRunner(
            self.data_store,
            proxy_settings_file=self.proxy_settings_file,
            backend_settings_file=self.backend_settings_file,
        )
        self.shared_files_lock = threading.Lock()
        self.shared_files: dict[str, dict[str, object]] = {}

    def request_desktop_refresh(self, source: str = "mobile") -> dict[str, object]:
        payload = {"ts": now_ts(), "source": source}
        DESKTOP_REFRESH_SIGNAL_FILE.parent.mkdir(parents=True, exist_ok=True)
        DESKTOP_REFRESH_SIGNAL_FILE.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return {"ok": True, **payload}

    def account_slots_payload(self) -> dict[str, object]:
        active_slot = auth_slots.detect_active_slot()
        current_auth = auth_slots.current_auth_info()
        slots = auth_slots.list_account_slots()
        return {
            "active_slot": active_slot or "",
            "current_auth": current_auth,
            "slots": slots,
            "has_running_jobs": self.has_running_jobs(),
            "quota": read_current_weekly_quota(),
            "backend": self.backend_status_payload(),
        }

    def create_account_slot(self, label: str) -> dict[str, object]:
        auth_slots.create_account_slot(label)
        return self.account_slots_payload()

    def rename_account_slot(self, slot_id: str, label: str) -> dict[str, object]:
        auth_slots.rename_account_slot(slot_id, label)
        return self.account_slots_payload()

    def delete_account_slot(self, slot_id: str) -> dict[str, object]:
        auth_slots.delete_account_slot(slot_id)
        return self.account_slots_payload()

    def bind_current_account(self, slot_id: str) -> dict[str, object]:
        auth_slots.save_current_auth_to_slot(slot_id)
        return self.account_slots_payload()

    def refresh_current_account(self) -> dict[str, object]:
        active_slot = auth_slots.detect_active_slot()
        refresh_current_chatgpt_auth(settings_file=self.proxy_settings_file)
        if active_slot:
            auth_slots.save_current_auth_to_slot(active_slot)
        self.request_desktop_refresh(source="account_refresh")
        return self.account_slots_payload()

    def login_and_bind_account(self, slot_id: str) -> dict[str, object]:
        if self.has_running_jobs():
            raise RuntimeError("Stop active replies before logging into a new account.")
        registry = auth_slots.load_slot_registry()
        if not any(str(item.get("slot_id", "")).strip() == slot_id for item in registry):
            raise FileNotFoundError(f"Account slot '{slot_id}' not found.")
        before_fingerprint = str(auth_slots.current_auth_info().get("fingerprint", "")).strip()
        result = run_codex_browser_login(settings_file=self.proxy_settings_file)
        if result.returncode != 0:
            raise RuntimeError(summarize_login_failure(result))
        after_fingerprint = str(auth_slots.current_auth_info().get("fingerprint", "")).strip()
        if not after_fingerprint or after_fingerprint == before_fingerprint:
            raise RuntimeError("Codex login finished but did not produce a new login.")
        auth_slots.save_current_auth_to_slot(slot_id)
        self.request_desktop_refresh(source="account_login_bind")
        return self.account_slots_payload()

    def switch_account(self, slot_id: str) -> dict[str, object]:
        if self.has_running_jobs():
            raise RuntimeError("Stop active replies before switching accounts.")
        auth_slots.switch_to_auth_slot(slot_id)
        self.request_desktop_refresh(source="account_switch")
        return self.account_slots_payload()

    def proxy_settings_payload(self) -> dict[str, object]:
        settings = load_proxy_settings(self.proxy_settings_file)
        return {
            "proxy_enabled": bool(settings.get("proxy_enabled", DEFAULT_PROXY_ENABLED)),
            "proxy_port": int(settings.get("proxy_port", DEFAULT_PROXY_PORT)),
            "proxy_scheme": "socks5h",
            "proxy_host": "127.0.0.1",
            "proxy_summary": current_proxy_summary_from_settings(settings),
            "public_urls": list(settings.get("public_urls", [])),
        }

    def update_proxy_settings(self, proxy_enabled: bool, proxy_port: int) -> dict[str, object]:
        save_proxy_settings(proxy_enabled, proxy_port, self.proxy_settings_file)
        return self.proxy_settings_payload()

    def browser_attach_payload(self, browser_name: str, url_prefix: str = "", hostname: str = "") -> dict[str, object]:
        return describe_controlled_browser_attach(browser_name, url_prefix=url_prefix, hostname=hostname)

    def _resolve_controlled_browser_page(
        self,
        browser_name: str,
        url_prefix: str = "",
        hostname: str = "",
    ) -> tuple[dict[str, object], dict[str, object]]:
        attach = self.browser_attach_payload(browser_name, url_prefix=url_prefix, hostname=hostname)
        if not bool(attach.get("running")):
            raise controlled_browser.ControlledBrowserError(str(attach.get("error", "Controlled browser is unavailable.")))
        if not bool(attach.get("matched")):
            raise controlled_browser.ControlledBrowserError(str(attach.get("error", "No matching controlled browser page found.")))
        selected_page = attach.get("selected_page")
        if not isinstance(selected_page, dict):
            raise controlled_browser.ControlledBrowserError("No matching controlled browser page found.")
        return attach, dict(selected_page)

    def perform_browser_action(
        self,
        *,
        browser_name: str,
        action: str,
        url_prefix: str = "",
        hostname: str = "",
        url: str = "",
        expression: str = "",
        selector: str = "",
        text: str = "",
        key: str = "",
        timeout_ms: int = 5000,
    ) -> dict[str, object]:
        attach, selected_page = self._resolve_controlled_browser_page(
            browser_name,
            url_prefix=url_prefix,
            hostname=hostname,
        )
        page_ws_url = str(selected_page.get("webSocketDebuggerUrl", "")).strip()
        if not page_ws_url:
            raise controlled_browser.ControlledBrowserError("Selected page does not expose a DevTools WebSocket URL.")
        with controlled_browser.connect_to_page(page_ws_url) as session:
            if action == "info":
                result = session.get_page_info()
            elif action == "html":
                result = {"html": session.get_html()}
            elif action == "navigate":
                result = session.navigate(url)
            elif action == "evaluate":
                result = {"value": session.evaluate(expression)}
            elif action == "click":
                result = session.click(selector)
            elif action == "type":
                result = session.type(selector, text)
            elif action == "press":
                result = session.press(key)
            elif action == "wait_text":
                result = session.wait_for_text(text, timeout_ms=timeout_ms)
            else:
                raise controlled_browser.ControlledBrowserError("Unsupported browser action.")
        return {
            "browser": str(browser_name).strip().lower(),
            "action": action,
            "selected_page": selected_page,
            "attach": attach,
            "result": result,
        }

    def restart_remote_computer(
        self,
        *,
        host: str,
        user: str,
        identity_file: str = "",
        password: str = "",
        host_key: str = "",
    ) -> dict[str, object]:
        remote_defaults = load_proxy_settings(self.proxy_settings_file).get("remote_restart", {})
        if not isinstance(remote_defaults, dict):
            remote_defaults = {}
        use_defaults = not host.strip() or not user.strip()
        clean_host = host.strip() or str(remote_defaults.get("host", "")).strip()
        clean_user = user.strip() or str(remote_defaults.get("user", "")).strip()
        clean_host_key = host_key.strip()
        if use_defaults and not clean_host_key:
            clean_host_key = str(remote_defaults.get("host_key", "")).strip()
        result = remote_ssh.restart_computer(
            user=clean_user,
            host=clean_host,
            identity_file=identity_file,
            password=password,
            host_key=clean_host_key,
        )
        output = (result.stdout or "").strip()
        if result.returncode != 0:
            raise RuntimeError(output or f"ssh exited with code {result.returncode}")
        return {
            "ok": True,
            "host": clean_host,
            "user": clean_user,
            "output": output,
        }

    def restart_local_computer(self) -> dict[str, object]:
        if os.name != "nt":
            raise RuntimeError("Local restart is only supported on Windows.")
        result = subprocess.run(
            ["shutdown", "/r", "/t", "0"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=30,
            check=False,
        )
        output = (result.stdout or "").strip()
        if result.returncode != 0:
            raise RuntimeError(output or f"shutdown exited with code {result.returncode}")
        return {"ok": True, "target": "local", "output": output}

    def backend_status_payload(self) -> dict[str, object]:
        settings = token_pool_settings.load_backend_settings(self.backend_settings_file)
        token_dir = Path(str(settings.get("token_dir", token_pool_settings.DEFAULT_TOKEN_POOL_DIR)))
        token_count = len(token_pool_settings.list_token_files(token_dir))
        proxy_port = int(settings.get("proxy_port", token_pool_settings.DEFAULT_PROXY_PORT))
        expected_backend_mode = expected_backend_mode_for_settings(settings)
        raw_health = token_pool_proxy_is_healthy(proxy_port) if expected_backend_mode else None
        health = raw_health if backend_health_matches(raw_health, expected_backend_mode) else None
        openai_models = settings.get("openai_models", [])
        openai_presets = settings.get("openai_presets", [])
        payload = {
            "backend_mode": str(settings.get("backend_mode", token_pool_settings.BACKEND_MODE_CODEX_AUTH)),
            "token_dir": str(token_dir),
            "proxy_port": proxy_port,
            "proxy_running": bool(health),
            "proxy_summary": f"http://127.0.0.1:{proxy_port}" if health else "stopped",
            "token_count": token_count,
            "openai_base_url": str(settings.get("openai_base_url", token_pool_settings.DEFAULT_OPENAI_BASE_URL)).strip(),
            "openai_model": str(settings.get("openai_model", "")).strip(),
            "openai_protocol": str(settings.get("openai_protocol", "")).strip(),
            "models_only_validation": _models_only_validation_value(
                None,
                bool(settings.get("models_only_validation", settings.get("skip_validation", False))),
            ),
            "openai_models": [str(item).strip() for item in openai_models if str(item).strip()] if isinstance(openai_models, list) else [],
            "openai_model_count": len(openai_models) if isinstance(openai_models, list) else 0,
            "openai_presets": [
                {
                    "id": str(item.get("id", "")).strip(),
                    "name": str(item.get("name", "")).strip(),
                    "openai_base_url": str(item.get("openai_base_url", token_pool_settings.DEFAULT_OPENAI_BASE_URL)).strip(),
                    "openai_model": str(item.get("openai_model", "")).strip(),
                    "openai_models": [str(model).strip() for model in item.get("openai_models", []) if str(model).strip()] if isinstance(item.get("openai_models", []), list) else [],
                    "openai_protocol": str(item.get("openai_protocol", "")).strip(),
                    "openai_api_key": str(item.get("openai_api_key", "")).strip(),
                    "proxy_preference": str(item.get("proxy_preference", "direct")).strip() if str(item.get("proxy_preference", "direct")).strip() in {"direct", "proxy"} else "direct",
                    "upstream_proxy_url": str(item.get("upstream_proxy_url", "")).strip(),
                    "models_only_validation": _models_only_validation_value(item),
                    "has_openai_api_key": bool(str(item.get("openai_api_key", "")).strip()),
                }
                for item in openai_presets
                if isinstance(item, dict) and str(item.get("id", "")).strip()
            ] if isinstance(openai_presets, list) else [],
            "active_openai_preset_id": str(settings.get("active_openai_preset_id", token_pool_settings.DEFAULT_OPENAI_PRESET_ID)).strip(),
            "proxy_preference": str(settings.get("proxy_preference", "direct")).strip() if str(settings.get("proxy_preference", "direct")).strip() in {"direct", "proxy"} else "direct",
            "upstream_proxy_url": str(settings.get("upstream_proxy_url", "")).strip(),
            "openai_api_key": str(settings.get("openai_api_key", "")).strip(),
            "has_openai_api_key": bool(str(settings.get("openai_api_key", "")).strip()),
            "last_error": "",
            "current_token_quota": {"state": "unavailable", "summary": "Quota unavailable"},
        }
        if payload["backend_mode"] == token_pool_settings.BACKEND_MODE_TOKEN_POOL:
            current_token_file = resolve_current_token_pool_file(token_dir, health)
            if current_token_file is not None:
                payload["current_token_quota"] = read_token_pool_token_quota(
                    current_token_file,
                    settings_file=self.proxy_settings_file,
                )
        return payload

    def update_backend_settings(
        self,
        backend_mode: str,
        token_dir: str,
        proxy_port: int,
        openai_base_url: str = "",
        openai_api_key: str = "",
        openai_model: str = "",
        openai_models: list[str] | None = None,
        preset_id: str = "",
        preset_name: str = "",
        create_new_preset: bool = False,
        openai_protocol: str = "",
        openai_manual_extra_models: list[str] | None = None,
        proxy_preference: str = "",
        upstream_proxy_url: str = "",
        models_only_validation: bool | None = None,
    ) -> dict[str, object]:
        current = token_pool_settings.load_backend_settings(
            self.backend_settings_file,
            persist_defaults=False,
        )
        previous_backend_mode = str(current.get("backend_mode", token_pool_settings.BACKEND_MODE_CODEX_AUTH))
        token_dir_path = Path(token_dir.strip() or str(current.get("token_dir", token_pool_settings.DEFAULT_TOKEN_POOL_DIR)))
        clean_preset_id = preset_id.strip()
        existing_preset = _find_openai_preset(current, clean_preset_id) if clean_preset_id else {}
        if models_only_validation is None:
            models_only_validation = _models_only_validation_value(
                existing_preset,
                bool(current.get("models_only_validation", current.get("skip_validation", False))),
            )
        resolved_openai_base_url = (
            openai_base_url.strip()
            or str(existing_preset.get("openai_base_url", "")).strip()
            or str(current.get("openai_base_url", token_pool_settings.DEFAULT_OPENAI_BASE_URL))
        )
        resolved_openai_api_key = (
            openai_api_key.strip()
            or str(existing_preset.get("openai_api_key", "")).strip()
            or str(current.get("openai_api_key", ""))
        )
        resolved_upstream_proxy_url = (
            upstream_proxy_url.strip()
            or str(existing_preset.get("upstream_proxy_url", "")).strip()
            or str(current.get("upstream_proxy_url", "")).strip()
        )
        resolved_openai_models = (
            openai_models
            if openai_models is not None
            else existing_preset.get("openai_models", current.get("openai_models", []))
        )
        resolved_openai_model = (
            openai_model.strip()
            or str(existing_preset.get("openai_model", "")).strip()
            or str(current.get("openai_model", ""))
        )
        resolved_openai_protocol = (
            openai_protocol.strip()
            or str(existing_preset.get("openai_protocol", "")).strip()
            or str(current.get("openai_protocol", ""))
        )
        resolved_manual_extras = (
            openai_manual_extra_models
            if openai_manual_extra_models is not None
            else existing_preset.get(
                "openai_manual_extra_models",
                current.get("openai_manual_extra_models", []),
            )
        )
        extras = [str(item).strip() for item in resolved_manual_extras or [] if str(item).strip()]
        if (
            backend_mode == token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE
        ):
            resolved = _resolve_openai_compatible_input(
                existing=current,
                existing_preset=existing_preset,
                base_url=resolved_openai_base_url,
                api_key=resolved_openai_api_key,
                model=resolved_openai_model,
                extras=extras,
                protocol_override=resolved_openai_protocol,
                models_only_validation=bool(models_only_validation),
                upstream_proxy_url=resolved_upstream_proxy_url,
            )
            resolved_openai_base_url = str(resolved.get("openai_base_url", resolved_openai_base_url))
            resolved_openai_api_key = str(resolved.get("openai_api_key", resolved_openai_api_key))
            resolved_openai_model = str(resolved.get("openai_model", resolved_openai_model))
            resolved_openai_models = resolved.get("openai_models", resolved_openai_models)
            resolved_openai_protocol = str(resolved.get("openai_protocol", resolved_openai_protocol))
            resolved_upstream_proxy_url = str(resolved.get("upstream_proxy_url", resolved_upstream_proxy_url))
        updated = token_pool_settings.save_backend_settings(
            backend_mode=backend_mode,
            settings_file=self.backend_settings_file,
            token_dir=token_dir_path,
            proxy_port=proxy_port,
            proxy_api_key=str(current.get("proxy_api_key", "")),
            openai_base_url=resolved_openai_base_url,
            openai_api_key=resolved_openai_api_key,
            openai_model=resolved_openai_model,
            openai_models=resolved_openai_models,
            openai_protocol=resolved_openai_protocol,
            openai_manual_extra_models=resolved_manual_extras,
            upstream_proxy_url=resolved_upstream_proxy_url,
            models_only_validation=bool(models_only_validation),
        )
        if backend_mode == token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE and (preset_id.strip() or preset_name.strip()):
            updated = token_pool_settings.save_openai_preset(
                settings_file=self.backend_settings_file,
                preset_id=preset_id.strip(),
                name=preset_name.strip() or preset_id.strip() or token_pool_settings.DEFAULT_OPENAI_PRESET_NAME,
                openai_base_url=str(updated.get("openai_base_url", token_pool_settings.DEFAULT_OPENAI_BASE_URL)),
                openai_api_key=str(updated.get("openai_api_key", "")),
                openai_model=str(updated.get("openai_model", "")),
                openai_models=updated.get("openai_models", []),
                openai_protocol=str(updated.get("openai_protocol", "")),
                openai_manual_extra_models=updated.get("openai_manual_extra_models", []),
                proxy_preference=proxy_preference,
                upstream_proxy_url=resolved_upstream_proxy_url,
                models_only_validation=bool(models_only_validation),
                installation_id=str(existing_preset.get("installation_id", "")),
                claude_env=existing_preset.get("claude_env", {}),
                disable_image_generation=bool(existing_preset.get("disable_image_generation", False)),
                set_active=True,
                create_new=create_new_preset,
            )
        _patch_image_generation_for_backend_mode(str(updated.get("backend_mode", backend_mode)))
        self.jobs.backend_settings_file = self.backend_settings_file
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
            stop_token_pool_backend()
        elif (
            previous_backend_mode == token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE
            and updated_backend_mode == token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE
        ):
            stop_token_pool_backend()
            time.sleep(0.2)
            if openai_compatible_requires_local_proxy(updated):
                start_openai_compatible_backend(
                    backend_settings_file=self.backend_settings_file,
                    proxy_settings_file=self.proxy_settings_file,
                )
        return {
            "backend_mode": str(updated.get("backend_mode", token_pool_settings.BACKEND_MODE_CODEX_AUTH)),
            **self.backend_status_payload(),
        }

    def apply_openai_backend_preset(
        self,
        preset_id: str,
        *,
        preset_name: str | None = None,
        openai_base_url: str | None = None,
        openai_api_key: str | None = None,
        openai_model: str | None = None,
        openai_protocol: str | None = None,
        proxy_preference: str | None = None,
        upstream_proxy_url: str | None = None,
        models_only_validation: bool | None = None,
    ) -> dict[str, object]:
        existing = token_pool_settings.load_backend_settings(
            self.backend_settings_file,
            persist_defaults=False,
        )
        existing_preset = _find_openai_preset(existing, preset_id)
        if not existing_preset:
            raise KeyError(f"OpenAI preset not found: {preset_id}")
        if models_only_validation is None:
            models_only_validation = _models_only_validation_value(existing_preset)
        extras = [
            str(item).strip()
            for item in existing_preset.get("openai_manual_extra_models", []) or []
            if str(item).strip()
        ]
        resolved = _resolve_openai_compatible_input(
            existing=existing,
            existing_preset=existing_preset,
            base_url=openai_base_url or "",
            api_key=openai_api_key or "",
            model=openai_model or "",
            extras=extras,
            protocol_override=openai_protocol or "",
            models_only_validation=bool(models_only_validation),
            upstream_proxy_url=upstream_proxy_url or "",
        )
        selected_model = str(resolved.get("openai_model", ""))
        selected_protocol = str(resolved.get("openai_protocol", ""))
        selected_base_url = str(resolved.get("openai_base_url", ""))
        selected_api_key = str(resolved.get("openai_api_key", ""))
        selected_upstream_proxy_url = str(resolved.get("upstream_proxy_url", ""))
        selected_proxy_preference = (
            proxy_preference.strip()
            if proxy_preference is not None and proxy_preference.strip()
            else str(existing_preset.get("proxy_preference", "direct"))
        )
        updated = token_pool_settings.save_backend_settings(
            backend_mode=token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE,
            settings_file=self.backend_settings_file,
            token_dir=Path(str(existing.get("token_dir", token_pool_settings.DEFAULT_TOKEN_POOL_DIR))),
            proxy_port=int(existing.get("proxy_port", token_pool_settings.DEFAULT_PROXY_PORT)),
            proxy_api_key=str(existing.get("proxy_api_key", "")),
            openai_base_url=selected_base_url,
            openai_api_key=selected_api_key,
            openai_model=selected_model,
            openai_models=resolved.get("openai_models", []),
            openai_protocol=selected_protocol,
            openai_manual_extra_models=extras,
            upstream_proxy_url=selected_upstream_proxy_url,
            models_only_validation=bool(models_only_validation),
        )
        updated = token_pool_settings.save_openai_preset(
            settings_file=self.backend_settings_file,
            preset_id=preset_id.strip(),
            name=(
                preset_name.strip()
                if preset_name is not None and preset_name.strip()
                else str(existing_preset.get("name", preset_id)).strip() or preset_id.strip()
            ),
            openai_base_url=selected_base_url,
            openai_api_key=selected_api_key,
            openai_model=selected_model,
            openai_models=resolved.get("openai_models", []),
            openai_protocol=selected_protocol,
            openai_manual_extra_models=extras,
            proxy_preference=selected_proxy_preference,
            upstream_proxy_url=selected_upstream_proxy_url,
            models_only_validation=bool(models_only_validation),
            installation_id=str(existing_preset.get("installation_id", "")),
            claude_env=existing_preset.get("claude_env", {}),
            disable_image_generation=bool(existing_preset.get("disable_image_generation", False)),
            set_active=True,
        )
        stop_token_pool_backend()
        updated = token_pool_settings.load_backend_settings(self.backend_settings_file)
        active_preset = next((item for item in updated.get("openai_presets", []) if isinstance(item, dict) and str(item.get("id", "")).strip() == preset_id.strip()), {})
        _swap_installation_id_for_preset(active_preset)
        _patch_claude_settings_for_preset(active_preset)
        _patch_image_generation_for_preset(active_preset)
        time.sleep(0.2)
        if openai_compatible_requires_local_proxy(updated):
            start_openai_compatible_backend(
                backend_settings_file=self.backend_settings_file,
                proxy_settings_file=self.proxy_settings_file,
            )
        return self.backend_status_payload()

    def delete_openai_backend_preset(self, preset_id: str) -> dict[str, object]:
        previous = token_pool_settings.load_backend_settings(self.backend_settings_file)
        updated = token_pool_settings.delete_openai_preset(preset_id, settings_file=self.backend_settings_file)
        if (
            str(previous.get("backend_mode", token_pool_settings.BACKEND_MODE_CODEX_AUTH)) == token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE
            or str(updated.get("backend_mode", token_pool_settings.BACKEND_MODE_CODEX_AUTH)) == token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE
        ):
            _patch_image_generation_for_backend_mode(str(updated.get("backend_mode", "")))
            stop_token_pool_backend()
            time.sleep(0.2)
            if openai_compatible_requires_local_proxy(updated):
                start_openai_compatible_backend(
                    backend_settings_file=self.backend_settings_file,
                    proxy_settings_file=self.proxy_settings_file,
                )
        return self.backend_status_payload()

    def start_backend_proxy(self) -> dict[str, object]:
        ensure_backend_proxy_ready(
            backend_settings_file=self.backend_settings_file,
            proxy_settings_file=self.proxy_settings_file,
        )
        return self.backend_status_payload()

    def stop_backend_proxy(self) -> dict[str, object]:
        stop_token_pool_backend()
        return self.backend_status_payload()

    def restart_backend_proxy(self) -> dict[str, object]:
        settings = token_pool_settings.load_backend_settings(self.backend_settings_file)
        _patch_image_generation_for_backend_mode(str(settings.get("backend_mode", "")))
        stop_token_pool_backend()
        time.sleep(0.2)
        if settings.get("backend_mode") == token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE:
            if openai_compatible_requires_local_proxy(settings):
                start_openai_compatible_backend(
                    backend_settings_file=self.backend_settings_file,
                    proxy_settings_file=self.proxy_settings_file,
                )
        elif settings.get("backend_mode") == token_pool_settings.BACKEND_MODE_TOKEN_POOL:
            start_token_pool_backend(
                backend_settings_file=self.backend_settings_file,
                proxy_settings_file=self.proxy_settings_file,
            )
        return self.backend_status_payload()

    def has_running_jobs(self) -> bool:
        with self.jobs.lock:
            return any(str(job.get("status", "")) == "running" for job in self.jobs.jobs.values())

    def download_page_html(self) -> str:
        return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Codex Downloads</title>
  <style>
    body {{ font-family: Segoe UI, Arial, sans-serif; background:#0b1220; color:#e8eefc; margin:0; padding:24px; }}
    .card {{ max-width:720px; margin:0 auto; background:#14213d; border:1px solid #26486f; border-radius:16px; padding:24px; }}
    h1 {{ margin-top:0; font-size:28px; }}
    p {{ color:#b8c4e0; line-height:1.5; }}
    code {{ background:#0f172a; padding:2px 6px; border-radius:6px; color:#d8e4ff; }}
    a.btn {{ display:inline-block; margin:12px 12px 0 0; padding:12px 16px; border-radius:10px; background:#79e0d4; color:#0b1220; text-decoration:none; font-weight:600; }}
  </style>
</head>
<body>
  <div class="card">
    <h1>Codex Downloads</h1>
    <p>Packaged ZIP/APK files are not served from this repository checkout.</p>
    <p>Use GitHub Releases when published, or build the desktop and Android packages locally from source.</p>
    <a class="btn" href="https://github.com/penguin-oo/codex-session-manager-windows/releases">Open GitHub Releases</a>
    <p>Local build output directory, if you create packages yourself: <code>{RELEASES_DIR}</code></p>
  </div>
</body>
</html>"""

    def bootstrap_payload(self) -> dict[str, object]:
        settings = load_proxy_settings(self.proxy_settings_file)
        proxy_summary = current_proxy_summary_from_settings(settings)
        remote_restart = settings.get("remote_restart", {})
        if not isinstance(remote_restart, dict):
            remote_restart = {}
        remote_host = str(remote_restart.get("host", "")).strip()
        remote_user = str(remote_restart.get("user", "")).strip()
        remote_target_label = ""
        if remote_host and remote_user:
            remote_target_label = f"{remote_user}@{remote_host}"
        elif remote_host:
            remote_target_label = remote_host
        sessions: list[dict[str, object]] = []
        for item in self.data_store.load_sessions():
            payload = asdict(item)
            payload["is_replying"] = self.jobs.active_job_for_session(item.session_id) is not None
            sessions.append(payload)
        return {
            "title": APP_TITLE,
            "sessions": sessions,
            "mcp": [asdict(item) for item in self.data_store.load_mcp_items()],
            "skills": [asdict(item) for item in self.data_store.load_skill_items()],
            "models": default_model_options(self.data_store.load_available_models()),
            "approval_options": ["default", "untrusted", "on-request", "never"],
            "sandbox_options": ["default", "read-only", "workspace-write", "danger-full-access"],
            "reasoning_options": list(REASONING_EFFORT_OPTIONS),
            "recent_cwds": self.jobs.list_recent_cwds(),
            "proxy_summary": proxy_summary,
            "backend": self.backend_status_payload(),
            "startup_url_groups": [{"label": label, "urls": list(urls)} for label, urls in self.startup_url_groups()],
            "default_portal_urls": list(settings.get("default_portal_urls", [])),
            "remote_restart_target_label": remote_target_label,
        }

    def session_payload(self, session_id: str) -> dict[str, object] | None:
        payload = self.data_store.session_payload(session_id)
        if payload is None:
            return None
        session = payload.get("session")
        active_job = self.jobs.active_job_for_session(session_id)
        completed_job = None if active_job else self.jobs.latest_completed_job_for_session(session_id)
        messages = payload.get("messages")
        if completed_job and isinstance(messages, list):
            payload["messages"] = reconcile_completed_job_message(messages, completed_job)
            messages = payload["messages"]
        if (
            active_job
            and isinstance(messages, list)
            and messages
            and isinstance(messages[-1], dict)
            and str(messages[-1].get("role", "")) == "assistant"
            and str(messages[-1].get("text", "")).strip() == INCOMPLETE_REPLY_PLACEHOLDER
        ):
            payload["messages"] = messages[:-1]
        if isinstance(session, dict):
            session["is_replying"] = active_job is not None
        payload["owner"] = self.jobs.current_owner(session_id)
        payload["active_job"] = active_job or self.jobs.latest_failed_job_for_session(session_id)
        payload["proxy_summary"] = current_proxy_summary(self.proxy_settings_file)
        payload["models"] = default_model_options(self.data_store.load_available_models())
        payload["approval_options"] = ["default", "untrusted", "on-request", "never"]
        payload["sandbox_options"] = ["default", "read-only", "workspace-write", "danger-full-access"]
        payload["reasoning_options"] = list(REASONING_EFFORT_OPTIONS)
        return payload

    def clear_session_goal_context(self, session_id: str) -> dict[str, object]:
        return self.data_store.clear_session_goal_context(session_id)

    def update_session_settings(
        self,
        session_id: str,
        model: str,
        approval_policy: str,
        sandbox_mode: str,
        reasoning_effort: str,
    ) -> dict[str, object]:
        self.data_store.set_session_settings(session_id, model, approval_policy, sandbox_mode, reasoning_effort)
        payload = self.session_payload(session_id)
        if payload is None:
            raise FileNotFoundError("Session not found.")
        return payload

    def create_file_share(self, session_id: str, raw_path: str) -> dict[str, object]:
        clean_session_id = session_id.strip()
        clean_path = raw_path.strip()
        if not clean_session_id:
            raise ValueError("Session id is required.")
        if not clean_path:
            raise ValueError("Path is required.")

        session_payload = self.session_payload(clean_session_id)
        if session_payload is None:
            raise FileNotFoundError("Session not found.")
        session = session_payload.get("session")
        session_cwd = ""
        if isinstance(session, dict):
            session_cwd = str(session.get("cwd", "")).strip()

        resolved_path = normalize_existing_file_path(clean_path, cwd=session_cwd)
        if resolved_path.suffix.lower() not in SUPPORTED_SHARED_SUFFIXES:
            raise ValueError("Unsupported file type for browser sharing.")

        allowed_roots: list[Path] = []
        for root_value in [session_cwd, *self.jobs.list_recent_cwds()]:
            clean_root = root_value.strip()
            if not clean_root:
                continue
            try:
                root_path = Path(clean_root).expanduser().resolve(strict=True)
            except OSError:
                continue
            if not root_path.is_dir():
                continue
            if all(existing != root_path for existing in allowed_roots):
                allowed_roots.append(root_path)

        if not any(path_is_within_root(resolved_path, root) for root in allowed_roots):
            raise PermissionError("File path is outside the allowed shared roots.")

        share_id = secrets.token_urlsafe(18)
        expires_at = now_ts() + FILE_SHARE_TTL_SECONDS
        entry = {
            "share_id": share_id,
            "path": resolved_path,
            "content_type": guess_shared_file_content_type(resolved_path),
            "file_name": resolved_path.name,
            "expires_at": expires_at,
            "session_id": clean_session_id,
        }
        with self.shared_files_lock:
            self._prune_expired_shared_files_locked()
            self.shared_files[share_id] = entry
        return {
            "share_id": share_id,
            "relative_url": f"/files/{share_id}?token={self.token}",
            "file_name": resolved_path.name,
            "content_type": entry["content_type"],
            "expires_at": expires_at,
        }

    def resolve_file_share(self, share_id: str) -> dict[str, object]:
        clean_share_id = share_id.strip()
        if not clean_share_id:
            raise FileNotFoundError("Shared file link not found.")
        with self.shared_files_lock:
            self._prune_expired_shared_files_locked()
            entry = self.shared_files.get(clean_share_id)
            if entry is None:
                raise FileNotFoundError("Shared file link not found.")
            return dict(entry)

    def _prune_expired_shared_files_locked(self) -> None:
        current_ts = now_ts()
        expired_ids = [
            share_id
            for share_id, entry in self.shared_files.items()
            if int(entry.get("expires_at", 0) or 0) <= current_ts
        ]
        for share_id in expired_ids:
            self.shared_files.pop(share_id, None)

    def tailscale_urls(self) -> list[str]:
        cli = find_tailscale_cli()
        if not cli:
            return []
        urls: list[str] = []
        dns_name = extract_tailscale_dns_name(run_text_command([cli, "status", "--json"]))
        if dns_name:
            urls.append(f"http://{dns_name}:{self.port}/?token={self.token}")
        for address in extract_tailscale_ipv4_addresses(run_text_command([cli, "ip", "-4"])):
            url = f"http://{address}:{self.port}/?token={self.token}"
            if url not in urls:
                urls.append(url)
        return urls

    def public_urls(self) -> list[str]:
        settings = load_proxy_settings(self.proxy_settings_file)
        return [build_public_access_url(base_url, self.token) for base_url in normalize_public_urls(settings.get("public_urls", []))]

    def lan_urls(self) -> list[str]:
        urls = [f"http://127.0.0.1:{self.port}/?token={self.token}"]
        try:
            hostname = socket.gethostname()
            addresses = {
                info[4][0]
                for info in socket.getaddrinfo(hostname, None, family=socket.AF_INET)
                if not info[4][0].startswith("127.")
            }
        except socket.gaierror:
            addresses = set()
        for address in sorted(addresses):
            urls.append(f"http://{address}:{self.port}/?token={self.token}")
        return urls

    def local_urls(self) -> list[str]:
        return self.lan_urls()

    def startup_url_groups(self) -> list[tuple[str, list[str]]]:
        groups: list[tuple[str, list[str]]] = []
        public_urls = self.public_urls()
        if public_urls:
            groups.append(("Public (Cloudflare/custom)", public_urls))
        tailscale_urls = self.tailscale_urls()
        if tailscale_urls:
            groups.append(("Tailscale (cross-network)", tailscale_urls))
        groups.append(("LAN", self.lan_urls()))
        return groups


INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>Codex+</title>
  <style>
    :root {
      --bg: #0b0d10;
      --surface: #111418;
      --surface-2: #171b20;
      --surface-3: #1d2329;
      --line: rgba(219, 226, 234, 0.12);
      --line-strong: rgba(219, 226, 234, 0.2);
      --text: #eef2f6;
      --muted: #98a2ad;
      --accent: #44c2a8;
      --danger: #f97066;
      --warn: #f6b667;
      --user: #174a5f;
      --assistant: #161b21;
      --radius: 10px;
      --font: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      --shadow: 0 12px 28px rgba(0, 0, 0, 0.22);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: var(--font);
      color: var(--text);
      background: var(--bg);
      min-height: 100vh;
    }
    .app-shell {
      max-width: 1280px;
      margin: 0 auto;
      min-height: 100vh;
      padding: 14px;
    }
    .topbar {
      display: grid;
      grid-template-columns: minmax(220px, 1fr) auto;
      gap: 16px;
      align-items: start;
      padding: 10px 2px 14px;
    }
    .topbar h1 {
      margin: 0;
      font-size: 1.12rem;
      line-height: 1.2;
      letter-spacing: 0;
    }
    .topbar p {
      margin: 5px 0 0;
      color: var(--muted);
      line-height: 1.45;
      font-size: 0.9rem;
      max-width: 760px;
    }
    .topbar-meta {
      display: grid;
      justify-items: end;
      gap: 8px;
    }
    .workspace-panel, .conversation-panel {
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
    }
    .meta, .session-meta, .toolbar { display: flex; gap: 8px; flex-wrap: wrap; }
    .meta { justify-content: flex-end; }
    .pill {
      padding: 5px 9px;
      border-radius: 999px;
      border: 1px solid var(--line);
      background: var(--surface-2);
      color: var(--muted);
      font-size: 0.78rem;
      line-height: 1.2;
    }
    a.pill {
      color: var(--text);
      text-decoration: none;
    }
    .workspace-layout { display: grid; grid-template-columns: 350px minmax(0, 1fr); gap: 12px; }
    .panel-head {
      padding: 11px 12px;
      border-bottom: 1px solid var(--line);
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 10px;
    }
    .panel-head h2 { margin: 0; font-size: 0.95rem; }
    button, select, input, textarea {
      font: inherit;
      color: var(--text);
      background: var(--surface-2);
      border: 1px solid var(--line-strong);
      border-radius: 8px;
      padding: 9px 11px;
    }
    button {
      min-height: 38px;
      cursor: pointer;
    }
    button:hover { border-color: rgba(68, 194, 168, 0.42); }
    select option { color: #101418; background: #f4f7fa; }
    label { color: var(--muted); font-size: 0.82rem; }
    input::placeholder, textarea::placeholder { color: #87919d; opacity: 1; }
    button.primary {
      color: #071310;
      background: var(--accent);
      border-color: var(--accent);
      font-weight: 650;
    }
    button.danger { color: var(--danger); border-color: rgba(255, 123, 114, 0.35); }
    .tabbar button.active {
      color: var(--text);
      background: var(--surface-3);
      border-color: rgba(68, 194, 168, 0.52);
    }
    .section { display: none; }
    .section.active { display: block; }
    .list, .item-list, .messages { display: grid; gap: 8px; padding: 10px; }
    .list { max-height: calc(100vh - 176px); overflow: auto; }
    .session-card, .item-card {
      padding: 12px;
      border-radius: 8px;
      border: 1px solid var(--line);
      background: var(--surface-2);
    }
    .session-card.active {
      border-color: rgba(68, 194, 168, 0.54);
      background: rgba(68, 194, 168, 0.08);
    }
    .session-card h3, .item-card h3 { margin: 0 0 8px; font-size: 0.95rem; word-break: break-all; }
    .session-card p, .item-card p { margin: 0; color: var(--muted); font-size: 0.85rem; line-height: 1.45; }
    .note { color: var(--warn); margin-top: 8px; font-size: 0.83rem; }
    .conversation-panel { display: grid; grid-template-rows: auto auto 1fr auto auto; min-height: calc(100vh - 88px); overflow: hidden; }
    .detail-head { padding: 16px; border-bottom: 1px solid var(--line); }
    .detail-head h2 { margin: 0; font-size: 1rem; word-break: break-all; }
    .detail-head p { margin: 8px 0 0; color: var(--muted); line-height: 1.45; font-size: 0.88rem; }
    .strip { padding: 12px 16px; border-top: 1px solid var(--line); }
    .field { display: grid; gap: 6px; }
    .checkline { display: flex; align-items: center; gap: 8px; color: var(--text); }
    .checkline input { width: auto; padding: 0; }
    .inline { display: grid; gap: 10px; grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .messages { overflow: auto; padding-top: 16px; align-content: start; }
    .bubble {
      max-width: 92%;
      padding: 14px 16px;
      border-radius: 18px;
      white-space: pre-wrap;
      word-break: break-word;
      line-height: 1.55;
      border: 1px solid var(--line);
      box-shadow: none;
    }
    .bubble.user { margin-left: auto; background: var(--user); }
    .bubble.assistant { margin-right: auto; background: var(--assistant); }
    .time { margin-top: 8px; color: var(--muted); font-size: 0.76rem; }
    .empty { color: var(--muted); text-align: center; line-height: 1.6; padding: 24px 18px; }
    .modal {
      position: fixed;
      inset: 0;
      background: rgba(2, 6, 11, 0.82);
      display: none;
      align-items: center;
      justify-content: center;
      padding: 16px;
    }
    .modal.open { display: flex; }
    .modal-card {
      width: min(680px, 100%);
      max-height: 92vh;
      overflow: auto;
      color: #f5f9ff;
      background: var(--surface);
      border: 1px solid var(--line-strong);
      border-radius: 12px;
      box-shadow: var(--shadow);
      padding: 18px;
    }
    .modal-card p, .modal-card .empty, .modal-card .time { color: #b9cbe0; }
    .dir-list { display: grid; gap: 8px; max-height: 300px; overflow: auto; margin-top: 12px; }
    .dir-item {
      text-align: left;
      display: flex;
      justify-content: space-between;
      gap: 10px;
      width: 100%;
    }
    @media (max-width: 920px) {
      .app-shell { padding: 10px; }
      .topbar { grid-template-columns: 1fr; }
      .topbar-meta { justify-items: start; }
      .meta { justify-content: flex-start; }
      .workspace-layout { grid-template-columns: 1fr; }
      .conversation-panel { min-height: auto; }
      .list { max-height: none; }
      .inline { grid-template-columns: 1fr; }
      .bubble { max-width: 100%; }
    }
  </style>
</head>
<body>
  <div class="app-shell">
    <header class="topbar">
      <div>
        <h1>Codex+</h1>
        <p>Browse local Codex sessions from your phone and continue them through this computer.</p>
      </div>
      <div class="topbar-meta">
        <div class="meta" id="heroMeta"></div>
        <div class="meta" id="heroLinks"></div>
      </div>
    </header>
    <div class="workspace-layout">
      <aside class="workspace-panel">
        <div class="panel-head">
          <h2>Workspace</h2>
          <div class="tabbar toolbar">
            <button data-tab="sessions" class="active">Sessions</button>
            <button data-tab="mcp">MCP</button>
            <button data-tab="skills">Skills</button>
            <button data-tab="backend">Backend</button>
            <button data-tab="remote">Remote</button>
          </div>
        </div>
        <section class="section active" id="tab-sessions">
          <div class="panel-head">
            <h2>Chats</h2>
            <button class="primary" id="openNewChat">New chat</button>
          </div>
          <div class="list" id="sessionList"></div>
        </section>
        <section class="section" id="tab-mcp"><div class="item-list" id="mcpList"></div></section>
        <section class="section" id="tab-skills"><div class="item-list" id="skillList"></div></section>
        <section class="section" id="tab-backend">
          <div class="item-list">
            <article class="item-card">
              <h3>Backend</h3>
              <p id="backendSummary">Loading backend settings...</p>
              <div class="field" style="margin-top:10px;"><label for="backendModeSelect">Mode</label><select id="backendModeSelect"><option value="codex_auth">Codex Auth</option><option value="built_in_token_pool">Built-in Token Pool</option><option value="openai_compatible">OpenAI-Compatible API</option></select></div>
              <div class="field" style="margin-top:10px;"><label for="backendTokenDir">Token folder</label><input id="backendTokenDir" type="text" placeholder="C:\\Users\\...\\.cli-proxy-api"></div>
              <div class="field" style="margin-top:10px;"><label for="backendProxyPort">Proxy port</label><input id="backendProxyPort" type="number" inputmode="numeric" placeholder="8317"></div>
              <div class="field" style="margin-top:10px;"><label for="backendPresetSelect">OpenAI preset</label><select id="backendPresetSelect"></select></div>
              <div class="field" style="margin-top:10px;"><label for="backendPresetName">Preset name</label><input id="backendPresetName" type="text" placeholder="GPTCode"></div>
              <div class="field" style="margin-top:10px;"><label for="backendOpenAiBaseUrl">OpenAI Base URL</label><input id="backendOpenAiBaseUrl" type="text" placeholder="https://api.openai.com/v1"></div>
              <div class="field" style="margin-top:10px;"><label for="backendOpenAiApiKey">OpenAI API key</label><input id="backendOpenAiApiKey" type="text" placeholder="Leave blank to keep saved key"></div>
              <div class="field" style="margin-top:10px;"><label for="backendProxyPreference">API proxy mode</label><select id="backendProxyPreference"><option value="direct">Direct, do not use proxy</option><option value="proxy">Use configured proxy</option></select></div>
              <div class="field" style="margin-top:10px;"><label for="backendUpstreamProxyUrl">Upstream proxy URL</label><input id="backendUpstreamProxyUrl" type="text" placeholder="Optional, e.g. http://127.0.0.1:7898"></div>
              <div class="field" style="margin-top:10px;"><label class="checkline"><input id="backendModelsOnlyValidation" type="checkbox"> Only fetch models (do not test a conversation)</label></div>
              <div class="toolbar" style="justify-content:flex-end; margin-top:12px;">
                <button id="refreshBackend">Refresh</button>
                <button id="fetchBackendModelsOnly">Fetch Models Only</button>
                <button class="primary" id="saveBackendPreset">Save preset</button>
                <button id="applyBackendPreset">Apply preset</button>
                <button class="danger" id="deleteBackendPreset">Delete preset</button>
              </div>
            </article>
          </div>
        </section>
        <section class="section" id="tab-remote">          <div class="item-list">
            <article class="item-card">
              <h3>Remote Restart</h3>
              <p>Restart a Windows computer reachable through Tailscale SSH.</p>
              <div class="field" style="margin-top:12px;"><label for="remoteHost">Tailscale host</label><input id="remoteHost" type="text" placeholder="100.x.x.x or MagicDNS name"></div>
              <div class="field" style="margin-top:10px;"><label for="remoteUser">SSH user</label><input id="remoteUser" type="text" placeholder="codexuser"></div>
              <div class="field" style="margin-top:10px;"><label for="remotePassword">Password</label><input id="remotePassword" type="password" placeholder="Optional, requires plink.exe on this PC"></div>
              <div class="field" style="margin-top:10px;"><label for="remoteIdentity">Identity file</label><input id="remoteIdentity" type="text" placeholder="Optional private key path"></div>
              <div class="toolbar" style="justify-content:flex-end; margin-top:12px;">
                <button class="danger" id="remoteRestart">Restart remote PC</button>
              </div>
            </article>
          </div>
        </section>
      </aside>
      <main class="conversation-panel">
        <div class="detail-head" id="detailHead">
          <h2>No session selected</h2>
          <p>Select an existing session from the left, or create a new one from a folder on this machine.</p>
        </div>
        <div class="strip" id="noteBox" hidden>
          <div class="inline">
            <div class="field">
              <label for="noteInput">Note</label>
              <input id="noteInput" type="text" placeholder="Optional note for this session">
            </div>
            <div class="field">
              <label>&nbsp;</label>
              <div class="toolbar">
                <button class="primary" id="saveNote">Save note</button>
                <button id="clearNote">Clear note</button>
                <button class="danger" id="deleteSession">Delete session</button>
              </div>
            </div>
          </div>
        </div>
        <div class="messages" id="messageList"><div class="empty">Conversation messages will appear here.</div></div>
        <div class="strip" id="composerSettings" hidden>
          <div class="inline">
            <div class="field"><label for="modelSelect">Model</label><select id="modelSelect"></select></div>
            <div class="field"><label for="approvalSelect">Approval</label><select id="approvalSelect"></select></div>
            <div class="field"><label for="sandboxSelect">Sandbox</label><select id="sandboxSelect"></select></div>
            <div class="field"><label for="reasoningSelect">Reasoning</label><select id="reasoningSelect"></select></div>
            <div class="field"><label>&nbsp;</label><button id="refreshSession">Refresh</button></div>
          </div>
        </div>
        <div class="strip" id="composer" hidden>
          <div class="field">
            <label for="promptInput">Send message</label>
            <textarea id="promptInput" rows="5" placeholder="Type the next message for this Codex session..."></textarea>
          </div>
          <div class="toolbar" style="justify-content:flex-end; margin-top:10px;">
            <button class="primary" id="sendPrompt">Send</button>
          </div>
        </div>
        <div class="strip" id="jobStatus"></div>
      </main>
    </div>
  </div>

  <div class="modal" id="newChatModal">
    <div class="modal-card">
      <h3>Start a new chat</h3>
      <div class="inline">
        <div class="field" style="grid-column:1 / -1;">
          <label for="cwdInput">Working directory</label>
          <input id="cwdInput" type="text" placeholder="C:\\path\\to\\project">
        </div>
        <div class="field"><label>&nbsp;</label><button id="browseDirs">Browse folders</button></div>
        <div class="field"><label for="newNoteInput">Note</label><input id="newNoteInput" type="text" placeholder="Optional note"></div>
        <div class="field"><label for="newModelSelect">Model</label><select id="newModelSelect"></select></div>
        <div class="field"><label for="newApprovalSelect">Approval</label><select id="newApprovalSelect"></select></div>
        <div class="field"><label for="newSandboxSelect">Sandbox</label><select id="newSandboxSelect"></select></div>
        <div class="field"><label for="newReasoningSelect">Reasoning</label><select id="newReasoningSelect"></select></div>
        <div class="field" style="grid-column:1 / -1;">
          <label for="newPromptInput">First message</label>
          <textarea id="newPromptInput" rows="6" placeholder="Describe what you want Codex to do."></textarea>
        </div>
      </div>
      <div class="toolbar" style="justify-content:flex-end; margin-top:14px;">
        <button id="closeNewChat">Close</button>
        <button class="primary" id="createChat">Create</button>
      </div>
    </div>
  </div>

  <div class="modal" id="dirModal">
    <div class="modal-card">
      <h3>Choose a folder</h3>
      <div class="field"><label for="dirPathInput">Current path</label><input id="dirPathInput" type="text"></div>
      <div class="toolbar" style="margin-top:12px;">
        <button id="dirUp">Up</button>
        <button id="dirRefresh">Refresh</button>
        <button class="primary" id="dirUse">Use this folder</button>
      </div>
      <div class="dir-list" id="dirList"></div>
      <div class="toolbar" style="justify-content:flex-end; margin-top:14px;"><button id="dirClose">Close</button></div>
    </div>
  </div>

  <script>
    const state = { token: "", bootstrap: null, selectedSessionId: "", selectedSessionPayload: null };
    const esc = (v) => (v || "").replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;");
    const timeText = (ts) => ts ? new Date(ts * 1000).toLocaleString() : "-";

    async function api(path, options = {}) {
      const headers = new Headers(options.headers || {});
      headers.set("X-Access-Token", state.token);
      if (!headers.has("Content-Type") && options.body) headers.set("Content-Type", "application/json");
      const res = await fetch(path, { ...options, headers });
      if (!res.ok) {
        let msg = res.statusText;
        try { msg = (await res.json()).error || msg; } catch (e) {}
        throw new Error(msg);
      }
      if (res.status === 204) return null;
      return res.json();
    }

    function fillSelect(id, values) {
      document.getElementById(id).innerHTML = values.map((v) => `<option value="${esc(v)}">${esc(v)}</option>`).join("");
    }

    function setStatus(text) {
      document.getElementById("jobStatus").innerHTML = text ? `<div class="pill">${esc(text)}</div>` : "";
    }

    function sessionMessages(payload) {
      return Array.isArray(payload && payload.messages) ? payload.messages : [];
    }

    function lastAssistantMessageKey(payload) {
      const messages = sessionMessages(payload);
      for (let index = messages.length - 1; index >= 0; index -= 1) {
        const message = messages[index];
        if (!message || message.role !== "assistant") continue;
        const text = String(message.text || "").trim();
        if (!text) continue;
        return `${message.ts || 0}:${text}`;
      }
      return "";
    }

    function currentSessionSnapshot() {
      return {
        messageCount: sessionMessages(state.selectedSessionPayload).length,
        lastAssistantKey: lastAssistantMessageKey(state.selectedSessionPayload),
      };
    }

    function hasFreshAssistantReply(payload, snapshot, requireAssistantReply = true) {
      const messages = sessionMessages(payload);
      if (!messages.length) return false;
      const lastMessage = messages[messages.length - 1];
      const countIncreased = messages.length > Number(snapshot && snapshot.messageCount || 0);
      if (!countIncreased) return false;
      if (!requireAssistantReply) return true;
      const currentAssistantKey = lastAssistantMessageKey(payload);
      return Boolean(
        lastMessage &&
        lastMessage.role === "assistant" &&
        String(lastMessage.text || "").trim() &&
        currentAssistantKey &&
        currentAssistantKey !== String(snapshot && snapshot.lastAssistantKey || "")
      );
    }

    async function waitForFinalAssistantMessage(sessionId, snapshot, options = {}) {
      const timeoutMs = Number.isFinite(options.timeoutMs) ? options.timeoutMs : 30000;
      const pollMs = Number.isFinite(options.pollMs) ? options.pollMs : 600;
      const requireAssistantReply = options.requireAssistantReply !== false;
      const startedAt = Date.now();
      let latestPayload = null;
      while (Date.now() - startedAt <= timeoutMs) {
        latestPayload = await api(`/api/sessions/${encodeURIComponent(sessionId)}`);
        if (hasFreshAssistantReply(latestPayload, snapshot, requireAssistantReply)) {
          return { payload: latestPayload, synced: true };
        }
        await new Promise((resolve) => setTimeout(resolve, pollMs));
      }
      if (!latestPayload) {
        latestPayload = await api(`/api/sessions/${encodeURIComponent(sessionId)}`);
      }
      return { payload: latestPayload, synced: false };
    }

    function renderHero() {
      const b = state.bootstrap;
      document.getElementById("heroMeta").innerHTML = `
        <span class="pill">Sessions: ${b.sessions.length}</span>
        <span class="pill">MCP: ${b.mcp.length}</span>
        <span class="pill">Skills: ${b.skills.length}</span>
        <span class="pill">Auth: token protected</span>`;
      const groups = Array.isArray(b.startup_url_groups) ? b.startup_url_groups : [];
      document.getElementById("heroLinks").innerHTML = groups.flatMap((group) =>
        (Array.isArray(group.urls) ? group.urls : []).map((url) =>
          `<a class="pill" href="${esc(url)}" target="_blank" rel="noreferrer">${esc(group.label)}: ${esc(url)}</a>`
        )
      ).join("");
    }

    function renderSessions() {
      const host = document.getElementById("sessionList");
      if (!state.bootstrap.sessions.length) {
        host.innerHTML = '<div class="empty">No sessions found.</div>';
        return;
      }
      host.innerHTML = state.bootstrap.sessions.map((item) => `
        <article class="session-card ${item.session_id === state.selectedSessionId ? "active" : ""}" data-session-id="${item.session_id}">
          <h3>${esc(item.text || item.session_id)}</h3>
          <p>${esc(item.cwd || "-")}</p>
          <div class="session-meta">
            <span class="pill">${timeText(item.ts)}</span>
            <span class="pill">${esc(item.model || DEFAULT_PRIMARY_MODEL)}</span>
          </div>
          ${item.note ? `<div class="note">${esc(item.note)}</div>` : ""}
        </article>`).join("");
      host.querySelectorAll("[data-session-id]").forEach((node) => {
        node.addEventListener("click", () => loadSession(node.dataset.sessionId));
      });
    }

    function renderItems() {
      document.getElementById("mcpList").innerHTML = state.bootstrap.mcp.map((item) => `
        <article class="item-card"><h3>${esc(item.name)}</h3><p>${esc(item.command || "-")}</p><p>Timeout: ${esc(item.timeout || "-")} | Env: ${item.env_count}</p><p>${esc(item.args || "-")}</p></article>`).join("") || '<div class="empty">No MCP items found.</div>';
      document.getElementById("skillList").innerHTML = state.bootstrap.skills.map((item) => `
        <article class="item-card"><h3>${esc(item.name)}</h3><p>${esc(item.summary || "-")}</p><p>${esc(item.path)}</p></article>`).join("") || '<div class="empty">No skill items found.</div>';
    }

    function backendPayload() {
      return (state.bootstrap && state.bootstrap.backend) || {};
    }

    function selectedBackendPreset() {
      const presets = Array.isArray(backendPayload().openai_presets) ? backendPayload().openai_presets : [];
      const selectedId = document.getElementById("backendPresetSelect").value;
      return presets.find((preset) => preset.id === selectedId) || null;
    }

    function renderBackendPanel() {
      const backend = backendPayload();
      const presets = Array.isArray(backend.openai_presets) ? backend.openai_presets : [];
      document.getElementById("backendSummary").textContent = `Mode: ${backend.backend_mode || "-"} | Proxy: ${backend.proxy_summary || "-"} | Protocol: ${backend.openai_protocol || "unverified"} | Models: ${backend.openai_model_count || 0}`;
      document.getElementById("backendModeSelect").value = backend.backend_mode || "codex_auth";
      document.getElementById("backendTokenDir").value = backend.token_dir || "";
      document.getElementById("backendProxyPort").value = backend.proxy_port || 8317;
      document.getElementById("backendOpenAiBaseUrl").value = backend.openai_base_url || "";
      document.getElementById("backendOpenAiApiKey").value = backend.openai_api_key || "";
      document.getElementById("backendProxyPreference").value = backend.proxy_preference || "direct";
      document.getElementById("backendUpstreamProxyUrl").value = backend.upstream_proxy_url || "";
      document.getElementById("backendModelsOnlyValidation").checked = Boolean(backend.models_only_validation);
      const presetOptions = presets.length ? presets : [{ id: "", name: "No presets" }];
      document.getElementById("backendPresetSelect").innerHTML = presetOptions.map((preset) => `<option value="${esc(preset.id || "")}">${esc(preset.name || preset.id || "No presets")}</option>`).join("");
      document.getElementById("backendPresetSelect").value = backend.active_openai_preset_id || "";
      const active = presets.find((preset) => preset.id === (backend.active_openai_preset_id || ""));
      document.getElementById("backendPresetName").value = active ? (active.name || active.id) : "";
      if (active) fillBackendPresetFields(active);
    }

    function fillBackendPresetFields(preset) {
      document.getElementById("backendPresetName").value = preset ? (preset.name || preset.id || "") : "";
      if (preset && preset.openai_base_url) document.getElementById("backendOpenAiBaseUrl").value = preset.openai_base_url;
      document.getElementById("backendOpenAiApiKey").value = preset ? (preset.openai_api_key || "") : "";
      if (preset && preset.proxy_preference) document.getElementById("backendProxyPreference").value = preset.proxy_preference;
      document.getElementById("backendUpstreamProxyUrl").value = preset ? (preset.upstream_proxy_url || "") : "";
      document.getElementById("backendModelsOnlyValidation").checked = Boolean(preset && preset.models_only_validation);
    }

    async function refreshBackendPanel() {
      return refreshBackendModels();
    }

    async function refreshBackendModels() {
      const modelsOnly = document.getElementById("backendModelsOnlyValidation").checked;
      state.bootstrap.backend = await api("/api/backend", {
        method: "POST",
        body: JSON.stringify(backendFormBody({ models_only_validation: modelsOnly }))
      });
      renderBackendPanel();
      setStatus(modelsOnly
        ? "Models loaded without testing a conversation."
        : "Models refreshed and connection validated.");
    }

    function backendFormBody(overrides = {}) {
      return {
        backend_mode: document.getElementById("backendModeSelect").value,
        token_dir: document.getElementById("backendTokenDir").value,
        proxy_port: Number(document.getElementById("backendProxyPort").value || 8317),
        openai_base_url: document.getElementById("backendOpenAiBaseUrl").value,
        openai_api_key: document.getElementById("backendOpenAiApiKey").value,
        openai_model: "",
        preset_id: document.getElementById("backendPresetSelect").value,
        preset_name: document.getElementById("backendPresetName").value,
        proxy_preference: document.getElementById("backendProxyPreference").value,
        upstream_proxy_url: document.getElementById("backendUpstreamProxyUrl").value,
        models_only_validation: document.getElementById("backendModelsOnlyValidation").checked,
        ...overrides,
      };
    }

    async function fetchBackendModelsOnly() {
      document.getElementById("backendModelsOnlyValidation").checked = true;
      return refreshBackendModels();
    }

    async function saveBackendPreset() {
      const body = backendFormBody();
      state.bootstrap.backend = await api("/api/backend", { method: "POST", body: JSON.stringify(body) });
      renderBackendPanel();
      setStatus("Backend preset saved.");
    }

    async function applyBackendPreset() {
      const presetId = document.getElementById("backendPresetSelect").value;
      if (!presetId) return setStatus("Select a backend preset first.");
      state.bootstrap.backend = await api("/api/backend", { method: "POST", body: JSON.stringify(backendFormBody({
        preset_action: "apply",
        preset_id: presetId,
      })) });
      renderBackendPanel();
      await refreshBootstrap();
      setStatus(`Backend preset applied: ${presetId}`);
    }

    async function deleteBackendPreset() {
      const presetId = document.getElementById("backendPresetSelect").value;
      if (!presetId) return setStatus("Select a backend preset first.");
      if (!confirm(`Delete backend preset '${presetId}'?`)) return;
      state.bootstrap.backend = await api("/api/backend", { method: "POST", body: JSON.stringify({ preset_action: "delete", preset_id: presetId }) });
      renderBackendPanel();
      await refreshBootstrap();
      setStatus(`Backend preset deleted: ${presetId}`);
    }

    function applyOptions() {
      fillSelect("modelSelect", state.bootstrap.models);
      fillSelect("approvalSelect", state.bootstrap.approval_options);
      fillSelect("sandboxSelect", state.bootstrap.sandbox_options);
      fillSelect("reasoningSelect", state.bootstrap.reasoning_options || ["default"]);
      fillSelect("newModelSelect", state.bootstrap.models);
      fillSelect("newApprovalSelect", state.bootstrap.approval_options);
      fillSelect("newSandboxSelect", state.bootstrap.sandbox_options);
      fillSelect("newReasoningSelect", state.bootstrap.reasoning_options || ["default"]);
      if (!document.getElementById("cwdInput").value && state.bootstrap.recent_cwds.length) {
        document.getElementById("cwdInput").value = state.bootstrap.recent_cwds[0];
      }
    }

    async function refreshBootstrap(resetSelection = false) {
      state.bootstrap = await api("/api/bootstrap");
      if (resetSelection) state.selectedSessionId = "";
      renderHero();
      renderSessions();
      renderItems();
      applyOptions();
      renderBackendPanel();
      if (!state.selectedSessionId) clearSession();
    }

    function clearSession() {
      document.getElementById("detailHead").innerHTML = "<h2>No session selected</h2><p>Select an existing session from the left, or create a new one from a folder on this machine.</p>";
      document.getElementById("messageList").innerHTML = '<div class="empty">Conversation messages will appear here.</div>';
      document.getElementById("noteBox").hidden = true;
      document.getElementById("composerSettings").hidden = true;
      document.getElementById("composer").hidden = true;
      document.getElementById("noteInput").value = "";
      state.selectedSessionPayload = null;
    }

    function renderSessionPayload(payload, options = {}) {
      state.selectedSessionPayload = payload;
      const item = payload.session;
      if (!item) {
        clearSession();
        return payload;
      }
      document.getElementById("detailHead").innerHTML = `<h2>${esc(item.text || item.session_id)}</h2><p>${esc(item.cwd || "-")}<br>${esc(item.session_id)}<br>Model: ${esc(item.model || DEFAULT_PRIMARY_MODEL)} | Approval: ${esc(item.approval_policy || "-")} | Sandbox: ${esc(item.sandbox_mode || "-")} | Reasoning: ${esc(item.reasoning_effort || "max")}</p>`;
      document.getElementById("noteInput").value = item.note || "";
      document.getElementById("noteBox").hidden = false;
      document.getElementById("composerSettings").hidden = false;
      document.getElementById("composer").hidden = false;
      const list = document.getElementById("messageList");
      list.innerHTML = sessionMessages(payload).map((m) => `<article class="bubble ${m.role}"><div>${esc(m.text)}</div><div class="time">${m.role} | ${timeText(m.ts)}</div></article>`).join("") || '<div class="empty">No messages parsed for this session yet.</div>';
      if (options.scrollToBottom !== false) {
        list.scrollTop = list.scrollHeight;
      }
      return payload;
    }

    async function loadSession(sessionId, options = {}) {
      state.selectedSessionId = sessionId;
      renderSessions();
      const payload = options.payload || await api(`/api/sessions/${encodeURIComponent(sessionId)}`);
      return renderSessionPayload(payload, options);
    }

    async function pollJob(jobId, onDone) {
      const tick = async () => {
        const job = await api(`/api/jobs/${encodeURIComponent(jobId)}`);
        const tail = Array.isArray(job.log_tail) && job.log_tail.length ? "\\n" + job.log_tail.join("\\n") : "";
        if (job.status === "running") {
          setStatus(`Codex is running...${tail}`);
          setTimeout(tick, 1800);
          return;
        }
        if (job.status === "failed") {
          setStatus(`Job failed: ${job.error || "unknown error"}`);
          return;
        }
        await onDone(job);
      };
      await tick();
    }

    async function sendPrompt() {
      const prompt = document.getElementById("promptInput").value.trim();
      if (!prompt || !state.selectedSessionId) return;
      const snapshot = currentSessionSnapshot();
      const result = await api(`/api/sessions/${encodeURIComponent(state.selectedSessionId)}/message`, {
        method: "POST",
        body: JSON.stringify({
          prompt,
          model: document.getElementById("modelSelect").value,
          approval: document.getElementById("approvalSelect").value,
          sandbox: document.getElementById("sandboxSelect").value,
          reasoning_effort: document.getElementById("reasoningSelect").value
        })
      });
      document.getElementById("promptInput").value = "";
      setStatus("Submitting prompt to Codex...");
      await pollJob(result.job_id, async (job) => {
        const sessionId = job.session_id || state.selectedSessionId;
        setStatus("Syncing final reply into chat history...");
        const syncResult = await waitForFinalAssistantMessage(sessionId, snapshot);
        await refreshBootstrap();
        await loadSession(sessionId, { payload: syncResult.payload });
        if (syncResult.synced) {
          setStatus(job.last_message ? `Finished: ${job.last_message.slice(0, 140)}` : "Finished.");
          return;
        }
        setStatus("Final reply is still syncing into chat history...");
      });
    }

    async function saveNote(clear = false) {
      if (!state.selectedSessionId) return;
      if (clear) document.getElementById("noteInput").value = "";
      await api(`/api/sessions/${encodeURIComponent(state.selectedSessionId)}/note`, {
        method: "POST",
        body: JSON.stringify({ note: document.getElementById("noteInput").value })
      });
      await refreshBootstrap();
      await loadSession(state.selectedSessionId);
      setStatus("Note saved.");
    }

    async function deleteSession() {
      if (!state.selectedSessionId) return;
      if (!confirm("Delete this session from local Codex history?")) return;
      await api(`/api/sessions/${encodeURIComponent(state.selectedSessionId)}`, { method: "DELETE" });
      state.selectedSessionId = "";
      await refreshBootstrap(true);
      setStatus("Session deleted.");
    }

    async function restartRemoteComputer() {
      const host = document.getElementById("remoteHost").value.trim();
      const user = document.getElementById("remoteUser").value.trim();
      const password = document.getElementById("remotePassword").value;
      const identityFile = document.getElementById("remoteIdentity").value.trim();
      if (!host || !user) {
        setStatus("Remote restart requires Tailscale host and SSH user.");
        return;
      }
      if (!confirm(`Restart ${user}@${host} now?`)) return;
      setStatus("Sending remote restart command...");
      const result = await api("/api/remote/restart", {
        method: "POST",
        body: JSON.stringify({
          host,
          user,
          password,
          identity_file: identityFile
        })
      });
      setStatus(`Remote restart sent to ${result.user}@${result.host}.`);
      document.getElementById("remotePassword").value = "";
    }

    async function createChat() {
      const openingPrompt = document.getElementById("newPromptInput").value.trim();
      const result = await api("/api/chats", {
        method: "POST",
        body: JSON.stringify({
          cwd: document.getElementById("cwdInput").value,
          prompt: document.getElementById("newPromptInput").value,
          note: document.getElementById("newNoteInput").value,
          model: document.getElementById("newModelSelect").value,
          approval: document.getElementById("newApprovalSelect").value,
          sandbox: document.getElementById("newSandboxSelect").value,
          reasoning_effort: document.getElementById("newReasoningSelect").value
        })
      });
      closeModal("newChatModal");
      setStatus("Creating new chat...");
      await pollJob(result.job_id, async (job) => {
        let syncResult = null;
        if (job.session_id && openingPrompt) {
          setStatus("Syncing final reply into chat history...");
          syncResult = await waitForFinalAssistantMessage(job.session_id, { messageCount: 0, lastAssistantKey: "" });
        }
        await refreshBootstrap(true);
        if (job.session_id) await loadSession(job.session_id, syncResult ? { payload: syncResult.payload } : {});
        if (syncResult && !syncResult.synced) {
          setStatus("Final reply is still syncing into chat history...");
          return;
        }
        setStatus(job.last_message ? `New chat ready: ${job.last_message.slice(0, 140)}` : "New chat ready.");
      });
    }

    async function browseDir(pathValue = "") {
      const query = pathValue ? `?path=${encodeURIComponent(pathValue)}` : "";
      const payload = await api(`/api/fs${query}`);
      document.getElementById("dirPathInput").value = payload.path || "";
      document.getElementById("dirUp").dataset.path = payload.parent || "";
      document.getElementById("dirList").innerHTML = payload.directories.map((item) => `<button class="dir-item" data-path="${esc(item.path)}"><span>${esc(item.name)}</span><span>${esc(item.path)}</span></button>`).join("") || '<div class="empty">No subdirectories found.</div>';
      document.querySelectorAll(".dir-item").forEach((node) => node.addEventListener("click", () => browseDir(node.dataset.path)));
      document.getElementById("dirModal").classList.add("open");
    }

    function closeModal(id) {
      document.getElementById(id).classList.remove("open");
    }

    function bind() {
      document.querySelectorAll("[data-tab]").forEach((node) => node.addEventListener("click", () => {
        const tab = node.dataset.tab;
        document.querySelectorAll("[data-tab]").forEach((btn) => btn.classList.toggle("active", btn.dataset.tab === tab));
        document.querySelectorAll(".section").forEach((section) => section.classList.toggle("active", section.id === `tab-${tab}`));
      }));
      document.getElementById("openNewChat").addEventListener("click", () => document.getElementById("newChatModal").classList.add("open"));
      document.getElementById("closeNewChat").addEventListener("click", () => closeModal("newChatModal"));
      document.getElementById("createChat").addEventListener("click", () => createChat().catch((e) => setStatus(e.message)));
      document.getElementById("browseDirs").addEventListener("click", () => browseDir(document.getElementById("cwdInput").value).catch((e) => setStatus(e.message)));
      document.getElementById("dirRefresh").addEventListener("click", () => browseDir(document.getElementById("dirPathInput").value).catch((e) => setStatus(e.message)));
      document.getElementById("dirUp").addEventListener("click", () => browseDir(document.getElementById("dirUp").dataset.path || "").catch((e) => setStatus(e.message)));
      document.getElementById("dirUse").addEventListener("click", () => {
        document.getElementById("cwdInput").value = document.getElementById("dirPathInput").value;
        closeModal("dirModal");
      });
      document.getElementById("dirClose").addEventListener("click", () => closeModal("dirModal"));
      document.getElementById("refreshSession").addEventListener("click", () => state.selectedSessionId && loadSession(state.selectedSessionId).catch((e) => setStatus(e.message)));
      document.getElementById("saveNote").addEventListener("click", () => saveNote(false).catch((e) => setStatus(e.message)));
      document.getElementById("clearNote").addEventListener("click", () => saveNote(true).catch((e) => setStatus(e.message)));
      document.getElementById("deleteSession").addEventListener("click", () => deleteSession().catch((e) => setStatus(e.message)));
      document.getElementById("sendPrompt").addEventListener("click", () => sendPrompt().catch((e) => setStatus(e.message)));
      document.getElementById("backendPresetSelect").addEventListener("change", () => {
        fillBackendPresetFields(selectedBackendPreset());
      });
      document.getElementById("refreshBackend").addEventListener("click", () => refreshBackendModels().catch((e) => setStatus(e.message)));
      document.getElementById("fetchBackendModelsOnly").addEventListener("click", () => fetchBackendModelsOnly().catch((e) => setStatus(e.message)));
      document.getElementById("saveBackendPreset").addEventListener("click", () => saveBackendPreset().catch((e) => setStatus(e.message)));
      document.getElementById("applyBackendPreset").addEventListener("click", () => applyBackendPreset().catch((e) => setStatus(e.message)));
      document.getElementById("deleteBackendPreset").addEventListener("click", () => deleteBackendPreset().catch((e) => setStatus(e.message)));
      document.getElementById("remoteRestart").addEventListener("click", () => restartRemoteComputer().catch((e) => setStatus(e.message)));
    }

    async function start() {
      const url = new URL(window.location.href);
      state.token = url.searchParams.get("token") || "";
      if (!state.token) {
        document.body.innerHTML = '<div class="app-shell"><section class="conversation-panel" style="min-height:auto; padding:18px;"><h1>Missing token</h1><p>Open the exact URL printed by the server console. It already includes <code>?token=...</code>.</p></section></div>';
        return;
      }
      bind();
      await refreshBootstrap(true);
    }

    start().catch((e) => { document.getElementById("jobStatus").textContent = e.message; });
  </script>
</body>
</html>
"""


class PortalHandler(BaseHTTPRequestHandler):
    server_version = "CodexMobilePortal/0.1"

    @property
    def portal(self) -> PortalService:
        return self.server.portal  # type: ignore[attr-defined]

    def do_GET(self) -> None:
        if self.path == "/" or self.path.startswith("/?"):
            self._send_html(INDEX_HTML)
            return
        if not self._is_authorized():
            self._send_json({"error": "Unauthorized."}, status=HTTPStatus.UNAUTHORIZED)
            return

        parsed = urlparse(self.path)
        if parsed.path == "/downloads":
            self._send_html(self.portal.download_page_html())
            return
        if parsed.path.startswith("/downloads/"):
            file_name = parsed.path.removeprefix("/downloads/").strip()
            file_path = RELEASES_DIR / file_name
            try:
                resolved_file = file_path.resolve(strict=True)
                resolved_root = RELEASES_DIR.resolve(strict=True)
            except OSError:
                self._send_json({"error": "File not found."}, status=HTTPStatus.NOT_FOUND)
                return
            if (
                file_name not in ALLOWED_DOWNLOAD_FILES
                and (not resolved_file.is_file() or not path_is_within_root(resolved_file, resolved_root))
            ):
                self._send_json({"error": "File not found."}, status=HTTPStatus.NOT_FOUND)
                return
            self._send_binary_file(
                file_path=resolved_file,
                content_type=guess_release_file_content_type(resolved_file),
                file_name=file_name,
            )
            return
        if parsed.path.startswith("/files/"):
            share_id = parsed.path.removeprefix("/files/")
            try:
                share = self.portal.resolve_file_share(share_id)
            except FileNotFoundError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
                return
            self._send_binary_file(
                file_path=Path(str(share["path"])),
                content_type=str(share["content_type"]),
                file_name=str(share["file_name"]),
            )
            return
        if parsed.path.startswith("/api/sessions/") and parsed.path.endswith("/owner"):
            session_id = parsed.path.split("/")[3]
            self._send_json({"owner": self.portal.jobs.current_owner(session_id)})
            return
        if parsed.path == "/api/bootstrap":
            self._send_json(self.portal.bootstrap_payload())
            return
        if parsed.path == "/api/accounts":
            self._send_json(self.portal.account_slots_payload())
            return
        if parsed.path == "/api/backend":
            self._send_json(self.portal.backend_status_payload())
            return
        if parsed.path == "/api/proxy-settings":
            self._send_json(self.portal.proxy_settings_payload())
            return
        if parsed.path == "/api/browser/attach":
            query = parse_qs(parsed.query)
            try:
                payload = self.portal.browser_attach_payload(
                    str(query.get("browser", ["edge"])[0]),
                    url_prefix=str(query.get("url_prefix", [""])[0]),
                    hostname=str(query.get("hostname", [""])[0]),
                )
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_json(payload)
            return
        if parsed.path.startswith("/api/sessions/"):
            session_id = parsed.path.removeprefix("/api/sessions/")
            payload = self.portal.session_payload(session_id)
            if payload is None:
                self._send_json({"error": "Session not found."}, status=HTTPStatus.NOT_FOUND)
                return
            self._send_json(payload)
            return
        if parsed.path == "/api/fs":
            path_value = parse_qs(parsed.query).get("path", [""])[0]
            try:
                payload = self.portal.data_store.list_directory(path_value)
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_json(payload)
            return
        if parsed.path.startswith("/api/jobs/"):
            job_id = parsed.path.removeprefix("/api/jobs/")
            job = self.portal.jobs.get_job(job_id)
            if job is None:
                self._send_json({"error": "Job not found."}, status=HTTPStatus.NOT_FOUND)
                return
            self._send_json(job)
            return

        self._send_json({"error": "Not found."}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if not self._is_authorized():
            self._send_json({"error": "Unauthorized."}, status=HTTPStatus.UNAUTHORIZED)
            return

        parsed = urlparse(self.path)
        payload = self._read_json_body()
        browser_action = BROWSER_ACTION_ROUTE_MAP.get(parsed.path)
        if browser_action:
            try:
                result = self.portal.perform_browser_action(
                    browser_name=str(payload.get("browser", "edge")),
                    action=browser_action,
                    url_prefix=str(payload.get("url_prefix", "")),
                    hostname=str(payload.get("hostname", "")),
                    url=str(payload.get("url", "")),
                    expression=str(payload.get("expression", "")),
                    selector=str(payload.get("selector", "")),
                    text=str(payload.get("text", "")),
                    key=str(payload.get("key", "")),
                    timeout_ms=int(payload.get("timeout_ms", 5000)),
                )
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_json(result)
            return
        if parsed.path == "/api/files/share":
            try:
                result = self.portal.create_file_share(
                    session_id=str(payload.get("session_id", "")),
                    raw_path=str(payload.get("path", "")),
                )
            except FileNotFoundError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
                return
            except PermissionError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.FORBIDDEN)
                return
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_json(result, status=HTTPStatus.CREATED)
            return
        if parsed.path == "/api/fs/mkdir":
            path_value = str(payload.get("path", "")).strip()
            try:
                created = self.portal.data_store.create_directory(path_value)
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_json(created)
            return
        if parsed.path.startswith("/api/sessions/") and parsed.path.endswith("/note"):
            session_id = parsed.path.split("/")[3]
            self.portal.data_store.set_note(session_id, str(payload.get("note", "")))
            self._send_json({"ok": True})
            return
        if parsed.path.startswith("/api/sessions/") and parsed.path.endswith("/settings"):
            session_id = parsed.path.split("/")[3]
            try:
                result = self.portal.update_session_settings(
                    session_id=session_id,
                    model=str(payload.get("model", "default")),
                    approval_policy=str(payload.get("approval_policy", "default")),
                    sandbox_mode=str(payload.get("sandbox_mode", "default")),
                    reasoning_effort=str(payload.get("reasoning_effort", DEFAULT_REASONING_EFFORT)),
                )
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_json(result)
            return
        if parsed.path.startswith("/api/sessions/") and parsed.path.endswith("/goal/clear"):
            session_id = parsed.path.split("/")[3]
            try:
                result = self.portal.clear_session_goal_context(session_id)
            except FileNotFoundError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
                return
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_json(result)
            return
        if parsed.path.startswith("/api/sessions/") and parsed.path.endswith("/claim"):
            session_id = parsed.path.split("/")[3]
            try:
                result = self.portal.jobs.claim_session(
                    session_id=session_id,
                    owner_kind=str(payload.get("owner_kind", "mobile")),
                    owner_label=str(payload.get("owner_label", "Mobile")),
                    mode=str(payload.get("mode", "write")),
                    lease_id=str(payload.get("lease_id", "")),
                )
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.CONFLICT)
                return
            self._send_json(result)
            return
        if parsed.path.startswith("/api/sessions/") and parsed.path.endswith("/heartbeat"):
            session_id = parsed.path.split("/")[3]
            try:
                result = self.portal.jobs.heartbeat_session(
                    session_id=session_id,
                    lease_id=str(payload.get("lease_id", "")),
                )
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.CONFLICT)
                return
            self._send_json(result)
            return
        if parsed.path.startswith("/api/sessions/") and parsed.path.endswith("/release"):
            session_id = parsed.path.split("/")[3]
            try:
                result = self.portal.jobs.release_session(
                    session_id=session_id,
                    lease_id=str(payload.get("lease_id", "")),
                )
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.CONFLICT)
                return
            self._send_json(result)
            return
        if parsed.path.startswith("/api/sessions/") and parsed.path.endswith("/message"):
            session_id = parsed.path.split("/")[3]
            try:
                result = self.portal.jobs.start_resume_job(
                    session_id=session_id,
                    prompt=str(payload.get("prompt", "")),
                    model=str(payload.get("model", "default")),
                    sandbox=str(payload.get("sandbox", "default")),
                    approval=str(payload.get("approval", "default")),
                    reasoning_effort=str(payload.get("reasoning_effort", DEFAULT_REASONING_EFFORT)),
                    lease_id=str(payload.get("lease_id", "")),
                    owner_kind=str(payload.get("owner_kind", "mobile")),
                    owner_label=str(payload.get("owner_label", "Mobile")),
                    image_payload=payload.get("image") if isinstance(payload.get("image"), dict) else None,
                )
            except Exception as exc:
                status = HTTPStatus.CONFLICT if "controlled by" in str(exc) or "already running" in str(exc) else HTTPStatus.BAD_REQUEST
                self._send_json({"error": str(exc)}, status=status)
                return
            self._send_json(result, status=HTTPStatus.ACCEPTED)
            return
        if parsed.path.startswith("/api/jobs/") and parsed.path.endswith("/cancel"):
            job_id = parsed.path.split("/")[3]
            try:
                result = self.portal.jobs.cancel_job(job_id)
            except FileNotFoundError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
                return
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.CONFLICT)
                return
            self._send_json(result, status=HTTPStatus.ACCEPTED)
            return
        if parsed.path == "/api/desktop/refresh":
            result = self.portal.request_desktop_refresh(source=str(payload.get("source", "mobile")))
            self._send_json(result, status=HTTPStatus.ACCEPTED)
            return
        if parsed.path.startswith("/api/accounts/") and parsed.path.endswith("/bind"):
            slot_id = parsed.path.split("/")[3]
            try:
                result = self.portal.bind_current_account(slot_id)
            except FileNotFoundError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
                return
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_json(result)
            return
        if parsed.path.startswith("/api/accounts/") and parsed.path.endswith("/login-bind"):
            slot_id = parsed.path.split("/")[3]
            try:
                result = self.portal.login_and_bind_account(slot_id)
            except FileNotFoundError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
                return
            except RuntimeError as exc:
                status = HTTPStatus.CONFLICT if "Stop active replies" in str(exc) else HTTPStatus.BAD_REQUEST
                self._send_json({"error": str(exc)}, status=status)
                return
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_json(result)
            return
        if parsed.path == "/api/accounts/refresh-current":
            try:
                result = self.portal.refresh_current_account()
            except RuntimeError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.CONFLICT)
                return
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_json(result)
            return
        if parsed.path == "/api/accounts":
            try:
                result = self.portal.create_account_slot(str(payload.get("label", "")))
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_json(result, status=HTTPStatus.CREATED)
            return
        if parsed.path == "/api/backend":
            try:
                action = str(payload.get("preset_action", "")).strip()
                if action == "apply":
                    result = self.portal.apply_openai_backend_preset(
                        str(payload.get("preset_id", "")),
                        preset_name=str(payload.get("preset_name", "")),
                        openai_base_url=str(payload.get("openai_base_url", "")),
                        openai_api_key=str(payload.get("openai_api_key", "")),
                        openai_model=str(payload.get("openai_model", "")),
                        openai_protocol=str(payload.get("openai_protocol", "")),
                        proxy_preference=str(payload.get("proxy_preference", "")),
                        upstream_proxy_url=str(payload.get("upstream_proxy_url", "")),
                        models_only_validation=(
                            bool(payload.get("models_only_validation"))
                            if "models_only_validation" in payload
                            else None
                        ),
                    )
                elif action == "delete":
                    result = self.portal.delete_openai_backend_preset(str(payload.get("preset_id", "")))
                else:
                    result = self.portal.update_backend_settings(
                        backend_mode=str(payload.get("backend_mode", token_pool_settings.BACKEND_MODE_CODEX_AUTH)),
                        token_dir=str(payload.get("token_dir", "")),
                        proxy_port=int(payload.get("proxy_port", token_pool_settings.DEFAULT_PROXY_PORT)),
                        openai_base_url=str(payload.get("openai_base_url", "")),
                        openai_api_key=str(payload.get("openai_api_key", "")),
                        openai_model=str(payload.get("openai_model", "")),
                        openai_models=payload.get("openai_models") if isinstance(payload.get("openai_models"), list) else None,
                        preset_id=str(payload.get("preset_id", "")),
                        preset_name=str(payload.get("preset_name", "")),
                        create_new_preset=bool(payload.get("create_new_preset", False)),
                        openai_protocol=str(payload.get("openai_protocol", "")),
                        openai_manual_extra_models=payload.get("openai_manual_extra_models") if isinstance(payload.get("openai_manual_extra_models"), list) else None,
                        proxy_preference=str(payload.get("proxy_preference", "")),
                        upstream_proxy_url=str(payload.get("upstream_proxy_url", "")),
                        models_only_validation=(
                            bool(payload.get("models_only_validation"))
                            if "models_only_validation" in payload
                            else None
                        ),
                    )
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_json(result)
            return
        if parsed.path == "/api/backend/start":
            try:
                result = self.portal.start_backend_proxy()
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_json(result)
            return
        if parsed.path == "/api/backend/stop":
            try:
                result = self.portal.stop_backend_proxy()
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_json(result)
            return
        if parsed.path == "/api/backend/restart":
            try:
                result = self.portal.restart_backend_proxy()
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_json(result)
            return
        if parsed.path == "/api/remote/restart":
            try:
                result = self.portal.restart_remote_computer(
                    host=str(payload.get("host", "")),
                    user=str(payload.get("user", "")),
                    identity_file=str(payload.get("identity_file", "")),
                    password=str(payload.get("password", "")),
                    host_key=str(payload.get("host_key", "")),
                )
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_json(result, status=HTTPStatus.ACCEPTED)
            return
        if parsed.path == "/api/desktop/restart":
            try:
                result = self.portal.restart_local_computer()
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_json(result, status=HTTPStatus.ACCEPTED)
            return
        if parsed.path == "/api/proxy-settings":
            try:
                result = self.portal.update_proxy_settings(
                    proxy_enabled=bool(payload.get("proxy_enabled", DEFAULT_PROXY_ENABLED)),
                    proxy_port=int(payload.get("proxy_port", DEFAULT_PROXY_PORT)),
                )
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_json(result)
            return
        if parsed.path.startswith("/api/accounts/") and parsed.path.endswith("/rename"):
            slot_id = parsed.path.split("/")[3]
            try:
                result = self.portal.rename_account_slot(slot_id, str(payload.get("label", "")))
            except FileNotFoundError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
                return
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_json(result)
            return
        if parsed.path.startswith("/api/accounts/") and parsed.path.endswith("/delete"):
            slot_id = parsed.path.split("/")[3]
            try:
                result = self.portal.delete_account_slot(slot_id)
            except FileNotFoundError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
                return
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_json(result)
            return
        if parsed.path.startswith("/api/accounts/") and parsed.path.endswith("/switch"):
            slot_id = parsed.path.split("/")[3]
            try:
                result = self.portal.switch_account(slot_id)
            except FileNotFoundError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
                return
            except RuntimeError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.CONFLICT)
                return
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_json(result)
            return
        if parsed.path == "/api/chats":
            try:
                result = self.portal.jobs.start_new_chat_job(
                    cwd=str(payload.get("cwd", "")),
                    prompt=str(payload.get("prompt", "")),
                    note=str(payload.get("note", "")),
                    model=str(payload.get("model", "default")),
                    sandbox=str(payload.get("sandbox", "default")),
                    approval=str(payload.get("approval", "default")),
                    reasoning_effort=str(payload.get("reasoning_effort", DEFAULT_REASONING_EFFORT)),
                )
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_json(result, status=HTTPStatus.ACCEPTED)
            return

        self._send_json({"error": "Not found."}, status=HTTPStatus.NOT_FOUND)

    def do_DELETE(self) -> None:
        if not self._is_authorized():
            self._send_json({"error": "Unauthorized."}, status=HTTPStatus.UNAUTHORIZED)
            return

        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/sessions/"):
            session_id = parsed.path.removeprefix("/api/sessions/")
            self.portal.data_store.delete_session(session_id)
            self._send_json({"ok": True})
            return

        self._send_json({"error": "Not found."}, status=HTTPStatus.NOT_FOUND)

    def log_message(self, format_text: str, *args: object) -> None:
        return

    def _is_authorized(self) -> bool:
        header_token = self.headers.get("X-Access-Token", "").strip()
        if tokens_match(header_token, self.portal.token):
            return True
        parsed = urlparse(self.path)
        query_token = parse_qs(parsed.query).get("token", [""])[0].strip()
        if tokens_match(query_token, self.portal.token):
            return True
        return False

    def _read_json_body(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            obj = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return {}
        return obj if isinstance(obj, dict) else {}

    def _send_html(self, content: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, payload: dict[str, object], status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_binary_file(self, file_path: Path, content_type: str, file_name: str) -> None:
        try:
            data = file_path.read_bytes()
        except OSError:
            self._send_json({"error": "File not found."}, status=HTTPStatus.NOT_FOUND)
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition", build_inline_content_disposition(file_name))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a phone-friendly Codex session portal.")
    parser.add_argument("--host", default="0.0.0.0", help="Listen host. Defaults to 0.0.0.0")
    parser.add_argument("--port", type=int, default=8765, help="Listen port. Defaults to 8765")
    parser.add_argument("--token", default="", help="Access token. Random if omitted.")
    parser.add_argument("--token-pool-proxy", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--custom-provider-proxy", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--api-key", default="", help=argparse.SUPPRESS)
    parser.add_argument("--token-dir", default="", help=argparse.SUPPRESS)
    parser.add_argument("--upstream-base-url", default="", help=argparse.SUPPRESS)
    parser.add_argument("--upstream-api-key", default="", help=argparse.SUPPRESS)
    parser.add_argument("--upstream-protocol", default="", help=argparse.SUPPRESS)
    parser.add_argument("--model", action="append", default=[], help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if args.token_pool_proxy:
        proxy_args = [
            "--port",
            str(args.port),
            "--api-key",
            str(args.api_key),
            "--token-dir",
            str(args.token_dir),
        ]
        if str(args.upstream_base_url).strip():
            proxy_args.extend(["--upstream-base-url", str(args.upstream_base_url).strip()])
        return token_pool_proxy.main(proxy_args)
    if args.custom_provider_proxy:
        proxy_args = [
            "--port",
            str(args.port),
            "--api-key",
            str(args.api_key),
            "--upstream-base-url",
            str(args.upstream_base_url).strip(),
            "--upstream-api-key",
            str(args.upstream_api_key),
            "--upstream-protocol",
            str(args.upstream_protocol).strip(),
        ]
        for model_id in args.model:
            proxy_args.extend(["--model", str(model_id)])
        return custom_provider_proxy.main(proxy_args)
    process_singleton.cleanup_previous_project_instances(
        app_dir=APP_DIR,
        markers=("mobile_portal.py",),
    )
    token = resolve_portal_token(args.token)
    portal = PortalService(host=args.host, port=args.port, token=token)
    server = ThreadingHTTPServer((args.host, args.port), PortalHandler)
    server.portal = portal  # type: ignore[attr-defined]
    startup_groups = portal.startup_url_groups()
    has_cross_network = any(
        (label.startswith("Tailscale") or label.startswith("Public")) and urls
        for label, urls in startup_groups
    )

    print(APP_TITLE)
    print(f"Access token: {token}")
    print("Open one of these URLs on your phone browser:")
    for label, urls in startup_groups:
        print(f"{label}:")
        for url in urls:
            print(f"  {url}")
    if not has_cross_network:
        print(
            "Tip: install and sign in to Tailscale on both devices, or add public_urls to "
            f"{PORTAL_SETTINGS_FILE} for Cloudflare/custom cross-network access."
        )
    print("Press Ctrl+C to stop.")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping portal...")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
