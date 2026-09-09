"""Twenty-session reversal and sixty-session total/idiosyncratic volatility."""

import datetime as dt
from typing import Any, cast

import numpy as np
import polars as pl


def rolling_residual_volatility(
    y: np.ndarray, x: np.ndarray, *, window: int, annualization: int,
) -> np.ndarray:
    """OLS with intercept and three regressors, using complete market-session windows."""
    if window <= 4 or len(y) != len(x) or x.shape[1] != 3:
        raise ValueError("Invalid IVOL regression dimensions")
    output = np.full(len(y), np.nan)
    for end in range(window, len(y) + 1):
        values, predictors = y[end - window:end], x[end - window:end]
        if not np.isfinite(values).all() or not np.isfinite(predictors).all():
            continue
        design = np.column_stack((np.ones(window), predictors))
        coefficients, _, rank, _ = np.linalg.lstsq(design, values, rcond=None)
        if rank != 4:
            continue
        residual = values - design @ coefficients
        output[end - 1] = np.sqrt(residual @ residual / (window - 4) * annualization)
    return output


def size_value_proxy_returns(
    grid: pl.DataFrame, *, minimum_bucket_symbols: int = 10,
) -> pl.DataFrame:
    """Monthly 2x3 size/BP sorts; return weights use only prior-session market cap."""
    month_ends = grid.group_by("_month").agg(pl.col("trade_date").max())
    members = grid.join(month_ends, on=["_month", "trade_date"]).filter(
        (pl.col("total_market_value") > 0) & (pl.col("pb") > 0)
        & pl.col("total_market_value").is_finite() & pl.col("pb").is_finite()
    ).with_columns((1 / pl.col("pb")).alias("_bp"))
    members = members.with_columns(
        pl.when(pl.col("total_market_value") <= pl.col("total_market_value").median().over("_month"))
        .then(pl.lit("S")).otherwise(pl.lit("B")).alias("_size"),
        pl.when(pl.col("_bp") <= pl.col("_bp").quantile(.3, interpolation="linear").over("_month"))
        .then(pl.lit("L")).when(pl.col("_bp") >= pl.col("_bp").quantile(.7, interpolation="linear").over("_month"))
        .then(pl.lit("H")).otherwise(pl.lit("M")).alias("_value"),
    ).select("symbol", pl.col("_month").dt.offset_by("1mo"),
             (pl.col("_size") + pl.col("_value")).alias("_bucket"))
    weighted = grid.filter(
        pl.col("_return").is_finite() & (pl.col("_lag_mv") > 0) & pl.col("_lag_mv").is_finite()
    ).with_columns((pl.col("_return") * pl.col("_lag_mv")).alias("_weighted_return"))
    market = weighted.group_by("trade_date").agg(
        (pl.col("_weighted_return").sum() / pl.col("_lag_mv").sum()).alias("market_return"))
    groups = weighted.join(members, on=["symbol", "_month"], how="inner").group_by(
        "trade_date", "_bucket").agg(
        (pl.col("_weighted_return").sum() / pl.col("_lag_mv").sum()).alias("_group_return"),
        pl.len().alias("_count"),
    ).with_columns(pl.when(pl.col("_count") >= minimum_bucket_symbols)
                   .then(pl.col("_group_return")).otherwise(None).alias("_group_return"))
    wide = groups.pivot(on="_bucket", index="trade_date", values="_group_return")
    for bucket in ("SL", "SM", "SH", "BL", "BM", "BH"):
        if bucket not in wide.columns:
            wide = wide.with_columns(pl.lit(None, dtype=pl.Float64).alias(bucket))
    # Ordinary arithmetic keeps a missing bucket missing instead of ignoring it.
    factors = wide.select("trade_date",
        ((pl.col("SL") + pl.col("SM") + pl.col("SH") - pl.col("BL") - pl.col("BM") - pl.col("BH")) / 3).alias("smb_return"),
        ((pl.col("SH") + pl.col("BH") - pl.col("SL") - pl.col("BL")) / 2).alias("hml_return"))
    return market.join(factors, on="trade_date", how="left").sort("trade_date")


