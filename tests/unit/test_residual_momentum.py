import calendar
import datetime as dt

import numpy as np
import polars as pl
import pytest
from polars.testing import assert_frame_equal

from quant.factors.residual_momentum import SIGNAL_COLUMNS, compute_residual_momentum


def sample(count=48):
    dates = tuple(dt.date(2010 + n // 12, 1 + n % 12,
                         calendar.monthrange(2010 + n // 12, 1 + n % 12)[1])
                  for n in range(count))
    rng = np.random.default_rng(92)
    x = rng.normal(0, .025, (count, 3))
    y = .004 + x @ np.array([1.1, -.25, .4]) + rng.normal(0, .015, count)
    stocks = pl.DataFrame({"symbol": ["A"] * count, "trade_date": dates, "stock_return": y})
    factors = pl.DataFrame({"trade_date": dates, "market_return": x[:, 0],
                            "smb_return": x[:, 1], "hml_return": x[:, 2]})
    return stocks, factors, dates, y, x


def test_matches_independent_qr_ols_and_exact_formation_windows():
    stocks, factors, dates, y, x = sample()
    result = compute_residual_momentum(stocks, factors, month_ends=dates,
                                       risk_free_monthly=.002)
    predictors = x[-36:].copy()
    predictors[:, 0] -= .002
    design = np.column_stack((np.ones(36), predictors))
    # Independent projection through QR, not the implementation's least-squares call.
    q, _ = np.linalg.qr(design)
    excess = y[-36:] - .002
    residual = excess - q @ (q.T @ excess)
    last = result.row(-1, named=True)
    assert last["regression_status"] == "ok"
    assert last["history_months"] == 36
    for label, count in (("12_1", 11), ("6_skip1", 6)):
        formation = residual[-count - 1:-1]
        assert last[f"residual_momentum_{label}_ff3_36"] == pytest.approx(
            formation.sum() / formation.std(ddof=1))
        stock_formation = y[-count - 1:-1]
        raw = np.prod(1 + stock_formation) - 1
        assert last[f"raw_momentum_{label}"] == pytest.approx(raw)
        assert last[f"vol_scaled_momentum_{label}"] == pytest.approx(
            raw / stock_formation.std(ddof=1))
    assert result.head(35)["residual_momentum_12_1_ff3_36"].null_count() == 35
    assert result.row(35, named=True)["regression_status"] == "ok"


def test_future_perturbation_and_appending_months_do_not_change_past_signals():
    stocks, factors, dates, _, _ = sample()
    cutoff = dates[39]
    baseline = compute_residual_momentum(stocks, factors, month_ends=dates)
    changed_stocks = stocks.with_columns(pl.when(pl.col("trade_date") > cutoff)
        .then(.85).otherwise(pl.col("stock_return")).alias("stock_return"))
    changed_factors = factors.with_columns(
        *(pl.when(pl.col("trade_date") > cutoff).then(.73).otherwise(pl.col(c)).alias(c)
          for c in ("market_return", "smb_return", "hml_return")))
    changed = compute_residual_momentum(changed_stocks, changed_factors, month_ends=dates)
    past = baseline.filter(pl.col("trade_date") <= cutoff)
    assert_frame_equal(past, changed.filter(pl.col("trade_date") <= cutoff))
    prefix = compute_residual_momentum(
        stocks.filter(pl.col("trade_date") <= cutoff),
        factors.filter(pl.col("trade_date") <= cutoff), month_ends=dates[:40])
    assert_frame_equal(prefix, past)


@pytest.mark.parametrize("missing_input", ["stocks", "factors"])
def test_missing_calendar_month_does_not_bridge_regression(missing_input):
    stocks, factors, dates, _, _ = sample(74)
    missing = dates[36]
    if missing_input == "stocks":
        stocks = stocks.filter(pl.col("trade_date") != missing)
    else:
        factors = factors.filter(pl.col("trade_date") != missing)
    result = compute_residual_momentum(stocks, factors, month_ends=dates)
    name = "missing_stock_month" if missing_input == "stocks" else "missing_factor_month"
    assert result.row(35, named=True)["regression_status"] == "ok"
    assert result.row(71, named=True)["regression_status"] == name
    assert result.row(71, named=True)["residual_momentum_12_1_ff3_36"] is None
    assert result.row(72, named=True)["regression_status"] == "ok"


def test_historical_delisted_symbol_is_retained_without_endpoint_survival_filter():
    stocks, factors, dates, _, _ = sample()
    old = stocks.head(38).with_columns(pl.lit("DELISTED").alias("symbol"))
    combined = compute_residual_momentum(pl.concat([stocks, old]), factors, month_ends=dates)
    old_result = combined.filter(pl.col("symbol") == "DELISTED")
    assert old_result.height == len(dates)
    assert old_result.row(37, named=True)["regression_status"] == "ok"
    assert old_result.row(38, named=True)["regression_status"] == "missing_stock_month"
    separate = compute_residual_momentum(old, factors, month_ends=dates)
    assert_frame_equal(old_result, separate)


@pytest.mark.parametrize("constant_stock", [False, True])
def test_zero_residual_variance_is_missing_not_an_explosive_score(constant_stock):
    stocks, factors, dates, _, x = sample()
    returns = np.full(len(dates), .007) if constant_stock else .01 + x @ np.array([.7, 1., -.2])
    stocks = stocks.with_columns(pl.Series("stock_return", returns))
    last = compute_residual_momentum(stocks, factors, month_ends=dates).row(-1, named=True)
    assert last["regression_status"] == "ok"
    for label in ("12_1", "6_skip1"):
        assert last[f"residual_momentum_{label}_ff3_36"] is None
        assert last[f"raw_momentum_{label}"] is not None
        if constant_stock:
            assert last[f"vol_scaled_momentum_{label}"] is None


@pytest.mark.parametrize("duplicate_input", ["stocks", "factors"])
def test_duplicate_keys_are_rejected(duplicate_input):
    stocks, factors, dates, _, _ = sample()
    if duplicate_input == "stocks":
        stocks = pl.concat([stocks, stocks.head(1)])
    else:
        factors = pl.concat([factors, factors.head(1)])
    with pytest.raises(ValueError, match="Duplicate monthly keys"):
        compute_residual_momentum(stocks, factors, month_ends=dates)


@pytest.mark.parametrize("bad_value", [None, float("nan"), float("inf"), -1.01])
def test_invalid_stock_return_invalidates_common_cohort(bad_value):
    stocks, factors, dates, _, _ = sample()
    stocks = stocks.with_columns(pl.when(pl.col("trade_date") == dates[-5])
                                .then(bad_value).otherwise(pl.col("stock_return"))
                                .alias("stock_return"))
    last = compute_residual_momentum(stocks, factors, month_ends=dates).row(-1, named=True)
    assert last["regression_status"] == "invalid_stock_return"
    assert all(last[name] is None for name in SIGNAL_COLUMNS)


def test_rank_deficient_proxy_is_missing_and_grid_cannot_skip_months():
    stocks, factors, dates, _, _ = sample()
    collinear = factors.with_columns(pl.col("market_return").alias("hml_return"))
    last = compute_residual_momentum(stocks, collinear, month_ends=dates).row(-1, named=True)
    assert last["regression_status"] == "rank_deficient"
    assert all(last[name] is None for name in SIGNAL_COLUMNS)
    with pytest.raises(ValueError, match="calendar-month contiguous"):
        compute_residual_momentum(stocks, factors, month_ends=dates[:4] + dates[5:])


def test_observations_must_match_exact_exchange_month_end():
    stocks, factors, dates, _, _ = sample()
    stocks = stocks.with_columns(pl.col("trade_date").dt.offset_by("-1d"))
    with pytest.raises(ValueError, match="exact supplied month end"):
        compute_residual_momentum(stocks, factors, month_ends=dates)
