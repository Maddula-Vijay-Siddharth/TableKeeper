from __future__ import annotations

import uuid
from datetime import date, datetime, time

from pydantic import BaseModel, ConfigDict, Field


class RestaurantCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    slug: str = Field(min_length=1, max_length=120, pattern=r"^[a-z0-9-]+$")
    location: str = Field(min_length=1, max_length=240)
    timezone: str = Field(min_length=1, max_length=80)
    published: bool = False
    default_duration_minutes: int = Field(default=90, gt=0, le=480)
    buffer_minutes: int = Field(default=15, ge=0, le=180)
    lead_time_minutes: int = Field(default=60, ge=0)
    horizon_days: int = Field(default=60, gt=0, le=730)
    min_party_size: int = Field(default=1, gt=0)
    max_party_size: int = Field(default=12, gt=0)


class RestaurantResponse(RestaurantCreate):
    id: uuid.UUID

    model_config = ConfigDict(from_attributes=True)


class TableCreate(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    capacity: int = Field(gt=0, le=100)
    enabled: bool = True


class TableUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=80)
    capacity: int | None = Field(default=None, gt=0, le=100)
    enabled: bool | None = None


class TableResponse(TableCreate):
    id: uuid.UUID
    restaurant_id: uuid.UUID

    model_config = ConfigDict(from_attributes=True)


class ServicePeriodRequest(BaseModel):
    weekday: int | None = Field(default=None, ge=0, le=6)
    service_date: date | None = None
    opens_at: time
    closes_at: time
    enabled: bool = True


class BookingRequest(BaseModel):
    restaurant_id: uuid.UUID
    local_date: date
    local_time: time
    utc_offset_minutes: int = Field(ge=-14 * 60, le=14 * 60)
    party_size: int = Field(gt=0, le=100)
    duration_minutes: int | None = Field(default=None, ge=15, le=480)
    contact_name: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=1000)


class BookingResponse(BaseModel):
    id: uuid.UUID
    restaurant_id: uuid.UUID
    customer_id: uuid.UUID
    status: str
    party_size: int
    starts_at: datetime
    ends_at: datetime
    local_date: date
    local_time: time
    timezone: str
    table_ids: list[uuid.UUID]


class Slot(BaseModel):
    local_time: time
    starts_at: datetime
    ends_at: datetime
    utc_offset_minutes: int
    available: bool


class AvailabilityResponse(BaseModel):
    restaurant_id: uuid.UUID
    date: date
    party_size: int
    generated_at: datetime
    slots: list[Slot]
