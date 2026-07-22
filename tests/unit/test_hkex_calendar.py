import datetime as dt
from pathlib import Path

import polars as pl
import pytest

from quant.data.hkex_calendar import apply_hkex_calendar_notice, load_hkex_calendar_notice


CONFIG = Path("configs/calendars/hk_market_2026.toml")


def calendar(rows: list[tuple[dt.date, bool]]) -> pl.DataFrame:
    return pl.DataFrame({
        "market": ["HK"] * len(rows),
        "date": [date for date, _ in rows],
        "is_open": [is_open for _, is_open in rows],
        "is_connect_open": [False] * len(rows),
        "is_half_day": [False] * len(rows),
    })


def test_applies_official_half_days_and_accepts_closures() -> None:
    notice = load_hkex_calendar_notice(CONFIG)
    result = apply_hkex_calendar_notice(
        calendar([
            (dt.date(2026, 2, 16), True),
            (dt.date(2026, 2, 17), False),
            (dt.date(2026, 12, 24), True),
            (dt.date(2026, 12, 31), True),
        ]),
        notice,
    )
    assert result.get_column("is_half_day").to_list() == [True, False, True, True]


def test_rejects_calendar_that_conflicts_with_official_notice() -> None:
    notice = load_hkex_calendar_notice(CONFIG)
    with pytest.raises(ValueError, match="官方通告冲突"):
        apply_hkex_calendar_notice(calendar([(dt.date(2026, 7, 1), True)]), notice)
