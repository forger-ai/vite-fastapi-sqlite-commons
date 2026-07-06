from __future__ import annotations

import base64
import hashlib
import hmac
import json
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


def test_runtime_url_normalizes_legacy_bridge_paths() -> None:
    assert forger_desktop.normalize_runtime_url("") == ""
    assert (
        forger_desktop.normalize_runtime_url(
            " http://127.0.0.1:1234/forgerApp/bridge/ ",
        )
        == "http://127.0.0.1:1234"
    )
    assert (
        forger_desktop.normalize_runtime_url("http://127.0.0.1:1234/api/bridge")
        == "http://127.0.0.1:1234"
    )
    assert (
        forger_desktop.normalize_runtime_url("http://127.0.0.1:1234")
        == "http://127.0.0.1:1234"
    )


def test_agent_task_requests_are_signed_and_strip_none(monkeypatch, desktop_env) -> None:
    fake = FakeDesktopRuntime()
    base = f"/v1/apps/{desktop_env['app_id']}"
    fake.add_json("GET", f"{base}/context", {"locale": "en", "rawLocale": "en-US"})
    fake.add_json("GET", f"{base}/agent-tasks/status", {"available": True})
    fake.add_json("POST", f"{base}/agent-tasks", {"runId": "task_1"})
    fake.add_json("GET", f"{base}/agent-tasks/task_1", {"status": "completed"})
    fake.add_json("POST", f"{base}/agent-tasks/task_1/cancel", {"canceled": True})
    monkeypatch.setattr(forger_desktop, "urlopen", fake.urlopen)

    assert forger_desktop.is_desktop_runtime_available() is True
    assert forger_desktop.get_app_context() == {"locale": "en", "rawLocale": "en-US"}
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
        workspace_path="/tmp/app",
        workspace={
            "cwdGrantId": "workspace_1",
            "additionalFolderGrantIds": ["workspace_2"],
        },
    ) == {"runId": "task_1"}
    assert forger_desktop.start_agent_task(
        template_id="template",
        runtime={"provider": "codex", "model": "gpt-5.4", "effort": "medium"},
    ) == {"runId": "task_1"}
    assert forger_desktop.get_agent_task("task_1") == {"status": "completed"}
    assert forger_desktop.cancel_agent_task("task_1") == {"canceled": True}

    assert_signed_desktop_request(
        fake.requests[0],
        app_id=desktop_env["app_id"],
        secret=desktop_env["secret"],
    )
    first_post = fake.requests[2]
    assert first_post.body == b'{"templateId":"template"}'
    assert_signed_desktop_request(
        first_post,
        app_id=desktop_env["app_id"],
        secret=desktop_env["secret"],
    )
    assert json.loads(fake.requests[3].body) == {
        "templateId": "template",
        "locale": "en",
        "arguments": {"name": "value"},
        "variables": {"context": "demo"},
        "attachments": [{"id": "att_1"}],
        "workspacePath": "/tmp/app",
        "workspace": {
            "cwdGrantId": "workspace_1",
            "additionalFolderGrantIds": ["workspace_2"],
        },
    }
    assert json.loads(fake.requests[4].body) == {
        "templateId": "template",
        "runtime": {"provider": "codex", "model": "gpt-5.4", "effort": "medium"},
    }


