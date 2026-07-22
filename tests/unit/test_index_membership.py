"""B3: index_weight observations -> conservative PIT membership."""

from __future__ import annotations

import datetime as dt
import importlib
import math
import sys
from collections.abc import Sequence
from dataclasses import asdict, replace
from typing import Any

import polars as pl
import pytest

from quant.data import m3_backfill as backfill
from quant.data.index_membership import (
    M3IndexMembershipError,
    ObservedMembershipResult,
    build_observed_membership,
    normalize_index_weight_observations,
    verify_observed_membership_result,
)
from quant.data.m3_backfill import (
    TUSHARE_FIELDS,
    TushareRequestBatch,
    TushareRequestReceipt,
    TushareRequestSpec,
    VerifiedRawResponse,
    plan_index_weight_requests,
    response_content_sha256,
)
from quant.data.m3_identity import clean_table_content_sha256

_UNIVERSE = "CSI300_TUSHARE_MONTHLY_OBSERVED_PIT_V1"
_HEX = "a" * 64
_INDEX = "000300.SH"


def _symbols(n: int = 300) -> list[str]:
    out: list[str] = []
    for i in range(n):
        code = f"{i + 1:06d}"
        out.append(f"{code}.SZ" if i < 150 else f"{code}.SH")
    return out


def _weights(n: int = 300, total: float = 100.0) -> list[float]:
    base = total / n
    return [base] * n


def _make_verified(
    *,
    start: dt.date,
    end: dt.date,
    frame: pl.DataFrame,
    index_code: str = _INDEX,
) -> VerifiedRawResponse:
    params = {
        "fields": TUSHARE_FIELDS["index_weight"],
        "index_code": index_code,
        "start_date": start.strftime("%Y%m%d"),
        "end_date": end.strftime("%Y%m%d"),
    }
    spec = TushareRequestSpec.create(endpoint="index_weight", parameters=params)
    content = response_content_sha256(frame, "index_weight")
    columns = tuple(frame.columns)
    parameters_sha256 = backfill._parameters_hash(spec.parameters)
    stable = backfill._stable_response_hash_values(
        {
            "request_id": spec.request_id,
            "endpoint": "index_weight",
            "parameters_sha256": parameters_sha256,
            "response_content_sha256": content,
            "row_count": frame.height,
            "columns": columns,
        }
    )
    receipt = TushareRequestReceipt(
        schema_version="m3-g1-tushare-receipt-v1",
        request_id=spec.request_id,
        endpoint="index_weight",
        parameters=spec.parameters,
        parameters_sha256=parameters_sha256,
        raw_snapshot_id=spec.request_id,
        raw_data_path="tushare/index_weight/request=x/data.parquet",
        raw_metadata_path="tushare/index_weight/request=x/metadata.json",
        raw_file_sha256=_HEX,
        raw_metadata_sha256=_HEX,
        response_content_sha256=content,
        stable_response_sha256=stable,
        raw_size_bytes=max(frame.height, 1),
        row_count=frame.height,
        columns=columns,
    )
    return VerifiedRawResponse(spec, receipt, backfill._sha256(asdict(receipt)), frame)


def _weight_frame(
    *,
    trade_date: str,
    symbols: Sequence[str] | None = None,
    weights: Sequence[float] | Sequence[str] | None = None,
    index_code: str = _INDEX,
    shuffle: bool = False,
) -> pl.DataFrame:
    syms = list(symbols) if symbols is not None else _symbols()
    vals: list[Any]
    if weights is None:
        vals = list(_weights(len(syms)))
    else:
        vals = list(weights)
    rows = [
        {
            "index_code": index_code,
            "con_code": sym,
            "trade_date": trade_date,
            "weight": weight,
        }
        for sym, weight in zip(syms, vals, strict=True)
    ]
    if shuffle:
        rows = list(reversed(rows))
    return pl.DataFrame(rows).select(_RAW_COLS)


_RAW_COLS = TUSHARE_FIELDS["index_weight"].split(",")


def _month_bounds(year: int, month: int) -> tuple[dt.date, dt.date]:
    start = dt.date(year, month, 1)
    if month == 12:
        end = dt.date(year, 12, 31)
    else:
        end = dt.date(year, month + 1, 1) - dt.timedelta(days=1)
    return start, end


def _batch_and_responses(
    months: Sequence[tuple[int, int, str, Sequence[str] | None, Sequence[float] | None]],
) -> tuple[TushareRequestBatch, list[VerifiedRawResponse]]:
    """months: (year, month, trade_date8, symbols|None, weights|None)."""
    responses: list[VerifiedRawResponse] = []
    for year, month, trade_date, symbols, weights in months:
        start, end = _month_bounds(year, month)
        frame = _weight_frame(
            trade_date=trade_date, symbols=symbols, weights=weights
        )
        responses.append(_make_verified(start=start, end=end, frame=frame))
    first = dt.date(months[0][0], months[0][1], 1)
    last = dt.date(months[-1][0], months[-1][1], 1)
    # plan_index_weight_requests builds continuous months from start month to end month.
    batch = plan_index_weight_requests(
        index_code=_INDEX,
        start=first,
        end=last,
        warmup_months=0,
    )
    # Align responses to batch request order by request_id.
    by_id = {item.spec.request_id: item for item in responses}
    ordered = [by_id[spec.request_id] for spec in batch.requests]
    return batch, ordered


def _calendar(
    days: Sequence[tuple[dt.date, bool]],
) -> pl.DataFrame:
    rows: list[dict[str, Any]] = []
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


def _weekday_calendar(start: dt.date, end: dt.date) -> pl.DataFrame:
    rows: list[tuple[dt.date, bool]] = []
    cursor = start
    while cursor <= end:
        rows.append((cursor, cursor.weekday() < 5))
        cursor += dt.timedelta(days=1)
    return _calendar(rows)


def _instruments(
    symbols: Sequence[str],
    *,
    list_date: dt.date = dt.date(2010, 1, 4),
    delist_date: dt.date | None = None,
) -> pl.DataFrame:
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
                "list_date": list_date,
                "delist_date": delist_date,
                "board_lot": 100,
                "status": "LISTED" if delist_date is None else "DELISTED",
            }
        )
    return pl.DataFrame(rows)


def _etf_instrument(symbol: str = "510050.SH") -> pl.DataFrame:
    market = symbol.rsplit(".", 1)[-1]
    return pl.DataFrame(
        [
            {
                "symbol": symbol,
                "market": market,
                "name": symbol,
                "instrument_type": "ETF",
                "currency": "CNY",
                "list_date": dt.date(2010, 1, 4),
                "delist_date": None,
                "board_lot": 100,
                "status": "LISTED",
            }
        ]
    )


def _fri_mon_fixture() -> dict[str, Any]:
    """2016-01-29 Fri observation -> 2016-02-01 Mon as_of; earliest exec Tue open."""
    symbols = _symbols()
    batch, responses = _batch_and_responses(
        [
            (2016, 1, "20160129", symbols, None),
            (2016, 2, "20160229", symbols, None),
        ]
    )
    calendars = _weekday_calendar(dt.date(2016, 1, 1), dt.date(2016, 3, 10))
    instruments = _instruments(symbols)
    signal_start = dt.date(2016, 2, 1)
    signal_end = dt.date(2016, 2, 5)
    return {
        "batch": batch,
        "responses": responses,
        "calendars": calendars,
        "instruments": instruments,
        "symbols": symbols,
        "signal_start": signal_start,
        "signal_end": signal_end,
    }


def test_normalize_happy_path_and_order_stability() -> None:
    symbols = _symbols()
    batch, responses = _batch_and_responses(
        [(2016, 1, "20160129", symbols, None)]
    )
    out = normalize_index_weight_observations(
        batch=batch, responses=responses, universe=_UNIVERSE
    )
    assert out.height == 300
    assert out.columns == [
        "universe",
        "observation_date",
        "symbol",
        "weight",
        "source",
        "source_snapshot_id",
    ]
    assert out.get_column("observation_date").unique().to_list() == [dt.date(2016, 1, 29)]
    assert "000001.SZ" in out.get_column("symbol").to_list()
    reversed_responses = list(reversed(responses))
    out2 = normalize_index_weight_observations(
        batch=batch, responses=reversed_responses, universe=_UNIVERSE
    )
    assert out.equals(out2)
    # Row shuffle inside frame.
    start, end = _month_bounds(2016, 1)
    shuffled = _make_verified(
        start=start,
        end=end,
        frame=_weight_frame(trade_date="20160129", shuffle=True),
    )
    out3 = normalize_index_weight_observations(
        batch=batch, responses=[shuffled], universe=_UNIVERSE
    )
    assert out.select(pl.exclude("source_snapshot_id")).equals(
        out3.select(pl.exclude("source_snapshot_id"))
    )


