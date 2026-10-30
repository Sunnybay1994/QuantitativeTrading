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
    VerifiedCninfoRawResponse,
    VerifiedRawResponse,
    cninfo_response_content_sha256,
    plan_index_weight_requests,
)
from quant.data.connectors.cninfo import (
    CNINFO_ADAPTER,
    CNINFO_ENDPOINT,
    CNINFO_SOURCE,
    CNINFO_STOCK_ALLOTMENT_FIELDS,
    empty_cninfo_allotment_frame,
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




def _make_cninfo_ca_verified(spec: backfill.CninfoCorporateActionRequestSpec):
    from quant.data.connectors.cninfo import (
        CNINFO_SOURCE,
        empty_cninfo_dividend_frame,
        empty_cninfo_share_change_frame,
        CNINFO_DIVIDEND_ENDPOINT,
    )
    from quant.data.m3_backfill import (
        cninfo_corporate_action_response_content_sha256,
        VerifiedCninfoCorporateActionRawResponse,
        CninfoCorporateActionRequestReceipt,
    )
    frame = (
        empty_cninfo_dividend_frame()
        if spec.endpoint == CNINFO_DIVIDEND_ENDPOINT
        else empty_cninfo_share_change_frame()
    )
    content = cninfo_corporate_action_response_content_sha256(frame, endpoint=spec.endpoint)
    parameters_sha256 = backfill._parameters_hash(spec.parameters)
    table = spec.endpoint
    raw_data_path = f"cninfo/{table}/{spec.request_id}.json"
    raw_metadata_path = f"cninfo/{table}/{spec.request_id}.metadata.json"
    values = {
        "request_id": spec.request_id,
        "endpoint": spec.endpoint,
        "adapter": spec.adapter,
        "parameters_sha256": parameters_sha256,
        "raw_snapshot_id": spec.request_id,
        "raw_data_path": raw_data_path,
        "raw_metadata_path": raw_metadata_path,
        "raw_file_sha256": _HEX,
        "raw_metadata_sha256": _HEX,
        "response_content_sha256": content,
        "resultcode": 200,
        "resultmsg": "success",
        "count": 0,
        "total": 0,
        "raw_size_bytes": 1,
        "row_count": 0,
        "columns": tuple(frame.columns),
    }
    stable = backfill._cninfo_ca_stable_response_hash_values(values)
    receipt = CninfoCorporateActionRequestReceipt(
        schema_version="m3-g1-cninfo-corporate-action-receipt-v1",
        request_id=spec.request_id,
        source=CNINFO_SOURCE,
        endpoint=spec.endpoint,
        adapter=spec.adapter,
        parameters=spec.parameters,
        parameters_sha256=parameters_sha256,
        raw_snapshot_id=spec.request_id,
        raw_data_path=raw_data_path,
        raw_metadata_path=raw_metadata_path,
        raw_file_sha256=_HEX,
        raw_metadata_sha256=_HEX,
        response_content_sha256=content,
        stable_response_sha256=stable,
        resultcode=200,
        resultmsg="success",
        count=0,
        total=0,
        raw_size_bytes=1,
        row_count=0,
        columns=tuple(frame.columns),
    )
    return VerifiedCninfoCorporateActionRawResponse(
        spec=spec,
        receipt=receipt,
        receipt_sha256=backfill._sha256(asdict(receipt)),
        frame=frame,
        resultcode=200,
        resultmsg="success",
        count=0,
        total=0,
    )


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


def _make_cninfo_verified(spec: backfill.CninfoRequestSpec) -> VerifiedCninfoRawResponse:
    frame = empty_cninfo_allotment_frame()
    content = cninfo_response_content_sha256(frame)
    parameters_sha256 = backfill._parameters_hash(spec.parameters)
    values = {
        "request_id": spec.request_id,
        "endpoint": CNINFO_ENDPOINT,
        "adapter": CNINFO_ADAPTER,
        "parameters_sha256": parameters_sha256,
        "response_content_sha256": content,
        "resultcode": 200,
        "count": 0,
        "total": 0,
        "row_count": 0,
        "columns": CNINFO_STOCK_ALLOTMENT_FIELDS,
    }
    stable = backfill._cninfo_stable_response_hash_values(values)
    receipt = backfill.CninfoRequestReceipt(
        schema_version="m3-g1-cninfo-receipt-v1",
        request_id=spec.request_id,
        source=CNINFO_SOURCE,
        endpoint=CNINFO_ENDPOINT,
        adapter=CNINFO_ADAPTER,
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
        count=0,
        total=0,
        raw_size_bytes=1,
        row_count=0,
        columns=CNINFO_STOCK_ALLOTMENT_FIELDS,
    )
    return VerifiedCninfoRawResponse(
        spec=spec,
        receipt=receipt,
        receipt_sha256=backfill._sha256(asdict(receipt)),
        frame=frame,
        resultcode=200,
        count=0,
        total=0,
    )


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
        mapper_version="m3-g1-tushare-mapper-v5",
        schema_version="m3-g1-schema-v3",
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
        cninfo_responses=tuple(
            _make_cninfo_verified(spec) for spec in plan.cninfo_rights_batch.requests
        ),
        cninfo_dividend_responses=tuple(
            _make_cninfo_ca_verified(spec) for spec in plan.cninfo_dividend_batch.requests
        ),
        cninfo_share_change_responses=tuple(
            _make_cninfo_ca_verified(spec) for spec in plan.cninfo_share_change_batch.requests
        ),
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
    Factors, factor-match evidence and reconciliation are trimmed to the
    remaining publish bar scopes so P0D audit bar-span/topology stay closed.
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
    bar_bounds: dict[str, tuple[dt.date, dt.date]] = {}
    for row in bars.iter_rows(named=True):
        symbol = row["symbol"]
        day = row["trade_date"]
        current = bar_bounds.get(symbol)
        if current is None:
            bar_bounds[symbol] = (day, day)
        else:
            first, last = current
            bar_bounds[symbol] = (min(first, day), max(last, day))
    factor_rows = []
    for row in candidate.adjustment_factors.iter_rows(named=True):
        span = bar_bounds.get(row["symbol"])
        if span is None:
            continue
        day = row["effective_date"]
        if span[0] <= day <= span[1]:
            factor_rows.append(row)
    factors = (
        pl.DataFrame(factor_rows)
        if factor_rows
        else candidate.adjustment_factors.clear()
    )
    match_rows = []
    bar_keys = {
        (row["symbol"], row["trade_date"], row["source"])
        for row in bars.iter_rows(named=True)
    }
    for row in candidate.factor_match_evidence.iter_rows(named=True):
        if (row["symbol"], row["trade_date"], row["source"]) in bar_keys:
            match_rows.append(row)
    matches = (
        pl.DataFrame(match_rows)
        if match_rows
        else candidate.factor_match_evidence.clear()
    )
    factor_dates_by_symbol: dict[str, list[dt.date]] = {}
    for row in factors.iter_rows(named=True):
        factor_dates_by_symbol.setdefault(row["symbol"], []).append(row["effective_date"])
    expected_recon: set[tuple[str, dt.date, dt.date]] = set()
    for symbol, dates in factor_dates_by_symbol.items():
        ordered = sorted(dates)
        for index in range(1, len(ordered)):
            expected_recon.add((symbol, ordered[index - 1], ordered[index]))
    recon_rows = [
        row
        for row in candidate.corporate_action_reconciliation.iter_rows(named=True)
        if (
            row["symbol"],
            row["previous_factor_date"],
            row["effective_date"],
        )
        in expected_recon
    ]
    recon = (
        pl.DataFrame(recon_rows)
        if recon_rows
        else candidate.corporate_action_reconciliation.clear()
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
    return _rebind_identity(
        candidate,
        bars=bars,
        adjustment_factors=factors,
        factor_match_evidence=matches,
        corporate_action_reconciliation=recon,
        suspensions=suspensions,
    )


@pytest.fixture(scope="module")
def happy_inputs(g1_reference_inputs) -> G1BuildInputs:
    return g1_reference_inputs


@pytest.fixture(scope="module")
def happy_candidate(g1_reference_baseline) -> G1Candidate:
    return g1_reference_baseline


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






# ===========================================================================
# 2. Sample plan: audit fail, <30 symbols, hash order stable, <20 dates
# ===========================================================================


















# ===========================================================================
# 3. Request plan/spec: parameters drift, symbol derivation, sorting
# ===========================================================================












def _sample_reference_frame(spec: ReferenceRequestSpec, day: dt.date) -> pl.DataFrame:
    code = ref._symbol_to_baostock_code(spec.symbol)
    row = {
        "date": day.isoformat(), "code": code, "open": "10.0", "high": "10.0", "low": "10.0",
        "close": "10.0", "volume": "1.0", "amount": "1.0", "adjustflag": "3", "tradestatus": "1",
    }
    return _reference_frame([row])








# ===========================================================================
# 4/5/6. Executor: plan-wide preflight, journal state machine, strict JSON
# ===========================================================================






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








































# ===========================================================================
# 7/8. reconcile_cross_source: sampling, tolerance, thresholds
# ===========================================================================




















# ===========================================================================
# 9. Bundle drift and wholesale re-run
# ===========================================================================






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










# ===========================================================================
# 10. Pure planners / reconcile perform zero IO / network
# ===========================================================================




# ===========================================================================
# 11. Unblock doc §5: cross-source issue codes and P4A audit regression
# ===========================================================================








# ===========================================================================
# General: error sanitization and package exports
# ===========================================================================
