import json
import sys
from argparse import ArgumentParser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from itertools import count
from typing import Iterator
from urllib import error as url_error
from urllib import request as url_request

import token_pool_settings


DEFAULT_MODEL_IDS = (
    "gpt-5.5",
    "gpt-5.4",
    "gpt-5.3-codex",
    "gpt-5.2",
    "gpt-5",
)


@dataclass
class ForwardResponse:
    status_code: int
    body: bytes
    headers: dict[str, str]


@dataclass
class StreamingForwardResponse:
    status_code: int
    headers: dict[str, str]
    chunk_iterator: Iterator[bytes]
    raw_response: object | None = None


def _flatten_text_parts(content: object) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "text":
            text = str(item.get("text", "")).strip()
            if text:
                parts.append(text)
        elif item.get("type") == "refusal":
            text = str(item.get("refusal", "")).strip()
            if text:
                parts.append(text)
    return "\n".join(parts).strip()


def _normalize_response_message_content(content: object) -> list[dict[str, object]]:
    if isinstance(content, str):
        text = content.strip()
        return [{"type": "output_text", "text": text, "annotations": []}] if text else []
    if not isinstance(content, list):
        return []
    normalized: list[dict[str, object]] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "text":
            text = str(item.get("text", "")).strip()
            if text:
                normalized.append({"type": "output_text", "text": text, "annotations": []})
        elif item.get("type") == "refusal":
            refusal = str(item.get("refusal", "")).strip()
            if refusal:
                normalized.append({"type": "refusal", "refusal": refusal})
    return normalized


def _stringify_tool_output(output: object) -> str:
    if isinstance(output, str):
        return output
    if isinstance(output, list):
        text_parts: list[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("type", "")).strip()
            if item_type == "input_text":
                text = str(item.get("text", "")).strip()
                if text:
                    text_parts.append(text)
            elif item_type == "input_image":
                image_url = str(item.get("image_url", "")).strip()
                if image_url:
                    text_parts.append(image_url)
        return "\n".join(text_parts).strip()
    return json.dumps(output, ensure_ascii=False)


def _response_content_part_to_chat_part(item: dict[str, object]) -> dict[str, object] | None:
    item_type = str(item.get("type", "")).strip()
    if item_type == "input_text":
        text = str(item.get("text", "")).strip()
        if text:
            return {"type": "text", "text": text}
        return None
    if item_type == "input_image":
        image_url = str(item.get("image_url", "")).strip()
        if not image_url:
            return None
        image_payload: dict[str, object] = {"url": image_url}
        detail = str(item.get("detail", "")).strip()
        if detail:
            image_payload["detail"] = detail
        return {"type": "image_url", "image_url": image_payload}
    return None


def _response_message_to_chat_message(item: dict[str, object]) -> dict[str, object] | None:
    role = str(item.get("role", "")).strip().lower()
    content = item.get("content")
    if isinstance(content, str):
        clean_content = content.strip()
        if clean_content:
            return {"role": "developer" if role in {"developer", "system"} else role or "user", "content": clean_content}
        return None
    if not isinstance(content, list):
        return None
    chat_parts = [part for raw in content if isinstance(raw, dict) if (part := _response_content_part_to_chat_part(raw)) is not None]
    if not chat_parts:
        return None
    normalized_role = "developer" if role in {"developer", "system"} else role or "user"
    return {"role": normalized_role, "content": chat_parts}


def _tool_definition_to_chat_tool(item: dict[str, object]) -> dict[str, object] | None:
    if str(item.get("type", "")).strip() != "function":
        return None
    name = str(item.get("name", "")).strip()
    if not name:
        return None
    function_payload: dict[str, object] = {"name": name}
    description = str(item.get("description", "")).strip()
    if description:
        function_payload["description"] = description
    parameters = item.get("parameters")
    if isinstance(parameters, dict):
        function_payload["parameters"] = parameters
    if "strict" in item:
        function_payload["strict"] = bool(item.get("strict"))
    return {"type": "function", "function": function_payload}


