import json
import hashlib
import os
import re
import secrets
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib import error as url_error
from urllib import request as url_request


USERPROFILE = Path(os.environ.get('USERPROFILE', ''))
CODEX_HOME = USERPROFILE / '.codex'
DEFAULT_TOKEN_POOL_DIR = USERPROFILE / '.cli-proxy-api'
DEFAULT_SETTINGS_FILE = CODEX_HOME / 'token_pool_settings.json'
DEFAULT_MODELS_CACHE_FILE = CODEX_HOME / 'models_cache.json'
DEFAULT_PROXY_PORT = 8317
CODEX_CONTEXT_WINDOW = 512_000
CODEX_AUTO_COMPACT_TOKEN_LIMIT = 460_000
BACKEND_MODE_CODEX_AUTH = 'codex_auth'
BACKEND_MODE_TOKEN_POOL = 'built_in_token_pool'
BACKEND_MODE_OPENAI_COMPATIBLE = 'openai_compatible'
DEFAULT_OPENAI_BASE_URL = 'https://api.openai.com/v1'
DEFAULT_OPENAI_PRESET_ID = 'default'
DEFAULT_OPENAI_PRESET_NAME = 'Default'
OPENAI_PROTOCOL_RESPONSES = 'responses'
OPENAI_PROTOCOL_CHAT_COMPLETIONS = 'chat_completions'
VALID_OPENAI_PROTOCOLS = {
    '',
    OPENAI_PROTOCOL_RESPONSES,
    OPENAI_PROTOCOL_CHAT_COMPLETIONS,
}
VALID_BACKEND_MODES = {
    BACKEND_MODE_CODEX_AUTH,
    BACKEND_MODE_TOKEN_POOL,
    BACKEND_MODE_OPENAI_COMPATIBLE,
}
MODEL_METADATA_SOURCE_SLUG = 'gpt-5.5'
OPENAI_COMPATIBLE_CODEX_USER_AGENT = 'codex_exec/0.142.5'
OPENAI_COMPATIBLE_CODEX_ORIGINATOR = 'codex_exec'

# Module-level proxy preference set by apply_openai_preset / resolve config.
# Values: 'direct' or 'proxy'. Default to direct so presets are deterministic.
_ACTIVE_PROXY_PREFERENCE = 'direct'


def build_codex_context_override_args() -> list[str]:
    """Apply the shared context and compaction limits to every Codex launch."""
    return [
        '-c',
        f'model_context_window={CODEX_CONTEXT_WINDOW}',
        '-c',
        f'model_auto_compact_token_limit={CODEX_AUTO_COMPACT_TOKEN_LIMIT}',
    ]


def _current_codex_client_version() -> str:
    executable = shutil.which('codex.cmd') or shutil.which('codex')
    if executable:
        try:
            result = subprocess.run(
                [executable, '--version'],
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='ignore',
                timeout=3,
                check=False,
            )
            match = re.search(r'\b\d+\.\d+\.\d+\b', f'{result.stdout}\n{result.stderr}')
            if match:
                return match.group(0)
        except (OSError, subprocess.SubprocessError):
            pass
    return '0.148.0'


def _prepare_codex_models_cache(payload: dict[str, object]) -> bool:
    """Keep the synthetic model catalog readable and fresh for Codex's cache loader."""
    changed = False
    client_version = _current_codex_client_version()
    if payload.get('client_version') != client_version:
        payload['client_version'] = client_version
        changed = True
    if 'etag' not in payload:
        payload['etag'] = None
        changed = True
    if 'fetched_at' not in payload:
        payload['fetched_at'] = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        changed = True
    return changed


def _touch_codex_models_cache(payload: dict[str, object]) -> None:
    payload['fetched_at'] = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def ensure_codex_model_context_metadata(
    model_ids: Iterable[str],
    *,
    models_cache_file: Path = DEFAULT_MODELS_CACHE_FILE,
) -> bool:
    """Keep every cached Codex model aligned with the shared context policy."""
    clean_model_ids = set(_normalize_openai_models([str(model_id).strip() for model_id in model_ids]))
    if not clean_model_ids or not models_cache_file.exists():
        return False
    try:
        payload = json.loads(models_cache_file.read_text(encoding='utf-8'))
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict) or not isinstance(payload.get('models'), list):
        return False

    changed = _prepare_codex_models_cache(payload)
    for model in payload['models']:
        if not isinstance(model, dict):
            continue
        if model.get('context_window') != CODEX_CONTEXT_WINDOW:
            model['context_window'] = CODEX_CONTEXT_WINDOW
            changed = True
        if model.get('max_context_window') != CODEX_CONTEXT_WINDOW:
            model['max_context_window'] = CODEX_CONTEXT_WINDOW
            changed = True
    if not changed:
        return False
    _touch_codex_models_cache(payload)
    try:
        models_cache_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    except OSError:
        return False
    return True


def set_active_proxy_preference(preference: str) -> None:
    """Set the proxy preference for subsequent HTTP requests."""
    global _ACTIVE_PROXY_PREFERENCE
    _ACTIVE_PROXY_PREFERENCE = preference if preference in ('direct', 'proxy', 'auto') else 'direct'


def get_active_proxy_preference() -> str:
    return _ACTIVE_PROXY_PREFERENCE


def effective_openai_proxy_preference(settings: dict[str, object]) -> str:
    top_level = str(settings.get('proxy_preference', '')).strip()
    if top_level in ('direct', 'proxy'):
        return top_level
    active_id = str(settings.get('active_openai_preset_id', '')).strip()
    presets = settings.get('openai_presets', [])
    if isinstance(presets, list) and active_id:
        for preset in presets:
            if not isinstance(preset, dict) or str(preset.get('id', '')).strip() != active_id:
                continue
            preset_preference = str(preset.get('proxy_preference', '')).strip()
            if preset_preference in ('direct', 'proxy'):
                return preset_preference
            break
    return 'direct'


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


def _normalize_openai_protocol(raw_protocol: object) -> str:
    clean_protocol = str(raw_protocol).strip()
    if clean_protocol not in VALID_OPENAI_PROTOCOLS:
        return ''
    return clean_protocol


def normalize_string_map(raw: object) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    normalized: dict[str, str] = {}
    for key, value in raw.items():
        clean_key = str(key).strip()
        clean_value = str(value).strip()
        if clean_key and clean_value:
            normalized[clean_key] = clean_value
    return normalized


def _normalize_string_map(raw: object) -> dict[str, str]:
    return normalize_string_map(raw)


def _openai_compatible_codex_headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    headers = {
        'User-Agent': OPENAI_COMPATIBLE_CODEX_USER_AGENT,
        'originator': OPENAI_COMPATIBLE_CODEX_ORIGINATOR,
    }
    if extra:
        headers.update(extra)
    return headers


def _normalize_openai_preset_id(raw_id: object, fallback: str = DEFAULT_OPENAI_PRESET_ID) -> str:
    clean = str(raw_id).strip()
    if clean:
        return clean
    return fallback


def openai_preset_id_from_name(name: object, fallback: str = DEFAULT_OPENAI_PRESET_ID) -> str:
    raw = str(name or '').strip().lower()
    chars: list[str] = []
    previous_dash = False
    for char in raw:
        if char.isascii() and char.isalnum():
            chars.append(char)
            previous_dash = False
        elif not previous_dash:
            chars.append('-')
            previous_dash = True
    slug = ''.join(chars).strip('-')
    if slug:
        return slug[:64]
    if raw:
        digest = hashlib.sha256(raw.encode('utf-8')).hexdigest()[:10]
        return f'preset-{digest}'
    return fallback


