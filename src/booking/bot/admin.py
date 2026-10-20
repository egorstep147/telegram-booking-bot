"""Админка в боте: записи на сегодня, статистика (выручка, загрузка, неявки, рейтинг), рассылка."""

import asyncio
import logging
from datetime import datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import func, select

from booking.bot import keyboards as kb
from booking.config import settings
from booking.db import AsyncSession, Session
from booking.db.models import Booking, Master, Review, TimeOff, User
from booking.niche import niche, now, tz
from booking.services import bookings
from booking.services.slots import work_intervals

log = logging.getLogger(__name__)
router = Router()
router.message.filter(F.from_user.id.in_(settings.admin_ids))
router.callback_query.filter(F.from_user.id.in_(settings.admin_ids))
_tasks: set[asyncio.Task] = set()


class Broadcast(StatesGroup):
    text = State()


async def _today(s: AsyncSession) -> str:
    lines = [f"📅 Сегодня, {now():%d.%m}"]
    for m in (await s.scalars(select(Master).where(Master.active).order_by(Master.sort))).unique():
        day = await bookings.of_master(s, m.id, now().date())
        lines.append(f"\n{m.photo} {m.name}: {len(day)} записей")
        for b in day:
            t = b.starts_at.astimezone(tz())
            lines.append(f"  {t:%H:%M} {b.service.name} — {b.name} {bookings.STATUS[b.status].split()[0]}")
    return "\n".join(lines)


async def stats(s: AsyncSession, days: int = 30) -> dict:
    """Выручка состоявшихся, доля неявок, загрузка мастеров (занятые минуты / рабочие), средний рейтинг."""
    end = datetime.combine(now().date(), datetime.min.time(), tz()) + timedelta(days=1)
    start = end - timedelta(days=days)
    rows = (
        await s.execute(
            select(Booking.status, func.count(), func.coalesce(func.sum(Booking.price), 0))
            .where(Booking.starts_at >= start, Booking.starts_at < end)
            .group_by(Booking.status)
        )
    ).all()
    by = {st: (n, total) for st, n, total in rows}
    done, noshow = by.get("completed", (0, 0)), by.get("no_show", (0, 0))
    load = {}
    for m in (await s.scalars(select(Master).where(Master.active))).unique():
        work = sum(
            (b - a).total_seconds()
            for d in range(days)
            for a, b in work_intervals(
                [(r.weekday, r.start, r.end) for r in m.rules], (start + timedelta(days=d)).date(), tz()
            )
        )
        off = (
            await s.execute(
                select(func.coalesce(func.sum(func.extract("epoch", TimeOff.ends_at - TimeOff.starts_at)), 0)).where(
                    TimeOff.master_id == m.id, TimeOff.starts_at >= start, TimeOff.ends_at <= end
                )
            )
        ).scalar()
        busy = (
            await s.execute(
                select(func.coalesce(func.sum(func.extract("epoch", Booking.ends_at - Booking.starts_at)), 0)).where(
                    Booking.master_id == m.id,
                    Booking.status.in_(("completed", "confirmed", "no_show")),
                    Booking.starts_at >= start,
                    Booking.starts_at < end,
                )
            )
        ).scalar()
        available = work - float(off)
        load[m.name] = round(100 * float(busy) / available) if available > 0 else 0
    rating = (await s.execute(select(func.avg(Review.rating), func.count()))).one()
    return {
        "completed": done[0],
        "revenue": int(done[1]),
        "no_show": noshow[0],
        "no_show_rate": round(100 * noshow[0] / (done[0] + noshow[0])) if done[0] + noshow[0] else 0,
        "cancelled": by.get("cancelled", (0, 0))[0],
        "load": load,
        "rating": round(float(rating[0]), 2) if rating[0] else None,
        "reviews": rating[1],
    }


def _menu():
    b = InlineKeyboardBuilder()
    b.button(text="📅 Сегодня", callback_data="adm:today")
    b.button(text="📊 Статистика 30 дней", callback_data="adm:stats")
    b.button(text="📣 Рассылка", callback_data="adm:broadcast")
    if button := kb.app_button("🗓 Кабинет", "#staff"):
        b.row(button)
    b.adjust(2, 1, 1)
    return b.as_markup()


@router.message(Command("admin"))
async def admin(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(f"🛠 {niche().name}", reply_markup=_menu())


@router.callback_query(F.data == "adm:today")
async def today(callback: CallbackQuery) -> None:
    async with Session() as s:
        await callback.message.answer(await _today(s))
    await callback.answer()


@router.callback_query(F.data == "adm:stats")
async def show_stats(callback: CallbackQuery) -> None:
    async with Session() as s:
        st = await stats(s)
        clients = await s.scalar(select(func.count()).select_from(User))
    load = "\n".join(f"  {name}: {pct}%" for name, pct in st["load"].items())
    await callback.message.answer(
        f"📊 За 30 дней\nСостоялось: {st['completed']} · выручка {st['revenue']:,} ₽\n".replace(",", " ")
        + f"Неявки: {st['no_show']} ({st['no_show_rate']}%) · отмены: {st['cancelled']}\n"
        + f"Рейтинг: {st['rating'] or '—'} ({st['reviews']} отзывов) · клиентов в базе: {clients}\n"
        + f"Загрузка мастеров:\n{load}"
    )
    await callback.answer()


@router.callback_query(F.data == "adm:broadcast")
async def broadcast(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Broadcast.text)
    await callback.message.answer("Пришлите сообщение для рассылки клиентам. /admin — отмена")
    await callback.answer()


@router.message(Broadcast.text)
async def broadcast_preview(message: Message, state: FSMContext) -> None:
    await state.update_data(chat_id=message.chat.id, message_id=message.message_id)
    b = InlineKeyboardBuilder()
    b.button(text="✅ Отправить всем", callback_data="bc_go")
    b.button(text="✖️ Отмена", callback_data="bc_no")
    await message.answer("Разослать это сообщение всем клиентам?", reply_markup=b.as_markup())


@router.callback_query(F.data.in_({"bc_go", "bc_no"}))
async def broadcast_go(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    await state.clear()
    if callback.data == "bc_no" or not data:
        await callback.message.edit_text("Рассылка отменена")
        return
    await callback.message.edit_text("📣 Рассылка запущена")
    task = asyncio.create_task(_send_all(bot, callback.from_user.id, data["chat_id"], data["message_id"]))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def _send_all(bot: Bot, admin_id: int, chat_id: int, message_id: int) -> None:
    async with Session() as s:
        ids = list(await s.scalars(select(User.id).where(User.blocked.is_(False))))
    ok = 0
    for uid in ids:
        try:
            await bot.copy_message(uid, chat_id, message_id)
            ok += 1
        except Exception as e:  # noqa: BLE001
            log.info("Рассылка: %s недоступен (%s)", uid, e)
        await asyncio.sleep(0.05)
    await bot.send_message(admin_id, f"📣 Доставлено {ok} из {len(ids)}")
