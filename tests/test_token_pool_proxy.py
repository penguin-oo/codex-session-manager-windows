import json
import tempfile
import unittest
from pathlib import Path

import token_pool_proxy
import token_pool_settings


class TokenPoolSettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.codex_home = self.root / '.codex'
        self.codex_home.mkdir(parents=True, exist_ok=True)
        self.settings_file = self.codex_home / 'token_pool_settings.json'
        self.token_dir = self.root / '.cli-proxy-api'

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_load_backend_settings_defaults_to_codex_auth(self) -> None:
        settings = token_pool_settings.load_backend_settings(settings_file=self.settings_file)

        self.assertEqual('codex_auth', settings['backend_mode'])
        self.assertTrue(settings['proxy_api_key'])
        self.assertTrue(self.settings_file.exists())

    def test_load_backend_settings_reuses_same_generated_proxy_key(self) -> None:
        first = token_pool_settings.load_backend_settings(settings_file=self.settings_file)
        second = token_pool_settings.load_backend_settings(settings_file=self.settings_file)

        self.assertEqual(first['proxy_api_key'], second['proxy_api_key'])

    def test_save_backend_settings_persists_proxy_api_key(self) -> None:
        token_pool_settings.save_backend_settings(
            backend_mode='built_in_token_pool',
            settings_file=self.settings_file,
            token_dir=self.token_dir,
            proxy_port=9317,
            proxy_api_key='local-proxy-key',
        )

        loaded = token_pool_settings.load_backend_settings(settings_file=self.settings_file)

        self.assertEqual('built_in_token_pool', loaded['backend_mode'])
        self.assertEqual(9317, loaded['proxy_port'])
        self.assertEqual('local-proxy-key', loaded['proxy_api_key'])

    def test_ensure_token_pool_dir_creates_missing_directory(self) -> None:
        created = token_pool_settings.ensure_token_pool_dir(token_dir=self.token_dir)

        self.assertEqual(self.token_dir, created)
        self.assertTrue(self.token_dir.exists())
        self.assertTrue(self.token_dir.is_dir())

    def test_import_token_files_copies_multiple_json_files(self) -> None:
        source_dir = self.root / 'source'
        source_dir.mkdir()
        first = source_dir / 'a.json'
        second = source_dir / 'b.json'
        first.write_text('{"token":"a"}', encoding='utf-8')
        second.write_text('{"token":"b"}', encoding='utf-8')

        imported = token_pool_settings.import_token_files([first, second], token_dir=self.token_dir)

        self.assertEqual(['a.json', 'b.json'], [path.name for path in imported])
        self.assertEqual('{"token":"a"}', (self.token_dir / 'a.json').read_text(encoding='utf-8'))
        self.assertEqual('{"token":"b"}', (self.token_dir / 'b.json').read_text(encoding='utf-8'))

    def test_import_token_files_overwrites_existing_target(self) -> None:
        source_dir = self.root / 'source'
        source_dir.mkdir()
        source = source_dir / 'same.json'
        source.write_text('{"token":"new"}', encoding='utf-8')
        self.token_dir.mkdir()
        (self.token_dir / 'same.json').write_text('{"token":"old"}', encoding='utf-8')

        token_pool_settings.import_token_files([source], token_dir=self.token_dir)

        self.assertEqual('{"token":"new"}', (self.token_dir / 'same.json').read_text(encoding='utf-8'))


class TokenPoolCoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.token_dir = Path(self.temp_dir.name)
        (self.token_dir / 'a.json').write_text(json.dumps({'access_token': 'token-a'}), encoding='utf-8')
        (self.token_dir / 'b.json').write_text(json.dumps({'access_token': 'token-b'}), encoding='utf-8')
        (self.token_dir / 'c.json').write_text(json.dumps({'access_token': 'token-c'}), encoding='utf-8')
        self.now = 1000.0
        self.pool = token_pool_proxy.TokenPool(token_dir=self.token_dir, cooldown_seconds=1800, time_fn=lambda: self.now)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_select_token_uses_round_robin_order(self) -> None:
        first = self.pool.select_token()
        second = self.pool.select_token()
        third = self.pool.select_token()
        fourth = self.pool.select_token()

        self.assertEqual('a.json', first.file_name)
        self.assertEqual('b.json', second.file_name)
        self.assertEqual('c.json', third.file_name)
        self.assertEqual('a.json', fourth.file_name)

    def test_mark_quota_failure_puts_token_on_cooldown(self) -> None:
        selected = self.pool.select_token()

        self.pool.mark_quota_failure(selected.file_name, 'quota exceeded')
        next_selected = self.pool.select_token()

        self.assertEqual('b.json', next_selected.file_name)
        state = self.pool.state_for(selected.file_name)
        self.assertGreater(state.cooldown_until, self.now)
        self.assertIn('quota exceeded', state.last_error)

    def test_retryable_failure_keeps_token_available_but_advances_to_next(self) -> None:
        first = self.pool.select_token()

        self.pool.mark_retryable_failure(first.file_name, 'upstream 502')
        next_selected = self.pool.select_token()

        self.assertEqual('b.json', next_selected.file_name)
        state = self.pool.state_for(first.file_name)
        self.assertEqual(0.0, state.cooldown_until)
        self.assertIn('upstream 502', state.last_error)


class TokenPoolForwardingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.token_dir = Path(self.temp_dir.name)
        (self.token_dir / 'a.json').write_text(json.dumps({'access_token': 'token-a'}), encoding='utf-8')
        (self.token_dir / 'b.json').write_text(json.dumps({'access_token': 'token-b'}), encoding='utf-8')
        self.now = 2000.0
        self.pool = token_pool_proxy.TokenPool(token_dir=self.token_dir, cooldown_seconds=1800, time_fn=lambda: self.now)
        self.forwarder = token_pool_proxy.TokenPoolForwarder(self.pool)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_forward_request_uses_selected_token(self) -> None:
        calls: list[str] = []

        def upstream(token_state: token_pool_proxy.TokenState) -> token_pool_proxy.ForwardResponse:
            calls.append(token_state.file_name)
            return token_pool_proxy.ForwardResponse(status_code=200, body=b'{"ok":true}', headers={'content-type': 'application/json'})

        response = self.forwarder.forward_with_failover(upstream)

        self.assertEqual(200, response.status_code)
        self.assertEqual(['a.json'], calls)

    def test_retryable_failure_tries_next_token(self) -> None:
        calls: list[str] = []

        def upstream(token_state: token_pool_proxy.TokenState) -> token_pool_proxy.ForwardResponse:
            calls.append(token_state.file_name)
            if token_state.file_name == 'a.json':
                raise token_pool_proxy.TokenPoolUpstreamError('temporary upstream failure', retryable=True, status_code=502)
            return token_pool_proxy.ForwardResponse(status_code=200, body=b'ok', headers={})

        response = self.forwarder.forward_with_failover(upstream)

        self.assertEqual(200, response.status_code)
        self.assertEqual(['a.json', 'b.json'], calls)

    def test_quota_failure_marks_token_on_cooldown(self) -> None:
        def upstream(token_state: token_pool_proxy.TokenState) -> token_pool_proxy.ForwardResponse:
            if token_state.file_name == 'a.json':
                raise token_pool_proxy.TokenPoolUpstreamError('quota exceeded', quota_exhausted=True, status_code=429)
            return token_pool_proxy.ForwardResponse(status_code=200, body=b'ok', headers={})

        self.forwarder.forward_with_failover(upstream)

        state = self.pool.state_for('a.json')
        self.assertGreater(state.cooldown_until, self.now)
        self.assertIn('quota exceeded', state.last_error)

    def test_forward_request_sanitizes_token_from_terminal_error(self) -> None:
        def upstream(token_state: token_pool_proxy.TokenState) -> token_pool_proxy.ForwardResponse:
            raise token_pool_proxy.TokenPoolUpstreamError(f'auth failed for {token_state.access_token}', status_code=401)

        with self.assertRaises(token_pool_proxy.TokenPoolForwardingError) as ctx:
            self.forwarder.forward_with_failover(upstream)

        self.assertNotIn('token-a', str(ctx.exception))
        self.assertNotIn('token-b', str(ctx.exception))


