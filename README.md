# vite-fastapi-sqlite-commons

Shared infrastructure for the `vite-fastapi-sqlite` stack.

Used as a git submodule inside each app repo under `commons/`.

## Contents

```
backend/
  Dockerfile        — Python/uv image
  database.py       — SQLAlchemy session factory
  health.py         — /health endpoint
  cors.py           — CORS middleware setup
  forger_desktop.py — Signed HTTP client for Desktop manifest agents, tasks, official tools, audio APIs, and folder grants
  audio_runtime.py  — Live transcription WebSocket URL and proxy helpers
  desktop_events.py — Signed websocket client for Desktop agent events
  realtime.py       — Generic FastAPI channel hub and websocket router
frontend/
  Dockerfile        — Node/Vite image
  client.ts         — Typed HTTP client and backend WebSocket URL helper
  query.ts          — TanStack Query defaults and provider
  realtime.ts       — Local and encrypted remote realtime client
docker-compose.base.yml  — Base service definitions (extends)
```

Use `apiWebSocketUrl()` for app-backend WebSockets. It preserves runtime path
prefixes such as `/__forger_api` that Forger Desktop injects for installed apps.

## Usage

```bash
# Add to an app repo
git submodule add git@github.com:forger-ai/vite-fastapi-sqlite-commons.git commons

# Update to latest
git submodule update --remote commons
git add commons && git commit -m "bump commons"
```
