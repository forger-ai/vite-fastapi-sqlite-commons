# AGENTS

## Source of Truth

This repo contains the shared files for the `vite-fastapi-sqlite` stack.

`vite-fastapi-sqlite` is the currently available Forger app stack. Apps in this stack combine a Python/FastAPI backend, local SQLite database, Vite + React frontend, and UI with MUI / Material Design.

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

frontend/
  Dockerfile        Frontend base image with Node/Vite
  client.ts         Typed HTTP client and error handling

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

## Frontend Contract

`frontend/client.ts` defines:

- `API_BASE_URL` from `VITE_API_BASE_URL`;
- local fallback to `http://localhost:8000`;
- `ApiError` class;
- generic `request<T>()` helper;
- HTTP helpers `get`, `post`, `patch`, `put`, and `del`;
- default JSON handling;
- `FormData` support;
- network and HTTP error handling.

Apps in the stack must use this shared client for base HTTP calls. If an app needs domain functions, it must create local wrappers in its own `frontend/src/api/`.

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
- managing Finance OS categories;
- adding domain endpoints;
- changing a product visual theme;
- creating a data-loading skill;
- defining app permissions;
- adjusting interface copy;
- modifying an app manifest.

If a need first appears in one app, implement it in that app. Move it to commons only when the behavior is clearly common to the stack and independent of domain.

## Relationship with Skeleton and Apps

`skeletons/vite-fastapi-sqlite` uses this repo as the stack shared base.

Stack apps, such as `apps/finance-os`, use commons for shared infrastructure and keep their own logic inside the app repo.

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

After changing commons, verify at least one consuming app in the stack.

For `finance-os`, relevant verifications are:

- backend: `scripts/verify.py`;
- frontend: `npm run verify`;
- local execution via Docker Compose when the change affects Dockerfiles, mounts, or services.

Commands are internal agent tools. They must not be presented to the final user as normal usage steps.
