# feed_and_search_and_bank_and_brain

Personal information ingestion and research platform. Project name is retained
for the GitHub repository; the Python package is named `info_hub`.

## Current status

**Phase 0 — Runtime skeleton**. The repository contains a minimal FastAPI
service, a PostgreSQL-backed runtime configuration, an Alembic migration
baseline, a separate worker entrypoint, Docker Compose and a CI workflow
template (not enabled yet).

**No RSS import, search, LLM, research processing or worker job consumer has
been implemented yet.** Those are next feature slices.

## Architecture

The intended design is a modular monolith, with separate API and worker
processes. Sources and subscriptions are distinct; connector adapters
normalize external information into common resource/storage contracts.
AI is optional and source-independent.

See [Architecture](docs/ARCHITECTURE.md), [Phase 0 scope](docs/PHASE0.md),
and [Development workflow](docs/DEVELOPMENT.md).

## Local start (Docker Desktop / Docker Engine)

1. Copy `.env.example` to `.env`.
2. Change `POSTGRES_PASSWORD` in `.env` to a **local-only password**.
   If you use special URL characters in the password, percent-encode them
   in the composed `DATABASE_URL` (the initial configuration is URL-based).
3. Run `docker compose up --build -d`.
4. Run `docker compose ps` and `docker compose logs --tail=100 migrate api worker`.
5. Open `http://127.0.0.1:8000/health/live` and
   `http://127.0.0.1:8000/health/ready`.

Both endpoints should return `{"status":"ok"}` when the API and database
are working.

`docker compose down` stops the stack **without removing the database
volume**. Avoid `docker compose down -v` unless deleting data is intended.

## CI status

The workflow template is stored at `ci/workflow-template.yml`, but is not
active because the current Fortis GitHub PAT lacks permission to modify
`.github/workflows/`. Once an authorized account enables it, CI can run
migrations, readiness checks, lint and tests.

## Development

```bash
python -m pip install -e ".[dev]"
ruff check .
pytest -q
```

`DATABASE_URL` is required for running the application and migrations.
Docker Compose supplies it to app containers; CI supplies a test database URL.

## Git workflow

Primary development checkout is in persistent Docker storage:

`/workspace/repos/feed_and_search_and_bank_and_brain`

The independent Windows checkout belongs in:

`$HOME\Repos\feed_and_search_and_bank_and_brain`

Changes move **Docker → commit/push GitHub → Windows git pull --ff-only**.
There is no bind mount or automatic synchronization. Do not commit secrets,
`.env` or PostgreSQL volumes.

## Next

Phase 1: Source/Subscription and Resource contracts, then the first end-to-end
RSS flow. The broader V1 adds file/API connectors, search, AI Q&A and
evidence-backed research runs.
