import datetime as dt

import polars as pl
import pytest

from quant.data.connectors.tushare import TushareConnector
from quant.data.mappers import (
    TushareAdjustmentFactorMapper,
    TushareBarMapper,
    TushareInstrumentMapper,
)
from quant.domain import Bar1dSchema


class FakePro:
    def __init__(self) -> None:
        self.daily_calls: list[dict[str, str]] = []

    def daily(self, **kwargs):
        self.daily_calls.append(kwargs)
        symbols = [kwargs["ts_code"]] if "ts_code" in kwargs else ["000001.SZ", "600000.SH"]
        return pl.DataFrame({
            "ts_code": symbols, "trade_date": ["20260710"] * len(symbols),
            "open": [10.0] * len(symbols), "high": [10.5] * len(symbols),
            "low": [9.8] * len(symbols), "close": [10.2] * len(symbols),
            "vol": [1000.0] * len(symbols), "amount": [10.2] * len(symbols),
        })

    def hk_daily(self, **kwargs):
        symbols = [kwargs["ts_code"]] if "ts_code" in kwargs else ["00700.HK", "00005.HK"]
        return pl.DataFrame({
            "ts_code": symbols, "trade_date": ["20260710"] * len(symbols),
            "open": [500.0] * len(symbols), "high": [510.0] * len(symbols),
            "low": [495.0] * len(symbols), "close": [505.0] * len(symbols),
            "vol": [1000.0] * len(symbols), "amount": [505000.0] * len(symbols),
        })

    def adj_factor(self, **kwargs):
        return pl.DataFrame({
            "ts_code": [kwargs["ts_code"]], "trade_date": ["20260710"],
            "adj_factor": [12.5],
        })

    def hk_adjfactor(self, **kwargs):
        return pl.DataFrame({
            "ts_code": [kwargs["ts_code"]], "trade_date": ["20260710"],
            "cum_adjfactor": [1.25],
        })


def test_a_share_units_are_converted_to_shares_and_yuan() -> None:
    connector = TushareConnector(pro_client=FakePro())
    raw = connector.fetch_bar_1d(
        ["000001.SZ"], dt.date(2026, 7, 10), dt.date(2026, 7, 10)
    )
    clean = TushareBarMapper().map(raw)
    assert clean.row(0, named=True)["volume"] == 100_000.0
    assert clean.row(0, named=True)["amount"] == 10_200.0


def test_hk_units_remain_shares_and_hkd() -> None:
    connector = TushareConnector(pro_client=FakePro())
    raw = connector.fetch_bar_1d(
        ["00700.HK"], dt.date(2026, 7, 10), dt.date(2026, 7, 10)
    )
    clean = TushareBarMapper().map(raw)
    assert clean.row(0, named=True)["volume"] == 1000.0
    assert clean.row(0, named=True)["amount"] == 505000.0


def _raw_ohlc(*, market: str, open_: float, high: float, low: float, close: float) -> pl.DataFrame:
    symbol = "02609.HK" if market == "HK" else "000001.SZ"
    return pl.DataFrame(
        {
            "_request_symbol": [symbol],
            "_market": [market],
            "trade_date": ["20260710"],
            "open": [open_],
            "high": [high],
            "low": [low],
            "close": [close],
            "vol": [100.0],
            "amount": [1_000.0],
        }
    )


def test_hk_open_auction_outside_vendor_range_expands_canonical_range() -> None:
    raw = _raw_ohlc(market="HK", open_=3.08, high=3.06, low=2.92, close=2.96)
    clean = TushareBarMapper().map(raw)

    assert raw.row(0, named=True)["high"] == 3.06
    assert clean.row(0, named=True)["high"] == 3.08
    assert clean.row(0, named=True)["open"] == 3.08
    Bar1dSchema.validate(clean)


def test_hk_open_below_vendor_low_expands_canonical_range() -> None:
    clean = TushareBarMapper().map(
        _raw_ohlc(market="HK", open_=2.90, high=3.06, low=2.92, close=2.96)
    )
    assert clean.row(0, named=True)["low"] == 2.90
    Bar1dSchema.validate(clean)


