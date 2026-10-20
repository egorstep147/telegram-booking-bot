"""Предоплата через Telegram Payments (ЮKassa). Запись ждёт оплату в статусе pending
hold_minutes минут; не оплатили — снимается фоновой задачей, слот освобождается."""

import logging

from aiogram import Bot, F, Router
from aiogram.types import LabeledPrice, Message, PreCheckoutQuery

from booking.bot import notify
from booking.config import settings
from booking.db import Session
from booking.db.models import Booking
from booking.niche import niche
from booking.services import bookings

log = logging.getLogger(__name__)
router = Router()


async def invoice_link(bot: Bot, b: Booking) -> str:
    return await bot.create_invoice_link(
        title=f"Предоплата: {b.service.name}"[:32],
        description=f"{niche().name}, запись №{b.id}. Оплатите в течение {niche().prepay.hold_minutes} минут."[:255],
        payload=f"booking:{b.id}",
        provider_token=settings.payment_token.get_secret_value(),
        currency="RUB",
        prices=[LabeledPrice(label="Предоплата", amount=(b.prepay - b.paid) * 100)],
    )


def _booking_id(payload: str) -> int:
    kind, _, bid = payload.partition(":")
    return int(bid) if kind == "booking" and bid.isdigit() else 0


@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery) -> None:
    async with Session() as s:
        b = await s.get(Booking, _booking_id(query.invoice_payload))
    ok = (
        b is not None
        and b.user_id == query.from_user.id
        and b.status == "pending"
        and query.currency == "RUB"
        and query.total_amount == (b.prepay - b.paid) * 100
    )
    if ok:
        await query.answer(ok=True)
    else:
        await query.answer(ok=False, error_message="Запись уже оплачена или снята — запишитесь заново")


@router.message(F.successful_payment)
async def paid(message: Message, bot: Bot) -> None:
    p = message.successful_payment
    async with Session() as s, s.begin():
        b = await bookings.mark_paid(
            s,
            _booking_id(p.invoice_payload),
            p.total_amount // 100,
            p.provider_payment_charge_id or p.telegram_payment_charge_id,
        )
    if b is None:
        log.warning("Оплата без ожидающей записи: %s — нужен возврат", p.invoice_payload)
        await message.answer("Оплата получена, но запись уже снята по времени. Мы вернём деньги — напишите нам.")
        for admin in settings.admin_ids:
            await notify.send(
                bot,
                admin,
                f"⚠️ Оплата {p.total_amount // 100} ₽ по снятой записи "
                f"{p.invoice_payload}, charge {p.provider_payment_charge_id} — сделайте возврат",
            )
        return
    await notify.confirmed(bot, b)
