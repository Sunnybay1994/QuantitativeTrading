"""G1-P3 B2C execution facts: price limits and corporate-action reconciliation."""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib
import json
import sys
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import polars as pl
import pytest

from quant.data import m3_backfill as backfill
from quant.data.connectors.cninfo import (
    CNINFO_DIVIDEND_ENDPOINT,
    CNINFO_SHARE_CHANGE_ENDPOINT,
    CNINFO_SOURCE,
    CNINFO_STOCK_ALLOTMENT_FIELDS,
    CNINFO_STOCK_DIVIDEND_FIELDS,
    CNINFO_STOCK_SHARE_CHANGE_FIELDS,
)
from quant.data.m3_backfill import (
    TUSHARE_FIELDS,
    CninfoRequestReceipt,
    CninfoRequestSpec,
    HistoryWindow,
    TushareRequestReceipt,
    TushareRequestSpec,
    VerifiedCninfoRawResponse,
    VerifiedRawResponse,
    response_content_sha256,
)
from quant.data.m3_execution_facts import (
    G1_CORPORATE_ACTION_RECONCILIATION_VERSION,
    G1_CORPORATE_ACTION_SELECTION_VERSION,
    G1_PRICE_LIMIT_METHOD_VERSION,
    CorporateActionReconciliationResult,
    CorporateActionSelectionResult,
    M3G1ExecutionFactError,
    assert_corporate_action_selection_receipt_closure,
    assert_corporate_action_reconciliation_ledger_closure,
    _parse_cninfo_iso_date,
    _consideration_event_id_sha256,
    _decimal_token,
    map_g1_price_limit_response,
    reconcile_g1_corporate_actions,
    require_g1_price_limit_coverage,
    select_g1_cninfo_rights_actions,
    select_g1_cninfo_share_consideration_actions,
    select_g1_corporate_actions,
    verify_corporate_action_reconciliation_result,
    verify_corporate_action_selection_result,
)
from quant.data.m3_identity import clean_table_content_sha256
from quant.domain import PriceLimit1dSchema

_HEX = "a" * 64
_SYMBOL = "600000.SH"
_START = "20260105"
_END = "20260109"
_D0 = dt.date(2026, 1, 5)
_D1 = dt.date(2026, 1, 6)
_D2 = dt.date(2026, 1, 7)
_D3 = dt.date(2026, 1, 8)
_D4 = dt.date(2026, 1, 9)


def _make_verified(
    endpoint: str,
    frame: pl.DataFrame,
    *,
    parameters: dict[str, str] | None = None,
) -> VerifiedRawResponse:
    params = {"fields": TUSHARE_FIELDS[endpoint], **(parameters or {})}
    if endpoint == "dividend":
        params.setdefault("ts_code", _SYMBOL)
    else:
        params.setdefault("start_date", _START)
        params.setdefault("end_date", _END)
        if endpoint in {"daily", "adj_factor", "stk_limit"}:
            params.setdefault("ts_code", _SYMBOL)
    spec = TushareRequestSpec.create(endpoint=endpoint, parameters=params)
    content = response_content_sha256(frame, endpoint)
    columns = tuple(frame.columns)
    parameters_sha256 = backfill._parameters_hash(spec.parameters)
    stable = backfill._stable_response_hash_values(
        {
            "request_id": spec.request_id,
            "endpoint": endpoint,
            "parameters_sha256": parameters_sha256,
            "response_content_sha256": content,
            "row_count": frame.height,
            "columns": columns,
        }
    )
    receipt = TushareRequestReceipt(
        schema_version="m3-g1-tushare-receipt-v1",
        request_id=spec.request_id,
        endpoint=endpoint,  # type: ignore[arg-type]
        parameters=spec.parameters,
        parameters_sha256=parameters_sha256,
        raw_snapshot_id=spec.request_id,
        raw_data_path=f"tushare/{endpoint}/request=x/data.parquet",
        raw_metadata_path=f"tushare/{endpoint}/request=x/metadata.json",
        raw_file_sha256=_HEX,
        raw_metadata_sha256=_HEX,
        response_content_sha256=content,
        stable_response_sha256=stable,
        raw_size_bytes=max(frame.height, 1),
        row_count=frame.height,
        columns=columns,
    )
    return VerifiedRawResponse(spec, receipt, backfill._sha256(asdict(receipt)), frame)


def _make_cninfo_ca_verified(
    *,
    endpoint: str,
    parameters: dict[str, str],
    frame: pl.DataFrame,
):
    spec = backfill.CninfoCorporateActionRequestSpec.create(
        endpoint=endpoint, parameters=parameters  # type: ignore[arg-type]
    )
    content = backfill.cninfo_corporate_action_response_content_sha256(
        frame, endpoint=spec.endpoint
    )
    parameters_sha256 = backfill._parameters_hash(spec.parameters)
    values = {
        "request_id": spec.request_id,
        "endpoint": spec.endpoint,
        "adapter": spec.adapter,
        "parameters_sha256": parameters_sha256,
        "raw_snapshot_id": spec.request_id,
        "raw_data_path": f"cninfo/{spec.endpoint}/{spec.request_id}.json",
        "raw_metadata_path": (
            f"cninfo/{spec.endpoint}/{spec.request_id}.metadata.json"
        ),
        "raw_file_sha256": _HEX,
        "raw_metadata_sha256": _HEX,
        "response_content_sha256": content,
        "resultcode": 200,
        "resultmsg": "success",
        "count": frame.height,
        "total": frame.height,
        "raw_size_bytes": 1,
        "row_count": frame.height,
        "columns": tuple(frame.columns),
    }
    stable = backfill._cninfo_ca_stable_response_hash_values(values)
    receipt = backfill.CninfoCorporateActionRequestReceipt(
        schema_version="m3-g1-cninfo-corporate-action-receipt-v1",
        request_id=spec.request_id,
        source=CNINFO_SOURCE,
        endpoint=spec.endpoint,
        adapter=spec.adapter,
        parameters=spec.parameters,
        parameters_sha256=parameters_sha256,
        raw_snapshot_id=spec.request_id,
        raw_data_path=values["raw_data_path"],
        raw_metadata_path=values["raw_metadata_path"],
        raw_file_sha256=_HEX,
        raw_metadata_sha256=_HEX,
        response_content_sha256=content,
        stable_response_sha256=stable,
        resultcode=200,
        resultmsg="success",
        count=frame.height,
        total=frame.height,
        raw_size_bytes=1,
        row_count=frame.height,
        columns=tuple(frame.columns),
    )
    return backfill.VerifiedCninfoCorporateActionRawResponse(
        spec=spec,
        receipt=receipt,
        receipt_sha256=backfill._sha256(asdict(receipt)),
        frame=frame,
        resultcode=200,
        resultmsg="success",
        count=frame.height,
        total=frame.height,
    )


def _limit_frame(rows: list[dict[str, Any]] | None = None) -> pl.DataFrame:
    default = [
        {
            "trade_date": "20260106",
            "ts_code": _SYMBOL,
            "pre_close": 10.0,
            "up_limit": 11.0,
            "down_limit": 9.0,
        },
        {
            "trade_date": "20260107",
            "ts_code": _SYMBOL,
            "pre_close": 10.5,
            "up_limit": 11.55,
            "down_limit": 9.45,
        },
        {
            "trade_date": "20260108",
            "ts_code": _SYMBOL,
            "pre_close": 10.2,
            "up_limit": 11.22,
            "down_limit": 9.18,
        },
        {
            "trade_date": "20260109",
            "ts_code": _SYMBOL,
            "pre_close": 10.1,
            "up_limit": 11.11,
            "down_limit": 9.09,
        },
    ]
    return pl.DataFrame(rows if rows is not None else default).select(
        TUSHARE_FIELDS["stk_limit"].split(",")
    )


def _dividend_row(**overrides: Any) -> dict[str, Any]:
    row = {
        "ts_code": _SYMBOL,
        "end_date": "20251231",
        "ann_date": "20260102",
        "div_proc": "实施",
        "stk_div": 0.0,
        "stk_bo_rate": 0.0,
        "stk_co_rate": 0.0,
        "cash_div": 0.09,
        "cash_div_tax": 0.1,
        "record_date": "20260106",
        "ex_date": "20260107",
        "pay_date": "20260108",
        "div_listdate": None,
        "imp_ann_date": "20260103",
        "base_date": "20251231",
        "base_share": 100.0,
    }
    row.update(overrides)
    return row


def _dividend_frame(rows: list[dict[str, Any]] | None = None) -> pl.DataFrame:
    data = rows if rows is not None else [_dividend_row()]
    return pl.DataFrame(data).select(TUSHARE_FIELDS["dividend"].split(","))


def _rights_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {name: None for name in CNINFO_STOCK_ALLOTMENT_FIELDS}
    row.update(
        {
            "DECLAREDATE": "2026-01-05",
            "F001V": "001001",
            "F002V": "A股",
            "F004N": "3.0",
            "F005N": "45.68",
            "F011D": "2026-01-06",
            "F012D": "2026-01-07",
            "F013D": "2026-01-05",
            "F014D": "2026-01-06",
            "F017N": "300.0",
            "F024N": "1000.0",
            "F025N": "1300.0",
            "F038D": "2026-01-09",
            "F052D": "2026-01-07",
            "ORGNAME": "测试公司",
            "SECCODE": "600000",
            "SECNAME": "测试",
            "SUBID": "1",
        }
    )
    row.update(overrides)
    return row


def _cninfo_frame(rows: list[dict[str, Any]] | None = None) -> pl.DataFrame:
    data = rows if rows is not None else [_rights_row()]
    return pl.DataFrame(
        data, schema={name: pl.Utf8 for name in CNINFO_STOCK_ALLOTMENT_FIELDS}
    )


def _make_cninfo_verified(
    frame: pl.DataFrame,
    *,
    symbols_param: str = "600000",
    start_date: str = _START,
    end_date: str = _END,
) -> VerifiedCninfoRawResponse:
    params = {"symbols": symbols_param, "start_date": start_date, "end_date": end_date}
    spec = CninfoRequestSpec.create(parameters=params)
    content = backfill.cninfo_response_content_sha256(frame)
    columns = tuple(frame.columns)
    parameters_sha256 = backfill._parameters_hash(spec.parameters)
    row_count = frame.height
    stable = backfill._cninfo_stable_response_hash_values(
        {
            "request_id": spec.request_id,
            "endpoint": spec.endpoint,
            "adapter": spec.adapter,
            "parameters_sha256": parameters_sha256,
            "response_content_sha256": content,
            "resultcode": 200,
            "count": row_count,
            "total": row_count,
            "row_count": row_count,
            "columns": columns,
        }
    )
    receipt = CninfoRequestReceipt(
        schema_version="m3-g1-cninfo-receipt-v1",
        request_id=spec.request_id,
        source="cninfo",
        endpoint="stock_allotment",
        adapter=spec.adapter,
        parameters=spec.parameters,
        parameters_sha256=parameters_sha256,
        raw_snapshot_id=spec.request_id,
        raw_data_path="cninfo/stock_allotment/request=x/data.parquet",
        raw_metadata_path="cninfo/stock_allotment/request=x/metadata.json",
        raw_file_sha256=_HEX,
        raw_metadata_sha256=_HEX,
        response_content_sha256=content,
        stable_response_sha256=stable,
        resultcode=200,
        count=row_count,
        total=row_count,
        raw_size_bytes=max(row_count, 1),
        row_count=row_count,
        columns=columns,
    )
    return VerifiedCninfoRawResponse(
        spec,
        receipt,
        backfill._sha256(asdict(receipt)),
        frame,
        200,
        row_count,
        row_count,
    )


def _bars_and_factors_for_rights(
    *,
    prev_close: float = 10.0,
    rights_price: float = 5.0,
    rights_ratio: float = 0.3,
    factor_prev: float = 1.0,
    factor_eff: float | None = None,
    include_ex_daily: bool = True,
    ex_pre_close: float | None = None,
    rights_row_overrides: dict[str, Any] | None = None,
) -> tuple[pl.DataFrame, pl.DataFrame, VerifiedRawResponse, pl.DataFrame]:
    rights_cash = rights_price * rights_ratio
    declared = prev_close * (1.0 + rights_ratio) / (prev_close + rights_cash)
    actual_factor = factor_eff if factor_eff is not None else factor_prev * declared
    market_pre = ex_pre_close if ex_pre_close is not None else prev_close / declared
    closes: dict[dt.date, tuple[float, float]] = {
        _D0: (prev_close, prev_close),
        _D1: (prev_close, prev_close),
    }
    if include_ex_daily:
        closes[_D2] = (market_pre, market_pre)
    bars_rows = []
    factor_rows = []
    for day, (close, _) in sorted(closes.items()):
        adj = factor_prev if day < _D2 else actual_factor
        bars_rows.append(
            {
                "symbol": _SYMBOL,
                "trade_date": day,
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "volume": 1.0,
                "amount": 1.0,
                "adj_factor": adj,
                "source": "tushare",
            }
        )
    factor_dates = [_D0, _D1, _D2]
    for day in factor_dates:
        factor_rows.append(
            {
                "symbol": _SYMBOL,
                "effective_date": day,
                "adj_factor": factor_prev if day < _D2 else actual_factor,
                "source": "tushare",
            }
        )
    bars = pl.DataFrame(bars_rows)
    factors = pl.DataFrame(factor_rows)
    daily = _make_verified(
        "daily",
        _daily_frame(closes),
        parameters={
            "ts_code": _SYMBOL,
            "start_date": _START,
            "end_date": _END,
        },
    )
    overrides = {"F005N": str(rights_price), "F004N": str(rights_ratio * 10.0)}
    if rights_row_overrides:
        overrides.update(rights_row_overrides)
    cninfo_response = _make_cninfo_verified(
        _cninfo_frame([_rights_row(**overrides)])
    )
    actions = select_g1_cninfo_rights_actions(
        response=cninfo_response, history=_history(), symbols=[_SYMBOL]
    ).ledger
    return bars, factors, daily, actions


def _daily_rows(
    *,
    closes: dict[dt.date, tuple[float, float]],
    symbol: str = _SYMBOL,
) -> list[dict[str, Any]]:
    rows = []
    for day, (close, pre_close) in sorted(closes.items()):
        rows.append(
            {
                "ts_code": symbol,
                "trade_date": day.strftime("%Y%m%d"),
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "pre_close": pre_close,
                "change": 0.0,
                "pct_chg": 0.0,
                "vol": 1.0,
                "amount": 1.0,
            }
        )
    return rows


def _daily_frame(closes: dict[dt.date, tuple[float, float]]) -> pl.DataFrame:
    return pl.DataFrame(_daily_rows(closes=closes)).select(
        TUSHARE_FIELDS["daily"].split(",")
    )


def _calendar(days: list[tuple[dt.date, bool]]) -> pl.DataFrame:
    rows = []
    for day, is_open in days:
        for market in ("SH", "SZ"):
            rows.append(
                {
                    "market": market,
                    "date": day,
                    "is_open": is_open,
                    "is_connect_open": False,
                    "is_half_day": False,
                }
            )
    return pl.DataFrame(rows)


def _default_calendar() -> pl.DataFrame:
    # Mon-Fri open around fixture week; Sat closed.
    days = [
        (dt.date(2026, 1, 5), True),
        (dt.date(2026, 1, 6), True),
        (dt.date(2026, 1, 7), True),
        (dt.date(2026, 1, 8), True),
        (dt.date(2026, 1, 9), True),
        (dt.date(2026, 1, 10), False),
        (dt.date(2026, 1, 12), True),
    ]
    return _calendar(days)


def _instrument(
    symbol: str = _SYMBOL,
    *,
    list_date: dt.date = dt.date(2000, 1, 1),
    delist_date: dt.date | None = None,
) -> pl.DataFrame:
    market = symbol.rsplit(".", 1)[-1]
    return pl.DataFrame(
        {
            "symbol": [symbol],
            "market": [market],
            "name": ["x"],
            "instrument_type": ["STOCK"],
            "currency": ["CNY"],
            "list_date": [list_date],
            "delist_date": [delist_date],
            "board_lot": [100],
            "status": ["LISTED" if delist_date is None else "DELISTED"],
        }
    )


def _suspension(
    rows: list[dict[str, Any]] | None = None,
) -> pl.DataFrame:
    if not rows:
        return pl.DataFrame(
            schema={
                "symbol": pl.Utf8,
                "trade_date": pl.Date,
                "suspension_scope": pl.Utf8,
                "suspension_detail": pl.Utf8,
                "source": pl.Utf8,
                "source_snapshot_id": pl.Utf8,
            }
        )
    return pl.DataFrame(rows)


def _coverage_bars(
    dates: list[dt.date], *, symbol: str = _SYMBOL
) -> pl.DataFrame:
    """Minimal Bar1d rows so coverage treats these sessions as tradeable."""
    return pl.DataFrame(
        {
            "symbol": [symbol] * len(dates),
            "trade_date": dates,
            "open": [10.0] * len(dates),
            "high": [10.5] * len(dates),
            "low": [9.5] * len(dates),
            "close": [10.0] * len(dates),
            "volume": [1000.0] * len(dates),
            "amount": [10000.0] * len(dates),
            "adj_factor": [1.0] * len(dates),
            "source": ["tushare"] * len(dates),
        }
    )


def _history() -> HistoryWindow:
    return HistoryWindow(_D0, _D4)


def _assert_code(exc_info: pytest.ExceptionInfo[BaseException], code: str) -> None:
    err = exc_info.value
    assert isinstance(err, M3G1ExecutionFactError)
    assert str(err) == code
    assert repr(err) == f"M3G1ExecutionFactError({code!r})"
    assert err.__cause__ is None
    assert "token=" not in str(err)
    assert "token=" not in repr(err)
    assert "/home/" not in str(err)
    assert "C:\\" not in str(err)


def test_version_constants() -> None:
    assert G1_PRICE_LIMIT_METHOD_VERSION == "tushare_stk_limit_suspension_aware_v2"
    assert G1_CORPORATE_ACTION_SELECTION_VERSION == (
        "tushare_dividend_cninfo_rights_share_consideration_basis_v8"
    )
    assert G1_CORPORATE_ACTION_SELECTION_VERSION != (
        "tushare_dividend_cninfo_rights_capital_iso_date_v5"
    )
    assert G1_CORPORATE_ACTION_RECONCILIATION_VERSION == (
        "tushare_factor_daily_preclose_suspension_resume_basis_terms_v9"
    )


def test_price_limit_happy_path_and_sorted() -> None:
    out = map_g1_price_limit_response(response=_make_verified("stk_limit", _limit_frame()))
    PriceLimit1dSchema.validate(out)
    assert out["has_price_limit"].to_list() == [True] * out.height
    assert out.sort(["symbol", "trade_date", "source"]).equals(out)


def test_price_limit_identity_drift_before_read() -> None:
    verified = _make_verified("stk_limit", _limit_frame())
    bad = VerifiedRawResponse.__new__(VerifiedRawResponse)
    object.__setattr__(bad, "spec", verified.spec)
    object.__setattr__(bad, "receipt", verified.receipt)
    object.__setattr__(bad, "receipt_sha256", "0" * 64)
    object.__setattr__(bad, "frame", verified.frame)
    with pytest.raises(M3G1ExecutionFactError) as caught:
        map_g1_price_limit_response(response=bad)
    _assert_code(caught, "G1_EXECUTION_FACT_RESPONSE_INVALID")


def test_price_limit_empty_and_column_errors() -> None:
    empty = pl.DataFrame(schema={c: pl.Float64 for c in TUSHARE_FIELDS["stk_limit"].split(",")})
    # empty with wrong dtypes still has columns
    empty = pl.DataFrame(
        {c: [] for c in TUSHARE_FIELDS["stk_limit"].split(",")}
    ).cast(
        {
            "trade_date": pl.Utf8,
            "ts_code": pl.Utf8,
            "pre_close": pl.Float64,
            "up_limit": pl.Float64,
            "down_limit": pl.Float64,
        }
    )
    with pytest.raises(M3G1ExecutionFactError) as caught:
        map_g1_price_limit_response(response=_make_verified("stk_limit", empty))
    _assert_code(caught, "G1_EXECUTION_FACT_EMPTY")

    frame = _limit_frame().select(["ts_code", "trade_date", "pre_close", "up_limit", "down_limit"])
    with pytest.raises(M3G1ExecutionFactError) as caught:
        map_g1_price_limit_response(response=_make_verified("stk_limit", frame))
    _assert_code(caught, "G1_EXECUTION_FACT_COLUMNS_INVALID")


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda r: {**r, "ts_code": "000001.SZ"}, "G1_EXECUTION_FACT_REQUEST_SCOPE_MISMATCH"),
        (lambda r: {**r, "trade_date": "20251231"}, "G1_EXECUTION_FACT_REQUEST_SCOPE_MISMATCH"),
        (lambda r: {**r, "pre_close": True}, "G1_EXECUTION_FACT_VALUE_INVALID"),
        (lambda r: {**r, "pre_close": -1.0}, "G1_EXECUTION_FACT_VALUE_INVALID"),
        (lambda r: {**r, "up_limit": None}, "G1_EXECUTION_FACT_VALUE_INVALID"),
        (lambda r: {**r, "up_limit": 9.0}, "G1_EXECUTION_FACT_VALUE_INVALID"),
        (lambda r: {**r, "pre_close": ""}, "G1_EXECUTION_FACT_VALUE_INVALID"),
    ],
)
def test_price_limit_value_rejects(mutate: Any, code: str) -> None:
    rows = _limit_frame().to_dicts()
    rows[0] = mutate(rows[0])
    with pytest.raises(M3G1ExecutionFactError) as caught:
        map_g1_price_limit_response(response=_make_verified("stk_limit", _limit_frame(rows)))
    _assert_code(caught, code)