@pytest.mark.parametrize(
    "market, open_, high, low, close",
    [
        ("SZ", 10.6, 10.5, 9.8, 10.2),
        ("HK", 3.00, 3.06, 2.92, 3.08),
        ("HK", 3.00, 2.90, 3.10, 3.00),
    ],
)
def test_mapper_does_not_hide_non_hk_open_only_ohlc_errors(
    market: str, open_: float, high: float, low: float, close: float
) -> None:
    clean = TushareBarMapper().map(
        _raw_ohlc(market=market, open_=open_, high=high, low=low, close=close)
    )
    with pytest.raises(Exception):
        Bar1dSchema.validate(clean)


def test_maps_a_and_h_adjustment_factor_columns() -> None:
    connector = TushareConnector(pro_client=FakePro())
    raw = connector.fetch_adjust_factors(
        ["000001.SZ", "00700.HK"], dt.date(2026, 7, 10), dt.date(2026, 7, 10)
    )
    clean = TushareAdjustmentFactorMapper().map(raw).sort("symbol")
    assert clean.get_column("adj_factor").to_list() == [12.5, 1.25]


def test_long_history_is_split_below_provider_row_limit() -> None:
    client = FakePro()
    connector = TushareConnector(pro_client=client)
    connector.fetch_bar_1d(
        ["000001.SZ"], dt.date(2000, 1, 1), dt.date(2010, 1, 1)
    )
    assert len(client.daily_calls) == 2


def test_single_day_batches_multiple_symbols_in_one_request() -> None:
    client = FakePro()
    raw = TushareConnector(pro_client=client).fetch_bar_1d(
        ["000001.SZ", "600000.SH"], dt.date(2026, 7, 10), dt.date(2026, 7, 10)
    )
    assert len(client.daily_calls) == 1
    assert set(raw.get_column("_request_symbol")) == {"000001.SZ", "600000.SH"}
    assert "ts_code" not in client.daily_calls[0]


def test_factor_mapper_keeps_only_change_events() -> None:
    raw = pl.DataFrame({
        "_request_symbol": ["000001.SZ"] * 3,
        "_market": ["SZ"] * 3,
        "trade_date": ["20260101", "20260102", "20260103"],
        "adj_factor": [1.0, 1.0, 1.2],
    })
    clean = TushareAdjustmentFactorMapper().map(raw)
    assert clean.get_column("effective_date").to_list() == [
        dt.date(2026, 1, 1), dt.date(2026, 1, 3)
    ]


def test_instrument_mapper_filters_provider_temporary_codes() -> None:
    raw = pl.DataFrame({
        "ts_code": ["600000.SH", "T600018.SH"], "name": ["浦发银行", "临时代码"],
        "list_date": ["19991110", "20260710"], "delist_date": [None, None],
        "_request_list_status": ["L", "L"],
    })
    clean = TushareInstrumentMapper("SH").map(raw)
    assert clean.get_column("symbol").to_list() == ["600000.SH"]


class FakeRawPro:
    """记录每次 API 调用参数；可配置空响应与同键重复行。"""

    def __init__(
        self,
        *,
        empty: bool = False,
        duplicate_key_rows: bool = False,
    ) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.empty = empty
        self.duplicate_key_rows = duplicate_key_rows

    def _record(self, method: str, kwargs: dict[str, object]) -> pl.DataFrame:
        self.calls.append((method, dict(kwargs)))
        if self.empty:
            return pl.DataFrame()
        if self.duplicate_key_rows:
            # 同键两行，供应商顺序精确为 [B, A]
            return pl.DataFrame({
                "ts_code": ["000001.SZ", "000001.SZ"],
                "trade_date": ["20260710", "20260710"],
                "row_id": ["B", "A"],
                "value": [2.0, 1.0],
            })
        return pl.DataFrame({
            "ts_code": ["000001.SZ"],
            "trade_date": ["20260710"],
            "value": [1.0],
        })

    def index_weight(self, **kwargs):
        return self._record("index_weight", kwargs)

    def daily(self, **kwargs):
        return self._record("daily", kwargs)

    def hk_daily(self, **kwargs):
        return self._record("hk_daily", kwargs)

    def adj_factor(self, **kwargs):
        return self._record("adj_factor", kwargs)

    def index_daily(self, **kwargs):
        return self._record("index_daily", kwargs)

    def suspend_d(self, **kwargs):
        return self._record("suspend_d", kwargs)

    def stk_limit(self, **kwargs):
        return self._record("stk_limit", kwargs)

    def dividend(self, **kwargs):
        return self._record("dividend", kwargs)

    def fund_daily(self, **kwargs):
        return self._record("fund_daily", kwargs)

    def fund_adj(self, **kwargs):
        return self._record("fund_adj", kwargs)

    def fund_div(self, **kwargs):
        return self._record("fund_div", kwargs)