def test_audio_runtime_requests_are_signed_and_use_exact_routes(monkeypatch, desktop_env) -> None:
    fake = FakeDesktopRuntime()
    base = f"/v1/apps/{desktop_env['app_id']}"
    fake.add_json(
        "GET",
        f"{base}/audio/devices",
        {"inputDevices": [{"id": "default"}], "outputDevices": [{"id": "speaker"}]},
    )
    fake.add_json("GET", f"{base}/audio/input-devices", {"inputDevices": []})
    fake.add_json("GET", f"{base}/audio/output-devices", {"outputDevices": []})
    fake.add_json(
        "POST",
        f"{base}/audio/transcriptions",
        {"sessionId": "session_1", "url": "ws://127.0.0.1/live", "token": "token"},
    )
    fake.add_json(
        "DELETE",
        f"{base}/audio/transcriptions/consumer-1",
        {"success": True},
    )
    fake.add_json(
        "POST",
        f"{base}/audio/file-transcriptions",
        {"success": True, "text": "hola"},
    )
    fake.add_json(
        "POST",
        f"{base}/audio/file-transcription-jobs",
        {"jobId": "file_job_1", "status": "queued"},
    )
    fake.add_json(
        "GET",
        f"{base}/audio/file-transcription-jobs/file_job_1",
        {"jobId": "file_job_1", "status": "completed"},
    )
    fake.add_json(
        "POST",
        f"{base}/audio/file-transcription-jobs/file_job_1/cancel",
        {"jobId": "file_job_1", "status": "canceled"},
    )
    fake.add_json(
        "POST",
        f"{base}/audio/synthesis",
        {"success": True, "audioDataBase64": "UklGRg==", "mimeType": "audio/wav"},
    )
    fake.add_json(
        "POST",
        f"{base}/audio/say",
        {"success": True, "playbackId": "playback_1", "status": "queued"},
    )
    fake.add_json(
        "GET",
        f"{base}/audio/playbacks/playback_1",
        {"playbackId": "playback_1", "status": "completed"},
    )
    fake.add_json(
        "POST",
        f"{base}/audio/playbacks/playback_1/cancel",
        {"playbackId": "playback_1", "status": "canceled"},
    )
    monkeypatch.setattr(forger_desktop, "urlopen", fake.urlopen)

    assert forger_desktop.list_audio_devices()["inputDevices"][0]["id"] == "default"
    assert forger_desktop.list_audio_input_devices() == {"inputDevices": []}
    assert forger_desktop.list_audio_output_devices() == {"outputDevices": []}
    assert forger_desktop.start_audio_transcription_session(
        device_id="default",
        task="translate",
        language="es",
    )["sessionId"] == "session_1"
    assert forger_desktop.stop_audio_transcription_session("consumer-1") == {"success": True}
    assert forger_desktop.transcribe_audio_file(
        path="/tmp/app/audio.wav",
        task="transcribe",
        language="es",
        model="small",
    ) == {"success": True, "text": "hola"}
    assert forger_desktop.start_audio_file_transcription_job(
        path="/tmp/app/audio.wav",
        task="transcribe",
        language="es",
        model="large-v3",
    )["jobId"] == "file_job_1"
    assert forger_desktop.get_audio_file_transcription_job("file_job_1")["status"] == "completed"
    assert forger_desktop.cancel_audio_file_transcription_job("file_job_1")["status"] == "canceled"
    assert forger_desktop.synthesize_speech(
        text="hola",
        model="kokoro",
        voice="ef_dora",
        speed=1.1,
        format="wav",
    )["mimeType"] == "audio/wav"
    assert forger_desktop.say_text(
        text="hola",
        model="kokoro",
        voice="ef_dora",
        output_device_id="speaker",
        speed=0.9,
    )["playbackId"] == "playback_1"
    assert forger_desktop.get_audio_playback("playback_1")["status"] == "completed"
    assert forger_desktop.cancel_audio_playback("playback_1")["status"] == "canceled"

    for record in fake.requests:
        assert_signed_desktop_request(
            record,
            app_id=desktop_env["app_id"],
            secret=desktop_env["secret"],
        )
    assert fake.requests[3].path == f"{base}/audio/transcriptions"
    assert fake.requests[3].body == b'{"deviceId":"default","task":"translate","language":"es"}'
    assert fake.requests[4].path == f"{base}/audio/transcriptions/consumer-1"
    assert fake.requests[4].method == "DELETE"
    assert fake.requests[4].body == b""
    assert fake.requests[5].path == f"{base}/audio/file-transcriptions"
    assert fake.requests[5].body == (
        b'{"path":"/tmp/app/audio.wav","task":"transcribe","language":"es","model":"small"}'
    )
    assert fake.requests[6].path == f"{base}/audio/file-transcription-jobs"
    assert fake.requests[6].body == (
        b'{"path":"/tmp/app/audio.wav","task":"transcribe","language":"es","model":"large-v3"}'
    )
    assert fake.requests[7].path == f"{base}/audio/file-transcription-jobs/file_job_1"
    assert fake.requests[7].method == "GET"
    assert fake.requests[8].path == f"{base}/audio/file-transcription-jobs/file_job_1/cancel"
    assert fake.requests[8].method == "POST"
    assert fake.requests[9].body == (
        b'{"text":"hola","model":"kokoro","voice":"ef_dora","speed":1.1,"format":"wav"}'
    )
    assert fake.requests[10].body == (
        b'{"text":"hola","model":"kokoro","voice":"ef_dora","outputDeviceId":"speaker",'
        b'"speed":0.9}'
    )


