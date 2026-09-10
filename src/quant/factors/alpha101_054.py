"""Alpha101 #54, evaluated without powers of absolute prices."""

import datetime as dt

import polars as pl


def compute_alpha101_054(bars: pl.DataFrame, *, sessions: tuple[dt.date, ...]) -> pl.DataFrame:
    """Same-session OHLC ratios; absent or untradable bars produce null scores."""
    keys = ["symbol", "trade_date"]
    if not sessions or tuple(sorted(set(sessions))) != sessions:
        raise ValueError("Sessions must be nonempty, unique and increasing")
    if bars.select(keys).is_duplicated().any():
        raise ValueError("Duplicate stock bars")
    if bars.select(pl.any_horizontal(pl.col(k).is_null() for k in keys).any()).item():
        raise ValueError("Missing stock bar keys")
    grid = bars.select("symbol").unique().join(pl.DataFrame({"trade_date": sessions}), how="cross").join(
        bars.select(*keys, "open", "high", "low", "close", "volume"),
        on=keys, how="left", validate="1:1").sort(*keys)
    valid = pl.all_horizontal(pl.col(k).is_finite() & (pl.col(k) > 0)
                              for k in ("open", "high", "low", "close", "volume"))
    valid &= (pl.col("high") > pl.col("low")) & pl.all_horizontal(
        pl.col(k).is_between(pl.col("low"), pl.col("high")) for k in ("open", "close"))
    score = -(pl.col("close") - pl.col("low")) / (pl.col("high") - pl.col("low")) * (
        pl.col("open") / pl.col("close")).pow(5)
    return grid.with_columns(pl.when(valid & score.is_finite()).then(score).otherwise(None)
                             .alias("alpha101_054")).select(*keys, "alpha101_054")
