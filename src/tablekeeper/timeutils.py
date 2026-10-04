from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .errors import AppError


def get_zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise AppError("invalid_timezone", "Unknown IANA timezone", status_code=422) from exc


def local_to_utc(local_date: date, local_time: time, zone_name: str, offset_minutes: int) -> datetime:
    zone = get_zone(zone_name)
    naive = datetime.combine(local_date, local_time)
    chosen_offset = timedelta(minutes=offset_minutes)
    matches: list[datetime] = []
    for fold in (0, 1):
        candidate = naive.replace(tzinfo=zone, fold=fold)
        round_trip = candidate.astimezone(timezone.utc).astimezone(zone)
        if round_trip.replace(tzinfo=None) == naive and candidate.utcoffset() == chosen_offset:
            matches.append(candidate.astimezone(timezone.utc))
    if not matches:
        raise AppError(
            "invalid_local_time",
            "Local time is nonexistent or offset does not match the restaurant timezone",
            status_code=422,
        )
    return min(matches)


def utc_offset_minutes(moment: datetime, zone_name: str) -> int:
    offset = moment.astimezone(get_zone(zone_name)).utcoffset()
    return int(offset.total_seconds() // 60) if offset else 0