def test_audio_runtime_helpers_strip_optional_none(monkeypatch, desktop_env) -> None:
    fake = FakeDesktopRuntime()
    base = f"/v1/apps/{desktop_env['app_id']}"
    fake.add_json("POST", f"{base}/audio/transcriptions", {"sessionId": "session_1"})
    fake.add_json("POST", f"{base}/audio/file-transcriptions", {"success": True})
    fake.add_json("POST", f"{base}/audio/file-transcription-jobs", {"jobId": "job_1"})
    fake.add_json("POST", f"{base}/audio/synthesis", {"success": True})
    fake.add_json("POST", f"{base}/audio/say", {"success": True})
    monkeypatch.setattr(forger_desktop, "urlopen", fake.urlopen)

    forger_desktop.start_audio_transcription_session()
    forger_desktop.transcribe_audio_file(path="/tmp/audio.wav")
    forger_desktop.start_audio_file_transcription_job(path="/tmp/audio.wav")
    forger_desktop.synthesize_speech(text="hola", model="kokoro", voice="ef_dora")
    forger_desktop.say_text(text="hola", model="kokoro", voice="ef_dora")

    assert fake.requests[0].body == b"{}"
    assert fake.requests[1].body == b'{"path":"/tmp/audio.wav"}'
    assert fake.requests[2].body == b'{"path":"/tmp/audio.wav"}'
    assert fake.requests[3].body == b'{"text":"hola","model":"kokoro","voice":"ef_dora"}'
    assert fake.requests[4].body == b'{"text":"hola","model":"kokoro","voice":"ef_dora"}'


def test_folder_grant_helpers_use_signed_grant_routes(monkeypatch, desktop_env) -> None:
    fake = FakeDesktopRuntime()
    base = f"/v1/apps/{desktop_env['app_id']}"
    fake.add_json(
        "POST",
        f"{base}/folder-grants/request",
        {
            "grantId": "grant_1",
            "path": "/Users/me/Documents",
            "access": "readWrite",
        },
    )
    fake.add_json(
        "GET",
        f"{base}/folder-grants",
        {"grants": [{"grantId": "grant_1"}]},
    )
    fake.add_json(
        "DELETE",
        f"{base}/folder-grants/grant%2F1",
        {"revoked": True},
    )
    monkeypatch.setattr(forger_desktop, "urlopen", fake.urlopen)

    assert forger_desktop.request_folder_grant(
        grant_token="signed-folder-token",
    )["grantId"] == "grant_1"
    assert forger_desktop.list_folder_grants() == {"grants": [{"grantId": "grant_1"}]}
    assert forger_desktop.revoke_folder_grant("grant/1") == {"revoked": True}

    assert fake.requests[0].method == "POST"
    assert fake.requests[0].path == f"{base}/folder-grants/request"
    assert json.loads(fake.requests[0].body) == {
        "grantToken": "signed-folder-token",
    }
    assert fake.requests[1].method == "GET"
    assert fake.requests[1].body == b""
    assert fake.requests[2].method == "DELETE"
    assert fake.requests[2].path == f"{base}/folder-grants/grant%2F1"
    assert fake.requests[2].body == b""
    for record in fake.requests:
        assert_signed_desktop_request(
            record,
            app_id=desktop_env["app_id"],
            secret=desktop_env["secret"],
        )


