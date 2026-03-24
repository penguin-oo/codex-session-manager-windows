import json
import os
import secrets
import shutil
from pathlib import Path
from typing import Iterable


USERPROFILE = Path(os.environ.get('USERPROFILE', ''))
CODEX_HOME = USERPROFILE / '.codex'
DEFAULT_TOKEN_POOL_DIR = USERPROFILE / '.cli-proxy-api'
DEFAULT_SETTINGS_FILE = CODEX_HOME / 'token_pool_settings.json'
DEFAULT_PROXY_PORT = 8317
BACKEND_MODE_CODEX_AUTH = 'codex_auth'
BACKEND_MODE_TOKEN_POOL = 'built_in_token_pool'
VALID_BACKEND_MODES = {BACKEND_MODE_CODEX_AUTH, BACKEND_MODE_TOKEN_POOL}


def ensure_token_pool_dir(token_dir: Path = DEFAULT_TOKEN_POOL_DIR) -> Path:
    token_dir.mkdir(parents=True, exist_ok=True)
    return token_dir


def load_backend_settings(settings_file: Path = DEFAULT_SETTINGS_FILE) -> dict[str, object]:
    def default_payload() -> dict[str, object]:
        return {
            'backend_mode': BACKEND_MODE_CODEX_AUTH,
            'token_dir': str(DEFAULT_TOKEN_POOL_DIR),
            'proxy_port': DEFAULT_PROXY_PORT,
            'proxy_api_key': secrets.token_urlsafe(18),
        }

    if settings_file.exists():
        try:
            raw = json.loads(settings_file.read_text(encoding='utf-8'))
        except (OSError, ValueError, json.JSONDecodeError):
            raw = {}
        if isinstance(raw, dict):
            backend_mode = str(raw.get('backend_mode', BACKEND_MODE_CODEX_AUTH)).strip() or BACKEND_MODE_CODEX_AUTH
            if backend_mode not in VALID_BACKEND_MODES:
                backend_mode = BACKEND_MODE_CODEX_AUTH
            token_dir = str(raw.get('token_dir', DEFAULT_TOKEN_POOL_DIR)).strip() or str(DEFAULT_TOKEN_POOL_DIR)
            try:
                proxy_port = int(raw.get('proxy_port', DEFAULT_PROXY_PORT))
            except (TypeError, ValueError):
                proxy_port = DEFAULT_PROXY_PORT
            proxy_api_key = str(raw.get('proxy_api_key', '')).strip() or secrets.token_urlsafe(18)
            return {
                'backend_mode': backend_mode,
                'token_dir': token_dir,
                'proxy_port': proxy_port,
                'proxy_api_key': proxy_api_key,
            }
    payload = default_payload()
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    settings_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return payload


def save_backend_settings(
    backend_mode: str,
    settings_file: Path = DEFAULT_SETTINGS_FILE,
    token_dir: Path = DEFAULT_TOKEN_POOL_DIR,
    proxy_port: int = DEFAULT_PROXY_PORT,
    proxy_api_key: str = '',
) -> dict[str, object]:
    clean_mode = backend_mode.strip() or BACKEND_MODE_CODEX_AUTH
    if clean_mode not in VALID_BACKEND_MODES:
        raise ValueError(f'Unsupported backend mode: {backend_mode}')
    payload = {
        'backend_mode': clean_mode,
        'token_dir': str(token_dir),
        'proxy_port': int(proxy_port),
        'proxy_api_key': proxy_api_key.strip() or secrets.token_urlsafe(18),
    }
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    settings_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return payload


def import_token_files(source_paths: Iterable[Path], token_dir: Path = DEFAULT_TOKEN_POOL_DIR) -> list[Path]:
    target_dir = ensure_token_pool_dir(token_dir)
    imported: list[Path] = []
    for source in source_paths:
        candidate = Path(source)
        if not candidate.is_file():
            raise FileNotFoundError(f'Token file not found: {candidate}')
        if candidate.suffix.lower() != '.json':
            raise ValueError(f'Token files must be .json: {candidate.name}')
        target = target_dir / candidate.name
        shutil.copy2(candidate, target)
        imported.append(target)
    return imported


def list_token_files(token_dir: Path = DEFAULT_TOKEN_POOL_DIR) -> list[Path]:
    if not token_dir.exists():
        return []
    return sorted(path for path in token_dir.iterdir() if path.is_file() and path.suffix.lower() == '.json')
