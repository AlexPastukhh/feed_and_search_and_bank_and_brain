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

## Границы этого среза

Этот документ проверяет **RSS-ингестию**. Извлечение публичного HTML и
полнотекстовый поиск реализованы позднее и описаны отдельно в
[CONTENT-SEARCH.md](CONTENT-SEARCH.md). Остальные запланированные возможности
см. в [STATUS.md](STATUS.md).

Каждый материал из RSS получает статус `partial`, если feed вернул текст,
или `metadata_only`, если есть только metadata. Это сознательное
ограничение: RSS-анонс нельзя считать полным текстом статьи.

## Ограничения доступа и запуск

Feedbrain ограничивает протоколы и адреса RSS, но URL validation не устраняет
все SSRF-риски, включая DNS rebinding. API **не имеет авторизации**.
Сетевая модель и ограничения: [SECURITY.md](SECURITY.md).

Команды запуска/обновления Docker и проверки health находятся в
[DEVELOPMENT.md](DEVELOPMENT.md).

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

## Миграции и данные

При запуске выполняется `alembic upgrade head`; используйте последнюю
миграцию, а не историческую версию только из этого RSS-среза.
Downgrade может удалить таблицы и записи. Не выполняйте его без backup.
