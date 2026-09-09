"""BaoStock 连接器测试，不访问真实网络。"""

import datetime as dt

import polars as pl
import pytest

from quant.data.connectors.baostock import BaostockConnector, BaostockResponseError
from quant.data.mappers import (
    BaostockAdjustmentFactorMapper,
    BaostockBarMapper,
    BaostockCalendarMapper,
    BaostockInstrumentMapper,
)


class Response:
    def __init__(
        self,
        *,
        fields: list[str] | None = None,
        rows: list[list[str]] | None = None,
        error_code: str = "0",
        error_msg: str = "success",
    ) -> None:
        self.fields = fields or []
        self.rows = rows or []
        self.error_code = error_code
        self.error_msg = error_msg
        self._index = -1

    def next(self) -> bool:
        self._index += 1
        return self._index < len(self.rows)

    def get_row_data(self) -> list[str]:
        return self.rows[self._index]


class FakeBaostock:
    def __init__(self, *, login_error: bool = False) -> None:
        self.login_error = login_error
        self.logout_calls = 0
        self.query_args: tuple[str, str, dict[str, str]] | None = None

    def login(self) -> Response:
        if self.login_error:
            return Response(error_code="1001", error_msg="login failed")
        return Response()

    def logout(self) -> Response:
        self.logout_calls += 1
        return Response()

    def query_history_k_data_plus(
        self, code: str, fields: str, **kwargs: str
    ) -> Response:
        self.query_args = (code, fields, kwargs)
        names = fields.split(",")
        return Response(
            fields=names,
            rows=[
                [
                    "2026-07-10",
                    code,
                    "13.80",
                    "13.98",
                    "13.75",
                    "13.90",
                    "1000000",
                    "13900000",
                    "3",
                    "1",
                ]
            ],
        )

    def query_trade_dates(self, **kwargs: str) -> Response:
        return Response(
            fields=["calendar_date", "is_trading_day"],
            rows=[["2026-07-10", "1"]],
        )

    def query_stock_basic(self) -> Response:
        return Response(
            fields=["code", "code_name", "ipoDate", "outDate", "type", "status"],
            rows=[
                ["sz.000001", "平安银行", "1991-04-03", "", "1", "1"],
                ["sh.510300", "沪深300ETF", "2012-05-28", "", "5", "1"],
                ["sh.000001", "上证指数", "1991-07-15", "", "2", "1"],
            ],
        )

    def query_adjust_factor(self, code: str, **kwargs: str) -> Response:
        return Response(
            fields=[
                "code",
                "dividOperateDate",
                "foreAdjustFactor",
                "backAdjustFactor",
                "adjustFactor",
            ],
            rows=[[code, "2026-06-12", "1.000000", "124.911625", "124.911625"]],
        )


def test_intraday_detects_error_at_end_of_response():
    class Interrupted(Response):
        def next(self):
            self.error_code = "10002007"
            self.error_msg = "connection interrupted"
            return False

    class Client(FakeBaostock):
        def query_history_k_data_plus(self, code, fields, **kwargs):
            return Interrupted(fields=fields.split(","))

    client = Client()
    with pytest.raises(BaostockResponseError, match="minute response completion"):
        BaostockConnector(client).fetch_intraday("600000.SH", dt.date(2020, 1, 1), dt.date(2026, 9, 8))
    assert client.logout_calls == 1


def test_baostock_bar_query_uses_unadjusted_daily_and_logs_out():
    client = FakeBaostock()
    raw = BaostockConnector(client).fetch_bar_1d(
        ["000001.SZ"], dt.date(2026, 7, 10), dt.date(2026, 7, 10)
    )

    assert client.query_args is not None
    code, _, kwargs = client.query_args
    assert code == "sz.000001"
    assert kwargs["frequency"] == "d"
    assert kwargs["adjustflag"] == "3"
    assert client.logout_calls == 1
    assert raw["_request_symbol"].to_list() == ["000001.SZ"]


def test_baostock_mapper_filters_suspended_rows():
    client = FakeBaostock()
    raw = BaostockConnector(client).fetch_bar_1d(
        ["000001.SZ"], dt.date(2026, 7, 10), dt.date(2026, 7, 10)
    )
    suspended = raw.with_columns(pl.lit("0").alias("tradestatus"))

    assert BaostockBarMapper().map(raw).height == 1
    assert BaostockBarMapper().map(suspended).is_empty()


def test_baostock_login_error_is_explicit_and_does_not_logout():
    client = FakeBaostock(login_error=True)

    with pytest.raises(BaostockResponseError, match="1001"):
        BaostockConnector(client).fetch_bar_1d(
            ["000001.SZ"], dt.date(2026, 7, 10), dt.date(2026, 7, 10)
        )

    assert client.logout_calls == 0


def test_baostock_calendar_maps_open_and_closed_dates():
    raw = pl.DataFrame(
        {
            "calendar_date": ["2026-07-10", "2026-07-11"],
            "is_trading_day": ["1", "0"],
        }
    )

    clean = BaostockCalendarMapper("SH").map(raw)

    assert clean["is_open"].to_list() == [True, False]
    assert clean["market"].to_list() == ["SH", "SH"]


