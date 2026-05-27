"""Durable in-process background jobs for vite-fastapi-sqlite apps."""

from __future__ import annotations

import asyncio
import inspect
import json
import os
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import uuid4

from sqlmodel import Field, Session, SQLModel, select

from app.database import engine

JsonDict = dict[str, Any]
JobHandler = Callable[..., Awaitable[JsonDict | None] | JsonDict | None]
MAX_JSON_CHARS = 64_000


def utcnow() -> datetime:
    return datetime.now(UTC)


class BackgroundJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"


class BackgroundJob(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    job_type: str = Field(index=True)
    status: BackgroundJobStatus = Field(default=BackgroundJobStatus.QUEUED, index=True)
    queue: str = Field(default="default", index=True)
    priority: int = Field(default=0, index=True)
    run_at: datetime = Field(default_factory=utcnow, index=True)
    attempt_count: int = 0
    max_attempts: int = 3
    locked_at: datetime | None = Field(default=None, index=True)
    locked_by: str | None = Field(default=None, index=True)
    heartbeat_at: datetime | None = None
    idempotency_key: str | None = Field(default=None, index=True)
    payload_json: str = "{}"
    progress_current: int | None = None
    progress_total: int | None = None
    progress_message: str | None = None
    result_json: str | None = None
    error_message: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None


class JobRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, JobHandler] = {}

    def job(self, job_type: str) -> Callable[[JobHandler], JobHandler]:
        normalized = _normalize_job_type(job_type)

        def decorator(handler: JobHandler) -> JobHandler:
            self.register(normalized, handler)
            return handler

        return decorator

    def register(self, job_type: str, handler: JobHandler) -> None:
        normalized = _normalize_job_type(job_type)
        if normalized in self._handlers:
            raise ValueError(f"background job type already registered: {normalized}")
        self._handlers[normalized] = handler

    def get(self, job_type: str) -> JobHandler | None:
        return self._handlers.get(job_type)

    def has(self, job_type: str) -> bool:
        return job_type in self._handlers


class JobContext:
    def __init__(self, job_id: str) -> None:
        self.job_id = job_id

    async def is_canceled(self) -> bool:
        with Session(engine) as session:
            job = session.get(BackgroundJob, self.job_id)
            return job is None or job.status == BackgroundJobStatus.CANCELED

    async def set_progress(
        self,
        *,
        current: int | None = None,
        total: int | None = None,
        message: str | None = None,
    ) -> None:
        with Session(engine) as session:
            job = session.get(BackgroundJob, self.job_id)
            if not job or job.status == BackgroundJobStatus.CANCELED:
                return
            job.progress_current = current
            job.progress_total = total
            job.progress_message = message
            job.heartbeat_at = utcnow()
            job.updated_at = job.heartbeat_at
            session.add(job)
            session.commit()

    async def log(self, message: str) -> None:
        await self.set_progress(message=message)

    async def enqueue(
        self,
        job_type: str,
        *,
        payload: JsonDict | None = None,
        queue: str = "default",
        priority: int = 0,
        run_at: datetime | None = None,
        max_attempts: int = 3,
        idempotency_key: str | None = None,
    ) -> BackgroundJob:
        return enqueue_job(
            job_type,
            payload=payload,
            queue=queue,
            priority=priority,
            run_at=run_at,
            max_attempts=max_attempts,
            idempotency_key=idempotency_key,
        )


