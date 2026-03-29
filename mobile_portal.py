import argparse
import auth_slots
import base64
import controlled_browser
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
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, parse_qsl, quote, urlencode, urlparse, urlsplit, urlunsplit
from urllib import error as url_error
from urllib import request as url_request

import token_pool_proxy
import token_pool_settings

try:
    import tomllib
except ModuleNotFoundError:
    tomllib = None


APP_TITLE = "Codex Mobile Portal"
DEFAULT_PROXY_URL = "socks5h://127.0.0.1:7897"
DEFAULT_NO_PROXY = "localhost,127.0.0.1,::1"
REASONING_EFFORT_OPTIONS = ["default", "low", "medium", "high", "xhigh"]
CODEX_HOME = Path(os.environ.get("USERPROFILE", "")) / ".codex"
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
OWNER_HEARTBEAT_TIMEOUT_SECONDS = 30
PROCESS_EXIT_GRACE_SECONDS = 1.0
PROCESS_STARTUP_NO_OUTPUT_TIMEOUT_SECONDS = 300.0
PROCESS_MAX_RUNTIME_SECONDS = 1800.0
TAILSCALE_WINDOWS_PATH = Path(r"C:\Program Files\Tailscale\tailscale.exe")
FILE_SHARE_TTL_SECONDS = 30 * 60
SUPPORTED_SHARED_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".pdf"}
ALLOWED_DOWNLOAD_FILES = {"codex-mobile-debug.apk", "codex-session-manager-windows-x64.zip"}
DEFAULT_PROXY_ENABLED = True
DEFAULT_PROXY_PORT = 7897
TOKEN_POOL_PROVIDER_NAME = "built_in_token_pool"
TOKEN_POOL_ENV_KEY_NAME = "CODEX_TOKEN_POOL_API_KEY"
INTERNAL_ASSISTANT_PROTOCOL_RE = re.compile(
    r"(?im)^\s*(?:user|assistant)\s+to=(?:functions|multi_tool_use|all|web|shell|commentary)\b.*$"
)
CONTROLLED_BROWSER_DEBUG_URLS = {
    "edge": "http://127.0.0.1:9222",
    "chrome": "http://127.0.0.1:9223",
}


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
            )
        )
    return updated


def copy_message_list(messages: list[dict[str, object]]) -> list[dict[str, object]]:
    return [dict(item) for item in messages]


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
    if model and model != "default":
        args.extend(["-m", model])
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
    if model and model != "default":
        args.extend(["-m", model])
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


def parse_weekly_quota_summary(status_output: str) -> dict[str, str]:
    text = (status_output or "").strip()
    if not text:
        return {"state": "unavailable", "summary": "Quota unavailable"}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if "weekly quota" in line.lower():
            return {"state": "ok", "summary": line}
    first_line = text.splitlines()[0].strip()
    if first_line:
        return {"state": "ok", "summary": first_line}
    return {"state": "unavailable", "summary": "Quota unavailable"}


def read_current_weekly_quota(timeout_seconds: float = 4.0) -> dict[str, str]:
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
                }
    return {"proxy_enabled": DEFAULT_PROXY_ENABLED, "proxy_port": DEFAULT_PROXY_PORT, "public_urls": []}


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
    payload = {
        "proxy_enabled": bool(proxy_enabled),
        "proxy_port": port,
        "public_urls": normalize_public_urls(existing.get("public_urls", []) if public_urls is None else public_urls),
    }
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


def build_backend_override_args(
    backend_settings_file: Path = BACKEND_SETTINGS_FILE,
) -> list[str]:
    settings = token_pool_settings.load_backend_settings(backend_settings_file)
    if settings.get("backend_mode") != token_pool_settings.BACKEND_MODE_TOKEN_POOL:
        return []
    return build_token_pool_provider_override_args(
        proxy_port=int(settings.get("proxy_port", token_pool_settings.DEFAULT_PROXY_PORT)),
        provider_name=TOKEN_POOL_PROVIDER_NAME,
        env_key_name=TOKEN_POOL_ENV_KEY_NAME,
    )


def build_codex_subprocess_env(
    base_env: dict[str, str] | None = None,
    settings_file: Path = PORTAL_SETTINGS_FILE,
    backend_settings_file: Path = BACKEND_SETTINGS_FILE,
) -> dict[str, str]:
    env = apply_proxy_settings_to_env(base_env, load_proxy_settings(settings_file))
    backend_settings = token_pool_settings.load_backend_settings(backend_settings_file)
    if backend_settings.get("backend_mode") == token_pool_settings.BACKEND_MODE_TOKEN_POOL:
        env[TOKEN_POOL_ENV_KEY_NAME] = str(backend_settings.get("proxy_api_key", "")).strip()
    else:
        env.pop(TOKEN_POOL_ENV_KEY_NAME, None)
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
        command = [executable, app_path]
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


