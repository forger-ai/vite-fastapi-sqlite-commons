from __future__ import annotations

import asyncio
import json
import sys
from contextlib import contextmanager
from datetime import timedelta

import pytest
from sqlmodel import SQLModel

from testing.database import (
    install_app_database_alias,
    reload_module,
    temp_sqlite_database,
)


@contextmanager
def load_background_jobs(monkeypatch, tmp_path):
    with temp_sqlite_database(monkeypatch, tmp_path) as (database, _db_path):
        SQLModel.metadata.clear()
        sys.modules.pop("background_jobs", None)
        install_app_database_alias(database)
        background_jobs = reload_module("background_jobs")
        database.SQLModel.metadata.create_all(database.engine)
        try:
            yield background_jobs
        finally:
            SQLModel.metadata.clear()
            sys.modules.pop("background_jobs", None)


def test_enqueue_persists_jobs_with_ordering_and_idempotency(monkeypatch, tmp_path) -> None:
    with load_background_jobs(monkeypatch, tmp_path) as jobs:
        later = jobs.utcnow() + timedelta(minutes=5)
        first = jobs.enqueue_job(
            "demo.fast",
            payload={"name": "first"},
            queue="critical",
            priority=10,
            run_at=later,
            max_attempts=0,
            idempotency_key="same",
        )
        duplicate = jobs.enqueue_job(
            "demo.fast",
            payload={"name": "second"},
            idempotency_key="same",
        )
        second = jobs.enqueue_job("demo.slow", queue="critical", priority=1)

        assert duplicate.id == first.id
        assert first.max_attempts == 1
        assert json.loads(first.payload_json) == {"name": "first"}
        assert jobs.get_job(first.id).run_at.replace(tzinfo=jobs.UTC) == later
        assert [job.id for job in jobs.list_jobs(queue="critical")] == [second.id, first.id]
        assert jobs.list_jobs(status=jobs.BackgroundJobStatus.QUEUED, limit=1)[0].id == second.id


def test_registry_rejects_duplicate_and_bad_job_types(monkeypatch, tmp_path) -> None:
    with load_background_jobs(monkeypatch, tmp_path) as jobs:
        registry = jobs.JobRegistry()

        @registry.job("demo.ok")
        async def handler(_ctx):
            return None

        assert registry.has("demo.ok")
        assert registry.get("demo.ok") is handler
        with pytest.raises(ValueError, match="already registered"):
            registry.register("demo.ok", handler)
        with pytest.raises(ValueError, match="non-empty"):
            jobs.enqueue_job("bad type")
        with pytest.raises(TypeError, match="JSON object"):
            jobs.enqueue_job("demo.bad", payload=[])  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="too large"):
            jobs.enqueue_job("demo.large", payload={"data": "x" * 64_001})


def test_run_due_jobs_executes_registered_handlers_and_progress(monkeypatch, tmp_path) -> None:
    with load_background_jobs(monkeypatch, tmp_path) as jobs:
        registry = jobs.JobRegistry()

        @registry.job("demo.add")
        async def add(ctx, left: int, right: int):
            await ctx.set_progress(current=1, total=2, message="adding")
            await ctx.log("done")
            child = await ctx.enqueue("demo.child", payload={"parent": ctx.job_id})
            return {"value": left + right, "child_id": child.id}

        queued = jobs.enqueue_job("demo.add", payload={"left": 2, "right": 3})
        ran = asyncio.run(jobs.run_due_jobs_once(registry, limit=1))

        finished = jobs.get_job(queued.id)
        assert [job.id for job in ran] == [queued.id]
        assert finished.status == jobs.BackgroundJobStatus.SUCCEEDED
        assert json.loads(finished.result_json)["value"] == 5
        assert finished.progress_message == "done"
        assert finished.progress_current is None
        assert finished.progress_total is None
        assert jobs.list_jobs(status=jobs.BackgroundJobStatus.QUEUED)[0].job_type == "demo.child"


def test_run_due_jobs_skips_future_and_wrong_queue(monkeypatch, tmp_path) -> None:
    with load_background_jobs(monkeypatch, tmp_path) as jobs:
        registry = jobs.JobRegistry()
        calls: list[str] = []

        @registry.job("demo.now")
        def handler(_ctx):
            calls.append("called")

        jobs.enqueue_job("demo.now", run_at=jobs.utcnow() + timedelta(minutes=1))
        jobs.enqueue_job("demo.now", queue="other")

        assert asyncio.run(jobs.run_due_jobs_once(registry, queue="default")) == []
        assert calls == []