def test_official_tool_helpers_use_signed_tool_routes(monkeypatch, desktop_env) -> None:
    fake = FakeDesktopRuntime()
    base = f"/v1/apps/{desktop_env['app_id']}"
    fake.add_json("GET", f"{base}/tools", {"tools": [{"id": "forger_chrome_extension"}]})
    fake.add_json(
        "GET",
        f"{base}/tools/forger_chrome_extension",
        {"id": "forger_chrome_extension"},
    )
    fake.add_json(
        "POST",
        f"{base}/tools/forger_chrome_extension/actions/forger_chrome_extension.get_styles",
        {"success": True, "data": {"styles": {}}},
    )
    monkeypatch.setattr(forger_desktop, "urlopen", fake.urlopen)

    assert forger_desktop.list_official_tools()["tools"][0]["id"] == "forger_chrome_extension"
    assert (
        forger_desktop.get_official_tool("forger_chrome_extension")["id"]
        == "forger_chrome_extension"
    )
    assert forger_desktop.call_official_tool(
        "forger_chrome_extension",
        "forger_chrome_extension.get_styles",
        {"sessionId": "session_1", "selector": "#total"},
    )["success"] is True

    assert fake.requests[0].method == "GET"
    assert fake.requests[0].path == f"{base}/tools"
    assert fake.requests[1].path == f"{base}/tools/forger_chrome_extension"
    assert fake.requests[2].method == "POST"
    assert fake.requests[2].path == (
        f"{base}/tools/forger_chrome_extension/actions/"
        "forger_chrome_extension.get_styles"
    )
    assert json.loads(fake.requests[2].body) == {
        "input": {
            "sessionId": "session_1",
            "selector": "#total",
        },
    }
    for record in fake.requests:
        assert_signed_desktop_request(
            record,
            app_id=desktop_env["app_id"],
            secret=desktop_env["secret"],
        )


def test_connection_helpers_serialize_action_inputs(monkeypatch, desktop_env) -> None:
    fake = FakeDesktopRuntime()
    base = f"/v1/apps/{desktop_env['app_id']}"
    fake.add_json("GET", f"{base}/connections", {"types": [{"type": "gmail"}]})
    fake.add_json(
        "GET",
        f"{base}/connections/gmail/status",
        {"connected": True, "status": "connected"},
    )
    fake.add_json(
        "POST",
        f"{base}/connections/gmail/actions/gmail.search_messages",
        {"success": True, "data": {"messages": []}},
    )
    fake.add_json(
        "POST",
        f"{base}/connections/slack/actions/slack.send_message",
        {"success": True, "data": {"sent": True}},
    )
    monkeypatch.setattr(forger_desktop, "urlopen", fake.urlopen)

    assert forger_desktop.list_connections()["types"][0]["type"] == "gmail"
    assert forger_desktop.connection_status("gmail")["connected"] is True
    assert forger_desktop.get_connection_status("gmail")["connected"] is True
    assert forger_desktop.call_connection_action(
        "gmail",
        "gmail.search_messages",
        {"query": "from:example@example.com"},
        connection_id="gmail-default",
    )["success"] is True
    assert forger_desktop.call_connection_action(
        "slack",
        "slack.send_message",
        {"channel": "C123", "text": "Hello"},
    )["success"] is True

    assert fake.requests[0].method == "GET"
    assert fake.requests[0].path == f"{base}/connections"
    assert fake.requests[1].path == f"{base}/connections/gmail/status"
    assert fake.requests[2].path == f"{base}/connections/gmail/status"
    assert fake.requests[3].method == "POST"
    assert fake.requests[3].path == (
        f"{base}/connections/gmail/actions/"
        "gmail.search_messages"
    )
    assert json.loads(fake.requests[3].body) == {
        "input": {"query": "from:example@example.com"},
        "connectionId": "gmail-default",
    }
    assert fake.requests[4].method == "POST"
    assert fake.requests[4].path == (
        f"{base}/connections/slack/actions/"
        "slack.send_message"
    )
    assert json.loads(fake.requests[4].body) == {
        "input": {"channel": "C123", "text": "Hello"},
    }
    for record in fake.requests:
        assert_signed_desktop_request(
            record,
            app_id=desktop_env["app_id"],
            secret=desktop_env["secret"],
        )


