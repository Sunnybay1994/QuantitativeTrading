"""Increment daily Shanghai/Shenzhen stock data without rebuilding frozen history."""

import argparse
import datetime as dt
import json
import time
import tomllib
from pathlib import Path
from typing import Any

import polars as pl

from quant.data.calendar import expected_open_dates
from quant.data.connectors.tushare import TushareConnector
from quant.data.mappers import TushareBarMapper
from quant.data.storage import RawStore
from quant.domain import AdjustmentFactorSchema, Bar1dSchema, DailyBasic1dSchema

TABLES = ("bar_1d", "adjust_factor", "daily_basic")
_RENAMES = {
    "turnover_rate_f": "turnover_rate_free", "dv_ratio": "dividend_yield",
    "dv_ttm": "dividend_yield_ttm", "total_share": "total_shares",
    "float_share": "float_shares", "free_share": "free_float_shares",
    "total_mv": "total_market_value", "circ_mv": "circulating_market_value",
}
_BASIC_NUMBERS = (
    "close", "turnover_rate", "turnover_rate_f", "volume_ratio", "pe", "pe_ttm", "pb",
    "ps", "ps_ttm", "dv_ratio", "dv_ttm", "total_share", "float_share", "free_share",
    "total_mv", "circ_mv",
)
_TEN_THOUSAND = {"total_share", "float_share", "free_share", "total_mv", "circ_mv"}


def normalize_day(
    daily: pl.DataFrame, factors: pl.DataFrame, basic: pl.DataFrame, *, date: dt.date,
) -> dict[str, pl.DataFrame]:
    """Keep all traded SH/SZ stocks and require exact factor/basic matches."""
    selected = []
    for name, frame in (("daily", daily), ("adj_factor", factors), ("daily_basic", basic)):
        if frame.is_empty() or frame.height >= 6000:
            raise ValueError(f"{name}: empty response or supplier row limit reached")
        if frame["trade_date"].unique().to_list() != [date.strftime("%Y%m%d")]:
            raise ValueError(f"{name}: response date differs from request")
        frame = frame.filter(pl.col("ts_code").str.contains(r"^[0-9]{6}\.(SH|SZ)$"))
        if frame.is_empty() or frame["ts_code"].is_duplicated().any():
            raise ValueError(f"{name}: empty universe or duplicate stock")
        selected.append(frame)
    daily, factors, basic = selected
    traded = set(daily["ts_code"])
    if not traded <= set(factors["ts_code"]) or not traded <= set(basic["ts_code"]):
        raise ValueError("Traded stocks are missing adjustment factors or daily_basic")
    paired = daily.select("ts_code", "close").join(
        basic.select("ts_code", pl.col("close").alias("basic_close")), on="ts_code"
    )
    if paired.filter((pl.col("close") - pl.col("basic_close")).abs() > 1e-8).height:
        raise ValueError("Daily close differs from daily_basic close")
    bars = TushareBarMapper().map(daily.with_columns(
        pl.col("ts_code").alias("_request_symbol"),
        pl.col("ts_code").str.split(".").list.last().alias("_market"),
    )).drop("adj_factor").join(
        factors.select(pl.col("ts_code").alias("symbol"), pl.col("adj_factor").cast(pl.Float64)),
        on="symbol", validate="1:1",
    ).select("symbol", "trade_date", "open", "high", "low", "close", "volume", "amount",
             "adj_factor", "source").sort("symbol")
    adjustment = factors.select(
        pl.col("ts_code").alias("symbol"), pl.lit(date).alias("effective_date"),
        pl.col("adj_factor").cast(pl.Float64), pl.lit("tushare").alias("source"),
    ).sort("symbol")
    daily_basic = basic.select(
        pl.col("ts_code").alias("symbol"), pl.lit(date).alias("trade_date"),
        *[(pl.col(name).cast(pl.Float64) * (10000 if name in _TEN_THOUSAND else 1))
          .alias(_RENAMES.get(name, name)) for name in _BASIC_NUMBERS],
        pl.lit("tushare").alias("source"),
    ).sort("symbol")
    invalid_free_float = pl.col("free_float_shares") > pl.col("float_shares")
    daily_basic = daily_basic.with_columns(
        pl.when(invalid_free_float).then(None).otherwise(pl.col("free_float_shares"))
        .alias("free_float_shares"),
        pl.when(invalid_free_float).then(None).otherwise(pl.col("turnover_rate_free"))
        .alias("turnover_rate_free"),
    )
    return {"bar_1d": Bar1dSchema.validate(bars),
            "adjust_factor": AdjustmentFactorSchema.validate(adjustment),
            "daily_basic": DailyBasic1dSchema.validate(daily_basic)}


def history_end(data_root: Path, settings: dict[str, Any]) -> dt.date:
    paths = (
        data_root / "clean/tushare_bulk/snapshots" / settings["stock_snapshot"]
        / "bar_1d/asset=stock/year=*/*.parquet",
        data_root / "clean/tushare_daily_basic/snapshots" / settings["daily_basic_snapshot"]
        / "year=*/*.parquet",
    )
    dates = [pl.scan_parquet(str(path)).select(pl.col("trade_date").max()).collect().item()
             for path in paths]
    return min(dates)