def test_raw_methods_pass_exact_parameters_and_fields() -> None:
    client = FakeRawPro()
    connector = TushareConnector(pro_client=client)
    start = dt.date(2026, 1, 1)
    end = dt.date(2026, 1, 31)
    fields = "ts_code,trade_date,close"

    connector.fetch_index_weight_raw(
        index_code="000300.SH", start=start, end=end, fields=fields
    )
    connector.fetch_daily_raw(
        symbol="000001.SZ", start=start, end=end, fields=fields
    )
    connector.fetch_hk_daily_batch_raw(
        symbols=("00005.HK", "00700.HK"), start=start, end=end, fields=fields
    )
    connector.fetch_adj_factor_raw(
        symbol="000001.SZ", start=start, end=end, fields=fields
    )
    connector.fetch_index_daily_raw(
        index_code="H00300.CSI", start=start, end=end, fields=fields
    )
    connector.fetch_suspend_raw(
        symbol="000001.SZ", start=start, end=end, fields=fields
    )
    connector.fetch_stk_limit_raw(
        symbol="600000.SH", start=start, end=end, fields=fields
    )
    connector.fetch_dividend_raw(symbol="000001.SZ", fields=fields)
    connector.fetch_fund_daily_raw(
        symbol="510300.SH", start=start, end=end, fields=fields
    )
    connector.fetch_fund_adj_raw(
        symbol="510300.SH", start=start, end=end, fields=fields
    )
    connector.fetch_fund_div_raw(symbol="510300.SH", fields=fields)

    assert client.calls == [
        (
            "index_weight",
            {
                "index_code": "000300.SH",
                "start_date": "20260101",
                "end_date": "20260131",
                "fields": fields,
            },
        ),
        (
            "daily",
            {
                "ts_code": "000001.SZ",
                "start_date": "20260101",
                "end_date": "20260131",
                "fields": fields,
            },
        ),
        (
            "hk_daily",
            {
                "ts_code": "00005.HK,00700.HK",
                "start_date": "20260101",
                "end_date": "20260131",
                "fields": fields,
            },
        ),
        (
            "adj_factor",
            {
                "ts_code": "000001.SZ",
                "start_date": "20260101",
                "end_date": "20260131",
                "fields": fields,
            },
        ),
        (
            "index_daily",
            {
                "ts_code": "H00300.CSI",
                "start_date": "20260101",
                "end_date": "20260131",
                "fields": fields,
            },
        ),
        (
            "suspend_d",
            {
                "ts_code": "000001.SZ",
                "start_date": "20260101",
                "end_date": "20260131",
                "suspend_type": "S",
                "fields": fields,
            },
        ),
        (
            "stk_limit",
            {
                "ts_code": "600000.SH",
                "start_date": "20260101",
                "end_date": "20260131",
                "fields": fields,
            },
        ),
        (
            "dividend",
            {
                "ts_code": "000001.SZ",
                "fields": fields,
            },
        ),
        (
            "fund_daily",
            {
                "ts_code": "510300.SH",
                "start_date": "20260101",
                "end_date": "20260131",
                "fields": fields,
            },
        ),
        (
            "fund_adj",
            {
                "ts_code": "510300.SH",
                "start_date": "20260101",
                "end_date": "20260131",
                "fields": fields,
            },
        ),
        (
            "fund_div",
            {
                "ts_code": "510300.SH",
                "fields": fields,
            },
        ),
    ]


