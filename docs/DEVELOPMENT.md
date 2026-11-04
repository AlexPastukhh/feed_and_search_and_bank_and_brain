# Development workflow

## Docker source checkout
`/workspace/repos/feed_and_search_and_bank_and_brain`

The alias `/workspace/repo/Repos/feed_and_search_and_bank_and_brain`
currently refers to the same persistent Docker files.

## GitHub
`https://github.com/AlexPastukhh/feed_and_search_and_bank_and_brain`

## Windows checkout
`$HOME\Repos\feed_and_search_and_bank_and_brain` — independent clone,
not a bind mount. GitHub is the synchronization boundary.

## Change propagation
1. Work and review changes in Docker checkout.
2. Run tests and inspect `git diff --check`.
3. Commit and push only the intended repository files.
4. On Windows: `git pull --ff-only origin main`.
5. Run Windows-specific checks only when needed.

Never copy credentials, database volumes or local `.env` through Git.

## Local Windows with Docker Desktop
From PowerShell in the Windows clone:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
# Edit .env: set a local-only POSTGRES_PASSWORD before starting.
docker compose up --build -d
docker compose ps
Invoke-RestMethod http://127.0.0.1:8000/health/live
Invoke-RestMethod http://127.0.0.1:8000/health/ready
```

The compose stack creates the database, runs Alembic migrations, then launches
the API and an **idle Phase-0 worker**. Worker job processing is NOT implemented yet.

To view logs: `docker compose logs --tail=100 api worker migrate`.

To stop without deleting stored data: `docker compose down`.
Do not use `down -v` unless intentionally deleting the local database.

## Python dev environment (optional)
```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[dev]"
ruff check .
pytest -q
```

The app requires DATABASE_URL. Docker Compose supplies it to containers.

## CI workflow activation

The workflow template is `ci/workflow-template.yml`. Activating it requires
placing it at `.github/workflows/ci.yml` using GitHub credentials with
workflow-management permission. The Fortis PAT currently cannot make this
change. Do not embed or transfer PATs into repository files.

## First RSS vertical slice

See [RSS-FIRST-SLICE.md](RSS-FIRST-SLICE.md) for step-by-step PowerShell API
requests and expected sync status. The worker is no longer idle.

Do not set `RUN_DB_INTEGRATION_TESTS=1` against your persistent database.
The integration test creates records and is reserved for disposable CI DBs.
