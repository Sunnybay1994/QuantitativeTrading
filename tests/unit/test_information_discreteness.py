import datetime as dt
from pathlib import Path
import tomllib

import polars as pl
import pytest

from quant.factors.information_discreteness import compute_information_discreteness
from quant.research.classic_factor_composite import build_equal_weight_zscore_composite, build_monthly_zscore_targets
from quant.research.monthly_information_discreteness import (
    build_monthly_information_discreteness, select_information_winners,
    summarize_information_pair,
)


def sample(prices=(100., 110., 110., 99., 120., 10., 1000.)):
    sessions = tuple(dt.date(2024, 1, 1) + dt.timedelta(days=i) for i in range(len(prices)))
    bars = pl.DataFrame({"trade_date": sessions, "symbol": ["A"] * len(prices), "close": prices,
                         "adj_factor": [1.] * len(prices), "volume": [1000.] * len(prices)})
    return bars, sessions


def compute(bars, sessions):
    return compute_information_discreteness(bars, sessions=sessions, formation_sessions=4, skip_sessions=2)


def test_equal_pret_different_path_and_zero_denominator_hand_check():
    bars, sessions = sample()
    row = compute(bars, sessions).tail(1).to_dicts()[0]
    assert row["pret_12m_skip1m"] == pytest.approx(.2)
    assert row["information_discreteness"] == -.25
    assert (row["formation_positive_days"], row["formation_negative_days"], row["formation_zero_days"]) == (2, 1, 1)
    assert row["formation_valid_returns"] == 4
    assert row["formation_price_start"] == sessions[0] and row["formation_end"] == sessions[4]
    other, _ = sample((100., 90., 80., 70., 120., 10., 1000.))
    row2 = compute(other, sessions).tail(1).to_dicts()[0]
    assert row2["pret_12m_skip1m"] == pytest.approx(.2)
    assert row2["information_discreteness"] == .5


@pytest.mark.parametrize("prices,expected", [
    ((100., 110., 110., 90., 100., 10., 1000.), 0.),
    ((100., 90., 90., 80., 75., 10., 1000.), -.75),
    ((100., 100., 100., 100., 100., 10., 1000.), 0.),
])
def test_negative_and_zero_pret(prices, expected):
    bars, sessions = sample(prices)
    assert compute(bars, sessions)["information_discreteness"][-1] == expected


def test_skip_boundary_no_future_leakage_and_adjustment():
    bars, sessions = sample()
    expected = compute(bars, sessions)
    changed = bars.with_columns(pl.when(pl.col("trade_date") > sessions[4])
        .then(30000.).otherwise(pl.col("close")).alias("close"))
    assert compute(changed, sessions).equals(expected)
    assert expected["information_discreteness"].to_list() == [None] * 6 + [-.25]
    longer, later = sample((100., 110., 110., 99., 120., 10., 1000., 5000.))
    assert compute(longer, later).head(7).equals(expected)
    split = bars.with_columns(
        pl.when(pl.col("trade_date") >= sessions[1]).then(pl.col("close") / 2).otherwise(pl.col("close")).alias("close"),
        pl.when(pl.col("trade_date") >= sessions[1]).then(2.).otherwise(1.).alias("adj_factor"),
    )
    assert compute(split, sessions).equals(expected)


@pytest.mark.parametrize("case", ["missing", "zero_volume", "zero_price", "null_price", "nan_factor"])
def test_missing_or_invalid_formation_day_does_not_bridge(case):
    bars, sessions = sample()
    bad_date = pl.col("trade_date") == sessions[2]
    if case == "missing":
        bars = bars.filter(~bad_date)
    else:
        column, value = {"zero_volume": ("volume", 0.), "zero_price": ("close", 0.),
                         "null_price": ("close", None), "nan_factor": ("adj_factor", float("nan"))}[case]
        bars = bars.with_columns(pl.when(bad_date).then(value).otherwise(pl.col(column)).alias(column))
    row = compute(bars, sessions).tail(1).to_dicts()[0]
    assert row["pret_12m_skip1m"] is None and row["information_discreteness"] is None
    assert row["formation_valid_returns"] == 2


def test_missing_skipped_day_is_not_part_of_formation_and_duplicate_rejected():
    bars, sessions = sample()
    assert compute(bars.filter(pl.col("trade_date") != sessions[5]), sessions)["information_discreteness"][-1] == -.25
    with pytest.raises(ValueError, match="Duplicate"):
        compute(pl.concat([bars, bars.tail(1)]), sessions)
    with pytest.raises(ValueError, match="increasing"):
        compute(bars, tuple(reversed(sessions)))


