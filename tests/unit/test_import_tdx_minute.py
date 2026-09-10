import datetime as dt
import struct

import polars as pl
import pytest

from quant.data.import_tdx_minute import import_symbol, parse_lc5


def _record(day, minute=575, volume=100, amount=1000.):
    return struct.pack("<HHfffffII", (day.year-2004)*2048+day.month*100+day.day,
                       minute, 10., 11., 9., 10.5, amount, volume, 0)


def test_binary_date_float_prices_share_units_and_interval():
    day = dt.date(2025, 2, 28)
    row = parse_lc5(_record(day), "002027.SZ").row(0, named=True)
    assert row["trade_date"] == day
    assert row["bar_start"].time() == dt.time(9, 30)
    assert row["bar_end"].time() == dt.time(9, 35)
    assert (row["open"], row["close"], row["volume"], row["amount"]) == (10., 10.5, 100., 1000.)
    for invalid in (_record(day)+b"x", _record(day, minute=700), _record(day)*2,
                    _record(day, amount=float("nan")), _record(day, volume=0)):
        with pytest.raises(ValueError):
            parse_lc5(invalid, "002027.SZ")


def test_import_preserves_raw_and_repeated_input_is_noop(tmp_path):
    day = dt.date(2025, 2, 28)
    source = tmp_path / "source/sz/fzline/sz002027.lc5"
    source.parent.mkdir(parents=True)
    source.write_bytes(_record(day))
    calendar = tmp_path / "data/clean/trade_calendar/market=SZ/data.parquet"
    calendar.parent.mkdir(parents=True)
    pl.DataFrame({"date": [day], "is_open": [True], "is_half_day": [False]}).write_parquet(calendar)
    first = import_symbol(tmp_path/"data", tmp_path/"source", "002027.SZ", day)
    assert first["changed_rows"] == 1
    assert import_symbol(tmp_path/"data", tmp_path/"source", "002027.SZ", day)["changed_rows"] == 0
    captures = list((tmp_path/"data/raw/tdx_intraday_local/symbol=002027.SZ").glob("*.lc5"))
    assert len(captures) == 1 and captures[0].read_bytes() == source.read_bytes()
    clean = pl.read_parquet(tmp_path/"data/clean/bar_intraday/freq=5m/source=tdx/symbol=002027.SZ/data.parquet")
    assert not clean["session_complete"].item()


def test_lunch_zero_transaction_quote_does_not_fill_a_missing_bar():
    day = dt.date(2024, 12, 30)
    encoded = (day.year-2004)*2048+day.month*100+day.day
    placeholder = struct.pack("<HHfffffII", encoded, 780, 10., 10., 10., 10., 0., 0, 0)
    bars = b"".join(_record(day, minute) for minute in (*range(575, 691, 5), *range(790, 901, 5)))
    frame = parse_lc5(bars+placeholder, "002217.SZ")
    assert frame.height == 47
    from quant.factors.intraday_low_frequency import compute_intraday_low_frequency_factors
    result = compute_intraday_low_frequency_factors(frame, sessions=(day,), window=1)
    assert not result["valid_day"].item()
    assert result["intraday_tail_amount20"].item() is None
