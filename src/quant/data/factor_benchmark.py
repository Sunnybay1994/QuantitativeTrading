"""Read the dated benchmark snapshot used by market-risk factor columns."""
import datetime as dt
import json
import re
import time
import tomllib
from pathlib import Path
from typing import Any

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


def refresh_factor_benchmark(*, data_root: Path, config: Path, end: dt.date,
                             client: Any = None) -> dict[str, Any]:
    """Extend the configured benchmark, retaining its old snapshot and raw captures."""
    from quant.data.connectors.tushare import TushareConnector
    from quant.data.factor_panels import available_sessions
    from quant.data.mappers import TushareBarMapper
    from quant.data.storage import RawStore

    text = config.read_text(encoding="utf-8")
    settings = tomllib.loads(text)
    snapshot = settings["factor_benchmark_snapshot"]
    old = read_factor_benchmark(data_root, config, dt.date(1900, 1, 1), dt.date.max).sort("trade_date")
    if old.is_empty():
        raise ValueError("Factor benchmark requires an existing historical snapshot")
    first, last = old["trade_date"].min(), old["trade_date"].max()
    if not isinstance(first, dt.date) or not isinstance(last, dt.date):
        raise ValueError("Factor benchmark requires dated observations")
    sessions = {day for day in available_sessions(data_root, end) if first <= day <= end}
    if not sessions or {day for day in sessions if day <= last} - set(old["trade_date"]):
        raise ValueError("Existing factor benchmark has missing exchange sessions")
    latest = max(sessions)
    if last >= latest:
        return {"new_rows": 0, "latest_date": str(last), "snapshot": snapshot}
    # Preserve unrelated settings and comments; this entry must be unambiguous.
    pattern = r'(?m)^(factor_benchmark_snapshot\s*=\s*)[\"\'][^\"\']+[\"\']'
    if len(re.findall(pattern, text)) != 1:
        raise ValueError("Expected one factor_benchmark_snapshot assignment")
    client = client or TushareConnector(config_path=Path("configs/tushare.local.toml"))
    store = RawStore(data_root / "raw")
    frames: dict[str, list[pl.DataFrame]] = {"fund_daily": [], "fund_adj": []}
    raw_paths = []
    for year in range(last.year, latest.year + 1):
        low, high = max(last, dt.date(year, 1, 1)), min(latest, dt.date(year, 12, 31))
        for endpoint in frames:
            params = {"ts_code": "510300.SH", "start_date": low.strftime("%Y%m%d"),
                      "end_date": high.strftime("%Y%m%d")}
            for attempt in range(3):
                try:
                    frame = client.query_raw(endpoint, **params)
                    break
                except Exception:
                    if attempt == 2:
                        raise RuntimeError(f"Factor benchmark {endpoint} request failed") from None
                    time.sleep(attempt + 1)
            saved = store.write(source="tushare", table=endpoint, frame=frame, parameters=params)
            raw_paths.append(str(saved.data_path))
            if not frame.is_empty():
                if set(frame["ts_code"]) != {"510300.SH"}:
                    raise ValueError("Unexpected factor benchmark symbol")
                frames[endpoint].append(frame)
            time.sleep(0.4)
    if any(not parts for parts in frames.values()):
        raise ValueError("Missing benchmark prices or adjustment factors")
    daily = pl.concat(frames["fund_daily"], how="diagonal_relaxed")
    adjustments = pl.concat(frames["fund_adj"], how="diagonal_relaxed").select(
        pl.col("ts_code").alias("symbol"), pl.col("trade_date").str.to_date("%Y%m%d"),
        pl.col("adj_factor").cast(pl.Float64))
    mapped = TushareBarMapper().map(daily.with_columns(
        pl.col("ts_code").alias("_request_symbol"), pl.lit("SH").alias("_market")))
    fresh = Bar1dSchema.validate(mapped.drop("adj_factor").join(
        adjustments, on=["symbol", "trade_date"], how="left", validate="1:1")).sort("trade_date")
    if (fresh["adj_factor"].null_count() or not fresh["adj_factor"].is_finite().all()
            or not (fresh["adj_factor"] > 0).all()
            or fresh["trade_date"].is_duplicated().any()
            or set(fresh["trade_date"]) != {day for day in sessions if day >= last}):
        raise ValueError("Incomplete factor benchmark dates or adjustment factors")
    prices = ["open", "high", "low", "close", "adj_factor"]
    seam = fresh.filter(pl.col("trade_date") == last).select(prices)
    if not seam.equals(old.tail(1).select(prices)):
        raise ValueError("Factor benchmark overlap changed; historical recomputation required")
    incoming = fresh.filter(pl.col("trade_date") > last)
    combined = pl.concat([old, incoming.select(old.columns)], how="vertical_relaxed").sort("trade_date")
    name = "510300_" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = data_root / "clean/factor_benchmark" / name
    output.mkdir(parents=True, exist_ok=False)
    combined.write_parquet(output / "bars.parquet")
    result = {"new_rows": incoming.height, "latest_date": str(latest), "snapshot": name,
              "previous_snapshot": snapshot, "raw_paths": raw_paths,
              "price_basis": "unadjusted OHLC with vendor fund_adj"}
    (output / "summary.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    config.write_text(re.sub(pattern, lambda match: match[1] + '"' + name + '"', text), encoding="utf-8")
    return result
