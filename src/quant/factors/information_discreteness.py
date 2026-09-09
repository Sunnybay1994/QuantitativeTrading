"""Frog-in-the-pan information discreteness, before conditioning on past winners."""

import datetime as dt

import polars as pl


def compute_information_discreteness(
    bars: pl.DataFrame, *, sessions: tuple[dt.date, ...],
    formation_sessions: int = 252, skip_sessions: int = 21,
) -> pl.DataFrame:
    """At t use returns t-skip-formation+1..t-skip, both endpoints inclusive.

    Prices are close * adj_factor. A formation window requires every exchange
    session, including its starting price. Reported zero returns count in the
    denominator; missing or zero-volume observations are never filled with zero.
    """
    if (type(formation_sessions) is not int or formation_sessions < 2
            or type(skip_sessions) is not int or skip_sessions < 0):
        raise ValueError("Formation and skip windows must be valid session counts")
    if not sessions or tuple(sorted(set(sessions))) != sessions:
        raise ValueError("Sessions must be nonempty, unique and increasing")
    keys = ["symbol", "trade_date"]
    if bars.select(keys).is_duplicated().any():
        raise ValueError("Duplicate information-discreteness symbol-date")
    if bars.select(pl.any_horizontal(pl.col(k).is_null() for k in keys).any()).item():
        raise ValueError("Missing information-discreteness symbol-date")
    grid = bars.select("symbol").unique().join(
        pl.DataFrame({"trade_date": sessions}), how="cross",
    ).join(bars.select(*keys, "close", "adj_factor", "volume"), on=keys, how="left", validate="1:1")
    grid = grid.sort(*keys).with_columns(
        pl.when(pl.all_horizontal(pl.col(k).is_finite() & (pl.col(k) > 0)
                                  for k in ("close", "adj_factor", "volume")))
        .then(pl.col("close") * pl.col("adj_factor")).otherwise(None).alias("_price"),
    ).with_columns(
        (pl.col("_price") / pl.col("_price").shift(1).over("symbol") - 1).alias("_return"),
    ).with_columns(
        pl.when(pl.col("_return").is_finite()).then(pl.col("_return")).otherwise(None).alias("_return"),
    ).with_columns(
        pl.col("_return").is_not_null().cast(pl.UInt16)
        .rolling_sum(formation_sessions, min_samples=formation_sessions).over("symbol").alias("_valid"),
        *[pl.when(pl.col("_return").is_not_null()).then(predicate.cast(pl.UInt16)).otherwise(None)
          .rolling_sum(formation_sessions, min_samples=formation_sessions).over("symbol").alias(name)
          for name, predicate in (("_positive", pl.col("_return") > 0),
                                  ("_negative", pl.col("_return") < 0),
                                  ("_zero", pl.col("_return") == 0))],
        (pl.col("_price") / pl.col("_price").shift(formation_sessions).over("symbol") - 1)
        .alias("_pret"),
    ).with_columns(
        *[pl.col(source).shift(skip_sessions).over("symbol").alias(target)
          for source, target in (("_valid", "formation_valid_returns"), ("_positive", "formation_positive_days"),
                                 ("_negative", "formation_negative_days"), ("_zero", "formation_zero_days"),
                                 ("_pret", "pret_12m_skip1m"))],
        pl.col("trade_date").shift(skip_sessions + formation_sessions).over("symbol").alias("formation_price_start"),
        pl.col("trade_date").shift(skip_sessions).over("symbol").alias("formation_end"),
    ).with_columns(
        pl.when((pl.col("formation_valid_returns") == formation_sessions)
                & pl.col("pret_12m_skip1m").is_finite()).then(pl.col("pret_12m_skip1m"))
        .otherwise(None).alias("pret_12m_skip1m"),
    ).with_columns(
        (pl.col("pret_12m_skip1m").sign()
         * (pl.col("formation_negative_days").cast(pl.Float64) - pl.col("formation_positive_days"))
         / formation_sessions).alias("information_discreteness"),
    )
    return grid.select(*keys, "pret_12m_skip1m", "information_discreteness", "formation_valid_returns",
                       "formation_positive_days", "formation_negative_days", "formation_zero_days",
                       "formation_price_start", "formation_end")
