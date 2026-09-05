import json
import os
import sys
from argparse import ArgumentParser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from itertools import count
from typing import Iterator
from urllib import error as url_error
from urllib import parse as url_parse
from urllib import request as url_request

import token_pool_settings


DEFAULT_MODEL_IDS = (
    "gpt-5.5",
    "gpt-5.4",
    "gpt-5.3-codex",
    "gpt-5.2",
    "gpt-5",
)
DEFAULT_UPSTREAM_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/136.0.0.0 Safari/537.36"
)

_BLOCKED_TOOL_TYPES = frozenset({"image_generation"})
_PASSTHROUGH_HEADER_NAMES = frozenset(
    {
        "originator",
        "session-id",
        "thread-id",
        "x-client-request-id",
        "x-codex-beta-features",
        "x-codex-turn-metadata",
        "x-codex-window-id",
    }
)


def _strip_blocked_tools(payload: dict[str, object]) -> dict[str, object]:
    """Remove tool types that third-party API panels typically reject."""
    raw_tools = payload.get("tools")
    if not isinstance(raw_tools, list):
        return payload
    filtered = [
        t for t in raw_tools
        if not (isinstance(t, dict) and str(t.get("type", "")).strip() in _BLOCKED_TOOL_TYPES)
    ]
    result = dict(payload)
    if filtered:
        result["tools"] = filtered
    else:
        result.pop("tools", None)
    return result


def build_upstream_headers(
    *,
    upstream_api_key: str,
    accept: str,
    client_headers: object | None = None,
) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {upstream_api_key}",
        "Accept": accept,
        "Content-Type": "application/json",
        "User-Agent": DEFAULT_UPSTREAM_USER_AGENT,
    }
    if client_headers is None:
        return headers

    try:
        header_items = client_headers.items()  # type: ignore[attr-defined]
    except AttributeError:
        return headers

    for raw_name, raw_value in header_items:
        name = str(raw_name).strip()
        value = str(raw_value).strip()
        if not name or not value:
            continue
        lower_name = name.lower()
        if lower_name not in _PASSTHROUGH_HEADER_NAMES:
            continue
        if lower_name == "originator":
            headers["originator"] = value
        else:
            headers[name] = value
    return headers


def _detect_system_proxy() -> str | None:
    """Detect system proxy from env vars or Windows registry."""
    for key in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
        value = os.environ.get(key, "").strip()
        if value:
            return value
    if os.name == "nt":
        try:
            import winreg
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as reg_key:
                try:
                    enabled, _ = winreg.QueryValueEx(reg_key, "ProxyEnable")
                    if int(enabled) != 1:
                        return None
                except (FileNotFoundError, TypeError, ValueError):
                    return None
                try:
                    server, _ = winreg.QueryValueEx(reg_key, "ProxyServer")
                except FileNotFoundError:
                    return None
                server = str(server).strip()
                if not server:
                    return None
                if "://" not in server:
                    server = "http://" + server
                return server
        except (ImportError, OSError):
            pass
    return None


def _proxy_aware_urlopen(
    req: url_request.Request,
    timeout: float = 620,
    explicit_proxy: str = "",
) -> object:
    """Open URL trying direct first, falling back to system proxy.

    Falls back to proxy on:
    - Network errors (SSL, DNS, connection refused)
    - Cloudflare-style HTML responses (200 OK but content is HTML, not API JSON)
    """
    clean_explicit_proxy = explicit_proxy.strip()
    if clean_explicit_proxy:
        proxy_handler = url_request.ProxyHandler({"http": clean_explicit_proxy, "https": clean_explicit_proxy})
        opener = url_request.build_opener(proxy_handler)
        return opener.open(req, timeout=timeout)

    proxy = _detect_system_proxy()
    direct_opener = url_request.build_opener(url_request.ProxyHandler({}))
    try:
        response = direct_opener.open(req, timeout=timeout)
        # Check if the response is HTML (Cloudflare block) instead of API data
        content_type = str(response.headers.get("content-type", "")).lower()
        if "text/html" in content_type and proxy:
            response.close()
            proxy_handler = url_request.ProxyHandler({"http": proxy, "https": proxy})
            opener = url_request.build_opener(proxy_handler)
            return opener.open(req, timeout=timeout)
        return response
    except (url_error.URLError, OSError):
        if not proxy:
            raise
        proxy_handler = url_request.ProxyHandler({"http": proxy, "https": proxy})
        opener = url_request.build_opener(proxy_handler)
        return opener.open(req, timeout=timeout)


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