def test_batch_drift_and_response_set_mismatch() -> None:
    fx = _fri_mon_fixture()
    batch = fx["batch"]
    responses = fx["responses"]
    bad_batch = TushareRequestBatch(
        batch.schema_version, batch.phase, batch.requests, batch.batch_sha256
    )
    object.__setattr__(bad_batch, "batch_sha256", "b" * 64)
    with pytest.raises(M3IndexMembershipError, match="G1_MEMBERSHIP_BATCH_INVALID"):
        normalize_index_weight_observations(
            batch=bad_batch, responses=responses, universe=_UNIVERSE
        )
    with pytest.raises(M3IndexMembershipError, match="G1_MEMBERSHIP_RESPONSE_SET_MISMATCH"):
        normalize_index_weight_observations(
            batch=batch, responses=responses[:1], universe=_UNIVERSE
        )
    with pytest.raises(M3IndexMembershipError, match="G1_MEMBERSHIP_RESPONSE_SET_MISMATCH"):
        normalize_index_weight_observations(
            batch=batch, responses=responses + responses[:1], universe=_UNIVERSE
        )
    # Cross-batch: build a third month response not in batch.
    start, end = _month_bounds(2016, 3)
    extra = _make_verified(
        start=start, end=end, frame=_weight_frame(trade_date="20160331")
    )
    with pytest.raises(M3IndexMembershipError, match="G1_MEMBERSHIP_RESPONSE_SET_MISMATCH"):
        normalize_index_weight_observations(
            batch=batch, responses=[responses[0], extra], universe=_UNIVERSE
        )


def test_response_frame_receipt_spec_drift() -> None:
    batch, responses = _batch_and_responses(
        [(2016, 1, "20160129", None, None)]
    )
    response = responses[0]
    # Frame drift after construction via object.__setattr__.
    drifted = VerifiedRawResponse(
        response.spec, response.receipt, response.receipt_sha256, response.frame
    )
    object.__setattr__(
        drifted,
        "frame",
        response.frame.with_columns(pl.col("weight") * 1.01),
    )
    with pytest.raises(M3IndexMembershipError, match="G1_MEMBERSHIP_RESPONSE_INVALID"):
        normalize_index_weight_observations(
            batch=batch, responses=[drifted], universe=_UNIVERSE
        )
    # Receipt hash drift.
    bad_receipt = replace(response.receipt, raw_file_sha256="c" * 64)
    with pytest.raises(Exception):
        VerifiedRawResponse(
            response.spec, bad_receipt, response.receipt_sha256, response.frame
        )


def test_non_full_month_and_gap_and_empty_month() -> None:
    symbols = _symbols()
    # Non-full month request cannot be built via plan; craft manually.
    spec = TushareRequestSpec.create(
        endpoint="index_weight",
        parameters={
            "fields": TUSHARE_FIELDS["index_weight"],
            "index_code": _INDEX,
            "start_date": "20160101",
            "end_date": "20160115",
        },
    )
    frame = _weight_frame(trade_date="20160115", symbols=symbols)
    content = response_content_sha256(frame, "index_weight")
    parameters_sha256 = backfill._parameters_hash(spec.parameters)
    stable = backfill._stable_response_hash_values(
        {
            "request_id": spec.request_id,
            "endpoint": "index_weight",
            "parameters_sha256": parameters_sha256,
            "response_content_sha256": content,
            "row_count": frame.height,
            "columns": tuple(frame.columns),
        }
    )
    receipt = TushareRequestReceipt(
        schema_version="m3-g1-tushare-receipt-v1",
        request_id=spec.request_id,
        endpoint="index_weight",
        parameters=spec.parameters,
        parameters_sha256=parameters_sha256,
        raw_snapshot_id=spec.request_id,
        raw_data_path="tushare/index_weight/request=x/data.parquet",
        raw_metadata_path="tushare/index_weight/request=x/metadata.json",
        raw_file_sha256=_HEX,
        raw_metadata_sha256=_HEX,
        response_content_sha256=content,
        stable_response_sha256=stable,
        raw_size_bytes=frame.height,
        row_count=frame.height,
        columns=tuple(frame.columns),
    )
    response = VerifiedRawResponse(
        spec, receipt, backfill._sha256(asdict(receipt)), frame
    )
    batch = TushareRequestBatch(
        "m3-g1-tushare-request-batch-v1",
        "INDEX_WEIGHT",
        (spec,),
        backfill._batch_hash("INDEX_WEIGHT", (spec,)),
    )
    with pytest.raises(M3IndexMembershipError, match="G1_MEMBERSHIP_REQUEST_SCOPE_INVALID"):
        normalize_index_weight_observations(
            batch=batch, responses=[response], universe=_UNIVERSE
        )

    # Month gap Jan+Mar.
    jan = _batch_and_responses([(2016, 1, "20160129", symbols, None)])
    mar_start, mar_end = _month_bounds(2016, 3)
    mar = _make_verified(
        start=mar_start, end=mar_end, frame=_weight_frame(trade_date="20160331")
    )
    specs = tuple(
        sorted(
            (jan[1][0].spec, mar.spec),
            key=lambda item: item.request_id,
        )
    )
    gap_batch = TushareRequestBatch(
        "m3-g1-tushare-request-batch-v1",
        "INDEX_WEIGHT",
        specs,
        backfill._batch_hash("INDEX_WEIGHT", specs),
    )
    by_id = {item.spec.request_id: item for item in (jan[1][0], mar)}
    with pytest.raises(M3IndexMembershipError, match="G1_MEMBERSHIP_REQUEST_SCOPE_INVALID"):
        normalize_index_weight_observations(
            batch=gap_batch,
            responses=[by_id[s.request_id] for s in specs],
            universe=_UNIVERSE,
        )

    # Empty response for a month.
    start, end = _month_bounds(2016, 1)
    empty = _make_verified(
        start=start,
        end=end,
        frame=pl.DataFrame(
            schema={
                "index_code": pl.Utf8,
                "con_code": pl.Utf8,
                "trade_date": pl.Utf8,
                "weight": pl.Float64,
            }
        ).select(_RAW_COLS),
    )
    batch_one = plan_index_weight_requests(
        index_code=_INDEX, start=dt.date(2016, 1, 1), end=dt.date(2016, 1, 1), warmup_months=0
    )
    with pytest.raises(M3IndexMembershipError, match="G1_MEMBERSHIP_MONTH_MISSING"):
        normalize_index_weight_observations(
            batch=batch_one, responses=[empty], universe=_UNIVERSE
        )


def test_same_month_multiple_observations_retained() -> None:
    symbols = _symbols()
    start, end = _month_bounds(2016, 1)
    rows = []
    for trade_date in ("20160115", "20160129"):
        rows.extend(
            {
                "index_code": _INDEX,
                "con_code": sym,
                "trade_date": trade_date,
                "weight": weight,
            }
            for sym, weight in zip(symbols, _weights(), strict=True)
        )
    frame = pl.DataFrame(rows).select(_RAW_COLS)
    response = _make_verified(start=start, end=end, frame=frame)
    batch = plan_index_weight_requests(
        index_code=_INDEX, start=dt.date(2016, 1, 1), end=dt.date(2016, 1, 1), warmup_months=0
    )
    out = normalize_index_weight_observations(
        batch=batch, responses=[response], universe=_UNIVERSE
    )
    assert out.get_column("observation_date").unique().sort().to_list() == [
        dt.date(2016, 1, 15),
        dt.date(2016, 1, 29),
    ]
    assert out.height == 600


