from __future__ import annotations

import asyncio
from typing import Any, cast

from starlette.testclient import TestClient

from realtime import (
    ChannelHub,
    create_realtime_router,
    is_remote_tunnel_websocket,
    utcnow_iso,
)
from testing.apps import minimal_fastapi_app


def test_is_remote_tunnel_websocket_reads_forwarded_header() -> None:
    class Socket:
        def __init__(self, value: str | None) -> None:
            self.headers = {"x-forger-remote-tunnel": value} if value is not None else {}

    assert is_remote_tunnel_websocket(cast(Any, Socket("true"))) is True
    assert is_remote_tunnel_websocket(cast(Any, Socket(" TRUE "))) is True
    assert is_remote_tunnel_websocket(cast(Any, Socket("false"))) is False
    assert is_remote_tunnel_websocket(cast(Any, Socket(None))) is False


def test_channel_hub_publish_subscribe_unsubscribe_and_stale_cleanup() -> None:
    hub = ChannelHub()

    class Socket:
        def __init__(self, *, broken: bool = False) -> None:
            self.broken = broken
            self.events: list[dict[str, object]] = []

        async def send_json(self, event: dict[str, object]) -> None:
            if self.broken:
                raise RuntimeError("closed")
            self.events.append(event)

    live = Socket()
    stale = Socket(broken=True)

    async def scenario() -> None:
        await hub.unsubscribe("missing", live)
        await hub.subscribe("tasks", live)
        await hub.subscribe("tasks", stale)
        await hub.subscribe("multi", live)
        await hub.subscribe("multi", stale)
        await hub.unsubscribe("multi", live)
        event = await hub.publish("tasks", "task.updated", {"id": 1})
        await hub.publish("empty", "ignored")
        await hub.unsubscribe("tasks", live)
        await hub.subscribe("cleanup", live)
        await hub.disconnect(live)

        assert event["channel"] == "tasks"
        assert event["type"] == "task.updated"
        assert event["payload"] == {"id": 1}
        assert live.events == [event]

    asyncio.run(scenario())


def test_realtime_websocket_subscribe_publish_reject_and_disconnect() -> None:
    hub = ChannelHub()
    app = minimal_fastapi_app(
        realtime_router=create_realtime_router(
            channel_hub=hub,
            allow_channel=lambda channel: channel == "allowed",
        ),
    )
    client = TestClient(app)

    with client.websocket_connect("/api/realtime/ws") as websocket:
        websocket.send_json({"action": "subscribe", "channel": "allowed"})
        confirmation = websocket.receive_json()
        published = asyncio.run(hub.publish("allowed", "demo.event", {"ok": True}))
        event = websocket.receive_json()

        websocket.send_json({"action": "subscribe", "channel": "blocked"})
        rejected_channel = websocket.receive_json()
        websocket.send_json({"action": "subscribe", "channel": "   "})
        rejected_blank = websocket.receive_json()
        websocket.send_json({"action": "unsubscribe", "channel": "allowed"})
        websocket.send_json({"action": "unsubscribe", "channel": "missing"})
        rejected_missing = websocket.receive_json()
        websocket.send_json({"action": "unknown", "channel": "allowed"})
        rejected_action = websocket.receive_json()

    assert utcnow_iso().endswith("+00:00")
    assert confirmation["type"] == "subscription.confirmed"
    assert event == published
    assert rejected_channel["type"] == "subscription.rejected"
    assert rejected_blank["payload"] == {"reason": "invalid_subscription"}
    assert rejected_missing["channel"] == "missing"
    assert rejected_action["channel"] == "allowed"
