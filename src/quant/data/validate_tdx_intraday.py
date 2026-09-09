"""Build concise quality and cross-source checks for an imported TongdaXin snapshot."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import tomllib
from pathlib import Path
from typing import Any, cast

import polars as pl

from quant.data.tdx_intraday import decode_daily_payload


def _daily(frame: pl.DataFrame, prefix: str) -> pl.DataFrame:
    return frame.sort("symbol", "bar_start").group_by("symbol", "trade_date").agg(
        pl.col("close").last().alias(f"{prefix}_close"),
        pl.col("volume").sum().alias(f"{prefix}_volume"),
        pl.col("amount").sum().alias(f"{prefix}_amount"),
        pl.len().alias(f"{prefix}_bars"),
        pl.col("session_complete").all().alias(f"{prefix}_session_complete"),
    )


def compare_daily_sources(tdx: pl.DataFrame, other: pl.DataFrame) -> pl.DataFrame:
    """Compare overlapping symbol-days while keeping supplier values visible."""
    joined = _daily(tdx, "tdx").join(
        _daily(other, "other"), on=["symbol", "trade_date"], how="inner", validate="1:1"
    )
    return joined.with_columns(
        (pl.col("tdx_close") - pl.col("other_close")).abs().alias("close_abs_error"),
        ((pl.col("tdx_volume") - pl.col("other_volume")).abs() / pl.col("other_volume"))
        .fill_nan(None)
        .alias("volume_rel_error"),
        ((pl.col("tdx_amount") - pl.col("other_amount")).abs() / pl.col("other_amount"))
        .fill_nan(None)
        .alias("amount_rel_error"),
    ).sort("symbol", "trade_date")


def compare_intraday_to_daily(tdx: pl.DataFrame, daily: pl.DataFrame) -> pl.DataFrame:
    """Compare intraday daily aggregates with the project's Tushare daily bars."""
    reference = daily.select(
        "symbol",
        "trade_date",
        pl.col("close").alias("other_close"),
        pl.col("volume").alias("other_volume"),
        pl.col("amount").alias("other_amount"),
    )
    joined = _daily(tdx, "tdx").join(
        reference, on=["symbol", "trade_date"], how="inner", validate="1:1"
    )
    return joined.with_columns(
        (pl.col("tdx_close") - pl.col("other_close")).abs().alias("close_abs_error"),
        ((pl.col("tdx_volume") - pl.col("other_volume")).abs() / pl.col("other_volume"))
        .fill_nan(None)
        .alias("volume_rel_error"),
        ((pl.col("tdx_amount") - pl.col("other_amount")).abs() / pl.col("other_amount"))
        .fill_nan(None)
        .alias("amount_rel_error"),
    ).sort("symbol", "trade_date")


def _read_if_possible(path: Path) -> pl.DataFrame | None:
    try:
        return pl.read_parquet(path)
    except (FileNotFoundError, OSError, pl.exceptions.PolarsError):
        return None


def _concat_or_empty(frames: list[pl.DataFrame]) -> pl.DataFrame:
    return pl.concat(frames, how="diagonal_relaxed") if frames else pl.DataFrame()


def _cross_source(data_root: Path, symbols: list[str]) -> tuple[pl.DataFrame, list[str]]:
    tdx_frames: list[pl.DataFrame] = []
    other_frames: list[pl.DataFrame] = []
    unreadable: list[str] = []
    for symbol in symbols:
        relative = Path(f"symbol={symbol}") / "data.parquet"
        tdx_path = data_root / "clean/bar_intraday/freq=5m/source=tdx" / relative
        other_path = data_root / "clean/bar_intraday/freq=5m/source=baostock" / relative
        if not tdx_path.is_file() or not other_path.is_file():
            continue
        tdx = _read_if_possible(tdx_path)
        other = _read_if_possible(other_path)
        if tdx is None or other is None:
            unreadable.append(symbol)
            continue
        tdx_frames.append(tdx)
        other_frames.append(other)
    if not tdx_frames:
        return pl.DataFrame(), unreadable
    return compare_daily_sources(
        _concat_or_empty(tdx_frames), _concat_or_empty(other_frames)
    ), unreadable