def enqueue_job(
    job_type: str,
    *,
    payload: JsonDict | None = None,
    queue: str = "default",
    priority: int = 0,
    run_at: datetime | None = None,
    max_attempts: int = 3,
    idempotency_key: str | None = None,
) -> BackgroundJob:
    payload_json = _encode_json_dict({} if payload is None else payload, field_name="payload")
    normalized = _normalize_job_type(job_type)
    with Session(engine) as session:
        if idempotency_key:
            existing = session.exec(
                select(BackgroundJob).where(
                    BackgroundJob.idempotency_key == idempotency_key,
                    BackgroundJob.job_type == normalized,
                )
            ).first()
            if existing:
                return existing
        job = BackgroundJob(
            job_type=normalized,
            queue=queue.strip() or "default",
            priority=priority,
            run_at=run_at or utcnow(),
            max_attempts=max(1, max_attempts),
            idempotency_key=idempotency_key,
            payload_json=payload_json,
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        return job


def get_job(job_id: str) -> BackgroundJob | None:
    with Session(engine) as session:
        return session.get(BackgroundJob, job_id)


def list_jobs(
    *,
    status: BackgroundJobStatus | None = None,
    queue: str | None = None,
    limit: int = 100,
) -> list[BackgroundJob]:
    statement = select(BackgroundJob)
    if status is not None:
        statement = statement.where(BackgroundJob.status == status)
    if queue is not None:
        statement = statement.where(BackgroundJob.queue == queue)
    statement = statement.order_by(BackgroundJob.created_at.desc()).limit(max(1, limit))
    with Session(engine) as session:
        return list(session.exec(statement).all())


def cancel_job(job_id: str) -> BackgroundJob | None:
    with Session(engine) as session:
        job = session.get(BackgroundJob, job_id)
        if not job:
            return None
        if job.status in {
            BackgroundJobStatus.SUCCEEDED,
            BackgroundJobStatus.FAILED,
            BackgroundJobStatus.CANCELED,
        }:
            return job
        job.status = BackgroundJobStatus.CANCELED
        job.finished_at = utcnow()
        job.locked_at = None
        job.locked_by = None
        job.updated_at = job.finished_at
        session.add(job)
        session.commit()
        session.refresh(job)
        return job


def recover_stale_jobs(*, lock_ttl_seconds: int = 300) -> int:
    stale_before = utcnow() - timedelta(seconds=max(1, lock_ttl_seconds))
    recovered = 0
    with Session(engine) as session:
        jobs = session.exec(
            select(BackgroundJob).where(
                BackgroundJob.status == BackgroundJobStatus.RUNNING,
                BackgroundJob.locked_at < stale_before,
            )
        ).all()
        for job in jobs:
            job.status = BackgroundJobStatus.QUEUED
            job.locked_at = None
            job.locked_by = None
            job.heartbeat_at = None
            job.progress_message = "Recovered after the previous runner stopped."
            job.updated_at = utcnow()
            session.add(job)
            recovered += 1
        session.commit()
    return recovered


async def run_due_jobs_once(
    registry: JobRegistry,
    *,
    queue: str = "default",
    limit: int = 1,
    lock_ttl_seconds: int = 300,
    lock_owner: str | None = None,
    retry_backoff_seconds: int = 30,
) -> list[BackgroundJob]:
    recover_stale_jobs(lock_ttl_seconds=lock_ttl_seconds)
    claimed = _claim_due_jobs(
        queue=queue,
        limit=limit,
        lock_owner=lock_owner or _default_lock_owner(),
    )
    if not claimed:
        return []
    return await asyncio.gather(
        *[
            _run_claimed_job(
                registry,
                job.id,
                retry_backoff_seconds=max(1, retry_backoff_seconds),
            )
            for job in claimed
        ]
    )


class BackgroundJobRunner:
    def __init__(
        self,
        registry: JobRegistry,
        *,
        queue: str = "default",
        poll_interval_seconds: float = 1.0,
        concurrency: int = 2,
        lock_ttl_seconds: int = 300,
        lock_owner: str | None = None,
        retry_backoff_seconds: int = 30,
    ) -> None:
        self.registry = registry
        self.queue = queue
        self.poll_interval_seconds = max(0.1, poll_interval_seconds)
        self.concurrency = max(1, concurrency)
        self.lock_ttl_seconds = max(1, lock_ttl_seconds)
        self.lock_owner = lock_owner or _default_lock_owner()
        self.retry_backoff_seconds = max(1, retry_backoff_seconds)
        self._stop_event: asyncio.Event | None = None
        self._task: asyncio.Task[None] | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        if self.running:
            return
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(self.run_until_stopped())

    async def stop(self) -> None:
        if self._stop_event:
            self._stop_event.set()
        if self._task:
            await self._task
            self._task = None
            self._stop_event = None

    async def run_until_stopped(self) -> None:
        if self._stop_event is None:
            self._stop_event = asyncio.Event()
        recover_stale_jobs(lock_ttl_seconds=self.lock_ttl_seconds)
        while not self._stop_event.is_set():
            await run_due_jobs_once(
                self.registry,
                queue=self.queue,
                limit=self.concurrency,
                lock_ttl_seconds=self.lock_ttl_seconds,
                lock_owner=self.lock_owner,
                retry_backoff_seconds=self.retry_backoff_seconds,
            )
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self.poll_interval_seconds,
                )
            except TimeoutError:
                pass


def _claim_due_jobs(*, queue: str, limit: int, lock_owner: str) -> list[BackgroundJob]:
    now = utcnow()
    with Session(engine) as session:
        jobs = session.exec(
            select(BackgroundJob)
            .where(
                BackgroundJob.status == BackgroundJobStatus.QUEUED,
                BackgroundJob.queue == queue,
                BackgroundJob.run_at <= now,
            )
            .order_by(BackgroundJob.priority.desc(), BackgroundJob.created_at)
            .limit(max(1, limit))
        ).all()
        claimed: list[BackgroundJob] = []
        for job in jobs:
            job.status = BackgroundJobStatus.RUNNING
            job.attempt_count += 1
            job.locked_at = now
            job.locked_by = lock_owner
            job.heartbeat_at = now
            job.error_message = None
            job.updated_at = now
            session.add(job)
            claimed.append(job)
        session.commit()
        for job in claimed:
            session.refresh(job)
        return claimed