@pytest.mark.parametrize(
    "symbols",
    [
        (),
        ("00700.HK", "00005.HK"),
        ("00005.HK", "00005.HK"),
        ("700.HK",),
        ("000001.SZ",),
    ],
)
def test_hk_daily_batch_raw_rejects_invalid_symbols(
    symbols: tuple[str, ...],
) -> None:
    with pytest.raises(ValueError, match="^HK_DAILY_BATCH_SYMBOLS_INVALID$"):
        TushareConnector(pro_client=FakeRawPro()).fetch_hk_daily_batch_raw(
            symbols=symbols,
            start=dt.date(2026, 1, 1),
            end=dt.date(2026, 1, 31),
            fields="ts_code,trade_date",
        )


def test_raw_methods_accept_empty_response() -> None:
    client = FakeRawPro(empty=True)
    connector = TushareConnector(pro_client=client)
    start = dt.date(2026, 1, 1)
    end = dt.date(2026, 1, 31)
    fields = "ts_code,trade_date"

    assert connector.fetch_index_weight_raw(
        index_code="000300.SH", start=start, end=end, fields=fields
    ).is_empty()
    assert connector.fetch_daily_raw(
        symbol="000001.SZ", start=start, end=end, fields=fields
    ).is_empty()
    assert connector.fetch_adj_factor_raw(
        symbol="000001.SZ", start=start, end=end, fields=fields
    ).is_empty()
    assert connector.fetch_index_daily_raw(
        index_code="H00300.CSI", start=start, end=end, fields=fields
    ).is_empty()
    assert connector.fetch_suspend_raw(
        symbol="000001.SZ", start=start, end=end, fields=fields
    ).is_empty()
    assert connector.fetch_stk_limit_raw(
        symbol="000001.SZ", start=start, end=end, fields=fields
    ).is_empty()
    assert connector.fetch_dividend_raw(
        symbol="000001.SZ", fields=fields
    ).is_empty()
    assert connector.fetch_fund_daily_raw(
        symbol="510300.SH", start=start, end=end, fields=fields
    ).is_empty()
    assert connector.fetch_fund_adj_raw(
        symbol="510300.SH", start=start, end=end, fields=fields
    ).is_empty()
    assert connector.fetch_fund_div_raw(
        symbol="510300.SH", fields=fields
    ).is_empty()


def test_raw_methods_passthrough_fields() -> None:
    client = FakeRawPro()
    connector = TushareConnector(pro_client=client)
    custom = "con_code,weight,trade_date"
    connector.fetch_index_weight_raw(
        index_code="000300.SH",
        start=dt.date(2026, 1, 1),
        end=dt.date(2026, 1, 31),
        fields=custom,
    )
    assert client.calls[0][1]["fields"] == custom
    fund_custom = "trade_date,adj_factor,ts_code"
    connector.fetch_fund_adj_raw(
        symbol="510300.SH",
        start=dt.date(2026, 1, 1),
        end=dt.date(2026, 1, 31),
        fields=fund_custom,
    )
    assert client.calls[1][1]["fields"] == fund_custom
    # connector 不得重排或改写 caller 传入的 fields 字符串
    assert client.calls[1][1]["fields"] != ",".join(
        sorted(fund_custom.split(","))
    )


