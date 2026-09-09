"""Import local TongdaXin minute files into the project's intraday store.

TongdaXin ``.lc1`` and ``.lc5`` records are 32-byte little-endian records.  The
supplier timestamp is the bar end, matching the BaoStock convention already
used by :mod:`quant.data.intraday_bars`.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import struct
import tomllib
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

import polars as pl

from quant.data.intraday import merge_bars
from quant.data.intraday_bars import SCHEMA, validate_bars

_MINUTE_RECORD = struct.Struct("<Hhfffffii")
_DAILY_RECORD = struct.Struct("<IIIIIfII")
_MINUTE_FILE = re.compile(r"^(sh|sz|bj)([0-9]{6})[.](lc1|lc5)$")
_FREQUENCY = {"lc1": "1m", "lc5": "5m"}
_EXTENSION = {value: key for key, value in _FREQUENCY.items()}
_MARKET = {"sh": "SH", "sz": "SZ", "bj": "BJ"}
_EXPECTED_BARS = {"1m": 240, "5m": 48}
_RAW_COLUMNS = (
    "source_record",
    "packed_date",
    "minute",
    "open",
    "high",
    "low",
    "close",
    "amount",
    "volume",
    "reserved",
)


@dataclass(frozen=True)
class DecodeStats:
    records: int
    trailing_bytes: int
    valid_rows: int
    zero_placeholder_rows: int
    invalid_date_rows: int
    invalid_time_rows: int
    invalid_ohlcv_rows: int
    duplicate_rows: int
    incomplete_days: int
    missing_bars: int
    first_date: str | None
    last_date: str | None


@dataclass(frozen=True)
class ImportResult:
    symbol: str
    market: str
    frequency: str
    source_file: str
    source_bytes: int
    source_mtime_ns: int
    source_sha256: str
    raw_path: str
    raw_written: bool
    clean_changed_rows: int
    skipped_unchanged: bool
    records: int
    trailing_bytes: int
    valid_rows: int
    zero_placeholder_rows: int
    invalid_date_rows: int
    invalid_time_rows: int
    invalid_ohlcv_rows: int
    duplicate_rows: int
    incomplete_days: int
    missing_bars: int
    first_date: str | None
    last_date: str | None


def _unpack_date(value: int) -> tuple[int, int, int]:
    year = 2004 + value // 2048
    remainder = value % 2048
    return year, remainder // 100, remainder % 100


def _symbol_from_path(path: Path) -> tuple[str, str, str]:
    matched = _MINUTE_FILE.fullmatch(path.name.lower())
    if matched is None:
        raise ValueError(f"Invalid TongdaXin minute file name: {path.name}")
    market, code, extension = matched.groups()
    return f"{code}.{_MARKET[market]}", market, _FREQUENCY[extension]


def _scheduled_minute(expression: pl.Expr, frequency: str) -> pl.Expr:
    morning = expression.is_between(571, 690)
    afternoon = expression.is_between(781, 900)
    scheduled = morning | afternoon
    if frequency == "5m":
        scheduled &= expression.mod(5) == 0
    return scheduled


def decode_minute_payload(
    payload: bytes, *, symbol: str, frequency: str
) -> tuple[pl.DataFrame, pl.DataFrame, DecodeStats]:
    """Decode one immutable byte snapshot into raw records and clean bars."""
    if frequency not in _EXPECTED_BARS:
        raise ValueError(f"Unsupported TongdaXin frequency: {frequency}")
    complete_size = len(payload) - len(payload) % _MINUTE_RECORD.size
    rows = list(_MINUTE_RECORD.iter_unpack(payload[:complete_size]))
    raw = pl.DataFrame(rows, schema=_RAW_COLUMNS[1:], orient="row").with_row_index(
        "source_record"
    )
    if raw.is_empty():
        stats = DecodeStats(
            records=0,
            trailing_bytes=len(payload),
            valid_rows=0,
            zero_placeholder_rows=0,
            invalid_date_rows=0,
            invalid_time_rows=0,
            invalid_ohlcv_rows=0,
            duplicate_rows=0,
            incomplete_days=0,
            missing_bars=0,
            first_date=None,
            last_date=None,
        )
        return raw, pl.DataFrame(schema={**SCHEMA, "session_complete": pl.Boolean}), stats

    packed = pl.col("packed_date")
    year = 2004 + packed // 2048
    remainder = packed % 2048
    date_text = pl.concat_str(
        year.cast(pl.String),
        (remainder // 100).cast(pl.String).str.pad_start(2, "0"),
        (remainder % 100).cast(pl.String).str.pad_start(2, "0"),
    )
    dated = raw.with_columns(
        date_text.str.to_date("%Y%m%d", strict=False).alias("trade_date")
    )
    dated = dated.with_columns(
        (
            pl.col("trade_date").cast(pl.Datetime("us"))
            .dt.replace_time_zone("Asia/Shanghai")
            + pl.duration(minutes=pl.col("minute"))
        ).alias("bar_end")
    )
    zero_placeholder = pl.all_horizontal(
        [pl.col(name) == 0 for name in ("open", "high", "low", "close", "amount", "volume")]
    )
    valid_date = pl.col("trade_date").is_not_null() & year.is_between(2004, 2100)
    valid_time = _scheduled_minute(pl.col("minute"), frequency)
    valid_ohlcv = (
        pl.all_horizontal(
            [pl.col(name).is_finite() & (pl.col(name) > 0) for name in ("open", "high", "low", "close")]
        )
        & pl.col("amount").is_finite()
        & (pl.col("amount") >= 0)
        & (pl.col("volume") >= 0)
        & (pl.col("high") >= pl.max_horizontal("open", "close", "low"))
        & (pl.col("low") <= pl.min_horizontal("open", "close", "high"))
    )
    duplicate = dated.select("packed_date", "minute").is_duplicated()
    marked = dated.with_columns(
        zero_placeholder.alias("_zero_placeholder"),
        valid_date.alias("_valid_date"),
        valid_time.alias("_valid_time"),
        valid_ohlcv.alias("_valid_ohlcv"),
        pl.Series("_duplicate", duplicate),
    )
    minutes = int(frequency[:-1])
    clean = marked.filter(
        ~pl.col("_zero_placeholder")
        & pl.col("_valid_date")
        & pl.col("_valid_time")
        & pl.col("_valid_ohlcv")
        & ~pl.col("_duplicate")
    ).select(
        pl.lit(symbol).alias("symbol"),
        "trade_date",
        (pl.col("bar_end") - pl.duration(minutes=minutes)).alias("bar_start"),
        "bar_end",
        *[pl.col(name).cast(pl.Float64) for name in ("open", "high", "low", "close")],
        pl.col("volume").cast(pl.Float64),
        pl.col("amount").cast(pl.Float64),
        pl.lit("tdx").alias("source"),
    )
    expected = _EXPECTED_BARS[frequency]
    clean = clean.with_columns(
        (pl.len().over("trade_date") == expected).alias("session_complete")
    )
    validate_bars(clean)
    observed = clean.group_by("trade_date").len() if not clean.is_empty() else pl.DataFrame()
    incomplete_days = observed.filter(pl.col("len") != expected).height if observed.height else 0
    missing_bars = (
        int(observed.select((expected - pl.col("len")).clip(lower_bound=0).sum()).item())
        if observed.height
        else 0
    )
    stats = DecodeStats(
        records=raw.height,
        trailing_bytes=len(payload) - complete_size,
        valid_rows=clean.height,
        zero_placeholder_rows=marked.filter(pl.col("_zero_placeholder")).height,
        invalid_date_rows=marked.filter(~pl.col("_zero_placeholder") & ~pl.col("_valid_date")).height,
        invalid_time_rows=marked.filter(~pl.col("_zero_placeholder") & ~pl.col("_valid_time")).height,
        invalid_ohlcv_rows=marked.filter(~pl.col("_zero_placeholder") & ~pl.col("_valid_ohlcv")).height,
        duplicate_rows=int(duplicate.sum()),
        incomplete_days=incomplete_days,
        missing_bars=missing_bars,
        first_date=str(clean["trade_date"].min()) if not clean.is_empty() else None,
        last_date=str(clean["trade_date"].max()) if not clean.is_empty() else None,
    )
    return raw, clean, stats


def decode_daily_payload(payload: bytes) -> tuple[pl.DataFrame, int]:
    """Decode ``.day`` records for scaling/unit spot checks, without guessing price scale."""
    complete_size = len(payload) - len(payload) % _DAILY_RECORD.size
    rows = list(_DAILY_RECORD.iter_unpack(payload[:complete_size]))
    frame = pl.DataFrame(
        rows,
        schema=("date", "open_raw", "high_raw", "low_raw", "close_raw", "amount", "volume", "reserved"),
        orient="row",
    )
    return frame, len(payload) - complete_size


def _clean_directory(data_root: Path, symbol: str, frequency: str) -> Path:
    return (
        data_root
        / "clean"
        / "bar_intraday"
        / f"freq={frequency}"
        / "source=tdx"
        / f"symbol={symbol}"
    )


def _raw_path(data_root: Path, symbol: str, market: str, frequency: str, digest: str) -> Path:
    return (
        data_root
        / "raw"
        / "tdx_intraday"
        / f"freq={frequency}"
        / "source=tdx"
        / f"market={market.upper()}"
        / f"symbol={symbol}"
        / f"{digest}.parquet"
    )


def _write_raw_once(path: Path, frame: pl.DataFrame) -> bool:
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    frame.write_parquet(temporary)
    try:
        temporary.rename(path)
    except FileExistsError:
        temporary.unlink()
        return False
    return True


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def import_minute_file(path: Path, *, data_root: Path) -> ImportResult:
    symbol, market, frequency = _symbol_from_path(path)
    directory = _clean_directory(data_root, symbol, frequency)
    coverage_path = directory / "coverage.json"
    before = path.stat()
    if coverage_path.is_file() and (directory / "data.parquet").is_file():
        coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
        if (
            coverage.get("source_file") == str(path)
            and coverage.get("source_bytes") == before.st_size
            and coverage.get("source_mtime_ns") == before.st_mtime_ns
            and Path(coverage.get("raw_path", "")).is_file()
        ):
            return ImportResult(**{**coverage, "raw_written": False, "clean_changed_rows": 0,
                                   "skipped_unchanged": True})

    payload = path.read_bytes()
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise RuntimeError(f"TongdaXin source changed while reading: {path}")
    digest = hashlib.sha256(payload).hexdigest()
    raw, clean, stats = decode_minute_payload(payload, symbol=symbol, frequency=frequency)
    raw_path = _raw_path(data_root, symbol, market, frequency, digest)
    raw_written = _write_raw_once(raw_path, raw)
    changed = merge_bars(directory, clean)
    values: dict[str, Any] = {
        "symbol": symbol,
        "market": market.upper(),
        "frequency": frequency,
        "source_file": str(path),
        "source_bytes": before.st_size,
        "source_mtime_ns": before.st_mtime_ns,
        "source_sha256": digest,
        "raw_path": str(raw_path),
        **asdict(stats),
    }
    _write_json(coverage_path, values)
    return ImportResult(
        **values,
        raw_written=raw_written,
        clean_changed_rows=changed,
        skipped_unchanged=False,
    )


def discover_minute_files(
    tdx_root: Path, *, markets: Sequence[str], frequencies: Sequence[str]
) -> list[Path]:
    unknown_markets = set(markets) - set(_MARKET)
    unknown_frequencies = set(frequencies) - set(_EXTENSION)
    if unknown_markets or unknown_frequencies:
        raise ValueError(
            f"Unsupported markets/frequencies: {sorted(unknown_markets)}, {sorted(unknown_frequencies)}"
        )
    files: list[Path] = []
    for market in markets:
        for frequency in frequencies:
            folder = "minline" if frequency == "1m" else "fzline"
            files.extend(sorted((tdx_root / market / folder).glob(f"{market}*.{_EXTENSION[frequency]}")))
    return files


def _summarize(results: list[ImportResult], errors: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "files": len(results),
        "errors": errors,
        "records": sum(result.records for result in results),
        "valid_rows": sum(result.valid_rows for result in results),
        "clean_changed_rows": sum(result.clean_changed_rows for result in results),
        "raw_files_written": sum(result.raw_written for result in results),
        "skipped_unchanged": sum(result.skipped_unchanged for result in results),
        "trailing_bytes": sum(result.trailing_bytes for result in results),
        "zero_placeholder_rows": sum(result.zero_placeholder_rows for result in results),
        "invalid_date_rows": sum(result.invalid_date_rows for result in results),
        "invalid_time_rows": sum(result.invalid_time_rows for result in results),
        "invalid_ohlcv_rows": sum(result.invalid_ohlcv_rows for result in results),
        "duplicate_rows": sum(result.duplicate_rows for result in results),
        "incomplete_days": sum(result.incomplete_days for result in results),
        "missing_bars": sum(result.missing_bars for result in results),
        "first_date": min((r.first_date for r in results if r.first_date), default=None),
        "last_date": max((r.last_date for r in results if r.last_date), default=None),
    }


def import_tdx_intraday(
    *,
    tdx_root: Path,
    data_root: Path,
    artifacts_root: Path,
    markets: Sequence[str] = ("sh", "sz", "bj"),
    frequencies: Sequence[str] = ("1m", "5m"),
    workers: int = 4,
    limit: int | None = None,
) -> dict[str, Any]:
    if workers < 1 or (limit is not None and limit < 1):
        raise ValueError("workers and limit must be positive")
    files = discover_minute_files(tdx_root, markets=markets, frequencies=frequencies)
    if limit is not None:
        files = files[:limit]
    results: list[ImportResult] = []
    errors: list[dict[str, str]] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        pending = {executor.submit(import_minute_file, path, data_root=data_root): path for path in files}
        for index, future in enumerate(as_completed(pending), 1):
            path = pending[future]
            try:
                results.append(future.result())
            except Exception as exc:
                errors.append({"source_file": str(path), "error": str(exc)})
            if index % 500 == 0 or index == len(files):
                print(f"TongdaXin {index}/{len(files)} files; errors={len(errors)}", flush=True)

    results.sort(key=lambda item: (item.frequency, item.market, item.symbol))
    timestamp = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y%m%dT%H%M%S%f")
    output = artifacts_root / timestamp
    output.mkdir(parents=True, exist_ok=False)
    if results:
        pl.DataFrame([asdict(result) for result in results]).write_csv(output / "file_inventory.csv")
    summary = _summarize(results, errors)
    summary.update(
        {
            "tdx_root": str(tdx_root),
            "data_root": str(data_root),
            "markets": list(markets),
            "frequencies": list(frequencies),
            "artifacts": str(output),
        }
    )
    _write_json(output / "summary.json", summary)
    return summary


def b8_file_coverage(tdx_root: Path, config: Path) -> dict[str, Any]:
    symbols: list[str] = tomllib.loads(config.read_text(encoding="utf-8"))["symbols"]
    rows = []
    for symbol in symbols:
        market = symbol[-2:].lower()
        code = symbol[:6]
        rows.append(
            {
                "symbol": symbol,
                "has_1m": (tdx_root / market / "minline" / f"{market}{code}.lc1").is_file(),
                "has_5m": (tdx_root / market / "fzline" / f"{market}{code}.lc5").is_file(),
            }
        )
    frame = pl.DataFrame(rows)
    return {
        "symbols": len(symbols),
        "symbols_with_1m": frame.filter(pl.col("has_1m")).height,
        "symbols_with_5m": frame.filter(pl.col("has_5m")).height,
        "symbols_with_both": frame.filter(pl.col("has_1m") & pl.col("has_5m")).height,
        "missing_symbols": frame.filter(~pl.col("has_1m") | ~pl.col("has_5m"))["symbol"].to_list(),
    }


def _parse_csv_values(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(part.strip().lower() for value in values for part in value.split(",") if part.strip())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tdx-root", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--artifacts-root", type=Path, default=Path("artifacts/tdx"))
    parser.add_argument("--markets", nargs="+", default=("sh", "sz", "bj"))
    parser.add_argument("--frequencies", nargs="+", default=("1m", "5m"))
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    markets = _parse_csv_values(args.markets)
    frequencies = _parse_csv_values(args.frequencies)
    summary = import_tdx_intraday(
        tdx_root=args.tdx_root,
        data_root=args.data_root,
        artifacts_root=args.artifacts_root,
        markets=markets,
        frequencies=frequencies,
        workers=args.workers,
        limit=args.limit,
    )
    summary["b8"] = b8_file_coverage(
        args.tdx_root, Path("configs/universe/stock_top800_5m.toml")
    )
    _write_json(Path(summary["artifacts"]) / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
