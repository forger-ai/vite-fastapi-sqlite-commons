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
  forger_desktop.py — Signed HTTP client for Desktop agent threads and tasks
  desktop_events.py — Signed websocket client for Desktop agent events
  realtime.py       — Generic FastAPI channel hub and websocket router
frontend/
  Dockerfile        — Node/Vite image
  client.ts         — Axios API client
docker-compose.base.yml  — Base service definitions (extends)
```

## Usage

```bash
# Add to an app repo
git submodule add git@github.com:forger-ai/vite-fastapi-sqlite-commons.git commons

# Update to latest
git submodule update --remote commons
git add commons && git commit -m "bump commons"
```
