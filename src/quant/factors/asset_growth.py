"""Same-quarter year-on-year asset growth from PIT-selected balance sheets."""

import polars as pl

from quant.factors.pit_quality import _quarter_coordinates


def compute_asset_growth(balance: pl.DataFrame) -> pl.DataFrame:
    """Lower is preferred; missing or non-positive assets are not ranked."""
    groups = ["symbol", "report_type", "comp_type"]
    if balance.select(pl.struct(*groups, "end_date").is_duplicated().any()).item():
        raise ValueError("Duplicate PIT balance sheet periods")
    frame = _quarter_coordinates(balance)
    previous = frame.select(
        *groups, (pl.col("_quarter_index") + 4).alias("_quarter_index"),
        pl.col("total_assets").alias("prior_total_assets"),
    )
    return frame.join(previous, on=[*groups, "_quarter_index"], how="left", validate="1:1").with_columns(
        pl.when((pl.col("total_assets") > 0) & (pl.col("prior_total_assets") > 0))
        .then(pl.col("total_assets") / pl.col("prior_total_assets") - 1)
        .otherwise(None).alias("pit_asset_growth_yoy")
    ).select(*groups, "end_date", "total_assets", "prior_total_assets", "pit_asset_growth_yoy")
