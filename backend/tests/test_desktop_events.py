from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest

import desktop_events
from desktop_events import DesktopEventClient, DesktopEventConfig
from testing.desktop import signed_desktop_event


def test_event_config_paths_urls_and_signed_headers(monkeypatch) -> None:
    monkeypatch.setenv("FORGER_DESKTOP_RUNTIME_URL", "https://desktop.test/")
    monkeypatch.setenv("FORGER_DESKTOP_RUNTIME_APP_ID", "app/id")
    monkeypatch.setenv("FORGER_DESKTOP_RUNTIME_SECRET", "secret")

    config = desktop_events.config_from_env()
    headers = desktop_events.signed_headers(
        config,
        "get",
        desktop_events.event_path(config.app_id),
        "",
    )

    assert config == DesktopEventConfig(
        url="https://desktop.test",
        app_id="app/id",
        secret="secret",
    )
    assert desktop_events.event_path(config.app_id) == "/v1/apps/app%2Fid/agent-events"
    assert desktop_events.event_url(config) == (
        "wss://desktop.test/v1/apps/app%2Fid/agent-events"
    )
    assert desktop_events.event_url(
        DesktopEventConfig("http://desktop.test", "app", "secret"),
    ) == "ws://desktop.test/v1/apps/app/agent-events"
    assert headers["x-forger-app-id"] == "app/id"
    assert headers["x-forger-body-sha256"] == desktop_events.sha256("")


def test_config_from_env_requires_all_values(monkeypatch) -> None:
    monkeypatch.delenv("FORGER_DESKTOP_RUNTIME_URL", raising=False)
    monkeypatch.setenv("FORGER_DESKTOP_RUNTIME_APP_ID", "app")
    monkeypatch.setenv("FORGER_DESKTOP_RUNTIME_SECRET", "secret")

    with pytest.raises(
        desktop_events.DesktopEventError,
        match="desktop runtime bridge is not configured",
    ):
        desktop_events.config_from_env()


def test_validate_event_rejects_invalid_envelopes_and_accepts_signed_event() -> None:
    config = DesktopEventConfig("http://desktop.test", "app", "secret")
    valid = signed_desktop_event(config, payload={"b": 2, "a": [3, 1]})

    wrong_app = {**valid, "app_id": "other"}
    missing_signature = {**valid, "signature": ""}
    invalid_date = {**valid, "created_at": "not-a-date"}
    old = signed_desktop_event(
        config,
        created_at=(datetime.now(UTC) - timedelta(minutes=10)).isoformat(),
    )
    tampered = {**valid, "payload": {"changed": True}}
    naive_time = signed_desktop_event(
        config,
        created_at=datetime.now(UTC).replace(tzinfo=None, microsecond=0).isoformat(),
    )

    assert desktop_events.validate_event(wrong_app, config) is False
    assert desktop_events.validate_event(missing_signature, config) is False
    assert desktop_events.validate_event(invalid_date, config) is False
    assert desktop_events.validate_event(old, config) is False
    assert desktop_events.validate_event(tampered, config) is False
    assert desktop_events.validate_event(valid, config) is True
    assert desktop_events.validate_event(naive_time, config) is True


def test_event_signature_handles_non_dict_payload_and_stable_json() -> None:
    config = DesktopEventConfig("http://desktop.test", "app", "secret")
    event = signed_desktop_event(config)
    event["payload"] = "not-a-dict"
    event["signature"] = desktop_events.event_signature(event, config.secret)

    assert desktop_events.validate_event(event, config) is True
    assert desktop_events.sort_json({"b": [2, {"d": 4, "c": 3}], "a": 1}) == {
        "a": 1,
        "b": [2, {"c": 3, "d": 4}],
    }
    assert desktop_events.stable_json({"b": 2, "a": 1}) == '{"a":1,"b":2}'


def test_client_duplicate_tracking_prunes_old_event_ids() -> None:
    client = DesktopEventClient(
        config=DesktopEventConfig("http://desktop.test", "app", "secret"),
        max_seen_events=1,
    )

    assert client._is_duplicate("") is True
    assert client._is_duplicate("evt_1") is False
    assert client._is_duplicate("evt_1") is True
    assert client._is_duplicate("evt_2") is False
    assert client._is_duplicate("evt_1") is False
    client.stop()
    assert client._stopped.is_set()


def test_client_listen_filters_invalid_and_duplicate_events(monkeypatch) -> None:
    config = DesktopEventConfig("http://desktop.test", "app", "secret")
    valid = signed_desktop_event(config, event_id="evt_1")
    invalid = {**valid, "app_id": "other"}
    messages = [
        json.dumps(["not", "a", "dict"]),
        json.dumps(invalid),
        json.dumps(valid),
        json.dumps(valid),
    ]
    captured: dict[str, object] = {}

    class FakeWebSocket:
        def __aiter__(self) -> FakeWebSocket:
            return self

        async def __anext__(self) -> str:
            if not messages:
                raise StopAsyncIteration
            return messages.pop(0)

    class FakeConnect:
        async def __aenter__(self) -> FakeWebSocket:
            return FakeWebSocket()

        async def __aexit__(self, *_exc: object) -> None:
            return None

    def fake_connect(url: str, **kwargs: object) -> FakeConnect:
        captured["url"] = url
        captured["headers"] = kwargs["additional_headers"]
        return FakeConnect()

    events: list[dict[str, object]] = []

    async def handler(event: dict[str, object]) -> None:
        events.append(event)

    monkeypatch.setattr(desktop_events.websockets, "connect", fake_connect)

    asyncio.run(DesktopEventClient(config=config)._listen(handler))

    assert captured["url"] == "ws://desktop.test/v1/apps/app/agent-events"
    assert events == [valid]


def test_client_run_retries_generic_errors_and_propagates_cancellation(
    monkeypatch,
) -> None:
    config = DesktopEventConfig("http://desktop.test", "app", "secret")
    client = DesktopEventClient(config=config)
    attempts = {"count": 0}

    async def handler(_event: dict[str, object]) -> None:
        return None

    async def flaky_listen(_handler) -> None:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("temporary")
        client.stop()

    async def fake_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(client, "_listen", flaky_listen)
    monkeypatch.setattr(desktop_events.asyncio, "sleep", fake_sleep)

    asyncio.run(client.run(handler))

    assert attempts["count"] == 2

    canceled_client = DesktopEventClient(config=config)

    async def canceled_listen(_handler) -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr(canceled_client, "_listen", canceled_listen)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(canceled_client.run(handler))
