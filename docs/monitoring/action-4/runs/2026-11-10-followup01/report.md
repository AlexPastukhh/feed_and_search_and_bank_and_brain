# Action №4 v1 — второе публичное наблюдение

**Report ID:** action4-v1-2026-11-10-followup01
**Дата:** 10 ноября 2026. **Режим:** внешний AI вручную; не ActionRun.
**Предыдущий результат:** [первый baseline](../2026-11-10-initial01/report.md),
action4-v1-2026-11-10-initial01.
**Источники:** публичная индексированная выдача Upwork и страницы категорий.
Залогиненного аккаунта и проверки доступности откликов не было.

## CHANGES — сравнение с первой выборкой

| Наблюдение | Число | ID |
| --- | ---: | --- |
| Повторное обнаружение точного URL объявления | 4 | FIND-001, FIND-003, FIND-004, FIND-005 |
| Вероятное повторение в списке категории (название + бюджет) | 2 | FIND-002, FIND-006 |
| Дополнительные ссылки, отсутствовавшие в первой выборке | 3 | FIND-007, FIND-008, FIND-009 |
| Достоверно изменившиеся старые объявления | 0 | Нет |
| Достоверно исчезнувшие объявления | 0 | Нет |

Два запуска были **в один календарный день**. Первый сбор был
выборочным, без полного сохранения дословных поисковых запросов,
времени и активности клиента. Поэтому «отсутствовало в выборке» не
означает «опубликовано после первого запуска». Дополнительные
объявления датированы 2 и 9 ноября.

Данные о количестве откликов/наймов у baseline были неполными;
доказать изменение этих полей нельзя. Прямые открытия некоторых
карточек дали cache miss; использованы публичные поисковые результаты.

## FINDINGS — повторные находки

- **FIND-001:** исправление API → CRM mapping, 20 USD. То же
  индексированное объявление (EV-001).
- **FIND-002:** бизнес-автоматизация за 1 500 USD. Совпадение
  названия и суммы в категории, прямой ID не подтверждён (EV-002).
- **FIND-003:** React/Python/Supabase, бюджет 3 000 USD;
  отдельно оплачиваемый аудит 200–500 USD (EV-003).
- **FIND-004:** React/Next.js, 150 USD. Указан один hire;
  изменения относительно baseline не доказаны (EV-004).
- **FIND-005:** аудит AI/CRM автоматизаций, 20 USD (EV-005).
- **FIND-006:** outbound workflow, 1 500 USD, повтор
  в категории по названию и бюджету (EV-006).

## FINDINGS — дополнительные находки

- **FIND-007 — 1 500 USD:** Next.js SaaS и GoHighLevel API:
  формы, синхронизация контактов, webhooks, authentication и retries.
  Требуется специфический опыт GHL; не простой bugfix (EV-007).
- **FIND-008 — 7 500 USD:** React/TypeScript/Supabase,
  доработка beta, мобильная обёртка Capacitor и публикация iOS/Android.
  Большой объём с мобильными компетенциями (EV-008).
- **FIND-009 — 250 USD:** React/Next.js SaaS,
  исправления auth/roles, Node backend и API. Для перечисленного
  объёма бюджет выглядит невысоким (EV-009).

Цены — указанные бюджеты, **не полученные исполнителем деньги**.
Состояние отклика по всем 9 карточкам остаётся неизвестным.

## OVERVIEW

Повторяющиеся проблемы: CRM/API интеграции, существующие React/SaaS
приложения и диагностика workflow. Реальных изменений старых объявлений
этот запуск не доказал. Новая подборка не меняет первоначальную
гипотезу: узкие исправления и самостоятельные платные аудиты могут
быть интереснее широких проектов с большим объёмом.

**Следующий корректный тест:** другой день, дословно сохранённые
поисковые запросы, фильтры и время, одинаковые поля состояния
(опубликовано, бюджет, статус, hires если доступно). Отсутствие в
индексе не считать закрытием заказа. Пока не нужны ни новый Tool,
ни Scheduler.

## EVIDENCE

- **EV-001 / FIND-001:** https://www.upwork.com/freelance-jobs/apply/Automation-Developer-Needed-Fix-CRM-Lead-Processing-Workflow_~022119052550147631506/
- **EV-002 / FIND-002:** https://www.upwork.com/freelance-jobs/operations-and-workflow/
- **EV-003 / FIND-003:** https://www.upwork.com/freelance-jobs/apply/Senior-Full-Stack-Developer-Integration-Supabase-Python-React_~022119025560020041069/
- **EV-004 / FIND-004:** https://www.upwork.com/freelance-jobs/apply/React-Next-Developer-Needed-for-Bug-Fixes-SEO-Optimization-Website-Improvements_~022119010351225727378/
- **EV-005 / FIND-005:** https://www.upwork.com/freelance-jobs/apply/Automation-CRM-Integration-Audit-Claude-n8n-MCP-APIs_~022117633594936182304/
- **EV-006 / FIND-006:** https://www.upwork.com/freelance-jobs/web-programming/
- **EV-007 / FIND-007:** https://www.upwork.com/freelance-jobs/apply/GoHighLevel-API-integration-for-Next-SaaS-website_~022119723102846020741/
- **EV-008 / FIND-008:** https://www.upwork.com/freelance-jobs/apply/React-TypeScript-Supabase-Dev-Bug-Fixes-Capacitor-Wrap-App-Store-Launch-Live-Beta-App_~022119880804865817689/
- **EV-009 / FIND-009:** https://www.upwork.com/freelance-jobs/apply/React-Next-Developer-SaaS-Bug-Fixes-Add-Features-API-Integration_~022117219558067250200/

Полный структурированный результат — [result.json](result.json).
Это внешнее ручное исследование, не программный ActionRun.
Файлы доступны в локальной task-ветке; до принятия PR их нет в main.
