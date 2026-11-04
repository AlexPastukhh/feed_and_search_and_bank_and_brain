# Разработка и эксплуатация Feedbrain

> Что реализовано — [PROJECT.md](PROJECT.md). Зачем это нужно и как связано с Actions — [ARCHITECTURE.md](ARCHITECTURE.md). Ограничения доступа — [SECURITY.md](SECURITY.md).

## Рабочие копии и Git

- Постоянный Docker checkout через Fortis Repo: `/workspace/repos/feed_and_search_and_bank_and_brain`.
- Независимый Windows checkout: `$HOME\Repos\feed_and_search_and_bank_and_brain`.
- GitHub: [AlexPastukhh/feed_and_search_and_bank_and_brain](https://github.com/AlexPastukhh/feed_and_search_and_bank_and_brain).

Изменения выполняются в Fortis Repo checkout → тесты → commit/push в GitHub → в Windows `git pull --ff-only origin main`. **Автоматической синхронизации между checkout нет.** Не копировать `.env`, секреты, базы и volume через Git.

## Запуск на Windows / Docker Desktop

В PowerShell из Windows checkout:

```powershell
Set-Location "$HOME\Repos\feed_and_search_and_bank_and_brain"
git status --short --branch
git pull --ff-only origin main

if (-not (Test-Path .env)) { Copy-Item .env.example .env }
# Отредактируйте .env: задайте локальный POSTGRES_PASSWORD.
# Спецсимволы в DATABASE_URL требуют URL-encoding в строке подключения.

docker compose up --build -d
docker compose ps -a

# Дождитесь health: healthy — сразу после старта API может ещё запускаться.
curl.exe http://127.0.0.1:8000/health/live
curl.exe http://127.0.0.1:8000/health/ready
```

`compose.yaml` поднимает PostgreSQL, однократный `migrate` (Alembic), FastAPI `api` и **рабочий `worker`**. Worker обрабатывает очередь и планирует синхронизации RSS; статус `migrate: Exited (0)` ожидаем.

Диагностика:

```powershell
docker compose logs --tail=100 api worker migrate
docker compose ps -a
```

Остановка без удаления данных: `docker compose down`. Команда `docker compose down -v` удалит volume и приведёт к потере базы.

## Проверка функций

- [RSS-FIRST-SLICE.md](RSS-FIRST-SLICE.md): создание RSS-источника/подписки, ручной и фоновый sync, идемпотентность.
- [CONTENT-SEARCH.md](CONTENT-SEARCH.md): поиск по уже сохранённым публикациям и извлечение публичной HTML-статьи.

Проверить **только YAML-контракт Action V1** после установки зависимостей
(команда не сохраняет Action и не выполняет Workflow):

```bash
python -m info_hub.action_workflow examples/actions/rss_sync.yaml
```

### Конфигурация Action Broker и Action worker

Поддерживается одна capability — `information.sync` — через Feedbrain HTTP API. Логические источники из Workflow должны быть явно привязаны к уже существующим подпискам Feedbrain.

В `.env` Docker Compose (пример — в `.env.example`):

```dotenv
# Найдите ID в GET /subscriptions; значение ниже исключительно пример.
ACTION_FEEDBRAIN_SOURCES_JSON={"ai_articles":11}
# Внутри Docker Compose по умолчанию http://api:8000
# ACTION_FEEDBRAIN_URL=http://api:8000
```

Broker не принимает адреса, пути HTTP или subscription ID из Action YAML: `with.source` — только логический алиас. По умолчанию bindings **пустые**, поэтому вызовы по ненастроенным источникам отклоняются. Изменение `.env` требует пересоздания `api` и `action-worker`. Broker исполняется только по запросу Run или из очереди worker; сама конфигурация ничего не запускает.

Локальная проверка HTTP-контракта **без запуска реальной RSS-синхронизации** (не нужен PostgreSQL; тест поднимает собственный временный HTTP-сервер):

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -p test_action_broker.py -q
# Tests of ActionRun SQL models/worker require an isolated, migrated PostgreSQL.
```

### Проверка ручного запуска Action через новый worker

**Только после `git pull --ff-only origin main` и `docker compose up --build -d`.** Этот шаг действительно инициирует синхронизацию RSS. Выберите **только подписку, которую намеренно разрешено синхронизировать**, желательно отдельную тестовую. Не проверять на чужих/дорогих источниках; не запускать тестовые скрипты на постоянной БД с `RUN_DB_INTEGRATION_TESTS=1`.

1. Получите реальные подписки: `Invoke-RestMethod http://127.0.0.1:8000/subscriptions`. Найдите `id` подходящей подписки.
2. В локальном `.env` задайте, например, `ACTION_FEEDBRAIN_SOURCES_JSON={"ai_articles":11}`, **заменив 11 настоящим ID**. Это binding логического алиаса из `examples/actions/rss_sync.yaml` / сохранённого Action; без него API вернёт `409` до вызова Feedbrain. URL API внутри Docker по умолчанию — `http://api:8000`.
3. Пересоздайте контейнеры изменённой конфигурацией: `docker compose up --build -d`. Проверяйте `docker compose ps -a`: миграция `20261104_0005` должна успешно завершиться, `api` — healthy, `worker` и **`action-worker`** — запущены. Для ошибок: `docker compose logs --tail=100 api action-worker worker migrate`.
4. Используйте **уже созданный** Action #1, если у него `with.source: ai_articles`, или создайте отдельный Action по инструкции ниже.

PowerShell (после выбора конкретного ID Action):

```powershell
$base = "http://127.0.0.1:8000"
$actionId = 1  # Проверьте GET /actions/$actionId перед запуском!
Invoke-RestMethod -Uri "$base/actions/$actionId"

$run = Invoke-RestMethod -Method Post -Uri "$base/actions/$actionId/runs" `
    -ContentType "application/json" -Body "{}"
$run.id
$run.status # queued
do {
    Start-Sleep -Seconds 2
    $detail = Invoke-RestMethod -Uri "$base/action-runs/$($run.id)"
    Write-Host $detail.status
} while ($detail.status -in @("queued", "running"))
$detail | ConvertTo-Json -Depth 15
Invoke-RestMethod -Uri "$base/actions/$actionId/runs"
```

Ожидается: `POST` возвращает `202 queued`; отдельный Action worker берёт Run, вызывает Feedbrain `POST /subscriptions/{id}/sync` и ждёт конечного `IngestionRun`. В `GET /action-runs/{id}` будут зафиксированы версия Action, шаг, фактически использованный `feedbrain`, `feedbrain:ingestion_run:<id>`, статус, счётчики и итог. При ошибке — `failed` и `error_code`; `202` от Feedbrain **не равно** успешному завершению Action.

**Проверяемые отказы:** ненастроенный алиас или Action без Workflow дают `409` и **не создают Run**; повторный запуск одного Action, пока предыдущий `queued/running`, тоже даёт `409`. Worker **не повторяет** неоднозначный внешний вызов после аварии: зависшее более двух часов выполнение помечается `interrupted`. Запуск с изменённой версией создаёт новый Run, не переписывает старый.

**Ограничения:** автоматический Action Schedule пока не реализован; `schedule` в YAML остаётся только декларацией. HTTP API пока без auth, поэтому не открывайте его недоверенным клиентам и не назначайте избыточные bindings.

Интеграционный набор `tests/test_action_run_integration.py` работает с мигрированной PostgreSQL и имитированным внешним HTTP-ответом. Запускать его можно **только** в отдельной одноразовой тестовой базе с `RUN_DB_INTEGRATION_TESTS=1`, а не на постоянном Feedbrain volume.

### Проверка Action Registry/API после обновления Docker

Этот сценарий **создаёт тестовый Action в текущей базе**; его можно выполнять в локальном доверенном окружении, но **не** на посторонней/рабочей базе без согласования. Сначала выполните `git pull --ff-only origin main` и `docker compose up --build -d` по инструкции выше. Проверьте, что контейнер `migrate` завершился с кодом **0** и применил текущую ревизию `20261104_0005` (включая `0004` для Registry).

В Windows PowerShell:

```powershell
$base = "http://127.0.0.1:8000"
$yaml = Get-Content ".\examples\actions\rss_sync.yaml" -Raw -Encoding UTF8
$body = @{ definition_yaml = $yaml } | ConvertTo-Json -Depth 5
$utf8 = [System.Text.Encoding]::UTF8

$action = Invoke-RestMethod -Method Post -Uri "$base/actions" `
    -ContentType "application/json; charset=utf-8" -Body ($utf8.GetBytes($body))
$action.id
$action.current_version_number        # 1
$action.current_version.schedule_active # False: расписание пока НЕ работает
Invoke-RestMethod -Method Get -Uri "$base/actions/$($action.id)"

$changed = $yaml.Replace("Синхронизируй", "Повторно синхронизируй")
$edit = @{ definition_yaml = $changed; expected_version = 1 } | ConvertTo-Json -Depth 5
$version2 = Invoke-RestMethod -Method Post -Uri "$base/actions/$($action.id)/versions" `
    -ContentType "application/json; charset=utf-8" -Body ($utf8.GetBytes($edit))
$version2.current_version_number      # 2
Invoke-RestMethod -Method Get -Uri "$base/actions/$($action.id)/versions"
Invoke-RestMethod -Method Get -Uri "$base/actions/$($action.id)/versions/1"
```

Ожидается: **201** при создании/публикации; v1 и v2 доступны независимо, старый YAML не изменён; повторная публикация с `expected_version: 1` вернёт **409**. При повреждённом YAML — **422**. Вызова Feedbrain, `ActionRun` и активации расписания **пока нет**.

Доступ к новым маршрутам из ChatGPT через Fortis Repo следует проверить **отдельно, после обновления Windows-контейнеров** через уже существующий HTTP-доступ `http://host.docker.internal:8000`; сам факт наличия маршрутов в исходниках ещё не доказывает доступность по сети.

Интеграционный тест `tests/test_action_registry_integration.py` использует настоящую PostgreSQL, проверяет также запрет SQL-изменения старой версии. Запускайте его **только на отдельной одноразовой мигрированной базе** c `RUN_DB_INTEGRATION_TESTS=1`, никогда на постоянном Feedbrain volume.

HTTP API локально доступен по `http://127.0.0.1:8000`, интерактивная схема FastAPI — `/docs`, OpenAPI — `/openapi.json`. Из проверенного контейнера Fortis Repo на Docker Desktop API ранее был доступен по `http://host.docker.internal:8000`; это зависит от сети и не даёт полномочий на безопасный удалённый доступ. **У API пока нет авторизации.**

## Локальные Python-тесты

В среде с Python >= 3.11 и зависимостями:

```bash
python -m pip install -e ".[dev]"
ruff check .
pytest -q
```

Для PostgreSQL-интеграционных тестов нужен **отдельный disposable test database**. Никогда не устанавливайте `RUN_DB_INTEGRATION_TESTS=1` на постоянную рабочую базу: тесты создают записи.

В среде Fortis Repo сейчас нет установленных зависимостей приложения, `pip` и Docker Engine. Там доступны базовые проверки:

```bash
python3 -m compileall -q src alembic tests
PYTHONPATH=src python3 -m unittest discover -s tests -p test_feeds.py -q
PYTHONPATH=src python3 -m unittest discover -s tests -p test_connectors.py -q
PYTHONPATH=src python3 -m unittest discover -s tests -p test_content.py -q
PYTHONPATH=src python3 -m unittest discover -s tests -p test_action_workflow.py -q
PYTHONPATH=src python3 -m unittest discover -s tests -p test_action_broker.py -q
# Tests of ActionRun SQL models/worker require an isolated, migrated PostgreSQL.
python3 -m unittest discover -s tests -p test_structure.py -q
git diff --check
```

В Fortis Repo без PyYAML **тесты чтения YAML пропускаются**, но проверки структуры документа выполняются; для полной проверки нужен установленный PyYAML (или Python venv с ним). Такие проверки **не заменяют Docker end-to-end**.

## CI

Есть шаблон `ci/workflow-template.yml`, но рабочий workflow в `.github/workflows/` **не установлен**, поскольку текущие полномочия Fortis GitHub PAT не позволяют его публиковать. Для включения потребуется владелец/токен с правами на workflows. Секреты и PAT не добавлять в файлы репозитория.