def token_pool_proxy_is_healthy(
    port: int,
    timeout_seconds: float = 0.5,
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
    return payload if isinstance(payload, dict) else None


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
    health = token_pool_proxy_is_healthy(port)
    if health:
        return health
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
        health = token_pool_proxy_is_healthy(port)
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
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, check=False)
        except OSError:
            pass
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
        if not SETTINGS_FILE.exists():
            return {}
        try:
            raw = SETTINGS_FILE.read_text(encoding="utf-8-sig", errors="ignore")
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
            for field_name in ("model", "approval_policy", "sandbox_mode", "reasoning_effort"):
                field_value = str(value.get(field_name, "")).strip()
                if field_value:
                    entry[field_name] = field_value
            if entry:
                out[sid] = entry
        return out

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
                if session_id in name and name.endswith(".jsonl"):
                    return str(Path(root) / name)
        return ""

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
                            if str(payload.get("type", "")) == "task_complete":
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
                            if is_duplicate_user_message(seen_user_messages, text, ts):
                                continue
                            flush_pending_assistant()
                            current_turn = {
                                "has_final_answer": False,
                                "last_assistant_text": "",
                                "last_assistant_ts": 0,
                            }
                            messages.append({"role": "user", "ts": ts, "text": text})
                            normalized = normalize_message_text(text)
                            if normalized:
                                seen_user_messages.setdefault(normalized, []).append(ts)
                            continue
                        if role != "assistant":
                            continue
                        if payload.get("phase") != "final_answer":
                            if current_turn is not None:
                                current_turn["last_assistant_text"] = text
                                current_turn["last_assistant_ts"] = ts
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
        if not models:
            models = ["gpt-5.3-codex", "gpt-5"]
        unique: list[str] = []
        seen: set[str] = set()
        for model in models:
            if model not in seen:
                seen.add(model)
                unique.append(model)
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
        with self.lock:
            job = self.jobs.get(clean_job_id)
            if not job:
                raise FileNotFoundError("Job not found.")
            if str(job.get("status", "")) != "running":
                raise RuntimeError("Job is not running.")
            pid = int(job.get("pid", 0) or 0)
            session_id = str(job.get("session_id", ""))
        if pid > 0:
            self._terminate_pid(pid)
        with self.lock:
            job = self.jobs.get(clean_job_id)
            if not job:
                raise FileNotFoundError("Job not found.")
            if str(job.get("status", "")) == "running":
                if not str(job.get("last_message", "")).strip():
                    job["last_message"] = str(job.get("live_text", "")).strip()
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
                    job["last_message"] = last_message or str(job.get("last_message", ""))
                    job["error"] = error
                    job["finished_at"] = now_ts()
            if release_session:
                self.active_sessions.discard(release_session)

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
        ensure_token_pool_backend_ready(
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
        ensure_token_pool_backend_ready(
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
        max_runtime_deadline = started_at + PROCESS_MAX_RUNTIME_SECONDS
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
                if now_mono >= max_runtime_deadline:
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
            detected_session_id, completion_seen = self._handle_codex_event(job_id, event, detected_session_id)
            if completion_seen or completion_deadline > 0.0:
                completion_deadline = time.monotonic() + PROCESS_EXIT_GRACE_SECONDS

        if completion_deadline > 0.0 and not stdout_finished.is_set():
            return_code = self._stop_process_after_grace(process)
        else:
            return_code = process.wait()
        if return_code != 0:
            raise RuntimeError(f"Codex exited with code {return_code}.")
        if not self._job_last_message(job_id):
            raise RuntimeError("Codex exited without completing the turn.")
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

    def _handle_codex_event(self, job_id: str, event: dict[str, object], detected_session_id: str) -> tuple[str, bool]:
        event_type = str(event.get("type", ""))
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
            with self.lock:
                job = self.jobs.get(job_id)
                if job:
                    job["heartbeat_at"] = now_ts()
            return detected_session_id, True

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
                return detected_session_id, True

        text = self._extract_event_text(event)
        if text:
            self._append_live_text(job_id, text)
            with self.lock:
                job = self.jobs.get(job_id)
                if job:
                    job["last_message"] = text
        return detected_session_id, False

    def _extract_event_text(self, event: dict[str, object]) -> str:
        direct_text = str(event.get("text", "")).strip()
        if direct_text:
            return direct_text
        for key in ("item", "payload"):
            item = event.get(key)
            if not isinstance(item, dict):
                continue
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
        if self._job_is_alive_locked(job):
            return
        self.jobs.pop(job_id, None)
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
            result = subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            return result.returncode == 0
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

    def backend_status_payload(self) -> dict[str, object]:
        settings = token_pool_settings.load_backend_settings(self.backend_settings_file)
        token_dir = Path(str(settings.get("token_dir", token_pool_settings.DEFAULT_TOKEN_POOL_DIR)))
        token_count = len(token_pool_settings.list_token_files(token_dir))
        proxy_port = int(settings.get("proxy_port", token_pool_settings.DEFAULT_PROXY_PORT))
        health = token_pool_proxy_is_healthy(proxy_port)
        return {
            "backend_mode": str(settings.get("backend_mode", token_pool_settings.BACKEND_MODE_CODEX_AUTH)),
            "token_dir": str(token_dir),
            "proxy_port": proxy_port,
            "proxy_running": bool(health),
            "proxy_summary": f"http://127.0.0.1:{proxy_port}" if health else "stopped",
            "token_count": token_count,
            "last_error": "",
        }

    def update_backend_settings(self, backend_mode: str, token_dir: str, proxy_port: int) -> dict[str, object]:
        current = token_pool_settings.load_backend_settings(self.backend_settings_file)
        token_dir_path = Path(token_dir.strip() or str(current.get("token_dir", token_pool_settings.DEFAULT_TOKEN_POOL_DIR)))
        updated = token_pool_settings.save_backend_settings(
            backend_mode=backend_mode,
            settings_file=self.backend_settings_file,
            token_dir=token_dir_path,
            proxy_port=proxy_port,
            proxy_api_key=str(current.get("proxy_api_key", "")),
        )
        self.jobs.backend_settings_file = self.backend_settings_file
        return {
            "backend_mode": str(updated.get("backend_mode", token_pool_settings.BACKEND_MODE_CODEX_AUTH)),
            **self.backend_status_payload(),
        }

    def start_backend_proxy(self) -> dict[str, object]:
        start_token_pool_backend(
            backend_settings_file=self.backend_settings_file,
            proxy_settings_file=self.proxy_settings_file,
        )
        return self.backend_status_payload()

    def stop_backend_proxy(self) -> dict[str, object]:
        stop_token_pool_backend()
        return self.backend_status_payload()

    def restart_backend_proxy(self) -> dict[str, object]:
        restart_token_pool_backend(
            backend_settings_file=self.backend_settings_file,
            proxy_settings_file=self.proxy_settings_file,
        )
        return self.backend_status_payload()

    def has_running_jobs(self) -> bool:
        with self.jobs.lock:
            return any(str(job.get("status", "")) == "running" for job in self.jobs.jobs.values())

    def download_page_html(self) -> str:
        token = self.token
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
    a.btn {{ display:inline-block; margin:12px 12px 0 0; padding:12px 16px; border-radius:10px; background:#79e0d4; color:#0b1220; text-decoration:none; font-weight:600; }}
    code {{ background:#0f172a; padding:2px 6px; border-radius:6px; color:#d8e4ff; }}
  </style>
</head>
<body>
  <div class="card">
    <h1>Codex Downloads</h1>
    <p>Download the latest build from this computer over Tailscale.</p>
    <a class="btn" href="/downloads/codex-mobile-debug.apk?token={token}">Download Android APK</a>
    <a class="btn" href="/downloads/codex-session-manager-windows-x64.zip?token={token}">Download Windows ZIP</a>
    <p><code>{RELEASES_DIR}</code></p>
  </div>
</body>
</html>"""

    def bootstrap_payload(self) -> dict[str, object]:
        proxy_summary = current_proxy_summary(self.proxy_settings_file)
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
            "models": ["default", *self.data_store.load_available_models()],
            "approval_options": ["default", "untrusted", "on-request", "never"],
            "sandbox_options": ["default", "read-only", "workspace-write", "danger-full-access"],
            "reasoning_options": list(REASONING_EFFORT_OPTIONS),
            "recent_cwds": self.jobs.list_recent_cwds(),
            "proxy_summary": proxy_summary,
            "startup_url_groups": [{"label": label, "urls": list(urls)} for label, urls in self.startup_url_groups()],
        }

    def session_payload(self, session_id: str) -> dict[str, object] | None:
        payload = self.data_store.session_payload(session_id)
        if payload is None:
            return None
        session = payload.get("session")
        if isinstance(session, dict):
            session["is_replying"] = self.jobs.active_job_for_session(session_id) is not None
        payload["owner"] = self.jobs.current_owner(session_id)
        payload["active_job"] = self.jobs.active_job_for_session(session_id)
        payload["proxy_summary"] = current_proxy_summary(self.proxy_settings_file)
        payload["models"] = ["default", *self.data_store.load_available_models()]
        payload["approval_options"] = ["default", "untrusted", "on-request", "never"]
        payload["sandbox_options"] = ["default", "read-only", "workspace-write", "danger-full-access"]
        payload["reasoning_options"] = list(REASONING_EFFORT_OPTIONS)
        return payload

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
  <title>Codex Mobile Portal</title>
  <style>
    :root {
      --bg: #08111d;
      --panel: rgba(11, 25, 43, 0.88);
      --line: rgba(124, 150, 182, 0.18);
      --text: #edf3fb;
      --muted: #8ba3be;
      --accent: #5dd4c0;
      --danger: #ff7b72;
      --user: #103757;
      --assistant: #0b2238;
      --radius: 20px;
      --font: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      --shadow: 0 20px 40px rgba(0, 0, 0, 0.3);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: var(--font);
      color: var(--text);
      background:
        radial-gradient(circle at top left, rgba(93, 212, 192, 0.18), transparent 28%),
        radial-gradient(circle at top right, rgba(247, 178, 103, 0.14), transparent 24%),
        linear-gradient(180deg, #09111c, #040911 72%);
      min-height: 100vh;
    }
    .shell { max-width: 1240px; margin: 0 auto; padding: 16px; }
    .hero, .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 24px;
      box-shadow: var(--shadow);
    }
    .hero { padding: 18px; margin-bottom: 14px; }
    .hero h1 { margin: 0; font-size: 1.2rem; }
    .hero p { margin: 8px 0 0; color: var(--muted); line-height: 1.5; }
    .meta, .session-meta, .toolbar { display: flex; gap: 8px; flex-wrap: wrap; }
    .meta { margin-top: 12px; }
    .pill {
      padding: 7px 11px;
      border-radius: 999px;
      border: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.04);
      color: var(--muted);
      font-size: 0.84rem;
    }
    a.pill {
      color: var(--text);
      text-decoration: none;
    }
    .layout { display: grid; grid-template-columns: 360px minmax(0, 1fr); gap: 14px; }
    .panel-head {
      padding: 14px 16px;
      border-bottom: 1px solid var(--line);
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 10px;
    }
    .panel-head h2 { margin: 0; font-size: 1rem; }
    button, select, input, textarea {
      font: inherit;
      color: var(--text);
      background: rgba(255, 255, 255, 0.04);
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 10px 12px;
    }
    button.primary {
      background: linear-gradient(135deg, rgba(93, 212, 192, 0.2), rgba(93, 212, 192, 0.06));
      border-color: rgba(93, 212, 192, 0.35);
    }
    button.danger { color: var(--danger); border-color: rgba(255, 123, 114, 0.35); }
    .tabbar button.active {
      background: linear-gradient(135deg, rgba(93, 212, 192, 0.2), rgba(93, 212, 192, 0.06));
      border-color: rgba(93, 212, 192, 0.35);
    }
    .section { display: none; }
    .section.active { display: block; }
    .list, .item-list, .messages { display: grid; gap: 10px; padding: 12px; }
    .list { max-height: calc(100vh - 240px); overflow: auto; }
    .session-card, .item-card {
      padding: 14px;
      border-radius: 18px;
      border: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.03);
    }
    .session-card.active {
      border-color: rgba(93, 212, 192, 0.35);
      background: rgba(93, 212, 192, 0.08);
    }
    .session-card h3, .item-card h3 { margin: 0 0 8px; font-size: 0.95rem; word-break: break-all; }
    .session-card p, .item-card p { margin: 0; color: var(--muted); font-size: 0.85rem; line-height: 1.45; }
    .note { color: #f7b267; margin-top: 8px; font-size: 0.83rem; }
    .detail { display: grid; grid-template-rows: auto auto 1fr auto auto; min-height: calc(100vh - 178px); }
    .detail-head { padding: 16px; border-bottom: 1px solid var(--line); }
    .detail-head h2 { margin: 0; font-size: 1rem; word-break: break-all; }
    .detail-head p { margin: 8px 0 0; color: var(--muted); line-height: 1.45; font-size: 0.88rem; }
    .strip { padding: 12px 16px; border-top: 1px solid var(--line); }
    .field { display: grid; gap: 6px; }
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
      box-shadow: 0 10px 24px rgba(0,0,0,0.2);
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
      background: rgba(8, 18, 30, 0.98);
      border: 1px solid var(--line);
      border-radius: 24px;
      box-shadow: var(--shadow);
      padding: 18px;
    }
    .dir-list { display: grid; gap: 8px; max-height: 300px; overflow: auto; margin-top: 12px; }
    .dir-item {
      text-align: left;
      display: flex;
      justify-content: space-between;
      gap: 10px;
      width: 100%;
    }
    @media (max-width: 920px) {
      .layout { grid-template-columns: 1fr; }
      .detail { min-height: auto; }
      .list { max-height: none; }
      .inline { grid-template-columns: 1fr; }
      .bubble { max-width: 100%; }
    }
  </style>
</head>
<body>
  <div class="shell">
    <section class="hero">
      <h1>Codex Mobile Portal</h1>
      <p>Browse local Codex sessions from your phone and continue them by calling real <code>codex exec resume</code> jobs on this computer.</p>
      <div class="meta" id="heroMeta"></div>
      <div class="meta" id="heroLinks"></div>
    </section>
    <div class="layout">
      <aside class="panel">
        <div class="panel-head">
          <h2>Workspace</h2>
          <div class="tabbar toolbar">
            <button data-tab="sessions" class="active">Sessions</button>
            <button data-tab="mcp">MCP</button>
            <button data-tab="skills">Skills</button>
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
      </aside>
      <main class="panel detail">
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
            <span class="pill">${esc(item.model || "default")}</span>
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
      document.getElementById("detailHead").innerHTML = `<h2>${esc(item.text || item.session_id)}</h2><p>${esc(item.cwd || "-")}<br>${esc(item.session_id)}<br>Model: ${esc(item.model || "default")} | Approval: ${esc(item.approval_policy || "-")} | Sandbox: ${esc(item.sandbox_mode || "-")} | Reasoning: ${esc(item.reasoning_effort || "default")}</p>`;
      document.getElementById("noteInput").value = item.note || "";
      document.getElementById("noteBox").hidden = false;
      document.getElementById("composerSettings").hidden = false;
      document.getElementById("composer").hidden = false;
      const list = document.getElementById("messageList");
      list.innerHTML = sessionMessages(payload).map((m) => `<article class="bubble ${m.role}"><div>${esc(m.text)}</div><div class="time">${m.role} 路 ${timeText(m.ts)}</div></article>`).join("") || '<div class="empty">No messages parsed for this session yet.</div>';
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
    }

    async function start() {
      const url = new URL(window.location.href);
      state.token = url.searchParams.get("token") || "";
      if (!state.token) {
        document.body.innerHTML = '<div class="shell"><section class="hero"><h1>Missing token</h1><p>Open the exact URL printed by the server console. It already includes <code>?token=...</code>.</p></section></div>';
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
            if file_name not in ALLOWED_DOWNLOAD_FILES:
                self._send_json({"error": "File not found."}, status=HTTPStatus.NOT_FOUND)
                return
            file_path = RELEASES_DIR / file_name
            self._send_binary_file(
                file_path=file_path,
                content_type=guess_release_file_content_type(file_path),
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
                    reasoning_effort=str(payload.get("reasoning_effort", "default")),
                )
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
                    reasoning_effort=str(payload.get("reasoning_effort", "default")),
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
                result = self.portal.update_backend_settings(
                    backend_mode=str(payload.get("backend_mode", token_pool_settings.BACKEND_MODE_CODEX_AUTH)),
                    token_dir=str(payload.get("token_dir", "")),
                    proxy_port=int(payload.get("proxy_port", token_pool_settings.DEFAULT_PROXY_PORT)),
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
                    reasoning_effort=str(payload.get("reasoning_effort", "default")),
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
    parser.add_argument("--api-key", default="", help=argparse.SUPPRESS)
    parser.add_argument("--token-dir", default="", help=argparse.SUPPRESS)
    parser.add_argument("--upstream-base-url", default="", help=argparse.SUPPRESS)
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
