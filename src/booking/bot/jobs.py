"""Фоновый цикл: раз в 30 секунд обрабатывает всё, что наступило, и отправляет сообщения."""

import asyncio
import logging

from aiogram import Bot

from booking.bot import keyboards as kb
from booking.bot import notify
from booking.db import Session
from booking.niche import niche, now
from booking.services import bookings, jobs

log = logging.getLogger(__name__)


def _when(minutes: int) -> str:
    return "завтра" if minutes >= 12 * 60 else f"через {minutes // 60} ч" if minutes >= 60 else f"через {minutes} мин"


async def tick(bot: Bot) -> None:
    # Каждый шаг — в своей транзакции: ошибка отправки не откатит другие изменения
    async with Session() as s, s.begin():
        expired = await jobs.expire_pending(s)
    for b in expired:
        await notify.send(bot, b.user_id, "⌛ Запись снята: предоплата не поступила вовремя. Можно записаться снова.")
        await notify.cancelled(bot, b, silent_client=True)

    async with Session() as s, s.begin():
        due = await jobs.due_reminders(s)
    for b, _stage in due:
        left = round((b.starts_at - now()).total_seconds() / 60)  # сколько реально осталось, а не ступень
        await notify.send(
            bot,
            b.user_id,
            f"⏰ Напоминаем: визит {_when(left)}\n\n{bookings.text(b)}",
            reply_markup=kb.reminder_kb(b.id),
        )

    async with Session() as s, s.begin():
        finished = await jobs.finish_visits(s)
    for b in finished:
        await notify.send(
            bot,
            b.user_id,
            f"Как прошёл визит к {b.master.name}? Оцените, пожалуйста 🙏",
            reply_markup=kb.review_kb(b.id),
        )

    async with Session() as s, s.begin():
        rebook = await jobs.due_rebook(s)
    for b in rebook:
        await notify.send(
            bot,
            b.user_id,
            f"{b.service.emoji} Пора снова на «{b.service.name}»! {niche().master_word} {b.master.name} ждёт вас.",
            reply_markup=kb.rebook_kb(b.service_id, b.master_id),
        )


async def loop(bot: Bot) -> None:
    while True:
        try:
            await tick(bot)
        except Exception:
            log.exception("Ошибка фоновых задач")
        await asyncio.sleep(30)
