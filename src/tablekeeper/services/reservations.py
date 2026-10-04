from __future__ import annotations

import hashlib
import json
import time
import uuid
from datetime import datetime, timedelta, timezone

from psycopg.errors import ExclusionViolation
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from tablekeeper.config import settings
from tablekeeper.errors import AppError
from tablekeeper.models import (
    IdempotencyRecord,
    IdempotencyState,
    OutboxEvent,
    Reservation,
    ReservationStatus,
    ReservationTable,
    Restaurant,
)
from tablekeeper.schemas import BookingRequest, BookingResponse
from tablekeeper.services.auth import ensure_user
from tablekeeper.services.policy import (
    eligible_tables,
    occupied_interval,
    table_has_overlap,
    validate_party_and_window,
    validate_service_window,
)
from tablekeeper.timeutils import local_to_utc


def _hash_payload(payload: BookingRequest) -> str:
    normalized = payload.model_dump(mode="json")
    return hashlib.sha256(json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _to_response(reservation: Reservation) -> BookingResponse:
    return BookingResponse(
        id=reservation.id,
        restaurant_id=reservation.restaurant_id,
        customer_id=reservation.customer_id,
        status=reservation.status.value,
        party_size=reservation.party_size,
        starts_at=reservation.starts_at,
        ends_at=reservation.ends_at,
        local_date=reservation.requested_local_date,
        local_time=reservation.requested_local_time,
        timezone=reservation.timezone,
        table_ids=[assignment.table_id for assignment in reservation.tables],
    )


def _is_overlap_violation(exc: IntegrityError) -> bool:
    original = exc.orig
    if isinstance(original, ExclusionViolation):
        return True
    return "excl_reservation_table_overlap" in str(original)


def create_reservation(db: Session, user_id: uuid.UUID, idempotency_key: str, payload: BookingRequest) -> tuple[BookingResponse, int]:
    if not idempotency_key or len(idempotency_key) > 200:
        raise AppError("invalid_idempotency_key", "Idempotency-Key is required and must be <= 200 characters", status_code=422)
    request_hash = _hash_payload(payload)
    for attempt in range(3):
        try:
            return _create_reservation_once(db, user_id, idempotency_key, request_hash, payload)
        except OperationalError:
            db.rollback()
            if attempt == 2:
                raise AppError("transaction_retry_exhausted", "Reservation transaction could not complete; retry with the same key", status_code=503)
            time.sleep(0.05 * (attempt + 1))
    raise AppError("transaction_retry_exhausted", "Reservation transaction could not complete; retry with the same key", status_code=503)


def _create_reservation_once(
    db: Session,
    user_id: uuid.UUID,
    idempotency_key: str,
    request_hash: str,
    payload: BookingRequest,
) -> tuple[BookingResponse, int]:
    ensure_user(db, user_id)
    restaurant = db.get(Restaurant, payload.restaurant_id)
    if restaurant is None:
        raise AppError("not_found", "Restaurant not found", status_code=404)
    duration = payload.duration_minutes or restaurant.default_duration_minutes
    starts_at = local_to_utc(payload.local_date, payload.local_time, restaurant.timezone, payload.utc_offset_minutes)
    ends_at = starts_at + timedelta(minutes=duration + restaurant.buffer_minutes)
    validate_party_and_window(restaurant, payload.party_size, starts_at, duration)
    validate_service_window(db, restaurant, payload.local_date, payload.local_time, duration)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=settings.idempotency_ttl_hours)

    record = db.scalar(
        select(IdempotencyRecord)
        .where(IdempotencyRecord.principal_id == user_id, IdempotencyRecord.key == idempotency_key)
        .with_for_update()
    )
    if record:
        if record.request_hash != request_hash:
            db.rollback()
            raise AppError("idempotency_conflict", "Idempotency key was already used with a different request", status_code=409)
        if record.state == IdempotencyState.completed and record.response_body:
            db.rollback()
            return BookingResponse.model_validate(record.response_body), 200
        raise AppError("idempotency_in_progress", "Matching idempotent request is still in progress; retry shortly", status_code=409)
    record = IdempotencyRecord(
        principal_id=user_id,
        key=idempotency_key,
        request_hash=request_hash,
        state=IdempotencyState.in_progress,
        expires_at=expires_at,
    )
    db.add(record)
    db.flush()

    candidates = eligible_tables(db, restaurant.id, payload.party_size)
    if not candidates:
        db.rollback()
        raise AppError("unavailable", "No eligible table is available", status_code=409)

    for table in candidates:
        if table_has_overlap(db, table.id, starts_at, ends_at):
            continue
        try:
            with db.begin_nested():
                reservation = Reservation(
                    restaurant_id=restaurant.id,
                    customer_id=user_id,
                    status=ReservationStatus.confirmed,
                    party_size=payload.party_size,
                    requested_local_date=payload.local_date,
                    requested_local_time=payload.local_time,
                    timezone=restaurant.timezone,
                    starts_at=starts_at,
                    ends_at=ends_at,
                    idempotency_key=idempotency_key,
                )
                db.add(reservation)
                db.flush()
                db.add(
                    ReservationTable(
                        reservation_id=reservation.id,
                        table_id=table.id,
                        occupied_range=func.tstzrange(starts_at, ends_at, "[)"),
                        blocks_inventory=True,
                    )
                )
                db.flush()
        except IntegrityError as exc:
            if not _is_overlap_violation(exc):
                db.rollback()
                raise
            continue
        db.refresh(reservation, attribute_names=["tables"])
        response = _to_response(reservation)
        record.state = IdempotencyState.completed
        record.response_status = 201
        record.response_body = response.model_dump(mode="json")
        record.reservation_id = reservation.id
        db.add(
            OutboxEvent(
                event_type="reservation.created",
                payload={"reservation_id": str(reservation.id), "restaurant_id": str(restaurant.id)},
            )
        )
        db.commit()
        return response, 201
    db.rollback()
    raise AppError("unavailable", "Requested slot is no longer available", status_code=409)


def list_user_reservations(db: Session, user_id: uuid.UUID) -> list[BookingResponse]:
    rows = db.scalars(select(Reservation).where(Reservation.customer_id == user_id).order_by(Reservation.starts_at.desc())).unique()
    return [_to_response(row) for row in rows]


def get_reservation(db: Session, user_id: uuid.UUID, reservation_id: uuid.UUID) -> BookingResponse:
    reservation = db.get(Reservation, reservation_id)
    if reservation is None or reservation.customer_id != user_id:
        raise AppError("not_found", "Reservation not found", status_code=404)
    return _to_response(reservation)


def cancel_reservation(db: Session, user_id: uuid.UUID, reservation_id: uuid.UUID) -> BookingResponse:
    reservation = db.scalar(select(Reservation).where(Reservation.id == reservation_id).with_for_update())
    if reservation is None or reservation.customer_id != user_id:
        raise AppError("not_found", "Reservation not found", status_code=404)
    if reservation.status == ReservationStatus.cancelled:
        return _to_response(reservation)
    reservation.status = ReservationStatus.cancelled
    reservation.cancelled_at = datetime.now(timezone.utc)
    db.execute(
        update(ReservationTable)
        .where(ReservationTable.reservation_id == reservation.id)
        .values(blocks_inventory=False)
    )
    db.add(
        OutboxEvent(
            event_type="reservation.cancelled",
            payload={"reservation_id": str(reservation.id), "restaurant_id": str(reservation.restaurant_id)},
        )
    )
    db.commit()
    db.refresh(reservation, attribute_names=["tables"])
    return _to_response(reservation)
