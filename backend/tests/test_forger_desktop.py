from __future__ import annotations

from io import BytesIO
from urllib.error import HTTPError, URLError

import pytest

import forger_desktop
from testing.desktop import FakeDesktopRuntime, assert_signed_desktop_request


@pytest.fixture
def desktop_env(monkeypatch) -> dict[str, str]:
    env = {
        "url": "http://127.0.0.1:9191",
        "app_id": "app.test",
        "secret": "secret.test",
    }
    monkeypatch.setenv("FORGER_DESKTOP_RUNTIME_URL", f"{env['url']}/")
    monkeypatch.setenv("FORGER_DESKTOP_RUNTIME_APP_ID", env["app_id"])
    monkeypatch.setenv("FORGER_DESKTOP_RUNTIME_SECRET", env["secret"])
    return env


def test_runtime_reports_unavailable_without_config(monkeypatch) -> None:
    monkeypatch.delenv("FORGER_DESKTOP_RUNTIME_URL", raising=False)
    monkeypatch.delenv("FORGER_DESKTOP_RUNTIME_APP_ID", raising=False)
    monkeypatch.delenv("FORGER_DESKTOP_RUNTIME_SECRET", raising=False)

    assert forger_desktop.is_desktop_runtime_available() is False
    with pytest.raises(forger_desktop.ForgerDesktopRuntimeUnavailable):
        forger_desktop.get_agent_task_status()


def test_agent_task_requests_are_signed_and_strip_none(monkeypatch, desktop_env) -> None:
    fake = FakeDesktopRuntime()
    base = f"/v1/apps/{desktop_env['app_id']}"
    fake.add_json("GET", f"{base}/agent-tasks/status", {"available": True})
    fake.add_json("POST", f"{base}/agent-tasks", {"runId": "task_1"})
    fake.add_json("GET", f"{base}/agent-tasks/task_1", {"status": "completed"})
    fake.add_json("POST", f"{base}/agent-tasks/task_1/cancel", {"canceled": True})
    monkeypatch.setattr(forger_desktop, "urlopen", fake.urlopen)

    assert forger_desktop.is_desktop_runtime_available() is True
    assert forger_desktop.get_agent_task_status() == {"available": True}
    assert forger_desktop.start_agent_task(template_id="template") == {
        "runId": "task_1"
    }
    assert forger_desktop.start_agent_task(
        template_id="template",
        locale="en",
        arguments={"name": "value"},
        variables={"context": "demo"},
        attachments=[{"id": "att_1"}],
    ) == {"runId": "task_1"}
    assert forger_desktop.get_agent_task("task_1") == {"status": "completed"}
    assert forger_desktop.cancel_agent_task("task_1") == {"canceled": True}

    first_post = fake.requests[1]
    assert first_post.body == b'{"templateId":"template"}'
    assert_signed_desktop_request(
        first_post,
        app_id=desktop_env["app_id"],
        secret=desktop_env["secret"],
    )


def test_agent_thread_and_run_requests_are_signed(monkeypatch, desktop_env) -> None:
    fake = FakeDesktopRuntime()
    base = f"/v1/apps/{desktop_env['app_id']}"
    fake.add_json("POST", f"{base}/agent-threads", {"id": "thread_1"})
    fake.add_json("GET", f"{base}/agent-threads/thread_1", {"id": "thread_1"})
    fake.add_json("POST", f"{base}/agent-threads/thread_1/runs", {"id": "run_1"})
    fake.add_json(
        "GET",
        f"{base}/agent-threads/thread_1/runs/run_1",
        {"status": "completed"},
    )
    fake.add_json(
        "POST",
        f"{base}/agent-threads/thread_1/runs/run_1/cancel",
        {"canceled": True},
    )
    monkeypatch.setattr(forger_desktop, "urlopen", fake.urlopen)

    assert forger_desktop.create_agent_thread(
        title="Thread",
        manifest_agent_id="agent",
        initial_prompt="Start",
    ) == {"id": "thread_1"}
    assert forger_desktop.create_agent_thread(
        title="Thread",
        manifest_agent_id="agent",
        initial_prompt="Start",
        runtime={"mode": "test"},
        metadata={"source": "pytest"},
        workspace_path="/tmp/app",
    ) == {"id": "thread_1"}
    assert forger_desktop.get_agent_thread("thread_1") == {"id": "thread_1"}
    assert forger_desktop.start_agent_run(
        desktop_thread_id="thread_1",
        message="Hello",
    ) == {"id": "run_1"}
    assert forger_desktop.start_agent_run(
        desktop_thread_id="thread_1",
        message="Hello",
        context="Context",
        runtime={"mode": "test"},
        workspace_path="/tmp/app",
    ) == {"id": "run_1"}
    assert forger_desktop.get_agent_run("thread_1", "run_1") == {
        "status": "completed"
    }
    assert forger_desktop.cancel_agent_run("thread_1", "run_1") == {
        "canceled": True
    }

    assert_signed_desktop_request(
        fake.requests[0],
        app_id=desktop_env["app_id"],
        secret=desktop_env["secret"],
    )


