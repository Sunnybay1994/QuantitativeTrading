"""Monthly signal groups and persistence diagnostics, independent of future labels."""
import datetime as dt
import math

import numpy as np
import polars as pl


def assign_groups(frame: pl.DataFrame, *, score: str, groups: int = 10,
                  minimum_symbols: int = 100) -> pl.DataFrame:
    """Use the existing battery's average-rank bins; ties stay together."""
    if groups < 2 or minimum_symbols < groups or frame.select("symbol", "trade_date").is_duplicated().any():
        raise ValueError("Invalid group inputs")
    cohort = frame.filter(pl.col(score).is_not_null() & pl.col(score).is_finite()).select(
        "symbol", "trade_date", pl.col(score).alias("score"))
    return (cohort.with_columns(pl.len().over("trade_date").alias("signal_count"),
        pl.col("score").n_unique().over("trade_date").alias("distinct_scores"),
        pl.col("score").rank("average").over("trade_date").alias("score_rank"))
        .filter((pl.col("signal_count") >= minimum_symbols) & (pl.col("distinct_scores") > 1))
        .with_columns((((pl.col("score_rank")-1)*groups/pl.col("signal_count")).floor()
            .cast(pl.Int64)+1).alias("group")).drop("distinct_scores").sort("trade_date", "symbol"))


def group_returns(cohort: pl.DataFrame, labels: pl.DataFrame, *, label: str,
                  signal_dates: tuple[dt.date, ...], groups: int = 10,
                  minimum_paired_coverage: float = .95) -> pl.DataFrame:
    """Retain empty bins and apply outcome coverage against ex-ante membership."""
    _check_dates(signal_dates)
    paired = cohort.join(labels.select("symbol", "trade_date", label),
        on=["symbol", "trade_date"], how="left", validate="1:1").with_columns(
            pl.when(pl.col(label).is_finite()).then(pl.col(label)).otherwise(None).alias("_return"))
    stats = paired.group_by("trade_date", "group").agg(pl.len().alias("members"),
        pl.col("_return").count().alias("paired"), pl.col("_return").mean().alias("mean_return"))
    grid = pl.DataFrame({"trade_date": signal_dates}, schema={"trade_date": pl.Date}).join(
        pl.DataFrame({"group": range(1, groups+1)}), how="cross")
    return (grid.join(stats, on=["trade_date", "group"], how="left", validate="1:1")
        .with_columns(pl.col("members", "paired").fill_null(0))
        .with_columns((pl.col("paired")/pl.col("members")).fill_nan(0).alias("paired_coverage"))
        .with_columns(pl.when((pl.col("members") > 0)
            & (pl.col("paired_coverage") >= minimum_paired_coverage))
            .then(pl.col("mean_return")).otherwise(None).alias("mean_return"))
        .sort("trade_date", "group"))


def persistence(cohort: pl.DataFrame, *, signal_dates: tuple[dt.date, ...],
                groups: int = 10, minimum_symbols: int = 100) -> pl.DataFrame:
    """Adjacent scheduled signals only; turnover is half L1 of target weights.

    This measures target membership changes, not drift-adjusted trading costs.
    Missing cohorts remain missing rather than bridging to a later month.
    """
    _check_dates(signal_dates)
    frames = {key[0]: value for key, value in cohort.partition_by("trade_date", as_dict=True).items()}
    rows = []
    for previous, current in zip(signal_dates, signal_dates[1:]):
        old, new = frames.get(previous), frames.get(current)
        row = {"trade_date": current, "previous_signal": previous, "common_symbols": 0,
               "rank_autocorrelation": None, "top_target_turnover": None}
        if old is not None and new is not None:
            joined = old.select("symbol", pl.col("score").alias("previous_score")).join(
                new.select("symbol", "score"), on="symbol", validate="1:1")
            row["common_symbols"] = joined.height
            if joined.height >= minimum_symbols:
                correlation = joined.select(pl.corr(pl.col("previous_score").rank("average"),
                    pl.col("score").rank("average"))).item()
                if correlation is not None and math.isfinite(correlation):
                    row["rank_autocorrelation"] = correlation
            old_top = set(old.filter(pl.col("group") == groups)["symbol"])
            new_top = set(new.filter(pl.col("group") == groups)["symbol"])
            if old_top and new_top:
                row["top_target_turnover"] = .5*sum(abs(
                    (1/len(new_top) if symbol in new_top else 0)
                    - (1/len(old_top) if symbol in old_top else 0)) for symbol in old_top | new_top)
        rows.append(row)
    return pl.DataFrame(rows, schema={"trade_date": pl.Date, "previous_signal": pl.Date,
        "common_symbols": pl.Int64, "rank_autocorrelation": pl.Float64,
        "top_target_turnover": pl.Float64})


def summarize_groups(returns: pl.DataFrame, *, groups: int = 10) -> dict:
    """Annualize observed monthly returns; expose coverage beside every statistic."""
    summaries = []
    for group in range(1, groups+1):
        values = returns.filter(pl.col("group") == group)["mean_return"].drop_nulls().to_numpy()
        annual = None
        if len(values) and np.isfinite(values).all() and (values >= -1).all():
            annual = float(np.prod(1+values)**(12/len(values))-1)
        summaries.append({"group": group, "months": len(values), "annualized_return": annual})
    low = returns.filter(pl.col("group") == 1).select("trade_date", pl.col("mean_return").alias("low"))
    spread = returns.filter(pl.col("group") == groups).join(low, on="trade_date", validate="1:1").select(
        (pl.col("mean_return")-pl.col("low")).alias("spread"))["spread"].drop_nulls().to_numpy()
    deviation = float(np.std(spread, ddof=1)) if len(spread) > 1 else 0.
    sharpe = float(np.mean(spread)/deviation*np.sqrt(12)) if deviation > 1e-12 else None
    common = returns.group_by("trade_date").agg(
        pl.col("mean_return").count().alias("valid_groups")).filter(pl.col("valid_groups") == groups)
    means = returns.join(common, on="trade_date", how="semi").group_by("group").agg(
        pl.col("mean_return").mean()).drop_nulls()
    monotonicity = None
    if means.height == groups:
        rho = means.select(pl.corr(pl.col("group").rank("average"),
            pl.col("mean_return").rank("average"))).item()
        if rho is not None and math.isfinite(rho):
            monotonicity = rho
    return {"groups": summaries, "long_short_months": len(spread),
            "long_short_sharpe": sharpe, "group_mean_rank_monotonicity": monotonicity,
            "monotonicity_common_months": common.height}


def _check_dates(dates: tuple[dt.date, ...]) -> None:
    if not dates or tuple(sorted(set(dates))) != dates:
        raise ValueError("Group diagnostics require an ordered signal calendar")
