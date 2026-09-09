"""Exchange-week signal dates for the ETF reversal experiment."""

import datetime as dt

import polars as pl

from quant.strategies.weekly_etf_reversal import WeeklyEtfReversalStrategy


def weekly_targets(
    prices: pl.DataFrame, calendar: pl.DataFrame, *, start: dt.date, end: dt.date,
    candidates: tuple[str, ...], name: str, strategy: WeeklyEtfReversalStrategy | None,
) -> pl.DataFrame:
    sessions = sorted(calendar.filter((pl.col("market") == "SH") & pl.col("is_open"))["date"].unique().to_list())
    week_ends = {a for a, b in zip(sessions, sessions[1:]) if a.isocalendar()[:2] != b.isocalendar()[:2]}
    frames = []
    for prior, execution in zip(sessions, sessions[1:]):
        if not start <= execution <= end or not (prior < start or prior in week_ends):
            continue
        completed = [d for d in week_ends if d <= prior]
        if not completed:
            raise ValueError("No completed week before execution")
        as_of = max(completed)
        if strategy is not None:
            dates = [d for d in sessions if d <= as_of][-strategy.lookback_sessions - 1:]
            available = prices.filter(pl.col("trade_date").is_in(dates))
            if sorted(available["trade_date"].unique().to_list()) != dates:
                raise ValueError("Missing exchange session in weekly prices")
            target = strategy.target_weights(as_of, available)
        else:
            target = pl.DataFrame({"as_of": [as_of] * len(candidates), "symbol": candidates,
                "strategy": [name] * len(candidates), "strategy_version": ["v1"] * len(candidates),
                "weight": [1 / len(candidates)] * len(candidates)})
        frames.append(target.with_columns(pl.lit(execution).alias("execution_date")))
    if not frames:
        raise ValueError("No weekly execution dates")
    return pl.concat(frames).sort("execution_date", "symbol")
