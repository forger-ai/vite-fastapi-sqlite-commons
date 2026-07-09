# AGENTS

## Source of Truth

This repo contains the shared files for the `vite-fastapi-sqlite` stack.

`vite-fastapi-sqlite` is the currently available Forger app stack. Apps in this stack combine a Python/FastAPI backend, local SQLite database, Vite + React frontend, and UI with Tailwind CSS, shadcn/ui copied components, and Radix primitives.

This repo does not contain a final app. It contains common infrastructure that stack apps consume as the `commons/` submodule or as a published copy inside catalog structures.

## Role of Commons

Commons exists to avoid duplicating common technical pieces across apps in the same stack.

Files in this repo must be generic, reusable, and free of app-specific business logic.

Belongs in commons:

- base backend Dockerfile for Python/FastAPI apps with `uv`;
- base frontend Dockerfile for Vite/React apps;
- SQLModel/SQLite database helper;
- shared health check endpoint;
- shared CORS helper;
- shared Desktop runtime HTTP and event helpers;
- shared Desktop audio bridge helpers;
- shared backend websocket proxy helper for live transcript sessions;
- shared FastAPI websocket channel hub;
- shared frontend HTTP client;
- base Docker Compose definitions extended by apps.

Does not belong in commons:

- business models for a specific app;
- business routes;
- domain services;
- specific screens;
- product copy;
- categories, seeds, or app data;
- app-specific skills;
- app-specific operational scripts;
- visual decisions that depend on a concrete product.

## Current Contents

```text
backend/
  Dockerfile        Backend base image with Python and uv
  database.py       SQLModel engine, init_db, and sessions
  health.py         GET /health router with database validation
  cors.py           CORS_ORIGINS reader from environment
  forger_desktop.py Signed HTTP client for the Forger Desktop runtime bridge and folder-grant token helpers
  audio_runtime.py  Helpers for live audio transcript WebSocket proxying
  desktop_events.py Signed websocket client for Desktop agent events
  realtime.py       Generic FastAPI channel hub and `/api/realtime/ws` router

frontend/
  Dockerfile        Frontend base image with Node/Vite
  client.ts         Typed HTTP client and error handling
  dateTimeSelectors.tsx Generic React date, date range, time, and time range selector primitives
  query.ts          TanStack Query provider, client defaults, and query key helpers
  realtime.ts       Realtime client for local WebSocket and encrypted remote tunnel sessions

docker-compose.base.yml
  Base backend/frontend services used by apps in the stack
```

## Backend Contract

`backend/database.py` defines:

- `DATABASE_URL` resolution from environment;
- fallback to a local SQLite database;
- shared SQLModel `engine`;
- SQLite foreign key activation;
- `init_db()` to create registered tables;
- `get_session()` as a FastAPI session dependency.

Apps must import their models before calling `init_db()`. The stack convention uses a local app file to register models before initializing the database.

`backend/health.py` defines:

- shared FastAPI router;
- `GET /health` endpoint;
- `SELECT 1` query against the database;
- simple response with `status: "ok"` and `database: "sqlite"`.

`backend/cors.py` defines:

- `allowed_origins()` helper;
- `CORS_ORIGINS` reader from environment;
- fallback to local Vite origins.

`backend/forger_desktop.py` defines:

- signed HTTP requests to the local Forger Desktop runtime bridge;
- helpers for signing short-lived folder grant tokens from the backend with Desktop-injected `FORGER_APP_GRANT_SECRET`;
- helpers for requesting, listing, and revoking Desktop folder grants;
- helpers for starting manifest agent threads, resuming manifest agent threads, steering active runs, inspecting threads/runs, canceling runs, and waiting for terminal run status;
- helpers for checking assistant task status, starting manifest prompt-template tasks, inspecting tasks, canceling tasks, and waiting for terminal task status;
- helpers for listing app-granted Forger Tools, calling granted Forger Tool actions, using the Forger Chrome Extension, and listing/status/calling app-granted Connections through the signed Desktop runtime bridge;
- helpers for listing audio devices, creating and closing live transcription sessions, transcribing saved audio files, synthesizing speech bytes, starting ephemeral playback, checking playback status, and canceling playback;
- the `FORGER_DESKTOP_RUNTIME_URL`, `FORGER_DESKTOP_RUNTIME_APP_ID`, `FORGER_DESKTOP_RUNTIME_SECRET`, and `FORGER_APP_GRANT_SECRET` environment contract.

`backend/audio_runtime.py` defines:

- a helper for building the live transcription WebSocket URL from a Desktop session descriptor;
- a FastAPI-compatible proxy helper for apps that want their backend to bridge browser audio to Desktop speech-to-text without exposing Desktop session details directly to frontend code.