def _normalize_openai_preset(raw: object, fallback_id: str, fallback_name: str) -> dict[str, object]:
    values = raw if isinstance(raw, dict) else {}
    preset_id = _normalize_openai_preset_id(values.get('id', ''), fallback_id)
    name = str(values.get('name', '')).strip() or fallback_name or preset_id
    raw_pref = str(values.get('proxy_preference', '')).strip()
    proxy_preference = raw_pref if raw_pref in ('direct', 'proxy', 'auto') else 'direct'
    upstream_proxy_url = str(values.get('upstream_proxy_url', '')).strip()
    models_only_validation = bool(
        values.get('models_only_validation', values.get('skip_validation', False))
    )
    return {
        'id': preset_id,
        'name': name,
        'openai_base_url': str(values.get('openai_base_url', DEFAULT_OPENAI_BASE_URL)).strip() or DEFAULT_OPENAI_BASE_URL,
        'openai_api_key': str(values.get('openai_api_key', '')).strip(),
        'openai_model': str(values.get('openai_model', '')).strip(),
        'openai_models': _normalize_openai_models(values.get('openai_models', [])),
        'openai_protocol': _normalize_openai_protocol(values.get('openai_protocol', '')),
        'openai_manual_extra_models': _normalize_openai_models(values.get('openai_manual_extra_models', [])),
        'proxy_preference': proxy_preference,
        'upstream_proxy_url': upstream_proxy_url,
        'models_only_validation': models_only_validation,
        'installation_id': str(values.get('installation_id', '')).strip(),
        'claude_env': _normalize_string_map(values.get('claude_env', {})),
        'disable_image_generation': bool(values.get('disable_image_generation', False)),
    }


def _openai_preset_from_payload(
    payload: dict[str, object],
    *,
    preset_id: str = DEFAULT_OPENAI_PRESET_ID,
    name: str = DEFAULT_OPENAI_PRESET_NAME,
) -> dict[str, object]:
    return _normalize_openai_preset(
        {
            'id': preset_id,
            'name': name,
            'openai_base_url': payload.get('openai_base_url', DEFAULT_OPENAI_BASE_URL),
            'openai_api_key': payload.get('openai_api_key', ''),
            'openai_model': payload.get('openai_model', ''),
            'openai_models': payload.get('openai_models', []),
            'openai_protocol': payload.get('openai_protocol', ''),
            'openai_manual_extra_models': payload.get('openai_manual_extra_models', []),
            'upstream_proxy_url': payload.get('upstream_proxy_url', ''),
            'models_only_validation': payload.get(
                'models_only_validation', payload.get('skip_validation', False)
            ),
            'installation_id': payload.get('installation_id', ''),
            'claude_env': payload.get('claude_env', {}),
            'disable_image_generation': payload.get('disable_image_generation', False),
        },
        fallback_id=preset_id,
        fallback_name=name,
    )


def _normalize_openai_presets(raw_presets: object, top_level_preset: dict[str, object]) -> list[dict[str, object]]:
    presets: list[dict[str, object]] = []
    seen: set[str] = set()
    if isinstance(raw_presets, list):
        for index, item in enumerate(raw_presets):
            fallback_id = DEFAULT_OPENAI_PRESET_ID if index == 0 else f'preset-{index + 1}'
            preset = _normalize_openai_preset(item, fallback_id=fallback_id, fallback_name=str(fallback_id))
            preset_id = str(preset.get('id', '')).strip()
            if not preset_id or preset_id in seen:
                continue
            seen.add(preset_id)
            presets.append(preset)
    if not presets:
        return [dict(top_level_preset)]
    return presets


def _find_openai_preset(payload: dict[str, object], preset_id: str) -> dict[str, object] | None:
    clean_id = preset_id.strip()
    presets = payload.get('openai_presets', [])
    if not isinstance(presets, list):
        return None
    for item in presets:
        if isinstance(item, dict) and str(item.get('id', '')).strip() == clean_id:
            return item
    return None


def _copy_openai_preset_to_top_level(payload: dict[str, object], preset: dict[str, object]) -> None:
    payload['openai_base_url'] = str(preset.get('openai_base_url', DEFAULT_OPENAI_BASE_URL)).strip() or DEFAULT_OPENAI_BASE_URL
    payload['openai_api_key'] = str(preset.get('openai_api_key', '')).strip()
    payload['openai_model'] = str(preset.get('openai_model', '')).strip()
    payload['openai_models'] = _normalize_openai_models(preset.get('openai_models', []))
    payload['openai_protocol'] = _normalize_openai_protocol(preset.get('openai_protocol', ''))
    payload['openai_manual_extra_models'] = _normalize_openai_models(preset.get('openai_manual_extra_models', []))
    raw_pref = str(preset.get('proxy_preference', 'direct')).strip()
    payload['proxy_preference'] = raw_pref if raw_pref in ('direct', 'proxy', 'auto') else 'direct'
    payload['upstream_proxy_url'] = str(preset.get('upstream_proxy_url', '')).strip()
    payload['models_only_validation'] = bool(preset.get('models_only_validation', False))
    payload.pop('skip_validation', None)
    payload['installation_id'] = str(preset.get('installation_id', '')).strip()
    payload['claude_env'] = _normalize_string_map(preset.get('claude_env', {}))
    payload['disable_image_generation'] = bool(preset.get('disable_image_generation', False))


def _replace_openai_preset(payload: dict[str, object], preset: dict[str, object]) -> None:
    presets = payload.get('openai_presets', [])
    if not isinstance(presets, list):
        presets = []
    preset_id = str(preset.get('id', '')).strip()
    replaced = False
    clean_presets: list[dict[str, object]] = []
    for item in presets:
        if not isinstance(item, dict):
            continue
        if str(item.get('id', '')).strip() == preset_id:
            clean_presets.append(dict(preset))
            replaced = True
        else:
            clean_presets.append(dict(item))
    if not replaced:
        clean_presets.append(dict(preset))
    payload['openai_presets'] = clean_presets


def _openai_preset_id_exists(payload: dict[str, object], preset_id: str) -> bool:
    return _find_openai_preset(payload, preset_id.strip()) is not None


def _unique_openai_preset_id(payload: dict[str, object], preferred_id: str) -> str:
    base_id = _normalize_openai_preset_id(preferred_id, DEFAULT_OPENAI_PRESET_ID)
    if not _openai_preset_id_exists(payload, base_id):
        return base_id
    for index in range(2, 10000):
        candidate = _normalize_openai_preset_id(f'{base_id}-{index}', f'preset-{index}')
        if not _openai_preset_id_exists(payload, candidate):
            return candidate
    raise ValueError(f'Unable to create a unique OpenAI preset id from: {preferred_id}')


def _sync_openai_presets(
    payload: dict[str, object],
    *,
    raw_presets: object,
    active_openai_preset_id: object,
    active_wins: bool,
) -> dict[str, object]:
    top_level_preset = _openai_preset_from_payload(payload)
    presets = _normalize_openai_presets(raw_presets, top_level_preset)
    active_id = _normalize_openai_preset_id(active_openai_preset_id, str(presets[0].get('id', DEFAULT_OPENAI_PRESET_ID)))
    if all(str(item.get('id', '')).strip() != active_id for item in presets):
        active_id = str(presets[0].get('id', DEFAULT_OPENAI_PRESET_ID)).strip() or DEFAULT_OPENAI_PRESET_ID
    payload['openai_presets'] = presets
    payload['active_openai_preset_id'] = active_id
    active_preset = _find_openai_preset(payload, active_id)
    if active_wins and active_preset is not None:
        _copy_openai_preset_to_top_level(payload, active_preset)
    elif not active_wins:
        existing_name = str(active_preset.get('name', '')).strip() if active_preset is not None else ''
        updated_active = _openai_preset_from_payload(
            payload,
            preset_id=active_id,
            name=existing_name or DEFAULT_OPENAI_PRESET_NAME,
        )
        _replace_openai_preset(payload, updated_active)
    return payload


def _preserve_openai_presets(
    payload: dict[str, object],
    *,
    raw_presets: object,
    active_openai_preset_id: object,
) -> dict[str, object]:
    top_level_preset = _openai_preset_from_payload(payload)
    presets = _normalize_openai_presets(raw_presets, top_level_preset)
    active_id = _normalize_openai_preset_id(active_openai_preset_id, str(presets[0].get('id', DEFAULT_OPENAI_PRESET_ID)))
    if all(str(item.get('id', '')).strip() != active_id for item in presets):
        active_id = str(presets[0].get('id', DEFAULT_OPENAI_PRESET_ID)).strip() or DEFAULT_OPENAI_PRESET_ID
    payload['openai_presets'] = presets
    payload['active_openai_preset_id'] = active_id
    return payload


