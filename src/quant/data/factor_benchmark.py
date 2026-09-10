"""Read the dated benchmark snapshot used by market-risk factor columns."""
import datetime as dt
import tomllib
from pathlib import Path

import polars as pl

from quant.domain import Bar1dSchema


def read_factor_benchmark(
    data_root: Path, config: Path, start: dt.date, end: dt.date,
) -> pl.DataFrame:
    settings = tomllib.loads(config.read_text(encoding="utf-8"))
    snapshot = settings.get("factor_benchmark_snapshot")
    if (not isinstance(snapshot, str) or not snapshot or Path(snapshot).name != snapshot
            or snapshot in (".", "..")):
        raise ValueError("Set factor_benchmark_snapshot before computing market-risk factors")
    bars = Bar1dSchema.validate(pl.read_parquet(
        data_root / "clean/factor_benchmark" / snapshot / "bars.parquet"))
    if set(bars["symbol"]) != {"510300.SH"}:
        raise ValueError("Factor benchmark must contain only 510300.SH")
    if bars.select("symbol", "trade_date").is_duplicated().any():
        raise ValueError("Duplicate benchmark observations")
    return bars.filter(pl.col("trade_date").is_between(start, end))
