import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app
import custom_provider_proxy
import mobile_portal
import token_pool_proxy
import token_pool_settings
import window_runtime


class FakeVar:
    def __init__(self, value: object) -> None:
        self.value = value

    def get(self) -> object:
        return self.value


def make_manager() -> app.SessionManagerApp:
    manager = object.__new__(app.SessionManagerApp)
    manager.use_global_defaults_var = FakeVar(False)
    manager.model_var = FakeVar("gpt-5.6-sol")
    manager.approval_var = FakeVar("never")
    manager.sandbox_var = FakeVar("danger-full-access")
    manager.reasoning_effort_var = FakeVar("high")
    manager.search_var = FakeVar(False)
    return manager


class ContextWindowTests(unittest.TestCase):
    def test_gpt6_model_is_the_shared_default(self) -> None:
        self.assertEqual("gpt-6-astra", app.DEFAULT_PRIMARY_MODEL)
        self.assertEqual("gpt-6-astra", app.DEFAULT_LAUNCH_MODEL)
        self.assertEqual("gpt-6-astra", mobile_portal.DEFAULT_PRIMARY_MODEL)

    def test_context_override_is_512k_tokens_with_460k_compaction(self) -> None:
        self.assertEqual(
            [
                "-c",
                "model_context_window=512000",
                "-c",
                "model_auto_compact_token_limit=460000",
            ],
            token_pool_settings.build_codex_context_override_args(),
        )

    def test_desktop_new_and_resume_args_include_context_override_for_every_backend(self) -> None:
        manager = make_manager()
        item = app.SessionItem(
            session_id="session-test",
            ts=0,
            text="",
            note="",
            history_count=1,
            cwd="D:\\workspace",
            model="gpt-5.6-sol",
            approval_policy="never",
            sandbox_mode="danger-full-access",
            turn_id="",
            session_file="",
        )
        settings_by_mode = {
            token_pool_settings.BACKEND_MODE_CODEX_AUTH: {
                "backend_mode": token_pool_settings.BACKEND_MODE_CODEX_AUTH,
            },
            token_pool_settings.BACKEND_MODE_TOKEN_POOL: {
                "backend_mode": token_pool_settings.BACKEND_MODE_TOKEN_POOL,
                "proxy_port": 8317,
            },
            token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE: {
                "backend_mode": token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE,
                "openai_base_url": "https://provider.example/v1",
                "openai_api_key": "key",
                "openai_model": "gpt-5.6-sol",
                "openai_models": ["gpt-5.6-sol"],
                "openai_protocol": token_pool_settings.OPENAI_PROTOCOL_RESPONSES,
                "proxy_preference": "direct",
            },
        }

        for settings in settings_by_mode.values():
            if settings["backend_mode"] == token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE:
                with (
                    mock.patch.object(manager, "_ensure_openai_compatible_launch_model_metadata"),
                    mock.patch.object(token_pool_settings, "ensure_codex_model_context_metadata"),
                ):
                    new_args = manager._build_codex_new_args(settings)
                    resume_args = manager._build_codex_resume_args(item, settings)
            else:
                with mock.patch.object(token_pool_settings, "ensure_codex_model_context_metadata"):
                    new_args = manager._build_codex_new_args(settings)
                    resume_args = manager._build_codex_resume_args(item, settings)
            self.assertIn("model_context_window=512000", new_args)
            self.assertIn("model_auto_compact_token_limit=460000", new_args)
            self.assertIn("model_context_window=512000", resume_args)
            self.assertIn("model_auto_compact_token_limit=460000", resume_args)

    def test_mobile_new_and_resume_args_include_context_override_for_every_backend(self) -> None:
        settings_by_mode = [
            {"backend_mode": token_pool_settings.BACKEND_MODE_CODEX_AUTH},
            {
                "backend_mode": token_pool_settings.BACKEND_MODE_TOKEN_POOL,
                "proxy_port": 8317,
            },
            {
                "backend_mode": token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE,
                "openai_base_url": "https://provider.example/v1",
                "openai_api_key": "key",
                "openai_model": "gpt-5.6-sol",
                "openai_models": ["gpt-5.6-sol"],
                "openai_protocol": token_pool_settings.OPENAI_PROTOCOL_RESPONSES,
                "proxy_preference": "direct",
            },
        ]

        with (
            tempfile.TemporaryDirectory() as temp_dir,
            mock.patch.object(token_pool_settings, "load_backend_settings") as load_settings,
            mock.patch.object(mobile_portal, "ensure_openai_compatible_launch_model_metadata"),
            mock.patch.object(token_pool_settings, "ensure_codex_model_context_metadata"),
        ):
            output_file = Path(temp_dir) / "output.json"
            for settings in settings_by_mode:
                load_settings.return_value = settings
                new_args = mobile_portal.build_new_chat_args(
                    output_file,
                    "hello",
                    "gpt-5.6-sol",
                    "default",
                    "default",
                    "default",
                )
                resume_args = mobile_portal.build_resume_args(
                    output_file,
                    "session-test",
                    "hello",
                    "gpt-5.6-sol",
                    "default",
                    "default",
                    "default",
                )
                self.assertIn("model_context_window=512000", new_args)
                self.assertIn("model_auto_compact_token_limit=460000", new_args)
                self.assertIn("model_context_window=512000", resume_args)
                self.assertIn("model_auto_compact_token_limit=460000", resume_args)

    def test_custom_provider_advertises_512k_token_context(self) -> None:
        model = custom_provider_proxy.build_models_payload(["custom-model"])["models"][0]
        self.assertEqual(512_000, model["context_window"])
        self.assertEqual(512_000, model["max_context_window"])

    def test_token_pool_advertises_codex_context_metadata(self) -> None:
        payload = token_pool_proxy.build_models_payload(("gpt-5.6-sol",))
        self.assertIn("models", payload)
        model = payload["models"][0]
        self.assertEqual("gpt-5.6-sol", model["slug"])
        self.assertEqual(512_000, model["context_window"])
        self.assertEqual(512_000, model["max_context_window"])

    def test_context_metadata_normalizes_every_cached_model(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_file = Path(temp_dir) / "models_cache.json"
            cache_file.write_text(
                json.dumps(
                    {
                        "models": [
                            {
                                "slug": "gpt-5.6-sol",
                                "context_window": 272000,
                                "max_context_window": 872000,
                            },
                            {
                                "slug": "gpt-reserve",
                                "context_window": 128000,
                                "max_context_window": 128000,
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

            self.assertTrue(
                token_pool_settings.ensure_codex_model_context_metadata(
                    ["gpt-5.6-sol"],
                    models_cache_file=cache_file,
                )
            )
            payload = json.loads(cache_file.read_text(encoding="utf-8"))
            for model in payload["models"]:
                self.assertEqual(512_000, model["context_window"])
                self.assertEqual(512_000, model["max_context_window"])

    def test_openai_compatible_cache_metadata_is_upgraded_to_512k(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_file = Path(temp_dir) / "models_cache.json"
            cache_file.write_text(
                json.dumps(
                    {
                        "models": [
                            {
                                "slug": "gpt-5.5",
                                "context_window": 272000,
                                "max_context_window": 272000,
                                "input_modalities": ["text"],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            self.assertTrue(
                token_pool_settings.ensure_openai_compatible_model_metadata(
                    ["custom-model"],
                    models_cache_file=cache_file,
                )
            )
            payload = json.loads(cache_file.read_text(encoding="utf-8"))
            custom = next(model for model in payload["models"] if model["slug"] == "custom-model")
            self.assertEqual(512_000, custom["context_window"])
            self.assertEqual(512_000, custom["max_context_window"])

    def test_existing_model_cache_metadata_is_upgraded_for_any_backend(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_file = Path(temp_dir) / "models_cache.json"
            cache_file.write_text(
                json.dumps(
                    {
                        "models": [
                            {
                                "slug": "gpt-5.6-sol",
                                "context_window": 272000,
                                "max_context_window": 872000,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            self.assertTrue(
                token_pool_settings.ensure_codex_model_context_metadata(
                    ["gpt-5.6-sol"],
                    models_cache_file=cache_file,
                )
            )
            payload = json.loads(cache_file.read_text(encoding="utf-8"))
            model = payload["models"][0]
            self.assertEqual(512_000, model["context_window"])
            self.assertEqual(512_000, model["max_context_window"])

    def test_unchanged_model_cache_is_not_rewritten(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_file = Path(temp_dir) / "models_cache.json"
            original = {
                "client_version": "0.148.0",
                "etag": None,
                "fetched_at": "2026-09-05T00:00:00Z",
                "models": [
                    {
                        "slug": "gpt-6-astra",
                        "context_window": 512_000,
                        "max_context_window": 512_000,
                    }
                ],
            }
            cache_file.write_text(
                json.dumps(original, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            before = cache_file.read_bytes()

            with mock.patch.object(
                token_pool_settings,
                "_current_codex_client_version",
                return_value="0.148.0",
            ):
                self.assertFalse(
                    token_pool_settings.ensure_codex_model_context_metadata(
                        ["gpt-6-astra"],
                        models_cache_file=cache_file,
                    )
                )

            self.assertEqual(before, cache_file.read_bytes())

    def test_model_cache_is_written_in_codex_cache_envelope(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_file = Path(temp_dir) / "models_cache.json"
            cache_file.write_text(
                json.dumps(
                    {
                        "client_version": "0.148.0",
                        "models": [
                            {
                                "slug": "gpt-5.6-sol",
                                "context_window": 272000,
                                "max_context_window": 872000,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            self.assertTrue(
                token_pool_settings.ensure_codex_model_context_metadata(
                    ["gpt-5.6-sol"],
                    models_cache_file=cache_file,
                )
            )
            payload = json.loads(cache_file.read_text(encoding="utf-8"))
            self.assertRegex(payload["fetched_at"], r"^20\d\d-")
            self.assertIsNone(payload["etag"])

    def test_models_only_resolver_prefers_shared_gpt6_default_when_available(self) -> None:
        with (
            mock.patch.object(
                token_pool_settings,
                "normalize_openai_base_url",
                return_value="https://provider.example/v1",
            ),
            mock.patch.object(
                token_pool_settings,
                "fetch_openai_compatible_models",
                return_value=["claude-sonnet", "gpt-6-astra"],
            ),
        ):
            resolved = token_pool_settings.resolve_openai_compatible_models_only_config(
                "https://provider.example/v1",
                "api-key",
                "missing-model",
            )

        self.assertEqual("gpt-6-astra", resolved["openai_model"])

    def test_unsupported_api_preset_does_not_accept_global_gpt6_default(self) -> None:
        manager = make_manager()
        settings = {
            "backend_mode": token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE,
            "openai_model": "gpt-5.5",
            "openai_models": ["gpt-5.5"],
        }

        self.assertEqual(
            "gpt-5.5",
            manager._resolve_openai_compatible_launch_model(
                app.DEFAULT_PRIMARY_MODEL,
                settings=settings,
            ),
        )
        self.assertEqual(
            "gpt-5.5",
            mobile_portal.resolve_launch_model_for_backend(
                app.DEFAULT_PRIMARY_MODEL,
                settings,
            ),
        )

    def test_desktop_runtime_refreshes_its_private_model_cache(self) -> None:
        manager = make_manager()
        manager.model_var = FakeVar("default")
        runtime = window_runtime.WindowRuntime(
            launch_id="launch-test",
            runtime_root=Path("D:/codex-runtime"),
            runtime_dir=Path("D:/codex-runtime/launch-test"),
            codex_home=Path("D:/codex-runtime/launch-test/home"),
            sqlite_home=Path("C:/Users/windows/.codex"),
            isolated=True,
            session_id="",
        )
        settings = {
            "backend_mode": token_pool_settings.BACKEND_MODE_CODEX_AUTH,
        }

        with (
            mock.patch.object(app.window_runtime, "prepare_window_runtime", return_value=runtime),
            mock.patch.object(token_pool_settings, "ensure_codex_model_context_metadata") as ensure,
        ):
            manager._prepare_window_runtime(settings, session_id="")

        ensure.assert_called_once_with(
            [app.DEFAULT_PRIMARY_MODEL],
            models_cache_file=runtime.codex_home / "models_cache.json",
        )


if __name__ == "__main__":
    unittest.main()
