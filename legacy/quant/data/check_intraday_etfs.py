"""Capture BaoStock ETF bars and compare their overlap with Yahoo five-minute data."""

import argparse
import datetime as dt
import json
import tomllib
from pathlib import Path

import polars as pl

from quant.data.connectors.baostock import BaostockConnector
from quant.data.intraday import _directory, add_session_quality, merge_bars
from quant.data.intraday_bars import normalize_baostock
from quant.data.storage import RawStore


def check(*, data_root: Path, end: dt.date, output: Path) -> pl.DataFrame:
    output.mkdir(parents=True, exist_ok=False)
    members = tomllib.loads(Path("configs/universe/t0_etf_pool_v1.toml").read_text(encoding="utf-8"))["members"]
    rows = []
    for member in members:
        symbol = member["symbol"]
        parameters = {"start": "2026-01-01", "end": str(end), "frequency": "5m"}
        cached = [p.with_suffix(".parquet") for p in sorted(
            (data_root / "raw/baostock_intraday" / symbol).glob("date=*/*.json"))
            if json.loads(p.read_text())["parameters"] == parameters]
        if cached:
            raw_path = cached[-1]
            raw = pl.read_parquet(raw_path)
        else:
            raw = BaostockConnector().fetch_intraday(symbol, dt.date(2026, 1, 1), end)
            raw_path = RawStore(data_root / "raw").write(
                source="baostock_intraday", table=symbol, frame=raw, parameters=parameters).data_path
        bao = add_session_quality(normalize_baostock(raw, symbol), data_root, "5m", symbol)
        merge_bars(_directory(data_root, "baostock", symbol, "5m"), bao)
        yahoo = pl.read_parquet(_directory(data_root, "yahoo", symbol, "5m") / "data.parquet")
        paired = bao.join(yahoo, on=["symbol", "bar_start"], suffix="_yahoo").with_columns(
            pl.max_horizontal([(pl.col(c) - pl.col(c + "_yahoo")).abs()
                               for c in ("open", "high", "low", "close")]).alias("max_ohlc_difference"),
            (pl.col("volume_yahoo") / pl.col("volume").replace(0, None)).alias("volume_ratio"),
        )
        paired.write_parquet(output / f"{symbol}.parquet")
        if paired.is_empty():
            raise ValueError(f"No overlap for {symbol}")
        row = {"symbol": symbol, "bao_rows": bao.height, "yahoo_rows": yahoo.height,
               "matched_rows": paired.height, "first_date": str(paired["trade_date"].min()),
               "last_date": str(paired["trade_date"].max()),
               "within_one_tick_fraction": paired.select((pl.col("max_ohlc_difference") <= .00101).mean()).item(),
               "max_ohlc_difference": paired["max_ohlc_difference"].max(),
               "median_volume_ratio_yahoo_bao": paired["volume_ratio"].median(),
               "raw": str(raw_path)}
        rows.append(row)
        print(json.dumps(row), flush=True)
    result = pl.DataFrame(rows)
    result.write_csv(output / "comparison.csv")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--to", type=dt.date.fromisoformat, required=True)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    check(data_root=args.data_root, end=args.to, output=args.output)


if __name__ == "__main__":
    main()
