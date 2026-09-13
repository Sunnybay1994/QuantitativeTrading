"""Same-quarter inventory change scaled by average assets, after PIT selection."""

import polars as pl

from quant.factors.pit_quality import _quarter_coordinates


def compute_inventory_expansion(balance: pl.DataFrame) -> pl.DataFrame:
    """Missing inventories stay missing; zero inventories are economically valid."""
    groups = ["symbol", "report_type", "comp_type"]
    if balance.select(pl.struct(*groups, "end_date").is_duplicated().any()).item():
        raise ValueError("Duplicate PIT balance sheet periods")
    frame = _quarter_coordinates(balance)
    previous = frame.select(
        *groups, (pl.col("_quarter_index") + 4).alias("_quarter_index"),
        pl.col("total_assets").alias("prior_total_assets"),
        pl.col("inventories").alias("prior_inventories"),
    )
    valid = pl.all_horizontal(
        *(pl.col(c).is_finite() & (pl.col(c) > 0)
          for c in ("total_assets", "prior_total_assets")),
        *(pl.col(c).is_finite() & (pl.col(c) >= 0)
          for c in ("inventories", "prior_inventories")),
    )
    return frame.join(previous, on=[*groups, "_quarter_index"], how="left", validate="1:1").with_columns(
        pl.when(valid).then(
            (pl.col("inventories") - pl.col("prior_inventories"))
            / ((pl.col("total_assets") + pl.col("prior_total_assets")) / 2)
        ).otherwise(None).alias("pit_inventory_expansion_yoy")
    ).select(*groups, "end_date", "pit_inventory_expansion_yoy")
