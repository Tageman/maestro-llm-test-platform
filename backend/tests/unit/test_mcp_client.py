from typing import Any, Mapping

import pytest

from maestro_app.infrastructure.mcp_client import MaestroMcpClient, MaestroMcpError


class FakeTransport:
    def __init__(self) -> None:
        self.started = False
        self.closed = False
        self.sent: list[dict[str, Any]] = []
        self.responses = [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {"serverInfo": {"name": "maestro"}},
            },
            {
                "jsonrpc": "2.0",
                "id": 2,
                "result": {"tools": [{"name": "list_devices"}]},
            },
            {
                "jsonrpc": "2.0",
                "id": 3,
                "result": {"content": [{"type": "text", "text": "ready"}]},
            },
        ]

    def start(self) -> None:
        self.started = True

    def send(self, message: Mapping[str, Any]) -> None:
        self.sent.append(dict(message))

    def receive(self, timeout_seconds: float) -> dict[str, Any]:
        return self.responses.pop(0)

    def close(self) -> None:
        self.closed = True


def test_mcp_client_initializes_lists_and_calls_tools() -> None:
    transport = FakeTransport()

    with MaestroMcpClient("maestro", transport=transport) as client:
        tools = client.list_tools()
        result = client.call_tool("list_devices")

    assert tools["tools"][0]["name"] == "list_devices"
    assert result["content"][0]["text"] == "ready"
    assert transport.started and transport.closed
    assert transport.sent[0]["method"] == "initialize"
    assert transport.sent[1]["method"] == "notifications/initialized"
    assert transport.sent[-1]["params"]["name"] == "list_devices"


def test_mcp_client_rejects_tool_error() -> None:
    transport = FakeTransport()
    transport.responses[-1] = {
        "jsonrpc": "2.0",
        "id": 3,
        "result": {"isError": True, "content": []},
    }

    with MaestroMcpClient("maestro", transport=transport) as client:
        client.list_tools()
        with pytest.raises(MaestroMcpError, match="returned an error"):
            client.call_tool("list_devices")