def test_columns_scope_and_weight_rejects() -> None:
    symbols = _symbols()
    start, end = _month_bounds(2016, 1)
    batch = plan_index_weight_requests(
        index_code=_INDEX, start=dt.date(2016, 1, 1), end=dt.date(2016, 1, 1), warmup_months=0
    )
    # Reordered columns.
    bad_cols = pl.DataFrame(
        {
            "con_code": symbols,
            "index_code": [_INDEX] * 300,
            "trade_date": ["20160129"] * 300,
            "weight": _weights(),
        }
    )
    with pytest.raises(M3IndexMembershipError, match="G1_MEMBERSHIP_COLUMNS_INVALID"):
        normalize_index_weight_observations(
            batch=batch,
            responses=[_make_verified(start=start, end=end, frame=bad_cols)],
            universe=_UNIVERSE,
        )
    # Date outside month.
    with pytest.raises(M3IndexMembershipError, match="G1_MEMBERSHIP_REQUEST_SCOPE_INVALID"):
        normalize_index_weight_observations(
            batch=batch,
            responses=[
                _make_verified(
                    start=start,
                    end=end,
                    frame=_weight_frame(trade_date="20160201"),
                )
            ],
            universe=_UNIVERSE,
        )
    # Bool weight (Boolean column; mixed True/float would coerce to float).
    bool_frame = _weight_frame(trade_date="20160129").with_columns(
        pl.Series("weight", [True] * 300)
    )
    with pytest.raises(M3IndexMembershipError, match="G1_MEMBERSHIP_VALUE_INVALID"):
        normalize_index_weight_observations(
            batch=batch,
            responses=[_make_verified(start=start, end=end, frame=bool_frame)],
            universe=_UNIVERSE,
        )
    for bad in (None, 0.0, -1.0, "", "abc"):
        weights: list[Any] = list(_weights())
        weights[0] = bad
        with pytest.raises(M3IndexMembershipError, match="G1_MEMBERSHIP_VALUE_INVALID"):
            normalize_index_weight_observations(
                batch=batch,
                responses=[
                    _make_verified(
                        start=start,
                        end=end,
                        frame=_weight_frame(trade_date="20160129", weights=weights),
                    )
                ],
                universe=_UNIVERSE,
            )
    # NaN/Inf cannot sit inside a verified response content digest; post-construct
    # frame drift is rejected at the verified rebuild boundary.
    valid = _make_verified(start=start, end=end, frame=_weight_frame(trade_date="20160129"))
    for dirty in (float("nan"), float("inf")):
        drifted = VerifiedRawResponse(
            valid.spec, valid.receipt, valid.receipt_sha256, valid.frame
        )
        object.__setattr__(
            drifted,
            "frame",
            valid.frame.with_columns(
                pl.Series("weight", [dirty] + valid.frame.get_column("weight").to_list()[1:])
            ),
        )
        with pytest.raises(M3IndexMembershipError, match="G1_MEMBERSHIP_RESPONSE_INVALID"):
            normalize_index_weight_observations(
                batch=batch, responses=[drifted], universe=_UNIVERSE
            )
    # Decimal string accepted.
    str_weights = [f"{w:.17g}" for w in _weights()]
    out = normalize_index_weight_observations(
        batch=batch,
        responses=[
            _make_verified(
                start=start,
                end=end,
                frame=_weight_frame(trade_date="20160129", weights=str_weights),
            )
        ],
        universe=_UNIVERSE,
    )
    assert out.height == 300


def test_duplicate_count_and_weight_sum_boundaries() -> None:
    symbols = _symbols()
    start, end = _month_bounds(2016, 1)
    batch = plan_index_weight_requests(
        index_code=_INDEX, start=dt.date(2016, 1, 1), end=dt.date(2016, 1, 1), warmup_months=0
    )
    # Duplicate key.
    dup_syms = symbols[:299] + [symbols[0]]
    with pytest.raises(M3IndexMembershipError, match="G1_MEMBERSHIP_DUPLICATE_KEY"):
        normalize_index_weight_observations(
            batch=batch,
            responses=[
                _make_verified(
                    start=start,
                    end=end,
                    frame=_weight_frame(trade_date="20160129", symbols=dup_syms),
                )
            ],
            universe=_UNIVERSE,
        )
    # 299 / 301
    with pytest.raises(M3IndexMembershipError, match="G1_MEMBERSHIP_CONSTITUENT_COUNT_INVALID"):
        normalize_index_weight_observations(
            batch=batch,
            responses=[
                _make_verified(
                    start=start,
                    end=end,
                    frame=_weight_frame(
                        trade_date="20160129",
                        symbols=symbols[:299],
                        weights=_weights(299),
                    ),
                )
            ],
            universe=_UNIVERSE,
        )
    extra = symbols + ["009999.SH"]
    with pytest.raises(M3IndexMembershipError, match="G1_MEMBERSHIP_CONSTITUENT_COUNT_INVALID"):
        normalize_index_weight_observations(
            batch=batch,
            responses=[
                _make_verified(
                    start=start,
                    end=end,
                    frame=_weight_frame(
                        trade_date="20160129",
                        symbols=extra,
                        weights=_weights(301),
                    ),
                )
            ],
            universe=_UNIVERSE,
        )
    # 99 and 101 pass.
    for total in (99.0, 101.0):
        out = normalize_index_weight_observations(
            batch=batch,
            responses=[
                _make_verified(
                    start=start,
                    end=end,
                    frame=_weight_frame(
                        trade_date="20160129", weights=_weights(total=total)
                    ),
                )
            ],
            universe=_UNIVERSE,
        )
        assert out.height == 300
    # Outside boundary.
    for total in (98.999999, 101.000001):
        with pytest.raises(M3IndexMembershipError, match="G1_MEMBERSHIP_WEIGHT_SUM_INVALID"):
            normalize_index_weight_observations(
                batch=batch,
                responses=[
                    _make_verified(
                        start=start,
                        end=end,
                        frame=_weight_frame(
                            trade_date="20160129", weights=_weights(total=total)
                        ),
                    )
                ],
                universe=_UNIVERSE,
            )
    # Near-boundary float permutation stability.
    near = _weights(total=100.0)
    near[0] += 1e-12
    near[1] -= 1e-12
    assert 99.0 <= math.fsum(sorted(near)) <= 101.0
    a = normalize_index_weight_observations(
        batch=batch,
        responses=[
            _make_verified(
                start=start,
                end=end,
                frame=_weight_frame(trade_date="20160129", weights=near),
            )
        ],
        universe=_UNIVERSE,
    )
    b = normalize_index_weight_observations(
        batch=batch,
        responses=[
            _make_verified(
                start=start,
                end=end,
                frame=_weight_frame(trade_date="20160129", weights=near, shuffle=True),
            )
        ],
        universe=_UNIVERSE,
    )
    assert a.select(["symbol", "weight"]).equals(b.select(["symbol", "weight"]))


def test_friday_observation_monday_as_of_tuesday_execution_fixture() -> None:
    fx = _fri_mon_fixture()
    observations = normalize_index_weight_observations(
        batch=fx["batch"], responses=fx["responses"], universe=_UNIVERSE
    )
    result = build_observed_membership(
        observations=observations,
        calendars=fx["calendars"],
        instruments=fx["instruments"],
        universe=_UNIVERSE,
        signal_start=fx["signal_start"],
        signal_end=fx["signal_end"],
        expected_constituent_count=300,
    )
    fri = dt.date(2016, 1, 29)
    mon = dt.date(2016, 2, 1)
    tue = dt.date(2016, 2, 2)
    assert fri not in result.eligible_keys.get_column("as_of").to_list()
    mon_syms = (
        result.eligible_keys.filter(pl.col("as_of") == mon).get_column("symbol").to_list()
    )
    assert len(mon_syms) == 300
    assert "000001.SZ" in mon_syms
    # Cross-module fixture note: earliest open execution after Monday as_of is Tuesday.
    assert tue == mon + dt.timedelta(days=1)
    assert tue.weekday() == 1
    verify_observed_membership_result(
        batch=fx["batch"],
        responses=fx["responses"],
        result=result,
        calendars=fx["calendars"],
        instruments=fx["instruments"],
        universe=_UNIVERSE,
        signal_start=fx["signal_start"],
        signal_end=fx["signal_end"],
        expected_constituent_count=300,
    )


