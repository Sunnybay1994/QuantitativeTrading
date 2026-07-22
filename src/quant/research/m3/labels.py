"""Independent label build: next-open to h-close excess vs total-return benchmark."""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Sequence
from dataclasses import dataclass

import polars as pl

from quant.domain import BenchmarkBar1dSchema, ForwardReturnLabelSchema

_EMPTY_LABELS = pl.DataFrame(
    schema={
        "as_of": pl.Date,
        "symbol": pl.Utf8,
        "benchmark": pl.Utf8,
        "horizon_sessions": pl.Int64,
        "return_start_date": pl.Date,
        "return_end_date": pl.Date,
        "available_as_of": pl.Date,
        "raw_return": pl.Float64,
        "benchmark_return": pl.Float64,
        "relative_return": pl.Float64,
        "label_version": pl.Utf8,
    }
)

_EMPTY_DIAGNOSTICS = pl.DataFrame(
    schema={
        "as_of": pl.Date,
        "horizon_sessions": pl.Int64,
        "reason": pl.Utf8,
        "sample_count": pl.Int64,
    }
)


@dataclass(frozen=True)
class LabelBuildResult:
    labels: pl.DataFrame
    diagnostics: pl.DataFrame


def compute_forward_relative_labels(
    *,
    bars: pl.DataFrame,
    benchmark_bars: pl.DataFrame,
    eligible_keys: pl.DataFrame,
    calendars: pl.DataFrame,
    horizons: Sequence[int],
    benchmark: str,
    label_version: str,
) -> LabelBuildResult:
    """Build forward relative labels over PIT eligible keys only."""
    if not horizons:
        raise ValueError("horizons 不得为空")
    if any(h <= 0 for h in horizons):
        raise ValueError("horizon 必须为正整数")

    keys = _validate_eligible_keys(eligible_keys)
    _reject_duplicate_key(bars, ["symbol", "trade_date"], "bars")
    bench = _validate_benchmark_bars(benchmark_bars, benchmark)
    _reject_duplicate_key(bench, ["benchmark", "trade_date"], "benchmark_bars")

    open_dates = (
        calendars.filter((pl.col("market") == "SH") & pl.col("is_open"))
        .sort("date")
        .get_column("date")
        .to_list()
    )
    date_to_idx = {date: idx for idx, date in enumerate(open_dates)}
    stock_lookup = _stock_lookup(bars)
    bench_lookup = _bench_lookup(bench)

    label_rows: list[dict[str, object]] = []
    diag_counts: dict[tuple[dt.date, int, str], int] = {}

    for key in keys.iter_rows(named=True):
        as_of: dt.date = key["as_of"]
        symbol: str = key["symbol"]
        as_of_idx = date_to_idx.get(as_of)
        for horizon in horizons:
            h = int(horizon)
            reason = _first_failure_reason(
                as_of_idx=as_of_idx,
                horizon=h,
                n_sessions=len(open_dates),
                symbol=symbol,
                open_dates=open_dates,
                stock_lookup=stock_lookup,
                bench_lookup=bench_lookup,
            )
            if reason is not None:
                diag_key = (as_of, h, reason)
                diag_counts[diag_key] = diag_counts.get(diag_key, 0) + 1
                continue

            assert as_of_idx is not None
            entry_date = open_dates[as_of_idx + 1]
            exit_date = open_dates[as_of_idx + h]
            entry = stock_lookup[(symbol, entry_date)]
            exit_bar = stock_lookup[(symbol, exit_date)]
            bench_entry = bench_lookup[entry_date]
            bench_exit = bench_lookup[exit_date]
            raw_return = (
                exit_bar["close"] * exit_bar["adj_factor"]
            ) / (entry["open"] * entry["adj_factor"]) - 1.0
            benchmark_return = bench_exit["close"] / bench_entry["open"] - 1.0
            label_rows.append(
                {
                    "as_of": as_of,
                    "symbol": symbol,
                    "benchmark": benchmark,
                    "horizon_sessions": h,
                    "return_start_date": entry_date,
                    "return_end_date": exit_date,
                    "available_as_of": exit_date,
                    "raw_return": float(raw_return),
                    "benchmark_return": float(benchmark_return),
                    "relative_return": float(raw_return - benchmark_return),
                    "label_version": label_version,
                }
            )

    raw_labels = (
        pl.DataFrame(label_rows, schema=_EMPTY_LABELS.schema)
        if label_rows
        else _EMPTY_LABELS
    )
    labels = ForwardReturnLabelSchema.validate(raw_labels).sort(
        ["as_of", "horizon_sessions", "symbol"]
    )

    if diag_counts:
        diagnostics = pl.DataFrame(
            [
                {
                    "as_of": as_of,
                    "horizon_sessions": horizon,
                    "reason": reason,
                    "sample_count": count,
                }
                for (as_of, horizon, reason), count in diag_counts.items()
            ],
            schema=_EMPTY_DIAGNOSTICS.schema,
        ).sort(["as_of", "horizon_sessions", "reason"])
    else:
        diagnostics = _EMPTY_DIAGNOSTICS

    expected = keys.height * len(horizons)
    observed = labels.height + int(diagnostics.get_column("sample_count").sum() or 0)
    if expected != observed:
        raise RuntimeError(
            f"label conservation broken: eligible*horizons={expected} "
            f"labels+diagnostics={observed}"
        )

    return LabelBuildResult(labels=labels, diagnostics=diagnostics)