def test_unregistered_job_fails_without_reflection(monkeypatch, tmp_path) -> None:
    with load_background_jobs(monkeypatch, tmp_path) as jobs:
        queued = jobs.enqueue_job("demo.missing")
        ran = asyncio.run(jobs.run_due_jobs_once(jobs.JobRegistry()))

        assert ran[0].id == queued.id
        failed = jobs.get_job(queued.id)
        assert failed.status == jobs.BackgroundJobStatus.FAILED
        assert "Unregistered background job type" in failed.error_message


def test_retry_backoff_and_terminal_failure(monkeypatch, tmp_path) -> None:
    with load_background_jobs(monkeypatch, tmp_path) as jobs:
        registry = jobs.JobRegistry()

        @registry.job("demo.fail")
        def handler(_ctx):
            raise RuntimeError("boom")

        jobs.enqueue_job("demo.fail", max_attempts=2)
        first = asyncio.run(
            jobs.run_due_jobs_once(registry, retry_backoff_seconds=7)
        )[0]
        assert first.status == jobs.BackgroundJobStatus.QUEUED
        assert first.attempt_count == 1
        assert first.error_message == "RuntimeError: boom"
        assert first.run_at.replace(tzinfo=jobs.UTC) > jobs.utcnow()

        first.run_at = jobs.utcnow() - timedelta(seconds=1)
        with jobs.Session(jobs.engine) as session:
            session.add(first)
            session.commit()
        second = asyncio.run(jobs.run_due_jobs_once(registry))[0]
        assert second.status == jobs.BackgroundJobStatus.FAILED
        assert second.finished_at is not None


def test_cancel_prevents_queued_and_preserves_running_completion(monkeypatch, tmp_path) -> None:
    with load_background_jobs(monkeypatch, tmp_path) as jobs:
        registry = jobs.JobRegistry()

        @registry.job("demo.cancel")
        async def handler(ctx):
            assert await ctx.is_canceled()
            return {"ignored": True}

        queued = jobs.enqueue_job("demo.cancel")
        canceled = jobs.cancel_job(queued.id)
        assert canceled.status == jobs.BackgroundJobStatus.CANCELED
        assert asyncio.run(jobs.run_due_jobs_once(registry)) == []

        running = jobs.enqueue_job("demo.cancel")
        claimed = jobs._claim_due_jobs(queue="default", limit=1, lock_owner="test")
        assert claimed[0].id == running.id
        jobs.cancel_job(running.id)
        completed = asyncio.run(
            jobs._run_claimed_job(registry, running.id, retry_backoff_seconds=1)
        )
        assert completed.status == jobs.BackgroundJobStatus.CANCELED
        assert jobs.cancel_job("missing") is None
        assert jobs.cancel_job(completed.id).status == jobs.BackgroundJobStatus.CANCELED


def test_recover_stale_jobs(monkeypatch, tmp_path) -> None:
    with load_background_jobs(monkeypatch, tmp_path) as jobs:
        stale = jobs.BackgroundJob(
            job_type="demo.stale",
            status=jobs.BackgroundJobStatus.RUNNING,
            locked_at=jobs.utcnow() - timedelta(minutes=10),
            locked_by="old",
            heartbeat_at=jobs.utcnow() - timedelta(minutes=10),
        )
        fresh = jobs.BackgroundJob(
            job_type="demo.fresh",
            status=jobs.BackgroundJobStatus.RUNNING,
            locked_at=jobs.utcnow(),
            locked_by="new",
        )
        with jobs.Session(jobs.engine) as session:
            session.add(stale)
            session.add(fresh)
            session.commit()
            stale_id = stale.id
            fresh_id = fresh.id

        assert jobs.recover_stale_jobs(lock_ttl_seconds=60) == 1
        assert jobs.get_job(stale_id).status == jobs.BackgroundJobStatus.QUEUED
        assert jobs.get_job(fresh_id).status == jobs.BackgroundJobStatus.RUNNING


