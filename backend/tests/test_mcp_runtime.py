from __future__ import annotations

import json
from io import BytesIO
from types import SimpleNamespace

import pytest

import mcp_runtime
from testing.mcp import json_rpc, mcp_text_result


class FakeHandler:
    def __init__(
        self,
        path: str,
        *,
        body: bytes = b"",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.path = path
        self.headers = headers or {"content-length": str(len(body))}
        self.rfile = BytesIO(body)
        self.wfile = BytesIO()
        self.status: int | None = None
        self.response_headers: list[tuple[str, str]] = []
        self.ended = False

    def send_response(self, status: int) -> None:
        self.status = status

    def send_header(self, name: str, value: str) -> None:
        self.response_headers.append((name, value))

    def end_headers(self) -> None:
        self.ended = True


def test_tool_registry_lists_calls_and_rejects_unknown_tools() -> None:
    registry = mcp_runtime.ToolRegistry()

    @registry.tool("echo", "Echo input")
    def echo(arguments: dict[str, object]) -> dict[str, object]:
        return arguments

    @registry.tool(
        "sum",
        "Sum values",
        {"type": "object", "properties": {"value": {"type": "number"}}},
    )
    def sum_tool(arguments: dict[str, object]) -> int:
        return int(arguments["value"]) + 1

    assert registry.list_tools() == [
        {
            "name": "echo",
            "description": "Echo input",
            "inputSchema": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
        {
            "name": "sum",
            "description": "Sum values",
            "inputSchema": {
                "type": "object",
                "properties": {"value": {"type": "number"}},
            },
        },
    ]
    assert registry.call("echo", {"ok": True}) == {"ok": True}
    assert registry.call("sum", {"value": 2}) == 3
    with pytest.raises(mcp_runtime.ToolError, match="Unknown tool: missing"):
        registry.call("missing", {})


def test_handle_rpc_covers_initialize_ping_list_call_and_errors() -> None:
    registry = mcp_runtime.ToolRegistry()

    @registry.tool("ok", "OK")
    def ok_tool(arguments: dict[str, object]) -> dict[str, object]:
        return {"arguments": arguments}

    @registry.tool("tool-error", "Tool error")
    def tool_error(_arguments: dict[str, object]) -> None:
        raise mcp_runtime.ToolError("expected", code="expected_error")

    @registry.tool("crash", "Crash")
    def crash(_arguments: dict[str, object]) -> None:
        raise RuntimeError("unexpected")

    initialize = mcp_runtime._handle_rpc(registry, "server", json_rpc("initialize"))
    notification = mcp_runtime._handle_rpc(
        registry,
        "server",
        json_rpc("notifications/initialized", request_id=None),
    )
    ping = mcp_runtime._handle_rpc(registry, "server", json_rpc("ping"))
    listed = mcp_runtime._handle_rpc(registry, "server", json_rpc("tools/list"))
    missing_name = mcp_runtime._handle_rpc(
        registry,
        "server",
        json_rpc("tools/call", params={"arguments": {}}),
    )
    non_dict_params = mcp_runtime._handle_rpc(
        registry,
        "server",
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": "bad"},
    )
    non_dict_arguments = mcp_runtime._handle_rpc(
        registry,
        "server",
        json_rpc("tools/call", params={"name": "ok", "arguments": "bad"}),
    )
    success = mcp_runtime._handle_rpc(
        registry,
        "server",
        json_rpc("tools/call", params={"name": "ok", "arguments": {"x": 1}}),
    )
    tool_error_response = mcp_runtime._handle_rpc(
        registry,
        "server",
        json_rpc("tools/call", params={"name": "tool-error"}),
    )
    crash_response = mcp_runtime._handle_rpc(
        registry,
        "server",
        json_rpc("tools/call", params={"name": "crash"}),
    )
    unknown = mcp_runtime._handle_rpc(registry, "server", json_rpc("unknown"))

    assert initialize["result"]["serverInfo"] == {"name": "server", "version": "1.0.0"}
    assert notification is None
    assert ping == {"jsonrpc": "2.0", "id": 1, "result": {}}
    assert listed["result"]["tools"][0]["name"] == "ok"
    assert missing_name["error"] == {"code": -32602, "message": "Tool name is required"}
    assert non_dict_params["error"] == {
        "code": -32602,
        "message": "Tool name is required",
    }
    assert mcp_text_result(non_dict_arguments) == {"arguments": {}}
    assert mcp_text_result(success) == {"arguments": {"x": 1}}
    assert mcp_text_result(tool_error_response) == {
        "success": False,
        "code": "expected_error",
        "message": "expected",
    }
    assert tool_error_response["result"]["isError"] is True
    assert mcp_text_result(crash_response) == {
        "success": False,
        "code": "internal_error",
        "message": "unexpected",
    }
    assert unknown["error"] == {"code": -32601, "message": "Method not found"}


def test_json_response_read_json_and_authorize(monkeypatch) -> None:
    handler = FakeHandler("/mcp")
    mcp_runtime._json_response(handler, 201, {"ok": True})

    assert handler.status == 201
    assert ("content-type", "application/json") in handler.response_headers
    assert json.loads(handler.wfile.getvalue()) == {"ok": True}
    assert mcp_runtime._read_json(FakeHandler("/mcp")) == {}
    assert mcp_runtime._read_json(
        FakeHandler(
            "/mcp",
            body=b'{"ok": true}',
            headers={"content-length": "12"},
        ),
    ) == {"ok": True}
    assert mcp_runtime._authorize(FakeHandler("/mcp")) is True

    monkeypatch.setenv("FORGER_APP_MCP_TOKEN", "token")

    assert mcp_runtime._authorize(FakeHandler("/mcp")) is False
    assert (
        mcp_runtime._authorize(
            FakeHandler("/mcp", headers={"authorization": "Bearer token"}),
        )
        is True
    )


def test_run_mcp_server_handler_http_paths(monkeypatch) -> None:
    registry = mcp_runtime.ToolRegistry()

    @registry.tool("ok", "OK")
    def ok_tool(arguments: dict[str, object]) -> dict[str, object]:
        return {"ok": arguments.get("ok", True)}

    captured: dict[str, object] = {}

    class FakeServer:
        def __init__(self, address: tuple[str, int], handler_cls: type) -> None:
            captured["address"] = address
            captured["handler_cls"] = handler_cls

        def serve_forever(self) -> None:
            captured["served"] = True

    monkeypatch.setenv("PORT", "8989")
    monkeypatch.setattr(mcp_runtime, "ThreadingHTTPServer", FakeServer)

    mcp_runtime.run_mcp_server(registry, server_name="server")

    assert captured["address"] == ("127.0.0.1", 8989)
    assert captured["served"] is True
    handler_cls = captured["handler_cls"]

    health = FakeHandler("/health")
    handler_cls.do_GET(health)
    not_found = FakeHandler("/missing")
    handler_cls.do_GET(not_found)

    wrong_path = FakeHandler("/wrong")
    handler_cls.do_POST(wrong_path)

    monkeypatch.setenv("FORGER_APP_MCP_TOKEN", "token")
    unauthorized = FakeHandler("/mcp")
    handler_cls.do_POST(unauthorized)

    monkeypatch.delenv("FORGER_APP_MCP_TOKEN", raising=False)
    invalid_json = FakeHandler(
        "/mcp",
        body=b"{",
        headers={"content-length": "1"},
    )
    handler_cls.do_POST(invalid_json)

    notification_body = json.dumps(json_rpc("notifications/initialized")).encode()
    notification = FakeHandler(
        "/mcp",
        body=notification_body,
        headers={"content-length": str(len(notification_body))},
    )
    handler_cls.do_POST(notification)

    batch_body = json.dumps(
        [
            json_rpc("ping", request_id=1),
            json_rpc(
                "tools/call",
                request_id=2,
                params={"name": "ok", "arguments": {"ok": False}},
            ),
        ],
    ).encode()
    batch = FakeHandler(
        "/mcp",
        body=batch_body,
        headers={"content-length": str(len(batch_body))},
    )
    handler_cls.do_POST(batch)

    single_body = json.dumps(json_rpc("tools/list")).encode()
    single = FakeHandler(
        "/mcp",
        body=single_body,
        headers={"content-length": str(len(single_body))},
    )
    handler_cls.do_POST(single)
    handler_cls.log_message(SimpleNamespace(), "ignored")

    assert health.status == 200
    assert json.loads(health.wfile.getvalue()) == {"status": "ok", "server": "server"}
    assert not_found.status == 404
    assert wrong_path.status == 404
    assert unauthorized.status == 401
    assert invalid_json.status == 400
    assert notification.status == 202
    assert json.loads(batch.wfile.getvalue())[0] == {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {},
    }
    assert json.loads(single.wfile.getvalue())["result"]["tools"][0]["name"] == "ok"


def test_run_mcp_server_accepts_explicit_port_and_main(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeServer:
        def __init__(self, address: tuple[str, int], _handler_cls: type) -> None:
            captured["address"] = address

        def serve_forever(self) -> None:
            return None

    monkeypatch.setattr(mcp_runtime, "ThreadingHTTPServer", FakeServer)
    mcp_runtime.run_mcp_server(
        mcp_runtime.ToolRegistry(),
        server_name="server",
        host="0.0.0.0",
        port=7777,
    )
    assert captured["address"] == ("0.0.0.0", 7777)

    def fake_run_mcp_server(
        registry: mcp_runtime.ToolRegistry,
        *,
        server_name: str,
        host: str,
        port: int | None = None,
    ) -> None:
        captured["main"] = (registry, server_name, host, port)

    monkeypatch.setattr(mcp_runtime, "run_mcp_server", fake_run_mcp_server)
    monkeypatch.setattr(
        "sys.argv",
        ["mcp", "--host", "127.0.0.2", "--port", "9999"],
    )
    registry = mcp_runtime.ToolRegistry()

    mcp_runtime.main(registry, server_name="main-server")

    assert captured["main"] == (registry, "main-server", "127.0.0.2", 9999)
