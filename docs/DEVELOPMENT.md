# Разработка и эксплуатация Feedbrain

> Что реализовано — [STATUS.md](STATUS.md). Зачем это нужно и как связано с Actions — [ARCHITECTURE.md](ARCHITECTURE.md). Ограничения доступа — [SECURITY.md](SECURITY.md).

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
python3 -m unittest discover -s tests -p test_structure.py -q
git diff --check
```

Такие проверки **не заменяют Docker end-to-end**.

## CI

Есть шаблон `ci/workflow-template.yml`, но рабочий workflow в `.github/workflows/` **не установлен**, поскольку текущие полномочия Fortis GitHub PAT не позволяют его публиковать. Для включения потребуется владелец/токен с правами на workflows. Секреты и PAT не добавлять в файлы репозитория.
