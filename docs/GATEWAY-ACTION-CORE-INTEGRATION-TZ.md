# ТЗ: подключение Action Core к Fortis Gateway (UC-GW-012)

**Статус:** проект ТЗ для реализации; не является подтверждением production deployment.

**Дата:** 2026-11-17. **Приоритет:** P0 READ, отдельно P0 WRITE.

**Владелец API:** `feed_and_search_and_bank_and_brain`. **Владелец Gateway:** `fortis-approvals`.

**Цель:** AI читает Action/версию/историю через единый типизированный Gateway без получения credential, а после отдельной WRITE-приёмки регистрирует завершённый внешний Run с проверяемым readback.

## 1. Нормативные документы

- Общий Git/Gateway/Windows: [UC-CONT-002/003](https://github.com/AlexPastukhh/fortis-container/blob/main/docs/use-cases/delivery.md) и [Release Planning](https://github.com/AlexPastukhh/fortis-container/blob/main/docs/RELEASE-PLANNING-CONTRACT.md).
- Для собственного API: [UC-GW-012](https://github.com/AlexPastukhh/fortis-approvals/blob/main/docs/use-cases/own-api.md), [Integration Extensions](https://github.com/AlexPastukhh/fortis-approvals/blob/main/docs/INTEGRATION-EXTENSIONS.md), [TOOLS](https://github.com/AlexPastukhh/fortis-approvals/blob/main/docs/templates/own-api/TOOLS.md) и [шаблоны](https://github.com/AlexPastukhh/fortis-approvals/blob/main/docs/templates/own-api/README.md).
- Разрешения и релизы: [UC-GW-002/003](https://github.com/AlexPastukhh/fortis-approvals/blob/main/docs/use-cases/integrations.md), [UC-GW-004](https://github.com/AlexPastukhh/fortis-approvals/blob/main/docs/use-cases/credential-lifecycle.md), [UC-GW-005](https://github.com/AlexPastukhh/fortis-approvals/blob/main/docs/use-cases/releases.md), [UC-GW-009](https://github.com/AlexPastukhh/fortis-approvals/blob/main/docs/use-cases/incidents.md).
- Предметные контракты: [Action Core](ACTION-CORE.md), [External AI Registration](EXTERNAL-AI-RUN-REGISTRATION.md), [UC-ACT-012](use-cases/external-run.md), [SECURITY](SECURITY.md), [Action Use Cases](use-cases/README.md).

Обязательно учесть смерженный **Gateway PR №103** (`4e3639985b472d431616aaad25e4a494a9735598`): проверка installed operation/version до READ admission, fsync файла **и директории** журнала UUID до отправки, повтор через `result()` без нового `call()`, ограничение ответа манифестом. **Не дублировать** common provider framework, vault, client, approvals, one-shot journal или controller.

## 2. Текущий факт, проверенный read-only 2026-11-17

| Объект | Результат | Ограничение |
| --- | --- | --- |
| Docker и GitHub main Action System | `fc806e9ad6aeb44ebae57c19f596bc860190728b`, Docker tree clean | Не является доказательством точного Windows image SHA |
| Windows API | `/health/ready` и `/health/live` = HTTP 200; OpenAPI содержит External AI POST | Не означает разрешённой регистрации |
| Research | Action №3 `research`, версия 3 доступна по GET | В Core history 0 Runs |
| Monitoring | Action №4 `monitoring`, версия 1 доступна по GET | В Core history 0 Runs |
| Live Gateway catalog | Есть `mirror.get_repository`, отсутствует `action_core` | Подключение пока не установлено |
| Манифест-кандидат | `DOCKER-HTTPS`, `action_core.read_action`, GET, targets 3/4: `SOURCE_MANIFEST_VALID` | `liveVerified=false`, `readyToDeploy=false` |

Прямой локальный GET использовался исключительно для диагностики, **не** является Gateway E2E и не разрешает обход Gateway в целевом workflow. Датированные README могут отставать от работающего Windows runtime; в evidence указывать свежий факт и источник наблюдения.

**Дополнительная read-only проверка Windows Docker после merge PR #15:** из `fortis-gateway` успешно открылись TCP и HTTP 200 на `host.docker.internal:8000/health/ready` и `192.168.0.2:8000/health/ready`; `feedbrain-api-1` не разрешился через DNS. Gateway находится в `bridge` (`172.17.0.2`), Action Core — в `feedbrain_default` (`192.168.0.2`). **Разные Docker networks не изолируют API в этой конфигурации.** Это STOP для live READ: сначала требуется доказать и реализовать host/network ACL, исключающий оба HTTP/8000 пути, при сохранении локального Windows API. Никакие runtime изменения пока не выполнялись. Дополнительно проверен текущий Gateway source: `Manage-Integrations.ps1` запускает Primary Gateway с `--network bridge`, а `github_pilot_helpers.py` Fortis Guard требует `HostConfig.NetworkMode == bridge`. Поэтому переход Gateway на `fortis-actioncore-net` нельзя делать ручным `docker network connect`/disconnect: если это потребуется для изоляции, нужно изменить стандартный owner-run release controller, Guard и их тесты в `fortis-approvals`, затем доставить и Promote штатно. Простое добавление второй сети не убирает существующий путь через default `bridge`.

**Свежая read-only проверка Gateway 2026-11-17:** штатный `extensions.client.default_client().catalog()` возвращает только `mirror.get_repository`; `action_core` отсутствует. Полный global unresolved inventory показывает 4 `UNCERTAIN`; actor-scoped activity — 1 `CLAIMED` по отдельному запросу, у которого incident inspection показывает `CLOSED_UNCONFIRMED`, receipt отсутствует. `quiescenceProven=false`, retry authorization отсутствует. Это не мешает source-разработке, но блокирует production release/Promotion и live Acceptance до разрешения по UC-GW-009.

**Windows TCP peer evidence 2026-11-17:** при параллельных TCP-сеансах Gateway→`host.docker.internal:8000`, Gateway→`192.168.0.2:8000` и Windows→`127.0.0.1:8000` `/proc/net/tcp` внутри `feedbrain-api-1` трижды показал peer `192.168.0.1` (разные ephemeral ports). Это NAT; IP-based ACL внутри API не отличит Gateway от Windows и не считается сетевым барьером. Первое Gateway-visible соединение допускается **только напрямую через конечный native TLS/443** с отдельным закрытым ASGI app. Нет временного HTTP bridge/proxy, compatibility-layer, dual mode или fallback. Для backend HTTP/8000 нужен проверенный блок обоих Gateway обходов **до NAT**, либо собственный недоступный Gateway локальный канал для Windows. Без доказательства — STOP. Source задача для нативного TLS entrypoint не изменяет running Compose, БД или Gateway.

## 3. Границы и критерии результата

Путь: `AI → Fortis Repo SDK → Primary Gateway (machine TLS, actor, policy, vault) → fixed HTTPS:443 → защищённый Action Core → PostgreSQL`.

- Action Core хранит ActionVersion, ActionRun, ActionResult; Gateway проверяет typed operation/target, управляет credential и technical receipt. **Нет `executor_id`** в предметной истории. Gateway machine actor не равен исполнителю Action.
- Нельзя передать из AI URL, path suffix, Host, header, токен, HTTP method, произвольный query, policy, credential alias или target вне trusted allowlist.
- READ не разрешает Action mutation, scheduling, worker starts, регистрацию Run или запись в Sources/Feedbrain. Существующие локальные клиенты, Broker и workers не ломаются.
- `SOURCE_MANIFEST_VALID`, green CI, работающий localhost API, Gateway catalog и `LIVE_API_VERIFIED` — разные уровни доказательств.

## 4. P0-A: upstream DOCKER-HTTPS и авторизация чтения

Выбрать **UC-GW-012 DOCKER-HTTPS**. Проектные (ещё не установленные) значения: DNS `action-core-gw`, origin `https://action-core-gw:443`, SAN `DNS:action-core-gw`, общая owner-reviewed сеть `fortis-actioncore-net`, Gateway read-only CA `/run/fortis-secrets/action-core-read/ca.pem`, Gateway credential alias `action-core-read`, scoped principal `action-core-gateway-reader`.

Action Core owner реализует фиксированный HTTPS/443 ingress к **той же** FastAPI/business logic (допустим ограниченный TLS ingress/sidecar, не второй Action Core). Локальный `127.0.0.1:8000` оставить для действующих клиентов. Проверить физическую/сетевую невозможность из Gateway-network обратиться к незащищённому API:8000, не открывать публичный host port, не включать HTTP/redirect/proxy fallback. Перед внесением изменений проверить фактические Docker network memberships, разделение API/ingress, совместимость Gateway Compose и Fortis Guards. Docker network сама по себе не является аутентификацией.

В реальной Gateway namespace проверить: DNS, TLS/443, hostname/SAN, CA provenance/expiry, Host allowlist, wrong CA/SAN/Host, отсутствие redirects/proxy/HTTP fallback, чужую сеть и ограничение методов/маршрутов. TLS server private key хранится **только upstream**; в Gateway попадает проверенный **публичный** CA, без ключа. Защищённый Core endpoint требует bearer и проверяет разрешённый Action ID/операцию, независимо от сетевого ACL; wrong/missing bearer -> 401/403.

**Секрет:** только Gateway existing `fortis-review-secrets` vault (`/run/fortis-secrets`), owner-controlled `Manage-Integrations.ps1`. Не передавать его в Repo, Git, `.env`, chat, argv, logs или Action. Core разрешено хранить только утверждённый проверочный материал (например, SHA-256 сильного случайного токена) и public scope, **не plaintext credential**. В source candidate upstream определён `ACTION_GATEWAY_READ_TOKEN_SHA256`: ровно 64 lowercase hex SHA-256 символа; соответствующий случайный ASCII Bearer — 32–256 символов без whitespace. Отсутствующий/некорректный verifier даёт 503, отсутствующий Bearer — 401, неверный Bearer или target вне scope — 403. Это отдельная настройка API и не переиспользует `ACTION_EXTERNAL_RUN_TOKENS`. Owner generation, provisioning, rotation/revocation и runtime verification остаются отдельными шагами до release.

## 5. P0-B: минимальная typed READ операция

В `fortis-approvals` стандартным `extensions.cli scaffold` создать пакет `fortis_approvals/integrations/action_core/` с `extension.py`, provider README, tests, trusted route и closed schema. Клиент только `fortis_approvals.extensions.client.default_client()`, стандартный `catalog/call/result`. Не добавлять собственные Core ingress, approval queue или SDK.

**Первый READ-пилот, совместимый с V1 own-api manifest/one-shot Acceptance:**

| Поле | Контракт |
| --- | --- |
| Service/operation | `action_core.read_action`, `kind=read`, policy `ALLOW` |
| Gateway `target` | ровно строка `"3"` или `"4"` (положительный `action_id`) |
| Caller params | ровно `{}`, неизвестные поля запрещены |
| HTTP route | `GET /gateway/v1/actions/{action_id}`, фиксированный HTTPS origin |
| Auth | read-only scoped Bearer внедряет Gateway; body GET отсутствует |
| Бounded result | `action_id:int`, `name:str`, `category:str`, `current_version_number:int`, `definition_yaml:str`, `schedule_active:bool` |
| Limit | JSON максимум 65536 bytes, неверные/лишние поля и большой документ отклоняются, не обрезаются |

`GET /gateway/v1/actions/{action_id}` — **проектируемый** защищённый upstream GET, не существующий текущий маршрут. Он повторно использует Action Registry services и отдаёт ограниченную проекцию **текущей** версии; никаких сырых объектов БД и credentials. Старый локальный `GET /actions/{id}` остаётся совместимым. Закрытая схема provider обязана проверять точные поля и типы; нет скрытого fallback на другую версию.

**Public manifest:** создать в рабочем task PR по шаблону `docs/templates/own-api`: `serviceId=action_core`, `ownerRepository=feed_and_search_and_bank_and_brain`, sourceSha **точного upstream merged main**, `DOCKER-HTTPS`, `origin=https://action-core-gw:443`, `tlsServerName=action-core-gw`, reviewed network и CA path, `vaultAlias=action-core-read`, `upstreamPrincipal=action-core-gateway-reader`; одна `GET/READ/ALLOW` операция `read_action`, `targetBinding=action_id`, `path=/gateway/v1/actions/{action_id}`, `targets=["3","4"]`, `maxResponseBytes=65536`. В manifest только публичные идентификаторы, **не токен и не сертификат**.

**После пилота:** тем же provider и отдельной contract-проверкой добавить READ `read_action_version` (точная версия, а не `current`), `list_runs` (пагинация с лимитами) и `read_run` (проверить, что `run_id` принадлежит разрешённому Action). Дополнительные path placeholders/параметры, которые V1 лентер не умеет выразить, добавлять по UC-GW-003 и тестировать отдельно: не ослаблять V1 и не объявлять все READ принятыми после проверки только `read_action`.

## 6. Read-only проверки и допуск

**Сейчас, без изменений runtime:** READ source/main/PR и Compose (без secrets), проверка `GET /health/ready`, точной ActionVersion и списка Runs, Gateway `catalog()`. `own_api_doctor.py` offline; его опциональные `--live-catalog --core-inventory` читают Gateway, но **не** проверяют upstream, quiescence или реальную сеть. Не отправлять POST и не читать private credential.

**Source gates:** зарегистрированный task worktree, `python3 -B scripts/check-own-api-manifest.py --manifest <absolute-json>` → `SOURCE_MANIFEST_VALID`; `scripts/test-source.sh`, unit/negative tests provider и TLS. Обязательные отказы: wrong actor/target, target `2`, неверный path/suffix/query, лишние params, POST/PUT, wrong/no bearer, wrong Host/CA/SAN, redirect, non-HTTPS, чужая Docker network, timeout, malformed/oversize JSON. Lint не является live acceptance.

**После owner release:** независимый host image/health/readback, catalog operation/version/policy/targets и защищённый `configurationDigest`. Штатный `own_api_acceptance.py` по [TOOLS](https://github.com/AlexPastukhh/fortis-approvals/blob/main/docs/templates/own-api/TOOLS.md) с новым UUID и private absolute journal: первый dry-run без `--submit-read`, затем явно разрешённый one-shot `--submit-read`. Журнал и directory entry fsync **до** call; повтор только `result(uuid,reconcile=False)`. Сверить exact schema и значение Action №3/№4 с независимым Core readback. Затем обычные READ выполняются напрямую существующим SDK. `catalog()` сам по себе — не `LIVE_API_VERIFIED`.

## 7. Отдельная P0-C: запись завершённых External AI Runs

**Только после live READ** добавить `action_core.register_external_run` по [UC-GW-003](https://github.com/AlexPastukhh/fortis-approvals/blob/main/docs/use-cases/integrations.md#uc-gw-003), **не** через READ-only V1 manifest/acceptance. Отдельный scoped WRITE principal/alias; policy пилота `ASK` на `3`,`4`; owner WebAuthn и неизменяемый preview, проверяемые preconditions, durable receipt, read-only lookup по `(action_id, external_run_key)` и safe `UNCERTAIN` без слепого POST. При отсутствии доказанной изоляции ASK от прямой записи нужен reviewed dispatch proof либо `DENY`. Новый approval engine/журнал/worker не создаётся.

Контракт Core: существующий `POST /actions/{action_id}/external-runs`; терминальные `completed|failed|interrupted`, реальная `version_number`, отдельный `external_run_key`, `initiated_by`, `summary`, `storage_status`, опциональные реальные timestamps/error/output_refs. **Нет** `executor_id`, фиктивных queued/StepRuns или запуска AI. Первый POST: `201`; точный повтор: `200`, прежний Run; изменённые данные с тем же ключом: `409`. Gateway UUID и внешний run key различны. Тестировать ASK Reject/Approve, конкурентные записи, отказ вне scope, credential rotation, потерю ответа после commit и lookup, Programmatic Run compatibility на **одноразовой PostgreSQL**. Никогда не тестировать запись на постоянном Windows volume.

После отдельной WRITE live-приёмки зарегистрировать три **реальных архивных** Run с подтверждённым Git readback: Research `#3/v3` из `research/action3/runs/2026-11-10-src001-review01/` и Monitoring `#4/v1` из `monitoring/action-4/runs/2026-11-10-initial01/`, `monitoring/action-4/runs/2026-11-10-followup01/`. У каждого свой key/output_ref; не придумывать время и не считать два несопоставимых snapshot трендом. UC-ACT-009/010/011 о решениях и сравнении данных выполняются отдельно.

## 8. Git, owner release, handoff

- Изменения в **двух** репозиториях отдельными PR: upstream (`feed_and_search_and_bank_and_brain`) — защищённый GET/TLS/identity + тесты; Gateway (`fortis-approvals`) — provider, public config/manifest, тесты и README. Не менять общий framework без конкретного несовместимого контракта.
- Только registered task worktree → typed Gateway edit/stage/commit/publish/PR → Release Impact в PR body и exact HEAD CI → owner GitHub UI merge → typed `update_main_from_pr`. Документальное ТЗ само по себе **no-deployment**.
- Windows Mirror exact-SHA Pull **не** обновляет контейнер. Upstream backup/restore и отдельный owner deployment; Gateway общий vault/Compose/Primary — только owner. Перед единым Gateway `Check/Apply/Backup/Promote`: UC-GW-009 глобальные `APPROVED/DISPATCHED/UNCERTAIN/CLAIMED`, quiescence, verified isolated restore, old image, network/TLS/grants; UC-GW-013 только отдельным owner-решением при отсутствии old image. Не выполнять concurrent releases, не удалять volumes и не ослаблять guards.
- Evidence по существующим [evidence/handoff templates](https://github.com/AlexPastukhh/fortis-approvals/tree/main/docs/templates/own-api): `SOURCE_MANIFEST_VALID` → `SOURCE_READY` → `PR_MERGED` → `IMAGE_ACTIVATED` → `LIVE_API_VERIFIED`, с точными SHAs, safe errors и owner probes. Не переносить токен, private CA key, raw env, protected record в Git/chat/Workfiles.

**STOP:** неизвестный image/manifest/actor/target, открытый HTTP/8000 с Gateway сети, неверная TLS identity, credential mismatch, иной effect без ASK, неполный READ/inventory, невозможный restore, активный competing worker, повтор неизвестного WRITE, недоказанный deploy. `docker compose down -v` запрещён.

**DoD READ:** владелец подтвердил транспорт, CA, сеть и upstream principal; приняты source PR+CI и production releases; `catalog()` показывает только разрешённые `action_core.read_action` на №3/4; обе инструкции реально получены через Gateway SDK; wrong-target и credential negatives отклонены; локальный API/Workers не сломаны; составлен безопасный handoff. **WRITE и архивные Runs не входят в DoD READ:** для них отдельные тесты и evidence раздела 7.