def _cross_tushare(data_root: Path, symbols: list[str]) -> pl.DataFrame:
    from quant.data.refresh_stocks import read_stock_data

    frames = []
    for symbol in symbols:
        frame = _read_if_possible(
            data_root
            / "clean/bar_intraday/freq=5m/source=tdx"
            / f"symbol={symbol}"
            / "data.parquet"
        )
        if frame is not None:
            frames.append(frame)
    tdx = _concat_or_empty(frames)
    if tdx.is_empty():
        return pl.DataFrame()
    start = cast(dt.date, tdx["trade_date"].min())
    end = cast(dt.date, tdx["trade_date"].max())
    daily = read_stock_data(
        data_root=data_root,
        config=Path("configs/data/refresh.toml"),
        table="bar_1d",
        start=start,
        end=end,
        symbols=symbols,
    )
    return compare_intraday_to_daily(tdx, daily)


def _frequency_daily(data_root: Path, symbols: list[str]) -> pl.DataFrame:
    one_frames: list[pl.DataFrame] = []
    five_frames: list[pl.DataFrame] = []
    for symbol in symbols:
        relative = Path(f"symbol={symbol}") / "data.parquet"
        one = _read_if_possible(data_root / "clean/bar_intraday/freq=1m/source=tdx" / relative)
        five = _read_if_possible(data_root / "clean/bar_intraday/freq=5m/source=tdx" / relative)
        if one is not None and five is not None:
            one_frames.append(one)
            five_frames.append(five)
    if not one_frames:
        return pl.DataFrame()
    return compare_daily_sources(
        _concat_or_empty(one_frames), _concat_or_empty(five_frames)
    ).rename({name: name.replace("other_", "five_minute_").replace("tdx_", "one_minute_")
              for name in compare_daily_sources(
                  one_frames[0], five_frames[0]
              ).columns if name.startswith(("other_", "tdx_"))})


def _describe_comparison(frame: pl.DataFrame) -> dict[str, Any]:
    if frame.is_empty():
        return {"symbol_days": 0, "symbols": 0}
    return {
        "symbol_days": frame.height,
        "symbols": frame["symbol"].n_unique(),
        "first_date": str(frame["trade_date"].min()),
        "last_date": str(frame["trade_date"].max()),
        "close_exact_rate": frame.select((pl.col("close_abs_error") <= 1e-6).mean()).item(),
        "close_within_0_01_rate": frame.select(
            (pl.col("close_abs_error") <= 0.010001).mean()
        ).item(),
        "close_max_abs_error": frame["close_abs_error"].max(),
        "volume_rel_error_median": frame["volume_rel_error"].median(),
        "volume_rel_error_p95": frame["volume_rel_error"].quantile(0.95),
        "amount_rel_error_median": frame["amount_rel_error"].median(),
        "amount_rel_error_p95": frame["amount_rel_error"].quantile(0.95),
    }


def _daily_samples(tdx_root: Path, data_root: Path) -> pl.DataFrame:
    rows: list[dict[str, Any]] = []
    for symbol in ("000001.SZ", "600000.SH", "518880.SH"):
        market, code = symbol[-2:].lower(), symbol[:6]
        day_path = tdx_root / market / "lday" / f"{market}{code}.day"
        minute_path = (
            data_root
            / "clean/bar_intraday/freq=5m/source=tdx"
            / f"symbol={symbol}"
            / "data.parquet"
        )
        daily, tail = decode_daily_payload(day_path.read_bytes())
        minute = pl.read_parquet(minute_path)
        overlap = set(daily["date"]) & {
            int(value.strftime("%Y%m%d")) for value in minute["trade_date"].to_list()
        }
        if not overlap:
            continue
        date_value = max(overlap)
        date = dt.datetime.strptime(str(date_value), "%Y%m%d").date()
        day_row = daily.filter(pl.col("date") == date_value).row(-1, named=True)
        intraday = minute.filter(pl.col("trade_date") == date).sort("bar_start")
        minute_close = intraday["close"][-1]
        price_scale = min((100, 1000), key=lambda scale: abs(day_row["close_raw"] / scale - minute_close))
        rows.append(
            {
                "symbol": symbol,
                "trade_date": date,
                "daily_price_scale": price_scale,
                "minute_close": minute_close,
                "daily_close": day_row["close_raw"] / price_scale,
                "minute_volume": intraday["volume"].sum(),
                "daily_volume": day_row["volume"],
                "minute_amount": intraday["amount"].sum(),
                "daily_amount": day_row["amount"],
                "day_trailing_bytes": tail,
            }
        )
    return pl.DataFrame(rows)


