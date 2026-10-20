"""Запись с настоящей базой: правила, двойная запись, перенос, отмена, фоновые задачи."""

import asyncio
from datetime import datetime, time, timedelta

import pytest
from sqlalchemy import select, update

from booking.db import Session
from booking.db.models import Booking, Master, Service, TimeOff, WaitlistEntry
from booking.niche import niche, now, tz
from booking.services import bookings, jobs, schedule
from booking.services.schedule import BookingError
from tests.conftest import next_weekday


async def ids(s):
    service = {x.slug: x for x in await s.scalars(select(Service))}
    master = {x.slug: x for x in await s.scalars(select(Master))}
    return service, master


def at(day, h, m=0):
    return datetime.combine(day, time(h, m), tz())


async def book(user, service, start, master=None, **kw):
    async with Session() as s, s.begin():
        svc, mst = await ids(s)
        return await bookings.create(
            s,
            user,
            service_id=svc[service].id,
            start=start,
            master_id=mst[master].id if master else None,
            name="Егор",
            phone="+79000000000",
            **kw,
        )


async def test_master_price_and_prepay():
    day = next_weekday(0)  # понедельник: работает только Иван
    b = await book(100, "haircut", at(day, 10), "ivan")
    assert (b.price, b.prepay, b.status) == (1900, 300, "pending")  # цена топ-барбера, депозит 300 ₽
    assert b.busy_until - b.ends_at == timedelta(minutes=10)


async def test_any_master_balances_load():
    day = next_weekday(2)  # среда: работают все трое
    first = await book(101, "haircut", at(day, 12))
    second = await book(102, "haircut", at(day, 12))
    third = await book(103, "haircut", at(day, 12))
    assert len({first.master_id, second.master_id, third.master_id}) == 3  # каждый раз — свободный мастер
    with pytest.raises(BookingError):
        await book(104, "haircut", at(day, 12))  # в 12:00 все заняты


async def test_slot_taken_and_outside_schedule():
    day = next_weekday(3)
    await book(105, "beard", at(day, 16), "ivan")
    with pytest.raises(BookingError):
        await book(106, "beard", at(day, 16, 15), "ivan")  # пересекается с 16:00–16:40
    with pytest.raises(BookingError):
        await book(106, "beard", at(day, 14, 15), "ivan")  # перерыв
    with pytest.raises(BookingError):
        await book(106, "kids", at(day, 11), "ivan")  # Иван не стрижёт детей


async def test_concurrent_requests_cannot_double_book(monkeypatch):
    """Два клиента жмут «Записаться» одновременно. Проверка по графику у обоих проходит —
    но база (EXCLUDE) пропускает только одного."""
    day = next_weekday(4)
    real_slots = schedule.slots

    async def slow_slots(*a, **kw):  # оба запроса успевают проверить график до вставки
        result = await real_slots(*a, **kw)
        await asyncio.sleep(0.3)
        return result

    monkeypatch.setattr(schedule, "slots", slow_slots)
    results = await asyncio.gather(
        book(107, "fade", at(day, 17), "artem"), book(108, "fade", at(day, 17), "artem"), return_exceptions=True
    )
    assert sum(isinstance(r, Booking) for r in results) == 1
    assert any(isinstance(r, BookingError) and "только что заняли" in str(r) for r in results)


async def test_time_off_and_slots_api():
    day = next_weekday(1)
    async with Session() as s, s.begin():
        svc, mst = await ids(s)
        s.add(TimeOff(master_id=mst["artem"].id, starts_at=at(day, 10), ends_at=at(day, 13), reason="врач"))
    async with Session() as s:
        svc, mst = await ids(s)
        free = await schedule.slots(s, svc["kids"], day, mst["artem"].id)
        assert at(day, 13) in free and at(day, 12) not in free
        strip = dict(await schedule.days(s, svc["kids"], mst["artem"].id))
        assert strip[day] == len(free)