def translate_responses_request_to_chat_completions(payload: dict[str, object]) -> dict[str, object]:
    translated: dict[str, object] = {
        "model": str(payload.get("model", "")).strip(),
        "messages": [],
        "stream": False,
    }
    instructions = payload.get("instructions")
    if isinstance(instructions, str) and instructions.strip():
        translated["messages"].append({"role": "developer", "content": instructions.strip()})
    elif isinstance(instructions, list):
        for raw in instructions:
            if isinstance(raw, dict):
                message = _response_message_to_chat_message(raw)
                if message is not None:
                    translated["messages"].append(message)

    input_value = payload.get("input")
    if isinstance(input_value, str):
        clean_input = input_value.strip()
        if clean_input:
            translated["messages"].append({"role": "user", "content": clean_input})
    elif isinstance(input_value, list):
        for raw in input_value:
            if not isinstance(raw, dict):
                continue
            item_type = str(raw.get("type", "")).strip()
            if item_type == "message":
                message = _response_message_to_chat_message(raw)
                if message is not None:
                    translated["messages"].append(message)
            elif item_type == "function_call_output":
                call_id = str(raw.get("call_id", "")).strip()
                tool_content = _stringify_tool_output(raw.get("output"))
                if call_id and tool_content:
                    translated["messages"].append(
                        {
                            "role": "tool",
                            "tool_call_id": call_id,
                            "content": tool_content,
                        }
                    )

    tools = payload.get("tools")
    if isinstance(tools, list):
        translated_tools = [tool for raw in tools if isinstance(raw, dict) if (tool := _tool_definition_to_chat_tool(raw)) is not None]
        if translated_tools:
            translated["tools"] = translated_tools

    max_output_tokens = payload.get("max_output_tokens")
    if isinstance(max_output_tokens, int):
        translated["max_tokens"] = max_output_tokens
    elif isinstance(max_output_tokens, str) and max_output_tokens.isdigit():
        translated["max_tokens"] = int(max_output_tokens)

    if payload.get("tool_choice") is not None:
        translated["tool_choice"] = payload.get("tool_choice")
    if payload.get("response_format") is not None:
        translated["response_format"] = payload.get("response_format")
    if payload.get("parallel_tool_calls") is not None:
        translated["parallel_tool_calls"] = payload.get("parallel_tool_calls")
    if payload.get("temperature") is not None:
        translated["temperature"] = payload.get("temperature")
    if payload.get("top_p") is not None:
        translated["top_p"] = payload.get("top_p")
    if payload.get("service_tier") is not None:
        translated["service_tier"] = payload.get("service_tier")
    return translated


def translate_chat_completion_to_responses_output(completion: dict[str, object]) -> dict[str, object]:
    choices = completion.get("choices", [])
    choice = choices[0] if isinstance(choices, list) and choices else {}
    if not isinstance(choice, dict):
        choice = {}
    message = choice.get("message", {})
    if not isinstance(message, dict):
        message = {}
    completion_id = str(completion.get("id", "")).strip() or "chatcmpl_local"
    response_id = completion_id if completion_id.startswith("resp_") else f"resp_{completion_id}"
    message_item_id = f"msg_{completion_id}_0"
    output_items: list[dict[str, object]] = []

    normalized_content = _normalize_response_message_content(message.get("content"))
    if normalized_content:
        output_items.append(
            {
                "id": message_item_id,
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": normalized_content,
            }
        )

    tool_calls = message.get("tool_calls", [])
    if isinstance(tool_calls, list):
        for index, raw in enumerate(tool_calls):
            if not isinstance(raw, dict):
                continue
            if str(raw.get("type", "")).strip() != "function":
                continue
            function_payload = raw.get("function", {})
            if not isinstance(function_payload, dict):
                function_payload = {}
            tool_call_id = str(raw.get("id", "")).strip() or f"call_{index}"
            output_items.append(
                {
                    "id": f"fc_{tool_call_id}",
                    "type": "function_call",
                    "call_id": tool_call_id,
                    "name": str(function_payload.get("name", "")).strip(),
                    "arguments": str(function_payload.get("arguments", "")).strip(),
                    "status": "completed",
                }
            )

    response_payload = {
        "id": response_id,
        "object": "response",
        "created_at": int(completion.get("created", 0) or 0),
        "model": str(completion.get("model", "")).strip(),
        "output": output_items,
        "status": "completed",
        "usage": dict(completion.get("usage", {})) if isinstance(completion.get("usage"), dict) else {},
    }
    return response_payload


def _sse_event(event_type: str, payload: dict[str, object]) -> bytes:
    data = json.dumps({"type": event_type, **payload}, ensure_ascii=False)
    return f"event: {event_type}\ndata: {data}\n\n".encode("utf-8")


