from __future__ import annotations

import importlib
import sys
import types
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType


def reload_module(module_name: str) -> ModuleType:
    sys.modules.pop(module_name, None)
    return importlib.import_module(module_name)


def install_app_database_alias(database_module: ModuleType) -> None:
    app_module = types.ModuleType("app")
    app_module.database = database_module  # type: ignore[attr-defined]
    sys.modules["app"] = app_module
    sys.modules["app.database"] = database_module


def reload_health_module(database_module: ModuleType) -> ModuleType:
    install_app_database_alias(database_module)
    return reload_module("health")


@contextmanager
def temp_sqlite_database(
    monkeypatch,
    tmp_path: Path,
    *,
    filename: str = "app.sqlite",
) -> Iterator[tuple[ModuleType, Path]]:
    db_path = tmp_path / filename
    db_path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    module = reload_module("database")
    try:
        yield module, db_path
    finally:
        for name in ("health", "app.database", "app", "database"):
            sys.modules.pop(name, None)