def _stable_config_fingerprint(*parts: object) -> str:
    digest = hashlib.sha256()
    for part in parts:
        text = "" if part is None else str(part)
        data = text.encode("utf-8")
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def openai_compatible_proxy_config_fingerprint(
    *,
    local_api_key: str,
    upstream_base_url: str,
    upstream_api_key: str,
    upstream_protocol: str,
    model_ids: Iterable[str],
    upstream_proxy_url: str = "",
) -> str:
    clean_protocol = upstream_protocol.strip()
    if clean_protocol not in VALID_OPENAI_PROTOCOLS:
        clean_protocol = ""
    return _stable_config_fingerprint(
        BACKEND_MODE_OPENAI_COMPATIBLE,
        local_api_key.strip(),
        upstream_base_url.strip().rstrip("/"),
        upstream_api_key.strip(),
        clean_protocol or OPENAI_PROTOCOL_RESPONSES,
        upstream_proxy_url.strip(),
        *_normalize_openai_models([str(model_id).strip() for model_id in model_ids if str(model_id).strip()]),
    )


def ensure_openai_compatible_model_metadata(
    model_ids: Iterable[str],
    *,
    models_cache_file: Path = DEFAULT_MODELS_CACHE_FILE,
    source_slug: str = MODEL_METADATA_SOURCE_SLUG,
) -> bool:
    """Add synthetic Codex model metadata for OpenAI-compatible model ids."""
    clean_model_ids = _normalize_openai_models([str(model_id).strip() for model_id in model_ids if str(model_id).strip()])
    if not clean_model_ids or not models_cache_file.exists():
        return False
    try:
        payload = json.loads(models_cache_file.read_text(encoding='utf-8'))
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict):
        return False
    models = payload.get('models')
    if not isinstance(models, list):
        return False

    existing_by_slug = {
        str(model.get('slug', '')).strip(): model
        for model in models
        if isinstance(model, dict) and str(model.get('slug', '')).strip()
    }
    source = next(
        (
            model
            for model in models
            if isinstance(model, dict) and str(model.get('slug', '')).strip() == source_slug
        ),
        None,
    )
    if source is None:
        source = next((model for model in models if isinstance(model, dict) and str(model.get('slug', '')).strip()), None)
    if source is None:
        return False

    changed = _prepare_codex_models_cache(payload)
    for model_id in clean_model_ids:
        existing = existing_by_slug.get(model_id)
        if existing is not None:
            modalities = [str(item).strip() for item in existing.get('input_modalities', []) if str(item).strip()]
            updated_modalities = list(modalities)
            for modality in ('text', 'image'):
                if modality not in updated_modalities:
                    updated_modalities.append(modality)
            if updated_modalities != modalities:
                existing['input_modalities'] = updated_modalities
                changed = True
            if existing.get('context_window') != CODEX_CONTEXT_WINDOW:
                existing['context_window'] = CODEX_CONTEXT_WINDOW
                changed = True
            if existing.get('max_context_window') != CODEX_CONTEXT_WINDOW:
                existing['max_context_window'] = CODEX_CONTEXT_WINDOW
                changed = True
            continue
        cloned = json.loads(json.dumps(source, ensure_ascii=False))
        cloned['slug'] = model_id
        cloned['display_name'] = model_id
        cloned['description'] = 'OpenAI-compatible model routed through the local Codex provider.'
        cloned['visibility'] = 'list'
        cloned['supported_in_api'] = True
        cloned['priority'] = int(cloned.get('priority', 1000) or 1000) + 1000
        cloned['input_modalities'] = ['text', 'image']
        cloned['context_window'] = CODEX_CONTEXT_WINDOW
        cloned['max_context_window'] = CODEX_CONTEXT_WINDOW
        models.append(cloned)
        existing_by_slug[model_id] = cloned
        changed = True
    if not changed:
        return False
    _touch_codex_models_cache(payload)

    try:
        models_cache_file.parent.mkdir(parents=True, exist_ok=True)
        models_cache_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    except OSError:
        return False
    return True


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
    openai_protocol: str,
    openai_manual_extra_models: object = (),
    upstream_proxy_url: str = '',
    models_only_validation: bool = False,
) -> dict[str, object]:
    clean_protocol = _normalize_openai_protocol(openai_protocol)
    return {
        'backend_mode': backend_mode,
        'token_dir': token_dir,
        'proxy_port': int(proxy_port),
        'proxy_api_key': proxy_api_key.strip() or secrets.token_urlsafe(18),
        'openai_base_url': openai_base_url.strip() or DEFAULT_OPENAI_BASE_URL,
        'openai_api_key': openai_api_key.strip(),
        'openai_model': openai_model.strip(),
        'openai_models': _normalize_openai_models(openai_models),
        'openai_protocol': clean_protocol,
        'openai_manual_extra_models': _normalize_openai_models(openai_manual_extra_models),
        'upstream_proxy_url': upstream_proxy_url.strip(),
        'models_only_validation': bool(models_only_validation),
    }


def ensure_token_pool_dir(token_dir: Path = DEFAULT_TOKEN_POOL_DIR) -> Path:
    token_dir.mkdir(parents=True, exist_ok=True)
    return token_dir


def load_backend_settings(
    settings_file: Path = DEFAULT_SETTINGS_FILE,
    *,
    persist_defaults: bool = True,
) -> dict[str, object]:
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
            openai_protocol='',
            models_only_validation=False,
        )

    if settings_file.exists():
        try:
            raw = json.loads(settings_file.read_text(encoding='utf-8-sig'))
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
            payload = _build_backend_payload(
                backend_mode=backend_mode,
                token_dir=token_dir,
                proxy_port=proxy_port,
                proxy_api_key=proxy_api_key,
                openai_base_url=str(raw.get('openai_base_url', DEFAULT_OPENAI_BASE_URL)),
                openai_api_key=str(raw.get('openai_api_key', '')),
                openai_model=str(raw.get('openai_model', '')),
                openai_models=raw.get('openai_models', []),
                openai_protocol=str(raw.get('openai_protocol', '')),
                openai_manual_extra_models=raw.get('openai_manual_extra_models', []),
                upstream_proxy_url=str(raw.get('upstream_proxy_url', '')),
                models_only_validation=bool(
                    raw.get('models_only_validation', raw.get('skip_validation', False))
                ),
            )
            raw_presets = raw.get('openai_presets', [])
            if raw.get('openai_config_detached_from_preset') and raw_presets:
                payload['openai_config_detached_from_preset'] = True
                return _preserve_openai_presets(
                    payload,
                    raw_presets=raw_presets,
                    active_openai_preset_id=raw.get('active_openai_preset_id', DEFAULT_OPENAI_PRESET_ID),
                )
            return _sync_openai_presets(
                payload,
                raw_presets=raw_presets,
                active_openai_preset_id=raw.get('active_openai_preset_id', DEFAULT_OPENAI_PRESET_ID),
                active_wins=bool(raw_presets),
            )
    payload = default_payload()
    _sync_openai_presets(
        payload,
        raw_presets=[],
        active_openai_preset_id=DEFAULT_OPENAI_PRESET_ID,
        active_wins=False,
    )
    if persist_defaults:
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
    openai_protocol: str = '',
    openai_manual_extra_models: object = None,
    upstream_proxy_url: str = '',
    models_only_validation: bool | None = None,
) -> dict[str, object]:
    clean_mode = backend_mode.strip() or BACKEND_MODE_CODEX_AUTH
    if clean_mode not in VALID_BACKEND_MODES:
        raise ValueError(f'Unsupported backend mode: {backend_mode}')
    existing: dict[str, object] = {}
    if settings_file.exists():
        try:
            loaded = json.loads(settings_file.read_text(encoding='utf-8-sig'))
        except (OSError, ValueError, json.JSONDecodeError):
            loaded = {}
        if isinstance(loaded, dict):
            existing = loaded
    if models_only_validation is None:
        raw_validation = existing.get(
            'models_only_validation',
            existing.get('skip_validation'),
        )
        if raw_validation is None:
            active_id = str(existing.get('active_openai_preset_id', '')).strip()
            raw_presets = existing.get('openai_presets', [])
            if active_id and isinstance(raw_presets, list):
                active_preset = next(
                    (
                        item
                        for item in raw_presets
                        if isinstance(item, dict)
                        and str(item.get('id', '')).strip() == active_id
                    ),
                    {},
                )
                raw_validation = active_preset.get(
                    'models_only_validation',
                    active_preset.get('skip_validation', False),
                )
        models_only_validation = bool(raw_validation)
    payload = _build_backend_payload(
        backend_mode=clean_mode,
        token_dir=str(token_dir),
        proxy_port=proxy_port,
        proxy_api_key=proxy_api_key,
        openai_base_url=openai_base_url,
        openai_api_key=openai_api_key,
        openai_model=openai_model,
        openai_models=[] if openai_models is None else openai_models,
        openai_protocol=openai_protocol,
        openai_manual_extra_models=[] if openai_manual_extra_models is None else openai_manual_extra_models,
        upstream_proxy_url=upstream_proxy_url,
        models_only_validation=models_only_validation,
    )
    existing_presets = existing.get('openai_presets', [])
    if isinstance(existing_presets, list) and existing_presets:
        _preserve_openai_presets(
            payload,
            raw_presets=existing_presets,
            active_openai_preset_id=existing.get('active_openai_preset_id', DEFAULT_OPENAI_PRESET_ID),
        )
        payload['openai_config_detached_from_preset'] = True
    else:
        _sync_openai_presets(
            payload,
            raw_presets=[],
            active_openai_preset_id=DEFAULT_OPENAI_PRESET_ID,
            active_wins=False,
        )
        payload['openai_config_detached_from_preset'] = False
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    settings_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return payload


