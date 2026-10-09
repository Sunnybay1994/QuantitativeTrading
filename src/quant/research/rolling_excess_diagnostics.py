"""Advisory rolling / concentration diagnostics for strategy assessment (A2).

Does not participate in §1.2 admission gates.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

import polars as pl


def _month_ends(dates: list[dt.date]) -> list[dt.date]:
    by_month: dict[tuple[int, int], dt.date] = {}
    for day in dates:
        by_month[(day.year, day.month)] = day
    return [by_month[k] for k in sorted(by_month)]


def _unit_nav(frame: pl.DataFrame) -> pl.DataFrame:
    if "unit_nav" in frame.columns:
        return frame.select("date", "unit_nav").sort("date")
    if "equity" in frame.columns:
        base = float(frame.sort("date")["equity"][0])
        if base <= 0:
            raise ValueError("equity base must be positive")
        return frame.select("date", (pl.col("equity") / base).alias("unit_nav")).sort("date")
    raise ValueError("nav/benchmark require unit_nav or equity")


def _nav_at(nav: pl.DataFrame, day: dt.date) -> float | None:
    row = nav.filter(pl.col("date") <= day).sort("date").tail(1)
    return None if row.is_empty() else float(row["unit_nav"][0])


def _return_between(nav: pl.DataFrame, start: dt.date, end: dt.date) -> float | None:
    """Return from last session strictly before start through end (inclusive)."""
    prior = nav.filter(pl.col("date") < start).sort("date").tail(1)
    last = nav.filter(pl.col("date") <= end).sort("date").tail(1)
    if prior.is_empty() or last.is_empty():
        return None
    return float(last["unit_nav"][0] / prior["unit_nav"][0] - 1)


def monthly_excess_series(nav: pl.DataFrame, benchmark: pl.DataFrame) -> pl.DataFrame:
    s = _unit_nav(nav)
    b = _unit_nav(benchmark)
    ends = _month_ends(s["date"].to_list())
    rows: list[dict[str, Any]] = []
    for end in ends:
        start = dt.date(end.year, end.month, 1)
        sr = _return_between(s, start, end)
        br = _return_between(b, start, end)
        if sr is None or br is None:
            continue
        rows.append({
            "month_end": end,
            "month": f"{end.year:04d}-{end.month:02d}",
            "year": end.year,
            "strategy_return": sr,
            "benchmark_return": br,
            "excess": sr - br,
        })
    if not rows:
        return pl.DataFrame({
            "month_end": [], "month": [], "year": [],
            "strategy_return": [], "benchmark_return": [], "excess": [],
        })
    return pl.DataFrame(rows)


def _rolling_linked(
    strategy: pl.DataFrame,
    benchmark: pl.DataFrame,
    month_ends: list[dt.date],
    months: int,
) -> dict[str, Any]:
    if len(month_ends) < months + 1:
        # Need a boundary month-end before the first window.
        return {
            "window_months": months,
            "n_windows": 0,
            "series": [],
            "min": None,
            "min_month": None,
            "positive_fraction": None,
            "median": None,
            "last": None,
            "last_month": None,
        }
    series = []
    for i in range(months, len(month_ends)):
        start_boundary = month_ends[i - months]
        end = month_ends[i]
        s0, s1 = _nav_at(strategy, start_boundary), _nav_at(strategy, end)
        b0, b1 = _nav_at(benchmark, start_boundary), _nav_at(benchmark, end)
        if None in (s0, s1, b0, b1) or s0 <= 0 or b0 <= 0:
            continue
        excess = (s1 / s0 - 1) - (b1 / b0 - 1)
        series.append({"month_end": f"{end.year:04d}-{end.month:02d}", "excess": float(excess)})
    if not series:
        return {
            "window_months": months,
            "n_windows": 0,
            "series": [],
            "min": None,
            "min_month": None,
            "positive_fraction": None,
            "median": None,
            "last": None,
            "last_month": None,
        }
    values = [r["excess"] for r in series]
    amin = min(values)
    imin = values.index(amin)
    ordered = sorted(values)
    mid = len(ordered) // 2
    median = ordered[mid] if len(ordered) % 2 else 0.5 * (ordered[mid - 1] + ordered[mid])
    return {
        "window_months": months,
        "n_windows": len(series),
        "series": series,
        "min": amin,
        "min_month": series[imin]["month_end"],
        "positive_fraction": sum(1 for v in values if v > 0) / len(values),
        "median": float(median),
        "last": values[-1],
        "last_month": series[-1]["month_end"],
    }


def rolling_excess_diagnostics(nav: pl.DataFrame, benchmark: pl.DataFrame) -> dict[str, Any]:
    """Advisory rolling excess / concentration diagnostics."""
    strategy = _unit_nav(nav)
    bench = _unit_nav(benchmark)
    monthly = monthly_excess_series(nav, benchmark)
    month_ends = monthly["month_end"].to_list()

    by_year: dict[int, list[float]] = {}
    for row in monthly.iter_rows(named=True):
        by_year.setdefault(int(row["year"]), []).append(float(row["excess"]))

    monthly_hit_rate: dict[str, float] = {}
    best_month_share: dict[str, dict[str, Any]] = {}
    for year, xs in sorted(by_year.items()):
        total = sum(xs)
        best = max(xs)
        monthly_hit_rate[str(year)] = sum(1 for x in xs if x > 0) / len(xs)
        best_month_share[str(year)] = {
            "best_month_excess": best,
            "year_excess_sum": total,
            "best_month_share": (best / total) if abs(total) > 1e-12 else None,
            "excess_sum_without_best": total - best,
            "n_months": len(xs),
        }

    up = [float(r["excess"]) for r in monthly.iter_rows(named=True) if r["benchmark_return"] > 0]
    down = [float(r["excess"]) for r in monthly.iter_rows(named=True) if r["benchmark_return"] < 0]
    rolling12 = _rolling_linked(strategy, bench, month_ends, 12)
    rolling24 = _rolling_linked(strategy, bench, month_ends, 24)
    rolling36 = _rolling_linked(strategy, bench, month_ends, 36)
    return {
        "advisory": True,
        "n_months": monthly.height,
        "monthly": monthly.to_dicts(),
        "rolling12_excess": rolling12,
        "rolling24_excess": rolling24,
        "rolling36_excess": rolling36,
        "monthly_hit_rate": monthly_hit_rate,
        "best_month_share": best_month_share,
        "up_down_split": {
            "up_months": len(up),
            "down_months": len(down),
            "mean_excess_when_benchmark_up": (sum(up) / len(up)) if up else None,
            "mean_excess_when_benchmark_down": (sum(down) / len(down)) if down else None,
        },
        "registry": {
            "rolling12_excess_min": rolling12["min"],
            "rolling24_excess": rolling24["last"],
            "best_month_share": best_month_share.get("2026", {}).get("best_month_share"),
            "monthly_hit_rate": monthly_hit_rate.get("2026"),
        },
    }
