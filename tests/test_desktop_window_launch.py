import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app
import token_pool_settings
import window_runtime


class FakeVar:
    def __init__(self, value: object) -> None:
        self.value = value

    def get(self) -> object:
        return self.value

    def set(self, value: object) -> None:
        self.value = value


def make_manager() -> app.SessionManagerApp:
    manager = object.__new__(app.SessionManagerApp)
    manager.use_global_defaults_var = FakeVar(False)
    manager.model_var = FakeVar("snapshot-model")
    manager.approval_var = FakeVar("never")
    manager.sandbox_var = FakeVar("danger-full-access")
    manager.reasoning_effort_var = FakeVar("high")
    manager.search_var = FakeVar(False)
    manager.use_proxy_var = FakeVar(False)
    manager.proxy_scheme_var = FakeVar("socks5h")
    manager.proxy_host_var = FakeVar("127.0.0.1")
    manager.proxy_port_var = FakeVar("7897")
    manager.admin_var = FakeVar(False)
    manager.status_var = FakeVar("")
    return manager


def make_runtime(root: Path, *, isolated: bool = True, session_id: str = "") -> window_runtime.WindowRuntime:
    runtime_root = root / "window_profiles"
    runtime_dir = runtime_root / "launch-test"
    return window_runtime.WindowRuntime(
        launch_id="launch-test",
        runtime_root=runtime_root,
        runtime_dir=runtime_dir,
        codex_home=runtime_dir / "home" if isolated else root,
        sqlite_home=root,
        isolated=isolated,
        session_id=session_id,
    )


def make_session(session_id: str = "session-test") -> app.SessionItem:
    return app.SessionItem(
        session_id=session_id,
        ts=0,
        text="",
        note="",
        history_count=1,
        cwd="D:\\workspace",
        model="snapshot-model",
        approval_policy="never",
        sandbox_mode="danger-full-access",
        turn_id="",
        session_file="",
    )


