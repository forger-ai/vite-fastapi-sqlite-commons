"""SQLite engine and session helpers shared across all vite-fastapi-sqlite apps."""

from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path

from sqlalchemy.event import listens_for
from sqlmodel import Session, SQLModel, create_engine

_DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "forger-app.sqlite"


def _resolve_database_url() -> str:
    raw = os.getenv("DATABASE_URL", "")
    return raw.strip() if raw.strip() else f"sqlite:///{_DEFAULT_DB_PATH}"


DATABASE_URL = _resolve_database_url()

engine = create_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)

if DATABASE_URL.startswith("sqlite"):
    @listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys = ON")
        finally:
            cursor.close()


def init_db() -> None:
    """Create all tables defined in SQLModel.metadata.

    Apps must import their models before calling this so SQLModel can
    register them. The canonical place to do that is app/database_ext.py.
    """
    if DATABASE_URL.startswith("sqlite"):
        _DEFAULT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    SQLModel.metadata.create_all(engine)


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
