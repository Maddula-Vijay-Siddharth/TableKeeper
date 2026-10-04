from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, FastAPI, Header, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from .database import SessionLocal
from .errors import AppError
from .schemas import (
    AvailabilityResponse,
    BookingRequest,
    BookingResponse,
    RestaurantCreate,
    RestaurantResponse,
    ServicePeriodRequest,
    TableCreate,
    TableResponse,
    TableUpdate,
)
from .services import availability, management, reservations


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def current_user_id(x_user_id: Annotated[str | None, Header()] = None) -> uuid.UUID:
    if not x_user_id:
        raise AppError("unauthenticated", "Missing X-User-Id header", status_code=401)
    try:
        return uuid.UUID(x_user_id)
    except ValueError as exc:
        raise AppError("invalid_user", "X-User-Id must be a UUID", status_code=401) from exc


def create_app() -> FastAPI:
    app = FastAPI(title="Tablekeeper", version="0.1.0")

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
        body: dict[str, object] = {
            "error": {
                "code": exc.code,
                "message": exc.message,
                "requestId": request_id,
            }
        }
        if exc.fields:
            body["error"]["fields"] = exc.fields
        return JSONResponse(status_code=exc.status_code, content=body)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
        fields = {
            ".".join(str(part) for part in error["loc"]): error["msg"]
            for error in exc.errors()
        }
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "Request validation failed",
                    "fields": fields,
                    "requestId": request_id,
                }
            },
        )

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/restaurants", response_model=RestaurantResponse, status_code=201)
    def create_restaurant(
        payload: RestaurantCreate,
        db: Session = Depends(get_db),
        user_id: uuid.UUID = Depends(current_user_id),
    ) -> RestaurantResponse:
        return management.create_restaurant(db, user_id, payload)

    @app.get("/restaurants", response_model=list[RestaurantResponse])
    def list_restaurants(
        query: str | None = None,
        location: str | None = None,
        partySize: Annotated[int | None, Query(ge=1)] = None,
        db: Session = Depends(get_db),
    ) -> list[RestaurantResponse]:
        return availability.list_restaurants(db, query, location, partySize)

    @app.get("/restaurants/{restaurant_id}", response_model=RestaurantResponse)
    def get_restaurant(restaurant_id: uuid.UUID, db: Session = Depends(get_db)) -> RestaurantResponse:
        return availability.get_restaurant(db, restaurant_id)

    @app.get("/restaurants/{restaurant_id}/availability", response_model=AvailabilityResponse)
    def get_availability(
        restaurant_id: uuid.UUID,
        date: str,
        partySize: Annotated[int, Query(ge=1)],
        durationMinutes: Annotated[int | None, Query(ge=15, le=480)] = None,
        db: Session = Depends(get_db),
    ) -> AvailabilityResponse:
        return availability.get_availability(db, restaurant_id, date, partySize, durationMinutes)

    @app.post("/reservations", response_model=BookingResponse, status_code=201)
    def create_reservation(
        payload: BookingRequest,
        response: Response,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
        db: Session = Depends(get_db),
        user_id: uuid.UUID = Depends(current_user_id),
    ) -> BookingResponse:
        booking, status_code = reservations.create_reservation(db, user_id, idempotency_key, payload)
        response.status_code = status_code
        return booking

    @app.get("/reservations", response_model=list[BookingResponse])
    def list_reservations(
        db: Session = Depends(get_db),
        user_id: uuid.UUID = Depends(current_user_id),
    ) -> list[BookingResponse]:
        return reservations.list_user_reservations(db, user_id)

    @app.get("/reservations/{reservation_id}", response_model=BookingResponse)
    def get_reservation(
        reservation_id: uuid.UUID,
        db: Session = Depends(get_db),
        user_id: uuid.UUID = Depends(current_user_id),
    ) -> BookingResponse:
        return reservations.get_reservation(db, user_id, reservation_id)

    @app.post("/reservations/{reservation_id}/cancel", response_model=BookingResponse)
    def cancel_reservation(
        reservation_id: uuid.UUID,
        db: Session = Depends(get_db),
        user_id: uuid.UUID = Depends(current_user_id),
    ) -> BookingResponse:
        return reservations.cancel_reservation(db, user_id, reservation_id)

    @app.post("/restaurants/{restaurant_id}/tables", response_model=TableResponse, status_code=201)
    def create_table(
        restaurant_id: uuid.UUID,
        payload: TableCreate,
        db: Session = Depends(get_db),
        user_id: uuid.UUID = Depends(current_user_id),
    ) -> TableResponse:
        return management.create_table(db, user_id, restaurant_id, payload)

    @app.get("/restaurants/{restaurant_id}/tables", response_model=list[TableResponse])
    def list_tables(
        restaurant_id: uuid.UUID,
        db: Session = Depends(get_db),
        user_id: uuid.UUID = Depends(current_user_id),
    ) -> list[TableResponse]:
        return management.list_tables(db, user_id, restaurant_id)

    @app.patch("/restaurants/{restaurant_id}/tables/{table_id}", response_model=TableResponse)
    def patch_table(
        restaurant_id: uuid.UUID,
        table_id: uuid.UUID,
        payload: TableUpdate,
        db: Session = Depends(get_db),
        user_id: uuid.UUID = Depends(current_user_id),
    ) -> TableResponse:
        return management.update_table(db, user_id, restaurant_id, table_id, payload)

    @app.put("/restaurants/{restaurant_id}/service-periods", status_code=204)
    def put_service_periods(
        restaurant_id: uuid.UUID,
        payload: list[ServicePeriodRequest],
        db: Session = Depends(get_db),
        user_id: uuid.UUID = Depends(current_user_id),
    ) -> None:
        management.replace_service_periods(db, user_id, restaurant_id, payload)

    return app


app = create_app()
