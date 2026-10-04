from __future__ import annotations

import uuid
from datetime import date as Date, datetime, time, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from tablekeeper.errors import AppError
from tablekeeper.models import Restaurant
from tablekeeper.schemas import AvailabilityResponse, RestaurantResponse, Slot
from tablekeeper.services.policy import eligible_tables, service_periods_for, table_has_overlap
from tablekeeper.timeutils import get_zone, utc_offset_minutes


def _restaurant_or_404(db: Session, restaurant_id: uuid.UUID) -> Restaurant:
    restaurant = db.get(Restaurant, restaurant_id)
    if restaurant is None:
        raise AppError("not_found", "Restaurant not found", status_code=404)
    return restaurant


def get_restaurant(db: Session, restaurant_id: uuid.UUID) -> RestaurantResponse:
    restaurant = _restaurant_or_404(db, restaurant_id)
    if not restaurant.published:
        raise AppError("not_found", "Restaurant not found", status_code=404)
    return RestaurantResponse.model_validate(restaurant)


def list_restaurants(db: Session, query: str | None, location: str | None, party_size: int | None) -> list[RestaurantResponse]:
    statement = select(Restaurant).where(Restaurant.published.is_(True))
    if query:
        pattern = f"%{query}%"
        statement = statement.where(or_(Restaurant.name.ilike(pattern), Restaurant.slug.ilike(pattern)))
    if location:
        statement = statement.where(Restaurant.location.ilike(f"%{location}%"))
    if party_size:
        statement = statement.where(Restaurant.min_party_size <= party_size, Restaurant.max_party_size >= party_size)
    statement = statement.order_by(Restaurant.name.asc()).limit(50)
    return [RestaurantResponse.model_validate(row) for row in db.scalars(statement)]


def get_availability(
    db: Session,
    restaurant_id: uuid.UUID,
    local_date_raw: str,
    party_size: int,
    duration_minutes: int | None,
) -> AvailabilityResponse:
    restaurant = _restaurant_or_404(db, restaurant_id)
    if not restaurant.published:
        raise AppError("not_found", "Restaurant not found", status_code=404)
    try:
        local_date = Date.fromisoformat(local_date_raw)
    except ValueError as exc:
        raise AppError("invalid_date", "date must use YYYY-MM-DD", status_code=422) from exc
    duration = duration_minutes or restaurant.default_duration_minutes
    tables = eligible_tables(db, restaurant_id, party_size)
    zone = get_zone(restaurant.timezone)
    slots: list[Slot] = []
    for period in service_periods_for(db, restaurant_id, local_date):
        current = datetime.combine(local_date, period.opens_at, tzinfo=zone)
        close_date = local_date + timedelta(days=1) if period.closes_at <= period.opens_at else local_date
        close_at = datetime.combine(close_date, period.closes_at, tzinfo=zone)
        while current + timedelta(minutes=duration + restaurant.buffer_minutes) <= close_at:
            start_utc = current.astimezone(timezone.utc)
            end_utc = start_utc + timedelta(minutes=duration + restaurant.buffer_minutes)
            available = any(not table_has_overlap(db, table.id, start_utc, end_utc) for table in tables)
            slots.append(
                Slot(
                    local_time=current.timetz().replace(tzinfo=None),
                    starts_at=start_utc,
                    ends_at=end_utc,
                    utc_offset_minutes=utc_offset_minutes(start_utc, restaurant.timezone),
                    available=available,
                )
            )
            current += timedelta(minutes=30)
    return AvailabilityResponse(
        restaurant_id=restaurant_id,
        date=local_date,
        party_size=party_size,
        generated_at=datetime.now(timezone.utc),
        slots=slots,
    )
