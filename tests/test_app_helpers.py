import tempfile
import subprocess
import unittest
from pathlib import Path
from unittest import mock

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

    def test_slot_supports_direct_login_only_for_unbound_slots(self) -> None:
        self.assertTrue(app.slot_supports_direct_login({}))
        self.assertTrue(app.slot_supports_direct_login({"fingerprint": ""}))
        self.assertFalse(app.slot_supports_direct_login({"fingerprint": "bound"}))

    def test_format_quota_summary_uses_backend_text(self) -> None:
        summary = app.format_account_quota_summary({"summary": "Weekly quota: 76% used", "state": "ok"})

        self.assertEqual("Weekly quota: 76% used", summary)

    def test_account_dialog_dimensions_fit_within_screen(self) -> None:
        width, height = app.account_dialog_dimensions(screen_width=1920, screen_height=1080)

        self.assertEqual((720, 820), (width, height))

    def test_account_dialog_dimensions_keep_small_screens_usable(self) -> None:
        width, height = app.account_dialog_dimensions(screen_width=640, screen_height=480)

        self.assertEqual((560, 400), (width, height))

    def test_merge_available_models_promotes_gpt_5_5_without_losing_cached_entries(self) -> None:
        models = app.merge_available_models(["gpt-5.4", "gpt-5.4-mini", "gpt-5.3-codex"])

        self.assertEqual(
            ["gpt-5.5", "gpt-5.4", "gpt-5.4-mini", "gpt-5.3-codex", "gpt-5.2", "gpt-5"],
            models,
        )

    def test_build_codex_new_args_defaults_backend_override_to_gpt_5_5(self) -> None:
        manager = object.__new__(app.SessionManagerApp)
        manager.model_var = mock.Mock()
        manager.model_var.get.return_value = "default"
        manager._build_codex_override_args = mock.Mock(return_value=[])
        manager._build_backend_override_args = mock.Mock(return_value=[])

        app.SessionManagerApp._build_codex_new_args(manager)

        manager._build_backend_override_args.assert_called_once_with("gpt-5.5")

    def test_build_token_pool_provider_override_args_points_codex_to_local_proxy(self) -> None:
        args = app.build_token_pool_provider_override_args(
            model="gpt-5.4",
            proxy_port=8317,
            provider_name="built_in_token_pool",
            env_key_name="CODEX_TOKEN_POOL_API_KEY",
        )

        rendered = " ".join(args)
        self.assertIn('model_provider="built_in_token_pool"', rendered)
        self.assertIn('model_providers.built_in_token_pool.base_url="http://127.0.0.1:8317"', rendered)
        self.assertIn('model_providers.built_in_token_pool.env_key="CODEX_TOKEN_POOL_API_KEY"', rendered)
        self.assertIn('model_providers.built_in_token_pool.wire_api="responses"', rendered)
        self.assertIn('model_providers.built_in_token_pool.requires_openai_auth=false', rendered)
        self.assertIn('model_providers.built_in_token_pool.supports_websockets=false', rendered)

    def test_build_token_pool_environment_ps_prefix_sets_local_api_key(self) -> None:
        prefix = app.build_token_pool_environment_ps_prefix(
            env_key_name="CODEX_TOKEN_POOL_API_KEY",
            api_key_value="local-proxy-key",
        )

        self.assertIn("$env:CODEX_TOKEN_POOL_API_KEY='local-proxy-key'", prefix)

    def test_build_openai_compatible_provider_override_args_points_codex_to_custom_base_url(self) -> None:
        args = app.build_openai_compatible_provider_override_args(
            model="gpt-5.5",
            base_url="https://api.openai.com/v1",
            provider_name="openai_compatible",
            env_key_name="CODEX_OPENAI_COMPATIBLE_API_KEY",
        )

        rendered = " ".join(args)
        self.assertIn('model_provider="openai_compatible"', rendered)
        self.assertIn('model_providers.openai_compatible.base_url="https://api.openai.com/v1"', rendered)
        self.assertIn('model_providers.openai_compatible.env_key="CODEX_OPENAI_COMPATIBLE_API_KEY"', rendered)
        self.assertIn('model_providers.openai_compatible.wire_api="responses"', rendered)

    def test_load_backend_settings_preserves_openai_compatible_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_file = Path(temp_dir) / "token_pool_settings.json"

            saved = app.token_pool_settings.save_backend_settings(
                app.token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE,
                settings_file=settings_file,
                token_dir=Path(temp_dir) / "tokens",
                proxy_port=8317,
                proxy_api_key="pool-api-key",
                openai_base_url="https://api.openai.com/v1",
                openai_api_key="sk-test",
                openai_model="gpt-5.5",
                openai_models=["gpt-5.5", "gpt-5.4"],
            )
            loaded = app.token_pool_settings.load_backend_settings(settings_file)

        self.assertEqual(app.token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE, saved["backend_mode"])
        self.assertEqual("https://api.openai.com/v1", loaded["openai_base_url"])
        self.assertEqual("sk-test", loaded["openai_api_key"])
        self.assertEqual("gpt-5.5", loaded["openai_model"])
        self.assertEqual(["gpt-5.5", "gpt-5.4"], loaded["openai_models"])

    def test_load_available_models_prefers_openai_compatible_cache_when_backend_enabled(self) -> None:
        manager = object.__new__(app.SessionManagerApp)
        manager.backend_settings = {
            "backend_mode": "openai_compatible",
            "openai_models": ["gpt-5.5", "gpt-4.1"],
        }
        manager._reload_backend_settings = mock.Mock(return_value=manager.backend_settings)

        with mock.patch.object(app, "MODELS_CACHE_FILE", Path("missing-models-cache.json")):
            models = app.SessionManagerApp._load_available_models(manager)

        self.assertEqual(["gpt-5.5", "gpt-4.1", "gpt-5.4", "gpt-5.3-codex", "gpt-5.2", "gpt-5"], models)

    def test_build_token_pool_proxy_command_uses_app_script_in_source_mode(self) -> None:
        with mock.patch.object(app.shutil, "which", return_value=None):
            command = app.build_token_pool_proxy_command(
                executable="C:\\Python311\\python.exe",
                app_path="D:\\codex\\manger\\app.py",
                port=8317,
                api_key="local-proxy-key",
                token_dir="C:\\Users\\MECHREVO\\.cli-proxy-api",
                frozen=False,
            )

        self.assertEqual("C:\\Python311\\python.exe", command[0])
        self.assertEqual("D:\\codex\\manger\\app.py", command[1])
        self.assertIn("--token-pool-proxy", command)
        self.assertIn("--port", command)

    def test_build_token_pool_proxy_command_prefers_conda_env_when_available(self) -> None:
        with mock.patch.object(app.shutil, "which", return_value="C:\\Miniconda3\\condabin\\conda.bat"):
            command = app.build_token_pool_proxy_command(
                executable="C:\\Python311\\python.exe",
                app_path="D:\\codex\\manger\\app.py",
                port=8317,
                api_key="local-proxy-key",
                token_dir="C:\\Users\\MECHREVO\\.cli-proxy-api",
                frozen=False,
            )

        self.assertEqual("C:\\Miniconda3\\condabin\\conda.bat", command[0])
        self.assertEqual(["run", "--no-capture-output", "-n", "codex-accel", "python", "D:\\codex\\manger\\app.py"], command[1:7])
        self.assertIn("--token-pool-proxy", command)

    def test_build_token_pool_proxy_command_uses_executable_only_when_frozen(self) -> None:
        command = app.build_token_pool_proxy_command(
            executable="D:\\codex\\manger\\codex-session-manager.exe",
            app_path="D:\\codex\\manger\\app.py",
            port=8317,
            api_key="local-proxy-key",
            token_dir="C:\\Users\\MECHREVO\\.cli-proxy-api",
            frozen=True,
        )

        self.assertEqual("D:\\codex\\manger\\codex-session-manager.exe", command[0])
        self.assertNotIn("D:\\codex\\manger\\app.py", command)

    def test_run_codex_browser_login_uses_default_login_command(self) -> None:
        completed = subprocess.CompletedProcess(["codex.cmd", "login"], 0, stdout="ok")

        with mock.patch.object(app.subprocess, "run", return_value=completed) as run:
            result = app.run_codex_browser_login()

        self.assertIs(result, completed)
        run.assert_called_once_with(
            ["codex.cmd", "login"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="ignore",
            check=False,
        )

    def test_start_codex_browser_login_process_uses_default_login_command(self) -> None:
        fake_process = mock.Mock()

        with mock.patch.object(app.subprocess, "Popen", return_value=fake_process) as popen:
            result = app.start_codex_browser_login_process()

        self.assertIs(result, fake_process)
        popen.assert_called_once_with(
            ["codex.cmd", "login"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="ignore",
        )

    def test_login_and_bind_account_slot_saves_new_current_auth(self) -> None:
        completed = subprocess.CompletedProcess(["codex.cmd", "login"], 0, stdout="ok")

        with mock.patch.object(app.auth_slots, "load_slot_registry", return_value=[{"slot_id": "slot-9"}]), \
             mock.patch.object(app.auth_slots, "current_auth_info", side_effect=[{"fingerprint": "old"}, {"fingerprint": "new"}]), \
             mock.patch.object(app, "run_codex_browser_login", return_value=completed) as run_login, \
             mock.patch.object(app.auth_slots, "save_current_auth_to_slot", return_value={"slot_id": "slot-9", "email": "new@example.com"}) as save:
            result = app.login_and_bind_account_slot("slot-9")

        self.assertEqual("slot-9", result["slot_id"])
        run_login.assert_called_once_with()
        save.assert_called_once_with("slot-9")

    def test_login_and_bind_account_slot_rejects_unchanged_auth(self) -> None:
        completed = subprocess.CompletedProcess(["codex.cmd", "login"], 0, stdout="ok")

        with mock.patch.object(app.auth_slots, "load_slot_registry", return_value=[{"slot_id": "slot-9"}]), \
             mock.patch.object(app.auth_slots, "current_auth_info", side_effect=[{"fingerprint": "same"}, {"fingerprint": "same"}]), \
             mock.patch.object(app, "run_codex_browser_login", return_value=completed):
            with self.assertRaisesRegex(RuntimeError, "did not produce a new login"):
                app.login_and_bind_account_slot("slot-9")

    def test_main_dispatches_token_pool_proxy_mode(self) -> None:
        with mock.patch.object(app, "sys") as mocked_sys, mock.patch.object(app.token_pool_proxy, "main", return_value=7) as proxy_main:
            mocked_sys.argv = ["app.py", "--token-pool-proxy", "--port", "8317", "--api-key", "local", "--token-dir", "C:\\tokens"]

            result = app.main()

        self.assertEqual(7, result)
        proxy_main.assert_called_once_with(["--port", "8317", "--api-key", "local", "--token-dir", "C:\\tokens"])



if __name__ == "__main__":
    unittest.main()
