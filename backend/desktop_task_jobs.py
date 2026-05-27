"""Background job helpers for Forger Desktop prompt-template tasks."""

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
TaskCallback = Callable[[JobContext, JsonDict], Awaitable[None] | None]
DESKTOP_TASK_JOB_TYPE = "forger.desktop.task"
TERMINAL_TASK_STATUSES = {"completed", "failed", "canceled"}

_task_update_callbacks: list[TaskCallback] = []
_task_success_callbacks: list[TaskCallback] = []
_task_error_callbacks: list[TaskCallback] = []


class DesktopTaskJobError(RuntimeError):
    pass


def on_task_update(callback: TaskCallback) -> TaskCallback:
    _task_update_callbacks.append(callback)
    return callback


def on_task_success(callback: TaskCallback) -> TaskCallback:
    _task_success_callbacks.append(callback)
    return callback


def on_task_error(callback: TaskCallback) -> TaskCallback:
    _task_error_callbacks.append(callback)
    return callback


def register_desktop_task_jobs(registry: JobRegistry | None = None) -> JobRegistry:
    registry = registry or JobRegistry()
    if not registry.has(DESKTOP_TASK_JOB_TYPE):
        registry.register(DESKTOP_TASK_JOB_TYPE, run_desktop_task_job)
    return registry


def enqueue_desktop_task_job(
    *,
    template_id: str,
    locale: str | None = None,
    arguments: JsonDict | None = None,
    variables: JsonDict | None = None,
    attachments: list[JsonDict] | None = None,
    realtime_channel: str | None = None,
    poll_interval_seconds: float = 1.0,
    timeout_seconds: int = 600,
    queue: str = "default",
    priority: int = 0,
    max_attempts: int = 1,
    idempotency_key: str | None = None,
) -> BackgroundJob:
    clean_template_id = template_id.strip()
    if not clean_template_id:
        raise ValueError("desktop task template_id is required")
    return enqueue_job(
        DESKTOP_TASK_JOB_TYPE,
        payload={
            "template_id": clean_template_id,
            "locale": locale,
            "arguments": arguments or {},
            "variables": variables or {},
            "attachments": attachments or [],
            "realtime_channel": realtime_channel,
            "poll_interval_seconds": poll_interval_seconds,
            "timeout_seconds": timeout_seconds,
        },
        queue=queue,
        priority=priority,
        max_attempts=max_attempts,
        idempotency_key=idempotency_key,
    )


async def run_desktop_task_job(
    ctx: JobContext,
    *,
    template_id: str,
    locale: str | None = None,
    arguments: JsonDict | None = None,
    variables: JsonDict | None = None,
    attachments: list[JsonDict] | None = None,
    realtime_channel: str | None = None,
    poll_interval_seconds: float = 1.0,
    timeout_seconds: int = 600,
) -> JsonDict:
    task = forger_desktop.start_agent_task(
        template_id=template_id,
        locale=locale,
        arguments=arguments or None,
        variables=variables or None,
        attachments=attachments or None,
    )
    return await poll_desktop_task_job(
        ctx,
        task=task,
        realtime_channel=realtime_channel,
        poll_interval_seconds=poll_interval_seconds,
        timeout_seconds=timeout_seconds,
    )


async def poll_desktop_task_job(
    ctx: JobContext,
    *,
    task: JsonDict,
    realtime_channel: str | None = None,
    poll_interval_seconds: float = 1.0,
    timeout_seconds: int = 600,
) -> JsonDict:
    run_id = desktop_task_run_id(task)
    if not run_id:
        raise DesktopTaskJobError("desktop task did not return a run id")
    deadline = time.monotonic() + max(1, timeout_seconds)
    current = task
    while time.monotonic() <= deadline:
        if await ctx.is_canceled():
            forger_desktop.cancel_agent_task(run_id)
            return desktop_task_result({**current, "status": "canceled"}, run_id=run_id)
        await _record_update(ctx, current, run_id, realtime_channel)
        status = str(current.get("status") or "")
        if status == "completed":
            result = desktop_task_result(current, run_id=run_id)
            await _fire_callbacks(_task_success_callbacks, ctx, result)
            await _publish_realtime(realtime_channel, "desktop.task.succeeded", result)
            return result
        if status == "canceled":
            cancel_job(ctx.job_id)
            result = desktop_task_result(current, run_id=run_id)
            await _publish_realtime(realtime_channel, "desktop.task.canceled", result)
            return result
        if status == "failed":
            result = desktop_task_result(current, run_id=run_id)
            await _fire_callbacks(_task_error_callbacks, ctx, result)
            await _publish_realtime(realtime_channel, "desktop.task.failed", result)
            raise DesktopTaskJobError(str(result.get("error") or "desktop task failed"))
        await asyncio.sleep(max(0.2, poll_interval_seconds))
        next_task = forger_desktop.get_agent_task(run_id)
        if not next_task:
            raise DesktopTaskJobError(f"desktop task disappeared: {run_id}")
        current = next_task
    raise DesktopTaskJobError(f"desktop task timed out: {run_id}")


def desktop_task_run_id(task: JsonDict) -> str:
    return str(task.get("runId") or task.get("id") or task.get("run_id") or "").strip()


def desktop_task_messages(task: JsonDict) -> list[str]:
    messages: list[str] = []
    for key in ("message", "statusMessage", "progressMessage", "summary"):
        _append_text(messages, task.get(key))
    _append_sequence(messages, task.get("progressLog"))
    for key in ("messages", "events", "steps", "logs"):
        _append_sequence(messages, task.get(key))
    return _unique_tail(messages, limit=20)


def desktop_task_result(task: JsonDict, *, run_id: str | None = None) -> JsonDict:
    return {
        "desktop_run_id": run_id or desktop_task_run_id(task),
        "status": str(task.get("status") or "queued"),
        "messages": desktop_task_messages(task),
        "resultText": str(task.get("resultText") or ""),
        "error": str(task.get("error") or task.get("errorMessage") or ""),
        "task": _public_task_summary(task),
    }


async def _record_update(
    ctx: JobContext,
    task: JsonDict,
    run_id: str,
    realtime_channel: str | None,
) -> None:
    result = desktop_task_result(task, run_id=run_id)
    messages = result["messages"]
    message = (
        messages[-1]
        if isinstance(messages, list) and messages
        else str(task.get("status") or "")
    )
    await ctx.set_progress(message=message)
    _store_partial_result(ctx.job_id, result)
    await _fire_callbacks(_task_update_callbacks, ctx, result)
    await _publish_realtime(realtime_channel, "desktop.task.updated", result)


def _store_partial_result(job_id: str, result: JsonDict) -> None:
    with Session(engine) as session:
        job = session.get(BackgroundJob, job_id)
        if not job or job.status == BackgroundJobStatus.CANCELED:
            return
        job.result_json = json.dumps(result, sort_keys=True, separators=(",", ":"))
        session.add(job)
        session.commit()


async def _fire_callbacks(
    callbacks: list[TaskCallback],
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


def _public_task_summary(task: JsonDict) -> JsonDict:
    return {
        key: task[key]
        for key in (
            "runId",
            "appId",
            "templateId",
            "status",
            "createdAt",
            "updatedAt",
            "resultText",
            "error",
            "progressLog",
            "permissionRequest",
        )
        if key in task
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
