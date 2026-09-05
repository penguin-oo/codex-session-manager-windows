import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import app
import mobile_portal
import token_pool_settings


class ProxyRoutingTests(unittest.TestCase):
    def test_save_proxy_settings_preserves_unknown_local_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_file = Path(temp_dir) / "mobile_portal_settings.json"
            settings_file.write_text(
                json.dumps(
                    {
                        "proxy_enabled": False,
                        "proxy_port": 7897,
                        "codex_executable": "C:\\Tools\\codex-clickable.exe",
                        "future_local_setting": {"enabled": True},
                    }
                ),
                encoding="utf-8",
            )

            mobile_portal.save_proxy_settings(
                proxy_enabled=True,
                proxy_port=7898,
                settings_file=settings_file,
            )

            saved = json.loads(settings_file.read_text(encoding="utf-8"))
            self.assertEqual("C:\\Tools\\codex-clickable.exe", saved["codex_executable"])
            self.assertEqual({"enabled": True}, saved["future_local_setting"])
            self.assertTrue(saved["proxy_enabled"])
            self.assertEqual(7898, saved["proxy_port"])

    def test_desktop_form_values_include_models_only_validation(self) -> None:
        values = app.openai_account_form_values(
            {
                "openai_base_url": "https://provider.example/v1",
                "openai_api_key": "api-key",
                "models_only_validation": True,
            }
        )
        self.assertTrue(values["models_only_validation"])

    def test_desktop_ui_wires_visible_models_only_control(self) -> None:
        source = Path(app.__file__).read_text(encoding="utf-8")
        self.assertIn("openai_models_only_validation_var", source)
        self.assertIn("models_only_validation=openai_models_only_validation_var.get()", source)
        self.assertIn("Fetch Models Only", source)

    def test_desktop_refresh_preserves_models_only_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_file = Path(temp_dir) / "settings.json"
            token_pool_settings.save_backend_settings(
                backend_mode=token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE,
                settings_file=settings_file,
                openai_base_url="https://provider.example/v1",
                openai_api_key="api-key",
                openai_model="missing-model",
                openai_models=["old-model"],
                openai_protocol=token_pool_settings.OPENAI_PROTOCOL_RESPONSES,
                models_only_validation=True,
            )
            with (
                mock.patch.object(
                    token_pool_settings,
                    "normalize_openai_base_url",
                    return_value="https://provider.example/v1",
                ),
                mock.patch.object(
                    token_pool_settings,
                    "fetch_openai_compatible_models",
                    return_value=["claude-sonnet", "gpt-5.6-sol"],
                ),
            ):
                refreshed = app.refresh_openai_compatible_models_from_upstream(settings_file)
            self.assertTrue(refreshed["models_only_validation"])
            self.assertEqual("gpt-5.6-sol", refreshed["openai_model"])

    def test_mobile_status_exposes_models_only_validation_for_presets(self) -> None:
        service = object.__new__(mobile_portal.PortalService)
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_file = Path(temp_dir) / "settings.json"
            token_pool_settings.save_openai_preset(
                settings_file=settings_file,
                preset_id="provider",
                name="Provider",
                openai_base_url="https://provider.example/v1",
                openai_api_key="api-key",
                openai_model="gpt-5.6-sol",
                openai_models=["gpt-5.6-sol"],
                models_only_validation=True,
                set_active=True,
            )
            service.backend_settings_file = settings_file
            with (
                mock.patch.object(token_pool_settings, "list_token_files", return_value=[]),
                mock.patch.object(mobile_portal, "token_pool_proxy_is_healthy", return_value=None),
            ):
                payload = service.backend_status_payload()

        self.assertTrue(payload["models_only_validation"])
        preset = next(item for item in payload["openai_presets"] if item["id"] == "provider")
        self.assertTrue(preset["models_only_validation"])

    def test_mobile_ui_wires_visible_models_only_control(self) -> None:
        source = Path(mobile_portal.__file__).read_text(encoding="utf-8")
        self.assertIn("models_only_validation", source)
        self.assertIn("Only fetch models", source)
        self.assertIn("async function refreshBackendModels", source)
        self.assertIn("refreshBackendModels()", source)

    def test_mobile_update_models_only_validates_before_persisting(self) -> None:
        service = object.__new__(mobile_portal.PortalService)
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_file = Path(temp_dir) / "settings.json"
            proxy_settings_file = Path(temp_dir) / "proxy.json"
            token_pool_settings.save_backend_settings(
                backend_mode=token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE,
                settings_file=settings_file,
                openai_base_url="https://old.example/v1",
                openai_api_key="old-key",
                openai_model="old-model",
                openai_models=["old-model"],
                openai_protocol=token_pool_settings.OPENAI_PROTOCOL_RESPONSES,
            )
            service.backend_settings_file = settings_file
            service.proxy_settings_file = proxy_settings_file
            service.jobs = SimpleNamespace(backend_settings_file=settings_file)
            service.backend_status_payload = mock.Mock(return_value={"ok": True})
            resolved = {
                "openai_base_url": "https://new.example/v1",
                "openai_api_key": "new-key",
                "openai_model": "gpt-5.6-sol",
                "openai_models": ["gpt-5.6-sol"],
                "openai_protocol": "",
                "upstream_proxy_url": "",
            }
            with (
                mock.patch.object(
                    token_pool_settings,
                    "resolve_openai_compatible_models_only_config",
                    return_value=resolved,
                ) as resolve_models_only,
                mock.patch.object(mobile_portal, "_patch_image_generation_for_backend_mode"),
                mock.patch.object(mobile_portal, "stop_token_pool_backend"),
                mock.patch.object(mobile_portal, "start_openai_compatible_backend"),
                mock.patch.object(mobile_portal.time, "sleep"),
            ):
                result = service.update_backend_settings(
                    backend_mode=token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE,
                    token_dir="",
                    proxy_port=8317,
                    openai_base_url="https://new.example/v1",
                    openai_api_key="new-key",
                    preset_id="provider",
                    preset_name="Provider",
                    models_only_validation=True,
                )

            self.assertEqual(token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE, result["backend_mode"])
            self.assertTrue(result["ok"])
            self.assertEqual("gpt-5.6-sol", token_pool_settings.load_backend_settings(settings_file)["openai_model"])
            self.assertTrue(token_pool_settings.load_backend_settings(settings_file)["models_only_validation"])
            resolve_models_only.assert_called_once()

    def test_mobile_update_models_only_failure_does_not_mutate_settings(self) -> None:
        service = object.__new__(mobile_portal.PortalService)
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_file = Path(temp_dir) / "settings.json"
            service.backend_settings_file = settings_file
            service.proxy_settings_file = Path(temp_dir) / "proxy.json"
            service.jobs = SimpleNamespace(backend_settings_file=settings_file)
            token_pool_settings.save_backend_settings(
                backend_mode=token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE,
                settings_file=settings_file,
                openai_base_url="https://old.example/v1",
                openai_api_key="old-key",
                openai_model="old-model",
                openai_models=["old-model"],
                openai_protocol=token_pool_settings.OPENAI_PROTOCOL_RESPONSES,
            )
            before = settings_file.read_bytes()
            with mock.patch.object(
                token_pool_settings,
                "resolve_openai_compatible_models_only_config",
                side_effect=RuntimeError("models unavailable"),
            ):
                with self.assertRaisesRegex(RuntimeError, "models unavailable"):
                    service.update_backend_settings(
                        backend_mode=token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE,
                        token_dir="",
                        proxy_port=8317,
                        openai_base_url="https://new.example/v1",
                        openai_api_key="new-key",
                        preset_id="provider",
                        preset_name="Provider",
                        models_only_validation=True,
                    )
            self.assertEqual(before, settings_file.read_bytes())

    def test_mobile_models_only_failure_does_not_create_settings_file(self) -> None:
        service = object.__new__(mobile_portal.PortalService)
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_file = Path(temp_dir) / "new-settings.json"
            service.backend_settings_file = settings_file
            service.proxy_settings_file = Path(temp_dir) / "proxy.json"
            service.jobs = SimpleNamespace(backend_settings_file=settings_file)
            with mock.patch.object(
                token_pool_settings,
                "resolve_openai_compatible_models_only_config",
                side_effect=RuntimeError("models unavailable"),
            ):
                with self.assertRaisesRegex(RuntimeError, "models unavailable"):
                    service.update_backend_settings(
                        backend_mode=token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE,
                        token_dir="",
                        proxy_port=8317,
                        openai_base_url="https://new.example/v1",
                        openai_api_key="new-key",
                        models_only_validation=True,
                    )
            self.assertFalse(settings_file.exists())

    def test_mobile_models_only_requires_credentials_before_saving(self) -> None:
        service = object.__new__(mobile_portal.PortalService)
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_file = Path(temp_dir) / "settings.json"
            service.backend_settings_file = settings_file
            service.proxy_settings_file = Path(temp_dir) / "proxy.json"
            service.jobs = SimpleNamespace(backend_settings_file=settings_file)
            with self.assertRaisesRegex(ValueError, "API key is required"):
                service.update_backend_settings(
                    backend_mode=token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE,
                    token_dir="",
                    proxy_port=8317,
                    openai_base_url="https://provider.example/v1",
                    openai_api_key="",
                    models_only_validation=True,
                )
            self.assertFalse(settings_file.exists())

    def test_mobile_apply_models_only_failure_does_not_switch_preset(self) -> None:
        service = object.__new__(mobile_portal.PortalService)
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_file = Path(temp_dir) / "settings.json"
            service.backend_settings_file = settings_file
            service.proxy_settings_file = Path(temp_dir) / "proxy.json"
            service.jobs = SimpleNamespace(backend_settings_file=settings_file)
            token_pool_settings.save_openai_preset(
                settings_file=settings_file,
                preset_id="candidate",
                name="Candidate",
                openai_base_url="https://candidate.example/v1",
                openai_api_key="candidate-key",
                openai_model="candidate-model",
                openai_models=["candidate-model"],
                models_only_validation=True,
                set_active=False,
            )
            before = settings_file.read_bytes()
            with mock.patch.object(
                token_pool_settings,
                "resolve_openai_compatible_models_only_config",
                side_effect=RuntimeError("models unavailable"),
            ):
                with self.assertRaisesRegex(RuntimeError, "models unavailable"):
                    service.apply_openai_backend_preset(
                        "candidate",
                        models_only_validation=True,
                    )
            self.assertEqual(before, settings_file.read_bytes())

    def test_mobile_models_only_update_defaults_to_responses_for_new_config(self) -> None:
        service = object.__new__(mobile_portal.PortalService)
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_file = Path(temp_dir) / "settings.json"
            service.backend_settings_file = settings_file
            service.proxy_settings_file = Path(temp_dir) / "proxy.json"
            service.jobs = SimpleNamespace(backend_settings_file=settings_file)
            service.backend_status_payload = mock.Mock(return_value={"ok": True})
            token_pool_settings.save_backend_settings(
                backend_mode=token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE,
                settings_file=settings_file,
                openai_base_url="https://old.example/v1",
                openai_api_key="old-key",
                openai_model="old-model",
                openai_models=["old-model"],
                openai_protocol="",
            )
            resolved = {
                "openai_base_url": "https://new.example/v1",
                "openai_api_key": "new-key",
                "openai_model": "gpt-5.6-sol",
                "openai_models": ["gpt-5.6-sol"],
                "openai_protocol": "",
                "upstream_proxy_url": "",
            }
            with (
                mock.patch.object(
                    token_pool_settings,
                    "resolve_openai_compatible_models_only_config",
                    return_value=resolved,
                ),
                mock.patch.object(mobile_portal, "_patch_image_generation_for_backend_mode"),
                mock.patch.object(mobile_portal, "stop_token_pool_backend"),
                mock.patch.object(mobile_portal.time, "sleep"),
            ):
                service.update_backend_settings(
                    backend_mode=token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE,
                    token_dir="",
                    proxy_port=8317,
                    openai_base_url="https://new.example/v1",
                    openai_api_key="new-key",
                    openai_model="",
                    openai_protocol="",
                    models_only_validation=True,
                )

            saved = token_pool_settings.load_backend_settings(settings_file)
            self.assertEqual(token_pool_settings.OPENAI_PROTOCOL_RESPONSES, saved["openai_protocol"])

    def test_mobile_models_only_apply_success_switches_after_model_fetch(self) -> None:
        service = object.__new__(mobile_portal.PortalService)
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_file = Path(temp_dir) / "settings.json"
            service.backend_settings_file = settings_file
            service.proxy_settings_file = Path(temp_dir) / "proxy.json"
            service.jobs = SimpleNamespace(backend_settings_file=settings_file)
            service.backend_status_payload = mock.Mock(return_value={"ok": True})
            token_pool_settings.save_backend_settings(
                backend_mode=token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE,
                settings_file=settings_file,
                openai_base_url="https://old.example/v1",
                openai_api_key="old-key",
                openai_model="old-model",
                openai_models=["old-model"],
                openai_protocol=token_pool_settings.OPENAI_PROTOCOL_RESPONSES,
            )
            token_pool_settings.save_openai_preset(
                settings_file=settings_file,
                preset_id="candidate",
                name="Candidate",
                openai_base_url="https://candidate.example/v1",
                openai_api_key="candidate-key",
                openai_model="missing-model",
                openai_models=["missing-model"],
                openai_protocol=token_pool_settings.OPENAI_PROTOCOL_CHAT_COMPLETIONS,
                models_only_validation=True,
                set_active=False,
            )
            resolved = {
                "openai_base_url": "https://candidate.example/v1",
                "openai_api_key": "candidate-key",
                "openai_model": "gpt-5.6-sol",
                "openai_models": ["gpt-5.6-sol"],
                "openai_protocol": "",
                "upstream_proxy_url": "",
            }
            with (
                mock.patch.object(
                    token_pool_settings,
                    "resolve_openai_compatible_models_only_config",
                    return_value=resolved,
                ) as resolve_models_only,
                mock.patch.object(
                    token_pool_settings,
                    "resolve_openai_compatible_backend_config",
                    side_effect=AssertionError("full conversation validation must not run"),
                ),
                mock.patch.object(mobile_portal, "_patch_image_generation_for_preset"),
                mock.patch.object(mobile_portal, "stop_token_pool_backend"),
                mock.patch.object(mobile_portal, "start_openai_compatible_backend"),
                mock.patch.object(mobile_portal.time, "sleep"),
            ):
                service.apply_openai_backend_preset(
                    "candidate",
                    models_only_validation=True,
                )

            saved = token_pool_settings.load_backend_settings(settings_file)
            self.assertEqual("candidate", saved["active_openai_preset_id"])
            self.assertEqual("gpt-5.6-sol", saved["openai_model"])
            candidate = next(item for item in saved["openai_presets"] if item["id"] == "candidate")
            self.assertTrue(candidate["models_only_validation"])
            self.assertEqual(token_pool_settings.OPENAI_PROTOCOL_CHAT_COMPLETIONS, candidate["openai_protocol"])
            resolve_models_only.assert_called_once()

    def test_models_only_validation_defaults_to_responses_without_existing_protocol(self) -> None:
        resolved = {
            "openai_base_url": "https://provider.example/v1",
            "openai_api_key": "api-key",
            "openai_model": "gpt-5.6-sol",
            "openai_models": ["gpt-5.6-sol"],
            "openai_protocol": "",
        }
        with mock.patch.object(
            token_pool_settings,
            "resolve_openai_compatible_models_only_config",
            return_value=resolved,
        ):
            result = app._resolve_openai_compatible_input(
                existing={},
                existing_preset={},
                base_url="https://provider.example/v1",
                api_key="api-key",
                model="",
                extras=[],
                protocol_override="",
                models_only_validation=True,
                upstream_proxy_url="",
            )
        self.assertEqual(token_pool_settings.OPENAI_PROTOCOL_RESPONSES, result["openai_protocol"])

    def test_models_only_validation_preserves_existing_chat_protocol(self) -> None:
        resolved = {
            "openai_base_url": "https://provider.example/v1",
            "openai_api_key": "api-key",
            "openai_model": "gpt-5.6-sol",
            "openai_models": ["gpt-5.6-sol"],
            "openai_protocol": "",
        }
        with mock.patch.object(
            token_pool_settings,
            "resolve_openai_compatible_models_only_config",
            return_value=resolved,
        ):
            result = app._resolve_openai_compatible_input(
                existing={},
                existing_preset={
                    "openai_protocol": token_pool_settings.OPENAI_PROTOCOL_CHAT_COMPLETIONS,
                },
                base_url="https://provider.example/v1",
                api_key="api-key",
                model="",
                extras=[],
                protocol_override="",
                models_only_validation=True,
                upstream_proxy_url="",
            )
        self.assertEqual(token_pool_settings.OPENAI_PROTOCOL_CHAT_COMPLETIONS, result["openai_protocol"])

    def test_models_only_resolver_fetches_models_without_protocol_probe(self) -> None:
        with (
            mock.patch.object(
                token_pool_settings,
                "normalize_openai_base_url",
                return_value="https://provider.example/v1",
            ) as normalize_url,
            mock.patch.object(
                token_pool_settings,
                "fetch_openai_compatible_models",
                return_value=["gpt-5.5", "gpt-5.6-sol"],
            ) as fetch_models,
            mock.patch.object(
                token_pool_settings,
                "detect_openai_compatible_protocol",
                side_effect=AssertionError("models-only validation must not probe a protocol"),
            ) as detect_protocol,
            mock.patch.object(
                token_pool_settings,
                "_http_post_json_with_optional_explicit_proxy",
                side_effect=AssertionError("models-only validation must not send POST"),
            ) as post_json,
        ):
            resolved = token_pool_settings.resolve_openai_compatible_models_only_config(
                "https://provider.example",
                "api-key",
                "gpt-5.5",
                upstream_proxy_url="http://proxy.example:8080",
            )

        self.assertEqual("https://provider.example/v1", resolved["openai_base_url"])
        self.assertEqual("api-key", resolved["openai_api_key"])
        self.assertEqual("gpt-5.5", resolved["openai_model"])
        self.assertEqual(["gpt-5.5", "gpt-5.6-sol"], resolved["openai_models"])
        self.assertEqual("", resolved["openai_protocol"])
        normalize_url.assert_called_once_with(
            "https://provider.example",
            "api-key",
            timeout_seconds=5.0,
            upstream_proxy_url="http://proxy.example:8080",
        )
        fetch_models.assert_called_once_with(
            "https://provider.example/v1",
            "api-key",
            timeout_seconds=8.0,
            upstream_proxy_url="http://proxy.example:8080",
        )
        detect_protocol.assert_not_called()
        post_json.assert_not_called()

    def test_models_only_resolver_prefers_sol_model_then_first_model(self) -> None:
        with mock.patch.object(
            token_pool_settings,
            "normalize_openai_base_url",
            return_value="https://provider.example/v1",
        ), mock.patch.object(
            token_pool_settings,
            "fetch_openai_compatible_models",
            return_value=["claude-sonnet", "gpt-5.6-sol"],
        ):
            resolved = token_pool_settings.resolve_openai_compatible_models_only_config(
                "https://provider.example/v1",
                "api-key",
                "missing-model",
            )
        self.assertEqual("gpt-5.6-sol", resolved["openai_model"])

        with mock.patch.object(
            token_pool_settings,
            "normalize_openai_base_url",
            return_value="https://provider.example/v1",
        ), mock.patch.object(
            token_pool_settings,
            "fetch_openai_compatible_models",
            return_value=["claude-sonnet", "gpt-5.4"],
        ):
            resolved = token_pool_settings.resolve_openai_compatible_models_only_config(
                "https://provider.example/v1",
                "api-key",
                "missing-model",
            )
        self.assertEqual("claude-sonnet", resolved["openai_model"])

    def test_models_only_resolver_rejects_empty_model_list(self) -> None:
        with (
            mock.patch.object(
                token_pool_settings,
                "normalize_openai_base_url",
                return_value="https://provider.example/v1",
            ),
            mock.patch.object(
                token_pool_settings,
                "fetch_openai_compatible_models",
                return_value=[],
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "No models returned"):
                token_pool_settings.resolve_openai_compatible_models_only_config(
                    "https://provider.example/v1",
                    "api-key",
                    "missing-model",
                )

    def test_models_only_validation_round_trips_without_hidden_skip_field(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_file = Path(temp_dir) / "settings.json"
            token_pool_settings.save_backend_settings(
                backend_mode=token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE,
                settings_file=settings_file,
                openai_base_url="https://provider.example/v1",
                openai_api_key="api-key",
                openai_model="gpt-5.6-sol",
                openai_models=["gpt-5.6-sol"],
                openai_protocol=token_pool_settings.OPENAI_PROTOCOL_RESPONSES,
            )
            saved = token_pool_settings.save_openai_preset(
                settings_file=settings_file,
                preset_id="provider",
                name="Provider",
                openai_base_url="https://provider.example/v1",
                openai_api_key="api-key",
                openai_model="gpt-5.6-sol",
                openai_models=["gpt-5.6-sol"],
                openai_protocol=token_pool_settings.OPENAI_PROTOCOL_RESPONSES,
                models_only_validation=True,
            )
            preset = next(item for item in saved["openai_presets"] if item["id"] == "provider")
            self.assertTrue(preset["models_only_validation"])
            self.assertNotIn("skip_validation", preset)

            loaded = token_pool_settings.load_backend_settings(settings_file)
            loaded_preset = next(item for item in loaded["openai_presets"] if item["id"] == "provider")
            self.assertTrue(loaded_preset["models_only_validation"])
            self.assertNotIn("skip_validation", loaded_preset)

    def test_backend_save_without_flag_preserves_active_preset_validation_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_file = Path(temp_dir) / "settings.json"
            token_pool_settings.save_openai_preset(
                settings_file=settings_file,
                preset_id="provider",
                name="Provider",
                openai_base_url="https://provider.example/v1",
                openai_api_key="api-key",
                openai_model="gpt-5.6-sol",
                openai_models=["gpt-5.6-sol"],
                models_only_validation=True,
                set_active=True,
            )

            token_pool_settings.save_backend_settings(
                backend_mode=token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE,
                settings_file=settings_file,
                openai_base_url="https://provider.example/v1",
                openai_api_key="api-key",
                openai_model="gpt-5.6-sol",
                openai_models=["gpt-5.6-sol"],
                openai_protocol=token_pool_settings.OPENAI_PROTOCOL_RESPONSES,
            )

            loaded = token_pool_settings.load_backend_settings(settings_file)
            self.assertTrue(loaded["models_only_validation"])
            active = next(item for item in loaded["openai_presets"] if item["id"] == "provider")
            self.assertTrue(active["models_only_validation"])

    def test_preset_save_without_flag_preserves_existing_validation_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_file = Path(temp_dir) / "settings.json"
            token_pool_settings.save_openai_preset(
                settings_file=settings_file,
                preset_id="provider",
                name="Provider",
                openai_base_url="https://provider.example/v1",
                openai_api_key="api-key",
                openai_model="gpt-5.6-sol",
                openai_models=["gpt-5.6-sol"],
                models_only_validation=True,
                set_active=True,
            )

            token_pool_settings.save_openai_preset(
                settings_file=settings_file,
                preset_id="provider",
                name="Provider renamed",
                openai_base_url="https://provider.example/v1",
                openai_api_key="api-key",
                openai_model="gpt-5.6-sol",
                openai_models=["gpt-5.6-sol"],
                set_active=True,
            )

            loaded = token_pool_settings.load_backend_settings(settings_file)
            active = next(item for item in loaded["openai_presets"] if item["id"] == "provider")
            self.assertTrue(active["models_only_validation"])

    def test_legacy_skip_validation_is_migrated_to_models_only_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_file = Path(temp_dir) / "settings.json"
            settings_file.write_text(
                json.dumps(
                    {
                        "backend_mode": token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE,
                        "openai_presets": [
                            {
                                "id": "legacy",
                                "name": "Legacy",
                                "skip_validation": True,
                                "openai_base_url": "https://provider.example/v1",
                                "openai_api_key": "api-key",
                            }
                        ],
                        "active_openai_preset_id": "legacy",
                    }
                ),
                encoding="utf-8",
            )

            loaded = token_pool_settings.load_backend_settings(settings_file)
            preset = next(item for item in loaded["openai_presets"] if item["id"] == "legacy")
            self.assertTrue(preset["models_only_validation"])
            self.assertNotIn("skip_validation", preset)

    def test_desktop_save_models_only_validates_before_persisting(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_file = Path(temp_dir) / "settings.json"
            token_pool_settings.save_backend_settings(
                backend_mode=token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE,
                settings_file=settings_file,
                openai_base_url="https://old.example/v1",
                openai_api_key="old-key",
                openai_model="old-model",
                openai_models=["old-model"],
                openai_protocol=token_pool_settings.OPENAI_PROTOCOL_RESPONSES,
            )
            before = settings_file.read_bytes()
            resolved = {
                "openai_base_url": "https://new.example/v1",
                "openai_api_key": "new-key",
                "openai_model": "gpt-5.6-sol",
                "openai_models": ["gpt-5.6-sol"],
                "openai_protocol": "",
            }
            with (
                mock.patch.object(
                    token_pool_settings,
                    "resolve_openai_compatible_models_only_config",
                    return_value=resolved,
                ) as resolve_models_only,
                mock.patch.object(
                    token_pool_settings,
                    "resolve_openai_compatible_backend_config",
                    side_effect=AssertionError("full conversation validation must not run"),
                ),
                mock.patch.object(app, "_patch_image_generation_for_backend_mode"),
            ):
                updated = app.save_openai_compatible_backend_settings(
                    settings_file=settings_file,
                    base_url="https://new.example/v1",
                    api_key="new-key",
                    model="",
                    preset_id="new-provider",
                    preset_name="New Provider",
                    protocol_override=token_pool_settings.OPENAI_PROTOCOL_RESPONSES,
                    models_only_validation=True,
                )

            self.assertNotEqual(before, settings_file.read_bytes())
            self.assertEqual("gpt-5.6-sol", updated["openai_model"])
            self.assertTrue(updated["models_only_validation"])
            resolve_models_only.assert_called_once()

    def test_desktop_save_models_only_failure_does_not_mutate_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_file = Path(temp_dir) / "settings.json"
            token_pool_settings.save_backend_settings(
                backend_mode=token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE,
                settings_file=settings_file,
                openai_base_url="https://old.example/v1",
                openai_api_key="old-key",
                openai_model="old-model",
                openai_models=["old-model"],
                openai_protocol=token_pool_settings.OPENAI_PROTOCOL_RESPONSES,
            )
            before = settings_file.read_bytes()
            with (
                mock.patch.object(
                    token_pool_settings,
                    "resolve_openai_compatible_models_only_config",
                    side_effect=RuntimeError("models unavailable"),
                ),
                mock.patch.object(app, "_patch_image_generation_for_backend_mode"),
            ):
                with self.assertRaisesRegex(RuntimeError, "models unavailable"):
                    app.save_openai_compatible_backend_settings(
                        settings_file=settings_file,
                        base_url="https://new.example/v1",
                        api_key="new-key",
                        preset_id="new-provider",
                        preset_name="New Provider",
                        models_only_validation=True,
                    )
            self.assertEqual(before, settings_file.read_bytes())

    def test_desktop_models_only_failure_does_not_create_settings_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_file = Path(temp_dir) / "new-settings.json"
            with mock.patch.object(
                token_pool_settings,
                "resolve_openai_compatible_models_only_config",
                side_effect=RuntimeError("models unavailable"),
            ):
                with self.assertRaisesRegex(RuntimeError, "models unavailable"):
                    app.save_openai_compatible_backend_settings(
                        settings_file=settings_file,
                        base_url="https://new.example/v1",
                        api_key="new-key",
                        models_only_validation=True,
                    )
            self.assertFalse(settings_file.exists())

    def test_desktop_apply_models_only_failure_does_not_switch_preset(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_file = Path(temp_dir) / "settings.json"
            token_pool_settings.save_backend_settings(
                backend_mode=token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE,
                settings_file=settings_file,
                openai_base_url="https://old.example/v1",
                openai_api_key="old-key",
                openai_model="old-model",
                openai_models=["old-model"],
                openai_protocol=token_pool_settings.OPENAI_PROTOCOL_RESPONSES,
            )
            token_pool_settings.save_openai_preset(
                settings_file=settings_file,
                preset_id="candidate",
                name="Candidate",
                openai_base_url="https://candidate.example/v1",
                openai_api_key="candidate-key",
                openai_model="candidate-model",
                openai_models=["candidate-model"],
                openai_protocol=token_pool_settings.OPENAI_PROTOCOL_RESPONSES,
                models_only_validation=True,
                set_active=False,
            )
            before = settings_file.read_bytes()
            manager = object.__new__(app.SessionManagerApp)
            with mock.patch.object(
                token_pool_settings,
                "resolve_openai_compatible_models_only_config",
                side_effect=RuntimeError("models unavailable"),
            ):
                with self.assertRaisesRegex(RuntimeError, "models unavailable"):
                    manager._apply_openai_compatible_preset_settings(
                        "candidate",
                        settings_file=settings_file,
                        models_only_validation=True,
                    )
            self.assertEqual(before, settings_file.read_bytes())


    def test_apply_standard_preset_persists_form_edits_before_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_file = Path(temp_dir) / "settings.json"
            token_pool_settings.save_backend_settings(
                backend_mode=token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE,
                settings_file=settings_file,
                proxy_api_key="proxy-key",
                openai_base_url="https://old.example/v1",
                openai_api_key="old-key",
                openai_model="old-model",
                openai_models=["old-model"],
                openai_protocol=token_pool_settings.OPENAI_PROTOCOL_RESPONSES,
            )
            token_pool_settings.save_openai_preset(
                settings_file=settings_file,
                preset_id="standard-provider",
                name="Old Name",
                openai_base_url="https://old.example/v1",
                openai_api_key="old-key",
                openai_model="old-model",
                openai_models=["old-model"],
                openai_protocol=token_pool_settings.OPENAI_PROTOCOL_RESPONSES,
                proxy_preference="direct",
                skip_validation=False,
                set_active=True,
            )
            manager = object.__new__(app.SessionManagerApp)

            def resolve_config(
                base_url: str,
                api_key: str,
                model: str,
                **_kwargs: object,
            ) -> dict[str, object]:
                return {
                    "openai_base_url": base_url,
                    "openai_api_key": api_key,
                    "openai_model": model,
                    "openai_models": [model],
                    "openai_protocol": token_pool_settings.OPENAI_PROTOCOL_RESPONSES,
                }

            with (
                mock.patch.object(
                    token_pool_settings,
                    "resolve_openai_compatible_backend_config",
                    side_effect=resolve_config,
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
                    "standard-provider",
                    settings_file=settings_file,
                    preset_name="New Name",
                    openai_base_url="https://new.example/v1",
                    openai_api_key="new-key",
                    openai_model="new-model",
                    openai_protocol=token_pool_settings.OPENAI_PROTOCOL_CHAT_COMPLETIONS,
                    proxy_preference="proxy",
                    disable_image_generation=True,
                )

            preset = next(
                item
                for item in updated["openai_presets"]
                if item["id"] == "standard-provider"
            )
            self.assertEqual("https://new.example/v1", updated["openai_base_url"])
            self.assertEqual("new-key", updated["openai_api_key"])
            self.assertEqual("new-model", updated["openai_model"])
            self.assertEqual(
                token_pool_settings.OPENAI_PROTOCOL_CHAT_COMPLETIONS,
                updated["openai_protocol"],
            )
            self.assertEqual("New Name", preset["name"])
            self.assertEqual("proxy", preset["proxy_preference"])
            self.assertTrue(preset["disable_image_generation"])

    def test_responses_network_proxy_does_not_require_local_adapter(self) -> None:
        settings = {
            "openai_protocol": token_pool_settings.OPENAI_PROTOCOL_RESPONSES,
            "proxy_preference": "proxy",
        }

        self.assertFalse(app._is_proxy_needed_for_openai_compatible(settings))
        self.assertFalse(mobile_portal.openai_compatible_requires_local_proxy(settings))

    def test_chat_completions_requires_local_adapter(self) -> None:
        settings = {
            "openai_protocol": token_pool_settings.OPENAI_PROTOCOL_CHAT_COMPLETIONS,
            "proxy_preference": "direct",
        }

        self.assertTrue(app._is_proxy_needed_for_openai_compatible(settings))
        self.assertTrue(mobile_portal.openai_compatible_requires_local_proxy(settings))

    def test_responses_proxy_preference_keeps_upstream_base_url(self) -> None:
        settings = {
            "backend_mode": token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE,
            "openai_protocol": token_pool_settings.OPENAI_PROTOCOL_RESPONSES,
            "openai_base_url": "https://provider.example/v1",
            "proxy_preference": "proxy",
            "proxy_port": 8317,
        }

        with mock.patch.object(
            token_pool_settings,
            "load_backend_settings",
            return_value=settings,
        ):
            args = mobile_portal.build_backend_override_args(Path("unused.json"))

        self.assertIn(
            'model_providers.openai_compatible.base_url="https://provider.example/v1"',
            args,
        )
        self.assertNotIn(
            'model_providers.openai_compatible.base_url="http://127.0.0.1:8317"',
            args,
        )

    def test_responses_proxy_preference_still_enables_network_proxy_env(self) -> None:
        settings = {
            "backend_mode": token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE,
            "openai_protocol": token_pool_settings.OPENAI_PROTOCOL_RESPONSES,
            "openai_api_key": "test-key",
            "proxy_preference": "proxy",
        }
        proxy_settings = {
            "proxy_enabled": True,
            "proxy_scheme": "socks5h",
            "proxy_host": "127.0.0.1",
            "proxy_port": 7897,
        }

        with (
            mock.patch.object(token_pool_settings, "load_backend_settings", return_value=settings),
            mock.patch.object(mobile_portal, "load_proxy_settings", return_value=proxy_settings),
        ):
            env = mobile_portal.build_codex_subprocess_env(
                base_env={},
                settings_file=Path("proxy.json"),
                backend_settings_file=Path("backend.json"),
            )

        self.assertEqual("socks5h://127.0.0.1:7897", env["HTTPS_PROXY"])
        self.assertEqual("test-key", env[mobile_portal.OPENAI_COMPAT_ENV_KEY_NAME])

    def test_network_proxy_falls_back_to_active_preset_when_top_level_is_detached(self) -> None:
        settings = {
            "backend_mode": token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE,
            "openai_protocol": token_pool_settings.OPENAI_PROTOCOL_RESPONSES,
            "openai_api_key": "test-key",
            "active_openai_preset_id": "preset-1",
            "openai_config_detached_from_preset": True,
            "openai_presets": [
                {
                    "id": "preset-1",
                    "proxy_preference": "proxy",
                }
            ],
        }
        proxy_settings = {
            "proxy_enabled": True,
            "proxy_scheme": "socks5h",
            "proxy_host": "127.0.0.1",
            "proxy_port": 7897,
        }

        with (
            mock.patch.object(token_pool_settings, "load_backend_settings", return_value=settings),
            mock.patch.object(mobile_portal, "load_proxy_settings", return_value=proxy_settings),
        ):
            env = mobile_portal.build_codex_subprocess_env(
                base_env={},
                settings_file=Path("proxy.json"),
                backend_settings_file=Path("backend.json"),
            )

        self.assertEqual("socks5h://127.0.0.1:7897", env["HTTPS_PROXY"])

    def test_apply_mode_passes_selected_protocol_to_openai_backend_save(self) -> None:
        with (
            mock.patch.object(token_pool_settings, "load_backend_settings", return_value={}),
            mock.patch.object(
                app,
                "save_openai_compatible_backend_settings",
                return_value={"backend_mode": token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE},
            ) as save_backend,
        ):
            app.apply_backend_mode_settings(
                backend_mode=token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE,
                settings_file=Path("unused.json"),
                token_dir=Path("tokens"),
                proxy_port=8317,
                proxy_api_key="proxy-key",
                openai_base_url="https://provider.example/v1",
                openai_api_key="api-key",
                openai_model="gpt-test",
                openai_protocol=token_pool_settings.OPENAI_PROTOCOL_CHAT_COMPLETIONS,
            )

        self.assertEqual(
            token_pool_settings.OPENAI_PROTOCOL_CHAT_COMPLETIONS,
            save_backend.call_args.kwargs["protocol_override"],
        )

    def test_apply_mode_keeps_active_skip_validation_preset_path(self) -> None:
        existing = {
            "active_openai_preset_id": "skip-provider",
            "openai_config_detached_from_preset": True,
            "openai_presets": [
                {
                    "id": "skip-provider",
                    "name": "Skip Provider",
                    "skip_validation": True,
                    "proxy_preference": "direct",
                }
            ],
        }

        with (
            mock.patch.object(token_pool_settings, "load_backend_settings", return_value=existing),
            mock.patch.object(
                app,
                "save_openai_compatible_backend_settings",
                return_value={"backend_mode": token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE},
            ) as save_backend,
        ):
            app.apply_backend_mode_settings(
                backend_mode=token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE,
                settings_file=Path("unused.json"),
                token_dir=Path("tokens"),
                proxy_port=8317,
                proxy_api_key="proxy-key",
                openai_base_url="https://provider.example/v1",
                openai_api_key="api-key",
                openai_model="gpt-test",
                openai_protocol=token_pool_settings.OPENAI_PROTOCOL_CHAT_COMPLETIONS,
            )

        self.assertEqual("skip-provider", save_backend.call_args.kwargs["preset_id"])
        self.assertEqual("Skip Provider", save_backend.call_args.kwargs["preset_name"])


if __name__ == "__main__":
    unittest.main()
