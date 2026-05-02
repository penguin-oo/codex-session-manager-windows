import codecs
import io
import json
import queue
import subprocess
import tempfile
import threading
import unittest
from base64 import b64encode
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import controlled_browser
import mobile_portal
import token_pool_settings


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


class ProxySettingsTests(unittest.TestCase):
    def test_load_proxy_settings_defaults_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_path = Path(temp_dir) / "mobile_portal_settings.json"

            settings = mobile_portal.load_proxy_settings(settings_path)

            self.assertTrue(settings["proxy_enabled"])
            self.assertEqual(7897, settings["proxy_port"])
            self.assertEqual([], settings["public_urls"])

    def test_load_proxy_settings_normalizes_public_urls(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_path = Path(temp_dir) / "mobile_portal_settings.json"
            settings_path.write_text(
                json.dumps(
                    {
                        "proxy_enabled": True,
                        "proxy_port": 7897,
                        "public_urls": [
                            " https://chat.pyguin.us.ci ",
                            "https://chat.pyguin.us.ci/?token=stale#fragment",
                            "https://chat.pyguin.us.ci/path?foo=1",
                            "not-a-url",
                            "",
                        ],
                    }
                ),
                encoding="utf-8",
            )

            settings = mobile_portal.load_proxy_settings(settings_path)

            self.assertEqual(
                [
                    "https://chat.pyguin.us.ci/",
                    "https://chat.pyguin.us.ci/path?foo=1",
                ],
                settings["public_urls"],
            )

    def test_load_proxy_settings_accepts_utf8_bom_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_path = Path(temp_dir) / "mobile_portal_settings.json"
            payload = json.dumps(
                {
                    "proxy_enabled": True,
                    "proxy_port": 7897,
                    "public_urls": ["https://chat.pyguin.us.ci"],
                }
            ).encode("utf-8")
            settings_path.write_bytes(codecs.BOM_UTF8 + payload)

            settings = mobile_portal.load_proxy_settings(settings_path)

            self.assertEqual(["https://chat.pyguin.us.ci/"], settings["public_urls"])

    def test_save_proxy_settings_validates_port(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_path = Path(temp_dir) / "mobile_portal_settings.json"

            saved = mobile_portal.save_proxy_settings(False, 9001, settings_path)

            self.assertFalse(saved["proxy_enabled"])
            self.assertEqual(9001, saved["proxy_port"])

            with self.assertRaisesRegex(ValueError, "between 1 and 65535"):
                mobile_portal.save_proxy_settings(True, 70000, settings_path)

    def test_apply_proxy_settings_to_env_uses_fixed_host_and_scheme(self) -> None:
        env = {"NO_PROXY": "localhost"}

        updated = mobile_portal.apply_proxy_settings_to_env(env, {"proxy_enabled": True, "proxy_port": 9002})

        self.assertEqual("socks5h://127.0.0.1:9002", updated["ALL_PROXY"])
        self.assertEqual("localhost", updated["NO_PROXY"])

        disabled = mobile_portal.apply_proxy_settings_to_env(env, {"proxy_enabled": False, "proxy_port": 9002})
        self.assertNotIn("ALL_PROXY", disabled)

    def test_build_codex_subprocess_env_uses_saved_settings_over_existing_proxy_env(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_path = Path(temp_dir) / "mobile_portal_settings.json"
            mobile_portal.save_proxy_settings(True, 9003, settings_path)
            with mock.patch.dict(
                mobile_portal.os.environ,
                {"ALL_PROXY": "http://10.0.0.2:8888", "NO_PROXY": "localhost"},
                clear=True,
            ):
                env = mobile_portal.build_codex_subprocess_env(settings_file=settings_path)

        self.assertEqual("socks5h://127.0.0.1:9003", env["ALL_PROXY"])
        self.assertEqual("localhost", env["NO_PROXY"])


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


class _FakeUrlResponse:
    def __init__(self, body: str, status: int = 200, headers: dict[str, str] | None = None) -> None:
        self.status = status
        self.headers = headers or {"content-type": "application/json"}
        self._body = body.encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeUrlResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class _FakeUrlOpener:
    def __init__(self, response: _FakeUrlResponse) -> None:
        self.response = response
        self.requests: list[tuple[object, float | None]] = []

    def open(self, request: object, timeout: float | None = None) -> _FakeUrlResponse:
        self.requests.append((request, timeout))
        return self.response


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

    def test_active_job_for_session_keeps_job_when_wrapper_pid_is_gone_but_exec_process_still_exists(self) -> None:
        runner = mobile_portal.JobRunner(_FakeStore())
        runner.active_sessions.add("session-1")
        runner.jobs["job-1"] = {
            "job_id": "job-1",
            "status": "running",
            "kind": "resume",
            "session_id": "session-1",
            "created_at": 1,
            "heartbeat_at": 1,
            "pid": 1744,
            "output_file": r"C:\Users\windows\AppData\Local\Temp\codex-mobile-out-test.txt",
            "error": "",
            "last_message": "",
            "log_tail": [],
            "live_text": "",
            "live_chunks_version": 0,
        }
        processes = [
            {
                "ProcessId": 23372,
                "Name": "node.exe",
                "CommandLine": (
                    '"node" "C:\\Users\\windows\\AppData\\Roaming\\npm\\node_modules\\@openai\\codex\\bin\\codex.js" '
                    'exec --json -o C:\\Users\\windows\\AppData\\Local\\Temp\\codex-mobile-out-test.txt '
                    "resume session-1 -"
                ),
            },
            {
                "ProcessId": 12376,
                "Name": "codex.exe",
                "CommandLine": (
                    "C:\\Users\\windows\\AppData\\Roaming\\npm\\node_modules\\@openai\\codex\\codex.exe "
                    "exec --json -o C:\\Users\\windows\\AppData\\Local\\Temp\\codex-mobile-out-test.txt "
                    "resume session-1 -"
                ),
            },
        ]

        with mock.patch.object(runner, "_is_pid_running", return_value=False), \
             mock.patch.object(mobile_portal, "list_windows_process_rows", return_value=processes), \
             mock.patch.object(mobile_portal, "now_ts", return_value=100):
            job = runner.active_job_for_session("session-1")

        self.assertIsNotNone(job)
        self.assertEqual("job-1", job["job_id"])
        self.assertEqual(23372, runner.jobs["job-1"]["pid"])
        self.assertIn("session-1", runner.active_sessions)

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

        append_history_entry.assert_called_once_with("session-1", "hello from mobile", ts=123)

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

    def test_start_resume_job_does_not_record_history_before_worker_starts(self) -> None:
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
        runner = mobile_portal.JobRunner(fake_store)

        with mock.patch.object(runner, "_run_resume_job"), \
             mock.patch("mobile_portal.list_windows_process_rows", return_value=[]):
            runner.start_resume_job("session-1", "hello again", "default", "default", "default", "default")

        self.assertEqual([], fake_store.append_history_calls)

    def test_run_codex_process_keeps_reading_after_turn_completed_to_capture_trailing_final_answer(self) -> None:
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
                    '{"type":"turn.completed","usage":{"total_tokens":1}}\n',
                    '{"type":"response_item","payload":{"type":"message","role":"assistant","phase":"final_answer","content":[{"text":"done after completion"}]}}\n',
                ])

            def wait(self, timeout: float | None = None) -> int:
                return 0

            def terminate(self) -> None:
                raise AssertionError("process should not be terminated after turn.completed when stdout continues")

            def kill(self) -> None:
                raise AssertionError("process should not be killed after turn.completed when stdout continues")

        fake_process = _FakeProcess()

        with mock.patch("mobile_portal.subprocess.Popen", return_value=fake_process):
            detected_session = runner._run_codex_process(
                "job-1",
                ["codex.cmd", "exec"],
                str(Path.cwd()),
                "session-1",
            )

        self.assertEqual("session-1", detected_session)
        job = runner.get_job("job-1")
        self.assertEqual("done after completion", job["last_message"])

    def test_run_codex_process_uses_task_complete_last_agent_message(self) -> None:
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
                self.pid = 654
                self.stdout = iter([
                    '{"type":"thread.started","thread_id":"session-1"}\n',
                    '{"type":"response_item","payload":{"type":"message","role":"assistant","phase":"commentary","content":[{"text":"working"}]}}\n',
                    '{"type":"event_msg","payload":{"type":"task_complete","turn_id":"turn-1","last_agent_message":"final link https://example.test/file.zip"}}\n',
                ])

            def wait(self, timeout: float | None = None) -> int:
                return 0

            def terminate(self) -> None:
                raise AssertionError("process should not be terminated when task_complete was received")

            def kill(self) -> None:
                raise AssertionError("process should not be killed when task_complete was received")

        fake_process = _FakeProcess()

        with mock.patch("mobile_portal.subprocess.Popen", return_value=fake_process):
            detected_session = runner._run_codex_process(
                "job-1",
                ["codex.cmd", "exec"],
                str(Path.cwd()),
                "session-1",
            )

        self.assertEqual("session-1", detected_session)
        job = runner.get_job("job-1")
        self.assertEqual("final link https://example.test/file.zip", job["last_message"])

    def test_run_codex_process_finishes_after_task_complete_even_if_process_does_not_exit(self) -> None:
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

        class _BlockingStdout:
            def __init__(self) -> None:
                self._queue: queue.Queue[str | None] = queue.Queue()
                self._queue.put('{"type":"thread.started","thread_id":"session-1"}\n')
                self._queue.put('{"type":"event_msg","payload":{"type":"task_complete","turn_id":"turn-1","last_agent_message":"done but process stuck"}}\n')

            def __iter__(self):
                return self

            def __next__(self) -> str:
                item = self._queue.get()
                if item is None:
                    raise StopIteration
                return item

            def finish(self) -> None:
                self._queue.put(None)

        class _FakeProcess:
            def __init__(self) -> None:
                self.pid = 432
                self.stdout = _BlockingStdout()
                self.terminate_calls = 0
                self.kill_calls = 0

            def wait(self, timeout: float | None = None) -> int:
                if self.terminate_calls > 0 or self.kill_calls > 0:
                    return 0
                if timeout is None:
                    return 0
                raise subprocess.TimeoutExpired("codex.cmd", timeout)

            def terminate(self) -> None:
                self.terminate_calls += 1
                self.stdout.finish()

            def kill(self) -> None:
                self.kill_calls += 1
                self.stdout.finish()

        fake_process = _FakeProcess()
        result: dict[str, object] = {}

        def _runner() -> None:
            try:
                result["session_id"] = runner._run_codex_process(
                    "job-1",
                    ["codex.cmd", "exec"],
                    str(Path.cwd()),
                    "session-1",
                )
            except Exception as exc:  # pragma: no cover - assertion uses result
                result["error"] = exc

        with mock.patch.object(mobile_portal, "PROCESS_EXIT_GRACE_SECONDS", 0.05), \
             mock.patch("mobile_portal.subprocess.Popen", return_value=fake_process):
            worker = threading.Thread(target=_runner, daemon=True)
            worker.start()
            worker.join(0.4)
            if worker.is_alive():
                fake_process.stdout.finish()
                worker.join(1.0)

        self.assertFalse(worker.is_alive(), "process should finish shortly after task_complete")
        self.assertNotIn("error", result)
        self.assertEqual("session-1", result.get("session_id"))
        job = runner.get_job("job-1")
        self.assertEqual("done but process stuck", job["last_message"])
        self.assertEqual(1, fake_process.terminate_calls)
        self.assertEqual(0, fake_process.kill_calls)

    def test_run_codex_process_writes_prompt_to_stdin_when_requested(self) -> None:
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

        class _FakeStdin:
            def __init__(self) -> None:
                self.parts: list[str] = []
                self.closed = False

            def write(self, value: str) -> int:
                self.parts.append(value)
                return len(value)

            def close(self) -> None:
                self.closed = True

        class _FakeProcess:
            def __init__(self) -> None:
                self.pid = 654
                self.stdin = _FakeStdin()
                self.stdout = iter([
                    '{"type":"thread.started","thread_id":"session-1"}\n',
                    '{"type":"turn.completed"}\n',
                    '{"type":"event_msg","payload":{"type":"task_complete","turn_id":"turn-1","last_agent_message":"stdin ok"}}\n',
                ])

            def wait(self, timeout: float | None = None) -> int:
                return 0

            def terminate(self) -> None:
                return None

            def kill(self) -> None:
                return None

        fake_process = _FakeProcess()

        with mock.patch("mobile_portal.subprocess.Popen", return_value=fake_process):
            detected_session = runner._run_codex_process(
                "job-1",
                ["codex.cmd", "exec", "-"],
                str(Path.cwd()),
                "session-1",
                stdin_text="--help\nsecond line",
            )

        self.assertEqual("session-1", detected_session)
        self.assertEqual("--help\nsecond line", "".join(fake_process.stdin.parts))
        self.assertTrue(fake_process.stdin.closed)

    def test_run_codex_process_rejects_empty_exit_without_turn_completion(self) -> None:
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
                self.pid = 777
                self.stdout = iter([
                    '{"type":"thread.started","thread_id":"session-1"}\n',
                ])

            def wait(self, timeout: float | None = None) -> int:
                return 0

            def terminate(self) -> None:
                return None

            def kill(self) -> None:
                return None

        fake_process = _FakeProcess()

        with mock.patch("mobile_portal.subprocess.Popen", return_value=fake_process):
            with self.assertRaisesRegex(RuntimeError, "without completing the turn"):
                runner._run_codex_process(
                    "job-1",
                    ["codex.cmd", "exec"],
                    str(Path.cwd()),
                    "session-1",
                )

    def test_run_codex_process_times_out_when_no_startup_output(self) -> None:
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

        class _SilentStdout:
            def __init__(self) -> None:
                self._queue: queue.Queue[str | None] = queue.Queue()

            def __iter__(self):
                return self

            def __next__(self) -> str:
                item = self._queue.get()
                if item is None:
                    raise StopIteration
                return item

            def finish(self) -> None:
                self._queue.put(None)

        class _FakeProcess:
            def __init__(self) -> None:
                self.pid = 888
                self.stdout = _SilentStdout()
                self.terminate_calls = 0
                self.kill_calls = 0

            def wait(self, timeout: float | None = None) -> int:
                if self.terminate_calls > 0 or self.kill_calls > 0:
                    return 0
                if timeout is None:
                    return 0
                raise subprocess.TimeoutExpired("codex.cmd", timeout)

            def terminate(self) -> None:
                self.terminate_calls += 1
                self.stdout.finish()

            def kill(self) -> None:
                self.kill_calls += 1
                self.stdout.finish()

        fake_process = _FakeProcess()

        with mock.patch.object(mobile_portal, "PROCESS_STARTUP_NO_OUTPUT_TIMEOUT_SECONDS", 0.05), \
             mock.patch.object(mobile_portal, "PROCESS_EXIT_GRACE_SECONDS", 0.05), \
             mock.patch("mobile_portal.subprocess.Popen", return_value=fake_process):
            with self.assertRaisesRegex(RuntimeError, "produced no startup output"):
                runner._run_codex_process(
                    "job-1",
                    ["codex.cmd", "exec"],
                    str(Path.cwd()),
                    "session-1",
                )

        self.assertEqual(1, fake_process.terminate_calls)

    def test_run_codex_process_uses_max_runtime_after_initial_output(self) -> None:
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

        class _BlockingStdout:
            def __init__(self) -> None:
                self._queue: queue.Queue[str | None] = queue.Queue()
                self._queue.put('{"type":"thread.started","thread_id":"session-1"}\n')

            def __iter__(self):
                return self

            def __next__(self) -> str:
                item = self._queue.get()
                if item is None:
                    raise StopIteration
                return item

            def finish(self) -> None:
                self._queue.put(None)

        class _FakeProcess:
            def __init__(self) -> None:
                self.pid = 889
                self.stdout = _BlockingStdout()
                self.terminate_calls = 0
                self.kill_calls = 0

            def wait(self, timeout: float | None = None) -> int:
                if self.terminate_calls > 0 or self.kill_calls > 0:
                    return 0
                if timeout is None:
                    return 0
                raise subprocess.TimeoutExpired("codex.cmd", timeout)

            def terminate(self) -> None:
                self.terminate_calls += 1
                self.stdout.finish()

            def kill(self) -> None:
                self.kill_calls += 1
                self.stdout.finish()

        fake_process = _FakeProcess()

        with mock.patch.object(mobile_portal, "PROCESS_STARTUP_NO_OUTPUT_TIMEOUT_SECONDS", 0.05), \
             mock.patch.object(mobile_portal, "PROCESS_MAX_RUNTIME_SECONDS", 0.1), \
             mock.patch.object(mobile_portal, "PROCESS_EXIT_GRACE_SECONDS", 0.05), \
             mock.patch("mobile_portal.subprocess.Popen", return_value=fake_process):
            with self.assertRaisesRegex(RuntimeError, "exceeded"):
                runner._run_codex_process(
                    "job-1",
                    ["codex.cmd", "exec"],
                    str(Path.cwd()),
                    "session-1",
                )

        self.assertEqual(1, fake_process.terminate_calls)

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

    def test_startup_url_groups_include_configured_public_urls(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_path = Path(temp_dir) / "mobile_portal_settings.json"
            settings_path.write_text(
                json.dumps(
                    {
                        "proxy_enabled": True,
                        "proxy_port": 7897,
                        "public_urls": ["https://chat.pyguin.us.ci"],
                    }
                ),
                encoding="utf-8",
            )
            service = mobile_portal.PortalService("127.0.0.1", 8765, "verify-token")
            service.proxy_settings_file = settings_path

            with mock.patch.object(service, "tailscale_urls", return_value=["http://100.64.0.1:8765/?token=verify-token"]), \
                 mock.patch.object(service, "lan_urls", return_value=["http://127.0.0.1:8765/?token=verify-token"]):
                groups = service.startup_url_groups()

        self.assertEqual(
            [
                ("Public (Cloudflare/custom)", ["https://chat.pyguin.us.ci/?token=verify-token"]),
                ("Tailscale (cross-network)", ["http://100.64.0.1:8765/?token=verify-token"]),
                ("LAN", ["http://127.0.0.1:8765/?token=verify-token"]),
            ],
            groups,
        )

    def test_bootstrap_payload_includes_startup_url_groups(self) -> None:
        service = mobile_portal.PortalService("127.0.0.1", 8765, "token")

        with mock.patch.object(
            service,
            "startup_url_groups",
            return_value=[("Public (Cloudflare/custom)", ["https://chat.pyguin.us.ci/?token=token"])],
        ):
            payload = service.bootstrap_payload()

        self.assertEqual(
            [{"label": "Public (Cloudflare/custom)", "urls": ["https://chat.pyguin.us.ci/?token=token"]}],
            payload["startup_url_groups"],
        )

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

    def test_proxy_settings_payload_and_update_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_path = Path(temp_dir) / "mobile_portal_settings.json"
            settings_path.write_text(
                json.dumps(
                    {
                        "proxy_enabled": True,
                        "proxy_port": 7897,
                        "public_urls": ["https://chat.pyguin.us.ci"],
                    }
                ),
                encoding="utf-8",
            )
            service = mobile_portal.PortalService("127.0.0.1", 8765, "token")
            service.proxy_settings_file = settings_path

            initial = service.proxy_settings_payload()
            updated = service.update_proxy_settings(False, 9010)

        self.assertTrue(initial["proxy_enabled"])
        self.assertEqual(7897, initial["proxy_port"])
        self.assertEqual("socks5h", initial["proxy_scheme"])
        self.assertEqual("127.0.0.1", initial["proxy_host"])
        self.assertEqual(["https://chat.pyguin.us.ci/"], initial["public_urls"])
        self.assertFalse(updated["proxy_enabled"])
        self.assertEqual(9010, updated["proxy_port"])
        self.assertEqual("direct", updated["proxy_summary"])
        self.assertEqual(["https://chat.pyguin.us.ci/"], updated["public_urls"])


class PortalPageTemplateTests(unittest.TestCase):
    def test_reply_completion_waits_for_final_message_before_finished_status(self) -> None:
        html = mobile_portal.INDEX_HTML

        self.assertIn("waitForFinalAssistantMessage", html)
        self.assertIn("Syncing final reply into chat history...", html)
        self.assertLess(
            html.index('setStatus("Syncing final reply into chat history...")'),
            html.index('setStatus(job.last_message ? `Finished: ${job.last_message.slice(0, 140)}` : "Finished.");'),
        )


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

    def test_refresh_current_chatgpt_auth_updates_auth_file_with_rotated_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            codex_home = Path(temp_dir) / ".codex"
            codex_home.mkdir(parents=True, exist_ok=True)
            auth_path = codex_home / "auth.json"
            auth_path.write_text(
                json.dumps(
                    {
                        "auth_mode": "chatgpt",
                        "OPENAI_API_KEY": None,
                        "last_refresh": "2026-04-20T00:00:00Z",
                        "tokens": {
                            "account_id": "acct-1",
                            "access_token": "old-access",
                            "refresh_token": "old-refresh",
                            "id_token": "old-id",
                        },
                    }
                ),
                encoding="utf-8",
            )
            opener = _FakeUrlOpener(
                _FakeUrlResponse(
                    json.dumps(
                        {
                            "access_token": "new-access",
                            "refresh_token": "new-refresh",
                            "id_token": "new-id",
                            "expires_in": 3600,
                            "scope": "openid profile email",
                            "token_type": "Bearer",
                        }
                    )
                )
            )

            with mock.patch.object(mobile_portal.url_request, "build_opener", return_value=opener):
                result = mobile_portal.refresh_current_chatgpt_auth(
                    auth_file=auth_path,
                    settings_file=codex_home / "mobile_portal_settings.json",
                )
            self.assertEqual("ok", result["status"])
            updated = json.loads(auth_path.read_text(encoding="utf-8"))
            self.assertEqual("new-access", updated["tokens"]["access_token"])
            self.assertEqual("new-refresh", updated["tokens"]["refresh_token"])
            self.assertEqual("new-id", updated["tokens"]["id_token"])
            self.assertEqual("acct-1", updated["tokens"]["account_id"])
            request, timeout = opener.requests[0]
            self.assertEqual("https://auth.openai.com/oauth/token", request.full_url)
            self.assertEqual(8.0, timeout)
            self.assertEqual(
                {
                    "grant_type": "refresh_token",
                    "client_id": "app_EMoamEEZ73f0CkXaXp7hrann",
                    "refresh_token": "old-refresh",
                },
                json.loads(request.data.decode("utf-8")),
            )

    def test_refresh_current_account_syncs_active_slot_after_refresh(self) -> None:
        service = mobile_portal.PortalService("127.0.0.1", 8765, "token")

        with mock.patch.object(mobile_portal, "refresh_current_chatgpt_auth", return_value={"status": "ok"}), \
             mock.patch.object(mobile_portal.auth_slots, "detect_active_slot", return_value="slot-2"), \
             mock.patch.object(mobile_portal.auth_slots, "save_current_auth_to_slot") as save_current_auth_to_slot, \
             mock.patch.object(service, "account_slots_payload", return_value={"active_slot": "slot-2"}) as account_slots_payload:
            payload = service.refresh_current_account()

        self.assertEqual({"active_slot": "slot-2"}, payload)
        save_current_auth_to_slot.assert_called_once_with("slot-2")
        account_slots_payload.assert_called_once_with()

    def test_login_and_bind_account_runs_browser_login_then_saves_current_auth(self) -> None:
        service = mobile_portal.PortalService("127.0.0.1", 8765, "token")

        login_result = subprocess.CompletedProcess([mobile_portal.CODEX_BIN, "login"], 0, stdout="logged in")
        with mock.patch.object(service, "has_running_jobs", return_value=False), \
             mock.patch.object(mobile_portal.auth_slots, "load_slot_registry", return_value=[{"slot_id": "slot-9"}]), \
             mock.patch.object(mobile_portal.auth_slots, "current_auth_info", side_effect=[{"fingerprint": "old"}, {"fingerprint": "new"}]), \
             mock.patch.object(mobile_portal, "run_codex_browser_login", return_value=login_result) as run_login, \
             mock.patch.object(mobile_portal.auth_slots, "save_current_auth_to_slot") as save_current_auth_to_slot, \
             mock.patch.object(service, "request_desktop_refresh") as request_desktop_refresh, \
             mock.patch.object(service, "account_slots_payload", return_value={"active_slot": "slot-9"}) as account_slots_payload:
            payload = service.login_and_bind_account("slot-9")

        self.assertEqual({"active_slot": "slot-9"}, payload)
        run_login.assert_called_once_with(settings_file=service.proxy_settings_file)
        save_current_auth_to_slot.assert_called_once_with("slot-9")
        request_desktop_refresh.assert_called_once_with(source="account_login_bind")
        account_slots_payload.assert_called_once_with()

    def test_login_and_bind_account_rejects_when_job_is_running(self) -> None:
        service = mobile_portal.PortalService("127.0.0.1", 8765, "token")

        with mock.patch.object(service, "has_running_jobs", return_value=True):
            with self.assertRaisesRegex(RuntimeError, "Stop active replies"):
                service.login_and_bind_account("slot-9")

    def test_login_and_bind_account_requires_existing_slot(self) -> None:
        service = mobile_portal.PortalService("127.0.0.1", 8765, "token")

        with mock.patch.object(service, "has_running_jobs", return_value=False), \
             mock.patch.object(mobile_portal.auth_slots, "load_slot_registry", return_value=[]):
            with self.assertRaisesRegex(FileNotFoundError, "slot-9"):
                service.login_and_bind_account("slot-9")

    def test_login_and_bind_account_rejects_unchanged_auth_after_login(self) -> None:
        service = mobile_portal.PortalService("127.0.0.1", 8765, "token")

        login_result = subprocess.CompletedProcess([mobile_portal.CODEX_BIN, "login"], 0, stdout="logged in")
        with mock.patch.object(service, "has_running_jobs", return_value=False), \
             mock.patch.object(mobile_portal.auth_slots, "load_slot_registry", return_value=[{"slot_id": "slot-9"}]), \
             mock.patch.object(mobile_portal.auth_slots, "current_auth_info", side_effect=[{"fingerprint": "same"}, {"fingerprint": "same"}]), \
             mock.patch.object(mobile_portal, "run_codex_browser_login", return_value=login_result):
            with self.assertRaisesRegex(RuntimeError, "did not produce a new login"):
                service.login_and_bind_account("slot-9")

    def test_read_current_weekly_quota_extracts_status_summary(self) -> None:
        output = "Plan: ChatGPT Plus\nWeekly quota: 76% used (resets in 3 days)\n"

        with mock.patch.object(mobile_portal, "read_current_usage_quota", return_value={"state": "unavailable", "summary": "Quota unavailable"}), \
             mock.patch.object(mobile_portal, "run_text_command", return_value=output):
            quota = mobile_portal.read_current_weekly_quota()

        self.assertEqual("ok", quota["state"])
        self.assertIn("Weekly quota: 76% used", quota["summary"])

    def test_read_current_weekly_quota_includes_5h_and_weekly_lines(self) -> None:
        output = (
            "Plan: ChatGPT Plus\n"
            "5h quota: 12% used (resets in 2h)\n"
            "Weekly quota: 76% used (resets in 3 days)\n"
        )

        with mock.patch.object(mobile_portal, "read_current_usage_quota", return_value={"state": "unavailable", "summary": "Quota unavailable"}), \
             mock.patch.object(mobile_portal, "run_text_command", return_value=output):
            quota = mobile_portal.read_current_weekly_quota()

        self.assertEqual("ok", quota["state"])
        self.assertEqual(
            "5h quota: 12% used (resets in 2h)\nWeekly quota: 76% used (resets in 3 days)",
            quota["summary"],
        )

    def test_read_current_weekly_quota_prefers_usage_api(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            auth_path = Path(temp_dir) / "auth.json"
            auth_path.write_text(json.dumps({"tokens": {"access_token": "test-token"}}), encoding="utf-8")
            settings_path = Path(temp_dir) / "mobile_portal_settings.json"
            mobile_portal.save_proxy_settings(True, 9003, settings_path)
            opener = _FakeUrlOpener(
                _FakeUrlResponse(
                    json.dumps(
                        {
                            "rate_limit": {
                                "primary_window": {
                                    "used_percent": 24,
                                    "limit_window_seconds": 18000,
                                    "reset_after_seconds": 16974,
                                },
                                "secondary_window": {
                                    "used_percent": 19,
                                    "limit_window_seconds": 604800,
                                    "reset_after_seconds": 582818,
                                },
                            }
                        }
                    )
                )
            )

            with mock.patch.object(mobile_portal.url_request, "build_opener", return_value=opener), \
                 mock.patch.object(mobile_portal, "run_text_command", return_value="") as run_text_command:
                quota = mobile_portal.read_current_weekly_quota(auth_file=auth_path, settings_file=settings_path)

        self.assertEqual("ok", quota["state"])
        self.assertEqual(
            "5h quota: 24% used (resets in 4h 42m)\nWeekly quota: 19% used (resets in 6d 17h)",
            quota["summary"],
        )
        self.assertFalse(run_text_command.called)
        request, timeout = opener.requests[0]
        self.assertEqual("Bearer test-token", request.headers["Authorization"])
        self.assertEqual(4.0, timeout)

    def test_read_current_weekly_quota_falls_back_to_plain_status_command(self) -> None:
        with mock.patch.object(mobile_portal, "run_text_command", return_value="") as run_text_command:
            mobile_portal.read_current_weekly_quota(auth_file=Path("missing-auth.json"))

        run_text_command.assert_called_once_with([mobile_portal.CODEX_BIN, "status"], timeout_seconds=4.0)

    def test_load_available_models_includes_gpt_5_5_even_when_cache_is_stale(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            models_path = Path(temp_dir) / "models_cache.json"
            models_path.write_text(
                json.dumps(
                    {
                        "models": [
                            {"slug": "gpt-5.4", "visibility": "list"},
                            {"slug": "gpt-5.4-mini", "visibility": "list"},
                            {"slug": "gpt-5.3-codex", "visibility": "list"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            store = mobile_portal.CodexDataStore()

            with mock.patch.object(mobile_portal, "MODELS_CACHE_FILE", models_path):
                models = store.load_available_models()

        self.assertEqual(
            ["gpt-5.5", "gpt-5.4", "gpt-5.4-mini", "gpt-5.3-codex", "gpt-5.2", "gpt-5"],
            models,
        )

    def test_load_available_models_prefers_openai_compatible_cache_when_backend_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            backend_settings_path = Path(temp_dir) / "token_pool_settings.json"
            token_pool_settings.save_backend_settings(
                token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE,
                settings_file=backend_settings_path,
                token_dir=Path(temp_dir) / "tokens",
                proxy_port=8317,
                proxy_api_key="pool-api-key",
                openai_base_url="https://api.openai.com/v1",
                openai_api_key="sk-test",
                openai_model="gpt-5.5",
                openai_models=["gpt-5.5", "gpt-4.1"],
            )
            store = mobile_portal.CodexDataStore()

            with mock.patch.object(mobile_portal, "BACKEND_SETTINGS_FILE", backend_settings_path), \
                 mock.patch.object(mobile_portal, "MODELS_CACHE_FILE", Path(temp_dir) / "missing-models-cache.json"):
                models = store.load_available_models()

        self.assertEqual(["gpt-5.5", "gpt-4.1", "gpt-5.4", "gpt-5.3-codex", "gpt-5.2", "gpt-5"], models)

    def test_account_slots_payload_includes_backend_status(self) -> None:
        service = mobile_portal.PortalService("127.0.0.1", 8765, "token")

        with mock.patch.object(mobile_portal.auth_slots, "detect_active_slot", return_value="account-b"), \
             mock.patch.object(mobile_portal.auth_slots, "current_auth_info", return_value={"email": "b@example.com"}), \
             mock.patch.object(mobile_portal.auth_slots, "list_account_slots", return_value=[]), \
             mock.patch.object(mobile_portal, "read_current_weekly_quota", return_value={"summary": "Weekly quota: 42%", "state": "ok"}), \
             mock.patch.object(service, "backend_status_payload", return_value={
                 "backend_mode": "built_in_token_pool",
                 "proxy_port": 8317,
                 "proxy_running": True,
                 "proxy_summary": "http://127.0.0.1:8317",
                 "token_count": 3,
                 "last_error": "",
             }):
            payload = service.account_slots_payload()

        self.assertEqual("built_in_token_pool", payload["backend"]["backend_mode"])
        self.assertTrue(payload["backend"]["proxy_running"])
        self.assertEqual(3, payload["backend"]["token_count"])

    def test_backend_status_payload_reports_token_pool_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = mobile_portal.PortalService("127.0.0.1", 8765, "token")
            backend_settings_path = Path(temp_dir) / "token_pool_settings.json"
            token_dir = Path(temp_dir) / "tokens"
            token_dir.mkdir()
            (token_dir / "a.json").write_text('{"token":"a"}', encoding="utf-8")
            (token_dir / "b.json").write_text('{"token":"b"}', encoding="utf-8")
            token_pool_settings.save_backend_settings(
                token_pool_settings.BACKEND_MODE_TOKEN_POOL,
                settings_file=backend_settings_path,
                token_dir=token_dir,
                proxy_port=8317,
                proxy_api_key="pool-api-key",
            )
            service.backend_settings_file = backend_settings_path

            with mock.patch.object(mobile_portal, "token_pool_proxy_is_healthy", return_value=True):
                payload = service.backend_status_payload()

        self.assertEqual("built_in_token_pool", payload["backend_mode"])
        self.assertEqual(8317, payload["proxy_port"])
        self.assertTrue(payload["proxy_running"])
        self.assertEqual(2, payload["token_count"])

    def test_update_backend_settings_persists_and_returns_backend_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = mobile_portal.PortalService("127.0.0.1", 8765, "token")
            backend_settings_path = Path(temp_dir) / "token_pool_settings.json"
            token_dir = Path(temp_dir) / "tokens"
            service.backend_settings_file = backend_settings_path

            updated = service.update_backend_settings(
                backend_mode=token_pool_settings.BACKEND_MODE_TOKEN_POOL,
                token_dir=str(token_dir),
                proxy_port=8456,
            )

            loaded = token_pool_settings.load_backend_settings(backend_settings_path)

        self.assertEqual(token_pool_settings.BACKEND_MODE_TOKEN_POOL, updated["backend_mode"])
        self.assertEqual(8456, loaded["proxy_port"])
        self.assertEqual(str(token_dir), loaded["token_dir"])

    def test_backend_status_payload_reports_openai_compatible_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = mobile_portal.PortalService("127.0.0.1", 8765, "token")
            backend_settings_path = Path(temp_dir) / "token_pool_settings.json"
            token_pool_settings.save_backend_settings(
                token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE,
                settings_file=backend_settings_path,
                token_dir=Path(temp_dir) / "tokens",
                proxy_port=8317,
                proxy_api_key="pool-api-key",
                openai_base_url="https://api.openai.com/v1",
                openai_api_key="sk-test",
                openai_model="gpt-5.5",
                openai_models=["gpt-5.5", "gpt-5.4"],
            )
            service.backend_settings_file = backend_settings_path

            payload = service.backend_status_payload()

        self.assertEqual("openai_compatible", payload["backend_mode"])
        self.assertEqual("https://api.openai.com/v1", payload["openai_base_url"])
        self.assertEqual("gpt-5.5", payload["openai_model"])
        self.assertEqual(["gpt-5.5", "gpt-5.4"], payload["openai_models"])
        self.assertEqual(2, payload["openai_model_count"])
        self.assertTrue(payload["has_openai_api_key"])

    def test_update_backend_settings_persists_openai_compatible_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = mobile_portal.PortalService("127.0.0.1", 8765, "token")
            backend_settings_path = Path(temp_dir) / "token_pool_settings.json"
            token_dir = Path(temp_dir) / "tokens"
            service.backend_settings_file = backend_settings_path

            updated = service.update_backend_settings(
                backend_mode=token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE,
                token_dir=str(token_dir),
                proxy_port=8456,
                openai_base_url="https://api.openai.com/v1",
                openai_api_key="sk-test",
                openai_model="gpt-5.5",
                openai_models=["gpt-5.5", "gpt-5.4"],
            )

            loaded = token_pool_settings.load_backend_settings(backend_settings_path)

        self.assertEqual(token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE, updated["backend_mode"])
        self.assertEqual("https://api.openai.com/v1", loaded["openai_base_url"])
        self.assertEqual("sk-test", loaded["openai_api_key"])
        self.assertEqual("gpt-5.5", loaded["openai_model"])
        self.assertEqual(["gpt-5.5", "gpt-5.4"], loaded["openai_models"])

    def test_update_backend_settings_fetches_openai_models_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = mobile_portal.PortalService("127.0.0.1", 8765, "token")
            backend_settings_path = Path(temp_dir) / "token_pool_settings.json"
            service.backend_settings_file = backend_settings_path

            with mock.patch.object(
                token_pool_settings,
                "fetch_openai_compatible_models",
                return_value=["gpt-5.5", "gpt-4.1"],
            ) as fetch_openai_models:
                updated = service.update_backend_settings(
                    backend_mode=token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE,
                    token_dir=str(Path(temp_dir) / "tokens"),
                    proxy_port=8456,
                    openai_base_url="https://api.openai.com/v1",
                    openai_api_key="sk-test",
                    openai_model="gpt-5.5",
                )

            loaded = token_pool_settings.load_backend_settings(backend_settings_path)

        fetch_openai_models.assert_called_once_with("https://api.openai.com/v1", "sk-test")
        self.assertEqual(["gpt-5.5", "gpt-4.1"], loaded["openai_models"])
        self.assertEqual(["gpt-5.5", "gpt-4.1"], updated["openai_models"])


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


class PortalAuthorizationTests(unittest.TestCase):
    def _make_handler(self, *, portal_token: str, header_token: str = "", path: str = "/") -> mobile_portal.PortalHandler:
        handler = mobile_portal.PortalHandler.__new__(mobile_portal.PortalHandler)
        handler.headers = {"X-Access-Token": header_token}
        handler.path = path
        handler.server = SimpleNamespace(portal=SimpleNamespace(token=portal_token))
        return handler

    def test_is_authorized_accepts_exact_non_ascii_header_token(self) -> None:
        handler = self._make_handler(portal_token="令牌-测试", header_token="令牌-测试")

        self.assertTrue(handler._is_authorized())

    def test_is_authorized_accepts_exact_non_ascii_query_token(self) -> None:
        handler = self._make_handler(portal_token="令牌-测试", path="/api/bootstrap?token=%E4%BB%A4%E7%89%8C-%E6%B5%8B%E8%AF%95")

        self.assertTrue(handler._is_authorized())


class PortalBrowserControlTests(unittest.TestCase):
    def _make_handler(self, *, path: str, portal: object) -> mobile_portal.PortalHandler:
        handler = mobile_portal.PortalHandler.__new__(mobile_portal.PortalHandler)
        handler.headers = {}
        handler.path = path
        handler.server = SimpleNamespace(portal=portal)
        return handler

    def test_do_get_browser_attach_returns_attach_payload(self) -> None:
        portal = SimpleNamespace(
            token="token",
            browser_attach_payload=mock.Mock(return_value={"running": True, "matched": True}),
        )
        handler = self._make_handler(
            path="/api/browser/attach?browser=edge&hostname=dash.cloudflare.com&token=token",
            portal=portal,
        )

        with mock.patch.object(handler, "_send_json") as send_json:
            handler.do_GET()

        portal.browser_attach_payload.assert_called_once_with("edge", url_prefix="", hostname="dash.cloudflare.com")
        send_json.assert_called_once_with({"running": True, "matched": True})

    def test_do_post_browser_navigate_dispatches_action(self) -> None:
        portal = SimpleNamespace(
            token="token",
            perform_browser_action=mock.Mock(return_value={"ok": True}),
        )
        handler = self._make_handler(path="/api/browser/navigate?token=token", portal=portal)

        with mock.patch.object(
            handler,
            "_read_json_body",
            return_value={"browser": "edge", "hostname": "dash.cloudflare.com", "url": "https://example.com"},
        ), mock.patch.object(handler, "_send_json") as send_json:
            handler.do_POST()

        portal.perform_browser_action.assert_called_once_with(
            browser_name="edge",
            action="navigate",
            url_prefix="",
            hostname="dash.cloudflare.com",
            url="https://example.com",
            expression="",
            selector="",
            text="",
            key="",
            timeout_ms=5000,
        )
        send_json.assert_called_once_with({"ok": True})

    def test_do_post_browser_click_surfaces_bad_request(self) -> None:
        portal = SimpleNamespace(
            token="token",
            perform_browser_action=mock.Mock(side_effect=controlled_browser.ControlledBrowserError("Selector not found.")),
        )
        handler = self._make_handler(path="/api/browser/click?token=token", portal=portal)

        with mock.patch.object(handler, "_read_json_body", return_value={"browser": "edge", "selector": "#missing"}), \
             mock.patch.object(handler, "_send_json") as send_json:
            handler.do_POST()

        send_json.assert_called_once()
        payload = send_json.call_args.args[0]
        status = send_json.call_args.kwargs.get("status")
        self.assertEqual({"error": "Selector not found."}, payload)
        self.assertEqual(mobile_portal.HTTPStatus.BAD_REQUEST, status)

    def test_do_post_account_login_bind_dispatches_action(self) -> None:
        portal = SimpleNamespace(
            token="token",
            login_and_bind_account=mock.Mock(return_value={"active_slot": "slot-9"}),
        )
        handler = self._make_handler(path="/api/accounts/slot-9/login-bind?token=token", portal=portal)

        with mock.patch.object(handler, "_read_json_body", return_value={}), \
             mock.patch.object(handler, "_send_json") as send_json:
            handler.do_POST()

        portal.login_and_bind_account.assert_called_once_with("slot-9")
        send_json.assert_called_once_with({"active_slot": "slot-9"})

    def test_do_post_backend_dispatches_openai_compatible_fields(self) -> None:
        portal = SimpleNamespace(
            token="token",
            update_backend_settings=mock.Mock(return_value={"backend_mode": "openai_compatible"}),
        )
        handler = self._make_handler(path="/api/backend?token=token", portal=portal)

        with mock.patch.object(
            handler,
            "_read_json_body",
            return_value={
                "backend_mode": "openai_compatible",
                "token_dir": r"C:\tokens",
                "proxy_port": 8317,
                "openai_base_url": "https://api.openai.com/v1",
                "openai_api_key": "sk-test",
                "openai_model": "gpt-5.5",
            },
        ), mock.patch.object(handler, "_send_json") as send_json:
            handler.do_POST()

        portal.update_backend_settings.assert_called_once_with(
            backend_mode="openai_compatible",
            token_dir=r"C:\tokens",
            proxy_port=8317,
            openai_base_url="https://api.openai.com/v1",
            openai_api_key="sk-test",
            openai_model="gpt-5.5",
            openai_models=None,
        )
        send_json.assert_called_once_with({"backend_mode": "openai_compatible"})


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

        self.assertEqual(["resume", "-i", str(image_file), "session-1", "-"], args[-5:])
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

    def test_build_new_chat_args_uses_stdin_marker_for_prompt_text(self) -> None:
        args = mobile_portal.build_new_chat_args(
            output_file=Path("out.txt"),
            prompt="--help",
            model="gpt-5.4",
            sandbox="workspace-write",
            approval="never",
            reasoning_effort="high",
        )

        self.assertEqual("-", args[-1])
        self.assertIn("--skip-git-repo-check", args)
        self.assertIn('approval_policy="never"', args)


class ProxyEnvTests(unittest.TestCase):
    def test_build_codex_subprocess_env_defaults_to_local_proxy(self) -> None:
        with mock.patch.dict(mobile_portal.os.environ, {}, clear=True):
            env = mobile_portal.build_codex_subprocess_env()

        self.assertEqual("socks5h://127.0.0.1:7897", env["HTTP_PROXY"])
        self.assertEqual("socks5h://127.0.0.1:7897", env["HTTPS_PROXY"])
        self.assertEqual("socks5h://127.0.0.1:7897", env["ALL_PROXY"])
        self.assertEqual("localhost,127.0.0.1,::1", env["NO_PROXY"])

    def test_build_codex_subprocess_env_uses_saved_proxy_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_path = Path(temp_dir) / "mobile_portal_settings.json"
            mobile_portal.save_proxy_settings(True, 9003, settings_path)
            with mock.patch.dict(mobile_portal.os.environ, {"ALL_PROXY": "http://10.0.0.2:8888"}, clear=True):
                env = mobile_portal.build_codex_subprocess_env(settings_file=settings_path)

        self.assertEqual("socks5h://127.0.0.1:9003", env["ALL_PROXY"])

    def test_build_codex_subprocess_env_includes_token_pool_api_key_when_backend_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            proxy_settings_path = Path(temp_dir) / "mobile_portal_settings.json"
            backend_settings_path = Path(temp_dir) / "token_pool_settings.json"
            mobile_portal.save_proxy_settings(True, 9003, proxy_settings_path)
            token_pool_settings.save_backend_settings(
                token_pool_settings.BACKEND_MODE_TOKEN_POOL,
                settings_file=backend_settings_path,
                token_dir=Path(temp_dir) / "tokens",
                proxy_port=8317,
                proxy_api_key="pool-api-key",
            )

            env = mobile_portal.build_codex_subprocess_env(
                settings_file=proxy_settings_path,
                backend_settings_file=backend_settings_path,
            )

        self.assertEqual("pool-api-key", env["CODEX_TOKEN_POOL_API_KEY"])

    def test_build_codex_subprocess_env_includes_openai_compatible_api_key_when_backend_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            proxy_settings_path = Path(temp_dir) / "mobile_portal_settings.json"
            backend_settings_path = Path(temp_dir) / "token_pool_settings.json"
            mobile_portal.save_proxy_settings(True, 9003, proxy_settings_path)
            token_pool_settings.save_backend_settings(
                token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE,
                settings_file=backend_settings_path,
                token_dir=Path(temp_dir) / "tokens",
                proxy_port=8317,
                proxy_api_key="pool-api-key",
                openai_base_url="https://api.openai.com/v1",
                openai_api_key="sk-openai",
                openai_model="gpt-5.5",
                openai_models=["gpt-5.5"],
            )

            env = mobile_portal.build_codex_subprocess_env(
                settings_file=proxy_settings_path,
                backend_settings_file=backend_settings_path,
            )

        self.assertEqual("sk-openai", env["CODEX_OPENAI_COMPATIBLE_API_KEY"])


class TokenPoolBackendStartupTests(unittest.TestCase):
    def test_build_token_pool_proxy_command_falls_back_to_current_python_when_conda_env_missing(self) -> None:
        with mock.patch.object(mobile_portal.shutil, "which", return_value="C:\Miniconda\Scripts\conda.exe"), \
             mock.patch.object(mobile_portal, "conda_env_available", return_value=False):
            command = mobile_portal.build_token_pool_proxy_command(
                executable="C:\Python311\python.exe",
                app_path="D:\codex\manger\mobile_portal.py",
                port=8317,
                api_key="pool-api-key",
                token_dir="C:\tokens",
            )

        self.assertEqual("C:\Python311\python.exe", command[0])
        self.assertNotIn("conda.exe", " ".join(command))

    def test_build_token_pool_proxy_command_uses_conda_when_target_env_exists(self) -> None:
        with mock.patch.object(mobile_portal.shutil, "which", return_value="C:\Miniconda\Scripts\conda.exe"), \
             mock.patch.object(mobile_portal, "conda_env_available", return_value=True):
            command = mobile_portal.build_token_pool_proxy_command(
                executable="C:\Python311\python.exe",
                app_path="D:\codex\manger\mobile_portal.py",
                port=8317,
                api_key="pool-api-key",
                token_dir="C:\tokens",
            )

        self.assertEqual("C:\Miniconda\Scripts\conda.exe", command[0])
        self.assertIn("codex-accel", command)

    def test_build_arg_parser_accepts_token_pool_proxy_mode(self) -> None:
        args = mobile_portal.build_arg_parser().parse_args(
            [
                "--token-pool-proxy",
                "--port",
                "8317",
                "--api-key",
                "pool-api-key",
                "--token-dir",
                "C:\\tokens",
            ]
        )

        self.assertTrue(args.token_pool_proxy)
        self.assertEqual(8317, args.port)
        self.assertEqual("pool-api-key", args.api_key)
        self.assertEqual("C:\\tokens", args.token_dir)

    def test_main_delegates_to_token_pool_proxy_main_when_proxy_mode_enabled(self) -> None:
        with mock.patch.object(mobile_portal.token_pool_proxy, "main", return_value=0) as proxy_main:
            result = mobile_portal.main(
                [
                    "--token-pool-proxy",
                    "--port",
                    "8317",
                    "--api-key",
                    "pool-api-key",
                    "--token-dir",
                    "C:\\tokens",
                ]
            )

        self.assertEqual(0, result)
        proxy_main.assert_called_once_with(
            [
                "--port",
                "8317",
                "--api-key",
                "pool-api-key",
                "--token-dir",
                "C:\\tokens",
            ]
        )

    def test_start_token_pool_backend_surfaces_early_process_exit_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            backend_settings_path = Path(temp_dir) / "token_pool_settings.json"
            proxy_settings_path = Path(temp_dir) / "mobile_portal_settings.json"
            token_dir = Path(temp_dir) / "tokens"
            token_dir.mkdir()
            (token_dir / "token-a.json").write_text('{"token":"abc"}', encoding="utf-8")
            token_pool_settings.save_backend_settings(
                token_pool_settings.BACKEND_MODE_TOKEN_POOL,
                settings_file=backend_settings_path,
                token_dir=token_dir,
                proxy_port=8317,
                proxy_api_key="pool-api-key",
            )
            fake_proc = mock.Mock()
            fake_proc.pid = 4321
            fake_proc.poll.return_value = 7
            fake_proc.returncode = 7
            fake_proc.stdout = io.StringIO("ModuleNotFoundError: no module named x")

            with mock.patch.object(mobile_portal, "token_pool_proxy_is_healthy", return_value=None), \
                 mock.patch.object(mobile_portal, "build_token_pool_proxy_command", return_value=["python", "mobile_portal.py"]), \
                 mock.patch.object(mobile_portal, "save_token_pool_proxy_state"), \
                 mock.patch.object(mobile_portal.subprocess, "Popen", return_value=fake_proc):
                with self.assertRaisesRegex(RuntimeError, "ModuleNotFoundError"):
                    mobile_portal.start_token_pool_backend(
                        backend_settings_file=backend_settings_path,
                        proxy_settings_file=proxy_settings_path,
                    )


class BackendOverrideArgsTests(unittest.TestCase):
    def test_build_backend_override_args_returns_empty_when_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            backend_settings_path = Path(temp_dir) / "token_pool_settings.json"
            token_pool_settings.save_backend_settings(
                token_pool_settings.BACKEND_MODE_CODEX_AUTH,
                settings_file=backend_settings_path,
                token_dir=Path(temp_dir) / "tokens",
                proxy_port=8317,
                proxy_api_key="pool-api-key",
            )

            args = mobile_portal.build_backend_override_args(backend_settings_file=backend_settings_path)

        self.assertEqual([], args)

    def test_build_backend_override_args_points_codex_to_local_token_pool_proxy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            backend_settings_path = Path(temp_dir) / "token_pool_settings.json"
            token_pool_settings.save_backend_settings(
                token_pool_settings.BACKEND_MODE_TOKEN_POOL,
                settings_file=backend_settings_path,
                token_dir=Path(temp_dir) / "tokens",
                proxy_port=8319,
                proxy_api_key="pool-api-key",
            )

            args = mobile_portal.build_backend_override_args(backend_settings_file=backend_settings_path)

        rendered = " ".join(args)
        self.assertIn('model_provider="built_in_token_pool"', rendered)
        self.assertIn('model_providers.built_in_token_pool.base_url="http://127.0.0.1:8319"', rendered)
        self.assertIn('model_providers.built_in_token_pool.env_key="CODEX_TOKEN_POOL_API_KEY"', rendered)

    def test_build_backend_override_args_points_codex_to_openai_compatible_base_url(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            backend_settings_path = Path(temp_dir) / "token_pool_settings.json"
            token_pool_settings.save_backend_settings(
                token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE,
                settings_file=backend_settings_path,
                token_dir=Path(temp_dir) / "tokens",
                proxy_port=8317,
                proxy_api_key="pool-api-key",
                openai_base_url="https://api.openai.com/v1",
                openai_api_key="sk-openai",
                openai_model="gpt-5.5",
                openai_models=["gpt-5.5"],
            )

            args = mobile_portal.build_backend_override_args(backend_settings_file=backend_settings_path)

        rendered = " ".join(args)
        self.assertIn('model_provider="openai_compatible"', rendered)
        self.assertIn('model_providers.openai_compatible.base_url="https://api.openai.com/v1"', rendered)
        self.assertIn('model_providers.openai_compatible.env_key="CODEX_OPENAI_COMPATIBLE_API_KEY"', rendered)


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


class ControlledBrowserAttachTests(unittest.TestCase):
    def test_get_controlled_browser_debug_url_returns_expected_ports(self) -> None:
        self.assertEqual("http://127.0.0.1:9222", mobile_portal.get_controlled_browser_debug_url("edge"))
        self.assertEqual("http://127.0.0.1:9223", mobile_portal.get_controlled_browser_debug_url("chrome"))

    def test_list_controlled_browser_pages_filters_only_page_entries(self) -> None:
        payload = """
        [
          {"type": "page", "url": "https://example.com", "title": "Example", "id": "1"},
          {"type": "iframe", "url": "https://ignored.example", "title": "Ignored", "id": "2"}
        ]
        """

        with mock.patch("mobile_portal.fetch_json_text", return_value=payload):
            pages = mobile_portal.list_controlled_browser_pages("edge")

        self.assertEqual(1, len(pages))
        self.assertEqual("https://example.com", pages[0]["url"])

    def test_select_controlled_browser_page_prefers_url_prefix_match(self) -> None:
        pages = [
            {"type": "page", "url": "https://example.com/login", "title": "Login"},
            {"type": "page", "url": "https://dash.cloudflare.com/one/", "title": "Cloudflare"},
        ]

        selected = mobile_portal.select_controlled_browser_page(
            pages,
            url_prefix="https://dash.cloudflare.com/",
        )

        self.assertEqual("https://dash.cloudflare.com/one/", selected["url"])

    def test_select_controlled_browser_page_prefers_hostname_match_when_prefix_missing(self) -> None:
        pages = [
            {"type": "page", "url": "https://example.com/login", "title": "Login"},
            {"type": "page", "url": "https://dash.cloudflare.com/one/", "title": "Cloudflare"},
        ]

        selected = mobile_portal.select_controlled_browser_page(pages, hostname="dash.cloudflare.com")

        self.assertEqual("https://dash.cloudflare.com/one/", selected["url"])

    def test_select_controlled_browser_page_falls_back_to_first_non_blank_page(self) -> None:
        pages = [
            {"type": "page", "url": "about:blank", "title": ""},
            {"type": "page", "url": "https://example.com", "title": "Example"},
        ]

        selected = mobile_portal.select_controlled_browser_page(pages)

        self.assertEqual("https://example.com", selected["url"])

    def test_select_controlled_browser_page_raises_when_no_usable_page_exists(self) -> None:
        pages = [{"type": "page", "url": "about:blank", "title": ""}]

        with self.assertRaisesRegex(RuntimeError, "No usable controlled browser page found"):
            mobile_portal.select_controlled_browser_page(pages)

    def test_describe_controlled_browser_attach_returns_running_match_status(self) -> None:
        pages = [
            {"type": "page", "url": "https://dash.cloudflare.com/one/", "title": "Cloudflare", "id": "abc"}
        ]

        with mock.patch("mobile_portal.list_controlled_browser_pages", return_value=pages):
            result = mobile_portal.describe_controlled_browser_attach(
                "edge",
                url_prefix="https://dash.cloudflare.com/",
            )

        self.assertTrue(result["running"])
        self.assertTrue(result["matched"])
        self.assertEqual("https://dash.cloudflare.com/one/", result["selected_page"]["url"])

    def test_describe_controlled_browser_attach_reports_unavailable_browser(self) -> None:
        with mock.patch("mobile_portal.list_controlled_browser_pages", side_effect=RuntimeError("debug endpoint unavailable")):
            result = mobile_portal.describe_controlled_browser_attach("edge")

        self.assertFalse(result["running"])
        self.assertFalse(result["matched"])
        self.assertEqual("debug endpoint unavailable", result["error"])

    def test_describe_controlled_browser_attach_reports_running_browser_without_match(self) -> None:
        pages = [{"type": "page", "url": "about:blank", "title": "", "id": "blank"}]

        with mock.patch("mobile_portal.list_controlled_browser_pages", return_value=pages):
            result = mobile_portal.describe_controlled_browser_attach(
                "edge",
                url_prefix="https://dash.cloudflare.com/",
            )

        self.assertTrue(result["running"])
        self.assertFalse(result["matched"])
        self.assertEqual(1, result["page_count"])
        self.assertIn("No usable controlled browser page found", result["error"])


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


class LoadMessagesTests(unittest.TestCase):
    def test_load_messages_includes_user_messages_from_session_file_when_history_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            history_file = temp_root / "history.jsonl"
            sessions_dir = temp_root / "sessions" / "2026" / "03" / "19"
            sessions_dir.mkdir(parents=True)
            session_file = sessions_dir / "rollout-session-1.jsonl"
            session_file.write_text(
                "\n".join(
                    [
                        mobile_portal.json.dumps(
                            {
                                "timestamp": "2026-03-19T07:00:00.000Z",
                                "type": "session_meta",
                                "payload": {"id": "session-1"},
                            },
                            ensure_ascii=False,
                        ),
                        mobile_portal.json.dumps(
                            {
                                "timestamp": "2026-03-19T07:00:01.000Z",
                                "type": "response_item",
                                "payload": {
                                    "type": "message",
                                    "role": "user",
                                    "content": [{"type": "input_text", "text": "hello from file"}],
                                },
                            },
                            ensure_ascii=False,
                        ),
                        mobile_portal.json.dumps(
                            {
                                "timestamp": "2026-03-19T07:00:02.000Z",
                                "type": "response_item",
                                "payload": {
                                    "type": "message",
                                    "role": "assistant",
                                    "phase": "final_answer",
                                    "content": [{"type": "output_text", "text": "reply from file"}],
                                },
                            },
                            ensure_ascii=False,
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            with mock.patch.object(mobile_portal, "HISTORY_FILE", history_file), \
                    mock.patch.object(mobile_portal, "SESSIONS_DIR", temp_root / "sessions"):
                store = mobile_portal.CodexDataStore()
                messages = store.load_messages("session-1")

        self.assertEqual(
            [
                {"role": "user", "text": "hello from file"},
                {"role": "assistant", "text": "reply from file"},
            ],
            [{"role": item["role"], "text": item["text"]} for item in messages],
        )

    def test_load_messages_deduplicates_user_messages_present_in_history_and_session_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            history_file = temp_root / "history.jsonl"
            history_file.write_text(
                mobile_portal.json.dumps(
                    {
                        "session_id": "session-1",
                        "ts": mobile_portal.iso_to_ts("2026-03-19T07:00:01.000Z"),
                        "text": "same prompt",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            sessions_dir = temp_root / "sessions" / "2026" / "03" / "19"
            sessions_dir.mkdir(parents=True)
            session_file = sessions_dir / "rollout-session-1.jsonl"
            session_file.write_text(
                "\n".join(
                    [
                        mobile_portal.json.dumps(
                            {
                                "timestamp": "2026-03-19T07:00:00.000Z",
                                "type": "session_meta",
                                "payload": {"id": "session-1"},
                            },
                            ensure_ascii=False,
                        ),
                        mobile_portal.json.dumps(
                            {
                                "timestamp": "2026-03-19T07:00:01.000Z",
                                "type": "response_item",
                                "payload": {
                                    "type": "message",
                                    "role": "user",
                                    "content": [{"type": "input_text", "text": "same prompt"}],
                                },
                            },
                            ensure_ascii=False,
                        ),
                        mobile_portal.json.dumps(
                            {
                                "timestamp": "2026-03-19T07:00:02.000Z",
                                "type": "response_item",
                                "payload": {
                                    "type": "message",
                                    "role": "assistant",
                                    "phase": "final_answer",
                                    "content": [{"type": "output_text", "text": "reply from file"}],
                                },
                            },
                            ensure_ascii=False,
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            with mock.patch.object(mobile_portal, "HISTORY_FILE", history_file), \
                    mock.patch.object(mobile_portal, "SESSIONS_DIR", temp_root / "sessions"):
                store = mobile_portal.CodexDataStore()
                messages = store.load_messages("session-1")

        self.assertEqual(
            [
                {"role": "user", "text": "same prompt"},
                {"role": "assistant", "text": "reply from file"},
            ],
            [{"role": item["role"], "text": item["text"]} for item in messages],
        )
    def test_load_messages_ignores_internal_session_context_messages(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            history_file = temp_root / "history.jsonl"
            sessions_dir = temp_root / "sessions" / "2026" / "03" / "19"
            sessions_dir.mkdir(parents=True)
            session_file = sessions_dir / "rollout-session-1.jsonl"
            session_file.write_text(
                "\n".join(
                    [
                        mobile_portal.json.dumps(
                            {
                                "timestamp": "2026-03-19T07:00:00.000Z",
                                "type": "session_meta",
                                "payload": {"id": "session-1"},
                            },
                            ensure_ascii=False,
                        ),
                        mobile_portal.json.dumps(
                            {
                                "timestamp": "2026-03-19T07:00:01.000Z",
                                "type": "response_item",
                                "payload": {
                                    "type": "message",
                                    "role": "user",
                                    "content": [
                                        {
                                            "type": "input_text",
                                            "text": "# AGENTS.md instructions for C:\Windows\System32",
                                        }
                                    ],
                                },
                            },
                            ensure_ascii=False,
                        ),
                        mobile_portal.json.dumps(
                            {
                                "timestamp": "2026-03-19T07:00:02.000Z",
                                "type": "response_item",
                                "payload": {
                                    "type": "message",
                                    "role": "user",
                                    "content": [
                                        {
                                            "type": "input_text",
                                            "text": "<environment_context>\n<cwd>C:\Windows\System32</cwd>\n</environment_context>",
                                        }
                                    ],
                                },
                            },
                            ensure_ascii=False,
                        ),
                        mobile_portal.json.dumps(
                            {
                                "timestamp": "2026-03-19T07:00:03.000Z",
                                "type": "response_item",
                                "payload": {
                                    "type": "message",
                                    "role": "user",
                                    "content": [{"type": "input_text", "text": "real user prompt"}],
                                },
                            },
                            ensure_ascii=False,
                        ),
                        mobile_portal.json.dumps(
                            {
                                "timestamp": "2026-03-19T07:00:04.000Z",
                                "type": "response_item",
                                "payload": {
                                    "type": "message",
                                    "role": "assistant",
                                    "phase": "final_answer",
                                    "content": [{"type": "output_text", "text": "real reply"}],
                                },
                            },
                            ensure_ascii=False,
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            with mock.patch.object(mobile_portal, "HISTORY_FILE", history_file), \
                    mock.patch.object(mobile_portal, "SESSIONS_DIR", temp_root / "sessions"):
                store = mobile_portal.CodexDataStore()
                messages = store.load_messages("session-1")

        self.assertEqual(
            [
                {"role": "user", "text": "real user prompt"},
                {"role": "assistant", "text": "real reply"},
            ],
            [{"role": item["role"], "text": item["text"]} for item in messages],
        )

    def test_load_messages_falls_back_to_task_complete_last_agent_message_when_final_answer_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            history_file = temp_root / "history.jsonl"
            sessions_dir = temp_root / "sessions" / "2026" / "03" / "19"
            sessions_dir.mkdir(parents=True)
            session_file = sessions_dir / "rollout-session-1.jsonl"
            session_file.write_text(
                "\n".join(
                    [
                        mobile_portal.json.dumps(
                            {
                                "timestamp": "2026-03-19T07:00:00.000Z",
                                "type": "session_meta",
                                "payload": {"id": "session-1"},
                            },
                            ensure_ascii=False,
                        ),
                        mobile_portal.json.dumps(
                            {
                                "timestamp": "2026-03-19T07:00:01.000Z",
                                "type": "response_item",
                                "payload": {
                                    "type": "message",
                                    "role": "user",
                                    "content": [{"type": "input_text", "text": "need link"}],
                                },
                            },
                            ensure_ascii=False,
                        ),
                        mobile_portal.json.dumps(
                            {
                                "timestamp": "2026-03-19T07:00:03.000Z",
                                "type": "event_msg",
                                "payload": {
                                    "type": "task_complete",
                                    "turn_id": "turn-1",
                                    "last_agent_message": "http://example.test/file.zip",
                                },
                            },
                            ensure_ascii=False,
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            with mock.patch.object(mobile_portal, "HISTORY_FILE", history_file), \
                    mock.patch.object(mobile_portal, "SESSIONS_DIR", temp_root / "sessions"):
                store = mobile_portal.CodexDataStore()
                messages = store.load_messages("session-1")

        self.assertEqual(
            [
                {"role": "user", "text": "need link"},
                {"role": "assistant", "text": "http://example.test/file.zip"},
            ],
            [{"role": item["role"], "text": item["text"]} for item in messages],
        )

    def test_load_messages_falls_back_to_last_assistant_message_when_task_complete_is_null(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            history_file = temp_root / "history.jsonl"
            sessions_dir = temp_root / "sessions" / "2026" / "03" / "19"
            sessions_dir.mkdir(parents=True)
            session_file = sessions_dir / "rollout-session-1.jsonl"
            session_file.write_text(
                "\n".join(
                    [
                        mobile_portal.json.dumps(
                            {
                                "timestamp": "2026-03-19T07:00:00.000Z",
                                "type": "session_meta",
                                "payload": {"id": "session-1"},
                            },
                            ensure_ascii=False,
                        ),
                        mobile_portal.json.dumps(
                            {
                                "timestamp": "2026-03-19T07:00:01.000Z",
                                "type": "response_item",
                                "payload": {
                                    "type": "message",
                                    "role": "user",
                                    "content": [{"type": "input_text", "text": "same link again"}],
                                },
                            },
                            ensure_ascii=False,
                        ),
                        mobile_portal.json.dumps(
                            {
                                "timestamp": "2026-03-19T07:00:02.000Z",
                                "type": "response_item",
                                "payload": {
                                    "type": "message",
                                    "role": "assistant",
                                    "phase": "commentary",
                                    "content": [{"type": "output_text", "text": "service still on 8877"}],
                                },
                            },
                            ensure_ascii=False,
                        ),
                        mobile_portal.json.dumps(
                            {
                                "timestamp": "2026-03-19T07:00:03.000Z",
                                "type": "event_msg",
                                "payload": {
                                    "type": "task_complete",
                                    "turn_id": "turn-1",
                                    "last_agent_message": None,
                                },
                            },
                            ensure_ascii=False,
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            with mock.patch.object(mobile_portal, "HISTORY_FILE", history_file), \
                    mock.patch.object(mobile_portal, "SESSIONS_DIR", temp_root / "sessions"):
                store = mobile_portal.CodexDataStore()
                messages = store.load_messages("session-1")

        self.assertEqual(
            [
                {"role": "user", "text": "same link again"},
                {"role": "assistant", "text": "service still on 8877"},
            ],
            [{"role": item["role"], "text": item["text"]} for item in messages],
        )

    def test_load_messages_keeps_task_complete_fallback_when_user_message_already_exists_in_history(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            history_file = temp_root / "history.jsonl"
            history_file.write_text(
                mobile_portal.json.dumps(
                    {
                        "session_id": "session-1",
                        "ts": mobile_portal.iso_to_ts("2026-03-19T07:00:01.000Z"),
                        "text": "测试啊。是卡住了吗",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            sessions_dir = temp_root / "sessions" / "2026" / "03" / "19"
            sessions_dir.mkdir(parents=True)
            session_file = sessions_dir / "rollout-session-1.jsonl"
            session_file.write_text(
                "\n".join(
                    [
                        mobile_portal.json.dumps(
                            {
                                "timestamp": "2026-03-19T07:00:00.000Z",
                                "type": "session_meta",
                                "payload": {"id": "session-1"},
                            },
                            ensure_ascii=False,
                        ),
                        mobile_portal.json.dumps(
                            {
                                "timestamp": "2026-03-19T07:00:01.000Z",
                                "type": "response_item",
                                "payload": {
                                    "type": "message",
                                    "role": "user",
                                    "content": [{"type": "input_text", "text": "测试啊。是卡住了吗"}],
                                },
                            },
                            ensure_ascii=False,
                        ),
                        mobile_portal.json.dumps(
                            {
                                "timestamp": "2026-03-19T07:00:02.000Z",
                                "type": "response_item",
                                "payload": {
                                    "type": "message",
                                    "role": "assistant",
                                    "phase": "commentary",
                                    "content": [{"type": "output_text", "text": "没卡住，轻量测试已经跑完并且通过了。"}],
                                },
                            },
                            ensure_ascii=False,
                        ),
                        mobile_portal.json.dumps(
                            {
                                "timestamp": "2026-03-19T07:00:03.000Z",
                                "type": "response_item",
                                "payload": {
                                    "type": "message",
                                    "role": "assistant",
                                    "phase": "final_answer",
                                    "content": [{"type": "output_text", "text": ""}],
                                },
                            },
                            ensure_ascii=False,
                        ),
                        mobile_portal.json.dumps(
                            {
                                "timestamp": "2026-03-19T07:00:04.000Z",
                                "type": "event_msg",
                                "payload": {
                                    "type": "task_complete",
                                    "turn_id": "turn-1",
                                    "last_agent_message": "没卡住，轻量测试已经跑完并且通过了。",
                                },
                            },
                            ensure_ascii=False,
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            with mock.patch.object(mobile_portal, "HISTORY_FILE", history_file), \
                    mock.patch.object(mobile_portal, "SESSIONS_DIR", temp_root / "sessions"):
                store = mobile_portal.CodexDataStore()
                messages = store.load_messages("session-1")

        self.assertEqual(
            [
                {"role": "user", "text": "测试啊。是卡住了吗"},
                {"role": "assistant", "text": "没卡住，轻量测试已经跑完并且通过了。"},
            ],
            [{"role": item["role"], "text": item["text"]} for item in messages],
        )

class MobileBackendLaunchTests(unittest.TestCase):
    def test_run_resume_job_ensures_token_pool_backend_ready(self) -> None:
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

        with mock.patch.object(mobile_portal, "ensure_token_pool_backend_ready", create=True) as ensure_ready, \
             mock.patch.object(mobile_portal, "build_resume_args", return_value=["codex.cmd", "exec"]), \
             mock.patch.object(runner, "_run_codex_process", return_value="session-1"), \
             mock.patch("mobile_portal.tempfile.mkstemp", return_value=(1, str(Path(tempfile.gettempdir()) / "portal-out-1.txt"))), \
             mock.patch.object(Path, "unlink", return_value=None):
            runner._run_resume_job(
                "job-1",
                str(Path.cwd()),
                "session-1",
                "hello",
                "default",
                "default",
                "default",
                "default",
                [],
            )

        ensure_ready.assert_called_once()

    def test_run_new_chat_job_ensures_token_pool_backend_ready(self) -> None:
        runner = mobile_portal.JobRunner(_FakeStore())
        runner.jobs["job-1"] = {
            "job_id": "job-1",
            "status": "running",
            "kind": "new_chat",
            "session_id": "",
            "created_at": mobile_portal.now_ts(),
            "heartbeat_at": mobile_portal.now_ts(),
            "pid": 0,
            "error": "",
            "last_message": "",
            "log_tail": [],
            "live_text": "",
            "live_chunks_version": 0,
            "note": "",
            "opening_prompt": "hello",
            "opening_prompt_recorded": False,
        }

        with mock.patch.object(mobile_portal, "ensure_token_pool_backend_ready", create=True) as ensure_ready, \
             mock.patch.object(mobile_portal, "build_new_chat_args", return_value=["codex.cmd", "exec"]), \
             mock.patch.object(runner, "_run_codex_process", return_value="session-1"), \
             mock.patch("mobile_portal.tempfile.mkstemp", return_value=(1, str(Path(tempfile.gettempdir()) / "portal-out-2.txt"))), \
             mock.patch.object(Path, "unlink", return_value=None):
            runner._run_new_chat_job(
                "job-1",
                str(Path.cwd()),
                "hello",
                "default",
                "default",
                "default",
                "default",
            )

        ensure_ready.assert_called_once()


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
