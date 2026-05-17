from __future__ import annotations

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware


def minimal_fastapi_app(
    *,
    health_router: APIRouter | None = None,
    realtime_router: APIRouter | None = None,
    cors_origins: list[str] | None = None,
) -> FastAPI:
    app = FastAPI()
    if cors_origins is not None:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    if health_router is not None:
        app.include_router(health_router)
    if realtime_router is not None:
        app.include_router(realtime_router)
    return app

