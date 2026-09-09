import datetime as dt
from pathlib import Path

import polars as pl
import pytest

from quant.data.etf_research_inputs import read_etf_research_inputs


def test_source_cutover_and_missing_session(monkeypatch):
    dates = [dt.date(2026, 7, 10), dt.date(2026, 7, 13)]
    bars = pl.DataFrame({
        "symbol": ["510300.SH"] * 3,
        "trade_date": [dates[0], dates[0], dates[1]],
        "source": ["baostock", "tushare", "tushare"],
    })
    prices = pl.DataFrame({
        "symbol": ["510300.SH"] * 2, "trade_date": dates,
        "adjustment_method": ["TOTAL_RETURN_DIVIDEND"] * 2,
    })

    def read(path):
        path = str(path).replace("\\", "/")
        if "/bar_1d/" in path:
            return bars
        if "/research_price_1d/" in path:
            return prices
        market = "SH" if "market=SH" in path else "SZ"
        if "/trade_calendar/" in path:
            return pl.DataFrame({"market": [market] * 2, "date": dates, "is_open": [True] * 2})
        return pl.DataFrame({"symbol": ["510300.SH" if market == "SH" else "159919.SZ"]})

    monkeypatch.setattr(pl, "read_parquet", read)
    actual, *_ = read_etf_research_inputs(Path("data"), ["510300.SH"], dates[0], dates[1])
    assert actual.get_column("source").to_list() == ["baostock", "tushare"]
    bars = bars.filter(pl.col("trade_date") == dates[0])
    with pytest.raises(ValueError, match="Incomplete or duplicate ETF bars"):
        read_etf_research_inputs(Path("data"), ["510300.SH"], dates[0], dates[1])