def _response_function_call_to_chat_message(item: dict[str, object]) -> dict[str, object] | None:
    if str(item.get("type", "")).strip() != "function_call":
        return None
    call_id = str(item.get("call_id", "")).strip()
    name = str(item.get("name", "")).strip()
    if not call_id or not name:
        return None
    arguments = item.get("arguments", "")
    if isinstance(arguments, str):
        clean_arguments = arguments.strip()
    else:
        clean_arguments = json.dumps(arguments, ensure_ascii=False)
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": clean_arguments,
                },
            }
        ],
    }


def normalize_chat_completion_usage(usage: object) -> dict[str, object]:
    if not isinstance(usage, dict):
        return {
            "input_tokens": 0,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens": 0,
            "output_tokens_details": {"reasoning_tokens": 0},
            "total_tokens": 0,
        }

    prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
    completion_tokens = int(usage.get("completion_tokens", 0) or 0)
    total_tokens = int(usage.get("total_tokens", prompt_tokens + completion_tokens) or 0)

    prompt_details = usage.get("prompt_tokens_details", {})
    if not isinstance(prompt_details, dict):
        prompt_details = {}
    completion_details = usage.get("completion_tokens_details", {})
    if not isinstance(completion_details, dict):
        completion_details = {}

    return {
        "input_tokens": prompt_tokens,
        "input_tokens_details": {
            "cached_tokens": int(prompt_details.get("cached_tokens", 0) or 0),
        },
        "output_tokens": completion_tokens,
        "output_tokens_details": {
            "reasoning_tokens": int(completion_details.get("reasoning_tokens", 0) or 0),
        },
        "total_tokens": total_tokens,
    }


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
    seen_tool_call_ids: set[str] = set()
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
            elif item_type == "function_call":
                message = _response_function_call_to_chat_message(raw)
                if message is not None:
                    translated["messages"].append(message)
                    for tool_call in message.get("tool_calls", []):
                        if isinstance(tool_call, dict):
                            call_id = str(tool_call.get("id", "")).strip()
                            if call_id:
                                seen_tool_call_ids.add(call_id)
            elif item_type == "function_call_output":
                call_id = str(raw.get("call_id", "")).strip()
                tool_content = _stringify_tool_output(raw.get("output"))
                if call_id and tool_content:
                    if call_id in seen_tool_call_ids:
                        translated["messages"].append(
                            {
                                "role": "tool",
                                "tool_call_id": call_id,
                                "content": tool_content,
                            }
                        )
                    else:
                        translated["messages"].append(
                            {
                                "role": "user",
                                "content": f"Tool output for {call_id}:\n{tool_content}",
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
        "usage": normalize_chat_completion_usage(completion.get("usage")),
    }
    return response_payload


def chat_completion_error_response(completion: dict[str, object]) -> ForwardResponse | None:
    choices = completion.get("choices")
    if isinstance(choices, list) and choices:
        return None
    raw_error = completion.get("error")
    message = ""
    if isinstance(raw_error, dict):
        message = str(raw_error.get("message", "")).strip()
    elif isinstance(raw_error, str):
        message = raw_error.strip()
    if not message:
        message = str(completion.get("message", "") or completion.get("msg", "")).strip()
    if not message:
        message = "Upstream chat completion response did not include choices."
    body = json.dumps({"error": {"message": message}}, ensure_ascii=False).encode("utf-8")
    return ForwardResponse(502, body, {"content-type": "application/json"})


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
    codex_models = [
        {
            "slug": model_id,
            "display_name": model_id,
            "description": model_id,
            "default_reasoning_level": "medium",
            "supported_reasoning_levels": [
                {"effort": "low", "description": "Fast responses with lighter reasoning"},
                {"effort": "medium", "description": "Balances speed and reasoning depth"},
                {"effort": "high", "description": "Greater reasoning depth for complex tasks"},
                {"effort": "xhigh", "description": "Extra high reasoning depth"},
            ],
            "shell_type": "shell_command",
            "visibility": "list",
            "supported_in_api": True,
            "priority": 0,
            "base_instructions": "",
            "instructions_variables": {},
            "supports_reasoning_summaries": True,
            "default_reasoning_summary": "none",
            "support_verbosity": True,
            "default_verbosity": "low",
            "apply_patch_tool_type": "freeform",
            "web_search_tool_type": "text_and_image",
            "truncation_policy": {"mode": "tokens", "limit": 10000},
            "supports_parallel_tool_calls": True,
            "supports_image_detail_original": True,
            "context_window": token_pool_settings.CODEX_CONTEXT_WINDOW,
            "max_context_window": token_pool_settings.CODEX_CONTEXT_WINDOW,
            "comp_hash": "",
            "effective_context_window_percent": 95,
            "experimental_supported_tools": [],
            "input_modalities": ["text", "image"],
            "supports_search_tool": False,
            "use_responses_lite": False,
        }
        for model_id in model_ids
    ]
    return {
        "object": "list",
        "models": codex_models,
        "data": [
            {
                "id": model_id,
                "object": "model",
                "owned_by": "openai",
            }
            for model_id in model_ids
        ],
    }


def _responses_payload_has_output(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    has_output_field = "output" in payload
    has_output_text_field = "output_text" in payload
    output = payload.get("output")
    if isinstance(output, list) and output:
        return True
    output_text = str(payload.get("output_text", "")).strip()
    if output_text:
        return True
    return not has_output_field and not has_output_text_field


def _responses_forward_response_has_output(response: ForwardResponse) -> bool:
    if response.status_code < 200 or response.status_code >= 300:
        return True
    try:
        payload = json.loads(response.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return True
    return _responses_payload_has_output(payload)


def _normalize_upstream_base_url(url: str) -> str:
    """Ensure upstream base URL includes an API version path (e.g. /v1).

    Third-party "new-api" panels expect paths like ``/v1/responses`` or
    ``/v1/chat/completions``.  When the user enters just the domain
    (for example ``https://provider.example``) the requests hit the web panel instead of the
    API.  This helper appends ``/v1`` when no version path is present.
    """
    url = url.strip().rstrip("/")
    if not url:
        return url
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        path = parsed.path.rstrip("/")
        # Already has a version-prefixed path like /v1, /v2, /v3 …
        if path and path.rsplit("/", 1)[-1].startswith("v") and path.rsplit("/", 1)[-1][1:].isdigit():
            return url
        # Already has some path (e.g. /api) — leave it alone
        if path:
            return url
    except Exception:
        pass
    return f"{url}/v1"


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
        upstream_proxy_url: str = "",
    ) -> None:
        self.local_api_key = local_api_key.strip()
        self.proxy_port = int(proxy_port)
        self.upstream_base_url = _normalize_upstream_base_url(upstream_base_url)
        self.upstream_api_key = upstream_api_key.strip()
        self.upstream_protocol = upstream_protocol.strip() or token_pool_settings.OPENAI_PROTOCOL_RESPONSES
        self.model_ids = tuple(str(model_id).strip() for model_id in model_ids if str(model_id).strip()) or DEFAULT_MODEL_IDS
        self.upstream_proxy_url = upstream_proxy_url.strip()

    def build_health_payload(self) -> dict[str, object]:
        return {
            "status": "ok",
            "backend_mode": token_pool_settings.BACKEND_MODE_OPENAI_COMPATIBLE,
            "port": self.proxy_port,
            "protocol": self.upstream_protocol,
            "model_count": len(self.model_ids),
            "config_fingerprint": token_pool_settings.openai_compatible_proxy_config_fingerprint(
                local_api_key=self.local_api_key,
                upstream_base_url=self.upstream_base_url,
                upstream_api_key=self.upstream_api_key,
                upstream_protocol=self.upstream_protocol,
                model_ids=self.model_ids,
                upstream_proxy_url=self.upstream_proxy_url,
            ),
        }

    def is_authorized(self, auth_header: str) -> bool:
        return bool(self.local_api_key) and auth_header.strip() == f"Bearer {self.local_api_key}"

    def build_models_response(self, auth_header: str) -> ForwardResponse:
        if not self.is_authorized(auth_header):
            return ForwardResponse(401, b'{"error":{"message":"Unauthorized"}}', {"content-type": "application/json"})
        body = json.dumps(build_models_payload(self.model_ids), ensure_ascii=False).encode("utf-8")
        return ForwardResponse(200, body, {"content-type": "application/json"})

    def _safe_stream_iterator(self, response: object) -> Iterator[bytes]:
        iterator = response.iter_content(chunk_size=4096)
        try:
            for chunk in iterator:
                if chunk:
                    yield chunk
        except Exception as exc:
            payload = {
                "type": "response.failed",
                "error": {
                    "message": f"Upstream stream interrupted: {exc}",
                },
            }
            data = json.dumps(payload, ensure_ascii=False)
            yield f"event: response.failed\ndata: {data}\n\n".encode("utf-8")

    @staticmethod
    def _responses_upstream_path(path: str) -> str:
        if path == "/responses/compact":
            return "/responses"
        return path or "/responses"

    def _forward_json_request(
        self,
        path: str,
        payload: dict[str, object],
        client_headers: object | None = None,
    ) -> tuple[int, bytes, dict[str, str]]:
        request = url_request.Request(
            f"{self.upstream_base_url}{path}",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=build_upstream_headers(
                upstream_api_key=self.upstream_api_key,
                accept="application/json",
                client_headers=client_headers,
            ),
            method="POST",
        )
        try:
            with _proxy_aware_urlopen(request, timeout=620, explicit_proxy=self.upstream_proxy_url) as response:
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

    def _forward_responses_request(
        self,
        path: str,
        payload: dict[str, object],
        client_headers: object | None = None,
    ) -> ForwardResponse | StreamingForwardResponse:
        request = url_request.Request(
            f"{self.upstream_base_url}{path}",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=build_upstream_headers(
                upstream_api_key=self.upstream_api_key,
                accept="text/event-stream" if payload.get("stream") else "application/json",
                client_headers=client_headers,
            ),
            method="POST",
        )
        try:
            upstream = _proxy_aware_urlopen(request, timeout=620, explicit_proxy=self.upstream_proxy_url)
        except url_error.HTTPError as exc:
            return (
                ForwardResponse(
                    int(getattr(exc, "code", 500) or 500),
                    exc.read(),
                    {"content-type": str(exc.headers.get("content-type", "application/json")) if exc.headers else "application/json"},
                )
            )
        except (OSError, ValueError, url_error.URLError) as exc:
            body = json.dumps({"error": {"message": f"Failed to connect to upstream: {exc}"}}, ensure_ascii=False).encode("utf-8")
            return ForwardResponse(502, body, {"content-type": "application/json"})

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

        status_code = int(getattr(upstream, "status", upstream.getcode()) or 200)
        content_type = str(upstream.headers.get("content-type", "application/json"))
        if payload.get("stream") or "text/event-stream" in content_type.lower():
            adapter = _UrllibResponseAdapter(upstream)
            return StreamingForwardResponse(
                status_code=status_code,
                headers={"content-type": content_type},
                chunk_iterator=self._safe_stream_iterator(adapter),
                raw_response=adapter,
            )
        try:
            body = upstream.read()
        finally:
            upstream.close()
        return ForwardResponse(status_code, body, {"content-type": content_type})

    def forward_request(
        self,
        auth_header: str,
        body_bytes: bytes,
        path: str = "/responses",
        client_headers: object | None = None,
    ) -> ForwardResponse | StreamingForwardResponse:
        if not self.is_authorized(auth_header):
            return ForwardResponse(401, b'{"error":{"message":"Unauthorized"}}', {"content-type": "application/json"})
        try:
            payload = json.loads(body_bytes.decode("utf-8"))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            return ForwardResponse(400, b'{"error":{"message":"Invalid JSON body"}}', {"content-type": "application/json"})
        if not isinstance(payload, dict):
            return ForwardResponse(400, b'{"error":{"message":"JSON body must be an object"}}', {"content-type": "application/json"})

        # Strip tools that third-party panels typically reject.
        payload = _strip_blocked_tools(payload)

        if self.upstream_protocol == token_pool_settings.OPENAI_PROTOCOL_RESPONSES:
            response = self._forward_responses_request(self._responses_upstream_path(path), payload, client_headers)
            if isinstance(response, StreamingForwardResponse) or _responses_forward_response_has_output(response):
                return response

        translated = translate_responses_request_to_chat_completions(payload)
        status_code, body, headers = self._forward_json_request("/chat/completions", translated, client_headers)
        if status_code >= 400:
            return ForwardResponse(status_code, body, headers)
        try:
            completion = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            return ForwardResponse(502, b'{"error":{"message":"Invalid upstream response"}}', {"content-type": "application/json"})
        if not isinstance(completion, dict):
            return ForwardResponse(502, b'{"error":{"message":"Invalid upstream response"}}', {"content-type": "application/json"})
        if error_response := chat_completion_error_response(completion):
            return error_response

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
        finally:
            raw = getattr(response, "raw_response", None)
            if raw and hasattr(raw, "close"):
                raw.close()

    def do_GET(self) -> None:
        parsed_path = url_parse.urlparse(self.path).path
        if parsed_path == "/health":
            body = json.dumps(self.app.build_health_payload(), ensure_ascii=False).encode("utf-8")
            self._write_response(ForwardResponse(200, body, {"content-type": "application/json"}))
            return
        if parsed_path == "/models":
            self._write_response(self.app.build_models_response(self.headers.get("Authorization", "")))
            return
        self._write_response(ForwardResponse(404, b'{"error":{"message":"Not found"}}', {"content-type": "application/json"}))

    def do_POST(self) -> None:
        if self.path in {"/responses", "/responses/compact"}:
            response = self.app.forward_request(
                self.headers.get("Authorization", ""),
                self._read_body(),
                self.path,
                dict(self.headers.items()),
            )
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
    upstream_proxy_url: str = "",
) -> int:
    app = CustomProviderProxyApp(
        local_api_key=api_key,
        proxy_port=port,
        upstream_base_url=upstream_base_url,
        upstream_api_key=upstream_api_key,
        upstream_protocol=upstream_protocol,
        model_ids=model_ids,
        upstream_proxy_url=upstream_proxy_url,
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
    parser.add_argument("--upstream-proxy-url", default="")
    parser.add_argument("--model", action="append", dest="models", default=[])
    args = parser.parse_args(argv)
    return run_server(
        api_key=args.api_key,
        port=args.port,
        upstream_base_url=args.upstream_base_url,
        upstream_api_key=args.upstream_api_key,
        upstream_protocol=args.upstream_protocol,
        upstream_proxy_url=args.upstream_proxy_url,
        model_ids=args.models or list(DEFAULT_MODEL_IDS),
    )


if __name__ == "__main__":
    sys.exit(main())
