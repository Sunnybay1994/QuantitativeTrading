"""Independent scalar calculations, null windows and information-time checks."""

import copy
import datetime as dt
from pathlib import Path
import statistics
import tomllib

import polars as pl
import pytest

from quant.factors.alpha101_001 import compute_alpha101_001
from quant.research.monthly_alpha101_001 import build_monthly_alpha101_001, validate_alpha101_001


DATES = tuple(dt.date(2023, 1, 1) + dt.timedelta(days=i) for i in range(65))


def sample() -> pl.DataFrame:
    rows = []
    for number, symbol in enumerate(("A", "B", "C", "D")):
        price = 10.
        for i, day in enumerate(DATES):
            price *= 1 + (.025 if (i + number) % 5 < number + 1 else -.015)
            rows.append(dict(symbol=symbol, trade_date=day, close=price, adj_factor=1., volume=100.))
    return pl.DataFrame(rows)


def scalar_position(prices: list[float], index: int) -> tuple[int, float, float]:
    returns = [prices[j] / prices[j-1] - 1 for j in range(1, index+1)]
    values = []
    for j in range(index-4, index+1):
        std = statistics.stdev(returns[j-20:j])
        values.append((std if returns[j-1] < 0 else prices[j]) ** 2)
    return values.index(max(values)) + 1, statistics.stdev(returns[-20:]), values[-1]


def test_all_values_match_scalar_formula_and_cross_section_ties() -> None:
    bars = sample()
    result = compute_alpha101_001(bars, sessions=DATES)
    assert result.filter(pl.col("trade_date") < DATES[24])["alpha101_001"].null_count() == 24 * 4
    for index in range(24, len(DATES)):
        expected = [scalar_position(bars.filter(pl.col("symbol") == s)["close"].to_list(), index)
                    for s in ("A", "B", "C", "D")]
        positions = [v[0] for v in expected]
        actual = result.filter(pl.col("trade_date") == DATES[index]).sort("symbol")
        assert actual["argmax_position"].to_list() == positions
        for row, (pos, std, squared) in zip(actual.iter_rows(named=True), expected, strict=True):
            rank = 1 + sum(p < pos for p in positions) + (positions.count(pos) - 1) / 2
            assert row["alpha101_001"] == pytest.approx((rank - 1) / 3 - .5)
            assert row["return_std20"] == pytest.approx(std)
            assert row["conditional_squared"] == pytest.approx(squared)


def test_flat_prices_tie_oldest_and_singleton_zero() -> None:
    bars = sample().filter(pl.col("symbol") == "A").with_columns(pl.lit(10.).alias("close"))
    result = compute_alpha101_001(bars, sessions=DATES).tail(1).row(0, named=True)
    assert result["argmax_position"] == 1
    assert result["alpha101_001"] == 0.


@pytest.mark.parametrize("column,bad", [("close", None), ("close", float("nan")),
    ("adj_factor", 0.), ("volume", 0.), ("volume", float("inf"))])
def test_invalid_price_window_cannot_be_skipped(column: str, bad: float | None) -> None:
    bars = sample().with_columns(pl.when((pl.col("symbol") == "A") & (pl.col("trade_date") == DATES[25]))
        .then(pl.lit(bad)).otherwise(pl.col(column)).alias(column))
    a = compute_alpha101_001(bars, sessions=DATES).filter(pl.col("symbol") == "A")
    assert a.filter(pl.col("trade_date").is_between(DATES[25], DATES[49]))["alpha101_001"].null_count() == 25
    assert a.filter(pl.col("trade_date") == DATES[50])["alpha101_001"].is_not_null().all()


def test_missing_session_is_not_compressed_and_future_cannot_change_past() -> None:
    bars = sample()
    missing = bars.filter(~((pl.col("symbol") == "A") & (pl.col("trade_date") == DATES[25])))
    a = compute_alpha101_001(missing, sessions=DATES).filter(pl.col("symbol") == "A")
    assert a.filter(pl.col("trade_date") == DATES[49])["alpha101_001"].item() is None
    changed = bars.with_columns(pl.when(pl.col("trade_date") > DATES[40]).then(999.)
        .otherwise(pl.col("close")).alias("close"))
    assert compute_alpha101_001(changed, sessions=DATES).filter(pl.col("trade_date") <= DATES[40]).equals(
        compute_alpha101_001(bars, sessions=DATES).filter(pl.col("trade_date") <= DATES[40]))


def test_month_ends_and_adjusted_price_consistency() -> None:
    bars = sample()
    split = bars.with_columns((pl.col("close") / 2).alias("close"), pl.lit(2.).alias("adj_factor"))
    assert compute_alpha101_001(bars, sessions=DATES).equals(compute_alpha101_001(split, sessions=DATES))
    monthly = build_monthly_alpha101_001(bars, sessions=DATES, start=DATES[0], end=DATES[-1])
    assert monthly["trade_date"].unique().sort().to_list() == [dt.date(2023, 1, 31), dt.date(2023, 2, 28)]


def test_fixed_configuration_and_duplicate_input() -> None:
    config = tomllib.loads(Path("configs/research/b67_alpha101_001_20260910.toml").read_text())
    validate_alpha101_001(config)
    for section, key, value in (("alpha101_001", "argmax_ties", "newest"),
        ("alpha101_001", "volatility_sessions", 10), ("factors", "directions", [-1]),
        ("portfolio", "retention_rank", 75)):
        changed = copy.deepcopy(config)
        changed[section][key] = value
        with pytest.raises(ValueError, match="fixed positive"):
            validate_alpha101_001(changed)
    with pytest.raises(ValueError, match="Duplicate"):
        compute_alpha101_001(pl.concat([sample(), sample().head(1)]), sessions=DATES)
