# Phase 0 — Repository skeleton

> **Historical record only** of the initial scaffold (not a current product status).
> Later slices implemented RSS, a working worker, content extraction and FTS.
> For the current, authoritative status see [PROJECT.md](PROJECT.md);
> for the updated Action-centric design see [ARCHITECTURE.md](ARCHITECTURE.md).

## Delivered components
- Installable Python package and FastAPI application.
- `/health/live`: process liveness.
- `/health/ready`: actual database SELECT 1.
- SQLAlchemy declarative base.
- Alembic configured from DATABASE_URL, with an empty initial baseline.
- PostgreSQL 16 in Docker Compose, persistent volume and healthcheck.
- One-shot migration service gating API/worker startup.
- Separate worker entrypoint with graceful shutdown.
- Environment template and secret-excluding ignore rules.
- Unit/contract smoke tests and a GitHub Actions workflow template. The template
is not active until installed by credentials authorized for `.github/workflows/`.

## Not delivered **in Phase 0** (historical)
- Source/Subscription tables.
- Durable job table or worker consumer.
- RSS/API connectors.
- Importers, search and LLM.
- Research workflow and application UI.

## Verification levels
- Syntax/structure can be checked without installing dependencies.
- Application tests require the dependencies in `pyproject.toml`.
- Compose runtime requires a Docker Engine; Fortis Repo container has no Docker CLI.
- The prepared CI template would run migrations and tests against PostgreSQL,
but it cannot run automatically until activated.

## Original Phase 0 acceptance notes (historical)
- Sources committed and published to GitHub.
- Python syntax and stdlib structure tests pass in Fortis.
- CI workflow activated by an authorized account, then GitHub Actions results
  reviewed; this activation is currently blocked by PAT workflow permissions.
- Docker Compose startup and health endpoints verified separately on a machine with Docker.
