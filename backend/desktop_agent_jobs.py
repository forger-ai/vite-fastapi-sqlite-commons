"""Background job helpers for Forger Desktop manifest agent runs."""

from __future__ import annotations

import asyncio
import inspect
import json
import time
from collections.abc import Awaitable, Callable
from typing import Any

from sqlmodel import Session

from app import forger_desktop
from app.background_jobs import (
    BackgroundJob,
    BackgroundJobStatus,
    JobContext,
    JobRegistry,
    cancel_job,
    engine,
    enqueue_job,
)

JsonDict = dict[str, Any]
AgentCallback = Callable[[JobContext, JsonDict], Awaitable[None] | None]
DESKTOP_AGENT_START_JOB_TYPE = "forger.desktop.agent.start"
DESKTOP_AGENT_RESUME_JOB_TYPE = "forger.desktop.agent.resume"

_agent_update_callbacks: list[AgentCallback] = []
_agent_success_callbacks: list[AgentCallback] = []
_agent_error_callbacks: list[AgentCallback] = []


class DesktopAgentJobError(RuntimeError):
    pass


def on_agent_update(callback: AgentCallback) -> AgentCallback:
    _agent_update_callbacks.append(callback)
    return callback


def on_agent_success(callback: AgentCallback) -> AgentCallback:
    _agent_success_callbacks.append(callback)
    return callback


def on_agent_error(callback: AgentCallback) -> AgentCallback:
    _agent_error_callbacks.append(callback)
    return callback


def register_desktop_agent_jobs(registry: JobRegistry | None = None) -> JobRegistry:
    registry = registry or JobRegistry()
    if not registry.has(DESKTOP_AGENT_START_JOB_TYPE):
        registry.register(DESKTOP_AGENT_START_JOB_TYPE, run_desktop_agent_start_job)
    if not registry.has(DESKTOP_AGENT_RESUME_JOB_TYPE):
        registry.register(DESKTOP_AGENT_RESUME_JOB_TYPE, run_desktop_agent_resume_job)
    return registry


def enqueue_desktop_agent_start_job(
    *,
    agent_id: str,
    title: str | None = None,
    variables: JsonDict | None = None,
    runtime: JsonDict | None = None,
    metadata: JsonDict | None = None,
    workspace_path: str | None = None,
    realtime_channel: str | None = None,
    poll_interval_seconds: float = 1.0,
    timeout_seconds: int = 600,
    queue: str = "default",
    priority: int = 0,
    max_attempts: int = 1,
    idempotency_key: str | None = None,
) -> BackgroundJob:
    clean_agent_id = agent_id.strip()
    if not clean_agent_id:
        raise ValueError("desktop agent_id is required")
    return enqueue_job(
        DESKTOP_AGENT_START_JOB_TYPE,
        payload={
            "agent_id": clean_agent_id,
            "title": title,
            "variables": variables or {},
            "runtime": runtime or {},
            "metadata": metadata or {},
            "workspace_path": workspace_path,
            "realtime_channel": realtime_channel,
            "poll_interval_seconds": poll_interval_seconds,
            "timeout_seconds": timeout_seconds,
        },
        queue=queue,
        priority=priority,
        max_attempts=max_attempts,
        idempotency_key=idempotency_key,
    )


def enqueue_desktop_agent_resume_job(
    *,
    desktop_thread_id: str,
    variables: JsonDict | None = None,
    runtime: JsonDict | None = None,
    workspace_path: str | None = None,
    realtime_channel: str | None = None,
    poll_interval_seconds: float = 1.0,
    timeout_seconds: int = 600,
    queue: str = "default",
    priority: int = 0,
    max_attempts: int = 1,
    idempotency_key: str | None = None,
) -> BackgroundJob:
    clean_thread_id = desktop_thread_id.strip()
    if not clean_thread_id:
        raise ValueError("desktop_thread_id is required")
    return enqueue_job(
        DESKTOP_AGENT_RESUME_JOB_TYPE,
        payload={
            "desktop_thread_id": clean_thread_id,
            "variables": variables or {},
            "runtime": runtime or {},
            "workspace_path": workspace_path,
            "realtime_channel": realtime_channel,
            "poll_interval_seconds": poll_interval_seconds,
            "timeout_seconds": timeout_seconds,
        },
        queue=queue,
        priority=priority,
        max_attempts=max_attempts,
        idempotency_key=idempotency_key,
    )