def build_responses_sse_from_chat_completion(completion: dict[str, object]) -> Iterator[bytes]:
    response_payload = translate_chat_completion_to_responses_output(completion)
    response_id = str(response_payload.get("id", "resp_local"))
    created_payload = dict(response_payload)
    created_payload["status"] = "in_progress"
    yield _sse_event("response.created", {"response": created_payload})

    sequence_number = count(1)
    for output_index, item in enumerate(response_payload.get("output", [])):
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type", "")).strip()
        if item_type == "message":
            content = item.get("content", [])
            if isinstance(content, list):
                for content_index, part in enumerate(content):
                    if not isinstance(part, dict):
                        continue
                    if str(part.get("type", "")).strip() != "output_text":
                        continue
                    text = str(part.get("text", "")).strip()
                    if not text:
                        continue
                    yield _sse_event(
                        "response.output_text.delta",
                        {
                            "sequence_number": next(sequence_number),
                            "response_id": response_id,
                            "item_id": str(item.get("id", "")),
                            "output_index": output_index,
                            "content_index": content_index,
                            "delta": text,
                        },
                    )
                    yield _sse_event(
                        "response.output_text.done",
                        {
                            "sequence_number": next(sequence_number),
                            "response_id": response_id,
                            "item_id": str(item.get("id", "")),
                            "output_index": output_index,
                            "content_index": content_index,
                            "text": text,
                        },
                    )
        elif item_type == "function_call":
            arguments = str(item.get("arguments", "")).strip()
            if arguments:
                yield _sse_event(
                    "response.function_call_arguments.delta",
                    {
                        "sequence_number": next(sequence_number),
                        "response_id": response_id,
                        "item_id": str(item.get("id", "")),
                        "output_index": output_index,
                        "delta": arguments,
                    },
                )
                yield _sse_event(
                    "response.function_call_arguments.done",
                    {
                        "sequence_number": next(sequence_number),
                        "response_id": response_id,
                        "item_id": str(item.get("id", "")),
                        "output_index": output_index,
                        "arguments": arguments,
                    },
                )

        yield _sse_event(
            "response.output_item.done",
            {
                "sequence_number": next(sequence_number),
                "response_id": response_id,
                "output_index": output_index,
                "item": item,
            },
        )

    yield _sse_event(
        "response.completed",
        {
            "sequence_number": next(sequence_number),
            "response": response_payload,
        },
    )


def build_models_payload(model_ids: list[str] | tuple[str, ...]) -> dict[str, object]:
    return {
        "object": "list",
        "data": [
            {
                "id": model_id,
                "object": "model",
                "owned_by": "openai",
            }
            for model_id in model_ids
        ],
    }


class CustomProviderProxyApp:
    def __init__(
        self,
        *,
        local_api_key: str,
        proxy_port: int,
        upstream_base_url: str,
        upstream_api_key: str,
        upstream_protocol: str,
        model_ids: list[str] | tuple[str, ...] = DEFAULT_MODEL_IDS,
    ) -> None:
        self.local_api_key = local_api_key.strip()
        self.proxy_port = int(proxy_port)
        self.upstream_base_url = upstream_base_url.strip().rstrip("/")
        self.upstream_api_key = upstream_api_key.strip()
        self.upstream_protocol = upstream_protocol.strip() or token_pool_settings.OPENAI_PROTOCOL_RESPONSES
        self.model_ids = tuple(str(model_id).strip() for model_id in model_ids if str(model_id).strip()) or DEFAULT_MODEL_IDS

    def build_health_payload(self) -> dict[str, object]:
        return {
            "status": "ok",
            "port": self.proxy_port,
            "protocol": self.upstream_protocol,
            "model_count": len(self.model_ids),
        }

    def is_authorized(self, auth_header: str) -> bool:
        return bool(self.local_api_key) and auth_header.strip() == f"Bearer {self.local_api_key}"

    def build_models_response(self, auth_header: str) -> ForwardResponse:
        if not self.is_authorized(auth_header):
            return ForwardResponse(401, b'{"error":{"message":"Unauthorized"}}', {"content-type": "application/json"})
        body = json.dumps(build_models_payload(self.model_ids), ensure_ascii=False).encode("utf-8")
        return ForwardResponse(200, body, {"content-type": "application/json"})

    def _forward_json_request(self, path: str, payload: dict[str, object]) -> tuple[int, bytes, dict[str, str]]:
        request = url_request.Request(
            f"{self.upstream_base_url}{path}",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.upstream_api_key}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with url_request.urlopen(request, timeout=620) as response:
                return (
                    int(getattr(response, "status", response.getcode()) or 200),
                    response.read(),
                    {"content-type": str(response.headers.get("content-type", "application/json"))},
                )
        except url_error.HTTPError as exc:
            return (
                int(getattr(exc, "code", 500) or 500),
                exc.read(),
                {"content-type": str(exc.headers.get("content-type", "application/json")) if exc.headers else "application/json"},
            )

    def forward_request(self, auth_header: str, body_bytes: bytes, path: str = "/responses") -> ForwardResponse | StreamingForwardResponse:
        if not self.is_authorized(auth_header):
            return ForwardResponse(401, b'{"error":{"message":"Unauthorized"}}', {"content-type": "application/json"})
        try:
            payload = json.loads(body_bytes.decode("utf-8"))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            return ForwardResponse(400, b'{"error":{"message":"Invalid JSON body"}}', {"content-type": "application/json"})
        if not isinstance(payload, dict):
            return ForwardResponse(400, b'{"error":{"message":"JSON body must be an object"}}', {"content-type": "application/json"})

        if self.upstream_protocol == token_pool_settings.OPENAI_PROTOCOL_RESPONSES:
            status_code, body, headers = self._forward_json_request(path, payload)
            return ForwardResponse(status_code, body, headers)

        translated = translate_responses_request_to_chat_completions(payload)
        status_code, body, headers = self._forward_json_request("/chat/completions", translated)
        if status_code >= 400:
            return ForwardResponse(status_code, body, headers)
        try:
            completion = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            return ForwardResponse(502, b'{"error":{"message":"Invalid upstream response"}}', {"content-type": "application/json"})
        if not isinstance(completion, dict):
            return ForwardResponse(502, b'{"error":{"message":"Invalid upstream response"}}', {"content-type": "application/json"})

        wants_stream = bool(payload.get("stream", True))
        if wants_stream:
            return StreamingForwardResponse(
                status_code=200,
                headers={"content-type": "text/event-stream"},
                chunk_iterator=build_responses_sse_from_chat_completion(completion),
                raw_response=None,
            )
        response_payload = translate_chat_completion_to_responses_output(completion)
        return ForwardResponse(
            200,
            json.dumps(response_payload, ensure_ascii=False).encode("utf-8"),
            {"content-type": "application/json"},
        )


