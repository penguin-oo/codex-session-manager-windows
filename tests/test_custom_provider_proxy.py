import json
import unittest

import custom_provider_proxy


class CustomProviderProxyTranslationTests(unittest.TestCase):
    def test_translate_responses_request_to_chat_completions_includes_instructions_and_text(self) -> None:
        payload = {
            "model": "mimo-v2-pro",
            "instructions": "You are strict.",
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "Hello"}],
                }
            ],
            "tools": [
                {
                    "type": "function",
                    "name": "lookup_weather",
                    "description": "Lookup weather",
                    "parameters": {
                        "type": "object",
                        "properties": {"city": {"type": "string"}},
                        "required": ["city"],
                    },
                }
            ],
            "max_output_tokens": 32,
        }

        translated = custom_provider_proxy.translate_responses_request_to_chat_completions(payload)

        self.assertEqual("mimo-v2-pro", translated["model"])
        self.assertEqual("developer", translated["messages"][0]["role"])
        self.assertEqual("You are strict.", translated["messages"][0]["content"])
        self.assertEqual("user", translated["messages"][1]["role"])
        self.assertEqual("Hello", translated["messages"][1]["content"][0]["text"])
        self.assertEqual("text", translated["messages"][1]["content"][0]["type"])
        self.assertEqual("lookup_weather", translated["tools"][0]["function"]["name"])
        self.assertEqual(32, translated["max_tokens"])
        self.assertFalse(translated["stream"])

    def test_translate_responses_request_to_chat_completions_maps_image_inputs(self) -> None:
        payload = {
            "model": "mimo-v2-pro",
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": "Describe this image"},
                        {"type": "input_image", "image_url": "data:image/png;base64,abc", "detail": "high"},
                    ],
                }
            ],
        }

        translated = custom_provider_proxy.translate_responses_request_to_chat_completions(payload)

        self.assertEqual("Describe this image", translated["messages"][0]["content"][0]["text"])
        self.assertEqual("image_url", translated["messages"][0]["content"][1]["type"])
        self.assertEqual("data:image/png;base64,abc", translated["messages"][0]["content"][1]["image_url"]["url"])
        self.assertEqual("high", translated["messages"][0]["content"][1]["image_url"]["detail"])

    def test_translate_responses_request_to_chat_completions_maps_tool_output_items(self) -> None:
        payload = {
            "model": "mimo-v2-pro",
            "input": [
                {
                    "type": "function_call_output",
                    "call_id": "call_123",
                    "output": '{"ok":true}',
                }
            ],
        }

        translated = custom_provider_proxy.translate_responses_request_to_chat_completions(payload)

        self.assertEqual("tool", translated["messages"][0]["role"])
        self.assertEqual("call_123", translated["messages"][0]["tool_call_id"])
        self.assertEqual('{"ok":true}', translated["messages"][0]["content"])

    def test_translate_chat_completion_to_responses_output_maps_text_and_tool_calls(self) -> None:
        completion = {
            "id": "chatcmpl_123",
            "model": "mimo-v2-pro",
            "created": 1710000000,
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "tool_calls",
                    "message": {
                        "role": "assistant",
                        "content": "Need tool data first.",
                        "tool_calls": [
                            {
                                "id": "call_123",
                                "type": "function",
                                "function": {
                                    "name": "lookup_weather",
                                    "arguments": '{"city":"Shanghai"}',
                                },
                            }
                        ],
                    },
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }

        response_payload = custom_provider_proxy.translate_chat_completion_to_responses_output(completion)

        self.assertEqual("response", response_payload["object"])
        self.assertEqual("mimo-v2-pro", response_payload["model"])
        self.assertEqual("message", response_payload["output"][0]["type"])
        self.assertEqual("Need tool data first.", response_payload["output"][0]["content"][0]["text"])
        self.assertEqual("function_call", response_payload["output"][1]["type"])
        self.assertEqual("lookup_weather", response_payload["output"][1]["name"])
        self.assertEqual('{"city":"Shanghai"}', response_payload["output"][1]["arguments"])
        self.assertEqual(15, response_payload["usage"]["total_tokens"])

    def test_build_responses_sse_from_chat_completion_emits_text_and_completion_events(self) -> None:
        completion = {
            "id": "chatcmpl_123",
            "model": "mimo-v2-pro",
            "created": 1710000000,
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": "Hello world",
                    },
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
        }

        chunks = list(custom_provider_proxy.build_responses_sse_from_chat_completion(completion))
        joined = b"".join(chunks).decode("utf-8")

        self.assertIn("response.output_text.delta", joined)
        self.assertIn("Hello world", joined)
        self.assertIn("response.completed", joined)


if __name__ == "__main__":
    unittest.main()
