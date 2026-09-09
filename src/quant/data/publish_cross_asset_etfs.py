"""Publish stock, Treasury-bond and gold ETF daily research inputs from saved raw."""

import argparse
import datetime as dt
import json
from pathlib import Path

import polars as pl

from quant.data.etf_paper_inputs import read_etf_dividends
from quant.data.etf_research_inputs import read_etf_research_inputs
from quant.data.mappers import TushareBarMapper
from quant.data.refresh_etf_prices import build_prices
from quant.data.research_price import validate_research_prices
from quant.domain import Bar1dSchema, InstrumentSchema

SYMBOLS = ("510300.SH", "511010.SH", "518880.SH")


def publish(*, data_root: Path, capture: Path, name: str, start: dt.date, end: dt.date) -> dict:
    if not name or Path(name).name != name or name in (".", "..") or start > end:
        raise ValueError("Invalid cross-asset dataset request")
    output = data_root / "clean/etf_cross_asset" / name
    if output.exists():
        raise FileExistsError(output)
    entries = json.loads(capture.read_text(encoding="utf-8"))
    captured = {(r["symbol"], r["dataset"]): pl.read_parquet(r["raw_path"]) for r in entries}
    bars, prices, calendar, instruments = read_etf_research_inputs(data_root, [SYMBOLS[0]], start, end)
    bar_frames, price_frames, instrument_frames = [bars], [prices], [instruments]
    for symbol in SYMBOLS[1:]:
        daily = captured[symbol, "fund_daily"].filter(
            pl.col("trade_date").str.to_date("%Y%m%d").is_between(start, end))
        basic = captured[symbol, "fund_basic"]
        dividend = captured[symbol, "fund_div"]
        if (set(daily["ts_code"]) != {symbol} or basic.height != 1
            or basic["ts_code"][0] != symbol
            or (not dividend.is_empty() and set(dividend["ts_code"]) != {symbol})):
            raise ValueError(f"Cross-asset raw scope differs: {symbol}")
        mapped = Bar1dSchema.validate(TushareBarMapper().map(daily.with_columns(
            pl.col("ts_code").alias("_request_symbol"), pl.lit("SH").alias("_market"))))
        dates = calendar.filter((pl.col("market") == "SH") & pl.col("is_open")
            & pl.col("date").is_between(start, end))["date"].to_list()
        if mapped.height != len(dates) or set(mapped["trade_date"]) != set(dates):
            raise ValueError(f"Incomplete cross-asset bars: {symbol}")
        price = build_prices(daily, dividend)
        quality = validate_research_prices(price, expected_symbols={symbol}, expected_dates=set(dates))
        if not quality.passed or quality.rows != quality.expected_rows:
            raise ValueError(f"Incomplete cross-asset total-return prices: {symbol}")
        instrument = InstrumentSchema.validate(basic.select(
            pl.col("ts_code").alias("symbol"), pl.lit("SH").alias("market"), "name",
            pl.lit("ETF").alias("instrument_type"), pl.lit("CNY").alias("currency"),
            pl.col("list_date").str.to_date("%Y%m%d").alias("list_date"),
            pl.lit(None, dtype=pl.Date).alias("delist_date"),
            pl.lit(100, dtype=pl.Int64).alias("board_lot"), pl.lit("LISTED").alias("status"),
        ))
        if instrument["list_date"][0] > start:
            raise ValueError(f"ETF listed after requested start: {symbol}")
        bar_frames.append(mapped)
        price_frames.append(price)
        instrument_frames.append(instrument)
    dividends = read_etf_dividends(data_root, list(SYMBOLS), start)
    frames = {"bars": pl.concat(bar_frames, how="diagonal_relaxed").sort("trade_date", "symbol"),
              "prices": pl.concat(price_frames, how="diagonal_relaxed").sort("trade_date", "symbol"),
              "instruments": pl.concat(instrument_frames, how="diagonal_relaxed").sort("symbol"),
              "calendar": calendar, "dividends": dividends}
    output.mkdir(parents=True, exist_ok=False)
    for label, frame in frames.items():
        frame.write_parquet(output / f"{label}.parquet")
    summary = {"symbols": list(SYMBOLS), "start": str(start), "end": str(end),
               "rows": {label: frame.height for label, frame in frames.items()},
               "new_etf_raw_capture": str(capture), "stock_etf_input": "existing ETF research panel",
               "total_return": "TR[t] = TR[t-1] * (close[t] + cash_dividend[t]) / close[t-1]"}
    (output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def read_cross_asset_etfs(data_root: Path, name: str) -> dict[str, pl.DataFrame]:
    if not name or Path(name).name != name or name in (".", ".."):
        raise ValueError("Invalid cross-asset dataset name")
    root = data_root / "clean/etf_cross_asset" / name
    if not (root / "summary.json").is_file():
        raise ValueError("Cross-asset dataset publication is incomplete")
    return {label: pl.read_parquet(root / f"{label}.parquet")
            for label in ("bars", "prices", "instruments", "calendar", "dividends")}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--start", type=dt.date.fromisoformat, required=True)
    parser.add_argument("--end", type=dt.date.fromisoformat, required=True)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    args = parser.parse_args()
    print(json.dumps(publish(data_root=args.data_root, capture=args.capture, name=args.name,
                             start=args.start, end=args.end)))


if __name__ == "__main__":
    main()
