from __future__ import annotations

import datetime as dt
import math

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from quant.data.daily_value_quality import diagnose_daily_value_inputs


_DATE = dt.date(2026, 9, 11)
_DIVIDEND = "daily_dividend_yield_ttm"


def _pool(symbols: list[str]) -> pl.DataFrame:
    return pl.DataFrame(
        {"symbol": symbols, "trade_date": [_DATE] * len(symbols)},
        schema={"symbol": pl.String, "trade_date": pl.Date},
    )


def _values(column: str, values: dict[str, float | None]) -> pl.DataFrame:
    return _pool(list(values)).with_columns(
        pl.Series(column, list(values.values()), dtype=pl.Float64)
    )


def test_dividend_zero_is_observed_and_source_null_nan_infinity_stay_distinct() -> None:
    basic = _values(
        "dividend_yield_ttm",
        {"zero": 0.0, "null": None, "nan": float("nan"), "inf": float("inf")},
    )
    factors = _values("value", {"zero": 0.0, "null": 0.0, "nan": None, "inf": 0.0})
    result = diagnose_daily_value_inputs(
        pool=basic.select("symbol", "trade_date"),
        basic=basic,
        factor_values=factors,
        factor_id=_DIVIDEND,
    )
    assert result["reason"].to_list() == [
        "observed", "source_field_null", "source_nonfinite", "source_nonfinite"
    ]
    assert result["unexpected_factor_value"].to_list() == [False, True, False, True]
    source = result["source_value"].to_list()
    assert source[:2] == [0.0, None]
    assert math.isnan(source[2]) and math.isinf(source[3])
    assert result["source_row_present"].to_list() == [True] * 4


def test_nonpositive_pe_is_definitionally_missing_without_inferring_null_pe_losses() -> None:
    basic = _values("pe_ttm", {"negative": -5.0, "zero": 0.0, "null": None, "ok": 20.0})
    result = diagnose_daily_value_inputs(
        pool=basic.select("symbol", "trade_date"),
        basic=basic,
        factor_values=_values("value", {"negative": 0.0, "zero": None, "ok": 0.05}),
        factor_id="daily_ep_ttm_positive",
    )
    assert result["reason"].to_list() == [
        "definition_nonpositive_pe", "definition_nonpositive_pe", "source_field_null", "observed"
    ]
    assert result["unexpected_factor_value"].to_list() == [True, False, False, False]
    assert result["factor_row_present"].to_list() == [True, True, False, True]


def test_source_and_factor_join_gaps_are_distinct_and_source_reason_takes_priority() -> None:
    symbols = ["source_absent", "factor_absent", "both_absent", "null", "nan", "inf"]
    basic = _values("dividend_yield_ttm", dict.fromkeys(symbols[1:2] + symbols[3:], 2.0))
    factors = _values(
        "value", {"source_absent": 0.02, "null": None, "nan": float("nan"), "inf": float("inf")}
    )
    result = diagnose_daily_value_inputs(
        pool=_pool(symbols), basic=basic, factor_values=factors, factor_id=_DIVIDEND,
    )
    assert result["reason"].to_list() == [
        "source_row_missing", "factor_row_missing", "source_row_missing",
        "factor_value_missing", "factor_value_missing", "factor_value_missing",
    ]
    assert result["source_row_present"].to_list() == [False, True, False, True, True, True]
    assert result["factor_row_present"].to_list() == [True, False, False, True, True, True]
    assert result["unexpected_factor_value"].to_list() == [True, False, False, False, False, False]


def test_percent_conversion_mismatch_and_absolute_tolerance_are_checked() -> None:
    basic = _values("dividend_yield_ttm", {"ok": 2.0, "near": 2.0, "far": 2.0, "units": 2.0})
    result = diagnose_daily_value_inputs(
        pool=basic.select("symbol", "trade_date"),
        basic=basic,
        factor_values=_values("value", {"ok": 0.02, "near": 0.02 + 5e-11,
                                       "far": 0.02 + 2e-10, "units": 2.0}),
        factor_id=_DIVIDEND,
    )
    assert result["reason"].to_list() == [
        "observed", "observed", "factor_value_mismatch", "factor_value_mismatch"
    ]
    assert result["source_value"].to_list() == [2.0] * 4
    assert not result["unexpected_factor_value"].any()


@pytest.mark.parametrize("duplicate", ["pool", "basic", "factor_values"])
def test_duplicate_keys_are_rejected_for_each_input(duplicate: str) -> None:
    frames = {
        "pool": _pool(["a"]),
        "basic": _values("dividend_yield_ttm", {"a": 2.0}),
        "factor_values": _values("value", {"a": 0.02}),
    }
    frames[duplicate] = pl.concat([frames[duplicate], frames[duplicate]])
    with pytest.raises(ValueError, match=f"{duplicate} contains duplicate"):
        diagnose_daily_value_inputs(**frames, factor_id=_DIVIDEND)


def test_extra_rows_are_ignored_alias_is_supported_and_inputs_are_unchanged() -> None:
    frames = {
        "pool": _pool(["b", "a"]),
        "basic": _values("dividend_yield_ttm", {"a": 2.0, "outside": None, "b": 4.0}),
        "factor_values": _values("value", {"outside": 0.0, "a": 0.02, "b": 0.04})
        .rename({"symbol": "ts_code"}),
    }
    snapshots = {name: frame.clone() for name, frame in frames.items()}
    result = diagnose_daily_value_inputs(**frames, factor_id=_DIVIDEND)
    assert result["symbol"].to_list() == ["b", "a"]
    assert result["reason"].to_list() == ["observed", "observed"]
    assert not result["unexpected_factor_value"].any()
    for name in frames:
        assert_frame_equal(frames[name], snapshots[name])


def test_empty_pool_returns_typed_empty_result() -> None:
    result = diagnose_daily_value_inputs(
        pool=_pool([]), basic=_values("dividend_yield_ttm", {}),
        factor_values=_values("value", {}), factor_id=_DIVIDEND,
    )
    assert result.is_empty()
    assert result.schema == {
        "symbol": pl.String, "trade_date": pl.Date, "source_row_present": pl.Boolean,
        "source_value": pl.Float64, "factor_row_present": pl.Boolean, "factor_value": pl.Float64,
        "reason": pl.String, "unexpected_factor_value": pl.Boolean,
    }


def test_unsupported_factor_and_missing_columns_are_rejected() -> None:
    frames = {
        "pool": _pool(["a"]),
        "basic": _values("dividend_yield_ttm", {"a": 2.0}),
        "factor_values": _values("value", {"a": 0.02}),
    }
    with pytest.raises(ValueError, match="Unsupported daily value factor"):
        diagnose_daily_value_inputs(**frames, factor_id="pit_sue8")
    with pytest.raises(ValueError, match="basic missing required columns"):
        diagnose_daily_value_inputs(**frames, factor_id="daily_ep_ttm_positive")
