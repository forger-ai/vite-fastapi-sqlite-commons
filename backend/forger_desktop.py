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
from urllib.parse import quote, urlsplit, urlunsplit
from urllib.request import Request, urlopen

TERMINAL_RUN_STATUSES = {"completed", "failed", "canceled"}
TERMINAL_TASK_STATUSES = {"completed", "failed", "canceled"}


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


def get_agent_task_status() -> dict[str, Any]:
    return _request("GET", "/agent-tasks/status", None)


def get_app_context() -> dict[str, Any]:
    return _request("GET", "/context", None)


def list_audio_devices() -> dict[str, Any]:
    return _request("GET", "/audio/devices", None)


def list_audio_input_devices() -> dict[str, Any]:
    return _request("GET", "/audio/input-devices", None)


def list_audio_output_devices() -> dict[str, Any]:
    return _request("GET", "/audio/output-devices", None)


def start_audio_transcription_session(
    *,
    device_id: str | None = None,
    task: str | None = None,
    language: str | None = None,
) -> dict[str, Any]:
    return _request(
        "POST",
        "/audio/transcriptions",
        {
            "deviceId": device_id or None,
            "task": task or None,
            "language": language or None,
        },
    )


def stop_audio_transcription_session(consumer_id: str) -> dict[str, Any] | None:
    return _request(
        "DELETE",
        f"/audio/transcriptions/{quote(consumer_id, safe='')}",
        None,
    )


