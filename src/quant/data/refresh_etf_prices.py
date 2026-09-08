"""Increment ETF cash-dividend total returns after checking the existing seam."""

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
from quant.data.mappers import AkshareResearchPriceMapper, TushareBarMapper
from quant.data.research_price import validate_research_prices
from quant.data.storage import CleanBarStore, CleanResearchPriceStore, RawStore
from quant.domain import Bar1dSchema


def build_prices(daily: pl.DataFrame, dividends: pl.DataFrame) -> pl.DataFrame:
    """Match the existing (close + cash dividend) / previous close convention.

    fund_div.div_cash is yuan per unit. Duplicate implementation records for the
    same ex-date are one event; conflicting amounts must be resolved upstream.
    """
    prices = daily.select(
        pl.col("ts_code").alias("_request_symbol"),
        pl.col("trade_date").str.to_date("%Y%m%d").alias("日期"),
        pl.col("close").cast(pl.Float64).alias("收盘"),
    )
    if prices.select("_request_symbol", "日期").is_duplicated().any():
        raise ValueError("Duplicate ETF daily prices")
    if prices.filter(pl.col("收盘").is_null() | ~pl.col("收盘").is_finite()
                     | (pl.col("收盘") <= 0)).height:
        raise ValueError("Invalid ETF close")
    if dividends.is_empty():
        events = pl.DataFrame(schema={
            "_request_symbol": pl.String, "日期": pl.Date, "_cash_dividend": pl.Float64,
        })
    else:
        events = dividends.filter(
            (pl.col("div_proc") == "实施") & pl.col("ex_date").is_not_null()
        ).select(
            pl.col("ts_code").alias("_request_symbol"),
            pl.col("ex_date").str.to_date("%Y%m%d").alias("日期"),
            pl.col("div_cash").cast(pl.Float64).alias("_cash_dividend"),
        ).unique()
        if events.select("_request_symbol", "日期").is_duplicated().any():
            raise ValueError("Conflicting dividend amounts on one ex-date")
        if events.filter(pl.col("_cash_dividend").is_null()
                         | ~pl.col("_cash_dividend").is_finite()
                         | (pl.col("_cash_dividend") < 0)).height:
            raise ValueError("Invalid cash dividend")
    raw = prices.join(events, on=["_request_symbol", "日期"], how="left").with_columns(
        pl.lit("total_return_dividend").alias("_adjustment")
    )
    return AkshareResearchPriceMapper(source="tushare").map(raw)


def join_seam(
    candidate: pl.DataFrame, old: pl.DataFrame, *, minimum_overlap: int = 20,
) -> tuple[pl.DataFrame, list[dict[str, Any]]]:
    """Anchor once at the first overlap, then verify every overlap observation."""
    frames = []
    checks = []
    for symbol in candidate.get_column("symbol").unique().sort().to_list():
        fresh = candidate.filter(pl.col("symbol") == symbol).sort("trade_date")
        previous = old.filter(pl.col("symbol") == symbol).sort("trade_date")
        overlap = fresh.join(previous, on=["symbol", "trade_date"], suffix="_old")
        if overlap.height < minimum_overlap:
            raise ValueError(f"Insufficient overlap: {symbol}")
        scale = overlap["adjusted_close_old"][0] / overlap["adjusted_close"][0]
        errors = overlap.select(
            ((pl.col("adjusted_close") * scale / pl.col("adjusted_close_old")) - 1)
            .abs().alias("error")
        )["error"]
        maximum_value = errors.max()
        assert isinstance(maximum_value, float)
        maximum = maximum_value
        if maximum >= 1e-6:
            raise ValueError(f"ETF seam mismatch: {symbol}, relative_error={maximum:.9g}")
        frames.append(fresh.with_columns(pl.col("adjusted_close") * scale).filter(
            pl.col("trade_date") > previous["trade_date"].max()
        ))
        checks.append({"symbol": symbol, "overlap_rows": overlap.height,
                       "max_relative_error": maximum, "scale": scale})
    return pl.concat(frames), checks


