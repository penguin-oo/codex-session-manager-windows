import base64
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any


CODEX_HOME = Path(os.environ.get("USERPROFILE", "")) / ".codex"
AUTH_FILE_NAME = "auth.json"
CAP_SID_FILE_NAME = "cap_sid"
ACCOUNT_SLOTS_DIR = CODEX_HOME / "account_slots"
STANDARD_SLOT_IDS = ("account-a", "account-b")


def slot_dir(slot_id: str, slots_dir: Path = ACCOUNT_SLOTS_DIR) -> Path:
    return slots_dir / slot_id


def decode_jwt_payload(token: str) -> dict[str, Any]:
    if not token or "." not in token:
        return {}
    parts = token.split(".")
    if len(parts) < 2 or not parts[1]:
        return {}
    payload = parts[1]
    payload += "=" * ((4 - (len(payload) % 4)) % 4)
    try:
        decoded = base64.urlsafe_b64decode(payload.encode("ascii"))
        data = json.loads(decoded.decode("utf-8"))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _fingerprint_bytes(*chunks: bytes) -> str | None:
    if not chunks or not any(chunks):
        return None
    digest = hashlib.sha256()
    for chunk in chunks:
        digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def read_auth_snapshot(auth_path: Path, cap_sid_path: Path | None = None) -> dict[str, str]:
    if not auth_path.exists():
        return {}
    try:
        raw = auth_path.read_text(encoding="utf-8")
        auth_data = json.loads(raw)
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    if not isinstance(auth_data, dict):
        return {}
    tokens = auth_data.get("tokens", {})
    if not isinstance(tokens, dict):
        tokens = {}
    id_token = str(tokens.get("id_token", ""))
    jwt_payload = decode_jwt_payload(id_token)
    cap_bytes = b""
    if cap_sid_path and cap_sid_path.exists():
        try:
            cap_bytes = cap_sid_path.read_bytes()
        except OSError:
            cap_bytes = b""
    try:
        auth_bytes = auth_path.read_bytes()
    except OSError:
        auth_bytes = b""
    fingerprint = _fingerprint_bytes(auth_bytes, cap_bytes) or ""
    return {
        "auth_mode": str(auth_data.get("auth_mode", "")),
        "account_id": str(tokens.get("account_id", "")),
        "email": str(jwt_payload.get("email", "")),
        "fingerprint": fingerprint,
        "has_cap_sid": "yes" if bool(cap_bytes) else "no",
    }


def current_auth_info(codex_home: Path = CODEX_HOME) -> dict[str, str]:
    return read_auth_snapshot(codex_home / AUTH_FILE_NAME, codex_home / CAP_SID_FILE_NAME)


def get_slot_info(slot_id: str, slots_dir: Path = ACCOUNT_SLOTS_DIR) -> dict[str, str]:
    info = read_auth_snapshot(
        slot_dir(slot_id, slots_dir) / AUTH_FILE_NAME,
        slot_dir(slot_id, slots_dir) / CAP_SID_FILE_NAME,
    )
    info["slot_id"] = slot_id
    if not info.get("email"):
        info["email"] = ""
    if not info.get("account_id"):
        info["account_id"] = ""
    return info


def list_account_slots(
    codex_home: Path = CODEX_HOME,
    slots_dir: Path = ACCOUNT_SLOTS_DIR,
    slot_ids: tuple[str, ...] = STANDARD_SLOT_IDS,
) -> list[dict[str, str]]:
    active_slot = detect_active_slot(codex_home=codex_home, slots_dir=slots_dir, slot_ids=slot_ids)
    items: list[dict[str, str]] = []
    for slot_id in slot_ids:
        item = get_slot_info(slot_id, slots_dir=slots_dir)
        item["active"] = "yes" if active_slot == slot_id else "no"
        items.append(item)
    return items


def save_current_auth_to_slot(
    slot_id: str,
    codex_home: Path = CODEX_HOME,
    slots_dir: Path = ACCOUNT_SLOTS_DIR,
) -> dict[str, str]:
    source_auth = codex_home / AUTH_FILE_NAME
    if not source_auth.exists():
        raise FileNotFoundError(f"Current auth file not found: {source_auth}")
    target_dir = slot_dir(slot_id, slots_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_auth, target_dir / AUTH_FILE_NAME)
    source_cap_sid = codex_home / CAP_SID_FILE_NAME
    target_cap_sid = target_dir / CAP_SID_FILE_NAME
    if source_cap_sid.exists():
        shutil.copy2(source_cap_sid, target_cap_sid)
    elif target_cap_sid.exists():
        target_cap_sid.unlink()
    info = get_slot_info(slot_id, slots_dir=slots_dir)
    info["active"] = "yes" if detect_active_slot(codex_home, slots_dir) == slot_id else "no"
    return info


def switch_to_auth_slot(
    slot_id: str,
    codex_home: Path = CODEX_HOME,
    slots_dir: Path = ACCOUNT_SLOTS_DIR,
) -> dict[str, str]:
    source_dir = slot_dir(slot_id, slots_dir)
    source_auth = source_dir / AUTH_FILE_NAME
    if not source_auth.exists():
        raise FileNotFoundError(f"Saved auth for slot '{slot_id}' not found.")
    codex_home.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_auth, codex_home / AUTH_FILE_NAME)
    source_cap_sid = source_dir / CAP_SID_FILE_NAME
    target_cap_sid = codex_home / CAP_SID_FILE_NAME
    if source_cap_sid.exists():
        shutil.copy2(source_cap_sid, target_cap_sid)
    elif target_cap_sid.exists():
        target_cap_sid.unlink()
    info = current_auth_info(codex_home=codex_home)
    info["slot_id"] = slot_id
    return info


def detect_active_slot(
    codex_home: Path = CODEX_HOME,
    slots_dir: Path = ACCOUNT_SLOTS_DIR,
    slot_ids: tuple[str, ...] = STANDARD_SLOT_IDS,
) -> str | None:
    current = current_auth_info(codex_home=codex_home)
    current_fingerprint = current.get("fingerprint", "")
    if not current_fingerprint:
        return None
    for slot_id in slot_ids:
        slot_info = get_slot_info(slot_id, slots_dir=slots_dir)
        if slot_info.get("fingerprint") == current_fingerprint:
            return slot_id
    return None
