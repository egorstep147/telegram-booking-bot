"""Конфиг бизнеса: niches/<name>/config.yaml — витрина и правила записи. Каталог (услуги, мастера,
графики) — в catalog.yaml, его загружает `booking seed`."""

from datetime import datetime
from functools import cache
from typing import Literal
from zoneinfo import ZoneInfo

import yaml
from pydantic import BaseModel

from booking.config import settings


class Prepay(BaseModel):
    mode: Literal["none", "deposit", "full"] = "none"
    deposit: int = 0  # ₽, для mode=deposit
    hold_minutes: int = 15  # сколько держим слот за неоплаченной записью


class Niche(BaseModel):
    name: str
    tagline: str = ""
    emoji: str = "📅"
    accent: str = "#2481cc"
    timezone: str = "Europe/Moscow"
    welcome: str
    address: str = ""
    phone: str = ""
    master_word: str = "Мастер"  # «Мастер», «Преподаватель», «Врач»
    slot_step: int = 15  # шаг времени записи, минут
    min_lead_minutes: int = 60  # раньше чем через столько минут записаться нельзя
    max_days_ahead: int = 30
    cancel_before_hours: int = 3  # клиент может отменить/перенести не позже чем за столько часов
    reminders: list[int] = [24 * 60, 120]  # за сколько минут до визита напомнить
    review_after_minutes: int = 120  # после конца визита — попросить отзыв
    prepay: Prepay = Prepay()
    waitlist: bool = True

    @property
    def prepay_mode(self) -> str:
        # Без платёжного токена предоплата невозможна — записываем без неё, а не ломаем запись
        return self.prepay.mode if settings.payment_token.get_secret_value() else "none"

    def prepay_amount(self, price: int) -> int:
        return {"none": 0, "deposit": min(self.prepay.deposit, price), "full": price}[self.prepay_mode]


@cache
def niche() -> Niche:
    path = settings.niches_dir / settings.niche / "config.yaml"
    return Niche.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def tz() -> ZoneInfo:
    return ZoneInfo(niche().timezone)


def now() -> datetime:
    return datetime.now(tz())
