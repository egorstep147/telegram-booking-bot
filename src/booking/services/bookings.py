"""Запись, перенос, отмена, отметки мастера. Бот и API зовут только эти функции."""

import re
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from booking.db import AsyncSession
from booking.db.models import ACTIVE, Booking, Master, Service
from booking.niche import niche, now
from booking.services import schedule
from booking.services.schedule import BookingError

CANCELLABLE_BY = {"client", "master", "admin", "timeout"}


def clean_phone(text: str) -> str | None:
    phone = re.sub(r"[\s()\-]", "", text)
    return phone if re.fullmatch(r"\+?\d{10,15}", phone) else None


async def _pick_master(s: AsyncSession, candidates: list[int], day: date) -> int:
    """«Любой мастер»: берём того, у кого в этот день меньше записей — нагрузка распределяется ровнее."""
    start = datetime.combine(day, datetime.min.time(), now().tzinfo)
    rows = dict(
        (
            await s.execute(
                select(Booking.master_id, func.count())
                .where(
                    Booking.master_id.in_(candidates),
                    Booking.status.in_(ACTIVE),
                    Booking.starts_at >= start,
                    Booking.starts_at < start + timedelta(days=1),
                )
                .group_by(Booking.master_id)
            )
        ).all()
    )
    return min(candidates, key=lambda m: (rows.get(m, 0), candidates.index(m)))


async def _insert(s: AsyncSession, b: Booking) -> Booking:
    # SAVEPOINT: если база отвергнет запись (слот заняли параллельно), откатится только она
    try:
        async with s.begin_nested():
            s.add(b)
            await s.flush()
    except IntegrityError as e:
        if "no_double_booking" in str(e.orig):
            raise BookingError("Это время только что заняли — выберите другое") from None
        raise
    await s.refresh(b, ["master", "service"])  # для сообщений после закрытия сессии
    return b


async def create(
    s: AsyncSession,
    user_id: int,
    *,
    service_id: int,
    start: datetime,
    master_id: int | None = None,
    name: str,
    phone: str,
    comment: str = "",
) -> Booking:
    service = await s.get(Service, service_id)
    if service is None or not service.active:
        raise BookingError("Услуга не найдена")
    # Свободно ли время по графику (рабочие часы, запас «не раньше чем через час»)? Окончательно
    # пересечения проверит база — между этой проверкой и вставкой кто-то мог успеть записаться
    free = (await schedule.slots(s, service, start.astimezone(now().tzinfo).date(), master_id)).get(start)
    if not free:
        raise BookingError("Это время недоступно — выберите другое")
    mid = master_id or await _pick_master(s, free, start.astimezone(now().tzinfo).date())
    master = await s.get(Master, mid)
    price, duration = schedule.offer(master, service)
    prepay = niche().prepay_amount(price)
    end = start + timedelta(minutes=duration)
    return await _insert(
        s,
        Booking(
            user_id=user_id,
            master_id=mid,
            service_id=service.id,
            starts_at=start,
            ends_at=end,
            busy_until=end + timedelta(minutes=service.buffer),
            status="pending" if prepay else "confirmed",
            price=price,
            prepay=prepay,
            name=name.strip()[:60],
            phone=phone,
            comment=comment.strip()[:300],
        ),
    )


def can_change(b: Booking) -> bool:
    """Клиент может отменить или перенести запись не позже чем за cancel_before_hours."""
    return b.status in ACTIVE and b.starts_at - now() >= timedelta(hours=niche().cancel_before_hours)


async def cancel(s: AsyncSession, b: Booking, by: str) -> Booking:
    if b.status not in ACTIVE:
        raise BookingError("Запись уже отменена или прошла")
    if by == "client" and b.status == "confirmed" and not can_change(b):
        raise BookingError(f"Отменить можно не позже чем за {niche().cancel_before_hours} ч — позвоните нам")
    b.status, b.cancelled_by = "cancelled", by
    await s.flush()
    return b


