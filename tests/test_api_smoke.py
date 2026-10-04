from __future__ import annotations

import uuid
from datetime import date, datetime, time, timezone

from fastapi.testclient import TestClient

from tablekeeper import api
from tablekeeper.api import create_app
from tablekeeper.schemas import BookingResponse


def test_healthz() -> None:
    client = TestClient(create_app())

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_validation_errors_use_stable_envelope() -> None:
    client = TestClient(create_app())

    response = client.get("/restaurants/not-a-uuid")

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    assert "requestId" in body["error"]


def test_reservation_route_preserves_idempotent_replay_status(monkeypatch) -> None:
    user_id = uuid.uuid4()
    restaurant_id = uuid.uuid4()
    reservation_id = uuid.uuid4()

    def fake_create_reservation(db, principal_id, idempotency_key, payload):
        assert principal_id == user_id
        assert idempotency_key == "same-key"
        return (
            BookingResponse(
                id=reservation_id,
                restaurant_id=restaurant_id,
                customer_id=user_id,
                status="confirmed",
                party_size=2,
                starts_at=datetime(2027, 1, 1, 18, tzinfo=timezone.utc),
                ends_at=datetime(2027, 1, 1, 19, 45, tzinfo=timezone.utc),
                local_date=date(2027, 1, 1),
                local_time=time(18, 0),
                timezone="UTC",
                table_ids=[uuid.uuid4()],
            ),
            200,
        )

    app = create_app()
    app.dependency_overrides[api.get_db] = lambda: object()
    monkeypatch.setattr(api.reservations, "create_reservation", fake_create_reservation)
    client = TestClient(app)

    response = client.post(
        "/reservations",
        headers={"X-User-Id": str(user_id), "Idempotency-Key": "same-key"},
        json={
            "restaurant_id": str(restaurant_id),
            "local_date": "2027-01-01",
            "local_time": "18:00:00",
            "utc_offset_minutes": 0,
            "party_size": 2,
        },
    )

    assert response.status_code == 200
