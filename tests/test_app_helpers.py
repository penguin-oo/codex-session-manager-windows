import tempfile
import unittest
from pathlib import Path

import app


class AppHelperTests(unittest.TestCase):
    def test_path_signature_reads_mtime_and_size(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "history.jsonl"
            target.write_text("hello", encoding="utf-8")

            signature = app.path_signature(target)

            self.assertIsNotNone(signature)
            self.assertEqual(target.stat().st_size, signature[1])

    def test_apply_session_notes_updates_matching_items_only(self) -> None:
        items = [
            app.SessionItem(
                session_id="session-1",
                ts=1,
                text="hello",
                note="old",
                history_count=1,
                cwd="",
                model="",
                approval_policy="",
                sandbox_mode="",
                turn_id="",
                session_file="",
            ),
            app.SessionItem(
                session_id="session-2",
                ts=2,
                text="world",
                note="keep",
                history_count=2,
                cwd="",
                model="",
                approval_policy="",
                sandbox_mode="",
                turn_id="",
                session_file="",
            ),
        ]

        updated = app.apply_session_notes(items, {"session-1": "new"})

        self.assertEqual("new", updated[0].note)
        self.assertEqual("keep", updated[1].note)
        self.assertEqual("old", items[0].note)


if __name__ == "__main__":
    unittest.main()
