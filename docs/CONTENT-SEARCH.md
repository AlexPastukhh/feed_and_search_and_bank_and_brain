# Извлечение текста статей и полнотекстовый поиск

## Что добавлено

- PostgreSQL full-text search по ContentChunk с GIN-индексом.
- Фрагменты сохраняют resource_version_id, номер и символьные координаты.
- RSS-публикации, сохранённые до миграции, worker индексирует небольшими пакетами.
- Поиск работает и по заголовкам материалов, у которых нет текста.
- По запросу можно извлечь основной текст открытой HTML-страницы.
- RSS-версия сохраняется, а доступный веб-текст становится текущей версией.
- Повторное получение неизменившегося веб-текста не создаёт новую версию.

## Ограничения

- Извлечение выполняется вручную для выбранной публикации, не для всей ленты.
- Trafilatura обрабатывает публичный HTML. Не обходит paywall, вход, CAPTCHA или JavaScript.
- Статус full означает извлечённый доступный основной текст страницы; сайт мог скрыть часть материала.
- Для видео, PDF, недоступных сайтов и страниц без статьи endpoint может вернуть ошибку.
- Извлечение пока выполняется в HTTP-запросе и может занять время.
- Сохраняются извлечённый текст, URL и метод извлечения, но не сырой HTML.
  Сохранение оригинального HTML через BlobStorage — отдельная будущая фича.
- Локальный single-user API не предназначен для публичного доступа.

## Перед проверкой

Обновление Windows-клона, Docker Compose и health checks — в
[DEVELOPMENT.md](DEVELOPMENT.md). Миграция `20261104_0003` добавляет
`content_chunks`, индекс полнотекстового поиска, `content_origin` и
`current_version_id`. Существующие RSS-версии сохраняются, а worker
индексирует их фоновыми пакетами.

## Поиск

    $base = 'http://127.0.0.1:8000'
    Invoke-RestMethod "$base/search?q=Qwen" |
      Select-Object resource_id,title,content_status,snippet,canonical_url |
      Format-List

## Извлечение статьи

Выбрать публикацию с оригинального сайта Simon Willison, а не ссылку на внешнее видео:

    $articles = Invoke-RestMethod "$base/resources?limit=100"
    $article = $articles | Where-Object {
        $_.canonical_url -like 'https://simonwillison.net/*'
    } | Select-Object -First 1
    $article | Select-Object id,title,canonical_url,content_status | Format-List

    if ($article) {
        $result = Invoke-RestMethod -Method Post -Uri "$base/resources/$($article.id)/extract"
        $result | Format-List
        Invoke-RestMethod "$base/resources/$($article.id)" |
          Select-Object id,title,content_origin,content_status,content_text |
          Format-List
    }

HTTP 422 может означать, что страница не содержит доступного основного
HTML-текста или источник вернул ошибку; HTTP 502 — сетевую проблему.
Существующий RSS-текст в обоих случаях сохраняется.
Логи: docker compose logs --tail=100 api worker.

## Семантика поиска

GET /search?q=...&source_id=1&limit=20 возвращает фрагменты и совпадения заголовков.
Одна статья может встречаться несколько раз, если совпали разные фрагменты.
Результат содержит resource_id, version_id, chunk_id, snippet,
char_start, char_end и ссылку на первоисточник.

Поиск использует PostgreSQL FTS с конфигурацией `simple` и совпадение
заголовка: это **не семантический поиск** и не полноценное морфологическое
ранжирование всех языков. Один Resource может появиться несколько раз по
разным chunks, а совпадение только по заголовку может иметь `rank=0`.
Поиск ограничен текущей предпочтительной версией содержимого.

В PowerShell 5.1 при выводе Unicode в консоль могут встречаться искажённые
символы. Для проверки **хранимого текста** читайте JSON-файл как UTF-8.
AI Q&A/Action execution не входят в этот срез.