async def reschedule(s: AsyncSession, b: Booking, start: datetime) -> Booking:
    """Перенос = отмена старой + новая запись в одной транзакции: не получилось — старая остаётся."""
    if not can_change(b):
        raise BookingError(f"Перенести можно не позже чем за {niche().cancel_before_hours} ч — позвоните нам")
    async with s.begin_nested():
        b.status, b.cancelled_by = "cancelled", "client"
        await s.flush()
        new = await create(
            s,
            b.user_id,
            service_id=b.service_id,
            start=start,
            master_id=b.master_id,
            name=b.name,
            phone=b.phone,
            comment=b.comment,
        )
        # Оплата переезжает вместе с записью
        new.paid, new.charge_id, new.prepay = b.paid, b.charge_id, max(new.prepay, b.paid)
        new.status = "confirmed" if new.paid >= new.prepay else "pending"
    return new


async def mark(s: AsyncSession, b: Booking, status: str) -> Booking:
    """Отметка мастера после визита: пришёл / не пришёл."""
    if status not in ("completed", "no_show") or b.status not in ("confirmed", "completed", "no_show"):
        raise BookingError("Нельзя поставить такой статус")
    if b.starts_at > now():
        raise BookingError("Визит ещё не начался")
    b.status = status
    if status == "completed" and b.service.rebook_weeks:
        b.rebook_at = b.starts_at + timedelta(weeks=b.service.rebook_weeks)
    return b


async def mark_paid(s: AsyncSession, booking_id: int, amount: int, charge_id: str) -> Booking | None:
    # FOR UPDATE только по bookings: к LEFT JOIN-подгрузке мастера и услуги блокировку не применить
    b = await s.scalar(select(Booking).where(Booking.id == booking_id).with_for_update(of=Booking))
    if b is None or b.status != "pending":
        return None  # повтор апдейта или запись уже снята по таймауту
    b.paid, b.charge_id, b.status = b.paid + amount, charge_id, "confirmed"
    return b


async def of_user(s: AsyncSession, user_id: int, *, upcoming: bool = True) -> list[Booking]:
    q = select(Booking).where(Booking.user_id == user_id)
    q = q.where(Booking.status.in_(ACTIVE), Booking.ends_at > now()) if upcoming else q
    return list(await s.scalars(q.order_by(Booking.starts_at if upcoming else Booking.starts_at.desc()).limit(20)))


async def of_master(s: AsyncSession, master_id: int, day: date) -> list[Booking]:
    start = datetime.combine(day, datetime.min.time(), now().tzinfo)
    q = select(Booking).where(
        Booking.master_id == master_id,
        Booking.status != "cancelled",
        Booking.starts_at >= start,
        Booking.starts_at < start + timedelta(days=1),
    )
    return list(await s.scalars(q.order_by(Booking.starts_at)))


WEEKDAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
STATUS = {
    "pending": "💳 Ждёт оплаты",
    "confirmed": "✅ Подтверждена",
    "completed": "✔️ Состоялась",
    "no_show": "🚫 Неявка",
    "cancelled": "✖️ Отменена",
}


def text(b: Booking) -> str:
    n, t = niche(), b.starts_at.astimezone(now().tzinfo)
    lines = [
        f"Запись №{b.id} · {STATUS[b.status]}",
        f"📅 {t:%d.%m} ({WEEKDAYS[t.weekday()]}) {t:%H:%M}–{b.ends_at.astimezone(now().tzinfo):%H:%M}",
        f"{b.service.emoji} {b.service.name} — {b.price} ₽",
        f"👤 {n.master_word}: {b.master.name}",
    ]
    if b.master.branch.address:
        lines.append(f"📍 {b.master.branch.address}")
    if b.prepay:
        lines.append(f"💳 Предоплата {b.prepay} ₽" + (" — оплачено" if b.paid >= b.prepay else ""))
    return "\n".join(lines)
