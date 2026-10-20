"""JSON API мини-приложения: каталог, свободное время, записи клиента, лист ожидания, кабинет мастера."""

from datetime import date, datetime, timedelta

from aiogram import Bot
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from booking.api.deps import DB, Staff, UserId
from booking.bot import notify
from booking.bot.payments import invoice_link
from booking.db.models import Booking, Master, Review, Service, TimeOff, WaitlistEntry
from booking.niche import niche, now, tz
from booking.services import bookings, schedule, users
from booking.services.schedule import BookingError

router = APIRouter(prefix="/api")


class BookingIn(BaseModel):
    service_id: int
    master_id: int | None = None  # None — любой свободный
    start: datetime
    name: str = Field(min_length=1, max_length=60)
    phone: str = Field(max_length=30)
    comment: str = Field("", max_length=300)


class RescheduleIn(BaseModel):
    start: datetime


class WaitlistIn(BaseModel):
    service_id: int
    master_id: int | None = None
    day: date


class StatusIn(BaseModel):
    status: str


class TimeOffIn(BaseModel):
    master_id: int | None = None  # админ указывает мастера, мастер — только себя
    starts_at: datetime
    ends_at: datetime
    reason: str = Field("", max_length=100)


def _bot(request: Request) -> Bot:
    return request.app.state.bot


def _booking(b: Booking) -> dict:
    return {
        "id": b.id,
        "status": b.status,
        "status_label": bookings.STATUS[b.status],
        "start": b.starts_at.isoformat(),
        "end": b.ends_at.isoformat(),
        "service": {"id": b.service_id, "name": b.service.name, "emoji": b.service.emoji},
        "master": {"id": b.master_id, "name": b.master.name, "photo": b.master.photo},
        "address": b.master.branch.address,
        "price": b.price,
        "prepay": b.prepay,
        "paid": b.paid,
        "can_change": bookings.can_change(b),
        "name": b.name,
        "phone": b.phone,
        "comment": b.comment,
    }


async def _own(s, uid: int, booking_id: int) -> Booking:
    b = await s.get(Booking, booking_id)
    if b is None or b.user_id != uid:
        raise HTTPException(404, "Запись не найдена")
    return b


# ---------- Каталог и свободное время (без авторизации) ----------


@router.get("/config")
async def config() -> dict:
    n = niche()
    return n.model_dump(
        include={
            "name",
            "tagline",
            "emoji",
            "accent",
            "address",
            "phone",
            "master_word",
            "cancel_before_hours",
            "waitlist",
            "max_days_ahead",
        }
    ) | {"timezone": n.timezone, "prepay": n.prepay.model_dump(), "today": now().date().isoformat()}


@router.get("/catalog")
async def catalog(s: DB) -> dict:
    services = list(await s.scalars(select(Service).where(Service.active).order_by(Service.sort)))
    masters = list((await s.scalars(select(Master).where(Master.active).order_by(Master.sort))).unique())
    ratings = dict(
        (await s.execute(select(Review.master_id, func.avg(Review.rating)).group_by(Review.master_id))).all()
    )
    counts = dict((await s.execute(select(Review.master_id, func.count()).group_by(Review.master_id))).all())
    return {
        "services": [
            {
                "id": x.id,
                "name": x.name,
                "category": x.category,
                "description": x.description,
                "emoji": x.emoji,
                "duration": x.duration,
                "price": x.price,
            }
            for x in services
        ],
        "masters": [
            {
                "id": m.id,
                "name": m.name,
                "title": m.title,
                "bio": m.bio,
                "photo": m.photo,
                "branch": m.branch.name,
                "address": m.branch.address,
                "rating": round(float(ratings[m.id]), 1) if m.id in ratings else None,
                "reviews": counts.get(m.id, 0),
                "offers": {ms.service_id: {"price": ms.price, "duration": ms.duration} for ms in m.services},
            }
            for m in masters
        ],
    }


async def _service(s, service_id: int) -> Service:
    svc = await s.get(Service, service_id)
    if svc is None or not svc.active:
        raise HTTPException(404, "Услуга не найдена")
    return svc


@router.get("/days")
async def days(s: DB, service_id: int, master_id: int | None = None) -> list[dict]:
    return [
        {"date": d.isoformat(), "free": n} for d, n in await schedule.days(s, await _service(s, service_id), master_id)
    ]


@router.get("/slots")
async def slots(s: DB, service_id: int, day: date, master_id: int | None = None) -> list[dict]:
    free = await schedule.slots(s, await _service(s, service_id), day, master_id)
    return [{"start": t.isoformat(), "time": t.strftime("%H:%M"), "masters": m} for t, m in free.items()]


# ---------- Записи клиента ----------


@router.post("/bookings")
async def create(s: DB, uid: UserId, body: BookingIn, request: Request) -> dict:
    phone = bookings.clean_phone(body.phone)
    if phone is None:
        raise BookingError("Не похоже на номер телефона")
    await users.upsert(s, uid, phone=phone)
    b = await bookings.create(
        s,
        uid,
        service_id=body.service_id,
        master_id=body.master_id,
        start=body.start,
        name=body.name,
        phone=phone,
        comment=body.comment,
    )
    await s.commit()  # до счёта и сообщений: оплата не должна прийти раньше, чем запись появится в базе
    await s.refresh(b)
    if b.status == "pending":
        return {"booking": _booking(b), "invoice": await invoice_link(_bot(request), b)}
    await notify.confirmed(_bot(request), b)
    return {"booking": _booking(b)}