def test_baostock_instrument_mapper_keeps_stocks_and_etfs_only():
    connector = BaostockConnector(FakeBaostock())
    raw = connector.fetch_instruments("SH")

    sh = BaostockInstrumentMapper("SH").map(raw)
    sz = BaostockInstrumentMapper("SZ").map(raw)

    assert sh["symbol"].to_list() == ["510300.SH"]
    assert sh["instrument_type"].to_list() == ["ETF"]
    assert sz["symbol"].to_list() == ["000001.SZ"]
    assert sz["list_date"].to_list() == [dt.date(1991, 4, 3)]


def test_baostock_adjustment_factor_maps_cumulative_backward_factor():
    connector = BaostockConnector(FakeBaostock())
    raw = connector.fetch_adjust_factors(
        ["000001.SZ"], dt.date(1990, 1, 1), dt.date(2026, 7, 10)
    )

    clean = BaostockAdjustmentFactorMapper().map(raw)

    assert clean["effective_date"].to_list() == [dt.date(2026, 6, 12)]
    assert clean["adj_factor"].to_list() == [124.911625]


_REFERENCE_FIELDS = "date,code,open,high,low,close,volume,amount,adjustflag,tradestatus"


class ReferenceBarFakeBaostock:
    """Fake client for fetch_reference_bar_raw; not shared with FakeBaostock above."""

    def __init__(self, *, login_error: bool = False, rows: list[list[str]] | None = None):
        self.login_error = login_error
        self._rows = rows
        self.logout_calls = 0
        self.query_calls: list[tuple[str, str, dict[str, str]]] = []

    def login(self) -> Response:
        if self.login_error:
            return Response(error_code="1001", error_msg="login failed")
        return Response()

    def logout(self) -> Response:
        self.logout_calls += 1
        return Response()

    def query_history_k_data_plus(self, code: str, fields: str, **kwargs: str) -> Response:
        self.query_calls.append((code, fields, dict(kwargs)))
        names = fields.split(",")
        default_row = [
            "2026-07-10", code, "13.80", "13.98", "13.75", "13.90",
            "1000000", "13900000", "3", "1",
        ]
        rows = self._rows if self._rows is not None else [default_row]
        return Response(fields=names, rows=[list(row) for row in rows])


def test_fetch_reference_bar_raw_converts_symbol_and_calls_with_exact_params():
    client = ReferenceBarFakeBaostock()
    connector = BaostockConnector(client)

    raw = connector.fetch_reference_bar_raw(
        symbol="000001.SZ",
        start=dt.date(2026, 7, 1),
        end=dt.date(2026, 7, 10),
        fields=_REFERENCE_FIELDS,
        frequency="d",
        adjustflag="3",
    )

    assert len(client.query_calls) == 1
    code, fields, kwargs = client.query_calls[0]
    assert code == "sz.000001"
    assert fields == _REFERENCE_FIELDS
    assert kwargs == {
        "start_date": "2026-07-01",
        "end_date": "2026-07-10",
        "frequency": "d",
        "adjustflag": "3",
    }
    assert client.logout_calls == 1
    assert list(raw.columns) == _REFERENCE_FIELDS.split(",")
    assert "_request_symbol" not in raw.columns


def test_fetch_reference_bar_raw_preserves_duplicate_rows():
    duplicate_row = [
        "2026-07-10", "sh.600000", "10.0", "10.5", "9.8", "10.2",
        "500000", "5100000", "3", "1",
    ]
    client = ReferenceBarFakeBaostock(rows=[duplicate_row, list(duplicate_row)])
    connector = BaostockConnector(client)

    raw = connector.fetch_reference_bar_raw(
        symbol="600000.SH",
        start=dt.date(2026, 7, 10),
        end=dt.date(2026, 7, 10),
        fields=_REFERENCE_FIELDS,
        frequency="d",
        adjustflag="3",
    )

    assert raw.height == 2
    assert raw["date"].to_list() == ["2026-07-10", "2026-07-10"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"fields": "date,code,close"},
        {"frequency": "w"},
        {"adjustflag": "1"},
        {"symbol": 123},
        {"fields": 123},
        {"frequency": 1},
        {"adjustflag": 1},
        {"start": "2026-07-01"},
        {"end": "2026-07-10"},
        {"start": dt.date(2026, 7, 10), "end": dt.date(2026, 7, 1)},
    ],
)
def test_fetch_reference_bar_raw_rejects_invalid_parameters(overrides: dict):
    client = ReferenceBarFakeBaostock()
    connector = BaostockConnector(client)
    kwargs = {
        "symbol": "000001.SZ",
        "start": dt.date(2026, 7, 1),
        "end": dt.date(2026, 7, 10),
        "fields": _REFERENCE_FIELDS,
        "frequency": "d",
        "adjustflag": "3",
    }
    kwargs.update(overrides)

    with pytest.raises(ValueError):
        connector.fetch_reference_bar_raw(**kwargs)

    assert client.query_calls == []
    assert client.logout_calls == 0


def test_fetch_reference_bar_raw_login_error_raises_without_logout():
    client = ReferenceBarFakeBaostock(login_error=True)
    connector = BaostockConnector(client)

    with pytest.raises(BaostockResponseError, match="1001"):
        connector.fetch_reference_bar_raw(
            symbol="000001.SZ",
            start=dt.date(2026, 7, 1),
            end=dt.date(2026, 7, 10),
            fields=_REFERENCE_FIELDS,
            frequency="d",
            adjustflag="3",
        )

    assert client.query_calls == []
    assert client.logout_calls == 0