`backend/desktop_events.py` defines:

- a signed websocket client for the local Forger Desktop runtime bridge;
- HMAC validation for every incoming Desktop event envelope;
- reconnect with backoff and in-memory event deduplication.

`backend/realtime.py` defines:

- `ChannelHub` for publishing app events to subscribed frontend sockets;
- `create_realtime_router()` for mounting a generic `/api/realtime/ws` endpoint;
- a simple subscribe/unsubscribe message protocol.

## Frontend Contract

`frontend/client.ts` defines:

- `API_BASE_URL` from `VITE_API_BASE_URL`;
- local fallback to `http://localhost:8000`;
- `ApiError` class;
- generic `request<T>()` helper;
- `apiWebSocketUrl()` for building backend WebSocket URLs while preserving runtime proxy prefixes such as `/__forger_api`;
- HTTP helpers `get`, `post`, `patch`, `put`, and `del`;
- default JSON handling;
- `FormData` support;
- network and HTTP error handling.

Apps in the stack must use this shared client for base HTTP calls. If an app needs domain functions, it must create local wrappers in its own `frontend/src/api/`.
Apps must not construct backend WebSocket URLs by replacing `URL.pathname` on `API_BASE_URL`, because installed apps receive prefixed runtime URLs.

`frontend/query.ts` defines:

- a conservative TanStack Query client for server state;
- a reusable provider for stack apps;
- shared query key helpers for app-local wrappers.

Commons declares TanStack Router as a stack frontend dependency, but routes stay app-local. Apps define their own route trees and visible navigation inside their frontend source.

`frontend/dateTimeSelectors.tsx` defines:

- generic React primitives for selecting one date, a date range, one time, or a time range;
- pure helpers for ISO date/time validation, calendar-month generation, range selection, and locale-aware labels;
- Tailwind token-based class names that apps can compose or override.

Apps can use these controls for common form input. App-specific business rules, presets, copy, and layout stay in the app.

`frontend/realtime.ts` defines:

- a shared client for `/api/realtime/ws`;
- local direct WebSocket connections;
- encrypted remote WebSocket frames through Forger Desktop remote tunnel sessions.

## Docker Compose Contract

`docker-compose.base.yml` defines base services:

- `backend`: builds with `commons/backend/Dockerfile` and runs FastAPI with uvicorn.
- `frontend`: builds with `commons/frontend/Dockerfile` and runs Vite.

Each app defines its own `docker-compose.yml` and extends or uses these services according to its local structure.

## When to Edit Commons

Edit commons when the change meets all these conditions:

- applies to more than one app in the stack;
- introduces no business rules;
- remains compatible with existing apps in the stack;
- reduces real duplication;
- keeps the contract simple for local apps;
- can be explained as stack/platform infrastructure, not as an app feature.

Appropriate examples:

- improve generic HTTP error handling;
- adjust base CORS configuration;
- fix SQLite initialization;
- improve the shared health check;
- update base Dockerfiles;
- add minimal shared helpers used by all apps in the stack.

## When Not to Edit Commons

Do not edit commons when the change belongs to a concrete app.

Examples that must stay in an app:

- importing financial movements;
- managing categories for a concrete app;
- adding domain endpoints;
- changing a product visual theme;
- creating a data-loading skill;
- defining app permissions;
- adjusting interface copy;
- modifying an app manifest.

If a need first appears in one app, implement it in that app. Move it to commons only when the behavior is clearly common to the stack and independent of domain.

## Relationship with Skeleton and Apps

`skeletons/vite-fastapi-sqlite` uses this repo as the stack shared base.

Stack apps use commons for shared infrastructure and keep their own logic inside each app repo.

If commons changes, apps that consume this repo must update their submodule reference or corresponding copy. That change is versioned inside each affected app repo.

## Agent Rules

- Read the app `AGENTS.md` before assuming a change belongs in commons.
- Keep commons free of specific product knowledge.
- Do not add heavy dependencies without a clear shared need.
- Do not change defaults that affect local data without reviewing impact on consuming apps.
- Do not break the `DATABASE_URL`, `CORS_ORIGINS`, or `VITE_API_BASE_URL` contract.
- Do not expose commons internals to the final user unless they ask about implementation.
- Describe commons changes as platform or stack improvements, not as visible app capabilities.

## Verification

After changing commons, verify at least one consuming app or the stack skeleton.

Relevant verifications include backend checks, frontend checks, and local execution through Docker Compose when the change affects Dockerfiles, mounts, or services.

Commands are internal agent tools. They must not be presented to the final user as normal usage steps.
