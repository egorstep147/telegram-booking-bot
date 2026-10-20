"""Сообщения о записях клиенту, мастеру и админам + синхронизация с Google Календарём."""

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError
from sqlalchemy import update

from booking.config import settings
from booking.db import Session
from booking.db.models import Booking, User
from booking.niche import now
from booking.services import bookings, gcal, jobs

log = logging.getLogger(__name__)


async def send(bot: Bot, chat_id: int | None, text: str, **kw) -> bool:
    """Отправка, которая не роняет обработчик: клиент мог заблокировать бота."""
    if not chat_id:
        return False
    try:
        await bot.send_message(chat_id, text, **kw)
        return True
    except TelegramForbiddenError:
        async with Session() as s, s.begin():
            await s.execute(update(User).where(User.id == chat_id).values(blocked=True))
    except TelegramAPIError as e:
        log.warning("Не удалось написать %s: %s", chat_id, e)
    return False


async def _staff(bot: Bot, b: Booking, text: str) -> None:
    for chat_id in {b.master.tg_id, *settings.admin_ids} - {None}:
        await send(bot, chat_id, text)


async def confirmed(bot: Bot, b: Booking, *, rescheduled: bool = False) -> None:
    from booking.bot.keyboards import booking_kb

    head = "🔁 Запись перенесена" if rescheduled else "✅ Вы записаны!"
    await send(bot, b.user_id, f"{head}\n\n{bookings.text(b)}", reply_markup=booking_kb(b.id))
    who = f"{b.name}, {b.phone}" + (f"\n💬 {b.comment}" if b.comment else "")
    await _staff(bot, b, f"{'🔁 Перенос' if rescheduled else '🆕 Новая запись'}\n\n{bookings.text(b)}\n👤 {who}")
    if gcal.enabled() and b.master.gcal_id:
        event = await gcal.add_event(
            b.master.gcal_id,
            f"{b.service.name} — {b.name}",
            f"{b.phone}\n{b.comment}\nЗапись №{b.id}",
            b.starts_at,
            b.ends_at,
        )
        async with Session() as s, s.begin():
            await s.execute(update(Booking).where(Booking.id == b.id).values(gcal_event_id=event))


async def cancelled(bot: Bot, b: Booking, *, silent_client: bool = False) -> None:
    from booking.bot.keyboards import waitlist_kb

    if not silent_client and b.cancelled_by in ("master", "admin"):
        await send(
            bot,
            b.user_id,
            f"😔 Запись отменена салоном. Приносим извинения!\n\n{bookings.text(b)}"
            + ("\n\nПредоплату вернём в течение нескольких дней." if b.paid else ""),
        )
    if b.cancelled_by in ("client", "timeout") and not silent_client:
        await _staff(
            bot,
            b,
            f"✖️ Отмена ({'клиент' if b.cancelled_by == 'client' else 'не оплачено'})\n\n"
            f"{bookings.text(b)}\n👤 {b.name}, {b.phone}" + ("\n💳 Нужен возврат предоплаты" if b.paid else ""),
        )
    if gcal.enabled() and b.master.gcal_id and b.gcal_event_id:
        await gcal.delete_event(b.master.gcal_id, b.gcal_event_id)
    # Освободилось время в будущем — предлагаем ждавшим
    if b.starts_at > now():
        async with Session() as s, s.begin():
            entries = await jobs.waitlist_for(s, b)
        t = b.starts_at.astimezone(now().tzinfo)
        for e in entries:
            await send(
                bot,
                e.user_id,
                f"🎉 Освободилось время: {t:%d.%m в %H:%M}, {b.service.name}, {b.master.name}. "
                "Успейте записаться — предложение получили несколько человек.",
                reply_markup=waitlist_kb(b.service_id, b.master_id, int(t.timestamp())),
            )