def test_price_limit_nonfinite_rejected_at_verified_or_mapper() -> None:
    verified = _make_verified("stk_limit", _limit_frame())
    poisoned = verified.frame.with_columns(pl.lit(float("nan")).alias("pre_close"))
    bad = VerifiedRawResponse.__new__(VerifiedRawResponse)
    object.__setattr__(bad, "spec", verified.spec)
    object.__setattr__(bad, "receipt", verified.receipt)
    object.__setattr__(bad, "receipt_sha256", verified.receipt_sha256)
    object.__setattr__(bad, "frame", poisoned)
    with pytest.raises(M3G1ExecutionFactError) as caught:
        map_g1_price_limit_response(response=bad)
    _assert_code(caught, "G1_EXECUTION_FACT_RESPONSE_INVALID")


def test_price_limit_sentinel_omitted_and_all_sentinel_empty() -> None:
    rows = [
        {
            "trade_date": "20260106",
            "ts_code": _SYMBOL,
            "pre_close": 0.0,
            "up_limit": 0.0,
            "down_limit": 0.0,
        },
        {
            "trade_date": "20260107",
            "ts_code": _SYMBOL,
            "pre_close": None,
            "up_limit": None,
            "down_limit": None,
        },
    ]
    out = map_g1_price_limit_response(response=_make_verified("stk_limit", _limit_frame(rows)))
    assert out.height == 0
    assert list(out.columns) == list(PriceLimit1dSchema.to_schema().columns.keys())
    assert out["has_price_limit"].to_list() == []


def test_price_limit_null_preclose_recovered_from_daily_lookup() -> None:
    rows = [
        {
            "trade_date": "20260106",
            "ts_code": _SYMBOL,
            "pre_close": None,
            "up_limit": 11.0,
            "down_limit": 9.0,
        }
    ]
    # Without lookup: still omitted (legacy sentinel behavior).
    omitted = map_g1_price_limit_response(
        response=_make_verified("stk_limit", _limit_frame(rows))
    )
    assert omitted.height == 0
    # With same-day daily pre_close inside the band: emit clean row.
    out = map_g1_price_limit_response(
        response=_make_verified("stk_limit", _limit_frame(rows)),
        daily_pre_close={(_SYMBOL, _D1): 10.0},
    )
    assert out.height == 1
    assert out["pre_close"].to_list() == [10.0]
    assert out["has_price_limit"].to_list() == [True]
    assert out["up_limit"].to_list() == [11.0]
    assert out["down_limit"].to_list() == [9.0]


def test_price_limit_null_preclose_daily_outside_band_fails() -> None:
    rows = [
        {
            "trade_date": "20260106",
            "ts_code": _SYMBOL,
            "pre_close": None,
            "up_limit": 11.0,
            "down_limit": 9.0,
        }
    ]
    with pytest.raises(M3G1ExecutionFactError) as caught:
        map_g1_price_limit_response(
            response=_make_verified("stk_limit", _limit_frame(rows)),
            daily_pre_close={(_SYMBOL, _D1): 12.0},
        )
    _assert_code(caught, "G1_EXECUTION_FACT_VALUE_INVALID")


def test_price_limit_duplicate_key() -> None:
    rows = _limit_frame().to_dicts()
    rows.append(dict(rows[0]))
    with pytest.raises(M3G1ExecutionFactError) as caught:
        map_g1_price_limit_response(response=_make_verified("stk_limit", _limit_frame(rows)))
    _assert_code(caught, "G1_EXECUTION_FACT_DUPLICATE_KEY")


def test_price_limit_lossless_string_and_schema_false_not_emitted() -> None:
    rows = _limit_frame().to_dicts()
    rows[0]["pre_close"] = "10.0"
    rows[0]["up_limit"] = "11.0"
    rows[0]["down_limit"] = "9.0"
    out = map_g1_price_limit_response(response=_make_verified("stk_limit", _limit_frame(rows)))
    assert out.height >= 1
    assert all(out["has_price_limit"].to_list())
    # Schema still accepts false independently of mapper.
    false_row = out.head(1).with_columns(
        pl.lit(False).alias("has_price_limit"),
        pl.lit(None, dtype=pl.Float64).alias("up_limit"),
        pl.lit(None, dtype=pl.Float64).alias("down_limit"),
    )
    PriceLimit1dSchema.validate(false_row)


def test_price_coverage_next_session_delist_full_day_and_extra() -> None:
    limits = map_g1_price_limit_response(response=_make_verified("stk_limit", _limit_frame()))
    # Extra pre-coverage day kept in limits.
    extra = limits.head(0)
    eligible = pl.DataFrame({"as_of": [_D0], "symbol": [_SYMBOL]})
    bars = _coverage_bars([_D1, _D2, _D3, _D4])
    suspensions = _suspension(
        [
            {
                "symbol": _SYMBOL,
                "trade_date": _D2,
                "suspension_scope": "FULL_DAY",
                "suspension_detail": None,
                "source": "tushare",
                "source_snapshot_id": _HEX,
            }
        ]
    )
    required = require_g1_price_limit_coverage(
        price_limits=limits,
        eligible_keys=eligible,
        suspensions=suspensions,
        calendars=_default_calendar(),
        instruments=_instrument(),
        bars=bars,
        history=_history(),
    )
    # coverage_start = next after D0 -> D1; D2 FULL_DAY excluded; through D4
    assert required.to_dicts() == [
        {"trade_date": _D1, "symbol": _SYMBOL},
        {"trade_date": _D3, "symbol": _SYMBOL},
        {"trade_date": _D4, "symbol": _SYMBOL},
    ]
    _ = extra

    # Missing non-FULL_DAY day fails.
    trimmed = limits.filter(pl.col("trade_date") != _D3)
    with pytest.raises(M3G1ExecutionFactError) as caught:
        require_g1_price_limit_coverage(
            price_limits=trimmed,
            eligible_keys=eligible,
            suspensions=suspensions,
            calendars=_default_calendar(),
            instruments=_instrument(),
            bars=bars,
            history=_history(),
        )
    _assert_code(caught, "G1_PRICE_LIMIT_UNPROVEN")

    # PARTIAL missing fails.
    partial = _suspension(
        [
            {
                "symbol": _SYMBOL,
                "trade_date": _D3,
                "suspension_scope": "PARTIAL",
                "suspension_detail": "am",
                "source": "tushare",
                "source_snapshot_id": _HEX,
            }
        ]
    )
    with pytest.raises(M3G1ExecutionFactError) as caught:
        require_g1_price_limit_coverage(
            price_limits=trimmed,
            eligible_keys=eligible,
            suspensions=partial,
            calendars=_default_calendar(),
            instruments=_instrument(),
            bars=bars,
            history=_history(),
        )
    _assert_code(caught, "G1_PRICE_LIMIT_UNPROVEN")

    # Delist truncates.
    required_delist = require_g1_price_limit_coverage(
        price_limits=limits,
        eligible_keys=eligible,
        suspensions=_suspension(),
        calendars=_default_calendar(),
        instruments=_instrument(delist_date=_D2),
        bars=bars,
        history=_history(),
    )
    assert required_delist.get_column("trade_date").to_list() == [_D1, _D2]

    # No same-day bar excludes the key (even without FULL_DAY).
    required_no_bar = require_g1_price_limit_coverage(
        price_limits=limits,
        eligible_keys=eligible,
        suspensions=_suspension(),
        calendars=_default_calendar(),
        instruments=_instrument(),
        bars=_coverage_bars([_D1, _D3, _D4]),
        history=_history(),
    )
    assert required_no_bar.get_column("trade_date").to_list() == [_D1, _D3, _D4]


def test_price_coverage_false_limit_rejected() -> None:
    limits = map_g1_price_limit_response(response=_make_verified("stk_limit", _limit_frame()))
    false_limits = limits.with_columns(
        pl.lit(False).alias("has_price_limit"),
        pl.lit(None, dtype=pl.Float64).alias("up_limit"),
        pl.lit(None, dtype=pl.Float64).alias("down_limit"),
    )
    with pytest.raises(M3G1ExecutionFactError) as caught:
        require_g1_price_limit_coverage(
            price_limits=false_limits,
            eligible_keys=pl.DataFrame({"as_of": [_D0], "symbol": [_SYMBOL]}),
            suspensions=_suspension(),
            calendars=_default_calendar(),
            instruments=_instrument(),
            bars=_coverage_bars([_D1, _D2, _D3, _D4]),
            history=_history(),
        )
    _assert_code(caught, "G1_PRICE_LIMIT_UNPROVEN")


def test_dividend_empty_and_out_of_window_ignored() -> None:
    empty = pl.DataFrame(
        {c: [] for c in TUSHARE_FIELDS["dividend"].split(",")}
    ).cast({c: pl.Utf8 for c in TUSHARE_FIELDS["dividend"].split(",")})
    # numeric columns
    schema = {c: pl.Utf8 for c in TUSHARE_FIELDS["dividend"].split(",")}
    for col in ("stk_div", "stk_bo_rate", "stk_co_rate", "cash_div", "cash_div_tax", "base_share"):
        schema[col] = pl.Float64
    empty = pl.DataFrame(schema=schema)
    result = select_g1_corporate_actions(
        response=_make_verified("dividend", empty), history=_history()
    )
    assert result.ledger.height == 0
    assert result.selection_evidence.height == 0
    verify_corporate_action_selection_result(result=result)

    old = _dividend_frame(
        [
            _dividend_row(
                ex_date="19920106",
                record_date="19920105",
                pay_date=None,
                cash_div_tax=0.1,
                ann_date=None,
                imp_ann_date=None,
            )
        ]
    )
    # out-of-window missing pay must not block
    result2 = select_g1_corporate_actions(
        response=_make_verified("dividend", old), history=_history()
    )
    assert result2.ledger.height == 0


def test_dividend_in_window_missing_pay_fails() -> None:
    frame = _dividend_frame([_dividend_row(pay_date=None)])
    with pytest.raises(M3G1ExecutionFactError) as caught:
        select_g1_corporate_actions(response=_make_verified("dividend", frame), history=_history())
    _assert_code(caught, "G1_CORPORATE_ACTION_EVENT_INVALID")


def test_dividend_null_unused_cash_leg_stock_only_passes() -> None:
    """Formal shape: 实施 + null cash_div_tax + positive stk_div + list date."""
    frame = _dividend_frame(
        [
            _dividend_row(
                cash_div_tax=None,
                stk_div=1.2,
                pay_date=None,
                div_listdate="20260107",
            )
        ]
    )
    result = select_g1_corporate_actions(
        response=_make_verified("dividend", frame), history=_history()
    )
    assert result.ledger.height == 1
    assert result.ledger["cash_per_share_gross"][0] == 0.0
    assert result.ledger["stock_ratio"][0] == 1.2
    assert result.ledger["pay_date"][0] is None
    assert result.ledger["stock_list_date"][0] == dt.date(2026, 1, 7)
    verify_corporate_action_selection_result(result=result)


def test_dividend_null_unused_stock_leg_cash_only_passes() -> None:
    """实施 + positive cash_div_tax + null stk_div + pay date."""
    frame = _dividend_frame(
        [
            _dividend_row(
                cash_div_tax=0.1,
                stk_div=None,
                pay_date="20260108",
                div_listdate=None,
            )
        ]
    )
    result = select_g1_corporate_actions(
        response=_make_verified("dividend", frame), history=_history()
    )
    assert result.ledger.height == 1
    assert result.ledger["cash_per_share_gross"][0] == 0.1
    assert result.ledger["stock_ratio"][0] == 0.0
    assert result.ledger["pay_date"][0] == dt.date(2026, 1, 8)
    assert result.ledger["stock_list_date"][0] is None
    verify_corporate_action_selection_result(result=result)


def test_dividend_both_legs_null_or_zero_omitted() -> None:
    """Zero-effect 实施 (both legs null→0 or explicit 0) are omitted, not invented."""
    both_null = _dividend_row(
        cash_div_tax=None,
        stk_div=None,
        pay_date=None,
        div_listdate=None,
    )
    both_zero = _dividend_row(
        cash_div_tax=0.0,
        stk_div=0.0,
        pay_date=None,
        div_listdate=None,
    )
    for incomplete in (both_null, both_zero):
        alone = select_g1_corporate_actions(
            response=_make_verified("dividend", _dividend_frame([incomplete])),
            history=_history(),
        )
        assert alone.ledger.height == 0
        verify_corporate_action_selection_result(result=alone)

        mixed = select_g1_corporate_actions(
            response=_make_verified(
                "dividend", _dividend_frame([incomplete, _dividend_row()])
            ),
            history=_history(),
        )
        assert mixed.ledger.height == 1
        assert mixed.ledger["cash_per_share_gross"][0] == 0.1
        verify_corporate_action_selection_result(result=mixed)


def test_dividend_null_ex_date_fully_before_window_skipped() -> None:
    """实施 + null ex_date with all support dates < history.start → skip.

    Formal shape (600176.SH): end/record/list all before window; other valid
    实施 in the same response must still select.
    """
    incomplete = _dividend_row(
        ex_date=None,
        end_date="20140319",
        record_date="20140418",
        pay_date=None,
        div_listdate="20140820",
        cash_div_tax=0.0,
        stk_div=0.1106,
    )
    valid = _dividend_row()
    result = select_g1_corporate_actions(
        response=_make_verified("dividend", _dividend_frame([incomplete, valid])),
        history=_history(),
    )
    assert result.ledger.height == 1
    assert result.ledger["ex_date"][0] == _D2
    assert result.ledger["cash_per_share_gross"][0] == 0.1
    verify_corporate_action_selection_result(result=result)


def test_dividend_null_ex_date_fully_after_window_skipped() -> None:
    incomplete = _dividend_row(
        ex_date=None,
        end_date="20270101",
        record_date="20270102",
        pay_date="20270103",
        div_listdate="20270104",
        cash_div_tax=0.0,
        stk_div=0.1,
    )
    result = select_g1_corporate_actions(
        response=_make_verified(
            "dividend", _dividend_frame([incomplete, _dividend_row()])
        ),
        history=_history(),
    )
    assert result.ledger.height == 1
    assert result.ledger["ex_date"][0] == _D2
    verify_corporate_action_selection_result(result=result)


def test_dividend_null_ex_date_in_window_omitted_not_invented() -> None:
    """窗内/跨越/无支持日的 null ex_date 一律省略；不发明除权日。

    Formal 002131.SZ shape: end/record/list in window, ex_date null, stk_div>0.
    """
    shapes = [
        _dividend_row(
            ex_date=None,
            end_date="20170929",
            record_date="20171213",
            pay_date=None,
            div_listdate="20171218",
            cash_div_tax=0.0,
            stk_div=0.00398595,
        ),
        _dividend_row(
            ex_date=None,
            end_date="20140319",
            record_date="20140418",
            pay_date=None,
            div_listdate="20270101",
            cash_div_tax=0.0,
            stk_div=0.1,
        ),
        _dividend_row(
            ex_date=None,
            end_date=None,
            record_date=None,
            pay_date=None,
            div_listdate=None,
            cash_div_tax=0.0,
            stk_div=0.1,
        ),
    ]
    for incomplete in shapes:
        result = select_g1_corporate_actions(
            response=_make_verified(
                "dividend", _dividend_frame([incomplete, _dividend_row()])
            ),
            history=_history(),
        )
        assert result.ledger.height == 1
        assert result.ledger["ex_date"][0] == _D2
        verify_corporate_action_selection_result(result=result)

    # Non-null illegal ex_date still fail closed (not omitted).
    bad_format = _dividend_frame(
        [
            _dividend_row(
                ex_date="20140399",
                end_date="20140319",
                record_date="20140418",
                pay_date=None,
                div_listdate="20140820",
                cash_div_tax=0.0,
                stk_div=0.1,
            )
        ]
    )
    with pytest.raises(M3G1ExecutionFactError) as caught_bad:
        select_g1_corporate_actions(
            response=_make_verified("dividend", bad_format), history=_history()
        )
    _assert_code(caught_bad, "G1_CORPORATE_ACTION_EVENT_INVALID")


def test_dividend_unimplemented_and_unparseable_ex_date() -> None:
    frame = _dividend_frame([_dividend_row(div_proc="预案")])
    result = select_g1_corporate_actions(
        response=_make_verified("dividend", frame), history=_history()
    )
    assert result.ledger.height == 0

    bad = _dividend_frame([_dividend_row(ex_date="20260199")])
    with pytest.raises(M3G1ExecutionFactError) as caught:
        select_g1_corporate_actions(response=_make_verified("dividend", bad), history=_history())
    _assert_code(caught, "G1_CORPORATE_ACTION_EVENT_INVALID")


def test_dividend_selection_order_duplicate_and_conflict() -> None:
    rows = [
        _dividend_row(imp_ann_date=None, ann_date="20260101", cash_div_tax=0.1),
        _dividend_row(imp_ann_date="20260104", ann_date="20260102", cash_div_tax=0.2),
        _dividend_row(imp_ann_date="20260104", ann_date="20260102", cash_div_tax=0.2),
    ]
    result = select_g1_corporate_actions(
        response=_make_verified("dividend", _dividend_frame(rows)), history=_history()
    )
    assert result.ledger.height == 1
    assert result.ledger["cash_per_share_gross"][0] == 0.2
    evidence = result.selection_evidence.sort("candidate_rank")
    assert evidence.height == 2
    assert evidence["raw_row_count"].to_list() == [2, 1]
    assert evidence["candidate_count"].to_list() == [2, 2]
    assert evidence["selected"].to_list() == [True, False]
    verify_corporate_action_selection_result(result=result)

    conflict = [
        _dividend_row(imp_ann_date="20260104", ann_date="20260102", cash_div_tax=0.2),
        _dividend_row(imp_ann_date="20260104", ann_date="20260102", cash_div_tax=0.3),
    ]
    with pytest.raises(M3G1ExecutionFactError) as caught:
        select_g1_corporate_actions(
            response=_make_verified("dividend", _dividend_frame(conflict)),
            history=_history(),
        )
    _assert_code(caught, "G1_CORPORATE_ACTION_VERSION_CONFLICT")

    pay_conflict = [
        _dividend_row(imp_ann_date="20260104", pay_date="20260108"),
        _dividend_row(imp_ann_date="20260104", pay_date="20260109"),
    ]
    with pytest.raises(M3G1ExecutionFactError) as caught:
        select_g1_corporate_actions(
            response=_make_verified("dividend", _dividend_frame(pay_conflict)),
            history=_history(),
        )
    _assert_code(caught, "G1_CORPORATE_ACTION_VERSION_CONFLICT")


def test_dividend_event_id_stable_pay_changes_candidate() -> None:
    base = select_g1_corporate_actions(
        response=_make_verified("dividend", _dividend_frame()), history=_history()
    )
    newer_pay = select_g1_corporate_actions(
        response=_make_verified(
            "dividend",
            _dividend_frame([_dividend_row(pay_date="20260109")]),
        ),
        history=_history(),
    )
    assert base.ledger["event_id"][0] == newer_pay.ledger["event_id"][0]
    assert (
        base.selection_evidence["candidate_id"][0]
        != newer_pay.selection_evidence["candidate_id"][0]
    )
    cash_changed = select_g1_corporate_actions(
        response=_make_verified(
            "dividend",
            _dividend_frame([_dividend_row(cash_div_tax=0.25)]),
        ),
        history=_history(),
    )
    assert base.ledger["event_id"][0] != cash_changed.ledger["event_id"][0]


def test_dividend_distinct_end_dates_same_ex_fields_pass_closure() -> None:
    """Two economic events that share ex/cash/stock/pay but differ in ann_date.

    Formal 600930.SH shape: different end_date alone is no longer enough to prove
    distinct events after cross-end exact fold; distinct ann_date must keep two
    event_ids and pass ledger↔evidence closure.
    """
    rows = [
        _dividend_row(end_date="20241231", ann_date="20260108"),
        _dividend_row(end_date="20251231", ann_date="20260124"),
    ]
    result = select_g1_corporate_actions(
        response=_make_verified("dividend", _dividend_frame(rows)), history=_history()
    )
    assert result.ledger.height == 2
    event_ids = result.ledger["event_id"].to_list()
    assert len(set(event_ids)) == 2
    selected = result.selection_evidence.filter(pl.col("selected"))
    assert selected.height == 2
    assert set(selected["end_date"].to_list()) == {
        dt.date(2024, 12, 31),
        dt.date(2025, 12, 31),
    }
    assert set(selected["ann_date"].to_list()) == {
        dt.date(2026, 1, 8),
        dt.date(2026, 1, 24),
    }
    verify_corporate_action_selection_result(result=result)