async def _run_claimed_job(
    registry: JobRegistry,
    job_id: str,
    *,
    retry_backoff_seconds: int,
) -> BackgroundJob:
    job = get_job(job_id)
    if not job:
        raise RuntimeError(f"background job disappeared before execution: {job_id}")
    handler = registry.get(job.job_type)
    if not handler:
        return _fail_job(job_id, f"Unregistered background job type: {job.job_type}")
    payload = _decode_json_dict(job.payload_json)
    ctx = JobContext(job_id)
    if await ctx.is_canceled():
        canceled = get_job(job_id)
        if not canceled:
            raise RuntimeError(f"background job disappeared after cancellation: {job_id}")
        return canceled
    try:
        result = handler(ctx, **payload)
        if inspect.isawaitable(result):
            result = await result
    except Exception as exc:
        return _retry_or_fail_job(
            job_id,
            f"{type(exc).__name__}: {exc}",
            retry_backoff_seconds=retry_backoff_seconds,
        )
    return _succeed_job(job_id, result if isinstance(result, dict) else {})


def _succeed_job(job_id: str, result: JsonDict) -> BackgroundJob:
    result_json = _encode_json_dict(result, field_name="result")
    with Session(engine) as session:
        job = session.get(BackgroundJob, job_id)
        if not job:
            raise RuntimeError(f"background job disappeared before success: {job_id}")
        if job.status == BackgroundJobStatus.CANCELED:
            return job
        now = utcnow()
        job.status = BackgroundJobStatus.SUCCEEDED
        job.result_json = result_json
        job.locked_at = None
        job.locked_by = None
        job.heartbeat_at = now
        job.updated_at = now
        job.finished_at = now
        session.add(job)
        session.commit()
        session.refresh(job)
        return job


def _retry_or_fail_job(
    job_id: str,
    error_message: str,
    *,
    retry_backoff_seconds: int,
) -> BackgroundJob:
    with Session(engine) as session:
        job = session.get(BackgroundJob, job_id)
        if not job:
            raise RuntimeError(f"background job disappeared before failure: {job_id}")
        if job.status == BackgroundJobStatus.CANCELED:
            return job
        now = utcnow()
        job.error_message = error_message[:1_000]
        job.locked_at = None
        job.locked_by = None
        job.heartbeat_at = now
        job.updated_at = now
        if job.attempt_count < job.max_attempts:
            job.status = BackgroundJobStatus.QUEUED
            job.run_at = now + timedelta(
                seconds=min(3600, retry_backoff_seconds * 2 ** max(0, job.attempt_count - 1))
            )
            job.progress_message = "Retry scheduled after failure."
        else:
            job.status = BackgroundJobStatus.FAILED
            job.finished_at = now
        session.add(job)
        session.commit()
        session.refresh(job)
        return job


def _fail_job(job_id: str, error_message: str) -> BackgroundJob:
    with Session(engine) as session:
        job = session.get(BackgroundJob, job_id)
        if not job:
            raise RuntimeError(f"background job disappeared before failure: {job_id}")
        now = utcnow()
        job.status = BackgroundJobStatus.FAILED
        job.error_message = error_message[:1_000]
        job.locked_at = None
        job.locked_by = None
        job.heartbeat_at = now
        job.updated_at = now
        job.finished_at = now
        session.add(job)
        session.commit()
        session.refresh(job)
        return job


def _normalize_job_type(job_type: str) -> str:
    normalized = job_type.strip()
    if not normalized or " " in normalized:
        raise ValueError("background job type must be a non-empty string without spaces")
    return normalized


def _encode_json_dict(value: JsonDict, *, field_name: str) -> str:
    if not isinstance(value, dict):
        raise TypeError(f"background job {field_name} must be a JSON object")
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    if len(encoded) > MAX_JSON_CHARS:
        raise ValueError(f"background job {field_name} is too large")
    return encoded


def _decode_json_dict(value: str | None) -> JsonDict:
    decoded = json.loads(value or "{}")
    if not isinstance(decoded, dict):
        raise ValueError("background job payload must decode to a JSON object")
    return decoded


def _default_lock_owner() -> str:
    return f"{os.uname().nodename}:{os.getpid()}"
