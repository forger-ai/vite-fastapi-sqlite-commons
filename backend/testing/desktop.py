from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from desktop_events import DesktopEventConfig, event_signature


@dataclass(frozen=True)
class RecordedDesktopRequest:
    method: str
    path: str
    body: bytes
    headers: dict[str, str]


class FakeDesktopResponse:
    def __init__(self, payload: Any = None, *, raw: bytes | None = None) -> None:
        self._raw = raw if raw is not None else json.dumps(payload).encode("utf-8")

    def __enter__(self) -> FakeDesktopResponse:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def read(self) -> bytes:
        return self._raw


class FakeDesktopRuntime:
    def __init__(self) -> None:
        self.requests: list[RecordedDesktopRequest] = []
        self.responses: dict[tuple[str, str], FakeDesktopResponse] = {}

    def add_json(self, method: str, path: str, payload: Any) -> None:
        self.responses[(method.upper(), path)] = FakeDesktopResponse(payload)

    def add_empty(self, method: str, path: str) -> None:
        self.responses[(method.upper(), path)] = FakeDesktopResponse(raw=b"")

    def urlopen(self, request, timeout: int = 30) -> FakeDesktopResponse:
        del timeout
        parsed = urlparse(request.full_url)
        method = request.get_method().upper()
        path = parsed.path
        record = RecordedDesktopRequest(
            method=method,
            path=path,
            body=request.data or b"",
            headers={key.lower(): value for key, value in request.header_items()},
        )
        self.requests.append(record)
        return self.responses[(method, path)]


def assert_signed_desktop_request(
    record: RecordedDesktopRequest,
    *,
    app_id: str,
    secret: str,
) -> None:
    body_sha = hashlib.sha256(record.body).hexdigest()
    assert record.headers["x-forger-app-id"] == app_id
    assert record.headers["x-forger-body-sha256"] == body_sha
    timestamp = record.headers["x-forger-timestamp"]
    signature_payload = "\n".join(
        [record.method, record.path, timestamp, body_sha],
    ).encode("utf-8")
    expected = hmac.new(secret.encode("utf-8"), signature_payload, hashlib.sha256)
    assert record.headers["x-forger-signature"] == expected.hexdigest()


def signed_desktop_event(
    config: DesktopEventConfig,
    *,
    event_id: str = "evt_1",
    event_type: str = "agent.run.updated",
    thread_id: str = "thread_1",
    run_id: str = "run_1",
    payload: dict[str, Any] | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    event = {
        "app_id": config.app_id,
        "event_id": event_id,
        "type": event_type,
        "thread_id": thread_id,
        "run_id": run_id,
        "created_at": created_at or datetime.now(UTC).isoformat(),
        "payload": payload or {},
    }
    event["signature"] = event_signature(event, config.secret)
    return event

