import json
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

import controlled_browser


class _FakeTransport:
    def __init__(self, responses: list[dict[str, object] | str]) -> None:
        self.sent: list[dict[str, object]] = []
        self._responses = [json.dumps(item) if isinstance(item, dict) else item for item in responses]
        self.closed = False

    def send(self, payload: str) -> None:
        self.sent.append(json.loads(payload))

    def recv(self) -> str:
        if not self._responses:
            raise RuntimeError("No more fake responses.")
        return self._responses.pop(0)

    def close(self) -> None:
        self.closed = True


class ControlledBrowserTransportTests(unittest.TestCase):
    def test_create_default_transport_suppresses_origin_header(self) -> None:
        fake_socket = object()
        fake_module = SimpleNamespace(create_connection=mock.Mock(return_value=fake_socket))

        with mock.patch.dict(sys.modules, {"websocket": fake_module}):
            transport = controlled_browser.create_default_transport("ws://127.0.0.1:9222/devtools/page/abc", timeout_seconds=7.0)

        fake_module.create_connection.assert_called_once_with(
            "ws://127.0.0.1:9222/devtools/page/abc",
            timeout=7.0,
            suppress_origin=True,
        )
        self.assertIs(fake_socket, transport.socket)

    def test_send_command_uses_incrementing_ids_and_returns_result(self) -> None:
        transport = _FakeTransport(
            [
                {"method": "Runtime.consoleAPICalled", "params": {}},
                {"id": 1, "result": {"ok": True}},
                {"id": 2, "result": {"value": 2}},
            ]
        )
        session = controlled_browser.ControlledBrowserSession(transport)

        first = session.send_command("Page.navigate", {"url": "https://example.com"})
        second = session.send_command("Runtime.evaluate", {"expression": "2"})

        self.assertEqual({"ok": True}, first)
        self.assertEqual({"value": 2}, second)
        self.assertEqual(1, transport.sent[0]["id"])
        self.assertEqual(2, transport.sent[1]["id"])

    def test_send_command_surfaces_protocol_error(self) -> None:
        transport = _FakeTransport([{"id": 1, "error": {"message": "boom"}}])
        session = controlled_browser.ControlledBrowserSession(transport)

        with self.assertRaisesRegex(controlled_browser.ControlledBrowserProtocolError, "boom"):
            session.send_command("Runtime.evaluate")

    def test_connect_to_page_uses_factory(self) -> None:
        transport = _FakeTransport([])

        def fake_factory(page_ws_url: str, timeout_seconds: float = 0.0) -> _FakeTransport:
            self.assertEqual("ws://127.0.0.1:9222/devtools/page/abc", page_ws_url)
            self.assertEqual(3.0, timeout_seconds)
            return transport

        session = controlled_browser.connect_to_page(
            "ws://127.0.0.1:9222/devtools/page/abc",
            timeout_seconds=3.0,
            transport_factory=fake_factory,
        )

        self.assertIsInstance(session, controlled_browser.ControlledBrowserSession)
        session.close()
        self.assertTrue(transport.closed)


class ControlledBrowserActionTests(unittest.TestCase):
    def test_get_page_info_uses_runtime_evaluate(self) -> None:
        transport = _FakeTransport(
            [
                {
                    "id": 1,
                    "result": {
                        "result": {
                            "type": "object",
                            "value": {"url": "https://example.com", "title": "Example", "readyState": "complete"},
                        }
                    },
                }
            ]
        )
        session = controlled_browser.ControlledBrowserSession(transport)

        info = session.get_page_info()

        self.assertEqual("https://example.com", info["url"])
        self.assertEqual("Runtime.evaluate", transport.sent[0]["method"])

    def test_navigate_uses_page_navigate(self) -> None:
        transport = _FakeTransport([{"id": 1, "result": {"frameId": "frame-1"}}])
        session = controlled_browser.ControlledBrowserSession(transport)

        result = session.navigate("https://example.com")

        self.assertEqual("frame-1", result["frameId"])
        self.assertEqual("Page.navigate", transport.sent[0]["method"])

    def test_click_uses_runtime_evaluate(self) -> None:
        transport = _FakeTransport([{"id": 1, "result": {"result": {"type": "object", "value": {"ok": True}}}}])
        session = controlled_browser.ControlledBrowserSession(transport)

        session.click("#submit")

        self.assertEqual("Runtime.evaluate", transport.sent[0]["method"])
        self.assertIn("#submit", transport.sent[0]["params"]["expression"])

    def test_type_uses_runtime_evaluate(self) -> None:
        transport = _FakeTransport(
            [
                {"id": 1, "result": {"result": {"type": "object", "value": {"ok": True}}}},
                {"id": 2, "result": {}},
                {"id": 3, "result": {"result": {"type": "object", "value": {"ok": True}}}},
            ]
        )
        session = controlled_browser.ControlledBrowserSession(transport)

        session.type("input[name=q]", "hello")

        self.assertEqual("Runtime.evaluate", transport.sent[0]["method"])
        self.assertEqual("Input.insertText", transport.sent[1]["method"])
        self.assertEqual("hello", transport.sent[1]["params"]["text"])
        self.assertEqual("Runtime.evaluate", transport.sent[2]["method"])
        self.assertIn("dispatchEvent", transport.sent[2]["params"]["expression"])

    def test_press_uses_runtime_evaluate(self) -> None:
        transport = _FakeTransport([{"id": 1, "result": {"result": {"type": "object", "value": {"ok": True}}}}])
        session = controlled_browser.ControlledBrowserSession(transport)

        session.press("Enter")

        self.assertEqual("Runtime.evaluate", transport.sent[0]["method"])
        self.assertIn("Enter", transport.sent[0]["params"]["expression"])

    def test_wait_for_text_polls_until_match(self) -> None:
        transport = _FakeTransport(
            [
                {"id": 1, "result": {"result": {"type": "boolean", "value": False}}},
                {"id": 2, "result": {"result": {"type": "boolean", "value": True}}},
            ]
        )
        session = controlled_browser.ControlledBrowserSession(transport)

        result = session.wait_for_text("Done", timeout_ms=100, poll_interval_seconds=0.0)

        self.assertEqual({"ok": True, "text": "Done"}, result)
        self.assertEqual(2, len(transport.sent))

    def test_wait_for_text_raises_on_timeout(self) -> None:
        transport = _FakeTransport(
            [
                {"id": 1, "result": {"result": {"type": "boolean", "value": False}}},
                {"id": 2, "result": {"result": {"type": "boolean", "value": False}}},
            ]
        )
        session = controlled_browser.ControlledBrowserSession(transport)

        with mock.patch("controlled_browser.time.monotonic", side_effect=[0.0, 0.0001, 0.01]):
            with self.assertRaisesRegex(controlled_browser.ControlledBrowserProtocolError, "Timed out waiting for text"):
                session.wait_for_text("Never", timeout_ms=1, poll_interval_seconds=0.0)


if __name__ == "__main__":
    unittest.main()
