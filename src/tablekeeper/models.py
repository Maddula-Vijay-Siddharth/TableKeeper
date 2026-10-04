from __future__ import annotations

import enum
import uuid
from datetime import date, datetime, time

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ExcludeConstraint, JSONB, TSTZRANGE, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class ReservationStatus(str, enum.Enum):
    confirmed = "confirmed"
    cancelled = "cancelled"


class IdempotencyState(str, enum.Enum):
    in_progress = "in_progress"
    completed = "completed"


class MembershipRole(str, enum.Enum):
    owner = "owner"
    manager = "manager"
    staff = "staff"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))


class Restaurant(Base):
    __tablename__ = "restaurants"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(120), unique=True)
    location: Mapped[str] = mapped_column(String(240))
    timezone: Mapped[str] = mapped_column(String(80))
    published: Mapped[bool] = mapped_column(Boolean, default=False)
    default_duration_minutes: Mapped[int] = mapped_column(Integer, default=90)
    buffer_minutes: Mapped[int] = mapped_column(Integer, default=15)
    lead_time_minutes: Mapped[int] = mapped_column(Integer, default=60)
    horizon_days: Mapped[int] = mapped_column(Integer, default=60)
    min_party_size: Mapped[int] = mapped_column(Integer, default=1)
    max_party_size: Mapped[int] = mapped_column(Integer, default=12)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))

    __table_args__ = (
        CheckConstraint("default_duration_minutes > 0", name="ck_restaurant_default_duration_positive"),
        CheckConstraint("buffer_minutes >= 0", name="ck_restaurant_buffer_nonnegative"),
        CheckConstraint("lead_time_minutes >= 0", name="ck_restaurant_lead_nonnegative"),
        CheckConstraint("horizon_days > 0", name="ck_restaurant_horizon_positive"),
        CheckConstraint("min_party_size > 0 AND max_party_size >= min_party_size", name="ck_restaurant_party_bounds"),
    )


class RestaurantMembership(Base):
    __tablename__ = "restaurant_memberships"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("restaurants.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    role: Mapped[MembershipRole] = mapped_column(Enum(MembershipRole), default=MembershipRole.owner)

    __table_args__ = (UniqueConstraint("restaurant_id", "user_id", name="uq_membership_restaurant_user"),)


class Table(Base):
    __tablename__ = "tables"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("restaurants.id", ondelete="CASCADE"))
    label: Mapped[str] = mapped_column(String(80))
    capacity: Mapped[int] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint("restaurant_id", "label", name="uq_table_restaurant_label"),
        CheckConstraint("capacity > 0", name="ck_table_capacity_positive"),
        Index("ix_tables_restaurant_enabled_capacity", "restaurant_id", "enabled", "capacity"),
    )


class ServicePeriod(Base):
    __tablename__ = "service_periods"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("restaurants.id", ondelete="CASCADE"))
    weekday: Mapped[int | None] = mapped_column(Integer, nullable=True)
    service_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    opens_at: Mapped[time] = mapped_column(Time)
    closes_at: Mapped[time] = mapped_column(Time)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (
        CheckConstraint("(weekday IS NOT NULL) <> (service_date IS NOT NULL)", name="ck_period_weekday_xor_date"),
        CheckConstraint("weekday IS NULL OR (weekday >= 0 AND weekday <= 6)", name="ck_period_weekday_range"),
    )


class Reservation(Base):
    __tablename__ = "reservations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("restaurants.id", ondelete="RESTRICT"))
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    status: Mapped[ReservationStatus] = mapped_column(Enum(ReservationStatus), default=ReservationStatus.confirmed)
    party_size: Mapped[int] = mapped_column(Integer)
    requested_local_date: Mapped[date] = mapped_column(Date)
    requested_local_time: Mapped[time] = mapped_column(Time)
    timezone: Mapped[str] = mapped_column(String(80))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    idempotency_key: Mapped[str] = mapped_column(String(200))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))

    tables: Mapped[list["ReservationTable"]] = relationship(back_populates="reservation")

    __table_args__ = (
        CheckConstraint("party_size > 0", name="ck_reservation_party_positive"),
        CheckConstraint("ends_at > starts_at", name="ck_reservation_end_after_start"),
        Index("ix_reservations_customer_start", "customer_id", "starts_at"),
        Index("ix_reservations_restaurant_start", "restaurant_id", "starts_at"),
    )


class ReservationTable(Base):
    __tablename__ = "reservation_tables"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    reservation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reservations.id", ondelete="CASCADE"))
    table_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tables.id", ondelete="RESTRICT"))
    occupied_range = mapped_column(TSTZRANGE, nullable=False)
    blocks_inventory: Mapped[bool] = mapped_column(Boolean, default=True)

    reservation: Mapped[Reservation] = relationship(back_populates="tables")

    __table_args__ = (
        CheckConstraint("NOT isempty(occupied_range)", name="ck_occupied_range_nonempty"),
        ExcludeConstraint(
            ("table_id", "="),
            ("occupied_range", "&&"),
            where=text("blocks_inventory"),
            using="gist",
            name="excl_reservation_table_overlap",
        ),
        Index("ix_reservation_tables_table", "table_id"),
    )


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    principal_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    key: Mapped[str] = mapped_column(String(200))
    request_hash: Mapped[str] = mapped_column(String(64))
    state: Mapped[IdempotencyState] = mapped_column(Enum(IdempotencyState), default=IdempotencyState.in_progress)
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_body: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    reservation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (UniqueConstraint("principal_id", "key", name="uq_idempotency_principal_key"),)


class OutboxEvent(Base):
    __tablename__ = "outbox_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_type: Mapped[str] = mapped_column(String(120))
    payload: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
