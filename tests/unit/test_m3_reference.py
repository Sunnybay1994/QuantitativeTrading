"""M3 G1-P4B: BaoStock cross-source evidence and reconciliation unit tests."""

from __future__ import annotations

import datetime as dt
import io
import json
import os
import socket
import sys
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any
from unittest.mock import patch

import polars as pl
import pytest

from quant.data import m3_backfill as backfill
from quant.data import m3_reference as ref
from quant.data.connectors.baostock import BaostockConnector
from quant.data.m3_backfill import (
    TUSHARE_FIELDS,
    HistoryWindow,
    VerifiedRawResponse,
    plan_index_weight_requests,
)
from quant.data.m3_execution_facts import (
    G1_CORPORATE_ACTION_RECONCILIATION_VERSION,
    G1_CORPORATE_ACTION_SELECTION_VERSION,
    G1_PRICE_LIMIT_METHOD_VERSION,
    require_g1_price_limit_coverage,
)
from quant.data.m3_g1_candidate import (
    G1_MEMBERSHIP_METHOD_VERSION,
    G1BuildInputs,
    G1BuildSpec,
    G1Candidate,
    G1QualityIssue,
    _TABLE_ATTRS,
    _TABLE_NAMES,
    _TABLE_SCHEMAS,
    _canonical_eligible_keys,
    _primary_candidate_key,
    audit_g1_candidate,
    build_g1_candidate,
)
from quant.data.m3_identity import clean_table_content_sha256
from quant.data.m3_reference import (
    CrossSourceFieldStatsV1,
    CrossSourceReconciliationBundle,
    CrossSourceSamplePlan,
    G1CrossSourcePolicy,
    M3ReferenceError,
    ReferenceRawCandidateV1,
    ReferenceRequestIntentV1,
    ReferenceRequestPlanV1,
    ReferenceRequestReceipt,
    ReferenceRequestSpec,
    VerifiedReferenceResponse,
    execute_baostock_reference_plan,
    plan_baostock_reference_requests,
    plan_cross_source_reconciliation,
    reconcile_cross_source,
    verify_reference_receipt,
)
from quant.data.storage import RawStore
from quant.research.m3.g1_planning import plan_g1_etf_history_requests

_HEX = "a" * 64
_UNIVERSE = "CSI300_TUSHARE_MONTHLY_OBSERVED_PIT_V1"
_INDEX = "000300.SH"
_BENCHMARK = "510300.SH"
_D0 = dt.date(2016, 2, 1)  # Monday signal day
_OBS_JAN = "20160129"
_OBS_FEB = "20160229"
_HISTORY_DAY_COUNT = 25


def _require_symlink(
    link: Path, target: Path, *, target_is_directory: bool = False
) -> None:
    """Create a symlink; skip only when Windows reports missing symlink privilege (1314)."""
    try:
        link.symlink_to(target, target_is_directory=target_is_directory)
    except OSError as exc:
        if sys.platform == "win32" and getattr(exc, "winerror", None) == 1314:
            pytest.skip("Windows session lacks SeCreateSymbolicLinkPrivilege")
        raise


def _require_fifo(path: Path) -> None:
    """Create a FIFO; skip when the platform/filesystem cannot create one."""
    mkfifo = getattr(os, "mkfifo", None)
    if mkfifo is None:
        pytest.skip("filesystem does not support FIFO")
    try:
        mkfifo(path)
    except OSError:
        pytest.skip("filesystem does not support FIFO")


def _weekdays(start: dt.date, count: int) -> list[dt.date]:
    days: list[dt.date] = []
    cursor = start
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += dt.timedelta(days=1)
    return days


_HISTORY_DAYS = _weekdays(_D0, _HISTORY_DAY_COUNT)
_D1 = _HISTORY_DAYS[-1]


# ---------------------------------------------------------------------------
# G1Candidate fixture builders (copied/extended from test_m3_g1_candidate.py
# patterns; NOT imported from that module per task constraints).
# ---------------------------------------------------------------------------


def _symbols(n: int = 300) -> list[str]:
    out: list[str] = []
    for i in range(n):
        code = f"{i + 1:06d}"
        out.append(f"{code}.SZ" if i < 150 else f"{code}.SH")
    return out


def _weights(n: int = 300) -> list[float]:
    return [100.0 / n] * n


def _make_verified(
    endpoint: str,
    frame: pl.DataFrame,
    *,
    parameters: dict[str, str] | None = None,
) -> VerifiedRawResponse:
    from quant.data.m3_backfill import TushareRequestReceipt, TushareRequestSpec, response_content_sha256

    params = {"fields": TUSHARE_FIELDS[endpoint], **(parameters or {})}
    if endpoint == "suspend_d":
        params.setdefault("suspend_type", "S")
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


def _weight_frame(trade_date: str, symbols: list[str]) -> pl.DataFrame:
    vals = _weights(len(symbols))
    rows = [
        {
            "index_code": _INDEX,
            "con_code": symbol,
            "trade_date": trade_date,
            "weight": weight,
        }
        for symbol, weight in zip(symbols, vals, strict=True)
    ]
    return pl.DataFrame(rows).select(TUSHARE_FIELDS["index_weight"].split(","))


def _calendar(start: dt.date, end: dt.date) -> pl.DataFrame:
    rows: list[dict[str, Any]] = []
    cursor = start
    while cursor <= end:
        is_open = cursor.weekday() < 5
        for market in ("SH", "SZ"):
            rows.append(
                {
                    "market": market,
                    "date": cursor,
                    "is_open": is_open,
                    "is_connect_open": False,
                    "is_half_day": False,
                }
            )
        cursor += dt.timedelta(days=1)
    return pl.DataFrame(rows)


def _instruments(symbols: list[str]) -> pl.DataFrame:
    rows = []
    for symbol in symbols:
        market = symbol.rsplit(".", 1)[-1]
        rows.append(
            {
                "symbol": symbol,
                "market": market,
                "name": symbol,
                "instrument_type": "STOCK",
                "currency": "CNY",
                "list_date": dt.date(2010, 1, 4),
                "delist_date": None,
                "board_lot": 100,
                "status": "LISTED",
            }
        )
    return pl.DataFrame(rows)


def _daily_frame(symbol: str, days: list[dt.date]) -> pl.DataFrame:
    rows = []
    for day in days:
        rows.append(
            {
                "ts_code": symbol,
                "trade_date": day.strftime("%Y%m%d"),
                "open": 10.0,
                "high": 10.0,
                "low": 10.0,
                "close": 10.0,
                "pre_close": 10.0,
                "change": 0.0,
                "pct_chg": 0.0,
                "vol": 1.0,
                "amount": 1.0,
            }
        )
    return pl.DataFrame(rows).select(TUSHARE_FIELDS["daily"].split(","))


def _factor_frame(symbol: str, days: list[dt.date], factor: float = 1.0) -> pl.DataFrame:
    rows = [
        {
            "ts_code": symbol,
            "trade_date": day.strftime("%Y%m%d"),
            "adj_factor": factor,
        }
        for day in days
    ]
    return pl.DataFrame(rows).select(TUSHARE_FIELDS["adj_factor"].split(","))


def _limit_frame(symbol: str, days: list[dt.date]) -> pl.DataFrame:
    rows = [
        {
            "trade_date": day.strftime("%Y%m%d"),
            "ts_code": symbol,
            "pre_close": 10.0,
            "up_limit": 11.0,
            "down_limit": 9.0,
        }
        for day in days
    ]
    return pl.DataFrame(rows).select(TUSHARE_FIELDS["stk_limit"].split(","))


def _empty_dividend(_symbol: str) -> pl.DataFrame:
    schema: dict[str, Any] = {c: pl.Utf8 for c in TUSHARE_FIELDS["dividend"].split(",")}
    for col in ("stk_div", "stk_bo_rate", "stk_co_rate", "cash_div", "cash_div_tax", "base_share"):
        schema[col] = pl.Float64
    return pl.DataFrame(schema=schema)


def _empty_suspend() -> pl.DataFrame:
    return pl.DataFrame(schema={c: pl.Utf8 for c in TUSHARE_FIELDS["suspend_d"].split(",")})



def _fund_daily_frame(days: list[dt.date]) -> pl.DataFrame:
    rows = []
    prev_close = 1.0
    for day in days:
        rows.append(
            {
                "ts_code": _BENCHMARK,
                "trade_date": day.strftime("%Y%m%d"),
                "open": 1.0,
                "high": 1.0,
                "low": 1.0,
                "close": 1.0,
                "pre_close": prev_close,
                "change": 0.0,
                "pct_chg": 0.0,
                "vol": 1.0,
                "amount": 1.0,
            }
        )
        prev_close = 1.0
    return pl.DataFrame(rows).select(TUSHARE_FIELDS["fund_daily"].split(","))


def _fund_adj_frame(days: list[dt.date]) -> pl.DataFrame:
    rows = [
        {
            "ts_code": _BENCHMARK,
            "trade_date": day.strftime("%Y%m%d"),
            "adj_factor": 1.0,
        }
        for day in days
    ]
    return pl.DataFrame(rows).select(TUSHARE_FIELDS["fund_adj"].split(","))


def _fund_div_frame() -> pl.DataFrame:
    # Outside test window so no in-window reconciliation is required.
    row = {
        "ts_code": _BENCHMARK,
        "ann_date": "20100105",
        "imp_anndate": "20100105",
        "base_date": "20100105",
        "div_proc": "实施",
        "record_date": "20100105",
        "ex_date": "20100106",
        "pay_date": "20100107",
        "earpay_date": None,
        "net_ex_date": "20100106",
        "div_cash": 0.01,
        "base_unit": 1.0,
        "ear_distr": None,
        "ear_amount": None,
        "account_date": None,
        "base_year": "2009",
    }
    return pl.DataFrame([row]).select(TUSHARE_FIELDS["fund_div"].split(","))


def _build_spec() -> G1BuildSpec:
    return G1BuildSpec(
        config_version="m3-g1-test-v1",
        g1_config_sha256=_HEX,
        mapper_version="m3-g1-tushare-mapper-v3",
        schema_version="m3-g1-schema-v1",
        membership_method_version=G1_MEMBERSHIP_METHOD_VERSION,
        price_limit_method_version=G1_PRICE_LIMIT_METHOD_VERSION,
        corporate_action_selection_version=G1_CORPORATE_ACTION_SELECTION_VERSION,
        corporate_action_reconciliation_version=G1_CORPORATE_ACTION_RECONCILIATION_VERSION,
        benchmark_mode="TRADEABLE_ETF_TOTAL_RETURN_PROXY",
        benchmark_method_version="tushare_510300_fund_daily_fund_adj_hfq_v1",
        benchmark_dividend_reconciliation_version="tushare_fund_div_implemented_cash_v1",
        build_code_version="m3-g1-candidate-v1",
        dependency_fingerprint_sha256=_HEX,
    )


def _build_inputs() -> G1BuildInputs:
    syms = _symbols()
    days = _HISTORY_DAYS
    history = HistoryWindow(_D0, _D1)
    weight_batch = plan_index_weight_requests(
        index_code=_INDEX, start=_D0, end=_D0, warmup_months=1,
    )
    plan = plan_g1_etf_history_requests(
        index_weight_batch=weight_batch, symbols=syms, history=history,
    )
    responses: list[VerifiedRawResponse] = []
    for spec in weight_batch.requests:
        params = dict(spec.parameters)
        start = dt.datetime.strptime(params["start_date"], "%Y%m%d").date()
        trade_date = _OBS_JAN if start.month == 1 else _OBS_FEB
        frame = _weight_frame(trade_date, syms)
        responses.append(
            _make_verified(
                "index_weight",
                frame,
                parameters={
                    "index_code": _INDEX,
                    "start_date": params["start_date"],
                    "end_date": params["end_date"],
                },
            )
        )
    for symbol in sorted(set(syms)):
        responses.append(
            _make_verified(
                "daily",
                _daily_frame(symbol, days),
                parameters={
                    "ts_code": symbol,
                    "start_date": _D0.strftime("%Y%m%d"),
                    "end_date": _D1.strftime("%Y%m%d"),
                },
            )
        )
        responses.append(
            _make_verified(
                "adj_factor",
                _factor_frame(symbol, days),
                parameters={
                    "ts_code": symbol,
                    "start_date": _D0.strftime("%Y%m%d"),
                    "end_date": _D1.strftime("%Y%m%d"),
                },
            )
        )
        responses.append(
            _make_verified(
                "stk_limit",
                _limit_frame(symbol, days),
                parameters={
                    "ts_code": symbol,
                    "start_date": _D0.strftime("%Y%m%d"),
                    "end_date": _D1.strftime("%Y%m%d"),
                },
            )
        )
        responses.append(
            _make_verified("dividend", _empty_dividend(symbol), parameters={"ts_code": symbol})
        )
    for spec in plan.history_batch.requests:
        if spec.endpoint == "fund_daily":
            responses.append(
                _make_verified(
                    "fund_daily",
                    _fund_daily_frame(days),
                    parameters=dict(spec.parameters),
                )
            )
        elif spec.endpoint == "fund_adj":
            responses.append(
                _make_verified(
                    "fund_adj",
                    _fund_adj_frame(days),
                    parameters=dict(spec.parameters),
                )
            )
        elif spec.endpoint == "fund_div":
            responses.append(
                _make_verified(
                    "fund_div",
                    _fund_div_frame(),
                    parameters=dict(spec.parameters),
                )
            )
    for spec in plan.history_batch.requests:
        if spec.endpoint != "suspend_d":
            continue
        params = dict(spec.parameters)
        # Per-symbol suspend_d (planning contract): include ts_code so request_id matches.
        responses.append(
            _make_verified(
                "suspend_d",
                _empty_suspend(),
                parameters={
                    "ts_code": params["ts_code"],
                    "start_date": params["start_date"],
                    "end_date": params["end_date"],
                    "suspend_type": params.get("suspend_type", "S"),
                },
            )
        )
    by_id = {item.spec.request_id: item for item in responses}
    plan_ids = {spec.request_id for spec in plan.index_weight_batch.requests} | {
        spec.request_id for spec in plan.history_batch.requests
    }
    response_ids = set(by_id)
    if plan_ids != response_ids:
        missing = sorted(plan_ids - response_ids)
        extra = sorted(response_ids - plan_ids)
        raise AssertionError(
            "reference fixture request ids must close with plan batches; "
            f"missing={missing[:5]!r}(+{max(0, len(missing) - 5)}) "
            f"extra={extra[:5]!r}(+{max(0, len(extra) - 5)})"
        )
    ordered = [by_id[spec.request_id] for spec in plan.index_weight_batch.requests] + [
        by_id[spec.request_id] for spec in plan.history_batch.requests
    ]
    return G1BuildInputs(
        build_spec=_build_spec(),
        request_plan=plan,
        responses=tuple(ordered),
        calendars=_calendar(dt.date(2016, 1, 1), _D1 + dt.timedelta(days=10)),
        instruments=_instruments(syms),
        universe=_UNIVERSE,
        signal_start=_D0,
        signal_end=_D0,
        history=history,
        expected_constituent_count=300,
        factor_ratio_rtol=0.001,
    )