class TokenPoolProtocolTests(unittest.TestCase):
    def test_translate_codex_request_forwards_responses_compatible_payload(self) -> None:
        payload = {
            'model': 'gpt-5.4',
            'input': 'Reply with OK.',
            'store': True,
            'parallel_tool_calls': False,
            'max_output_tokens': 2048,
            'temperature': 0.2,
            'top_p': 0.9,
            'truncation': 'auto',
            'user': 'user-1',
            'context_management': {'mode': 'truncate'},
            'service_tier': 'standard',
            'previous_response_id': 'resp_123',
            'prompt_cache_retention': {'enabled': True},
            'safety_identifier': 'abc',
        }

        translated = token_pool_proxy.translate_codex_request(payload)

        self.assertEqual('gpt-5.4', translated['model'])
        self.assertTrue(translated['stream'])
        self.assertFalse(translated['store'])
        self.assertTrue(translated['parallel_tool_calls'])
        self.assertEqual(['reasoning.encrypted_content'], translated['include'])
        self.assertEqual('', translated['instructions'])
        self.assertEqual('message', translated['input'][0]['type'])
        self.assertEqual('user', translated['input'][0]['role'])
        self.assertEqual('input_text', translated['input'][0]['content'][0]['type'])
        self.assertNotIn('max_output_tokens', translated)
        self.assertNotIn('temperature', translated)
        self.assertNotIn('top_p', translated)
        self.assertNotIn('truncation', translated)
        self.assertNotIn('user', translated)
        self.assertNotIn('context_management', translated)
        self.assertNotIn('service_tier', translated)
        self.assertNotIn('previous_response_id', translated)
        self.assertNotIn('prompt_cache_retention', translated)
        self.assertNotIn('safety_identifier', translated)

    def test_translate_codex_request_keeps_priority_service_tier(self) -> None:
        payload = {
            'model': 'gpt-5.4',
            'input': 'Reply with OK.',
            'service_tier': 'priority',
        }

        translated = token_pool_proxy.translate_codex_request(payload)

        self.assertEqual('priority', translated['service_tier'])

    def test_translate_codex_request_rewrites_system_role_to_developer(self) -> None:
        payload = {
            'model': 'gpt-5.4',
            'input': [
                {
                    'type': 'message',
                    'role': 'system',
                    'content': [{'type': 'input_text', 'text': 'You are strict.'}],
                }
            ],
        }

        translated = token_pool_proxy.translate_codex_request(payload)

        self.assertEqual('developer', translated['input'][0]['role'])

    def test_build_models_payload_includes_default_codex_models(self) -> None:
        payload = token_pool_proxy.build_models_payload()

        self.assertEqual('list', payload['object'])
        model_ids = [item['id'] for item in payload['data']]
        self.assertIn('gpt-5.4', model_ids)
        self.assertIn('gpt-5.3-codex', model_ids)


class TokenPoolAppTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.token_dir = Path(self.temp_dir.name)
        (self.token_dir / 'a.json').write_text(json.dumps({'access_token': 'token-a'}), encoding='utf-8')
        self.pool = token_pool_proxy.TokenPool(token_dir=self.token_dir)
        self.app = token_pool_proxy.TokenPoolProxyApp(self.pool, local_api_key='local-proxy-key', proxy_port=8317)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_build_health_payload_reports_token_count_and_port(self) -> None:
        payload = self.app.build_health_payload()

        self.assertEqual('ok', payload['status'])
        self.assertEqual(1, payload['token_count'])
        self.assertEqual(8317, payload['port'])

    def test_authorize_requires_matching_bearer_key(self) -> None:
        self.assertTrue(self.app.is_authorized('Bearer local-proxy-key'))
        self.assertFalse(self.app.is_authorized('Bearer wrong-key'))
        self.assertFalse(self.app.is_authorized(''))

    def test_forward_responses_request_rejects_wrong_local_key(self) -> None:
        response = self.app.forward_responses_request(
            auth_header='Bearer wrong-key',
            body_bytes=b'{"model":"gpt-5.4","input":"Hi"}',
            upstream_fn=lambda *_args, **_kwargs: None,
        )

        self.assertEqual(401, response.status_code)

    def test_forward_responses_request_translates_payload_before_upstream(self) -> None:
        captured: dict[str, object] = {}

        def upstream(
            token_state: token_pool_proxy.TokenState,
            payload: dict[str, object],
            _path: str,
        ) -> token_pool_proxy.ForwardResponse:
            captured['token'] = token_state.file_name
            captured['payload'] = payload
            return token_pool_proxy.ForwardResponse(status_code=200, body=b'ok', headers={'content-type': 'text/plain'})

        response = self.app.forward_responses_request(
            auth_header='Bearer local-proxy-key',
            body_bytes=b'{"model":"gpt-5.4","input":"Hi"}',
            upstream_fn=upstream,
        )

        self.assertEqual(200, response.status_code)
        self.assertEqual('a.json', captured['token'])
        self.assertTrue(captured['payload']['stream'])
        self.assertEqual('message', captured['payload']['input'][0]['type'])


if __name__ == '__main__':
    unittest.main()
