import json
import tempfile
import unittest
from pathlib import Path

import session_context_repair


class SessionContextRepairTests(unittest.TestCase):
    def test_compact_oversized_session_file_backs_up_and_keeps_recent_history(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            session_id = "session-1"
            session_file = root / "rollout-session-1.jsonl"
            history_file = root / "history.jsonl"
            session_file.write_text(
                json.dumps(
                    {
                        "timestamp": "2026-01-01T00:00:00.000Z",
                        "type": "session_meta",
                        "payload": {"id": session_id, "cwd": "C:\\tmp"},
                    }
                )
                + "\n"
                + ("x" * 200),
                encoding="utf-8",
            )
            history_file.write_text(
                json.dumps({"session_id": "other", "text": "ignore"}, ensure_ascii=False)
                + "\n"
                + json.dumps({"session_id": session_id, "text": "older"}, ensure_ascii=False)
                + "\n"
                + json.dumps({"session_id": session_id, "text": "之前我们是不是创建过一个临时邮箱"}, ensure_ascii=False)
                + "\n",
                encoding="utf-8",
            )

            backup = session_context_repair.compact_oversized_session_file(
                session_id,
                session_file,
                history_file,
                max_bytes=50,
            )

            self.assertIsNotNone(backup)
            self.assertTrue(Path(str(backup)).exists())
            lines = session_file.read_text(encoding="utf-8").splitlines()
            self.assertLess(len(lines), 6)
            self.assertIn("历史摘要", lines[1])
            self.assertIn("older", lines[1])
            self.assertIn("之前我们是不是创建过一个临时邮箱", lines[-1])

    def test_compact_oversized_session_file_skips_small_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            session_file = root / "rollout-session-1.jsonl"
            history_file = root / "history.jsonl"
            session_file.write_text('{"type":"session_meta","payload":{"id":"session-1"}}\n', encoding="utf-8")

            backup = session_context_repair.compact_oversized_session_file(
                "session-1",
                session_file,
                history_file,
                max_bytes=500,
            )

            self.assertIsNone(backup)
            self.assertEqual('{"type":"session_meta","payload":{"id":"session-1"}}\n', session_file.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