def _validate_eligible_keys(eligible_keys: pl.DataFrame) -> pl.DataFrame:
    required = {"as_of", "symbol"}
    missing = required - set(eligible_keys.columns)
    if missing:
        raise ValueError(f"eligible_keys 缺少列: {sorted(missing)}")
    keys = eligible_keys.select("as_of", "symbol")
    if keys.is_empty():
        raise ValueError("eligible_keys 不得为空")
    dup = keys.group_by("as_of", "symbol").len().filter(pl.col("len") > 1)
    if not dup.is_empty():
        raise ValueError("eligible_keys 存在重复 (as_of, symbol)")
    return keys.sort(["as_of", "symbol"])


def _validate_benchmark_bars(benchmark_bars: pl.DataFrame, benchmark: str) -> pl.DataFrame:
    frame = BenchmarkBar1dSchema.validate(benchmark_bars)
    codes = set(frame.get_column("benchmark").unique().to_list())
    if codes != {benchmark}:
        raise ValueError(
            f"benchmark_bars 必须只含显式基准 {benchmark!r}，实际为 {sorted(codes)!r}"
        )
    return frame


def _reject_duplicate_key(frame: pl.DataFrame, columns: list[str], name: str) -> None:
    dup = frame.group_by(columns).len().filter(pl.col("len") > 1)
    if not dup.is_empty():
        key = ", ".join(columns)
        raise ValueError(f"{name} 存在重复 ({key})")


def _factor_invalid(value: float | None) -> bool:
    if value is None:
        return True
    number = float(value)
    return (not math.isfinite(number)) or number <= 0.0


def _first_failure_reason(
    *,
    as_of_idx: int | None,
    horizon: int,
    n_sessions: int,
    symbol: str,
    open_dates: list[dt.date],
    stock_lookup: dict[tuple[str, dt.date], dict[str, float]],
    bench_lookup: dict[dt.date, dict[str, float]],
) -> str | None:
    if as_of_idx is None or as_of_idx + 1 >= n_sessions or as_of_idx + horizon >= n_sessions:
        return "TAIL_INCOMPLETE"
    entry_date = open_dates[as_of_idx + 1]
    exit_date = open_dates[as_of_idx + horizon]
    if entry_date not in bench_lookup:
        return "BENCHMARK_ENTRY_MISSING"
    if exit_date not in bench_lookup:
        return "BENCHMARK_EXIT_MISSING"
    entry = stock_lookup.get((symbol, entry_date))
    if entry is None:
        return "ASSET_ENTRY_BAR_MISSING"
    exit_bar = stock_lookup.get((symbol, exit_date))
    if exit_bar is None:
        return "ASSET_EXIT_BAR_MISSING"
    if _factor_invalid(entry["adj_factor"]):
        return "ASSET_ENTRY_FACTOR_INVALID"
    if _factor_invalid(exit_bar["adj_factor"]):
        return "ASSET_EXIT_FACTOR_INVALID"
    return None


def _stock_lookup(
    frame: pl.DataFrame,
) -> dict[tuple[str, dt.date], dict[str, float]]:
    lookup: dict[tuple[str, dt.date], dict[str, float]] = {}
    cols = ["symbol", "trade_date", "open", "close", "adj_factor"]
    for row in frame.select(cols).iter_rows(named=True):
        factor = row["adj_factor"]
        lookup[(row["symbol"], row["trade_date"])] = {
            "open": float(row["open"]),
            "close": float(row["close"]),
            "adj_factor": float("nan") if factor is None else float(factor),
        }
    return lookup


def _bench_lookup(frame: pl.DataFrame) -> dict[dt.date, dict[str, float]]:
    lookup: dict[dt.date, dict[str, float]] = {}
    for row in frame.select("trade_date", "open", "close").iter_rows(named=True):
        lookup[row["trade_date"]] = {
            "open": float(row["open"]),
            "close": float(row["close"]),
        }
    return lookup
