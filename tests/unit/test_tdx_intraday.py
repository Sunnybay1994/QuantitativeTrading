import datetime as dt
import json
import struct
from pathlib import Path

import polars as pl

from quant.data.stock_intraday_repository import (
    read_stock_five_minute_bars,
    read_stock_intraday_bars,
)
from quant.data.tdx_intraday import decode_daily_payload, decode_minute_payload, import_minute_file
from quant.data.validate_tdx_intraday import compare_daily_sources


def packed_date(value: dt.date) -> int:
    return (value.year - 2004) * 2048 + value.month * 100 + value.day


def minute_record(
    day: dt.date,
    minute: int,
    *,
    close: float = 10.5,
    volume: int = 100,
    amount: float = 1050.0,
) -> bytes:
    return struct.pack(
        "<Hhfffffii",
        packed_date(day),
        minute,
        10.0,
        11.0,
        9.0,
        close,
        amount,
        volume,
        0,
    )


def test_decode_tdx_end_timestamp_units_and_daily_reference():
    day = dt.date(2026, 9, 8)
    raw, clean, stats = decode_minute_payload(
        minute_record(day, 575), symbol="600000.SH", frequency="5m"
    )
    assert raw.row(0, named=True)["amount"] == 1050.0
    assert clean["bar_start"][0] == dt.datetime(
        2026, 9, 8, 9, 30, tzinfo=dt.timezone(dt.timedelta(hours=8))
    )
    assert clean["bar_end"][0].hour == 9 and clean["bar_end"][0].minute == 35
    assert clean["volume"][0] == 100.0 and clean["amount"][0] == 1050.0
    assert stats.incomplete_days == 1 and stats.missing_bars == 47

    daily, tail = decode_daily_payload(
        struct.pack("<IIIIIfII", 20260908, 1000, 1100, 900, 1050, 105000.0, 10000, 0)
    )
    assert tail == 0
    assert daily.row(0, named=True) == {
        "date": 20260908,
        "open_raw": 1000,
        "high_raw": 1100,
        "low_raw": 900,
        "close_raw": 1050,
        "amount": 105000.0,
        "volume": 10000,
        "reserved": 0,
    }


def test_invalid_tail_duplicate_and_bad_rows_never_become_clean():
    day = dt.date(2026, 9, 8)
    good = minute_record(day, 575)
    bad_time = minute_record(day, 576)
    bad_price = minute_record(day, 580, close=12.0)
    zero = struct.pack("<Hhfffffii", packed_date(day), 585, 0, 0, 0, 0, 0, 0, 0)
    raw, clean, stats = decode_minute_payload(
        good + good + bad_time + bad_price + zero + b"tail",
        symbol="600000.SH",
        frequency="5m",
    )
    assert raw.height == 5
    assert clean.is_empty()
    assert stats.trailing_bytes == 4
    assert stats.duplicate_rows == 2
    assert stats.invalid_time_rows == 1
    assert stats.invalid_ohlcv_rows == 1
    assert stats.zero_placeholder_rows == 1


def test_import_is_idempotent_and_repository_reads_tdx(tmp_path: Path):
    source = tmp_path / "vipdoc/sh/fzline/sh600000.lc5"
    source.parent.mkdir(parents=True)
    day = dt.date(2026, 9, 8)
    source.write_bytes(b"".join(minute_record(day, minute) for minute in (
        list(range(575, 691, 5)) + list(range(785, 901, 5))
    )))
    data_root = tmp_path / "data"
    first = import_minute_file(source, data_root=data_root)
    second = import_minute_file(source, data_root=data_root)
    assert first.clean_changed_rows == 48 and first.raw_written
    assert second.clean_changed_rows == 0 and second.skipped_unchanged
    assert len(list((data_root / "raw/tdx_intraday").rglob("*.parquet"))) == 1
    coverage = json.loads((
        data_root / "clean/bar_intraday/freq=5m/source=tdx/symbol=600000.SH/coverage.json"
    ).read_text())
    assert coverage["valid_rows"] == 48 and coverage["incomplete_days"] == 0

    frame = read_stock_intraday_bars(
        data_root,
        symbol="600000.SH",
        start=day,
        end=day,
        frequency="5m",
        source="tdx",
    )
    assert frame.height == 48 and set(frame["source"]) == {"tdx"}
    assert read_stock_five_minute_bars(
        data_root, symbol="600000.SH", start=day, end=day, source="tdx"
    ).equals(frame)


def test_daily_cross_source_comparison_keeps_auction_volume_difference():
    day = dt.date(2026, 9, 8)
    schema = {
        "symbol": ["600000.SH"],
        "trade_date": [day],
        "bar_start": [dt.datetime(2026, 9, 8, 9, 30)],
        "close": [10.5],
        "volume": [100.0],
        "amount": [1050.0],
        "session_complete": [True],
    }
    tdx = pl.DataFrame(schema)
    other = tdx.with_columns(pl.lit(110.0).alias("volume"), pl.lit(1155.0).alias("amount"))
    result = compare_daily_sources(tdx, other)
    assert result["close_abs_error"][0] == 0
    assert abs(result["volume_rel_error"][0] - 10 / 110) < 1e-12