def save_openai_preset(
    *,
    settings_file: Path = DEFAULT_SETTINGS_FILE,
    preset_id: str = '',
    name: str = '',
    openai_base_url: str = DEFAULT_OPENAI_BASE_URL,
    openai_api_key: str = '',
    openai_model: str = '',
    openai_models: object = None,
    openai_protocol: str = '',
    openai_manual_extra_models: object = None,
    proxy_preference: str = '',
    upstream_proxy_url: str = '',
    models_only_validation: bool | None = None,
    skip_validation: bool | None = None,
    installation_id: str = '',
    claude_env: object = None,
    disable_image_generation: bool = False,
    set_active: bool = True,
    create_new: bool = False,
) -> dict[str, object]:
    payload = load_backend_settings(settings_file)
    preferred_id = _normalize_openai_preset_id(preset_id, openai_preset_id_from_name(name))
    clean_id = _unique_openai_preset_id(payload, preferred_id) if create_new else preferred_id

    if models_only_validation is None:
        if skip_validation is not None:
            # Keep the legacy parameter as an explicit compatibility override.
            models_only_validation = bool(skip_validation)
        else:
            existing_preset = _find_openai_preset(payload, clean_id)
            models_only_validation = bool(
                existing_preset.get(
                    'models_only_validation',
                    existing_preset.get('skip_validation', False),
                )
            )

    clean_pref = proxy_preference.strip() if proxy_preference.strip() in ('direct', 'proxy', 'auto') else 'direct'

    preset = _normalize_openai_preset(
        {
            'id': clean_id,
            'name': name or clean_id,
            'openai_base_url': openai_base_url,
            'openai_api_key': openai_api_key,
            'openai_model': openai_model,
            'openai_models': [] if openai_models is None else openai_models,
            'openai_protocol': openai_protocol,
            'openai_manual_extra_models': [] if openai_manual_extra_models is None else openai_manual_extra_models,
            'proxy_preference': clean_pref,
            'upstream_proxy_url': upstream_proxy_url,
            'models_only_validation': models_only_validation,
            'installation_id': installation_id,
            'claude_env': {} if claude_env is None else claude_env,
            'disable_image_generation': disable_image_generation,
        },
        fallback_id=clean_id,
        fallback_name=name or clean_id,
    )
    _replace_openai_preset(payload, preset)
    if set_active:
        payload['active_openai_preset_id'] = clean_id
        _copy_openai_preset_to_top_level(payload, preset)
        payload['openai_config_detached_from_preset'] = False
        # Activate proxy preference for subsequent HTTP requests.
        set_active_proxy_preference(clean_pref)
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    settings_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return payload


def _write_settings_payload_atomically(
    settings_file: Path,
    payload: dict[str, object],
) -> None:
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    temp_file = settings_file.with_name(
        f'{settings_file.name}.{os.getpid()}-{secrets.token_hex(6)}.tmp'
    )
    try:
        temp_file.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding='utf-8',
        )
        os.replace(temp_file, settings_file)
    finally:
        if temp_file.exists():
            temp_file.unlink()


def save_and_activate_openai_preset(
    *,
    settings_file: Path = DEFAULT_SETTINGS_FILE,
    preset_id: str,
    name: str,
    openai_base_url: str,
    openai_api_key: str,
    openai_model: str,
    openai_models: object,
    openai_protocol: str,
    openai_manual_extra_models: object = None,
    proxy_preference: str = 'direct',
    upstream_proxy_url: str = '',
    models_only_validation: bool | None = None,
    skip_validation: bool | None = None,
    installation_id: str = '',
    claude_env: object = None,
    disable_image_generation: bool = False,
) -> dict[str, object]:
    payload = load_backend_settings(settings_file)
    clean_id = _normalize_openai_preset_id(
        preset_id,
        openai_preset_id_from_name(name),
    )
    if models_only_validation is None:
        models_only_validation = bool(skip_validation) if skip_validation is not None else False
    clean_pref = (
        proxy_preference.strip()
        if proxy_preference.strip() in ('direct', 'proxy', 'auto')
        else 'direct'
    )
    preset = _normalize_openai_preset(
        {
            'id': clean_id,
            'name': name or clean_id,
            'openai_base_url': openai_base_url,
            'openai_api_key': openai_api_key,
            'openai_model': openai_model,
            'openai_models': openai_models,
            'openai_protocol': openai_protocol,
            'openai_manual_extra_models': (
                []
                if openai_manual_extra_models is None
                else openai_manual_extra_models
            ),
            'proxy_preference': clean_pref,
            'upstream_proxy_url': upstream_proxy_url,
            'models_only_validation': bool(models_only_validation),
            'installation_id': installation_id,
            'claude_env': {} if claude_env is None else claude_env,
            'disable_image_generation': disable_image_generation,
        },
        fallback_id=clean_id,
        fallback_name=name or clean_id,
    )
    payload['backend_mode'] = BACKEND_MODE_OPENAI_COMPATIBLE
    _replace_openai_preset(payload, preset)
    payload['active_openai_preset_id'] = clean_id
    _copy_openai_preset_to_top_level(payload, preset)
    payload['openai_config_detached_from_preset'] = False
    _write_settings_payload_atomically(settings_file, payload)
    set_active_proxy_preference(clean_pref)
    return payload


def apply_openai_preset(
    preset_id: str,
    *,
    settings_file: Path = DEFAULT_SETTINGS_FILE,
) -> dict[str, object]:
    payload = load_backend_settings(settings_file)
    clean_id = preset_id.strip()
    preset = _find_openai_preset(payload, clean_id)
    if preset is None:
        raise KeyError(f'OpenAI preset not found: {preset_id}')
    payload['active_openai_preset_id'] = clean_id
    _copy_openai_preset_to_top_level(payload, preset)
    payload['openai_config_detached_from_preset'] = False
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    settings_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    # Activate the preset's proxy preference for subsequent HTTP requests.
    set_active_proxy_preference(str(payload.get('proxy_preference', 'direct')))
    return payload


def delete_openai_preset(
    preset_id: str,
    *,
    settings_file: Path = DEFAULT_SETTINGS_FILE,
) -> dict[str, object]:
    payload = load_backend_settings(settings_file)
    clean_id = preset_id.strip()
    presets = [
        dict(item)
        for item in payload.get('openai_presets', [])
        if isinstance(item, dict) and str(item.get('id', '')).strip() != clean_id
    ]
    if not presets:
        blank = _openai_preset_from_payload(
            _build_backend_payload(
                backend_mode=str(payload.get('backend_mode', BACKEND_MODE_CODEX_AUTH)),
                token_dir=str(payload.get('token_dir', DEFAULT_TOKEN_POOL_DIR)),
                proxy_port=int(payload.get('proxy_port', DEFAULT_PROXY_PORT)),
                proxy_api_key=str(payload.get('proxy_api_key', '')),
                openai_base_url=DEFAULT_OPENAI_BASE_URL,
                openai_api_key='',
                openai_model='',
                openai_models=[],
                openai_protocol='',
                openai_manual_extra_models=[],
            )
        )
        presets = [blank]
    payload['openai_presets'] = presets
    active_id = str(payload.get('active_openai_preset_id', '')).strip()
    if active_id == clean_id or all(str(item.get('id', '')).strip() != active_id for item in presets):
        active_id = str(presets[0].get('id', DEFAULT_OPENAI_PRESET_ID)).strip() or DEFAULT_OPENAI_PRESET_ID
    payload['active_openai_preset_id'] = active_id
    active = _find_openai_preset(payload, active_id)
    if active is not None:
        _copy_openai_preset_to_top_level(payload, active)
    payload['openai_config_detached_from_preset'] = False
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    settings_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return payload


