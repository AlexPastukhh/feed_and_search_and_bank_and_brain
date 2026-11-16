# feed_and_search_and_bank_and_brain

Этот репозиторий содержит первую реализацию **Action System** и подключаемый сервис **Feedbrain** для фонового получения, хранения, подготовки и поиска информации. Для нас главный прикладной сценарий — поиск оплачиваемой работы и мониторинг интересующих изменений; функциональные способы использования описаны в [Use Cases](docs/use-cases/README.md).

**Action System** — целевая, пока лишь частично реализованная среда, в которой пользователь формулирует, версионирует и планирует **Actions**, а AI или другой исполнитель выполняет их через возможности подключённых **своих или сторонних приложений**. Приложения рассматриваются как чёрные ящики: нужен доступный инструмент/API/MCP/другой вызываемый интерфейс, а не знание внутренней реализации. Feedbrain **не обязателен** для выполнения каждого Action.

## Документация: где что искать

| Документ | Единственная ответственность |
|---|---|
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | Целевой дизайн: Action, исполнители, инструменты, источники, представления и границы Feedbrain |
| [PROJECT.md](docs/PROJECT.md) | Проверенное состояние и датированная история решений/проверок |
| [BACKLOG-IMPROVEMENTS.md](docs/BACKLOG-IMPROVEMENTS.md) | Единый список открытых задач и условных улучшений |
| [ACTION-CORE.md](docs/ACTION-CORE.md) | Первая рабочая версия: простой YAML, Broker → Feedbrain, история и расписание |
| [EXECUTION-MODES.md](docs/EXECUTION-MODES.md) | Независимые от категории режимы выполнения: External AI, Programmatic, Managed AI |
| [EXTERNAL-AI-RUN-REGISTRATION.md](docs/EXTERNAL-AI-RUN-REGISTRATION.md) | Регистрация завершённого внешнего Run; исходники, права, тесты и граница Windows runtime |
| [Use Cases](docs/use-cases/README.md) | Повторяемые способы работы с Actions: от AI-инструкции до программного мониторинга, фида и ожидания действия |
| [SECURITY.md](docs/SECURITY.md) | Сетевая доступность, текущие риски и необходимые permissions |
| [GATEWAY-COMPOSE.md](docs/GATEWAY-COMPOSE.md) | Опциональный native HTTPS/443 service и owner-only activation gates |
| [DEVELOPMENT.md](docs/DEVELOPMENT.md) | Локальный запуск, тесты, Git workflow, CI |
| [RSS-FIRST-SLICE.md](docs/RSS-FIRST-SLICE.md) | Ручная проверка RSS и фоновой синхронизации |
| [CONTENT-SEARCH.md](docs/CONTENT-SEARCH.md) | Поиск и извлечение текста |
| [PHASE0.md](docs/PHASE0.md) | Исторический снимок начального каркаса, не актуальный статус |

## Кратко о работающем Feedbrain

Python/FastAPI + PostgreSQL 16 + worker + Alembic в Docker Compose. RSS/Atom-подписки автоматически опрашиваются **пока работает worker**; публикации дедуплицируются и версионируются. Текст публичных HTML-статей извлекается **по запросу**; ContentChunk и PostgreSQL FTS дают поиск по архиву.

HTTP API позволяет читать источники, публикации и результаты поиска. Через Fortis Repo доступ к этому API на Windows Docker Desktop уже был проверен. Это **не MCP-сервер** и **не встроенный AI**: внешний AI может вызывать HTTP API средствами своих инструментов. Другие сервисы и внешние поисковые инструменты можно использовать напрямую, без Feedbrain.

**Основные маршруты API пока не имеют общей аутентификации и прав доступа**, поэтому предназначены только для локального доверенного окружения. В принятом коде External AI Run имеет отдельную отключённую по умолчанию проверку полномочий; на Windows этот маршрут ещё не развёрнут. Подробнее — [SECURITY.md](docs/SECURITY.md).

## Запуск

Инструкция по созданию `.env`, запуску Docker, миграциям, проверке работоспособности и тестам: [DEVELOPMENT.md](docs/DEVELOPMENT.md). Не удаляйте PostgreSQL volume случайным `docker compose down -v`.

Имя репозитория историческое; Python package называется `info_hub`, Docker Compose project — `feedbrain`.

**Текущий статус и проверенные возможности:** [PROJECT.md](docs/PROJECT.md); **ближайшие задачи:** [BACKLOG-IMPROVEMENTS.md](docs/BACKLOG-IMPROVEMENTS.md). Принципы оркестрации инструментов и работы с результатами — [ARCHITECTURE.md](docs/ARCHITECTURE.md); детали YAML и API V1 — [ACTION-CORE.md](docs/ACTION-CORE.md).
