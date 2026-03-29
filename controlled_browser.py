import json
import time
from dataclasses import dataclass


class ControlledBrowserError(RuntimeError):
    pass


class ControlledBrowserTransportError(ControlledBrowserError):
    pass


class ControlledBrowserProtocolError(ControlledBrowserError):
    pass


@dataclass
class _WebSocketTransport:
    socket: object

    def send(self, payload: str) -> None:
        self.socket.send(payload)

    def recv(self) -> str:
        data = self.socket.recv()
        if isinstance(data, bytes):
            return data.decode("utf-8", errors="ignore")
        return str(data)

    def close(self) -> None:
        try:
            self.socket.close()
        except Exception:
            return


def create_default_transport(page_ws_url: str, timeout_seconds: float = 5.0) -> _WebSocketTransport:
    try:
        import websocket as websocket_client
    except Exception as exc:
        raise ControlledBrowserTransportError(
            "websocket-client package is required for controlled browser actions."
        ) from exc
    try:
        socket = websocket_client.create_connection(
            page_ws_url,
            timeout=timeout_seconds,
            suppress_origin=True,
        )
    except Exception as exc:
        raise ControlledBrowserTransportError(f"Failed to connect to DevTools WebSocket: {exc}") from exc
    return _WebSocketTransport(socket)


def _extract_runtime_value(payload: dict[str, object]) -> object:
    result = payload.get("result")
    if not isinstance(result, dict):
        return None
    if "value" in result:
        return result.get("value")
    if result.get("type") == "undefined":
        return None
    return result


def _json_string(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


class ControlledBrowserSession:
    def __init__(self, transport: object) -> None:
        self.transport = transport
        self._next_id = 0

    def close(self) -> None:
        close = getattr(self.transport, "close", None)
        if callable(close):
            close()

    def __enter__(self) -> "ControlledBrowserSession":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def send_command(self, method: str, params: dict[str, object] | None = None) -> dict[str, object]:
        self._next_id += 1
        message_id = self._next_id
        envelope = {
            "id": message_id,
            "method": method,
            "params": params or {},
        }
        self.transport.send(json.dumps(envelope, ensure_ascii=False))
        while True:
            raw_message = self.transport.recv()
            payload = json.loads(raw_message)
            if not isinstance(payload, dict):
                continue
            if payload.get("id") != message_id:
                continue
            if isinstance(payload.get("error"), dict):
                error = payload["error"]
                raise ControlledBrowserProtocolError(str(error.get("message", "DevTools command failed.")))
            result = payload.get("result", {})
            if isinstance(result, dict):
                return result
            return {}

    def evaluate(self, expression: str, *, await_promise: bool = True, return_by_value: bool = True) -> object:
        result = self.send_command(
            "Runtime.evaluate",
            {
                "expression": expression,
                "awaitPromise": await_promise,
                "returnByValue": return_by_value,
            },
        )
        if isinstance(result.get("exceptionDetails"), dict):
            raise ControlledBrowserProtocolError("JavaScript evaluation failed.")
        return _extract_runtime_value(result)

    def get_page_info(self) -> dict[str, object]:
        value = self.evaluate(
            "(() => ({url: location.href, title: document.title, readyState: document.readyState}))()"
        )
        return dict(value) if isinstance(value, dict) else {}

    def get_html(self) -> str:
        value = self.evaluate("document.documentElement ? document.documentElement.outerHTML : ''")
        return str(value or "")

    def navigate(self, url: str) -> dict[str, object]:
        return self.send_command("Page.navigate", {"url": str(url)})

    def click(self, selector: str) -> dict[str, object]:
        value = self.evaluate(
            f"""
            (() => {{
              const el = document.querySelector({_json_string(selector)});
              if (!el) return {{ok: false, error: 'Selector not found.'}};
              el.scrollIntoView({{block: 'center', inline: 'center'}});
              el.click();
              return {{ok: true}};
            }})()
            """
        )
        if not isinstance(value, dict) or not bool(value.get("ok")):
            raise ControlledBrowserProtocolError(str((value or {}).get("error", "Click failed.")))
        return dict(value)

    def type(self, selector: str, text: str) -> dict[str, object]:
        value = self.evaluate(
            f"""
            (() => {{
              const el = document.querySelector({_json_string(selector)});
              if (!el) return {{ok: false, error: 'Selector not found.'}};
              el.scrollIntoView({{block: 'center', inline: 'center'}});
              el.focus();
              if ('value' in el) {{
                if (typeof el.setSelectionRange === 'function') {{
                  const length = typeof el.value === 'string' ? el.value.length : 0;
                  el.setSelectionRange(0, length);
                }}
              }} else if (el.isContentEditable) {{
                const selection = window.getSelection();
                const range = document.createRange();
                range.selectNodeContents(el);
                selection.removeAllRanges();
                selection.addRange(range);
              }} else {{
                return {{ok: false, error: 'Element is not editable.'}};
              }}
              return {{ok: true}};
            }})()
            """
        )
        if not isinstance(value, dict) or not bool(value.get("ok")):
            raise ControlledBrowserProtocolError(str((value or {}).get("error", "Type failed.")))
        self.send_command("Input.insertText", {"text": str(text)})
        self.evaluate(
            f"""
            (() => {{
              const el = document.querySelector({_json_string(selector)});
              if (!el) return {{ok: false, error: 'Selector not found after input.'}};
              el.dispatchEvent(new InputEvent('input', {{
                bubbles: true,
                data: {_json_string(text)},
                inputType: 'insertText',
              }}));
              el.dispatchEvent(new Event('change', {{bubbles: true}}));
              return {{ok: true}};
            }})()
            """
        )
        return dict(value)

    def press(self, key: str) -> dict[str, object]:
        value = self.evaluate(
            f"""
            (() => {{
              const target = document.activeElement || document.body || document.documentElement;
              if (!target) return {{ok: false, error: 'No active target.'}};
              const down = new KeyboardEvent('keydown', {{key: {_json_string(key)}, bubbles: true}});
              const up = new KeyboardEvent('keyup', {{key: {_json_string(key)}, bubbles: true}});
              target.dispatchEvent(down);
              target.dispatchEvent(up);
              return {{ok: true}};
            }})()
            """
        )
        if not isinstance(value, dict) or not bool(value.get("ok")):
            raise ControlledBrowserProtocolError(str((value or {}).get("error", "Key press failed.")))
        return dict(value)

    def wait_for_text(self, text: str, timeout_ms: int = 5000, poll_interval_seconds: float = 0.1) -> dict[str, object]:
        deadline = time.monotonic() + (max(int(timeout_ms), 1) / 1000.0)
        while time.monotonic() < deadline:
            found = self.evaluate(
                f"""
                (() => {{
                  const bodyText = document.body ? (document.body.innerText || '') : '';
                  return bodyText.includes({_json_string(text)});
                }})()
                """
            )
            if bool(found):
                return {"ok": True, "text": str(text)}
            time.sleep(poll_interval_seconds)
        raise ControlledBrowserProtocolError(f"Timed out waiting for text: {text}")


def connect_to_page(
    page_ws_url: str,
    *,
    timeout_seconds: float = 5.0,
    transport_factory=create_default_transport,
) -> ControlledBrowserSession:
    transport = transport_factory(page_ws_url, timeout_seconds=timeout_seconds)
    return ControlledBrowserSession(transport)