async def run_desktop_agent_start_job(
    ctx: JobContext,
    *,
    agent_id: str,
    title: str | None = None,
    variables: JsonDict | None = None,
    runtime: JsonDict | None = None,
    metadata: JsonDict | None = None,
    workspace_path: str | None = None,
    realtime_channel: str | None = None,
    poll_interval_seconds: float = 1.0,
    timeout_seconds: int = 600,
) -> JsonDict:
    thread = forger_desktop.start_manifest_agent_thread(
        agent_id=agent_id,
        title=title,
        variables=variables or None,
        runtime=runtime or None,
        metadata=metadata or None,
        workspace_path=workspace_path,
    )
    return await _poll_started_or_resumed_agent_job(
        ctx,
        thread_or_run=thread,
        fallback_thread_id=desktop_thread_id(thread),
        realtime_channel=realtime_channel,
        poll_interval_seconds=poll_interval_seconds,
        timeout_seconds=timeout_seconds,
    )


async def run_desktop_agent_resume_job(
    ctx: JobContext,
    *,
    desktop_thread_id: str,
    variables: JsonDict | None = None,
    runtime: JsonDict | None = None,
    workspace_path: str | None = None,
    realtime_channel: str | None = None,
    poll_interval_seconds: float = 1.0,
    timeout_seconds: int = 600,
) -> JsonDict:
    run = forger_desktop.resume_manifest_agent_thread(
        desktop_thread_id=desktop_thread_id,
        variables=variables or None,
        runtime=runtime or None,
        workspace_path=workspace_path,
    )
    return await _poll_started_or_resumed_agent_job(
        ctx,
        thread_or_run=run,
        fallback_thread_id=desktop_thread_id,
        realtime_channel=realtime_channel,
        poll_interval_seconds=poll_interval_seconds,
        timeout_seconds=timeout_seconds,
    )


async def poll_desktop_agent_job(
    ctx: JobContext,
    *,
    desktop_thread_id: str,
    desktop_run_id: str,
    run: JsonDict | None = None,
    realtime_channel: str | None = None,
    poll_interval_seconds: float = 1.0,
    timeout_seconds: int = 600,
) -> JsonDict:
    if not desktop_thread_id or not desktop_run_id:
        raise DesktopAgentJobError("desktop agent thread and run ids are required")
    deadline = time.monotonic() + max(1, timeout_seconds)
    current = run or forger_desktop.get_agent_run(desktop_thread_id, desktop_run_id)
    while time.monotonic() <= deadline:
        if not current:
            raise DesktopAgentJobError(f"desktop agent run disappeared: {desktop_run_id}")
        if await ctx.is_canceled():
            forger_desktop.cancel_agent_run(desktop_thread_id, desktop_run_id)
            return desktop_agent_result(
                {**current, "status": "canceled"},
                desktop_thread_id=desktop_thread_id,
                desktop_run_id=desktop_run_id,
            )
        await _record_update(ctx, current, desktop_thread_id, desktop_run_id, realtime_channel)
        status = str(current.get("status") or "")
        if status == "completed":
            result = desktop_agent_result(
                current,
                desktop_thread_id=desktop_thread_id,
                desktop_run_id=desktop_run_id,
            )
            await _fire_callbacks(_agent_success_callbacks, ctx, result)
            await _publish_realtime(realtime_channel, "desktop.agent.succeeded", result)
            return result
        if status == "canceled":
            cancel_job(ctx.job_id)
            result = desktop_agent_result(
                current,
                desktop_thread_id=desktop_thread_id,
                desktop_run_id=desktop_run_id,
            )
            await _publish_realtime(realtime_channel, "desktop.agent.canceled", result)
            return result
        if status == "failed":
            result = desktop_agent_result(
                current,
                desktop_thread_id=desktop_thread_id,
                desktop_run_id=desktop_run_id,
            )
            await _fire_callbacks(_agent_error_callbacks, ctx, result)
            await _publish_realtime(realtime_channel, "desktop.agent.failed", result)
            raise DesktopAgentJobError(str(result.get("error") or "desktop agent run failed"))
        await asyncio.sleep(max(0.2, poll_interval_seconds))
        current = forger_desktop.get_agent_run(desktop_thread_id, desktop_run_id)
    raise DesktopAgentJobError(f"desktop agent run timed out: {desktop_run_id}")


def desktop_thread_id(thread_or_run: JsonDict) -> str:
    return str(
        thread_or_run.get("desktop_thread_id")
        or thread_or_run.get("threadId")
        or thread_or_run.get("id")
        or ""
    ).strip()