def test_dividend_cross_end_exact_fold_600733_shape() -> None:
    """Formal 600733.SH shape: only end_date differs → one event, max end_date."""
    rows = [
        _dividend_row(
            end_date="20180201",
            ann_date="20180201",
            imp_ann_date="20180913",
            stk_div=2.5,
            stk_bo_rate=None,
            stk_co_rate=2.5,
            cash_div=0.0,
            cash_div_tax=None,
            record_date="20180918",
            ex_date="20180919",
            pay_date=None,
            div_listdate="20180920",
            base_date="20180823",
            base_share=95867.1182,
        ),
        _dividend_row(
            end_date="20180823",
            ann_date="20180201",
            imp_ann_date="20180913",
            stk_div=2.5,
            stk_bo_rate=None,
            stk_co_rate=2.5,
            cash_div=0.0,
            cash_div_tax=None,
            record_date="20180918",
            ex_date="20180919",
            pay_date=None,
            div_listdate="20180920",
            base_date="20180823",
            base_share=95867.1182,
        ),
    ]
    history = HistoryWindow(dt.date(2018, 1, 1), dt.date(2018, 12, 31))
    result = select_g1_corporate_actions(
        response=_make_verified("dividend", _dividend_frame(rows)), history=history
    )
    assert result.ledger.height == 1
    assert result.ledger["stock_ratio"][0] == 2.5
    assert result.ledger["cash_per_share_gross"][0] == 0.0
    selected = result.selection_evidence.filter(pl.col("selected"))
    assert selected.height == 1
    assert selected["end_date"][0] == dt.date(2018, 8, 23)
    assert selected["raw_row_count"][0] == 2
    verify_corporate_action_selection_result(result=result)


def test_dividend_cross_end_exact_fold_three_ends_order_independent() -> None:
    """Three exact cross-end duplicates fold identically under reversed/shuffled input."""
    base = dict(
        ann_date="20260102",
        imp_ann_date="20260103",
        cash_div_tax=0.1,
        stk_div=0.0,
        record_date="20260106",
        ex_date="20260107",
        pay_date="20260108",
        div_listdate=None,
        base_date="20251231",
        base_share=100.0,
    )
    ends = ["20231231", "20241231", "20251231"]
    forward = [_dividend_row(end_date=end, **base) for end in ends]
    reversed_rows = list(reversed(forward))
    shuffled = [
        _dividend_row(end_date=ends[1], **base),
        _dividend_row(end_date=ends[2], **base),
        _dividend_row(end_date=ends[0], **base),
    ]
    digests: list[tuple[str, str]] = []
    for rows in (forward, reversed_rows, shuffled):
        result = select_g1_corporate_actions(
            response=_make_verified("dividend", _dividend_frame(rows)),
            history=_history(),
        )
        assert result.ledger.height == 1
        selected = result.selection_evidence.filter(pl.col("selected"))
        assert selected.height == 1
        assert selected["end_date"][0] == dt.date(2025, 12, 31)
        assert selected["raw_row_count"][0] == 3
        verify_corporate_action_selection_result(result=result)
        digests.append((result.ledger_sha256, result.selection_evidence_sha256))
    assert digests[0] == digests[1] == digests[2]


def test_dividend_cross_end_exact_fold_with_same_end_duplicates_counts_all() -> None:
    """Exact same-end duplicates plus cross-end duplicates sum into raw_row_count."""
    rows = [
        _dividend_row(end_date="20241231"),
        _dividend_row(end_date="20241231"),
        _dividend_row(end_date="20251231"),
        _dividend_row(end_date="20251231"),
        _dividend_row(end_date="20231231"),
    ]
    result = select_g1_corporate_actions(
        response=_make_verified("dividend", _dividend_frame(rows)), history=_history()
    )
    assert result.ledger.height == 1
    selected = result.selection_evidence.filter(pl.col("selected"))
    assert selected.height == 1
    assert selected["end_date"][0] == dt.date(2025, 12, 31)
    assert selected["raw_row_count"][0] == 5
    verify_corporate_action_selection_result(result=result)


def test_dividend_cross_end_exact_fold_blocked_by_provenance_fields() -> None:
    """Any non-end_date formal-field difference blocks cross-end exact fold."""
    cases: list[tuple[dict[str, Any], dict[str, Any]]] = [
        (
            {"end_date": "20241231"},
            {"end_date": "20251231", "imp_ann_date": "20260104"},
        ),
        (
            {"end_date": "20241231"},
            {"end_date": "20251231", "ann_date": "20260101"},
        ),
        (
            {"end_date": "20241231"},
            {"end_date": "20251231", "cash_div_tax": 0.11},
        ),
        (
            {"end_date": "20241231"},
            {"end_date": "20251231", "pay_date": "20260109"},
        ),
        (
            {
                "end_date": "20241231",
                "cash_div_tax": None,
                "stk_div": 0.05,
                "pay_date": None,
                "div_listdate": "20260107",
            },
            {
                "end_date": "20251231",
                "cash_div_tax": None,
                "stk_div": 0.06,
                "pay_date": None,
                "div_listdate": "20260107",
            },
        ),
        (
            {
                "end_date": "20241231",
                "cash_div_tax": None,
                "stk_div": 0.05,
                "pay_date": None,
                "div_listdate": "20260107",
            },
            {
                "end_date": "20251231",
                "cash_div_tax": None,
                "stk_div": 0.05,
                "pay_date": None,
                "div_listdate": "20260108",
            },
        ),
        (
            {"end_date": "20241231"},
            {"end_date": "20251231", "base_date": "20251130"},
        ),
        (
            {"end_date": "20241231"},
            {"end_date": "20251231", "base_share": 101.0},
        ),
        (
            {"end_date": "20241231"},
            {"end_date": "20251231", "stk_bo_rate": 0.1},
        ),
        (
            {"end_date": "20241231"},
            {"end_date": "20251231", "stk_co_rate": 0.1},
        ),
        (
            {"end_date": "20241231"},
            {"end_date": "20251231", "cash_div": 0.08},
        ),
        (
            {
                "end_date": "20241231",
                "cash_div_tax": None,
                "stk_div": 0.05,
                "pay_date": None,
                "div_listdate": "20260107",
            },
            {
                "end_date": "20251231",
                "cash_div_tax": 0.0,
                "stk_div": 0.05,
                "pay_date": None,
                "div_listdate": "20260107",
            },
        ),
    ]
    for left, right in cases:
        rows = [_dividend_row(**left), _dividend_row(**right)]
        result = select_g1_corporate_actions(
            response=_make_verified("dividend", _dividend_frame(rows)),
            history=_history(),
        )
        assert result.ledger.height == 2, (left, right)
        assert len(set(result.ledger["event_id"].to_list())) == 2, (left, right)
        verify_corporate_action_selection_result(result=result)


def test_dividend_post_canonical_provenance_collision_fail_closed() -> None:
    """A1+A2 exact fold to max end_date must not silently merge with B (base_share)."""
    a1 = _dividend_row(end_date="20241231", base_share=100.0)
    a2 = _dividend_row(end_date="20251231", base_share=100.0)
    b = _dividend_row(end_date="20251231", base_share=101.0)
    with pytest.raises(M3G1ExecutionFactError) as caught:
        select_g1_corporate_actions(
            response=_make_verified("dividend", _dividend_frame([a1, a2, b])),
            history=_history(),
        )
    _assert_code(caught, "G1_CORPORATE_ACTION_VERSION_CONFLICT")


def test_dividend_cross_end_exact_fold_a1_a2_only_still_folds() -> None:
    """Only A1+A2 (exact except end_date) still folds to one event with max end."""
    rows = [
        _dividend_row(end_date="20241231", base_share=100.0),
        _dividend_row(end_date="20251231", base_share=100.0),
    ]
    result = select_g1_corporate_actions(
        response=_make_verified("dividend", _dividend_frame(rows)), history=_history()
    )
    assert result.ledger.height == 1
    selected = result.selection_evidence.filter(pl.col("selected"))
    assert selected.height == 1
    assert selected["end_date"][0] == dt.date(2025, 12, 31)
    assert selected["raw_row_count"][0] == 2
    verify_corporate_action_selection_result(result=result)


def test_dividend_same_end_provenance_collision_fail_closed() -> None:
    """Same end_date, same rank/decision, different base_share → VERSION_CONFLICT."""
    rows = [
        _dividend_row(end_date="20251231", base_share=100.0),
        _dividend_row(end_date="20251231", base_share=101.0),
    ]
    with pytest.raises(M3G1ExecutionFactError) as caught:
        select_g1_corporate_actions(
            response=_make_verified("dividend", _dividend_frame(rows)),
            history=_history(),
        )
    _assert_code(caught, "G1_CORPORATE_ACTION_VERSION_CONFLICT")


def test_dividend_same_end_exact_duplicates_still_accumulate() -> None:
    """Fully exact same-end duplicates still accumulate raw_row_count."""
    rows = [
        _dividend_row(end_date="20251231", base_share=100.0),
        _dividend_row(end_date="20251231", base_share=100.0),
    ]
    result = select_g1_corporate_actions(
        response=_make_verified("dividend", _dividend_frame(rows)), history=_history()
    )
    assert result.ledger.height == 1
    selected = result.selection_evidence.filter(pl.col("selected"))
    assert selected.height == 1
    assert selected["raw_row_count"][0] == 2
    verify_corporate_action_selection_result(result=result)


def test_dividend_post_canonical_provenance_collision_order_independent() -> None:
    """Input order must not change the post-canonical provenance conflict code."""
    a1 = _dividend_row(end_date="20241231", base_share=100.0)
    a2 = _dividend_row(end_date="20251231", base_share=100.0)
    b = _dividend_row(end_date="20251231", base_share=101.0)
    for rows in ([a1, a2, b], [b, a2, a1], [a2, b, a1]):
        with pytest.raises(M3G1ExecutionFactError) as caught:
            select_g1_corporate_actions(
                response=_make_verified("dividend", _dividend_frame(rows)),
                history=_history(),
            )
        _assert_code(caught, "G1_CORPORATE_ACTION_VERSION_CONFLICT")


def test_dividend_cross_end_exact_fold_reconcile_stock_once() -> None:
    """600733-shaped dual end_date stock rows reconcile as one declared stock event."""
    stock = 2.5
    prev_close = 10.0
    declared = prev_close * (1.0 + stock) / prev_close
    assert declared == 3.5
    rows = [
        _dividend_row(
            end_date="20241231",
            cash_div_tax=None,
            stk_div=stock,
            pay_date=None,
            div_listdate="20260107",
        ),
        _dividend_row(
            end_date="20251231",
            cash_div_tax=None,
            stk_div=stock,
            pay_date=None,
            div_listdate="20260107",
        ),
    ]
    actions = select_g1_corporate_actions(
        response=_make_verified("dividend", _dividend_frame(rows)),
        history=_history(),
    ).ledger
    assert actions.height == 1
    assert actions["stock_ratio"][0] == stock

    closes: dict[dt.date, tuple[float, float]] = {
        _D0: (prev_close, prev_close),
        _D1: (prev_close, prev_close),
        _D2: (prev_close / declared, prev_close / declared),
    }
    bars_rows = []
    factor_rows = []
    for day, (close, _) in sorted(closes.items()):
        adj = 1.0 if day < _D2 else declared
        bars_rows.append(
            {
                "symbol": _SYMBOL,
                "trade_date": day,
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "volume": 1.0,
                "amount": 1.0,
                "adj_factor": adj,
                "source": "tushare",
            }
        )
    for day in (_D0, _D1, _D2):
        factor_rows.append(
            {
                "symbol": _SYMBOL,
                "effective_date": day,
                "adj_factor": 1.0 if day < _D2 else declared,
                "source": "tushare",
            }
        )
    bars = pl.DataFrame(bars_rows)
    factors = pl.DataFrame(factor_rows)
    daily = _make_verified(
        "daily",
        _daily_frame(closes),
        parameters={
            "ts_code": _SYMBOL,
            "start_date": _START,
            "end_date": _END,
        },
    )
    result = reconcile_g1_corporate_actions(
        corporate_actions=actions,
        bars=bars,
        adjustment_factors=factors,
        daily_responses=[daily],
        suspensions=_suspension(),
        calendars=_default_calendar(),
        history=_history(),
        factor_ratio_rtol=0.001,
    )
    event_row = result.evidence.filter(pl.col("event_count") > 0)
    assert event_row.height == 1
    assert event_row["stock_ratio"][0] == stock
    assert event_row["event_count"][0] == 1
    assert event_row["status"][0] == "MATCHED_EVENT_DECLARED_FORMULA"
    verify_corporate_action_reconciliation_result(result=result)


def test_ledger_evidence_closure_rejects_tampered_event_id_or_fields() -> None:
    result = select_g1_corporate_actions(
        response=_make_verified("dividend", _dividend_frame()), history=_history()
    )

    poisoned_ledger = result.ledger.with_columns(pl.lit("0" * 64).alias("event_id"))
    poisoned_ledger_sha = clean_table_content_sha256(
        table_name="corporate_action_ledger", frame=poisoned_ledger
    )
    with pytest.raises(M3G1ExecutionFactError) as caught:
        CorporateActionSelectionResult(
            ledger=poisoned_ledger,
            selection_evidence=result.selection_evidence,
            ledger_sha256=poisoned_ledger_sha,
            selection_evidence_sha256=result.selection_evidence_sha256,
        )
    _assert_code(caught, "G1_CORPORATE_ACTION_RESULT_INVALID")

    # pay_date is outside event_id hash; field-consistency path must still reject.
    poisoned_evidence = result.selection_evidence.with_columns(
        pl.when(pl.col("selected"))
        .then(pl.lit(dt.date(2026, 1, 9)))
        .otherwise(pl.col("pay_date"))
        .alias("pay_date")
    )
    poisoned_evidence_sha = clean_table_content_sha256(
        table_name="corporate_action_selection_evidence", frame=poisoned_evidence
    )
    with pytest.raises(M3G1ExecutionFactError) as caught2:
        CorporateActionSelectionResult(
            ledger=result.ledger,
            selection_evidence=poisoned_evidence,
            ledger_sha256=result.ledger_sha256,
            selection_evidence_sha256=poisoned_evidence_sha,
        )
    _assert_code(caught2, "G1_CORPORATE_ACTION_RESULT_INVALID")


def test_selection_result_frame_hash_drift() -> None:
    result = select_g1_corporate_actions(
        response=_make_verified("dividend", _dividend_frame()), history=_history()
    )
    with pytest.raises(M3G1ExecutionFactError) as caught:
        CorporateActionSelectionResult(
            ledger=result.ledger,
            selection_evidence=result.selection_evidence,
            ledger_sha256="0" * 64,
            selection_evidence_sha256=result.selection_evidence_sha256,
        )
    _assert_code(caught, "G1_CORPORATE_ACTION_RESULT_INVALID")


def _bars_and_factors_for_cash(
    *,
    prev_close: float = 10.0,
    cash: float = 0.1,
    factor_prev: float = 1.0,
    factor_eff: float | None = None,
    include_ex_daily: bool = True,
    ex_pre_close: float | None = None,
) -> tuple[pl.DataFrame, pl.DataFrame, VerifiedRawResponse, pl.DataFrame]:
    declared = prev_close * 1.0 / (prev_close - cash)
    actual_factor = factor_eff if factor_eff is not None else factor_prev * declared
    market_pre = ex_pre_close if ex_pre_close is not None else (prev_close - cash)
    closes: dict[dt.date, tuple[float, float]] = {
        _D0: (prev_close, prev_close),
        _D1: (prev_close, prev_close),
    }
    if include_ex_daily:
        closes[_D2] = (prev_close - cash, market_pre)
    bars_rows = []
    factor_rows = []
    for day, (close, _) in sorted(closes.items()):
        adj = factor_prev if day < _D2 else actual_factor
        bars_rows.append(
            {
                "symbol": _SYMBOL,
                "trade_date": day,
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "volume": 1.0,
                "amount": 1.0,
                "adj_factor": adj,
                "source": "tushare",
            }
        )
    # factors must include D0,D1,D2 even if bar missing on D2
    factor_dates = [_D0, _D1, _D2]
    for day in factor_dates:
        factor_rows.append(
            {
                "symbol": _SYMBOL,
                "effective_date": day,
                "adj_factor": factor_prev if day < _D2 else actual_factor,
                "source": "tushare",
            }
        )
    bars = pl.DataFrame(bars_rows)
    factors = pl.DataFrame(factor_rows)
    daily = _make_verified(
        "daily",
        _daily_frame(closes),
        parameters={
            "ts_code": _SYMBOL,
            "start_date": _START,
            "end_date": _END,
        },
    )
    actions = select_g1_corporate_actions(
        response=_make_verified(
            "dividend",
            _dividend_frame([_dividend_row(cash_div_tax=cash)]),
        ),
        history=_history(),
    ).ledger
    return bars, factors, daily, actions


def test_reconcile_declared_market_and_no_event() -> None:
    bars, factors, daily, actions = _bars_and_factors_for_cash()
    # Add stable no-event transition D0->D1 by ensuring factor constant before event
    result = reconcile_g1_corporate_actions(
        corporate_actions=actions,
        bars=bars,
        adjustment_factors=factors,
        daily_responses=[daily],
        suspensions=_suspension(),
        calendars=_default_calendar(),
        history=_history(),
        factor_ratio_rtol=0.001,
    )
    assert result.evidence.height == 2
    statuses = result.evidence.sort("effective_date")["status"].to_list()
    assert statuses == ["NO_EVENT_STABLE_FACTOR", "MATCHED_EVENT_DECLARED_FORMULA"]
    verify_corporate_action_reconciliation_result(result=result)

    # Market reference path: declared diverges, raw pre_close matches actual.
    prev_close = 10.0
    cash = 0.1
    actual_ratio = 1.05  # not equal declared ~1.0101
    market_pre = prev_close / actual_ratio
    bars2, factors2, daily2, actions2 = _bars_and_factors_for_cash(
        prev_close=prev_close,
        cash=cash,
        factor_eff=actual_ratio,
        ex_pre_close=market_pre,
    )
    result2 = reconcile_g1_corporate_actions(
        corporate_actions=actions2,
        bars=bars2,
        adjustment_factors=factors2,
        daily_responses=[daily2],
        suspensions=_suspension(),
        calendars=_default_calendar(),
        history=_history(),
        factor_ratio_rtol=0.001,
    )
    event_row = result2.evidence.filter(pl.col("event_count") > 0)
    assert event_row["status"][0] == "MATCHED_EVENT_MARKET_REFERENCE"


def test_reconcile_no_market_reference_full_day() -> None:
    bars, factors, daily, actions = _bars_and_factors_for_cash(include_ex_daily=False)
    suspensions = _suspension(
        [
            {
                "symbol": _SYMBOL,
                "trade_date": _D2,
                "suspension_scope": "FULL_DAY",
                "suspension_detail": None,
                "source": "tushare",
                "source_snapshot_id": _HEX,
            }
        ]
    )
    result = reconcile_g1_corporate_actions(
        corporate_actions=actions,
        bars=bars,
        adjustment_factors=factors,
        daily_responses=[daily],
        suspensions=suspensions,
        calendars=_default_calendar(),
        history=_history(),
        factor_ratio_rtol=0.001,
    )
    event_row = result.evidence.filter(pl.col("event_count") > 0)
    assert event_row["status"][0] == (
        "MATCHED_EVENT_DECLARED_FORMULA_NO_MARKET_REFERENCE"
    )
    assert event_row["ex_reference_price"][0] is None

    # PARTIAL with missing daily: fail-closed (must not fall back to no-event).
    partial = _suspension(
        [
            {
                "symbol": _SYMBOL,
                "trade_date": _D2,
                "suspension_scope": "PARTIAL",
                "suspension_detail": "am",
                "source": "tushare",
                "source_snapshot_id": _HEX,
            }
        ]
    )
    with pytest.raises(M3G1ExecutionFactError) as caught_partial:
        reconcile_g1_corporate_actions(
            corporate_actions=actions,
            bars=bars,
            adjustment_factors=factors,
            daily_responses=[daily],
            suspensions=partial,
            calendars=_default_calendar(),
            history=_history(),
            factor_ratio_rtol=0.001,
        )
    _assert_code(caught_partial, "G1_CORPORATE_ACTION_FACTOR_UNEXPLAINED")