def test_raw_methods_reject_illegal_dates_and_codes() -> None:
    connector = TushareConnector(pro_client=FakeRawPro())
    start = dt.date(2026, 2, 1)
    end = dt.date(2026, 1, 1)
    fields = "ts_code"

    with pytest.raises(ValueError, match="start"):
        connector.fetch_daily_raw(
            symbol="000001.SZ", start=start, end=end, fields=fields
        )
    with pytest.raises(ValueError, match="start"):
        connector.fetch_index_weight_raw(
            index_code="000300.SH", start=start, end=end, fields=fields
        )
    with pytest.raises(ValueError, match="start"):
        connector.fetch_suspend_raw(
            symbol="000001.SZ", start=start, end=end, fields=fields
        )

    with pytest.raises(ValueError, match="证券代码"):
        connector.fetch_daily_raw(
            symbol="00700.HK",
            start=dt.date(2026, 1, 1),
            end=dt.date(2026, 1, 2),
            fields=fields,
        )
    with pytest.raises(ValueError, match="证券代码"):
        connector.fetch_adj_factor_raw(
            symbol="BAD",
            start=dt.date(2026, 1, 1),
            end=dt.date(2026, 1, 2),
            fields=fields,
        )
    with pytest.raises(ValueError, match="证券代码"):
        connector.fetch_stk_limit_raw(
            symbol="000001",
            start=dt.date(2026, 1, 1),
            end=dt.date(2026, 1, 2),
            fields=fields,
        )
    with pytest.raises(ValueError, match="证券代码"):
        connector.fetch_dividend_raw(symbol="H00300.CSI", fields=fields)
    with pytest.raises(ValueError, match="证券代码"):
        connector.fetch_suspend_raw(
            symbol="00700.HK",
            start=dt.date(2026, 1, 1),
            end=dt.date(2026, 1, 2),
            fields=fields,
        )
    with pytest.raises(ValueError, match="证券代码"):
        connector.fetch_suspend_raw(
            symbol="000001",
            start=dt.date(2026, 1, 1),
            end=dt.date(2026, 1, 2),
            fields=fields,
        )

    with pytest.raises(ValueError, match="指数代码"):
        connector.fetch_index_weight_raw(
            index_code="00700.HK",
            start=dt.date(2026, 1, 1),
            end=dt.date(2026, 1, 2),
            fields=fields,
        )
    with pytest.raises(ValueError, match="指数代码"):
        connector.fetch_index_daily_raw(
            index_code="NOTANINDEX",
            start=dt.date(2026, 1, 1),
            end=dt.date(2026, 1, 2),
            fields=fields,
        )


def test_fund_raw_methods_reject_before_any_sdk_call() -> None:
    client = FakeRawPro()
    connector = TushareConnector(pro_client=client)
    start = dt.date(2026, 1, 1)
    end = dt.date(2026, 1, 2)
    fields = "ts_code,trade_date,adj_factor"

    for bad_symbol in (True, "", "00700.HK", "H00300.CSI", "51030.SH", "0510300.SH"):
        with pytest.raises(ValueError, match="基金代码"):
            connector.fetch_fund_daily_raw(
                symbol=bad_symbol,  # type: ignore[arg-type]
                start=start,
                end=end,
                fields=fields,
            )
        with pytest.raises(ValueError, match="基金代码"):
            connector.fetch_fund_adj_raw(
                symbol=bad_symbol,  # type: ignore[arg-type]
                start=start,
                end=end,
                fields=fields,
            )
        with pytest.raises(ValueError, match="基金代码"):
            connector.fetch_fund_div_raw(
                symbol=bad_symbol,  # type: ignore[arg-type]
                fields=fields,
            )

    with pytest.raises(ValueError, match="start"):
        connector.fetch_fund_daily_raw(
            symbol="510300.SH", start=end, end=start, fields=fields
        )
    with pytest.raises(ValueError, match="date"):
        connector.fetch_fund_adj_raw(
            symbol="510300.SH",
            start="20260101",  # type: ignore[arg-type]
            end=end,
            fields=fields,
        )
    with pytest.raises(ValueError, match="date"):
        connector.fetch_fund_adj_raw(
            symbol="510300.SH",
            start=True,  # type: ignore[arg-type]
            end=end,
            fields=fields,
        )
    assert client.calls == []


