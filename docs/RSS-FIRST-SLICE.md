# Первый RSS end-to-end сценарий

## Что работает

- Создание Source для RSS/Atom.
- Создание Subscription c отдельными флагами read/research.
- Автоматический polling по расписанию и ручной sync.
- Durable IngestionRun в PostgreSQL.
- Worker выполняет HTTP fetch, RSS/Atom parser, idempotent upsert.
- Версии публикаций сохраняют исходный XML item и извлечённый текст.
- Resource связан с несколькими Subscription одного Source.
- API показывает Source, Subscription, Run и Resource.
- ETag/If-Modified-Since и HTTP 304 поддерживаются.

## Что пока не работает

- Получение полного текста с оригинальной веб-страницы.
- UI для ленты.
- Full-text search, AI и исследования.
- Другие connectors (GitHub, Steam, вакансии, файлы).
- Универсальная нормализация всех типов ресурсов.

Каждый материал из RSS получает статус `partial`, если feed вернул текст,
или `metadata_only`, если есть только metadata. Это сознательное
ограничение: RSS-анонс нельзя считать полным текстом статьи.

## Security note

Пользовательские RSS URL ограничены HTTP/HTTPS, стандартными портами и
публичными IP-адресами. Worker проверяет DNS для каждого redirect, не
использует системные proxy settings и ограничивает размер ответа.
DNS rebinding между проверкой и самим сетевым соединением полностью не
исключается; не предоставлять API недоверенным пользователям и не
публиковать его напрямую в интернет до полноценного network isolation.

## Windows / Docker Desktop: запуск

Из Windows checkout:

```powershell
git status --short --branch
git pull --ff-only origin main
docker compose up --build -d
docker compose ps -a
curl.exe http://127.0.0.1:8000/health/ready
```

Миграция `20261104_0002` создаст таблицы Source, Subscription,
IngestionRun, Resource, ResourceVersion и SubscriptionResource.

## Windows / Docker Desktop: первый RSS

В PowerShell (команды изменяют только локальную БД приложения):

```powershell
$base = 'http://127.0.0.1:8000'
$sourcePayload = @{
    name = 'Simon Willison'
    feed_url = 'https://simonwillison.net/atom/everything/'
} | ConvertTo-Json
$source = Invoke-RestMethod -Method Post -Uri "$base/sources" -ContentType 'application/json' -Body $sourcePayload
$source | Format-List

$subscriptionPayload = @{
    name = 'Simon Willison hourly'
    interval_minutes = 60
    read_enabled = $true
    research_enabled = $true
    enabled = $true
} | ConvertTo-Json
$sub = Invoke-RestMethod -Method Post -Uri "$base/sources/$($source.id)/subscriptions" -ContentType 'application/json' -Body $subscriptionPayload
$sub | Format-List

$run = Invoke-RestMethod -Method Post -Uri "$base/subscriptions/$($sub.id)/sync"
$run | Format-List
Start-Sleep -Seconds 8
Invoke-RestMethod "$base/runs/$($run.id)" | Format-List

$items = Invoke-RestMethod "$base/resources?subscription_id=$($sub.id)&limit=10"
$items | Select-Object id,title,content_status,canonical_url | Format-Table -AutoSize
```

При сетевых ограничениях или недоступности feed, Run станет `failed`,
а причина будет в `error` и `docker compose logs --tail=100 worker`.

## Проверка идемпотентности

Повторить POST /subscriptions/{id}/sync после завершения первого.
При неизменившихся публикациях `items_created` и `items_updated`
должны быть равны нулю. Для HTTP 304 `items_seen` будет нулём.

## Возврат к предыдущей версии

Миграция выполняется автоматически и **не стирает старые данные**.
Для отката схемы потребуется отдельная осознанная операция:
`alembic downgrade 20261104_0001` удаляет новые таблицы и их данные.
Не выполнять downgrade без необходимости и backup.