def read_stock_data(
    *, data_root: Path, config: Path, table: str, start: dt.date, end: dt.date,
    symbols: list[str] | None = None,
) -> pl.DataFrame:
    """Read the frozen historical table plus complete daily increments."""
    if table not in TABLES or start > end:
        raise ValueError("Invalid stock data query")
    settings = tomllib.loads(config.read_text(encoding="utf-8"))
    if table == "daily_basic":
        history = data_root / "clean/tushare_daily_basic/snapshots" / settings["daily_basic_snapshot"]
        history_glob = str(history / "year=*/*.parquet")
    else:
        history = data_root / "clean/tushare_bulk/snapshots" / settings["stock_snapshot"]
        history_glob = str(history / "bar_1d/asset=stock/year=*/*.parquet")
    old = pl.scan_parquet(history_glob).filter(pl.col("trade_date").is_between(start, end))
    date_column = "effective_date" if table == "adjust_factor" else "trade_date"
    if table == "adjust_factor":
        old = old.select("symbol", pl.col("trade_date").alias("effective_date"), "adj_factor", "source")
    frames = [old]
    for date in sorted((data_root / "clean/tushare_incremental").glob("date=*")):
        if (start.isoformat() <= date.name[5:] <= end.isoformat()
                and all((date / f"{name}.parquet").is_file() for name in TABLES)):
            frames.append(pl.scan_parquet(date / f"{table}.parquet"))
    combined = pl.concat(frames, how="vertical_relaxed")
    if symbols is not None:
        combined = combined.filter(pl.col("symbol").is_in(symbols))
    return combined.collect().unique(subset=["symbol", date_column], keep="last",
                                     maintain_order=True).sort(date_column, "symbol")


def refresh(
    *, end: dt.date, data_root: Path, artifact_root: Path, config: Path,
) -> dict[str, Any]:
    settings = tomllib.loads(config.read_text(encoding="utf-8"))
    base_end = history_end(data_root, settings)
    if end <= base_end:
        return {"new_dates": 0, "new_rows": dict.fromkeys(TABLES, 0), "message": "no-op"}
    dates = sorted(expected_open_dates(data_root, ["000001.SZ", "600000.SH"],
                                       base_end + dt.timedelta(days=1), end))
    root = data_root / "clean/tushare_incremental"
    todo = [date for date in dates
            if not all((root / f"date={date}" / f"{name}.parquet").is_file() for name in TABLES)]
    if not todo:
        return {"new_dates": 0, "new_rows": dict.fromkeys(TABLES, 0),
                "latest_date": str(dates[-1] if dates else base_end), "message": "no-op"}
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = artifact_root / "data_quality/stock_refresh" / stamp
    output.mkdir(parents=True)
    connector = TushareConnector(config_path=Path("configs/tushare.local.toml"))
    raw_store = RawStore(data_root / "raw")
    totals = dict.fromkeys(TABLES, 0)
    records: list[dict[str, Any]] = []
    spacing = 60 / int(settings["requests_per_minute"])
    if spacing < 0.2:
        raise ValueError("requests_per_minute must be between 1 and 300")
    for date in todo:
        raw: list[pl.DataFrame] = []
        paths = []
        for api in ("daily", "adj_factor", "daily_basic"):
            for attempt in range(3):
                time.sleep(spacing * (attempt + 1))
                try:
                    frame = connector.query_raw(api, trade_date=date.strftime("%Y%m%d"))
                    break
                except Exception:
                    if attempt == 2:
                        raise RuntimeError(f"{api} request failed on {date} after 3 attempts") from None
            snapshot = raw_store.write(source="tushare", table=api, frame=frame,
                                       parameters={"trade_date": date.strftime("%Y%m%d")})
            raw.append(frame)
            paths.append(str(snapshot.data_path))
        clean = normalize_day(*raw, date=date)
        target = root / f"date={date}"
        temporary = root / f".date={date}-{stamp}"
        temporary.mkdir(parents=True)
        for name, frame in clean.items():
            frame.write_parquet(temporary / f"{name}.parquet")
        # One directory rename exposes the three complete tables together.
        # Existing partial partitions are repaired in place from the saved raw.
        if target.exists():
            for name in TABLES:
                (temporary / f"{name}.parquet").replace(target / f"{name}.parquet")
            temporary.rmdir()
        else:
            temporary.rename(target)
        counts = {name: frame.height for name, frame in clean.items()}
        for name in TABLES:
            totals[name] += counts[name]
        records.append({"date": str(date), "rows": counts, "raw_paths": paths,
                        "invalid_free_float_set_null": raw[2].filter(
                            pl.col("ts_code").str.contains(r"^[0-9]{6}\.(SH|SZ)$")
                            & (pl.col("free_share") > pl.col("float_share"))).height,
                        "excluded_non_sh_sz": [frame.height - clean[name].height
                                               for frame, name in zip(raw, TABLES, strict=True)]})
        (output / "days.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
        print(f"Published {date}: {counts}", flush=True)
    summary = {"new_dates": len(todo), "new_rows": totals,
               "latest_date": str(dates[-1]), "base_date": str(base_end),
               "artifact_path": str(output), "universe": "SH/SZ stocks",
               "invalid_free_float_set_null": sum(r["invalid_free_float_set_null"] for r in records)}
    (output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--end", required=True, type=dt.date.fromisoformat)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--artifact-root", type=Path, default=Path("artifacts"))
    parser.add_argument("--config", type=Path, default=Path("configs/data/refresh.toml"))
    args = parser.parse_args()
    print(json.dumps(refresh(end=args.end, data_root=args.data_root,
                             artifact_root=args.artifact_root, config=args.config), indent=2))


if __name__ == "__main__":
    main()
