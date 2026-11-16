# Безопасность, доступ и доверенные границы

**Текущее состояние:** локальный прототип Feedbrain, **без аутентификации и разграничения прав**. Этот документ различает факты реализации и целевые требования. Концепция разрешений для Action System описана в [ARCHITECTURE.md](ARCHITECTURE.md).

## Доступ к работающему Feedbrain

В `compose.yaml` контейнер FastAPI слушает `0.0.0.0:8000` **внутри контейнера**; Docker Desktop публикует его на Windows как `127.0.0.1:8000` (через конфигурируемый `API_PORT`). PostgreSQL наружу порт не публикует.

- Windows-приложения могут обращаться к локальному API.
- Fortis Repo **на конкретной проверенной конфигурации Docker Desktop** достигал API по `http://host.docker.internal:8000`, несмотря на привязку опубликованного порта к loopback.
- Другие контейнеры **могут** иметь такой доступ в зависимости от сети Docker. Публикация только на localhost не означает обязательной изоляции от всех контейнеров.
- API обычно не доступен напрямую с другого компьютера в сети, но это зависит от конфигурации хоста, прокси и форвардинга портов.

**Любой клиент с сетевым доступом сейчас может вызывать и чтение, и изменение источников/подписок, и запуск синхронизации/извлечения.** После обновления на ActionRun API он сможет **читать, создавать Actions, публиковать версии и запускать привязанные workflows**; это может раскрывать инструкции и инициировать сетевые операции Feedbrain. У новых маршрутов пока нет auth: теперь каждый Action может явно указывать `tool` и `with.source` (в том числе ID любой подписки Feedbrain, доступной API). Broker ограничен зарегистрированными инструментами и операциями, но **не реализует per-user permissions**. Добавление `PUT /actions/{id}/schedule` означает, что любой клиент с доступом к API сможет **включить повторяющиеся автоматические внешние вызовы**; по умолчанию расписания выключены, но это не заменяет авторизацию. Не публикуйте API в интернет и не давайте недоверенным клиентам создавать или запускать Actions. Токенов, READ/ADMIN-ролей, авторизации на эндпоинтах и per-tool permissions ещё нет. Не публикуйте порт API в интернет и не давайте недоверенному ПО доступ к этому endpoint. Отсутствие публичного порта PostgreSQL не защищает от вызовов через API.

## Source-only Gateway READ pilot

В принятом source есть защищённый `GET /gateway/v1/actions/{action_id}`: только Action 3/4, точный Host `action-core-gw`, без query/body, с отдельным Bearer, проверяемым по SHA-256 digest, закрытой проекцией текущей ActionVersion (65 536 bytes). Он не использует `ACTION_EXTERNAL_RUN_TOKENS` и не открывает запись. В новой task-ветке `action-core-native-https-entry-20261117` маршрут вынесен **из** локального HTTP-приложения в отдельный узкий ASGI app `info_hub.gateway_read_main:app`. Прямой TLS/443 listener `python -m info_hub.gateway_https_server` проверяет verifier, неизменяемый сертификат и закрытый ключ, TLS-цепочку и fail-closed старт; это не HTTP-прокси и не временный compatibility transport. Текущий Windows image **ещё не обновлён**.

Это **не** означает, что существующий API защищён: локальные `/actions`, `/actions/{id}/runs`, Sources, Search и другие маршруты остаются без общей аутентификации. Source candidate не развернут. Windows probe 2026-11-17 подтвердил HTTP 200 к `host.docker.internal:8000` и `192.168.0.2:8000` из `fortis-gateway`; разные Docker networks не обеспечивают изоляцию. Дополнительная Windows TCP-проверка показала, что Action Core видит **одинаковый peer `192.168.0.1`** и от Gateway по `host.docker.internal:8000`, и от Gateway напрямую по `192.168.0.2:8000`, и от Windows `127.0.0.1:8000`. Поэтому ACL по этому source IP **не различает** клиентов; запрещено выдавать такой allowlist за изоляцию. Нужна owner-reviewed граница **до NAT** или независимый Windows-local IPC/endpoint, недоступный Gateway, с обязательными отрицательными проверками обоих HTTP/8000 путей. До этого и до verified native TLS/443 Gateway нельзя считать безопасно ограниченным READ; live Acceptance остановлена. Ни отдельный ASGI app, ни валидный manifest сами по себе не закрывают bypass.