@router.get("/bookings")
async def mine(s: DB, uid: UserId, past: bool = False) -> list[dict]:
    return [_booking(b) for b in await bookings.of_user(s, uid, upcoming=not past)]


@router.post("/bookings/{booking_id}/cancel")
async def cancel(s: DB, uid: UserId, booking_id: int, request: Request) -> dict:
    b = await bookings.cancel(s, await _own(s, uid, booking_id), "client")
    await s.commit()
    await notify.cancelled(_bot(request), b)
    return _booking(b)


@router.post("/bookings/{booking_id}/reschedule")
async def reschedule(s: DB, uid: UserId, booking_id: int, body: RescheduleIn, request: Request) -> dict:
    old = await _own(s, uid, booking_id)
    new = await bookings.reschedule(s, old, body.start)
    await s.commit()
    await s.refresh(new)
    await notify.cancelled(_bot(request), old, silent_client=True)
    if new.status == "pending":
        return {"booking": _booking(new), "invoice": await invoice_link(_bot(request), new)}
    await notify.confirmed(_bot(request), new, rescheduled=True)
    return {"booking": _booking(new)}


@router.post("/bookings/{booking_id}/invoice")
async def pay_again(s: DB, uid: UserId, booking_id: int, request: Request) -> dict:
    b = await _own(s, uid, booking_id)
    if b.status != "pending":
        raise BookingError("Эту запись оплачивать не нужно")
    return {"invoice": await invoice_link(_bot(request), b)}


@router.post("/waitlist")
async def waitlist(s: DB, uid: UserId, body: WaitlistIn) -> dict:
    if not niche().waitlist:
        raise BookingError("Лист ожидания выключен")
    await _service(s, body.service_id)
    entry = await s.scalar(
        select(WaitlistEntry).where(
            WaitlistEntry.user_id == uid, WaitlistEntry.service_id == body.service_id, WaitlistEntry.day == body.day
        )
    )
    if entry is None:
        await users.upsert(s, uid)
        s.add(WaitlistEntry(user_id=uid, service_id=body.service_id, master_id=body.master_id, day=body.day))
    else:
        entry.active, entry.master_id = True, body.master_id
    return {"ok": True}


# ---------- Кабинет мастера ----------


@router.get("/staff/me")
async def staff_me(s: DB, master: Staff) -> dict:
    masters = [master] if master else list((await s.scalars(select(Master).where(Master.active))).unique())
    return {"admin": master is None, "masters": [{"id": m.id, "name": m.name, "photo": m.photo} for m in masters]}


def _check_master(master: Master | None, master_id: int) -> None:
    if master is not None and master.id != master_id:
        raise HTTPException(403, "Это расписание другого мастера")


@router.get("/staff/schedule")
async def staff_schedule(s: DB, master: Staff, master_id: int, day: date) -> dict:
    _check_master(master, master_id)
    start = datetime.combine(day, datetime.min.time(), tz())
    offs = await s.scalars(
        select(TimeOff)
        .where(TimeOff.master_id == master_id, TimeOff.starts_at < start + timedelta(days=1), TimeOff.ends_at > start)
        .order_by(TimeOff.starts_at)
    )
    return {
        "bookings": [_booking(b) for b in await bookings.of_master(s, master_id, day)],
        "time_off": [
            {"id": t.id, "start": t.starts_at.isoformat(), "end": t.ends_at.isoformat(), "reason": t.reason}
            for t in offs
        ],
    }


@router.post("/staff/bookings/{booking_id}/status")
async def staff_status(s: DB, master: Staff, booking_id: int, body: StatusIn, request: Request) -> dict:
    b = await s.get(Booking, booking_id)
    if b is None:
        raise HTTPException(404, "Запись не найдена")
    _check_master(master, b.master_id)
    if body.status == "cancelled":
        b = await bookings.cancel(s, b, "master" if master else "admin")
        await s.commit()
        await notify.cancelled(_bot(request), b)
    else:
        b = await bookings.mark(s, b, body.status)
    return _booking(b)


@router.post("/staff/time-off")
async def add_time_off(s: DB, master: Staff, body: TimeOffIn) -> dict:
    master_id = master.id if master else body.master_id
    if master_id is None or body.ends_at <= body.starts_at:
        raise BookingError("Укажите мастера и интервал")
    t = TimeOff(master_id=master_id, starts_at=body.starts_at, ends_at=body.ends_at, reason=body.reason)
    s.add(t)
    await s.flush()
    return {"id": t.id}


@router.delete("/staff/time-off/{time_off_id}")
async def delete_time_off(s: DB, master: Staff, time_off_id: int) -> dict:
    t = await s.get(TimeOff, time_off_id)
    if t is None:
        raise HTTPException(404)
    _check_master(master, t.master_id)
    await s.delete(t)
    return {"ok": True}
