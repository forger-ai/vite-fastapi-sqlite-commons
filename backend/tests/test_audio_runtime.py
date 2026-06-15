from __future__ import annotations

import asyncio

import pytest

import audio_runtime
from starlette.websockets import WebSocketDisconnect


def test_live_transcription_websocket_url_adds_token() -> None:
    assert (
        audio_runtime.live_transcription_websocket_url(
            {"url": "ws://127.0.0.1:1234/v1/realtime/transcribe?mode=live", "token": "secret"}
        )
        == "ws://127.0.0.1:1234/v1/realtime/transcribe?mode=live&token=secret"
    )


def test_live_transcription_websocket_url_preserves_existing_token() -> None:
    assert (
        audio_runtime.live_transcription_websocket_url(
            {"url": "ws://127.0.0.1:1234/v1/realtime/transcribe?token=existing", "token": "new"}
        )
        == "ws://127.0.0.1:1234/v1/realtime/transcribe?token=existing"
    )


def test_live_transcription_websocket_url_allows_missing_token() -> None:
    assert (
        audio_runtime.live_transcription_websocket_url(
            {"url": "ws://127.0.0.1:1234/v1/realtime/transcribe"}
        )
        == "ws://127.0.0.1:1234/v1/realtime/transcribe"
    )


def test_live_transcription_websocket_url_requires_url() -> None:
    with pytest.raises(ValueError, match="live_transcription_url_missing"):
        audio_runtime.live_transcription_websocket_url({"token": "secret"})


def test_normalize_live_transcription_start_frame_uses_session_defaults_and_drops_model() -> None:
    assert audio_runtime.normalize_live_transcription_start_frame(
        '{"type":"start","model":"large-v3"}',
        {"task": "translate", "language": "es"},
    ) == '{"type":"start","task":"translate","language":"es"}'
    assert audio_runtime.normalize_live_transcription_start_frame(
        '{"type":"ping","model":"large-v3"}',
        {"task": "translate", "language": "es"},
    ) == '{"type":"ping","model":"large-v3"}'
    assert (
        audio_runtime.normalize_live_transcription_start_frame(
            "not-json",
            {"task": "translate", "language": "es"},
        )
        == "not-json"
    )


class FakeClientWebSocket:
    def __init__(self, messages: list[dict[str, object]]) -> None:
        self.messages = messages
        self.accepted = False
        self.sent_text: list[str] = []
        self.sent_bytes: list[bytes] = []
        self.close_code: int | None = None
        self.close_reason: str | None = None

    async def accept(self) -> None:
        self.accepted = True

    async def receive(self) -> dict[str, object]:
        if self.messages:
            return self.messages.pop(0)
        await asyncio.sleep(60)
        return {"type": "websocket.disconnect"}

    async def send_text(self, message: str) -> None:
        self.sent_text.append(message)

    async def send_bytes(self, message: bytes) -> None:
        self.sent_bytes.append(message)

    async def close(self, code: int = 1000, reason: str | None = None) -> None:
        self.close_code = code
        self.close_reason = reason


class DisconnectingClientWebSocket(FakeClientWebSocket):
    async def receive(self) -> dict[str, object]:
        raise WebSocketDisconnect


class FakeTargetWebSocket:
    def __init__(self) -> None:
        self.sent: list[str | bytes] = []
        self.closed = False
        self.outbound = iter(['{"type":"ready"}', b"pcm"])

    async def send(self, message: str | bytes) -> None:
        self.sent.append(message)

    async def close(self) -> None:
        self.closed = True

    def __aiter__(self) -> FakeTargetWebSocket:
        return self

    async def __anext__(self) -> str | bytes:
        try:
            return next(self.outbound)
        except StopIteration as error:
            raise StopAsyncIteration from error


class BlockingTargetWebSocket(FakeTargetWebSocket):
    def __init__(self) -> None:
        super().__init__()
        self.outbound = iter([])

    async def __anext__(self) -> str | bytes:
        await asyncio.sleep(60)
        raise StopAsyncIteration


