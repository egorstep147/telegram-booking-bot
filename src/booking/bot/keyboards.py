from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder

from booking.config import settings
from booking.niche import niche


def app_button(text: str, path: str = "") -> InlineKeyboardButton | None:
    """Кнопка, открывающая мини-приложение (сразу на нужном экране через #путь)."""
    if not settings.webapp_url:
        return None
    return InlineKeyboardButton(text=text, web_app=WebAppInfo(url=settings.webapp_url.rstrip("/") + "/" + path))


def _kb(*rows: list[InlineKeyboardButton | None]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for row in rows:
        if buttons := [x for x in row if x]:
            b.row(*buttons)
    return b.as_markup()


def start_kb(is_staff: bool) -> InlineKeyboardMarkup:
    return _kb(
        [app_button(f"{niche().emoji} Записаться")],
        [InlineKeyboardButton(text="📋 Мои записи", callback_data="my")],
        [app_button("🗓 Кабинет мастера", "#staff")] if is_staff else [],
    )


def booking_kb(booking_id: int) -> InlineKeyboardMarkup:
    return _kb(
        [
            app_button("🔁 Перенести", f"#booking/{booking_id}"),
            InlineKeyboardButton(text="✖️ Отменить", callback_data=f"bx:{booking_id}"),
        ]
    )


def reminder_kb(booking_id: int) -> InlineKeyboardMarkup:
    return _kb(
        [InlineKeyboardButton(text="✅ Приду", callback_data=f"bc:{booking_id}")],
        [
            app_button("🔁 Перенести", f"#booking/{booking_id}"),
            InlineKeyboardButton(text="✖️ Отменить", callback_data=f"bx:{booking_id}"),
        ],
    )


def confirm_cancel_kb(booking_id: int) -> InlineKeyboardMarkup:
    return _kb(
        [
            InlineKeyboardButton(text="Да, отменить", callback_data=f"bxy:{booking_id}"),
            InlineKeyboardButton(text="Нет", callback_data="noop"),
        ]
    )


def review_kb(booking_id: int) -> InlineKeyboardMarkup:
    return _kb(
        [InlineKeyboardButton(text="⭐" * n, callback_data=f"rv:{booking_id}:{n}") for n in (1, 2, 3)],
        [InlineKeyboardButton(text="⭐" * n, callback_data=f"rv:{booking_id}:{n}") for n in (4, 5)],
    )


def waitlist_kb(service_id: int, master_id: int, ts: int) -> InlineKeyboardMarkup:
    return _kb(
        [InlineKeyboardButton(text="✅ Записаться", callback_data=f"wl:{service_id}:{master_id}:{ts}")],
        [app_button("Выбрать другое время")],
    )


def rebook_kb(service_id: int, master_id: int) -> InlineKeyboardMarkup:
    return _kb([app_button("📅 Выбрать время", f"#book/{service_id}/{master_id}")])
