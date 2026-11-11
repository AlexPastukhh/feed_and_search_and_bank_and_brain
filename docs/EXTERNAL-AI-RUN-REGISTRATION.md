# Регистрация External AI ActionRun — реализация и проверка

**Статус на 2026-11-11:** исходники и миграция смержены владельцем
через [PR №8](https://github.com/AlexPastukhh/feed_and_search_and_bank_and_brain/pull/8)
в Docker `main` (`23abaac2a561978a787cbca3e690193abdd3f650`).
**Следующее изменение, пока только в task-ветке:** убрать `executor_id`
из модели, API и учёта, добавив миграцию `20261111_0008`.
Авторизация остаётся по разрешённым Action ID, без имени/ID исполнителя.
Миграция и новый HTTP API **не развёрнуты на рабочем Windows Docker/Core**;
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
выдумывать. **Идентификатор исполнителя не нужен и не сохраняется**.
`initiated_by` — тип инициирования (`user`, `ai` и т. п.),
`external_run_key` идентифицирует сам Run, не человека или AI.
Пример **только формата**, не реального Run:

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
`200` с тем же Run даже с другим разрешённым токеном. Попытка
подменить данные под тем же ключом — `409`;
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
может задать `ACTION_EXTERNAL_RUN_TOKENS` как JSON-массив:
`[{ "token": "<секрет>", "action_ids": [3,4] }]`. Имен/ID
исполнителя в настройке, истории и API нет. Токены уникальны,
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
- Эти проверки относились к принятой версии `0007` с
  `executor_id`. **Новая проверка отказа от идентификатора**:
  17 контрактных тестов PASS, полный набор на одноразовой
  PostgreSQL 15.19 — **139 passed, 127 subtests passed, 1 warning**;
  `ruff check` изменённых Python-файлов PASS.
  Миграция `0006 → 0008` сохранила старый Programmatic Run,
  `0008 → 0007 → 0008` безопасна без внешних Runs.
  При старом заполненном `executor_id` миграция `0008`
  отказала без потери данных; обратный переход при анонимных Runs
  также заблокирован без фиктивных идентификаторов.
- Отдельная вторая база: создан Programmatic Run по схеме `20261104_0006`;
  upgrade до `20261110_0007` сохранил ActionRun/ActionResult, `execution_kind`
  стал `programmatic`; downgrade вернул прежнюю схему с прежним Run.
- На момент **самих тестов** постоянная PostgreSQL и Windows runtime
  не изменялись; позже код попал в `main` через owner merge PR №8.

**Следующая приёмка:** отдельное разрешённое обновление Windows
через Mirror с проверкой точного SHA, применение всех миграций до
принятого `head` (при принятии изменения без ID — включая `0008`),
проверка живого Registry и разрешённого способа настройки прав; после этого
регистрация архивных Research №3 и Monitoring №4 только с реальными
ссылками, достоверными датами и проверенным readback. До этого не
отмечать P0 как реализованный на рабочем Core.