@pytest.mark.parametrize(
    "bad_symbol",
    (
        "５１０３００.SH",  # 全角 Unicode 数字
        "٥١٠٣٠٠.SH",  # Arabic-Indic 数字
    ),
)
def test_fund_raw_methods_reject_unicode_digit_symbols_before_sdk(
    bad_symbol: str,
) -> None:
    """connector 基金代码须与 backfill ASCII [0-9]{6} 同口径；Unicode 数字不得触达 SDK。"""
    client = FakeRawPro()
    connector = TushareConnector(pro_client=client)
    start = dt.date(2026, 1, 1)
    end = dt.date(2026, 1, 2)
    fields = "x"

    with pytest.raises(ValueError, match="基金代码"):
        connector.fetch_fund_daily_raw(
            symbol=bad_symbol, start=start, end=end, fields=fields
        )
    with pytest.raises(ValueError, match="基金代码"):
        connector.fetch_fund_adj_raw(
            symbol=bad_symbol, start=start, end=end, fields=fields
        )
    with pytest.raises(ValueError, match="基金代码"):
        connector.fetch_fund_div_raw(symbol=bad_symbol, fields=fields)
    assert client.calls == []


def test_fund_raw_methods_accept_ascii_sh_sz_symbols() -> None:
    """合法 ASCII 510300.SH / 159919.SZ 仍可到达 SDK，参数不被改写。"""
    client = FakeRawPro()
    connector = TushareConnector(pro_client=client)
    start = dt.date(2026, 1, 1)
    end = dt.date(2026, 1, 2)
    fields = "ts_code,trade_date"

    connector.fetch_fund_daily_raw(
        symbol="510300.SH", start=start, end=end, fields=fields
    )
    connector.fetch_fund_adj_raw(
        symbol="159919.SZ", start=start, end=end, fields=fields
    )
    connector.fetch_fund_div_raw(symbol="510300.SH", fields=fields)
    assert client.calls == [
        (
            "fund_daily",
            {
                "ts_code": "510300.SH",
                "start_date": "20260101",
                "end_date": "20260102",
                "fields": fields,
            },
        ),
        (
            "fund_adj",
            {
                "ts_code": "159919.SZ",
                "start_date": "20260101",
                "end_date": "20260102",
                "fields": fields,
            },
        ),
        (
            "fund_div",
            {"ts_code": "510300.SH", "fields": fields},
        ),
    ]


def test_raw_methods_preserve_duplicate_key_rows_order_b_then_a() -> None:
    """跨既有七 endpoint + 三基金 endpoint：同键两行供应商顺序 [B,A] 必须原样保留。"""
    client = FakeRawPro(duplicate_key_rows=True)
    connector = TushareConnector(pro_client=client)
    start = dt.date(2026, 7, 10)
    end = dt.date(2026, 7, 10)
    fields = "ts_code,trade_date,row_id,value"

    frames = [
        connector.fetch_daily_raw(
            symbol="000001.SZ", start=start, end=end, fields=fields
        ),
        connector.fetch_adj_factor_raw(
            symbol="000001.SZ", start=start, end=end, fields=fields
        ),
        connector.fetch_stk_limit_raw(
            symbol="000001.SZ", start=start, end=end, fields=fields
        ),
        connector.fetch_index_weight_raw(
            index_code="000300.SH", start=start, end=end, fields=fields
        ),
        connector.fetch_index_daily_raw(
            index_code="H00300.CSI", start=start, end=end, fields=fields
        ),
        connector.fetch_suspend_raw(
            symbol="000001.SZ", start=start, end=end, fields=fields
        ),
        connector.fetch_dividend_raw(symbol="000001.SZ", fields=fields),
        connector.fetch_fund_daily_raw(
            symbol="510300.SH", start=start, end=end, fields=fields
        ),
        connector.fetch_fund_adj_raw(
            symbol="510300.SH", start=start, end=end, fields=fields
        ),
        connector.fetch_fund_div_raw(symbol="510300.SH", fields=fields),
    ]
    assert len(frames) == 10
    expected = {
        "ts_code": ["000001.SZ", "000001.SZ"],
        "trade_date": ["20260710", "20260710"],
        "row_id": ["B", "A"],
        "value": [2.0, 1.0],
    }
    for frame in frames:
        assert frame.columns == ["ts_code", "trade_date", "row_id", "value"]
        assert frame.get_column("row_id").to_list() == ["B", "A"]
        assert frame.get_column("value").to_list() == [2.0, 1.0]
        # 只比较值/列序/行序，不要求同一 DataFrame 对象引用
        assert frame.to_dict(as_series=False) == expected
