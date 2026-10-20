"""Фоновые задачи: что пора сделать прямо сейчас. Функции меняют статусы и возвращают записи,
а отправкой сообщений занимается бот (bot/jobs.py). FOR UPDATE SKIP LOCKED — если процессов два,
одно событие не обработается дважды."""

from datetime import timedelta

from sqlalchemy import select

from booking.db import AsyncSession
from booking.db.models import Booking, WaitlistEntry
from booking.niche import niche, now


def _locked(q):
    return q.with_for_update(of=Booking, skip_locked=True).limit(200)


async def expire_pending(s: AsyncSession) -> list[Booking]:
    """Не оплатили предоплату вовремя — запись снимается, слот свободен."""
    deadline = now() - timedelta(minutes=niche().prepay.hold_minutes)
    rows = list(
        await s.scalars(_locked(select(Booking).where(Booking.status == "pending", Booking.created_at < deadline)))
    )
    for b in rows:
        b.status, b.cancelled_by = "cancelled", "timeout"
    return rows


async def due_reminders(s: AsyncSession) -> list[tuple[Booking, int]]:
    """(запись, за сколько минут напоминание). reminded — сколько ступеней уже ушло, повторов нет."""
    stages = sorted(niche().reminders, reverse=True)  # [1440, 120]: сначала за сутки, потом за 2 часа
    horizon = now() + timedelta(minutes=stages[0]) if stages else now()
    rows = list(
        await s.scalars(
            _locked(
                select(Booking).where(
                    Booking.status == "confirmed",
                    Booking.starts_at > now(),
                    Booking.starts_at <= horizon,
                    Booking.reminded < len(stages),
                )
            )
        )
    )
    out = []
    for b in rows:
        left = (b.starts_at - now()).total_seconds() / 60
        # Записались за час до визита — напоминание «за сутки» не шлём, сразу ставим нужную ступень
        due = [i for i, m in enumerate(stages) if left <= m and i >= b.reminded]
        if due:
            b.reminded = due[-1] + 1
            out.append((b, stages[due[-1]]))
    return out


async def finish_visits(s: AsyncSession) -> list[Booking]:
    """Визит прошёл — считаем состоявшимся (мастер может поправить на «не пришёл») и просим отзыв."""
    edge = now() - timedelta(minutes=niche().review_after_minutes)
    rows = list(await s.scalars(_locked(select(Booking).where(Booking.status == "confirmed", Booking.ends_at < edge))))
    for b in rows:
        b.status, b.review_asked = "completed", True
        if b.service.rebook_weeks:
            b.rebook_at = b.starts_at + timedelta(weeks=b.service.rebook_weeks)
    return rows


async def due_rebook(s: AsyncSession) -> list[Booking]:
    rows = list(
        await s.scalars(_locked(select(Booking).where(Booking.rebook_at.is_not(None), Booking.rebook_at <= now())))
    )
    for b in rows:
        b.rebook_at = None
    return rows


async def waitlist_for(s: AsyncSession, b: Booking) -> list[WaitlistEntry]:
    """Освободилось время — кто ждал эту услугу в этот день (у этого мастера или у любого)."""
    day = b.starts_at.astimezone(now().tzinfo).date()
    q = (
        select(WaitlistEntry)
        .where(
            WaitlistEntry.active,
            WaitlistEntry.service_id == b.service_id,
            WaitlistEntry.day == day,
            (WaitlistEntry.master_id.is_(None)) | (WaitlistEntry.master_id == b.master_id),
            WaitlistEntry.user_id != b.user_id,
        )
        .order_by(WaitlistEntry.created_at)
        .limit(3)
    )
    entries = list(await s.scalars(q))
    for e in entries:
        e.active = False  # одно предложение на заявку — без спама
    return entries
