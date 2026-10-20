"""Свободное время из базы: графики мастеров, записи, выходные и Google Календарь → слоты."""

from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import select

from booking.db import AsyncSession
from booking.db.models import ACTIVE, Booking, Master, MasterService, Service, TimeOff
from booking.niche import niche, now, tz
from booking.services import gcal
from booking.services.slots import Interval, free_starts


class BookingError(ValueError):
    pass


def offer(master: Master, service: Service) -> tuple[int, int] | None:
    """(цена, длительность) услуги у мастера или None, если мастер её не делает."""
    ms: MasterService | None = next((x for x in master.services if x.service_id == service.id), None)
    return None if ms is None else (ms.price or service.price, ms.duration or service.duration)


async def masters_for(s: AsyncSession, service: Service, master_id: int | None = None) -> list[Master]:
    q = select(Master).join(MasterService).where(Master.active, MasterService.service_id == service.id)
    if master_id:
        q = q.where(Master.id == master_id)
    return list((await s.scalars(q.order_by(Master.sort, Master.id))).unique())


async def busy(s: AsyncSession, masters: list[Master], start: datetime, end: datetime) -> dict[int, list[Interval]]:
    """Всё занятое время мастеров в окне [start, end): активные записи, выходные, Google Календарь."""
    ids = [m.id for m in masters]
    out: dict[int, list[Interval]] = defaultdict(list)
    rows = await s.execute(
        select(Booking.master_id, Booking.starts_at, Booking.busy_until).where(
            Booking.master_id.in_(ids), Booking.status.in_(ACTIVE), Booking.starts_at < end, Booking.busy_until > start
        )
    )
    for mid, a, b in rows:
        out[mid].append((a, b))
    rows = await s.execute(
        select(TimeOff.master_id, TimeOff.starts_at, TimeOff.ends_at).where(
            TimeOff.master_id.in_(ids), TimeOff.starts_at < end, TimeOff.ends_at > start
        )
    )
    for mid, a, b in rows:
        out[mid].append((a, b))
    if gcal.enabled():
        for m in masters:
            if m.gcal_id:
                out[m.id] += await gcal.busy(m.gcal_id, start, end)
    return out


def _free(
    service: Service, masters: list[Master], taken: dict[int, list[Interval]], day: date
) -> dict[datetime, list[int]]:
    n, z = niche(), tz()
    if not (now().date() <= day <= now().date() + timedelta(days=n.max_days_ahead)):
        return {}
    earliest = now() + timedelta(minutes=n.min_lead_minutes)
    result: dict[datetime, list[int]] = defaultdict(list)
    for m in masters:
        _, duration = offer(m, service)
        rules = [(r.weekday, r.start, r.end) for r in m.rules]
        for t in free_starts(
            day, rules, taken[m.id], duration=duration, buffer=service.buffer, step=n.slot_step, earliest=earliest, tz=z
        ):
            result[t].append(m.id)
    return dict(sorted(result.items()))


def _day_start(day: date) -> datetime:
    return datetime.combine(day, datetime.min.time(), tz())


async def slots(
    s: AsyncSession, service: Service, day: date, master_id: int | None = None
) -> dict[datetime, list[int]]:
    """Время начала → мастера, свободные в это время. Для «любого мастера» — объединение по всем."""
    masters = await masters_for(s, service, master_id)
    # +6 часов: запись с прошлого дня или выходной могут заходить за полночь
    taken = await busy(s, masters, _day_start(day) - timedelta(hours=6), _day_start(day) + timedelta(days=1, hours=6))
    return _free(service, masters, taken, day)


async def days(s: AsyncSession, service: Service, master_id: int | None = None) -> list[tuple[date, int]]:
    """Ближайшие дни и сколько в каждом свободных слотов — для ленты дат. Занятое берём одним запросом."""
    today, count = now().date(), niche().max_days_ahead + 1
    masters = await masters_for(s, service, master_id)
    taken = await busy(s, masters, _day_start(today), _day_start(today) + timedelta(days=count, hours=6))
    return [(d, len(_free(service, masters, taken, d))) for d in (today + timedelta(days=i) for i in range(count))]
