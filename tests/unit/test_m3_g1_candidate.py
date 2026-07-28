"""G1-P4A: primary candidate rebuild and global primary-source audit."""

from __future__ import annotations

import datetime as dt
import socket
from dataclasses import asdict, replace
from typing import Any
from unittest.mock import patch

import polars as pl
import pytest

from quant.data import m3_backfill as backfill
from quant.data.m3_backfill import (
    TUSHARE_FIELDS,
    HistoryWindow,
    TushareRequestReceipt,
    TushareRequestSpec,
    VerifiedCninfoRawResponse,
    VerifiedRawResponse,
    cninfo_response_content_sha256,
    plan_index_weight_requests,
    response_content_sha256,
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
    M3G1CandidateError,
    _TABLE_ATTRS,
    _TABLE_NAMES,
    _TABLE_SCHEMAS,
    _canonical_eligible_keys,
    _primary_candidate_key,
    apply_adjustment_factors_strict,
    audit_g1_candidate,
    build_g1_candidate,
    project_scoped_adjustment_factors,
    verify_g1_candidate,
)
from quant.data.m3_identity import clean_table_content_sha256
from quant.data.storage import RawStore
from quant.research.m3.g1_planning import plan_g1_etf_history_requests

_HEX = "a" * 64
_UNIVERSE = "CSI300_TUSHARE_MONTHLY_OBSERVED_PIT_V1"
_INDEX = "000300.SH"
_BENCHMARK = "510300.SH"
_D0 = dt.date(2016, 2, 1)  # Mon signal
_D1 = dt.date(2016, 2, 2)  # Tue history end / price-limit coverage
_OBS_JAN = "20160129"
_OBS_FEB = "20160229"


def _symbols(n: int = 300) -> list[str]:
    out: list[str] = []
    for i in range(n):
        code = f"{i + 1:06d}"
        out.append(f"{code}.SZ" if i < 150 else f"{code}.SH")
    return out


def _weights(n: int = 300) -> list[float]:
    return [100.0 / n] * n


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


def _make_verified(
    endpoint: str,
    frame: pl.DataFrame,
    *,
    parameters: dict[str, str] | None = None,
) -> VerifiedRawResponse:
    params = {"fields": TUSHARE_FIELDS[endpoint], **(parameters or {})}
    if endpoint == "suspend_d":
        params.setdefault("suspend_type", "S")
    if endpoint == "fund_div":
        params.pop("start_date", None)
        params.pop("end_date", None)
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
    for col in (
        "stk_div",
        "stk_bo_rate",
        "stk_co_rate",
        "cash_div",
        "cash_div_tax",
        "base_share",
    ):
        schema[col] = pl.Float64
    return pl.DataFrame(schema=schema)


def _empty_suspend() -> pl.DataFrame:
    return pl.DataFrame(
        schema={c: pl.Utf8 for c in TUSHARE_FIELDS["suspend_d"].split(",")}
    )


def _full_day_suspend(symbol: str, day: dt.date) -> pl.DataFrame:
    return pl.DataFrame(
        [
            {
                "ts_code": symbol,
                "trade_date": day.strftime("%Y%m%d"),
                "suspend_timing": None,
                "suspend_type": "S",
            }
        ]
    ).select(TUSHARE_FIELDS["suspend_d"].split(","))



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
        mapper_version="m3-g1-tushare-mapper-v4",
        schema_version="m3-g1-schema-v2",
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


