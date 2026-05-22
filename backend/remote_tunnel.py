"""Reusable remote tunnel guards for vite-fastapi-sqlite apps.

The encrypted RPC endpoint is owned by Forger Desktop. App backends still need a
small guard because Desktop forwards decrypted requests to the regular FastAPI
routes and marks them as remote tunnel traffic.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp

REMOTE_TUNNEL_HEADER = "x-forger-remote-tunnel"
REMOTE_SESSION_HEADER = "x-forger-remote-session-id"

DEFAULT_BLOCKED_PREFIXES = (
    "/mcp",
    "/__forger_internal",
    "/__forger_remote_rpc",
)


@dataclass(frozen=True)
class RemoteTunnelConfig:
    blocked_prefixes: tuple[str, ...] = DEFAULT_BLOCKED_PREFIXES


class RemoteTunnelGuardMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app: ASGIApp,
        *,
        config: RemoteTunnelConfig | None = None,
    ) -> None:
        super().__init__(app)
        self.config = config or RemoteTunnelConfig()

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        if is_remote_tunnel_request(request) and path_is_blocked(
            request.url.path,
            self.config.blocked_prefixes,
        ):
            return JSONResponse(
                {"detail": "This action is not available from a remote tunnel."},
                status_code=403,
            )
        return await call_next(request)


def is_remote_tunnel_request(request: Request) -> bool:
    return request.headers.get(REMOTE_TUNNEL_HEADER, "").lower() == "true"


def remote_session_id(request: Request) -> str | None:
    value = request.headers.get(REMOTE_SESSION_HEADER, "").strip()
    return value or None


def path_is_blocked(
    path: str,
    blocked_prefixes: Iterable[str] = DEFAULT_BLOCKED_PREFIXES,
) -> bool:
    normalized = path.lower()
    if ".." in normalized:
        return True
    return any(normalized.startswith(prefix.lower()) for prefix in blocked_prefixes)


def remote_tunnel_headers(session_id: str) -> dict[str, str]:
    return {
        REMOTE_TUNNEL_HEADER: "true",
        REMOTE_SESSION_HEADER: session_id,
    }