def test_chrome_official_tool_helpers_serialize_action_inputs(monkeypatch, desktop_env) -> None:
    fake = FakeDesktopRuntime()
    base = f"/v1/apps/{desktop_env['app_id']}"
    action_ids = [
        "connection.status",
        "open_dedicated_tab",
        "get_current_url",
        "navigate",
        "get_html",
        "wait_for_selector",
        "click",
        "focus",
        "hover",
        "input_text",
        "submit_form",
        "get_styles",
        "set_styles",
        "set_styles",
        "close_window",
        "close_session",
    ]
    for action in action_ids:
        fake.add_json(
            "POST",
            f"{base}/tools/forger_chrome_extension/actions/forger_chrome_extension.{action}",
            {"success": True, "action": action},
        )
    monkeypatch.setattr(forger_desktop, "urlopen", fake.urlopen)

    assert forger_desktop.chrome_connection_status()["success"] is True
    assert forger_desktop.chrome_open_dedicated_tab()["success"] is True
    assert forger_desktop.chrome_get_current_url("session_1")["success"] is True
    assert forger_desktop.chrome_navigate("session_1", "https://example.com")["success"] is True
    assert forger_desktop.chrome_get_html("session_1")["success"] is True
    assert (
        forger_desktop.chrome_wait_for_selector("session_1", "#ready", timeout_ms=60000)[
            "success"
        ]
        is True
    )
    assert forger_desktop.chrome_click("session_1", "#save")["success"] is True
    assert forger_desktop.chrome_focus("session_1", "#name")["success"] is True
    assert forger_desktop.chrome_hover("session_1", "#menu")["success"] is True
    assert forger_desktop.chrome_input_text("session_1", "#name", "Forger")["success"] is True
    assert forger_desktop.chrome_submit_form(
        "session_1",
        "form",
        submit_selector="button.primary",
    )["success"] is True
    assert forger_desktop.chrome_get_styles(
        "session_1",
        "#total",
        properties=["outline", "box-shadow"],
    )["success"] is True
    assert forger_desktop.chrome_set_styles(
        "session_1",
        "#total",
        {"outline": "2px solid #dd782b"},
    )["success"] is True
    assert forger_desktop.chrome_highlight_element("session_1", "#total")["success"] is True
    assert forger_desktop.chrome_close_window("session_1")["success"] is True
    assert forger_desktop.chrome_close_session("session_1")["success"] is True

    assert json.loads(fake.requests[0].body) == {"input": {}}
    assert json.loads(fake.requests[1].body) == {"input": {}}
    assert json.loads(fake.requests[2].body) == {"input": {"sessionId": "session_1"}}
    assert json.loads(fake.requests[3].body) == {
        "input": {"sessionId": "session_1", "url": "https://example.com"},
    }
    assert json.loads(fake.requests[4].body) == {"input": {"sessionId": "session_1"}}
    assert json.loads(fake.requests[5].body) == {
        "input": {
            "sessionId": "session_1",
            "selector": "#ready",
            "state": "visible",
            "timeoutMs": 60000,
        },
    }
    assert fake.requests[5].timeout == 70
    assert fake.requests[4].timeout == 30
    assert json.loads(fake.requests[9].body) == {
        "input": {"sessionId": "session_1", "selector": "#name", "text": "Forger"},
    }
    assert json.loads(fake.requests[10].body) == {
        "input": {
            "sessionId": "session_1",
            "selector": "form",
            "submitSelector": "button.primary",
        },
    }
    assert json.loads(fake.requests[11].body) == {
        "input": {
            "sessionId": "session_1",
            "selector": "#total",
            "properties": ["outline", "box-shadow"],
        },
    }
    assert json.loads(fake.requests[12].body) == {
        "input": {
            "sessionId": "session_1",
            "selector": "#total",
            "styles": {"outline": "2px solid #dd782b"},
        },
    }
    assert json.loads(fake.requests[13].body)["input"]["styles"] == {
        "outline": "2px solid #dd782b",
        "outline-offset": "3px",
        "box-shadow": "0 0 0 4px rgba(221, 120, 43, 0.24)",
    }
    assert json.loads(fake.requests[14].body) == {"input": {"sessionId": "session_1"}}
    assert json.loads(fake.requests[15].body) == {"input": {"sessionId": "session_1"}}

    assert forger_desktop.chrome_open_dedicated_tab("https://example.com")["success"] is True
    assert forger_desktop.chrome_get_html("session_1", selector="#main")["success"] is True
    assert forger_desktop.chrome_submit_form("session_1", "form")["success"] is True
    assert forger_desktop.chrome_get_styles("session_1", "#total")["success"] is True
    assert json.loads(fake.requests[16].body) == {
        "input": {"url": "https://example.com"},
    }
    assert json.loads(fake.requests[17].body) == {
        "input": {"sessionId": "session_1", "selector": "#main"},
    }
    assert json.loads(fake.requests[18].body) == {
        "input": {"sessionId": "session_1", "selector": "form"},
    }
    assert json.loads(fake.requests[19].body) == {
        "input": {"sessionId": "session_1", "selector": "#total"},
    }
    for record in fake.requests:
        assert_signed_desktop_request(
            record,
            app_id=desktop_env["app_id"],
            secret=desktop_env["secret"],
        )