def test_add_remove_merge_reentry_and_same_month_two_states() -> None:
    base = _symbols()
    add_set = base[:299] + ["000300.SZ"]
    # Jan: base; Feb mid change via two observations in Feb? Use Jan + Feb with different sets.
    # Jan obs -> activate Feb1; Feb obs (new member) -> activate Mar1.
    batch, responses = _batch_and_responses(
        [
            (2016, 1, "20160129", base, None),
            (2016, 2, "20160229", add_set, None),
        ]
    )
    calendars = _weekday_calendar(dt.date(2016, 1, 1), dt.date(2016, 3, 15))
    instruments = _instruments(sorted(set(base) | set(add_set)))
    observations = normalize_index_weight_observations(
        batch=batch, responses=responses, universe=_UNIVERSE
    )
    result = build_observed_membership(
        observations=observations,
        calendars=calendars,
        instruments=instruments,
        universe=_UNIVERSE,
        signal_start=dt.date(2016, 2, 1),
        signal_end=dt.date(2016, 3, 4),
        expected_constituent_count=300,
    )
    # base[299] is 000300.SH; add_set replaced it with 000300.SZ.
    removed = base[299]
    added = "000300.SZ"
    feb_syms = set(
        result.eligible_keys.filter(pl.col("as_of") == dt.date(2016, 2, 1))
        .get_column("symbol")
        .to_list()
    )
    mar_syms = set(
        result.eligible_keys.filter(pl.col("as_of") == dt.date(2016, 3, 1))
        .get_column("symbol")
        .to_list()
    )
    assert removed in feb_syms and removed not in mar_syms
    assert added not in feb_syms and added in mar_syms
    # Continuous member merged into one interval.
    cont = base[0]
    intervals = result.membership.filter(pl.col("symbol") == cont)
    assert intervals.height == 1
    assert intervals.row(0, named=True)["effective_from"] == dt.date(2016, 2, 1)
    assert intervals.row(0, named=True)["effective_to"] == dt.date(2016, 3, 4)

    # Re-entry: Jan has X, Feb without X, Mar with X again -> two intervals.
    # Use three months.
    set_a = base
    set_b = base[:299] + ["000301.SZ"]
    set_c = base  # re-enter original
    batch3, responses3 = _batch_and_responses(
        [
            (2016, 1, "20160129", set_a, None),
            (2016, 2, "20160229", set_b, None),
            (2016, 3, "20160331", set_c, None),
        ]
    )
    calendars3 = _weekday_calendar(dt.date(2016, 1, 1), dt.date(2016, 4, 15))
    instruments3 = _instruments(sorted(set(set_a) | set(set_b) | set(set_c)))
    obs3 = normalize_index_weight_observations(
        batch=batch3, responses=responses3, universe=_UNIVERSE
    )
    result3 = build_observed_membership(
        observations=obs3,
        calendars=calendars3,
        instruments=instruments3,
        universe=_UNIVERSE,
        signal_start=dt.date(2016, 2, 1),
        signal_end=dt.date(2016, 4, 1),
        expected_constituent_count=300,
    )
    reenter = set_a[299]
    intervals_r = result3.membership.filter(pl.col("symbol") == reenter).sort(
        "effective_from"
    )
    assert intervals_r.height == 2

    # Same-month two states.
    start, end = _month_bounds(2016, 1)
    rows = []
    for trade_date, syms in (("20160115", set_a), ("20160129", set_b)):
        rows.extend(
            {
                "index_code": _INDEX,
                "con_code": sym,
                "trade_date": trade_date,
                "weight": weight,
            }
            for sym, weight in zip(syms, _weights(), strict=True)
        )
    frame = pl.DataFrame(rows).select(_RAW_COLS)
    response = _make_verified(start=start, end=end, frame=frame)
    # Need warmup before signal: add Dec observation month.
    full_batch = plan_index_weight_requests(
        index_code=_INDEX,
        start=dt.date(2015, 12, 1),
        end=dt.date(2016, 1, 1),
        warmup_months=0,
    )
    dec_start, dec_end = _month_bounds(2015, 12)
    dec_resp = _make_verified(
        start=dec_start, end=dec_end, frame=_weight_frame(trade_date="20151231", symbols=set_a)
    )
    by_id = {dec_resp.spec.request_id: dec_resp, response.spec.request_id: response}
    ordered = [by_id[spec.request_id] for spec in full_batch.requests]
    calendars_m = _weekday_calendar(dt.date(2015, 12, 1), dt.date(2016, 2, 15))
    instruments_m = _instruments(sorted(set(set_a) | set(set_b)))
    obs_m = normalize_index_weight_observations(
        batch=full_batch, responses=ordered, universe=_UNIVERSE
    )
    assert obs_m.get_column("observation_date").n_unique() == 3
    result_m = build_observed_membership(
        observations=obs_m,
        calendars=calendars_m,
        instruments=instruments_m,
        universe=_UNIVERSE,
        signal_start=dt.date(2016, 1, 18),
        signal_end=dt.date(2016, 2, 1),
        expected_constituent_count=300,
    )
    # After 20160129 activates on 20160201, composition follows set_b.
    assert "000301.SZ" in (
        result_m.eligible_keys.filter(pl.col("as_of") == dt.date(2016, 2, 1))
        .get_column("symbol")
        .to_list()
    )


def test_warmup_truncate_null_effective_to_and_closed_days() -> None:
    fx = _fri_mon_fixture()
    observations = normalize_index_weight_observations(
        batch=fx["batch"], responses=fx["responses"], universe=_UNIVERSE
    )
    # Warmup missing: signal starts before first activation.
    with pytest.raises(M3IndexMembershipError, match="G1_MEMBERSHIP_WARMUP_MISSING"):
        build_observed_membership(
            observations=observations,
            calendars=fx["calendars"],
            instruments=fx["instruments"],
            universe=_UNIVERSE,
            signal_start=dt.date(2016, 1, 28),
            signal_end=dt.date(2016, 2, 5),
            expected_constituent_count=300,
        )
    result = build_observed_membership(
        observations=observations,
        calendars=fx["calendars"],
        instruments=fx["instruments"],
        universe=_UNIVERSE,
        signal_start=fx["signal_start"],
        signal_end=fx["signal_end"],
        expected_constituent_count=300,
    )
    assert result.membership.get_column("effective_to").null_count() == 0
    assert result.membership.get_column("effective_to").max() == fx["signal_end"]
    # Closed days not in eligible.
    assert dt.date(2016, 2, 6) not in result.eligible_keys.get_column("as_of").to_list()
    assert dt.date(2016, 2, 7) not in result.eligible_keys.get_column("as_of").to_list()


def test_calendar_failures() -> None:
    fx = _fri_mon_fixture()
    observations = normalize_index_weight_observations(
        batch=fx["batch"], responses=fx["responses"], universe=_UNIVERSE
    )
    # Missing natural day.
    cal = fx["calendars"].filter(pl.col("date") != dt.date(2016, 2, 3))
    with pytest.raises(M3IndexMembershipError, match="G1_MEMBERSHIP_CALENDAR_COVERAGE_INVALID"):
        build_observed_membership(
            observations=observations,
            calendars=cal,
            instruments=fx["instruments"],
            universe=_UNIVERSE,
            signal_start=fx["signal_start"],
            signal_end=fx["signal_end"],
            expected_constituent_count=300,
        )
    # SH/SZ missing side.
    cal2 = fx["calendars"].filter(
        ~((pl.col("market") == "SZ") & (pl.col("date") == dt.date(2016, 2, 3)))
    )
    with pytest.raises(M3IndexMembershipError, match="G1_MEMBERSHIP_CALENDAR_COVERAGE_INVALID"):
        build_observed_membership(
            observations=observations,
            calendars=cal2,
            instruments=fx["instruments"],
            universe=_UNIVERSE,
            signal_start=fx["signal_start"],
            signal_end=fx["signal_end"],
            expected_constituent_count=300,
        )
    # is_open conflict.
    cal3 = fx["calendars"].with_columns(
        pl.when(
            (pl.col("market") == "SZ") & (pl.col("date") == dt.date(2016, 2, 3))
        )
        .then(pl.lit(False))
        .otherwise(pl.col("is_open"))
        .alias("is_open")
    )
    with pytest.raises(M3IndexMembershipError, match="G1_MEMBERSHIP_CALENDAR_MISMATCH"):
        build_observed_membership(
            observations=observations,
            calendars=cal3,
            instruments=fx["instruments"],
            universe=_UNIVERSE,
            signal_start=fx["signal_start"],
            signal_end=fx["signal_end"],
            expected_constituent_count=300,
        )
    # Observation not open day: craft Sunday observation.
    symbols = _symbols()
    batch, responses = _batch_and_responses(
        [(2016, 1, "20160131", symbols, None)]  # Sunday
    )
    calendars = _weekday_calendar(dt.date(2016, 1, 1), dt.date(2016, 3, 10))
    instruments = _instruments(symbols)
    obs = normalize_index_weight_observations(
        batch=batch, responses=responses, universe=_UNIVERSE
    )
    with pytest.raises(M3IndexMembershipError, match="G1_MEMBERSHIP_CALENDAR_INVALID"):
        build_observed_membership(
            observations=obs,
            calendars=calendars,
            instruments=instruments,
            universe=_UNIVERSE,
            signal_start=dt.date(2016, 2, 1),
            signal_end=dt.date(2016, 2, 5),
            expected_constituent_count=300,
        )
    # Missing calendar_proof_end after last observation/signal.
    short = _weekday_calendar(dt.date(2016, 1, 1), dt.date(2016, 2, 5))
    with pytest.raises(M3IndexMembershipError, match="G1_MEMBERSHIP_CALENDAR_COVERAGE_INVALID"):
        build_observed_membership(
            observations=observations,
            calendars=short,
            instruments=fx["instruments"],
            universe=_UNIVERSE,
            signal_start=fx["signal_start"],
            signal_end=fx["signal_end"],
            expected_constituent_count=300,
        )


