"""Independent correlation arithmetic, complete windows, and timing checks."""

import copy
import datetime as dt
import math
from pathlib import Path
import tomllib

import polars as pl
from polars.testing import assert_frame_equal
import pytest

from quant.factors.return_turnover_correlation import FACTOR_NAME, compute_return_turnover_correlation
from quant.research.monthly_return_turnover import build_monthly_return_turnover, validate_return_turnover


DATES = tuple(dt.date(2023, 1, 1) + dt.timedelta(days=i) for i in range(100))


def frames(n: int = 42) -> tuple[pl.DataFrame, pl.DataFrame]:
    prices = [100.]
    for i in range(1, n):
        prices.append(prices[-1] * (1 + ((i % 7) - 3) / 100))
    bars = pl.DataFrame({"symbol": ["000001.SZ"] * n, "trade_date": DATES[:n],
                        "close": prices, "adj_factor": [1.] * n})
    basic = bars.select("symbol", "trade_date").with_columns(pl.Series("turnover_rate", [float(i % 5) for i in range(n)]))
    return bars, basic


def test_hand_correlation_and_twenty_pairs_require_twenty_one_prices() -> None:
    bars, basic = frames(21)
    r = compute_return_turnover_correlation(bars, basic, sessions=DATES[:21])
    prices = bars["close"].to_list()
    x = [prices[i] / prices[i - 1] - 1 for i in range(1, 21)]
    y = basic["turnover_rate"].to_list()[1:]
    mx, my = math.fsum(x) / 20, math.fsum(y) / 20
    expected = math.fsum((a-mx)*(b-my) for a,b in zip(x,y)) / math.sqrt(
        math.fsum((a-mx)**2 for a in x) * math.fsum((b-my)**2 for b in y))
    assert r[FACTOR_NAME].to_list()[:20] == [None] * 20
    assert r[FACTOR_NAME][-1] == pytest.approx(expected)


@pytest.mark.parametrize("table,first_valid", [("bars", 31), ("basic", 30)])
def test_missing_session_is_not_compressed(table: str, first_valid: int) -> None:
    bars, basic = frames()
    if table == "bars":
        bars = bars.filter(pl.col("trade_date") != DATES[10])
    else:
        basic = basic.filter(pl.col("trade_date") != DATES[10])
    r = compute_return_turnover_correlation(bars, basic, sessions=DATES[:42])
    assert r[FACTOR_NAME].to_list()[:first_valid] == [None] * first_valid
    assert r[FACTOR_NAME][first_valid] is not None


@pytest.mark.parametrize("bad", [None, -1., float("inf"), float("nan")])
def test_invalid_turnover_breaks_pair_window(bad: float | None) -> None:
    bars, basic = frames()
    basic = basic.with_columns(pl.when(pl.col("trade_date") == DATES[10]).then(pl.lit(bad))
                               .otherwise(pl.col("turnover_rate")).alias("turnover_rate"))
    r = compute_return_turnover_correlation(bars, basic, sessions=DATES[:42])
    assert r[FACTOR_NAME].to_list()[:30] == [None] * 30
    assert r[FACTOR_NAME][30] is not None


def test_constant_inputs_invalid_and_observed_zeros_allowed() -> None:
    bars, basic = frames()
    assert compute_return_turnover_correlation(bars, basic, sessions=DATES[:42])[FACTOR_NAME][-1] is not None
    constant = basic.with_columns(pl.lit(1.).alias("turnover_rate"))
    assert compute_return_turnover_correlation(bars, constant, sessions=DATES[:42])[FACTOR_NAME].null_count() == 42
    flat = bars.with_columns(pl.lit(100.).alias("close"))
    assert compute_return_turnover_correlation(flat, basic, sessions=DATES[:42])[FACTOR_NAME].null_count() == 42


