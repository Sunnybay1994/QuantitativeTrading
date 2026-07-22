"""AKShare 连接器骨架测试，不访问真实网络。"""

import datetime as dt

import polars as pl
import pytest

from quant.data.connectors import AkshareConnector
from quant.data.connectors.akshare_connector import AKShareConnector


class FakeAkshare:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []

    def stock_sh_a_spot_em(self) -> pl.DataFrame:
        return pl.DataFrame({"代码": ["600000"]})

    def stock_sz_a_spot_em(self) -> pl.DataFrame:
        return pl.DataFrame({"代码": ["000001"]})

    def stock_hk_spot_em(self) -> pl.DataFrame:
        return pl.DataFrame({"代码": ["00700"]})

    def tool_trade_date_hist_sina(self) -> pl.DataFrame:
        return pl.DataFrame({"trade_date": [dt.date(2026, 7, 10)]})

    def stock_zh_a_hist(self, **kwargs: str) -> pl.DataFrame:
        self.calls.append(("stock_zh_a_hist", kwargs))
        return pl.DataFrame({"日期": [dt.date(2026, 7, 10)], "收盘": [10.0]})

    def stock_zh_a_daily(self, **kwargs: str) -> pl.DataFrame:
        self.calls.append(("stock_zh_a_daily", kwargs))
        return pl.DataFrame(
            {
                "date": [dt.date(2026, 7, 10)],
                "open": [10.0],
                "high": [10.5],
                "low": [9.8],
                "close": [10.2],
                "volume": [1000.0],
                "amount": [10200.0],
            }
        )

    def stock_hk_hist(self, **kwargs: str) -> pl.DataFrame:
        self.calls.append(("stock_hk_hist", kwargs))
        return pl.DataFrame({"日期": [dt.date(2026, 7, 10)], "收盘": [400.0]})

    def fund_etf_hist_em(self, **kwargs: str) -> pl.DataFrame:
        self.calls.append(("fund_etf_hist_em", kwargs))
        return pl.DataFrame(
            {
                "日期": [dt.date(2026, 7, 10)],
                "开盘": [4.0],
                "最高": [4.1],
                "最低": [3.9],
                "收盘": [4.05],
                "成交量": [1000],
                "成交额": [4050.0],
            }
        )

    def fund_etf_hist_sina(self, **kwargs: str) -> pl.DataFrame:
        self.calls.append(("fund_etf_hist_sina", kwargs))
        return pl.DataFrame({
            "date": [dt.date(2026, 7, 9), dt.date(2026, 7, 10)],
            "open": [4.0, 4.1],
            "high": [4.2, 4.2],
            "low": [3.9, 4.0],
            "close": [4.1, 4.15],
            "volume": [100000, 120000],
            "amount": [410000.0, 498000.0],
        })


def test_legacy_class_name_is_compatibility_alias():
    assert AKShareConnector is AkshareConnector


def test_instrument_endpoint_selected_by_market():
    connector = AkshareConnector(FakeAkshare())

    assert connector.fetch_instruments("SH")["代码"].to_list() == ["600000"]
    assert connector.fetch_instruments("HK")["代码"].to_list() == ["00700"]


def test_mixed_market_bars_keep_request_symbol():
    client = FakeAkshare()
    connector = AkshareConnector(client)
    start = dt.date(2026, 7, 1)
    end = dt.date(2026, 7, 10)

    result = connector.fetch_bar_1d(["000001.SZ", "00700.HK"], start, end)

    assert result["_request_symbol"].to_list() == ["000001.SZ", "00700.HK"]
    assert [name for name, _ in client.calls] == ["stock_zh_a_hist", "stock_hk_hist"]
    assert client.calls[0][1]["adjust"] == ""


def test_invalid_range_and_unsupported_calendar_rejected():
    connector = AkshareConnector(FakeAkshare())

    with pytest.raises(ValueError, match="start"):
        connector.fetch_trade_calendar("SH", dt.date(2026, 7, 2), dt.date(2026, 7, 1))
    with pytest.raises(NotImplementedError, match="港股"):
        connector.fetch_trade_calendar("HK", dt.date(2026, 7, 1), dt.date(2026, 7, 2))


def test_a_share_falls_back_to_sina_endpoint():
    client = FakeAkshare()

    def fail_primary(**kwargs: str) -> pl.DataFrame:
        raise ConnectionError("primary unavailable")

    client.stock_zh_a_hist = fail_primary  # type: ignore[method-assign]
    result = AkshareConnector(client).fetch_bar_1d(
        ["000001.SZ"], dt.date(2026, 7, 10), dt.date(2026, 7, 10)
    )

    assert result["_endpoint"].to_list() == ["stock_zh_a_daily"]
    assert client.calls[-1][1]["symbol"] == "sz000001"


def test_etf_falls_back_when_stock_endpoints_are_empty():
    client = FakeAkshare()

    def empty(**kwargs: str) -> pl.DataFrame:
        return pl.DataFrame()

    client.stock_zh_a_hist = empty  # type: ignore[method-assign]
    client.stock_zh_a_daily = empty  # type: ignore[method-assign]
    result = AkshareConnector(client).fetch_bar_1d(
        ["510300.SH"], dt.date(2026, 7, 10), dt.date(2026, 7, 10)
    )

    assert result["_endpoint"].to_list() == ["fund_etf_hist_em"]
    assert client.calls[-1][1]["symbol"] == "510300"


def test_research_price_endpoint_requires_hfq_and_keeps_lineage():
    client = FakeAkshare()
    result = AkshareConnector(client).fetch_research_price_1d(
        ["510300.SH"], dt.date(2026, 7, 1), dt.date(2026, 7, 10)
    )
    assert result["_request_symbol"].to_list() == ["510300.SH"]
    assert result["_adjustment"].to_list() == ["hfq"]
    assert client.calls[-1] == (
        "fund_etf_hist_em",
        {
            "symbol": "510300",
            "period": "daily",
            "start_date": "20260701",
            "end_date": "20260710",
            "adjust": "hfq",
        },
    )
    with pytest.raises(ValueError, match="拒绝"):
        AkshareConnector(client).fetch_research_price_1d(
            ["510300.SH"],
            dt.date(2026, 7, 1),
            dt.date(2026, 7, 10),
            adjustment="qfq",
        )


def test_etf_falls_back_to_sina_full_history_and_filters_dates():
    client = FakeAkshare()

    def empty(**kwargs: str) -> pl.DataFrame:
        return pl.DataFrame()

    client.stock_zh_a_hist = empty  # type: ignore[method-assign]
    client.stock_zh_a_daily = empty  # type: ignore[method-assign]
    client.fund_etf_hist_em = empty  # type: ignore[method-assign]
    result = AkshareConnector(client).fetch_bar_1d(
        ["510300.SH"], dt.date(2026, 7, 10), dt.date(2026, 7, 10)
    )
    assert result.get_column("date").to_list() == [dt.date(2026, 7, 10)]
    assert result.get_column("_endpoint").to_list() == ["fund_etf_hist_sina"]
