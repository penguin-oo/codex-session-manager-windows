import tempfile
import unittest
from base64 import b64encode
import subprocess
from pathlib import Path
from unittest import mock

import mobile_portal


class ResolvePortalTokenTests(unittest.TestCase):
    def test_explicit_token_is_returned_and_saved(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            token_file = Path(temp_dir) / "mobile_portal_token.txt"

            resolved = mobile_portal.resolve_portal_token("fixed-token", token_file)

            self.assertEqual("fixed-token", resolved)
            self.assertEqual("fixed-token", token_file.read_text(encoding="utf-8"))

    def test_existing_saved_token_is_reused(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            token_file = Path(temp_dir) / "mobile_portal_token.txt"
            token_file.write_text("saved-token", encoding="utf-8")

            resolved = mobile_portal.resolve_portal_token("", token_file)

            self.assertEqual("saved-token", resolved)

    def test_missing_token_file_generates_and_persists_token(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            token_file = Path(temp_dir) / "mobile_portal_token.txt"

            resolved = mobile_portal.resolve_portal_token("", token_file)

            self.assertTrue(resolved)
            self.assertEqual(resolved, token_file.read_text(encoding="utf-8"))


class WorkingDirectoryTests(unittest.TestCase):
    def test_ensure_working_directory_creates_missing_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "nested" / "project"

            resolved = mobile_portal.ensure_working_directory(str(target))

            self.assertEqual(target, resolved)
            self.assertTrue(target.exists())
            self.assertTrue(target.is_dir())


class _FakeStore:
    def __init__(self, sessions: list[mobile_portal.SessionItem] | None = None) -> None:
        self._sessions = sessions or []
        self._settings: dict[str, dict[str, str]] = {}
        self.append_history_calls: list[tuple[str, str, int | None]] = []

    def load_sessions(self) -> list[mobile_portal.SessionItem]:
        return mobile_portal.apply_session_overrides(list(self._sessions), self._settings)

    def session_payload(self, session_id: str) -> dict[str, object] | None:
        for item in self.load_sessions():
            if item.session_id == session_id:
                return {"session": mobile_portal.asdict(item), "messages": []}
        return None

    def set_session_settings(
        self,
        session_id: str,
        model: str,
        approval_policy: str,
        sandbox_mode: str,
        reasoning_effort: str,
    ) -> dict[str, str]:
        cleaned = {
            key: value
            for key, value in {
                "model": model.strip(),
                "approval_policy": approval_policy.strip(),
                "sandbox_mode": sandbox_mode.strip(),
                "reasoning_effort": reasoning_effort.strip(),
            }.items()
            if value and value != "default"
        }
        if cleaned:
            self._settings[session_id] = cleaned
        else:
            self._settings.pop(session_id, None)
        return cleaned

    def append_history_entry(self, session_id: str, text: str, ts: int | None = None, history_file: Path | None = None) -> None:
        self.append_history_calls.append((session_id, text, ts))

    def load_mcp_items(self) -> list[object]:
        return []

    def load_skill_items(self) -> list[object]:
        return []

    def load_available_models(self) -> list[str]:
        return []


class JobRunnerOwnershipTests(unittest.TestCase):
    def test_claim_session_rejects_conflicting_owner(self) -> None:
        runner = mobile_portal.JobRunner(_FakeStore())

        claim = runner.claim_session("session-1", "mobile", "Mobile", mode="write")

        self.assertTrue(claim["ok"])
        with self.assertRaisesRegex(RuntimeError, "Mobile"):
            runner.claim_session("session-1", "desktop_manager", "Desktop Manager", mode="write")

    def test_start_resume_job_releases_stale_running_lock_when_process_is_gone(self) -> None:
        session = mobile_portal.SessionItem(
            session_id="session-1",
            ts=1,
            text="hello",
            note="",
            history_count=1,
            cwd=str(Path.cwd()),
            model="gpt-5",
            approval_policy="default",
            sandbox_mode="workspace-write",
            turn_id="turn-1",
            session_file="",
        )
        runner = mobile_portal.JobRunner(_FakeStore([session]))
        runner.active_sessions.add("session-1")
        runner.jobs["dead-job"] = {
            "job_id": "dead-job",
            "status": "running",
            "kind": "resume",
            "session_id": "session-1",
            "created_at": 1,
            "heartbeat_at": 0,
            "pid": 999999,
            "error": "",
            "last_message": "",
            "log_tail": [],
            "live_text": "",
            "live_chunks_version": 0,
        }

        with mock.patch.object(runner, "_run_resume_job"), mock.patch.object(runner, "_is_pid_running", return_value=False):
            result = runner.start_resume_job("session-1", "hello again", "default", "default", "default", "default")

        self.assertIn("job_id", result)
        self.assertIn("session-1", runner.active_sessions)
        self.assertNotIn("dead-job", runner.jobs)

    def test_append_live_text_tracks_incremental_preview(self) -> None:
        runner = mobile_portal.JobRunner(_FakeStore())
        runner.jobs["job-1"] = {
            "job_id": "job-1",
            "status": "running",
            "kind": "resume",
            "session_id": "session-1",
            "created_at": mobile_portal.now_ts(),
            "heartbeat_at": mobile_portal.now_ts(),
            "pid": 0,
            "error": "",
            "last_message": "",
            "log_tail": [],
            "live_text": "",
            "live_chunks_version": 0,
        }

        runner._append_live_text("job-1", "partial reply")

        job = runner.get_job("job-1")
        self.assertEqual("partial reply", job["live_text"])
        self.assertEqual(1, job["live_chunks_version"])

    def test_active_job_for_session_returns_running_job_payload(self) -> None:
        runner = mobile_portal.JobRunner(_FakeStore())
        runner.jobs["job-1"] = {
            "job_id": "job-1",
            "status": "running",
            "kind": "resume",
            "session_id": "session-1",
            "created_at": mobile_portal.now_ts(),
            "heartbeat_at": mobile_portal.now_ts(),
            "pid": 0,
            "error": "",
            "last_message": "",
            "log_tail": [],
            "live_text": "partial reply",
            "live_chunks_version": 1,
        }

        job = runner.active_job_for_session("session-1")

        self.assertIsNotNone(job)
        self.assertEqual("job-1", job["job_id"])

    def test_start_resume_job_rejects_conflicting_desktop_terminal(self) -> None:
        session = mobile_portal.SessionItem(
            session_id="session-1",
            ts=1,
            text="hello",
            note="",
            history_count=1,
            cwd=str(Path.cwd()),
            model="gpt-5",
            approval_policy="default",
            sandbox_mode="workspace-write",
            turn_id="turn-1",
            session_file="",
        )
        runner = mobile_portal.JobRunner(_FakeStore([session]))

        with mock.patch("mobile_portal.list_windows_process_rows", return_value=[
            {"ProcessId": 11, "CommandLine": "codex.exe resume session-1"}
        ]):
            with self.assertRaisesRegex(RuntimeError, "desktop Codex terminal"):
                runner.start_resume_job("session-1", "hello again", "default", "default", "default", "default")

    def test_run_resume_job_records_user_history_for_forked_session_with_job_created_timestamp(self) -> None:
        runner = mobile_portal.JobRunner(mobile_portal.CodexDataStore())
        runner.jobs["job-1"] = {
            "job_id": "job-1",
            "status": "running",
            "kind": "resume",
            "session_id": "session-1",
            "created_at": 123,
            "heartbeat_at": 123,
            "pid": 0,
            "error": "",
            "last_message": "",
            "log_tail": [],
            "live_text": "",
            "live_chunks_version": 0,
        }

        with mock.patch.object(runner, "_run_codex_process", return_value="session-1"), \
                mock.patch.object(runner.data_store, "append_history_entry") as append_history_entry:
            runner._run_resume_job(
                "job-1",
                str(Path.cwd()),
                "session-1",
                "hello from mobile",
                "default",
                "default",
                "default",
                "default",
            )

        append_history_entry.assert_not_called()

        with mock.patch.object(runner, "_run_codex_process", return_value="session-2"), \
                mock.patch.object(runner.data_store, "append_history_entry") as append_history_entry:
            runner._run_resume_job(
                "job-1",
                str(Path.cwd()),
                "session-1",
                "hello from mobile",
                "default",
                "default",
                "default",
                "default",
            )

        append_history_entry.assert_called_once_with("session-2", "hello from mobile", ts=123)

    def test_run_codex_process_finishes_after_turn_completed_even_if_process_exit_lags(self) -> None:
        runner = mobile_portal.JobRunner(_FakeStore())
        runner.jobs["job-1"] = {
            "job_id": "job-1",
            "status": "running",
            "kind": "resume",
            "session_id": "session-1",
            "created_at": mobile_portal.now_ts(),
            "heartbeat_at": mobile_portal.now_ts(),
            "pid": 0,
            "error": "",
            "last_message": "",
            "log_tail": [],
            "live_text": "",
            "live_chunks_version": 0,
        }

        class _FakeProcess:
            def __init__(self) -> None:
                self.pid = 321
                self.stdout = iter([
                    '{"type":"thread.started","thread_id":"session-1"}\n',
                    '{"type":"response_item","payload":{"type":"message","role":"assistant","phase":"final_answer","content":[{"text":"done"}]}}\n',
                    '{"type":"turn.completed","usage":{"total_tokens":1}}\n',
                ])
                self.terminated = False

            def wait(self, timeout: float | None = None) -> int:
                if not self.terminated:
                    raise subprocess.TimeoutExpired(cmd="codex", timeout=timeout)
                return 0

            def terminate(self) -> None:
                self.terminated = True

            def kill(self) -> None:
                self.terminated = True

        fake_process = _FakeProcess()

        with mock.patch("mobile_portal.subprocess.Popen", return_value=fake_process), \
                mock.patch.object(runner, "_is_pid_running", side_effect=[True, False]):
            detected_session = runner._run_codex_process(
                "job-1",
                ["codex.cmd", "exec"],
                str(Path.cwd()),
                "session-1",
            )

        self.assertEqual("session-1", detected_session)
        self.assertTrue(fake_process.terminated)
        job = runner.get_job("job-1")
        self.assertEqual("done", job["last_message"])

    def test_run_new_chat_job_records_opening_message_for_created_session(self) -> None:
        runner = mobile_portal.JobRunner(_FakeStore())
        runner.jobs["job-1"] = {
            "job_id": "job-1",
            "status": "running",
            "kind": "new_chat",
            "session_id": "",
            "created_at": 456,
            "heartbeat_at": 456,
            "pid": 0,
            "error": "",
            "last_message": "",
            "log_tail": [],
            "live_text": "",
            "live_chunks_version": 0,
            "note": "",
        }

        with mock.patch.object(runner, "_run_codex_process", return_value="session-2"), \
                mock.patch.object(runner.data_store, "append_history_entry") as append_history_entry:
            runner._run_new_chat_job(
                "job-1",
                str(Path.cwd()),
                "hello from new chat",
                "default",
                "default",
                "default",
                "default",
            )

        append_history_entry.assert_called_once_with("session-2", "hello from new chat", ts=456)

    def test_thread_started_for_new_chat_records_opening_message_immediately(self) -> None:
        runner = mobile_portal.JobRunner(_FakeStore())
        runner.jobs["job-1"] = {
            "job_id": "job-1",
            "status": "running",
            "kind": "new_chat",
            "session_id": "",
            "created_at": 789,
            "heartbeat_at": 789,
            "pid": 0,
            "error": "",
            "last_message": "",
            "log_tail": [],
            "live_text": "",
            "live_chunks_version": 0,
            "note": "",
            "opening_prompt": "hello early",
            "opening_prompt_recorded": False,
        }

        with mock.patch.object(runner.data_store, "append_history_entry") as append_history_entry:
            detected_session, stop_reading = runner._handle_codex_event(
                "job-1",
                {"type": "thread.started", "thread_id": "session-3"},
                "",
            )

        self.assertEqual("session-3", detected_session)
        self.assertFalse(stop_reading)
        append_history_entry.assert_called_once_with("session-3", "hello early", ts=789)
        self.assertTrue(runner.jobs["job-1"]["opening_prompt_recorded"])


class PortalServiceBootstrapTests(unittest.TestCase):
    def test_bootstrap_payload_marks_running_sessions(self) -> None:
        session = mobile_portal.SessionItem(
            session_id="session-1",
            ts=1,
            text="hello",
            note="",
            history_count=1,
            cwd=str(Path.cwd()),
            model="gpt-5",
            approval_policy="default",
            sandbox_mode="workspace-write",
            turn_id="turn-1",
            session_file="",
        )
        fake_store = _FakeStore([session])
        service = mobile_portal.PortalService("127.0.0.1", 8765, "token")
        service.data_store = fake_store
        service.jobs = mobile_portal.JobRunner(fake_store)
        service.jobs.jobs["job-1"] = {
            "job_id": "job-1",
            "status": "running",
            "kind": "resume",
            "session_id": "session-1",
            "created_at": mobile_portal.now_ts(),
            "heartbeat_at": mobile_portal.now_ts(),
            "pid": 0,
            "error": "",
            "last_message": "",
            "log_tail": [],
            "live_text": "",
            "live_chunks_version": 0,
        }

        payload = service.bootstrap_payload()

        self.assertTrue(payload["sessions"][0]["is_replying"])
        self.assertEqual(mobile_portal.current_proxy_summary(), payload["proxy_summary"])

    def test_update_session_settings_changes_follow_up_defaults(self) -> None:
        session = mobile_portal.SessionItem(
            session_id="session-1",
            ts=1,
            text="hello",
            note="",
            history_count=1,
            cwd=str(Path.cwd()),
            model="gpt-5",
            approval_policy="default",
            sandbox_mode="workspace-write",
            turn_id="turn-1",
            session_file="",
        )
        fake_store = _FakeStore([session])
        service = mobile_portal.PortalService("127.0.0.1", 8765, "token")
        service.data_store = fake_store
        service.jobs = mobile_portal.JobRunner(fake_store)

        payload = service.update_session_settings("session-1", "gpt-5.4", "never", "danger-full-access", "high")

        session_payload = payload["session"]
        self.assertEqual("gpt-5.4", session_payload["model"])
        self.assertEqual("never", session_payload["approval_policy"])
        self.assertEqual("danger-full-access", session_payload["sandbox_mode"])
        self.assertEqual("high", session_payload["reasoning_effort"])


class PortalAccountSlotsTests(unittest.TestCase):
    def test_account_slots_payload_includes_active_slot_running_flag_and_quota(self) -> None:
        service = mobile_portal.PortalService("127.0.0.1", 8765, "token")
        service.jobs.jobs["job-1"] = {"status": "running"}

        with mock.patch.object(mobile_portal.auth_slots, "detect_active_slot", return_value="account-b"), \
             mock.patch.object(mobile_portal.auth_slots, "current_auth_info", return_value={"email": "b@example.com"}), \
             mock.patch.object(mobile_portal.auth_slots, "list_account_slots", return_value=[{"slot_id": "slot-1"}, {"slot_id": "slot-2"}]), \
             mock.patch.object(mobile_portal, "read_current_weekly_quota", return_value={"summary": "Weekly quota: 42%", "state": "ok"}):
            payload = service.account_slots_payload()

        self.assertEqual("account-b", payload["active_slot"])
        self.assertEqual("b@example.com", payload["current_auth"]["email"])
        self.assertTrue(payload["has_running_jobs"])
        self.assertEqual(2, len(payload["slots"]))
        self.assertEqual("Weekly quota: 42%", payload["quota"]["summary"])

    def test_switch_account_rejects_when_job_is_running(self) -> None:
        service = mobile_portal.PortalService("127.0.0.1", 8765, "token")
        service.jobs.jobs["job-1"] = {"status": "running"}

        with self.assertRaisesRegex(RuntimeError, "Stop active replies"):
            service.switch_account("account-b")

    def test_create_rename_and_delete_account_slot_round_trip(self) -> None:
        service = mobile_portal.PortalService("127.0.0.1", 8765, "token")

        with mock.patch.object(mobile_portal.auth_slots, "create_account_slot", return_value={"slot_id": "slot-3", "label": "Travel"}), \
             mock.patch.object(service, "account_slots_payload", return_value={"slots": [{"slot_id": "slot-3", "label": "Travel"}]}):
            created = service.create_account_slot("Travel")
        self.assertEqual("Travel", created["slots"][0]["label"])

        with mock.patch.object(mobile_portal.auth_slots, "rename_account_slot", return_value={"slot_id": "slot-3", "label": "Travel Backup"}), \
             mock.patch.object(service, "account_slots_payload", return_value={"slots": [{"slot_id": "slot-3", "label": "Travel Backup"}]}):
            renamed = service.rename_account_slot("slot-3", "Travel Backup")
        self.assertEqual("Travel Backup", renamed["slots"][0]["label"])

        with mock.patch.object(mobile_portal.auth_slots, "delete_account_slot"), \
             mock.patch.object(service, "account_slots_payload", return_value={"slots": []}):
            deleted = service.delete_account_slot("slot-3")
        self.assertEqual([], deleted["slots"])

    def test_read_current_weekly_quota_extracts_status_summary(self) -> None:
        output = "Plan: ChatGPT Plus\nWeekly quota: 76% used (resets in 3 days)\n"

        with mock.patch.object(mobile_portal, "run_text_command", return_value=output):
            quota = mobile_portal.read_current_weekly_quota()

        self.assertEqual("ok", quota["state"])
        self.assertIn("Weekly quota: 76% used", quota["summary"])


class PortalFileShareTests(unittest.TestCase):
    def test_build_inline_content_disposition_supports_utf8_pdf_names(self) -> None:
        header = mobile_portal.build_inline_content_disposition("动量守恒_长板双物块_原题摘录.pdf")

        self.assertIn('inline; filename="', header)
        self.assertIn("filename*=UTF-8''", header)
        self.assertIn("%E5%8A%A8%E9%87%8F%E5%AE%88%E6%81%92", header)
        self.assertNotIn('filename="动量守恒_长板双物块_原题摘录.pdf"', header)

    def test_create_file_share_allows_supported_file_under_session_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cwd = Path(temp_dir)
            target = cwd / "preview.png"
            target.write_bytes(b"\x89PNG\r\n\x1a\npreview")
            session = mobile_portal.SessionItem(
                session_id="session-1",
                ts=1,
                text="hello",
                note="",
                history_count=1,
                cwd=str(cwd),
                model="gpt-5",
                approval_policy="default",
                sandbox_mode="workspace-write",
                turn_id="turn-1",
                session_file="",
            )
            fake_store = _FakeStore([session])
            service = mobile_portal.PortalService("127.0.0.1", 8765, "token")
            service.data_store = fake_store
            service.jobs = mobile_portal.JobRunner(fake_store)

            share = service.create_file_share("session-1", str(target))

            self.assertIn("/files/", share["relative_url"])
            entry = service.resolve_file_share(str(share["share_id"]))
            self.assertEqual(target.resolve(), entry["path"])
            self.assertEqual("image/png", entry["content_type"])

    def test_create_file_share_rejects_file_outside_allowed_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            cwd = base / "project"
            outside = base / "outside.png"
            cwd.mkdir()
            outside.write_bytes(b"\x89PNG\r\n\x1a\npreview")
            session = mobile_portal.SessionItem(
                session_id="session-1",
                ts=1,
                text="hello",
                note="",
                history_count=1,
                cwd=str(cwd),
                model="gpt-5",
                approval_policy="default",
                sandbox_mode="workspace-write",
                turn_id="turn-1",
                session_file="",
            )
            fake_store = _FakeStore([session])
            service = mobile_portal.PortalService("127.0.0.1", 8765, "token")
            service.data_store = fake_store
            service.jobs = mobile_portal.JobRunner(fake_store)

            with self.assertRaisesRegex(PermissionError, "allowed"):
                service.create_file_share("session-1", str(outside))

    def test_create_file_share_rejects_unsupported_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cwd = Path(temp_dir)
            target = cwd / "notes.txt"
            target.write_text("not supported", encoding="utf-8")
            session = mobile_portal.SessionItem(
                session_id="session-1",
                ts=1,
                text="hello",
                note="",
                history_count=1,
                cwd=str(cwd),
                model="gpt-5",
                approval_policy="default",
                sandbox_mode="workspace-write",
                turn_id="turn-1",
                session_file="",
            )
            fake_store = _FakeStore([session])
            service = mobile_portal.PortalService("127.0.0.1", 8765, "token")
            service.data_store = fake_store
            service.jobs = mobile_portal.JobRunner(fake_store)

            with self.assertRaisesRegex(ValueError, "Unsupported"):
                service.create_file_share("session-1", str(target))


class PortalDownloadsTests(unittest.TestCase):
    def test_download_page_includes_release_links(self) -> None:
        service = mobile_portal.PortalService("127.0.0.1", 8765, "verify-token")

        html = service.download_page_html()

        self.assertIn("/downloads/codex-mobile-debug.apk?token=verify-token", html)
        self.assertIn("/downloads/codex-session-manager-windows-x64.zip?token=verify-token", html)


class ResumeArgsTests(unittest.TestCase):
    def test_build_resume_args_includes_image_attachment_after_resume_command(self) -> None:
        output_file = Path("out.txt")
        image_file = Path("photo.png")

        args = mobile_portal.build_resume_args(
            output_file=output_file,
            session_id="session-1",
            prompt="describe this",
            model="gpt-5",
            sandbox="workspace-write",
            approval="never",
            reasoning_effort="medium",
            image_paths=[image_file],
        )

        self.assertEqual(["resume", "-i", str(image_file), "session-1", "describe this"], args[-5:])
        self.assertIn('model_reasoning_effort="medium"', args)

    def test_build_resume_args_omits_blank_prompt_for_image_only_message(self) -> None:
        args = mobile_portal.build_resume_args(
            output_file=Path("out.txt"),
            session_id="session-1",
            prompt="",
            model="default",
            sandbox="default",
            approval="default",
            reasoning_effort="default",
            image_paths=[Path("photo.png")],
        )

        self.assertEqual(["resume", "-i", "photo.png", "session-1"], args[-4:])


class ProxyEnvTests(unittest.TestCase):
    def test_build_codex_subprocess_env_defaults_to_local_proxy(self) -> None:
        with mock.patch.dict(mobile_portal.os.environ, {}, clear=True):
            env = mobile_portal.build_codex_subprocess_env()

        self.assertEqual("socks5h://127.0.0.1:7897", env["HTTP_PROXY"])
        self.assertEqual("socks5h://127.0.0.1:7897", env["HTTPS_PROXY"])
        self.assertEqual("socks5h://127.0.0.1:7897", env["ALL_PROXY"])
        self.assertEqual("localhost,127.0.0.1,::1", env["NO_PROXY"])

    def test_build_codex_subprocess_env_preserves_explicit_proxy(self) -> None:
        with mock.patch.dict(mobile_portal.os.environ, {"ALL_PROXY": "http://10.0.0.2:8888"}, clear=True):
            env = mobile_portal.build_codex_subprocess_env()

        self.assertEqual("http://10.0.0.2:8888", env["ALL_PROXY"])


class SessionProcessDetectionTests(unittest.TestCase):
    def test_find_conflicting_interactive_session_pids_ignores_exec_json_resume(self) -> None:
        processes = [
            {"ProcessId": 11, "CommandLine": "powershell.exe -NoExit -Command codex resume session-1"},
            {"ProcessId": 12, "CommandLine": "codex.exe resume session-1"},
            {"ProcessId": 13, "CommandLine": "cmd.exe /c codex.cmd exec --json -o out.txt resume session-1 hi"},
            {"ProcessId": 14, "CommandLine": "codex.exe resume session-2"},
        ]

        pids = mobile_portal.find_conflicting_interactive_session_pids("session-1", processes)

        self.assertEqual([11, 12], pids)

class ImageAttachmentTests(unittest.TestCase):
    def test_materialize_image_attachment_writes_named_temp_file(self) -> None:
        payload = {
            "name": "sample.png",
            "mime_type": "image/png",
            "data_base64": b64encode(b"png-bytes").decode("ascii"),
        }

        temp_path = mobile_portal.materialize_image_attachment(payload)

        try:
            self.assertEqual(".png", temp_path.suffix)
            self.assertEqual(b"png-bytes", temp_path.read_bytes())
        finally:
            temp_path.unlink(missing_ok=True)

    def test_materialize_image_attachment_uses_signature_when_metadata_is_generic(self) -> None:
        payload = {
            "name": "image",
            "mime_type": "image/*",
            "data_base64": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9s6Pvx0AAAAASUVORK5CYII=",
        }

        temp_path = mobile_portal.materialize_image_attachment(payload)

        try:
            self.assertEqual(".png", temp_path.suffix)
            self.assertTrue(temp_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"))
        finally:
            temp_path.unlink(missing_ok=True)


class TailscaleHelpersTests(unittest.TestCase):
    def test_extract_tailscale_ipv4_addresses_filters_noise(self) -> None:
        output = "100.64.0.1\ninvalid\n100.88.7.9\nfe80::1\n"

        addresses = mobile_portal.extract_tailscale_ipv4_addresses(output)

        self.assertEqual(["100.64.0.1", "100.88.7.9"], addresses)

    def test_extract_tailscale_dns_name_reads_self_dns_name(self) -> None:
        payload = '{"Self": {"DNSName": "codex-box.tail123.ts.net."}}'

        dns_name = mobile_portal.extract_tailscale_dns_name(payload)

        self.assertEqual("codex-box.tail123.ts.net", dns_name)

    def test_extract_tailscale_dns_name_returns_blank_on_invalid_json(self) -> None:
        dns_name = mobile_portal.extract_tailscale_dns_name("not-json")

        self.assertEqual("", dns_name)


class CacheHelperTests(unittest.TestCase):
    def test_path_signature_reads_size(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "history.jsonl"
            target.write_text("hello", encoding="utf-8")

            signature = mobile_portal.path_signature(target)

            self.assertIsNotNone(signature)
            self.assertEqual(target.stat().st_size, signature[1])

    def test_apply_session_notes_returns_copied_items(self) -> None:
        items = [
            mobile_portal.SessionItem(
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
            )
        ]

        updated = mobile_portal.apply_session_notes(items, {"session-1": "new"})

        self.assertEqual("new", updated[0].note)
        self.assertEqual("old", items[0].note)

    def test_copy_message_list_returns_detached_dicts(self) -> None:
        original = [{"role": "assistant", "text": "hello"}]

        copied = mobile_portal.copy_message_list(original)
        copied[0]["text"] = "changed"

        self.assertEqual("hello", original[0]["text"])


class HistoryEntryTests(unittest.TestCase):
    def test_append_history_entry_writes_jsonl_line(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            history_file = Path(temp_dir) / "history.jsonl"
            store = mobile_portal.CodexDataStore()

            store.append_history_entry("session-2", "hello from mobile", ts=123, history_file=history_file)

            rows = history_file.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(1, len(rows))
            parsed = mobile_portal.json.loads(rows[0])
            self.assertEqual("session-2", parsed["session_id"])
            self.assertEqual("hello from mobile", parsed["text"])
            self.assertEqual(123, parsed["ts"])

    def test_build_history_entry_text_prefers_prompt_and_keeps_image_label(self) -> None:
        text = mobile_portal.build_history_entry_text("describe this", [Path("photo.jpg")])

        self.assertEqual("describe this\n\n[Image] photo.jpg", text)

    def test_build_history_entry_text_supports_image_only_messages(self) -> None:
        text = mobile_portal.build_history_entry_text("", [Path("photo.jpg")])

        self.assertEqual("[Image] photo.jpg", text)


if __name__ == "__main__":
    unittest.main()


class JobCancellationTests(unittest.TestCase):
    def test_cancel_job_marks_running_job_cancelled_and_releases_session(self) -> None:
        runner = mobile_portal.JobRunner(_FakeStore())
        runner.active_sessions.add("session-1")
        runner.jobs["job-1"] = {
            "job_id": "job-1",
            "status": "running",
            "kind": "resume",
            "session_id": "session-1",
            "created_at": mobile_portal.now_ts(),
            "heartbeat_at": mobile_portal.now_ts(),
            "pid": 321,
            "error": "",
            "last_message": "partial",
            "log_tail": [],
            "live_text": "partial",
            "live_chunks_version": 1,
        }

        with mock.patch.object(runner, "_terminate_pid", return_value=True) as terminate_pid:
            job = runner.cancel_job("job-1")

        terminate_pid.assert_called_once_with(321)
        self.assertEqual("cancelled", job["status"])
        self.assertNotIn("session-1", runner.active_sessions)

    def test_cancel_job_rejects_finished_job(self) -> None:
        runner = mobile_portal.JobRunner(_FakeStore())
        runner.jobs["job-1"] = {
            "job_id": "job-1",
            "status": "completed",
            "kind": "resume",
            "session_id": "session-1",
            "created_at": mobile_portal.now_ts(),
            "heartbeat_at": mobile_portal.now_ts(),
            "pid": 0,
            "error": "",
            "last_message": "done",
            "log_tail": [],
            "live_text": "done",
            "live_chunks_version": 1,
        }

        with self.assertRaisesRegex(RuntimeError, "not running"):
            runner.cancel_job("job-1")
