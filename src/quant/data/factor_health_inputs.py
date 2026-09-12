"""Bounded raw factor inputs and causal annual schedules for health diagnostics."""
from __future__ import annotations

from collections.abc import Mapping
import bisect
import datetime as dt
from pathlib import Path
import re

import polars as pl

from quant.data.factor_battery_inputs import read_frozen_battery_universe
from quant.data.factor_panels import available_sessions

_ID = re.compile(r"^[A-Za-z0-9_]+$")
_FACTOR_SCHEMA = {"trade_date": pl.Date, "ts_code": pl.String, "value": pl.Float64}
_SCHEDULE_SCHEMA = {
    "as_of": pl.Date, "factor": pl.String, "factor_id": pl.String,
    "test_year": pl.Int64, "refit_close": pl.Date, "variant": pl.String,
}


def _dates(as_of_dates: list[dt.date]) -> list[dt.date]:
    if (not as_of_dates or any(type(day) is not dt.date for day in as_of_dates)
            or len(set(as_of_dates)) != len(as_of_dates)):
        raise ValueError("Require nonempty unique calendar dates")
    return sorted(as_of_dates)


def _factor_id(value: str) -> None:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError("Invalid factor identifier")


def read_factor_health_inputs(
    *, data_root: Path, statistics: Path, factor_id: str, as_of_dates: list[dt.date],
) -> pl.DataFrame:
    """Left-join raw values onto the complete frozen eligible pool on requested dates.

    No score, z-score, current industry or alternative factor is consulted. Status
    distinguishes missing yearly files, absent keys, null values and nonfinite
    values. Frozen null industry/size controls remain null and do not remove rows.
    """
    _factor_id(factor_id)
    dates = _dates(as_of_dates)
    frozen = read_frozen_battery_universe(statistics=statistics, as_of_dates=dates)
    if frozen.schema["eligible"] != pl.Boolean or frozen["eligible"].null_count():
        raise ValueError("Frozen eligibility must be a non-null boolean")
    if (frozen.schema["industry_l1"] not in (pl.String, pl.Null) or
            (frozen.schema["total_market_value"] != pl.Null and
             not frozen.schema["total_market_value"].is_numeric())):
        raise ValueError("Invalid frozen industry/size control schema")
    pool = frozen.filter(pl.col("eligible")).select(
        "symbol", "trade_date", pl.col("industry_l1").cast(pl.String),
        pl.col("total_market_value").cast(pl.Float64),
    )
    parts = []
    for year in sorted({day.year for day in dates}):
        year_pool = pool.filter(pl.col("trade_date").dt.year() == year)
        path = data_root / "factors" / factor_id / f"year={year}/data.parquet"
        if not path.is_file():
            parts.append(year_pool.with_columns(pl.lit(None, dtype=pl.Float64).alias("value"),
                pl.lit("missing_partition").alias("raw_value_status")))
            continue
        lazy = pl.scan_parquet(path)
        if dict(lazy.collect_schema()) != _FACTOR_SCHEMA:
            raise ValueError(f"Wrong raw factor schema: {factor_id}, {year}")
        values = lazy.filter(pl.col("trade_date").is_in([day for day in dates if day.year == year])).collect()
        if values["ts_code"].null_count() or values.select("ts_code", "trade_date").is_duplicated().any():
            raise ValueError(f"Null or duplicate raw factor stock/date keys: {factor_id}, {year}")
        values = values.rename({"ts_code": "symbol"}).with_columns(pl.lit(True).alias("_factor_row"))
        joined = year_pool.join(values, on=["symbol", "trade_date"], how="left", validate="1:1")
        parts.append(joined.with_columns(
            pl.when(pl.col("_factor_row").is_null()).then(pl.lit("missing_row"))
            .when(pl.col("value").is_null()).then(pl.lit("null_value"))
            .when(~pl.col("value").is_finite()).then(pl.lit("nonfinite_value"))
            .otherwise(pl.lit("observed")).alias("raw_value_status"),
        ).drop("_factor_row"))
    return pl.concat(parts).sort("trade_date", "symbol")


