"""Загрузка niches/<name>/catalog.yaml: филиалы, услуги, мастера и их графики. `booking seed`.
Повторный запуск обновляет записи по slug; график мастера заменяется целиком."""

from datetime import time

import yaml
from sqlalchemy import select

from booking.config import settings
from booking.db import AsyncSession
from booking.db.models import Branch, Master, MasterService, Service, WorkRule

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def parse_days(spec: str) -> list[int]:
    """«mon-fri» → [0..4], «sat,sun» → [5, 6], «wed» → [2]."""
    out = []
    for part in spec.replace(" ", "").split(","):
        a, _, b = part.partition("-")
        out += list(range(DAYS.index(a), DAYS.index(b or a) + 1))
    return out


def parse_schedule(schedule: dict) -> list[tuple[int, time, time]]:
    rules = []
    for days, intervals in schedule.items():
        for interval in intervals:
            start, end = (time.fromisoformat(x.strip()) for x in interval.split("-"))
            rules += [(d, start, end) for d in parse_days(days)]
    return rules


async def _upsert(s: AsyncSession, model, where: dict, **values):
    obj = await s.scalar(select(model).filter_by(**where))
    if obj is None:
        obj = model(**where)
        s.add(obj)
    for k, v in values.items():
        setattr(obj, k, v)
    await s.flush()
    return obj


async def seed(s: AsyncSession, path=None) -> dict[str, int]:
    data = yaml.safe_load((path or settings.niches_dir / settings.niche / "catalog.yaml").read_text(encoding="utf-8"))
    branches = {
        b["slug"]: await _upsert(s, Branch, {"slug": b["slug"]}, name=b["name"], address=b.get("address", ""))
        for b in data["branches"]
    }
    services = {}
    for i, x in enumerate(data["services"]):
        services[x["slug"]] = await _upsert(
            s,
            Service,
            {"slug": x["slug"]},
            name=x["name"],
            category=x.get("category", ""),
            description=x.get("description", ""),
            emoji=x.get("emoji", ""),
            duration=x["duration"],
            buffer=x.get("buffer", 0),
            price=x["price"],
            rebook_weeks=x.get("rebook_weeks"),
            active=x.get("active", True),
            sort=i,
        )
    for i, m in enumerate(data["masters"]):
        master = await _upsert(
            s,
            Master,
            {"slug": m["slug"]},
            name=m["name"],
            title=m.get("title", ""),
            bio=m.get("bio", ""),
            photo=m.get("photo", ""),
            branch_id=branches[m.get("branch") or next(iter(branches))].id,
            tg_id=m.get("tg_id"),
            gcal_id=m.get("gcal_id"),
            active=m.get("active", True),
            sort=i,
        )
        await s.refresh(master, ["services", "rules"])
        offers = m["services"] if isinstance(m["services"], dict) else {slug: {} for slug in m["services"]}
        master.services = [
            MasterService(
                service_id=services[slug].id, price=(o or {}).get("price"), duration=(o or {}).get("duration")
            )
            for slug, o in offers.items()
        ]
        master.rules = [WorkRule(weekday=d, start=a, end=b) for d, a, b in parse_schedule(m["schedule"])]
    await s.flush()
    return {"branches": len(branches), "services": len(services), "masters": len(data["masters"])}
