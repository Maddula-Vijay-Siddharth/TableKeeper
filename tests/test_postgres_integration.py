from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timezone
from threading import Barrier

import pytest
from sqlalchemy import create_engine, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from tablekeeper.migrations import apply_migrations
from tablekeeper.models import Reservation, ReservationStatus, ReservationTable, Restaurant, Table, User


pytestmark = pytest.mark.skipif(
    not os.getenv("TABLEKEEPER_TEST_DATABASE_URL"),
    reason="TABLEKEEPER_TEST_DATABASE_URL is required for PostgreSQL integration tests",
)


@pytest.fixture()
def db():
    engine = create_engine(os.environ["TABLEKEEPER_TEST_DATABASE_URL"], future=True)
    Session = sessionmaker(bind=engine, future=True)
    with Session() as session:
        apply_migrations(session)
        yield session
        session.rollback()


def _reservation(db, restaurant_id, user_id, starts_at, ends_at):
    reservation = Reservation(
        restaurant_id=restaurant_id,
        customer_id=user_id,
        status=ReservationStatus.confirmed,
        party_size=2,
        requested_local_date=date(2027, 1, 1),
        requested_local_time=time(18, 0),
        timezone="UTC",
        starts_at=starts_at,
        ends_at=ends_at,
        idempotency_key=str(uuid.uuid4()),
    )
    db.add(reservation)
    db.flush()
    return reservation


def test_exclusion_constraint_blocks_overlap_and_allows_adjacency(db) -> None:
    user = User(id=uuid.uuid4(), email=f"{uuid.uuid4()}@example.com", name="Test")
    restaurant = Restaurant(
        id=uuid.uuid4(),
        name="Testaurant",
        slug=f"test-{uuid.uuid4()}",
        location="Test",
        timezone="UTC",
        published=True,
    )
    table = Table(id=uuid.uuid4(), restaurant_id=restaurant.id, label="A1", capacity=4, enabled=True)
    db.add_all([user, restaurant, table])
    db.flush()

    first_start = datetime(2027, 1, 1, 18, tzinfo=timezone.utc)
    first_end = datetime(2027, 1, 1, 19, tzinfo=timezone.utc)
    first = _reservation(db, restaurant.id, user.id, first_start, first_end)
    db.add(ReservationTable(reservation_id=first.id, table_id=table.id, occupied_range=func.tstzrange(first_start, first_end, "[)")))
    db.flush()

    adjacent = _reservation(db, restaurant.id, user.id, first_end, datetime(2027, 1, 1, 20, tzinfo=timezone.utc))
    db.add(ReservationTable(reservation_id=adjacent.id, table_id=table.id, occupied_range=func.tstzrange(first_end, adjacent.ends_at, "[)")))
    db.flush()

    overlapping = _reservation(db, restaurant.id, user.id, datetime(2027, 1, 1, 18, 30, tzinfo=timezone.utc), datetime(2027, 1, 1, 19, 30, tzinfo=timezone.utc))
    db.add(ReservationTable(reservation_id=overlapping.id, table_id=table.id, occupied_range=func.tstzrange(overlapping.starts_at, overlapping.ends_at, "[)")))

    with pytest.raises(IntegrityError):
        db.flush()


def test_concurrent_overlapping_inventory_has_one_winner(db) -> None:
    user = User(id=uuid.uuid4(), email=f"{uuid.uuid4()}@example.com", name="Concurrency test")
    restaurant = Restaurant(
        id=uuid.uuid4(),
        name="Concurrency Testaurant",
        slug=f"concurrency-{uuid.uuid4()}",
        location="Test",
        timezone="UTC",
        published=True,
    )
    table = Table(id=uuid.uuid4(), restaurant_id=restaurant.id, label="A1", capacity=4, enabled=True)
    db.add_all([user, restaurant, table])
    db.commit()

    starts_at = datetime(2027, 1, 1, 18, tzinfo=timezone.utc)
    ends_at = datetime(2027, 1, 1, 19, tzinfo=timezone.utc)
    start_barrier = Barrier(50)
    concurrent_engine = create_engine(
        db.get_bind().url,
        future=True,
        pool_size=50,
        max_overflow=0,
    )
    ConcurrentSession = sessionmaker(bind=concurrent_engine, future=True)

    def attempt_insert() -> bool:
        with ConcurrentSession() as session:
            reservation = Reservation(
                id=uuid.uuid4(),
                restaurant_id=restaurant.id,
                customer_id=user.id,
                status=ReservationStatus.confirmed,
                party_size=2,
                requested_local_date=date(2027, 1, 1),
                requested_local_time=time(18, 0),
                timezone="UTC",
                starts_at=starts_at,
                ends_at=ends_at,
                idempotency_key=str(uuid.uuid4()),
            )
            session.add(reservation)
            try:
                start_barrier.wait(timeout=30)
                session.add(
                    ReservationTable(
                        reservation_id=reservation.id,
                        table_id=table.id,
                        occupied_range=func.tstzrange(starts_at, ends_at, "[)"),
                    )
                )
                session.commit()
                return True
            except IntegrityError:
                session.rollback()
                return False

    try:
        with ThreadPoolExecutor(max_workers=50) as executor:
            results = list(executor.map(lambda _: attempt_insert(), range(50)))
        assert sum(results) == 1
        assert results.count(False) == 49
    finally:
        concurrent_engine.dispose()
        db.rollback()
        db.query(Reservation).filter(Reservation.restaurant_id == restaurant.id).delete(synchronize_session=False)
        db.delete(restaurant)
        db.delete(user)
        db.commit()
