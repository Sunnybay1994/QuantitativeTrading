"""B35 fixed low-volatility intersection before reversal ranking."""

import polars as pl


def select_low_volatility_pool(
    frame: pl.DataFrame, *, keep_fraction: float, minimum_candidates: int,
) -> pl.DataFrame:
    """Keep the least volatile fraction separately at each known signal date."""
    if not 0 < keep_fraction <= 1 or minimum_candidates < 1:
        raise ValueError("Invalid low-volatility pool size")
    if frame.is_empty():
        raise ValueError("Empty low-volatility input")
    if frame.filter((pl.col("realized_volatility_60") < 0) | ~pl.col("realized_volatility_60").is_finite()
                    | pl.col("realized_volatility_60").is_null()).height:
        raise ValueError("Low-volatility pool needs complete input")
    selected = frame.sort("trade_date", "realized_volatility_60", "symbol").with_columns(
        pl.col("symbol").cum_count().over("trade_date").alias("low_vol_rank"),
        pl.len().over("trade_date").alias("low_vol_universe_size"),
    ).filter(pl.col("low_vol_rank") <= (pl.col("low_vol_universe_size") * keep_fraction).ceil())
    if any(n < minimum_candidates for n in selected.group_by("trade_date").len()["len"]):
        raise ValueError("Low-volatility pool smaller than required target count")
    return selected
