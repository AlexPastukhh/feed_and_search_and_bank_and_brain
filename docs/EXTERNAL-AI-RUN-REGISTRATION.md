# Регистрация External AI ActionRun — реализация и проверка

**Статус на 2026-11-11:** source candidate в отдельной task-ветке.
Миграция и HTTP API **не развёрнуты на рабочем Windows Docker/Core**;
внешние ручные выполнения №3/№4 ещё не появились в живом ActionRun.
Семантика — [EXECUTION-MODES](EXECUTION-MODES.md), предметный результат —
[ACTION-RESULTS-LIFECYCLE](ACTION-RESULTS-LIFECYCLE.md). Открытая работа —
[backlog](BACKLOG-IMPROVEMENTS.md), реальный deployed status —
[PROJECT](PROJECT.md).

## Контракт исходного API

`POST /actions/{action_id}/external-runs` **регистрирует факт уже
завершённой внешней AI-работы**, не пробуждает AI, не вызывает Broker
и не создаёт программные queued/running/StepRun. Внешний AI может быть
ChatGPT через Fortis Repo или другой авторизованный исполнитель.
`research`/`monitoring` остаются семантическими категориями ActionVersion.

Требуются `version_number`, `external_run_key`, `initiated_by`,
`status`, `summary`, `storage_status`. Допускаются только терминальные
`completed`, `failed`, `interrupted`; необязательны известные
`started_at`, `finished_at` с timezone, `error_code`, максимум восемь
`output_refs` (HTTPS URI без userinfo/query/fragment). Время не
выдумывать. Исполнитель привязывается к авторизованному credential,
а не к полю из тела запроса. Пример **только формата**, не реального Run:

```json
{
  "version_number": 3,
  "external_run_key": "example-research-001",
  "initiated_by": "user",
  "status": "completed",
  "summary": "Research result recorded after external readback",
  "output_refs": ["https://example.org/reports/research-001.json"],
  "storage_status": "reported_saved"
}
```

Первый успешный запрос даёт `201`, точный идемпотентный повтор —
`200` с тем же Run. Попытка подменить данные под тем же ключом — `409`;
неизвестные Action/версия — `404`, неверные поля — `422`.
Существующие `GET /actions/{id}/runs` и `GET /action-runs/{run_id}`
показывают единый ActionRun и ActionResult. Старый
`POST /actions/{id}/runs` продолжает ставить программный Workflow в Broker.

`storage_status` допускает `reported_saved`, `reported_not_saved`,
`unknown`. Это **заявление исполнителя**: Core не скачивает URL и не
доказывает сохранение; `ActionResult.details.storage_evidence` имеет
значение `executor_reported`. Фактическое чтение внешнего результата
нужно подтверждать отдельно. Предложения Research не применяются
автоматически; Monitoring dataset не создаётся этим API.

## Безопасность

Маршрут записи **выключен по умолчанию** (`503`). Доверенный сервер
может задать `ACTION_EXTERNAL_RUN_TOKENS`: JSON mapping ID исполнителя
на `{ "token": "<секрет>", "action_ids": [3,4] }`. Токены уникальны,
не менее 32 ASCII символов без пробелов; проверяется также разрешённый
Action ID. Отсутствие Bearer — `401`, неверный токен или чужой Action
— `403`. Секреты в Git/чат/логи не записывать. Другие endpoints
локального Core V1 всё ещё **без общего scoped auth**, поэтому эта
новая проверка не разрешает выставлять API в недоверенную сеть.
Настройка реальных credentials требует отдельного согласованного шага.

## Подтверждённые исходные проверки — 2026-11-11

- Изолированный Python venv с зависимостями проекта; `ruff check`
  изменённых файлов — PASS. Полный repo-level Ruff находит нарушения
  формата импортов в прежних, не изменённых этой задачей файлах.
- Контрактные тесты: **15 passed** (без SQL).
- Новые External AI и существующие Programmatic интеграционные тесты:
  **21 passed** на отдельной PostgreSQL 15.19.
- Полный `pytest tests` с `RUN_DB_INTEGRATION_TESTS=1` на **изолированной
  мигрированной** базе: **137 passed, 127 subtests passed, 1 warning**.
- Отдельная вторая база: создан Programmatic Run по схеме `20261104_0006`;
  upgrade до `20261110_0007` сохранил ActionRun/ActionResult, `execution_kind`
  стал `programmatic`; downgrade вернул прежнюю схему с прежним Run.
- Постоянная PostgreSQL, Windows runtime и GitHub `main` не изменялись.

**Следующая приёмка:** source PR и owner merge, затем отдельное одобренное
развёртывание и проверка реального Registry/миграции/прав, после чего
регистрация архивных Research №3 и Monitoring №4 только с реальными
ссылками, достоверными датами и проверенным readback. До этого не
отмечать P0 как реализованный на рабочем Core.