def desktop_run_id(thread_or_run: JsonDict) -> str:
    active_run = thread_or_run.get("active_run")
    if isinstance(active_run, dict):
        active = desktop_run_id(active_run)
        if active:
            return active
    return str(
        thread_or_run.get("desktop_run_id")
        or thread_or_run.get("runId")
        or thread_or_run.get("id")
        or ""
    ).strip()


def desktop_agent_messages(run: JsonDict) -> list[str]:
    messages: list[str] = []
    for key in ("message", "statusMessage", "progressMessage", "summary"):
        _append_text(messages, run.get(key))
    _append_sequence(messages, run.get("progressLog"))
    for key in ("messages", "events", "steps", "logs"):
        _append_sequence(messages, run.get(key))
    return _unique_tail(messages, limit=20)


def desktop_agent_result(
    run: JsonDict,
    *,
    desktop_thread_id: str,
    desktop_run_id: str,
) -> JsonDict:
    return {
        "desktop_thread_id": desktop_thread_id,
        "desktop_run_id": desktop_run_id,
        "status": str(run.get("status") or "queued"),
        "messages": desktop_agent_messages(run),
        "resultText": str(run.get("resultText") or ""),
        "error": str(run.get("error") or run.get("errorMessage") or ""),
        "run": _public_run_summary(run),
    }


async def _poll_started_or_resumed_agent_job(
    ctx: JobContext,
    *,
    thread_or_run: JsonDict,
    fallback_thread_id: str,
    realtime_channel: str | None,
    poll_interval_seconds: float,
    timeout_seconds: int,
) -> JsonDict:
    thread_id = desktop_thread_id(thread_or_run) or fallback_thread_id
    run_id = desktop_run_id(thread_or_run)
    if not thread_id or not run_id:
        raise DesktopAgentJobError("desktop agent did not return thread and run ids")
    return await poll_desktop_agent_job(
        ctx,
        desktop_thread_id=thread_id,
        desktop_run_id=run_id,
        run=thread_or_run,
        realtime_channel=realtime_channel,
        poll_interval_seconds=poll_interval_seconds,
        timeout_seconds=timeout_seconds,
    )


async def _record_update(
    ctx: JobContext,
    run: JsonDict,
    thread_id: str,
    run_id: str,
    realtime_channel: str | None,
) -> None:
    result = desktop_agent_result(run, desktop_thread_id=thread_id, desktop_run_id=run_id)
    messages = result["messages"]
    message = (
        messages[-1]
        if isinstance(messages, list) and messages
        else str(run.get("status") or "")
    )
    await ctx.set_progress(message=message)
    _store_partial_result(ctx.job_id, result)
    await _fire_callbacks(_agent_update_callbacks, ctx, result)
    await _publish_realtime(realtime_channel, "desktop.agent.updated", result)


def _store_partial_result(job_id: str, result: JsonDict) -> None:
    with Session(engine) as session:
        job = session.get(BackgroundJob, job_id)
        if not job or job.status == BackgroundJobStatus.CANCELED:
            return
        job.result_json = json.dumps(result, sort_keys=True, separators=(",", ":"))
        session.add(job)
        session.commit()


async def _fire_callbacks(
    callbacks: list[AgentCallback],
    ctx: JobContext,
    payload: JsonDict,
) -> None:
    for callback in list(callbacks):
        result = callback(ctx, payload)
        if inspect.isawaitable(result):
            await result


async def _publish_realtime(
    realtime_channel: str | None,
    event_type: str,
    payload: JsonDict,
) -> None:
    if not realtime_channel:
        return
    from app.realtime import hub

    await hub.publish(realtime_channel, event_type, payload)


def _public_run_summary(run: JsonDict) -> JsonDict:
    return {
        key: run[key]
        for key in (
            "desktop_thread_id",
            "desktop_run_id",
            "status",
            "createdAt",
            "updatedAt",
            "resultText",
            "error",
            "progressLog",
            "permissionRequest",
        )
        if key in run
    }


def _append_sequence(messages: list[str], value: Any) -> None:
    if not isinstance(value, list):
        return
    for item in value:
        if isinstance(item, dict):
            _append_text(messages, item.get("message") or item.get("text") or item.get("title"))
        else:
            _append_text(messages, item)


def _append_text(messages: list[str], value: Any) -> None:
    if isinstance(value, str) and value.strip():
        messages.append(value.strip())


def _unique_tail(messages: list[str], *, limit: int) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for message in messages:
        if message in seen:
            continue
        seen.add(message)
        unique.append(message)
    return unique[-limit:]