def compute_reversal_volatility_factors(
    bars: pl.DataFrame, daily_basic: pl.DataFrame, *, sessions: tuple[dt.date, ...],
    settings: dict[str, Any],
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Return PIT factor values and the locally constructed market/size/value proxies."""
    if bars.select("symbol", "trade_date").is_duplicated().any():
        raise ValueError("Duplicate stock bars")
    first, last = cast(dt.date, bars["trade_date"].min()), cast(dt.date, bars["trade_date"].max())
    dates = [day for day in sessions if first <= day <= last]
    grid = bars.select("symbol").unique().join(pl.DataFrame({"trade_date": dates}), how="cross").join(
        bars.select("symbol", "trade_date", (pl.col("close") * pl.col("adj_factor")).alias("_price")),
        on=["symbol", "trade_date"], how="left", validate="1:1",
    ).join(daily_basic.select("symbol", "trade_date", "total_market_value", "pb"),
           on=["symbol", "trade_date"], how="left", validate="1:1").sort("symbol", "trade_date")
    grid = grid.with_columns(
        (pl.col("_price") / pl.col("_price").shift(1).over("symbol") - 1).alias("_return"),
        pl.col("total_market_value").shift(1).over("symbol").alias("_lag_mv"),
        pl.col("trade_date").dt.month_start().alias("_month"),
    )
    reversal, volatility = settings["reversal_window_sessions"], settings["volatility_window_sessions"]
    grid = grid.with_columns(
        pl.when(pl.col("_return").is_not_null().cast(pl.Int64).rolling_sum(reversal).over("symbol") == reversal)
        .then(1 - pl.col("_price") / pl.col("_price").shift(reversal).over("symbol"))
        .otherwise(None).alias("reversal_20"),
        (pl.col("_return").rolling_std(volatility, ddof=1).over("symbol")
         * settings["annualization_sessions"] ** .5).alias("realized_volatility_60"),
    )
    proxies = size_value_proxy_returns(grid, minimum_bucket_symbols=settings["proxy_minimum_bucket_symbols"])
    paired = grid.join(proxies, on="trade_date", how="left").sort("symbol", "trade_date")
    chunks = []
    for _, group in paired.group_by("symbol", maintain_order=True):
        ivol = rolling_residual_volatility(group["_return"].to_numpy(),
            group.select("market_return", "smb_return", "hml_return").to_numpy(),
            window=settings["ivol_window_sessions"], annualization=settings["annualization_sessions"])
        chunks.append(group.select("symbol", "trade_date", "reversal_20", "realized_volatility_60")
                      .with_columns(pl.Series("ivol_ff3_60", ivol).fill_nan(None)))
    return pl.concat(chunks).sort("symbol", "trade_date"), proxies


def exclude_historical_risk_names(panel: pl.DataFrame, names: pl.DataFrame) -> pl.DataFrame:
    """The exchange name is observable when effective; never use today's ST label in history."""
    dated = names.select("symbol", "start_date", "end_date", "name").unique()
    dated = dated.group_by("symbol", "start_date").agg(
        pl.when(pl.len() == 1).then(pl.col("name").first()).otherwise(None).alias("name"),
        pl.col("end_date").max(),
    )
    joined = panel.sort("symbol", "trade_date").join_asof(
        dated.sort("symbol", "start_date"), left_on="trade_date", right_on="start_date",
        by="symbol", strategy="backward", check_sortedness=False)
    return joined.filter(pl.col("name").is_not_null()
        & (pl.col("end_date").is_null() | (pl.col("trade_date") <= pl.col("end_date")))
        & ~pl.col("name").str.contains(r"(?i)^\*?S?ST|^PT|退")
    ).drop("start_date", "end_date", "name")
