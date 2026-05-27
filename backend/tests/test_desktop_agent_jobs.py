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
def load_agent_jobs(monkeypatch, tmp_path):
    with temp_sqlite_database(monkeypatch, tmp_path) as (database, _db_path):
        SQLModel.metadata.clear()
        for name in ("desktop_agent_jobs", "background_jobs"):
            sys.modules.pop(name, None)
        install_app_database_alias(database)
        background_jobs = reload_module("background_jobs")
        forger_desktop = types.ModuleType("forger_desktop")
        app_module = sys.modules["app"]
        app_module.background_jobs = background_jobs  # type: ignore[attr-defined]
        app_module.forger_desktop = forger_desktop  # type: ignore[attr-defined]
        sys.modules["app.background_jobs"] = background_jobs
        sys.modules["app.forger_desktop"] = forger_desktop
        desktop_agent_jobs = reload_module("desktop_agent_jobs")
        database.SQLModel.metadata.create_all(database.engine)
        try:
            yield background_jobs, desktop_agent_jobs, forger_desktop
        finally:
            SQLModel.metadata.clear()
            for name in (
                "desktop_agent_jobs",
                "background_jobs",
                "app.background_jobs",
                "app.forger_desktop",
                "app.database",
                "app",
                "database",
            ):
                sys.modules.pop(name, None)


def test_start_and_resume_agent_jobs_complete(monkeypatch, tmp_path) -> None:
    with load_agent_jobs(monkeypatch, tmp_path) as (jobs, agent_jobs, desktop):
        start_states = iter(
            [
                {
                    "desktop_thread_id": "thread_1",
                    "active_run": {"desktop_run_id": "run_1", "status": "running"},
                    "status": "running",
                    "progressLog": ["start"],
                },
                {
                    "desktop_thread_id": "thread_1",
                    "desktop_run_id": "run_1",
                    "status": "completed",
                    "progressLog": ["start", "done"],
                    "resultText": "Result",
                },
            ]
        )
        desktop.start_manifest_agent_thread = lambda **_kwargs: next(start_states)
        desktop.get_agent_run = lambda *_args: next(start_states)
        monkeypatch.setattr(agent_jobs.asyncio, "sleep", _noop_sleep)
        seen: list[tuple[str, str]] = []

        @agent_jobs.on_agent_update
        def update(_ctx, payload):
            seen.append(("update", payload["status"]))

        @agent_jobs.on_agent_success
        async def success(_ctx, payload):
            seen.append(("success", payload["resultText"]))

        registry = agent_jobs.register_desktop_agent_jobs()
        assert agent_jobs.register_desktop_agent_jobs(registry) is registry
        queued = agent_jobs.enqueue_desktop_agent_start_job(agent_id="coach")
        asyncio.run(jobs.run_due_jobs_once(registry))
        result = json.loads(jobs.get_job(queued.id).result_json)

        assert result["desktop_thread_id"] == "thread_1"
        assert result["desktop_run_id"] == "run_1"
        assert result["messages"] == ["start", "done"]
        assert seen == [("update", "running"), ("update", "completed"), ("success", "Result")]

        resume_states = iter(
            [
                {"desktop_run_id": "run_2", "status": "running", "progressLog": ["resume"]},
                {"desktop_run_id": "run_2", "status": "completed", "resultText": "OK"},
            ]
        )
        desktop.resume_manifest_agent_thread = lambda **_kwargs: next(resume_states)
        desktop.get_agent_run = lambda *_args: next(resume_states)
        queued_resume = agent_jobs.enqueue_desktop_agent_resume_job(desktop_thread_id="thread_1")
        asyncio.run(jobs.run_due_jobs_once(registry))
        assert json.loads(jobs.get_job(queued_resume.id).result_json)["resultText"] == "OK"


