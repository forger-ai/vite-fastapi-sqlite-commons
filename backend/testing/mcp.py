from __future__ import annotations

import json
from typing import Any


def json_rpc(
    method: str,
    *,
    request_id: int | str | None = 1,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    request: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
    if request_id is not None:
        request["id"] = request_id
    if params is not None:
        request["params"] = params
    return request


def mcp_text_result(response: dict[str, Any]) -> Any:
    text = response["result"]["content"][0]["text"]
    return json.loads(text)

