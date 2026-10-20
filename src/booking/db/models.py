"""Схема базы. Главное — таблица bookings: ограничение EXCLUDE не даёт двум активным записям
к одному мастеру пересечься во времени. Это проверяет сама база, поэтому двойной записи не будет
даже при одновременных запросах."""

from datetime import date, datetime, time

from sqlalchemy import (
    BigInteger,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    Text,
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import TSTZRANGE, ExcludeConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Статусы, при которых запись занимает время мастера
ACTIVE = ("pending", "confirmed")


class Base(DeclarativeBase):
    type_annotation_map = {datetime: DateTime(timezone=True), date: Date, time: Time, str: Text}


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # Telegram ID
    first_name: Mapped[str] = mapped_column(default="")
    username: Mapped[str | None]
    phone: Mapped[str | None]
    blocked: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Branch(Base):
    __tablename__ = "branches"
    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(unique=True)
    name: Mapped[str]
    address: Mapped[str] = mapped_column(default="")


class Service(Base):
    __tablename__ = "services"
    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(unique=True)
    category: Mapped[str] = mapped_column(default="")
    name: Mapped[str]
    description: Mapped[str] = mapped_column(default="")
    emoji: Mapped[str] = mapped_column(default="")
    duration: Mapped[int]  # минут
    buffer: Mapped[int] = mapped_column(default=0)  # уборка/подготовка после — тоже занятое время мастера
    price: Mapped[int]
    rebook_weeks: Mapped[int | None]  # через сколько недель предложить записаться снова
    active: Mapped[bool] = mapped_column(default=True)
    sort: Mapped[int] = mapped_column(default=0)


class Master(Base):
    __tablename__ = "masters"
    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(unique=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"))
    name: Mapped[str]
    title: Mapped[str] = mapped_column(default="")  # «Топ-барбер»
    bio: Mapped[str] = mapped_column(default="")
    photo: Mapped[str] = mapped_column(default="")  # URL или эмодзи
    tg_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)  # для кабинета и уведомлений
    gcal_id: Mapped[str | None]  # id Google Календаря мастера
    active: Mapped[bool] = mapped_column(default=True)
    sort: Mapped[int] = mapped_column(default=0)

    branch: Mapped[Branch] = relationship(lazy="joined")
    services: Mapped[list["MasterService"]] = relationship(cascade="all, delete-orphan", lazy="selectin")
    rules: Mapped[list["WorkRule"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin", order_by="(WorkRule.weekday, WorkRule.start)"
    )


class MasterService(Base):
    """Какие услуги делает мастер; цена и длительность могут отличаться от базовых (топ-мастер дороже)."""

    __tablename__ = "master_services"
    master_id: Mapped[int] = mapped_column(ForeignKey("masters.id", ondelete="CASCADE"), primary_key=True)
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id", ondelete="CASCADE"), primary_key=True)
    price: Mapped[int | None]
    duration: Mapped[int | None]


class WorkRule(Base):
    """Рабочий интервал в день недели. Перерыв = два интервала: 10:00–14:00 и 15:00–20:00."""

    __tablename__ = "work_rules"
    id: Mapped[int] = mapped_column(primary_key=True)
    master_id: Mapped[int] = mapped_column(ForeignKey("masters.id", ondelete="CASCADE"), index=True)
    weekday: Mapped[int] = mapped_column(SmallInteger)  # 0 — понедельник
    start: Mapped[time]
    end: Mapped[time]


class TimeOff(Base):
    """Выходной, отпуск, перерыв на конкретную дату — время, когда записываться нельзя."""

    __tablename__ = "time_off"
    id: Mapped[int] = mapped_column(primary_key=True)
    master_id: Mapped[int] = mapped_column(ForeignKey("masters.id", ondelete="CASCADE"), index=True)
    starts_at: Mapped[datetime]
    ends_at: Mapped[datetime]
    reason: Mapped[str] = mapped_column(default="")


class Booking(Base):
    __tablename__ = "bookings"
    __table_args__ = (
        # Главная защита: у одного мастера активные записи не пересекаются (нужно расширение btree_gist)
        ExcludeConstraint(
            ("master_id", "="),
            ("slot", "&&"),
            name="no_double_booking",
            using="gist",
            where=text("status IN ('pending', 'confirmed')"),
        ),
        Index("ix_bookings_user", "user_id", "starts_at"),
        Index("ix_bookings_status_start", "status", "starts_at"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    master_id: Mapped[int] = mapped_column(ForeignKey("masters.id"))
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id"))
    starts_at: Mapped[datetime]
    ends_at: Mapped[datetime]  # конец услуги — его видит клиент
    busy_until: Mapped[datetime]  # конец услуги + буфер — до этого времени мастер занят
    # Вычисляемая колонка: база сама собирает диапазон [начало, занят до) для проверки пересечений
    slot: Mapped[object] = mapped_column(TSTZRANGE, Computed("tstzrange(starts_at, busy_until, '[)')", persisted=True))
    # pending — ждёт предоплату; confirmed; completed; no_show; cancelled
    status: Mapped[str]
    price: Mapped[int]
    prepay: Mapped[int] = mapped_column(default=0)  # сколько нужно оплатить онлайн
    paid: Mapped[int] = mapped_column(default=0)  # сколько оплачено
    charge_id: Mapped[str | None]
    name: Mapped[str]
    phone: Mapped[str]
    comment: Mapped[str] = mapped_column(default="")
    client_confirmed: Mapped[bool] = mapped_column(default=False)  # нажал «Подтверждаю» в напоминании
    reminded: Mapped[int] = mapped_column(SmallInteger, default=0)  # сколько напоминаний из niche.reminders ушло
    review_asked: Mapped[bool] = mapped_column(default=False)
    rebook_at: Mapped[datetime | None]  # когда предложить записаться снова
    gcal_event_id: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    cancelled_by: Mapped[str | None]  # client | master | admin | timeout

    master: Mapped[Master] = relationship(lazy="joined")
    service: Mapped[Service] = relationship(lazy="joined")


class Review(Base):
    __tablename__ = "reviews"
    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id"), unique=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    master_id: Mapped[int] = mapped_column(ForeignKey("masters.id"), index=True)
    rating: Mapped[int] = mapped_column(SmallInteger)
    text: Mapped[str] = mapped_column(default="")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class WaitlistEntry(Base):
    """Хочу на эту услугу в этот день; освободится слот — бот предложит его первому в очереди."""

    __tablename__ = "waitlist"
    __table_args__ = (UniqueConstraint("user_id", "service_id", "day"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id"))
    master_id: Mapped[int | None] = mapped_column(ForeignKey("masters.id"))  # None — любой мастер
    day: Mapped[date]
    active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