class CustomProviderProxyHandler(BaseHTTPRequestHandler):
    server_version = "CodexCustomProviderProxy/1.0"
    protocol_version = "HTTP/1.1"

    @property
    def app(self) -> CustomProviderProxyApp:
        return self.server.proxy_app  # type: ignore[attr-defined]

    def log_message(self, format: str, *args: object) -> None:
        return

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", "0") or "0")
        return self.rfile.read(length) if length > 0 else b""

    def _write_response(self, response: ForwardResponse) -> None:
        self.send_response(response.status_code)
        for key, value in response.headers.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(response.body)))
        self.end_headers()
        if response.body:
            self.wfile.write(response.body)

    def _write_streaming_response(self, response: StreamingForwardResponse) -> None:
        self.send_response(response.status_code)
        for key, value in response.headers.items():
            self.send_header(key, value)
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        try:
            for chunk in response.chunk_iterator:
                if not chunk:
                    continue
                self.wfile.write(f"{len(chunk):x}\r\n".encode("ascii"))
                self.wfile.write(chunk)
                self.wfile.write(b"\r\n")
                self.wfile.flush()
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def do_GET(self) -> None:
        if self.path == "/health":
            body = json.dumps(self.app.build_health_payload(), ensure_ascii=False).encode("utf-8")
            self._write_response(ForwardResponse(200, body, {"content-type": "application/json"}))
            return
        if self.path == "/models":
            self._write_response(self.app.build_models_response(self.headers.get("Authorization", "")))
            return
        self._write_response(ForwardResponse(404, b'{"error":{"message":"Not found"}}', {"content-type": "application/json"}))

    def do_POST(self) -> None:
        if self.path in {"/responses", "/responses/compact"}:
            response = self.app.forward_request(self.headers.get("Authorization", ""), self._read_body(), self.path)
            if isinstance(response, StreamingForwardResponse):
                self._write_streaming_response(response)
            else:
                self._write_response(response)
            return
        self._write_response(ForwardResponse(404, b'{"error":{"message":"Not found"}}', {"content-type": "application/json"}))


def run_server(
    *,
    api_key: str,
    port: int,
    upstream_base_url: str,
    upstream_api_key: str,
    upstream_protocol: str,
    model_ids: list[str] | tuple[str, ...],
) -> int:
    app = CustomProviderProxyApp(
        local_api_key=api_key,
        proxy_port=port,
        upstream_base_url=upstream_base_url,
        upstream_api_key=upstream_api_key,
        upstream_protocol=upstream_protocol,
        model_ids=model_ids,
    )
    server = ThreadingHTTPServer(("127.0.0.1", int(port)), CustomProviderProxyHandler)
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
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--upstream-base-url", required=True)
    parser.add_argument("--upstream-api-key", required=True)
    parser.add_argument(
        "--upstream-protocol",
        required=True,
        choices=[
            token_pool_settings.OPENAI_PROTOCOL_RESPONSES,
            token_pool_settings.OPENAI_PROTOCOL_CHAT_COMPLETIONS,
        ],
    )
    parser.add_argument("--model", action="append", dest="models", default=[])
    args = parser.parse_args(argv)
    return run_server(
        api_key=args.api_key,
        port=args.port,
        upstream_base_url=args.upstream_base_url,
        upstream_api_key=args.upstream_api_key,
        upstream_protocol=args.upstream_protocol,
        model_ids=args.models or list(DEFAULT_MODEL_IDS),
    )


if __name__ == "__main__":
    sys.exit(main())
