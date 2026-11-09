# Разработка и эксплуатация Feedbrain

> Что реализовано — [PROJECT.md](PROJECT.md). Зачем это нужно и как связано с Actions — [ARCHITECTURE.md](ARCHITECTURE.md). Ограничения доступа — [SECURITY.md](SECURITY.md).

## Рабочие копии и Git

- Постоянный Docker checkout через Fortis Repo: `/workspace/repos/feed_and_search_and_bank_and_brain`.
- Независимый Windows checkout: `$HOME\Repos\feed_and_search_and_bank_and_brain`.
- GitHub: [AlexPastukhh/feed_and_search_and_bank_and_brain](https://github.com/AlexPastukhh/feed_and_search_and_bank_and_brain).

Изменения готовятся в **отдельном task worktree**, затем проходят проверки, авторизованную публикацию через **Fortis Gateway**, GitHub PR и слияние владельцем. Только **принятый merged `main` с проверенным SHA** передаётся на Windows через [Mirror workflow](https://github.com/AlexPastukhh/docke-windows-mirror/blob/main/docs/WORKFLOW.md). Ни Docker primary `main`, ни Windows-копию не использовать для обходного direct push или внедрения файлов из task-ветки. **Автоматической синхронизации checkout нет.** Не копировать `.env`, секреты, базы и volume через Git. См. [UC-CONT-002/003](https://github.com/AlexPastukhh/fortis-container/blob/main/docs/use-cases/delivery.md).

## Запуск на Windows / Docker Desktop

В PowerShell из Windows checkout:

```powershell
Set-Location "$HOME\Repos\feed_and_search_and_bank_and_brain"
git status --short --branch
git rev-parse HEAD  # Сверьте с принятой версией main, доставленной через Mirror.

if (-not (Test-Path .env)) { Copy-Item .env.example .env }
# Отредактируйте .env: задайте локальный POSTGRES_PASSWORD.
# Спецсимволы в DATABASE_URL требуют URL-encoding в строке подключения.

docker compose up --build -d
docker compose ps -a

# Дождитесь health: healthy — сразу после старта API может ещё запускаться.
curl.exe http://127.0.0.1:8000/health/live
curl.exe http://127.0.0.1:8000/health/ready
```

`compose.yaml` поднимает PostgreSQL, однократный `migrate` (Alembic), FastAPI `api`, **RSS worker** и **отдельный `action-worker`**. RSS worker планирует синхронизации Feedbrain; Action worker выполняет ручные и явно включённые запланированные Actions. Статус `migrate: Exited (0)` ожидаем.

Диагностика:

```powershell
docker compose logs --tail=100 api worker action-worker migrate
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

### Выбор инструмента и источника в Action

В V1 **инструмент, операция и источник указываются в самом Action YAML**. Для Feedbrain:

```yaml
workflow:
  schema: 1
  steps:
    - id: refresh_feed
      tool: feedbrain
      capability: information.sync
      with:
        source:
          type: subscription
          id: 1
```

`id: 1` — пример, а не обязательное значение: получить реальные ID можно через `GET /subscriptions`. Универсальный формат ядра — `tool` + `capability` + `with`. `source` допускает разные типы ресурсов для разных инструментов; **только Feedbrain adapter** требует `type: subscription` и целочисленный ID. Название `subscription` не встроено в Action Core.

**Привязка `ACTION_FEEDBRAIN_SOURCES_JSON` больше не нужна.** Старый параметр из `.env` можно удалить; его значение не используется. В доверенной конфигурации остаётся только адрес подключения Feedbrain (внутри Docker по умолчанию `http://api:8000`, необязательный `ACTION_FEEDBRAIN_URL`). Не помещайте в Action сетевые URL или ключи доступа к инструменту. Сохранение YAML ничего не запускает, запуск инициируется отдельным API.

Локальная проверка HTTP-контракта **без запуска реальной RSS-синхронизации** (не нужен PostgreSQL; тест поднимает собственный временный HTTP-сервер):

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -p test_action_broker.py -q
# Tests of ActionRun SQL models/worker require an isolated, migrated PostgreSQL.
```

### Проверка ручного запуска Action через новый worker

**Только после доставки и проверки нужного merged `main` через Mirror и `docker compose up --build -d`.** Этот шаг действительно инициирует синхронизацию RSS. Выберите **только подписку, которую намеренно разрешено синхронизировать**, желательно отдельную тестовую. Не проверять на чужих/дорогих источниках; не запускать тестовые скрипты на постоянной БД с `RUN_DB_INTEGRATION_TESTS=1`.

1. Посмотрите реальные подписки: `Invoke-RestMethod http://127.0.0.1:8000/subscriptions`. Выберите ID тестовой/разрешённой подписки.
2. В `examples/actions/rss_sync.yaml` замените `with.source.id` на этот ID. **Не добавляйте сопоставления в `.env`**: ID задаётся в YAML Action.
3. Проверьте `docker compose ps -a`: миграция `20261104_0005` должна завершиться успешно, `api` — healthy, `worker` и `action-worker` — запущены. При проблемах: `docker compose logs --tail=100 api action-worker worker migrate`.
4. Создайте **новый тестовый Action** из обновлённого YAML (пример в разделе «Проверка Action Registry/API» ниже) и используйте его ID. Ранее созданный Action #1 v1/v2 использует старое `with.source: ai_articles` и не исполняется в новом формате: для него можно отдельно опубликовать v3, не меняя v1/v2.

PowerShell (после выбора конкретного ID Action):

```powershell
$base = "http://127.0.0.1:8000"
$actionId = 1  # Замените на ID нового Action с актуальным форматом source!
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

**Проверяемые отказы:** неизвестный `tool`, неподдерживаемый `source.type` или Action без Workflow дают `409` и **не создают Run**; повторный запуск одного Action, пока предыдущий `queued/running`, тоже даёт `409`. Worker **не повторяет** неоднозначный внешний вызов после аварии: зависшее более двух часов выполнение помечается `interrupted`. Запуск с изменённой версией создаёт новый Run, не переписывает старый.

**Ограничения:** Scheduler добавлен в код, но требует отдельного явного включения `PUT /actions/{id}/schedule`; `schedule` в YAML остаётся только декларацией. HTTP API пока без auth: не давайте недоверенным клиентам возможности включать повторяющиеся действия или запускать подписки.

Интеграционный набор `tests/test_action_run_integration.py` работает с мигрированной PostgreSQL и имитированным внешним HTTP-ответом. Запускать его можно **только** в отдельной одноразовой тестовой базе с `RUN_DB_INTEGRATION_TESTS=1`, а не на постоянном Feedbrain volume.

### Проверка Action Scheduler V1 после обновления Windows Docker

Это **повторяемый сценарий проверки Scheduler**, а не отдельный отчёт о его готовности (результаты — в [PROJECT.md](PROJECT.md)). После обновления убедитесь, что `migrate` завершился `Exited (0)`, `api` — healthy и `action-worker` — работает.

1. Для **тестовой** подписки Feedbrain выберите Action с подходящими `tool`, `capability` и `source`. Помните, что у подписки может быть собственное RSS-расписание. Не включайте короткий Action-интервал для нагруженного источника без необходимости.
2. Прочитайте состояние расписания: `GET /actions/{id}/schedule` вернёт `enabled: false`, если оно ещё не настроено. **Само поле `schedule.every_minutes` в YAML ничего не включает.**
3. Включите расписание явно через API. Для проверки можно временно поставить интервал **2 минуты**, но это действительно будет **повторно запускать Feedbrain**:

```powershell
$base = "http://127.0.0.1:8000"
$actionId = 1 # Замените на ID выбранного тестового Action с поддерживаемым Workflow
Invoke-RestMethod -Uri "$base/actions/$actionId/schedule"

$enable = @{ enabled = $true; every_minutes = 2 } | ConvertTo-Json
Invoke-RestMethod -Method Put -Uri "$base/actions/$actionId/schedule" `
    -ContentType "application/json" -Body $enable

# next_run_at: не ранее чем через 2 минуты после активации
Invoke-RestMethod -Uri "$base/actions/$actionId/schedule"
Invoke-RestMethod -Uri "$base/actions/$actionId/runs"
```

4. **Не запускайте Action вручную для этого теста.** Проверяйте `GET /actions/{id}/runs` после каждого интервала. У двух новых Runs должно быть `initiated_by: "schedule"`, разные Run ID, конечный статус и StepRun/ActionResult с реальным `feedbrain:ingestion_run:{id}`.
5. Если Run всё ещё `queued/running` к следующему интервалу, Scheduler **не создаёт дубликат**, а пишет `last_skip_reason: active_run`; после пропусков/выключенного worker **не воспроизводит весь backlog**. `next_run_at`, `last_enqueued_at` и `last_skipped_at` видны через `GET /actions/{id}/schedule`.
6. Для проверки **сохранения расписания после перезапуска** используйте [готовый PowerShell-скрипт](../scripts/verify_action_scheduler_restart.ps1). Он проверяет начальное состояние, включает тестовый интервал в 1 минуту, перезапускает **только** `action-worker`, проверяет неизменность `next_run_at`, ожидает **новый** `ActionRun` с `initiated_by: schedule` и завершением `completed`. В `finally` он выключает расписание. **Не выполняйте сначала блок из пункта 3:** скрипт сам включает расписание и откажется работать, если оно уже активно.

```powershell
Set-Location "$HOME\Repos\feed_and_search_and_bank_and_brain"
git rev-parse HEAD  # До запуска убедитесь, что Mirror доставил нужный merged main.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify_action_scheduler_restart.ps1
```

Параметр `-ActionId 1` можно передать при необходимости; по умолчанию используется Action #1, который обращается к реальному Feedbrain. **Скрипт выполняет настоящую синхронизацию источника.** Его нужно запускать только после проверки, что API доступен и Action не выполняется. При неудаче отключения расписания скрипт выдаст предупреждение: после восстановления API убедитесь через `GET /actions/{id}/schedule`, что `enabled: false`; при необходимости отключите расписание вручную.

Предыдущий пример с `@(Invoke-RestMethod .../runs)` был некорректен для Windows PowerShell: HTTP JSON-массив мог рассматриваться как **один вложенный элемент** и создавать составной ID вида `"8 5 4 3 2 1"`. В исправленном сценарии каждую запись перебирает `foreach`, а перед вызовом `GET /action-runs/{id}` ID преобразуется к целому числу.

При выключении **новые** Runs не создаются, но уже запущенный Run не прерывается. `PUT` с `{"enabled":true}` без `every_minutes` использует ранее сохранённый интервал либо `schedule.every_minutes` из текущей версии YAML. Все поля расписания живут **отдельно от неизменяемых ActionVersion**. Новый Scheduled Run использует **текущую** версию Action на момент постановки в очередь.

Тесты SQL/API/worker: `tests/test_action_schedule_integration.py` (и `tests/test_action_run_integration.py`) **только на отдельной одноразовой мигрированной PostgreSQL** с `RUN_DB_INTEGRATION_TESTS=1`; **не запускать** на постоянном Feedbrain volume. Базовые расчёты интервалов доступны без БД: `PYTHONPATH=src python3 -m unittest discover -s tests -p test_action_schedule_time.py -q`.

### Проверка Action Registry/API после обновления Docker

Этот сценарий **создаёт тестовый Action в текущей базе**; его можно выполнять в локальном доверенном окружении, но **не** на посторонней/рабочей базе без согласования. Сначала подтвердите доставку нужного merged `main` через Mirror и выполните `docker compose up --build -d` по инструкции выше. Проверьте, что контейнер `migrate` завершился с кодом **0** и применил текущую ревизию `20261104_0006` (включая `0004` Registry и `0005` ActionRun).

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
$action.current_version.schedule_active # False, пока расписание явно не включено
Invoke-RestMethod -Method Get -Uri "$base/actions/$($action.id)"

$changed = $yaml.Replace("Синхронизируй", "Повторно синхронизируй")
$edit = @{ definition_yaml = $changed; expected_version = 1 } | ConvertTo-Json -Depth 5
$version2 = Invoke-RestMethod -Method Post -Uri "$base/actions/$($action.id)/versions" `
    -ContentType "application/json; charset=utf-8" -Body ($utf8.GetBytes($edit))
$version2.current_version_number      # 2
Invoke-RestMethod -Method Get -Uri "$base/actions/$($action.id)/versions"
Invoke-RestMethod -Method Get -Uri "$base/actions/$($action.id)/versions/1"
```

Ожидается: **201** при создании/публикации; v1 и v2 доступны независимо, старый YAML не изменён; повторная публикация с `expected_version: 1` вернёт **409**. При повреждённом YAML — **422**. Создание Action/версии **само по себе** не инициирует Feedbrain и не включает расписание.

После изменения конфигурации Windows Docker или сетевого соединения повторно проверьте доступ к API из Fortis Repo через `http://host.docker.internal:8000`: наличие маршрутов в исходниках само по себе не гарантирует доступность по сети.

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

Есть шаблон `ci/workflow-template.yml`, но рабочий workflow в `.github/workflows/` **не установлен**. CI/CD отложен до функциональных проверок ([backlog](BACKLOG-IMPROVEMENTS.md)). Если его включать, изменение файла workflow должно проходить через авторизованный **Fortis Gateway** с необходимыми правами GitHub на workflow-файлы и подтверждением владельца, а не через старый PAT/credential helper. Наличие шаблона не доказывает запуск CI. Секреты и PAT не добавлять в репозиторий.
