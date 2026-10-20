"""Тесты работают с отдельной базой (TEST_DATABASE_URL или booking_test в docker compose)
и нишей «барбершоп». Настройки задаём до импорта booking."""

import os
from datetime import date, timedelta
from pathlib import Path

import pytest


def _local_test_db() -> str:
    env = Path(__file__).parents[1] / ".env"
    lines = env.read_text().splitlines() if env.exists() else []
    pw = next((ln.split("=", 1)[1].strip() for ln in lines if ln.startswith("POSTGRES_PASSWORD=")), "booking")
    # 127.0.0.1, а не localhost: на Windows localhost сначала пробует IPv6 и теряет ~2 с на каждом соединении
    return f"postgresql://booking:{pw}@127.0.0.1:5434/booking_test"


os.environ |= {
    "BOT_TOKEN": "123456:TEST-TOKEN",
    "DATABASE_URL": os.environ.get("TEST_DATABASE_URL") or _local_test_db(),
    "NICHE": "barbershop",
    "ADMIN_IDS": "1",
    "POLLING": "false",
    "REDIS_URL": "",
    "PAYMENT_TOKEN": "TEST:card",
    "GOOGLE_CREDENTIALS_FILE": "",
}

from sqlalchemy import text  # noqa: E402

from booking.config import ROOT  # noqa: E402
from booking.db import Session, engine  # noqa: E402
from booking.db.models import Base, User  # noqa: E402
from booking.niche import now  # noqa: E402
from booking.services.seed import seed  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
async def database():
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS btree_gist"))
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with Session() as s, s.begin():
        await seed(s, ROOT / "niches" / "barbershop" / "catalog.yaml")
        s.add_all(User(id=i, first_name=f"Клиент {i}") for i in range(100, 130))
    yield
    await engine.dispose()


def next_weekday(weekday: int, after_days: int = 2) -> date:
    """Ближайший нужный день недели не раньше чем через after_days: тесты не зависят от сегодняшней даты."""
    d = now().date() + timedelta(days=after_days)
    return d + timedelta(days=(weekday - d.weekday()) % 7)
