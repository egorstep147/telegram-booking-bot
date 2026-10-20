# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Что это

Шаблон бота записи на услуги: бот + Mini App. Один бизнес на процесс, бизнес — папка `niches/<name>/`
с `config.yaml` (правила: шаг слотов, запас, отмена, напоминания, предоплата) и `catalog.yaml`
(филиалы, услуги, мастера, графики). Выбирается переменной `NICHE`.

## Tech stack

Python 3.13, uv, ruff, pytest · aiogram 3 + FastAPI в одном процессе · SQLAlchemy 2 async + Alembic ·
PostgreSQL (btree_gist для EXCLUDE) · Redis (FSM) · React 19 + TypeScript + Vite в `webapp/` (oxlint).

## Commands

- `docker compose up -d` — PostgreSQL (порт 5434) и Redis (6381)
- `uv run booking migrate | seed | run`
- `uv run pytest` — база booking_test или TEST_DATABASE_URL
- `uv run ruff check src tests && uv run ruff format src tests`
- `cd webapp && npm run dev | build | lint`
- DATABASE_URL с `127.0.0.1`, не `localhost`: на Windows localhost теряет ~2 с на соединение (IPv6)

## Architecture

- `services/slots.py` — чистый алгоритм свободного времени; `schedule.py` — данные из базы (записи, TimeOff,
  Google busy) → слоты; `bookings.py` — create/cancel/reschedule/mark/mark_paid
- Двойную запись запрещает EXCLUDE `no_double_booking` (master_id =, slot &&) для статусов pending/confirmed;
  `slot` — вычисляемая колонка `tstzrange(starts_at, busy_until)`. Вставка в SAVEPOINT, нарушение → BookingError
- Статусы: pending (ждёт предоплату) → confirmed → completed | no_show; cancelled (cancelled_by client/master/admin/timeout)
- `services/jobs.py` — что наступило (FOR UPDATE SKIP LOCKED OF bookings); `bot/jobs.py` — отправка
- `bot/notify.py` — сообщения и Google Календарь при подтверждении/отмене; отмена в будущем → лист ожидания
- API: `api/routes.py`; кабинет `/api/staff/*` — мастер по `Master.tg_id`, админ по ADMIN_IDS
- `create_app(bot, dp)` принимает готовые бот и диспетчер (тесты): роутеры aiogram подключаются один раз

## Rules

- Все ответы и комментарии в коде на русском
- Код компактный, без лишних абстракций
- Всё асинхронно; HTTP — `httpx.AsyncClient`
- Секреты только через `.env`
- Зависимости только через `uv add`
- Перед изменением нескольких файлов — сначала показать план
- После изменений объяснять, что и зачем сделано (я учусь)
