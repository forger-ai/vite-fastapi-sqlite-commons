from __future__ import annotations

import asyncio
import json
import sys
import types
from contextlib import contextmanager

import pytest
from sqlmodel import SQLModel

from testing.database import (
    install_app_database_alias,
    reload_module,
    temp_sqlite_database,
)


@contextmanager
def load_task_jobs(monkeypatch, tmp_path):
    with temp_sqlite_database(monkeypatch, tmp_path) as (database, _db_path):
        SQLModel.metadata.clear()
        for name in ("desktop_task_jobs", "background_jobs"):
            sys.modules.pop(name, None)
        install_app_database_alias(database)
        background_jobs = reload_module("background_jobs")
        forger_desktop = types.ModuleType("forger_desktop")
        app_module = sys.modules["app"]
        app_module.background_jobs = background_jobs  # type: ignore[attr-defined]
        app_module.forger_desktop = forger_desktop  # type: ignore[attr-defined]
        sys.modules["app.background_jobs"] = background_jobs
        sys.modules["app.forger_desktop"] = forger_desktop
        desktop_task_jobs = reload_module("desktop_task_jobs")
        database.SQLModel.metadata.create_all(database.engine)
        try:
            yield background_jobs, desktop_task_jobs, forger_desktop
        finally:
            SQLModel.metadata.clear()
            for name in (
                "desktop_task_jobs",
                "background_jobs",
                "app.background_jobs",
                "app.forger_desktop",
                "app.database",
                "app",
                "database",
            ):
                sys.modules.pop(name, None)


def test_enqueue_register_and_complete_task_job(monkeypatch, tmp_path) -> None:
    with load_task_jobs(monkeypatch, tmp_path) as (jobs, task_jobs, desktop):
        states = iter(
            [
                {
                    "runId": "run_1",
                    "status": "running",
                    "progressLog": ["starting"],
                },
                {
                    "runId": "run_1",
                    "status": "completed",
                    "progressLog": ["starting", "done"],
                    "resultText": "Finished",
                },
            ]
        )
        desktop.start_agent_task = lambda **_kwargs: next(states)
        desktop.get_agent_task = lambda _run_id: next(states)
        monkeypatch.setattr(task_jobs.asyncio, "sleep", _noop_sleep)
        seen: list[tuple[str, str]] = []

        @task_jobs.on_task_update
        def update(_ctx, payload):
            seen.append(("update", payload["status"]))

        @task_jobs.on_task_success
        async def success(_ctx, payload):
            seen.append(("success", payload["resultText"]))

        registry = task_jobs.register_desktop_task_jobs()
        assert task_jobs.register_desktop_task_jobs(registry) is registry
        queued = task_jobs.enqueue_desktop_task_job(
            template_id="coach",
            arguments={"game_id": {"type": "string", "value": "g1"}},
            poll_interval_seconds=0.2,
        )
        ran = asyncio.run(jobs.run_due_jobs_once(registry))
        finished = jobs.get_job(queued.id)
        result = json.loads(finished.result_json)

        assert ran[0].status == jobs.BackgroundJobStatus.SUCCEEDED
        assert result["desktop_run_id"] == "run_1"
        assert result["messages"] == ["starting", "done"]
        assert result["resultText"] == "Finished"
        assert finished.progress_message == "done"
        assert seen == [("update", "running"), ("update", "completed"), ("success", "Finished")]


