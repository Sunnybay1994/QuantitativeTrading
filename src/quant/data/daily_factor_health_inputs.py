"""Read current-session health inputs using the historical battery's eligibility rules."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
import re
import tomllib

import polars as pl

from quant.data.factor_panels import available_sessions
from quant.data.industry_history import attach_industry
from quant.data.refresh_stocks import read_stock_data
from quant.research.factor_battery_universe import prepare_battery_universe

_KEYS = ["symbol", "trade_date"]


def _read_current_limits(
    data_root: Path, snapshot: str, as_of: dt.date, required_keys: pl.DataFrame,
) -> tuple[pl.DataFrame, str]:
    if not snapshot or Path(snapshot).name != snapshot or snapshot in (".", ".."):
        raise ValueError("Invalid configured limits snapshot")
    candidates = [data_root / f"clean/factor_execution/{snapshot}/year={as_of.year}/limits.parquet",
                  data_root / f"clean/stock_paper_inputs/date={as_of}/limits.parquet"]
    for path in candidates:
        if path.is_file():
            frame = pl.scan_parquet(path).filter(pl.col("trade_date") == as_of).select(
                *_KEYS, "up_limit", "down_limit").collect()
            if frame.height:
                if frame.select(_KEYS).is_duplicated().any():
                    raise ValueError("Duplicate current-session limit keys")
                if required_keys.join(frame.select(_KEYS), on=_KEYS, how="anti").is_empty():
                    return frame, str(path)
    # Existing same-day raw is a bounded last fallback; no capture or network call.
    for metadata in sorted((data_root / f"raw/tushare/stk_limit/date={as_of}").glob("*.json"), reverse=True):
        description = json.loads(metadata.read_text(encoding="utf-8"))
        if description.get("parameters", {}).get("trade_date") != as_of.strftime("%Y%m%d"):
            continue
        path = metadata.with_suffix(".parquet")
        raw = pl.read_parquet(path)
        if raw.is_empty() or raw["trade_date"].unique().to_list() != [as_of.strftime("%Y%m%d")]:
            raise ValueError("Current raw limits are empty or wrong-date")
        frame = raw.filter(pl.col("ts_code").str.contains(r"^\d{6}\.(SH|SZ)$")).select(
            pl.col("ts_code").alias("symbol"), pl.lit(as_of).alias("trade_date"),
            pl.col("up_limit").cast(pl.Float64), pl.col("down_limit").cast(pl.Float64))
        if frame["symbol"].null_count() or frame["symbol"].is_duplicated().any():
            raise ValueError("Invalid current raw limit keys")
        if required_keys.join(frame.select(_KEYS), on=_KEYS, how="anti").is_empty():
            return frame, str(path)
    raise ValueError(f"No saved complete same-session limits for {as_of}; old limits cannot replace them")


def _read_current_industry(data_root: Path, as_of: dt.date) -> tuple[pl.DataFrame, str]:
    for path in sorted((data_root / "clean/tushare_industry").glob("*/summary.json"), reverse=True):
        summary = json.loads(path.read_text(encoding="utf-8"))
        if not summary.get("with_current") or summary.get("as_of") != str(as_of):
            continue
        intervals = pl.read_parquet(path.parent / "intervals.parquet")
        if not intervals.filter((pl.col("valid_from") <= as_of) & (pl.col("valid_to") > as_of)).height:
            raise ValueError(f"Dated industry publication has no coverage for {as_of}")
        return intervals, str(path.parent / "intervals.parquet")
    raise ValueError(f"No saved industry publication covering exactly {as_of}; stale/future snapshots not substituted")


def read_daily_health_universe(
    *, data_root: Path, refresh_config: Path, battery_config: Path, as_of: dt.date,
) -> pl.DataFrame:
    """Return all current bar rows, eligibility reasons and same-day controls.

    Uses the same listing/ST/limits/liquidity function and configuration as the
    historical battery. Date-specific paper reference files are preferred when
    present. Missing individual basic/industry controls remain explicit nulls;
    absent current sessions, required warmup, limits or industry publications fail.
    """
    if type(as_of) is not dt.date:
        raise ValueError("as_of must be a calendar date")
    settings = tomllib.loads(battery_config.read_text(encoding="utf-8"))
    rules = settings["universe"]
    window = rules["amount_window_sessions"]
    if type(window) is not int or window < 1:
        raise ValueError("Invalid battery liquidity window")
    sessions = available_sessions(data_root, as_of)
    if not sessions or sessions[-1] != as_of or len(sessions) < window:
        raise ValueError(f"Calendar cannot supply {window} sessions ending on {as_of}")
    expected = sessions[-window:]
    bars = read_stock_data(data_root=data_root, config=refresh_config, table="bar_1d",
                           start=expected[0], end=as_of)
    if set(bars["trade_date"]) != set(expected):
        raise ValueError(f"Current bar/warmup session missing for {as_of}")
    current = bars.filter(pl.col("trade_date") == as_of)
    basic = read_stock_data(data_root=data_root, config=refresh_config, table="daily_basic", start=as_of, end=as_of)
    minimum = settings.get("minimum_symbols", 100)
    if current.height < minimum or basic.height < minimum or set(basic["trade_date"]) != {as_of}:
        raise ValueError(f"Insufficient same-session daily bars/basic for {as_of}")
    if basic.select(_KEYS).is_duplicated().any():
        raise ValueError("Duplicate same-session daily-basic keys")
    limits, limits_source = _read_current_limits(
        data_root, settings["data"]["limits_snapshot"], as_of, current.select(_KEYS),
    )
    if current.select(_KEYS).join(limits.select(_KEYS), on=_KEYS, how="anti").height:
        raise ValueError(f"Current-session limits do not cover all observed bars: {as_of}")
    intervals, industry_source = _read_current_industry(data_root, as_of)
    reference = data_root / f"clean/stock_paper_inputs/date={as_of}"
    if (reference / "instruments.parquet").is_file() and (reference / "names.parquet").is_file():
        instruments = pl.read_parquet(reference / "instruments.parquet")
        names = pl.read_parquet(reference / "names.parquet")
    else:
        instruments = pl.concat([pl.read_parquet(data_root / f"clean/instrument/market={market}/data.parquet")
                                 for market in ("SH", "SZ")])
        names = pl.read_parquet(data_root / "clean/stock_name_history/data.parquet")
    universe = prepare_battery_universe(bars, instruments, names, limits, sessions=sessions,
        minimum_listing_days=rules["minimum_listing_days"], amount_window_sessions=window,
        amount_exclude_bottom_fraction=rules["amount_exclude_bottom_fraction"]).filter(pl.col("trade_date") == as_of)
    controls = basic.select(*_KEYS, "total_market_value").with_columns(pl.lit(True).alias("daily_basic_row_present"))
    result = attach_industry(universe.join(controls, on=_KEYS, how="left", validate="1:1"), intervals)
    return result.with_columns(
        pl.col("daily_basic_row_present").fill_null(False), pl.lit(limits_source).alias("limits_source"),
        pl.lit(industry_source).alias("industry_source"), pl.lit(as_of).alias("industry_source_as_of"),
    ).sort("trade_date", "symbol")


def read_daily_health_factor(
    *, data_root: Path, factor_id: str, universe: pl.DataFrame, as_of: dt.date,
) -> pl.DataFrame:
    """Left-join one same-day raw factor onto eligible rows; keep five raw statuses."""
    if not isinstance(factor_id, str) or not re.fullmatch(r"[A-Za-z0-9_]+", factor_id):
        raise ValueError("Invalid factor identifier")
    required = {"symbol", "trade_date", "eligible", "industry_l1", "total_market_value"}
    if type(as_of) is not dt.date or not required <= set(universe.columns) or universe.is_empty():
        raise ValueError("Require a nonempty current-session universe with controls")
    if (universe["trade_date"].unique().to_list() != [as_of] or universe.select(_KEYS).is_duplicated().any()
            or universe.schema["eligible"] != pl.Boolean or universe["eligible"].null_count()
            or universe["symbol"].null_count()):
        raise ValueError("Invalid or wrong-date current-session universe")
    pool = universe.filter(pl.col("eligible")).select(*_KEYS, "industry_l1", "total_market_value")
    path = data_root / f"factors/{factor_id}/year={as_of.year}/data.parquet"
    if not path.is_file():
        return pool.with_columns(pl.lit(None, dtype=pl.Float64).alias("value"),
                                 pl.lit("missing_partition").alias("raw_value_status"))
    lazy = pl.scan_parquet(path)
    if dict(lazy.collect_schema()) != {"trade_date": pl.Date, "ts_code": pl.String, "value": pl.Float64}:
        raise ValueError("Wrong raw daily-factor schema")
    values = lazy.filter(pl.col("trade_date") == as_of).collect()
    if values["ts_code"].null_count() or values.select("ts_code", "trade_date").is_duplicated().any():
        raise ValueError("Duplicate or null raw daily-factor keys")
    values = values.rename({"ts_code": "symbol"}).with_columns(pl.lit(True).alias("_row"))
    return pool.join(values, on=_KEYS, how="left", validate="1:1").with_columns(
        pl.when(pl.col("_row").is_null()).then(pl.lit("missing_row"))
        .when(pl.col("value").is_null()).then(pl.lit("null_value"))
        .when(~pl.col("value").is_finite()).then(pl.lit("nonfinite_value"))
        .otherwise(pl.lit("observed")).alias("raw_value_status"),
    ).drop("_row").sort("trade_date", "symbol")


__all__ = ["read_daily_health_universe", "read_daily_health_factor"]
