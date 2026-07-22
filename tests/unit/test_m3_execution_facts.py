"""G1-P3 B2C execution facts: price limits and corporate-action reconciliation."""

from __future__ import annotations

import datetime as dt
import importlib
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from quant.data import m3_backfill as backfill
from quant.data.m3_backfill import (
    TUSHARE_FIELDS,
    HistoryWindow,
    TushareRequestReceipt,
    TushareRequestSpec,
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
    map_g1_price_limit_response,
    reconcile_g1_corporate_actions,
    require_g1_price_limit_coverage,
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
    assert G1_PRICE_LIMIT_METHOD_VERSION == "tushare_stk_limit_suspension_aware_v1"
    assert G1_CORPORATE_ACTION_SELECTION_VERSION == (
        "tushare_dividend_implemented_latest_v1"
    )
    assert G1_CORPORATE_ACTION_RECONCILIATION_VERSION == (
        "tushare_factor_daily_preclose_v1"
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
        history=_history(),
    )
    assert required_delist.get_column("trade_date").to_list() == [_D1, _D2]


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
        response=_make_verified("dividend", _dividend_frame()), history=_history()
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

    # PARTIAL fails
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
    with pytest.raises(M3G1ExecutionFactError) as caught:
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
    _assert_code(caught, "G1_CORPORATE_ACTION_FACTOR_UNEXPLAINED")


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


def test_no_network_or_research_imports() -> None:
    path = Path("src/quant/data/m3_execution_facts.py")
    text = path.read_text(encoding="utf-8")
    assert "requests" not in text
    assert "quant.research" not in text
    assert "qlib" not in text.lower()
    assert "open(" not in text
    importlib.reload(sys.modules["quant.data.m3_execution_facts"])