def test_instrument_lifecycle_cases() -> None:
    fx = _fri_mon_fixture()
    observations = normalize_index_weight_observations(
        batch=fx["batch"], responses=fx["responses"], universe=_UNIVERSE
    )
    # Unknown symbol.
    inst = fx["instruments"].filter(pl.col("symbol") != "000001.SZ")
    with pytest.raises(M3IndexMembershipError, match="G1_MEMBERSHIP_INSTRUMENT_INVALID"):
        build_observed_membership(
            observations=observations,
            calendars=fx["calendars"],
            instruments=inst,
            universe=_UNIVERSE,
            signal_start=fx["signal_start"],
            signal_end=fx["signal_end"],
            expected_constituent_count=300,
        )
    # Duplicate instrument.
    dup = pl.concat([fx["instruments"], fx["instruments"].head(1)])
    with pytest.raises(M3IndexMembershipError, match="G1_MEMBERSHIP_INSTRUMENT_INVALID"):
        build_observed_membership(
            observations=observations,
            calendars=fx["calendars"],
            instruments=dup,
            universe=_UNIVERSE,
            signal_start=fx["signal_start"],
            signal_end=fx["signal_end"],
            expected_constituent_count=300,
        )
    # Wrong type.
    bad_type = fx["instruments"].with_columns(
        pl.when(pl.col("symbol") == "000001.SZ")
        .then(pl.lit("ETF"))
        .otherwise(pl.col("instrument_type"))
        .alias("instrument_type")
    )
    with pytest.raises(M3IndexMembershipError, match="G1_MEMBERSHIP_INSTRUMENT_INVALID"):
        build_observed_membership(
            observations=observations,
            calendars=fx["calendars"],
            instruments=bad_type,
            universe=_UNIVERSE,
            signal_start=fx["signal_start"],
            signal_end=fx["signal_end"],
            expected_constituent_count=300,
        )
    # Not yet listed at observation.
    late = fx["instruments"].with_columns(
        pl.when(pl.col("symbol") == "000001.SZ")
        .then(pl.lit(dt.date(2016, 2, 1)))
        .otherwise(pl.col("list_date"))
        .alias("list_date")
    )
    with pytest.raises(M3IndexMembershipError, match="G1_MEMBERSHIP_LIFECYCLE_INVALID"):
        build_observed_membership(
            observations=observations,
            calendars=fx["calendars"],
            instruments=late,
            universe=_UNIVERSE,
            signal_start=fx["signal_start"],
            signal_end=fx["signal_end"],
            expected_constituent_count=300,
        )
    # Already delisted at observation.
    early_delist = fx["instruments"].with_columns(
        pl.when(pl.col("symbol") == "000001.SZ")
        .then(pl.lit(dt.date(2016, 1, 28)))
        .otherwise(pl.col("delist_date"))
        .alias("delist_date")
    )
    with pytest.raises(M3IndexMembershipError, match="G1_MEMBERSHIP_LIFECYCLE_INVALID"):
        build_observed_membership(
            observations=observations,
            calendars=fx["calendars"],
            instruments=early_delist,
            universe=_UNIVERSE,
            signal_start=fx["signal_start"],
            signal_end=fx["signal_end"],
            expected_constituent_count=300,
        )
    # Later observation still lists a symbol already delisted -> lifecycle fail-closed.
    # (Legal mid-window 299 after a clean replacement observation is covered separately.)
    mid_delist = fx["instruments"].with_columns(
        pl.when(pl.col("symbol") == "000001.SZ")
        .then(pl.lit(dt.date(2016, 2, 2)))
        .otherwise(pl.col("delist_date"))
        .alias("delist_date")
    )
    with pytest.raises(M3IndexMembershipError, match="G1_MEMBERSHIP_LIFECYCLE_INVALID"):
        build_observed_membership(
            observations=observations,
            calendars=fx["calendars"],
            instruments=mid_delist,
            universe=_UNIVERSE,
            signal_start=fx["signal_start"],
            signal_end=fx["signal_end"],
            expected_constituent_count=300,
        )
    # Weekend list_date maps forward; delist on weekend maps backward.
    # list_date Saturday 2016-01-30 -> first session 2016-02-01.
    # Symbol observed 2016-01-29 requires list_date <= obs, so use earlier weekend.
    weekend_list = fx["instruments"].with_columns(
        pl.when(pl.col("symbol") == "000001.SZ")
        .then(pl.lit(dt.date(2016, 1, 23)))  # Saturday
        .otherwise(pl.col("list_date"))
        .alias("list_date")
    )
    result = build_observed_membership(
        observations=observations,
        calendars=fx["calendars"],
        instruments=weekend_list,
        universe=_UNIVERSE,
        signal_start=fx["signal_start"],
        signal_end=fx["signal_end"],
        expected_constituent_count=300,
    )
    assert "000001.SZ" in result.eligible_keys.get_column("symbol").to_list()

    # Historical future delist after all observations; still valid at obs time.
    hist = fx["instruments"].with_columns(
        pl.when(pl.col("symbol") == "000001.SZ")
        .then(pl.lit(dt.date(2016, 3, 15)))
        .otherwise(pl.col("delist_date"))
        .alias("delist_date")
    )
    # Extend signal so delist bites after some days; still 300 until delist day mapped.
    # Use short signal ending on delist session so still 300 every day.
    result_h = build_observed_membership(
        observations=observations,
        calendars=_weekday_calendar(dt.date(2016, 1, 1), dt.date(2016, 3, 10)),
        instruments=hist,
        universe=_UNIVERSE,
        signal_start=dt.date(2016, 2, 1),
        signal_end=dt.date(2016, 2, 5),
        expected_constituent_count=300,
    )
    assert "000001.SZ" in (
        result_h.eligible_keys.filter(pl.col("as_of") == dt.date(2016, 2, 5))
        .get_column("symbol")
        .to_list()
    )


def test_eligible_exactly_300_and_bars_do_not_invent_keys() -> None:
    fx = _fri_mon_fixture()
    observations = normalize_index_weight_observations(
        batch=fx["batch"], responses=fx["responses"], universe=_UNIVERSE
    )
    result = build_observed_membership(
        observations=observations,
        calendars=fx["calendars"],
        instruments=fx["instruments"],
        universe=_UNIVERSE,
        signal_start=fx["signal_start"],
        signal_end=fx["signal_end"],
        expected_constituent_count=300,
    )
    counts = (
        result.eligible_keys.group_by("as_of")
        .len()
        .get_column("len")
        .to_list()
    )
    assert counts and all(value == 300 for value in counts)
    # Pre-membership date has no keys even if a bar fixture date exists.
    assert (
        result.eligible_keys.filter(pl.col("as_of") == dt.date(2016, 1, 28)).height == 0
    )