## Optional native TLS/443 Compose profile (source candidate)

The task `action-core-gateway-compose-service-20261117` adds an opt-in `gateway` profile with a separate `action-core-gw` service. It runs the narrow HTTPS ASGI entrypoint directly on 443, has no published host port, and receives only the SHA-256 verifier. Its TLS private key is in an owner-provisioned external Docker volume mounted read-only. The dedicated `fortis-actioncore-net` is an internal bridge; the Gateway must join it only through the reviewed Fortis owner release controller. The normal Compose profile and local HTTP API are unchanged.

This profile is **not deployed or live-verified**. The Gateway-to-HTTP/8000 bypass through `host.docker.internal` remains possible, and the prior direct API-IP path also succeeded. A Docker network split by itself does not close both paths. Do not start the profile, attach the Gateway, or run READ Acceptance until a tested pre-NAT barrier preserves Windows `127.0.0.1:8000`, the existing Gateway controller/Guard/tests support the reviewed network, owner TLS/vault material is provisioned, and UC-GW-009 quiescence is confirmed. See [GATEWAY-COMPOSE.md](GATEWAY-COMPOSE.md) for the exact source contract and STOP gates.

## Минимальные требования перед подключением недоверенных инструментов

- Два уровня возможностей: **read-only** (поиск, чтение данных) и **admin/write** (изменение настроек, запуск сетевых операций, запись результатов). Точная модель токенов — отдельное решение, **пока не реализовано**.
- Выдавать инструментам только необходимые permissions, не передавать секреты приложения в prompt и не включать их в Git/логи.
- Для внешних Action — per-run политика: разрешённые connections/operations, лимиты запросов и расходов, timeout и подтверждение потенциально значимых изменений (например, правок Goal Map).
- Сохранять хотя бы идентификатор ActionRun, инструмент, операцию, статус и ссылки на результаты для аудита. Broker ограничивает сохранённые `StepRun.details` 16 КиБ JSON, маскирует распознаваемые credential-строки и удаляет подозрительные поля. Это **best effort**, а не надёжный детектор секретов: адаптеры обязаны явно отбирать безопасные метаданные и не передавать приватное содержимое и credentials в историю или логи.
- Не принимать внешние веб-страницы, файлы или ответы API как системные инструкции для AI (prompt injection). Передавать их только как данные с происхождением.
- Проверять SSRF, redirects, внутренние адреса, rate limits, MIME, размер и условия использования источников.

## Что уже ограничено

RSS и URL fetch проверяют схему HTTP/HTTPS, запрещают локальные/private IP, проверяют DNS и redirects, ограничивают число redirects, размер и время загрузки; HTTP-клиент не использует системные proxy settings. **Полной защиты от DNS rebinding между DNS-проверкой и подключением нет**. Это не эквивалент сетевой песочницы. HTML-извлечение не обходит login/paywall/JavaScript.

Локальные секреты PostgreSQL находятся в `.env` и не должны попадать в Git; наружная публикация DB порта отсутствует. Приватные файлы, бэкапы, исходные данные и токены других сервисов также не должны сохраняться в репозиторий.

## Эксплуатация

- Для Docker Compose используйте `docker compose down`, чтобы сохранить PostgreSQL volume; **не** выполняйте `docker compose down -v` без намерения удалить данные.
- Полный backup/restore и его тестирование ещё предстоит реализовать до использования как надёжного долговременного архива.
- Если сервис будет доступен вне локального окружения, обязательны auth, TLS, ограничение сети и аудит.
