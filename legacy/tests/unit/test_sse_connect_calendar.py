import datetime as dt
from pathlib import Path

import polars as pl
import pytest

from quant.data.sse_connect_calendar import (
    build_sse_connect_calendar,
    load_calendar_notice,
)


CONFIG = Path("configs/calendars/sh_connect_2026.toml")


def base_calendar(start: dt.date, end: dt.date) -> pl.DataFrame:
    dates = pl.date_range(start, end, interval="1d", eager=True)
    return pl.DataFrame({
        "market": ["SH"] * len(dates), "date": dates,
        "is_open": [date.weekday() < 5 for date in dates],
        "is_connect_open": [False] * len(dates), "is_half_day": [False] * len(dates),
    })


def test_official_2026_closure_and_half_days() -> None:
    notice = load_calendar_notice(CONFIG)
    base = base_calendar(dt.date(2026, 7, 1), dt.date(2026, 12, 31))
    result = build_sse_connect_calendar(
        base, notice, start=dt.date(2026, 7, 1), end=dt.date(2026, 12, 31)
    )
    rows = {row["date"]: row for row in result.iter_rows(named=True)}
    assert rows[dt.date(2026, 7, 1)]["is_open"] is False
    assert rows[dt.date(2026, 7, 2)]["is_open"] is True
    assert rows[dt.date(2026, 12, 24)]["is_half_day"] is True
    assert rows[dt.date(2026, 12, 25)]["is_open"] is False
    assert rows[dt.date(2026, 12, 31)]["is_half_day"] is True


def test_rejects_incomplete_base_calendar() -> None:
    notice = load_calendar_notice(CONFIG)
    base = base_calendar(dt.date(2026, 7, 1), dt.date(2026, 7, 2)).head(1)
    with pytest.raises(ValueError, match="覆盖不完整"):
        build_sse_connect_calendar(
            base, notice, start=dt.date(2026, 7, 1), end=dt.date(2026, 7, 2)
        )