def test_split_adjustment_and_future_prefix_invariance() -> None:
    bars, basic = frames()
    before = compute_return_turnover_correlation(bars.head(21), basic.head(21), sessions=DATES[:21])
    full = compute_return_turnover_correlation(bars, basic, sessions=DATES[:42])
    assert_frame_equal(before, full.head(21))
    split = bars.with_columns(pl.when(pl.col("trade_date") >= DATES[10]).then(2.).otherwise(1.).alias("adj_factor"))
    split = split.with_columns((pl.col("close") / pl.col("adj_factor")).alias("close"))
    assert_frame_equal(full, compute_return_turnover_correlation(split, basic, sessions=DATES[:42]))


def test_symbol_isolation_and_duplicate_rejection() -> None:
    bars, basic = frames()
    other_bars = bars.with_columns(pl.lit("000002.SZ").alias("symbol"))
    other_basic = basic.with_columns(pl.lit("000002.SZ").alias("symbol"),
                                    (5-pl.col("turnover_rate")).alias("turnover_rate"))
    r = compute_return_turnover_correlation(pl.concat([other_bars, bars]).reverse(),
        pl.concat([other_basic, basic]).reverse(), sessions=DATES[:42])
    a = r.filter(pl.col("symbol") == "000001.SZ")[FACTOR_NAME][-1]
    b = r.filter(pl.col("symbol") == "000002.SZ")[FACTOR_NAME][-1]
    assert a == pytest.approx(-b)
    with pytest.raises(ValueError, match="Duplicate"):
        compute_return_turnover_correlation(bars, pl.concat([basic, basic.head(1)]), sessions=DATES[:42])


@pytest.mark.parametrize("bad", [0., -1., float("inf"), float("nan")])
def test_invalid_price_breaks_two_adjacent_returns(bad: float) -> None:
    bars, basic = frames()
    bars = bars.with_columns(pl.when(pl.col("trade_date") == DATES[10]).then(bad)
                             .otherwise(pl.col("close")).alias("close"))
    r = compute_return_turnover_correlation(bars, basic, sessions=DATES[:42])
    assert r[FACTOR_NAME].to_list()[:31] == [None] * 31
    assert r[FACTOR_NAME][31] is not None


def test_near_constant_turnover_is_invalid() -> None:
    bars, basic = frames()
    basic = basic.with_columns(pl.Series("turnover_rate", [1. + i * 1e-9 for i in range(42)]))
    assert compute_return_turnover_correlation(bars, basic, sessions=DATES[:42])[FACTOR_NAME].null_count() == 42


def test_monthly_sampling_and_distinct_comparators() -> None:
    bars, basic = frames(100)
    bars = bars.with_columns(*(pl.col("close").alias(c) for c in ("open", "high", "low")),
        pl.Series("volume", [1000. + i * i for i in range(100)]), pl.lit(100000.).alias("amount"),
        pl.lit("tushare").alias("source"))
    r = build_monthly_return_turnover(bars, basic, sessions=DATES, start=DATES[0], end=DATES[-1])
    assert r["trade_date"].to_list() == [dt.date(2023, 1, 31), dt.date(2023, 2, 28), dt.date(2023, 3, 31)]
    assert r[FACTOR_NAME].is_finite().all()
    assert {"alpha158_corr20", "alpha158_cord20"}.issubset(r.columns)


def test_preregistered_config_rejects_lag_window_direction_changes() -> None:
    config = tomllib.loads(Path("configs/research/b63_return_turnover_corr20_20260910.toml").read_text())
    validate_return_turnover(config)
    for section, key, value in (("return_turnover", "lag_sessions", 1),
        ("return_turnover", "window_sessions", 60), ("return_turnover", "minimum_pair_count", 15),
        ("return_turnover", "input_column", "turnover_rate_free"), ("factors", "directions", [1])):
        altered = copy.deepcopy(config)
        altered[section][key] = value
        with pytest.raises(ValueError, match="fixed synchronous"):
            validate_return_turnover(altered)
