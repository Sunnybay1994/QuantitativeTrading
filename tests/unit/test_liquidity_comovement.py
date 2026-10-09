import datetime as dt
from calendar import monthrange

import numpy as np
import polars as pl
from polars.testing import assert_frame_equal
import pytest

from quant.factors.liquidity_comovement import (
    CONTROLS, SIGNALS, compute_liquidity_comovement,
)


@pytest.fixture(scope="module")
def sample():
    rng = np.random.default_rng(72039)
    months = [(2010 + m // 12, m % 12 + 1) for m in range(85)]
    sessions = tuple(dt.date(y, m, d) for y, m in months
                     for d in range(1, monthrange(y, m)[1] + 1)
                     if dt.date(y, m, d).weekday() < 5)
    ends = tuple(a for a, b in zip(sessions, sessions[1:]) if a.month != b.month)
    n, t = 125, len(ends)
    common = rng.normal(0, 0.10, t)
    shock = rng.normal(0, 0.02, (n, t)) + np.linspace(.5, 1.5, n)[:, None] * common
    levels = np.exp(-7 + np.cumsum(shock, axis=1))
    returns = rng.normal(0, .03, (n, t)) - .15 * common + rng.normal(.005, .04, t)
    symbols = [f"{i:06}.SZ" for i in range(n)]
    frame = pl.DataFrame({"symbol": np.repeat(symbols, t), "trade_date": ends * n,
                          "illiquidity": levels.ravel(), "monthly_return": returns.ravel()})
    return frame, sessions, ends


def run(sample, frame=None, dates=None):
    base, sessions, ends = sample
    return compute_liquidity_comovement(base if frame is None else frame, sessions=sessions,
                                       signal_dates=dates or ends[-3:])


def test_independent_regressions_and_self_exclusion(sample):
    frame, _, ends = sample
    result, market = run(sample, dates=(ends[-1],))
    assert result["status"].unique().to_list() == ["ok"]
    target = "000000.SZ"
    wide_l = frame.pivot(on="trade_date", index="symbol", values="illiquidity").sort("symbol")
    wide_r = frame.pivot(on="trade_date", index="symbol", values="monthly_return").sort("symbol")
    dl = np.diff(np.log(wide_l.select(pl.exclude("symbol")).to_numpy()), axis=1)[:, -60:]
    r = wide_r.select(pl.exclude("symbol")).to_numpy()[:, -60:]
    x_liq, x_r = dl[1:].mean(axis=0), r[1:].mean(axis=0)
    slopes = [np.linalg.lstsq(np.column_stack([np.ones(60), x]), y, rcond=None)[0][1]
              for x, y in [(x_liq, dl[0]), (x_liq, r[0]), (x_r, dl[0]), (x_r, r[0])]]
    row = result.filter(pl.col("symbol") == target).row(0, named=True)
    np.testing.assert_allclose([row[s] for s in (*SIGNALS, CONTROLS[-1])], slopes, rtol=1e-10, atol=1e-12)
    assert row["current_reference_members_ex_self"] == row["current_valid_members_ex_self"] == 124
    assert row["joint_months"] == 60
    assert market["reference_members"][-1] == 125


def test_future_changes_and_append_do_not_change_past(sample):
    frame, sessions, ends = sample
    cutoff = ends[-6]
    prefix = frame.filter(pl.col("trade_date") <= cutoff)
    a, _ = run(sample, prefix, (cutoff,))
    future = frame.with_columns(pl.when(pl.col("trade_date") > cutoff).then(pl.col("illiquidity") * 1e9)
                                .otherwise(pl.col("illiquidity")).alias("illiquidity"))
    b, _ = run(sample, future, (cutoff, ends[-1]))
    assert_frame_equal(a, b.filter(pl.col("trade_date") == cutoff))
    assert a["effective_date"][0] == sessions[sessions.index(cutoff) + 1]


def test_old_prefix_cannot_pollute_local_window(sample):
    frame, _, ends = sample
    # One extra month suffices for first dL; no cumulative state is carried.
    cropped = frame.filter(pl.col("trade_date") >= ends[-61])
    a, _ = run(sample, dates=(ends[-1],))
    b, _ = run(sample, cropped, (ends[-1],))
    assert_frame_equal(a, b, rel_tol=1e-11, abs_tol=1e-12)


def test_currency_units_cannot_change_slopes(sample):
    frame, _, _ = sample
    a, _ = run(sample)
    b, _ = run(sample, frame.with_columns((pl.col("illiquidity") * 1e6).alias("illiquidity")))
    assert_frame_equal(a.select(*SIGNALS, *CONTROLS[1:]), b.select(*SIGNALS, *CONTROLS[1:]),
                       rel_tol=1e-10, abs_tol=1e-10)
    np.testing.assert_allclose(b[CONTROLS[0]].to_numpy() - a[CONTROLS[0]].to_numpy(), np.log(1e6))


def test_missing_months_not_compressed_or_zero_filled(sample):
    frame, _, ends = sample
    # A missing level invalidates that month's and the next month's dL.
    missing = [ends[-4], ends[-8]]
    altered = frame.filter(~((pl.col("symbol") == "000000.SZ") & pl.col("trade_date").is_in(missing)))
    result, _ = run(sample, altered, (ends[-1],))
    target = result.filter(pl.col("symbol") == "000000.SZ")
    assert target["joint_months"].item() == 56
    assert target["status"].item() == "ok"
    assert target["window_start"].item() == ends[-60]


@pytest.mark.parametrize("bad", [None, 0.0, -1.0, float("nan"), float("inf")])
def test_invalid_current_level_never_publishes_a_signal(sample, bad):
    frame, _, ends = sample
    altered = frame.with_columns(pl.when((pl.col("symbol") == "000000.SZ") & (pl.col("trade_date") == ends[-1]))
        .then(pl.lit(bad, dtype=pl.Float64)).otherwise(pl.col("illiquidity")).alias("illiquidity"))
    result, _ = run(sample, altered, (ends[-1],))
    row = result.filter(pl.col("symbol") == "000000.SZ")
    assert row["status"].item() == "current_observation_unavailable"
    assert all(row[s].item() is None for s in (*SIGNALS, *CONTROLS))


def test_missing_reference_members_stay_in_denominator(sample):
    frame, _, ends = sample
    bad = (pl.col("symbol") < "000020.SZ") & (pl.col("trade_date") == ends[-1])
    altered = frame.with_columns(pl.when(bad).then(None).otherwise(pl.col("monthly_return")).alias("monthly_return"))
    result, market = run(sample, altered, (ends[-1],))
    last = market.row(-1, named=True)
    assert last["reference_members"] == 125 and last["valid_members"] == 105
    assert last["coverage"] == .84 and last["mean_return"] is None
    assert result[SIGNALS[0]].null_count() == result.height


def test_threshold_rechecked_after_self_removal(sample):
    frame, _, ends = sample
    altered = frame.filter(pl.col("symbol") < "000100.SZ")
    result, market = run(sample, altered, (ends[-1],))
    assert market["status"][-1] == "ok"  # 100 available before removal
    assert result["current_valid_members_ex_self"].unique().to_list() == [99]
    assert result[SIGNALS[0]].null_count() == result.height


def test_constant_predictor_is_not_zero_beta(sample):
    frame, _, ends = sample
    altered = frame.with_columns(pl.lit(.01).alias("monthly_return"))
    result, _ = run(sample, altered, (ends[-1],))
    assert result["status"].unique().to_list() == ["degenerate_or_nonfinite_window"]
    assert result[SIGNALS[0]].null_count() == result.height


def test_no_short_history_even_with_48_observations(sample):
    _, _, ends = sample
    result, _ = run(sample, dates=(ends[50],))
    assert result["status"].unique().to_list() == ["insufficient_history"]


def test_current_observation_and_joint_history_are_separate(sample):
    frame, _, ends = sample
    bad = (pl.col("symbol") == "000000.SZ") & pl.col("trade_date").is_in(ends[-30:-15])
    altered = frame.with_columns(pl.when(bad).then(None).otherwise(pl.col("monthly_return")).alias("monthly_return"))
    result, _ = run(sample, altered, (ends[-1],))
    row = result.filter(pl.col("symbol") == "000000.SZ")
    assert row["joint_months"].item() == 45
    assert row["status"].item() == "insufficient_joint_months"


def test_reject_duplicate_and_nonendpoint_rows(sample):
    frame, _, ends = sample
    with pytest.raises(ValueError, match="duplicate"):
        run(sample, pl.concat([frame, frame.head(1)]))
    with pytest.raises(ValueError, match="completed"):
        run(sample, frame.with_columns((pl.col("trade_date") - dt.timedelta(days=1)).alias("trade_date")))