def test_reconcile_unexplained_jump_and_rtol_bounds() -> None:
    bars, factors, daily, actions = _bars_and_factors_for_cash()
    bad_factors = factors.with_columns(
        pl.when(pl.col("effective_date") == _D1)
        .then(pl.lit(1.5))
        .otherwise(pl.col("adj_factor"))
        .alias("adj_factor")
    )
    # also sync bar factor on D1
    bad_bars = bars.with_columns(
        pl.when(pl.col("trade_date") == _D1)
        .then(pl.lit(1.5))
        .otherwise(pl.col("adj_factor"))
        .alias("adj_factor")
    )
    # B2C §9.2: no-event factor jump must raise FACTOR_UNEXPLAINED.
    with pytest.raises(M3G1ExecutionFactError) as caught_jump:
        reconcile_g1_corporate_actions(
            corporate_actions=actions.clear(),
            bars=bad_bars,
            adjustment_factors=bad_factors,
            daily_responses=[daily],
            suspensions=_suspension(),
            calendars=_default_calendar(),
            history=_history(),
            factor_ratio_rtol=0.001,
        )
    _assert_code(caught_jump, "G1_CORPORATE_ACTION_FACTOR_UNEXPLAINED")

    # Event path with market/declared both exceeding rtol must also raise
    # (must not fall back to NO_EVENT_STABLE_FACTOR).
    prev_close = 10.0
    cash = 0.1
    bad_actual = 1.5
    bars_e, factors_e, daily_e, actions_e = _bars_and_factors_for_cash(
        prev_close=prev_close,
        cash=cash,
        factor_eff=bad_actual,
        ex_pre_close=prev_close - cash,  # market ≈ declared ≈ 1.0101
    )
    with pytest.raises(M3G1ExecutionFactError) as caught_event:
        reconcile_g1_corporate_actions(
            corporate_actions=actions_e,
            bars=bars_e,
            adjustment_factors=factors_e,
            daily_responses=[daily_e],
            suspensions=_suspension(),
            calendars=_default_calendar(),
            history=_history(),
            factor_ratio_rtol=0.001,
        )
    _assert_code(caught_event, "G1_CORPORATE_ACTION_FACTOR_UNEXPLAINED")

    for bad in (True, -0.1, 0.02, float("nan")):
        with pytest.raises(M3G1ExecutionFactError) as caught:
            reconcile_g1_corporate_actions(
                corporate_actions=actions,
                bars=bars,
                adjustment_factors=factors,
                daily_responses=[daily],
                suspensions=_suspension(),
                calendars=_default_calendar(),
                history=_history(),
                factor_ratio_rtol=bad,  # type: ignore[arg-type]
            )
        _assert_code(caught, "G1_CORPORATE_ACTION_FACTOR_INVALID")


def test_reconcile_event_in_factor_gap_fails() -> None:
    # factors only on D0 and D2; event on D1 should fail (no factor row on ex_date)
    bars, factors, daily, actions = _bars_and_factors_for_cash()
    gap_factors = factors.filter(pl.col("effective_date") != _D1)
    gap_bars = bars.filter(pl.col("trade_date") != _D1)
    # rebuild daily without D1
    closes = {
        _D0: (10.0, 10.0),
        _D2: (9.9, 9.9),
    }
    daily2 = _make_verified(
        "daily",
        _daily_frame(closes),
        parameters={"ts_code": _SYMBOL, "start_date": _START, "end_date": _END},
    )
    # Move event to D1 while factors jump D0->D2
    actions_d1 = actions.with_columns(pl.lit(_D1).alias("ex_date"))
    with pytest.raises(M3G1ExecutionFactError) as caught:
        reconcile_g1_corporate_actions(
            corporate_actions=actions_d1,
            bars=gap_bars,
            adjustment_factors=gap_factors,
            daily_responses=[daily2],
            suspensions=_suspension(),
            calendars=_default_calendar(),
            history=_history(),
            factor_ratio_rtol=0.001,
        )
    _assert_code(caught, "G1_CORPORATE_ACTION_FACTOR_INVALID")
    _ = daily


def test_reconcile_event_on_first_factor_day_omitted() -> None:
    """ex_date == first factor day cannot form prior ratio; omit from matching."""
    bars, factors, daily, actions = _bars_and_factors_for_cash()
    flat_factors = factors.with_columns(pl.lit(1.0).alias("adj_factor"))
    flat_bars = bars.with_columns(pl.lit(1.0).alias("adj_factor"))
    edge_actions = actions.with_columns(
        pl.lit(_D0).alias("ex_date"),
        pl.lit(_D0).alias("record_date"),
        pl.when(pl.col("pay_date").is_not_null())
        .then(pl.lit(_D0))
        .otherwise(pl.col("pay_date"))
        .alias("pay_date"),
        pl.when(pl.col("stock_list_date").is_not_null())
        .then(pl.lit(_D0))
        .otherwise(pl.col("stock_list_date"))
        .alias("stock_list_date"),
    )
    result = reconcile_g1_corporate_actions(
        corporate_actions=edge_actions,
        bars=flat_bars,
        adjustment_factors=flat_factors,
        daily_responses=[daily],
        suspensions=_suspension(),
        calendars=_default_calendar(),
        history=_history(),
        factor_ratio_rtol=0.001,
    )
    assert result.evidence.height == 2
    assert result.evidence.filter(pl.col("event_count") > 0).height == 0
    assert set(result.evidence["status"].to_list()) == {"NO_EVENT_STABLE_FACTOR"}
    verify_corporate_action_reconciliation_result(result=result)


def test_reconcile_stable_factor_with_events_fails() -> None:
    """Events on a no-jump factor pair cannot fall back to NO_EVENT_STABLE."""
    bars, factors, daily, actions = _bars_and_factors_for_cash()
    flat_factors = factors.with_columns(pl.lit(1.0).alias("adj_factor"))
    flat_bars = bars.with_columns(pl.lit(1.0).alias("adj_factor"))
    with pytest.raises(M3G1ExecutionFactError) as caught:
        reconcile_g1_corporate_actions(
            corporate_actions=actions,
            bars=flat_bars,
            adjustment_factors=flat_factors,
            daily_responses=[daily],
            suspensions=_suspension(),
            calendars=_default_calendar(),
            history=_history(),
            factor_ratio_rtol=0.001,
        )
    _assert_code(caught, "G1_CORPORATE_ACTION_FACTOR_UNEXPLAINED")


def test_reconcile_full_day_factor_jump_before_first_bar_fails() -> None:
    """Omitted event + unexplained factor jump must fail closed."""
    bars, factors, daily, actions = _bars_and_factors_for_cash()
    # Keep only D2+ bars so D0->D1 has no prior close; mark D1 FULL_DAY.
    # Unstable D0->D1 factors with events omitted must raise.
    edge_factors = factors.with_columns(
        pl.when(pl.col("effective_date") >= _D1)
        .then(pl.lit(1.2))
        .otherwise(pl.col("adj_factor"))
        .alias("adj_factor")
    )
    late_bars = bars.filter(pl.col("trade_date") >= _D2).with_columns(
        pl.lit(1.2).alias("adj_factor")
    )
    late_daily = _make_verified(
        "daily",
        _daily_frame({_D2: (9.9, 9.9)}),
        parameters={"ts_code": _SYMBOL, "start_date": _START, "end_date": _END},
    )
    edge_actions = actions.with_columns(
        pl.lit(_D1).alias("ex_date"),
        pl.lit(_D0).alias("record_date"),
        pl.when(pl.col("pay_date").is_not_null())
        .then(pl.lit(_D1))
        .otherwise(pl.col("pay_date"))
        .alias("pay_date"),
        pl.when(pl.col("stock_list_date").is_not_null())
        .then(pl.lit(_D1))
        .otherwise(pl.col("stock_list_date"))
        .alias("stock_list_date"),
    )
    suspensions = _suspension(
        [
            {
                "symbol": _SYMBOL,
                "trade_date": _D1,
                "suspension_scope": "FULL_DAY",
                "suspension_detail": None,
                "source": "tushare",
                "source_snapshot_id": _HEX,
            }
        ]
    )
    with pytest.raises(M3G1ExecutionFactError) as caught:
        reconcile_g1_corporate_actions(
            corporate_actions=edge_actions,
            bars=late_bars,
            adjustment_factors=edge_factors,
            daily_responses=[late_daily],
            suspensions=suspensions,
            calendars=_default_calendar(),
            history=_history(),
            factor_ratio_rtol=0.001,
        )
    _assert_code(caught, "G1_CORPORATE_ACTION_FACTOR_UNEXPLAINED")
    _ = daily
    _ = bars
    _ = factors
    _ = actions


def test_reconcile_daily_identity_and_digest_stability() -> None:
    bars, factors, daily, actions = _bars_and_factors_for_cash()
    result = reconcile_g1_corporate_actions(
        corporate_actions=actions,
        bars=bars,
        adjustment_factors=factors,
        daily_responses=[daily],
        suspensions=_suspension(),
        calendars=_default_calendar(),
        history=_history(),
        factor_ratio_rtol=0.001,
    )
    # reorder factors input
    result2 = reconcile_g1_corporate_actions(
        corporate_actions=actions.reverse(),
        bars=bars.reverse(),
        adjustment_factors=factors.reverse(),
        daily_responses=[daily],
        suspensions=_suspension(),
        calendars=_default_calendar(),
        history=_history(),
        factor_ratio_rtol=0.001,
    )
    assert result.evidence_sha256 == result2.evidence_sha256
    assert result.evidence_sha256 == clean_table_content_sha256(
        table_name="corporate_action_reconciliation", frame=result.evidence
    )

    bad_daily = VerifiedRawResponse.__new__(VerifiedRawResponse)
    object.__setattr__(bad_daily, "spec", daily.spec)
    object.__setattr__(bad_daily, "receipt", daily.receipt)
    object.__setattr__(bad_daily, "receipt_sha256", "0" * 64)
    object.__setattr__(bad_daily, "frame", daily.frame)
    with pytest.raises(M3G1ExecutionFactError) as caught:
        reconcile_g1_corporate_actions(
            corporate_actions=actions,
            bars=bars,
            adjustment_factors=factors,
            daily_responses=[bad_daily],
            suspensions=_suspension(),
            calendars=_default_calendar(),
            history=_history(),
            factor_ratio_rtol=0.001,
        )
    _assert_code(caught, "G1_EXECUTION_FACT_RESPONSE_INVALID")


def test_sanitize_credential_markers() -> None:
    rows = _limit_frame().to_dicts()
    rows[0]["pre_close"] = "/home/secret/token=abc"
    with pytest.raises(M3G1ExecutionFactError) as caught:
        map_g1_price_limit_response(response=_make_verified("stk_limit", _limit_frame(rows)))
    _assert_code(caught, "G1_EXECUTION_FACT_VALUE_INVALID")
    assert "token=abc" not in repr(caught.value)
    assert "/home/secret" not in repr(caught.value)


def _matched_result() -> CorporateActionReconciliationResult:
    bars, factors, daily, actions = _bars_and_factors_for_cash()
    return reconcile_g1_corporate_actions(
        corporate_actions=actions,
        bars=bars,
        adjustment_factors=factors,
        daily_responses=[daily],
        suspensions=_suspension(),
        calendars=_default_calendar(),
        history=_history(),
        factor_ratio_rtol=0.001,
    )


def _rebuild_recon(
    evidence: pl.DataFrame,
) -> None:
    digest = clean_table_content_sha256(
        table_name="corporate_action_reconciliation", frame=evidence
    )
    CorporateActionReconciliationResult(evidence=evidence, evidence_sha256=digest)


def test_p1_1_matched_event_ids_sha256_drift_rejected() -> None:
    result = _matched_result()
    assert result.evidence.filter(pl.col("event_count") > 0).height == 1
    poisoned = result.evidence.with_columns(
        pl.when(pl.col("event_count") > 0)
        .then(pl.lit("c" * 64))
        .otherwise(pl.col("event_ids_sha256"))
        .alias("event_ids_sha256")
    )
    with pytest.raises(M3G1ExecutionFactError) as caught:
        _rebuild_recon(poisoned)
    _assert_code(caught, "G1_CORPORATE_ACTION_RECONCILIATION_INVALID")

    digest = clean_table_content_sha256(
        table_name="corporate_action_reconciliation", frame=poisoned
    )
    fake = CorporateActionReconciliationResult.__new__(
        CorporateActionReconciliationResult
    )
    object.__setattr__(fake, "evidence", poisoned)
    object.__setattr__(fake, "evidence_sha256", digest)
    with pytest.raises(M3G1ExecutionFactError) as caught:
        verify_corporate_action_reconciliation_result(result=fake)
    _assert_code(caught, "G1_CORPORATE_ACTION_RECONCILIATION_INVALID")


def test_p1_1_matched_event_ids_json_or_count_drift_rejected() -> None:
    result = _matched_result()
    empty_json = result.evidence.with_columns(
        pl.when(pl.col("event_count") > 0)
        .then(pl.lit("[]"))
        .otherwise(pl.col("event_ids_json"))
        .alias("event_ids_json")
    )
    with pytest.raises(M3G1ExecutionFactError) as caught:
        _rebuild_recon(empty_json)
    _assert_code(caught, "G1_CORPORATE_ACTION_RECONCILIATION_INVALID")

    count_drift = result.evidence.with_columns(
        pl.when(pl.col("event_count") > 0)
        .then(pl.lit(2))
        .otherwise(pl.col("event_count"))
        .alias("event_count")
    )
    with pytest.raises(M3G1ExecutionFactError) as caught:
        _rebuild_recon(count_drift)
    _assert_code(caught, "G1_CORPORATE_ACTION_RECONCILIATION_INVALID")


def test_p1_1_no_event_empty_json_and_drift() -> None:
    result = _matched_result()
    no_event = result.evidence.filter(pl.col("status") == "NO_EVENT_STABLE_FACTOR")
    assert no_event.height == 1
    assert no_event["event_ids_json"][0] == "[]"
    assert no_event["event_count"][0] == 0
    from quant.data import m3_execution_facts as facts

    assert no_event["event_ids_sha256"][0] == facts._event_set_sha256([])

    poisoned = result.evidence.with_columns(
        pl.when(pl.col("status") == "NO_EVENT_STABLE_FACTOR")
        .then(pl.lit("c" * 64))
        .otherwise(pl.col("event_ids_sha256"))
        .alias("event_ids_sha256")
    )
    with pytest.raises(M3G1ExecutionFactError) as caught:
        _rebuild_recon(poisoned)
    _assert_code(caught, "G1_CORPORATE_ACTION_RECONCILIATION_INVALID")


def test_p1_1_dual_event_json_sorted_stable() -> None:
    bars, factors, daily, base_actions = _bars_and_factors_for_cash()
    first_id = base_actions["event_id"][0]
    second_id = "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
    if first_id > second_id:
        second_id = "0000000000000000000000000000000000000000000000000000000000000001"
    second = base_actions.with_columns(
        pl.lit(second_id).alias("event_id"),
        pl.lit(0.05).alias("cash_per_share_gross"),
    )
    actions = pl.concat([base_actions, second])
    prev_close = 10.0
    total_cash = 0.1 + 0.05
    declared = prev_close / (prev_close - total_cash)
    factors = factors.with_columns(
        pl.when(pl.col("effective_date") == _D2)
        .then(pl.lit(declared))
        .otherwise(pl.col("adj_factor"))
        .alias("adj_factor")
    )
    bars = bars.with_columns(
        pl.when(pl.col("trade_date") == _D2)
        .then(pl.lit(declared))
        .otherwise(pl.col("adj_factor"))
        .alias("adj_factor")
    )
    closes = {
        _D0: (prev_close, prev_close),
        _D1: (prev_close, prev_close),
        _D2: (prev_close - total_cash, prev_close - total_cash),
    }
    bars = bars.with_columns(
        pl.when(pl.col("trade_date") == _D2)
        .then(pl.lit(prev_close - total_cash))
        .otherwise(pl.col("close"))
        .alias("close"),
        pl.when(pl.col("trade_date") == _D2)
        .then(pl.lit(declared))
        .otherwise(pl.col("adj_factor"))
        .alias("adj_factor"),
    )
    # keep OHLC consistent on ex-date
    bars = bars.with_columns(
        pl.when(pl.col("trade_date") == _D2)
        .then(pl.col("close"))
        .otherwise(pl.col("open"))
        .alias("open"),
        pl.when(pl.col("trade_date") == _D2)
        .then(pl.col("close"))
        .otherwise(pl.col("high"))
        .alias("high"),
        pl.when(pl.col("trade_date") == _D2)
        .then(pl.col("close"))
        .otherwise(pl.col("low"))
        .alias("low"),
    )
    daily = _make_verified(
        "daily",
        _daily_frame(closes),
        parameters={"ts_code": _SYMBOL, "start_date": _START, "end_date": _END},
    )
    result = reconcile_g1_corporate_actions(
        corporate_actions=actions,
        bars=bars,
        adjustment_factors=factors,
        daily_responses=[daily],
        suspensions=_suspension(),
        calendars=_default_calendar(),
        history=_history(),
        factor_ratio_rtol=0.001,
    )
    matched = result.evidence.filter(pl.col("event_count") > 0)
    assert matched["event_count"][0] == 2
    import json

    ids = json.loads(matched["event_ids_json"][0])
    assert ids == sorted(ids)
    assert len(ids) == 2
    from quant.data import m3_execution_facts as facts

    assert matched["event_ids_json"][0] == facts._event_ids_json(ids)
    assert matched["event_ids_sha256"][0] == facts._event_set_sha256(ids)

    reversed_actions = pl.concat([second, base_actions])
    result2 = reconcile_g1_corporate_actions(
        corporate_actions=reversed_actions,
        bars=bars,
        adjustment_factors=factors,
        daily_responses=[daily],
        suspensions=_suspension(),
        calendars=_default_calendar(),
        history=_history(),
        factor_ratio_rtol=0.001,
    )
    matched2 = result2.evidence.filter(pl.col("event_count") > 0)
    assert matched2["event_ids_json"][0] == matched["event_ids_json"][0]
    assert result2.evidence_sha256 == result.evidence_sha256


@pytest.mark.parametrize(
    "bad_json",
    [
        ' ["aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"]',
        '["aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"] ',
        '["AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"]',
        (
            '["bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",'
            '"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"]'
        ),
        (
            '["aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",'
            '"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"]'
        ),
        "{}",
        "null",
        "[1]",
        "[[]]",
    ],
)
def test_p1_1_rejects_noncanonical_event_ids_json(bad_json: str) -> None:
    result = _matched_result()
    poisoned = result.evidence.with_columns(
        pl.when(pl.col("event_count") > 0)
        .then(pl.lit(bad_json))
        .otherwise(pl.col("event_ids_json"))
        .alias("event_ids_json")
    )
    with pytest.raises(M3G1ExecutionFactError) as caught:
        _rebuild_recon(poisoned)
    _assert_code(caught, "G1_CORPORATE_ACTION_RECONCILIATION_INVALID")


def test_p1_1_dtype_coercion_writeback() -> None:
    from quant.domain import CorporateActionReconciliationSchema

    result = _matched_result()
    frame = result.evidence.with_columns(pl.col("event_count").cast(pl.Int32))
    validated = CorporateActionReconciliationSchema.validate(frame)
    digest = clean_table_content_sha256(
        table_name="corporate_action_reconciliation", frame=validated
    )
    rebuilt = CorporateActionReconciliationResult(
        evidence=frame, evidence_sha256=digest
    )
    assert rebuilt.evidence_sha256 == clean_table_content_sha256(
        table_name="corporate_action_reconciliation", frame=rebuilt.evidence
    )
    verify_corporate_action_reconciliation_result(result=rebuilt)


def test_p0d_scoped_factors_exclude_pre_first_bar_jump() -> None:
    """000553 structure: pre-first-bar jump + ledger event omitted after scope."""
    bars, factors, daily, actions = _bars_and_factors_for_cash()
    edge_actions = actions.with_columns(
        pl.lit(_D1).alias("ex_date"),
        pl.lit(_D0).alias("record_date"),
    )
    # Unscoped: D0->D1 unexplained jump with bars only from D2.
    unscoped = factors.with_columns(
        pl.when(pl.col("effective_date") >= _D1)
        .then(pl.lit(1.2))
        .otherwise(pl.col("adj_factor"))
        .alias("adj_factor")
    )
    late_bars = bars.filter(pl.col("trade_date") >= _D2).with_columns(
        pl.lit(1.2).alias("adj_factor")
    )
    late_daily = _make_verified(
        "daily",
        _daily_frame({_D2: (9.9, 9.9)}),
        parameters={"ts_code": _SYMBOL, "start_date": _START, "end_date": _END},
    )
    with pytest.raises(M3G1ExecutionFactError) as caught:
        reconcile_g1_corporate_actions(
            corporate_actions=edge_actions,
            bars=late_bars,
            adjustment_factors=unscoped,
            daily_responses=[late_daily],
            suspensions=_suspension(),
            calendars=_default_calendar(),
            history=_history(),
            factor_ratio_rtol=0.001,
        )
    _assert_code(caught, "G1_CORPORATE_ACTION_FACTOR_UNEXPLAINED")

    scoped_factors = unscoped.filter(pl.col("effective_date") >= _D2)
    result = reconcile_g1_corporate_actions(
        corporate_actions=edge_actions,
        bars=late_bars,
        adjustment_factors=scoped_factors,
        daily_responses=[late_daily],
        suspensions=_suspension(),
        calendars=_default_calendar(),
        history=_history(),
        factor_ratio_rtol=0.001,
    )
    # Single scoped factor -> zero transitions; pre-bar event omitted.
    assert result.evidence.height == 0
    assert edge_actions.height == 1
    verify_corporate_action_reconciliation_result(result=result)
    _ = daily
    _ = bars