def test_agent_job_failure_cancel_timeout_and_helpers(monkeypatch, tmp_path) -> None:
    with load_agent_jobs(monkeypatch, tmp_path) as (jobs, agent_jobs, desktop):
        assert agent_jobs.desktop_thread_id({"threadId": "thread"}) == "thread"
        assert agent_jobs.desktop_run_id({"active_run": {"runId": "run"}}) == "run"
        assert agent_jobs.desktop_run_id({"active_run": {}, "runId": "fallback"}) == "fallback"
        assert agent_jobs.desktop_agent_messages(
            {"summary": "one", "progressLog": ["two", "two"], "logs": [{"title": "three"}]}
        ) == ["one", "two", "three"]
        with pytest.raises(ValueError, match="agent_id"):
            agent_jobs.enqueue_desktop_agent_start_job(agent_id=" ")
        with pytest.raises(ValueError, match="desktop_thread_id"):
            agent_jobs.enqueue_desktop_agent_resume_job(desktop_thread_id=" ")

        errors: list[str] = []

        @agent_jobs.on_agent_error
        def error(_ctx, payload):
            errors.append(payload["error"])

        desktop.resume_manifest_agent_thread = lambda **_kwargs: {
            "desktop_run_id": "run_failed",
            "status": "failed",
            "error": "bad",
        }
        failed = agent_jobs.enqueue_desktop_agent_resume_job(desktop_thread_id="thread")
        asyncio.run(jobs.run_due_jobs_once(agent_jobs.register_desktop_agent_jobs()))
        assert jobs.get_job(failed.id).status == jobs.BackgroundJobStatus.FAILED
        assert errors == ["bad"]

        canceled = jobs.enqueue_job(agent_jobs.DESKTOP_AGENT_RESUME_JOB_TYPE)
        jobs._claim_due_jobs(queue="default", limit=1, lock_owner="test")
        jobs.cancel_job(canceled.id)
        desktop.cancel_agent_run = lambda thread_id, run_id: {
            "thread": thread_id,
            "run": run_id,
            "status": "canceled",
        }
        result = asyncio.run(
            agent_jobs.poll_desktop_agent_job(
                jobs.JobContext(canceled.id),
                desktop_thread_id="thread",
                desktop_run_id="run_cancel",
                run={"status": "running"},
                timeout_seconds=1,
            )
        )
        assert result["status"] == "canceled"

        canceled_by_desktop = jobs.enqueue_job(agent_jobs.DESKTOP_AGENT_RESUME_JOB_TYPE)
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
            agent_jobs.poll_desktop_agent_job(
                jobs.JobContext(canceled_by_desktop.id),
                desktop_thread_id="thread",
                desktop_run_id="run_done",
                run={"status": "canceled"},
                realtime_channel="agents",
            )
        )
        assert canceled_result["status"] == "canceled"
        assert published[-1][1] == "desktop.agent.canceled"

        with pytest.raises(agent_jobs.DesktopAgentJobError, match="required"):
            asyncio.run(
                agent_jobs.poll_desktop_agent_job(
                    jobs.JobContext(canceled.id),
                    desktop_thread_id="",
                    desktop_run_id="",
                )
            )

        desktop.get_agent_run = lambda *_args: None
        with pytest.raises(agent_jobs.DesktopAgentJobError, match="disappeared"):
            asyncio.run(
                agent_jobs.poll_desktop_agent_job(
                    jobs.JobContext(jobs.enqueue_job(agent_jobs.DESKTOP_AGENT_RESUME_JOB_TYPE).id),
                    desktop_thread_id="thread",
                    desktop_run_id="missing",
                    timeout_seconds=1,
                )
            )

        desktop.get_agent_run = lambda *_args: {"status": "running"}
        times = iter([0, 2])
        monkeypatch.setattr(
            agent_jobs,
            "time",
            types.SimpleNamespace(monotonic=lambda: next(times)),
        )
        monkeypatch.setattr(agent_jobs.asyncio, "sleep", _noop_sleep)
        with pytest.raises(agent_jobs.DesktopAgentJobError, match="timed out"):
            asyncio.run(
                agent_jobs.poll_desktop_agent_job(
                    jobs.JobContext(jobs.enqueue_job(agent_jobs.DESKTOP_AGENT_RESUME_JOB_TYPE).id),
                    desktop_thread_id="thread",
                    desktop_run_id="slow",
                    timeout_seconds=1,
                )
            )
        agent_jobs._store_partial_result("missing", {"status": "ignored"})
        stored_canceled = jobs.enqueue_job(agent_jobs.DESKTOP_AGENT_RESUME_JOB_TYPE)
        jobs.cancel_job(stored_canceled.id)
        agent_jobs._store_partial_result(stored_canceled.id, {"status": "ignored"})
        assert jobs.get_job(stored_canceled.id).result_json is None

        with pytest.raises(agent_jobs.DesktopAgentJobError, match="did not return"):
            asyncio.run(
                agent_jobs._poll_started_or_resumed_agent_job(
                    jobs.JobContext(canceled.id),
                    thread_or_run={},
                    fallback_thread_id="",
                    realtime_channel=None,
                    poll_interval_seconds=1,
                    timeout_seconds=1,
                )
            )


async def _noop_sleep(_seconds: float) -> None:
    return None


async def _publish(
    published: list[tuple[str, str, dict]],
    channel: str,
    event_type: str,
    payload: dict,
) -> None:
    published.append((channel, event_type, payload))
