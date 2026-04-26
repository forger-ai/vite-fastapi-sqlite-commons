"""SQLModel database setup shared across all vite-fastapi-sqlite apps.

Apps copy this file via ``scripts/build_setup`` and may extend it,
but should not modify the core engine/session wiring.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

# Apps override this via the DATABASE_URL env var (set by Forger at runtime).
# The fallback path is relative to this file so it works in both dev and
# packaged (zip-extracted) layouts.
_DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "app.sqlite"


def _resolve_database_url() -> str:
    raw = os.getenv("DATABASE_URL")
    if raw and raw.strip():
        return raw.strip()
    return f"sqlite:///{_DEFAULT_DB_PATH}"


DATABASE_URL = _resolve_database_url()

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
    echo=False,
)


def init_db() -> None:
    if DATABASE_URL.startswith("sqlite"):
        _DEFAULT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    SQLModel.metadata.create_all(engine)


def get_session() -> Session:
    return Session(engine)