def test_result_verify_rejects_frame_hash_and_shifted_forgeries() -> None:
    fx = _fri_mon_fixture()
    observations = normalize_index_weight_observations(
        batch=fx["batch"], responses=fx["responses"], universe=_UNIVERSE
    )
    result = build_observed_membership(
        observations=observations,
        calendars=fx["calendars"],
        instruments=fx["instruments"],
        universe=_UNIVERSE,
        signal_start=fx["signal_start"],
        signal_end=fx["signal_end"],
        expected_constituent_count=300,
    )
    # Frame-only drift.
    drifted = ObservedMembershipResult(
        result.observations,
        result.membership,
        result.eligible_keys,
        result.observations_sha256,
        result.membership_sha256,
        result.eligible_keys_sha256,
    )
    object.__setattr__(
        drifted,
        "eligible_keys",
        result.eligible_keys.with_columns(pl.col("as_of") + dt.timedelta(days=1)),
    )
    with pytest.raises(M3IndexMembershipError, match="G1_MEMBERSHIP_RESULT_INVALID"):
        ObservedMembershipResult(
            drifted.observations,
            drifted.membership,
            drifted.eligible_keys,
            drifted.observations_sha256,
            drifted.membership_sha256,
            drifted.eligible_keys_sha256,
        )
    # Hash-only drift.
    with pytest.raises(M3IndexMembershipError, match="G1_MEMBERSHIP_RESULT_INVALID"):
        ObservedMembershipResult(
            result.observations,
            result.membership,
            result.eligible_keys,
            result.observations_sha256,
            result.membership_sha256,
            "f" * 64,
        )
    # Shift membership/eligible by one session and recompute digests (self-consistent forgery).
    shifted_eligible = result.eligible_keys.with_columns(
        pl.col("as_of") + dt.timedelta(days=1)
    )
    # Make it schema-valid-ish by filtering to open days inside window — still wrong vs rebuild.
    shifted_membership = result.membership.with_columns(
        pl.col("effective_from") + dt.timedelta(days=1),
        pl.col("effective_to") + dt.timedelta(days=1),
    )
    forged = ObservedMembershipResult(
        result.observations,
        shifted_membership,
        shifted_eligible,
        clean_table_content_sha256(
            table_name="index_constituent_observation", frame=result.observations
        ),
        clean_table_content_sha256(
            table_name="universe_membership", frame=shifted_membership
        ),
        clean_table_content_sha256(table_name="eligible_keys", frame=shifted_eligible),
    )
    with pytest.raises(M3IndexMembershipError, match="G1_MEMBERSHIP_RESULT_INVALID"):
        verify_observed_membership_result(
            batch=fx["batch"],
            responses=fx["responses"],
            result=forged,
            calendars=fx["calendars"],
            instruments=fx["instruments"],
            universe=_UNIVERSE,
            signal_start=fx["signal_start"],
            signal_end=fx["signal_end"],
            expected_constituent_count=300,
        )


def test_result_constructor_consumes_coerced_frames_and_closes_digests() -> None:
    """P1-1: write back Schema/validator returns; digests bind exposed frames."""
    from quant.domain import IndexConstituentObservationSchema

    fx = _fri_mon_fixture()
    observations = normalize_index_weight_observations(
        batch=fx["batch"], responses=fx["responses"], universe=_UNIVERSE
    )
    result = build_observed_membership(
        observations=observations,
        calendars=fx["calendars"],
        instruments=fx["instruments"],
        universe=_UNIVERSE,
        signal_start=fx["signal_start"],
        signal_end=fx["signal_end"],
        expected_constituent_count=300,
    )

    # 1) observations: Utf8 date + digest from coerced Date frame.
    str_obs = result.observations.with_columns(pl.col("observation_date").cast(pl.Utf8))
    coerced_obs = IndexConstituentObservationSchema.validate(str_obs)
    obs_digest = clean_table_content_sha256(
        table_name="index_constituent_observation", frame=coerced_obs
    )
    rebuilt_obs = ObservedMembershipResult(
        str_obs,
        result.membership,
        result.eligible_keys,
        obs_digest,
        result.membership_sha256,
        result.eligible_keys_sha256,
    )
    assert rebuilt_obs.observations.schema["observation_date"] == pl.Date
    assert clean_table_content_sha256(
        table_name="index_constituent_observation", frame=rebuilt_obs.observations
    ) == rebuilt_obs.observations_sha256

    # 2) membership: Utf8 effective_* coerce + write-back.
    str_mem = result.membership.with_columns(
        pl.col("effective_from").cast(pl.Utf8),
        pl.col("effective_to").cast(pl.Utf8),
    )
    from quant.domain import UniverseMembershipSchema

    coerced_mem = UniverseMembershipSchema.validate(str_mem)
    mem_digest = clean_table_content_sha256(
        table_name="universe_membership", frame=coerced_mem
    )
    rebuilt_mem = ObservedMembershipResult(
        result.observations,
        str_mem,
        result.eligible_keys,
        result.observations_sha256,
        mem_digest,
        result.eligible_keys_sha256,
    )
    assert rebuilt_mem.membership.schema["effective_from"] == pl.Date
    assert rebuilt_mem.membership.schema["effective_to"] == pl.Date
    assert clean_table_content_sha256(
        table_name="universe_membership", frame=rebuilt_mem.membership
    ) == rebuilt_mem.membership_sha256

    # 3) eligible_keys: Utf8 as_of coerce + write-back.
    str_elig = result.eligible_keys.with_columns(pl.col("as_of").cast(pl.Utf8))
    coerced_elig = str_elig.select(
        pl.col("as_of").cast(pl.Date), pl.col("symbol").cast(pl.Utf8)
    )
    elig_digest = clean_table_content_sha256(
        table_name="eligible_keys", frame=coerced_elig
    )
    rebuilt_elig = ObservedMembershipResult(
        result.observations,
        result.membership,
        str_elig,
        result.observations_sha256,
        result.membership_sha256,
        elig_digest,
    )
    assert rebuilt_elig.eligible_keys.schema["as_of"] == pl.Date
    assert clean_table_content_sha256(
        table_name="eligible_keys", frame=rebuilt_elig.eligible_keys
    ) == rebuilt_elig.eligible_keys_sha256

    # 4) All three tables coercible at once.
    all_three = ObservedMembershipResult(
        str_obs,
        str_mem,
        str_elig,
        obs_digest,
        mem_digest,
        elig_digest,
    )
    assert all_three.observations.schema["observation_date"] == pl.Date
    assert all_three.membership.schema["effective_from"] == pl.Date
    assert all_three.eligible_keys.schema["as_of"] == pl.Date
    assert (
        clean_table_content_sha256(
            table_name="index_constituent_observation", frame=all_three.observations
        )
        == all_three.observations_sha256
    )
    assert (
        clean_table_content_sha256(
            table_name="universe_membership", frame=all_three.membership
        )
        == all_three.membership_sha256
    )
    assert (
        clean_table_content_sha256(
            table_name="eligible_keys", frame=all_three.eligible_keys
        )
        == all_three.eligible_keys_sha256
    )

    # Happy-path digests also close on exposed frames.
    assert clean_table_content_sha256(
        table_name="index_constituent_observation", frame=result.observations
    ) == result.observations_sha256
    assert clean_table_content_sha256(
        table_name="universe_membership", frame=result.membership
    ) == result.membership_sha256
    assert clean_table_content_sha256(
        table_name="eligible_keys", frame=result.eligible_keys
    ) == result.eligible_keys_sha256

    verify_observed_membership_result(
        batch=fx["batch"],
        responses=fx["responses"],
        result=result,
        calendars=fx["calendars"],
        instruments=fx["instruments"],
        universe=_UNIVERSE,
        signal_start=fx["signal_start"],
        signal_end=fx["signal_end"],
        expected_constituent_count=300,
    )


