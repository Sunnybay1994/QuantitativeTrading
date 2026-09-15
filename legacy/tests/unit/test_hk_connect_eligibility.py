import datetime as dt
import json
from pathlib import Path

import polars as pl
import pytest

from quant.data.hk_connect_eligibility import (
    eligibility_on,
    normalize_szse,
    normalize_tables,
    read_official_table,
    read_szse_pages,
    reconstruct,
)


def inputs() -> tuple[pl.DataFrame, pl.DataFrame]:
    snapshot = pl.DataFrame({"SECURITY_CODE": ["00001", "09988"],
        "UPDATE_DATE": ["2024-09-11"] * 2, "TRADE_FLAG": ["1"] * 2,
        "ABBR_CN": ["A", "B"], "ABBR_EN": ["A", "B"], "SECURITY_TYPE": ["股票"] * 2})
    events = pl.DataFrame({"SECURITY_CODE": ["00001", "00002", "09988"],
        "VALID_DATE": ["2023-01-01", "2024-04-01", "2024-09-10"],
        "ADJUST_TYPE": ["调进", "调出", "调进"], "FILE_DATE": ["2026-09-04"] * 3,
        "SECURITY_ABBR": ["A", "C", "B"], "ABBR_EN": ["A", "C", "B"],
        "SECURITY_TYPE": ["股票"] * 3})
    return snapshot, events


def test_invert_and_replay_uses_effective_dates_not_update_dates() -> None:
    snapshot, events = normalize_tables(*inputs())
    assert events["published_date"].null_count() == 3
    assert events["source_updated_date"][0] == dt.date(2026, 9, 4)
    intervals = reconstruct(snapshot, events, dt.date(2023, 11, 1))
    before = eligibility_on(intervals, dt.date(2024, 9, 9))
    after = eligibility_on(intervals, dt.date(2024, 9, 10))
    assert not before.filter(pl.col("symbol") == "09988.HK")["buy_eligible"][0]
    assert after.filter(pl.col("symbol") == "09988.HK")["buy_eligible"][0]
    start = eligibility_on(intervals, dt.date(2023, 11, 1))
    assert set(start.filter("buy_eligible")["symbol"]) == {"00001.HK", "00002.HK"}
    assert not after.filter(pl.col("symbol") == "00002.HK")["buy_eligible"][0]
    with pytest.raises(ValueError, match="outside"):
        eligibility_on(intervals, dt.date(2024, 9, 12))


def test_event_at_start_is_already_effective() -> None:
    snapshot, events = normalize_tables(*inputs())
    result = eligibility_on(reconstruct(snapshot, events, dt.date(2024, 9, 10)),
                            dt.date(2024, 9, 10))
    assert result.filter(pl.col("symbol") == "09988.HK")["buy_eligible"][0]


def test_contradictory_events_and_duplicates_rejected() -> None:
    raw, raw_events = inputs()
    snapshot, events = normalize_tables(raw, raw_events)
    bad = events.with_columns(pl.when(pl.col("symbol") == "09988.HK")
        .then(pl.lit("REMOVE")).otherwise(pl.col("action")).alias("action"))
    with pytest.raises(ValueError, match="contradiction"):
        reconstruct(snapshot, bad, dt.date(2023, 11, 1))
    with pytest.raises(ValueError, match="Duplicate"):
        normalize_tables(raw, pl.concat([raw_events, raw_events.head(1)]))
    with pytest.raises(ValueError, match="buy-eligible"):
        normalize_tables(raw.with_columns(pl.lit("2").alias("TRADE_FLAG")), raw_events)


def test_partial_sse_response_rejected(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonp"
    payload = {"pageHelp": {"data": [{"x": 1}], "total": 2, "pageCount": 1}}
    path.write_text("jsonpCallback(" + json.dumps(payload) + ")", encoding="utf-8")
    with pytest.raises(ValueError, match="Incomplete"):
        read_official_table(path)


def sz_page(path: Path, data: list[dict[str, str]], *, pages: int = 1) -> None:
    path.write_text(json.dumps([{"metadata": {"pagecount": pages, "recordcount": len(data),
        "pageno": 1, "subname": "2024-09-11"}, "data": data}]), encoding="utf-8")


def test_szse_complete_pages_and_direction(tmp_path: Path) -> None:
    common = {"zqdm": "09988", "zqjc": "B", "zqywjc": "B"}
    sz_page(tmp_path / "snapshot_001.json", [common])
    sz_page(tmp_path / "events_001.json", [{**common, "tznr": "调入", "sxrq": "2024-09-10"}])
    snapshot, events = normalize_szse(tmp_path)
    assert snapshot["route"][0] == "SZ_CONNECT"
    assert events["effective_date"][0] == dt.date(2024, 9, 10)
    sz_page(tmp_path / "events_001.json", [{**common, "tznr": "未知", "sxrq": "2024-09-10"}])
    with pytest.raises(ValueError, match="Unknown"):
        normalize_szse(tmp_path)
    sz_page(tmp_path / "events_001.json", [common], pages=2)
    with pytest.raises(ValueError, match="Incomplete"):
        read_szse_pages(tmp_path, "events")