def _get_upstream_proxy() -> str | None:
    """Return the first proxy URL found from standard env vars or Windows
    system proxy settings."""
    for key in ('HTTPS_PROXY', 'https_proxy', 'HTTP_PROXY', 'http_proxy', 'ALL_PROXY', 'all_proxy'):
        value = os.environ.get(key, '').strip()
        if value:
            return value
    # Fall back to Windows system proxy (registry).
    if os.name == 'nt':
        server = _read_windows_proxy_from_registry()
        if server:
            return server
    return None


def _read_windows_proxy_from_registry() -> str | None:
    """Read the system HTTP proxy from the Windows registry.
    Returns a proxy URL like 'http://127.0.0.1:7897' when the system
    proxy is enabled, or None otherwise."""
    try:
        import winreg
        key_path = r'Software\Microsoft\Windows\CurrentVersion\Internet Settings'
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as reg_key:
            try:
                enabled, _ = winreg.QueryValueEx(reg_key, 'ProxyEnable')
            except FileNotFoundError:
                enabled = 0
            if not enabled:
                return None
            try:
                server, _ = winreg.QueryValueEx(reg_key, 'ProxyServer')
            except FileNotFoundError:
                return None
            server = str(server).strip()
            if not server:
                return None
            if '://' not in server:
                server = f'http://{server}'
            return server
    except (ImportError, OSError):
        # Registry access failed — try PowerShell as last resort.
        return _read_windows_proxy_via_powershell()


def _read_windows_proxy_via_powershell() -> str | None:
    """Fallback: read the system proxy via PowerShell."""
    try:
        import subprocess
        result = subprocess.run(
            [
                'powershell.exe', '-NoProfile', '-Command',
                "$s = Get-ItemProperty -Path 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings' -ErrorAction SilentlyContinue; "
                "if ($s -and $s.ProxyEnable -eq 1 -and $s.ProxyServer) { Write-Output $s.ProxyServer }",
            ],
            capture_output=True, text=True, timeout=3, creationflags=0x08000000,
        )
        server = (result.stdout or '').strip()
        if server and result.returncode == 0:
            if '://' not in server:
                server = f'http://{server}'
            return server
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def detect_proxy_preference(
    base_url: str,
    api_key: str,
    timeout_seconds: float = 5.0,
) -> str:
    """Auto-detect whether *base_url* is faster via direct connection or proxy.

    Returns 'direct', 'proxy', or 'auto' (when no proxy is available or both
    fail).  Tests by hitting GET /models on the endpoint.
    """
    proxy = _get_upstream_proxy()
    if not proxy:
        return 'direct'  # No proxy available

    clean_url = base_url.strip().rstrip('/')
    test_url = f'{clean_url}/models'
    headers = {
        'Accept': 'application/json',
        'Authorization': f'Bearer {api_key.strip()}',
        'User-Agent': 'codex-session-manager-proxy-detect',
    }

    direct_ok = False
    direct_time = float('inf')
    proxy_ok = False
    proxy_time = float('inf')

    # --- Test direct ---
    import time as _time
    start = _time.monotonic()
    try:
        status, body = _direct_get(test_url, headers, timeout_seconds)
        direct_time = _time.monotonic() - start
        direct_ok = 200 <= status < 400
    except RuntimeError:
        pass

    # --- Test proxy ---
    start = _time.monotonic()
    try:
        status, body = _proxy_get(test_url, headers, timeout_seconds, proxy)
        proxy_time = _time.monotonic() - start
        proxy_ok = 200 <= status < 400
    except RuntimeError:
        pass

    if direct_ok and not proxy_ok:
        return 'direct'
    if proxy_ok and not direct_ok:
        return 'proxy'
    if direct_ok and proxy_ok:
        # Both work — prefer whichever is faster
        return 'direct' if direct_time <= proxy_time else 'proxy'
    # Both failed
    return 'auto'


def _direct_get(url: str, headers: dict[str, str], timeout: float) -> tuple[int, str]:
    request = url_request.Request(url, headers=headers, method='GET')
    opener = url_request.build_opener(url_request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=timeout) as response:
            return int(getattr(response, 'status', response.getcode()) or 200), response.read().decode('utf-8', errors='ignore')
    except url_error.HTTPError as exc:
        return int(getattr(exc, 'code', 500) or 500), exc.read().decode('utf-8', errors='ignore')
    except (OSError, ValueError, url_error.URLError) as exc:
        raise RuntimeError('Failed to connect to the configured endpoint.') from exc


def _proxy_get(url: str, headers: dict[str, str], timeout: float, proxy: str) -> tuple[int, str]:
    try:
        import requests as _requests
        resp = _requests.get(url, headers=headers, timeout=timeout,
                             proxies={'http': proxy, 'https': proxy})
        return resp.status_code, resp.text
    except ImportError:
        raise RuntimeError('Failed to connect to the configured endpoint.')
    except Exception as exc:
        raise RuntimeError('Failed to connect to the configured endpoint.') from exc


def _direct_post(url: str, headers: dict[str, str], payload: bytes, timeout: float) -> tuple[int, str]:
    request = url_request.Request(url, data=payload, headers=headers, method='POST')
    opener = url_request.build_opener(url_request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=timeout) as response:
            return int(getattr(response, 'status', response.getcode()) or 200), response.read().decode('utf-8', errors='ignore')
    except url_error.HTTPError as exc:
        return int(getattr(exc, 'code', 500) or 500), exc.read().decode('utf-8', errors='ignore')
    except (OSError, ValueError, url_error.URLError) as exc:
        raise RuntimeError('Failed to connect to the configured endpoint.') from exc


def _proxy_post(url: str, headers: dict[str, str], payload: bytes, timeout: float, proxy: str) -> tuple[int, str]:
    try:
        import requests as _requests
        resp = _requests.post(url, headers=headers, data=payload, timeout=timeout,
                              proxies={'http': proxy, 'https': proxy})
        return resp.status_code, resp.text
    except ImportError:
        raise RuntimeError('Failed to connect to the configured endpoint.')
    except Exception as exc:
        raise RuntimeError('Failed to connect to the configured endpoint.') from exc


def _http_get(
    url: str,
    headers: dict[str, str],
    timeout: float,
    explicit_proxy: str = '',
) -> tuple[int, str]:
    """Proxy-aware HTTP GET.  Behaviour depends on _ACTIVE_PROXY_PREFERENCE:
    - explicit_proxy: only use this proxy
    - 'auto':  try direct first, fall back to proxy on network errors
    - 'direct': only direct
    - 'proxy': only proxy (if available), fall back to direct"""
    clean_explicit_proxy = explicit_proxy.strip()
    if clean_explicit_proxy:
        return _proxy_get(url, headers, timeout, clean_explicit_proxy)

    pref = get_active_proxy_preference()
    proxy = _get_upstream_proxy() if pref != 'direct' else None

    if pref == 'proxy' and proxy:
        try:
            return _proxy_get(url, headers, timeout, proxy)
        except RuntimeError:
            return _direct_get(url, headers, timeout)
    elif pref == 'direct':
        return _direct_get(url, headers, timeout)
    else:  # auto
        try:
            return _direct_get(url, headers, timeout)
        except RuntimeError:
            if proxy:
                return _proxy_get(url, headers, timeout, proxy)
            raise


