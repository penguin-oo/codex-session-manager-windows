import base64
import hashlib
import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CODEX_HOME = Path(os.environ.get("USERPROFILE", "")) / ".codex"
AUTH_FILE_NAME = "auth.json"
CAP_SID_FILE_NAME = "cap_sid"
ACCOUNT_SLOTS_DIR = CODEX_HOME / "account_slots"
SLOT_REGISTRY_FILE_NAME = "slots.json"
STANDARD_SLOT_IDS = ("account-a", "account-b")
LEGACY_SLOT_LABELS = {
    "account-a": "Account A",
    "account-b": "Account B",
}


def slot_dir(slot_id: str, slots_dir: Path = ACCOUNT_SLOTS_DIR) -> Path:
    return slots_dir / slot_id


def slot_registry_path(slots_dir: Path = ACCOUNT_SLOTS_DIR) -> Path:
    return slots_dir / SLOT_REGISTRY_FILE_NAME


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _clean_slot_label(label: str, fallback: str = "Account Slot") -> str:
    clean = (label or "").strip()
    return clean or fallback


def _default_slot_label(slot_id: str) -> str:
    if slot_id in LEGACY_SLOT_LABELS:
        return LEGACY_SLOT_LABELS[slot_id]
    return slot_id.replace("-", " ").replace("_", " ").title()


def _normalize_slot_record(raw: dict[str, object], index: int) -> dict[str, str]:
    slot_id = str(raw.get("slot_id", "")).strip()
    if not slot_id:
        raise ValueError("slot_id is required")
    created_at = str(raw.get("created_at", "")).strip() or _utc_now_iso()
    updated_at = str(raw.get("updated_at", "")).strip() or created_at
    sort_order = str(raw.get("sort_order", "")).strip() or str(index)
    return {
        "slot_id": slot_id,
        "label": _clean_slot_label(str(raw.get("label", "")), _default_slot_label(slot_id)),
        "created_at": created_at,
        "updated_at": updated_at,
        "sort_order": sort_order,
    }


def _sort_registry_items(items: list[dict[str, str]]) -> list[dict[str, str]]:
    def sort_key(item: dict[str, str]) -> tuple[int, str]:
        try:
            order = int(item.get("sort_order", "0"))
        except ValueError:
            order = 0
        return (order, item["slot_id"])

    return sorted(items, key=sort_key)


def save_slot_registry(items: list[dict[str, object]], slots_dir: Path = ACCOUNT_SLOTS_DIR) -> list[dict[str, str]]:
    slots_dir.mkdir(parents=True, exist_ok=True)
    normalized = [_normalize_slot_record(item if isinstance(item, dict) else {}, index) for index, item in enumerate(items)]
    normalized = _sort_registry_items(normalized)
    slot_registry_path(slots_dir).write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    return normalized


def _discover_slot_directories(slots_dir: Path) -> list[dict[str, str]]:
    if not slots_dir.exists():
        return []
    discovered: list[dict[str, str]] = []
    preferred_order = {slot_id: index for index, slot_id in enumerate(STANDARD_SLOT_IDS)}
    directories = [item for item in slots_dir.iterdir() if item.is_dir() and (item / AUTH_FILE_NAME).exists()]
    directories.sort(key=lambda item: (preferred_order.get(item.name, 9999), item.name))
    for index, item in enumerate(directories):
        slot_id = item.name
        now = _utc_now_iso()
        discovered.append(
            {
                "slot_id": slot_id,
                "label": _default_slot_label(slot_id),
                "created_at": now,
                "updated_at": now,
                "sort_order": str(index),
            }
        )
    return discovered