def _rebind_identity(candidate: G1Candidate, **changes: Any) -> G1Candidate:
    """Mutate frames then recompute digests/required/primary so constructor accepts."""
    values: dict[str, Any] = {
        "build_spec": candidate.build_spec,
        "request_plan": candidate.request_plan,
        "signal_start": candidate.signal_start,
        "signal_end": candidate.signal_end,
        "history_start": candidate.history_start,
        "history_end": candidate.history_end,
        "input_receipts": candidate.input_receipts,
        "calendars": candidate.calendars,
        "instruments": candidate.instruments,
        "observations": candidate.observations,
        "membership": candidate.membership,
        "eligible_keys": candidate.eligible_keys,
        "bars": candidate.bars,
        "adjustment_factors": candidate.adjustment_factors,
        "factor_match_evidence": candidate.factor_match_evidence,
        "benchmark_bars": candidate.benchmark_bars,
        "suspensions": candidate.suspensions,
        "price_limits": candidate.price_limits,
        "corporate_actions": candidate.corporate_actions,
        "corporate_action_selection_evidence": candidate.corporate_action_selection_evidence,
        "corporate_action_reconciliation": candidate.corporate_action_reconciliation,
    }
    values.update(changes)
    for table_name in _TABLE_NAMES:
        attr = _TABLE_ATTRS[table_name]
        if table_name == "eligible_keys":
            values[attr] = _canonical_eligible_keys(values[attr])
        else:
            values[attr] = _TABLE_SCHEMAS[table_name].validate(values[attr])
    digests = tuple(
        (name, clean_table_content_sha256(table_name=name, frame=values[_TABLE_ATTRS[name]]))
        for name in _TABLE_NAMES
    )
    required = require_g1_price_limit_coverage(
        price_limits=values["price_limits"],
        eligible_keys=values["eligible_keys"],
        suspensions=values["suspensions"],
        calendars=values["calendars"],
        instruments=values["instruments"],
        bars=values["bars"],
        history=HistoryWindow(values["history_start"], values["history_end"]),
    )
    required_digest = clean_table_content_sha256(
        table_name="price_limit_required_keys", frame=required
    )
    primary = _primary_candidate_key(
        build_spec=values["build_spec"],
        request_plan_sha256=values["request_plan"].plan_sha256,
        signal_start=values["signal_start"],
        signal_end=values["signal_end"],
        history_start=values["history_start"],
        history_end=values["history_end"],
        input_receipts=values["input_receipts"],
        table_content_digests=digests,
        price_limit_required_keys_sha256=required_digest,
    )
    return G1Candidate(
        **values,
        table_content_digests=digests,
        price_limit_required_keys_sha256=required_digest,
        primary_candidate_key=primary,
    )


def _restrict_bar_symbols(
    candidate: G1Candidate,
    keep_symbols: list[str],
    *,
    short_symbol: str | None = None,
    short_keep: int | None = None,
) -> G1Candidate:
    """Shrink bars to ``keep_symbols`` and FULL_DAY-suspend the rest on D0.

    Used to build deterministic <30-symbol and <20-date reconciliation
    fixtures without violating the frozen 300-member P4A build contract.
    """
    keep_set = set(keep_symbols)
    bars = candidate.bars.filter(pl.col("symbol").is_in(sorted(keep_set)))
    if short_symbol is not None:
        remaining_days = sorted(
            bars.filter(pl.col("symbol") == short_symbol).get_column("trade_date").to_list()
        )[:short_keep]
        bars = bars.filter(
            (pl.col("symbol") != short_symbol) | pl.col("trade_date").is_in(remaining_days)
        )
    all_symbols = sorted(set(candidate.instruments.get_column("symbol").to_list()))
    drop_symbols = [symbol for symbol in all_symbols if symbol not in keep_set]
    suspensions = pl.DataFrame(
        [
            {
                "symbol": symbol,
                "trade_date": _D0,
                "suspension_scope": "FULL_DAY",
                "suspension_detail": None,
                "source": "tushare",
                "source_snapshot_id": _HEX,
            }
            for symbol in drop_symbols
        ]
    )
    return _rebind_identity(candidate, bars=bars, suspensions=suspensions)


@pytest.fixture(scope="module")
def happy_inputs() -> G1BuildInputs:
    return _build_inputs()


@pytest.fixture(scope="module")
def happy_candidate(happy_inputs: G1BuildInputs) -> G1Candidate:
    return build_g1_candidate(inputs=happy_inputs)


def _base_policy_kwargs() -> dict[str, Any]:
    return dict(
        reference_source="baostock",
        sample_symbols=30,
        dates_per_symbol=20,
        price_atol=0.01,
        price_rtol=0.0001,
        volume_rtol=0.01,
        max_mismatch_rate=0.01,
    )


def _policy(**overrides: Any) -> G1CrossSourcePolicy:
    kwargs = _base_policy_kwargs()
    kwargs.update(overrides)
    return G1CrossSourcePolicy(**kwargs)


@pytest.fixture(scope="module")
def sample_plan(happy_candidate: G1Candidate) -> CrossSourceSamplePlan:
    return plan_cross_source_reconciliation(candidate=happy_candidate, policy=_policy())


@pytest.fixture(scope="module")
def request_plan(sample_plan: CrossSourceSamplePlan) -> ReferenceRequestPlanV1:
    return plan_baostock_reference_requests(sample_plan=sample_plan)


# ---------------------------------------------------------------------------
# Reference-frame helpers for reconciliation tests.
# ---------------------------------------------------------------------------


def _num(value: float) -> str:
    return repr(float(value))


def _make_verified_reference(
    spec: ReferenceRequestSpec, frame: pl.DataFrame
) -> VerifiedReferenceResponse:
    content = ref._reference_response_content_sha256(frame)
    candidate = ReferenceRawCandidateV1(
        "m3-g1-baostock-candidate-v1",
        spec.request_id,
        spec.endpoint,
        spec.symbol,
        ref._parameters_hash(spec.parameters),
        spec.request_id,
        f"baostock/query_history_k_data_plus/request={spec.request_id}/data.parquet",
        f"baostock/query_history_k_data_plus/request={spec.request_id}/metadata.json",
        _HEX,
        _HEX,
        content,
        max(frame.height, 1),
        frame.height,
        tuple(frame.columns),
    )
    receipt = ref._receipt_from_candidate(spec, candidate)
    receipt_sha256 = ref._sha256_json(asdict(receipt))
    return VerifiedReferenceResponse(spec, receipt, receipt_sha256, frame)


def _reference_frame(rows: list[dict[str, str]]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema={c: pl.Utf8 for c in ref._FIELD_COLUMNS}).select(
        list(ref._FIELD_COLUMNS)
    )


def _reference_rows_for_symbol(
    candidate: G1Candidate,
    symbol: str,
    dates: list[dt.date],
    *,
    zero_dates: frozenset[dt.date] = frozenset(),
) -> list[dict[str, str]]:
    code = ref._symbol_to_baostock_code(symbol)
    bars_index = {
        row["trade_date"]: row
        for row in candidate.bars.filter(pl.col("symbol") == symbol).iter_rows(named=True)
    }
    rows: list[dict[str, str]] = []
    for day in dates:
        if day in zero_dates:
            rows.append(
                {
                    "date": day.isoformat(),
                    "code": code,
                    "open": "",
                    "high": "",
                    "low": "",
                    "close": "",
                    "volume": "",
                    "amount": "",
                    "adjustflag": "3",
                    "tradestatus": "0",
                }
            )
            continue
        bar = bars_index[day]
        rows.append(
            {
                "date": day.isoformat(),
                "code": code,
                "open": _num(bar["open"]),
                "high": _num(bar["high"]),
                "low": _num(bar["low"]),
                "close": _num(bar["close"]),
                "volume": _num(bar["volume"]),
                "amount": "1000000.0",
                "adjustflag": "3",
                "tradestatus": "1",
            }
        )
    return rows


def _sample_dates_by_symbol(sample_plan: CrossSourceSamplePlan) -> dict[str, list[dt.date]]:
    out: dict[str, list[dt.date]] = {}
    for symbol, day in sample_plan.keys:
        out.setdefault(symbol, []).append(day)
    for symbol in out:
        out[symbol].sort()
    return out


def _perfect_reference_responses(
    candidate: G1Candidate,
    sample_plan: CrossSourceSamplePlan,
    request_plan: ReferenceRequestPlanV1,
) -> tuple[VerifiedReferenceResponse, ...]:
    by_symbol = _sample_dates_by_symbol(sample_plan)
    responses = []
    for spec in request_plan.requests:
        rows = _reference_rows_for_symbol(candidate, spec.symbol, by_symbol[spec.symbol])
        responses.append(_make_verified_reference(spec, _reference_frame(rows)))
    return tuple(responses)


def _bundle_with_n_mismatches(
    candidate: G1Candidate,
    sample_plan: CrossSourceSamplePlan,
    request_plan: ReferenceRequestPlanV1,
    policy: G1CrossSourcePolicy,
    n: int,
) -> Any:
    by_symbol = _sample_dates_by_symbol(sample_plan)
    responses = list(_perfect_reference_responses(candidate, sample_plan, request_plan))
    remaining = n
    for index, spec in enumerate(request_plan.requests):
        if remaining <= 0:
            break
        dates = by_symbol[spec.symbol]
        rows = _reference_rows_for_symbol(candidate, spec.symbol, dates)
        changed = False
        for row in rows:
            if remaining <= 0:
                break
            row["close"] = _num(float(row["close"]) + 1.0)
            remaining -= 1
            changed = True
        if changed:
            responses[index] = _make_verified_reference(spec, _reference_frame(rows))
    assert remaining == 0
    return reconcile_cross_source(
        candidate=candidate,
        sample_plan=sample_plan,
        reference_responses=tuple(responses),
        policy=policy,
    )


# ---------------------------------------------------------------------------
# Fake BaoStock client for journal/executor tests (no real network).
# ---------------------------------------------------------------------------


