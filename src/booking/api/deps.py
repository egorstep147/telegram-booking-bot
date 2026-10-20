from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Annotated

from aiogram.utils.web_app import safe_parse_webapp_init_data
from fastapi import Depends, Header, HTTPException
from sqlalchemy import select

from booking.config import settings
from booking.db import AsyncSession, Session
from booking.db.models import Master


async def get_session() -> AsyncIterator[AsyncSession]:
    """Сессия на запрос: обработчик отработал — commit, упал — откат при закрытии."""
    async with Session() as s:
        yield s
        await s.commit()


def get_user_id(authorization: Annotated[str, Header()] = "") -> int:
    """Пользователь по подписи Telegram (initData) — подделать без токена бота нельзя."""
    if not authorization.startswith("tma "):
        raise HTTPException(401, "Откройте запись из Telegram")
    try:
        data = safe_parse_webapp_init_data(settings.bot_token.get_secret_value(), authorization[4:])
    except ValueError:
        raise HTTPException(401, "Неверная подпись Telegram") from None
    if data.user is None or datetime.now(UTC) - data.auth_date > timedelta(days=1):
        raise HTTPException(401, "Сессия устарела, откройте приложение заново")
    return data.user.id


DB = Annotated[AsyncSession, Depends(get_session)]
UserId = Annotated[int, Depends(get_user_id)]


async def get_staff(s: DB, uid: UserId) -> Master | None:
    """Кабинет: мастер видит своё расписание; админ — любого мастера (master=None)."""
    master = await s.scalar(select(Master).where(Master.tg_id == uid, Master.active))
    if master is None and uid not in settings.admin_ids:
        raise HTTPException(403, "Кабинет доступен только мастерам")
    return master


Staff = Annotated[Master | None, Depends(get_staff)]
