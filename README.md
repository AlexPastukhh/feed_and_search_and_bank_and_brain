# feed_and_search_and_bank_and_brain

Personal information ingestion and research platform. Project name is retained
for the GitHub repository; the Python package is named `info_hub`.

## Current status

**Second functional slice — content extraction and search**. RSS sources
are ingested and saved in PostgreSQL. The application now has indexed
ContentChunks, full-text search and an on-demand open-HTML article extractor.

**File/API connectors, LLM and research workflows are not implemented yet.**
Feed content stays marked partial/metadata_only unless an accessible article
is successfully extracted from its public URL.

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

## First RSS end-to-end test

Follow [the RSS test walkthrough](docs/RSS-FIRST-SLICE.md) to create a
Source and Subscription, enqueue a sync and inspect the saved articles.
Then follow [content/search instructions](docs/CONTENT-SEARCH.md) to
search archived materials and extract a public article.

Useful endpoints:
- `POST /sources` and `GET /sources`
- `POST /sources/{id}/subscriptions` and `GET /subscriptions`
- `POST /subscriptions/{id}/sync` and `GET /runs/{id}`
- `GET /resources` and `GET /resources/{id}`
- `GET /search?q=...` and `POST /resources/{id}/extract`
- `GET /health/live` and `GET /health/ready`

All source-management endpoints are currently single-user/local-only; they
must not be published on an unauthenticated internet-facing interface.

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

Next V1 slices add file/API connectors, AI Q&A and evidence-backed
research runs. Full-text fetching is on-demand in the current slice.
