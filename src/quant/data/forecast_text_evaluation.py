"""Read contemporaneous numerical controls for P7 text diagnostics."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import polars as pl


def read_forecast_controls(source: Path) -> pl.DataFrame:
    frame = pl.read_parquet(source)
    if "symbol" not in frame.columns:
        frame = frame.rename({"ts_code": "symbol"})
    keys = ["symbol", "publication_date", "report_period"]
    required = {*keys, "same_day_conflict", "p_change_min", "p_change_max"}
    if not required.issubset(frame.columns):
        raise ValueError("Forecast corpus requires original dated numerical ranges and conflict flags")
    frame = frame.unique().with_columns(
        pl.col("p_change_min", "p_change_max").cast(pl.Float64, strict=True))
    conflict = pl.col("same_day_conflict").fill_null(True) | (pl.len().over(keys) > 1)
    valid = pl.col("p_change_min").is_finite() & pl.col("p_change_max").is_finite() & ~conflict
    return frame.with_columns(
        pl.when(valid).then(pl.col("p_change_min") / 2 + pl.col("p_change_max") / 2)
        .otherwise(None).alias("forecast_p_change_midpoint")
    ).sort(keys).unique(subset=["symbol", "publication_date"], keep="last", maintain_order=True).select(
        "symbol", "publication_date", "report_period", "forecast_p_change_midpoint")


def attach_forecast_controls(keys: pl.DataFrame, events: pl.DataFrame, *, max_age_days: int) -> pl.DataFrame:
    if keys.select("symbol", "trade_date").is_duplicated().any() or max_age_days < 1:
        raise ValueError("Invalid forecast control grid")
    result = keys.sort("trade_date").join_asof(events.sort("publication_date"),
        left_on="trade_date", right_on="publication_date", by="symbol",
        strategy="backward", check_sortedness=False)
    return result.with_columns(
        pl.when((pl.col("trade_date") - pl.col("publication_date")).dt.total_days() < max_age_days)
        .then(pl.col("forecast_p_change_midpoint")).otherwise(None).alias("forecast_p_change_midpoint")
    ).rename({"publication_date": "forecast_publication_date"})


def read_text_evaluation_year(*, data_root: Path, year: int, known_through: dt.date,
                              universe: pl.DataFrame, numeric_events: pl.DataFrame,
                              factors: list[str], max_age_days: int) -> tuple[pl.DataFrame, pl.DataFrame]:
    from quant.data.factor_battery_inputs import read_battery_factor_year

    keys = ["symbol", "trade_date"]
    panel = attach_forecast_controls(universe, numeric_events, max_age_days=max_age_days)
    sue_path = data_root / f"factors/pit_sue8/year={year}/data.parquet"
    if sue_path.is_file():
        sue = pl.read_parquet(sue_path).rename({"ts_code": "symbol", "value": "pit_sue8"})
        panel = panel.join(sue.select(*keys, "pit_sue8"), on=keys, how="left", validate="1:1")
    else:
        panel = panel.with_columns(pl.lit(None, dtype=pl.Float64).alias("pit_sue8"))
    labels = None
    for factor in factors:
        values, current_labels = read_battery_factor_year(data_root, factor=factor, year=year,
                                                          known_through=known_through)
        panel = panel.join(values.select(*keys, pl.col("value").alias(factor)),
                           on=keys, how="left", validate="1:1")
        if labels is None:
            labels = current_labels
    if labels is None:
        raise ValueError("No text factors selected")
    return panel, labels
