import json
import os
import secrets
import shutil
from pathlib import Path
from typing import Iterable
from urllib import error as url_error
from urllib import request as url_request


USERPROFILE = Path(os.environ.get('USERPROFILE', ''))
CODEX_HOME = USERPROFILE / '.codex'
DEFAULT_TOKEN_POOL_DIR = USERPROFILE / '.cli-proxy-api'
DEFAULT_SETTINGS_FILE = CODEX_HOME / 'token_pool_settings.json'
DEFAULT_PROXY_PORT = 8317
BACKEND_MODE_CODEX_AUTH = 'codex_auth'
BACKEND_MODE_TOKEN_POOL = 'built_in_token_pool'
BACKEND_MODE_OPENAI_COMPATIBLE = 'openai_compatible'
DEFAULT_OPENAI_BASE_URL = 'https://api.openai.com/v1'
VALID_BACKEND_MODES = {
    BACKEND_MODE_CODEX_AUTH,
    BACKEND_MODE_TOKEN_POOL,
    BACKEND_MODE_OPENAI_COMPATIBLE,
}


def _normalize_openai_models(raw_models: object) -> list[str]:
    if not isinstance(raw_models, list):
        return []
    unique: list[str] = []
    seen: set[str] = set()
    for item in raw_models:
        clean = str(item).strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        unique.append(clean)
    return unique


def _build_backend_payload(
    *,
    backend_mode: str,
    token_dir: str,
    proxy_port: int,
    proxy_api_key: str,
    openai_base_url: str,
    openai_api_key: str,
    openai_model: str,
    openai_models: object,
) -> dict[str, object]:
    return {
        'backend_mode': backend_mode,
        'token_dir': token_dir,
        'proxy_port': int(proxy_port),
        'proxy_api_key': proxy_api_key.strip() or secrets.token_urlsafe(18),
        'openai_base_url': openai_base_url.strip() or DEFAULT_OPENAI_BASE_URL,
        'openai_api_key': openai_api_key.strip(),
        'openai_model': openai_model.strip(),
        'openai_models': _normalize_openai_models(openai_models),
    }


def ensure_token_pool_dir(token_dir: Path = DEFAULT_TOKEN_POOL_DIR) -> Path:
    token_dir.mkdir(parents=True, exist_ok=True)
    return token_dir


def load_backend_settings(settings_file: Path = DEFAULT_SETTINGS_FILE) -> dict[str, object]:
    def default_payload() -> dict[str, object]:
        return _build_backend_payload(
            backend_mode=BACKEND_MODE_CODEX_AUTH,
            token_dir=str(DEFAULT_TOKEN_POOL_DIR),
            proxy_port=DEFAULT_PROXY_PORT,
            proxy_api_key='',
            openai_base_url=DEFAULT_OPENAI_BASE_URL,
            openai_api_key='',
            openai_model='',
            openai_models=[],
        )

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
            return _build_backend_payload(
                backend_mode=backend_mode,
                token_dir=token_dir,
                proxy_port=proxy_port,
                proxy_api_key=proxy_api_key,
                openai_base_url=str(raw.get('openai_base_url', DEFAULT_OPENAI_BASE_URL)),
                openai_api_key=str(raw.get('openai_api_key', '')),
                openai_model=str(raw.get('openai_model', '')),
                openai_models=raw.get('openai_models', []),
            )
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
    openai_base_url: str = DEFAULT_OPENAI_BASE_URL,
    openai_api_key: str = '',
    openai_model: str = '',
    openai_models: object = None,
) -> dict[str, object]:
    clean_mode = backend_mode.strip() or BACKEND_MODE_CODEX_AUTH
    if clean_mode not in VALID_BACKEND_MODES:
        raise ValueError(f'Unsupported backend mode: {backend_mode}')
    payload = _build_backend_payload(
        backend_mode=clean_mode,
        token_dir=str(token_dir),
        proxy_port=proxy_port,
        proxy_api_key=proxy_api_key,
        openai_base_url=openai_base_url,
        openai_api_key=openai_api_key,
        openai_model=openai_model,
        openai_models=[] if openai_models is None else openai_models,
    )
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    settings_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return payload


def fetch_openai_compatible_models(base_url: str, api_key: str, timeout_seconds: float = 8.0) -> list[str]:
    clean_base_url = base_url.strip().rstrip('/')
    clean_api_key = api_key.strip()
    if not clean_base_url:
        raise ValueError('Base URL is required.')
    if not clean_api_key:
        raise ValueError('API key is required.')
    request = url_request.Request(
        f'{clean_base_url}/models',
        headers={
            'Accept': 'application/json',
            'Authorization': f'Bearer {clean_api_key}',
            'User-Agent': 'codex-session-manager-openai-compatible',
        },
        method='GET',
    )
    try:
        with url_request.urlopen(request, timeout=timeout_seconds) as response:
            body = response.read().decode('utf-8', errors='ignore')
    except url_error.HTTPError as exc:
        detail = exc.read().decode('utf-8', errors='ignore').strip()
        if detail:
            raise RuntimeError(f'Failed to fetch models: HTTP {exc.code} {detail}') from exc
        raise RuntimeError(f'Failed to fetch models: HTTP {exc.code}.') from exc
    except (OSError, ValueError, url_error.URLError) as exc:
        raise RuntimeError('Failed to fetch models.') from exc
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError('Invalid /models response.') from exc
    data = payload.get('data', []) if isinstance(payload, dict) else []
    models = _normalize_openai_models(
        [item.get('id', '') for item in data if isinstance(item, dict)]
    )
    if not models:
        raise RuntimeError('No models returned by the configured endpoint.')
    return models


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
