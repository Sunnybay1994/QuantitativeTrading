"""Unit tests for advisory rolling excess diagnostics (A2)."""
import datetime as dt

import polars as pl

from quant.research.rolling_excess_diagnostics import rolling_excess_diagnostics


def _nav(start: dt.date, monthly_returns: list[float]) -> pl.DataFrame:
    """Build daily unit_nav with constant within-month levels and month-end jumps."""
    rows = [{"date": start - dt.timedelta(days=3), "unit_nav": 1.0}]
    level = 1.0
    year, month = start.year, start.month
    for ret in monthly_returns:
        # One mid-month and one month-end point
        if month == 12:
            end = dt.date(year, 12, 31)
            mid = dt.date(year, 12, 15)
            next_year, next_month = year + 1, 1
        else:
            end = dt.date(year, month + 1, 1) - dt.timedelta(days=1)
            mid = dt.date(year, month, 15)
            next_year, next_month = year, month + 1
        rows.append({"date": mid, "unit_nav": level})
        level *= 1 + ret
        rows.append({"date": end, "unit_nav": level})
        year, month = next_year, next_month
    return pl.DataFrame(rows).unique("date").sort("date")


def test_rolling12_linked_excess_and_concentration():
    # 24 months: strategy flat then +10% in month 24; benchmark +1% each month.
    strat = [0.0] * 23 + [0.10]
    bench = [0.01] * 24
    nav = _nav(dt.date(2024, 1, 1), strat)
    baseline = _nav(dt.date(2024, 1, 1), bench)
    diag = rolling_excess_diagnostics(nav, baseline)
    assert diag["advisory"] is True
    assert diag["n_months"] == 24
    r12 = diag["rolling12_excess"]
    assert r12["n_windows"] == 12
    # Last 12m: strat (1.10-1)=0.10 over full path from m12 end; from boundary m12:
    # After 12 flat months level=1, then months 13-23 flat, month 24 +10% → 1.10
    # Boundary at month 12 end = 1.0; end month 24 = 1.10 → strat +10%
    # Bench: 12 months of +1% → 1.01**12 - 1
    last = r12["last"]
    expected_bench = 1.01 ** 12 - 1
    assert abs(last - (0.10 - expected_bench)) < 1e-9
    assert diag["monthly_hit_rate"]["2025"] is not None or "2024" in diag["monthly_hit_rate"]
    # Best month share for the year containing the +10% month
    year_key = "2025" if "2025" in diag["best_month_share"] else "2024"
    share = diag["best_month_share"][year_key]
    assert share["best_month_excess"] > 0
    assert share["excess_sum_without_best"] < share["year_excess_sum"]
    assert diag["up_down_split"]["up_months"] + diag["up_down_split"]["down_months"] == 24


def test_empty_when_insufficient_history():
    nav = _nav(dt.date(2026, 1, 1), [0.01, 0.02])
    bench = _nav(dt.date(2026, 1, 1), [0.0, 0.0])
    diag = rolling_excess_diagnostics(nav, bench)
    assert diag["rolling12_excess"]["n_windows"] == 0
    assert diag["rolling12_excess"]["min"] is None
