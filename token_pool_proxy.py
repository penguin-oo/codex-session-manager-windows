import json
import os
import sys
import time
from argparse import ArgumentParser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Iterator
from urllib import error as url_error
from urllib import request as url_request

DEFAULT_MODEL_IDS = (
    "gpt-5.5",
    "gpt-5.4",
    "gpt-5.3-codex",
    "gpt-5.2",
    "gpt-5",
)
DEFAULT_UPSTREAM_BASE_URL = "https://chatgpt.com/backend-api/codex"
DEFAULT_FALLBACK_INSTRUCTIONS = "You are Codex, a coding assistant."


def _resolve_max_failover_attempts(total_states: int) -> int:
    raw = os.environ.get("TOKEN_POOL_MAX_FAILOVER_ATTEMPTS", "").strip()
    if not raw:
        return max(1, total_states)
    try:
        value = int(raw)
    except ValueError:
        value = total_states
    return max(1, min(max(1, total_states), value))


@dataclass
class TokenState:
    file_name: str
    access_token: str
    source_path: Path
    cooldown_until: float = 0.0
    last_error: str = ''


@dataclass
class ForwardResponse:
    status_code: int
    body: bytes
    headers: dict[str, str]


@dataclass
class StreamingForwardResponse:
    """Response that streams body chunks from upstream."""
    status_code: int
    headers: dict[str, str]
    chunk_iterator: Iterator[bytes]
    raw_response: object  # holds the requests.Response for cleanup


class TokenPoolUpstreamError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        retryable: bool = False,
        quota_exhausted: bool = False,
        status_code: int = 500,
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.quota_exhausted = quota_exhausted
        self.status_code = status_code


class TokenPoolForwardingError(RuntimeError):
    pass


