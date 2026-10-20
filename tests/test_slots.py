"""Алгоритм свободного времени — без базы."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from booking.services.seed import parse_days, parse_schedule
from booking.services.slots import free_starts

TZ = ZoneInfo("Asia/Kamchatka")
DAY = date(2026, 11, 3)  # вторник
RULES = [(1, time(10), time(14)), (1, time(15), time(20))]  # перерыв 14–15


def at(h: int, m: int = 0, day: date = DAY, tz=TZ) -> datetime:
    return datetime.combine(day, time(h, m), tz)


def starts(busy=(), duration=45, buffer=10, step=15, earliest=None, rules=RULES, day=DAY, tz=TZ):
    return free_starts(
        day,
        rules,
        list(busy),
        duration=duration,
        buffer=buffer,
        step=step,
        earliest=earliest or at(0, day=day, tz=tz),
        tz=tz,
    )


def test_service_fits_working_interval():
    s = starts()
    assert s[0] == at(10) and at(13, 15) in s
    assert at(13, 30) not in s  # 13:30 + 45 мин = 14:15 — за границей до перерыва
    assert at(15) in s and s[-1] == at(19, 15)


def test_busy_time_and_buffer():
    s = starts(busy=[(at(11), at(11, 55))])  # чужая запись 11:00–11:55 (услуга + буфер)
    assert at(10) in s  # 10:00 + 45 + 10 буфер = 10:55 — успевает
    assert at(10, 15) not in s  # 10:15–11:10 пересекается
    assert at(12) in s and at(11, 45) not in s  # 11:45–12:40 задевает чужую запись до 11:55


def test_lead_time_and_other_weekday():
    s = starts(earliest=at(16, 5))
    assert s[0] == at(16, 15)  # «не раньше чем через час» отсекает утро
    assert starts(day=DAY + timedelta(days=5)) == []  # воскресенье — нерабочий день


def test_dst_day_keeps_local_hours():
    berlin = ZoneInfo("Europe/Berlin")
    day = date(2026, 10, 25)  # в эту ночь Германия переводит часы
    s = starts(rules=[(6, time(10), time(12))], day=day, tz=berlin, duration=60, buffer=0, step=60)
    assert [t.hour for t in s] == [10, 11] and s[0].utcoffset() == timedelta(hours=1)


def test_schedule_parsing():
    assert parse_days("mon-fri") == [0, 1, 2, 3, 4]
    assert parse_days("tue,thu,sat") == [1, 3, 5]
    rules = parse_schedule({"sat,sun": ["11:00-17:00"], "wed": ["10:00-14:00", "15:00-20:00"]})
    assert (5, time(11), time(17)) in rules and len(rules) == 4
