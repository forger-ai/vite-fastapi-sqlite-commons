from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


TERMINAL_RUN_STATUSES = {"completed", "failed", "canceled"}


class ForgerDesktopRuntimeError(RuntimeError):
    pass


class ForgerDesktopRuntimeUnavailable(ForgerDesktopRuntimeError):
    pass


@dataclass(frozen=True)
class ForgerDesktopRuntimeConfig:
    url: str
    app_id: str
    secret: str


def is_desktop_runtime_available() -> bool:
    return bool(_config_or_none())


def create_agent_thread(
    *,
    title: str,
    manifest_agent_id: str,
    initial_prompt: str,
    runtime: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    workspace_path: str | None = None,
) -> dict[str, Any]:
    return _request(
        "POST",
        "/agent-threads",
        {
            "title": title,
            "manifestAgentId": manifest_agent_id,
            "initialPrompt": initial_prompt,
            "runtime": runtime or None,
            "metadata": metadata or None,
            "workspacePath": workspace_path or None,
        },
    )


def start_agent_run(
    *,
    desktop_thread_id: str,
    message: str,
    context: str | None = None,
    runtime: dict[str, Any] | None = None,
    workspace_path: str | None = None,
) -> dict[str, Any]:
    return _request(
        "POST",
        f"/agent-threads/{desktop_thread_id}/runs",
        {
            "desktopThreadId": desktop_thread_id,
            "message": message,
            "context": context,
            "runtime": runtime or None,
            "workspacePath": workspace_path or None,
        },
    )


def get_agent_thread(desktop_thread_id: str) -> dict[str, Any] | None:
    return _request("GET", f"/agent-threads/{desktop_thread_id}", None)


def get_agent_run(desktop_thread_id: str, desktop_run_id: str) -> dict[str, Any] | None:
    return _request(
        "GET",
        f"/agent-threads/{desktop_thread_id}/runs/{desktop_run_id}",
        None,
    )


def cancel_agent_run(desktop_thread_id: str, desktop_run_id: str) -> dict[str, Any]:
    return _request(
        "POST",
        f"/agent-threads/{desktop_thread_id}/runs/{desktop_run_id}/cancel",
        {},
    )


def wait_for_run(
    *,
    desktop_thread_id: str,
    desktop_run_id: str,
    timeout_seconds: int = 600,
    poll_interval_seconds: float = 1.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + max(1, timeout_seconds)
    last: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        run = get_agent_run(desktop_thread_id, desktop_run_id)
        if run:
            last = run
            if str(run.get("status") or "") in TERMINAL_RUN_STATUSES:
                return run
        time.sleep(max(0.2, poll_interval_seconds))
    raise ForgerDesktopRuntimeError(f"agent run timed out: {last or desktop_run_id}")


def _request(method: str, app_path: str, body: dict[str, Any] | None) -> Any:
    config = _config()
    path = f"/v1/apps/{config.app_id}{app_path}"
    body_bytes = (
        b""
        if body is None
        else json.dumps(_strip_none(body), separators=(",", ":")).encode("utf-8")
    )
    body_sha = hashlib.sha256(body_bytes).hexdigest()
    timestamp = datetime.now(UTC).isoformat()
    signature_payload = "\n".join(
        [method.upper(), path, timestamp, body_sha],
    ).encode("utf-8")
    signature = hmac.new(
        config.secret.encode("utf-8"),
        signature_payload,
        hashlib.sha256,
    ).hexdigest()
    request = Request(
        f"{config.url}{path}",
        data=None if method.upper() == "GET" else body_bytes,
        method=method.upper(),
        headers={
            "content-type": "application/json",
            "x-forger-app-id": config.app_id,
            "x-forger-timestamp": timestamp,
            "x-forger-body-sha256": body_sha,
            "x-forger-signature": signature,
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else None
    except HTTPError as error:
        raw = error.read().decode("utf-8", errors="replace")
        raise ForgerDesktopRuntimeError(
            f"desktop runtime returned {error.code}: {raw}",
        ) from error
    except URLError as error:
        raise ForgerDesktopRuntimeError(
            f"desktop runtime unavailable: {error.reason}",
        ) from error


def _config() -> ForgerDesktopRuntimeConfig:
    config = _config_or_none()
    if not config:
        raise ForgerDesktopRuntimeUnavailable(
            "Forger Desktop runtime bridge is not available",
        )
    return config


def _config_or_none() -> ForgerDesktopRuntimeConfig | None:
    url = os.getenv("FORGER_DESKTOP_RUNTIME_URL", "").rstrip("/")
    app_id = os.getenv("FORGER_DESKTOP_RUNTIME_APP_ID", "")
    secret = os.getenv("FORGER_DESKTOP_RUNTIME_SECRET", "")
    if not url or not app_id or not secret:
        return None
    return ForgerDesktopRuntimeConfig(url=url, app_id=app_id, secret=secret)


def _strip_none(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if item is not None}
