from __future__ import annotations

import datetime as dt

import polars as pl
import pytest
from pandera.errors import SchemaError

from quant.factors.daily_value import (
    DAILY_VALUE_FACTOR_NAMES,
    DAILY_VALUE_FACTOR_SPECS,
    compute_daily_value_factors,
)


def _daily_basic(**overrides: object) -> pl.DataFrame:
    row: dict[str, object] = {
        "symbol": "000001.SZ",
        "trade_date": dt.date(2026, 8, 14),
        "close": 10.0,
        "turnover_rate": 1.0,
        "turnover_rate_free": 1.2,
        "volume_ratio": None,
        "pe": 12.0,
        "pe_ttm": 10.0,
        "pb": 2.0,
        "ps": 5.0,
        "ps_ttm": 4.0,
        "dividend_yield": 1.0,
        "dividend_yield_ttm": 2.0,
        "total_shares": 10_000_000.0,
        "float_shares": 8_000_000.0,
        "free_float_shares": 7_000_000.0,
        "total_market_value": 100_000_000.0,
        "circulating_market_value": 80_000_000.0,
        "source": "tushare",
    }
    row.update(overrides)
    return pl.DataFrame([row])


def test_catalog_and_hand_values_are_frozen() -> None:
    assert tuple(spec.name for spec in DAILY_VALUE_FACTOR_SPECS) == (
        DAILY_VALUE_FACTOR_NAMES
    )
    result = compute_daily_value_factors(_daily_basic())
    assert result.get_column("daily_ep_ttm_positive").item() == pytest.approx(0.1)
    assert result.get_column("daily_bp_positive").item() == pytest.approx(0.5)
    assert result.get_column("daily_sp_ttm_positive").item() == pytest.approx(0.25)
    assert result.get_column("daily_dividend_yield_ttm").item() == pytest.approx(
        0.02
    )
    assert result.get_column("log_total_market_value").item() == pytest.approx(
        18.420680743952367
    )


def test_losses_and_invalid_denominators_propagate_to_null() -> None:
    result = compute_daily_value_factors(
        _daily_basic(pe_ttm=-10.0, pb=None, ps_ttm=0.0, dividend_yield_ttm=None)
    )
    assert result.select(DAILY_VALUE_FACTOR_NAMES).row(0) == (
        None,
        None,
        None,
        None,
    )


def test_zero_dividend_is_not_treated_as_missing() -> None:
    result = compute_daily_value_factors(_daily_basic(dividend_yield_ttm=0.0))
    assert result.get_column("daily_dividend_yield_ttm").item() == 0.0


def test_duplicate_key_and_empty_input_are_rejected() -> None:
    row = _daily_basic()
    with pytest.raises(SchemaError, match="symbol_date_source_unique"):
        compute_daily_value_factors(pl.concat([row, row]))
    with pytest.raises(ValueError, match="must be non-empty"):
        compute_daily_value_factors(pl.DataFrame())
