"""Check exact 252/21 endpoints and independence from the skipped month."""

import copy
import datetime as dt
from pathlib import Path
import tomllib

import polars as pl
import pytest

from quant.research.monthly_momentum_12_1 import build_monthly_momentum_12_1, validate_momentum_12_1


DATES = tuple(dt.date(2022, 1, 1) + dt.timedelta(days=i) for i in range(400))
SIGNAL = DATES[364]


def bars() -> pl.DataFrame:
    return pl.DataFrame({"symbol": ["A"] * 400, "trade_date": DATES,
        "close": [100. + i for i in range(400)], "adj_factor": [1.] * 400, "volume": [1000.] * 400})


def value(x: pl.DataFrame) -> dict:
    return build_monthly_momentum_12_1(x, sessions=DATES, start=SIGNAL, end=DATES[-1]).filter(
        pl.col("trade_date") == SIGNAL).row(0, named=True)


def test_exact_endpoints_and_distinction_from_b26() -> None:
    r = value(bars())
    assert r["momentum_12_1"] == pytest.approx(443 / 212 - 1)
    assert r["pret_12m_skip1m"] == pytest.approx(443 / 191 - 1)
    assert r["formation_valid_returns"] == 231
    assert r["formation_price_start"] == DATES[112]
    assert r["formation_end"] == DATES[343]


def test_skipped_month_and_future_prices_cannot_change_signal() -> None:
    x = bars().with_columns(pl.when(pl.col("trade_date") > DATES[343]).then(999999.)
        .otherwise(pl.col("close")).alias("close"),
        pl.when(pl.col("trade_date") > DATES[343]).then(0.)
        .otherwise(pl.col("volume")).alias("volume"))
    assert value(x) == value(bars())


@pytest.mark.parametrize("column,bad", [("close", None), ("close", 0.), ("volume", 0.)])
def test_invalid_formation_observation_invalidates_primary(column: str, bad: float | None) -> None:
    x = bars().with_columns(pl.when(pl.col("trade_date") == DATES[150]).then(pl.lit(bad))
                            .otherwise(pl.col(column)).alias(column))
    assert value(x)["momentum_12_1"] is None


def test_missing_before_primary_window_only_invalidates_long_comparator() -> None:
    x = bars().filter(pl.col("trade_date") != DATES[100])
    r = value(x)
    assert r["momentum_12_1"] == pytest.approx(443 / 212 - 1)
    assert r["pret_12m_skip1m"] is None
    assert value(bars().filter(pl.col("trade_date") != DATES[150]))["momentum_12_1"] is None


def test_flat_prices_valid_and_only_completed_month_ends() -> None:
    x = bars().with_columns(pl.lit(100.).alias("close"))
    assert value(x)["momentum_12_1"] == 0
    r = build_monthly_momentum_12_1(x, sessions=DATES, start=SIGNAL, end=DATES[-1])
    assert r["trade_date"].to_list() == [SIGNAL, dt.date(2023, 1, 31)]


def test_fixed_configuration_rejects_b26_window_and_filters() -> None:
    config = tomllib.loads(Path("configs/research/b66_momentum12_1_20260910.toml").read_text())
    validate_momentum_12_1(config)
    for section, key, val in (("momentum_12_1", "formation_sessions", 252),
        ("momentum_12_1", "skip_sessions", 0), ("momentum_12_1", "winner_fraction", .2),
        ("factors", "directions", [-1]), ("portfolio", "top_k", 40)):
        altered = copy.deepcopy(config)
        altered[section][key] = val
        with pytest.raises(ValueError, match="fixed positive"):
            validate_momentum_12_1(altered)
