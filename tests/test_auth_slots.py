import base64
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import auth_slots


def encode_jwt(payload: dict[str, object]) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    token = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    return f"header.{token}.signature"


class AuthSlotsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.codex_home = self.root / ".codex"
        self.codex_home.mkdir(parents=True, exist_ok=True)
        self.slots_dir = self.codex_home / "account_slots"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def write_current_auth(
        self,
        *,
        email: str,
        account_id: str,
        refresh_token: str,
        cap_sid: str = "cap-a",
    ) -> None:
        auth_path = self.codex_home / "auth.json"
        payload = {
            "auth_mode": "chatgpt",
            "tokens": {
                "account_id": account_id,
                "refresh_token": refresh_token,
                "id_token": encode_jwt({"email": email}),
            },
        }
        auth_path.write_text(json.dumps(payload), encoding="utf-8")
        (self.codex_home / "cap_sid").write_text(cap_sid, encoding="utf-8")

    def test_decode_jwt_payload_extracts_email(self) -> None:
        token = encode_jwt({"email": "a@example.com"})

        payload = auth_slots.decode_jwt_payload(token)

        self.assertEqual("a@example.com", payload.get("email"))

    def test_save_current_auth_to_slot_copies_auth_and_cap_sid(self) -> None:
        self.write_current_auth(
            email="a@example.com",
            account_id="acct-a",
            refresh_token="refresh-a",
            cap_sid="cap-a",
        )

        info = auth_slots.save_current_auth_to_slot(
            "account-a",
            codex_home=self.codex_home,
            slots_dir=self.slots_dir,
        )

        slot_auth = self.slots_dir / "account-a" / "auth.json"
        slot_cap = self.slots_dir / "account-a" / "cap_sid"
        self.assertTrue(slot_auth.exists())
        self.assertTrue(slot_cap.exists())
        self.assertEqual("a@example.com", info["email"])
        self.assertEqual("acct-a", info["account_id"])
        self.assertEqual("account-a", info["slot_id"])

    def test_switch_to_auth_slot_restores_saved_files(self) -> None:
        self.write_current_auth(
            email="a@example.com",
            account_id="acct-a",
            refresh_token="refresh-a",
            cap_sid="cap-a",
        )
        auth_slots.save_current_auth_to_slot(
            "account-a",
            codex_home=self.codex_home,
            slots_dir=self.slots_dir,
        )
        self.write_current_auth(
            email="b@example.com",
            account_id="acct-b",
            refresh_token="refresh-b",
            cap_sid="cap-b",
        )

        info = auth_slots.switch_to_auth_slot(
            "account-a",
            codex_home=self.codex_home,
            slots_dir=self.slots_dir,
        )

        current = json.loads((self.codex_home / "auth.json").read_text("utf-8"))
        self.assertEqual("acct-a", current["tokens"]["account_id"])
        self.assertEqual("cap-a", (self.codex_home / "cap_sid").read_text("utf-8"))
        self.assertEqual("a@example.com", info["email"])

    def test_detect_active_slot_matches_current_auth_fingerprint(self) -> None:
        self.write_current_auth(
            email="a@example.com",
            account_id="acct-a",
            refresh_token="refresh-a",
            cap_sid="cap-a",
        )
        auth_slots.save_current_auth_to_slot(
            "account-a",
            codex_home=self.codex_home,
            slots_dir=self.slots_dir,
        )
        self.write_current_auth(
            email="b@example.com",
            account_id="acct-b",
            refresh_token="refresh-b",
            cap_sid="cap-b",
        )
        auth_slots.save_current_auth_to_slot(
            "account-b",
            codex_home=self.codex_home,
            slots_dir=self.slots_dir,
        )
        auth_slots.switch_to_auth_slot(
            "account-b",
            codex_home=self.codex_home,
            slots_dir=self.slots_dir,
        )

        active = auth_slots.detect_active_slot(
            codex_home=self.codex_home,
            slots_dir=self.slots_dir,
        )

        self.assertEqual("account-b", active)

    def test_list_account_slots_migrates_legacy_standard_slots(self) -> None:
        self.write_current_auth(
            email="a@example.com",
            account_id="acct-a",
            refresh_token="refresh-a",
            cap_sid="cap-a",
        )
        auth_slots.save_current_auth_to_slot(
            "account-a",
            codex_home=self.codex_home,
            slots_dir=self.slots_dir,
        )
        self.write_current_auth(
            email="b@example.com",
            account_id="acct-b",
            refresh_token="refresh-b",
            cap_sid="cap-b",
        )
        auth_slots.save_current_auth_to_slot(
            "account-b",
            codex_home=self.codex_home,
            slots_dir=self.slots_dir,
        )

        items = auth_slots.list_account_slots(
            codex_home=self.codex_home,
            slots_dir=self.slots_dir,
        )

        self.assertEqual(["account-a", "account-b"], [item["slot_id"] for item in items])
        self.assertEqual(["Account A", "Account B"], [item["label"] for item in items])
        metadata = auth_slots.load_slot_registry(slots_dir=self.slots_dir)
        self.assertEqual(2, len(metadata))

    def test_create_rename_and_delete_dynamic_slot(self) -> None:
        created = auth_slots.create_account_slot("Personal Plus", slots_dir=self.slots_dir)
        self.assertEqual("Personal Plus", created["label"])

        renamed = auth_slots.rename_account_slot(created["slot_id"], "Backup", slots_dir=self.slots_dir)
        self.assertEqual("Backup", renamed["label"])

        items = auth_slots.list_account_slots(codex_home=self.codex_home, slots_dir=self.slots_dir)
        self.assertEqual(["Backup"], [item["label"] for item in items])

        auth_slots.delete_account_slot(created["slot_id"], slots_dir=self.slots_dir)
        self.assertEqual([], auth_slots.list_account_slots(codex_home=self.codex_home, slots_dir=self.slots_dir))

    def test_save_current_auth_to_dynamic_slot_uses_label_metadata(self) -> None:
        created = auth_slots.create_account_slot("Work", slots_dir=self.slots_dir)
        self.write_current_auth(
            email="work@example.com",
            account_id="acct-work",
            refresh_token="refresh-work",
            cap_sid="cap-work",
        )

        info = auth_slots.save_current_auth_to_slot(
            created["slot_id"],
            codex_home=self.codex_home,
            slots_dir=self.slots_dir,
        )

        self.assertEqual("Work", info["label"])
        listed = auth_slots.list_account_slots(codex_home=self.codex_home, slots_dir=self.slots_dir)
        self.assertEqual("work@example.com", listed[0]["email"])


if __name__ == "__main__":
    unittest.main()