class _Response:
    def __init__(
        self, *, fields: list[str] | None = None, rows: list[list[str]] | None = None,
        error_code: str = "0", error_msg: str = "ok",
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


class _JournalFakeClient:
    def __init__(self, *, login_error: bool = False, row_count: int = 1) -> None:
        self.login_error = login_error
        self.row_count = row_count
        self.logout_calls = 0
        self.calls: list[tuple[str, dict[str, str]]] = []
        self.fail_codes: set[str] = set()

    def login(self) -> _Response:
        if self.login_error:
            return _Response(error_code="1001", error_msg="login failed")
        return _Response()

    def logout(self) -> _Response:
        self.logout_calls += 1
        return _Response()

    def query_history_k_data_plus(self, code: str, fields: str, **kwargs: str) -> _Response:
        self.calls.append((code, dict(kwargs)))
        if code in self.fail_codes:
            raise RuntimeError("simulated network failure")
        names = fields.split(",")
        row = ["2016-02-01", code, "10.0", "10.0", "10.0", "10.0", "100.0", "1000000.0", "3", "1"]
        return _Response(fields=names, rows=[list(row) for _ in range(self.row_count)])


class _ExplodingClient:
    def login(self) -> _Response:
        raise AssertionError("network must not be touched")

    def logout(self) -> _Response:
        raise AssertionError("network must not be touched")

    def query_history_k_data_plus(self, *args: Any, **kwargs: Any) -> _Response:
        raise AssertionError("network must not be touched")


# ===========================================================================
# 1. Policy: bool/int/NaN/Inf/bounds
# ===========================================================================


@pytest.mark.parametrize(
    "overrides",
    [
        {"reference_source": "tushare"},
        {"reference_source": "BAOSTOCK"},
        {"sample_symbols": 31},
        {"sample_symbols": True},
        {"sample_symbols": 30.0},
        {"dates_per_symbol": 19},
        {"dates_per_symbol": False},
        {"price_atol": -0.001},
        {"price_atol": float("nan")},
        {"price_atol": float("inf")},
        {"price_atol": 1},
        {"price_atol": True},
        {"price_rtol": -0.1},
        {"price_rtol": 1.1},
        {"price_rtol": float("nan")},
        {"price_rtol": float("inf")},
        {"price_rtol": 1},
        {"price_rtol": False},
        {"volume_rtol": -0.1},
        {"volume_rtol": 1.1},
        {"volume_rtol": float("nan")},
        {"volume_rtol": float("inf")},
        {"max_mismatch_rate": -0.1},
        {"max_mismatch_rate": 1.1},
        {"max_mismatch_rate": float("nan")},
        {"max_mismatch_rate": float("inf")},
    ],
)
def test_policy_rejects_illegal_values(overrides: dict[str, Any]) -> None:
    kwargs = _base_policy_kwargs()
    kwargs.update(overrides)
    with pytest.raises(ValueError):
        G1CrossSourcePolicy(**kwargs)


def test_policy_accepts_boundary_values() -> None:
    policy = G1CrossSourcePolicy(
        reference_source="baostock",
        sample_symbols=30,
        dates_per_symbol=20,
        price_atol=0.0,
        price_rtol=0.0,
        volume_rtol=1.0,
        max_mismatch_rate=1.0,
    )
    assert policy.price_atol == 0.0
    assert policy.max_mismatch_rate == 1.0


# ===========================================================================
# 2. Sample plan: audit fail, <30 symbols, hash order stable, <20 dates
# ===========================================================================


def test_happy_candidate_audit_passes(happy_candidate: G1Candidate) -> None:
    audit = audit_g1_candidate(candidate=happy_candidate)
    assert audit.passed is True
    assert audit.issues == ()


def test_sample_plan_has_exact_shape_and_is_deterministic(
    happy_candidate: G1Candidate, sample_plan: CrossSourceSamplePlan
) -> None:
    assert sample_plan.sample_symbols == 30
    assert sample_plan.dates_per_symbol == 20
    assert len(sample_plan.keys) == 600
    by_symbol: dict[str, list[dt.date]] = {}
    for symbol, day in sample_plan.keys:
        by_symbol.setdefault(symbol, []).append(day)
    assert len(by_symbol) == 30
    assert all(len(days) == 20 for days in by_symbol.values())
    assert sample_plan.keys == tuple(sorted(sample_plan.keys))

    again = plan_cross_source_reconciliation(candidate=happy_candidate, policy=_policy())
    assert again == sample_plan


def test_sample_plan_rejects_non_candidate_type() -> None:
    with pytest.raises(M3ReferenceError) as excinfo:
        plan_cross_source_reconciliation(candidate="not-a-candidate", policy=_policy())  # type: ignore[arg-type]
    assert excinfo.value.code == "G1_REFERENCE_INPUT_INVALID"


def test_sample_plan_rejects_bad_policy_type(happy_candidate: G1Candidate) -> None:
    with pytest.raises(M3ReferenceError) as excinfo:
        plan_cross_source_reconciliation(candidate=happy_candidate, policy="bad")  # type: ignore[arg-type]
    assert excinfo.value.code == "G1_REFERENCE_INPUT_INVALID"


def test_sample_plan_rejects_failed_audit(happy_candidate: G1Candidate) -> None:
    symbol = happy_candidate.eligible_keys["symbol"][0]
    bars = happy_candidate.bars.filter(
        ~((pl.col("symbol") == symbol) & (pl.col("trade_date") == _D0))
    )
    damaged = _rebind_identity(happy_candidate, bars=bars)
    assert audit_g1_candidate(candidate=damaged).passed is False
    with pytest.raises(M3ReferenceError) as excinfo:
        plan_cross_source_reconciliation(candidate=damaged, policy=_policy())
    assert excinfo.value.code == "G1_REFERENCE_INPUT_INVALID"


def test_sample_plan_rejects_fewer_than_30_symbols(happy_candidate: G1Candidate) -> None:
    keep = sorted(happy_candidate.instruments.get_column("symbol").to_list())[:10]
    damaged = _restrict_bar_symbols(happy_candidate, keep)
    assert audit_g1_candidate(candidate=damaged).passed is True
    with pytest.raises(M3ReferenceError) as excinfo:
        plan_cross_source_reconciliation(candidate=damaged, policy=_policy())
    assert excinfo.value.code == "G1_REFERENCE_PLAN_INVALID"


def test_sample_plan_rejects_selected_symbol_with_fewer_than_20_dates(
    happy_candidate: G1Candidate,
) -> None:
    keep = sorted(happy_candidate.instruments.get_column("symbol").to_list())[:30]
    damaged = _restrict_bar_symbols(happy_candidate, keep, short_symbol=keep[0], short_keep=5)
    assert audit_g1_candidate(candidate=damaged).passed is True
    with pytest.raises(M3ReferenceError) as excinfo:
        plan_cross_source_reconciliation(candidate=damaged, policy=_policy())
    assert excinfo.value.code == "G1_REFERENCE_PLAN_INVALID"


def test_sample_plan_constructor_rejects_drift(sample_plan: CrossSourceSamplePlan) -> None:
    with pytest.raises(ValueError):
        replace(sample_plan, keys=sample_plan.keys[:-1])
    with pytest.raises(ValueError):
        replace(sample_plan, keys=tuple(reversed(sample_plan.keys)))
    with pytest.raises(ValueError):
        replace(sample_plan, sample_plan_sha256="0" * 64)
    with pytest.raises(ValueError):
        replace(sample_plan, primary_candidate_key="not-hex")
    with pytest.raises(ValueError):
        replace(sample_plan, sample_symbols=29)


# ===========================================================================
# 3. Request plan/spec: parameters drift, symbol derivation, sorting
# ===========================================================================


def test_request_plan_matches_sample_and_symbol_derivation(
    sample_plan: CrossSourceSamplePlan, request_plan: ReferenceRequestPlanV1
) -> None:
    assert len(request_plan.requests) == 30
    assert request_plan.sample_plan_sha256 == sample_plan.sample_plan_sha256
    assert [spec.request_id for spec in request_plan.requests] == sorted(
        spec.request_id for spec in request_plan.requests
    )
    symbols = {spec.symbol for spec in request_plan.requests}
    assert len(symbols) == 30
    by_symbol_dates = _sample_dates_by_symbol(sample_plan)
    for spec in request_plan.requests:
        params = dict(spec.parameters)
        assert set(params) == {"fields", "frequency", "adjustflag", "start_date", "end_date"}
        assert params["fields"] == ref._FIELDS
        assert params["frequency"] == "d"
        assert params["adjustflag"] == "3"
        days = by_symbol_dates[spec.symbol]
        assert params["start_date"] == days[0].isoformat()
        assert params["end_date"] == days[-1].isoformat()
        assert "symbol" not in params
        assert "code" not in params


def test_request_plan_rejects_bad_sample_plan_type() -> None:
    with pytest.raises(M3ReferenceError) as excinfo:
        plan_baostock_reference_requests(sample_plan="not-a-plan")  # type: ignore[arg-type]
    assert excinfo.value.code == "G1_REFERENCE_INPUT_INVALID"


def test_request_spec_constructor_rejects_drift(request_plan: ReferenceRequestPlanV1) -> None:
    spec = request_plan.requests[0]
    with pytest.raises(ValueError):
        replace(spec, endpoint="query_history_k_data")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        replace(spec, symbol="000001.BJ")
    with pytest.raises(ValueError):
        replace(spec, request_id="0" * 64)
    params = dict(spec.parameters)
    with pytest.raises(ValueError):
        replace(spec, parameters=tuple(sorted({**params, "extra": "x"}.items())))
    with pytest.raises(ValueError):
        replace(
            spec,
            parameters=tuple(sorted({k: v for k, v in params.items() if k != "fields"}.items())),
        )
    with pytest.raises(ValueError):
        replace(spec, parameters=tuple(sorted({**params, "adjustflag": "1"}.items())))
    with pytest.raises(ValueError):
        replace(spec, parameters=tuple(sorted({**params, "frequency": "w"}.items())))
    swapped = {**params, "start_date": params["end_date"], "end_date": params["start_date"]}
    with pytest.raises(ValueError):
        replace(spec, parameters=tuple(sorted(swapped.items())))


def test_request_plan_constructor_rejects_drift(request_plan: ReferenceRequestPlanV1) -> None:
    with pytest.raises(ValueError):
        replace(request_plan, requests=request_plan.requests[:-1])
    with pytest.raises(ValueError):
        replace(request_plan, requests=tuple(reversed(request_plan.requests)))
    with pytest.raises(ValueError):
        replace(request_plan, requests=request_plan.requests + (request_plan.requests[0],))
    with pytest.raises(ValueError):
        replace(request_plan, request_plan_sha256="0" * 64)
    with pytest.raises(ValueError):
        replace(request_plan, sample_plan_sha256="1" * 64)


def test_intent_constructor_rejects_drift(request_plan: ReferenceRequestPlanV1) -> None:
    spec = request_plan.requests[0]
    intent = ReferenceRequestIntentV1(
        "m3-g1-baostock-intent-v1", spec.request_id, spec.endpoint, spec.symbol,
        spec.parameters, ref._parameters_hash(spec.parameters),
    )
    with pytest.raises(ValueError):
        replace(intent, parameters_sha256="0" * 64)
    with pytest.raises(ValueError):
        replace(intent, symbol="000002.SZ")


def _sample_reference_frame(spec: ReferenceRequestSpec, day: dt.date) -> pl.DataFrame:
    code = ref._symbol_to_baostock_code(spec.symbol)
    row = {
        "date": day.isoformat(), "code": code, "open": "10.0", "high": "10.0", "low": "10.0",
        "close": "10.0", "volume": "1.0", "amount": "1.0", "adjustflag": "3", "tradestatus": "1",
    }
    return _reference_frame([row])


def test_candidate_constructor_rejects_drift(request_plan: ReferenceRequestPlanV1) -> None:
    spec = request_plan.requests[0]
    frame = _sample_reference_frame(spec, dt.date.fromisoformat(dict(spec.parameters)["start_date"]))
    content = ref._reference_response_content_sha256(frame)
    candidate = ReferenceRawCandidateV1(
        "m3-g1-baostock-candidate-v1", spec.request_id, spec.endpoint, spec.symbol,
        ref._parameters_hash(spec.parameters), spec.request_id,
        f"baostock/query_history_k_data_plus/request={spec.request_id}/data.parquet",
        f"baostock/query_history_k_data_plus/request={spec.request_id}/metadata.json",
        _HEX, _HEX, content, 1, frame.height, tuple(frame.columns),
    )
    with pytest.raises(ValueError):
        replace(candidate, raw_snapshot_id="0" * 64)
    with pytest.raises(ValueError):
        replace(candidate, raw_data_path="/abs/data.parquet")
    with pytest.raises(ValueError):
        replace(candidate, raw_data_path="../escape/data.parquet")
    with pytest.raises(ValueError):
        replace(candidate, raw_data_path="a\\b\\data.parquet")
    with pytest.raises(ValueError):
        replace(candidate, columns=("date", "code"))
    with pytest.raises(ValueError):
        replace(candidate, raw_size_bytes=-1)


def test_receipt_constructor_rejects_drift(request_plan: ReferenceRequestPlanV1) -> None:
    spec = request_plan.requests[0]
    frame = _sample_reference_frame(spec, dt.date.fromisoformat(dict(spec.parameters)["start_date"]))
    updated = _make_verified_reference(spec, frame)
    receipt = updated.receipt
    with pytest.raises(ValueError):
        replace(receipt, stable_response_sha256="0" * 64)
    with pytest.raises(ValueError):
        replace(receipt, parameters_sha256="0" * 64)
    with pytest.raises(ValueError):
        replace(receipt, raw_snapshot_id="0" * 64)
    with pytest.raises(ValueError):
        replace(receipt, columns=("date",))


def test_verified_reference_constructor_rejects_drift(request_plan: ReferenceRequestPlanV1) -> None:
    spec = request_plan.requests[0]
    frame = _sample_reference_frame(spec, dt.date.fromisoformat(dict(spec.parameters)["start_date"]))
    verified = _make_verified_reference(spec, frame)
    with pytest.raises(ValueError):
        VerifiedReferenceResponse(verified.spec, verified.receipt, "0" * 64, verified.frame)
    changed = verified.frame.with_columns(pl.lit("999.0").alias("close"))
    with pytest.raises(ValueError):
        VerifiedReferenceResponse(verified.spec, verified.receipt, verified.receipt_sha256, changed)
    with pytest.raises(ValueError):
        VerifiedReferenceResponse(
            verified.spec, verified.receipt, verified.receipt_sha256, "not-a-frame"  # type: ignore[arg-type]
        )


# ===========================================================================
# 4/5/6. Executor: plan-wide preflight, journal state machine, strict JSON
# ===========================================================================


def test_executor_happy_path_produces_30_sorted_receipts(
    sample_plan: CrossSourceSamplePlan, request_plan: ReferenceRequestPlanV1, tmp_path: Path,
) -> None:
    client = _JournalFakeClient()
    receipts = execute_baostock_reference_plan(
        sample_plan=sample_plan, plan=request_plan, connector=BaostockConnector(client),
        raw_store=RawStore(tmp_path / "raw"), journal_root=tmp_path / "journal",
    )
    assert len(receipts) == 30
    assert [item.request_id for item in receipts] == sorted(item.request_id for item in receipts)
    assert {item.request_id for item in receipts} == {
        spec.request_id for spec in request_plan.requests
    }
    assert client.logout_calls == 30
    assert len(client.calls) == 30
    lock_path = tmp_path / "journal" / ".writer.lock"
    assert lock_path.is_file()
    assert os.lstat(lock_path).st_nlink == 1


def test_executor_stale_lock_file_allows_repeat_run(
    sample_plan: CrossSourceSamplePlan, request_plan: ReferenceRequestPlanV1, tmp_path: Path,
) -> None:
    journal = tmp_path / "journal"
    journal.mkdir()
    lock_path = journal / ".writer.lock"
    lock_path.write_bytes(b"stale-nonempty")
    first = execute_baostock_reference_plan(
        sample_plan=sample_plan, plan=request_plan, connector=BaostockConnector(_JournalFakeClient()),
        raw_store=RawStore(tmp_path / "raw"), journal_root=journal,
    )
    second = execute_baostock_reference_plan(
        sample_plan=sample_plan, plan=request_plan, connector=BaostockConnector(_JournalFakeClient()),
        raw_store=RawStore(tmp_path / "raw"), journal_root=journal,
    )
    assert [item.request_id for item in first] == [item.request_id for item in second]
    for item in first:
        payload = (journal / item.request_id / "receipt.json").read_bytes()
        assert payload == (journal / item.request_id / "receipt.json").read_bytes()
    assert lock_path.exists()


# ===========================================================================
# XP0-R2: honest cross-platform publish / failure recovery (no Windows no-op)
# ===========================================================================


def _simple_intent(
    *,
    symbol: str = "000001.SZ",
    start_date: str = "2016-02-01",
    end_date: str = "2016-02-01",
) -> tuple[ReferenceRequestSpec, ReferenceRequestIntentV1]:
    params = (
        ("adjustflag", "3"),
        ("end_date", end_date),
        ("fields", ref._FIELDS),
        ("frequency", "d"),
        ("start_date", start_date),
    )
    rid = ref._request_id(symbol=symbol, parameters=params)
    spec = ReferenceRequestSpec(
        "m3-g1-baostock-request-v1", rid, "query_history_k_data_plus", symbol, params,
    )
    intent = ReferenceRequestIntentV1(
        "m3-g1-baostock-intent-v1",
        spec.request_id,
        spec.endpoint,
        spec.symbol,
        spec.parameters,
        ref._parameters_hash(spec.parameters),
    )
    return spec, intent


def test_fsync_directory_and_write_dataclass_once_without_monkeypatch(tmp_path: Path) -> None:
    """Product path must run on both platforms without replacing ``_fsync_directory``."""
    ref._fsync_directory(tmp_path)
    _spec, intent = _simple_intent()
    target = tmp_path / "intent.json"
    ref._write_dataclass_once(target, intent)
    assert target.is_file()
    expected = ref._canonical_json(asdict(intent)).encode("utf-8")
    assert target.read_bytes() == expected
    assert ref._strict_json(target.read_bytes())["request_id"] == intent.request_id
    leftovers = list(tmp_path.glob(".intent.json.*.tmp"))
    assert leftovers == []


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX directory fsync contract")
def test_linux_fsync_directory_invokes_open_fsync_close(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[Any] = []
    real_open, real_fsync, real_close = os.open, os.fsync, os.close

    def spy_open(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        calls.append(("open", path, flags))
        return real_open(path, flags, *args, **kwargs)

    def spy_fsync(fd: int) -> None:
        calls.append(("fsync", fd))
        real_fsync(fd)

    def spy_close(fd: int) -> None:
        calls.append(("close", fd))
        real_close(fd)

    monkeypatch.setattr(os, "open", spy_open)
    monkeypatch.setattr(os, "fsync", spy_fsync)
    monkeypatch.setattr(os, "close", spy_close)
    ref._fsync_directory(tmp_path)
    kinds = [item[0] for item in calls]
    assert kinds == ["open", "fsync", "close"]
    assert calls[0][2] == os.O_RDONLY


def test_write_dataclass_once_file_fsync_failure_leaves_no_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _spec, intent = _simple_intent()
    target = tmp_path / "intent.json"

    def boom_fsync(fd: int) -> None:
        raise OSError(5, "injected file fsync failure")

    monkeypatch.setattr(os, "fsync", boom_fsync)
    with pytest.raises(M3ReferenceError) as caught:
        ref._write_dataclass_once(target, intent)
    assert caught.value.code == "G1_REFERENCE_IO_FAILED"
    assert not target.exists()
    assert list(tmp_path.glob(".intent.json.*.tmp")) == []


def test_write_dataclass_once_link_file_exists_is_journal_invalid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _spec, intent = _simple_intent()
    target = tmp_path / "intent.json"
    target.write_bytes(b"preexisting")
    with pytest.raises(M3ReferenceError) as caught:
        ref._write_dataclass_once(target, intent)
    assert caught.value.code == "G1_REFERENCE_JOURNAL_INVALID"
    assert target.read_bytes() == b"preexisting"
    assert list(tmp_path.glob(".intent.json.*.tmp")) == []


def test_write_dataclass_once_link_oserror_is_io_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _spec, intent = _simple_intent()
    target = tmp_path / "intent.json"

    def boom_link(src: str | bytes, dst: str | bytes) -> None:
        raise OSError(1, "injected link failure")

    monkeypatch.setattr(os, "link", boom_link)
    with pytest.raises(M3ReferenceError) as caught:
        ref._write_dataclass_once(target, intent)
    assert caught.value.code == "G1_REFERENCE_IO_FAILED"
    assert not target.exists()
    assert list(tmp_path.glob(".intent.json.*.tmp")) == []


def test_write_dataclass_once_dir_fsync_fail_after_link_is_recoverable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Complete hardlinked target retained after directory persist confirmation failure."""
    spec, intent = _simple_intent()
    target = tmp_path / "intent.json"
    expected = ref._canonical_json(asdict(intent)).encode("utf-8")

    def boom_dir(_directory: Path) -> None:
        raise OSError(5, "injected directory fsync failure")

    monkeypatch.setattr(ref, "_fsync_directory", boom_dir)
    with pytest.raises(M3ReferenceError) as caught:
        ref._write_dataclass_once(target, intent)
    assert caught.value.code == "G1_REFERENCE_IO_FAILED"
    assert target.is_file()
    assert target.read_bytes() == expected
    assert list(tmp_path.glob(".intent.json.*.tmp")) == []

    # Same-spec retry recovers via existing intent verification (not re-publish).
    ref._ensure_intent(target, spec)

    other_spec, _other = _simple_intent(symbol="000002.SZ")
    with pytest.raises(M3ReferenceError) as mismatch:
        ref._ensure_intent(target, other_spec)
    assert mismatch.value.code == "G1_REFERENCE_JOURNAL_INVALID"

    target.write_bytes(b'{"schema_version":"corrupt"}')
    with pytest.raises(M3ReferenceError) as corrupt:
        ref._ensure_intent(target, spec)
    assert corrupt.value.code == "G1_REFERENCE_JOURNAL_INVALID"


def test_executor_active_flock_and_sigkill_recovery(
    sample_plan: CrossSourceSamplePlan, request_plan: ReferenceRequestPlanV1, tmp_path: Path,
) -> None:
    import subprocess
    import sys
    import textwrap
    import time

    from quant.data._journal_lock import hold_journal_writer_lock

    journal = (tmp_path / "journal").resolve()
    journal.mkdir()
    with hold_journal_writer_lock(journal_root=journal):
        client = _JournalFakeClient()
        with pytest.raises(M3ReferenceError) as held:
            execute_baostock_reference_plan(
                sample_plan=sample_plan, plan=request_plan, connector=BaostockConnector(client),
                raw_store=RawStore(tmp_path / "raw"), journal_root=journal,
            )
        assert held.value.code == "G1_REFERENCE_JOURNAL_INVALID"
        assert client.calls == []

    ready = tmp_path / "ready"
    script = textwrap.dedent(
        f"""
        import sys, time
        from pathlib import Path
        sys.path.insert(0, {str(Path(__file__).resolve().parents[2] / "src")!r})
        from quant.data._journal_lock import hold_journal_writer_lock
        with hold_journal_writer_lock(journal_root=Path({str(journal)!r})):
            Path({str(ready)!r}).write_text("1", encoding="utf-8")
            time.sleep(60)
        """
    )
    child = subprocess.Popen([sys.executable, "-c", script])
    try:
        # Windows cold import of quant.lock stack often exceeds 2s; match journal_lock budget.
        for _ in range(1000):
            if ready.exists():
                break
            time.sleep(0.01)
        assert ready.exists(), (
            f"holder subprocess did not signal ready; poll={child.poll()}"
        )
        blocked = _JournalFakeClient()
        with pytest.raises(M3ReferenceError) as active:
            execute_baostock_reference_plan(
                sample_plan=sample_plan, plan=request_plan, connector=BaostockConnector(blocked),
                raw_store=RawStore(tmp_path / "raw2"), journal_root=journal,
            )
        assert active.value.code == "G1_REFERENCE_JOURNAL_INVALID"
        assert blocked.calls == []
        child.kill()
        child.wait(timeout=5)
        receipts = execute_baostock_reference_plan(
            sample_plan=sample_plan, plan=request_plan,
            connector=BaostockConnector(_JournalFakeClient()),
            raw_store=RawStore(tmp_path / "raw3"), journal_root=journal,
        )
        assert len(receipts) == 30
        assert (journal / ".writer.lock").exists()
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)


def test_executor_rejects_forged_plan_with_same_sample_hash_zero_io(
    sample_plan: CrossSourceSamplePlan, request_plan: ReferenceRequestPlanV1, tmp_path: Path,
) -> None:
    """Sample-hash-only equality must not bypass full-plan closure comparison."""
    specs = list(request_plan.requests)
    idx_a, idx_b = 0, 1
    for i in range(len(specs)):
        for j in range(i + 1, len(specs)):
            if dict(specs[i].parameters) != dict(specs[j].parameters):
                idx_a, idx_b = i, j
                break
        else:
            continue
        break
    params_a, params_b = dict(specs[idx_a].parameters), dict(specs[idx_b].parameters)
    assert params_a != params_b
    swapped_a = ReferenceRequestSpec(
        specs[idx_a].schema_version,
        ref._request_id(symbol=specs[idx_a].symbol, parameters=tuple(sorted(params_b.items()))),
        specs[idx_a].endpoint, specs[idx_a].symbol, tuple(sorted(params_b.items())),
    )
    swapped_b = ReferenceRequestSpec(
        specs[idx_b].schema_version,
        ref._request_id(symbol=specs[idx_b].symbol, parameters=tuple(sorted(params_a.items()))),
        specs[idx_b].endpoint, specs[idx_b].symbol, tuple(sorted(params_a.items())),
    )
    untouched = [spec for k, spec in enumerate(specs) if k not in {idx_a, idx_b}]
    new_specs = tuple(sorted([swapped_a, swapped_b, *untouched], key=lambda item: item.request_id))
    forged_hash = ref._request_plan_sha256(
        sample_plan_sha256=request_plan.sample_plan_sha256, requests=new_specs
    )
    forged_plan = ReferenceRequestPlanV1(
        request_plan.schema_version, request_plan.sample_plan_sha256, new_specs, forged_hash,
    )
    assert forged_plan.requests != request_plan.requests

    journal_root = tmp_path / "journal"
    raw_root = tmp_path / "raw"
    client = _JournalFakeClient()
    with pytest.raises(M3ReferenceError) as excinfo:
        execute_baostock_reference_plan(
            sample_plan=sample_plan, plan=forged_plan, connector=BaostockConnector(client),
            raw_store=RawStore(raw_root), journal_root=journal_root,
        )
    assert excinfo.value.code == "G1_REFERENCE_PLAN_INVALID"
    assert client.calls == []
    assert not journal_root.exists()
    assert not raw_root.exists()


def test_executor_rejects_request_plan_from_different_sample_plan_zero_io(
    happy_candidate: G1Candidate, sample_plan: CrossSourceSamplePlan, tmp_path: Path,
) -> None:
    keep = sorted(happy_candidate.instruments.get_column("symbol").to_list())[-30:]
    other_candidate = _restrict_bar_symbols(happy_candidate, keep)
    other_sample_plan = plan_cross_source_reconciliation(candidate=other_candidate, policy=_policy())
    other_request_plan = plan_baostock_reference_requests(sample_plan=other_sample_plan)
    assert other_sample_plan.sample_plan_sha256 != sample_plan.sample_plan_sha256

    journal_root = tmp_path / "journal"
    raw_root = tmp_path / "raw"
    client = _JournalFakeClient()
    with pytest.raises(M3ReferenceError) as excinfo:
        execute_baostock_reference_plan(
            sample_plan=sample_plan, plan=other_request_plan, connector=BaostockConnector(client),
            raw_store=RawStore(raw_root), journal_root=journal_root,
        )
    assert excinfo.value.code == "G1_REFERENCE_PLAN_INVALID"
    assert client.calls == []
    assert not journal_root.exists()


def test_executor_plan_wide_preflight_conflict_blocks_all_requests_before_any_io(
    sample_plan: CrossSourceSamplePlan, request_plan: ReferenceRequestPlanV1, tmp_path: Path,
) -> None:
    journal_root = tmp_path / "journal"
    target = request_plan.requests[-1]
    conflict_dir = journal_root / target.request_id
    conflict_dir.mkdir(parents=True)
    (conflict_dir / "unexpected.txt").write_text("x", encoding="utf-8")

    client = _JournalFakeClient()
    with pytest.raises(M3ReferenceError) as excinfo:
        execute_baostock_reference_plan(
            sample_plan=sample_plan, plan=request_plan, connector=BaostockConnector(client),
            raw_store=RawStore(tmp_path / "raw"), journal_root=journal_root,
        )
    assert excinfo.value.code == "G1_REFERENCE_JOURNAL_INVALID"
    assert client.calls == []
    for spec in request_plan.requests:
        if spec.request_id == target.request_id:
            continue
        assert not (journal_root / spec.request_id / "intent.json").exists()
    assert not (tmp_path / "raw").exists()


@pytest.mark.parametrize(
    "layout",
    ["request_is_file", "request_symlink", "unknown_file_symlink", "unknown_directory", "fifo"],
)
def test_executor_journal_layout_is_strictly_checked_before_network(
    sample_plan: CrossSourceSamplePlan, request_plan: ReferenceRequestPlanV1, tmp_path: Path, layout: str,
) -> None:
    journal_root = tmp_path / "journal"
    journal_root.mkdir(parents=True)
    target = request_plan.requests[0]
    request_dir = journal_root / target.request_id
    outside = tmp_path / "outside"
    if layout == "request_is_file":
        request_dir.write_text("not-a-dir", encoding="utf-8")
    elif layout == "request_symlink":
        outside.mkdir()
        _require_symlink(request_dir, outside, target_is_directory=True)
    else:
        request_dir.mkdir()
        entry = request_dir / "extra"
        if layout == "unknown_file_symlink":
            outside.write_text("x", encoding="utf-8")
            _require_symlink(entry, outside)
        elif layout == "unknown_directory":
            entry.mkdir()
        else:
            _require_fifo(entry)

    client = _JournalFakeClient()
    with pytest.raises(M3ReferenceError) as excinfo:
        execute_baostock_reference_plan(
            sample_plan=sample_plan, plan=request_plan, connector=BaostockConnector(client),
            raw_store=RawStore(tmp_path / "raw"), journal_root=journal_root,
        )
    assert excinfo.value.code == "G1_REFERENCE_JOURNAL_INVALID"
    assert client.calls == []


def test_executor_journal_state_machine_full_lifecycle(
    sample_plan: CrossSourceSamplePlan, request_plan: ReferenceRequestPlanV1, tmp_path: Path,
) -> None:
    journal_root = tmp_path / "journal"
    raw_root = tmp_path / "raw"

    first_client = _JournalFakeClient()
    first_receipts = execute_baostock_reference_plan(
        sample_plan=sample_plan, plan=request_plan, connector=BaostockConnector(first_client),
        raw_store=RawStore(raw_root), journal_root=journal_root,
    )
    assert len(first_receipts) == 30
    assert len(first_client.calls) == 30

    # Full receipt replay: zero network for every request.
    replay_receipts = execute_baostock_reference_plan(
        sample_plan=sample_plan, plan=request_plan, connector=BaostockConnector(_ExplodingClient()),
        raw_store=RawStore(raw_root), journal_root=journal_root,
    )
    assert replay_receipts == first_receipts

    # Candidate recovery: delete only receipts, keep intent+candidate+raw.
    for spec in request_plan.requests:
        (journal_root / spec.request_id / "receipt.json").unlink()
    recover_receipts = execute_baostock_reference_plan(
        sample_plan=sample_plan, plan=request_plan, connector=BaostockConnector(_ExplodingClient()),
        raw_store=RawStore(raw_root), journal_root=journal_root,
    )
    assert recover_receipts == first_receipts
    for spec in request_plan.requests:
        assert (journal_root / spec.request_id / "receipt.json").exists()

    # Network failure mid-plan keeps earlier commits and the failing intent,
    # and a later retry resumes only the unfinished requests.
    fresh_journal = tmp_path / "journal2"
    fresh_raw = tmp_path / "raw2"
    failing_target = request_plan.requests[5]
    failing_client = _JournalFakeClient()
    failing_client.fail_codes = {ref._symbol_to_baostock_code(failing_target.symbol)}
    with pytest.raises(M3ReferenceError) as excinfo:
        execute_baostock_reference_plan(
            sample_plan=sample_plan, plan=request_plan, connector=BaostockConnector(failing_client),
            raw_store=RawStore(fresh_raw), journal_root=fresh_journal,
        )
    assert excinfo.value.code == "G1_REFERENCE_NETWORK_FAILED"
    for spec in request_plan.requests[:5]:
        assert (fresh_journal / spec.request_id / "receipt.json").exists()
    failed_dir = fresh_journal / failing_target.request_id
    assert (failed_dir / "intent.json").exists()
    assert not (failed_dir / "candidate.json").exists()
    assert not (failed_dir / "receipt.json").exists()
    for spec in request_plan.requests[6:]:
        assert not (fresh_journal / spec.request_id).exists()

    retry_client = _JournalFakeClient()
    retry_receipts = execute_baostock_reference_plan(
        sample_plan=sample_plan, plan=request_plan, connector=BaostockConnector(retry_client),
        raw_store=RawStore(fresh_raw), journal_root=fresh_journal,
    )
    assert len(retry_receipts) == 30
    assert len(retry_client.calls) == 25


def test_executor_detects_candidate_raw_and_receipt_drift(
    sample_plan: CrossSourceSamplePlan, request_plan: ReferenceRequestPlanV1, tmp_path: Path,
) -> None:
    journal_root = tmp_path / "journal"
    raw_root = tmp_path / "raw"
    execute_baostock_reference_plan(
        sample_plan=sample_plan, plan=request_plan, connector=BaostockConnector(_JournalFakeClient()),
        raw_store=RawStore(raw_root), journal_root=journal_root,
    )
    target = request_plan.requests[0]
    receipt_path = journal_root / target.request_id / "receipt.json"

    original = receipt_path.read_bytes()
    payload = json.loads(original)
    payload["row_count"] = payload["row_count"] + 1
    receipt_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(M3ReferenceError):
        execute_baostock_reference_plan(
            sample_plan=sample_plan, plan=request_plan,
            connector=BaostockConnector(_ExplodingClient()),
            raw_store=RawStore(raw_root), journal_root=journal_root,
        )
    receipt_path.write_bytes(original)

    data_path, _metadata_path = RawStore(raw_root).request_paths(
        source="baostock", table="query_history_k_data_plus", request_id=target.request_id,
    )
    original_raw = data_path.read_bytes()
    data_path.write_bytes(b"corrupted-bytes")
    with pytest.raises(M3ReferenceError):
        execute_baostock_reference_plan(
            sample_plan=sample_plan, plan=request_plan,
            connector=BaostockConnector(_ExplodingClient()),
            raw_store=RawStore(raw_root), journal_root=journal_root,
        )
    data_path.write_bytes(original_raw)


def test_no_replace_or_rename_used_in_reference_module() -> None:
    source = Path(ref.__file__).read_text(encoding="utf-8")
    assert "os.replace(" not in source
    assert "os.rename(" not in source


@pytest.mark.parametrize(
    "payload",
    [
        b'{"schema_version":"x","schema_version":"y"}',
        b"\xff\xfe",
        b'{"row_count":"1"}',
        b'{"unknown":1}',
        b'{"row_count":NaN}',
    ],
)
def test_verify_reference_receipt_rejects_strict_json_violations(
    sample_plan: CrossSourceSamplePlan, request_plan: ReferenceRequestPlanV1, tmp_path: Path,
    payload: bytes,
) -> None:
    journal_root = tmp_path / "journal"
    raw_root = tmp_path / "raw"
    execute_baostock_reference_plan(
        sample_plan=sample_plan, plan=request_plan, connector=BaostockConnector(_JournalFakeClient()),
        raw_store=RawStore(raw_root), journal_root=journal_root,
    )
    target = request_plan.requests[0]
    receipt_path = journal_root / target.request_id / "receipt.json"
    receipt_path.write_bytes(payload)
    with pytest.raises(M3ReferenceError) as excinfo:
        verify_reference_receipt(
            spec=target, receipt_path=receipt_path, raw_root=raw_root, journal_root=journal_root,
        )
    assert excinfo.value.code == "G1_REFERENCE_RECEIPT_INVALID"


def test_verify_reference_receipt_rejects_absolute_or_escaping_raw_path(
    sample_plan: CrossSourceSamplePlan, request_plan: ReferenceRequestPlanV1, tmp_path: Path,
) -> None:
    journal_root = tmp_path / "journal"
    raw_root = tmp_path / "raw"
    execute_baostock_reference_plan(
        sample_plan=sample_plan, plan=request_plan, connector=BaostockConnector(_JournalFakeClient()),
        raw_store=RawStore(raw_root), journal_root=journal_root,
    )
    target = request_plan.requests[0]
    receipt_path = journal_root / target.request_id / "receipt.json"
    original = receipt_path.read_bytes()
    payload = json.loads(original)
    for bad_path in ("/etc/passwd", "../escape/data.parquet", "a\\b\\data.parquet"):
        payload["raw_data_path"] = bad_path
        receipt_path.write_bytes(json.dumps(payload).encode("utf-8"))
        with pytest.raises(M3ReferenceError) as excinfo:
            verify_reference_receipt(
                spec=target, receipt_path=receipt_path, raw_root=raw_root, journal_root=journal_root,
            )
        assert excinfo.value.code == "G1_REFERENCE_RECEIPT_INVALID"
    receipt_path.write_bytes(original)


def test_verify_reference_receipt_rejects_raw_content_drift(
    sample_plan: CrossSourceSamplePlan, request_plan: ReferenceRequestPlanV1, tmp_path: Path,
) -> None:
    journal_root = tmp_path / "journal"
    raw_root = tmp_path / "raw"
    execute_baostock_reference_plan(
        sample_plan=sample_plan, plan=request_plan, connector=BaostockConnector(_JournalFakeClient()),
        raw_store=RawStore(raw_root), journal_root=journal_root,
    )
    target = request_plan.requests[0]
    data_path, _metadata_path = RawStore(raw_root).request_paths(
        source="baostock", table="query_history_k_data_plus", request_id=target.request_id,
    )
    original = data_path.read_bytes()
    frame = pl.read_parquet(data_path)
    tampered = frame.with_columns(pl.lit("999.0").alias("close"))
    buffer = io.BytesIO()
    tampered.write_parquet(buffer)
    data_path.write_bytes(buffer.getvalue())
    with pytest.raises(M3ReferenceError) as excinfo:
        verify_reference_receipt(
            spec=target,
            receipt_path=journal_root / target.request_id / "receipt.json",
            raw_root=raw_root, journal_root=journal_root,
        )
    assert excinfo.value.code == "G1_REFERENCE_RECEIPT_INVALID"
    data_path.write_bytes(original)


def test_validate_reference_frame_row_limit_boundaries() -> None:
    empty = pl.DataFrame(schema={c: pl.Utf8 for c in ref._FIELD_COLUMNS})
    ref._validate_reference_frame(empty)
    at_limit_minus_one = pl.DataFrame({c: ["x"] * 5999 for c in ref._FIELD_COLUMNS})
    ref._validate_reference_frame(at_limit_minus_one)
    at_limit = pl.DataFrame({c: ["x"] * 6000 for c in ref._FIELD_COLUMNS})
    with pytest.raises(M3ReferenceError) as excinfo:
        ref._validate_reference_frame(at_limit)
    assert excinfo.value.code == "G1_REFERENCE_RESPONSE_INVALID"


def test_executor_rejects_response_at_row_limit(
    sample_plan: CrossSourceSamplePlan, request_plan: ReferenceRequestPlanV1, tmp_path: Path,
) -> None:
    client = _JournalFakeClient(row_count=6000)
    with pytest.raises(M3ReferenceError) as excinfo:
        execute_baostock_reference_plan(
            sample_plan=sample_plan, plan=request_plan, connector=BaostockConnector(client),
            raw_store=RawStore(tmp_path / "raw"), journal_root=tmp_path / "journal",
        )
    assert excinfo.value.code == "G1_REFERENCE_RESPONSE_INVALID"


# ===========================================================================
# 7/8. reconcile_cross_source: sampling, tolerance, thresholds
# ===========================================================================


def test_reconcile_cross_source_happy_path_full_closure(
    happy_candidate: G1Candidate, sample_plan: CrossSourceSamplePlan, request_plan: ReferenceRequestPlanV1,
) -> None:
    responses = _perfect_reference_responses(happy_candidate, sample_plan, request_plan)
    bundle = reconcile_cross_source(
        candidate=happy_candidate, sample_plan=sample_plan, reference_responses=responses,
        policy=_policy(),
    )
    assert bundle.passed is True
    assert bundle.issues == ()
    assert bundle.detail.height == 3000
    assert bundle.summary.missing_primary_rows == 0
    assert bundle.summary.missing_reference_rows == 0
    assert bundle.summary.mismatch_cells == 0
    assert bundle.summary.mismatch_rate == 0.0
    assert len(bundle.reference_receipts) == 30
    assert bundle.summary.sample_symbol_count == 30
    assert bundle.summary.dates_per_symbol == 20
    assert bundle.summary.key_count == 600
    assert bundle.summary.field_count == 5
    assert bundle.summary.comparison_count == 3000
    for stats in bundle.summary.field_stats:
        assert stats.mismatch_count == 0
        assert stats.max_abs_diff == 0.0


def test_reconcile_ignores_extra_reference_dates_within_range(
    happy_candidate: G1Candidate, sample_plan: CrossSourceSamplePlan, request_plan: ReferenceRequestPlanV1,
) -> None:
    by_symbol = _sample_dates_by_symbol(sample_plan)
    bar_days_by_symbol: dict[str, set[dt.date]] = {}
    for row in happy_candidate.bars.iter_rows(named=True):
        bar_days_by_symbol.setdefault(row["symbol"], set()).add(row["trade_date"])
    target_spec, extra_day = None, None
    for spec in request_plan.requests:
        params = dict(spec.parameters)
        start = dt.date.fromisoformat(params["start_date"])
        end = dt.date.fromisoformat(params["end_date"])
        sampled = set(by_symbol[spec.symbol])
        candidates = sorted(
            day for day in bar_days_by_symbol[spec.symbol] if start <= day <= end and day not in sampled
        )
        if candidates:
            target_spec, extra_day = spec, candidates[0]
            break
    assert target_spec is not None and extra_day is not None

    responses = list(_perfect_reference_responses(happy_candidate, sample_plan, request_plan))
    rows = _reference_rows_for_symbol(
        happy_candidate, target_spec.symbol, by_symbol[target_spec.symbol] + [extra_day]
    )
    index = next(i for i, s in enumerate(request_plan.requests) if s.request_id == target_spec.request_id)
    responses[index] = _make_verified_reference(target_spec, _reference_frame(rows))

    bundle = reconcile_cross_source(
        candidate=happy_candidate, sample_plan=sample_plan, reference_responses=tuple(responses),
        policy=_policy(),
    )
    assert bundle.passed is True
    assert bundle.detail.height == 3000


def test_reconcile_missing_reference_row_produces_incomplete_only(
    happy_candidate: G1Candidate, sample_plan: CrossSourceSamplePlan, request_plan: ReferenceRequestPlanV1,
) -> None:
    by_symbol = _sample_dates_by_symbol(sample_plan)
    responses = list(_perfect_reference_responses(happy_candidate, sample_plan, request_plan))
    target_spec = request_plan.requests[0]
    remaining_days = by_symbol[target_spec.symbol][1:]
    rows = _reference_rows_for_symbol(happy_candidate, target_spec.symbol, remaining_days)
    responses[0] = _make_verified_reference(target_spec, _reference_frame(rows))

    bundle = reconcile_cross_source(
        candidate=happy_candidate, sample_plan=sample_plan, reference_responses=tuple(responses),
        policy=_policy(max_mismatch_rate=0.01),
    )
    assert bundle.passed is False
    assert {issue.code for issue in bundle.issues} == {"CROSS_SOURCE_INCOMPLETE"}
    assert bundle.summary.missing_reference_rows == 1
    assert bundle.summary.mismatch_cells == 5
    assert bundle.summary.mismatch_rate == pytest.approx(5 / 3000)
    assert bundle.detail.height == 3000


def test_reconcile_tradestatus_zero_is_reference_missing_not_error(
    happy_candidate: G1Candidate, sample_plan: CrossSourceSamplePlan, request_plan: ReferenceRequestPlanV1,
) -> None:
    by_symbol = _sample_dates_by_symbol(sample_plan)
    responses = list(_perfect_reference_responses(happy_candidate, sample_plan, request_plan))
    target_spec = request_plan.requests[0]
    dates = by_symbol[target_spec.symbol]
    zero_day = dates[0]
    rows = _reference_rows_for_symbol(
        happy_candidate, target_spec.symbol, dates, zero_dates=frozenset({zero_day})
    )
    responses[0] = _make_verified_reference(target_spec, _reference_frame(rows))

    bundle = reconcile_cross_source(
        candidate=happy_candidate, sample_plan=sample_plan, reference_responses=tuple(responses),
        policy=_policy(max_mismatch_rate=0.01),
    )
    assert {issue.code for issue in bundle.issues} == {"CROSS_SOURCE_INCOMPLETE"}
    assert bundle.summary.missing_reference_rows == 1


@pytest.mark.parametrize(
    "mutator",
    [
        "wrong_code",
        "date_before_start",
        "date_after_end",
        "duplicate_date",
        "bad_adjustflag",
        "bad_tradestatus",
        "nonpositive_price",
        "negative_volume",
        "nonnumeric_value",
        "nan_value",
    ],
)
def test_reconcile_rejects_invalid_reference_rows(
    happy_candidate: G1Candidate, sample_plan: CrossSourceSamplePlan, request_plan: ReferenceRequestPlanV1,
    mutator: str,
) -> None:
    by_symbol = _sample_dates_by_symbol(sample_plan)
    responses = list(_perfect_reference_responses(happy_candidate, sample_plan, request_plan))
    target_spec = request_plan.requests[0]
    dates = by_symbol[target_spec.symbol]
    rows = _reference_rows_for_symbol(happy_candidate, target_spec.symbol, dates)
    params = dict(target_spec.parameters)
    start = dt.date.fromisoformat(params["start_date"])
    end = dt.date.fromisoformat(params["end_date"])

    if mutator == "wrong_code":
        rows[0]["code"] = "sz.999999"
    elif mutator == "date_before_start":
        rows[0]["date"] = (start - dt.timedelta(days=1)).isoformat()
    elif mutator == "date_after_end":
        rows[0]["date"] = (end + dt.timedelta(days=1)).isoformat()
    elif mutator == "duplicate_date":
        rows.append(dict(rows[0]))
    elif mutator == "bad_adjustflag":
        rows[0]["adjustflag"] = "1"
    elif mutator == "bad_tradestatus":
        rows[0]["tradestatus"] = "2"
    elif mutator == "nonpositive_price":
        rows[0]["open"] = "0.0"
    elif mutator == "negative_volume":
        rows[0]["volume"] = "-1.0"
    elif mutator == "nonnumeric_value":
        rows[0]["close"] = "abc"
    elif mutator == "nan_value":
        rows[0]["close"] = "nan"

    responses[0] = _make_verified_reference(target_spec, _reference_frame(rows))
    with pytest.raises(M3ReferenceError) as excinfo:
        reconcile_cross_source(
            candidate=happy_candidate, sample_plan=sample_plan, reference_responses=tuple(responses),
            policy=_policy(),
        )
    assert excinfo.value.code == "G1_CROSS_SOURCE_RECONCILIATION_INVALID"


def test_reconcile_price_tolerance_atol_and_rtol_boundaries(
    happy_candidate: G1Candidate, sample_plan: CrossSourceSamplePlan, request_plan: ReferenceRequestPlanV1,
) -> None:
    target_spec = request_plan.requests[0]
    by_symbol = _sample_dates_by_symbol(sample_plan)
    dates = by_symbol[target_spec.symbol]
    bars_index = {
        row["trade_date"]: row
        for row in happy_candidate.bars.filter(pl.col("symbol") == target_spec.symbol).iter_rows(
            named=True
        )
    }
    base_close = bars_index[dates[0]]["close"]
    policy = _policy(price_atol=0.02, price_rtol=0.0, max_mismatch_rate=0.5)

    def _bundle_with_close(delta: float) -> Any:
        rows = _reference_rows_for_symbol(happy_candidate, target_spec.symbol, dates)
        rows[0]["close"] = _num(base_close + delta)
        responses = list(_perfect_reference_responses(happy_candidate, sample_plan, request_plan))
        responses[0] = _make_verified_reference(target_spec, _reference_frame(rows))
        return reconcile_cross_source(
            candidate=happy_candidate, sample_plan=sample_plan, reference_responses=tuple(responses),
            policy=policy,
        )

    assert _bundle_with_close(-(0.02 - 1e-6)).summary.mismatch_cells == 0
    assert _bundle_with_close(-(0.02 + 1e-6)).summary.mismatch_cells == 1


def test_reconcile_volume_tolerance_uses_relative_denominator(
    happy_candidate: G1Candidate, sample_plan: CrossSourceSamplePlan, request_plan: ReferenceRequestPlanV1,
) -> None:
    target_spec = request_plan.requests[0]
    by_symbol = _sample_dates_by_symbol(sample_plan)
    dates = by_symbol[target_spec.symbol]
    bars_index = {
        row["trade_date"]: row
        for row in happy_candidate.bars.filter(pl.col("symbol") == target_spec.symbol).iter_rows(
            named=True
        )
    }
    primary_volume = bars_index[dates[0]]["volume"]
    rtol = 0.1
    policy = _policy(volume_rtol=rtol, max_mismatch_rate=0.5)
    boundary = primary_volume / (1.0 + rtol)

    def _bundle_with_volume(value: float) -> Any:
        rows = _reference_rows_for_symbol(happy_candidate, target_spec.symbol, dates)
        rows[0]["volume"] = _num(value)
        responses = list(_perfect_reference_responses(happy_candidate, sample_plan, request_plan))
        responses[0] = _make_verified_reference(target_spec, _reference_frame(rows))
        return reconcile_cross_source(
            candidate=happy_candidate, sample_plan=sample_plan, reference_responses=tuple(responses),
            policy=policy,
        )

    assert _bundle_with_volume(boundary + 1e-3).summary.mismatch_cells == 0
    assert _bundle_with_volume(boundary - 1e-3).summary.mismatch_cells == 1


def test_reconcile_mismatch_rate_exact_threshold_vs_exceeding(
    happy_candidate: G1Candidate, sample_plan: CrossSourceSamplePlan, request_plan: ReferenceRequestPlanV1,
) -> None:
    policy = _policy(price_atol=0.0, price_rtol=0.0, volume_rtol=0.0, max_mismatch_rate=0.01)
    at_threshold = _bundle_with_n_mismatches(happy_candidate, sample_plan, request_plan, policy, 30)
    assert at_threshold.summary.mismatch_cells == 30
    assert at_threshold.summary.mismatch_rate == pytest.approx(0.01)
    assert {issue.code for issue in at_threshold.issues} == set()
    assert at_threshold.passed is True

    over_threshold = _bundle_with_n_mismatches(happy_candidate, sample_plan, request_plan, policy, 31)
    assert over_threshold.summary.mismatch_cells == 31
    assert {issue.code for issue in over_threshold.issues} == {"CROSS_SOURCE_MISMATCH"}
    assert over_threshold.passed is False


def test_reconcile_both_issue_types_can_coexist(
    happy_candidate: G1Candidate, sample_plan: CrossSourceSamplePlan, request_plan: ReferenceRequestPlanV1,
) -> None:
    by_symbol = _sample_dates_by_symbol(sample_plan)
    policy = _policy(price_atol=0.0, price_rtol=0.0, volume_rtol=0.0, max_mismatch_rate=0.001)
    responses = list(_perfect_reference_responses(happy_candidate, sample_plan, request_plan))

    spec0 = request_plan.requests[0]
    dates0 = by_symbol[spec0.symbol]
    rows0 = _reference_rows_for_symbol(happy_candidate, spec0.symbol, dates0[1:])
    responses[0] = _make_verified_reference(spec0, _reference_frame(rows0))

    spec1 = request_plan.requests[1]
    dates1 = by_symbol[spec1.symbol]
    rows1 = _reference_rows_for_symbol(happy_candidate, spec1.symbol, dates1)
    rows1[0]["close"] = _num(float(rows1[0]["close"]) + 1.0)
    responses[1] = _make_verified_reference(spec1, _reference_frame(rows1))

    bundle = reconcile_cross_source(
        candidate=happy_candidate, sample_plan=sample_plan, reference_responses=tuple(responses),
        policy=policy,
    )
    assert {issue.code for issue in bundle.issues} == {
        "CROSS_SOURCE_INCOMPLETE", "CROSS_SOURCE_MISMATCH",
    }
    assert bundle.passed is False


# ===========================================================================
# 9. Bundle drift and wholesale re-run
# ===========================================================================


def test_bundle_constructor_rejects_wholesale_and_field_drift(
    happy_candidate: G1Candidate, sample_plan: CrossSourceSamplePlan, request_plan: ReferenceRequestPlanV1,
) -> None:
    responses = _perfect_reference_responses(happy_candidate, sample_plan, request_plan)
    bundle = reconcile_cross_source(
        candidate=happy_candidate, sample_plan=sample_plan, reference_responses=responses,
        policy=_policy(),
    )
    with pytest.raises(ValueError):
        replace(bundle, detail_sha256="0" * 64)
    with pytest.raises(ValueError):
        replace(bundle, detail=bundle.detail.with_columns(pl.lit(999.0).alias("abs_diff")))
    with pytest.raises(ValueError):
        replace(bundle, summary_sha256="0" * 64)
    with pytest.raises(ValueError):
        replace(bundle, passed=not bundle.passed)
    with pytest.raises(ValueError):
        replace(
            bundle,
            issues=(
                G1QualityIssue(
                    code="CROSS_SOURCE_MISMATCH", severity="ERROR", message="forged",
                    count=1, evidence=(),
                ),
            ),
        )
    with pytest.raises(ValueError):
        replace(
            bundle,
            summary=replace(bundle.summary, mismatch_cells=bundle.summary.mismatch_cells + 1),
        )
    with pytest.raises(ValueError):
        replace(bundle, reference_receipts=bundle.reference_receipts[:-1])


def test_bundle_wholesale_summary_drift_only_caught_by_recomputing_reconcile(
    happy_candidate: G1Candidate, sample_plan: CrossSourceSamplePlan, request_plan: ReferenceRequestPlanV1,
) -> None:
    responses_a = _perfect_reference_responses(happy_candidate, sample_plan, request_plan)
    bundle_a = reconcile_cross_source(
        candidate=happy_candidate, sample_plan=sample_plan, reference_responses=responses_a,
        policy=_policy(),
    )
    by_symbol = _sample_dates_by_symbol(sample_plan)
    spec0 = request_plan.requests[0]
    rows = _reference_rows_for_symbol(happy_candidate, spec0.symbol, by_symbol[spec0.symbol])
    rows[0]["close"] = _num(float(rows[0]["close"]) + 5.0)
    responses_b = list(responses_a)
    responses_b[0] = _make_verified_reference(spec0, _reference_frame(rows))
    bundle_b = reconcile_cross_source(
        candidate=happy_candidate, sample_plan=sample_plan, reference_responses=tuple(responses_b),
        policy=_policy(),
    )
    assert bundle_b.summary_sha256 != bundle_a.summary_sha256
    assert bundle_b.detail_sha256 != bundle_a.detail_sha256
    assert bundle_b.summary.mismatch_cells != bundle_a.summary.mismatch_cells


# ===========================================================================
# Independent-review rework: ADV5 / ADV9 / F3
# ===========================================================================


def _lying_green_summary_from_mismatch_bundle(bundle: CrossSourceReconciliationBundle) -> Any:
    """Build a self-consistent all-green summary for the same detail digest (ADV5)."""
    green_stats = tuple(
        CrossSourceFieldStatsV1(
            field=stats.field,
            comparison_count=stats.comparison_count,
            mismatch_count=0,
            max_abs_diff=0.0,
            max_relative_diff=0.0,
        )
        for stats in bundle.summary.field_stats
    )
    green = replace(
        bundle.summary,
        missing_primary_rows=0,
        missing_reference_rows=0,
        mismatch_cells=0,
        mismatch_rate=0.0,
        field_stats=green_stats,
        passed=True,
    )
    return green, ref._sha256_json(asdict(green))


def test_adv5_bundle_rejects_lying_green_summary_on_mismatch_detail(
    happy_candidate: G1Candidate, sample_plan: CrossSourceSamplePlan, request_plan: ReferenceRequestPlanV1,
) -> None:
    policy = _policy(max_mismatch_rate=0.0)
    bundle = _bundle_with_n_mismatches(happy_candidate, sample_plan, request_plan, policy, 1)
    assert bundle.summary.mismatch_cells > 0
    assert bundle.passed is False
    green, green_hash = _lying_green_summary_from_mismatch_bundle(bundle)
    with pytest.raises(ValueError):
        CrossSourceReconciliationBundle(
            sample_plan=bundle.sample_plan,
            reference_receipts=bundle.reference_receipts,
            detail=bundle.detail,
            detail_sha256=bundle.detail_sha256,
            summary=green,
            summary_sha256=green_hash,
            issues=(),
            passed=True,
        )


def test_adv5_variants_reject_forged_stats_missing_rate_issues_passed(
    happy_candidate: G1Candidate, sample_plan: CrossSourceSamplePlan, request_plan: ReferenceRequestPlanV1,
) -> None:
    policy = _policy(max_mismatch_rate=0.0)
    bundle = _bundle_with_n_mismatches(happy_candidate, sample_plan, request_plan, policy, 5)
    # Forge max diffs to zero while keeping mismatch counts consistent with summary totals.
    forged_stats = replace(
        bundle.summary.field_stats[3],  # close — mismatches are injected on close
        max_abs_diff=0.0,
        max_relative_diff=0.0,
    )
    assert bundle.summary.field_stats[3].max_abs_diff > 0.0
    stats_summary = replace(
        bundle.summary,
        field_stats=(
            *bundle.summary.field_stats[:3],
            forged_stats,
            bundle.summary.field_stats[4],
        ),
    )
    with pytest.raises(ValueError):
        replace(
            bundle,
            summary=stats_summary,
            summary_sha256=ref._sha256_json(asdict(stats_summary)),
        )

    missing_summary = replace(bundle.summary, missing_reference_rows=bundle.summary.missing_reference_rows + 1)
    with pytest.raises(ValueError):
        replace(
            bundle,
            summary=missing_summary,
            summary_sha256=ref._sha256_json(asdict(missing_summary)),
        )

    zero_stats = tuple(
        CrossSourceFieldStatsV1(
            field=stats.field,
            comparison_count=stats.comparison_count,
            mismatch_count=0,
            max_abs_diff=0.0,
            max_relative_diff=0.0,
        )
        for stats in bundle.summary.field_stats
    )
    cells_summary = replace(
        bundle.summary,
        mismatch_cells=0,
        mismatch_rate=0.0,
        field_stats=zero_stats,
        passed=False,
    )
    with pytest.raises(ValueError):
        replace(
            bundle,
            summary=cells_summary,
            summary_sha256=ref._sha256_json(asdict(cells_summary)),
        )

    with pytest.raises(ValueError):
        replace(
            bundle,
            issues=(
                G1QualityIssue(
                    code="CROSS_SOURCE_MISMATCH",
                    severity="ERROR",
                    message="cross-source mismatch rate exceeds policy threshold",
                    count=bundle.summary.mismatch_cells + 1,
                    evidence=(),
                ),
            ),
        )
    with pytest.raises(ValueError):
        replace(
            bundle,
            issues=(
                G1QualityIssue(
                    code="CROSS_SOURCE_MISMATCH",
                    severity="ERROR",
                    message="forged message",
                    count=bundle.summary.mismatch_cells,
                    evidence=(),
                ),
            ),
        )
    with pytest.raises(ValueError):
        replace(
            bundle,
            passed=True,
            summary=replace(bundle.summary, passed=True),
            summary_sha256=ref._sha256_json(asdict(replace(bundle.summary, passed=True))),
        )

def test_adv5_detail_schema_and_key_drifts_reject_with_stable_valueerror(
    happy_candidate: G1Candidate, sample_plan: CrossSourceSamplePlan, request_plan: ReferenceRequestPlanV1,
) -> None:
    responses = _perfect_reference_responses(happy_candidate, sample_plan, request_plan)
    bundle = reconcile_cross_source(
        candidate=happy_candidate, sample_plan=sample_plan, reference_responses=responses,
        policy=_policy(),
    )
    cases = [
        bundle.detail.with_row_index().filter(pl.col("index") > 0).drop("index"),  # missing row
        pl.concat([bundle.detail, bundle.detail.head(1)]),  # duplicate/extra
        bundle.detail.with_columns(pl.col("field").cast(pl.Categorical)),
        bundle.detail.with_columns(pl.lit("WRONG").alias("missing_side")),
        bundle.detail.with_columns(pl.lit(False).alias("matched")),
        bundle.detail.with_columns(pl.lit(None, dtype=pl.Float64).alias("tolerance")),
    ]
    for detail in cases:
        digest = clean_table_content_sha256(table_name="cross_source_detail", frame=detail)
        summary = replace(bundle.summary, detail_sha256=digest)
        with pytest.raises(ValueError) as excinfo:
            CrossSourceReconciliationBundle(
                sample_plan=bundle.sample_plan,
                reference_receipts=bundle.reference_receipts,
                detail=detail,
                detail_sha256=digest,
                summary=summary,
                summary_sha256=ref._sha256_json(asdict(summary)),
                issues=bundle.issues,
                passed=bundle.passed,
            )
        text = f"{excinfo.value}{excinfo.value!s}{excinfo.value!r}"
        assert "/home/" not in text
        assert "polars" not in text.lower()
        assert "ComputeError" not in text


def test_adv9_bundle_rejects_warning_severity_for_both_cross_source_codes(
    happy_candidate: G1Candidate, sample_plan: CrossSourceSamplePlan, request_plan: ReferenceRequestPlanV1,
) -> None:
    policy = _policy(max_mismatch_rate=0.0)
    bundle = _bundle_with_n_mismatches(happy_candidate, sample_plan, request_plan, policy, 1)
    for code in ("CROSS_SOURCE_INCOMPLETE", "CROSS_SOURCE_MISMATCH"):
        # Force a WARNING issue while keeping passed/summary consistent enough to isolate severity.
        if code == "CROSS_SOURCE_MISMATCH":
            warn_issue = G1QualityIssue(
                code=code,
                severity="WARNING",
                message="cross-source mismatch rate exceeds policy threshold",
                count=bundle.summary.mismatch_cells,
                evidence=(),
            )
            with pytest.raises(ValueError):
                replace(bundle, issues=(warn_issue,), passed=False)
        else:
            # Build an incomplete bundle then swap ERROR→WARNING on the incomplete issue.
            incomplete = reconcile_cross_source(
                candidate=happy_candidate,
                sample_plan=sample_plan,
                reference_responses=_perfect_reference_responses(
                    happy_candidate, sample_plan, request_plan
                )[:-1] + (
                    _make_verified_reference(
                        request_plan.requests[-1],
                        _reference_frame([]),
                    ),
                ),
                policy=_policy(max_mismatch_rate=1.0),
            )
            assert any(i.code == "CROSS_SOURCE_INCOMPLETE" for i in incomplete.issues)
            base = incomplete.issues[0]
            warn_issue = G1QualityIssue(
                code="CROSS_SOURCE_INCOMPLETE",
                severity="WARNING",
                message=base.message,
                count=base.count,
                evidence=base.evidence,
            )
            with pytest.raises(ValueError):
                replace(incomplete, issues=(warn_issue,))


def test_f3_bundle_rejects_sample_plan_and_reference_receipt_closure_drifts(
    happy_candidate: G1Candidate, sample_plan: CrossSourceSamplePlan, request_plan: ReferenceRequestPlanV1,
) -> None:
    responses = _perfect_reference_responses(happy_candidate, sample_plan, request_plan)
    bundle = reconcile_cross_source(
        candidate=happy_candidate, sample_plan=sample_plan, reference_responses=responses,
        policy=_policy(),
    )
    # primary_candidate_key drift
    key_summary = replace(bundle.summary, primary_candidate_key="a" * 64)
    with pytest.raises(ValueError):
        replace(bundle, summary=key_summary, summary_sha256=ref._sha256_json(asdict(key_summary)))
    # sample_plan_sha256 drift
    plan_summary = replace(bundle.summary, sample_plan_sha256="b" * 64)
    with pytest.raises(ValueError):
        replace(bundle, summary=plan_summary, summary_sha256=ref._sha256_json(asdict(plan_summary)))
    # delete one reference receipt
    with pytest.raises(ValueError):
        replace(bundle, reference_receipts=bundle.reference_receipts[:-1])
    # change summary digests without changing receipts
    digests_only = replace(
        bundle.summary,
        reference_receipt_digests=tuple(
            sorted({*bundle.summary.reference_receipt_digests[:-1], "c" * 64})
        ),
    )
    with pytest.raises(ValueError):
        replace(
            bundle,
            summary=digests_only,
            summary_sha256=ref._sha256_json(asdict(digests_only)),
        )
    # change one receipt digest without updating summary digests
    forged_receipt = replace(
        bundle.reference_receipts[0], stable_response_sha256="c" * 64
    )
    forged_receipts = tuple(
        sorted(
            (forged_receipt, *bundle.reference_receipts[1:]),
            key=lambda item: (item.source, item.endpoint, item.request_id),
        )
    )
    with pytest.raises(ValueError):
        replace(bundle, reference_receipts=forged_receipts)
    # summary.detail_sha256 drift vs bundle.detail_sha256
    detail_summary = replace(bundle.summary, detail_sha256="d" * 64)
    with pytest.raises(ValueError):
        replace(
            bundle,
            summary=detail_summary,
            summary_sha256=ref._sha256_json(asdict(detail_summary)),
        )


def test_f3_summary_reference_digests_must_match_receipt_projections(
    happy_candidate: G1Candidate, sample_plan: CrossSourceSamplePlan, request_plan: ReferenceRequestPlanV1,
) -> None:
    responses = _perfect_reference_responses(happy_candidate, sample_plan, request_plan)
    bundle = reconcile_cross_source(
        candidate=happy_candidate, sample_plan=sample_plan, reference_responses=responses,
        policy=_policy(),
    )
    wrong_digests = tuple(sorted({*bundle.summary.reference_receipt_digests, "e" * 64}))
    # Keep length uniqueness rules of summary validator in mind: digests must be sorted unique.
    # Adding an extra digest changes the tuple and must be rejected by F3 closure.
    with pytest.raises(ValueError):
        summary = replace(bundle.summary, reference_receipt_digests=wrong_digests)
        replace(bundle, summary=summary, summary_sha256=ref._sha256_json(asdict(summary)))


# ===========================================================================
# Main-acceptance rework: H1 / H2 / H3
# ===========================================================================


def _missing_reference_bundle(
    happy_candidate: G1Candidate,
    sample_plan: CrossSourceSamplePlan,
    request_plan: ReferenceRequestPlanV1,
) -> CrossSourceReconciliationBundle:
    by_symbol = _sample_dates_by_symbol(sample_plan)
    responses = list(_perfect_reference_responses(happy_candidate, sample_plan, request_plan))
    target_spec = request_plan.requests[0]
    remaining_days = by_symbol[target_spec.symbol][1:]
    rows = _reference_rows_for_symbol(happy_candidate, target_spec.symbol, remaining_days)
    responses[0] = _make_verified_reference(target_spec, _reference_frame(rows))
    return reconcile_cross_source(
        candidate=happy_candidate,
        sample_plan=sample_plan,
        reference_responses=tuple(responses),
        policy=_policy(max_mismatch_rate=0.01),
    )


def _detail_rows(detail: pl.DataFrame) -> list[dict[str, Any]]:
    return [dict(row) for row in detail.to_dicts()]


def _detail_from_rows(detail: pl.DataFrame, rows: list[dict[str, Any]]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=detail.schema)


def _first_key_for_side(detail: pl.DataFrame, missing_side: str) -> tuple[str, dt.date]:
    for row in detail.iter_rows(named=True):
        if row["missing_side"] == missing_side:
            return row["symbol"], row["trade_date"]
    raise AssertionError(f"no key with missing_side={missing_side}")


_UNSET = object()


def _mutate_key_rows(
    detail: pl.DataFrame,
    symbol: str,
    day: dt.date,
    *,
    missing_side: str,
    tolerance: float | None,
    primary_value: Any = _UNSET,
    reference_value: Any = _UNSET,
) -> pl.DataFrame:
    rows = _detail_rows(detail)
    for row in rows:
        if row["symbol"] != symbol or row["trade_date"] != day:
            continue
        row["missing_side"] = missing_side
        row["matched"] = False
        row["abs_diff"] = None
        row["relative_diff"] = None
        row["tolerance"] = tolerance
        if missing_side == "PRIMARY":
            row["primary_value"] = None if primary_value is _UNSET else primary_value
            if reference_value is not _UNSET:
                row["reference_value"] = reference_value
        elif missing_side == "REFERENCE":
            row["reference_value"] = None if reference_value is _UNSET else reference_value
            if primary_value is not _UNSET:
                row["primary_value"] = primary_value
        elif missing_side == "BOTH":
            row["primary_value"] = None if primary_value is _UNSET else primary_value
            row["reference_value"] = None if reference_value is _UNSET else reference_value
    return _detail_from_rows(detail, rows)


def _rebundle_with_mutated_detail(
    bundle: CrossSourceReconciliationBundle,
    detail: pl.DataFrame,
    *,
    summary_overrides: dict[str, Any] | None = None,
    receipts: tuple[Any, ...] | None = None,
    issues: tuple[G1QualityIssue, ...] | None = None,
    passed: bool | None = None,
) -> CrossSourceReconciliationBundle:
    digest = clean_table_content_sha256(table_name="cross_source_detail", frame=detail)
    summary = replace(bundle.summary, detail_sha256=digest)
    if summary_overrides:
        summary = replace(summary, **summary_overrides, detail_sha256=digest)
    return CrossSourceReconciliationBundle(
        sample_plan=bundle.sample_plan,
        reference_receipts=receipts if receipts is not None else bundle.reference_receipts,
        detail=detail,
        detail_sha256=digest,
        summary=summary,
        summary_sha256=ref._sha256_json(asdict(summary)),
        issues=issues if issues is not None else bundle.issues,
        passed=bundle.passed if passed is None else passed,
    )


def _rebuild_bundle_from_valid_detail(
    bundle: CrossSourceReconciliationBundle,
    detail: pl.DataFrame,
) -> CrossSourceReconciliationBundle:
    derived = ref._derive_cross_source_from_detail(
        detail=detail,
        sample_plan=bundle.sample_plan,
        price_atol=bundle.summary.price_atol,
        price_rtol=bundle.summary.price_rtol,
        volume_rtol=bundle.summary.volume_rtol,
        max_mismatch_rate=bundle.summary.max_mismatch_rate,
    )
    summary = replace(
        bundle.summary,
        missing_primary_rows=derived.missing_primary_rows,
        missing_reference_rows=derived.missing_reference_rows,
        mismatch_cells=derived.mismatch_cells,
        mismatch_rate=derived.mismatch_rate,
        field_stats=derived.field_stats,
        detail_sha256=derived.detail_sha256,
        passed=derived.passed,
    )
    return CrossSourceReconciliationBundle(
        sample_plan=bundle.sample_plan,
        reference_receipts=bundle.reference_receipts,
        detail=detail,
        detail_sha256=derived.detail_sha256,
        summary=summary,
        summary_sha256=ref._sha256_json(asdict(summary)),
        issues=derived.issues,
        passed=derived.passed,
    )


def test_h1_missing_rows_require_exact_zero_tolerance(
    happy_candidate: G1Candidate, sample_plan: CrossSourceSamplePlan, request_plan: ReferenceRequestPlanV1,
) -> None:
    incomplete = _missing_reference_bundle(happy_candidate, sample_plan, request_plan)
    symbol, day = _first_key_for_side(incomplete.detail, "REFERENCE")

    bad_tol = _mutate_key_rows(
        incomplete.detail, symbol, day, missing_side="REFERENCE", tolerance=123.0
    )
    with pytest.raises(ValueError):
        _rebundle_with_mutated_detail(incomplete, bad_tol)

    for bad in (float("nan"), float("inf"), float("-inf"), None, 1, True):
        rows = _detail_rows(incomplete.detail)
        for row in rows:
            if row["symbol"] == symbol and row["trade_date"] == day:
                row["tolerance"] = bad
        detail = _detail_from_rows(incomplete.detail, rows)
        with pytest.raises(ValueError):
            _rebundle_with_mutated_detail(incomplete, detail)

    neg_zero = _mutate_key_rows(
        incomplete.detail, symbol, day, missing_side="REFERENCE", tolerance=-0.0
    )
    rebuilt = _rebundle_with_mutated_detail(incomplete, neg_zero)
    assert rebuilt.summary.missing_reference_rows == 1

    happy = reconcile_cross_source(
        candidate=happy_candidate,
        sample_plan=sample_plan,
        reference_responses=_perfect_reference_responses(
            happy_candidate, sample_plan, request_plan
        ),
        policy=_policy(),
    )
    first_symbol, first_day = happy.detail.row(0, named=True)["symbol"], happy.detail.row(
        0, named=True
    )["trade_date"]
    for side in ("PRIMARY", "BOTH"):
        forged = _mutate_key_rows(
            happy.detail,
            first_symbol,
            first_day,
            missing_side=side,
            tolerance=123.0,
            primary_value=None,
            reference_value=None if side == "BOTH" else 1.0,
        )
        # Hash-rebinding attack: craft summary counts as if tolerance were accepted.
        overrides = {
            "missing_primary_rows": 1 if side in {"PRIMARY", "BOTH"} else 0,
            "missing_reference_rows": 1 if side in {"REFERENCE", "BOTH"} else 0,
            "mismatch_cells": 5,
            "mismatch_rate": 5 / 3000,
            "field_stats": tuple(
                CrossSourceFieldStatsV1(
                    field=stats.field,
                    comparison_count=stats.comparison_count,
                    mismatch_count=1,
                    max_abs_diff=0.0,
                    max_relative_diff=0.0,
                )
                for stats in happy.summary.field_stats
            ),
            "passed": False,
        }
        evidence = (f"{first_symbol}|{first_day.isoformat()}",)
        issues = (
            G1QualityIssue(
                code="CROSS_SOURCE_INCOMPLETE",
                severity="ERROR",
                message="cross-source sample row missing primary or reference bar",
                count=overrides["missing_primary_rows"] + overrides["missing_reference_rows"],
                evidence=evidence,
            ),
        )
        with pytest.raises(ValueError):
            _rebundle_with_mutated_detail(
                happy, forged, summary_overrides=overrides, issues=issues, passed=False
            )

        ok = _mutate_key_rows(
            happy.detail,
            first_symbol,
            first_day,
            missing_side=side,
            tolerance=0.0,
            primary_value=None,
            reference_value=None if side == "BOTH" else 1.0,
        )
        rebuilt_ok = _rebuild_bundle_from_valid_detail(happy, ok)
        assert rebuilt_ok.summary.missing_primary_rows == overrides["missing_primary_rows"]
        assert rebuilt_ok.summary.missing_reference_rows == overrides["missing_reference_rows"]


@pytest.mark.parametrize(
    ("missing_side", "field", "bad_value"),
    [
        ("REFERENCE", "open", 0.0),
        ("REFERENCE", "open", -1.0),
        ("REFERENCE", "open", float("nan")),
        ("REFERENCE", "open", float("inf")),
        ("REFERENCE", "high", 0.0),
        ("REFERENCE", "low", -1.0),
        ("REFERENCE", "close", float("nan")),
        ("REFERENCE", "volume", -1.0),
        ("REFERENCE", "volume", float("nan")),
        ("REFERENCE", "volume", float("inf")),
        ("PRIMARY", "open", 0.0),
        ("PRIMARY", "close", -1.0),
        ("PRIMARY", "volume", -1.0),
        ("PRIMARY", "volume", float("nan")),
    ],
)
def test_h2_missing_rows_reject_invalid_present_side_domain(
    happy_candidate: G1Candidate,
    sample_plan: CrossSourceSamplePlan,
    request_plan: ReferenceRequestPlanV1,
    missing_side: str,
    field: str,
    bad_value: float,
) -> None:
    happy = reconcile_cross_source(
        candidate=happy_candidate,
        sample_plan=sample_plan,
        reference_responses=_perfect_reference_responses(
            happy_candidate, sample_plan, request_plan
        ),
        policy=_policy(max_mismatch_rate=0.01),
    )
    first_symbol = happy.detail.row(0, named=True)["symbol"]
    first_day = happy.detail.row(0, named=True)["trade_date"]
    base = _mutate_key_rows(
        happy.detail,
        first_symbol,
        first_day,
        missing_side=missing_side,
        tolerance=0.0,
        primary_value=None if missing_side == "PRIMARY" else 1.0,
        reference_value=None if missing_side == "REFERENCE" else 1.0,
    )
    rows = _detail_rows(base)
    for row in rows:
        if row["symbol"] == first_symbol and row["trade_date"] == first_day and row["field"] == field:
            if missing_side == "REFERENCE":
                row["primary_value"] = bad_value
            else:
                row["reference_value"] = bad_value
    detail = _detail_from_rows(base, rows)
    with pytest.raises(ValueError) as excinfo:
        _rebuild_bundle_from_valid_detail(happy, detail)
    text = f"{excinfo.value}{excinfo.value!s}{excinfo.value!r}"
    assert "/home/" not in text
    assert "polars" not in text.lower()
    assert "ComputeError" not in text


def test_h2_missing_rows_accept_valid_present_side_and_both_nulls(
    happy_candidate: G1Candidate, sample_plan: CrossSourceSamplePlan, request_plan: ReferenceRequestPlanV1,
) -> None:
    incomplete = _missing_reference_bundle(happy_candidate, sample_plan, request_plan)
    symbol, day = _first_key_for_side(incomplete.detail, "REFERENCE")
    rows = _detail_rows(incomplete.detail)
    for row in rows:
        if row["symbol"] == symbol and row["trade_date"] == day and row["field"] == "volume":
            row["primary_value"] = 0.0
    detail = _detail_from_rows(incomplete.detail, rows)
    rebuilt = _rebundle_with_mutated_detail(incomplete, detail)
    assert rebuilt.summary.missing_reference_rows == 1

    happy = reconcile_cross_source(
        candidate=happy_candidate,
        sample_plan=sample_plan,
        reference_responses=_perfect_reference_responses(
            happy_candidate, sample_plan, request_plan
        ),
        policy=_policy(),
    )
    first_symbol = happy.detail.row(0, named=True)["symbol"]
    first_day = happy.detail.row(0, named=True)["trade_date"]

    primary_ok = _mutate_key_rows(
        happy.detail,
        first_symbol,
        first_day,
        missing_side="PRIMARY",
        tolerance=0.0,
        primary_value=None,
        reference_value=2.5,
    )
    rebuilt_primary = _rebuild_bundle_from_valid_detail(happy, primary_ok)
    assert rebuilt_primary.summary.missing_primary_rows == 1

    both_ok = _mutate_key_rows(
        happy.detail,
        first_symbol,
        first_day,
        missing_side="BOTH",
        tolerance=0.0,
        primary_value=None,
        reference_value=None,
    )
    rebuilt_both = _rebuild_bundle_from_valid_detail(happy, both_ok)
    assert rebuilt_both.summary.missing_primary_rows == 1
    assert rebuilt_both.summary.missing_reference_rows == 1

    both_bad = _mutate_key_rows(
        happy.detail,
        first_symbol,
        first_day,
        missing_side="BOTH",
        tolerance=0.0,
        primary_value=1.0,
        reference_value=None,
    )
    with pytest.raises(ValueError):
        _rebuild_bundle_from_valid_detail(happy, both_bad)


def test_h3_stable_response_digests_remain_one_per_request(
    happy_candidate: G1Candidate, sample_plan: CrossSourceSamplePlan, request_plan: ReferenceRequestPlanV1,
) -> None:
    responses = _perfect_reference_responses(happy_candidate, sample_plan, request_plan)
    bundle = reconcile_cross_source(
        candidate=happy_candidate, sample_plan=sample_plan, reference_responses=responses,
        policy=_policy(),
    )
    assert len(bundle.reference_receipts) == 30
    assert len(set(item.stable_response_sha256 for item in bundle.reference_receipts)) == 30
    assert len(bundle.summary.reference_receipt_digests) == 30

    r0 = bundle.reference_receipts[0]
    r1 = bundle.reference_receipts[1]
    dup_receipt = replace(r1, stable_response_sha256=r0.stable_response_sha256)
    forged_receipts = tuple(
        sorted(
            (dup_receipt if item.request_id == r1.request_id else item for item in bundle.reference_receipts),
            key=lambda item: (item.source, item.endpoint, item.request_id),
        )
    )
    assert len(set(item.stable_response_sha256 for item in forged_receipts)) == 29

    # Receipt-only drift (summary still lists 30).
    with pytest.raises(ValueError):
        replace(bundle, reference_receipts=forged_receipts)

    # Summary-only drift to 29 while receipts remain 30 unique.
    digests_29 = tuple(sorted(set(bundle.summary.reference_receipt_digests[:-1])))
    assert len(digests_29) == 29
    summary_29 = replace(bundle.summary, reference_receipt_digests=digests_29)
    with pytest.raises(ValueError):
        replace(
            bundle,
            summary=summary_29,
            summary_sha256=ref._sha256_json(asdict(summary_29)),
        )

    # Self-consistent collapse: receipts + summary both rebound to 29 unique digests.
    collapsed = tuple(sorted({item.stable_response_sha256 for item in forged_receipts}))
    assert len(collapsed) == 29
    summary_collapsed = replace(bundle.summary, reference_receipt_digests=collapsed)
    with pytest.raises(ValueError):
        CrossSourceReconciliationBundle(
            sample_plan=bundle.sample_plan,
            reference_receipts=forged_receipts,
            detail=bundle.detail,
            detail_sha256=bundle.detail_sha256,
            summary=summary_collapsed,
            summary_sha256=ref._sha256_json(asdict(summary_collapsed)),
            issues=bundle.issues,
            passed=bundle.passed,
        )


# ===========================================================================
# 10. Pure planners / reconcile perform zero IO / network
# ===========================================================================


def test_pure_functions_perform_zero_io_or_network(
    happy_candidate: G1Candidate, sample_plan: CrossSourceSamplePlan, request_plan: ReferenceRequestPlanV1,
) -> None:
    import builtins

    real_open = builtins.open

    def guarded_open(file: object, *args: object, **kwargs: object) -> object:
        text = str(file).replace("\\", "/").lower()
        forbidden = ("/raw/", "/journal/", ".parquet", "receipt.json", "candidate.json", "intent.json")
        if any(token in text for token in forbidden):
            raise AssertionError("open called on data/journal path")
        return real_open(file, *args, **kwargs)  # type: ignore[arg-type]

    responses = _perfect_reference_responses(happy_candidate, sample_plan, request_plan)
    with (
        patch("builtins.open", side_effect=guarded_open),
        patch.object(socket.socket, "connect", side_effect=AssertionError("socket")),
        patch.object(RawStore, "write", side_effect=AssertionError("raw write")),
        patch.object(RawStore, "write_request", side_effect=AssertionError("raw write_request")),
    ):
        plan_a = plan_cross_source_reconciliation(candidate=happy_candidate, policy=_policy())
        plan_b = plan_baostock_reference_requests(sample_plan=plan_a)
        bundle = reconcile_cross_source(
            candidate=happy_candidate, sample_plan=plan_a, reference_responses=responses,
            policy=_policy(),
        )
    assert plan_a == sample_plan
    assert plan_b == request_plan
    assert bundle.passed is True


# ===========================================================================
# 11. Unblock doc §5: cross-source issue codes and P4A audit regression
# ===========================================================================


def test_cross_source_issue_codes_constructible_and_enter_bundle() -> None:
    for code in ("CROSS_SOURCE_INCOMPLETE", "CROSS_SOURCE_MISMATCH"):
        issue = G1QualityIssue(code=code, severity="ERROR", message="m", count=1, evidence=())
        assert issue.code == code


def test_unfrozen_cross_source_codes_are_rejected() -> None:
    with pytest.raises(ValueError):
        G1QualityIssue(code="CROSS_SOURCE_UNKNOWN", severity="ERROR", message="m", count=1, evidence=())


def test_audit_g1_candidate_only_uses_primary_codes_on_happy_and_damaged_candidates(
    happy_candidate: G1Candidate,
) -> None:
    audit = audit_g1_candidate(candidate=happy_candidate)
    assert audit.passed is True
    codes = {issue.code for issue in audit.issues}
    assert codes.isdisjoint({"CROSS_SOURCE_INCOMPLETE", "CROSS_SOURCE_MISMATCH"})

    symbol = happy_candidate.eligible_keys["symbol"][0]
    bars = happy_candidate.bars.filter(
        ~((pl.col("symbol") == symbol) & (pl.col("trade_date") == _D0))
    )
    damaged = _rebind_identity(happy_candidate, bars=bars)
    audit2 = audit_g1_candidate(candidate=damaged)
    assert audit2.passed is False
    codes2 = {issue.code for issue in audit2.issues}
    assert codes2.isdisjoint({"CROSS_SOURCE_INCOMPLETE", "CROSS_SOURCE_MISMATCH"})
    assert "BAR_OR_SUSPENSION_MISSING" in codes2


# ===========================================================================
# General: error sanitization and package exports
# ===========================================================================


def test_m3_reference_error_str_repr_is_sanitized() -> None:
    err = M3ReferenceError("G1_REFERENCE_IO_FAILED")
    text = f"{err}{err!s}{err!r}"
    assert "/home/" not in text
    assert "token" not in text.lower()
    assert err.__cause__ is None


def test_m3_reference_error_rejects_unknown_code() -> None:
    with pytest.raises(ValueError):
        M3ReferenceError("NOT_A_REAL_CODE")


def test_package_exports_frozen_public_names() -> None:
    import quant.data as qd

    assert qd.G1CrossSourcePolicy is G1CrossSourcePolicy
    assert qd.CrossSourceSamplePlan is CrossSourceSamplePlan
    assert qd.ReferenceRequestSpec is ReferenceRequestSpec
    assert qd.ReferenceRequestPlanV1 is ReferenceRequestPlanV1
    assert qd.ReferenceRequestIntentV1 is ReferenceRequestIntentV1
    assert qd.ReferenceRawCandidateV1 is ReferenceRawCandidateV1
    assert qd.ReferenceRequestReceipt is ReferenceRequestReceipt
    assert qd.VerifiedReferenceResponse is VerifiedReferenceResponse
    assert qd.plan_cross_source_reconciliation is plan_cross_source_reconciliation
    assert qd.plan_baostock_reference_requests is plan_baostock_reference_requests
    assert qd.execute_baostock_reference_plan is execute_baostock_reference_plan
    assert qd.verify_reference_receipt is verify_reference_receipt
    assert qd.reconcile_cross_source is reconcile_cross_source
    assert qd.M3ReferenceError is M3ReferenceError
