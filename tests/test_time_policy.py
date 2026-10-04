from __future__ import annotations

from datetime import date, time

import pytest

from tablekeeper.errors import AppError
from tablekeeper.timeutils import local_to_utc


def test_adjacent_half_open_intervals_do_not_overlap() -> None:
    first = range(0, 90)
    second = range(90, 180)

    assert set(first).isdisjoint(second)


def test_spring_forward_gap_is_rejected() -> None:
    with pytest.raises(AppError) as exc:
        local_to_utc(date(2027, 3, 14), time(2, 30), "America/New_York", -5 * 60)

    assert exc.value.code == "invalid_local_time"


def test_fall_back_requires_matching_offset_choice() -> None:
    early = local_to_utc(date(2027, 11, 7), time(1, 30), "America/New_York", -4 * 60)
    late = local_to_utc(date(2027, 11, 7), time(1, 30), "America/New_York", -5 * 60)

    assert early != late
