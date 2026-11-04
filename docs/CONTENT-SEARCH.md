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

## Проверка после git pull на Windows

В Windows PowerShell в каталоге проекта:

    git status --short --branch
    git pull --ff-only origin main
    docker compose up --build -d
    docker compose ps -a
    curl.exe http://127.0.0.1:8000/health/ready

Миграция 20261104_0003 создаёт content_chunks и индекс полнотекстового поиска,
добавляет content_origin и current_version_id.
30 ранее сохранённых RSS-записей и их исходные версии остаются в PostgreSQL.

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

HTTP 422 означает, что доступный основной текст получить не удалось.
RSS-оригинал при этом сохраняется.
Логи: docker compose logs --tail=100 api worker.

## Семантика поиска

GET /search?q=...&source_id=1&limit=20 возвращает фрагменты и совпадения заголовков.
Одна статья может встречаться несколько раз, если совпали разные фрагменты.
Результат содержит resource_id, version_id, chunk_id, snippet,
char_start, char_end и ссылку на первоисточник.

Семантический поиск и AI Q&A не входят в этот срез.
