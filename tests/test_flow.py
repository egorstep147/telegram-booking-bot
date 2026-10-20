"""Сквозные сценарии через API мини-приложения и бота: запись, предоплата, кабинет мастера,
лист ожидания, напоминания и отзывы. Telegram — поддельный, база — настоящая."""

import hashlib
import hmac
import itertools
import json
import time
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx
import pytest
from aiogram import Bot
from aiogram.methods import AnswerPreCheckoutQuery, CreateInvoiceLink, SendMessage
from aiogram.types import CallbackQuery, Chat, Message, PreCheckoutQuery, SuccessfulPayment, Update
from aiogram.types import User as TgUser
from sqlalchemy import select, update

from booking.app import create_app
from booking.bot import create_dispatcher
from booking.bot import jobs as bot_jobs
from booking.db import Session
from booking.db.models import Booking, Master, Review, Service
from booking.niche import now
from tests.conftest import next_weekday
from tests.fakes import FakeSession

TOKEN = "123456:TEST-TOKEN"
ids = itertools.count(1)


def auth(uid: int) -> dict:
    data = {
        "auth_date": str(int(time.time())),
        "query_id": "q",
        "user": json.dumps({"id": uid, "first_name": "Тест"}, ensure_ascii=False),
    }
    check = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    return {
        "Authorization": "tma "
        + urlencode(data | {"hash": hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()})
    }


@pytest.fixture(scope="session")
def tg():
    session = FakeSession()
    return Bot(TOKEN, session=session), session, create_dispatcher()


@pytest.fixture(scope="session")
async def api(tg):
    app = create_app(tg[0], tg[2])
    app.state.bot = tg[0]  # lifespan в тестах не запускается — бота кладём сами
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def ids_of():
    async with Session() as s:
        return (
            {x.slug: x.id for x in await s.scalars(select(Service))},
            {x.slug: x.id for x in (await s.scalars(select(Master))).unique()},
        )


async def feed(tg, **update):
    bot, session, dp = tg
    session.requests.clear()
    await dp.feed_update(bot, Update(update_id=next(ids), **update))
    return session


def user(uid):
    return TgUser(id=uid, is_bot=False, first_name="Клиент")


def msg(uid, **kw):
    return Message(
        message_id=next(ids), date=datetime.now(UTC), chat=Chat(id=uid, type="private"), from_user=user(uid), **kw
    )


async def test_catalog_and_slots(api):
    svc, mst = await ids_of()
    cat = (await api.get("/api/catalog")).json()
    ivan = next(m for m in cat["masters"] if m["name"] == "Иван")
    assert ivan["offers"][str(svc["haircut"])]["price"] == 1900
    day = next_weekday(1, after_days=10)
    days = (await api.get("/api/days", params={"service_id": svc["kids"]})).json()
    assert any(d["date"] == day.isoformat() and d["free"] > 0 for d in days)
    slots = (await api.get("/api/slots", params={"service_id": svc["kids"], "day": day.isoformat()})).json()
    assert slots[0]["time"] == "10:00" and slots[0]["masters"] == [mst["artem"]]  # детей стрижёт только Артём


async def test_book_pay_and_notify(api, tg):
    bot, session, dp = tg
    svc, mst = await ids_of()
    async with Session() as s, s.begin():
        await s.execute(update(Master).where(Master.id == mst["ivan"]).values(tg_id=900))
    day = next_weekday(3, after_days=3)
    start = datetime.combine(day, datetime.min.time(), now().tzinfo) + timedelta(hours=11)
    session.requests.clear()
    r = await api.post(
        "/api/bookings",
        headers=auth(120),
        json={
            "service_id": svc["combo"],
            "master_id": mst["ivan"],
            "start": start.isoformat(),
            "name": "Егор",
            "phone": "+7 (900) 111-22-33",
            "comment": "без машинки",
        },
    )
    assert r.status_code == 200, r.text
    b = r.json()["booking"]
    assert (b["status"], b["price"], b["prepay"]) == ("pending", 2800, 300) and "invoice" in r.json()
    link = next(m for m in session.requests if isinstance(m, CreateInvoiceLink))
    assert link.prices[0].amount == 30000

    # То же время другому клиенту — уже занято
    r2 = await api.post(
        "/api/bookings",
        headers=auth(121),
        json={
            "service_id": svc["beard"],
            "master_id": mst["ivan"],
            "start": start.isoformat(),
            "name": "Б",
            "phone": "+79000000001",
        },
    )
    assert r2.status_code == 400

    q = PreCheckoutQuery(
        id="q", from_user=user(120), currency="RUB", total_amount=30000, invoice_payload=f"booking:{b['id']}"
    )
    s = await feed(tg, pre_checkout_query=q)
    assert next(m for m in s.requests if isinstance(m, AnswerPreCheckoutQuery)).ok
    paid = SuccessfulPayment(
        currency="RUB",
        total_amount=30000,
        invoice_payload=f"booking:{b['id']}",
        telegram_payment_charge_id="t1",
        provider_payment_charge_id="p1",
    )
    s = await feed(tg, message=msg(120, successful_payment=paid))
    sent = {m.chat_id: m.text for m in s.requests if isinstance(m, SendMessage)}
    assert sent[120].startswith("✅ Вы записаны!") and "Предоплата 300 ₽ — оплачено" in sent[120]
    assert "Новая запись" in sent[900] and "без машинки" in sent[900]  # мастер узнал сразу
    mine = (await api.get("/api/bookings", headers=auth(120))).json()
    assert mine[0]["status"] == "confirmed" and mine[0]["paid"] == 300


