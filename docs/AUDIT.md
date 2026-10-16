# ShiftBot — аудит (2026-09-17)

Аудит по коду из `/root/shiftbot` на 185.80.130.222 + логи контейнера.

## A. Баги (падает сейчас)

### A1. `admin:active` падает → `sqlalchemy.exc.MissingGreenlet`
- **Где:** `app/handlers/admin.py:89-91` → `job_text(j)` (`app/services/formatting.py:12`)
- **Причина:** `job_text` при `filled=None` обращается к `job.applications`, а `admin:active` грузит
  `select(Job)...scalars().all()` без `selectinload`. Синхронный lazy-load внутри async → падение.
- **В логах:** 9 раз, `sqlalchemy.exc.MissingGreenlet`.

### A2. Кнопка «📋 Активные работы» показывает только первую работу
- **Где:** `app/handlers/admin.py:91`. `j=jobs[0]` — список из N работ, а рендерится одна.
- **Итог:** остальные работы недоступны (нельзя ни закрыть, ни глянуть работников).

### A3. `admin:workers:<id>` падает → `MissingGreenlet`
- **Где:** `app/handlers/admin.py:107`. `a.full_name` / `u.username` — lazy-load на `Application`/`User`.
- **В логах:** в стеке `admin.py:107`.
- **Итог:** список работников по работе не открывается никогда.

### A4. `admin:filled` / `admin:history` / `admin:stats` — тоже без eager-load
- Менее очевидно, но `filled`/`history` строят текст без `.applications`, поэтому отрабатывают как повезёт.
  В логах `admin.py:94 (filled)` — 2 падения. Чинить тем же способом (явные запросы/`selectinload`).

### A5. `job:view:<id>` частично исправлен, но не везде
- **Где:** `app/handlers/worker.py:31-36`. Тут `job` берётся без `selectinload` → тот же риск `MissingGreenlet`.
  `worker:jobs` (`worker.py:24`) грузит `active_jobs()` без eager-load → тоже падает при наличии заявок.

### A6. `job:cancel:<id>` — «Активная запись не найдена»
- **Где:** `app/handlers/applications.py:47-52`.
- **Причина:** `@router.callback_query(F.data.startswith("job:cancel:"))` без фильтра `ApplicationStatus.ACTIVE`
  + `job:view` показывает `work_button(job.id)`, а не `cancel_application`. Отмена из карточки работы
  не открывается вообще; в «Мои работы» кнопка рисуется только если ровно 1 запись (`worker.py:48`).

### A7. Повторный отклик после отмены ломает UNIQUE
- **Где:** `app/database/repositories.py:39-41` + `models.py:54` (`uq_job_user`).
- **Причина:** у отменённой заявки статус `CANCELLED`, `create_application_locked` возвращает `already` только
  для `ACTIVE`, иначе пытается вставить новую строку → `IntegrityError` на `uq_job_user`.
- **Итог:** после отмены повторно записаться нельзя.

### A8. `admin:delete:<id>` падает на FK
- **Где:** `app/handlers/admin.py:101-104` + `models.py:56-57`.
- **Причина:** у `applications.user_id` стоит `ondelete="CASCADE"`, но удаление `Job` со стороны
  `applications.job_id` тоже каскадное — БД каскадит, однако при уже существующих `applications`
  в логах ловится ошибка FK/`MissingGreenlet`. Нужен явный порядок удаления.

## B. Не доделано (по README «Важные ограничения MVP»)

| # | Что | Где место |
|---|-----|-----------|
| B1 | Напоминания 24ч/2ч | `notifications.py` есть `reminder_loop`, но 24ч/2ч окно по дате work `start_at` — проверить |
| B2 | Редактирование опубликованной работы | есть кнопка `admin:edit:<id>`, обработчика нет |
| B3 | CSV/Excel-экспорт | нет |
| B4 | i18n-таблица | есть кнопка 🌐 «Язык» (`worker:language`) — заглушка |
| B5 | «Набранные работы» — не показывает состав | `admin:filled` — только счётчики |
| B6 | «История работ» — без раскрытия | `admin:history` — плоский список |
| B7 | `reminder_logs` уже есть в БД — работает ли loop | проверить лог |
| B8 | `admin:editdraft` (превью черновика) | handler упомянут в клавиатуре, обработчика нет |

## C. Мелочи / гигиена

- `requirements.txt` не пинит `tzdata` (на Linux ок, на Alpine нужен пакет).
- `migrations/versions/0001_initial.py.save` — лишний артефакт, удалить.
- `.env` на сервере с боевым токеном — ок для личного VPS, но лучше secret manager.
- `app/handlers/admin.py` использует `__import__('app.database.models', ...)` вместо импортов
  сверху — читаемо плохо, но работает.
- В `worker.py:53` — мёртвая ветка `if False else 0` в `profile()`.

## D. План фиксов

1. **Eager-loading:** `selectinload(Job.applications)` во всех выборках (`admin:active`, `admin:workers`,
   `active_jobs`, `job:view`, `myjobs`).
2. **`admin:active`:** список работ с кнопками → карточка → `job_actions`.
3. **`admin:workers`:** явные `selectinload`/join, чтобы не было lazy.
4. **`job:cancel`:** вернуть кнопку отмены в карточку работы; фильтр только `ACTIVE`.
5. **Повторный отклик:** реактивировать существующую `CANCELLED`-заявку вместо INSERT.
6. **Удаление работы:** сначала `delete(Application)` где `job_id`, потом `Job` (или полагаться на CASCADE
   осознанно, с явным flush).
7. Убрать `if False else 0`, `.save`-мусор, добавить `tzdata`.
8. **Тесты:** расширить `tests/` на все фиксы (SQLite async).

## E. Новое: Excel-экспорт (запрос Лёши)

**Цель:** вся статистика — в Excel; скачивание через бота.
Листы:
1. `Работы` — id, название, дата, адрес, ставка, часы, требуется, набрано, статус.
2. `Работники` — по каждому работнику: имя, @username, Telegram ID, работы, часы, ставка, **к оплате**.
3. `Заявки` — job_id, работник, дата записи, статус.
4. `Итоги` — суммы, количество работ, топ работников.

**Кнопки:** в админ-панели `📤 Экспорт в Excel` (и `export:all`, `export:job:<id>` для одной работы).
**Реализация:** `openpyxl` → `BytesIO` → `bot.send_document`.

