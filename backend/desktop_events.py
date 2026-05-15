from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote, urlparse, urlunparse

import websockets


JsonDict = dict[str, Any]
EventHandler = Callable[[JsonDict], Awaitable[None]]
SIGNATURE_WINDOW_SECONDS = 5 * 60


@dataclass(frozen=True)
class DesktopEventConfig:
    url: str
    app_id: str
    secret: str


class DesktopEventError(RuntimeError):
    pass


class DesktopEventClient:
    def __init__(
        self,
        *,
        config: DesktopEventConfig | None = None,
        max_seen_events: int = 2000,
    ) -> None:
        self.config = config or config_from_env()
        self.max_seen_events = max_seen_events
        self._seen: list[str] = []
        self._seen_set: set[str] = set()
        self._stopped = asyncio.Event()

    async def run(self, handler: EventHandler) -> None:
        delay = 0.5
        while not self._stopped.is_set():
            try:
                await self._listen(handler)
                delay = 0.5
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(delay)
                delay = min(delay * 2, 15)

    def stop(self) -> None:
        self._stopped.set()

    async def _listen(self, handler: EventHandler) -> None:
        async with websockets.connect(
            event_url(self.config),
            additional_headers=signed_headers(
                self.config,
                "GET",
                event_path(self.config.app_id),
                "",
            ),
            ping_interval=20,
            ping_timeout=20,
        ) as websocket:
            async for raw in websocket:
                event = json.loads(raw)
                if not isinstance(event, dict):
                    continue
                if not validate_event(event, self.config):
                    continue
                event_id = str(event.get("event_id") or "")
                if self._is_duplicate(event_id):
                    continue
                await handler(event)

    def _is_duplicate(self, event_id: str) -> bool:
        if not event_id:
            return True
        if event_id in self._seen_set:
            return True
        self._seen.append(event_id)
        self._seen_set.add(event_id)
        if len(self._seen) > self.max_seen_events:
            removed = self._seen.pop(0)
            self._seen_set.discard(removed)
        return False


def config_from_env() -> DesktopEventConfig:
    url = os.getenv("FORGER_DESKTOP_RUNTIME_URL", "").rstrip("/")
    app_id = os.getenv("FORGER_DESKTOP_RUNTIME_APP_ID", "")
    secret = os.getenv("FORGER_DESKTOP_RUNTIME_SECRET", "")
    if not url or not app_id or not secret:
        raise DesktopEventError("desktop runtime bridge is not configured")
    return DesktopEventConfig(url=url, app_id=app_id, secret=secret)


def event_path(app_id: str) -> str:
    return f"/v1/apps/{quote(app_id, safe='')}/agent-events"


def event_url(config: DesktopEventConfig) -> str:
    parsed = urlparse(config.url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return urlunparse((scheme, parsed.netloc, event_path(config.app_id), "", "", ""))


def signed_headers(
    config: DesktopEventConfig,
    method: str,
    path: str,
    body: str,
) -> dict[str, str]:
    body_sha = sha256(body)
    timestamp = datetime.now(UTC).isoformat()
    signature_payload = "\n".join([method.upper(), path, timestamp, body_sha]).encode(
        "utf-8"
    )
    secret = config.secret.encode("utf-8")
    return {
        "x-forger-app-id": config.app_id,
        "x-forger-timestamp": timestamp,
        "x-forger-body-sha256": body_sha,
        "x-forger-signature": hmac.new(
            secret,
            signature_payload,
            hashlib.sha256,
        ).hexdigest(),
    }


def validate_event(event: JsonDict, config: DesktopEventConfig) -> bool:
    if str(event.get("app_id") or "") != config.app_id:
        return False
    signature = str(event.get("signature") or "")
    if not signature:
        return False
    created_at = str(event.get("created_at") or "")
    try:
        created = datetime.fromisoformat(created_at)
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
    except ValueError:
        return False
    event_age = abs((datetime.now(UTC) - created.astimezone(UTC)).total_seconds())
    if event_age > SIGNATURE_WINDOW_SECONDS:
        return False
    expected = event_signature(event, config.secret)
    return hmac.compare_digest(signature, expected)


def event_signature(event: JsonDict, secret: str) -> str:
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    payload_sha = sha256(stable_json(payload))
    signature_payload = "\n".join(
        [
            str(event.get("app_id") or ""),
            str(event.get("event_id") or ""),
            str(event.get("type") or ""),
            str(event.get("thread_id") or ""),
            str(event.get("run_id") or ""),
            str(event.get("created_at") or ""),
            payload_sha,
        ]
    )
    return hmac.new(
        secret.encode("utf-8"),
        signature_payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def stable_json(value: Any) -> str:
    return json.dumps(sort_json(value), separators=(",", ":"), ensure_ascii=False)


def sort_json(value: Any) -> Any:
    if isinstance(value, list):
        return [sort_json(item) for item in value]
    if isinstance(value, dict):
        return {key: sort_json(value[key]) for key in sorted(value)}
    return value