def _build_inputs(
    *,
    symbols: list[str] | None = None,
    shuffle_responses: bool = False,
    mutate_daily_close: float | None = None,
    include_extra_response: bool = False,
    drop_one_response: bool = False,
    duplicate_response: bool = False,
) -> G1BuildInputs:
    syms = list(symbols) if symbols is not None else _symbols()
    days = [_D0, _D1]
    history = HistoryWindow(_D0, _D1)
    weight_batch = plan_index_weight_requests(
        index_code=_INDEX,
        start=_D0,
        end=_D0,
        warmup_months=1,
    )
    plan = plan_g1_etf_history_requests(
        index_weight_batch=weight_batch,
        symbols=syms,
        history=history,
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
        daily = _daily_frame(symbol, days)
        if mutate_daily_close is not None and symbol == sorted(set(syms))[0]:
            price = float(mutate_daily_close)
            daily = daily.with_columns(
                pl.lit(price).alias("open"),
                pl.lit(price).alias("high"),
                pl.lit(price).alias("low"),
                pl.lit(price).alias("close"),
            )
        responses.append(
            _make_verified(
                "daily",
                daily,
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
            _make_verified(
                "dividend",
                _empty_dividend(symbol),
                parameters={"ts_code": symbol},
            )
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
        responses.append(
            _make_verified(
                "suspend_d",
                _empty_suspend(),
                parameters={
                    "ts_code": params["ts_code"],
                    "start_date": params["start_date"],
                    "end_date": params["end_date"],
                    "suspend_type": params["suspend_type"],
                },
            )
        )

    by_id = {item.spec.request_id: item for item in responses}
    ordered = [by_id[spec.request_id] for spec in plan.index_weight_batch.requests] + [
        by_id[spec.request_id] for spec in plan.history_batch.requests
    ]
    if shuffle_responses:
        ordered = list(reversed(ordered))
    if drop_one_response:
        ordered = ordered[:-1]
    if duplicate_response:
        ordered = ordered + [ordered[0]]
    if include_extra_response:
        extra = _make_verified(
            "daily",
            _daily_frame(syms[0], days),
            parameters={
                "ts_code": "999999.SH",
                "start_date": _D0.strftime("%Y%m%d"),
                "end_date": _D1.strftime("%Y%m%d"),
            },
        )
        ordered = ordered + [extra]

    return G1BuildInputs(
        build_spec=_build_spec(),
        request_plan=plan,
        responses=tuple(ordered),
        cninfo_responses=tuple(
            _make_cninfo_verified(spec) for spec in plan.cninfo_rights_batch.requests
        ),
        calendars=_calendar(dt.date(2016, 1, 1), dt.date(2016, 3, 10)),
        instruments=_instruments(syms),
        universe=_UNIVERSE,
        signal_start=_D0,
        signal_end=_D0,
        history=history,
        expected_constituent_count=300,
        factor_ratio_rtol=0.001,
    )


@pytest.fixture(scope="module")
def happy_inputs() -> G1BuildInputs:
    return _build_inputs()


@pytest.fixture(scope="module")
def happy_candidate(happy_inputs: G1BuildInputs) -> G1Candidate:
    return build_g1_candidate(inputs=happy_inputs)


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
        "corporate_action_selection_evidence": (
            candidate.corporate_action_selection_evidence
        ),
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
        (
            name,
            clean_table_content_sha256(
                table_name=name, frame=values[_TABLE_ATTRS[name]]
            ),
        )
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


def _assert_identity_reject(excinfo: pytest.ExceptionInfo[BaseException]) -> None:
    err = excinfo.value
    assert isinstance(err, M3G1CandidateError)
    assert err.code == "G1_CANDIDATE_IDENTITY_MISMATCH"
    assert err.__cause__ is None
    text = f"{err}{err!s}{err!r}"
    assert "/home/" not in text
    assert "token" not in text.lower()


def test_happy_path_build_verify_audit(
    happy_inputs: G1BuildInputs, happy_candidate: G1Candidate
) -> None:
    verify_g1_candidate(inputs=happy_inputs, candidate=happy_candidate)
    audit = audit_g1_candidate(candidate=happy_candidate)
    assert audit.passed is True
    assert audit.issues == ()
    assert happy_candidate.primary_candidate_key == audit.primary_candidate_key
    assert len(happy_candidate.table_content_digests) == 14
    assert [name for name, _ in happy_candidate.table_content_digests] == sorted(
        name for name, _ in happy_candidate.table_content_digests
    )
    assert happy_candidate.eligible_keys.filter(pl.col("as_of") == _D0).height == 300


def test_response_order_and_frame_row_order_stable_identity(
    happy_inputs: G1BuildInputs, happy_candidate: G1Candidate
) -> None:
    shuffled = _build_inputs(shuffle_responses=True)
    candidate2 = build_g1_candidate(inputs=shuffled)
    assert candidate2.primary_candidate_key == happy_candidate.primary_candidate_key
    # Shuffle clean frame rows; rebuild identity via digests stays same.
    bars_shuffled = happy_candidate.bars.reverse()
    digest_a = clean_table_content_sha256(table_name="bar_1d", frame=happy_candidate.bars)
    digest_b = clean_table_content_sha256(table_name="bar_1d", frame=bars_shuffled)
    assert digest_a == digest_b


def test_price_change_changes_primary_key(happy_candidate: G1Candidate) -> None:
    mutated = _build_inputs(mutate_daily_close=10.5)
    other = build_g1_candidate(inputs=mutated)
    assert other.primary_candidate_key != happy_candidate.primary_candidate_key


def test_calendar_list_date_change_changes_primary_key(
    happy_inputs: G1BuildInputs, happy_candidate: G1Candidate
) -> None:
    instruments = happy_inputs.instruments.with_columns(
        pl.when(pl.col("symbol") == happy_inputs.instruments["symbol"][0])
        .then(pl.lit(dt.date(2010, 1, 5)))
        .otherwise(pl.col("list_date"))
        .alias("list_date")
    )
    altered = G1BuildInputs(
        build_spec=happy_inputs.build_spec,
        request_plan=happy_inputs.request_plan,
        responses=happy_inputs.responses,
        cninfo_responses=happy_inputs.cninfo_responses,
        calendars=happy_inputs.calendars,
        instruments=instruments,
        universe=happy_inputs.universe,
        signal_start=happy_inputs.signal_start,
        signal_end=happy_inputs.signal_end,
        history=happy_inputs.history,
        expected_constituent_count=happy_inputs.expected_constituent_count,
        factor_ratio_rtol=happy_inputs.factor_ratio_rtol,
    )
    other = build_g1_candidate(inputs=altered)
    assert other.primary_candidate_key != happy_candidate.primary_candidate_key


@pytest.mark.parametrize(
    "kwargs,code",
    [
        ({"drop_one_response": True}, "G1_CANDIDATE_PLAN_RESPONSE_MISMATCH"),
        ({"include_extra_response": True}, "G1_CANDIDATE_PLAN_RESPONSE_MISMATCH"),
        ({"duplicate_response": True}, "G1_CANDIDATE_PLAN_RESPONSE_MISMATCH"),
    ],
)
def test_response_multiset_mismatch(kwargs: dict[str, bool], code: str) -> None:
    with pytest.raises(M3G1CandidateError) as excinfo:
        build_g1_candidate(inputs=_build_inputs(**kwargs))
    assert excinfo.value.code == code
    assert excinfo.value.__cause__ is None


def test_frame_receipt_spec_drift(happy_inputs: G1BuildInputs) -> None:
    first = happy_inputs.responses[0]
    poisoned_frame = first.frame.with_columns(pl.lit(99.0).alias("weight"))
    with pytest.raises(ValueError):
        VerifiedRawResponse(
            first.spec, first.receipt, first.receipt_sha256, poisoned_frame
        )
    # Spec endpoint/parameters drift against plan is caught at build time.
    alien = _make_verified(
        "daily",
        _daily_frame(_symbols()[0], [_D0, _D1]),
        parameters={
            "ts_code": _symbols()[0],
            "start_date": _D0.strftime("%Y%m%d"),
            "end_date": _D1.strftime("%Y%m%d"),
        },
    )
    responses = list(happy_inputs.responses)
    responses[0] = alien
    with pytest.raises(M3G1CandidateError) as excinfo:
        build_g1_candidate(
            inputs=G1BuildInputs(
                build_spec=happy_inputs.build_spec,
                request_plan=happy_inputs.request_plan,
                responses=tuple(responses),
        cninfo_responses=happy_inputs.cninfo_responses,
                calendars=happy_inputs.calendars,
                instruments=happy_inputs.instruments,
                universe=happy_inputs.universe,
                signal_start=happy_inputs.signal_start,
                signal_end=happy_inputs.signal_end,
                history=happy_inputs.history,
                expected_constituent_count=happy_inputs.expected_constituent_count,
                factor_ratio_rtol=happy_inputs.factor_ratio_rtol,
            )
        )
    assert excinfo.value.code == "G1_CANDIDATE_PLAN_RESPONSE_MISMATCH"


def test_factor_missing_duplicate_nonpositive_and_lineage(
    happy_inputs: G1BuildInputs, happy_candidate: G1Candidate
) -> None:
    daily = [
        item for item in happy_inputs.responses if item.spec.endpoint == "daily"
    ][:1]
    factors = [
        item for item in happy_inputs.responses if item.spec.endpoint == "adj_factor"
    ][:1]
    symbol = dict(daily[0].spec.parameters)["ts_code"]
    bars = happy_candidate.bars.filter(pl.col("symbol") == symbol).drop("adj_factor")
    factors_frame = happy_candidate.adjustment_factors.filter(
        pl.col("symbol") == symbol
    )

    # Missing factor date.
    with pytest.raises(M3G1CandidateError) as missing:
        apply_adjustment_factors_strict(
            bars=bars,
            adjustment_factors=factors_frame.head(1),
            daily_responses=daily,
            factor_responses=factors,
        )
    assert missing.value.code == "G1_CANDIDATE_COMPONENT_INVALID"

    # Non-positive factor.
    bad_factor = factors_frame.with_columns(pl.lit(-1.0).alias("adj_factor"))
    with pytest.raises(M3G1CandidateError):
        apply_adjustment_factors_strict(
            bars=bars,
            adjustment_factors=bad_factor,
            daily_responses=daily,
            factor_responses=factors,
        )

    # Duplicate factor key.
    dup = pl.concat([factors_frame, factors_frame])
    with pytest.raises(M3G1CandidateError):
        apply_adjustment_factors_strict(
            bars=bars,
            adjustment_factors=dup,
            daily_responses=daily,
            factor_responses=factors,
        )

    # Wrong stable digest lineage: receipt self-check rejects before apply.
    factor_resp = factors[0]
    with pytest.raises(ValueError):
        replace(factor_resp.receipt, stable_response_sha256="b" * 64)


def test_factor_only_date_does_not_create_bar_or_match(
    happy_candidate: G1Candidate,
) -> None:
    symbol = _symbols()[0]
    daily_response = _make_verified(
        "daily",
        _daily_frame(symbol, [_D1]),
        parameters={
            "ts_code": symbol,
            "start_date": _D0.strftime("%Y%m%d"),
            "end_date": _D1.strftime("%Y%m%d"),
        },
    )
    factor_response = _make_verified(
        "adj_factor",
        _factor_frame(symbol, [_D0, _D1]),
        parameters={
            "ts_code": symbol,
            "start_date": _D0.strftime("%Y%m%d"),
            "end_date": _D1.strftime("%Y%m%d"),
        },
    )
    bars = happy_candidate.bars.filter(
        (pl.col("symbol") == symbol) & (pl.col("trade_date") == _D1)
    ).drop("adj_factor")
    factors = happy_candidate.adjustment_factors.filter(pl.col("symbol") == symbol)

    applied = apply_adjustment_factors_strict(
        bars=bars,
        adjustment_factors=factors,
        daily_responses=[daily_response],
        factor_responses=[factor_response],
    )

    assert applied.bars.get_column("trade_date").to_list() == [_D1]
    assert applied.factor_match_evidence.get_column("trade_date").to_list() == [_D1]
    assert factors.get_column("effective_date").to_list() == [_D0, _D1]


def test_full_day_suspension_allows_factor_without_daily_bar(
    happy_inputs: G1BuildInputs,
) -> None:
    symbol = _symbols()[0]
    replacements: list[VerifiedRawResponse] = []
    for item in happy_inputs.responses:
        params = dict(item.spec.parameters)
        endpoint = item.spec.endpoint
        if params.get("ts_code") != symbol:
            replacements.append(item)
            continue
        request_params = {key: value for key, value in params.items() if key != "fields"}
        if endpoint == "daily":
            replacement = _make_verified(
                "daily", _daily_frame(symbol, [_D1]), parameters=request_params
            )
        elif endpoint == "suspend_d":
            replacement = _make_verified(
                "suspend_d",
                _full_day_suspend(symbol, _D0),
                parameters=request_params,
            )
        else:
            replacements.append(item)
            continue
        assert replacement.spec == item.spec
        replacements.append(replacement)

    inputs = replace(happy_inputs, responses=tuple(replacements))
    candidate = build_g1_candidate(inputs=inputs)
    verify_g1_candidate(inputs=inputs, candidate=candidate)
    audit = audit_g1_candidate(candidate=candidate)

    assert audit.passed is True
    assert candidate.bars.filter(pl.col("symbol") == symbol).get_column(
        "trade_date"
    ).to_list() == [_D1]
    # D0 is strictly before first_bar; publish-scoped factors keep only D1.
    assert candidate.adjustment_factors.filter(pl.col("symbol") == symbol).get_column(
        "effective_date"
    ).to_list() == [_D1]
    assert candidate.factor_match_evidence.filter(
        pl.col("symbol") == symbol
    ).get_column("trade_date").to_list() == [_D1]
    suspension = candidate.suspensions.filter(pl.col("symbol") == symbol)
    assert suspension.get_column("trade_date").to_list() == [_D0]
    assert suspension.get_column("suspension_scope").to_list() == ["FULL_DAY"]


def test_eligible_bar_suspension_rules(
    happy_inputs: G1BuildInputs, happy_candidate: G1Candidate
) -> None:
    symbol = happy_candidate.eligible_keys["symbol"][0]
    # Remove bar for one eligible key; rebind identity so audit (not constructor) fires.
    bars = happy_candidate.bars.filter(
        ~((pl.col("symbol") == symbol) & (pl.col("trade_date") == _D0))
    )
    damaged = _rebind_identity(happy_candidate, bars=bars)
    audit = audit_g1_candidate(candidate=damaged)
    assert audit.passed is False
    assert any(issue.code == "BAR_OR_SUSPENSION_MISSING" for issue in audit.issues)

    # Both bar and FULL_DAY.
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
        ]
    )
    conflicted = _rebind_identity(happy_candidate, suspensions=suspensions)
    audit2 = audit_g1_candidate(candidate=conflicted)
    assert any(issue.code == "BAR_FULL_SUSPENSION_CONFLICT" for issue in audit2.issues)

    # PARTIAL without bar.
    partial = pl.DataFrame(
        [
            {
                "symbol": symbol,
                "trade_date": _D0,
                "suspension_scope": "PARTIAL",
                "suspension_detail": "09:30-10:00",
                "source": "tushare",
                "source_snapshot_id": _HEX,
            }
        ]
    )
    no_bar = _rebind_identity(happy_candidate, bars=bars, suspensions=partial)
    audit3 = audit_g1_candidate(candidate=no_bar)
    assert any(
        issue.code == "PARTIAL_SUSPENSION_BAR_MISSING" for issue in audit3.issues
    )


def test_membership_count_calendar_unknown_and_benchmark(
    happy_inputs: G1BuildInputs, happy_candidate: G1Candidate
) -> None:
    # Artificial 299 (not produced by authoritative builder) must fail audit.
    eligible_299 = happy_candidate.eligible_keys.head(299)
    bad_299 = _rebind_identity(happy_candidate, eligible_keys=eligible_299)
    audit_299 = audit_g1_candidate(candidate=bad_299)
    assert audit_299.passed is False
    assert any(issue.code == "MEMBERSHIP_COUNT_MISMATCH" for issue in audit_299.issues)

    # eligible_keys rebound to head(1) with synced digests/primary must fail.
    eligible_1 = happy_candidate.eligible_keys.head(1)
    bad_1 = _rebind_identity(happy_candidate, eligible_keys=eligible_1)
    audit_1 = audit_g1_candidate(candidate=bad_1)
    assert audit_1.passed is False
    assert any(issue.code == "MEMBERSHIP_COUNT_MISMATCH" for issue in audit_1.issues)
    assert bad_1.eligible_keys.height == 1

    # Drop one non-lifecycle membership symbol (and its eligible rows) must fail.
    drop_symbol = happy_candidate.membership.sort(
        ["symbol", "effective_from"]
    )["symbol"][0]
    trimmed_membership = happy_candidate.membership.filter(
        pl.col("symbol") != drop_symbol
    )
    trimmed_eligible = happy_candidate.eligible_keys.filter(
        pl.col("symbol") != drop_symbol
    )
    bad_drop = _rebind_identity(
        happy_candidate,
        membership=trimmed_membership,
        eligible_keys=trimmed_eligible,
    )
    audit_drop = audit_g1_candidate(candidate=bad_drop)
    assert audit_drop.passed is False
    assert any(
        issue.code == "MEMBERSHIP_COUNT_MISMATCH" for issue in audit_drop.issues
    )

    # SH/SZ is_open divergence: stale digests must fail at constructor.
    calendars = happy_inputs.calendars.with_columns(
        pl.when(
            (pl.col("market") == "SZ") & (pl.col("date") == _D0)
        )
        .then(pl.lit(False))
        .otherwise(pl.col("is_open"))
        .alias("is_open")
    )
    with pytest.raises(M3G1CandidateError) as cal_exc:
        replace(happy_candidate, calendars=calendars)
    _assert_identity_reject(cal_exc)

    # Unknown instrument symbol on bar with stale digests -> constructor rejects.
    bars = happy_candidate.bars.with_columns(
        pl.when(pl.col("symbol") == happy_candidate.bars["symbol"][0])
        .then(pl.lit("999999.SH"))
        .otherwise(pl.col("symbol"))
        .alias("symbol")
    )
    with pytest.raises(M3G1CandidateError) as bar_exc:
        replace(happy_candidate, bars=bars)
    assert bar_exc.value.code in {
        "G1_CANDIDATE_IDENTITY_MISMATCH",
        "G1_CANDIDATE_INPUT_INVALID",
    }
    assert bar_exc.value.__cause__ is None

    # Benchmark missing history day with rebound identity -> audit.
    bench = happy_candidate.benchmark_bars.filter(pl.col("trade_date") != _D1)
    bench_damaged = _rebind_identity(happy_candidate, benchmark_bars=bench)
    audit4 = audit_g1_candidate(candidate=bench_damaged)
    assert any(issue.code == "BENCHMARK_MISSING" for issue in audit4.issues)


def test_price_limit_and_corporate_action_drift(
    happy_candidate: G1Candidate,
) -> None:
    # Drop a required price-limit row with stale digests -> constructor rejects.
    if happy_candidate.price_limits.height:
        limits = happy_candidate.price_limits.head(
            max(happy_candidate.price_limits.height - 1, 0)
        )
        with pytest.raises(M3G1CandidateError) as lim_exc:
            replace(happy_candidate, price_limits=limits)
        _assert_identity_reject(lim_exc)

    # Drift reconciliation digest while keeping frame -> constructor rejects.
    digests = list(happy_candidate.table_content_digests)
    idx = [name for name, _ in digests].index("corporate_action_reconciliation")
    digests[idx] = ("corporate_action_reconciliation", "c" * 64)
    with pytest.raises(M3G1CandidateError) as dig_exc:
        replace(happy_candidate, table_content_digests=tuple(digests))
    _assert_identity_reject(dig_exc)


def test_constructor_rejects_primary_key_replace(
    happy_candidate: G1Candidate,
) -> None:
    with pytest.raises(M3G1CandidateError) as excinfo:
        replace(happy_candidate, primary_candidate_key="f" * 64)
    _assert_identity_reject(excinfo)
    # Direct constructor path with same attack.
    kwargs = {
        field: getattr(happy_candidate, field)
        for field in happy_candidate.__dataclass_fields__
    }
    kwargs["primary_candidate_key"] = "f" * 64
    with pytest.raises(M3G1CandidateError) as excinfo2:
        G1Candidate(**kwargs)
    _assert_identity_reject(excinfo2)


@pytest.mark.parametrize("table_name", list(_TABLE_NAMES))
def test_constructor_rejects_per_table_frame_drift(
    happy_candidate: G1Candidate, table_name: str
) -> None:
    attr = _TABLE_ATTRS[table_name]
    frame = getattr(happy_candidate, attr)
    symbol0 = happy_candidate.instruments["symbol"][0]
    if frame.height == 0 and table_name == "suspension_1d":
        mutated = pl.DataFrame(
            [
                {
                    "symbol": symbol0,
                    "trade_date": _D0,
                    "suspension_scope": "FULL_DAY",
                    "suspension_detail": None,
                    "source": "tushare",
                    "source_snapshot_id": _HEX,
                }
            ]
        )
    elif frame.height == 0 and table_name == "corporate_action_ledger":
        mutated = pl.DataFrame(
            [
                {
                    "event_id": "b" * 64,
                    "symbol": symbol0,
                    "ex_date": _D1,
                    "cash_per_share_gross": 0.1,
                    "stock_ratio": 0.0,
                    "record_date": _D0,
                    "pay_date": _D1,
                    "stock_list_date": None,
                    "source": "tushare",
                    "source_snapshot_id": _HEX,
                }
            ]
        )
    elif frame.height == 0 and table_name == "corporate_action_selection_evidence":
        mutated = pl.DataFrame(
            [
                {
                    "economic_event_key_sha256": "c" * 64,
                    "candidate_id": "d" * 64,
                    "symbol": symbol0,
                    "end_date": dt.date(2015, 12, 31),
                    "record_date": _D0,
                    "ex_date": _D1,
                    "imp_ann_date": _D0,
                    "ann_date": _D0,
                    "cash_per_share_gross": 0.1,
                    "stock_ratio": 0.0,
                    "pay_date": _D1,
                    "stock_list_date": None,
                    "candidate_rank": 1,
                    "candidate_count": 1,
                    "raw_row_count": 1,
                    "selected": True,
                    "selection_reason": "SELECTED_LATEST",
                    "source": "tushare",
                    "source_request_id": _HEX,
                    "source_snapshot_id": _HEX,
                }
            ]
        )
    elif table_name == "eligible_keys":
        mutated = frame.with_columns(
            pl.when(pl.col("symbol") == frame["symbol"][0])
            .then(pl.lit("999998.SH"))
            .otherwise(pl.col("symbol"))
            .alias("symbol")
        )
    elif table_name == "instrument":
        mutated = frame.with_columns(
            pl.when(pl.col("symbol") == frame["symbol"][0])
            .then(pl.lit(dt.date(2011, 1, 4)))
            .otherwise(pl.col("list_date"))
            .alias("list_date")
        )
    elif table_name == "trade_calendar":
        target = frame.filter(pl.col("is_open"))["date"][0]
        mutated = frame.with_columns(
            pl.when((pl.col("market") == "SH") & (pl.col("date") == target))
            .then(pl.lit(False))
            .otherwise(pl.col("is_open"))
            .alias("is_open")
        )
    elif table_name == "universe_membership":
        mutated = frame.with_columns(
            pl.when(pl.int_range(0, pl.len()) == 0)
            .then(pl.col("effective_from").dt.offset_by("1d"))
            .otherwise(pl.col("effective_from"))
            .alias("effective_from")
        )
    elif "adj_factor" in frame.columns:
        mutated = frame.with_columns(
            pl.when(pl.int_range(0, pl.len()) == 0)
            .then(pl.col("adj_factor") + 0.0001)
            .otherwise(pl.col("adj_factor"))
            .alias("adj_factor")
        )
    elif "close" in frame.columns:
        mutated = frame.with_columns(
            pl.when(pl.int_range(0, pl.len()) == 0)
            .then(pl.col("close") + 0.01)
            .otherwise(pl.col("close"))
            .alias("close")
        )
    elif "weight" in frame.columns:
        mutated = frame.with_columns(
            pl.when(pl.int_range(0, pl.len()) == 0)
            .then(pl.col("weight") + 0.0001)
            .otherwise(pl.col("weight"))
            .alias("weight")
        )
    elif "pre_close" in frame.columns:
        mutated = frame.with_columns(
            pl.when(pl.int_range(0, pl.len()) == 0)
            .then(pl.col("pre_close") + 0.01)
            .otherwise(pl.col("pre_close"))
            .alias("pre_close")
        )
    elif "event_ids_json" in frame.columns:
        mutated = frame.with_columns(
            pl.when(pl.int_range(0, pl.len()) == 0)
            .then(pl.lit("[\"eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee\"]"))
            .otherwise(pl.col("event_ids_json"))
            .alias("event_ids_json")
        )
    elif "cash_per_share_gross" in frame.columns:
        mutated = frame.with_columns(
            pl.when(pl.int_range(0, pl.len()) == 0)
            .then(pl.col("cash_per_share_gross") + 0.01)
            .otherwise(pl.col("cash_per_share_gross"))
            .alias("cash_per_share_gross")
        )
    else:
        mutated = frame.head(max(frame.height - 1, 1))

    with pytest.raises(M3G1CandidateError) as replace_exc:
        replace(happy_candidate, **{attr: mutated})
    assert replace_exc.value.code in {
        "G1_CANDIDATE_IDENTITY_MISMATCH",
        "G1_CANDIDATE_INPUT_INVALID",
    }
    assert replace_exc.value.__cause__ is None

    kwargs = {
        field: getattr(happy_candidate, field)
        for field in happy_candidate.__dataclass_fields__
    }
    kwargs[attr] = mutated
    with pytest.raises(M3G1CandidateError) as ctor_exc:
        G1Candidate(**kwargs)
    assert ctor_exc.value.code in {
        "G1_CANDIDATE_IDENTITY_MISMATCH",
        "G1_CANDIDATE_INPUT_INVALID",
    }
    assert ctor_exc.value.__cause__ is None


def test_constructor_rejects_digest_only_and_required_key_drift(
    happy_candidate: G1Candidate,
) -> None:
    digests = list(happy_candidate.table_content_digests)
    digests[0] = (digests[0][0], "d" * 64)
    base_kwargs = {
        field: getattr(happy_candidate, field)
        for field in happy_candidate.__dataclass_fields__
    }

    # Sync primary key to a different hex but frames unchanged.
    with pytest.raises(M3G1CandidateError) as exc1:
        replace(
            happy_candidate,
            table_content_digests=tuple(digests),
            primary_candidate_key="e" * 64,
        )
    _assert_identity_reject(exc1)
    with pytest.raises(M3G1CandidateError) as exc1b:
        G1Candidate(
            **{
                **base_kwargs,
                "table_content_digests": tuple(digests),
                "primary_candidate_key": "e" * 64,
            }
        )
    _assert_identity_reject(exc1b)

    with pytest.raises(M3G1CandidateError) as exc2:
        replace(happy_candidate, price_limit_required_keys_sha256="c" * 64)
    _assert_identity_reject(exc2)
    with pytest.raises(M3G1CandidateError) as exc2b:
        G1Candidate(
            **{**base_kwargs, "price_limit_required_keys_sha256": "c" * 64}
        )
    _assert_identity_reject(exc2b)

    # Sync required digest + primary key while required domain unchanged.
    with pytest.raises(M3G1CandidateError) as exc3:
        replace(
            happy_candidate,
            price_limit_required_keys_sha256="c" * 64,
            primary_candidate_key="e" * 64,
        )
    _assert_identity_reject(exc3)
    with pytest.raises(M3G1CandidateError) as exc3b:
        G1Candidate(
            **{
                **base_kwargs,
                "price_limit_required_keys_sha256": "c" * 64,
                "primary_candidate_key": "e" * 64,
            }
        )
    _assert_identity_reject(exc3b)


def test_constructor_coercion_writeback_and_lossy_reject(
    happy_candidate: G1Candidate,
) -> None:
    # Safe coercion: Utf8 dates for eligible as_of if castable.
    eligible = happy_candidate.eligible_keys.with_columns(
        pl.col("as_of").cast(pl.Utf8).alias("as_of")
    )
    coerced = replace(happy_candidate, eligible_keys=eligible)
    assert coerced.eligible_keys.schema["as_of"] == pl.Date
    assert coerced.primary_candidate_key == happy_candidate.primary_candidate_key

    # Lossy / non-coercible: list-typed symbol column.
    bad = happy_candidate.eligible_keys.with_columns(
        pl.col("symbol").map_elements(lambda s: [s], return_dtype=pl.List(pl.Utf8))
        .alias("symbol")
    )
    with pytest.raises(M3G1CandidateError) as excinfo:
        replace(happy_candidate, eligible_keys=bad)
    assert excinfo.value.code == "G1_CANDIDATE_INPUT_INVALID"
    assert excinfo.value.__cause__ is None


def test_wholesale_candidate_replacement_fails_verify(
    happy_inputs: G1BuildInputs, happy_candidate: G1Candidate
) -> None:
    other = build_g1_candidate(inputs=_build_inputs(mutate_daily_close=11.0))
    # Pretend attacker synced all digests/identity of another valid candidate.
    with pytest.raises(M3G1CandidateError) as excinfo:
        verify_g1_candidate(inputs=happy_inputs, candidate=other)
    assert excinfo.value.code == "G1_CANDIDATE_IDENTITY_MISMATCH"


def test_exception_surfaces_are_sanitized() -> None:
    err = M3G1CandidateError("G1_CANDIDATE_INPUT_INVALID")
    text = f"{err}{err!s}{err!r}{err.__cause__}"
    assert "/home/" not in text
    assert "token" not in text.lower()
    assert "Tushare" not in text
    assert err.__cause__ is None


def test_no_file_or_network_io_during_build(happy_inputs: G1BuildInputs) -> None:
    import builtins

    real_open = builtins.open

    def guarded_open(file: object, *args: object, **kwargs: object) -> object:
        path = str(file).replace("\\", "/").lower()
        forbidden = (
            "/data/raw/",
            "/data/clean/",
            "/journal/",
            ".parquet",
            "releases/",
        )
        if any(token in path for token in forbidden):
            raise AssertionError("open called on data path")
        return real_open(file, *args, **kwargs)  # type: ignore[arg-type]

    with (
        patch("builtins.open", side_effect=guarded_open),
        patch.object(socket.socket, "connect", side_effect=AssertionError("socket")),
        patch.object(RawStore, "write", side_effect=AssertionError("raw write")),
        patch.object(
            RawStore, "write_request", side_effect=AssertionError("raw write_request")
        ),
    ):
        candidate = build_g1_candidate(inputs=happy_inputs)
        verify_g1_candidate(inputs=happy_inputs, candidate=candidate)
        audit = audit_g1_candidate(candidate=candidate)
        assert audit.passed is True


def _rebuild_inputs_with_suspend_specs(
    inputs: G1BuildInputs,
    suspend_specs: list[TushareRequestSpec],
) -> G1BuildInputs:
    """Rebuild plan/responses so only suspend_d specs differ; multiset stays closed."""
    history_requests = [
        spec
        for spec in inputs.request_plan.history_batch.requests
        if spec.endpoint != "suspend_d"
    ] + list(suspend_specs)
    history_batch = backfill._make_batch("HISTORY", history_requests)
    plan = backfill.G1RequestPlan(
        "m3-g1-request-plan-v2",
        inputs.request_plan.index_weight_batch,
        history_batch,
        inputs.request_plan.cninfo_rights_batch,
        backfill._plan_hash(
            inputs.request_plan.index_weight_batch,
            history_batch,
            inputs.request_plan.cninfo_rights_batch,
        ),
    )
    non_suspend = [
        item for item in inputs.responses if item.spec.endpoint != "suspend_d"
    ]
    suspend_responses = [
        _make_verified(
            "suspend_d",
            _empty_suspend(),
            parameters={
                "ts_code": dict(spec.parameters)["ts_code"],
                "start_date": dict(spec.parameters)["start_date"],
                "end_date": dict(spec.parameters)["end_date"],
                "suspend_type": dict(spec.parameters)["suspend_type"],
            },
        )
        for spec in suspend_specs
    ]
    by_id = {item.spec.request_id: item for item in non_suspend + suspend_responses}
    ordered = [by_id[spec.request_id] for spec in plan.index_weight_batch.requests] + [
        by_id[spec.request_id] for spec in plan.history_batch.requests
    ]
    return G1BuildInputs(
        build_spec=inputs.build_spec,
        request_plan=plan,
        responses=tuple(ordered),
        cninfo_responses=inputs.cninfo_responses,
        instruments=inputs.instruments,
        universe=inputs.universe,
        signal_start=inputs.signal_start,
        signal_end=inputs.signal_end,
        history=inputs.history,
        expected_constituent_count=inputs.expected_constituent_count,
        factor_ratio_rtol=inputs.factor_ratio_rtol,
    )


def test_suspend_d_natural_month_window_rejected(
    happy_inputs: G1BuildInputs,
) -> None:
    """旧自然月 end 窗口不得被 candidate 接受。"""
    month_start = happy_inputs.history.start.replace(day=1)
    month_end = (month_start.replace(day=28) + dt.timedelta(days=4)).replace(
        day=1
    ) - dt.timedelta(days=1)
    assert month_end != happy_inputs.history.end
    monthly: list[TushareRequestSpec] = []
    for spec in happy_inputs.request_plan.history_batch.requests:
        if spec.endpoint != "suspend_d":
            continue
        params = dict(spec.parameters)
        monthly.append(
            TushareRequestSpec.create(
                endpoint="suspend_d",
                parameters={
                    "fields": TUSHARE_FIELDS["suspend_d"],
                    "ts_code": params["ts_code"],
                    "start_date": month_start.strftime("%Y%m%d"),
                    "end_date": month_end.strftime("%Y%m%d"),
                    "suspend_type": "S",
                },
            )
        )
    poisoned = _rebuild_inputs_with_suspend_specs(happy_inputs, monthly)
    with pytest.raises(M3G1CandidateError) as excinfo:
        build_g1_candidate(inputs=poisoned)
    assert excinfo.value.code == "G1_CANDIDATE_PLAN_RESPONSE_MISMATCH"
    assert excinfo.value.__cause__ is None


def test_suspend_d_missing_symbol_rejected(happy_inputs: G1BuildInputs) -> None:
    """缺任一 history_symbol 的 suspend_d 不得被 candidate 接受。"""
    suspend_specs = [
        spec
        for spec in happy_inputs.request_plan.history_batch.requests
        if spec.endpoint == "suspend_d"
    ]
    assert len(suspend_specs) >= 2
    poisoned = _rebuild_inputs_with_suspend_specs(happy_inputs, suspend_specs[1:])
    with pytest.raises(M3G1CandidateError) as excinfo:
        build_g1_candidate(inputs=poisoned)
    assert excinfo.value.code == "G1_CANDIDATE_PLAN_RESPONSE_MISMATCH"
    assert excinfo.value.__cause__ is None


def test_package_exports() -> None:
    import quant.data as qd

    assert qd.build_g1_candidate is build_g1_candidate
    assert qd.audit_g1_candidate is audit_g1_candidate
    assert qd.G1_MEMBERSHIP_METHOD_VERSION == G1_MEMBERSHIP_METHOD_VERSION


def test_p0d_versions_and_scoped_projection_bounds() -> None:
    assert G1_CORPORATE_ACTION_RECONCILIATION_VERSION == (
        "tushare_factor_daily_preclose_v5"
    )
    with pytest.raises(ValueError, match="corporate_action_reconciliation_version"):
        G1BuildSpec(
            config_version="m3-g1-test-v1",
            g1_config_sha256=_HEX,
            mapper_version="m3-g1-tushare-mapper-v4",
            schema_version="m3-g1-schema-v2",
            membership_method_version=G1_MEMBERSHIP_METHOD_VERSION,
            price_limit_method_version=G1_PRICE_LIMIT_METHOD_VERSION,
            corporate_action_selection_version=G1_CORPORATE_ACTION_SELECTION_VERSION,
            corporate_action_reconciliation_version="tushare_factor_daily_preclose_v3",
            benchmark_mode="TRADEABLE_ETF_TOTAL_RETURN_PROXY",
            benchmark_method_version="tushare_510300_fund_daily_fund_adj_hfq_v1",
            benchmark_dividend_reconciliation_version=(
                "tushare_fund_div_implemented_cash_v1"
            ),
            build_code_version="m3-g1-candidate-v1",
            dependency_fingerprint_sha256=_HEX,
        )
    d0 = dt.date(2016, 2, 1)
    d1 = dt.date(2016, 2, 2)
    d_halt = dt.date(2016, 2, 3)
    d2 = dt.date(2016, 2, 4)
    d3 = dt.date(2016, 2, 5)
    symbol = "000001.SZ"
    bars = pl.DataFrame(
        [
            {
                "symbol": symbol,
                "trade_date": day,
                "open": 10.0,
                "high": 10.0,
                "low": 10.0,
                "close": 10.0,
                "volume": 1.0,
                "amount": 1.0,
                "source": "tushare",
            }
            for day in (d1, d2)
        ]
    )
    factors = pl.DataFrame(
        [
            {
                "symbol": symbol,
                "effective_date": day,
                "adj_factor": 1.0 if day != d0 else 0.5,
                "source": "tushare",
            }
            for day in (d0, d1, d_halt, d2, d3)
        ]
    )
    # Input shuffle must not change scoped projection.
    scoped = project_scoped_adjustment_factors(
        bars=bars, adjustment_factors=factors.reverse()
    )
    # Inclusive bounds + keep mid-span suspension factor without a bar.
    assert scoped.get_column("effective_date").to_list() == [d1, d_halt, d2]
    assert scoped.get_column("adj_factor").to_list() == [1.0, 1.0, 1.0]
    assert d0 not in scoped.get_column("effective_date").to_list()
    assert d3 not in scoped.get_column("effective_date").to_list()


def test_p0d_build_excludes_pre_first_bar_factor_jump(
    happy_inputs: G1BuildInputs,
) -> None:
    """Structural 000553: pre-first-bar jump + ledger event must not fail build."""
    symbol = _symbols()[0]
    replacements: list[VerifiedRawResponse] = []
    for item in happy_inputs.responses:
        params = dict(item.spec.parameters)
        endpoint = item.spec.endpoint
        if params.get("ts_code") != symbol:
            replacements.append(item)
            continue
        request_params = {key: value for key, value in params.items() if key != "fields"}
        if endpoint == "daily":
            replacement = _make_verified(
                "daily", _daily_frame(symbol, [_D1]), parameters=request_params
            )
        elif endpoint == "adj_factor":
            # D0 factor 1.0 -> D1 factor 1.2 (~20% jump) plus ledger event on D0.
            frame = pl.DataFrame(
                [
                    {
                        "ts_code": symbol,
                        "trade_date": _D0.strftime("%Y%m%d"),
                        "adj_factor": 1.0,
                    },
                    {
                        "ts_code": symbol,
                        "trade_date": _D1.strftime("%Y%m%d"),
                        "adj_factor": 1.2,
                    },
                ]
            ).select(TUSHARE_FIELDS["adj_factor"].split(","))
            replacement = _make_verified(
                "adj_factor", frame, parameters=request_params
            )
        elif endpoint == "dividend":
            frame = pl.DataFrame(
                [
                    {
                        "ts_code": symbol,
                        "end_date": _D0.strftime("%Y%m%d"),
                        "ann_date": _D0.strftime("%Y%m%d"),
                        "div_proc": "实施",
                        "stk_div": 0.0,
                        "stk_bo_rate": None,
                        "stk_co_rate": None,
                        "cash_div": 0.1,
                        "cash_div_tax": 0.1,
                        "record_date": _D0.strftime("%Y%m%d"),
                        "ex_date": _D0.strftime("%Y%m%d"),
                        "pay_date": _D0.strftime("%Y%m%d"),
                        "div_listdate": None,
                        "imp_ann_date": _D0.strftime("%Y%m%d"),
                        "base_date": None,
                        "base_share": None,
                    }
                ]
            ).select(TUSHARE_FIELDS["dividend"].split(","))
            replacement = _make_verified(
                "dividend", frame, parameters=request_params
            )
        elif endpoint == "suspend_d":
            replacement = _make_verified(
                "suspend_d",
                _full_day_suspend(symbol, _D0),
                parameters=request_params,
            )
        else:
            replacements.append(item)
            continue
        assert replacement.spec == item.spec
        replacements.append(replacement)

    inputs = replace(happy_inputs, responses=tuple(replacements))
    candidate = build_g1_candidate(inputs=inputs)
    verify_g1_candidate(inputs=inputs, candidate=candidate)
    audit = audit_g1_candidate(candidate=candidate)
    assert audit.passed is True
    assert candidate.build_spec.mapper_version == "m3-g1-tushare-mapper-v4"
    assert (
        candidate.build_spec.corporate_action_reconciliation_version
        == "tushare_factor_daily_preclose_v5"
    )
    scoped = candidate.adjustment_factors.filter(pl.col("symbol") == symbol)
    assert scoped.get_column("effective_date").to_list() == [_D1]
    assert scoped.get_column("adj_factor").to_list() == [1.2]
    # Ledger may retain the pre-bar event; reconciliation must not include it.
    ledger = candidate.corporate_actions.filter(pl.col("symbol") == symbol)
    assert ledger.height >= 1
    assert ledger.filter(pl.col("ex_date") == _D0).height == 1
    recon = candidate.corporate_action_reconciliation.filter(
        pl.col("symbol") == symbol
    )
    assert recon.height == 0


def test_p0d_audit_rejects_restored_out_of_scope_factors(
    happy_inputs: G1BuildInputs,
) -> None:
    """Audit: self-contained bar-span check. Verify: rebuild from frozen inputs."""
    symbol = _symbols()[0]
    replacements: list[VerifiedRawResponse] = []
    for item in happy_inputs.responses:
        params = dict(item.spec.parameters)
        endpoint = item.spec.endpoint
        if params.get("ts_code") != symbol:
            replacements.append(item)
            continue
        request_params = {key: value for key, value in params.items() if key != "fields"}
        if endpoint == "daily":
            replacement = _make_verified(
                "daily", _daily_frame(symbol, [_D1]), parameters=request_params
            )
        elif endpoint == "suspend_d":
            replacement = _make_verified(
                "suspend_d",
                _full_day_suspend(symbol, _D0),
                parameters=request_params,
            )
        else:
            replacements.append(item)
            continue
        assert replacement.spec == item.spec
        replacements.append(replacement)
    inputs = replace(happy_inputs, responses=tuple(replacements))
    candidate = build_g1_candidate(inputs=inputs)
    assert candidate.adjustment_factors.filter(pl.col("symbol") == symbol).height == 1

    restored = pl.concat(
        [
            candidate.adjustment_factors,
            pl.DataFrame(
                [
                    {
                        "symbol": symbol,
                        "effective_date": _D0,
                        "adj_factor": 0.5,
                        "source": "tushare",
                    }
                ]
            ),
        ]
    ).sort(["symbol", "effective_date", "source"])
    attacked = _rebind_identity(candidate, adjustment_factors=restored)
    # audit_g1_candidate only sees candidate tables: reject out-of-span factors.
    audit = audit_g1_candidate(candidate=attacked)
    assert audit.passed is False
    assert any(
        issue.code == "FACTOR_INVALID"
        and "outside publish bar scope" in issue.message
        for issue in audit.issues
    )
    # verify_g1_candidate rebuilds scoped factors from frozen inputs and mismatches.
    with pytest.raises(M3G1CandidateError) as caught:
        verify_g1_candidate(inputs=inputs, candidate=attacked)
    assert caught.value.code == "G1_CANDIDATE_IDENTITY_MISMATCH"


def test_p0d_bar_missing_factor_and_lineage_still_fail(
    happy_inputs: G1BuildInputs, happy_candidate: G1Candidate
) -> None:
    symbol = _symbols()[0]
    factors = happy_candidate.adjustment_factors.filter(pl.col("symbol") == symbol)
    bars = happy_candidate.bars.filter(pl.col("symbol") == symbol).drop("adj_factor")
    daily = [
        item
        for item in happy_inputs.responses
        if item.spec.endpoint == "daily"
        and dict(item.spec.parameters).get("ts_code") == symbol
    ]
    factor_resps = [
        item
        for item in happy_inputs.responses
        if item.spec.endpoint == "adj_factor"
        and dict(item.spec.parameters).get("ts_code") == symbol
    ]
    with pytest.raises(M3G1CandidateError):
        apply_adjustment_factors_strict(
            bars=bars,
            adjustment_factors=factors.head(factors.height - 1),
            daily_responses=daily,
            factor_responses=factor_resps,
        )
    bad_factor = factors.with_columns(pl.lit(-1.0).alias("adj_factor"))
    with pytest.raises(M3G1CandidateError):
        apply_adjustment_factors_strict(
            bars=bars,
            adjustment_factors=bad_factor,
            daily_responses=daily,
            factor_responses=factor_resps,
        )


_D2 = dt.date(2016, 2, 3)  # Wed; mid-span halt day between D0 and D2 bars


def _assert_topology_mismatch(audit: Any) -> None:
    assert audit.passed is False
    assert any(
        issue.code == "CORPORATE_ACTION_FACTOR_MISMATCH"
        and "scoped factor transition topology mismatch" in issue.message
        for issue in audit.issues
    )


def _clone_no_event_recon_row(
    template: dict[str, Any],
    *,
    previous_factor_date: dt.date,
    effective_date: dt.date,
    actual_factor_ratio: float,
) -> dict[str, Any]:
    row = dict(template)
    row["previous_factor_date"] = previous_factor_date
    row["effective_date"] = effective_date
    row["actual_factor_ratio"] = actual_factor_ratio
    row["declared_dividend_relative_error"] = abs(actual_factor_ratio - 1.0)
    row["declared_dividend_factor_ratio"] = 1.0
    row["event_count"] = 0
    row["cash_per_share_gross"] = 0.0
    row["stock_ratio"] = 0.0
    row["previous_close_date"] = None
    row["previous_close"] = None
    row["ex_reference_price"] = None
    row["market_reference_factor_ratio"] = None
    row["market_reference_relative_error"] = None
    row["status"] = "NO_EVENT_STABLE_FACTOR"
    return row


def test_p0d_r1_audit_rejects_deleted_transition_evidence(
    happy_candidate: G1Candidate, happy_inputs: G1BuildInputs
) -> None:
    """Matrix 1: delete one scoped transition evidence → topology fail."""
    target = (
        happy_candidate.corporate_action_reconciliation.filter(
            (pl.col("symbol") == "000001.SZ")
            & (pl.col("previous_factor_date") == _D0)
            & (pl.col("effective_date") == _D1)
        )
    )
    assert target.height == 1
    trimmed = happy_candidate.corporate_action_reconciliation.filter(
        ~(
            (pl.col("symbol") == "000001.SZ")
            & (pl.col("previous_factor_date") == _D0)
            & (pl.col("effective_date") == _D1)
        )
    )
    attacked = _rebind_identity(
        happy_candidate, corporate_action_reconciliation=trimmed
    )
    _assert_topology_mismatch(audit_g1_candidate(candidate=attacked))
    with pytest.raises(M3G1CandidateError) as caught:
        verify_g1_candidate(inputs=happy_inputs, candidate=attacked)
    assert caught.value.code == "G1_CANDIDATE_IDENTITY_MISMATCH"


def test_p0d_r1_audit_rejects_non_adjacent_previous_date(
    happy_candidate: G1Candidate,
) -> None:
    """Matrix 2: previous_factor_date not the immediate prior factor day."""
    earlier = dt.date(2016, 1, 29)
    mutated = happy_candidate.corporate_action_reconciliation.with_columns(
        pl.when(
            (pl.col("symbol") == "000001.SZ")
            & (pl.col("previous_factor_date") == _D0)
            & (pl.col("effective_date") == _D1)
        )
        .then(pl.lit(earlier))
        .otherwise(pl.col("previous_factor_date"))
        .alias("previous_factor_date")
    )
    attacked = _rebind_identity(
        happy_candidate, corporate_action_reconciliation=mutated
    )
    _assert_topology_mismatch(audit_g1_candidate(candidate=attacked))


def test_p0d_r1_audit_rejects_extra_topology_evidence(
    happy_candidate: G1Candidate,
) -> None:
    """Matrix 3: schema-legal extra evidence outside expected topology."""
    template = happy_candidate.corporate_action_reconciliation.filter(
        pl.col("symbol") == "000001.SZ"
    ).to_dicts()[0]
    extra = _clone_no_event_recon_row(
        template,
        previous_factor_date=_D0,
        effective_date=dt.date(2016, 2, 5),
        actual_factor_ratio=1.0,
    )
    expanded = pl.concat(
        [
            happy_candidate.corporate_action_reconciliation,
            pl.DataFrame([extra]),
        ]
    ).sort(["symbol", "effective_date", "source"])
    attacked = _rebind_identity(
        happy_candidate, corporate_action_reconciliation=expanded
    )
    _assert_topology_mismatch(audit_g1_candidate(candidate=attacked))


def test_p0d_r1_audit_rejects_rewritten_actual_factor_ratio(
    happy_candidate: G1Candidate,
) -> None:
    """Matrix 4: sync formula fields; exact factor ratio bind still fails."""
    # Stay within NO_EVENT rtol so row-formula verify passes; topology exactness fails.
    rewritten = 1.0005
    mutated = happy_candidate.corporate_action_reconciliation.with_columns(
        pl.when(
            (pl.col("symbol") == "000001.SZ")
            & (pl.col("previous_factor_date") == _D0)
            & (pl.col("effective_date") == _D1)
        )
        .then(pl.lit(rewritten))
        .otherwise(pl.col("actual_factor_ratio"))
        .alias("actual_factor_ratio"),
        pl.when(
            (pl.col("symbol") == "000001.SZ")
            & (pl.col("previous_factor_date") == _D0)
            & (pl.col("effective_date") == _D1)
        )
        .then(pl.lit(abs(rewritten - 1.0)))
        .otherwise(pl.col("declared_dividend_relative_error"))
        .alias("declared_dividend_relative_error"),
    )
    attacked = _rebind_identity(
        happy_candidate, corporate_action_reconciliation=mutated
    )
    audit = audit_g1_candidate(candidate=attacked)
    _assert_topology_mismatch(audit)
    # Row-formula verify must not be the only failure mode for this attack.
    assert not any(
        issue.message == "reconciliation result failed verification"
        for issue in audit.issues
    )


def test_p0d_r1_single_scoped_factor_allows_empty_evidence(
    happy_inputs: G1BuildInputs,
) -> None:
    """Matrix 5: one scoped factor → zero transitions; empty evidence legal."""
    symbol = _symbols()[0]
    replacements: list[VerifiedRawResponse] = []
    for item in happy_inputs.responses:
        params = dict(item.spec.parameters)
        endpoint = item.spec.endpoint
        if params.get("ts_code") != symbol:
            replacements.append(item)
            continue
        request_params = {key: value for key, value in params.items() if key != "fields"}
        if endpoint == "daily":
            replacement = _make_verified(
                "daily", _daily_frame(symbol, [_D1]), parameters=request_params
            )
        elif endpoint == "suspend_d":
            replacement = _make_verified(
                "suspend_d",
                _full_day_suspend(symbol, _D0),
                parameters=request_params,
            )
        else:
            replacements.append(item)
            continue
        assert replacement.spec == item.spec
        replacements.append(replacement)
    inputs = replace(happy_inputs, responses=tuple(replacements))
    candidate = build_g1_candidate(inputs=inputs)
    scoped = candidate.adjustment_factors.filter(pl.col("symbol") == symbol)
    assert scoped.height == 1
    recon = candidate.corporate_action_reconciliation.filter(pl.col("symbol") == symbol)
    assert recon.height == 0
    audit = audit_g1_candidate(candidate=candidate)
    assert audit.passed is True
    assert audit.issues == ()


def _mid_halt_scoped_candidate(happy_candidate: G1Candidate) -> G1Candidate:
    """Bars on D0/D2 with mid-span D1 factor → two adjacent transitions."""
    symbol = "000001.SZ"
    d1_bar = happy_candidate.bars.filter(
        (pl.col("symbol") == symbol) & (pl.col("trade_date") == _D1)
    ).to_dicts()[0]
    d2_bar = dict(d1_bar)
    d2_bar["trade_date"] = _D2
    bars = pl.concat(
        [
            happy_candidate.bars.filter(
                ~((pl.col("symbol") == symbol) & (pl.col("trade_date") == _D1))
            ),
            pl.DataFrame([d2_bar]),
        ]
    ).sort(["symbol", "trade_date", "source"])

    factors = pl.concat(
        [
            happy_candidate.adjustment_factors,
            pl.DataFrame(
                [
                    {
                        "symbol": symbol,
                        "effective_date": _D2,
                        "adj_factor": 1.0,
                        "source": "tushare",
                    }
                ]
            ),
        ]
    ).sort(["symbol", "effective_date", "source"])

    d1_match = happy_candidate.factor_match_evidence.filter(
        (pl.col("symbol") == symbol) & (pl.col("trade_date") == _D1)
    ).to_dicts()[0]
    d2_match = dict(d1_match)
    d2_match["trade_date"] = _D2
    matches = pl.concat(
        [
            happy_candidate.factor_match_evidence.filter(
                ~((pl.col("symbol") == symbol) & (pl.col("trade_date") == _D1))
            ),
            pl.DataFrame([d2_match]),
        ]
    ).sort(["symbol", "trade_date", "source"])

    d1_limit = happy_candidate.price_limits.filter(
        (pl.col("symbol") == symbol) & (pl.col("trade_date") == _D1)
    ).to_dicts()[0]
    d2_limit = dict(d1_limit)
    d2_limit["trade_date"] = _D2
    limits = pl.concat(
        [
            happy_candidate.price_limits.filter(
                ~((pl.col("symbol") == symbol) & (pl.col("trade_date") == _D1))
            ),
            pl.DataFrame([d2_limit]),
        ]
    ).sort(["symbol", "trade_date", "source"])

    suspensions = pl.concat(
        [
            happy_candidate.suspensions,
            pl.DataFrame(
                [
                    {
                        "symbol": symbol,
                        "trade_date": _D1,
                        "suspension_scope": "FULL_DAY",
                        "suspension_detail": None,
                        "source": "tushare",
                        "source_snapshot_id": _HEX,
                    }
                ]
            ),
        ]
    ).sort(["symbol", "trade_date", "source"])

    bench_d1 = happy_candidate.benchmark_bars.filter(
        pl.col("trade_date") == _D1
    ).to_dicts()[0]
    bench_d2 = dict(bench_d1)
    bench_d2["trade_date"] = _D2
    benchmarks = pl.concat(
        [happy_candidate.benchmark_bars, pl.DataFrame([bench_d2])]
    ).sort(["benchmark", "trade_date", "source"])

    template = happy_candidate.corporate_action_reconciliation.filter(
        pl.col("symbol") == symbol
    ).to_dicts()[0]
    other_recon = happy_candidate.corporate_action_reconciliation.filter(
        pl.col("symbol") != symbol
    )
    recon = pl.concat(
        [
            other_recon,
            pl.DataFrame(
                [
                    _clone_no_event_recon_row(
                        template,
                        previous_factor_date=_D0,
                        effective_date=_D1,
                        actual_factor_ratio=1.0,
                    ),
                    _clone_no_event_recon_row(
                        template,
                        previous_factor_date=_D1,
                        effective_date=_D2,
                        actual_factor_ratio=1.0,
                    ),
                ]
            ),
        ]
    ).sort(["symbol", "effective_date", "source"])

    return _rebind_identity(
        happy_candidate,
        history_end=_D2,
        bars=bars,
        adjustment_factors=factors,
        factor_match_evidence=matches,
        price_limits=limits,
        suspensions=suspensions,
        benchmark_bars=benchmarks,
        corporate_action_reconciliation=recon,
    )


def test_p0d_r1_mid_halt_transitions_delete_either_fails(
    happy_candidate: G1Candidate,
) -> None:
    """Matrix 6: mid-span halt factor → two transitions; delete either fails."""
    base = _mid_halt_scoped_candidate(happy_candidate)
    audit_ok = audit_g1_candidate(candidate=base)
    assert audit_ok.passed is True
    assert audit_ok.issues == ()
    scoped = base.adjustment_factors.filter(pl.col("symbol") == "000001.SZ")
    assert scoped.get_column("effective_date").to_list() == [_D0, _D1, _D2]
    recon = base.corporate_action_reconciliation.filter(pl.col("symbol") == "000001.SZ")
    assert recon.height == 2

    for previous, effective in ((_D0, _D1), (_D1, _D2)):
        trimmed = base.corporate_action_reconciliation.filter(
            ~(
                (pl.col("symbol") == "000001.SZ")
                & (pl.col("previous_factor_date") == previous)
                & (pl.col("effective_date") == effective)
            )
        )
        attacked = _rebind_identity(base, corporate_action_reconciliation=trimmed)
        _assert_topology_mismatch(audit_g1_candidate(candidate=attacked))


def test_p0d_r1_adv3a_out_of_scope_factor_still_rejected(
    happy_inputs: G1BuildInputs,
) -> None:
    """Matrix 7: ADV3a bar-span reject kept; verify still inputs-rebuild only."""
    symbol = _symbols()[0]
    replacements: list[VerifiedRawResponse] = []
    for item in happy_inputs.responses:
        params = dict(item.spec.parameters)
        endpoint = item.spec.endpoint
        if params.get("ts_code") != symbol:
            replacements.append(item)
            continue
        request_params = {key: value for key, value in params.items() if key != "fields"}
        if endpoint == "daily":
            replacement = _make_verified(
                "daily", _daily_frame(symbol, [_D1]), parameters=request_params
            )
        elif endpoint == "suspend_d":
            replacement = _make_verified(
                "suspend_d",
                _full_day_suspend(symbol, _D0),
                parameters=request_params,
            )
        else:
            replacements.append(item)
            continue
        assert replacement.spec == item.spec
        replacements.append(replacement)
    inputs = replace(happy_inputs, responses=tuple(replacements))
    candidate = build_g1_candidate(inputs=inputs)
    restored = pl.concat(
        [
            candidate.adjustment_factors,
            pl.DataFrame(
                [
                    {
                        "symbol": symbol,
                        "effective_date": _D0,
                        "adj_factor": 0.5,
                        "source": "tushare",
                    }
                ]
            ),
        ]
    ).sort(["symbol", "effective_date", "source"])
    attacked = _rebind_identity(candidate, adjustment_factors=restored)
    audit = audit_g1_candidate(candidate=attacked)
    assert audit.passed is False
    assert any(
        issue.code == "FACTOR_INVALID"
        and "outside publish bar scope" in issue.message
        for issue in audit.issues
    )
    with pytest.raises(M3G1CandidateError) as caught:
        verify_g1_candidate(inputs=inputs, candidate=attacked)
    assert caught.value.code == "G1_CANDIDATE_IDENTITY_MISMATCH"


def test_p0d_r1_happy_and_no_event_jump_still_pass(
    happy_candidate: G1Candidate, happy_inputs: G1BuildInputs
) -> None:
    """Matrix 8: legal happy audit continues to pass after topology bind."""
    audit = audit_g1_candidate(candidate=happy_candidate)
    assert audit.passed is True
    assert audit.issues == ()
    verify_g1_candidate(inputs=happy_inputs, candidate=happy_candidate)
    assert happy_candidate.corporate_action_reconciliation.height == 300