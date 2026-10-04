from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tablekeeper.errors import AppError
from tablekeeper.models import ReservationTable, Restaurant, ServicePeriod, Table
from tablekeeper.timeutils import get_zone


def occupied_interval(starts_at: datetime, duration_minutes: int, buffer_minutes: int) -> tuple[datetime, datetime]:
    return starts_at, starts_at + timedelta(minutes=duration_minutes + buffer_minutes)


def validate_party_and_window(restaurant: Restaurant, party_size: int, starts_at: datetime, duration_minutes: int) -> None:
    if not restaurant.published:
        raise AppError("restaurant_unpublished", "Restaurant is not accepting reservations", status_code=409)
    if party_size < restaurant.min_party_size or party_size > restaurant.max_party_size:
        raise AppError("invalid_party_size", "Party size is outside restaurant policy", status_code=422)
    now = datetime.now(timezone.utc)
    if starts_at < now + timedelta(minutes=restaurant.lead_time_minutes):
        raise AppError("lead_time", "Reservation is inside the required lead time", status_code=409)
    if starts_at > now + timedelta(days=restaurant.horizon_days):
        raise AppError("booking_horizon", "Reservation is beyond the booking horizon", status_code=409)
    if duration_minutes <= 0:
        raise AppError("invalid_duration", "Duration must be positive", status_code=422)


def service_periods_for(db: Session, restaurant_id, local_date: date) -> list[ServicePeriod]:
    weekday = local_date.weekday()
    exceptions = list(
        db.scalars(
            select(ServicePeriod).where(
                ServicePeriod.restaurant_id == restaurant_id,
                ServicePeriod.service_date == local_date,
            )
        )
    )
    if exceptions:
        return [period for period in exceptions if period.enabled]
    return list(
        db.scalars(
            select(ServicePeriod).where(
                ServicePeriod.restaurant_id == restaurant_id,
                ServicePeriod.weekday == weekday,
                ServicePeriod.enabled.is_(True),
            )
        )
    )


def fits_service_period(restaurant: Restaurant, local_date: date, local_time: time, duration_minutes: int, periods: Iterable[ServicePeriod]) -> bool:
    zone = get_zone(restaurant.timezone)
    start = datetime.combine(local_date, local_time, tzinfo=zone)
    end = start + timedelta(minutes=duration_minutes + restaurant.buffer_minutes)
    for period in periods:
        open_at = datetime.combine(local_date, period.opens_at, tzinfo=zone)
        close_date = local_date + timedelta(days=1) if period.closes_at <= period.opens_at else local_date
        close_at = datetime.combine(close_date, period.closes_at, tzinfo=zone)
        if start >= open_at and end <= close_at:
            return True
    return False


def validate_service_window(
    db: Session,
    restaurant: Restaurant,
    local_date: date,
    local_time: time,
    duration_minutes: int,
) -> None:
    if not fits_service_period(restaurant, local_date, local_time, duration_minutes, service_periods_for(db, restaurant.id, local_date)):
        raise AppError("outside_service_hours", "Reservation does not fit service hours", status_code=409)


def eligible_tables(db: Session, restaurant_id, party_size: int) -> list[Table]:
    return list(
        db.scalars(
            select(Table)
            .where(Table.restaurant_id == restaurant_id, Table.enabled.is_(True), Table.capacity >= party_size)
            .order_by(Table.capacity.asc(), Table.id.asc())
        )
    )


def table_has_overlap(db: Session, table_id, starts_at: datetime, ends_at: datetime) -> bool:
    return bool(
        db.execute(
            select(ReservationTable.id).where(
                ReservationTable.table_id == table_id,
                ReservationTable.blocks_inventory.is_(True),
                ReservationTable.occupied_range.op("&&")(func.tstzrange(starts_at, ends_at, "[)")),
            )
        ).first()
    )