def validate_import(
    *, tdx_root: Path, data_root: Path, import_artifacts: Path, output_root: Path,
    config: Path = Path("configs/universe/stock_top800_5m.toml"),
) -> dict[str, Any]:
    inventory = pl.read_csv(import_artifacts / "file_inventory.csv")
    quality = inventory.group_by("market", "frequency").agg(
        pl.len().alias("files"),
        pl.col("records").sum(),
        pl.col("valid_rows").sum(),
        pl.col("invalid_date_rows").sum(),
        pl.col("invalid_time_rows").sum(),
        pl.col("invalid_ohlcv_rows").sum(),
        pl.col("duplicate_rows").sum(),
        pl.col("trailing_bytes").sum(),
        pl.col("incomplete_days").sum(),
        pl.col("missing_bars").sum(),
        pl.col("first_date").min(),
        pl.col("last_date").max(),
    ).sort("frequency", "market")
    symbols: list[str] = tomllib.loads(config.read_text(encoding="utf-8"))["symbols"]
    b8 = inventory.filter(pl.col("symbol").is_in(symbols)).select(
        "symbol", "frequency", "valid_rows", "first_date", "last_date", "incomplete_days",
        "missing_bars",
    )
    cross, unreadable = _cross_source(data_root, symbols)
    tushare = _cross_tushare(data_root, symbols)
    frequency = _frequency_daily(data_root, symbols)
    samples = _daily_samples(tdx_root, data_root)

    timestamp = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y%m%dT%H%M%S%f")
    output = output_root / timestamp
    output.mkdir(parents=True, exist_ok=False)
    quality.write_csv(output / "quality_by_market_frequency.csv")
    b8.write_csv(output / "b8_coverage.csv")
    if not cross.is_empty():
        cross.write_csv(output / "tdx_vs_baostock_daily.csv")
    if not tushare.is_empty():
        tushare.write_csv(output / "tdx_vs_tushare_daily.csv")
    if not frequency.is_empty():
        frequency.write_csv(output / "tdx_1m_vs_5m_daily.csv")
    samples.write_csv(output / "tdx_minute_vs_day_samples.csv")
    summary = {
        "import_artifacts": str(import_artifacts),
        "output": str(output),
        "b8_symbols": len(symbols),
        "b8_with_1m": b8.filter(pl.col("frequency") == "1m")["symbol"].n_unique(),
        "b8_with_5m": b8.filter(pl.col("frequency") == "5m")["symbol"].n_unique(),
        "tdx_vs_baostock": _describe_comparison(cross),
        "baostock_files_unreadable_during_snapshot": unreadable,
        "tdx_vs_tushare": _describe_comparison(tushare),
        "tdx_1m_vs_5m": _describe_comparison(frequency.rename({
            name: name.replace("one_minute_", "tdx_").replace("five_minute_", "other_")
            for name in frequency.columns
            if name.startswith(("one_minute_", "five_minute_"))
        })) if not frequency.is_empty() else {"symbol_days": 0, "symbols": 0},
        "daily_samples": samples.to_dicts(),
    }
    (output / "validation_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tdx-root", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--import-artifacts", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(validate_import(
        tdx_root=args.tdx_root,
        data_root=args.data_root,
        import_artifacts=args.import_artifacts,
        output_root=args.output_root,
    ), ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
