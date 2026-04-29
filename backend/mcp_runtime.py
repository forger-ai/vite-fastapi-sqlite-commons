"""Minimal HTTP MCP runtime for local Forger app tools."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


JsonDict = dict[str, Any]
ToolHandler = Callable[[JsonDict], Any]


class ToolError(Exception):
    def __init__(self, message: str, *, code: str = "tool_error") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: JsonDict
    handler: ToolHandler


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def tool(
        self,
        name: str,
        description: str,
        input_schema: JsonDict | None = None,
    ) -> Callable[[ToolHandler], ToolHandler]:
        def register(handler: ToolHandler) -> ToolHandler:
            self._tools[name] = ToolDefinition(
                name=name,
                description=description,
                input_schema=input_schema
                or {"type": "object", "properties": {}, "additionalProperties": False},
                handler=handler,
            )
            return handler

        return register

    def list_tools(self) -> list[JsonDict]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "inputSchema": tool.input_schema,
            }
            for tool in self._tools.values()
        ]

    def call(self, name: str, arguments: JsonDict) -> Any:
        tool = self._tools.get(name)
        if tool is None:
            raise ToolError(f"Unknown tool: {name}", code="unknown_tool")
        return tool.handler(arguments)


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: Any) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("content-type", "application/json")
    handler.send_header("cache-control", "no-store")
    handler.send_header("content-length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _read_json(handler: BaseHTTPRequestHandler) -> Any:
    length = int(handler.headers.get("content-length", "0"))
    raw = handler.rfile.read(length).decode("utf-8") if length > 0 else ""
    return json.loads(raw or "{}")


def _content(result: Any, *, is_error: bool = False) -> JsonDict:
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(result, ensure_ascii=False, indent=2),
            }
        ],
        "isError": is_error,
    }


def _authorize(handler: BaseHTTPRequestHandler) -> bool:
    token = os.getenv("FORGER_APP_MCP_TOKEN", "").strip()
    if not token:
        return True
    return handler.headers.get("authorization", "").strip() == f"Bearer {token}"


def _handle_rpc(
    registry: ToolRegistry,
    server_name: str,
    request: JsonDict,
) -> JsonDict | None:
    request_id = request.get("id")
    method = request.get("method")
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": "2025-06-18",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": server_name, "version": "1.0.0"},
            },
        }
    if method == "notifications/initialized":
        return None
    if method == "ping":
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}
    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {"tools": registry.list_tools()},
        }
    if method == "tools/call":
        params = (
            request.get("params")
            if isinstance(request.get("params"), dict)
            else {}
        )
        assert isinstance(params, dict)
        name = params.get("name")
        arguments = (
            params.get("arguments")
            if isinstance(params.get("arguments"), dict)
            else {}
        )
        if not isinstance(name, str):
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32602, "message": "Tool name is required"},
            }
        try:
            result = registry.call(name, arguments)
            return {"jsonrpc": "2.0", "id": request_id, "result": _content(result)}
        except ToolError as exc:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": _content(
                    {"success": False, "code": exc.code, "message": str(exc)},
                    is_error=True,
                ),
            }
        except Exception as exc:  # pragma: no cover - defensive MCP boundary
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": _content(
                    {"success": False, "code": "internal_error", "message": str(exc)},
                    is_error=True,
                ),
            }
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": -32601, "message": "Method not found"},
    }


def run_mcp_server(
    registry: ToolRegistry,
    *,
    server_name: str,
    host: str = "127.0.0.1",
    port: int | None = None,
) -> None:
    resolved_port = port or int(os.getenv("PORT", "8765"))

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/health":
                _json_response(
                    self,
                    HTTPStatus.OK,
                    {"status": "ok", "server": server_name},
                )
                return
            _json_response(self, HTTPStatus.NOT_FOUND, {"error": "not_found"})

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/mcp":
                _json_response(self, HTTPStatus.NOT_FOUND, {"error": "not_found"})
                return
            if not _authorize(self):
                _json_response(self, HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
                return
            try:
                payload = _read_json(self)
                requests = payload if isinstance(payload, list) else [payload]
                responses = [
                    response
                    for request in requests
                    if isinstance(request, dict)
                    for response in [_handle_rpc(registry, server_name, request)]
                    if response is not None
                ]
                if not responses:
                    self.send_response(HTTPStatus.ACCEPTED)
                    self.end_headers()
                    return
                response_payload = (
                    responses if isinstance(payload, list) else responses[0]
                )
                _json_response(self, HTTPStatus.OK, response_payload)
            except json.JSONDecodeError:
                _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "invalid_json"})

        def log_message(self, _format: str, *_args: Any) -> None:
            return

    ThreadingHTTPServer((host, resolved_port), Handler).serve_forever()


def main(registry: ToolRegistry, *, server_name: str) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=os.getenv("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "8765")))
    args = parser.parse_args()
    run_mcp_server(registry, server_name=server_name, host=args.host, port=args.port)
