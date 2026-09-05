import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app
import mobile_portal


CURRENT_ID = "01a0201d-93fd-7682-a3e1-335a70661cc9"
CORRECT_CWD = r"D:\codex\codex-session-manager-windows\codex-session-manager-windows-main"


def make_mobile_session() -> mobile_portal.SessionItem:
    return mobile_portal.SessionItem(
        session_id=CURRENT_ID,
        ts=1,
        text="current",
        note="",
        history_count=1,
        cwd=r"D:\paper",
        model="gpt-5.6-sol",
        approval_policy="never",
        sandbox_mode="danger-full-access",
        turn_id="",
        session_file="",
        reasoning_effort="max",
    )


class SessionCwdOverrideTests(unittest.TestCase):
    def test_mobile_session_override_replaces_rollout_cwd(self) -> None:
        items = mobile_portal.apply_session_overrides(
            [make_mobile_session()],
            {CURRENT_ID: {"cwd": CORRECT_CWD}},
        )

        self.assertEqual(CORRECT_CWD, items[0].cwd)

    def test_mobile_setting_update_preserves_cwd_override(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_file = Path(temp_dir) / "session_settings.json"
            settings_file.write_text(
                json.dumps({CURRENT_ID: {"cwd": CORRECT_CWD}}),
                encoding="utf-8",
            )
            with mock.patch.object(mobile_portal, "SETTINGS_FILE", settings_file):
                store = mobile_portal.CodexDataStore()
                store.set_session_settings(
                    CURRENT_ID,
                    "gpt-5.6-sol",
                    "never",
                    "danger-full-access",
                    "max",
                )
                saved = json.loads(settings_file.read_text(encoding="utf-8"))

        self.assertEqual(CORRECT_CWD, saved[CURRENT_ID]["cwd"])

    def test_desktop_loader_uses_cwd_override(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            history_file = root / "history.jsonl"
            settings_file = root / "session_settings.json"
            history_file.write_text(
                json.dumps({"session_id": CURRENT_ID, "ts": 1, "text": "current"}) + "\n",
                encoding="utf-8",
            )
            settings_file.write_text(
                json.dumps({CURRENT_ID: {"cwd": CORRECT_CWD}}),
                encoding="utf-8",
            )
            manager = object.__new__(app.SessionManagerApp)
            manager.items = []
            manager.session_notes = {}
            manager._history_signature = None
            manager._find_session_file = mock.Mock(return_value="rollout.jsonl")
            manager._extract_session_details = mock.Mock(return_value={"cwd": r"D:\paper"})

            with (
                mock.patch.object(app, "HISTORY_FILE", history_file),
                mock.patch.object(app, "SETTINGS_FILE", settings_file, create=True),
            ):
                items = manager._load_sessions(force=True)

        self.assertEqual(CORRECT_CWD, items[0].cwd)


if __name__ == "__main__":
    unittest.main()