def test_request_returns_none_for_empty_desktop_response(
    monkeypatch,
    desktop_env,
) -> None:
    fake = FakeDesktopRuntime()
    fake.add_empty("GET", f"/v1/apps/{desktop_env['app_id']}/agent-threads/missing")
    monkeypatch.setattr(forger_desktop, "urlopen", fake.urlopen)

    assert forger_desktop.get_agent_thread("missing") is None


def test_request_wraps_http_and_url_errors(monkeypatch, desktop_env) -> None:
    http_error = HTTPError(
        url=desktop_env["url"],
        code=500,
        msg="server error",
        hdrs={},
        fp=BytesIO(b"broken"),
    )
    monkeypatch.setattr(
        forger_desktop,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(http_error),
    )

    with pytest.raises(
        forger_desktop.ForgerDesktopRuntimeError,
        match="desktop runtime returned 500: broken",
    ):
        forger_desktop.get_agent_task_status()

    monkeypatch.setattr(
        forger_desktop,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(URLError("offline")),
    )

    with pytest.raises(
        forger_desktop.ForgerDesktopRuntimeError,
        match="desktop runtime unavailable: offline",
    ):
        forger_desktop.get_agent_task_status()


def test_wait_for_task_returns_terminal_task_after_intermediate_states(
    monkeypatch,
) -> None:
    states = iter([None, {"status": "running"}, {"status": "completed"}])
    monkeypatch.setattr(forger_desktop, "get_agent_task", lambda _run_id: next(states))
    monkeypatch.setattr(forger_desktop.time, "monotonic", lambda: 0)
    monkeypatch.setattr(forger_desktop.time, "sleep", lambda _seconds: None)

    assert forger_desktop.wait_for_task(
        run_id="task_1",
        timeout_seconds=1,
        poll_interval_seconds=0,
    ) == {"status": "completed"}


def test_wait_for_task_times_out_with_last_seen_task(monkeypatch) -> None:
    times = iter([0, 0.1, 2])
    monkeypatch.setattr(
        forger_desktop,
        "get_agent_task",
        lambda _run_id: {"status": "running"},
    )
    monkeypatch.setattr(forger_desktop.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(forger_desktop.time, "sleep", lambda _seconds: None)

    with pytest.raises(
        forger_desktop.ForgerDesktopRuntimeError,
        match="agent task timed out: {'status': 'running'}",
    ):
        forger_desktop.wait_for_task(run_id="task_1", timeout_seconds=0)


def test_wait_for_run_returns_terminal_run_after_intermediate_states(monkeypatch) -> None:
    states = iter([None, {"status": "running"}, {"status": "failed"}])
    monkeypatch.setattr(
        forger_desktop,
        "get_agent_run",
        lambda _thread_id, _run_id: next(states),
    )
    monkeypatch.setattr(forger_desktop.time, "monotonic", lambda: 0)
    monkeypatch.setattr(forger_desktop.time, "sleep", lambda _seconds: None)

    assert forger_desktop.wait_for_run(
        desktop_thread_id="thread_1",
        desktop_run_id="run_1",
        timeout_seconds=1,
        poll_interval_seconds=0,
    ) == {"status": "failed"}


def test_wait_for_run_times_out_with_run_id_when_no_run_is_seen(monkeypatch) -> None:
    times = iter([0, 0.1, 2])
    monkeypatch.setattr(forger_desktop, "get_agent_run", lambda *_args: None)
    monkeypatch.setattr(forger_desktop.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(forger_desktop.time, "sleep", lambda _seconds: None)

    with pytest.raises(
        forger_desktop.ForgerDesktopRuntimeError,
        match="agent run timed out: run_1",
    ):
        forger_desktop.wait_for_run(
            desktop_thread_id="thread_1",
            desktop_run_id="run_1",
            timeout_seconds=0,
        )