def refresh(
    *, end: dt.date, data_root: Path, artifact_root: Path, config: Path,
) -> dict[str, Any]:
    universe = tomllib.loads(config.read_text(encoding="utf-8"))["universe"]
    symbols = sorted({s for value in universe.values() if isinstance(value, list) for s in value})
    root = data_root / "clean" / "research_price_1d"
    old = pl.read_parquet(str(root / "date=*" / "*.parquet")).filter(
        pl.col("symbol").is_in(symbols)
    )
    latest = old.group_by("symbol").agg(pl.col("trade_date").max())
    bar_root = data_root / "clean/bar_1d"
    old_bars = pl.read_parquet(str(bar_root / "date=*/*.parquet")).filter(
        pl.col("symbol").is_in(symbols)
    )
    bar_latest = old_bars.group_by("symbol").agg(pl.col("trade_date").max().alias("last_bar"))
    if latest.height != len(symbols) or bar_latest.height != len(symbols):
        raise ValueError("Existing ETF pool is incomplete")
    price_last, bar_last = latest["trade_date"].min(), bar_latest["last_bar"].min()
    assert isinstance(price_last, dt.date) and isinstance(bar_last, dt.date)
    last = min(price_last, bar_last)
    if last >= end:
        return {"new_rows": 0, "new_bar_rows": 0, "latest_date": str(last), "message": "no-op"}
    start = last - dt.timedelta(days=45)
    dates = expected_open_dates(data_root, symbols, start, end)
    end = max(dates)
    if last >= end:
        return {"new_rows": 0, "new_bar_rows": 0, "latest_date": str(last), "message": "no-op"}
    connector = TushareConnector(config_path=Path("configs/tushare.local.toml"))
    store = RawStore(data_root / "raw")
    daily_frames: list[pl.DataFrame] = []
    dividend_frames: list[pl.DataFrame] = []
    paths: list[str] = []
    for symbol in symbols:
        for api, params, frames in (
            ("fund_daily", {"ts_code": symbol, "start_date": start.strftime("%Y%m%d"),
                            "end_date": end.strftime("%Y%m%d")}, daily_frames),
            ("fund_div", {"ts_code": symbol}, dividend_frames),
        ):
            for attempt in range(3):
                try:
                    frame = connector.query_raw(api, **params)
                    break
                except Exception:
                    if attempt == 2:
                        raise RuntimeError(f"ETF {api} request failed for {symbol}") from None
                    time.sleep(attempt + 1)
            snapshot = store.write(source="tushare", table=api, frame=frame, parameters=params)
            paths.append(str(snapshot.data_path))
            if not frame.is_empty():
                frames.append(frame)
            time.sleep(0.35)
        print(f"Fetched {symbol}", flush=True)
    daily = pl.concat(daily_frames, how="diagonal_relaxed")
    dividends = (pl.concat(dividend_frames, how="diagonal_relaxed")
                 if dividend_frames else pl.DataFrame())
    candidate = build_prices(daily, dividends)
    quality = validate_research_prices(candidate, expected_symbols=set(symbols), expected_dates=dates)
    if not quality.passed or quality.rows != quality.expected_rows:
        raise ValueError(f"Incomplete ETF prices: {quality}")
    incoming, checks = join_seam(candidate, old)
    bars = Bar1dSchema.validate(TushareBarMapper().map(daily.with_columns(
        pl.col("ts_code").alias("_request_symbol"),
        pl.col("ts_code").str.split(".").list.last().alias("_market"),
    )))
    incoming_bars = bars.join(bar_latest, on="symbol").filter(
        pl.col("trade_date") > pl.col("last_bar")
    ).drop("last_bar")
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = artifact_root / "data_quality" / "etf_refresh" / stamp
    output.mkdir(parents=True, exist_ok=False)
    # Save the anchor observations and incoming prices so the source switch is reproducible.
    old.filter(pl.col("trade_date") >= start).write_parquet(output / "old_overlap.parquet")
    incoming.write_parquet(output / "new_prices.parquet")
    incoming_bars.write_parquet(output / "new_bars.parquet")
    summary = {
        "symbols": len(symbols), "previous_date": str(last), "latest_date": str(end),
        "new_rows": incoming.height, "new_dates": incoming["trade_date"].n_unique(),
        "new_bar_rows": incoming_bars.height,
        "overlap_checks": checks, "raw_paths": paths,
        "formula": "TR[t] = TR[t-1] * (close[t] + cash_dividend[t]) / close[t-1]",
        "artifact_path": str(output),
    }
    CleanResearchPriceStore(root).upsert(incoming)
    CleanBarStore(bar_root).upsert(incoming_bars)
    (output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--end", required=True, type=dt.date.fromisoformat)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--artifact-root", type=Path, default=Path("artifacts"))
    parser.add_argument("--config", type=Path,
                        default=Path("configs/research/m2_s2_volatility_target.toml"))
    args = parser.parse_args()
    print(json.dumps(refresh(end=args.end, data_root=args.data_root,
                             artifact_root=args.artifact_root, config=args.config), indent=2))


if __name__ == "__main__":
    main()
