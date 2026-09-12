"""Read-only checks that SUE values have a compatible latest PIT report context."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import polars as pl

from quant.data.financial_repository import (
    TushareFinancialHistoryQuery,
    read_tushare_financial_history,
)

_KEYS = ["symbol", "trade_date"]
_KNOWN_COMP_TYPES = ["1", "2", "3", "4", "7"]
_HISTORY_SCHEMA = {
    "symbol": pl.String, "available_date": pl.Date, "end_date": pl.Date,
    "report_type": pl.String, "comp_type": pl.String, "update_flag": pl.String,
}


def _pool_keys(pool: pl.DataFrame, as_of: dt.date) -> pl.DataFrame:
    if type(as_of) is not dt.date or not set(_KEYS) <= set(pool.columns):
        raise ValueError("SUE quality pool requires symbol/trade_date and a date cutoff")
    keys = pool.select(_KEYS)
    if (keys.schema["symbol"] != pl.String or keys.schema["trade_date"] != pl.Date
            or keys.select(pl.any_horizontal(pl.all().is_null()).any()).item()
            or keys.filter((pl.col("trade_date") != as_of) | (pl.col("symbol") == "")).height
            or keys.select(pl.struct(_KEYS).is_duplicated().any()).item()):
        raise ValueError("SUE quality pool must contain unique non-null keys for as_of only")
    return keys


def _factor_values(frame: pl.DataFrame) -> pl.DataFrame:
    names = set(frame.columns)
    symbol = "symbol" if "symbol" in names else "ts_code"
    date = "trade_date" if "trade_date" in names else "date"
    if not {symbol, date, "value"} <= names:
        raise ValueError("SUE factor values require symbol or ts_code, date and value")
    values = frame.select(pl.col(symbol).alias("symbol"), pl.col(date).alias("trade_date"),
                          pl.col("value").alias("factor_value"))
    value_type = values.schema["factor_value"]
    if (values.schema["symbol"] != pl.String or values.schema["trade_date"] != pl.Date
            or (value_type != pl.Null and not value_type.is_numeric())
            or values.select(pl.any_horizontal(pl.col(_KEYS).is_null()).any()).item()
            or values.select(pl.struct(_KEYS).is_duplicated().any()).item()):
        raise ValueError("SUE factor values require unique non-null dated keys and numeric values")
    return values.with_columns(pl.col("factor_value").cast(pl.Float64))


def diagnose_sue_report_context(
    *, pool: pl.DataFrame, income_history: pl.DataFrame, factor_values: pl.DataFrame,
    as_of: dt.date,
) -> pl.DataFrame:
    """Compare finite values with the latest report, without computing or changing SUE.

    Context selects report type 1 known strictly before as_of, then the latest
    period, latest available_date, and highest update flag (1 before other flags).
    Company type is inspected after selection, retaining tied conflicting types.
    A finite factor with unknown/ambiguous/no report context is unsupported too.
    """
    keys = _pool_keys(pool, as_of)
    values = _factor_values(factor_values)
    if not set(_HISTORY_SCHEMA) <= set(income_history.columns):
        raise ValueError("SUE report history is missing context columns")
    for name, dtype in _HISTORY_SCHEMA.items():
        actual = income_history.schema[name]
        if actual != dtype and not (actual == pl.Null and dtype == pl.String):
            raise ValueError(f"SUE report context requires clean {name} values")
    known = income_history.select(*_HISTORY_SCHEMA).filter(
        pl.col("symbol").is_in(keys["symbol"].to_list())
        & (pl.col("available_date") < as_of)
        & (pl.col("end_date") <= as_of)
        & (pl.col("report_type") == "1")
    ).with_columns(
        (pl.col("update_flag") == "1").fill_null(False).cast(pl.Int8).alias("_update_rank"),
        pl.col("comp_type").cast(pl.String).fill_null("<null>").alias("_comp_type"),
    )
    latest_period = known.group_by("symbol").agg(pl.col("end_date").max())
    known = known.join(latest_period, on=["symbol", "end_date"], how="inner")
    latest_available = known.group_by("symbol").agg(pl.col("available_date").max())
    known = known.join(latest_available, on=["symbol", "available_date"], how="inner")
    highest_update = known.group_by("symbol").agg(pl.col("_update_rank").max())
    known = known.join(highest_update, on=["symbol", "_update_rank"], how="inner")
    context = known.group_by("symbol").agg(
        pl.col("end_date").first().alias("latest_report_end"),
        pl.col("available_date").first().alias("latest_available_date"),
        pl.col("_comp_type").unique().sort().alias("_types"),
    ).with_columns(
        pl.col("_types").list.join(",").alias("latest_comp_types"),
        pl.when((pl.col("_types").list.len() == 1)
                & pl.col("_types").list.first().is_in(_KNOWN_COMP_TYPES))
        .then(pl.col("_types").list.first()).otherwise(None).alias("latest_comp_type"),
        pl.when(pl.col("_types").list.len() > 1).then(pl.lit("ambiguous"))
        .when(pl.col("_types").list.first() == "1").then(pl.lit("industrial"))
        .when(pl.col("_types").list.first().is_in(_KNOWN_COMP_TYPES))
        .then(pl.lit("non_industrial"))
        .otherwise(pl.lit("unknown")).alias("report_context"),
    ).drop("_types")
    result = keys.join(values, on=_KEYS, how="left", validate="1:1").join(
        context, on="symbol", how="left", validate="m:1",
    ).with_columns(pl.col("report_context").fill_null("no_report"))
    return result.with_columns(
        (pl.col("factor_value").is_finite().fill_null(False)
         & (pl.col("report_context") != "industrial")).alias("unexpected_factor_value"),
    ).sort(_KEYS)


def read_sue_report_context(
    *, data_root: Path, snapshot: str, pool: pl.DataFrame, factor_values: pl.DataFrame,
    as_of: dt.date,
) -> pl.DataFrame:
    """Read existing full-period income history, then inspect latest PIT context."""
    keys = _pool_keys(pool, as_of)
    history = (read_tushare_financial_history(data_root=data_root,
        query=TushareFinancialHistoryQuery(snapshot_id=snapshot, dataset="income",
            start_period=dt.date(1900, 1, 1), end_period=as_of,
            symbols=tuple(keys["symbol"].unique().sort().to_list())))
        if keys.height else pl.DataFrame(schema=_HISTORY_SCHEMA))
    return diagnose_sue_report_context(pool=keys, income_history=history,
                                      factor_values=factor_values, as_of=as_of)