def test_result_constructor_rejects_non_coercible_list_struct() -> None:
    fx = _fri_mon_fixture()
    observations = normalize_index_weight_observations(
        batch=fx["batch"], responses=fx["responses"], universe=_UNIVERSE
    )
    result = build_observed_membership(
        observations=observations,
        calendars=fx["calendars"],
        instruments=fx["instruments"],
        universe=_UNIVERSE,
        signal_start=fx["signal_start"],
        signal_end=fx["signal_end"],
        expected_constituent_count=300,
    )
    list_obs = result.observations.with_columns(
        pl.Series(
            "observation_date",
            [[d] for d in result.observations.get_column("observation_date").to_list()],
            dtype=pl.List(pl.Date),
        )
    )
    with pytest.raises(M3IndexMembershipError) as obs_exc:
        ObservedMembershipResult(
            list_obs,
            result.membership,
            result.eligible_keys,
            result.observations_sha256,
            result.membership_sha256,
            result.eligible_keys_sha256,
        )
    assert obs_exc.value.__cause__ is None
    assert str(obs_exc.value) in {
        "G1_MEMBERSHIP_OBSERVATION_SCHEMA_INVALID",
        "G1_MEMBERSHIP_RESULT_INVALID",
    }

    list_elig = result.eligible_keys.with_columns(
        pl.Series(
            "as_of",
            [[d] for d in result.eligible_keys.get_column("as_of").to_list()],
            dtype=pl.List(pl.Date),
        )
    )
    with pytest.raises(M3IndexMembershipError) as elig_exc:
        ObservedMembershipResult(
            result.observations,
            result.membership,
            list_elig,
            result.observations_sha256,
            result.membership_sha256,
            result.eligible_keys_sha256,
        )
    assert elig_exc.value.__cause__ is None
    assert str(elig_exc.value) in {
        "G1_MEMBERSHIP_ELIGIBLE_KEYS_INVALID",
        "G1_MEMBERSHIP_RESULT_INVALID",
    }

    struct_mem = result.membership.with_columns(
        pl.Series(
            "effective_from",
            [{"d": d} for d in result.membership.get_column("effective_from").to_list()],
            dtype=pl.Struct({"d": pl.Date}),
        )
    )
    with pytest.raises(M3IndexMembershipError) as mem_exc:
        ObservedMembershipResult(
            result.observations,
            struct_mem,
            result.eligible_keys,
            result.observations_sha256,
            result.membership_sha256,
            result.eligible_keys_sha256,
        )
    assert mem_exc.value.__cause__ is None
    assert str(mem_exc.value) in {
        "G1_MEMBERSHIP_INTERVAL_INVALID",
        "G1_MEMBERSHIP_RESULT_INVALID",
    }


def test_exception_sanitization_and_no_network_imports() -> None:
    with pytest.raises(M3IndexMembershipError) as excinfo:
        normalize_index_weight_observations(
            batch="nope",  # type: ignore[arg-type]
            responses=[],
            universe=_UNIVERSE,
        )
    err = excinfo.value
    text = f"{err!s}{err!r}{err.__cause__}"
    assert "token" not in text.lower()
    assert "G:\\" not in text and "/home/" not in text
    assert err.__cause__ is None

    # Production modules must not pull research/provider/qlib.
    before = set(sys.modules)
    importlib.import_module("quant.data.index_membership")
    importlib.import_module("quant.data.m3_identity")
    loaded = set(sys.modules) - before
    forbidden = {"qlib", "mlflow", "lightgbm", "requests", "urllib3"}
    assert not (forbidden & {name.split(".")[0] for name in loaded})
    src = open(
        "src/quant/data/index_membership.py", encoding="utf-8"
    ).read() + open("src/quant/data/m3_identity.py", encoding="utf-8").read()
    assert "socket" not in src
    assert "urllib" not in src
    assert "write_parquet" not in src
    assert "quant.research" not in src
    assert "qlib" not in src


def test_expected_count_and_universe_rejected() -> None:
    fx = _fri_mon_fixture()
    observations = normalize_index_weight_observations(
        batch=fx["batch"], responses=fx["responses"], universe=_UNIVERSE
    )
    with pytest.raises(M3IndexMembershipError, match="G1_MEMBERSHIP_REQUEST_SCOPE_INVALID"):
        normalize_index_weight_observations(
            batch=fx["batch"], responses=fx["responses"], universe="OTHER"
        )
    with pytest.raises(M3IndexMembershipError, match="G1_MEMBERSHIP_CONSTITUENT_COUNT_INVALID"):
        build_observed_membership(
            observations=observations,
            calendars=fx["calendars"],
            instruments=fx["instruments"],
            universe=_UNIVERSE,
            signal_start=fx["signal_start"],
            signal_end=fx["signal_end"],
            expected_constituent_count=301,
        )


def test_unrelated_etf_superset_preserves_digests() -> None:
    """Schema-valid unrelated ETF must not change observations/membership/eligible."""
    fx = _fri_mon_fixture()
    observations = normalize_index_weight_observations(
        batch=fx["batch"], responses=fx["responses"], universe=_UNIVERSE
    )
    stock_only = build_observed_membership(
        observations=observations,
        calendars=fx["calendars"],
        instruments=fx["instruments"],
        universe=_UNIVERSE,
        signal_start=fx["signal_start"],
        signal_end=fx["signal_end"],
        expected_constituent_count=300,
    )
    with_etf = build_observed_membership(
        observations=observations,
        calendars=fx["calendars"],
        instruments=pl.concat([fx["instruments"], _etf_instrument()]),
        universe=_UNIVERSE,
        signal_start=fx["signal_start"],
        signal_end=fx["signal_end"],
        expected_constituent_count=300,
    )
    assert stock_only.observations.equals(with_etf.observations)
    assert stock_only.membership.equals(with_etf.membership)
    assert stock_only.eligible_keys.equals(with_etf.eligible_keys)
    assert stock_only.observations_sha256 == with_etf.observations_sha256
    assert stock_only.membership_sha256 == with_etf.membership_sha256
    assert stock_only.eligible_keys_sha256 == with_etf.eligible_keys_sha256
    verify_observed_membership_result(
        batch=fx["batch"],
        responses=fx["responses"],
        result=with_etf,
        calendars=fx["calendars"],
        instruments=pl.concat([fx["instruments"], _etf_instrument("510300.SH")]),
        universe=_UNIVERSE,
        signal_start=fx["signal_start"],
        signal_end=fx["signal_end"],
        expected_constituent_count=300,
    )
    verify_observed_membership_result(
        batch=fx["batch"],
        responses=fx["responses"],
        result=stock_only,
        calendars=fx["calendars"],
        instruments=fx["instruments"],
        universe=_UNIVERSE,
        signal_start=fx["signal_start"],
        signal_end=fx["signal_end"],
        expected_constituent_count=300,
    )


def test_observed_instrument_contract_failures_stable() -> None:
    """Referenced ETF / non-CNY / wrong market / missing still fail closed."""
    fx = _fri_mon_fixture()
    observations = normalize_index_weight_observations(
        batch=fx["batch"], responses=fx["responses"], universe=_UNIVERSE
    )
    # Observed symbol is ETF.
    bad_type = fx["instruments"].with_columns(
        pl.when(pl.col("symbol") == "000001.SZ")
        .then(pl.lit("ETF"))
        .otherwise(pl.col("instrument_type"))
        .alias("instrument_type")
    )
    with pytest.raises(M3IndexMembershipError, match="G1_MEMBERSHIP_INSTRUMENT_INVALID") as etf_exc:
        build_observed_membership(
            observations=observations,
            calendars=fx["calendars"],
            instruments=bad_type,
            universe=_UNIVERSE,
            signal_start=fx["signal_start"],
            signal_end=fx["signal_end"],
            expected_constituent_count=300,
        )
    assert etf_exc.value.__cause__ is None
    assert str(etf_exc.value) == "G1_MEMBERSHIP_INSTRUMENT_INVALID"

    # Observed symbol non-CNY (Schema rejects SH+HKD; stable instrument code).
    bad_ccy = fx["instruments"].with_columns(
        pl.when(pl.col("symbol") == "000001.SZ")
        .then(pl.lit("HKD"))
        .otherwise(pl.col("currency"))
        .alias("currency")
    )
    with pytest.raises(M3IndexMembershipError, match="G1_MEMBERSHIP_INSTRUMENT_INVALID") as ccy_exc:
        build_observed_membership(
            observations=observations,
            calendars=fx["calendars"],
            instruments=bad_ccy,
            universe=_UNIVERSE,
            signal_start=fx["signal_start"],
            signal_end=fx["signal_end"],
            expected_constituent_count=300,
        )
    assert ccy_exc.value.__cause__ is None

    # Wrong market suffix vs market column.
    bad_mkt = fx["instruments"].with_columns(
        pl.when(pl.col("symbol") == "000001.SZ")
        .then(pl.lit("SH"))
        .otherwise(pl.col("market"))
        .alias("market")
    )
    with pytest.raises(M3IndexMembershipError, match="G1_MEMBERSHIP_INSTRUMENT_INVALID") as mkt_exc:
        build_observed_membership(
            observations=observations,
            calendars=fx["calendars"],
            instruments=bad_mkt,
            universe=_UNIVERSE,
            signal_start=fx["signal_start"],
            signal_end=fx["signal_end"],
            expected_constituent_count=300,
        )
    assert mkt_exc.value.__cause__ is None

    # Missing observed symbol.
    missing = fx["instruments"].filter(pl.col("symbol") != "000001.SZ")
    with pytest.raises(M3IndexMembershipError, match="G1_MEMBERSHIP_INSTRUMENT_INVALID") as miss_exc:
        build_observed_membership(
            observations=observations,
            calendars=fx["calendars"],
            instruments=missing,
            universe=_UNIVERSE,
            signal_start=fx["signal_start"],
            signal_end=fx["signal_end"],
            expected_constituent_count=300,
        )
    assert miss_exc.value.__cause__ is None