def load_slot_registry(slots_dir: Path = ACCOUNT_SLOTS_DIR) -> list[dict[str, str]]:
    registry_path = slot_registry_path(slots_dir)
    if registry_path.exists():
        try:
            raw = json.loads(registry_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            raw = []
        if isinstance(raw, list):
            normalized = []
            for index, item in enumerate(raw):
                if not isinstance(item, dict):
                    continue
                try:
                    normalized.append(_normalize_slot_record(item, index))
                except ValueError:
                    continue
            if normalized:
                return save_slot_registry(normalized, slots_dir=slots_dir)
    discovered = _discover_slot_directories(slots_dir)
    if discovered:
        return save_slot_registry(discovered, slots_dir=slots_dir)
    return []


def _next_dynamic_slot_id(existing_slot_ids: list[str]) -> str:
    used_numbers: set[int] = set()
    for slot_id in existing_slot_ids:
        match = re.fullmatch(r"slot-(\d+)", slot_id)
        if match:
            used_numbers.add(int(match.group(1)))
    next_number = 1
    while next_number in used_numbers:
        next_number += 1
    return f"slot-{next_number}"


def create_account_slot(label: str, slots_dir: Path = ACCOUNT_SLOTS_DIR) -> dict[str, str]:
    items = load_slot_registry(slots_dir=slots_dir)
    slot_id = _next_dynamic_slot_id([item["slot_id"] for item in items])
    timestamp = _utc_now_iso()
    record = {
        "slot_id": slot_id,
        "label": _clean_slot_label(label, "New Account"),
        "created_at": timestamp,
        "updated_at": timestamp,
        "sort_order": str(len(items)),
    }
    items.append(record)
    save_slot_registry(items, slots_dir=slots_dir)
    return record


def rename_account_slot(slot_id: str, label: str, slots_dir: Path = ACCOUNT_SLOTS_DIR) -> dict[str, str]:
    items = load_slot_registry(slots_dir=slots_dir)
    for item in items:
        if item["slot_id"] == slot_id:
            item["label"] = _clean_slot_label(label, item["label"])
            item["updated_at"] = _utc_now_iso()
            save_slot_registry(items, slots_dir=slots_dir)
            return item
    raise FileNotFoundError(f"Account slot '{slot_id}' not found.")


def delete_account_slot(slot_id: str, slots_dir: Path = ACCOUNT_SLOTS_DIR) -> None:
    items = load_slot_registry(slots_dir=slots_dir)
    remaining = [item for item in items if item["slot_id"] != slot_id]
    if len(remaining) == len(items):
        raise FileNotFoundError(f"Account slot '{slot_id}' not found.")
    for index, item in enumerate(remaining):
        item["sort_order"] = str(index)
    save_slot_registry(remaining, slots_dir=slots_dir)
    shutil.rmtree(slot_dir(slot_id, slots_dir), ignore_errors=True)


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
    label = _default_slot_label(slot_id)
    for item in load_slot_registry(slots_dir=slots_dir):
        if item["slot_id"] == slot_id:
            label = item["label"]
            break
    info = read_auth_snapshot(
        slot_dir(slot_id, slots_dir) / AUTH_FILE_NAME,
        slot_dir(slot_id, slots_dir) / CAP_SID_FILE_NAME,
    )
    info["slot_id"] = slot_id
    info["label"] = label
    if not info.get("email"):
        info["email"] = ""
    if not info.get("account_id"):
        info["account_id"] = ""
    return info


def list_account_slots(
    codex_home: Path = CODEX_HOME,
    slots_dir: Path = ACCOUNT_SLOTS_DIR,
) -> list[dict[str, str]]:
    registry = load_slot_registry(slots_dir=slots_dir)
    active_slot = detect_active_slot(codex_home=codex_home, slots_dir=slots_dir)
    items: list[dict[str, str]] = []
    for meta in registry:
        item = get_slot_info(meta["slot_id"], slots_dir=slots_dir)
        item["label"] = meta["label"]
        item["created_at"] = meta["created_at"]
        item["updated_at"] = meta["updated_at"]
        item["sort_order"] = meta["sort_order"]
        item["active"] = "yes" if active_slot == meta["slot_id"] else "no"
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
    registry = load_slot_registry(slots_dir=slots_dir)
    if not any(item["slot_id"] == slot_id for item in registry):
        timestamp = _utc_now_iso()
        registry.append(
            {
                "slot_id": slot_id,
                "label": _default_slot_label(slot_id),
                "created_at": timestamp,
                "updated_at": timestamp,
                "sort_order": str(len(registry)),
            }
        )
    else:
        for item in registry:
            if item["slot_id"] == slot_id:
                item["updated_at"] = _utc_now_iso()
                break
    save_slot_registry(registry, slots_dir=slots_dir)
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
    slot_info = get_slot_info(slot_id, slots_dir=slots_dir)
    info["label"] = slot_info.get("label", _default_slot_label(slot_id))
    return info


def detect_active_slot(
    codex_home: Path = CODEX_HOME,
    slots_dir: Path = ACCOUNT_SLOTS_DIR,
) -> str | None:
    current = current_auth_info(codex_home=codex_home)
    current_fingerprint = current.get("fingerprint", "")
    if not current_fingerprint:
        return None
    for item in load_slot_registry(slots_dir=slots_dir):
        slot_info = get_slot_info(item["slot_id"], slots_dir=slots_dir)
        if slot_info.get("fingerprint") == current_fingerprint:
            return item["slot_id"]
    return None
