from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

JsonDict = dict[str, Any]
ChannelAuthorizer = Callable[[str], bool]


def utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


class ChannelHub:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def subscribe(self, channel: str, websocket: WebSocket) -> None:
        async with self._lock:
            self._subscribers[channel].add(websocket)

    async def unsubscribe(self, channel: str, websocket: WebSocket) -> None:
        async with self._lock:
            subscribers = self._subscribers.get(channel)
            if not subscribers:
                return
            subscribers.discard(websocket)
            if not subscribers:
                self._subscribers.pop(channel, None)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            empty: list[str] = []
            for channel, subscribers in self._subscribers.items():
                subscribers.discard(websocket)
                if not subscribers:
                    empty.append(channel)
            for channel in empty:
                self._subscribers.pop(channel, None)

    async def publish(
        self,
        channel: str,
        event_type: str,
        payload: JsonDict | None = None,
    ) -> JsonDict:
        event = {
            "event_id": str(uuid4()),
            "channel": channel,
            "type": event_type,
            "payload": payload or {},
            "created_at": utcnow_iso(),
        }
        async with self._lock:
            subscribers = list(self._subscribers.get(channel, set()))
        stale: list[WebSocket] = []
        for websocket in subscribers:
            try:
                await websocket.send_json(event)
            except RuntimeError:
                stale.append(websocket)
        for websocket in stale:
            await self.disconnect(websocket)
        return event


hub = ChannelHub()


def create_realtime_router(
    *,
    channel_hub: ChannelHub = hub,
    allow_channel: ChannelAuthorizer | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/realtime", tags=["realtime"])

    def allowed(channel: str) -> bool:
        return bool(channel.strip()) and (
            allow_channel(channel) if allow_channel else True
        )

    @router.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        await websocket.accept()
        subscribed: set[str] = set()
        try:
            while True:
                message = await websocket.receive_json()
                action = str(message.get("action") or "").strip().lower()
                channel = str(message.get("channel") or "").strip()
                if action == "subscribe" and allowed(channel):
                    await channel_hub.subscribe(channel, websocket)
                    subscribed.add(channel)
                    await websocket.send_json(
                        {
                            "event_id": str(uuid4()),
                            "channel": channel,
                            "type": "subscription.confirmed",
                            "payload": {},
                            "created_at": utcnow_iso(),
                        }
                    )
                elif action == "unsubscribe" and channel in subscribed:
                    await channel_hub.unsubscribe(channel, websocket)
                    subscribed.discard(channel)
                else:
                    await websocket.send_json(
                        {
                            "event_id": str(uuid4()),
                            "channel": channel,
                            "type": "subscription.rejected",
                            "payload": {"reason": "invalid_subscription"},
                            "created_at": utcnow_iso(),
                        }
                    )
        except WebSocketDisconnect:
            await channel_hub.disconnect(websocket)

    return router