def test_runner_start_stop_processes_jobs(monkeypatch, tmp_path) -> None:
    with load_background_jobs(monkeypatch, tmp_path) as jobs:
        registry = jobs.JobRegistry()
        calls: list[str] = []

        @registry.job("demo.runner")
        def handler(_ctx):
            calls.append("ran")

        async def scenario() -> None:
            jobs.enqueue_job("demo.runner")
            runner = jobs.BackgroundJobRunner(
                registry,
                poll_interval_seconds=0.01,
                concurrency=3,
                lock_ttl_seconds=1,
                lock_owner="runner",
                retry_backoff_seconds=1,
            )
            assert not runner.running
            runner.start()
            runner.start()
            await asyncio.sleep(0.05)
            assert runner.running
            await runner.stop()
            assert not runner.running

        asyncio.run(scenario())
        assert calls == ["ran"]
        assert jobs.list_jobs(status=jobs.BackgroundJobStatus.SUCCEEDED)[0].locked_by is None


def test_defensive_branches_for_canceled_and_missing_jobs(monkeypatch, tmp_path) -> None:
    with load_background_jobs(monkeypatch, tmp_path) as jobs:
        canceled = jobs.enqueue_job("demo.canceled")
        jobs.cancel_job(canceled.id)
        asyncio.run(jobs.JobContext(canceled.id).set_progress(message="ignored"))
        assert jobs.get_job(canceled.id).progress_message is None
        assert jobs._succeed_job(canceled.id, {"ignored": True}).status == (
            jobs.BackgroundJobStatus.CANCELED
        )
        assert jobs._retry_or_fail_job(
            canceled.id,
            "ignored",
            retry_backoff_seconds=1,
        ).status == jobs.BackgroundJobStatus.CANCELED
        assert jobs._decode_json_dict(None) == {}
        with pytest.raises(ValueError, match="decode"):
            jobs._decode_json_dict("[]")
        with pytest.raises(RuntimeError, match="before execution"):
            asyncio.run(
                jobs._run_claimed_job(
                    jobs.JobRegistry(),
                    "missing",
                    retry_backoff_seconds=1,
                )
            )
        with pytest.raises(RuntimeError, match="before success"):
            jobs._succeed_job("missing", {})
        with pytest.raises(RuntimeError, match="before failure"):
            jobs._retry_or_fail_job("missing", "bad", retry_backoff_seconds=1)
        with pytest.raises(RuntimeError, match="before failure"):
            jobs._fail_job("missing", "bad")

        registry = jobs.JobRegistry()

        @registry.job("demo.vanish")
        def vanish(_ctx):
            return None

        queued = jobs.enqueue_job("demo.vanish")
        claimed = jobs._claim_due_jobs(queue="default", limit=1, lock_owner="test")
        assert claimed[0].id == queued.id

        original_get_job = jobs.get_job
        calls = iter([claimed[0], None])
        monkeypatch.setattr(jobs, "get_job", lambda _job_id: next(calls))
        monkeypatch.setattr(jobs.JobContext, "is_canceled", lambda _ctx: _true())
        with pytest.raises(RuntimeError, match="after cancellation"):
            asyncio.run(
                jobs._run_claimed_job(
                    registry,
                    queued.id,
                    retry_backoff_seconds=1,
                )
            )
        monkeypatch.setattr(jobs, "get_job", original_get_job)

        async def runner_without_start() -> None:
            runner = jobs.BackgroundJobRunner(
                registry,
                poll_interval_seconds=0.01,
                concurrency=1,
            )
            await runner.stop()
            task = asyncio.create_task(runner.run_until_stopped())
            await asyncio.sleep(0.02)
            await runner.stop()
            await task

        asyncio.run(runner_without_start())

        async def runner_timeout_branch() -> None:
            runner = jobs.BackgroundJobRunner(registry, poll_interval_seconds=0.01)

            async def fake_wait_for(_awaitable, *, timeout):
                _awaitable.close()
                assert timeout == 0.1
                runner._stop_event.set()
                raise TimeoutError

            monkeypatch.setattr(jobs.asyncio, "wait_for", fake_wait_for)
            await runner.run_until_stopped()

        asyncio.run(runner_timeout_branch())


async def _true() -> bool:
    return True
