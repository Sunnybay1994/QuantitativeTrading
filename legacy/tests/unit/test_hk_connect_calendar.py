import datetime as dt
import json
from pathlib import Path

import polars as pl
import pytest

from quant.data.hk_connect_calendar import (
    build_calendar,
    check_trade_dates,
    read_sse_closures,
    read_szse_calendar,
)


def one_day(date: str, part: str = "", hk_open: bool = True) -> pl.DataFrame:
    day = dt.date.fromisoformat(date)
    hk = pl.DataFrame({"date": [day], "is_open": [hk_open], "is_half_day": [False]})
    closures = {day: (part, "holiday")} if part else {}
    status = {"": "不休市", "全天": "全日休市", "下午": "下午休市"}[part]
    return build_calendar(hk, closures, {day: status}, day, day)


def test_mainland_holiday_and_optimized_preholiday() -> None:
    assert one_day("2024-02-08")["can_execute_1430"].item()
    row = one_day("2024-02-15", "全天").row(0, named=True)
    assert row["hk_is_open"] and not row["is_connect_open"]
    assert not row["can_execute_1430"]


@pytest.mark.parametrize("date", ["2024-12-24", "2024-12-31", "2025-12-24"])
def test_half_day_allows_morning_but_never_1430(date: str) -> None:
    row = one_day(date, "下午").row(0, named=True)
    assert row["hk_is_half_day"] and row["southbound_am_open"]
    assert row["is_connect_open"] and not row["can_execute_1430"]


def test_half_day_correction_and_storm_override() -> None:
    assert one_day("2024-02-09", "全天")["hk_is_half_day"].item()
    storm = one_day("2024-09-06", hk_open=False).row(0, named=True)
    assert storm["southbound_scheduled_open"] and not storm["is_connect_open"]
    assert storm["source_published_date"] == dt.date(2024, 9, 6)
    with pytest.raises(ValueError, match="dated official override"):
        one_day("2024-09-05", hk_open=False)


def test_source_publication_differs_from_effective_date() -> None:
    row = one_day("2023-12-28").row(0, named=True)
    assert row["source_published_date"] == dt.date(2023, 12, 26)
    assert row["schedule_effective_date"] == dt.date(2023, 12, 28)
    assert row["optimization_effective_date"] == dt.date(2023, 4, 24)


def test_sse_parser_rejects_unknown_and_duplicate_status(tmp_path: Path) -> None:
    source = tmp_path / "calendar.js"
    source.write_text("[['2024-01-01','全天','元旦']]", encoding="utf-8")
    assert read_sse_closures(source)[dt.date(2024, 1, 1)] == ("全天", "元旦")
    source.write_text("[['2024-01-01','未知','元旦']]", encoding="utf-8")
    with pytest.raises(ValueError, match="Unknown or duplicate"):
        read_sse_closures(source)
    source.write_text("[['2024-01-01','全天',''],['2024-01-01','全天','']]", encoding="utf-8")
    with pytest.raises(ValueError, match="Unknown or duplicate"):
        read_sse_closures(source)


def test_missing_szse_weekday_rejected_known_yearend_weekends_allowed(tmp_path: Path) -> None:
    (tmp_path / "2023-12.json").write_text(json.dumps({"data": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="every requested date"):
        read_szse_calendar(tmp_path, dt.date(2023, 12, 29), dt.date(2023, 12, 31))
    assert len(read_szse_calendar(tmp_path, dt.date(2023, 12, 30), dt.date(2023, 12, 31))) == 2


def test_disagreement_and_incomplete_hk_input_rejected() -> None:
    date = dt.date(2024, 2, 15)
    hk = pl.DataFrame({"date": [date], "is_open": [True]})
    with pytest.raises(ValueError, match="disagreement"):
        build_calendar(hk, {date: ("全天", "春节")}, {date: "不休市"}, date, date)
    with pytest.raises(ValueError, match="exactly once"):
        build_calendar(hk.clear(), {}, {}, date, date)


def test_trade_check_keeps_duplicate_symbols_and_unknown_dates() -> None:
    closed = dt.date(2024, 2, 15)
    opened = dt.date(2024, 2, 8)
    unknown = dt.date(2023, 10, 31)
    calendar = pl.concat([one_day(str(closed), "全天"), one_day(str(opened))])
    trades = pl.DataFrame(
        {
            "symbol": ["00001.HK"] * 3,
            "entry_date": [opened, closed, unknown],
            "exit_date": [closed, opened, opened],
        }
    )
    result = check_trade_dates(trades, calendar)
    assert result["trade_row"].to_list() == [0, 1, 2]
    assert result["leg"].to_list() == ["exit_date", "entry_date", "entry_date"]
    assert trades.height == 3