def test_p0d_post_first_bar_no_event_jump_still_unexplained() -> None:
    bars, factors, daily, actions = _bars_and_factors_for_cash()
    bad_factors = factors.with_columns(
        pl.when(pl.col("effective_date") == _D1)
        .then(pl.lit(1.5))
        .otherwise(pl.col("adj_factor"))
        .alias("adj_factor")
    )
    bad_bars = bars.with_columns(
        pl.when(pl.col("trade_date") == _D1)
        .then(pl.lit(1.5))
        .otherwise(pl.col("adj_factor"))
        .alias("adj_factor")
    )
    with pytest.raises(M3G1ExecutionFactError) as caught:
        reconcile_g1_corporate_actions(
            corporate_actions=actions.clear(),
            bars=bad_bars,
            adjustment_factors=bad_factors,
            daily_responses=[daily],
            suspensions=_suspension(),
            calendars=_default_calendar(),
            history=_history(),
            factor_ratio_rtol=0.001,
        )
    _assert_code(caught, "G1_CORPORATE_ACTION_FACTOR_UNEXPLAINED")


def test_p0d_ledger_outside_scope_omitted_inside_strict() -> None:
    bars, factors, daily, actions = _bars_and_factors_for_cash()
    flat_factors = factors.with_columns(pl.lit(1.0).alias("adj_factor"))
    flat_bars = bars.with_columns(pl.lit(1.0).alias("adj_factor"))
    # Move the real selected ledger event before scoped first factor day.
    outside = actions.with_columns(
        pl.lit(_D0).alias("ex_date"),
        pl.lit(_D0).alias("record_date"),
        pl.when(pl.col("pay_date").is_not_null())
        .then(pl.lit(_D0))
        .otherwise(pl.col("pay_date"))
        .alias("pay_date"),
    )
    # Scope factors to D1..D2 so D0 is outside.
    scoped = flat_factors.filter(pl.col("effective_date") >= _D1)
    scoped_bars = flat_bars.filter(pl.col("trade_date") >= _D1)
    scoped_daily = _make_verified(
        "daily",
        _daily_frame({_D1: (10.0, 10.0), _D2: (9.9, 9.9)}),
        parameters={"ts_code": _SYMBOL, "start_date": _START, "end_date": _END},
    )
    ok = reconcile_g1_corporate_actions(
        corporate_actions=outside,
        bars=scoped_bars,
        adjustment_factors=scoped,
        daily_responses=[scoped_daily],
        suspensions=_suspension(),
        calendars=_default_calendar(),
        history=_history(),
        factor_ratio_rtol=0.001,
    )
    assert ok.evidence.height == 1
    assert ok.evidence["status"].to_list() == ["NO_EVENT_STABLE_FACTOR"]
    assert ok.evidence.filter(pl.col("event_count") > 0).height == 0

    # Tamper: keep a scoped-range event but pair it with an unexplained jump.
    jumped = scoped.with_columns(
        pl.when(pl.col("effective_date") == _D2)
        .then(pl.lit(1.5))
        .otherwise(pl.col("adj_factor"))
        .alias("adj_factor")
    )
    jumped_bars = scoped_bars.with_columns(
        pl.when(pl.col("trade_date") == _D2)
        .then(pl.lit(1.5))
        .otherwise(pl.col("adj_factor"))
        .alias("adj_factor")
    )
    with pytest.raises(M3G1ExecutionFactError) as caught:
        reconcile_g1_corporate_actions(
            corporate_actions=actions,
            bars=jumped_bars,
            adjustment_factors=jumped,
            daily_responses=[scoped_daily],
            suspensions=_suspension(),
            calendars=_default_calendar(),
            history=_history(),
            factor_ratio_rtol=0.001,
        )
    _assert_code(caught, "G1_CORPORATE_ACTION_FACTOR_UNEXPLAINED")
    _ = daily
    _ = bars
    _ = factors

def test_p0d_scoped_row_count_formula_and_digest_stable_under_shuffle() -> None:
    bars, factors, daily, actions = _bars_and_factors_for_cash()
    result = reconcile_g1_corporate_actions(
        corporate_actions=actions,
        bars=bars,
        adjustment_factors=factors,
        daily_responses=[daily],
        suspensions=_suspension(),
        calendars=_default_calendar(),
        history=_history(),
        factor_ratio_rtol=0.001,
    )
    per_symbol = factors.group_by("symbol").len().to_dicts()
    expected = sum(max(int(row["len"]) - 1, 0) for row in per_symbol)
    assert result.evidence.height == expected
    shuffled = reconcile_g1_corporate_actions(
        corporate_actions=actions.reverse(),
        bars=bars.reverse(),
        adjustment_factors=factors.reverse(),
        daily_responses=[daily],
        suspensions=_suspension(),
        calendars=_default_calendar(),
        history=_history(),
        factor_ratio_rtol=0.001,
    )
    assert shuffled.evidence_sha256 == result.evidence_sha256
    assert shuffled.evidence.sort(
        ["symbol", "previous_factor_date", "effective_date"]
    ).equals(
        result.evidence.sort(["symbol", "previous_factor_date", "effective_date"])
    )


def _p0e_small_dividend_fixture(
    *,
    prev_close: float = 2.91,
    cash: float = 0.005,
    factor_eff: float = 1.0,
    ex_pre_close: float | None = None,
    include_ex_daily: bool = True,
) -> tuple[pl.DataFrame, pl.DataFrame, VerifiedRawResponse, pl.DataFrame]:
    """Shape matching the formal small-dividend precision failure (no hardcodes in prod)."""
    return _bars_and_factors_for_cash(
        prev_close=prev_close,
        cash=cash,
        factor_eff=factor_eff,
        ex_pre_close=prev_close if ex_pre_close is None else ex_pre_close,
        include_ex_daily=include_ex_daily,
    )


def test_p0e_small_dividend_market_reference_happy_path() -> None:
    """Matrix 1: cash precision keeps actual=market=1.0 → MATCHED_EVENT_MARKET_REFERENCE."""
    rtol = 0.001
    bars, factors, daily, actions = _p0e_small_dividend_fixture()
    result = reconcile_g1_corporate_actions(
        corporate_actions=actions,
        bars=bars,
        adjustment_factors=factors,
        daily_responses=[daily],
        suspensions=_suspension(),
        calendars=_default_calendar(),
        history=_history(),
        factor_ratio_rtol=rtol,
    )
    event = result.evidence.filter(pl.col("event_count") > 0)
    assert event.height == 1
    assert event["status"][0] == "MATCHED_EVENT_MARKET_REFERENCE"
    assert event["actual_factor_ratio"][0] == 1.0
    assert event["market_reference_factor_ratio"][0] == 1.0
    assert float(event["declared_dividend_relative_error"][0]) > rtol
    assert float(event["cash_per_share_gross"][0]) == 0.005
    assert event["event_count"][0] == 1
    assert event["event_ids_json"][0] != "[]"
    assert len(event["event_ids_sha256"][0]) == 64
    verify_corporate_action_reconciliation_result(result=result)


def test_p0e_symmetric_rtol_allows_actual_below_one() -> None:
    """Matrix 2: actual=0.9995 within 1±rtol is allowed when market matches."""
    rtol = 0.001
    bars, factors, daily, actions = _p0e_small_dividend_fixture(factor_eff=0.9995)
    result = reconcile_g1_corporate_actions(
        corporate_actions=actions,
        bars=bars,
        adjustment_factors=factors,
        daily_responses=[daily],
        suspensions=_suspension(),
        calendars=_default_calendar(),
        history=_history(),
        factor_ratio_rtol=rtol,
    )
    event = result.evidence.filter(pl.col("event_count") > 0)
    assert event.height == 1
    assert event["actual_factor_ratio"][0] == 0.9995
    assert event["market_reference_factor_ratio"][0] == 1.0
    assert event["status"][0] == "MATCHED_EVENT_MARKET_REFERENCE"
    verify_corporate_action_reconciliation_result(result=result)


def test_p0e_rejects_matched_reverse_ratio_far_from_one() -> None:
    """Matrix 3: actual=market=0.998 still fails — support domain is about 1, not mutual match."""
    bars, factors, daily, actions = _p0e_small_dividend_fixture(
        factor_eff=0.998,
        ex_pre_close=2.91 / 0.998,
    )
    with pytest.raises(M3G1ExecutionFactError) as caught:
        reconcile_g1_corporate_actions(
            corporate_actions=actions,
            bars=bars,
            adjustment_factors=factors,
            daily_responses=[daily],
            suspensions=_suspension(),
            calendars=_default_calendar(),
            history=_history(),
            factor_ratio_rtol=0.001,
        )
    _assert_code(caught, "G1_CORPORATE_ACTION_FACTOR_UNEXPLAINED")


def test_p0e_rejects_actual_one_market_mismatch() -> None:
    """Matrix 4: actual=1.0 but market clearly >1 and mutually out of rtol."""
    bars, factors, daily, actions = _p0e_small_dividend_fixture(
        factor_eff=1.0,
        ex_pre_close=2.91 - 0.005,  # market ≈ declared > 1
    )
    with pytest.raises(M3G1ExecutionFactError) as caught:
        reconcile_g1_corporate_actions(
            corporate_actions=actions,
            bars=bars,
            adjustment_factors=factors,
            daily_responses=[daily],
            suspensions=_suspension(),
            calendars=_default_calendar(),
            history=_history(),
            factor_ratio_rtol=0.001,
        )
    _assert_code(caught, "G1_CORPORATE_ACTION_FACTOR_UNEXPLAINED")


def test_p0e_rejects_actual_one_missing_daily_without_full_day() -> None:
    """Matrix 5: actual=1.0, no ex-date daily, not FULL_DAY → fail closed."""
    bars, factors, daily, actions = _p0e_small_dividend_fixture(
        include_ex_daily=False
    )
    with pytest.raises(M3G1ExecutionFactError) as caught:
        reconcile_g1_corporate_actions(
            corporate_actions=actions,
            bars=bars,
            adjustment_factors=factors,
            daily_responses=[daily],
            suspensions=_suspension(),
            calendars=_default_calendar(),
            history=_history(),
            factor_ratio_rtol=0.001,
        )
    _assert_code(caught, "G1_CORPORATE_ACTION_FACTOR_UNEXPLAINED")


def test_p0e_rejects_full_day_declared_error_exceeds_rtol() -> None:
    """Matrix 6: FULL_DAY + no daily + actual=1.0 but declared error > rtol."""
    bars, factors, daily, actions = _p0e_small_dividend_fixture(
        include_ex_daily=False
    )
    suspensions = _suspension(
        [
            {
                "symbol": _SYMBOL,
                "trade_date": _D2,
                "suspension_scope": "FULL_DAY",
                "suspension_detail": None,
                "source": "tushare",
                "source_snapshot_id": _HEX,
            }
        ]
    )
    with pytest.raises(M3G1ExecutionFactError) as caught:
        reconcile_g1_corporate_actions(
            corporate_actions=actions,
            bars=bars,
            adjustment_factors=factors,
            daily_responses=[daily],
            suspensions=suspensions,
            calendars=_default_calendar(),
            history=_history(),
            factor_ratio_rtol=0.001,
        )
    _assert_code(caught, "G1_CORPORATE_ACTION_FACTOR_UNEXPLAINED")


def test_p0e_no_event_stable_and_jump_still_fail_closed() -> None:
    """Matrix 7: no-event actual=1.0 accepted; no-event large jump rejected."""
    bars, factors, daily, actions = _p0e_small_dividend_fixture()
    flat = factors.with_columns(pl.lit(1.0).alias("adj_factor"))
    flat_bars = bars.with_columns(pl.lit(1.0).alias("adj_factor"))
    stable = reconcile_g1_corporate_actions(
        corporate_actions=actions.clear(),
        bars=flat_bars,
        adjustment_factors=flat,
        daily_responses=[daily],
        suspensions=_suspension(),
        calendars=_default_calendar(),
        history=_history(),
        factor_ratio_rtol=0.001,
    )
    assert set(stable.evidence["status"].to_list()) == {"NO_EVENT_STABLE_FACTOR"}
    verify_corporate_action_reconciliation_result(result=stable)

    jumped = flat.with_columns(
        pl.when(pl.col("effective_date") == _D2)
        .then(pl.lit(1.5))
        .otherwise(pl.col("adj_factor"))
        .alias("adj_factor")
    )
    jumped_bars = flat_bars.with_columns(
        pl.when(pl.col("trade_date") == _D2)
        .then(pl.lit(1.5))
        .otherwise(pl.col("adj_factor"))
        .alias("adj_factor")
    )
    with pytest.raises(M3G1ExecutionFactError) as caught:
        reconcile_g1_corporate_actions(
            corporate_actions=actions.clear(),
            bars=jumped_bars,
            adjustment_factors=jumped,
            daily_responses=[daily],
            suspensions=_suspension(),
            calendars=_default_calendar(),
            history=_history(),
            factor_ratio_rtol=0.001,
        )
    _assert_code(caught, "G1_CORPORATE_ACTION_FACTOR_UNEXPLAINED")


def test_p0e_rejects_disguised_no_event_cleared_ids_or_cash() -> None:
    """Matrix 8: tampering matched evidence into NO_EVENT / cleared ids / cash fails."""
    from quant.domain import CorporateActionReconciliationSchema

    bars, factors, daily, actions = _p0e_small_dividend_fixture()
    result = reconcile_g1_corporate_actions(
        corporate_actions=actions,
        bars=bars,
        adjustment_factors=factors,
        daily_responses=[daily],
        suspensions=_suspension(),
        calendars=_default_calendar(),
        history=_history(),
        factor_ratio_rtol=0.001,
    )
    event_mask = pl.col("event_count") > 0

    disguised = result.evidence.with_columns(
        pl.when(event_mask)
        .then(pl.lit("NO_EVENT_STABLE_FACTOR"))
        .otherwise(pl.col("status"))
        .alias("status")
    )
    with pytest.raises(Exception):
        CorporateActionReconciliationSchema.validate(disguised)

    cleared_ids = result.evidence.with_columns(
        pl.when(event_mask)
        .then(pl.lit("[]"))
        .otherwise(pl.col("event_ids_json"))
        .alias("event_ids_json"),
        pl.when(event_mask)
        .then(pl.lit(0))
        .otherwise(pl.col("event_count"))
        .alias("event_count"),
    )
    with pytest.raises(M3G1ExecutionFactError) as caught_ids:
        _rebuild_recon(cleared_ids)
    _assert_code(caught_ids, "G1_CORPORATE_ACTION_RECONCILIATION_INVALID")

    cash_tamper = result.evidence.with_columns(
        pl.when(event_mask)
        .then(pl.lit(0.0))
        .otherwise(pl.col("cash_per_share_gross"))
        .alias("cash_per_share_gross")
    )
    rejected = False
    try:
        CorporateActionReconciliationSchema.validate(cash_tamper)
    except Exception:
        rejected = True
    if not rejected:
        with pytest.raises(M3G1ExecutionFactError) as caught_cash:
            _rebuild_recon(cash_tamper)
        _assert_code(caught_cash, "G1_CORPORATE_ACTION_RECONCILIATION_INVALID")
        rejected = True
    assert rejected is True


def test_p0e_extra_full_day_tiny_declared_within_rtol() -> None:
    """Extra boundary: FULL_DAY + actual=1.0 + declared within rtol → NO_MARKET_REFERENCE."""
    # cash small enough that abs(1/declared-1) <= 0.001 with prev_close=10.
    bars, factors, daily, actions = _bars_and_factors_for_cash(
        prev_close=10.0,
        cash=0.009,
        factor_eff=1.0,
        include_ex_daily=False,
    )
    suspensions = _suspension(
        [
            {
                "symbol": _SYMBOL,
                "trade_date": _D2,
                "suspension_scope": "FULL_DAY",
                "suspension_detail": None,
                "source": "tushare",
                "source_snapshot_id": _HEX,
            }
        ]
    )
    result = reconcile_g1_corporate_actions(
        corporate_actions=actions,
        bars=bars,
        adjustment_factors=factors,
        daily_responses=[daily],
        suspensions=suspensions,
        calendars=_default_calendar(),
        history=_history(),
        factor_ratio_rtol=0.001,
    )
    event = result.evidence.filter(pl.col("event_count") > 0)
    assert event.height == 1
    assert event["status"][0] == (
        "MATCHED_EVENT_DECLARED_FORMULA_NO_MARKET_REFERENCE"
    )
    assert event["actual_factor_ratio"][0] == 1.0
    assert float(event["declared_dividend_relative_error"][0]) <= 0.001
    verify_corporate_action_reconciliation_result(result=result)


def test_rights_selection_maps_f004n_and_populates_fields() -> None:
    response = _make_cninfo_verified(_cninfo_frame())
    result = select_g1_cninfo_rights_actions(
        response=response, history=_history(), symbols=[_SYMBOL]
    )
    assert result.ledger.height == 1
    row = result.ledger.row(0, named=True)
    assert row["action_type"] == "RIGHTS"
    assert row["symbol"] == _SYMBOL
    assert row["ex_date"] == _D2
    assert row["cash_per_share_gross"] == 0.0
    assert row["stock_ratio"] == 0.0
    assert row["rights_price"] == 45.68
    assert row["rights_ratio"] == pytest.approx(0.3)
    assert row["pay_date"] is None
    assert row["stock_list_date"] == _D4
    assert row["vendor_record_id"] == "1"
    assert row["source"] == "cninfo"
    assert result.selection_evidence.height == 1
    evidence_row = result.selection_evidence.row(0, named=True)
    assert evidence_row["selection_reason"] == "SELECTED_LATEST"
    assert evidence_row["selected"] is True
    verify_corporate_action_selection_result(result=result)


def _mixed_rights_share_change_response(
    **overrides: Any,
) -> backfill.VerifiedCninfoCorporateActionRawResponse:
    row = {name: None for name in CNINFO_STOCK_SHARE_CHANGE_FIELDS}
    row.update(
        {
            "DECLAREDATE": _D3.isoformat(),
            "VARYDATE": _D4.isoformat(),
            "F001V": "015012,015005",
            "F002V": "可转债转股,配股上市",
            "F003N": "647507.6893",
            "F021N": "594324.6574",
            "F022N": "594324.6574",
            "SECCODE": "600000",
        }
    )
    row.update(overrides)
    frame = pl.DataFrame(
        [row], schema={name: pl.Utf8 for name in CNINFO_STOCK_SHARE_CHANGE_FIELDS}
    )
    return _make_cninfo_ca_verified(
        endpoint=CNINFO_SHARE_CHANGE_ENDPOINT,
        parameters={
            "symbol": "600000",
            "start_date": _START,
            "end_date": _END,
        },
        frame=frame,
    )


def _mixed_rights_response(**overrides: Any) -> VerifiedCninfoRawResponse:
    row = {
        "F017N": "146252.3613",
        "F024N": "501254.9956",
        "F025N": "647507.6893",
        "F041N": "448071.9637",
        "F042N": "594324.6574",
    }
    row.update(overrides)
    return _make_cninfo_verified(
        _cninfo_frame([_rights_row(**row)])
    )


def test_p0kc_mixed_rights_requires_unique_listing_and_conversion_proof() -> None:
    share = _mixed_rights_share_change_response()
    result = select_g1_cninfo_rights_actions(
        response=_mixed_rights_response(),
        history=_history(),
        symbols=[_SYMBOL],
        share_change_responses_by_code={"600000": share},
    )
    assert result.ledger.height == 1
    ledger = result.ledger.row(0, named=True)
    evidence = result.selection_evidence.row(0, named=True)
    assert ledger["rights_pre_circulating_shares"] == pytest.approx(448071.9637)
    assert ledger["rights_post_circulating_shares"] == pytest.approx(594324.6574)
    assert ledger["rights_mixed_change_proof_sha256"] == evidence[
        "rights_mixed_change_proof_sha256"
    ]
    proof = json.loads(evidence["rights_mixed_change_proof_json"])
    assert proof["rights_non_rights_residual"] == "0.3324"
    assert proof["reason_pairs"] == [
        ["015005", "配股上市"],
        ["015012", "可转债转股"],
    ]
    verify_corporate_action_selection_result(result=result)


def test_p0kc_mixed_rights_without_share_proof_fails_closed() -> None:
    with pytest.raises(M3G1ExecutionFactError) as caught:
        select_g1_cninfo_rights_actions(
            response=_mixed_rights_response(),
            history=_history(),
            symbols=[_SYMBOL],
        )
    _assert_code(caught, "G1_CORPORATE_ACTION_RIGHTS_MIXED_CHANGE_UNPROVEN")


def test_p0kc_strict_rights_keeps_mixed_fields_null() -> None:
    result = select_g1_cninfo_rights_actions(
        response=_make_cninfo_verified(_cninfo_frame()),
        history=_history(),
        symbols=[_SYMBOL],
    )
    ledger = result.ledger.row(0, named=True)
    evidence = result.selection_evidence.row(0, named=True)
    for name in (
        "rights_pre_circulating_shares",
        "rights_post_circulating_shares",
        "rights_mixed_change_proof_sha256",
    ):
        assert ledger[name] is None
        assert evidence[name] is None
    assert evidence["rights_mixed_change_proof_json"] is None