def transcribe_audio_file(
    *,
    path: str,
    task: str | None = None,
    language: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    return _request(
        "POST",
        "/audio/file-transcriptions",
        {
            "path": path,
            "task": task or None,
            "language": language or None,
            "model": model or None,
        },
    )


def start_audio_file_transcription_job(
    *,
    path: str,
    task: str | None = None,
    language: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    return _request(
        "POST",
        "/audio/file-transcription-jobs",
        {
            "path": path,
            "task": task or None,
            "language": language or None,
            "model": model or None,
        },
    )


def get_audio_file_transcription_job(job_id: str) -> dict[str, Any]:
    return _request("GET", f"/audio/file-transcription-jobs/{quote(job_id, safe='')}", None)


def cancel_audio_file_transcription_job(job_id: str) -> dict[str, Any]:
    return _request("POST", f"/audio/file-transcription-jobs/{quote(job_id, safe='')}/cancel", {})


def synthesize_speech(
    *,
    text: str,
    model: str,
    voice: str,
    speed: float | None = None,
    format: str | None = None,
) -> dict[str, Any]:
    return _request(
        "POST",
        "/audio/synthesis",
        {
            "text": text,
            "model": model,
            "voice": voice,
            "speed": speed,
            "format": format or None,
        },
    )


def say_text(
    *,
    text: str,
    model: str,
    voice: str,
    output_device_id: str | None = None,
    speed: float | None = None,
) -> dict[str, Any]:
    return _request(
        "POST",
        "/audio/say",
        {
            "text": text,
            "model": model,
            "voice": voice,
            "outputDeviceId": output_device_id or None,
            "speed": speed,
        },
    )


def get_audio_playback(playback_id: str) -> dict[str, Any]:
    return _request("GET", f"/audio/playbacks/{playback_id}", None)


def cancel_audio_playback(playback_id: str) -> dict[str, Any]:
    return _request("POST", f"/audio/playbacks/{playback_id}/cancel", {})


def start_agent_task(
    *,
    template_id: str,
    locale: str | None = None,
    arguments: dict[str, Any] | None = None,
    variables: dict[str, Any] | None = None,
    attachments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return _request(
        "POST",
        "/agent-tasks",
        {
            "templateId": template_id,
            "locale": locale or None,
            "arguments": arguments or None,
            "variables": variables or None,
            "attachments": attachments or None,
        },
    )


def get_agent_task(run_id: str) -> dict[str, Any] | None:
    return _request("GET", f"/agent-tasks/{run_id}", None)


def cancel_agent_task(run_id: str) -> dict[str, Any]:
    return _request("POST", f"/agent-tasks/{run_id}/cancel", {})


def wait_for_task(
    *,
    run_id: str,
    timeout_seconds: int = 600,
    poll_interval_seconds: float = 1.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + max(1, timeout_seconds)
    last: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        task = get_agent_task(run_id)
        if task:
            last = task
            if str(task.get("status") or "") in TERMINAL_TASK_STATUSES:
                return task
        time.sleep(max(0.2, poll_interval_seconds))
    raise ForgerDesktopRuntimeError(f"agent task timed out: {last or run_id}")


def start_manifest_agent_thread(
    *,
    agent_id: str,
    title: str | None = None,
    variables: dict[str, Any] | None = None,
    runtime: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    workspace_path: str | None = None,
) -> dict[str, Any]:
    return _request(
        "POST",
        f"/agents/{agent_id}/start",
        {
            "title": title or None,
            "variables": variables or None,
            "runtime": runtime or None,
            "metadata": metadata or None,
            "workspacePath": workspace_path or None,
        },
    )


def resume_manifest_agent_thread(
    *,
    desktop_thread_id: str,
    variables: dict[str, Any] | None = None,
    runtime: dict[str, Any] | None = None,
    workspace_path: str | None = None,
) -> dict[str, Any]:
    return _request(
        "POST",
        f"/agent-threads/{desktop_thread_id}/resume",
        {
            "variables": variables or None,
            "runtime": runtime or None,
            "workspacePath": workspace_path or None,
        },
    )


def steer_manifest_agent_run(
    *,
    desktop_thread_id: str,
    desktop_run_id: str,
    variables: dict[str, Any] | None = None,
    runtime: dict[str, Any] | None = None,
    workspace_path: str | None = None,
) -> dict[str, Any]:
    return _request(
        "POST",
        f"/agent-threads/{desktop_thread_id}/runs/{desktop_run_id}/steer",
        {
            "variables": variables or None,
            "runtime": runtime or None,
            "workspacePath": workspace_path or None,
        },
    )


def create_agent_thread(
    *,
    title: str,
    manifest_agent_id: str,
    initial_prompt: str,
    runtime: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    workspace_path: str | None = None,
) -> dict[str, Any]:
    thread = start_manifest_agent_thread(
        agent_id=manifest_agent_id,
        title=title,
        variables={"message": initial_prompt},
        runtime=runtime,
        metadata=metadata,
        workspace_path=workspace_path,
    )
    return _with_legacy_thread_aliases(thread)


def start_agent_run(
    *,
    desktop_thread_id: str,
    message: str,
    context: str | None = None,
    runtime: dict[str, Any] | None = None,
    workspace_path: str | None = None,
) -> dict[str, Any]:
    run = resume_manifest_agent_thread(
        desktop_thread_id=desktop_thread_id,
        variables={
            "message": message,
            "context": context or "",
            "session_state": context or "",
        },
        runtime=runtime,
        workspace_path=workspace_path,
    )
    return _with_legacy_run_aliases(run)


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
    url = normalize_runtime_url(os.getenv("FORGER_DESKTOP_RUNTIME_URL", ""))
    app_id = os.getenv("FORGER_DESKTOP_RUNTIME_APP_ID", "")
    secret = os.getenv("FORGER_DESKTOP_RUNTIME_SECRET", "")
    if not url or not app_id or not secret:
        return None
    return ForgerDesktopRuntimeConfig(url=url, app_id=app_id, secret=secret)


def normalize_runtime_url(raw_url: str) -> str:
    url = raw_url.strip().rstrip("/")
    if not url:
        return ""
    parsed = urlsplit(url)
    legacy_path = parsed.path.lower()
    if "forgerapp" in legacy_path or "bridge" in legacy_path:
        return urlunsplit((parsed.scheme, parsed.netloc, "", "", "")).rstrip("/")
    return url


def _strip_none(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if item is not None}


def _with_legacy_thread_aliases(thread: dict[str, Any]) -> dict[str, Any]:
    desktop_thread_id = str(thread.get("desktop_thread_id") or "")
    if desktop_thread_id and not thread.get("threadId"):
        thread = {
            **thread,
            "threadId": desktop_thread_id,
            "id": thread.get("id") or desktop_thread_id,
        }
    return thread


def _with_legacy_run_aliases(run: dict[str, Any]) -> dict[str, Any]:
    desktop_run_id = str(run.get("desktop_run_id") or "")
    if desktop_run_id and not run.get("runId"):
        run = {
            **run,
            "runId": desktop_run_id,
            "id": run.get("id") or desktop_run_id,
        }
    return run
