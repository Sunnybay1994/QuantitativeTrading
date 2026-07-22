import datetime as dt
from pathlib import Path

import polars as pl

from quant.data.mappers import AkshareResearchPriceMapper
from quant.data.reprocess_etf_total_return import ArchivedEtfTotalReturnConnector


class FakeDividendClient:
    def fund_etf_dividend_sina(self, *, symbol: str) -> pl.DataFrame:
        assert symbol == "sz159919"
        return pl.DataFrame({
            "日期": [dt.date(2020, 1, 1), dt.date(2026, 7, 10)],
            "累计分红": [0.2, 1.2],
        })


def test_archived_prices_and_dividends_build_total_return_input(tmp_path: Path):
    raw_path = tmp_path / "bars.parquet"
    pl.DataFrame({
        "_request_symbol": ["159919.SZ", "159919.SZ"],
        "date": ["2026-07-09", "2026-07-10"],
        "close": ["10.0", "9.0"],
        "tradestatus": ["1", "1"],
    }).write_parquet(raw_path)
    connector = ArchivedEtfTotalReturnConnector(raw_path, FakeDividendClient())
    raw = connector.fetch_research_price_1d(
        ["159919.SZ"], dt.date(2026, 7, 9), dt.date(2026, 7, 10)
    )
    assert raw.get_column("_cash_dividend").to_list() == [0.0, 1.0]
    result = AkshareResearchPriceMapper(source=connector.source).map(raw)
    assert result.get_column("adjusted_close").to_list() == [10.0, 10.0]
    assert result.get_column("source").unique().to_list() == ["baostock_akshare"]


def test_combined_raw_keeps_rows_without_baostock_trading_status(tmp_path: Path):
    akshare_path = tmp_path / "akshare" / "bars.parquet"
    baostock_path = tmp_path / "baostock" / "bars.parquet"
    akshare_path.parent.mkdir()
    baostock_path.parent.mkdir()
    pl.DataFrame({
        "_request_symbol": ["159919.SZ"],
        "date": [dt.date(2025, 12, 31)],
        "close": [10.0],
    }).write_parquet(akshare_path)
    pl.DataFrame({
        "_request_symbol": ["159919.SZ"],
        "date": ["2026-01-05"],
        "close": ["10.1"],
        "tradestatus": ["1"],
    }).write_parquet(baostock_path)
    connector = ArchivedEtfTotalReturnConnector(
        [akshare_path, baostock_path], FakeDividendClient()
    )
    raw = connector.fetch_research_price_1d(
        ["159919.SZ"], dt.date(2025, 12, 31), dt.date(2026, 1, 5)
    )
    assert raw.get_column("日期").to_list() == [
        dt.date(2025, 12, 31), dt.date(2026, 1, 5)
    ]
    assert connector.source == "akshare_baostock"