def test_p0kc_small_real_positive_residual_requires_mixed_proof() -> None:
    rights = _mixed_rights_response(F017N="146252.6936")
    with pytest.raises(M3G1ExecutionFactError) as caught:
        select_g1_cninfo_rights_actions(
            response=rights,
            history=_history(),
            symbols=[_SYMBOL],
        )
    _assert_code(caught, "G1_CORPORATE_ACTION_RIGHTS_MIXED_CHANGE_UNPROVEN")

    result = select_g1_cninfo_rights_actions(
        response=rights,
        history=_history(),
        symbols=[_SYMBOL],
        share_change_responses_by_code={
            "600000": _mixed_rights_share_change_response()
        },
    )
    assert result.ledger["rights_mixed_change_proof_sha256"][0] is not None
    proof = json.loads(
        result.selection_evidence["rights_mixed_change_proof_json"][0]
    )
    assert proof["rights_non_rights_residual"] == "0.0001"


def test_p0kc_small_negative_residual_fails_even_with_mixed_proof() -> None:
    with pytest.raises(M3G1ExecutionFactError) as caught:
        select_g1_cninfo_rights_actions(
            response=_mixed_rights_response(F017N="146252.6938"),
            history=_history(),
            symbols=[_SYMBOL],
            share_change_responses_by_code={
                "600000": _mixed_rights_share_change_response()
            },
        )
    _assert_code(caught, "G1_CORPORATE_ACTION_RIGHTS_MIXED_CHANGE_UNPROVEN")


def test_p0kc_representation_only_residual_remains_strict() -> None:
    result = select_g1_cninfo_rights_actions(
        response=_mixed_rights_response(F017N="146252.69369999"),
        history=_history(),
        symbols=[_SYMBOL],
    )
    assert result.ledger["rights_mixed_change_proof_sha256"][0] is None
    assert result.selection_evidence["rights_mixed_change_proof_json"][0] is None


def test_p0kc_mixed_rights_proof_binds_formal_receipt_projection() -> None:
    official_share = _mixed_rights_share_change_response()
    forged_share = _mixed_rights_share_change_response(F004N="1")
    rights = _mixed_rights_response()
    official = select_g1_cninfo_rights_actions(
        response=rights,
        history=_history(),
        symbols=[_SYMBOL],
        share_change_responses_by_code={"600000": official_share},
    )
    forged = select_g1_cninfo_rights_actions(
        response=rights,
        history=_history(),
        symbols=[_SYMBOL],
        share_change_responses_by_code={"600000": forged_share},
    )
    verify_corporate_action_selection_result(result=forged)
    assert forged.ledger["event_id"][0] != official.ledger["event_id"][0]
    assert (
        forged.selection_evidence["candidate_id"][0]
        != official.selection_evidence["candidate_id"][0]
    )
    formal_receipts = (
        SimpleNamespace(
            source="cninfo",
            endpoint="stock_allotment",
            request_id=rights.receipt.request_id,
            stable_response_sha256=rights.receipt.stable_response_sha256,
        ),
        SimpleNamespace(
            source="cninfo",
            endpoint=CNINFO_SHARE_CHANGE_ENDPOINT,
            request_id=official_share.receipt.request_id,
            stable_response_sha256=official_share.receipt.stable_response_sha256,
        ),
    )
    with pytest.raises(M3G1ExecutionFactError) as caught:
        assert_corporate_action_selection_receipt_closure(
            selection_evidence=forged.selection_evidence,
            input_receipts=formal_receipts,
        )
    _assert_code(caught, "G1_CORPORATE_ACTION_RESULT_INVALID")


@pytest.mark.parametrize(
    "column", ["economic_event_key_sha256", "candidate_id"]
)
def test_p0kc_mixed_rights_verifier_recomputes_candidate_identity(
    column: str,
) -> None:
    result = select_g1_cninfo_rights_actions(
        response=_mixed_rights_response(),
        history=_history(),
        symbols=[_SYMBOL],
        share_change_responses_by_code={
            "600000": _mixed_rights_share_change_response()
        },
    )
    poisoned_evidence = result.selection_evidence.with_columns(
        pl.lit("0" * 64).alias(column)
    )
    poisoned_evidence_sha = clean_table_content_sha256(
        table_name="corporate_action_selection_evidence",
        frame=poisoned_evidence,
    )
    with pytest.raises(M3G1ExecutionFactError) as caught:
        CorporateActionSelectionResult(
            ledger=result.ledger,
            selection_evidence=poisoned_evidence,
            ledger_sha256=result.ledger_sha256,
            selection_evidence_sha256=poisoned_evidence_sha,
        )
    _assert_code(caught, "G1_CORPORATE_ACTION_RESULT_INVALID")


def test_p0kc_mixed_rights_rejects_two_equally_valid_share_rows() -> None:
    one = _mixed_rights_share_change_response()
    duplicate_frame = pl.concat([one.frame, one.frame])
    duplicate = _make_cninfo_ca_verified(
        endpoint=CNINFO_SHARE_CHANGE_ENDPOINT,
        parameters={
            "symbol": "600000",
            "start_date": _START,
            "end_date": _END,
        },
        frame=duplicate_frame,
    )
    with pytest.raises(M3G1ExecutionFactError) as caught:
        select_g1_cninfo_rights_actions(
            response=_mixed_rights_response(),
            history=_history(),
            symbols=[_SYMBOL],
            share_change_responses_by_code={"600000": duplicate},
        )
    _assert_code(caught, "G1_CORPORATE_ACTION_RIGHTS_MIXED_CHANGE_UNPROVEN")


@pytest.mark.parametrize(
    "overrides",
    [
        {"VARYDATE": _D3.isoformat()},
        {"F001V": "015005", "F002V": "配股上市"},
        {
            "F001V": "015005,015012",
            "F002V": "可转债转股,配股上市",
        },
        {
            "F001V": "015005,015012,015020",
            "F002V": "配股上市,可转债转股,股权分置",
        },
        {"F003N": "647508.0"},
        {"F021N": "594325.0"},
        {"F022N": "594325.0"},
    ],
)
def test_p0kc_mixed_rights_rejects_unproven_share_change(
    overrides: dict[str, Any],
) -> None:
    share = _mixed_rights_share_change_response(**overrides)
    with pytest.raises(M3G1ExecutionFactError) as caught:
        select_g1_cninfo_rights_actions(
            response=_mixed_rights_response(),
            history=_history(),
            symbols=[_SYMBOL],
            share_change_responses_by_code={"600000": share},
        )
    _assert_code(caught, "G1_CORPORATE_ACTION_RIGHTS_MIXED_CHANGE_UNPROVEN")


def test_rights_market_reference_happy_path() -> None:
    """000661-shaped fixture: declared diverges from actual, market matches."""
    prev_close = 103.20
    rights_price = 45.68
    rights_ratio = 0.3
    bars, factors, daily, actions = _bars_and_factors_for_rights(
        prev_close=prev_close,
        rights_price=rights_price,
        rights_ratio=rights_ratio,
        factor_prev=3.195,
        factor_eff=3.66,
        ex_pre_close=90.09,
    )
    assert actions.height == 1
    result = reconcile_g1_corporate_actions(
        corporate_actions=actions,
        bars=bars,
        adjustment_factors=factors,
        daily_responses=[daily],
        suspensions=_suspension(),
        calendars=_default_calendar(),
        history=_history(),
        factor_ratio_rtol=0.001,
    )
    event = result.evidence.filter(pl.col("event_count") > 0)
    assert event.height == 1
    assert event["status"][0] == "MATCHED_EVENT_MARKET_REFERENCE"
    assert event["rights_ratio"][0] == pytest.approx(0.3)
    assert float(event["rights_subscription_cash_per_share"][0]) == pytest.approx(
        rights_price * rights_ratio
    )
    verify_corporate_action_reconciliation_result(result=result)


def test_rights_declared_formula_match() -> None:
    bars, factors, daily, actions = _bars_and_factors_for_rights()
    result = reconcile_g1_corporate_actions(
        corporate_actions=actions,
        bars=bars,
        adjustment_factors=factors,
        daily_responses=[daily],
        suspensions=_suspension(),
        calendars=_default_calendar(),
        history=_history(),
        factor_ratio_rtol=0.001,
    )
    event = result.evidence.filter(pl.col("event_count") > 0)
    assert event.height == 1
    assert event["status"][0] == "MATCHED_EVENT_DECLARED_FORMULA"
    verify_corporate_action_reconciliation_result(result=result)


def test_rights_missing_daily_requires_full_day_and_rtol() -> None:
    bars, factors, daily, actions = _bars_and_factors_for_rights(include_ex_daily=False)
    # Missing daily without FULL_DAY suspension must fail closed.
    with pytest.raises(M3G1ExecutionFactError) as caught:
        reconcile_g1_corporate_actions(
            corporate_actions=actions,
            bars=bars,
            adjustment_factors=factors,
            daily_responses=[daily],
            suspensions=_suspension(),
            calendars=_default_calendar(),
            history=_history(),
            factor_ratio_rtol=0.001,
        )
    _assert_code(caught, "G1_CORPORATE_ACTION_FACTOR_UNEXPLAINED")

    # FULL_DAY but declared error exceeds rtol must also fail closed.
    bars_bad, factors_bad, daily_bad, actions_bad = _bars_and_factors_for_rights(
        include_ex_daily=False, factor_eff=5.0
    )
    suspensions = _suspension(
        [
            {
                "symbol": _SYMBOL,
                "trade_date": _D2,
                "suspension_scope": "FULL_DAY",
                "suspension_detail": None,
                "source": "tushare",
                "source_snapshot_id": _HEX,
            }
        ]
    )
    with pytest.raises(M3G1ExecutionFactError) as caught_bad:
        reconcile_g1_corporate_actions(
            corporate_actions=actions_bad,
            bars=bars_bad,
            adjustment_factors=factors_bad,
            daily_responses=[daily_bad],
            suspensions=suspensions,
            calendars=_default_calendar(),
            history=_history(),
            factor_ratio_rtol=0.001,
        )
    _assert_code(caught_bad, "G1_CORPORATE_ACTION_FACTOR_UNEXPLAINED")


def test_rights_unsupported_ratio_far_below_one_rejected() -> None:
    prev_close = 10.0
    rights_price = 5.0
    rights_ratio = 0.3
    # Force both actual and market far below 1 despite otherwise matching.
    bars, factors, daily, actions = _bars_and_factors_for_rights(
        prev_close=prev_close,
        rights_price=rights_price,
        rights_ratio=rights_ratio,
        factor_eff=0.5,
        ex_pre_close=prev_close / 0.5,
    )
    with pytest.raises(M3G1ExecutionFactError) as caught:
        reconcile_g1_corporate_actions(
            corporate_actions=actions,
            bars=bars,
            adjustment_factors=factors,
            daily_responses=[daily],
            suspensions=_suspension(),
            calendars=_default_calendar(),
            history=_history(),
            factor_ratio_rtol=0.001,
        )
    _assert_code(caught, "G1_CORPORATE_ACTION_FACTOR_UNEXPLAINED")


def test_rights_same_shape_without_event_fails_closed() -> None:
    """Same bar/factor jump shape, but with actions cleared: no-event fail-closed."""
    bars, factors, daily, actions = _bars_and_factors_for_rights()
    with pytest.raises(M3G1ExecutionFactError) as caught:
        reconcile_g1_corporate_actions(
            corporate_actions=actions.clear(),
            bars=bars,
            adjustment_factors=factors,
            daily_responses=[daily],
            suspensions=_suspension(),
            calendars=_default_calendar(),
            history=_history(),
            factor_ratio_rtol=0.001,
        )
    _assert_code(caught, "G1_CORPORATE_ACTION_FACTOR_UNEXPLAINED")


def test_rights_f004n_non_positive_rejected() -> None:
    for bad_f004n in ("0", "-1"):
        response = _make_cninfo_verified(
            _cninfo_frame([_rights_row(F004N=bad_f004n)])
        )
        with pytest.raises(M3G1ExecutionFactError) as caught:
            select_g1_cninfo_rights_actions(
                response=response, history=_history(), symbols=[_SYMBOL]
            )
        _assert_code(caught, "G1_CORPORATE_ACTION_EVENT_INVALID")


def test_rights_price_non_positive_rejected() -> None:
    response = _make_cninfo_verified(_cninfo_frame([_rights_row(F005N="0")]))
    with pytest.raises(M3G1ExecutionFactError) as caught:
        select_g1_cninfo_rights_actions(
            response=response, history=_history(), symbols=[_SYMBOL]
        )
    _assert_code(caught, "G1_CORPORATE_ACTION_EVENT_INVALID")


def test_rights_failed_issuance_omitted() -> None:
    # post_shares <= pre_shares: failed issuance must be omitted, not rejected.
    response = _make_cninfo_verified(
        _cninfo_frame([_rights_row(F024N="1000.0", F025N="900.0")])
    )
    result = select_g1_cninfo_rights_actions(
        response=response, history=_history(), symbols=[_SYMBOL]
    )
    assert result.ledger.height == 0
    assert result.selection_evidence.height == 0


def test_rights_duplicate_subid_rejected() -> None:
    rows = [_rights_row(SUBID="1"), _rights_row(SUBID="1", SECCODE="600000")]
    response = _make_cninfo_verified(_cninfo_frame(rows))
    with pytest.raises(M3G1ExecutionFactError) as caught:
        select_g1_cninfo_rights_actions(
            response=response, history=_history(), symbols=[_SYMBOL]
        )
    _assert_code(caught, "G1_CORPORATE_ACTION_EVENT_INVALID")


def test_rights_conflicting_same_symbol_ex_date_rejected() -> None:
    rows = [
        _rights_row(SUBID="1", F005N="45.68"),
        _rights_row(SUBID="2", F005N="50.0"),
    ]
    response = _make_cninfo_verified(_cninfo_frame(rows))
    with pytest.raises(M3G1ExecutionFactError) as caught:
        select_g1_cninfo_rights_actions(
            response=response, history=_history(), symbols=[_SYMBOL]
        )
    _assert_code(caught, "G1_CORPORATE_ACTION_EVENT_INVALID")


def test_dividend_and_rights_same_day_formula_and_order_invariant_digest() -> None:
    prev_close = 10.0
    cash = 0.1
    rights_price = 5.0
    rights_ratio = 0.3
    declared = (
        prev_close
        * (1.0 + rights_ratio)
        / (prev_close - cash + rights_price * rights_ratio)
    )
    closes: dict[dt.date, tuple[float, float]] = {
        _D0: (prev_close, prev_close),
        _D1: (prev_close, prev_close),
        _D2: (prev_close - cash, prev_close / declared),
    }
    bars_rows = []
    factor_rows = []
    for day in (_D0, _D1, _D2):
        close, _ = closes[day]
        adj = 1.0 if day < _D2 else declared
        bars_rows.append(
            {
                "symbol": _SYMBOL,
                "trade_date": day,
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "volume": 1.0,
                "amount": 1.0,
                "adj_factor": adj,
                "source": "tushare",
            }
        )
        factor_rows.append(
            {
                "symbol": _SYMBOL,
                "effective_date": day,
                "adj_factor": adj,
                "source": "tushare",
            }
        )
    bars = pl.DataFrame(bars_rows)
    factors = pl.DataFrame(factor_rows)
    daily = _make_verified(
        "daily",
        _daily_frame(closes),
        parameters={"ts_code": _SYMBOL, "start_date": _START, "end_date": _END},
    )
    dividend_actions = select_g1_corporate_actions(
        response=_make_verified(
            "dividend", _dividend_frame([_dividend_row(cash_div_tax=cash)])
        ),
        history=_history(),
    ).ledger
    rights_actions = select_g1_cninfo_rights_actions(
        response=_make_cninfo_verified(
            _cninfo_frame(
                [_rights_row(F005N=str(rights_price), F004N=str(rights_ratio * 10.0))]
            )
        ),
        history=_history(),
        symbols=[_SYMBOL],
    ).ledger

    combined_forward = pl.concat([dividend_actions, rights_actions])
    combined_reversed = pl.concat([rights_actions, dividend_actions])

    result_forward = reconcile_g1_corporate_actions(
        corporate_actions=combined_forward,
        bars=bars,
        adjustment_factors=factors,
        daily_responses=[daily],
        suspensions=_suspension(),
        calendars=_default_calendar(),
        history=_history(),
        factor_ratio_rtol=0.001,
    )
    result_reversed = reconcile_g1_corporate_actions(
        corporate_actions=combined_reversed,
        bars=bars,
        adjustment_factors=factors,
        daily_responses=[daily],
        suspensions=_suspension(),
        calendars=_default_calendar(),
        history=_history(),
        factor_ratio_rtol=0.001,
    )
    event = result_forward.evidence.filter(pl.col("event_count") > 0)
    assert event.height == 1
    assert event["event_count"][0] == 2
    assert event["status"][0] == "MATCHED_EVENT_DECLARED_FORMULA"
    assert float(event["cash_per_share_gross"][0]) == pytest.approx(cash)
    assert float(event["rights_ratio"][0]) == pytest.approx(rights_ratio)
    assert float(event["rights_subscription_cash_per_share"][0]) == pytest.approx(
        rights_price * rights_ratio
    )
    assert (
        result_forward.evidence_sha256 == result_reversed.evidence_sha256
    )
    verify_corporate_action_reconciliation_result(result=result_forward)
    verify_corporate_action_reconciliation_result(result=result_reversed)


def test_p0f_r1_rights_capital_identity_collision_and_tamper() -> None:
    """Different legal capital triples must not collide; tamper fail-closed."""
    base = {
        "SUBID": "42",
        "F005N": "45.68",
        "F004N": "3.0",
        "F011D": "2026-01-06",
        "F012D": "2026-01-07",
    }
    left = select_g1_cninfo_rights_actions(
        response=_make_cninfo_verified(
            _cninfo_frame(
                [_rights_row(**base, F017N="100.0", F024N="1000.0", F025N="1100.0")]
            )
        ),
        history=_history(),
        symbols=[_SYMBOL],
    )
    right = select_g1_cninfo_rights_actions(
        response=_make_cninfo_verified(
            _cninfo_frame(
                [_rights_row(**base, F017N="200.0", F024N="1000.0", F025N="1200.0")]
            )
        ),
        history=_history(),
        symbols=[_SYMBOL],
    )
    assert left.ledger.height == 1 and right.ledger.height == 1
    assert left.ledger["event_id"][0] != right.ledger["event_id"][0]
    assert (
        left.selection_evidence["candidate_id"][0]
        != right.selection_evidence["candidate_id"][0]
    )
    assert left.ledger["rights_actual_shares"][0] == 100.0
    assert left.ledger["rights_pre_shares"][0] == 1000.0
    assert left.ledger["rights_post_shares"][0] == 1100.0
    verify_corporate_action_selection_result(result=left)
    verify_corporate_action_selection_result(result=right)

    # Tamper capital and recompute digests: selection verify must reject.
    poisoned = left.ledger.with_columns(pl.lit(999.0).alias("rights_actual_shares"))
    poisoned_sha = clean_table_content_sha256(
        table_name="corporate_action_ledger", frame=poisoned
    )
    with pytest.raises(M3G1ExecutionFactError):
        verify_corporate_action_selection_result(
            result=CorporateActionSelectionResult(
                ledger=poisoned,
                selection_evidence=left.selection_evidence,
                ledger_sha256=poisoned_sha,
                selection_evidence_sha256=left.selection_evidence_sha256,
            )
        )


def test_p0f_r1_dividend_capital_fields_null() -> None:
    result = select_g1_corporate_actions(
        response=_make_verified("dividend", _dividend_frame()),
        history=_history(),
    )
    assert result.ledger.height == 1
    row = result.ledger.row(0, named=True)
    assert row["rights_actual_shares"] is None
    assert row["rights_pre_shares"] is None
    assert row["rights_post_shares"] is None
    evidence = result.selection_evidence.row(0, named=True)
    assert evidence["rights_actual_shares"] is None
    assert evidence["rights_pre_shares"] is None
    assert evidence["rights_post_shares"] is None
    verify_corporate_action_selection_result(result=result)


_CNINFO_REQUIRED_DATE_FIELDS = (
    "DECLAREDATE",
    "F011D",
    "F012D",
    "F013D",
    "F014D",
    "F052D",
    "F038D",
)


@pytest.mark.parametrize("field", _CNINFO_REQUIRED_DATE_FIELDS)
def test_p0h_cninfo_required_iso_date_fields_accepted(field: str) -> None:
    """Each required CNINFO date field accepts a legal exact YYYY-MM-DD value."""
    # Keep calendar order invariants while swapping one field to an alternate
    # but still-valid ISO date within the same day for most fields.
    legal_overrides = {
        "DECLAREDATE": "2026-01-05",
        "F011D": "2026-01-06",
        "F012D": "2026-01-07",
        "F013D": "2026-01-05",
        "F014D": "2026-01-06",
        "F052D": "2026-01-07",
        "F038D": "2026-01-09",
    }
    response = _make_cninfo_verified(
        _cninfo_frame([_rights_row(**{field: legal_overrides[field]})])
    )
    result = select_g1_cninfo_rights_actions(
        response=response, history=_history(), symbols=[_SYMBOL]
    )
    assert result.ledger.height == 1
    verify_corporate_action_selection_result(result=result)