def read_factor_health_selection(
    *, selection: Path, as_of_dates: list[dt.date], max_factors: int = 20,
    replacements: Mapping[str, str] | None = None,
) -> pl.DataFrame:
    """Expand the latest known whole annual selection, preserving original IDs.

    A December refit applies from its own close, including when its test year is
    the following year. Future refits are ignored; no known refit, ambiguity and
    too-large output unions raise. Only an explicit mapping changes a factor ID.
    """
    dates = _dates(as_of_dates)
    if type(max_factors) is not int or max_factors < 1:
        raise ValueError("max_factors must be a positive integer")
    replacement_map = dict(replacements or {})
    for original, actual in replacement_map.items():
        _factor_id(original)
        _factor_id(actual)
    path = selection / "annual_selection.parquet"
    if not path.is_file():
        raise ValueError("Missing annual selection table")
    lazy = pl.scan_parquet(path)
    schema = lazy.collect_schema()
    required = {"factor": pl.String, "variant": pl.String, "refit_close": pl.Date,
                "provisional_selected": pl.Boolean}
    if (any(schema.get(name) != dtype for name, dtype in required.items()) or
            "test_year" not in schema or not schema["test_year"].is_integer()):
        raise ValueError("Wrong annual selection schema")
    annual = lazy.select(
        "factor", "variant", pl.col("test_year").cast(pl.Int64), "refit_close", "provisional_selected",
    ).collect()
    if annual.is_empty():
        raise ValueError("Annual selection table is empty")
    if annual.null_count().sum_horizontal().item():
        raise ValueError("Null annual selection keys or decision")
    if annual.select("test_year", "factor", "variant").is_duplicated().any():
        raise ValueError("Duplicate annual selection factor/year/variant")
    for factor in annual["factor"].unique():
        _factor_id(factor)
    if annual.filter(pl.col("variant") == "").height:
        raise ValueError("Annual selection variant is empty")
    refit_years = {}
    for year in annual["test_year"].unique().to_list():
        refits = annual.filter(pl.col("test_year") == year)["refit_close"].unique().to_list()
        if len(refits) != 1:
            raise ValueError("Conflicting annual refit dates")
        if refits[0] in refit_years:
            raise ValueError("Ambiguous annual test years share one refit date")
        refit_years[refits[0]] = year
    known_refits = sorted(refit_years)
    date_years = {}
    for day in dates:
        index = bisect.bisect_right(known_refits, day) - 1
        if index < 0:
            raise ValueError(f"No annual refit was known on {day}")
        date_years[day] = refit_years[known_refits[index]]
    chosen = annual.filter(pl.col("provisional_selected") &
                           pl.col("test_year").is_in(set(date_years.values())))
    if chosen.select("test_year", "factor").is_duplicated().any():
        raise ValueError("Multiple selected variants for one factor/year")
    originals = chosen["factor"].unique().to_list()
    if len(originals) > max_factors:
        raise ValueError("Selected factor union exceeds max_factors")
    actuals = [replacement_map.get(factor, factor) for factor in originals]
    if len(set(actuals)) != len(actuals):
        raise ValueError("Replacement mapping merges distinct selected factors")
    records = []
    for day in dates:
        for row in chosen.filter(pl.col("test_year") == date_years[day]).to_dicts():
            records.append({"as_of": day, "factor": row["factor"],
                "factor_id": replacement_map.get(row["factor"], row["factor"]),
                "test_year": row["test_year"], "refit_close": row["refit_close"], "variant": row["variant"]})
    return pl.from_dicts(records, schema=_SCHEDULE_SCHEMA).sort("as_of", "factor")


def read_factor_health_month_ends(
    *, data_root: Path, statistics: Path, start: dt.date, end: dt.date,
) -> list[dt.date]:
    """Use completed exchange-calendar month ends and require matching frozen input."""
    if type(start) is not dt.date or type(end) is not dt.date or start > end:
        raise ValueError("Require an ordered calendar date interval")
    sessions = available_sessions(data_root, end + dt.timedelta(days=40))
    if not sessions or list(sessions) != sorted(set(sessions)):
        raise ValueError("Invalid available exchange sessions")
    confirmed = {(before.year, before.month): before for before, after in zip(sessions, sessions[1:])
                 if (before.year, before.month) != (after.year, after.month)}
    month = start.replace(day=1)
    while month <= end:
        if (month.year, month.month) not in confirmed:
            raise ValueError(f"Exchange calendar cannot confirm completed month: {month:%Y-%m}")
        month = (month.replace(year=month.year + 1, month=1) if month.month == 12 else
                 month.replace(month=month.month + 1))
    dates = sorted(day for day in confirmed.values() if start <= day <= end)
    if dates:
        read_frozen_battery_universe(statistics=statistics, as_of_dates=dates)
    return dates


__all__ = [
    "read_factor_health_inputs", "read_factor_health_selection", "read_factor_health_month_ends",
]
