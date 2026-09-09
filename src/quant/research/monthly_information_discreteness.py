"""Monthly ID signals and the shared PRET winner pool for a paired experiment."""

import datetime as dt
import math
from typing import Any

import polars as pl

from quant.factors.information_discreteness import compute_information_discreteness
from quant.research.pit_quality_research import monthly_signal_sessions


def build_monthly_information_discreteness(
    *, bars: pl.DataFrame, sessions: tuple[dt.date, ...], start: dt.date, end: dt.date,
    settings: dict[str, Any],
) -> pl.DataFrame:
    """Use the pre-registered exchange-session approximation, with no parameter fit."""
    expected = {
        "formation_sessions": 252, "skip_sessions": 21,
        "formula": "sign(PRET) * (negative_days - positive_days) / 252",
        "pret_formula": "adjusted_close[t-21] / adjusted_close[t-273] - 1",
        "return_indices": "t-272 through t-21 inclusive",
        "minimum_valid_returns": 252, "missing_session": "null_entire_formation_window",
        "zero_return": "included_in_denominator", "zero_pret": "ID_zero",
        "zero_volume": "invalid_price_observation", "winner_fraction": 0.2,
        "winner_count_rounding": "floor", "winner_tie_break": "symbol_ascending",
        "winner_absolute_pret_filter": "none_relative_top_quintile",
    }
    if any(settings.get(k) != v for k, v in expected.items()):
        raise ValueError("Unsupported pre-registered information discreteness configuration")
    signals = monthly_signal_sessions(sessions, start=start, end=end)
    return compute_information_discreteness(bars, sessions=sessions).filter(pl.col("trade_date").is_in(signals))


def select_information_winners(eligible: pl.DataFrame) -> pl.DataFrame:
    """Take the same top PRET quintile after shared price/liquidity/name filters.

    Both ID and PRET portfolios consume this identical pool. Stock symbols settle
    PRET ties before taking floor(20% * eligible count); no absolute PRET filter.
    """
    return eligible.filter(
        pl.col("pret_12m_skip1m").is_finite() & pl.col("information_discreteness").is_finite(),
    ).sort(["trade_date", "pret_12m_skip1m", "symbol"], descending=[False, True, False]).with_columns(
        pl.len().over("trade_date").alias("formation_eligible_count"),
        pl.col("symbol").cum_count().over("trade_date").alias("winner_pret_rank"),
    ).with_columns(
        (pl.col("formation_eligible_count") * 0.2).floor().cast(pl.UInt32).alias("winner_pool_count"),
    ).filter(pl.col("winner_pret_rank") <= pl.col("winner_pool_count"))


def summarize_information_pair(results: list[dict[str, Any]], admission: dict[str, Any]) -> dict[str, Any]:
    """Apply the frozen incremental-return requirements after identical replay."""
    primary = {r["fold"]: r["total_return"] for r in results
               if r["comparison"] == "top50" and r["cost_multiplier"] == 1.0}
    baseline = {r["fold"]: r["total_return"] for r in results
                if r["comparison"] == "momentum" and r["cost_multiplier"] == 1.0}
    stress = {r["fold"]: r["total_return"] for r in results
              if r["comparison"] == "top50" and r["cost_multiplier"] == 2.0}
    if not primary or primary.keys() != baseline.keys() or primary.keys() != stress.keys():
        raise ValueError("Incomplete paired information-discreteness results")
    differences = [{"fold": f, "excess_return_1x": primary[f] - baseline[f]} for f in sorted(primary)]
    positive = sum(r["excess_return_1x"] > 0 for r in differences)
    compounded_excess = math.prod(1 + x for x in primary.values()) - math.prod(1 + x for x in baseline.values())
    stress_return = math.prod(1 + x for x in stress.values()) - 1
    return {
        "fold_excess": differences, "positive_excess_folds_1x": positive,
        "compounded_excess_1x": compounded_excess, "compounded_net_return_2x": stress_return,
        "passed": (positive >= admission["minimum_positive_paired_excess_folds"]
                   and compounded_excess > admission["minimum_compounded_paired_excess_1x"]
                   and stress_return > admission["minimum_compounded_net_return_2x"]),
    }
