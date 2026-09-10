"""Validate imported TongdaXin daily bars against project data and minute closes."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import tomllib
from pathlib import Path
from typing import Any

import polars as pl

from quant.data.refresh_stocks import read_stock_data


def compare_daily(tdx: pl.DataFrame, reference: pl.DataFrame) -> pl.DataFrame:
    keys = ["symbol", "trade_date"]
    left = tdx.select(*keys, *[
        pl.col(name).alias(f"tdx_{name}") for name in ("close", "volume", "amount")
    ])
    right = reference.select(*keys, *[
        pl.col(name).alias(f"reference_{name}") for name in ("close", "volume", "amount")
    ])
    return left.join(right, on=keys, how="inner", validate="1:1").with_columns(
        (pl.col("tdx_close") - pl.col("reference_close")).abs().alias("close_abs_error"),
        ((pl.col("tdx_volume") - pl.col("reference_volume")).abs()
         / pl.col("reference_volume")).fill_nan(None).alias("volume_rel_error"),
        ((pl.col("tdx_amount") - pl.col("reference_amount")).abs()
         / pl.col("reference_amount")).fill_nan(None).alias("amount_rel_error"),
    ).sort(*keys)


def compare_minute_close(daily: pl.DataFrame, minute: pl.DataFrame) -> pl.DataFrame:
    minute_last = minute.sort("symbol", "bar_start").group_by("symbol", "trade_date").agg(
        pl.col("close").last().alias("minute_close")
    )
    return daily.select("symbol", "trade_date", pl.col("close").alias("daily_close")).join(
        minute_last, on=["symbol", "trade_date"], how="inner", validate="1:1"
    ).with_columns(
        (pl.col("daily_close") - pl.col("minute_close")).abs().alias("close_abs_error")
    ).sort("symbol", "trade_date")


def _read_tdx(data_root: Path, symbols: list[str], start: dt.date, end: dt.date) -> pl.DataFrame:
    frames = []
    for symbol in symbols:
        path = (
            data_root / "clean/bar_1d_tdx/source=tdx"
            / f"market={symbol[-2:]}" / f"symbol={symbol}" / "data.parquet"
        )
        if path.is_file():
            frames.append(
                pl.scan_parquet(path).filter(pl.col("trade_date").is_between(start, end)).collect()
            )
    return pl.concat(frames, how="vertical_relaxed") if frames else pl.DataFrame()


def _read_minutes(data_root: Path, symbols: list[str], frequency: str) -> pl.DataFrame:
    frames = []
    for symbol in symbols:
        path = (
            data_root / f"clean/bar_intraday/freq={frequency}/source=tdx"
            / f"symbol={symbol}" / "data.parquet"
        )
        if path.is_file():
            frames.append(pl.read_parquet(path))
    return pl.concat(frames, how="diagonal_relaxed") if frames else pl.DataFrame()


def _describe(frame: pl.DataFrame) -> dict[str, Any]:
    if frame.is_empty():
        return {"rows": 0, "symbols": 0}
    return {
        "rows": frame.height,
        "symbols": frame["symbol"].n_unique(),
        "first_date": str(frame["trade_date"].min()),
        "last_date": str(frame["trade_date"].max()),
        "close_within_0_001_rate": frame.select(
            (pl.col("close_abs_error") <= 0.001001).mean()
        ).item(),
        "close_max_abs_error": frame["close_abs_error"].max(),
        "volume_rel_error_median": frame["volume_rel_error"].median()
        if "volume_rel_error" in frame.columns else None,
        "volume_rel_error_p95": frame["volume_rel_error"].quantile(0.95)
        if "volume_rel_error" in frame.columns else None,
        "amount_rel_error_median": frame["amount_rel_error"].median()
        if "amount_rel_error" in frame.columns else None,
        "amount_rel_error_p95": frame["amount_rel_error"].quantile(0.95)
        if "amount_rel_error" in frame.columns else None,
    }


def validate(
    *, data_root: Path, import_artifacts: Path, output_root: Path,
    start: dt.date = dt.date(2024, 9, 1), end: dt.date = dt.date(2026, 9, 9),
) -> dict[str, Any]:
    inventory = pl.read_csv(import_artifacts / "file_inventory.csv")
    b8: list[str] = tomllib.loads(
        Path("configs/universe/stock_top800_5m.toml").read_text(encoding="utf-8")
    )["symbols"]
    tdx_stocks = _read_tdx(data_root, b8, start, end)
    tushare_stocks = read_stock_data(
        data_root=data_root,
        config=Path("configs/data/refresh.toml"),
        table="bar_1d",
        start=start,
        end=end,
        symbols=b8,
    )
    stock_comparison = compare_daily(tdx_stocks, tushare_stocks)

    etf_glob = str(data_root / "clean/bar_1d/date=*/data.parquet")
    etf_symbols: list[str] = []
    for market in ("SH", "SZ"):
        instruments = pl.read_parquet(
            data_root / f"clean/instrument/market={market}/data.parquet"
        )
        etf_symbols.extend(
            instruments.filter(pl.col("instrument_type") == "ETF")["symbol"].to_list()
        )
    tushare_etfs = pl.scan_parquet(etf_glob).filter(
        pl.col("trade_date").is_between(start, end)
        & pl.col("symbol").is_in(etf_symbols)
        & (pl.col("source") == "tushare")
    ).collect().unique(subset=["symbol", "trade_date"], keep="last")
    etfs = tushare_etfs["symbol"].unique().sort().to_list()
    tdx_etfs = _read_tdx(data_root, etfs, start, end)
    etf_comparison = compare_daily(tdx_etfs, tushare_etfs)

    sample_symbols = b8 + etfs
    tdx_sample = pl.concat([tdx_stocks, tdx_etfs], how="vertical_relaxed")
    minute_1m = compare_minute_close(tdx_sample, _read_minutes(data_root, sample_symbols, "1m"))
    minute_5m = compare_minute_close(tdx_sample, _read_minutes(data_root, sample_symbols, "5m"))

    quality = inventory.group_by("market", "instrument_type").agg(
        pl.len().alias("files"),
        pl.col("records").sum(),
        pl.col("valid_rows").sum(),
        pl.col("invalid_date_rows").sum(),
        pl.col("invalid_ohlcv_rows").sum(),
        pl.col("duplicate_rows").sum(),
        pl.col("trailing_bytes").sum(),
        pl.col("first_date").min(),
        pl.col("last_date").max(),
    ).sort("market", "instrument_type")
    timestamp = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y%m%dT%H%M%S%f")
    output = output_root / timestamp
    output.mkdir(parents=True, exist_ok=False)
    quality.write_csv(output / "quality_by_market_type.csv")
    stock_comparison.write_csv(output / "tdx_vs_tushare_stocks.csv")
    etf_comparison.write_csv(output / "tdx_vs_tushare_etfs.csv")
    minute_1m.write_csv(output / "tdx_daily_vs_1m_close.csv")
    minute_5m.write_csv(output / "tdx_daily_vs_5m_close.csv")
    summary = {
        "import_artifacts": str(import_artifacts),
        "output": str(output),
        "tdx_vs_tushare_stocks": _describe(stock_comparison),
        "tdx_vs_tushare_etfs": _describe(etf_comparison),
        "tdx_daily_vs_1m_close": _describe(minute_1m),
        "tdx_daily_vs_5m_close": _describe(minute_5m),
    }
    (output / "validation_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--import-artifacts", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(validate(
        data_root=args.data_root,
        import_artifacts=args.import_artifacts,
        output_root=args.output_root,
    ), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
