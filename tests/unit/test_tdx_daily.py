import datetime as dt
import struct
from pathlib import Path

import polars as pl

from quant.data.tdx_daily import (
    classify_instrument,
    decode_daily_clean,
    import_daily_file,
)
from quant.data.tdx_daily_repository import read_tdx_daily_bars
from quant.data.validate_tdx_daily import compare_daily, compare_minute_close


def record(
    day: int = 20260909,
    *,
    open_: int = 1000,
    high: int = 1100,
    low: int = 900,
    close: int = 1050,
    amount: float = 105000.0,
    volume: int = 10000,
) -> bytes:
    return struct.pack("<IIIIIfII", day, open_, high, low, close, amount, volume, 0)


def test_classification_and_price_scaling():
    assert classify_instrument("600000.SH") == "STOCK"
    assert classify_instrument("518880.SH") == "ETF"
    assert classify_instrument("000001.SH") == "INDEX"
    assert classify_instrument("000001.SZ") == "STOCK"
    assert classify_instrument("899050.BJ") == "INDEX"
    assert classify_instrument("920001.BJ") == "STOCK"
    _, stock, _ = decode_daily_clean(record(), symbol="600000.SH", instrument_type="STOCK")
    _, etf, _ = decode_daily_clean(record(), symbol="518880.SH", instrument_type="ETF")
    assert stock["close"][0] == 10.5
    assert etf["close"][0] == 1.05
    assert stock["volume"][0] == 10000 and stock["amount"][0] == 105000


def test_bad_daily_rows_and_tail_stay_out_of_clean():
    payload = record() + record(day=20261340) + record(day=20260908, high=800) + b"tail"
    raw, clean, stats = decode_daily_clean(
        payload, symbol="600000.SH", instrument_type="STOCK"
    )
    assert raw.height == 3 and clean.height == 1
    assert stats.trailing_bytes == 4
    assert stats.invalid_date_rows == 1
    assert stats.invalid_ohlcv_rows == 1


def test_other_instrument_is_raw_only():
    raw, clean, stats = decode_daily_clean(
        record(), symbol="110000.SH", instrument_type="OTHER"
    )
    assert raw.height == 1 and clean.is_empty() and stats.excluded_other_rows == 1


def test_daily_volume_lot_overflow_is_normalized_to_shares():
    payload = record(open_=580, high=600, low=570, close=580, amount=2_600_000_000.0,
                     volume=44_827_586)
    _, clean, stats = decode_daily_clean(
        payload, symbol="513180.SH", instrument_type="ETF"
    )
    assert clean["volume"][0] == 4_482_758_600
    assert stats.volume_scaled_100_rows == 1


def test_daily_import_noop_and_repository(tmp_path: Path):
    source = tmp_path / "vipdoc/sh/lday/sh600000.day"
    source.parent.mkdir(parents=True)
    source.write_bytes(record())
    data_root = tmp_path / "data"
    first = import_daily_file(source, data_root=data_root)
    second = import_daily_file(source, data_root=data_root)
    assert first.clean_changed_rows == 1 and first.raw_written
    assert second.clean_changed_rows == 0 and second.skipped_unchanged
    assert len(list((data_root / "raw/tdx_daily").rglob("*.parquet"))) == 1
    bars = read_tdx_daily_bars(
        data_root,
        symbol="600000.SH",
        start=dt.date(2026, 9, 9),
        end=dt.date(2026, 9, 9),
    )
    assert bars.height == 1 and bars["close"][0] == 10.5


def test_daily_reference_and_minute_close_comparisons():
    day = dt.date(2026, 9, 9)
    daily = pl.DataFrame({
        "symbol": ["600000.SH"], "trade_date": [day], "close": [10.5],
        "volume": [100.0], "amount": [1050.0],
    })
    reference = daily.with_columns(pl.lit(110.0).alias("volume"))
    compared = compare_daily(daily, reference)
    assert compared["close_abs_error"][0] == 0
    assert abs(compared["volume_rel_error"][0] - 10 / 110) < 1e-12
    minute = daily.select("symbol", "trade_date", "close").with_columns(
        pl.lit(dt.datetime(2026, 9, 9, 14, 55)).alias("bar_start")
    )
    assert compare_minute_close(daily, minute)["close_abs_error"][0] == 0
