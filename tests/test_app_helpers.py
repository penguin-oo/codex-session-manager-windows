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

    def test_terminal_proxy_schemes_include_socks5h(self) -> None:
        self.assertIn("socks5h", app.TERMINAL_PROXY_SCHEMES)

    def test_build_start_process_command_uses_no_profile(self) -> None:
        command = app.build_start_process_command(
            ps_command="Write-Host 'hello'",
            run_as_admin=True,
        )

        self.assertIn("-Verb RunAs", command)
        self.assertIn("'-NoProfile'", command)
        self.assertIn("'-NoExit'", command)
        self.assertIn("'-Command'", command)

    def test_build_proxy_environment_ps_prefix_clears_proxy_when_disabled(self) -> None:
        prefix = app.build_proxy_environment_ps_prefix(
            enabled=False,
            scheme="socks5h",
            host="127.0.0.1",
            port_text="7897",
        )

        self.assertIn("$env:HTTP_PROXY=$null", prefix)
        self.assertIn("$env:ALL_PROXY=$null", prefix)

    def test_build_proxy_environment_ps_prefix_supports_socks5h(self) -> None:
        prefix = app.build_proxy_environment_ps_prefix(
            enabled=True,
            scheme="socks5h",
            host="127.0.0.1",
            port_text="7897",
        )

        self.assertIn("socks5h://127.0.0.1:7897", prefix)

    def test_format_account_status_label_uses_active_slot_name(self) -> None:
        label = app.format_account_status_label(
            "account-a",
            {"email": "a@example.com", "account_id": "acct-a"},
        )

        self.assertEqual("Auth: Account A | a@example.com", label)

    def test_format_account_slot_summary_marks_unbound_slots(self) -> None:
        summary = app.format_account_slot_summary("account-b", {}, None)

        self.assertIn("Account B", summary)
        self.assertIn("Not bound yet.", summary)

    def test_format_account_slot_summary_prefers_dynamic_label(self) -> None:
        summary = app.format_account_slot_summary(
            "slot-3",
            {"label": "Travel", "email": "travel@example.com", "auth_mode": "chatgpt", "fingerprint": "abc"},
            None,
        )

        self.assertIn("Travel", summary)
        self.assertNotIn("slot-3", summary)

    def test_format_quota_summary_uses_backend_text(self) -> None:
        summary = app.format_account_quota_summary({"summary": "Weekly quota: 76% used", "state": "ok"})

        self.assertEqual("Weekly quota: 76% used", summary)



if __name__ == "__main__":
    unittest.main()