class TokenPool:
    def __init__(
        self,
        token_dir: Path,
        cooldown_seconds: int = 1800,
        time_fn: Callable[[], float] | None = None,
        state_file: Path | None = None,
    ) -> None:
        self.token_dir = Path(token_dir)
        self.cooldown_seconds = cooldown_seconds
        self.time_fn = time_fn or time.time
        self.state_file = Path(state_file) if state_file is not None else self.token_dir / '.token-pool-state'
        self._cursor = 0
        self._states: list[TokenState] = self._load_states()

    def _load_states(self) -> list[TokenState]:
        states: list[TokenState] = []
        if not self.token_dir.exists():
            return states
        for path in sorted(self.token_dir.glob('*.json')):
            try:
                payload = json.loads(path.read_text(encoding='utf-8'))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict):
                continue
            access_token = str(
                payload.get('access_token')
                or payload.get('token')
                or payload.get('api_key')
                or ''
            ).strip()
            if not access_token:
                continue
            states.append(TokenState(file_name=path.name, access_token=access_token, source_path=path))
        persisted = self._load_persisted_state()
        for state in states:
            saved = persisted.get(state.file_name)
            if not isinstance(saved, dict):
                continue
            try:
                state.cooldown_until = float(saved.get('cooldown_until', 0.0) or 0.0)
            except (TypeError, ValueError):
                state.cooldown_until = 0.0
            state.last_error = str(saved.get('last_error', '') or '').strip()
        return states

    def _load_persisted_state(self) -> dict[str, dict[str, object]]:
        if not self.state_file.exists():
            return {}
        try:
            payload = json.loads(self.state_file.read_text(encoding='utf-8'))
        except (OSError, ValueError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        result: dict[str, dict[str, object]] = {}
        for key, value in payload.items():
            if isinstance(key, str) and isinstance(value, dict):
                result[key] = value
        return result

    def _save_persisted_state(self) -> None:
        payload = {
            state.file_name: {
                'cooldown_until': state.cooldown_until,
                'last_error': state.last_error,
            }
            for state in self._states
            if state.cooldown_until > 0.0 or state.last_error
        }
        try:
            if payload:
                self.state_file.parent.mkdir(parents=True, exist_ok=True)
                self.state_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
            elif self.state_file.exists():
                self.state_file.unlink()
        except OSError:
            pass

    def states(self) -> list[TokenState]:
        return list(self._states)

    def state_for(self, file_name: str) -> TokenState:
        for state in self._states:
            if state.file_name == file_name:
                return state
        raise FileNotFoundError(f'Token state not found: {file_name}')

    def select_token(self) -> TokenState:
        if not self._states:
            raise RuntimeError('No token files available.')
        now = self.time_fn()
        total = len(self._states)
        for offset in range(total):
            index = (self._cursor + offset) % total
            state = self._states[index]
            if state.cooldown_until > now:
                continue
            self._cursor = (index + 1) % total
            return state
        raise RuntimeError('No usable tokens available.')

    def mark_quota_failure(self, file_name: str, message: str) -> None:
        state = self.state_for(file_name)
        state.cooldown_until = self.time_fn() + float(self.cooldown_seconds)
        state.last_error = message.strip()
        self._save_persisted_state()

    def mark_retryable_failure(self, file_name: str, message: str) -> None:
        state = self.state_for(file_name)
        state.last_error = message.strip()
        self._save_persisted_state()


class TokenPoolForwarder:
    def __init__(self, pool: TokenPool) -> None:
        self.pool = pool

    def _sanitize_message(self, message: str) -> str:
        clean = message
        for state in self.pool.states():
            if state.access_token:
                clean = clean.replace(state.access_token, '[redacted-token]')
        return clean

    def _is_model_capacity_error(self, message: str) -> bool:
        text = message.lower()
        return (
            'selected model is at capacity' in text
            or ('at capacity' in text and 'model' in text)
            or 'please try a different model' in text
        )

    def forward_with_failover(self, upstream_fn: Callable[[TokenState], ForwardResponse | StreamingForwardResponse]) -> ForwardResponse | StreamingForwardResponse:
        states = self.pool.states()
        if not states:
            raise TokenPoolForwardingError('No token files available.')
        last_error = 'No usable tokens available.'
        max_attempts = _resolve_max_failover_attempts(len(states))
        for _ in range(max_attempts):
            try:
                state = self.pool.select_token()
            except RuntimeError as exc:
                raise TokenPoolForwardingError(self._sanitize_message(str(exc))) from exc
            try:
                return upstream_fn(state)
            except TokenPoolUpstreamError as exc:
                sanitized = self._sanitize_message(str(exc))
                last_error = sanitized
                if exc.quota_exhausted or exc.status_code in {401, 403, 429} or self._is_model_capacity_error(sanitized):
                    self.pool.mark_quota_failure(state.file_name, sanitized)
                    continue
                if exc.retryable or exc.status_code >= 500:
                    self.pool.mark_retryable_failure(state.file_name, sanitized)
                    continue
                raise TokenPoolForwardingError(sanitized) from exc
        raise TokenPoolForwardingError(last_error)


def _normalize_input_item(item: object) -> dict[str, object] | None:
    if not isinstance(item, dict):
        return None
    normalized = dict(item)
    if normalized.get('type') == 'message':
        role = str(normalized.get('role', '')).strip().lower()
        if role == 'system':
            normalized['role'] = 'developer'
    return normalized


def translate_codex_request(payload: dict[str, object]) -> dict[str, object]:
    translated = dict(payload)
    input_value = translated.get('input')
    if isinstance(input_value, str):
        translated['input'] = [
            {
                'type': 'message',
                'role': 'user',
                'content': [{'type': 'input_text', 'text': input_value}],
            }
        ]
    elif isinstance(input_value, list):
        translated['input'] = [item for raw in input_value if (item := _normalize_input_item(raw)) is not None]
    translated['stream'] = True
    translated['store'] = False
    translated['parallel_tool_calls'] = True
    translated['include'] = ['reasoning.encrypted_content']
    instructions = str(translated.get('instructions', '') or '').strip()
    translated['instructions'] = instructions or DEFAULT_FALLBACK_INSTRUCTIONS
    if translated.get('service_tier') != 'priority':
        translated.pop('service_tier', None)
    for key in (
        'max_output_tokens',
        'max_completion_tokens',
        'temperature',
        'top_p',
        'truncation',
        'user',
        'context_management',
        'previous_response_id',
        'prompt_cache_retention',
        'safety_identifier',
    ):
        translated.pop(key, None)
    return translated


def build_models_payload(model_ids: tuple[str, ...] = DEFAULT_MODEL_IDS) -> dict[str, object]:
    return {
        'object': 'list',
        'data': [
            {
                'id': model_id,
                'object': 'model',
                'owned_by': 'openai',
            }
            for model_id in model_ids
        ],
    }


class TokenPoolProxyApp:
    def __init__(
        self,
        pool: TokenPool,
        local_api_key: str,
        proxy_port: int,
        upstream_base_url: str = DEFAULT_UPSTREAM_BASE_URL,
    ) -> None:
        self.pool = pool
        self.local_api_key = local_api_key.strip()
        self.proxy_port = int(proxy_port)
        self.upstream_base_url = upstream_base_url.rstrip('/')

    def build_health_payload(self) -> dict[str, object]:
        return {
            'status': 'ok',
            'backend_mode': 'built_in_token_pool',
            'token_count': len(self.pool.states()),
            'port': self.proxy_port,
        }

    def _build_sse_failed_event(self, message: str) -> bytes:
        payload = {
            'type': 'response.failed',
            'error': {
                'message': message,
            },
        }
        data = json.dumps(payload, ensure_ascii=False)
        return f'event: response.failed\ndata: {data}\n\n'.encode('utf-8')

    def _safe_stream_iterator(self, response: object) -> Iterator[bytes]:
        iterator = response.iter_content(chunk_size=4096)
        try:
            for chunk in iterator:
                if chunk:
                    yield chunk
        except Exception as exc:
            message = self._build_sse_failed_event(f'Upstream stream interrupted: {exc}')
            yield message

    def _forward_to_upstream_with_urllib(self, token_state: TokenState, payload: dict[str, object], path: str) -> ForwardResponse | StreamingForwardResponse:
        url = f'{self.upstream_base_url}{path}'
        headers = {
            'Authorization': f'Bearer {token_state.access_token}',
            'Accept': 'text/event-stream',
            'Content-Type': 'application/json',
        }
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        req = url_request.Request(url, data=body, headers=headers, method='POST')
        try:
            upstream = url_request.urlopen(req, timeout=620)
        except url_error.HTTPError as exc:
            status_code = int(getattr(exc, 'code', 500) or 500)
            error_body = exc.read().decode('utf-8', errors='ignore') or str(exc)
            if status_code in {401, 403, 429}:
                raise TokenPoolUpstreamError(error_body, quota_exhausted=True, status_code=status_code) from exc
            if status_code >= 500:
                raise TokenPoolUpstreamError(error_body, retryable=True, status_code=status_code) from exc
            raise TokenPoolUpstreamError(error_body, status_code=status_code) from exc
        except OSError as exc:
            raise TokenPoolUpstreamError(str(exc), retryable=True, status_code=502) from exc

        class _UrllibResponseAdapter:
            def __init__(self, raw_response: object) -> None:
                self._raw_response = raw_response

            def iter_content(self, chunk_size: int = 4096) -> Iterator[bytes]:
                while True:
                    chunk = self._raw_response.read(chunk_size)
                    if not chunk:
                        break
                    yield chunk

            def close(self) -> None:
                self._raw_response.close()

        status_code = int(getattr(upstream, 'status', upstream.getcode()) or 200)
        content_type = str(upstream.headers.get('content-type', 'application/json'))
        adapter = _UrllibResponseAdapter(upstream)
        return StreamingForwardResponse(
            status_code=status_code,
            headers={'content-type': content_type},
            chunk_iterator=self._safe_stream_iterator(adapter),
            raw_response=adapter,
        )

    def is_authorized(self, auth_header: str) -> bool:
        expected = f'Bearer {self.local_api_key}'
        return bool(self.local_api_key) and auth_header.strip() == expected

    def build_models_response(self, auth_header: str) -> ForwardResponse:
        if not self.is_authorized(auth_header):
            return ForwardResponse(401, b'{"error":{"message":"Unauthorized"}}', {'content-type': 'application/json'})
        body = json.dumps(build_models_payload(), ensure_ascii=False).encode('utf-8')
        return ForwardResponse(200, body, {'content-type': 'application/json'})

    def forward_responses_request(
        self,
        *,
        auth_header: str,
        body_bytes: bytes,
        upstream_fn: Callable[[TokenState, dict[str, object], str], ForwardResponse | StreamingForwardResponse],
        path: str = '/responses',
    ) -> ForwardResponse | StreamingForwardResponse:
        if not self.is_authorized(auth_header):
            return ForwardResponse(
                status_code=401,
                body=b'{"error":{"message":"Unauthorized"}}',
                headers={'content-type': 'application/json'},
            )
        try:
            payload = json.loads(body_bytes.decode('utf-8'))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            return ForwardResponse(
                status_code=400,
                body=b'{"error":{"message":"Invalid JSON body"}}',
                headers={'content-type': 'application/json'},
            )
        if not isinstance(payload, dict):
            return ForwardResponse(
                status_code=400,
                body=b'{"error":{"message":"JSON body must be an object"}}',
                headers={'content-type': 'application/json'},
            )
        translated = translate_codex_request(payload)
        try:
            return TokenPoolForwarder(self.pool).forward_with_failover(
                lambda token_state: upstream_fn(token_state, translated, path)
            )
        except TokenPoolForwardingError as exc:
            body = json.dumps({'error': {'message': str(exc)}}).encode('utf-8')
            return ForwardResponse(status_code=502, body=body, headers={'content-type': 'application/json'})

    def _forward_to_upstream(self, token_state: TokenState, payload: dict[str, object], path: str) -> ForwardResponse | StreamingForwardResponse:
        try:
            import requests
        except ModuleNotFoundError:
            return self._forward_to_upstream_with_urllib(token_state, payload, path)

        url = f'{self.upstream_base_url}{path}'
        headers = {
            'Authorization': f'Bearer {token_state.access_token}',
            'Accept': 'text/event-stream',
            'Content-Type': 'application/json',
        }
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=(20, 600), stream=True)
        except requests.RequestException as exc:
            raise TokenPoolUpstreamError(str(exc), retryable=True, status_code=502) from exc
        content_type = response.headers.get('content-type', 'application/json')
        if response.status_code in {401, 403, 429}:
            error_body = response.text or response.reason
            response.close()
            raise TokenPoolUpstreamError(error_body, quota_exhausted=True, status_code=response.status_code)
        if response.status_code >= 500:
            error_body = response.text or response.reason
            response.close()
            raise TokenPoolUpstreamError(error_body, retryable=True, status_code=response.status_code)
        if response.status_code >= 400:
            error_body = response.text or response.reason
            response.close()
            raise TokenPoolUpstreamError(error_body, status_code=response.status_code)
        # For successful responses, return a streaming response so SSE data
        # is forwarded chunk-by-chunk instead of buffered in memory.
        return StreamingForwardResponse(
            status_code=response.status_code,
            headers={'content-type': content_type},
            chunk_iterator=self._safe_stream_iterator(response),
            raw_response=response,
        )

    def forward_to_upstream(self, auth_header: str, body_bytes: bytes, path: str = '/responses') -> ForwardResponse | StreamingForwardResponse:
        return self.forward_responses_request(
            auth_header=auth_header,
            body_bytes=body_bytes,
            upstream_fn=self._forward_to_upstream,
            path=path,
        )


