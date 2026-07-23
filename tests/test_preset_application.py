import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app
import token_pool_settings


class PresetApplicationTests(unittest.TestCase):
    def test_form_values_follow_active_preset_when_runtime_is_detached(self) -> None:
        settings = {
            "openai_base_url": "https://runtime.example.invalid/v1",
            "openai_api_key": "runtime-key",
            "openai_model": "runtime-model",
            "openai_models": ["runtime-model"],
            "openai_protocol": token_pool_settings.OPENAI_PROTOCOL_CHAT_COMPLETIONS,
            "proxy_preference": "proxy",
            "active_openai_preset_id": "selected-provider",
            "openai_config_detached_from_preset": True,
            "openai_presets": [
                {
                    "id": "selected-provider",
                    "name": "Selected Provider",
                    "openai_base_url": "https://selected.example.invalid/v1",
                    "openai_api_key": "selected-key",
                    "openai_model": "selected-model",
                    "openai_models": ["selected-model", "selected-model-2"],
                    "openai_protocol": token_pool_settings.OPENAI_PROTOCOL_RESPONSES,
                    "proxy_preference": "direct",
                }
            ],
        }

        values = app.openai_account_form_values(settings)

        self.assertEqual(
            {
                "openai_base_url": "https://selected.example.invalid/v1",
                "openai_api_key": "selected-key",
                "openai_model": "selected-model",
                "openai_models": ["selected-model", "selected-model-2"],
                "openai_protocol": token_pool_settings.OPENAI_PROTOCOL_RESPONSES,
                "proxy_preference": "direct",
            },
            values,
        )

    def test_form_values_do_not_inherit_runtime_fields_when_preset_fields_are_empty(
        self,
    ) -> None:
        settings = {
            "openai_base_url": "https://runtime.example.invalid/v1",
            "openai_api_key": "runtime-key",
            "openai_model": "runtime-model",
            "openai_models": ["runtime-model"],
            "openai_protocol": token_pool_settings.OPENAI_PROTOCOL_CHAT_COMPLETIONS,
            "proxy_preference": "proxy",
            "active_openai_preset_id": "empty-provider",
            "openai_config_detached_from_preset": True,
            "openai_presets": [
                {
                    "id": "empty-provider",
                    "name": "Empty Provider",
                    "openai_base_url": "https://empty.example.invalid/v1",
                    "openai_api_key": "",
                    "openai_model": "",
                    "openai_models": [],
                    "openai_protocol": token_pool_settings.OPENAI_PROTOCOL_RESPONSES,
                    "proxy_preference": "direct",
                }
            ],
        }

        values = app.openai_account_form_values(settings)

        self.assertEqual("https://empty.example.invalid/v1", values["openai_base_url"])
        self.assertEqual("", values["openai_api_key"])
        self.assertEqual("", values["openai_model"])
        self.assertEqual([], values["openai_models"])
        self.assertEqual(
            token_pool_settings.OPENAI_PROTOCOL_RESPONSES,
            values["openai_protocol"],
        )
        self.assertEqual("direct", values["proxy_preference"])
        model_values, selected_model = app.openai_model_form_state(
            values,
            fallback_models=["fallback-model"],
            allow_fallback=False,
        )
        self.assertEqual([], model_values)
        self.assertEqual("", selected_model)

    def test_validation_failure_does_not_mutate_settings(self) -> None:
        original_proxy_preference = token_pool_settings.get_active_proxy_preference()
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings_file = Path(temp_dir) / "settings.json"
                token_pool_settings.save_backend_settings(
                    backend_mode=token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE,
                    settings_file=settings_file,
                    proxy_api_key="proxy-key",
                    openai_base_url="https://current.example.invalid/v1",
                    openai_api_key="current-key",
                    openai_model="current-model",
                    openai_models=["current-model"],
                    openai_protocol=token_pool_settings.OPENAI_PROTOCOL_RESPONSES,
                )
                token_pool_settings.save_openai_preset(
                    settings_file=settings_file,
                    preset_id="current-provider",
                    name="Current Provider",
                    openai_base_url="https://current.example.invalid/v1",
                    openai_api_key="current-key",
                    openai_model="current-model",
                    openai_models=["current-model"],
                    openai_protocol=token_pool_settings.OPENAI_PROTOCOL_RESPONSES,
                    proxy_preference="direct",
                    skip_validation=False,
                    set_active=True,
                )
                token_pool_settings.save_openai_preset(
                    settings_file=settings_file,
                    preset_id="target-provider",
                    name="Target Provider",
                    openai_base_url="https://target.example.invalid/v1",
                    openai_api_key="target-key",
                    openai_model="target-model",
                    openai_models=["target-model"],
                    openai_protocol=token_pool_settings.OPENAI_PROTOCOL_RESPONSES,
                    proxy_preference="direct",
                    skip_validation=False,
                    set_active=False,
                )
                before = settings_file.read_bytes()
                manager = object.__new__(app.SessionManagerApp)
                token_pool_settings.set_active_proxy_preference("direct")

                with mock.patch.object(
                    token_pool_settings,
                    "resolve_openai_compatible_backend_config",
                    side_effect=RuntimeError("validation failed"),
                ):
                    with self.assertRaisesRegex(RuntimeError, "validation failed"):
                        manager._apply_openai_compatible_preset_settings(
                            "target-provider",
                            settings_file=settings_file,
                            preset_name="Edited Target",
                            openai_base_url="https://edited.example.invalid/v1",
                            openai_api_key="edited-key",
                            openai_model="edited-model",
                            openai_protocol=token_pool_settings.OPENAI_PROTOCOL_CHAT_COMPLETIONS,
                            proxy_preference="proxy",
                            disable_image_generation=True,
                        )

                self.assertEqual(before, settings_file.read_bytes())
                self.assertEqual(
                    "current-provider",
                    token_pool_settings.load_backend_settings(settings_file)[
                        "active_openai_preset_id"
                    ],
                )
                self.assertEqual(
                    "direct",
                    token_pool_settings.get_active_proxy_preference(),
                )
        finally:
            token_pool_settings.set_active_proxy_preference(
                original_proxy_preference
            )

    def test_atomic_preset_activation_preserves_file_when_replace_fails(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_file = Path(temp_dir) / "settings.json"
            token_pool_settings.save_backend_settings(
                backend_mode=token_pool_settings.BACKEND_MODE_CODEX_AUTH,
                settings_file=settings_file,
                proxy_api_key="proxy-key",
                openai_base_url="https://current.example.invalid/v1",
                openai_api_key="current-key",
                openai_model="current-model",
                openai_models=["current-model"],
                openai_protocol=token_pool_settings.OPENAI_PROTOCOL_RESPONSES,
            )
            token_pool_settings.save_openai_preset(
                settings_file=settings_file,
                preset_id="target-provider",
                name="Target Provider",
                openai_base_url="https://target.example.invalid/v1",
                openai_api_key="target-key",
                openai_model="target-model",
                openai_models=["target-model"],
                openai_protocol=token_pool_settings.OPENAI_PROTOCOL_RESPONSES,
                proxy_preference="direct",
                skip_validation=False,
                set_active=False,
            )
            before = settings_file.read_bytes()

            with mock.patch.object(
                token_pool_settings.os,
                "replace",
                side_effect=OSError("replace failed"),
            ):
                with self.assertRaisesRegex(OSError, "replace failed"):
                    token_pool_settings.save_and_activate_openai_preset(
                        settings_file=settings_file,
                        preset_id="target-provider",
                        name="Edited Target",
                        openai_base_url="https://edited.example.invalid/v1",
                        openai_api_key="edited-key",
                        openai_model="edited-model",
                        openai_models=["edited-model"],
                        openai_protocol=token_pool_settings.OPENAI_PROTOCOL_CHAT_COMPLETIONS,
                        proxy_preference="proxy",
                        skip_validation=False,
                        disable_image_generation=True,
                    )

            self.assertEqual(before, settings_file.read_bytes())
            self.assertEqual([], list(settings_file.parent.glob("*.tmp")))

    def test_skip_validation_preset_applies_edits_without_network_validation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_file = Path(temp_dir) / "settings.json"
            token_pool_settings.save_backend_settings(
                backend_mode=token_pool_settings.BACKEND_MODE_CODEX_AUTH,
                settings_file=settings_file,
                proxy_api_key="proxy-key",
                openai_base_url="https://current.example.invalid/v1",
                openai_api_key="current-key",
                openai_model="current-model",
                openai_models=["current-model"],
                openai_protocol=token_pool_settings.OPENAI_PROTOCOL_RESPONSES,
            )
            token_pool_settings.save_openai_preset(
                settings_file=settings_file,
                preset_id="skip-provider",
                name="Skip Provider",
                openai_base_url="https://skip.example.invalid/v1",
                openai_api_key="skip-key",
                openai_model="skip-model",
                openai_models=["skip-model"],
                openai_protocol=token_pool_settings.OPENAI_PROTOCOL_RESPONSES,
                proxy_preference="direct",
                skip_validation=True,
                set_active=False,
            )
            manager = object.__new__(app.SessionManagerApp)

            with (
                mock.patch.object(
                    token_pool_settings,
                    "resolve_openai_compatible_backend_config",
                    side_effect=AssertionError("validation must be skipped"),
                ),
                mock.patch.object(app, "_swap_installation_id_for_preset"),
                mock.patch.object(app, "_patch_claude_settings_for_preset"),
                mock.patch.object(app, "_patch_image_generation_for_preset"),
                mock.patch.object(app.time, "sleep"),
                mock.patch.object(manager, "_stop_token_pool_proxy"),
                mock.patch.object(manager, "_start_openai_compatible_proxy"),
                mock.patch.object(manager, "_load_available_models", return_value=[]),
                mock.patch.object(manager, "_render_models"),
            ):
                updated = manager._apply_openai_compatible_preset_settings(
                    "skip-provider",
                    settings_file=settings_file,
                    preset_name="Edited Skip Provider",
                    openai_base_url="https://edited-skip.example.invalid/v1",
                    openai_api_key="edited-skip-key",
                    openai_model="edited-skip-model",
                    openai_protocol=token_pool_settings.OPENAI_PROTOCOL_CHAT_COMPLETIONS,
                    proxy_preference="proxy",
                    disable_image_generation=True,
                )

            preset = next(
                item
                for item in updated["openai_presets"]
                if item["id"] == "skip-provider"
            )
            self.assertEqual(
                token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE,
                updated["backend_mode"],
            )
            self.assertEqual("skip-provider", updated["active_openai_preset_id"])
            self.assertEqual("edited-skip-key", preset["openai_api_key"])
            self.assertEqual("edited-skip-model", preset["openai_model"])
            self.assertEqual(
                token_pool_settings.OPENAI_PROTOCOL_CHAT_COMPLETIONS,
                preset["openai_protocol"],
            )
            self.assertEqual("proxy", preset["proxy_preference"])
            self.assertTrue(preset["skip_validation"])
            self.assertTrue(preset["disable_image_generation"])


if __name__ == "__main__":
    unittest.main()
