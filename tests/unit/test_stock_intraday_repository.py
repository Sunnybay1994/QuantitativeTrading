import datetime as dt

import polars as pl
import pytest

from quant.data.stock_intraday_repository import read_stock_five_minute_pool


def test_pool_requires_all_files_and_applies_date_and_symbol_scope(tmp_path):
    symbols = ("000001.SZ", "000333.SZ")
    day = dt.date(2026, 9, 8)
    expected = pl.DataFrame({"symbol": symbols, "trade_date": [day, day]})
    query = dict(symbols=symbols, start=day, end=day, expected_traded_days=expected)
    root = tmp_path / "clean/bar_intraday/freq=5m/source=baostock"
    for symbol in symbols:
        directory = root / f"symbol={symbol}"
        directory.mkdir(parents=True)
        pl.DataFrame({"symbol": [symbol, symbol], "trade_date": [day, dt.date(2026, 9, 9)],
                      "close": [10., 11.]}).write_parquet(directory / "data.parquet")
        if symbol == symbols[0]:
            with pytest.raises(FileNotFoundError, match="pending for 1"):
                read_stock_five_minute_pool(tmp_path, **query)
    result = read_stock_five_minute_pool(tmp_path, **query)
    assert result.height == 2
    assert set(result["symbol"]) == set(symbols)
    assert set(result["trade_date"]) == {day}
    pl.DataFrame({"symbol": ["000333.SZ"], "trade_date": [dt.date(2026, 9, 7)], "close": [10.]}).write_parquet(
        root / "symbol=000333.SZ/data.parquet")
    with pytest.raises(ValueError, match="known traded"):
        read_stock_five_minute_pool(tmp_path, **query)
    pl.DataFrame({"symbol": ["600000.SH"], "trade_date": [day], "close": [10.]}).write_parquet(
        root / "symbol=000333.SZ/data.parquet")
    with pytest.raises(ValueError, match="another symbol"):
        read_stock_five_minute_pool(tmp_path, **query)