class TokenPoolProxyHandler(BaseHTTPRequestHandler):
    server_version = 'CodexTokenPoolProxy/1.0'
    protocol_version = 'HTTP/1.1'

    @property
    def app(self) -> TokenPoolProxyApp:
        return self.server.proxy_app  # type: ignore[attr-defined]

    def _write_response(self, response: ForwardResponse) -> None:
        self.send_response(response.status_code)
        for key, value in response.headers.items():
            self.send_header(key, value)
        self.send_header('Content-Length', str(len(response.body)))
        self.end_headers()
        if response.body:
            self.wfile.write(response.body)

    def _write_streaming_response(self, response: StreamingForwardResponse) -> None:
        self.send_response(response.status_code)
        for key, value in response.headers.items():
            self.send_header(key, value)
        self.send_header('Transfer-Encoding', 'chunked')
        self.end_headers()
        try:
            for chunk in response.chunk_iterator:
                if not chunk:
                    continue
                # HTTP chunked encoding: size in hex, CRLF, data, CRLF
                self.wfile.write(f'{len(chunk):x}\r\n'.encode('ascii'))
                self.wfile.write(chunk)
                self.wfile.write(b'\r\n')
                self.wfile.flush()
            # Final zero-length chunk to signal end
            self.wfile.write(b'0\r\n\r\n')
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            raw = getattr(response, 'raw_response', None)
            if raw and hasattr(raw, 'close'):
                raw.close()

    def _read_body(self) -> bytes:
        length = int(self.headers.get('Content-Length', '0') or '0')
        return self.rfile.read(length) if length > 0 else b''

    def log_message(self, format: str, *args: object) -> None:
        return

    def do_GET(self) -> None:
        if self.path == '/health':
            body = json.dumps(self.app.build_health_payload(), ensure_ascii=False).encode('utf-8')
            self._write_response(ForwardResponse(200, body, {'content-type': 'application/json'}))
            return
        if self.path == '/models':
            self._write_response(self.app.build_models_response(self.headers.get('Authorization', '')))
            return
        self._write_response(ForwardResponse(404, b'{"error":{"message":"Not found"}}', {'content-type': 'application/json'}))

    def do_POST(self) -> None:
        if self.path in {'/responses', '/responses/compact'}:
            response = self.app.forward_to_upstream(
                self.headers.get('Authorization', ''),
                self._read_body(),
                path=self.path,
            )
            if isinstance(response, StreamingForwardResponse):
                self._write_streaming_response(response)
            else:
                self._write_response(response)
            return
        self._write_response(ForwardResponse(404, b'{"error":{"message":"Not found"}}', {'content-type': 'application/json'}))


def run_server(*, token_dir: Path, api_key: str, port: int, upstream_base_url: str = DEFAULT_UPSTREAM_BASE_URL) -> int:
    pool = TokenPool(token_dir=token_dir)
    app = TokenPoolProxyApp(pool=pool, local_api_key=api_key, proxy_port=port, upstream_base_url=upstream_base_url)
    server = ThreadingHTTPServer(('127.0.0.1', int(port)), TokenPoolProxyHandler)
    server.proxy_app = app  # type: ignore[attr-defined]
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = ArgumentParser()
    parser.add_argument('--token-dir', required=True)
    parser.add_argument('--api-key', required=True)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--upstream-base-url', default=os.environ.get('TOKEN_POOL_UPSTREAM_BASE_URL', DEFAULT_UPSTREAM_BASE_URL))
    args = parser.parse_args(argv)
    return run_server(
        token_dir=Path(args.token_dir),
        api_key=args.api_key,
        port=args.port,
        upstream_base_url=args.upstream_base_url,
    )


if __name__ == '__main__':
    sys.exit(main())
