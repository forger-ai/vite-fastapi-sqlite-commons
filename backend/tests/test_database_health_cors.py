from __future__ import annotations

from sqlalchemy import text
from starlette.testclient import TestClient

import cors
from testing.apps import minimal_fastapi_app
from testing.database import reload_health_module, reload_module, temp_sqlite_database


def test_database_uses_default_sqlite_url_when_env_is_blank(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "  ")
    database = reload_module("database")

    assert database.DATABASE_URL.startswith("sqlite:///")
    assert database.DATABASE_URL.endswith("/data/forger-app.sqlite")


def test_database_uses_non_sqlite_engine_without_sqlite_connect_args(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_create_engine(url: str, *, echo: bool, connect_args: dict[str, object]):
        captured.update(url=url, echo=echo, connect_args=connect_args)
        return object()

    import sqlmodel

    monkeypatch.setenv("DATABASE_URL", "postgresql://example.test/app")
    monkeypatch.setattr(sqlmodel, "create_engine", fake_create_engine)

    database = reload_module("database")
    created_with: list[object] = []
    monkeypatch.setattr(
        database.SQLModel.metadata,
        "create_all",
        lambda engine: created_with.append(engine),
    )
    database.init_db()

    assert database.DATABASE_URL == "postgresql://example.test/app"
    assert captured == {
        "url": "postgresql://example.test/app",
        "echo": False,
        "connect_args": {},
    }
    assert created_with == [database.engine]


def test_temp_sqlite_database_initializes_parent_and_enables_foreign_keys(
    monkeypatch,
    tmp_path,
) -> None:
    nested_db = tmp_path / "nested" / "forger-app.sqlite"

    with temp_sqlite_database(
        monkeypatch,
        nested_db.parent,
        filename=nested_db.name,
    ) as (database, db_path):
        assert db_path == nested_db
        assert db_path.parent.exists()

        monkeypatch.setattr(database, "_DEFAULT_DB_PATH", db_path)
        database.init_db()

        session_generator = database.get_session()
        session = next(session_generator)
        try:
            enabled = session.execute(text("PRAGMA foreign_keys")).scalar_one()
            assert enabled == 1
        finally:
            try:
                next(session_generator)
            except StopIteration:
                pass


def test_health_router_uses_injected_app_database_and_cors(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv(
        "CORS_ORIGINS",
        "https://app.example.test, , http://127.0.0.1:5173 ",
    )

    with temp_sqlite_database(monkeypatch, tmp_path) as (database, _db_path):
        health = reload_health_module(database)
        app = minimal_fastapi_app(
            health_router=health.router,
            cors_origins=cors.allowed_origins(),
        )
        client = TestClient(app)

        response = client.get("/health")
        preflight = client.options(
            "/health",
            headers={
                "origin": "https://app.example.test",
                "access-control-request-method": "GET",
            },
        )

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "sqlite"}
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == (
        "https://app.example.test"
    )


def test_allowed_origins_falls_back_to_local_vite(monkeypatch) -> None:
    monkeypatch.delenv("CORS_ORIGINS", raising=False)

    assert cors.allowed_origins() == [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
