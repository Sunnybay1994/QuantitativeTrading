"""Import local TongdaXin ``.day`` files without touching the source directory."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import polars as pl

from quant.data.tdx_intraday import decode_daily_payload

_DAY_FILE = re.compile(r"^(sh|sz|bj)([0-9a-z]{6})[.]day$")
_MARKET = {"sh": "SH", "sz": "SZ", "bj": "BJ"}
_DECODER_VERSION = "tdx-day-v2"
_CLEAN_SCHEMA: dict[str, Any] = {
    "symbol": pl.String,
    "market": pl.String,
    "instrument_type": pl.String,
    "trade_date": pl.Date,
    "open": pl.Float64,
    "high": pl.Float64,
    "low": pl.Float64,
    "close": pl.Float64,
    "volume": pl.Float64,
    "amount": pl.Float64,
    "source": pl.String,
}


@dataclass(frozen=True)
class DailyDecodeStats:
    records: int
    trailing_bytes: int
    valid_rows: int
    zero_placeholder_rows: int
    invalid_date_rows: int
    invalid_ohlcv_rows: int
    duplicate_rows: int
    excluded_other_rows: int
    volume_scaled_100_rows: int
    first_date: str | None
    last_date: str | None


@dataclass(frozen=True)
class DailyImportResult:
    symbol: str
    market: str
    instrument_type: str
    price_scale: int
    decoder_version: str
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
    invalid_ohlcv_rows: int
    duplicate_rows: int
    excluded_other_rows: int
    volume_scaled_100_rows: int
    first_date: str | None
    last_date: str | None


def _symbol_from_path(path: Path) -> tuple[str, str]:
    matched = _DAY_FILE.fullmatch(path.name.lower())
    if matched is None:
        raise ValueError(f"Invalid TongdaXin daily file name: {path.name}")
    market, code = matched.groups()
    return f"{code.upper()}.{_MARKET[market]}", market


def classify_instrument(symbol: str, known: Mapping[str, str] | None = None) -> str:
    """Classify project-relevant A shares, exchange funds, and indices."""
    if known and symbol in known:
        return known[symbol]
    code, market = symbol.split(".")
    if market == "SH":
        if code.startswith(("000", "880", "999")):
            return "INDEX"
        if code.startswith(("600", "601", "603", "605", "688", "689")):
            return "STOCK"
        if code.startswith("5"):
            return "ETF"
    elif market == "SZ":
        if code.startswith("399"):
            return "INDEX"
        if code.startswith(("000", "001", "002", "003", "300", "301")):
            return "STOCK"
        if code.startswith(("15", "16")):
            return "ETF"
    elif market == "BJ":
        if code.startswith("899"):
            return "INDEX"
        if code.startswith(("4", "8", "9")):
            return "STOCK"
    return "OTHER"


def price_scale(instrument_type: str) -> int:
    return 1000 if instrument_type == "ETF" else 100


def decode_daily_clean(
    payload: bytes, *, symbol: str, instrument_type: str
) -> tuple[pl.DataFrame, pl.DataFrame, DailyDecodeStats]:
    raw, trailing = decode_daily_payload(payload)
    raw = raw.with_row_index("source_record")
    if raw.is_empty():
        stats = DailyDecodeStats(0, trailing, 0, 0, 0, 0, 0, 0, 0, None, None)
        return raw, pl.DataFrame(schema=_CLEAN_SCHEMA), stats

    trade_date = pl.col("date").cast(pl.String).str.to_date("%Y%m%d", strict=False)
    dated = raw.with_columns(trade_date.alias("trade_date"))
    zero = pl.all_horizontal(
        [pl.col(name) == 0 for name in (
            "open_raw", "high_raw", "low_raw", "close_raw", "amount", "volume"
        )]
    )
    valid_date = pl.col("trade_date").is_not_null() & pl.col("date").is_between(19900101, 21001231)
    valid_ohlcv = (
        pl.all_horizontal(
            [pl.col(name) > 0 for name in ("open_raw", "high_raw", "low_raw", "close_raw")]
        )
        & pl.col("amount").is_finite()
        & (pl.col("amount") >= 0)
        & (pl.col("volume") >= 0)
        & (pl.col("high_raw") >= pl.max_horizontal("open_raw", "close_raw", "low_raw"))
        & (pl.col("low_raw") <= pl.min_horizontal("open_raw", "close_raw", "high_raw"))
    )
    duplicate = dated.select("date").is_duplicated()
    scale = price_scale(instrument_type)
    close_price = pl.col("close_raw") / scale
    direct_error = (pl.col("amount") / pl.col("volume") / close_price - 1).abs()
    lot_error = (pl.col("amount") / (pl.col("volume") * 100) / close_price - 1).abs()
    volume_scale = (
        pl.when((pl.col("volume") > 0) & (pl.col("amount") > 0) & (lot_error < direct_error))
        .then(100)
        .otherwise(1)
    )
    marked = dated.with_columns(
        zero.alias("_zero"),
        valid_date.alias("_valid_date"),
        valid_ohlcv.alias("_valid_ohlcv"),
        pl.Series("_duplicate", duplicate),
        volume_scale.alias("_volume_scale"),
    )
    selected = instrument_type in {"STOCK", "ETF", "INDEX"}
    clean = marked.filter(
        ~pl.col("_zero")
        & pl.col("_valid_date")
        & pl.col("_valid_ohlcv")
        & ~pl.col("_duplicate")
        & pl.lit(selected)
    ).select(
        pl.lit(symbol).alias("symbol"),
        pl.lit(symbol[-2:]).alias("market"),
        pl.lit(instrument_type).alias("instrument_type"),
        "trade_date",
        *[
            (pl.col(f"{name}_raw") / scale).cast(pl.Float64).alias(name)
            for name in ("open", "high", "low", "close")
        ],
        (pl.col("volume") * pl.col("_volume_scale")).cast(pl.Float64).alias("volume"),
        pl.col("amount").cast(pl.Float64),
        pl.lit("tdx").alias("source"),
    )
    _validate_clean(clean)
    eligible = marked.filter(~pl.col("_zero") & pl.col("_valid_date") & pl.col("_valid_ohlcv"))
    stats = DailyDecodeStats(
        records=raw.height,
        trailing_bytes=trailing,
        valid_rows=clean.height,
        zero_placeholder_rows=marked.filter(pl.col("_zero")).height,
        invalid_date_rows=marked.filter(~pl.col("_zero") & ~pl.col("_valid_date")).height,
        invalid_ohlcv_rows=marked.filter(~pl.col("_zero") & ~pl.col("_valid_ohlcv")).height,
        duplicate_rows=int(duplicate.sum()),
        excluded_other_rows=eligible.height if not selected else 0,
        volume_scaled_100_rows=marked.filter(
            pl.col("_volume_scale") == 100
        ).height if selected else 0,
        first_date=str(clean["trade_date"].min()) if not clean.is_empty() else None,
        last_date=str(clean["trade_date"].max()) if not clean.is_empty() else None,
    )
    return raw, clean, stats


def _validate_clean(frame: pl.DataFrame) -> None:
    if frame.schema != _CLEAN_SCHEMA:
        raise ValueError("Unexpected TongdaXin daily clean schema")
    if frame.is_empty():
        return
    if (
        frame.select("symbol", "trade_date").is_duplicated().any()
        or set(frame["source"]) != {"tdx"}
        or not set(frame["instrument_type"]) <= {"STOCK", "ETF", "INDEX"}
        or frame.filter(
            pl.any_horizontal(
                [~pl.col(name).is_finite() | (pl.col(name) <= 0) for name in (
                    "open", "high", "low", "close"
                )]
            )
            | ~pl.col("amount").is_finite()
            | (pl.col("amount") < 0)
            | ~pl.col("volume").is_finite()
            | (pl.col("volume") < 0)
            | (pl.col("high") < pl.max_horizontal("open", "close", "low"))
            | (pl.col("low") > pl.min_horizontal("open", "close", "high"))
        ).height
    ):
        raise ValueError("Invalid TongdaXin daily clean bars")


def _clean_directory(data_root: Path, symbol: str) -> Path:
    return (
        data_root / "clean/bar_1d_tdx/source=tdx"
        / f"market={symbol[-2:]}" / f"symbol={symbol}"
    )


def _raw_path(data_root: Path, symbol: str, digest: str) -> Path:
    return (
        data_root / "raw/tdx_daily/source=tdx"
        / f"market={symbol[-2:]}" / f"symbol={symbol}" / f"{digest}.parquet"
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


def _merge_clean(directory: Path, incoming: pl.DataFrame) -> int:
    path = directory / "data.parquet"
    old = pl.read_parquet(path) if path.is_file() else pl.DataFrame(schema=_CLEAN_SCHEMA)
    changed = incoming.join(old, on=incoming.columns, how="anti", nulls_equal=True).height
    result = pl.concat([old, incoming], how="vertical_relaxed").unique(
        subset=["symbol", "trade_date"], keep="last", maintain_order=True
    ).sort("trade_date")
    _validate_clean(result)
    directory.mkdir(parents=True, exist_ok=True)
    if changed or not path.exists():
        temporary = path.with_suffix(".tmp.parquet")
        result.write_parquet(temporary)
        os.replace(temporary, path)
    return changed


def import_daily_file(
    path: Path, *, data_root: Path, known_types: Mapping[str, str] | None = None
) -> DailyImportResult:
    symbol, market = _symbol_from_path(path)
    instrument_type = classify_instrument(symbol, known_types)
    directory = _clean_directory(data_root, symbol)
    coverage_path = directory / "coverage.json"
    before = path.stat()
    if coverage_path.is_file() and (directory / "data.parquet").is_file():
        coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
        if (
            coverage.get("source_file") == str(path)
            and coverage.get("decoder_version") == _DECODER_VERSION
            and coverage.get("source_bytes") == before.st_size
            and coverage.get("source_mtime_ns") == before.st_mtime_ns
            and Path(coverage.get("raw_path", "")).is_file()
        ):
            return DailyImportResult(
                **coverage, raw_written=False, clean_changed_rows=0, skipped_unchanged=True
            )

    payload = path.read_bytes()
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise RuntimeError(f"TongdaXin source changed while reading: {path}")
    digest = hashlib.sha256(payload).hexdigest()
    raw, clean, stats = decode_daily_clean(
        payload, symbol=symbol, instrument_type=instrument_type
    )
    raw_path = _raw_path(data_root, symbol, digest)
    raw_written = _write_raw_once(raw_path, raw)
    changed = _merge_clean(directory, clean)
    values: dict[str, Any] = {
        "symbol": symbol,
        "market": market.upper(),
        "instrument_type": instrument_type,
        "price_scale": price_scale(instrument_type),
        "decoder_version": _DECODER_VERSION,
        "source_file": str(path),
        "source_bytes": before.st_size,
        "source_mtime_ns": before.st_mtime_ns,
        "source_sha256": digest,
        "raw_path": str(raw_path),
        **asdict(stats),
    }
    _write_json(coverage_path, values)
    return DailyImportResult(
        **values,
        raw_written=raw_written,
        clean_changed_rows=changed,
        skipped_unchanged=False,
    )


def _known_types(data_root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for market in ("SH", "SZ"):
        path = data_root / f"clean/instrument/market={market}/data.parquet"
        if path.is_file():
            result.update(
                pl.read_parquet(path).select("symbol", "instrument_type").rows_by_key("symbol", unique=True)
            )
    return {symbol: value[0] for symbol, value in result.items()}


def discover_daily_files(tdx_root: Path, markets: Sequence[str]) -> list[Path]:
    if set(markets) - set(_MARKET):
        raise ValueError(f"Unsupported markets: {markets}")
    return [
        path
        for market in markets
        for path in sorted((tdx_root / market / "lday").glob(f"{market}*.day"))
    ]


def import_tdx_daily(
    *, tdx_root: Path, data_root: Path, artifacts_root: Path,
    markets: Sequence[str] = ("sh", "sz", "bj"), workers: int = 8,
    limit: int | None = None,
) -> dict[str, Any]:
    if workers < 1 or (limit is not None and limit < 1):
        raise ValueError("workers and limit must be positive")
    files = discover_daily_files(tdx_root, markets)
    if limit is not None:
        files = files[:limit]
    known = _known_types(data_root)
    results: list[DailyImportResult] = []
    errors: list[dict[str, str]] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        pending = {
            executor.submit(import_daily_file, path, data_root=data_root, known_types=known): path
            for path in files
        }
        for index, future in enumerate(as_completed(pending), 1):
            path = pending[future]
            try:
                results.append(future.result())
            except Exception as exc:
                errors.append({"source_file": str(path), "error": str(exc)})
            if index % 500 == 0 or index == len(files):
                print(f"TongdaXin daily {index}/{len(files)} files; errors={len(errors)}", flush=True)

    results.sort(key=lambda item: (item.market, item.symbol))
    timestamp = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y%m%dT%H%M%S%f")
    output = artifacts_root / timestamp
    output.mkdir(parents=True, exist_ok=False)
    if results:
        pl.DataFrame([asdict(result) for result in results]).write_csv(output / "file_inventory.csv")
    summary = {
        "files": len(results),
        "errors": errors,
        "records": sum(item.records for item in results),
        "valid_rows": sum(item.valid_rows for item in results),
        "clean_changed_rows": sum(item.clean_changed_rows for item in results),
        "raw_files_written": sum(item.raw_written for item in results),
        "skipped_unchanged": sum(item.skipped_unchanged for item in results),
        "trailing_bytes": sum(item.trailing_bytes for item in results),
        "zero_placeholder_rows": sum(item.zero_placeholder_rows for item in results),
        "invalid_date_rows": sum(item.invalid_date_rows for item in results),
        "invalid_ohlcv_rows": sum(item.invalid_ohlcv_rows for item in results),
        "duplicate_rows": sum(item.duplicate_rows for item in results),
        "excluded_other_rows": sum(item.excluded_other_rows for item in results),
        "volume_scaled_100_rows": sum(item.volume_scaled_100_rows for item in results),
        "first_date": min((item.first_date for item in results if item.first_date), default=None),
        "last_date": max((item.last_date for item in results if item.last_date), default=None),
        "by_instrument_type": {
            kind: {
                "files": sum(item.instrument_type == kind for item in results),
                "valid_rows": sum(item.valid_rows for item in results if item.instrument_type == kind),
            }
            for kind in ("STOCK", "ETF", "INDEX", "OTHER")
        },
        "tdx_root": str(tdx_root),
        "data_root": str(data_root),
        "artifacts": str(output),
    }
    _write_json(output / "summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tdx-root", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--artifacts-root", type=Path, default=Path("artifacts/tdx/daily"))
    parser.add_argument("--markets", nargs="+", default=("sh", "sz", "bj"))
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    summary = import_tdx_daily(
        tdx_root=args.tdx_root,
        data_root=args.data_root,
        artifacts_root=args.artifacts_root,
        markets=tuple(value.lower() for value in args.markets),
        workers=args.workers,
        limit=args.limit,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