def test_create_folder_grant_token_matches_desktop_contract(monkeypatch, desktop_env) -> None:
    monkeypatch.setenv("FORGER_APP_GRANT_SECRET", "grant.secret")
    monkeypatch.setattr(forger_desktop.time, "time", lambda: 1_700_000_000)

    token = forger_desktop.create_folder_grant_token(
        path=" /Users/me/Project ",
        expires_in_seconds=120,
    )

    payload, signature = token.split(".")
    decoded_payload = json.loads(_base64url_decode(payload).decode("utf-8"))
    assert decoded_payload == {
        "appId": desktop_env["app_id"],
        "path": "/Users/me/Project",
        "exp": 1_700_000_120,
    }
    expected_signature = _base64url_encode(
        hmac.new(
            b"grant.secret",
            payload.encode("utf-8"),
            hashlib.sha256,
        ).digest(),
    )
    assert signature == expected_signature


def test_request_folder_grant_for_path_signs_and_requests_grant(monkeypatch, desktop_env) -> None:
    fake = FakeDesktopRuntime()
    base = f"/v1/apps/{desktop_env['app_id']}"
    fake.add_json(
        "POST",
        f"{base}/folder-grants/request",
        {"grantId": "grant_1"},
    )
    monkeypatch.setattr(forger_desktop, "urlopen", fake.urlopen)
    monkeypatch.setenv("FORGER_APP_GRANT_SECRET", "grant.secret")
    monkeypatch.setattr(forger_desktop.time, "time", lambda: 1_700_000_000)

    assert forger_desktop.request_folder_grant_for_path(
        path="/Users/me/Project",
        expires_in_seconds=60,
    ) == {"grantId": "grant_1"}

    body = json.loads(fake.requests[0].body)
    payload, signature = body["grantToken"].split(".")
    assert json.loads(_base64url_decode(payload).decode("utf-8")) == {
        "appId": desktop_env["app_id"],
        "path": "/Users/me/Project",
        "exp": 1_700_000_060,
    }
    assert signature == _base64url_encode(
        hmac.new(
            b"grant.secret",
            payload.encode("utf-8"),
            hashlib.sha256,
        ).digest(),
    )
    assert_signed_desktop_request(
        fake.requests[0],
        app_id=desktop_env["app_id"],
        secret=desktop_env["secret"],
    )


def test_create_folder_grant_token_requires_app_id_secret_and_path(monkeypatch) -> None:
    monkeypatch.delenv("FORGER_DESKTOP_RUNTIME_APP_ID", raising=False)
    monkeypatch.delenv("FORGER_APP_GRANT_SECRET", raising=False)
    with pytest.raises(forger_desktop.ForgerAppGrantUnavailable):
        forger_desktop.create_folder_grant_token(path="/Users/me/Project")

    monkeypatch.setenv("FORGER_DESKTOP_RUNTIME_APP_ID", "app.test")
    monkeypatch.setenv("FORGER_APP_GRANT_SECRET", "grant.secret")
    with pytest.raises(ValueError):
        forger_desktop.create_folder_grant_token(path=" ")