def _http_post_json(
    url: str,
    headers: dict[str, str],
    payload: bytes,
    timeout: float,
    explicit_proxy: str = '',
) -> tuple[int, str]:
    """Proxy-aware HTTP POST (JSON).  Behaviour depends on _ACTIVE_PROXY_PREFERENCE:
    - explicit_proxy: only use this proxy
    - 'auto':  try direct first, fall back to proxy on network errors
    - 'direct': only direct
    - 'proxy': only proxy (if available), fall back to direct"""
    clean_explicit_proxy = explicit_proxy.strip()
    if clean_explicit_proxy:
        return _proxy_post(url, headers, payload, timeout, clean_explicit_proxy)

    pref = get_active_proxy_preference()
    proxy = _get_upstream_proxy() if pref != 'direct' else None

    if pref == 'proxy' and proxy:
        try:
            return _proxy_post(url, headers, payload, timeout, proxy)
        except RuntimeError:
            return _direct_post(url, headers, payload, timeout)
    elif pref == 'direct':
        return _direct_post(url, headers, payload, timeout)
    else:  # auto
        try:
            return _direct_post(url, headers, payload, timeout)
        except RuntimeError:
            if proxy:
                return _proxy_post(url, headers, payload, timeout, proxy)
            raise


def _http_get_with_optional_explicit_proxy(
    url: str,
    headers: dict[str, str],
    timeout: float,
    upstream_proxy_url: str = '',
) -> tuple[int, str]:
    if upstream_proxy_url.strip():
        return _http_get(url, headers, timeout, explicit_proxy=upstream_proxy_url)
    return _http_get(url, headers, timeout)


def _http_post_json_with_optional_explicit_proxy(
    url: str,
    headers: dict[str, str],
    payload: bytes,
    timeout: float,
    upstream_proxy_url: str = '',
) -> tuple[int, str]:
    if upstream_proxy_url.strip():
        return _http_post_json(url, headers, payload, timeout, explicit_proxy=upstream_proxy_url)
    return _http_post_json(url, headers, payload, timeout)


def _body_looks_like_json(body: str) -> bool:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return False
    return isinstance(payload, dict)


