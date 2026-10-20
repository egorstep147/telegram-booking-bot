"""Свободное время мастера — чистые функции без базы.

Слот подходит, если:
  1) услуга целиком помещается в рабочий интервал (10:00–14:00, 15:00–20:00);
  2) [начало, конец услуги + буфер) не пересекается ни с чем занятым (записи, выходные, Google Календарь);
  3) начало не раньше «сейчас + минимальный запас»."""

from collections.abc import Iterable
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

Interval = tuple[datetime, datetime]


def work_intervals(rules: Iterable[tuple[int, time, time]], day: date, tz: ZoneInfo) -> list[Interval]:
    """Правила недели (день недели, начало, конец) → интервалы конкретной даты с часовым поясом.
    datetime.combine с tz корректно учитывает переход на летнее время в этот день."""
    return sorted(
        (datetime.combine(day, start, tz), datetime.combine(day, end, tz))
        for weekday, start, end in rules
        if weekday == day.weekday() and start < end
    )


def overlaps(a: Interval, b: Interval) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def free_starts(
    day: date,
    rules: Iterable[tuple[int, time, time]],
    busy: list[Interval],
    *,
    duration: int,
    buffer: int,
    step: int,
    earliest: datetime,
    tz: ZoneInfo,
) -> list[datetime]:
    out = []
    need, occupy = timedelta(minutes=duration), timedelta(minutes=duration + buffer)
    for ws, we in work_intervals(rules, day, tz):
        t = ws
        while t + need <= we:
            if t >= earliest and not any(overlaps((t, t + occupy), b) for b in busy):
                out.append(t)
            t += timedelta(minutes=step)
    return out
