"""Import official TDX extended daily and professional data into separate snapshots.

Financial layout reference: rainx/pytdx history_financial_crawler.py.
Numbered financial/stock fields deliberately retain vendor identifiers: they are
not PIT fundamentals until their meaning and publication dates are established.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import shutil
import struct
from pathlib import Path
from typing import Any

import polars as pl


def decode_hk(payload: bytes, symbol: str) -> tuple[pl.DataFrame, int]:
    """Extended .day prices are float32; retain vendor volume without guessing units."""
    if not re.fullmatch(r"\d{5}\.HK", symbol) or len(payload) % 32:
        raise ValueError("Invalid HK symbol or truncated record")
    names = ["date_raw", "open", "high", "low", "close", "amount",
             "volume_raw", "reserved_float"]
    schema: dict[str, Any] = {n: pl.Float64 for n in names}
    schema.update(date_raw=pl.UInt32, volume_raw=pl.UInt32)
    frame = pl.DataFrame(struct.iter_unpack("<IfffffIf", payload),
                         schema=schema, orient="row")
    frame = frame.with_columns(
        pl.col("date_raw").cast(pl.String).str.to_date("%Y%m%d", strict=False)
        .alias("trade_date"), pl.lit(symbol).alias("symbol"),
        pl.lit("tdx").alias("source"), pl.lit("HKD").alias("currency"),
        pl.lit("unadjusted").alias("adjustment"),
    )
    valid = (
        pl.col("trade_date").is_not_null()
        & pl.col("trade_date").is_between(dt.date(1970, 1, 1), dt.date.today())
        & pl.all_horizontal([pl.col(n).is_finite() & (pl.col(n) > 0)
                             for n in ("open", "high", "low", "close")])
        & (pl.col("high") >= pl.max_horizontal("open", "low", "close"))
        & (pl.col("low") <= pl.min_horizontal("open", "high", "close"))
        & pl.col("amount").is_finite() & (pl.col("amount") >= 0)
        & ~pl.col("trade_date").is_duplicated()
    )
    clean = frame.filter(valid).sort("trade_date")
    return clean, frame.height - clean.height


def decode_financial(payload: bytes) -> pl.DataFrame:
    """Read the vendor header, symbol offset table and float fields with bounds checks."""
    if len(payload) < 20:
        raise ValueError("Truncated financial header")
    _, date, count, _, size, _ = struct.unpack_from("<hIHIII", payload)
    report_date = dt.datetime.strptime(str(date), "%Y%m%d").date()
    # Empty vendor reports encode report_size as unsigned -4, not a field count.
    if count == 0:
        size = 0
    if size % 4 or (count and not size) or 20 + count * 11 > len(payload):
        raise ValueError("Invalid financial table size")
    if count and size > len(payload) - 20 - count * 11:
        raise ValueError("Financial offset or size outside payload")
    fields = size // 4
    records = []
    for index in range(count):
        code, market, offset = struct.unpack_from("<6sBI", payload, 20 + index * 11)
        if offset < 20 + count * 11 or offset + size > len(payload):
            raise ValueError("Financial offset outside payload")
        code_text = code.decode("ascii")
        if not re.fullmatch(r"\d{6}", code_text):
            raise ValueError("Invalid financial security code")
        records.append((code_text, market, report_date,
                        *struct.unpack_from(f"<{fields}f", payload, offset)))
    schema = {"code": pl.String, "market_raw": pl.UInt8, "report_date": pl.Date}
    schema.update({f"field_{i:03}": pl.Float32 for i in range(1, fields + 1)})
    frame = pl.DataFrame(records, schema=schema, orient="row")
    duplicate = frame.select("code", "market_raw").is_duplicated()
    return frame.with_row_index("source_record").with_columns(
                              pl.Series("duplicate_security", duplicate),
                              pl.lit(None, dtype=pl.Date).alias("available_date"),
                              pl.lit(False).alias("pit_ready"))


def decode_stock(payload: bytes) -> pl.DataFrame:
    """Decode observed 13-byte typed records; field meaning and units remain vendor raw."""
    if len(payload) % 13:
        raise ValueError("Truncated stock data record")
    frame = pl.DataFrame(struct.iter_unpack("<BIff", payload), schema={
        "field_id": pl.UInt8, "date_raw": pl.UInt32,
        "value_raw": pl.Float32, "aux_raw": pl.Float32,
    }, orient="row").with_row_index("source_record")
    return frame.with_columns(
        pl.col("date_raw").cast(pl.String).str.to_date("%Y%m%d", strict=False)
        .alias("record_date"), pl.lit(False).alias("pit_ready"),
    )


def read_hk_bars(data_root: Path, snapshot: str, symbol: str,
                 start: dt.date, end: dt.date) -> pl.DataFrame:
    if not re.fullmatch(r"\d{5}\.HK", symbol) or not re.fullmatch(r"[\w-]+", snapshot):
        raise ValueError("Invalid query")
    if start > end:
        raise ValueError("Invalid date interval")
    path = data_root / "clean/tdx_extra" / snapshot / "hk_daily" / f"{symbol}.parquet"
    return pl.scan_parquet(path).filter(pl.col("trade_date").is_between(start, end)).collect()


def import_snapshot(tdx_root: Path, data_root: Path, snapshot: str,
                    datasets: list[str] | None = None) -> dict[str, Any]:
    if not re.fullmatch(r"[\w-]+", snapshot):
        raise ValueError("Invalid snapshot")
    raw = data_root / "raw/tdx_extra" / snapshot
    clean = data_root / "clean/tdx_extra" / snapshot
    raw.mkdir(parents=True, exist_ok=False)
    clean.mkdir(parents=True, exist_ok=False)
    summary: dict[str, Any] = {"snapshot": snapshot, "datasets": {}, "errors": []}
    groups = {
        "hk_daily": sorted((tdx_root / "ggtday").glob("31#*.day")),
        "hk_connect_daily": sorted((tdx_root / "ggtday").glob("49#*.day")),
        "financial": sorted((tdx_root / "cw").glob("gpcw*.dat")),
        "stock": sorted(p for p in (tdx_root / "cw").glob("gp*.dat")
                        if re.fullmatch(r"gp(sh|sz|bj)\d{6}\.dat", p.name)),
    }
    for name, files in groups.items():
        if datasets is not None and name not in datasets:
            continue
        (raw / name).mkdir()
        (clean / name).mkdir()
        stats: dict[str, Any] = {"files": 0, "rows": 0, "excluded_rows": 0, "first_date": None,
                 "last_date": None}
        for path in files:
            try:
                target = raw / name / path.name
                with path.open("rb") as src, target.open("xb") as dst:
                    shutil.copyfileobj(src, dst)
                payload = target.read_bytes()
                if name.startswith("hk_"):
                    symbol = path.stem[3:] + ".HK"
                    frame, excluded = decode_hk(payload, symbol)
                    stats["excluded_rows"] += excluded
                    output_name, date_column = symbol, "trade_date"
                    sidecar = path.with_suffix(".txt")
                    if sidecar.exists():
                        with sidecar.open("rb") as src, (raw / name / sidecar.name).open("xb") as dst:
                            shutil.copyfileobj(src, dst)
                elif name == "financial":
                    frame = decode_financial(payload)
                    output_name, date_column = path.stem, "report_date"
                else:
                    frame = decode_stock(payload)
                    frame = frame.with_columns(pl.lit(path.stem[2:]).alias("security_raw"))
                    output_name, date_column = path.stem, "record_date"
                frame.write_parquet(clean / name / (output_name + ".parquet"))
                stats["files"] += 1
                stats["rows"] += frame.height
                lo, hi = frame[date_column].min(), frame[date_column].max()
                if lo is not None:
                    stats["first_date"] = min(stats["first_date"] or str(lo), str(lo))
                    stats["last_date"] = max(stats["last_date"] or str(hi), str(hi))
            except (ValueError, OSError, struct.error, pl.exceptions.PolarsError) as exc:
                summary["errors"].append({"file": str(path), "error": str(exc)})
                print(path.name, str(exc), flush=True)
        summary["datasets"][name] = stats
        print(name, stats, flush=True)
    (clean / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tdx-root", type=Path, default=Path("D:/new_tdx/vipdoc"))
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--snapshot", default=dt.datetime.now().strftime("%Y%m%dT%H%M%S"))
    parser.add_argument("--datasets", nargs="+", choices=[
        "hk_daily", "hk_connect_daily", "financial", "stock"])
    args = parser.parse_args()
    result = import_snapshot(args.tdx_root, args.data_root, args.snapshot, args.datasets)
    print(json.dumps(result, indent=2))
    if result["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
