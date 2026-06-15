from __future__ import annotations

import asyncio
import json
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import websockets
from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect


def live_transcription_websocket_url(session: dict[str, Any]) -> str:
    url = str(session.get("url") or "")
    token = str(session.get("token") or "")
    if not url:
        raise ValueError("live_transcription_url_missing")
    if not token:
        return url
    parsed = urlsplit(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.setdefault("token", token)
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment)
    )


async def proxy_live_transcription_websocket(
    client_websocket: WebSocket,
    session: dict[str, Any],
) -> None:
    await client_websocket.accept()
    try:
        target_url = live_transcription_websocket_url(session)
    except ValueError:
        await client_websocket.close(code=1011, reason="live_transcription_url_missing")
        return
    try:
        async with websockets.connect(target_url, ping_interval=20, ping_timeout=20) as target:
            async def client_to_target() -> None:
                try:
                    while True:
                        message = await client_websocket.receive()
                        if message.get("type") == "websocket.disconnect":
                            await target.close()
                            return
                        if "bytes" in message and message["bytes"] is not None:
                            await target.send(message["bytes"])
                        elif "text" in message and message["text"] is not None:
                            start_frame = normalize_live_transcription_start_frame(
                                message["text"],
                                session,
                            )
                            await target.send(start_frame)
                except WebSocketDisconnect:
                    await target.close()

            async def target_to_client() -> None:
                async for message in target:
                    if isinstance(message, bytes):
                        await client_websocket.send_bytes(message)
                    else:
                        await client_websocket.send_text(message)

            first_done, pending = await asyncio.wait(
                {
                    asyncio.create_task(client_to_target()),
                    asyncio.create_task(target_to_client()),
                },
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            for task in first_done:
                task.result()
    except Exception:
        await client_websocket.close(code=1013, reason="live_transcription_target_unavailable")


def normalize_live_transcription_start_frame(message: str, session: dict[str, Any]) -> str:
    try:
        payload = json.loads(message)
    except json.JSONDecodeError:
        return message
    if not isinstance(payload, dict) or payload.get("type") != "start":
        return message
    payload.pop("model", None)
    if not payload.get("task") and isinstance(session.get("task"), str):
        payload["task"] = session["task"]
    if not payload.get("language") and isinstance(session.get("language"), str):
        payload["language"] = session["language"]
    return json.dumps(payload, separators=(",", ":"))
