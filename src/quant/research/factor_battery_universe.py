"""Point-in-time tradability masks for daily factor evaluation."""
import datetime as dt

import polars as pl


def prepare_battery_universe(
    bars: pl.DataFrame, instruments: pl.DataFrame, names: pl.DataFrame, limits: pl.DataFrame, *,
    sessions: tuple[dt.date, ...], minimum_listing_days: int = 120,
    amount_window_sessions: int = 20, amount_exclude_bottom_fraction: float = .2,
) -> pl.DataFrame:
    """Keep all observed bars and expose each exclusion reason beside eligibility."""
    keys = ["symbol", "trade_date"]
    if bars.is_empty() or bars.select(keys).is_duplicated().any():
        raise ValueError("Universe bars must be nonempty with unique keys")
    low, high = bars["trade_date"].min(), bars["trade_date"].max()
    if not isinstance(low, dt.date) or not isinstance(high, dt.date):
        raise ValueError("Universe bars require date keys")
    calendar = [day for day in sessions if low <= day <= high]
    if not calendar or calendar != sorted(set(calendar)) or not set(bars["trade_date"]) <= set(calendar):
        raise ValueError("Universe requires a complete ordered exchange calendar")
    grid = bars.select("symbol").unique().join(pl.DataFrame({"trade_date": calendar}), how="cross").join(
        bars.select(*keys, "amount"), on=keys, how="left", validate="1:1").sort(*keys)
    average = grid.with_columns(pl.when(pl.col("amount") > 0).then(pl.col("amount")).otherwise(None)
        .rolling_mean(amount_window_sessions, min_samples=amount_window_sessions).over("symbol")
        .alias("amount20")).select(*keys, "amount20")
    history = names.with_columns(pl.max_horizontal("start_date", "ann_date").alias("available_date"))
    history = history.select("symbol", "available_date", "name").unique()
    history = history.group_by("symbol", "available_date").agg(
        pl.when(pl.col("name").n_unique() == 1).then(pl.col("name").first()).otherwise(None).alias("known_name"),
    )
    result = bars.join(average, on=keys, how="left", validate="1:1").join(
        instruments.select("symbol", "list_date", "delist_date", "instrument_type"),
        on="symbol", how="left", validate="m:1").sort(*keys).join_asof(
            history.sort("symbol", "available_date"), left_on="trade_date", right_on="available_date",
            by="symbol", strategy="backward", check_sortedness=False).join(
                limits.select(*keys, "up_limit", "down_limit"), on=keys, how="left", validate="1:1")
    result = result.with_columns(
        pl.col("known_name").is_not_null().alias("name_known"),
        (~pl.col("known_name").str.contains(r"(?i)^\*?S?ST|^PT|退")).fill_null(False).alias("not_risk_name"),
        ((pl.col("trade_date")-pl.col("list_date")).dt.total_days() >= minimum_listing_days)
            .fill_null(False).alias("listing_age_ok"),
        ((pl.col("instrument_type") == "STOCK") & (pl.col("delist_date").is_null()
            | (pl.col("trade_date") < pl.col("delist_date")))).fill_null(False).alias("active_stock"),
        ((pl.col("volume") > 0) & (pl.col("amount") > 0)).fill_null(False).alias("traded"),
        (pl.col("up_limit").is_finite() & pl.col("down_limit").is_finite()
            & (pl.col("up_limit") > pl.col("down_limit")) & (pl.col("down_limit") > 0))
            .fill_null(False).alias("limits_known"),
        ((pl.col("close") < pl.col("up_limit")-1e-8) & (pl.col("close") > pl.col("down_limit")+1e-8))
            .fill_null(False).alias("away_from_limits"),
    ).with_columns(pl.all_horizontal("name_known", "not_risk_name", "listing_age_ok", "active_stock",
        "traded", "limits_known", "away_from_limits").alias("base_eligible"))
    threshold = result.filter(pl.col("base_eligible") & pl.col("amount20").is_not_null()).group_by(
        "trade_date").agg(pl.col("amount20").quantile(amount_exclude_bottom_fraction,
            interpolation="linear").alias("amount_threshold"))
    return result.join(threshold, on="trade_date", how="left", validate="m:1").with_columns(
        (pl.col("amount20") >= pl.col("amount_threshold")).fill_null(False).alias("liquidity_ok"),
    ).with_columns((pl.col("base_eligible") & pl.col("liquidity_ok")).alias("eligible")).sort(*keys)
