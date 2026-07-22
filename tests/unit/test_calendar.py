"""clean 交易日历门禁测试。"""

import datetime as dt
from pathlib import Path

import polars as pl
import pytest

from quant.data.calendar import expected_open_dates


def write_calendar(root: Path, market: str, dates: list[dt.date], open_flags: list[bool]) -> None:
    path = root / "clean" / "trade_calendar" / f"market={market}" / "data.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(
        {
            "market": [market] * len(dates),
            "date": dates,
            "is_open": open_flags,
            "is_connect_open": [False] * len(dates),
            "is_half_day": [False] * len(dates),
        }
    ).write_parquet(path)


def test_expected_open_dates_requires_complete_calendar(tmp_path: Path):
    write_calendar(
        tmp_path,
        "SZ",
        [dt.date(2026, 7, 10), dt.date(2026, 7, 11)],
        [True, False],
    )

    dates = expected_open_dates(
        tmp_path, ["000001.SZ"], dt.date(2026, 7, 10), dt.date(2026, 7, 11)
    )
    assert dates == {dt.date(2026, 7, 10)}

    with pytest.raises(RuntimeError, match="未完整覆盖"):
        expected_open_dates(
            tmp_path, ["000001.SZ"], dt.date(2026, 7, 9), dt.date(2026, 7, 11)
        )


def test_expected_open_dates_supports_hk_and_cross_market_intersection(tmp_path: Path):
    dates = [dt.date(2026, 7, 1), dt.date(2026, 7, 2)]
    write_calendar(tmp_path, "SH", dates, [True, True])
    write_calendar(tmp_path, "HK", dates, [False, True])
    assert expected_open_dates(
        tmp_path, ["600000.SH", "00700.HK"], dates[0], dates[1]
    ) == {dt.date(2026, 7, 2)}
