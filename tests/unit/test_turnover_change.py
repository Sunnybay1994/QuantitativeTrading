"""Hand-check the fixed ratio, session completeness and month-end sampling."""

import copy
import datetime as dt
from pathlib import Path
import tomllib

import polars as pl
from polars.testing import assert_frame_equal
import pytest

from quant.factors.turnover_change import FACTOR_NAME, compute_turnover_change
from quant.research.monthly_turnover_change import build_monthly_turnover_change, validate_turnover_change


DATES = tuple(dt.date(2023, 1, 2) + dt.timedelta(days=i) for i in range(260))


def frame(values: list[float | None]) -> pl.DataFrame:
    return pl.DataFrame({"symbol": ["A"] * len(values), "trade_date": DATES[:len(values)],
                         "turnover_rate": values}, schema_overrides={"turnover_rate": pl.Float64})


def test_nested_window_hand_calculation_scale_and_symbol_isolation() -> None:
    a = frame([1.] * 100 + [3.] * 20)
    b = a.with_columns(pl.lit("B").alias("symbol"), (pl.col("turnover_rate") * 7))
    r = compute_turnover_change(pl.concat([a, b]).reverse(), sessions=DATES[:120])
    for symbol in ("A", "B"):
        values = r.filter(pl.col("symbol") == symbol)[FACTOR_NAME].to_list()
        assert values[:119] == [None] * 119
        assert values[119] == pytest.approx(3 / (160 / 120))


@pytest.mark.parametrize("bad", [None, -1., float("nan"), float("inf")])
def test_invalid_observation_invalidates_long_window_and_recovers(bad: float | None) -> None:
    r = compute_turnover_change(frame([bad] + [2.] * 120), sessions=DATES[:121])
    assert r[FACTOR_NAME].to_list()[:120] == [None] * 120
    assert r[FACTOR_NAME][-1] == pytest.approx(1)


def test_missing_exchange_session_not_compressed() -> None:
    x = frame([1.] * 240).filter(pl.col("trade_date") != DATES[119])
    r = compute_turnover_change(x, sessions=DATES[:240])
    assert r[FACTOR_NAME].to_list()[:239] == [None] * 239
    assert r[FACTOR_NAME][-1] == pytest.approx(1)


def test_observed_zero_short_mean_valid_zero_long_mean_invalid() -> None:
    r = compute_turnover_change(frame([2.] * 100 + [0.] * 20), sessions=DATES[:120])
    assert r[FACTOR_NAME][-1] == 0
    r = compute_turnover_change(frame([0.] * 120), sessions=DATES[:120])
    assert r[FACTOR_NAME][-1] is None


def test_future_rows_do_not_change_past_and_calendar_controls_window() -> None:
    x = frame([1.] * 100 + [3.] * 20)
    before = compute_turnover_change(x, sessions=DATES[:120])
    after = compute_turnover_change(frame([1.] * 100 + [3.] * 20 + [99999.] * 20), sessions=DATES[:140])
    assert_frame_equal(before, after.filter(pl.col("trade_date") <= DATES[119]))
    sparse = tuple(d for i, d in enumerate(DATES) if i % 7 < 5)[:120]
    y = x.with_columns(pl.Series("trade_date", sparse))
    assert compute_turnover_change(y, sessions=sparse)[FACTOR_NAME][-1] == pytest.approx(2.25)


def test_duplicate_keys_rejected() -> None:
    x = frame([1.] * 120)
    with pytest.raises(ValueError, match="Duplicate"):
        compute_turnover_change(pl.concat([x, x.head(1)]), sessions=DATES[:120])


def test_monthly_builder_keeps_only_complete_month_ends_and_comparators() -> None:
    columns = ("close", "turnover_rate_free", "volume_ratio", "pe", "pe_ttm", "pb", "ps", "ps_ttm",
               "dividend_yield", "dividend_yield_ttm", "total_shares", "float_shares", "free_float_shares",
               "total_market_value", "circulating_market_value")
    x = frame([1.] * 260).with_columns(
        pl.lit("000001.SZ").alias("symbol"), pl.lit("tushare").alias("source"),
        *(pl.lit(1.).alias(c) for c in columns))
    r = build_monthly_turnover_change(x, sessions=DATES, candidates=("000001.SZ",), start=DATES[120], end=DATES[-1])
    assert r["trade_date"].to_list() == [dt.date(2023, m, d) for m, d in ((5, 31), (6, 30), (7, 31), (8, 31))]
    assert r[FACTOR_NAME].to_list() == pytest.approx([1.] * 4)
    assert "turnover_cv20" in r.columns and "free_float_turnover_abnormal_12m" in r.columns


def test_preregistered_config_rejects_window_direction_and_portfolio_changes() -> None:
    config = tomllib.loads(Path("configs/research/b62_turnover_change20_120_20260910.toml").read_text())
    validate_turnover_change(config)
    for section, key, value in (("turnover_change", "long_window_sessions", 250),
        ("turnover_change", "minimum_valid_sessions", 100), ("turnover_change", "long_window_includes_short", False),
        ("factors", "directions", [1]), ("portfolio", "top_k", 40), ("portfolio", "retention_rank", 100)):
        changed = copy.deepcopy(config)
        changed[section][key] = value
        with pytest.raises(ValueError, match="fixed negative"):
            validate_turnover_change(changed)
