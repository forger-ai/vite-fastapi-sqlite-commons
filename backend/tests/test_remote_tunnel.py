from fastapi import FastAPI, Request
from starlette.testclient import TestClient

from remote_tunnel import (
    REMOTE_SESSION_HEADER,
    REMOTE_TUNNEL_HEADER,
    RemoteTunnelConfig,
    RemoteTunnelGuardMiddleware,
    is_remote_tunnel_request,
    path_is_blocked,
    remote_session_id,
    remote_tunnel_headers,
)


def test_remote_tunnel_guard_blocks_remote_internal_paths() -> None:
    app = FastAPI()
    app.add_middleware(RemoteTunnelGuardMiddleware)

    @app.get("/mcp/tools")
    def blocked_route() -> dict[str, bool]:
        return {"blocked": False}

    @app.get("/api/items")
    def allowed_route() -> dict[str, bool]:
        return {"allowed": True}

    client = TestClient(app)

    blocked = client.get("/mcp/tools", headers={REMOTE_TUNNEL_HEADER: "true"})
    allowed = client.get("/api/items", headers={REMOTE_TUNNEL_HEADER: "true"})
    local = client.get("/mcp/tools")

    assert blocked.status_code == 403
    assert blocked.json() == {"detail": "This action is not available from a remote tunnel."}
    assert allowed.json() == {"allowed": True}
    assert local.json() == {"blocked": False}


def test_remote_tunnel_guard_accepts_custom_blocked_prefixes() -> None:
    app = FastAPI()
    app.add_middleware(
        RemoteTunnelGuardMiddleware,
        config=RemoteTunnelConfig(blocked_prefixes=("/api/private",)),
    )

    @app.get("/api/private/reports")
    def private_route() -> dict[str, bool]:
        return {"private": True}

    response = TestClient(app).get("/api/private/reports", headers={REMOTE_TUNNEL_HEADER: "true"})

    assert response.status_code == 403


def test_remote_tunnel_helpers_read_headers_and_block_paths() -> None:
    app = FastAPI()

    @app.get("/inspect")
    def inspect(request: Request) -> dict[str, str | bool | None]:
        return {
            "remote": is_remote_tunnel_request(request),
            "session_id": remote_session_id(request),
        }

    headers = remote_tunnel_headers("session-1")
    response = TestClient(app).get("/inspect", headers=headers)

    assert headers == {
        REMOTE_TUNNEL_HEADER: "true",
        REMOTE_SESSION_HEADER: "session-1",
    }
    assert response.json() == {"remote": True, "session_id": "session-1"}
    assert path_is_blocked("/__forger_internal/state")
    assert path_is_blocked("/api/../secret")
    assert not path_is_blocked("/api/items")