def _chat_completion_payload_has_text(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    choices = payload.get('choices')
    if not isinstance(choices, list):
        return False
    for raw_choice in choices:
        if not isinstance(raw_choice, dict):
            continue
        message = raw_choice.get('message')
        if isinstance(message, dict) and str(message.get('content', '')).strip():
            return True
        delta = raw_choice.get('delta')
        if isinstance(delta, dict) and str(delta.get('content', '')).strip():
            return True
    return False


def _responses_stream_event_has_output(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    event_type = str(payload.get('type', '')).strip()
    if event_type == 'response.output_text.delta':
        return bool(str(payload.get('delta', '')).strip())
    if event_type == 'response.output_text.done':
        return bool(str(payload.get('text', '')).strip())

    part = payload.get('part')
    if isinstance(part, dict) and str(part.get('text', '')).strip():
        return True

    item = payload.get('item')
    if isinstance(item, dict):
        content = item.get('content')
        if isinstance(content, list):
            for raw_part in content:
                if isinstance(raw_part, dict) and str(raw_part.get('text', '')).strip():
                    return True

    return _chat_completion_payload_has_text(payload)


def _sse_body_looks_like_valid_output(body: str) -> bool:
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line.startswith('data:'):
            continue
        data = line[5:].strip()
        if not data or data == '[DONE]':
            continue
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            continue
        if _responses_stream_event_has_output(payload):
            return True
    return False


def _body_looks_like_valid_responses_output(body: str) -> bool:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return _sse_body_looks_like_valid_output(body)
    if not isinstance(payload, dict):
        return False
    output = payload.get('output')
    if isinstance(output, list) and output:
        return True
    output_text = str(payload.get('output_text', '')).strip()
    return bool(output_text)


def normalize_openai_base_url(
    base_url: str,
    api_key: str,
    timeout_seconds: float = 5.0,
    upstream_proxy_url: str = '',
) -> str:
    """Auto-detect whether *base_url* needs ``/v1`` appended.

    Tries ``GET /models`` on the URL as-is first.  If that fails with a
    non-success status, retries with ``/v1`` appended.  Returns whichever
    form produced a valid response.  Falls back to the original URL (with
    trailing slash stripped) when neither form succeeds.
    """
    clean = base_url.strip().rstrip('/')
    if not clean:
        raise ValueError('Base URL is required.')
    clean_api_key = api_key.strip()
    if not clean_api_key:
        raise ValueError('API key is required.')

    for candidate in (clean, f'{clean}/v1'):
        try:
            status, _body = _http_get_with_optional_explicit_proxy(
                f'{candidate}/models',
                headers=_openai_compatible_codex_headers({
                    'Accept': 'application/json',
                    'Authorization': f'Bearer {clean_api_key}',
                }),
                timeout=timeout_seconds,
                upstream_proxy_url=upstream_proxy_url,
            )
            if 200 <= status < 300 and _body_looks_like_json(_body):
                return candidate
        except (RuntimeError, OSError):
            continue
        except (OSError, ValueError, url_error.URLError):
            continue

    return clean


def _looks_like_stream_required_error(status: int, body: str) -> bool:
    """Return True when *status* / *body* indicate a streaming-only proxy."""
    if status != 400:
        return False
    lower = body.lower()
    return any(keyword in lower for keyword in ('stream', 'must be stream'))


def _looks_like_codex_client_required_error(status: int, body: str) -> bool:
    if status not in (400, 403):
        return False
    lower = body.lower()
    return 'codex_access_restricted' in lower or 'codex cli' in lower or 'codex客户端' in body


def _looks_like_supported_endpoint_runtime_error(status: int, body: str) -> bool:
    if status not in (402, 403, 429):
        return False
    lower = body.lower()
    return any(
        keyword in lower
        for keyword in (
            'insufficient_user_quota',
            'insufficient quota',
            'rate_limit',
            'rate limit',
            'quota',
            '额度不足',
        )
    )


def detect_openai_compatible_protocol(
    base_url: str,
    api_key: str,
    model: str,
    timeout_seconds: float = 8.0,
    upstream_proxy_url: str = '',
    _skip_normalize: bool = False,
) -> tuple[str, str]:
    clean_api_key = api_key.strip()
    clean_model = model.strip()
    if not base_url.strip():
        raise ValueError('Base URL is required.')
    if not clean_api_key:
        raise ValueError('API key is required.')
    if not clean_model:
        raise ValueError('Model is required.')

    # Auto-detect whether the URL needs /v1 appended.
    if _skip_normalize:
        clean_base_url = base_url.strip().rstrip('/')
    else:
        clean_base_url = normalize_openai_base_url(
            base_url,
            clean_api_key,
            timeout_seconds=min(timeout_seconds, 5.0),
            upstream_proxy_url=upstream_proxy_url,
        )

    _FALLBACK_CODES = {400, 404, 405, 501}

    # --- Probe /responses (non-stream first) ---
    responses_error: RuntimeError | None = None
    try:
        responses_status, responses_body = _http_post_json_with_optional_explicit_proxy(
            f'{clean_base_url}/responses',
            headers=_openai_compatible_codex_headers({
                'Accept': 'application/json',
                'Authorization': f'Bearer {clean_api_key}',
                'Content-Type': 'application/json',
            }),
            payload=json.dumps({
                'model': clean_model,
                'input': [{'role': 'user', 'content': 'ping'}],
                'max_output_tokens': 1,
                'stream': False,
            }, ensure_ascii=False).encode('utf-8'),
            timeout=timeout_seconds,
            upstream_proxy_url=upstream_proxy_url,
        )
    except RuntimeError as exc:
        responses_status, responses_body = 0, ''
        responses_error = exc
    if 200 <= responses_status < 300 and _body_looks_like_valid_responses_output(responses_body):
        return OPENAI_PROTOCOL_RESPONSES, clean_base_url
    if 200 <= responses_status < 300:
        try:
            stream_status, stream_body = _http_post_json_with_optional_explicit_proxy(
                f'{clean_base_url}/responses',
                headers=_openai_compatible_codex_headers({
                    'Accept': 'text/event-stream',
                    'Authorization': f'Bearer {clean_api_key}',
                    'Content-Type': 'application/json',
                }),
                payload=json.dumps({
                    'model': clean_model,
                    'input': [{'role': 'user', 'content': 'ping'}],
                    'max_output_tokens': 64,
                    'stream': True,
                }, ensure_ascii=False).encode('utf-8'),
                timeout=timeout_seconds,
                upstream_proxy_url=upstream_proxy_url,
            )
            if 200 <= stream_status < 300 and _body_looks_like_valid_responses_output(stream_body):
                return OPENAI_PROTOCOL_RESPONSES, clean_base_url
        except RuntimeError:
            pass
        responses_status = 404
    if _looks_like_codex_client_required_error(responses_status, responses_body):
        return OPENAI_PROTOCOL_RESPONSES, clean_base_url

    # --- If the proxy requires streaming, retry /responses with stream=True ---
    if _looks_like_stream_required_error(responses_status, responses_body):
        # The proxy explicitly told us it speaks the Responses API (just requires streaming).
        # Even if the stream probe fails (rate limit, model issue, etc.), we should still
        # return OPENAI_PROTOCOL_RESPONSES because the proxy confirmed it supports it.
        try:
            stream_status, stream_body = _http_post_json_with_optional_explicit_proxy(
                f'{clean_base_url}/responses',
                headers=_openai_compatible_codex_headers({
                    'Accept': 'application/json',
                    'Authorization': f'Bearer {clean_api_key}',
                    'Content-Type': 'application/json',
                }),
                payload=json.dumps({
                    'model': clean_model,
                    'input': 'ping',
                    'max_output_tokens': 1,
                    'stream': True,
                }, ensure_ascii=False).encode('utf-8'),
                timeout=timeout_seconds,
                upstream_proxy_url=upstream_proxy_url,
            )
            if 200 <= stream_status < 300:
                return OPENAI_PROTOCOL_RESPONSES, clean_base_url
        except RuntimeError:
            pass
        # Stream probe failed but proxy confirmed it supports Responses API.
        # Return Responses protocol rather than falling back to chat completions.
        return OPENAI_PROTOCOL_RESPONSES, clean_base_url

    if responses_status and responses_status not in _FALLBACK_CODES:
        detail = responses_body.strip()
        if detail:
            raise RuntimeError(f'Failed to validate /responses: HTTP {responses_status} {detail}')
        raise RuntimeError(f'Failed to validate /responses: HTTP {responses_status}.')

    # --- Probe /chat/completions ---
    chat_status, chat_body = _http_post_json_with_optional_explicit_proxy(
        f'{clean_base_url}/chat/completions',
        headers=_openai_compatible_codex_headers({
            'Accept': 'application/json',
            'Authorization': f'Bearer {clean_api_key}',
            'Content-Type': 'application/json',
        }),
        payload=json.dumps({
            'model': clean_model,
            'messages': [{'role': 'user', 'content': 'ping'}],
            'max_tokens': 1,
            'stream': False,
        }, ensure_ascii=False).encode('utf-8'),
        timeout=timeout_seconds,
        upstream_proxy_url=upstream_proxy_url,
    )
    if 200 <= chat_status < 300 and _body_looks_like_json(chat_body):
        return OPENAI_PROTOCOL_CHAT_COMPLETIONS, clean_base_url
    if _looks_like_supported_endpoint_runtime_error(chat_status, chat_body):
        return OPENAI_PROTOCOL_CHAT_COMPLETIONS, clean_base_url
    if chat_status not in _FALLBACK_CODES:
        detail = chat_body.strip()
        if detail:
            raise RuntimeError(f'Failed to validate /chat/completions: HTTP {chat_status} {detail}')
        raise RuntimeError(f'Failed to validate /chat/completions: HTTP {chat_status}.')

    if responses_error is not None:
        raise RuntimeError('This endpoint must support Responses API or Chat Completions API.') from responses_error
    raise RuntimeError('This endpoint must support Responses API or Chat Completions API.')


def resolve_openai_compatible_backend_config(
    base_url: str,
    api_key: str,
    model: str,
    timeout_seconds: float = 8.0,
    upstream_proxy_url: str = '',
) -> dict[str, object]:
    clean_base_url = base_url.strip() or DEFAULT_OPENAI_BASE_URL
    clean_api_key = api_key.strip()
    if not clean_api_key:
        raise ValueError('API key is required.')

    # Auto-detect whether the URL needs /v1 appended.
    clean_base_url = normalize_openai_base_url(
        clean_base_url,
        clean_api_key,
        timeout_seconds=min(timeout_seconds, 5.0),
        upstream_proxy_url=upstream_proxy_url,
    )

    if upstream_proxy_url.strip():
        models = fetch_openai_compatible_models(
            clean_base_url,
            clean_api_key,
            timeout_seconds=timeout_seconds,
            upstream_proxy_url=upstream_proxy_url,
        )
    else:
        models = fetch_openai_compatible_models(
            clean_base_url,
            clean_api_key,
            timeout_seconds=timeout_seconds,
        )
    selected_model = model.strip()
    if selected_model not in models:
        selected_model = models[0]

    # Try protocol detection with the selected model first, then fall back to
    # other models if the first one fails (some proxies only support certain
    # models for specific endpoints).
    protocol: str | None = None
    resolved_url = clean_base_url
    # Prioritize models likely to support /responses (gpt/codex models)
    priority_models = [m for m in models if 'gpt' in m.lower() or 'codex' in m.lower()]
    other_models = [m for m in models if m not in priority_models]
    models_to_try = [selected_model] + [m for m in priority_models + other_models if m != selected_model]
    last_error: Exception | None = None
    # Use shorter timeout per attempt to keep total time reasonable
    per_model_timeout = min(timeout_seconds, 5.0)
    for candidate_model in models_to_try:
        try:
            if upstream_proxy_url.strip():
                protocol, resolved_url = detect_openai_compatible_protocol(
                    clean_base_url,
                    clean_api_key,
                    candidate_model,
                    timeout_seconds=per_model_timeout,
                    upstream_proxy_url=upstream_proxy_url,
                    _skip_normalize=True,
                )
            else:
                protocol, resolved_url = detect_openai_compatible_protocol(
                    clean_base_url,
                    clean_api_key,
                    candidate_model,
                    timeout_seconds=per_model_timeout,
                    _skip_normalize=True,
                )
            break
        except RuntimeError as exc:
            last_error = exc
            continue

    if protocol is None:
        if last_error is not None:
            raise last_error
        raise RuntimeError('This endpoint must support Responses API or Chat Completions API.')

    return {
        'openai_base_url': resolved_url.rstrip('/') or DEFAULT_OPENAI_BASE_URL,
        'openai_api_key': clean_api_key,
        'openai_model': selected_model,
        'openai_models': models,
        'openai_protocol': protocol,
    }


def resolve_openai_compatible_models_only_config(
    base_url: str,
    api_key: str,
    model: str,
    timeout_seconds: float = 8.0,
    upstream_proxy_url: str = '',
) -> dict[str, object]:
    """Resolve an OpenAI-compatible endpoint using only its model catalog.

    This deliberately performs no POST request and does not infer a protocol.
    It is used when a provider permits model discovery but rejects conversation
    probes during preset configuration.
    """
    clean_base_url = base_url.strip() or DEFAULT_OPENAI_BASE_URL
    clean_api_key = api_key.strip()
    if not clean_api_key:
        raise ValueError('API key is required.')

    clean_base_url = normalize_openai_base_url(
        clean_base_url,
        clean_api_key,
        timeout_seconds=min(timeout_seconds, 5.0),
        upstream_proxy_url=upstream_proxy_url,
    )
    fetch_kwargs: dict[str, object] = {'timeout_seconds': timeout_seconds}
    if upstream_proxy_url.strip():
        fetch_kwargs['upstream_proxy_url'] = upstream_proxy_url
    models = fetch_openai_compatible_models(
        clean_base_url,
        clean_api_key,
        **fetch_kwargs,
    )
    if not models:
        raise RuntimeError('No models returned by the configured endpoint.')

    selected_model = model.strip()
    if selected_model not in models:
        selected_model = next(
            (
                preferred
                for preferred in ('gpt-6-astra', 'gpt-5.6-sol')
                if preferred in models
            ),
            models[0],
        )
    return {
        'openai_base_url': clean_base_url.rstrip('/') or DEFAULT_OPENAI_BASE_URL,
        'openai_api_key': clean_api_key,
        'openai_model': selected_model,
        'openai_models': models,
        # The caller must preserve the user's configured protocol.
        'openai_protocol': '',
    }


def fetch_openai_compatible_models(
    base_url: str,
    api_key: str,
    timeout_seconds: float = 8.0,
    upstream_proxy_url: str = '',
) -> list[str]:
    clean_base_url = base_url.strip().rstrip('/')
    clean_api_key = api_key.strip()
    if not clean_base_url:
        raise ValueError('Base URL is required.')
    if not clean_api_key:
        raise ValueError('API key is required.')
    try:
        status, body = _http_get_with_optional_explicit_proxy(
            f'{clean_base_url}/models',
            headers=_openai_compatible_codex_headers({
                'Accept': 'application/json',
                'Authorization': f'Bearer {clean_api_key}',
            }),
            timeout=timeout_seconds,
            upstream_proxy_url=upstream_proxy_url,
        )
    except RuntimeError as exc:
        raise RuntimeError('Failed to fetch models.') from exc
    if not (200 <= status < 300):
        detail = body.strip()
        if detail:
            raise RuntimeError(f'Failed to fetch models: HTTP {status} {detail}')
        raise RuntimeError(f'Failed to fetch models: HTTP {status}.')
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


def _array_from_list_or_map(value: object) -> list[object]:
    if isinstance(value, list):
        return value
    if not isinstance(value, dict):
        return []
    items: list[object] = []
    for key, item in value.items():
        if isinstance(item, dict):
            cloned = dict(item)
            cloned.setdefault('id', key)
            items.append(cloned)
        else:
            items.append(item)
    return items


def _looks_like_sub2api_account(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    credentials = value.get('credentials')
    if isinstance(credentials, dict):
        credential_keys = {
            'access_token',
            'token',
            'api_key',
            'refresh_token',
            'id_token',
            'account_id',
            'chatgpt_account_id',
        }
        return any(str(credentials.get(key, '')).strip() for key in credential_keys)
    return False


def _extract_sub2api_accounts(payload: object) -> list[object]:
    seen: set[int] = set()

    def visit(value: object) -> list[object]:
        if not isinstance(value, (dict, list)):
            return []
        value_id = id(value)
        if value_id in seen:
            return []
        seen.add(value_id)
        if isinstance(value, list):
            if value and any(_looks_like_sub2api_account(item) for item in value):
                return value
            for item in value:
                found = visit(item)
                if found:
                    return found
            return []

        accounts = value.get('accounts')
        account_items = _array_from_list_or_map(accounts)
        if account_items and any(_looks_like_sub2api_account(item) for item in account_items):
            return account_items

        for key in ('data', 'result', 'output', 'account', 'items', 'list', 'files', 'auth_files', 'authFiles'):
            found = visit(value.get(key))
            if found:
                return found
        return []

    return visit(payload)


def _first_clean_string(*values: object) -> str:
    for value in values:
        clean = str(value or '').strip()
        if clean:
            return clean
    return ''


def _sub2api_account_to_token_payload(account: object) -> dict[str, object] | None:
    if not isinstance(account, dict):
        return None
    credentials = account.get('credentials')
    if not isinstance(credentials, dict):
        return None

    access_token = _first_clean_string(
        credentials.get('access_token'),
        credentials.get('token'),
        credentials.get('api_key'),
        account.get('access_token'),
        account.get('token'),
        account.get('api_key'),
    )
    if not access_token:
        return None

    converted: dict[str, object] = {
        key: value
        for key, value in credentials.items()
        if value is not None
    }
    converted['access_token'] = access_token

    refresh_token = _first_clean_string(credentials.get('refresh_token'), account.get('refresh_token'))
    if refresh_token:
        converted['refresh_token'] = refresh_token
    id_token = _first_clean_string(credentials.get('id_token'), account.get('id_token'))
    if id_token:
        converted['id_token'] = id_token

    account_id = _first_clean_string(
        credentials.get('account_id'),
        credentials.get('chatgpt_account_id'),
        account.get('account_id'),
        account.get('chatgpt_account_id'),
        account.get('id'),
    )
    if account_id:
        converted['account_id'] = account_id
        converted.setdefault('chatgpt_account_id', account_id)

    name = _first_clean_string(account.get('name'), credentials.get('name'))
    email = _first_clean_string(account.get('email'), credentials.get('email'))
    if not email and '@' in name:
        email = name
    if email:
        converted['email'] = email
    if name:
        converted['name'] = name

    for key in ('platform', 'type', 'concurrency', 'priority', 'rate_multiplier', 'auto_pause_on_expired'):
        if key in account and account.get(key) is not None:
            converted[key] = account[key]
    converted['source_format'] = 'sub2api'
    return converted


def extract_sub2api_token_payloads(payload: object) -> list[dict[str, object]]:
    accounts = _extract_sub2api_accounts(payload)
    if not accounts:
        return []
    converted: list[dict[str, object]] = []
    for account in accounts:
        token_payload = _sub2api_account_to_token_payload(account)
        if token_payload:
            converted.append(token_payload)
    return converted


def _safe_token_file_stem(value: object, fallback: str) -> str:
    raw = str(value or '').strip() or fallback
    safe_chars: list[str] = []
    for char in raw:
        if char.isalnum() or char in {'-', '_', '.', '@'}:
            safe_chars.append(char)
        else:
            safe_chars.append('_')
    safe = ''.join(safe_chars).strip(' ._')
    while '__' in safe:
        safe = safe.replace('__', '_')
    return (safe or fallback)[:96]


def build_sub2api_token_file_records(source_name: str, payload: object) -> list[tuple[str, dict[str, object]]]:
    source_stem = _safe_token_file_stem(Path(source_name).stem, 'sub2api')
    records: list[tuple[str, dict[str, object]]] = []
    for index, token_payload in enumerate(extract_sub2api_token_payloads(payload), start=1):
        identity = _first_clean_string(
            token_payload.get('email'),
            token_payload.get('name'),
            token_payload.get('account_id'),
            token_payload.get('chatgpt_account_id'),
            f'account-{index:03d}',
        )
        identity_stem = _safe_token_file_stem(identity, f'account-{index:03d}')
        records.append((f'{source_stem}__{index:03d}-{identity_stem}.json', token_payload))
    return records


def _unique_generated_target(target_dir: Path, file_name: str, used_names: set[str]) -> Path:
    stem = Path(file_name).stem
    suffix = Path(file_name).suffix or '.json'
    candidate_name = file_name
    counter = 2
    while candidate_name.lower() in used_names or (target_dir / candidate_name).exists():
        candidate_name = f'{stem}-{counter}{suffix}'
        counter += 1
    used_names.add(candidate_name.lower())
    return target_dir / candidate_name


def import_token_files(source_paths: Iterable[Path], token_dir: Path = DEFAULT_TOKEN_POOL_DIR) -> list[Path]:
    target_dir = ensure_token_pool_dir(token_dir)
    imported: list[Path] = []
    used_generated_names: set[str] = set()
    for source in source_paths:
        candidate = Path(source)
        if not candidate.is_file():
            raise FileNotFoundError(f'Token file not found: {candidate}')
        if candidate.suffix.lower() != '.json':
            raise ValueError(f'Token files must be .json: {candidate.name}')
        try:
            payload = json.loads(candidate.read_text(encoding='utf-8'))
        except (OSError, ValueError, json.JSONDecodeError):
            payload = None
        sub2api_records = build_sub2api_token_file_records(candidate.name, payload) if payload is not None else []
        if sub2api_records:
            for file_name, token_payload in sub2api_records:
                target = _unique_generated_target(target_dir, file_name, used_generated_names)
                target.write_text(json.dumps(token_payload, ensure_ascii=False, indent=2), encoding='utf-8')
                imported.append(target)
            continue
        target = target_dir / candidate.name
        shutil.copy2(candidate, target)
        imported.append(target)
    return imported


def list_token_files(token_dir: Path = DEFAULT_TOKEN_POOL_DIR) -> list[Path]:
    if not token_dir.exists():
        return []
    return sorted(path for path in token_dir.iterdir() if path.is_file() and path.suffix.lower() == '.json')
