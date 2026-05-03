import json
import shutil
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


MAX_RESUMABLE_SESSION_FILE_BYTES = 50 * 1024 * 1024
MAX_HISTORY_SUMMARY_ENTRIES = 12
MAX_HISTORY_ENTRY_CHARS = 500


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _backup_suffix() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _json_line(payload: dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _truncate_text(text: str, limit: int = MAX_HISTORY_ENTRY_CHARS) -> str:
    clean = " ".join(str(text).split())
    if len(clean) <= limit:
        return clean
    return f"{clean[: max(0, limit - 3)]}..."


def recent_history_entries(
    session_id: str,
    history_file: Path,
    *,
    max_entries: int = MAX_HISTORY_SUMMARY_ENTRIES,
) -> list[str]:
    if not history_file.exists() or max_entries <= 0:
        return []
    entries: deque[str] = deque(maxlen=max_entries)
    try:
        with history_file.open("r", encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                try:
                    item = json.loads(line)
                except (ValueError, json.JSONDecodeError):
                    continue
                if not isinstance(item, dict) or str(item.get("session_id", "")).strip() != session_id:
                    continue
                text = _truncate_text(str(item.get("text", "")).strip())
                if text:
                    entries.append(text)
    except OSError:
        return []
    return list(entries)


def _build_summary(entries: Iterable[str], backup_path: Path) -> str:
    lines = [
        "[历史摘要 / compacted because the original rollout exceeded the model context window]",
        "这条会话的原始 rollout 太大，继续恢复会超过模型上下文窗口；程序已先备份原文件，再保留最近历史摘要。",
        f"完整备份文件名：{backup_path.name}",
    ]
    recent = [entry for entry in entries if entry]
    if recent:
        lines.append("最近的用户历史：")
        for entry in recent:
            lines.append(f"- {entry}")
    return "\n".join(lines)


def compact_oversized_session_file(
    session_id: str,
    session_file: Path,
    history_file: Path,
    *,
    max_bytes: int = MAX_RESUMABLE_SESSION_FILE_BYTES,
) -> Path | None:
    path = Path(session_file)
    if not session_id or not path.exists():
        return None
    try:
        if path.stat().st_size <= max_bytes:
            return None
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            first_line = handle.readline().rstrip("\n")
    except OSError:
        return None
    if not first_line:
        return None
    try:
        first_item = json.loads(first_line)
    except (ValueError, json.JSONDecodeError):
        return None
    if (
        not isinstance(first_item, dict)
        or first_item.get("type") != "session_meta"
        or str(first_item.get("payload", {}).get("id", "")).strip() != session_id
    ):
        return None

    backup_path = path.with_name(f"{path.name}.context-overflow-backup-{_backup_suffix()}.jsonl")
    try:
        shutil.copy2(path, backup_path)
    except OSError:
        return None

    entries = recent_history_entries(session_id, Path(history_file))
    now = _utc_timestamp()
    lines = [
        first_line,
        _json_line(
            {
                "timestamp": now,
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": _build_summary(entries, backup_path)}],
                },
            }
        ),
        _json_line(
            {
                "timestamp": now,
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "已载入瘦身后的历史摘要。"}],
                },
            }
        ),
    ]
    if entries:
        lines.append(
            _json_line(
                {
                    "timestamp": now,
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": entries[-1]}],
                    },
                }
            )
        )

    temp_path = path.with_name(f"{path.name}.repairing")
    try:
        temp_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        temp_path.replace(path)
    except OSError:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass
        return None
    return backup_path
