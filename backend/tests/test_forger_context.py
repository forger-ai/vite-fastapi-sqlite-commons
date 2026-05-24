from __future__ import annotations

from starlette.testclient import TestClient

import forger_context
from forger_desktop import ForgerDesktopRuntimeError
from testing.apps import minimal_fastapi_app


def test_forger_context_router_returns_desktop_locale(monkeypatch) -> None:
    monkeypatch.setattr(
        forger_context,
        "get_app_context",
        lambda: {"locale": "en", "rawLocale": "en-US"},
    )
    app = minimal_fastapi_app()
    app.include_router(forger_context.router)
    client = TestClient(app)

    response = client.get("/api/forger/context")

    assert response.status_code == 200
    assert response.json() == {
        "locale": "en",
        "rawLocale": "en-US",
        "source": "desktop",
    }


def test_forger_context_falls_back_when_desktop_is_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(
        forger_context,
        "get_app_context",
        lambda: (_ for _ in ()).throw(ForgerDesktopRuntimeError("offline")),
    )

    assert forger_context.runtime_context() == {
        "locale": "es",
        "rawLocale": None,
        "source": "fallback",
    }


def test_forger_context_normalizes_invalid_desktop_payloads(monkeypatch) -> None:
    monkeypatch.setattr(forger_context, "get_app_context", lambda: "bad")
    assert forger_context.runtime_context()["source"] == "fallback"

    monkeypatch.setattr(
        forger_context,
        "get_app_context",
        lambda: {"locale": "fr-CA", "rawLocale": ""},
    )
    assert forger_context.runtime_context() == {
        "locale": "es",
        "rawLocale": None,
        "source": "desktop",
    }

    monkeypatch.setattr(
        forger_context,
        "get_app_context",
        lambda: {"rawLocale": "en-GB"},
    )
    assert forger_context.runtime_context() == {
        "locale": "en",
        "rawLocale": "en-GB",
        "source": "desktop",
    }
