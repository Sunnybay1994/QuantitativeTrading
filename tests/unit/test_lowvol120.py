"""Sample-volatility arithmetic and equivalence with the existing B3 estimator."""

import copy
import datetime as dt
import math
from pathlib import Path
import statistics
import tomllib

import polars as pl
from polars.testing import assert_frame_equal
import pytest

from quant.factors.reversal_volatility import compute_reversal_volatility_factors, compute_total_volatility_windows
from quant.research.monthly_lowvol120 import (
    build_monthly_lowvol120, validate_lowvol120, validate_lowvol60_composition,
)


DATES = tuple(dt.date(2023, 1, 1) + dt.timedelta(days=i) for i in range(240))


def bars(n: int = 240) -> pl.DataFrame:
    prices = [100.]
    for i in range(1, n):
        prices.append(prices[-1] * (1 + ((i % 9) - 4) / 100))
    return pl.DataFrame({"symbol": ["A"] * n, "trade_date": DATES[:n],
                         "close": prices, "adj_factor": [1.] * n})


def test_hand_standard_deviation_and_full_return_count() -> None:
    x = bars(121)
    r = compute_total_volatility_windows(x, sessions=DATES[:121])
    prices = x["close"].to_list()
    returns = [prices[i] / prices[i - 1] - 1 for i in range(1, 121)]
    assert r["realized_volatility_120"].to_list()[:120] == [None] * 120
    assert r["realized_volatility_60"].to_list()[:60] == [None] * 60
    assert r["realized_volatility_120"][-1] == pytest.approx(statistics.stdev(returns) * math.sqrt(252))
    assert r["realized_volatility_60"][-1] == pytest.approx(statistics.stdev(returns[-60:]) * math.sqrt(252))


@pytest.mark.parametrize("bad", [None, 0., -1., float("inf"), float("nan")])
def test_invalid_price_invalidates_complete_window(bad: float | None) -> None:
    x = bars().with_columns(pl.when(pl.col("trade_date") == DATES[10]).then(pl.lit(bad))
                            .otherwise(pl.col("close")).alias("close"))
    r = compute_total_volatility_windows(x, sessions=DATES)
    assert r["realized_volatility_120"].to_list()[:131] == [None] * 131
    assert r["realized_volatility_120"][131] is not None


def test_missing_session_not_compressed_and_flat_prices_valid_zero() -> None:
    x = bars().filter(pl.col("trade_date") != DATES[10])
    r = compute_total_volatility_windows(x, sessions=DATES)
    assert r["realized_volatility_120"].to_list()[:131] == [None] * 131
    assert r["realized_volatility_120"][131] is not None
    flat = bars(121).with_columns(pl.lit(100.).alias("close"))
    assert compute_total_volatility_windows(flat, sessions=DATES[:121])["realized_volatility_120"][-1] == 0


def test_original_sixty_session_estimator_matches() -> None:
    x = bars(140)
    basic = x.select("symbol", "trade_date").with_columns(
        pl.lit(1000.).alias("total_market_value"), pl.lit(1.).alias("pb"))
    settings = {"reversal_window_sessions": 20, "volatility_window_sessions": 60,
                "annualization_sessions": 252, "proxy_minimum_bucket_symbols": 1, "ivol_window_sessions": 60}
    old, _ = compute_reversal_volatility_factors(x, basic, sessions=DATES[:140], settings=settings)
    new = compute_total_volatility_windows(x, sessions=DATES[:140])
    assert_frame_equal(old.select("symbol", "trade_date", "realized_volatility_60"),
                       new.select("symbol", "trade_date", "realized_volatility_60"))


def test_future_rows_split_and_symbol_isolation() -> None:
    x = bars()
    before = compute_total_volatility_windows(x.head(121), sessions=DATES[:121])
    full = compute_total_volatility_windows(x, sessions=DATES)
    assert_frame_equal(before, full.head(121))
    other = x.with_columns(pl.lit("B").alias("symbol"), pl.lit(2.).alias("adj_factor"),
                            (pl.col("close") / 2).alias("close"))
    together = compute_total_volatility_windows(pl.concat([other, x]).reverse(), sessions=DATES)
    assert_frame_equal(full, together.filter(pl.col("symbol") == "A"))
    assert_frame_equal(full.drop("symbol"), together.filter(pl.col("symbol") == "B").drop("symbol"))


def test_monthly_only_and_duplicate_keys() -> None:
    x = bars()
    r = build_monthly_lowvol120(x, sessions=DATES, start=dt.date(2023, 5, 1), end=DATES[-1])
    assert r["trade_date"].to_list() == [dt.date(2023, m, d) for m, d in ((5,31), (6,30), (7,31))]
    with pytest.raises(ValueError, match="Duplicate"):
        compute_total_volatility_windows(pl.concat([x, x.head(1)]), sessions=DATES)


def test_preregistered_fixed_window_and_direction() -> None:
    config = tomllib.loads(Path("configs/research/b64_lowvol120_20260910.toml").read_text())
    validate_lowvol120(config)
    for section, key, value in (("lowvol120", "window_sessions", 60), ("lowvol120", "standard_deviation_ddof", 0),
        ("lowvol120", "minimum_valid_returns", 100), ("factors", "directions", [1]), ("portfolio", "top_k", 40)):
        altered = copy.deepcopy(config)
        altered[section][key] = value
        with pytest.raises(ValueError, match="fixed negative"):
            validate_lowvol120(altered)


def test_sixty_day_composition_requires_fixed_same_pool_and_positive_increment() -> None:
    config = tomllib.loads(Path("configs/research/b65_lowvol60_composite_20260910.toml").read_text())
    validate_lowvol60_composition(config)
    for section, key, value in (("lowvol60", "window_sessions", 120),
        ("lowvol60_composition", "weights", "optimized"), ("lowvol60_composition", "eligibility", "three_factor_only"),
        ("portfolio", "top_k", 40), ("portfolio", "retention_rank", 100),
        ("admission", "comparison", "510300"), ("admission", "require_positive_paired_1x_compounded_increment", False),
        ("factors", "directions", [-1,1,-1,1])):
        altered = copy.deepcopy(config)
        altered[section][key] = value
        with pytest.raises(ValueError, match="same-pool"):
            validate_lowvol60_composition(altered)