@pytest.mark.parametrize(
    "bad_value",
    [
        "20160427",
        "2016/04/27",
        "2016-04-27T00:00:00",
        " 2016-04-27",
        "2016-04-27 ",
        "2016-02-30",
        "",
        None,
    ],
)
def test_p0h_cninfo_iso_date_rejects_non_exact_iso(bad_value: object) -> None:
    """Illegal CNINFO date formats fail closed (F012D sample field)."""
    response = _make_cninfo_verified(_cninfo_frame([_rights_row(F012D=bad_value)]))
    with pytest.raises(M3G1ExecutionFactError) as caught:
        select_g1_cninfo_rights_actions(
            response=response, history=_history(), symbols=[_SYMBOL]
        )
    _assert_code(caught, "G1_CORPORATE_ACTION_EVENT_INVALID")


@pytest.mark.parametrize("bad_value", [True, False, 20160427, 2016.0427, b"2016-04-27"])
def test_p0h_cninfo_iso_parser_rejects_non_string(bad_value: object) -> None:
    with pytest.raises(M3G1ExecutionFactError) as caught:
        _parse_cninfo_iso_date(bad_value)
    _assert_code(caught, "G1_CORPORATE_ACTION_EVENT_INVALID")


def test_p0h_cninfo_iso_fixture_selection_verify_and_identity() -> None:
    """Real connector-shaped ISO dates pass selection, verify, and identity."""
    response = _make_cninfo_verified(
        _cninfo_frame(
            [
                _rights_row(
                    SECCODE="000661",
                    SUBID="cninfo-000661-1",
                    DECLAREDATE="2026-01-05",
                    F011D="2026-01-06",
                    F012D="2026-01-07",
                    F013D="2026-01-05",
                    F014D="2026-01-06",
                    F052D="2026-01-07",
                    F038D="2026-01-09",
                )
            ]
        ),
        symbols_param="000661",
    )
    result = select_g1_cninfo_rights_actions(
        response=response, history=_history(), symbols=["000661.SZ"]
    )
    assert result.ledger.height == 1
    assert result.ledger["symbol"][0] == "000661.SZ"
    assert result.ledger["ex_date"][0] == _D2
    assert result.ledger["stock_list_date"][0] == _D4
    verify_corporate_action_selection_result(result=result)
    # Identity self-check: recomputed digests match stored hashes.
    assert result.ledger_sha256 == clean_table_content_sha256(
        table_name="corporate_action_ledger", frame=result.ledger
    )
    assert result.selection_evidence_sha256 == clean_table_content_sha256(
        table_name="corporate_action_selection_evidence",
        frame=result.selection_evidence,
    )


def test_p0h_tushare_date8_unchanged_rejects_iso() -> None:
    """Tushare dividend keeps YYYYMMDD; ISO dates are not silently accepted."""
    happy = select_g1_corporate_actions(
        response=_make_verified("dividend", _dividend_frame()),
        history=_history(),
    )
    assert happy.ledger.height == 1
    assert happy.ledger["ex_date"][0] == _D2
    verify_corporate_action_selection_result(result=happy)

    iso_frame = _dividend_frame([_dividend_row(ex_date="2026-01-07")])
    with pytest.raises(M3G1ExecutionFactError) as caught:
        select_g1_corporate_actions(
            response=_make_verified("dividend", iso_frame), history=_history()
        )
    _assert_code(caught, "G1_CORPORATE_ACTION_EVENT_INVALID")


def test_p0h_rights_date8_no_longer_accepted() -> None:
    """CNINFO selector must not accept legacy YYYYMMDD after ISO closure."""
    response = _make_cninfo_verified(
        _cninfo_frame([_rights_row(F012D="20260107")])
    )
    with pytest.raises(M3G1ExecutionFactError) as caught:
        select_g1_cninfo_rights_actions(
            response=response, history=_history(), symbols=[_SYMBOL]
        )
    _assert_code(caught, "G1_CORPORATE_ACTION_EVENT_INVALID")


def test_p0h_rights_date_order_still_fail_closed() -> None:
    """Existing ordering invariants remain after ISO parser swap."""
    response = _make_cninfo_verified(
        _cninfo_frame([_rights_row(F011D="2026-01-07", F012D="2026-01-07")])
    )
    with pytest.raises(M3G1ExecutionFactError) as caught:
        select_g1_cninfo_rights_actions(
            response=response, history=_history(), symbols=[_SYMBOL]
        )
    _assert_code(caught, "G1_CORPORATE_ACTION_EVENT_INVALID")


def _p0i_full_day_rows(*days: dt.date, symbol: str = _SYMBOL) -> list[dict[str, Any]]:
    return [
        {
            "symbol": symbol,
            "trade_date": day,
            "suspension_scope": "FULL_DAY",
            "suspension_detail": None,
            "source": "tushare",
            "source_snapshot_id": _HEX,
        }
        for day in days
    ]


def _p0i_halt_resume_frames(
    *,
    symbol: str = _SYMBOL,
    prev_close: float = 4.31,
    cash_by_ex: dict[dt.date, float] | None = None,
    resume_cash: float | None = None,
    factor_prev: float = 34.8547,
    factor_resume: float = 35.6826,
    resume_pre_close: float = 4.21,
    halt_days: tuple[dt.date, ...] = (_D2, _D3),
    resume_day: dt.date = _D4,
    resume_factor: float | None = None,
    include_resume_bar: bool = True,
    include_resume_daily: bool = True,
    include_resume_factor: bool = True,
    include_mid_factors: bool = True,
    mid_non_full_day: dt.date | None = None,
) -> tuple[
    pl.DataFrame,
    pl.DataFrame,
    VerifiedRawResponse,
    pl.DataFrame,
    pl.DataFrame,
]:
    """600717-shaped halt: stable factors through halt, jump on first resume."""
    cash_by_ex = dict(cash_by_ex or {_D2: 0.102})
    resume_factor_value = factor_resume if resume_factor is None else resume_factor
    bar_days = [_D0, _D1]
    if include_resume_bar:
        bar_days.append(resume_day)
    closes: dict[dt.date, tuple[float, float]] = {
        _D0: (prev_close, prev_close),
        _D1: (prev_close, prev_close),
    }
    if include_resume_bar and include_resume_daily:
        closes[resume_day] = (prev_close - sum(cash_by_ex.values()), resume_pre_close)

    factor_days = [_D0, _D1]
    if include_mid_factors:
        factor_days.extend(day for day in halt_days if day not in factor_days)
    if include_resume_factor and resume_day not in factor_days:
        factor_days.append(resume_day)
    factor_days = sorted(set(factor_days))

    bars_rows = []
    for day in bar_days:
        close = closes.get(day, (prev_close, prev_close))[0]
        adj = factor_prev if day < resume_day else resume_factor_value
        bars_rows.append(
            {
                "symbol": symbol,
                "trade_date": day,
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "volume": 1.0,
                "amount": 1.0,
                "adj_factor": adj,
                "source": "tushare",
            }
        )
    factor_rows = []
    for day in factor_days:
        adj = factor_prev if day < resume_day else resume_factor_value
        factor_rows.append(
            {
                "symbol": symbol,
                "effective_date": day,
                "adj_factor": adj,
                "source": "tushare",
            }
        )
    bars = pl.DataFrame(bars_rows)
    factors = pl.DataFrame(factor_rows)
    daily_closes = closes if closes else {_D0: (prev_close, prev_close)}
    daily = _make_verified(
        "daily",
        pl.DataFrame(_daily_rows(closes=daily_closes, symbol=symbol)).select(
            TUSHARE_FIELDS["daily"].split(",")
        ),
        parameters={
            "ts_code": symbol,
            "start_date": _START,
            "end_date": _END,
        },
    )

    dividend_rows = []
    for index, (ex_date, cash) in enumerate(sorted(cash_by_ex.items())):
        dividend_rows.append(
            _dividend_row(
                ts_code=symbol,
                end_date=f"{2024 + index}1231",
                cash_div=cash,
                cash_div_tax=cash,
                record_date=(ex_date - dt.timedelta(days=1)).strftime("%Y%m%d"),
                ex_date=ex_date.strftime("%Y%m%d"),
                pay_date=(ex_date + dt.timedelta(days=1)).strftime("%Y%m%d"),
            )
        )
    if resume_cash is not None:
        dividend_rows.append(
            _dividend_row(
                ts_code=symbol,
                end_date="20261231",
                cash_div=resume_cash,
                cash_div_tax=resume_cash,
                record_date=(resume_day - dt.timedelta(days=1)).strftime("%Y%m%d"),
                ex_date=resume_day.strftime("%Y%m%d"),
                pay_date=(resume_day + dt.timedelta(days=1)).strftime("%Y%m%d"),
            )
        )
    actions = select_g1_corporate_actions(
        response=_make_verified(
            "dividend",
            _dividend_frame(dividend_rows),
            parameters={"ts_code": symbol},
        ),
        history=_history(),
    ).ledger

    halt_for_suspend = [
        day for day in halt_days if mid_non_full_day is None or day != mid_non_full_day
    ]
    suspensions = _suspension(_p0i_full_day_rows(*halt_for_suspend, symbol=symbol))
    return bars, factors, daily, actions, suspensions


def test_p0i_version_constant_exact() -> None:
    assert G1_CORPORATE_ACTION_RECONCILIATION_VERSION == (
        "tushare_factor_daily_preclose_suspension_resume_basis_terms_v9"
    )


def test_p0i_600717_shaped_delay_to_first_resume() -> None:
    """Continuous FULL_DAY, stable ex-date factor, jump only on first resume."""
    rtol = 0.001
    symbol = "600717.SH"
    bars, factors, daily, actions, suspensions = _p0i_halt_resume_frames(symbol=symbol)
    result = reconcile_g1_corporate_actions(
        corporate_actions=actions,
        bars=bars,
        adjustment_factors=factors,
        daily_responses=[daily],
        suspensions=suspensions,
        calendars=_default_calendar(),
        history=_history(),
        factor_ratio_rtol=rtol,
    )
    event = result.evidence.filter(pl.col("event_count") > 0)
    assert event.height == 1
    assert event["effective_date"][0] == _D4
    assert event["event_count"][0] == 1
    assert float(event["cash_per_share_gross"][0]) == pytest.approx(0.102)
    assert float(event["declared_dividend_relative_error"][0]) <= rtol
    assert float(event["market_reference_relative_error"][0]) <= rtol
    assert event["status"][0] in {
        "MATCHED_EVENT_DECLARED_FORMULA",
        "MATCHED_EVENT_MARKET_REFERENCE",
    }
    stable = result.evidence.filter(pl.col("status") == "NO_EVENT_STABLE_FACTOR")
    assert set(stable["effective_date"].to_list()) == {_D1, _D2, _D3}
    verify_corporate_action_reconciliation_result(result=result)


def _p0kb_reconciliation_inputs():
    transfer_id = "d" * 64
    transfer_actions = pl.DataFrame(
        [
            {
                "event_id": transfer_id,
                "symbol": _SYMBOL,
                "ex_date": _D3,
                "action_type": "DIVIDEND_DISTRIBUTION",
                "cash_per_share_gross": 0.0,
                "stock_ratio": 2.5,
                "rights_price": None,
                "rights_ratio": 0.0,
                "rights_actual_shares": None,
                "rights_pre_shares": None,
                "rights_post_shares": None,
                "rights_pre_circulating_shares": None,
                "rights_post_circulating_shares": None,
                "rights_mixed_change_proof_sha256": None,
                "record_date": _D2,
                "pay_date": None,
                "stock_list_date": _D3,
                "vendor_record_id": None,
                "source": "tushare",
                "source_snapshot_id": "2" * 64,
            },
        ]
    )
    dividend_row = {name: None for name in CNINFO_STOCK_DIVIDEND_FIELDS}
    dividend_row.update(
        {
            "F006D": _D0.isoformat(),
            "F007V": "10送5股",
            "F010N": "5",
            "F018D": _D0.isoformat(),
            "F044V": "承诺补偿",
        }
    )
    dividend_frame = pl.DataFrame(
        [dividend_row],
        schema={name: pl.Utf8 for name in CNINFO_STOCK_DIVIDEND_FIELDS},
    )
    share_rows: list[dict[str, Any]] = []
    for day, reason_code, reason_name, total, circulating in (
        (_D1, "015020", "股权分置", "100", "20"),
        (_D3, "015011", "转增", "350", "70"),
    ):
        row = {name: None for name in CNINFO_STOCK_SHARE_CHANGE_FIELDS}
        row.update(
            {
                "DECLAREDATE": day.isoformat(),
                "F001V": reason_code,
                "F002V": reason_name,
                "F003N": total,
                "F021N": circulating,
                "SECCODE": _SYMBOL[:6],
                "VARYDATE": day.isoformat(),
            }
        )
        share_rows.append(row)
    share_frame = pl.DataFrame(
        share_rows,
        schema={name: pl.Utf8 for name in CNINFO_STOCK_SHARE_CHANGE_FIELDS},
    )
    selection, facts = select_g1_cninfo_share_consideration_actions(
        dividend_response=_make_cninfo_ca_verified(
            endpoint=CNINFO_DIVIDEND_ENDPOINT,
            parameters={"symbol": _SYMBOL[:6]},
            frame=dividend_frame,
        ),
        share_change_response=_make_cninfo_ca_verified(
            endpoint=CNINFO_SHARE_CHANGE_ENDPOINT,
            parameters={
                "symbol": _SYMBOL[:6],
                "start_date": _D0.strftime("%Y%m%d"),
                "end_date": _D4.strftime("%Y%m%d"),
            },
            frame=share_frame,
        ),
        history=_history(),
        symbols=(_SYMBOL,),
        existing_actions=transfer_actions,
    )
    assert len(facts) == 1
    fact = facts[0]
    actions = pl.concat(
        [selection.ledger, transfer_actions], how="vertical_relaxed"
    )
    factors = pl.DataFrame(
        [
            {
                "symbol": _SYMBOL,
                "effective_date": day,
                "adj_factor": value,
                "source": "tushare",
            }
            for day, value in [
                (_D0, 2.34),
                (_D1, 2.34),
                (_D2, 2.34),
                (_D3, 8.19),
                (_D4, 9.36),
            ]
        ]
    )
    bars = pl.DataFrame(
        [
            {
                "symbol": _SYMBOL,
                "trade_date": day,
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "volume": 1.0,
                "amount": 1.0,
                "adj_factor": factor,
                "source": "tushare",
            }
            for day, close, factor in [(_D0, 10.0, 2.34), (_D4, 8.75, 9.36)]
        ]
    )
    daily = _make_verified(
        "daily",
        pl.DataFrame(
            _daily_rows(
                closes={_D0: (10.0, 10.0), _D4: (8.75, 8.75)},
                symbol=_SYMBOL,
            )
        ).select(TUSHARE_FIELDS["daily"].split(",")),
    )
    return actions, bars, factors, daily, fact


def test_p0kb_reconciliation_applies_basis_only_after_resume() -> None:
    actions, bars, factors, daily, fact = _p0kb_reconciliation_inputs()
    result = reconcile_g1_corporate_actions(
        corporate_actions=actions,
        bars=bars,
        adjustment_factors=factors,
        daily_responses=[daily],
        suspensions=_suspension(_p0i_full_day_rows(_D1, _D2, _D3)),
        calendars=_default_calendar(),
        history=_history(),
        factor_ratio_rtol=0.001,
        stock_ratio_normalization_facts=(fact,),
    )
    transfer = result.evidence.filter(pl.col("effective_date") == _D3).row(
        0, named=True
    )
    resume = result.evidence.filter(pl.col("effective_date") == _D4).row(
        0, named=True
    )
    assert transfer["stock_ratio"] == 2.5
    assert resume["stock_ratio"] == pytest.approx(0.5 / 3.5)
    assert resume["actual_factor_ratio"] == pytest.approx(9.36 / 8.19)
    assert resume["declared_dividend_relative_error"] <= 0.001
    assert '"basis_multiplier":"3.5"' in resume["stock_ratio_terms_json"]
    verify_corporate_action_reconciliation_result(result=result)
    receipts = (
        SimpleNamespace(
            request_id=fact.dividend_request_id,
            endpoint="stock_dividend",
            stable_response_sha256=fact.dividend_stable_response_sha256,
        ),
        SimpleNamespace(
            request_id=fact.share_change_request_id,
            endpoint="stock_share_change",
            stable_response_sha256=fact.share_change_stable_response_sha256,
        ),
    )
    assert_corporate_action_reconciliation_ledger_closure(
        corporate_actions=actions,
        reconciliation=result.evidence,
        input_receipts=receipts,
    )
    with pytest.raises(M3G1ExecutionFactError) as caught:
        assert_corporate_action_reconciliation_ledger_closure(
            corporate_actions=actions,
            reconciliation=result.evidence,
            input_receipts=receipts[:1],
        )
    assert caught.value.code == "G1_CORPORATE_ACTION_RECONCILIATION_INVALID"


def test_p0kb_formal_resume_uses_proven_basis_when_market_reference_is_not_comparable(
) -> None:
    actions, bars, factors, _daily, fact = _p0kb_reconciliation_inputs()
    pre_transfer_factor = 8.192 / 3.5
    factors = factors.with_columns(
        pl.when(pl.col("effective_date").is_in([_D0, _D1, _D2]))
        .then(pl.lit(pre_transfer_factor))
        .when(pl.col("effective_date") == _D3)
        .then(pl.lit(8.192))
        .otherwise(pl.lit(9.36))
        .alias("adj_factor")
    )
    bars = bars.with_columns(
        pl.when(pl.col("trade_date") == _D0)
        .then(pl.lit(52.69))
        .otherwise(pl.lit(9.5))
        .alias("open"),
        pl.when(pl.col("trade_date") == _D0)
        .then(pl.lit(52.69))
        .otherwise(pl.lit(9.5))
        .alias("high"),
        pl.when(pl.col("trade_date") == _D0)
        .then(pl.lit(52.69))
        .otherwise(pl.lit(9.5))
        .alias("low"),
        pl.when(pl.col("trade_date") == _D0)
        .then(pl.lit(52.69))
        .otherwise(pl.lit(9.5))
        .alias("close"),
        pl.when(pl.col("trade_date") == _D0)
        .then(pl.lit(pre_transfer_factor))
        .otherwise(pl.lit(9.36))
        .alias("adj_factor"),
    )
    daily = _make_verified(
        "daily",
        pl.DataFrame(
            _daily_rows(
                closes={_D0: (52.69, 52.69), _D4: (9.5, 15.05)},
                symbol=_SYMBOL,
            )
        ).select(TUSHARE_FIELDS["daily"].split(",")),
    )
    result = reconcile_g1_corporate_actions(
        corporate_actions=actions,
        bars=bars,
        adjustment_factors=factors,
        daily_responses=[daily],
        suspensions=_suspension(_p0i_full_day_rows(_D1, _D2, _D3)),
        calendars=_default_calendar(),
        history=_history(),
        factor_ratio_rtol=0.001,
        stock_ratio_normalization_facts=(fact,),
    )
    resume = result.evidence.filter(pl.col("effective_date") == _D4).row(
        0, named=True
    )
    assert resume["status"] == (
        "MATCHED_EVENT_BASIS_NORMALIZED_DECLARED_FORMULA"
    )
    assert resume["actual_factor_ratio"] == pytest.approx(9.36 / 8.192)
    assert resume["stock_ratio"] == pytest.approx(0.5 / 3.5)
    assert resume["declared_dividend_relative_error"] <= 0.001
    assert resume["market_reference_relative_error"] > 0.001
    verify_corporate_action_reconciliation_result(result=result)


def test_p0kb_exact_tushare_alias_closes_with_cninfo_lineage() -> None:
    actions, bars, factors, daily, fact = _p0kb_reconciliation_inputs()
    actions = actions.with_columns(
        pl.when(pl.col("event_id") == fact.event_id)
        .then(pl.lit("DIVIDEND_DISTRIBUTION"))
        .otherwise(pl.col("action_type"))
        .alias("action_type"),
        pl.when(pl.col("event_id") == fact.event_id)
        .then(pl.lit("tushare"))
        .otherwise(pl.col("source"))
        .alias("source"),
        pl.when(pl.col("event_id") == fact.event_id)
        .then(pl.lit("8" * 64))
        .otherwise(pl.col("source_snapshot_id"))
        .alias("source_snapshot_id"),
    )
    result = reconcile_g1_corporate_actions(
        corporate_actions=actions,
        bars=bars,
        adjustment_factors=factors,
        daily_responses=[daily],
        suspensions=_suspension(_p0i_full_day_rows(_D1, _D2, _D3)),
        calendars=_default_calendar(),
        history=_history(),
        factor_ratio_rtol=0.001,
        stock_ratio_normalization_facts=(fact,),
    )
    assert_corporate_action_reconciliation_ledger_closure(
        corporate_actions=actions,
        reconciliation=result.evidence,
        input_receipts=(
            SimpleNamespace(
                request_id=fact.dividend_request_id,
                endpoint="stock_dividend",
                stable_response_sha256=fact.dividend_stable_response_sha256,
            ),
            SimpleNamespace(
                request_id=fact.share_change_request_id,
                endpoint="stock_share_change",
                stable_response_sha256=fact.share_change_stable_response_sha256,
            ),
        ),
    )