def test_delist_between_observations_allows_299() -> None:
    """Member delisted before next monthly observation: 299 sessions are legal."""
    base = _symbols()
    replaced = base[:299] + ["000300.SZ"]
    batch, responses = _batch_and_responses(
        [
            (2016, 1, "20160129", base, None),
            (2016, 2, "20160229", replaced, None),
        ]
    )
    calendars = _weekday_calendar(dt.date(2016, 1, 1), dt.date(2016, 3, 15))
    departing = base[299]  # 000300.SH
    instruments = _instruments(sorted(set(base) | set(replaced))).with_columns(
        pl.when(pl.col("symbol") == departing)
        .then(pl.lit(dt.date(2016, 2, 10)))
        .otherwise(pl.col("delist_date"))
        .alias("delist_date")
    )
    observations = normalize_index_weight_observations(
        batch=batch, responses=responses, universe=_UNIVERSE
    )
    assert observations.height == 600  # two exact-300 observations
    result = build_observed_membership(
        observations=observations,
        calendars=calendars,
        instruments=instruments,
        universe=_UNIVERSE,
        signal_start=dt.date(2016, 2, 1),
        signal_end=dt.date(2016, 3, 4),
        expected_constituent_count=300,
    )
    # Still listed through delist session 2016-02-10.
    on_delist = result.eligible_keys.filter(pl.col("as_of") == dt.date(2016, 2, 10))
    assert on_delist.height == 300
    assert departing in on_delist.get_column("symbol").to_list()
    # After delist, before Feb observation activates (2016-03-01): 299.
    gap = result.eligible_keys.filter(pl.col("as_of") == dt.date(2016, 2, 11))
    assert gap.height == 299
    assert departing not in gap.get_column("symbol").to_list()
    # Next observation activates 2016-03-01 with replacement.
    after = result.eligible_keys.filter(pl.col("as_of") == dt.date(2016, 3, 1))
    assert after.height == 300
    assert "000300.SZ" in after.get_column("symbol").to_list()
    assert departing not in after.get_column("symbol").to_list()


def test_observation_299_301_still_rejected() -> None:
    """Revised eligible contract must not relax supplier observation gate."""
    symbols = _symbols()
    start, end = _month_bounds(2016, 1)
    batch = plan_index_weight_requests(
        index_code=_INDEX, start=dt.date(2016, 1, 1), end=dt.date(2016, 1, 1), warmup_months=0
    )
    with pytest.raises(M3IndexMembershipError, match="G1_MEMBERSHIP_CONSTITUENT_COUNT_INVALID"):
        normalize_index_weight_observations(
            batch=batch,
            responses=[
                _make_verified(
                    start=start,
                    end=end,
                    frame=_weight_frame(
                        trade_date="20160129",
                        symbols=symbols[:299],
                        weights=_weights(299),
                    ),
                )
            ],
            universe=_UNIVERSE,
        )
    with pytest.raises(M3IndexMembershipError, match="G1_MEMBERSHIP_CONSTITUENT_COUNT_INVALID"):
        normalize_index_weight_observations(
            batch=batch,
            responses=[
                _make_verified(
                    start=start,
                    end=end,
                    frame=_weight_frame(
                        trade_date="20160129",
                        symbols=symbols + ["009999.SH"],
                        weights=_weights(301),
                    ),
                )
            ],
            universe=_UNIVERSE,
        )


def test_eligible_empty_over_300_and_closed_day_guards() -> None:
    fx = _fri_mon_fixture()
    observations = normalize_index_weight_observations(
        batch=fx["batch"], responses=fx["responses"], universe=_UNIVERSE
    )
    result = build_observed_membership(
        observations=observations,
        calendars=fx["calendars"],
        instruments=fx["instruments"],
        universe=_UNIVERSE,
        signal_start=fx["signal_start"],
        signal_end=fx["signal_end"],
        expected_constituent_count=300,
    )
    # Closed / out-of-window days never appear as eligible keys.
    assert dt.date(2016, 2, 6) not in result.eligible_keys.get_column("as_of").to_list()
    assert dt.date(2016, 1, 28) not in result.eligible_keys.get_column("as_of").to_list()
    # Empty eligible frame rejected by constructor.
    with pytest.raises(M3IndexMembershipError, match="G1_MEMBERSHIP_ELIGIBLE_KEYS_INVALID") as empty_exc:
        ObservedMembershipResult(
            result.observations,
            result.membership,
            result.eligible_keys.clear(),
            result.observations_sha256,
            result.membership_sha256,
            result.eligible_keys_sha256,
        )
    assert empty_exc.value.__cause__ is None
    # Duplicate keys rejected.
    dup = pl.concat([result.eligible_keys.head(1), result.eligible_keys])
    with pytest.raises(M3IndexMembershipError, match="G1_MEMBERSHIP_ELIGIBLE_KEYS_INVALID") as dup_exc:
        ObservedMembershipResult(
            result.observations,
            result.membership,
            dup,
            result.observations_sha256,
            result.membership_sha256,
            result.eligible_keys_sha256,
        )
    assert dup_exc.value.__cause__ is None
    # Forged result with >300 on a session fails verify rebuild mismatch path via
    # constructor digest bind when height invents extras inconsistently; direct
    # oversize frame with unique keys still fails unique/digest closure.
    extra_row = pl.DataFrame(
        {"as_of": [fx["signal_start"]], "symbol": ["009998.SH"]}
    )
    oversized = pl.concat([result.eligible_keys, extra_row]).sort(["as_of", "symbol"])
    # Build would have rejected >300; constructor only checks uniqueness/non-empty.
    # Verifier rebuild must reject self-consistent forgery that adds a symbol.
    forged_digest = clean_table_content_sha256(table_name="eligible_keys", frame=oversized)
    forged = ObservedMembershipResult(
        result.observations,
        result.membership,
        oversized,
        result.observations_sha256,
        result.membership_sha256,
        forged_digest,
    )
    with pytest.raises(M3IndexMembershipError, match="G1_MEMBERSHIP_RESULT_INVALID"):
        verify_observed_membership_result(
            batch=fx["batch"],
            responses=fx["responses"],
            result=forged,
            calendars=fx["calendars"],
            instruments=fx["instruments"],
            universe=_UNIVERSE,
            signal_start=fx["signal_start"],
            signal_end=fx["signal_end"],
            expected_constituent_count=300,
        )


def test_package_exports() -> None:
    import quant.data as qd
    import quant.domain as domain

    assert qd.normalize_index_weight_observations is normalize_index_weight_observations
    assert qd.build_observed_membership is build_observed_membership
    assert qd.verify_observed_membership_result is verify_observed_membership_result
    assert qd.ObservedMembershipResult is ObservedMembershipResult
    assert qd.M3IndexMembershipError is M3IndexMembershipError
    assert domain.IndexConstituentObservationSchema is not None