def test_task_job_failure_cancel_timeout_and_helpers(monkeypatch, tmp_path) -> None:
    with load_task_jobs(monkeypatch, tmp_path) as (jobs, task_jobs, desktop):
        assert task_jobs.desktop_task_run_id({"id": "legacy"}) == "legacy"
        assert task_jobs.desktop_task_messages(
            {
                "message": "one",
                "progressLog": ["two", "two"],
                "events": [{"text": "three"}],
            }
        ) == ["one", "two", "three"]
        with pytest.raises(ValueError, match="template_id"):
            task_jobs.enqueue_desktop_task_job(template_id=" ")

        errors: list[str] = []

        @task_jobs.on_task_error
        def error(_ctx, payload):
            errors.append(payload["error"])

        desktop.start_agent_task = lambda **_kwargs: {
            "runId": "run_failed",
            "status": "failed",
            "error": "bad",
        }
        failed = task_jobs.enqueue_desktop_task_job(template_id="fail")
        asyncio.run(jobs.run_due_jobs_once(task_jobs.register_desktop_task_jobs()))
        assert jobs.get_job(failed.id).status == jobs.BackgroundJobStatus.FAILED
        assert errors == ["bad"]

        canceled = jobs.enqueue_job(task_jobs.DESKTOP_TASK_JOB_TYPE)
        jobs._claim_due_jobs(queue="default", limit=1, lock_owner="test")
        jobs.cancel_job(canceled.id)
        desktop.cancel_agent_task = lambda run_id: {"runId": run_id, "status": "canceled"}
        result = asyncio.run(
            task_jobs.poll_desktop_task_job(
                jobs.JobContext(canceled.id),
                task={"runId": "run_cancel", "status": "running"},
                timeout_seconds=1,
            )
        )
        assert result["status"] == "canceled"

        canceled_by_desktop = jobs.enqueue_job(task_jobs.DESKTOP_TASK_JOB_TYPE)
        jobs._claim_due_jobs(queue="default", limit=1, lock_owner="test")
        published: list[tuple[str, str, dict]] = []
        realtime = types.ModuleType("realtime")
        realtime.hub = types.SimpleNamespace(
            publish=lambda channel, event_type, payload: _publish(
                published,
                channel,
                event_type,
                payload,
            )
        )
        sys.modules["app.realtime"] = realtime
        canceled_result = asyncio.run(
            task_jobs.poll_desktop_task_job(
                jobs.JobContext(canceled_by_desktop.id),
                task={"runId": "run_done", "status": "canceled"},
                realtime_channel="tasks",
            )
        )
        assert canceled_result["status"] == "canceled"
        assert published[-1][1] == "desktop.task.canceled"

        with pytest.raises(task_jobs.DesktopTaskJobError, match="run id"):
            asyncio.run(
                task_jobs.poll_desktop_task_job(
                    jobs.JobContext(canceled.id),
                    task={"status": "running"},
                )
            )

        desktop.get_agent_task = lambda _run_id: None
        with pytest.raises(task_jobs.DesktopTaskJobError, match="disappeared"):
            asyncio.run(
                task_jobs.poll_desktop_task_job(
                    jobs.JobContext(jobs.enqueue_job(task_jobs.DESKTOP_TASK_JOB_TYPE).id),
                    task={"runId": "missing", "status": "running"},
                    timeout_seconds=1,
                    poll_interval_seconds=0.2,
                )
            )

        desktop.get_agent_task = lambda _run_id: {"runId": "slow", "status": "running"}
        times = iter([0, 2])
        monkeypatch.setattr(
            task_jobs,
            "time",
            types.SimpleNamespace(monotonic=lambda: next(times)),
        )
        monkeypatch.setattr(task_jobs.asyncio, "sleep", _noop_sleep)
        with pytest.raises(task_jobs.DesktopTaskJobError, match="timed out"):
            asyncio.run(
                task_jobs.poll_desktop_task_job(
                    jobs.JobContext(jobs.enqueue_job(task_jobs.DESKTOP_TASK_JOB_TYPE).id),
                    task={"runId": "slow", "status": "running"},
                    timeout_seconds=1,
                )
            )
        task_jobs._store_partial_result("missing", {"status": "ignored"})
        stored_canceled = jobs.enqueue_job(task_jobs.DESKTOP_TASK_JOB_TYPE)
        jobs.cancel_job(stored_canceled.id)
        task_jobs._store_partial_result(stored_canceled.id, {"status": "ignored"})
        assert jobs.get_job(stored_canceled.id).result_json is None


async def _noop_sleep(_seconds: float) -> None:
    return None


async def _publish(
    published: list[tuple[str, str, dict]],
    channel: str,
    event_type: str,
    payload: dict,
) -> None:
    published.append((channel, event_type, payload))
