"""Check and fill only the latest requested daily slice using existing refresh entrypoints."""

from __future__ import annotations
import datetime as dt
import json
import time
import tomllib
from pathlib import Path
from typing import Any
import polars as pl
from quant.data.connectors.tushare import TushareConnector
from quant.data.refresh_stocks import refresh as refresh_stocks, normalize_day, TABLES
from quant.data.refresh_etf_prices import refresh as refresh_etfs
from quant.data.storage import RawStore
from quant.domain import AdjustmentFactorSchema

CONFIG = Path("configs/data/daily_freshness_20260912.toml")


def profile(frame: pl.DataFrame, date_col: str, date: dt.date) -> dict[str, Any]:
    today = frame.filter(pl.col(date_col) == date)
    return {
        "rows": today.height,
        "symbols": today["symbol"].n_unique(),
        "duplicate_keys": today.height - today.select("symbol", date_col).unique().height,
        "latest_date": str(frame[date_col].max()),
        "symbol_list": sorted(today["symbol"].to_list()),
    }


def run() -> dict[str, Any]:
    settings = tomllib.loads(CONFIG.read_text(encoding="utf-8-sig"))
    date = dt.date.fromisoformat(settings["audit"]["trade_date"])
    output = Path(settings["audit"]["artifact_root"])
    output.mkdir(parents=True, exist_ok=True)
    if (output / "result.json").is_file():
        return json.loads((output / "result.json").read_text(encoding="utf8"))
    etf_config = Path(settings["etf_config"])
    universe = tomllib.loads(etf_config.read_text(encoding="utf8"))["universe"]
    symbols = sorted({s for v in universe.values() if isinstance(v, list) for s in v})
    # Refuse any older stock gap; this task must not trigger a historical backfill.
    from quant.data.refresh_stocks import history_end
    from quant.data.calendar import expected_open_dates

    start = history_end(Path("data"), settings) + dt.timedelta(days=1)
    dates = sorted(expected_open_dates(Path("data"), ["000001.SZ", "600000.SH"], start, date))
    missing = [
        str(d)
        for d in dates
        if not all(
            (Path("data/clean/tushare_incremental") / f"date={d}" / f"{t}.parquet").exists()
            for t in TABLES
        )
    ]
    if any(d != str(date) for d in missing):
        raise ValueError("Older gaps require a separate task: " + str(missing))
    for table in ["bar_1d", "research_price_1d"]:
        prior = (
            pl.scan_parquet(f"data/clean/{table}/date=*/*.parquet")
            .filter(pl.col("symbol").is_in(symbols))
            .group_by("symbol")
            .agg(pl.col("trade_date").max())
            .collect()
        )
        minimum = prior["trade_date"].min()
        if (
            not isinstance(minimum, dt.date)
            or prior.height != len(symbols)
            or minimum < date - dt.timedelta(days=1)
        ):
            raise ValueError("ETF earlier gaps exceed this one-day scope")
    stocks_result = refresh_stocks(
        end=date, data_root=Path("data"), artifact_root=output, config=CONFIG
    )
    etfs_result = refresh_etfs(
        end=date, data_root=Path("data"), artifact_root=output, config=etf_config
    )
    stock = {
        t: pl.read_parquet(Path("data/clean/tushare_incremental") / f"date={date}" / f"{t}.parquet")
        for t in TABLES
    }
    profiles = {
        t: profile(f, "effective_date" if t == "adjust_factor" else "trade_date", date)
        for t, f in stock.items()
    }
    bars = pl.read_parquet(f"data/clean/bar_1d/date={date}/data.parquet").filter(
        pl.col("symbol").is_in(symbols)
    )
    prices = pl.read_parquet(f"data/clean/research_price_1d/date={date}/data.parquet").filter(
        pl.col("symbol").is_in(symbols)
    )
    profiles.update(
        etf_bar=profile(bars, "trade_date", date),
        etf_total_return=profile(prices, "trade_date", date),
    )
    traded = set(stock["bar_1d"]["symbol"])
    factors = set(stock["adjust_factor"]["symbol"])
    basic = set(stock["daily_basic"]["symbol"])
    gaps = {
        "bar_missing_factor": sorted(traded - factors),
        "bar_missing_basic": sorted(traded - basic),
        "factor_without_bar": sorted(factors - traded),
        "etf_missing_bar": sorted(set(symbols) - set(bars["symbol"])),
        "etf_missing_total_return": sorted(set(symbols) - set(prices["symbol"])),
    }
    old_days = json.loads(
        Path("artifacts/data_quality/stock_refresh/20260911T091856918338Z/days.json").read_text(
            encoding="utf8"
        )
    )[0]
    rebuilt = normalize_day(*(pl.read_parquet(p) for p in old_days["raw_paths"]), date=date)
    raw_reproduction = {
        t: stock[t].sort("symbol").equals(rebuilt[t].sort("symbol")) for t in TABLES
    }
    connector = TushareConnector(config_path=Path("configs/tushare.local.toml"))
    store = RawStore(Path("data/raw"))
    calls: list[dict[str, Any]] = []

    def query(api: str, **params: str) -> pl.DataFrame:
        # Resume from already captured raw for this date, including interrupted calls.
        raw_folder = Path("data/raw/tushare") / api / f"date={date}"
        for metadata in sorted(raw_folder.glob("*.json"), reverse=True):
            saved_meta = json.loads(metadata.read_text(encoding="utf8"))
            candidate = metadata.with_suffix(".parquet")
            if saved_meta.get("parameters") == params and candidate.is_file():
                frame = pl.read_parquet(candidate)
                calls.append(
                    {
                        "api": api,
                        "params": params,
                        "rows": frame.height,
                        "raw_path": str(candidate),
                        "reused": True,
                    }
                )
                return frame
        time.sleep(2)
        try:
            frame = connector.query_raw(api, **params)
        except Exception:
            calls.append(
                {
                    "api": api,
                    "params": params,
                    "status": "failed; credential-bearing error suppressed",
                }
            )
            raise RuntimeError(api + " unavailable") from None
        saved = store.write(source="tushare", table=api, frame=frame, parameters=params)
        calls.append(
            {"api": api, "params": params, "rows": frame.height, "raw_path": str(saved.data_path)}
        )
        return frame

    suspension = []
    try:
        suspension = (
            query("suspend_d", trade_date=date.strftime("%Y%m%d"))
            .filter(pl.col("ts_code").is_in(gaps["factor_without_bar"]))
            .to_dicts()
        )
    except RuntimeError:
        pass
    etf_adj = []
    adj_status = "unavailable"
    for symbol in symbols:
        try:
            frame = query("fund_adj", ts_code=symbol, trade_date=date.strftime("%Y%m%d"))
        except RuntimeError:
            break
        frame = frame.filter(
            (pl.col("ts_code") == symbol) & (pl.col("trade_date") == date.strftime("%Y%m%d"))
        )
        if frame.height != 1:
            raise ValueError("Expected one ETF adjustment row: " + symbol)
        etf_adj.append(frame)
    adj_path = None
    if len(etf_adj) == len(symbols):
        clean = pl.concat(etf_adj).select(
            pl.col("ts_code").alias("symbol"),
            pl.col("trade_date").str.to_date("%Y%m%d").alias("effective_date"),
            pl.col("adj_factor").cast(pl.Float64),
            pl.lit("tushare").alias("source"),
        )
        clean = AdjustmentFactorSchema.validate(clean)
        folder = Path("data/clean/etf_daily_slices/snapshots/daily_freshness_20260912_01")
        folder.mkdir(parents=True, exist_ok=False)
        adj_path = str(folder / "adjust_factor.parquet")
        clean.write_parquet(adj_path)
        adj_status = "complete_new_slice"
    result = {
        "trade_date": str(date),
        "stock_refresh": stocks_result,
        "etf_refresh": etfs_result,
        "profiles": profiles,
        "gaps": gaps,
        "stock_raw_reproduction": raw_reproduction,
        "suspension_rows": suspension,
        "etf_fund_adj_status": adj_status,
        "etf_fund_adj_rows": len(etf_adj),
        "etf_fund_adj_clean": adj_path,
        "api_calls": calls,
        "etf_daily_basic": "not_applicable: stock daily_basic is not an ETF fundamentals table",
        "existing_etf_bar_factor_values": bars["adj_factor"].unique().to_list(),
    }
    (output / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf8"
    )
    print(
        json.dumps(
            {k: v for k, v in result.items() if k != "profiles"}, ensure_ascii=False, default=str
        ),
        flush=True,
    )
    return result


if __name__ == "__main__":
    run()