async def test_cancel_rules_and_reschedule():
    day = next_weekday(5)  # суббота
    b = await book(109, "haircut", at(day, 11), "artem")
    async with Session() as s, s.begin():
        b = await s.get(Booking, b.id)
        b.status, b.paid = "confirmed", 300
        new = await bookings.reschedule(s, b, at(day, 15))
    assert new.paid == 300 and new.status == "confirmed" and b.status == "cancelled"
    async with Session() as s, s.begin():
        new = await s.get(Booking, new.id)
        await s.execute(
            update(Booking)
            .where(Booking.id == new.id)
            .values(
                starts_at=now() + timedelta(hours=1),
                ends_at=now() + timedelta(hours=2),
                busy_until=now() + timedelta(hours=2),
            )
        )
        await s.refresh(new)
        with pytest.raises(BookingError, match="за 3 ч"):
            await bookings.cancel(s, new, "client")  # поздно — только звонком
        await bookings.cancel(s, new, "admin")  # админ может всегда


async def test_jobs_expire_remind_finish_rebook():
    day = next_weekday(0, after_days=9)
    pending = await book(110, "haircut", at(day, 15), "ivan")
    soon = await book(111, "combo", at(day, 17), "ivan")
    past = await book(112, "beard", at(day, 11), "ivan")
    async with Session() as s, s.begin():
        await s.execute(
            update(Booking)
            .where(Booking.id == pending.id)
            .values(created_at=now() - timedelta(minutes=niche().prepay.hold_minutes + 1))
        )
        # «Скоро»: визит через 100 минут — пора второе напоминание, первое пропускаем
        start = now() + timedelta(minutes=100)
        await s.execute(
            update(Booking)
            .where(Booking.id == soon.id)
            .values(
                status="confirmed",
                starts_at=start,
                ends_at=start + timedelta(minutes=75),
                busy_until=start + timedelta(minutes=85),
            )
        )
        start = now() - timedelta(hours=3)
        await s.execute(
            update(Booking)
            .where(Booking.id == past.id)
            .values(
                status="confirmed",
                starts_at=start,
                ends_at=start + timedelta(minutes=30),
                busy_until=start + timedelta(minutes=40),
            )
        )
        s.add(WaitlistEntry(user_id=113, service_id=pending.service_id, day=day))
    async with Session() as s, s.begin():
        expired = await jobs.expire_pending(s)
        assert pending.id in [b.id for b in expired]
        assert [e.user_id for e in await jobs.waitlist_for(s, expired[0])] == [113]
        reminders = await jobs.due_reminders(s)
        assert [(b.id, m) for b, m in reminders] == [(soon.id, 120)]
        finished = await jobs.finish_visits(s)
        assert [b.id for b in finished] == [past.id] and finished[0].rebook_at is not None
    async with Session() as s, s.begin():
        assert await jobs.due_reminders(s) == []  # повторно не напоминаем
        await s.execute(update(Booking).where(Booking.id == past.id).values(rebook_at=now() - timedelta(minutes=1)))
        assert [b.id for b in await jobs.due_rebook(s)] == [past.id]


async def test_google_calendar_busy_closes_slots(monkeypatch):
    """Занятое в Google Календаре мастера закрывает время для записи (сам Google подменён)."""
    from booking.services import gcal

    day = next_weekday(3, after_days=12)
    calls = []

    async def fake_busy(calendar_id, start, end):
        calls.append(calendar_id)
        return [(at(day, 15), at(day, 17))]  # у мастера личные дела 15–17

    monkeypatch.setattr(gcal, "enabled", lambda: True)
    monkeypatch.setattr(gcal, "busy", fake_busy)
    async with Session() as s, s.begin():
        svc, mst = await ids(s)
        mst["ivan"].gcal_id = "ivan@example.com"
    async with Session() as s:
        svc, mst = await ids(s)
        free = await schedule.slots(s, svc["beard"], day, mst["ivan"].id)
    assert calls == ["ivan@example.com"]
    assert at(day, 14, 30) not in free  # перерыв
    assert at(day, 15) not in free and at(day, 16, 30) not in free and at(day, 17) in free
    async with Session() as s, s.begin():
        (await ids(s))[1]["ivan"].gcal_id = None


async def test_no_payment_token_means_no_prepay(monkeypatch):
    from pydantic import SecretStr

    from booking.config import settings

    monkeypatch.setattr(settings, "payment_token", SecretStr(""))
    b = await book(114, "beard", at(next_weekday(4, after_days=14), 11), "ivan")
    assert (b.prepay, b.status) == (0, "confirmed")  # без провайдера запись подтверждается сразу
