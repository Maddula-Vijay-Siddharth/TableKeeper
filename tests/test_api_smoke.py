from __future__ import annotations

import uuid
from datetime import date, datetime, time, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from tablekeeper import api
from tablekeeper.api import create_app
from tablekeeper.models import ReservationStatus
from tablekeeper.schemas import BookingResponse
from tablekeeper.services.auth import create_access_token


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
    monkeypatch.setattr(api.auth.settings, "auth_token_secret", "test-secret")
    client = TestClient(app)

    response = client.post(
        "/reservations",
        headers={"Authorization": f"Bearer {create_access_token(user_id)}", "Idempotency-Key": "same-key"},
        json={
            "restaurant_id": str(restaurant_id),
            "local_date": "2027-01-01",
            "local_time": "18:00:00",
            "utc_offset_minutes": 0,
            "party_size": 2,
        },
    )

    assert response.status_code == 200


def _booking(owner_id: uuid.UUID, reservation_id: uuid.UUID) -> BookingResponse:
    return BookingResponse(
        id=reservation_id,
        restaurant_id=uuid.uuid4(),
        customer_id=owner_id,
        status="confirmed",
        party_size=2,
        starts_at=datetime(2027, 1, 1, 18, tzinfo=timezone.utc),
        ends_at=datetime(2027, 1, 1, 19, 45, tzinfo=timezone.utc),
        local_date=date(2027, 1, 1),
        local_time=time(18, 0),
        timezone="UTC",
        table_ids=[],
    )


def _reservation_model(owner_id: uuid.UUID, reservation_id: uuid.UUID):
    response = _booking(owner_id, reservation_id)
    return SimpleNamespace(
        id=response.id,
        restaurant_id=response.restaurant_id,
        customer_id=response.customer_id,
        status=ReservationStatus.confirmed,
        party_size=response.party_size,
        starts_at=response.starts_at,
        ends_at=response.ends_at,
        requested_local_date=response.local_date,
        requested_local_time=response.local_time,
        timezone=response.timezone,
        tables=[],
    )


def test_valid_bearer_token_can_access_own_reservation(monkeypatch) -> None:
    owner_id, reservation_id = uuid.uuid4(), uuid.uuid4()
    monkeypatch.setattr(api.auth.settings, "auth_token_secret", "test-secret")
    reservation = _reservation_model(owner_id, reservation_id)
    app = create_app()
    app.dependency_overrides[api.get_db] = lambda: SimpleNamespace(get=lambda _model, _id: reservation)

    response = TestClient(app).get(
        f"/reservations/{reservation_id}",
        headers={"Authorization": f"Bearer {create_access_token(owner_id)}"},
    )

    assert response.status_code == 200
    assert response.json()["customer_id"] == str(owner_id)


def test_x_user_id_cannot_claim_another_users_reservation(monkeypatch) -> None:
    owner_id, attacker_id, reservation_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    monkeypatch.setattr(api.auth.settings, "auth_token_secret", "test-secret")
    reservation = _reservation_model(owner_id, reservation_id)
    app = create_app()
    app.dependency_overrides[api.get_db] = lambda: SimpleNamespace(get=lambda _model, _id: reservation)

    response = TestClient(app).get(
        f"/reservations/{reservation_id}",
        headers={
            "Authorization": f"Bearer {create_access_token(attacker_id)}",
            "X-User-Id": str(owner_id),
        },
    )

    assert response.status_code == 404


def test_user_cannot_cancel_another_users_reservation(monkeypatch) -> None:
    owner_id, attacker_id, reservation_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    monkeypatch.setattr(api.auth.settings, "auth_token_secret", "test-secret")
    reservation = _reservation_model(owner_id, reservation_id)
    app = create_app()
    app.dependency_overrides[api.get_db] = lambda: SimpleNamespace(scalar=lambda _: reservation)

    response = TestClient(app).post(
        f"/reservations/{reservation_id}/cancel",
        headers={"Authorization": f"Bearer {create_access_token(attacker_id)}"},
    )

    assert response.status_code == 404


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer invalid.token"}])
def test_missing_or_invalid_bearer_token_is_rejected(monkeypatch, headers) -> None:
    monkeypatch.setattr(api.auth.settings, "auth_token_secret", "test-secret")
    app = create_app()
    app.dependency_overrides[api.get_db] = lambda: object()

    response = TestClient(app).get("/reservations", headers=headers)

    assert response.status_code == 401
