"""Бот для клиента: вход в запись, мои записи, отмена, ответы на напоминания, отзывы, лист ожидания.
Выбор услуги и времени — в мини-приложении."""

from datetime import datetime

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select

from booking.bot import keyboards as kb
from booking.bot import notify
from booking.config import settings
from booking.db import Session
from booking.db.models import Booking, Master, Review, User
from booking.niche import niche, tz
from booking.services import bookings, users
from booking.services.schedule import BookingError

router = Router()


class ReviewText(StatesGroup):
    waiting = State()


async def _is_staff(user_id: int) -> bool:
    async with Session() as s:
        return (
            user_id in settings.admin_ids
            or await s.scalar(select(Master.id).where(Master.tg_id == user_id)) is not None
        )


@router.message(CommandStart())
async def start(message: Message) -> None:
    u = message.from_user
    async with Session() as s, s.begin():
        await users.upsert(s, u.id, u.first_name, u.username)
    await message.answer(niche().welcome, reply_markup=kb.start_kb(await _is_staff(u.id)))


async def _my_text(user_id: int) -> list[tuple[str, int]]:
    async with Session() as s:
        return [(bookings.text(b), b.id) for b in await bookings.of_user(s, user_id)]


@router.message(Command("my"))
async def my(message: Message) -> None:
    await _send_my(message, message.from_user.id)


@router.callback_query(F.data == "my")
async def my_button(callback: CallbackQuery) -> None:
    await _send_my(callback.message, callback.from_user.id)
    await callback.answer()


async def _send_my(message: Message, user_id: int) -> None:
    items = await _my_text(user_id)
    if not items:
        await message.answer("Предстоящих записей нет.", reply_markup=kb.start_kb(False))
    for text, bid in items:
        await message.answer(text, reply_markup=kb.booking_kb(bid))


# ---------- Отмена и подтверждение ----------


async def _own(user_id: int, booking_id: int) -> Booking | None:
    async with Session() as s:
        b = await s.get(Booking, booking_id)
    return b if b and b.user_id == user_id else None


@router.callback_query(F.data.startswith("bx:"))
async def ask_cancel(callback: CallbackQuery) -> None:
    b = await _own(callback.from_user.id, int(callback.data[3:]))
    if b is None or b.status not in ("pending", "confirmed"):
        await callback.answer("Запись уже неактуальна", show_alert=True)
        return
    await callback.message.answer(f"Отменить запись?\n\n{bookings.text(b)}", reply_markup=kb.confirm_cancel_kb(b.id))
    await callback.answer()


@router.callback_query(F.data.startswith("bxy:"))
async def do_cancel(callback: CallbackQuery, bot: Bot) -> None:
    try:
        async with Session() as s, s.begin():
            b = await s.get(Booking, int(callback.data[4:]))
            if b is None or b.user_id != callback.from_user.id:
                raise BookingError("Запись не найдена")
            b = await bookings.cancel(s, b, "client")
    except BookingError as e:
        await callback.answer(str(e), show_alert=True)
        return
    await callback.message.edit_text("✖️ Запись отменена. Будем рады видеть вас снова!")
    await notify.cancelled(bot, b)


@router.callback_query(F.data.startswith("bc:"))
async def client_confirms(callback: CallbackQuery) -> None:
    async with Session() as s, s.begin():
        b = await s.get(Booking, int(callback.data[3:]))
        if b and b.user_id == callback.from_user.id:
            b.client_confirmed = True
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer("Спасибо, ждём вас!")


@router.callback_query(F.data == "noop")
async def noop(callback: CallbackQuery) -> None:
    await callback.message.delete()
    await callback.answer()


# ---------- Отзывы ----------


@router.callback_query(F.data.startswith("rv:"))
async def rate(callback: CallbackQuery, state: FSMContext) -> None:
    _, bid, rating = callback.data.split(":")
    async with Session() as s, s.begin():
        b = await s.get(Booking, int(bid))
        if (
            b is None
            or b.user_id != callback.from_user.id
            or await s.scalar(select(Review.id).where(Review.booking_id == b.id))
        ):
            await callback.answer("Отзыв уже оставлен", show_alert=True)
            return
        s.add(Review(booking_id=b.id, user_id=b.user_id, master_id=b.master_id, rating=int(rating)))
    await callback.message.edit_text(
        f"Спасибо за оценку {'⭐' * int(rating)}! Напишите пару слов о визите или нажмите /skip."
    )
    await state.set_state(ReviewText.waiting)
    await state.update_data(booking_id=b.id)
    await callback.answer()


@router.message(ReviewText.waiting, Command("skip"))
async def skip_review(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Хорошо! До встречи 👋")


@router.message(ReviewText.waiting, F.text)
async def review_text(message: Message, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    await state.clear()
    async with Session() as s, s.begin():
        r = await s.scalar(select(Review).where(Review.booking_id == data["booking_id"]))
        if r:
            r.text = message.text[:1000]
            master = await s.get(Master, r.master_id)
    await message.answer("Спасибо за отзыв! 💛")
    if r:
        stars = "⭐" * r.rating
        for chat_id in {master.tg_id, *settings.admin_ids} - {None}:
            await notify.send(bot, chat_id, f"💬 Отзыв о {master.name} {stars}\n{r.text}")


# ---------- Лист ожидания: запись в одно нажатие ----------


@router.callback_query(F.data.startswith("wl:"))
async def waitlist_book(callback: CallbackQuery, bot: Bot) -> None:
    _, service_id, master_id, ts = callback.data.split(":")
    async with Session() as s:
        user = await s.get(User, callback.from_user.id)
    if user is None or not user.phone:
        await callback.answer("Откройте приложение, чтобы записаться", show_alert=True)
        return
    try:
        async with Session() as s, s.begin():
            b = await bookings.create(
                s,
                user.id,
                service_id=int(service_id),
                master_id=int(master_id),
                start=datetime.fromtimestamp(int(ts), tz()),
                name=user.first_name or "Клиент",
                phone=user.phone,
            )
    except BookingError as e:
        await callback.answer(f"Не успели: {e}", show_alert=True)
        return
    await callback.message.edit_reply_markup(reply_markup=None)
    if b.status == "pending":
        from booking.bot.payments import invoice_link

        pay = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text=f"💳 Оплатить {b.prepay} ₽", url=await invoice_link(bot, b))]]
        )
        await callback.message.answer(
            f"Время за вами! Внесите предоплату {b.prepay} ₽ в течение {niche().prepay.hold_minutes} минут.",
            reply_markup=pay,
        )
    else:
        await notify.confirmed(bot, b)
    await callback.answer()
