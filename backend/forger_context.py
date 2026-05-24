from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter

try:  # pragma: no cover - app package import path
    from app.forger_desktop import ForgerDesktopRuntimeError, get_app_context
except ModuleNotFoundError:  # pragma: no cover - commons test import path
    from forger_desktop import (  # pyright: ignore[reportMissingImports]
        ForgerDesktopRuntimeError,
        get_app_context,
    )

Locale = Literal["es", "en"]
ContextSource = Literal["desktop", "fallback"]

router = APIRouter(prefix="/api/forger", tags=["forger"])


def normalize_locale(value: object) -> Locale:
    normalized = str(value or "").strip().lower()
    return "en" if normalized == "en" or normalized.startswith("en-") else "es"


def fallback_context() -> dict[str, str | None]:
    return {"locale": "es", "rawLocale": None, "source": "fallback"}


def runtime_context() -> dict[str, str | None]:
    try:
        context = get_app_context()
    except ForgerDesktopRuntimeError:
        return fallback_context()
    if not isinstance(context, dict):
        return fallback_context()

    raw_locale = context.get("rawLocale")
    locale = normalize_locale(context.get("locale") or raw_locale)
    return {
        "locale": locale,
        "rawLocale": raw_locale if isinstance(raw_locale, str) and raw_locale else None,
        "source": "desktop",
    }


@router.get("/context")
def get_forger_context() -> dict[str, Any]:
    return runtime_context()
