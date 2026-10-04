from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from tablekeeper.errors import AppError
from tablekeeper.models import (
    MembershipRole,
    ReservationTable,
    Restaurant,
    RestaurantMembership,
    ServicePeriod,
    Table,
)
from tablekeeper.schemas import RestaurantCreate, RestaurantResponse, ServicePeriodRequest, TableCreate, TableResponse, TableUpdate
from tablekeeper.services.auth import ensure_user, require_staff
from tablekeeper.timeutils import get_zone


def create_restaurant(db: Session, user_id: uuid.UUID, payload: RestaurantCreate) -> RestaurantResponse:
    get_zone(payload.timezone)
    if payload.max_party_size < payload.min_party_size:
        raise AppError("invalid_party_policy", "max_party_size must be >= min_party_size", status_code=422)
    ensure_user(db, user_id)
    restaurant = Restaurant(**payload.model_dump())
    db.add(restaurant)
    db.flush()
    db.add(RestaurantMembership(restaurant_id=restaurant.id, user_id=user_id, role=MembershipRole.owner))
    db.commit()
    db.refresh(restaurant)
    return RestaurantResponse.model_validate(restaurant)


def create_table(db: Session, user_id: uuid.UUID, restaurant_id: uuid.UUID, payload: TableCreate) -> TableResponse:
    require_staff(db, user_id, restaurant_id)
    table = Table(restaurant_id=restaurant_id, **payload.model_dump())
    db.add(table)
    db.commit()
    db.refresh(table)
    return TableResponse.model_validate(table)


def list_tables(db: Session, user_id: uuid.UUID, restaurant_id: uuid.UUID) -> list[TableResponse]:
    require_staff(db, user_id, restaurant_id)
    return [TableResponse.model_validate(table) for table in db.scalars(select(Table).where(Table.restaurant_id == restaurant_id).order_by(Table.label))]


def update_table(db: Session, user_id: uuid.UUID, restaurant_id: uuid.UUID, table_id: uuid.UUID, payload: TableUpdate) -> TableResponse:
    require_staff(db, user_id, restaurant_id)
    table = db.get(Table, table_id)
    if table is None or table.restaurant_id != restaurant_id:
        raise AppError("not_found", "Table not found", status_code=404)
    future_booking = db.execute(
        select(ReservationTable.id)
        .where(
            ReservationTable.table_id == table_id,
            ReservationTable.blocks_inventory.is_(True),
            func.upper(ReservationTable.occupied_range) > datetime.now(timezone.utc),
        )
        .limit(1)
    ).first()
    if future_booking and (payload.enabled is False or (payload.capacity is not None and payload.capacity < table.capacity)):
        raise AppError("unsafe_table_edit", "Table edit would affect existing future reservations", status_code=409)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(table, key, value)
    db.commit()
    db.refresh(table)
    return TableResponse.model_validate(table)


def replace_service_periods(db: Session, user_id: uuid.UUID, restaurant_id: uuid.UUID, payload: list[ServicePeriodRequest]) -> None:
    require_staff(db, user_id, restaurant_id)
    future_booking = db.execute(
        select(ReservationTable.id)
        .where(ReservationTable.blocks_inventory.is_(True), func.upper(ReservationTable.occupied_range) > datetime.now(timezone.utc))
        .join(Table, Table.id == ReservationTable.table_id)
        .where(Table.restaurant_id == restaurant_id)
        .limit(1)
    ).first()
    if future_booking:
        raise AppError("unsafe_schedule_edit", "Service-period replacement would affect existing future reservations", status_code=409)
    for period in payload:
        if (period.weekday is None) == (period.service_date is None):
            raise AppError("invalid_service_period", "Specify exactly one of weekday or service_date", status_code=422)
        if period.opens_at == period.closes_at:
            raise AppError("invalid_service_period", "opens_at and closes_at must differ", status_code=422)
    db.execute(delete(ServicePeriod).where(ServicePeriod.restaurant_id == restaurant_id))
    for period in payload:
        db.add(ServicePeriod(restaurant_id=restaurant_id, **period.model_dump()))
    db.commit()