async def test_staff_cabinet_and_waitlist(api, tg):
    bot, session, dp = tg
    svc, mst = await ids_of()
    async with Session() as s, s.begin():
        await s.execute(update(Master).where(Master.id == mst["max"]).values(tg_id=901))
    day = next_weekday(6, after_days=3)  # воскресенье — работает только Максим
    start = datetime.combine(day, datetime.min.time(), now().tzinfo) + timedelta(hours=12)
    b = (
        await api.post(
            "/api/bookings",
            headers=auth(122),
            json={
                "service_id": svc["beard"],
                "master_id": mst["max"],
                "start": start.isoformat(),
                "name": "В",
                "phone": "+79000000002",
            },
        )
    ).json()["booking"]
    await api.post("/api/waitlist", headers=auth(123), json={"service_id": svc["beard"], "day": day.isoformat()})

    assert (await api.get("/api/staff/me", headers=auth(122))).status_code == 403  # клиент — не мастер
    me = (await api.get("/api/staff/me", headers=auth(901))).json()
    assert me == {"admin": False, "masters": [{"id": mst["max"], "name": "Максим", "photo": "🧑"}]}
    other = await api.get(
        "/api/staff/schedule", headers=auth(901), params={"master_id": mst["ivan"], "day": day.isoformat()}
    )
    assert other.status_code == 403  # чужое расписание закрыто
    sched = (
        await api.get(
            "/api/staff/schedule", headers=auth(901), params={"master_id": mst["max"], "day": day.isoformat()}
        )
    ).json()
    assert [x["id"] for x in sched["bookings"]] == [b["id"]]

    session.requests.clear()
    r = await api.post(f"/api/staff/bookings/{b['id']}/status", headers=auth(901), json={"status": "cancelled"})
    assert r.json()["status"] == "cancelled"
    sent = {m.chat_id: m for m in session.requests if isinstance(m, SendMessage)}
    assert "отменена салоном" in sent[122].text
    offer = sent[123]  # освободившееся время ушло ждавшему
    assert "Освободилось время" in offer.text
    data = offer.reply_markup.inline_keyboard[0][0].callback_data
    async with Session() as s, s.begin():
        await s.execute(update(Booking).where(Booking.user_id == 123).values(status="cancelled"))
    from booking.services import users

    async with Session() as s, s.begin():
        await users.upsert(s, 123, "Ждун", phone="+79000000003")
    cb = CallbackQuery(id="c", from_user=user(123), chat_instance="x", message=msg(123, text="…"), data=data)
    s = await feed(tg, callback_query=cb)
    pay = next(m for m in s.requests if isinstance(m, SendMessage))
    assert pay.text.startswith("Время за вами!")  # в барбершопе предоплата: кнопка оплаты
    assert pay.reply_markup.inline_keyboard[0][0].url == "https://t.me/$invoice"


async def test_reminder_review_flow(api, tg):
    bot, session, dp = tg
    svc, mst = await ids_of()
    day = next_weekday(2, after_days=10)
    start = datetime.combine(day, datetime.min.time(), now().tzinfo) + timedelta(hours=13)
    b = (
        await api.post(
            "/api/bookings",
            headers=auth(124),
            json={
                "service_id": svc["kids"],
                "master_id": mst["artem"],
                "start": start.isoformat(),
                "name": "Г",
                "phone": "+79000000004",
            },
        )
    ).json()["booking"]
    async with Session() as s, s.begin():  # визит через 90 минут и уже оплачен
        soon = now() + timedelta(minutes=90)
        await s.execute(
            update(Booking)
            .where(Booking.id == b["id"])
            .values(
                status="confirmed",
                paid=300,
                starts_at=soon,
                ends_at=soon + timedelta(minutes=30),
                busy_until=soon + timedelta(minutes=40),
            )
        )
    session.requests.clear()
    await bot_jobs.tick(bot)
    reminder = next(m for m in session.requests if isinstance(m, SendMessage) and m.chat_id == 124)
    assert reminder.text.startswith("⏰ Напоминаем: визит через 1 ч")

    async with Session() as s, s.begin():  # визит прошёл
        past = now() - timedelta(hours=3)
        await s.execute(
            update(Booking)
            .where(Booking.id == b["id"])
            .values(starts_at=past, ends_at=past + timedelta(minutes=30), busy_until=past + timedelta(minutes=40))
        )
    session.requests.clear()
    await bot_jobs.tick(bot)
    ask = next(m for m in session.requests if isinstance(m, SendMessage) and m.chat_id == 124)
    assert "Как прошёл визит" in ask.text
    five = ask.reply_markup.inline_keyboard[1][1].callback_data
    await feed(
        tg,
        callback_query=CallbackQuery(
            id="r", from_user=user(124), chat_instance="x", message=msg(124, text="…"), data=five
        ),
    )
    await feed(tg, message=msg(124, text="Отлично подстриг!"))
    async with Session() as s:
        r = await s.scalar(select(Review).where(Review.booking_id == b["id"]))
    assert (r.rating, r.text) == (5, "Отлично подстриг!")
    cat = (await api.get("/api/catalog")).json()
    assert next(m for m in cat["masters"] if m["id"] == mst["artem"])["rating"] == 5.0