def test_winner_pool_is_shared_floor_quintile_with_symbol_ties():
    # An invalid high-PRET name must not change the eligible-count denominator.
    data = pl.DataFrame({"trade_date": [dt.date(2024, 1, 31)] * 12,
                         "symbol": [f"S{i:02}" for i in range(12)],
                         "pret_12m_skip1m": [99., .9, .9, .9, .7, .6, .5, .4, .3, .2, .1, 0.],
                         "information_discreteness": [None, .5, -.25, -.9, 0., 0., 0., 0., 0., 0., 0., 0.]})
    winners = select_information_winners(data.reverse())
    assert winners["symbol"].to_list() == ["S01", "S02"]
    assert winners["formation_eligible_count"].to_list() == [11, 11]
    assert winners["winner_pool_count"].to_list() == [2, 2]
    # Same past winners: low-ID ordering differs from highest PRET/ticker ordering.
    assert winners.sort("information_discreteness", "symbol")["symbol"][0] == "S02"


def test_paired_top50_uses_identical_winners_and_next_session_open():
    signal, execution = dt.date(2024, 1, 31), dt.date(2024, 2, 1)
    data = pl.DataFrame({"trade_date": [signal] * 300, "symbol": [f"S{i:03}" for i in range(300)],
                         "pret_12m_skip1m": [i / 100 for i in range(300)],
                         "information_discreteness": [i / 300 for i in range(300)]})
    pool = select_information_winners(data)
    assert pool.height == 60
    targets = []
    for factor, direction in (("information_discreteness", -1), ("pret_12m_skip1m", 1)):
        scored = build_equal_weight_zscore_composite(pool, component_directions=((factor, direction),))
        targets.append(build_monthly_zscore_targets(scored, sessions=(signal, execution), start=execution,
                       end=execution, top_k=50, strategy_name=factor))
    assert targets[0]["symbol"].to_list() == [f"S{i:03}" for i in range(240, 290)]
    assert targets[1]["symbol"].to_list() == [f"S{i:03}" for i in range(250, 300)]
    for target in targets:
        assert target["as_of"].unique().to_list() == [signal]
        assert target["execution_date"].unique().to_list() == [execution]
        assert target["weight"].sum() == pytest.approx(1.)


def test_monthly_adapter_has_full_273_session_warmup_and_fixed_parameters():
    dates = tuple(dt.date(2022, 1, 1) + dt.timedelta(days=i) for i in range(390))
    bars = pl.DataFrame({"trade_date": dates, "symbol": ["A"] * len(dates),
                         "close": [100 * 1.001 ** i for i in range(len(dates))],
                         "adj_factor": [1.] * len(dates), "volume": [1.] * len(dates)})
    full = compute_information_discreteness(bars, sessions=dates)
    assert full["information_discreteness"][:273].null_count() == 273
    assert full["information_discreteness"][273] == -1.
    assert full["pret_12m_skip1m"][273] == pytest.approx(1.001 ** 252 - 1)
    root = Path(__file__).resolve().parents[2]
    settings = tomllib.loads((root / "configs/research/b26_information_discreteness_20260909.toml").read_text())["information_discreteness"]
    monthly = build_monthly_information_discreteness(bars=bars, sessions=dates, start=dates[300], end=dates[-1], settings=settings)
    assert monthly["trade_date"].to_list() == [dt.date(2022, 10, 31), dt.date(2022, 11, 30), dt.date(2022, 12, 31)]
    assert monthly["information_discreteness"].to_list() == [-1., -1., -1.]
    with pytest.raises(ValueError, match="pre-registered"):
        build_monthly_information_discreteness(bars=bars, sessions=dates, start=dates[300], end=dates[-1],
                                             settings={**settings, "skip_sessions": 0})


@pytest.mark.parametrize("one,stress,expected", [
    ([.1, .1, .1], [.05, .05, .05], True),
    ([.1, .1, -.01], [.05, .05, -.01], True),
    ([.1, -.01, -.01], [.05, .05, .05], False),
    ([.1, .1, -.5], [.05, .05, .05], False),
    ([.1, .1, .1], [-.01, -.01, -.01], False),
    ([0., 0., 0.], [.05, .05, .05], False),
])
def test_pair_admission_requires_fixed_increment_and_stress_profit(one, stress, expected):
    rows = []
    for f, (primary, stressed) in enumerate(zip(one, stress), 1):
        rows += [{"fold": f, "comparison": "top50", "cost_multiplier": 1., "total_return": primary},
                 {"fold": f, "comparison": "momentum", "cost_multiplier": 1., "total_return": 0.},
                 {"fold": f, "comparison": "top50", "cost_multiplier": 2., "total_return": stressed}]
    admission = {"minimum_positive_paired_excess_folds": 2, "minimum_compounded_paired_excess_1x": 0.,
                 "minimum_compounded_net_return_2x": 0.}
    assert summarize_information_pair(rows, admission)["passed"] is expected
    with pytest.raises(ValueError, match="Incomplete"):
        summarize_information_pair(rows[:-1], admission)