def test_agent_thread_and_run_requests_are_signed(monkeypatch, desktop_env) -> None:
    fake = FakeDesktopRuntime()
    base = f"/v1/apps/{desktop_env['app_id']}"
    fake.add_json(
        "POST",
        f"{base}/agents/agent/start",
        {
            "desktop_thread_id": "thread_1",
            "active_run": {"desktop_run_id": "run_start", "status": "running"},
        },
    )
    fake.add_json("GET", f"{base}/agent-threads/thread_1", {"id": "thread_1"})
    fake.add_json(
        "POST",
        f"{base}/agent-threads/thread_1/resume",
        {"desktop_run_id": "run_1", "status": "running"},
    )
    fake.add_json(
        "POST",
        f"{base}/agent-threads/thread_1/runs/run_1/steer",
        {"desktop_run_id": "run_2", "status": "running"},
    )
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

    assert forger_desktop.start_manifest_agent_thread(
        agent_id="agent",
        title="Thread",
        variables={"message": "Start"},
        workspace={
            "cwdGrantId": "workspace_1",
            "additionalFolderGrantIds": ["workspace_2"],
        },
    )["desktop_thread_id"] == "thread_1"
    assert forger_desktop.create_agent_thread(
        title="Thread",
        manifest_agent_id="agent",
        initial_prompt="Start",
    )["threadId"] == "thread_1"
    assert forger_desktop.create_agent_thread(
        title="Thread",
        manifest_agent_id="agent",
        initial_prompt="Start",
        runtime={"mode": "test"},
        metadata={"source": "pytest"},
        workspace_path="/tmp/app",
        workspace={
            "cwdGrantId": "workspace_1",
            "additionalFolderGrantIds": ["workspace_2"],
        },
    )["id"] == "thread_1"
    assert forger_desktop.get_agent_thread("thread_1") == {"id": "thread_1"}
    assert forger_desktop.resume_manifest_agent_thread(
        desktop_thread_id="thread_1",
        variables={"message": "Hello"},
    ) == {"desktop_run_id": "run_1", "status": "running"}
    assert forger_desktop.start_agent_run(
        desktop_thread_id="thread_1",
        message="Hello",
    )["runId"] == "run_1"
    assert forger_desktop.start_agent_run(
        desktop_thread_id="thread_1",
        message="Hello",
        context="Context",
        runtime={"mode": "test"},
        workspace_path="/tmp/app",
        workspace={
            "cwdGrantId": "workspace_1",
            "additionalFolderGrantIds": ["workspace_2"],
        },
    )["id"] == "run_1"
    assert forger_desktop.steer_manifest_agent_run(
        desktop_thread_id="thread_1",
        desktop_run_id="run_1",
        variables={"instruction": "Adjust"},
        workspace={
            "cwdGrantId": "workspace_1",
            "additionalFolderGrantIds": ["workspace_2"],
        },
    ) == {"desktop_run_id": "run_2", "status": "running"}
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
    assert json.loads(fake.requests[0].body) == {
        "title": "Thread",
        "variables": {"message": "Start"},
        "workspace": {
            "cwdGrantId": "workspace_1",
            "additionalFolderGrantIds": ["workspace_2"],
        },
    }
    assert json.loads(fake.requests[2].body) == {
        "title": "Thread",
        "variables": {"message": "Start"},
        "runtime": {"mode": "test"},
        "metadata": {"source": "pytest"},
        "workspacePath": "/tmp/app",
        "workspace": {
            "cwdGrantId": "workspace_1",
            "additionalFolderGrantIds": ["workspace_2"],
        },
    }
    assert json.loads(fake.requests[6].body) == {
        "variables": {
            "message": "Hello",
            "context": "Context",
            "session_state": "Context",
        },
        "runtime": {"mode": "test"},
        "workspacePath": "/tmp/app",
        "workspace": {
            "cwdGrantId": "workspace_1",
            "additionalFolderGrantIds": ["workspace_2"],
        },
    }
    assert json.loads(fake.requests[7].body) == {
        "variables": {"instruction": "Adjust"},
        "workspace": {
            "cwdGrantId": "workspace_1",
            "additionalFolderGrantIds": ["workspace_2"],
        },
    }


def test_legacy_aliases_preserve_existing_values() -> None:
    thread = forger_desktop._with_legacy_thread_aliases(
        {
            "desktop_thread_id": "desktop_thread",
            "threadId": "existing_thread",
            "id": "existing_id",
        }
    )
    run = forger_desktop._with_legacy_run_aliases(
        {
            "desktop_run_id": "desktop_run",
            "runId": "existing_run",
            "id": "existing_id",
        }
    )

    assert thread == {
        "desktop_thread_id": "desktop_thread",
        "threadId": "existing_thread",
        "id": "existing_id",
    }
    assert run == {
        "desktop_run_id": "desktop_run",
        "runId": "existing_run",
        "id": "existing_id",
    }


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


def _base64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}")


def _base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")
