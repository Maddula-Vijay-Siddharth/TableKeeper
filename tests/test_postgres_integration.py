from __future__ import annotations

import os
import uuid
from datetime import date, datetime, time, timezone

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