class FakeConnect:
    def __init__(self, target: FakeTargetWebSocket) -> None:
        self.target = target

    async def __aenter__(self) -> FakeTargetWebSocket:
        return self.target

    async def __aexit__(self, *_exc: object) -> None:
        return None


def test_proxy_live_transcription_websocket_relays_both_directions(monkeypatch) -> None:
    target = FakeTargetWebSocket()
    called_urls: list[str] = []

    def fake_connect(url: str, **_kwargs: object) -> FakeConnect:
        called_urls.append(url)
        return FakeConnect(target)

    monkeypatch.setattr(audio_runtime.websockets, "connect", fake_connect)
    client = FakeClientWebSocket([
        {"text": '{"type":"start"}'},
        {"bytes": b"input-pcm"},
        {"type": "websocket.disconnect"},
    ])

    asyncio.run(
        audio_runtime.proxy_live_transcription_websocket(
            client,
            {"url": "ws://127.0.0.1/live", "token": "secret"},
        )
    )

    assert client.accepted is True
    assert called_urls == ["ws://127.0.0.1/live?token=secret"]
    assert target.sent == ['{"type":"start"}', b"input-pcm"]
    assert client.sent_text == ['{"type":"ready"}']
    assert client.sent_bytes == [b"pcm"]


def test_proxy_live_transcription_websocket_closes_target_on_client_disconnect(monkeypatch) -> None:
    target = BlockingTargetWebSocket()
    monkeypatch.setattr(
        audio_runtime.websockets,
        "connect",
        lambda *_args, **_kwargs: FakeConnect(target),
    )
    client = FakeClientWebSocket([{"type": "websocket.disconnect"}])

    asyncio.run(
        audio_runtime.proxy_live_transcription_websocket(
            client,
            {"url": "ws://127.0.0.1/live"},
        )
    )

    assert target.closed is True


def test_proxy_live_transcription_websocket_ignores_empty_client_messages(monkeypatch) -> None:
    target = BlockingTargetWebSocket()
    monkeypatch.setattr(
        audio_runtime.websockets,
        "connect",
        lambda *_args, **_kwargs: FakeConnect(target),
    )
    client = FakeClientWebSocket([{}, {"type": "websocket.disconnect"}])

    asyncio.run(
        audio_runtime.proxy_live_transcription_websocket(
            client,
            {"url": "ws://127.0.0.1/live"},
        )
    )

    assert target.sent == []
    assert target.closed is True


def test_proxy_live_transcription_websocket_handles_websocket_disconnect(monkeypatch) -> None:
    target = BlockingTargetWebSocket()
    monkeypatch.setattr(
        audio_runtime.websockets,
        "connect",
        lambda *_args, **_kwargs: FakeConnect(target),
    )
    client = DisconnectingClientWebSocket([])

    asyncio.run(
        audio_runtime.proxy_live_transcription_websocket(
            client,
            {"url": "ws://127.0.0.1/live"},
        )
    )

    assert target.closed is True


def test_proxy_live_transcription_websocket_closes_client_when_session_url_missing() -> None:
    client = FakeClientWebSocket([])

    asyncio.run(audio_runtime.proxy_live_transcription_websocket(client, {"token": "secret"}))

    assert client.accepted is True
    assert client.close_code == 1011
    assert client.close_reason == "live_transcription_url_missing"


def test_proxy_websocket_closes_client_when_target_unavailable(monkeypatch) -> None:
    def fake_connect(*_args: object, **_kwargs: object) -> FakeConnect:
        raise OSError("connection refused")

    monkeypatch.setattr(audio_runtime.websockets, "connect", fake_connect)
    client = FakeClientWebSocket([])

    asyncio.run(audio_runtime.proxy_live_transcription_websocket(client, {"url": "ws://127.0.0.1/live"}))

    assert client.accepted is True
    assert client.close_code == 1013
    assert client.close_reason == "live_transcription_target_unavailable"