def test_p0kb_resume_raw_ratio_without_basis_still_fails() -> None:
    actions, bars, factors, daily, _ = _p0kb_reconciliation_inputs()
    with pytest.raises(M3G1ExecutionFactError) as caught:
        reconcile_g1_corporate_actions(
            corporate_actions=actions,
            bars=bars,
            adjustment_factors=factors,
            daily_responses=[daily],
            suspensions=_suspension(_p0i_full_day_rows(_D1, _D2, _D3)),
            calendars=_default_calendar(),
            history=_history(),
            factor_ratio_rtol=0.001,
        )
    assert caught.value.code == "G1_CORPORATE_ACTION_BASIS_UNPROVEN"


def test_p0kb_row_hash_tamper_fails_after_rehashing_all_self_digests() -> None:
    actions, bars, factors, daily, fact = _p0kb_reconciliation_inputs()
    result = reconcile_g1_corporate_actions(
        corporate_actions=actions,
        bars=bars,
        adjustment_factors=factors,
        daily_responses=[daily],
        suspensions=_suspension(_p0i_full_day_rows(_D1, _D2, _D3)),
        calendars=_default_calendar(),
        history=_history(),
        factor_ratio_rtol=0.001,
        stock_ratio_normalization_facts=(fact,),
    )
    rows = result.evidence.to_dicts()
    resume = next(row for row in rows if row["effective_date"] == _D4)
    terms = json.loads(resume["stock_ratio_terms_json"])
    terms[0]["before_row_json"] = "{}"
    terms[0]["before_row_sha256"] = hashlib.sha256(b"{}").hexdigest()
    encoded = json.dumps(
        terms, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )
    resume["stock_ratio_terms_json"] = encoded
    resume["stock_ratio_terms_sha256"] = hashlib.sha256(
        encoded.encode("utf-8")
    ).hexdigest()
    attacked = pl.DataFrame(rows, schema=result.evidence.schema)
    digest = clean_table_content_sha256(
        table_name="corporate_action_reconciliation", frame=attacked
    )
    with pytest.raises(M3G1ExecutionFactError) as caught:
        CorporateActionReconciliationResult(
            evidence=attacked, evidence_sha256=digest
        )
    assert caught.value.code == "G1_CORPORATE_ACTION_RECONCILIATION_INVALID"


def test_p0kb_forged_source_bundle_still_fails_formal_receipt_closure() -> None:
    actions, bars, factors, daily, fact = _p0kb_reconciliation_inputs()
    result = reconcile_g1_corporate_actions(
        corporate_actions=actions,
        bars=bars,
        adjustment_factors=factors,
        daily_responses=[daily],
        suspensions=_suspension(_p0i_full_day_rows(_D1, _D2, _D3)),
        calendars=_default_calendar(),
        history=_history(),
        factor_ratio_rtol=0.001,
        stock_ratio_normalization_facts=(fact,),
    )
    rows = result.evidence.to_dicts()
    resume = next(row for row in rows if row["effective_date"] == _D4)
    terms = json.loads(resume["stock_ratio_terms_json"])
    term = terms[0]
    before = json.loads(term["before_row_json"])
    before["SECNAME"] = "FORGED"
    before_json = json.dumps(
        before, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )
    response_rows = json.loads(term["share_change_response_json"])
    response_rows = [
        before if row["VARYDATE"] == before["VARYDATE"] else row
        for row in response_rows
    ]
    response_json = json.dumps(
        response_rows, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )
    response_frame = pl.DataFrame(
        response_rows,
        schema={name: pl.Utf8 for name in CNINFO_STOCK_SHARE_CHANGE_FIELDS},
    ).select(list(CNINFO_STOCK_SHARE_CHANGE_FIELDS))
    receipt = json.loads(term["share_change_receipt_json"])
    receipt["response_content_sha256"] = (
        backfill.cninfo_corporate_action_response_content_sha256(
            response_frame, endpoint=CNINFO_SHARE_CHANGE_ENDPOINT
        )
    )
    receipt["stable_response_sha256"] = (
        backfill._cninfo_ca_stable_response_hash_values(receipt)
    )
    term["share_change_receipt_json"] = json.dumps(
        receipt, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )
    term["share_change_response_json"] = response_json
    term["share_change_stable_response_sha256"] = receipt[
        "stable_response_sha256"
    ]
    term["before_row_json"] = before_json
    term["before_row_sha256"] = hashlib.sha256(
        before_json.encode("utf-8")
    ).hexdigest()
    encoded = json.dumps(
        terms, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )
    resume["stock_ratio_terms_json"] = encoded
    resume["stock_ratio_terms_sha256"] = hashlib.sha256(
        encoded.encode("utf-8")
    ).hexdigest()
    attacked = pl.DataFrame(rows, schema=result.evidence.schema)
    attacked_result = CorporateActionReconciliationResult(
        evidence=attacked,
        evidence_sha256=clean_table_content_sha256(
            table_name="corporate_action_reconciliation", frame=attacked
        ),
    )
    with pytest.raises(M3G1ExecutionFactError) as caught:
        assert_corporate_action_reconciliation_ledger_closure(
            corporate_actions=actions,
            reconciliation=attacked_result.evidence,
            input_receipts=(
                SimpleNamespace(
                    request_id=fact.dividend_request_id,
                    endpoint=CNINFO_DIVIDEND_ENDPOINT,
                    stable_response_sha256=fact.dividend_stable_response_sha256,
                ),
                SimpleNamespace(
                    request_id=fact.share_change_request_id,
                    endpoint=CNINFO_SHARE_CHANGE_ENDPOINT,
                    stable_response_sha256=fact.share_change_stable_response_sha256,
                ),
            ),
        )
    assert caught.value.code == "G1_CORPORATE_ACTION_RECONCILIATION_INVALID"


def test_p0kb_event_identity_binds_lineage_and_decimal_canonical() -> None:
    assert _decimal_token(Decimal("0.1")) == "0.1"
    common = (
        _SYMBOL,
        _D0,
        _D1,
        Decimal("0.1"),
        "1" * 64,
    )
    first = _consideration_event_id_sha256(*common, "2" * 64)
    second = _consideration_event_id_sha256(*common, "3" * 64)
    assert first != second


def test_p0i_two_halt_events_aggregate_on_same_resume() -> None:
    declared = 4.31 / (4.31 - 0.102)
    bars, factors, daily, actions, suspensions = _p0i_halt_resume_frames(
        cash_by_ex={_D2: 0.05, _D3: 0.052},
        factor_resume=34.8547 * declared,
        resume_pre_close=4.31 / declared,
    )
    result = reconcile_g1_corporate_actions(
        corporate_actions=actions,
        bars=bars,
        adjustment_factors=factors,
        daily_responses=[daily],
        suspensions=suspensions,
        calendars=_default_calendar(),
        history=_history(),
        factor_ratio_rtol=0.001,
    )
    event = result.evidence.filter(pl.col("event_count") > 0)
    assert event.height == 1
    assert event["effective_date"][0] == _D4
    assert event["event_count"][0] == 2
    ids = set(actions["event_id"].to_list())
    assert len(ids) == 2
    import json

    matched_ids = set(json.loads(event["event_ids_json"][0]))
    assert matched_ids == ids
    assert float(event["cash_per_share_gross"][0]) == pytest.approx(0.102)
    verify_corporate_action_reconciliation_result(result=result)


def test_p0i_resume_day_exact_event_merges_with_delayed() -> None:
    declared = 4.31 / (4.31 - 0.15)
    bars, factors, daily, actions, suspensions = _p0i_halt_resume_frames(
        cash_by_ex={_D2: 0.102},
        resume_cash=0.048,
        factor_resume=34.8547 * declared,
        resume_pre_close=4.31 / declared,
    )
    result = reconcile_g1_corporate_actions(
        corporate_actions=actions,
        bars=bars,
        adjustment_factors=factors,
        daily_responses=[daily],
        suspensions=suspensions,
        calendars=_default_calendar(),
        history=_history(),
        factor_ratio_rtol=0.001,
    )
    event = result.evidence.filter(pl.col("event_count") > 0)
    assert event.height == 1
    assert event["effective_date"][0] == _D4
    assert event["event_count"][0] == 2
    assert float(event["cash_per_share_gross"][0]) == pytest.approx(0.15)
    verify_corporate_action_reconciliation_result(result=result)


def test_p0i_full_day_explainable_jump_stays_on_exact_date() -> None:
    bars, factors, daily, actions = _bars_and_factors_for_cash(include_ex_daily=False)
    suspensions = _suspension(_p0i_full_day_rows(_D2))
    result = reconcile_g1_corporate_actions(
        corporate_actions=actions,
        bars=bars,
        adjustment_factors=factors,
        daily_responses=[daily],
        suspensions=suspensions,
        calendars=_default_calendar(),
        history=_history(),
        factor_ratio_rtol=0.001,
    )
    event = result.evidence.filter(pl.col("event_count") > 0)
    assert event.height == 1
    assert event["effective_date"][0] == _D2
    assert event["status"][0] == "MATCHED_EVENT_DECLARED_FORMULA_NO_MARKET_REFERENCE"
    verify_corporate_action_reconciliation_result(result=result)


def test_p0i_full_day_stable_declared_within_rtol_no_delay() -> None:
    bars, factors, daily, actions = _bars_and_factors_for_cash(
        prev_close=10.0,
        cash=0.009,
        factor_eff=1.0,
        include_ex_daily=False,
    )
    suspensions = _suspension(_p0i_full_day_rows(_D2))
    result = reconcile_g1_corporate_actions(
        corporate_actions=actions,
        bars=bars,
        adjustment_factors=factors,
        daily_responses=[daily],
        suspensions=suspensions,
        calendars=_default_calendar(),
        history=_history(),
        factor_ratio_rtol=0.001,
    )
    event = result.evidence.filter(pl.col("event_count") > 0)
    assert event.height == 1
    assert event["effective_date"][0] == _D2
    assert event["status"][0] == (
        "MATCHED_EVENT_DECLARED_FORMULA_NO_MARKET_REFERENCE"
    )
    verify_corporate_action_reconciliation_result(result=result)


def test_p0i_non_full_day_event_never_delayed() -> None:
    bars, factors, daily, actions, _ = _p0i_halt_resume_frames()
    with pytest.raises(M3G1ExecutionFactError) as caught:
        reconcile_g1_corporate_actions(
            corporate_actions=actions,
            bars=bars,
            adjustment_factors=factors,
            daily_responses=[daily],
            suspensions=_suspension(),
            calendars=_default_calendar(),
            history=_history(),
            factor_ratio_rtol=0.001,
        )
    _assert_code(caught, "G1_CORPORATE_ACTION_FACTOR_UNEXPLAINED")


def test_p0i_fail_closed_no_resume_in_scope() -> None:
    bars, factors, daily, actions, suspensions = _p0i_halt_resume_frames(
        halt_days=(_D2, _D3, _D4),
        include_resume_bar=False,
        include_resume_daily=False,
        include_resume_factor=True,
        resume_factor=34.8547,
    )
    # Resume day still FULL_DAY and factor-stable; no non-FULL_DAY target.
    suspensions = _suspension(_p0i_full_day_rows(_D2, _D3, _D4))
    with pytest.raises(M3G1ExecutionFactError) as caught:
        reconcile_g1_corporate_actions(
            corporate_actions=actions,
            bars=bars,
            adjustment_factors=factors,
            daily_responses=[daily],
            suspensions=suspensions,
            calendars=_default_calendar(),
            history=_history(),
            factor_ratio_rtol=0.001,
        )
    _assert_code(caught, "G1_CORPORATE_ACTION_FACTOR_UNEXPLAINED")


def test_p0i_fail_closed_first_resume_missing_factor() -> None:
    bars, factors, daily, actions, suspensions = _p0i_halt_resume_frames(
        halt_days=(_D2,),
        resume_day=_D3,
        include_resume_factor=False,
        include_resume_bar=False,
        include_resume_daily=False,
    )
    # First non-FULL_DAY is D3 (no factor). Later D4 jump must not be searched.
    factors = pl.concat(
        [
            factors,
            pl.DataFrame(
                [
                    {
                        "symbol": _SYMBOL,
                        "effective_date": _D4,
                        "adj_factor": 35.6826,
                        "source": "tushare",
                    }
                ]
            ),
        ]
    )
    bars = pl.concat(
        [
            bars,
            pl.DataFrame(
                [
                    {
                        "symbol": _SYMBOL,
                        "trade_date": _D4,
                        "open": 4.21,
                        "high": 4.21,
                        "low": 4.21,
                        "close": 4.21,
                        "volume": 1.0,
                        "amount": 1.0,
                        "adj_factor": 35.6826,
                        "source": "tushare",
                    }
                ]
            ),
        ]
    )
    closes = {
        _D0: (4.31, 4.31),
        _D1: (4.31, 4.31),
        _D4: (4.21, 4.21),
    }
    daily = _make_verified(
        "daily",
        _daily_frame(closes),
        parameters={"ts_code": _SYMBOL, "start_date": _START, "end_date": _END},
    )
    with pytest.raises(M3G1ExecutionFactError) as caught:
        reconcile_g1_corporate_actions(
            corporate_actions=actions,
            bars=bars,
            adjustment_factors=factors,
            daily_responses=[daily],
            suspensions=suspensions,
            calendars=_default_calendar(),
            history=_history(),
            factor_ratio_rtol=0.001,
        )
    _assert_code(caught, "G1_CORPORATE_ACTION_FACTOR_UNEXPLAINED")


def test_p0i_fail_closed_resume_missing_daily_or_bar() -> None:
    bars, factors, daily, actions, suspensions = _p0i_halt_resume_frames(
        include_resume_bar=False,
        include_resume_daily=False,
        include_resume_factor=True,
    )
    with pytest.raises(M3G1ExecutionFactError) as caught:
        reconcile_g1_corporate_actions(
            corporate_actions=actions,
            bars=bars,
            adjustment_factors=factors,
            daily_responses=[daily],
            suspensions=suspensions,
            calendars=_default_calendar(),
            history=_history(),
            factor_ratio_rtol=0.001,
        )
    _assert_code(caught, "G1_CORPORATE_ACTION_FACTOR_UNEXPLAINED")


def test_p0i_fail_closed_resume_still_stable_declared_exceeds() -> None:
    # Resume factor stays flat while market implies a jump → cannot explain events.
    bars, factors, daily, actions, suspensions = _p0i_halt_resume_frames(
        resume_factor=34.8547,
        resume_pre_close=4.21,
    )
    with pytest.raises(M3G1ExecutionFactError) as caught:
        reconcile_g1_corporate_actions(
            corporate_actions=actions,
            bars=bars,
            adjustment_factors=factors,
            daily_responses=[daily],
            suspensions=suspensions,
            calendars=_default_calendar(),
            history=_history(),
            factor_ratio_rtol=0.001,
        )
    _assert_code(caught, "G1_CORPORATE_ACTION_FACTOR_UNEXPLAINED")


def test_p0i_fail_closed_resume_unsupported_or_over_rtol() -> None:
    bars, factors, daily, actions, suspensions = _p0i_halt_resume_frames(
        factor_resume=20.0,
        resume_pre_close=2.0,
    )
    with pytest.raises(M3G1ExecutionFactError) as caught:
        reconcile_g1_corporate_actions(
            corporate_actions=actions,
            bars=bars,
            adjustment_factors=factors,
            daily_responses=[daily],
            suspensions=suspensions,
            calendars=_default_calendar(),
            history=_history(),
            factor_ratio_rtol=0.001,
        )
    _assert_code(caught, "G1_CORPORATE_ACTION_FACTOR_UNEXPLAINED")


def test_p0i_must_not_skip_intermediate_non_full_day() -> None:
    """First non-FULL_DAY that cannot explain must fail; do not search later jump."""
    bars, factors, daily, actions, suspensions = _p0i_halt_resume_frames(
        halt_days=(_D2,),
        resume_day=_D3,
        resume_factor=34.8547,
        resume_pre_close=4.21,
    )
    # Align resume-day bar close with daily; keep factor flat so matching fails.
    bars = bars.with_columns(
        pl.when(pl.col("trade_date") == _D3)
        .then(pl.lit(4.31))
        .otherwise(pl.col("close"))
        .alias("close"),
        pl.when(pl.col("trade_date") == _D3)
        .then(pl.lit(4.31))
        .otherwise(pl.col("open"))
        .alias("open"),
        pl.when(pl.col("trade_date") == _D3)
        .then(pl.lit(4.31))
        .otherwise(pl.col("high"))
        .alias("high"),
        pl.when(pl.col("trade_date") == _D3)
        .then(pl.lit(4.31))
        .otherwise(pl.col("low"))
        .alias("low"),
    )
    factors = pl.concat(
        [
            factors,
            pl.DataFrame(
                [
                    {
                        "symbol": _SYMBOL,
                        "effective_date": _D4,
                        "adj_factor": 35.6826,
                        "source": "tushare",
                    }
                ]
            ),
        ]
    ).sort(["symbol", "effective_date"])
    bars = pl.concat(
        [
            bars,
            pl.DataFrame(
                [
                    {
                        "symbol": _SYMBOL,
                        "trade_date": _D4,
                        "open": 4.21,
                        "high": 4.21,
                        "low": 4.21,
                        "close": 4.21,
                        "volume": 1.0,
                        "amount": 1.0,
                        "adj_factor": 35.6826,
                        "source": "tushare",
                    }
                ]
            ),
        ]
    ).sort(["symbol", "trade_date"])
    closes = {
        _D0: (4.31, 4.31),
        _D1: (4.31, 4.31),
        _D3: (4.31, 4.21),
        _D4: (4.21, 4.21),
    }
    daily = _make_verified(
        "daily",
        _daily_frame(closes),
        parameters={"ts_code": _SYMBOL, "start_date": _START, "end_date": _END},
    )
    with pytest.raises(M3G1ExecutionFactError) as caught:
        reconcile_g1_corporate_actions(
            corporate_actions=actions,
            bars=bars,
            adjustment_factors=factors,
            daily_responses=[daily],
            suspensions=suspensions,
            calendars=_default_calendar(),
            history=_history(),
            factor_ratio_rtol=0.001,
        )
    _assert_code(caught, "G1_CORPORATE_ACTION_FACTOR_UNEXPLAINED")

def test_p0i_delayed_evidence_tamper_rejected() -> None:
    bars, factors, daily, actions, suspensions = _p0i_halt_resume_frames()
    result = reconcile_g1_corporate_actions(
        corporate_actions=actions,
        bars=bars,
        adjustment_factors=factors,
        daily_responses=[daily],
        suspensions=suspensions,
        calendars=_default_calendar(),
        history=_history(),
        factor_ratio_rtol=0.001,
    )
    event_mask = pl.col("event_count") > 0
    for poisoned in (
        result.evidence.with_columns(
            pl.when(event_mask)
            .then(pl.lit("[]"))
            .otherwise(pl.col("event_ids_json"))
            .alias("event_ids_json")
        ),
        result.evidence.with_columns(
            pl.when(event_mask)
            .then(pl.lit(0))
            .otherwise(pl.col("event_count"))
            .alias("event_count")
        ),
        result.evidence.with_columns(
            pl.when(event_mask)
            .then(pl.lit("c" * 64))
            .otherwise(pl.col("event_ids_sha256"))
            .alias("event_ids_sha256")
        ),
    ):
        with pytest.raises(M3G1ExecutionFactError) as caught:
            _rebuild_recon(poisoned)
        _assert_code(caught, "G1_CORPORATE_ACTION_RECONCILIATION_INVALID")


def test_p0i_input_order_does_not_affect_digest() -> None:
    bars, factors, daily, actions, suspensions = _p0i_halt_resume_frames(
        cash_by_ex={_D2: 0.05, _D3: 0.052},
        factor_resume=34.8547 * (4.31 / (4.31 - 0.102)),
        resume_pre_close=4.31 / (4.31 / (4.31 - 0.102)),
    )
    forward = reconcile_g1_corporate_actions(
        corporate_actions=actions,
        bars=bars,
        adjustment_factors=factors,
        daily_responses=[daily],
        suspensions=suspensions,
        calendars=_default_calendar(),
        history=_history(),
        factor_ratio_rtol=0.001,
    )
    reversed_result = reconcile_g1_corporate_actions(
        corporate_actions=actions.reverse(),
        bars=bars.reverse(),
        adjustment_factors=factors.reverse(),
        daily_responses=[daily],
        suspensions=suspensions.reverse(),
        calendars=_default_calendar(),
        history=_history(),
        factor_ratio_rtol=0.001,
    )
    assert forward.evidence_sha256 == reversed_result.evidence_sha256
    assert forward.evidence.sort(
        ["symbol", "previous_factor_date", "effective_date"]
    ).equals(
        reversed_result.evidence.sort(
            ["symbol", "previous_factor_date", "effective_date"]
        )
    )
    verify_corporate_action_reconciliation_result(result=forward)


def test_no_network_or_research_imports() -> None:
    path = Path("src/quant/data/m3_execution_facts.py")
    text = path.read_text(encoding="utf-8")
    assert "requests" not in text
    assert "quant.research" not in text
    assert "qlib" not in text.lower()
    assert "open(" not in text
    # Do not importlib.reload here: it replaces exception/classes in sys.modules
    # and breaks later pytest.raises(M3G1ExecutionFactError) identity checks.