class DesktopWindowLaunchTests(unittest.TestCase):
    def openai_settings(self) -> dict[str, object]:
        return {
            "backend_mode": token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE,
            "openai_base_url": "https://snapshot.invalid/v1",
            "openai_api_key": "snapshot-key",
            "openai_model": "snapshot-model",
            "openai_models": ["snapshot-model"],
            "openai_protocol": token_pool_settings.OPENAI_PROTOCOL_RESPONSES,
            "proxy_preference": "direct",
            "installation_id": "snapshot-installation",
        }

    def test_new_args_use_explicit_snapshot_without_reloading_settings(self) -> None:
        manager = make_manager()
        manager._token_pool_settings = mock.Mock(side_effect=AssertionError("settings reloaded"))
        settings = self.openai_settings()

        with mock.patch.object(
            manager,
            "_ensure_openai_compatible_launch_model_metadata",
        ) as ensure_metadata:
            args = manager._build_codex_new_args(settings)

        self.assertIn("snapshot-model", args)
        self.assertIn(
            'model_providers.openai_compatible.base_url="https://snapshot.invalid/v1"',
            args,
        )
        ensure_metadata.assert_called_once_with(settings, "snapshot-model")
        manager._token_pool_settings.assert_not_called()

    def test_terminal_command_binds_runtime_and_uses_same_snapshot(self) -> None:
        manager = make_manager()
        manager._token_pool_settings = mock.Mock(side_effect=AssertionError("settings reloaded"))
        manager._resolve_terminal_codex_args = mock.Mock(side_effect=lambda args, **_kwargs: args)
        settings = self.openai_settings()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runtime = make_runtime(root)

            command = manager._build_terminal_ps_command(
                "D:\\workspace",
                ["codex.cmd", "-m", "snapshot-model"],
                settings,
                runtime,
            )

        self.assertIn("snapshot-key", command)
        self.assertIn("$env:CODEX_HOME", command)
        self.assertIn(str(runtime.codex_home), command)
        self.assertIn("$env:CODEX_SQLITE_HOME", command)
        self.assertIn("finally {", command)
        manager._token_pool_settings.assert_not_called()

    def test_configured_codex_executable_reads_local_setting(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_file = Path(temp_dir) / "mobile_portal_settings.json"
            settings_file.write_text(
                '{"codex_executable":"%USERPROFILE%\\\\.codex\\\\bin\\\\codex-clickable.exe"}',
                encoding="utf-8",
            )

            with mock.patch.dict(os.environ, {"USERPROFILE": "C:\\Users\\Test"}):
                executable = app.configured_codex_executable(settings_file)

        self.assertEqual(
            Path("C:\\Users\\Test\\.codex\\bin\\codex-clickable.exe"),
            executable,
        )

    def test_configured_codex_executable_ignores_malformed_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_file = Path(temp_dir) / "mobile_portal_settings.json"
            settings_file.write_text("{not-json", encoding="utf-8")

            executable = app.configured_codex_executable(settings_file)

        self.assertIsNone(executable)

    def test_configured_codex_executable_ignores_missing_setting(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_file = Path(temp_dir) / "mobile_portal_settings.json"
            settings_file.write_text('{"proxy_enabled":false}', encoding="utf-8")

            executable = app.configured_codex_executable(settings_file)

        self.assertIsNone(executable)

    def test_configured_codex_executable_rejects_relative_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_file = Path(temp_dir) / "mobile_portal_settings.json"
            settings_file.write_text(
                '{"codex_executable":"bin\\\\codex-clickable.exe"}',
                encoding="utf-8",
            )

            executable = app.configured_codex_executable(settings_file)

        self.assertIsNone(executable)

    def test_configured_codex_file_opener_reads_supported_local_setting(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_file = Path(temp_dir) / "mobile_portal_settings.json"
            settings_file.write_text(
                '{"codex_file_opener":"explorer"}',
                encoding="utf-8",
            )

            opener = app.configured_codex_file_opener(settings_file)

        self.assertEqual("explorer", opener)

    def test_configured_codex_file_opener_rejects_unknown_setting(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_file = Path(temp_dir) / "mobile_portal_settings.json"
            settings_file.write_text(
                '{"codex_file_opener":"shell"}',
                encoding="utf-8",
            )

            opener = app.configured_codex_file_opener(settings_file)

        self.assertIsNone(opener)

    def test_codex_executable_health_check_rejects_missing_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            executable = Path(temp_dir) / "missing.exe"

            with mock.patch.object(app.subprocess, "run") as run:
                healthy = app.codex_executable_is_healthy(executable)

        self.assertFalse(healthy)
        run.assert_not_called()

    def test_codex_executable_health_check_requires_codex_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            executable = Path(temp_dir) / "codex-clickable.exe"
            executable.write_bytes(b"test")
            result = subprocess.CompletedProcess(
                args=[str(executable), "--version"],
                returncode=0,
                stdout="codex-cli 0.144.3\n",
                stderr="",
            )

            with mock.patch.object(app.subprocess, "run", return_value=result):
                healthy = app.codex_executable_is_healthy(executable)

        self.assertTrue(healthy)

    def test_codex_executable_health_check_rejects_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            executable = Path(temp_dir) / "codex-clickable.exe"
            executable.write_bytes(b"test")

            with mock.patch.object(
                app.subprocess,
                "run",
                side_effect=subprocess.TimeoutExpired(str(executable), 3),
            ):
                healthy = app.codex_executable_is_healthy(executable)

        self.assertFalse(healthy)

    def test_codex_executable_health_check_rejects_unexpected_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            executable = Path(temp_dir) / "codex-clickable.exe"
            executable.write_bytes(b"test")
            result = subprocess.CompletedProcess(
                args=[str(executable), "--version"],
                returncode=0,
                stdout="not-codex\n",
                stderr="",
            )

            with mock.patch.object(app.subprocess, "run", return_value=result):
                healthy = app.codex_executable_is_healthy(executable)

        self.assertFalse(healthy)

    def test_codex_executable_health_check_rejects_nonzero_exit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            executable = Path(temp_dir) / "codex-clickable.exe"
            executable.write_bytes(b"test")
            result = subprocess.CompletedProcess(
                args=[str(executable), "--version"],
                returncode=1,
                stdout="codex-cli 0.144.3\n",
                stderr="failed",
            )

            with mock.patch.object(app.subprocess, "run", return_value=result):
                healthy = app.codex_executable_is_healthy(executable)

        self.assertFalse(healthy)

    def test_healthy_configured_codex_executable_is_selected(self) -> None:
        manager = make_manager()
        custom = Path("C:\\local\\codex-clickable.exe")
        local_settings = app.CodexLocalLaunchSettings(
            executable=custom,
            file_opener=None,
            sqlite_home=app.CODEX_HOME,
            sqlite_isolated=False,
        )
        with (
            mock.patch.object(
                app,
                "load_codex_local_launch_settings",
                return_value=local_settings,
            ),
            mock.patch.object(
                app,
                "codex_executable_is_healthy",
                return_value=True,
            ),
        ):
            resolved = manager._resolve_terminal_codex_args(
                ["codex.cmd", "resume", "session-id"]
            )

        self.assertEqual(
            [str(custom), "resume", "session-id"],
            resolved,
        )

    def test_healthy_custom_executable_applies_configured_file_opener(self) -> None:
        manager = make_manager()
        custom = Path("C:\\local\\codex-clickable-explorer.exe")
        local_settings = app.CodexLocalLaunchSettings(
            executable=custom,
            file_opener="explorer",
            sqlite_home=app.CODEX_HOME,
            sqlite_isolated=False,
        )
        with (
            mock.patch.object(
                app,
                "load_codex_local_launch_settings",
                return_value=local_settings,
            ),
            mock.patch.object(
                app,
                "codex_executable_is_healthy",
                return_value=True,
            ),
        ):
            resolved = manager._resolve_terminal_codex_args(
                ["codex.cmd", "resume", "session-id"]
            )

        self.assertEqual(
            [
                str(custom),
                "resume",
                "session-id",
                "-c",
                'file_opener="explorer"',
            ],
            resolved,
        )

    def test_unhealthy_configured_codex_executable_falls_back_to_official(self) -> None:
        manager = make_manager()
        custom = Path("C:\\local\\broken.exe")
        local_settings = app.CodexLocalLaunchSettings(
            executable=custom,
            file_opener=None,
            sqlite_home=app.CODEX_HOME,
            sqlite_isolated=False,
        )
        with (
            mock.patch.object(
                app,
                "load_codex_local_launch_settings",
                return_value=local_settings,
            ),
            mock.patch.object(
                app,
                "codex_executable_is_healthy",
                return_value=False,
            ),
            mock.patch.object(
                app.shutil,
                "which",
                return_value="C:\\official\\codex.cmd",
            ),
        ):
            resolved = manager._resolve_terminal_codex_args(["codex.cmd"])

        self.assertEqual(["C:\\official\\codex.cmd"], resolved)

    def test_runtime_isolated_for_non_auth_backends_only(self) -> None:
        manager = make_manager()
        runtime = make_runtime(Path("D:\\runtime"))
        with mock.patch.object(
            app.window_runtime,
            "prepare_window_runtime",
            return_value=runtime,
        ) as prepare:
            auth_result = manager._prepare_window_runtime(
                {"backend_mode": token_pool_settings.BACKEND_MODE_CODEX_AUTH},
                session_id="auth-session",
            )
            custom_result = manager._prepare_window_runtime(
                self.openai_settings(),
                session_id="custom-session",
            )

        self.assertIs(runtime, auth_result)
        self.assertIs(runtime, custom_result)
        self.assertFalse(prepare.call_args_list[0].kwargs["isolate_home"])
        self.assertEqual("", prepare.call_args_list[0].kwargs["installation_id"])
        self.assertTrue(prepare.call_args_list[1].kwargs["isolate_home"])
        self.assertEqual(
            "snapshot-installation",
            prepare.call_args_list[1].kwargs["installation_id"],
        )

    def test_new_chat_captures_settings_once_for_the_entire_launch(self) -> None:
        manager = make_manager()
        source_settings = self.openai_settings()
        manager._token_pool_settings = mock.Mock(return_value=source_settings)
        manager._ensure_backend_ready = mock.Mock()
        manager._build_codex_new_args = mock.Mock(return_value=["codex.cmd"])
        runtime = make_runtime(Path("D:\\runtime"))
        manager._prepare_window_runtime = mock.Mock(return_value=runtime)
        manager._build_terminal_ps_command = mock.Mock(return_value="terminal-command")
        manager._launch_terminal_with_runtime = mock.Mock()

        with (
            mock.patch.object(app.filedialog, "askdirectory", return_value="D:\\workspace"),
            mock.patch.object(app, "launch_terminal_command"),
        ):
            manager.open_new_chat()

        manager._token_pool_settings.assert_called_once_with()
        captured = manager._ensure_backend_ready.call_args.args[0]
        self.assertIs(captured, manager._build_codex_new_args.call_args.args[0])
        self.assertIs(captured, manager._prepare_window_runtime.call_args.args[0])
        self.assertIs(captured, manager._build_terminal_ps_command.call_args.args[2])
        launch = manager._prepare_window_runtime.call_args.kwargs["codex_launch"]
        self.assertIs(
            launch,
            manager._build_terminal_ps_command.call_args.kwargs["codex_launch"],
        )
        manager._prepare_window_runtime.assert_called_once_with(
            captured,
            session_id="",
            codex_launch=launch,
        )
        manager._build_terminal_ps_command.assert_called_once_with(
            "D:\\workspace",
            ["codex.cmd"],
            captured,
            runtime,
            codex_launch=launch,
        )
        manager._launch_terminal_with_runtime.assert_called_once_with("terminal-command", runtime)

    def test_duplicate_resume_is_reported_without_launching_terminal(self) -> None:
        manager = make_manager()
        item = make_session("session-locked")
        manager._selected_session = mock.Mock(return_value=item)
        manager._portal_owner = mock.Mock(return_value=None)
        manager._token_pool_settings = mock.Mock(return_value=self.openai_settings())
        manager._ensure_backend_ready = mock.Mock()
        manager._build_codex_resume_args = mock.Mock(return_value=["codex.cmd"])
        manager._prepare_window_runtime = mock.Mock(
            side_effect=window_runtime.SessionAlreadyOpenError(item.session_id)
        )
        manager._build_terminal_ps_command = mock.Mock()
        manager._launch_terminal_with_runtime = mock.Mock()

        with (
            mock.patch.object(app.messagebox, "showinfo") as showinfo,
            mock.patch.object(app, "launch_terminal_command") as launch,
        ):
            manager.open_selected_admin()

        showinfo.assert_called_once()
        self.assertIn("already open", showinfo.call_args.args[1].lower())
        manager._build_terminal_ps_command.assert_not_called()
        manager._launch_terminal_with_runtime.assert_not_called()
        launch.assert_not_called()

    def test_terminal_launch_failure_cleans_runtime_immediately(self) -> None:
        manager = make_manager()
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = make_runtime(Path(temp_dir))
            with (
                mock.patch.object(
                    app,
                    "launch_terminal_command",
                    side_effect=OSError("launch failed"),
                ),
                mock.patch.object(app.window_runtime, "cleanup_window_runtime") as cleanup,
            ):
                with self.assertRaisesRegex(OSError, "launch failed"):
                    manager._launch_terminal_with_runtime("terminal-command", runtime)

        cleanup.assert_called_once_with(runtime.runtime_dir, runtime.runtime_root)

    def test_cleanup_failure_does_not_hide_terminal_launch_error(self) -> None:
        manager = make_manager()
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = make_runtime(Path(temp_dir))
            with (
                mock.patch.object(
                    app,
                    "launch_terminal_command",
                    side_effect=OSError("original launch failure"),
                ),
                mock.patch.object(
                    app.window_runtime,
                    "cleanup_window_runtime",
                    side_effect=window_runtime.WindowRuntimeError("cleanup failure"),
                ),
            ):
                with self.assertRaisesRegex(OSError, "original launch failure"):
                    manager._launch_terminal_with_runtime("terminal-command", runtime)

    def test_switching_to_auth_restores_the_baseline_installation_id(self) -> None:
        updated = {"backend_mode": token_pool_settings.BACKEND_MODE_CODEX_AUTH}
        with (
            mock.patch.object(
                token_pool_settings,
                "save_backend_settings",
                return_value=updated,
            ),
            mock.patch.object(app, "_patch_image_generation_for_backend_mode"),
            mock.patch.object(app, "_swap_installation_id_for_preset") as restore,
        ):
            result = app.apply_backend_mode_settings(
                backend_mode=token_pool_settings.BACKEND_MODE_CODEX_AUTH,
            )

        self.assertIs(updated, result)
        restore.assert_called_once_with({})

    def test_packaged_cleanup_mode_runs_without_starting_the_gui(self) -> None:
        with (
            mock.patch.object(
                app.sys,
                "argv",
                [
                    "CodexPlus.exe",
                    "--window-runtime-cleanup",
                    "--runtime-root",
                    "runtime-root",
                    "--runtime-dir",
                    "runtime-dir",
                ],
            ),
            mock.patch.object(app.window_runtime, "main", return_value=7) as cleanup_main,
            mock.patch.object(app.process_singleton, "cleanup_previous_project_instances") as singleton,
        ):
            result = app.main()

        self.assertEqual(7, result)
        cleanup_main.assert_called_once_with(
            [
                "cleanup",
                "--runtime-root",
                "runtime-root",
                "--runtime-dir",
                "runtime-dir",
            ]
        )
        singleton.assert_not_called()

    def test_source_cleanup_command_uses_the_safe_python_launcher(self) -> None:
        manager = make_manager()
        with (
            mock.patch.object(app.sys, "frozen", False, create=True),
            mock.patch.object(
                app,
                "build_source_python_command",
                return_value=["py.exe", "-3", "window_runtime.py"],
            ) as build_command,
        ):
            command = manager._runtime_cleanup_command()

        build_command.assert_called_once_with(
            app.sys.executable,
            str(app.APP_DIR / "window_runtime.py"),
        )
        self.assertEqual(
            ["py.exe", "-3", "window_runtime.py", "cleanup"],
            command,
        )


if __name__ == "__main__":
    unittest.main()
