"""数据源字段映射测试。"""

import datetime as dt

import polars as pl

from quant.data.mappers import AkshareBarMapper, AkshareResearchPriceMapper


def test_akshare_mapper_accepts_sina_english_columns():
    raw = pl.DataFrame(
        {
            "_request_symbol": ["000001.SZ"],
            "_endpoint": ["stock_zh_a_daily"],
            "date": [dt.date(2026, 7, 10)],
            "open": [10.0],
            "high": [10.5],
            "low": [9.8],
            "close": [10.2],
            "volume": [1000.0],
            "amount": [10200.0],
        }
    )

    clean = AkshareBarMapper().map(raw)

    assert clean.columns == [
        "symbol",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "adj_factor",
        "source",
    ]
    assert clean["source"].to_list() == ["akshare"]


def test_research_price_mapper_builds_cash_dividend_total_return() -> None:
    raw = pl.DataFrame({
        "_request_symbol": ["159919.SZ", "159919.SZ"],
        "_adjustment": ["total_return_dividend", "total_return_dividend"],
        "日期": [dt.date(2026, 7, 9), dt.date(2026, 7, 10)],
        "收盘": [10.0, 9.0],
        "_cash_dividend": [0.0, 1.0],
    })
    result = AkshareResearchPriceMapper().map(raw)
    assert result.get_column("adjusted_close").to_list() == [10.0, 10.0]
    assert result.get_column("adjustment_method").unique().to_list() == [
        "TOTAL_RETURN_DIVIDEND"
    ]


def test_akshare_eastmoney_volume_is_converted_from_lots_to_shares() -> None:
    raw = pl.DataFrame({
        "_request_symbol": ["510300.SH"],
        "_endpoint": ["fund_etf_hist_em"],
        "日期": [dt.date(2026, 7, 10)],
        "开盘": [4.0], "最高": [4.1], "最低": [3.9], "收盘": [4.05],
        "成交量": [1000.0], "成交额": [405000.0],
    })
    result = AkshareBarMapper().map(raw)
    assert result.item(0, "volume") == 100000.0
