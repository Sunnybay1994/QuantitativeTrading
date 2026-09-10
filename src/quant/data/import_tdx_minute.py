"""Import locally downloaded A-share TDX five-minute files, preserving new raw captures."""

import argparse
import datetime as dt
import json
import struct
from pathlib import Path
from typing import Any

import polars as pl

from quant.data.intraday import add_session_quality, merge_bars
from quant.data.intraday_bars import SCHEMA, TZ, validate_bars


def parse_lc5(content: bytes, symbol: str) -> pl.DataFrame:
    """Local .lc5 files use 32-byte records, float32 prices and share volume."""
    if len(symbol) != 9 or not symbol[:6].isdigit() or symbol[6:] not in (".SH", ".SZ"):
        raise ValueError("Invalid A-share symbol")
    if len(content) % 32:
        raise ValueError("Truncated TDX minute record")
    rows = []
    for encoded, minute, opening, high, low, close, amount, volume, _ in struct.iter_unpack(
        "<HHfffffII", content,
    ):
        day = dt.date(encoded // 2048 + 2004, (encoded % 2048) // 100, (encoded % 2048) % 100)
        # Some local files retain a 13:00 flat quote with no transactions.
        # It is not a five-minute bar; the resulting 47-bar day stays incomplete.
        if minute == 780 and volume == 0 and amount == 0 and 0 < opening == high == low == close:
            continue
        if minute not in (*range(575, 691, 5), *range(785, 901, 5)):
            raise ValueError("TDX timestamp outside five-minute exchange grid")
        if not any((opening, high, low, close, amount, volume)):
            continue
        end = dt.datetime.combine(day, dt.time(minute // 60, minute % 60), TZ)
        rows.append(dict(symbol=symbol, trade_date=day, bar_start=end-dt.timedelta(minutes=5),
                         bar_end=end, open=opening, high=high, low=low, close=close,
                         amount=amount, volume=float(volume), source="tdx"))
    result = pl.DataFrame(rows, schema=SCHEMA)
    if result.filter(~pl.col("amount").is_finite() | (pl.col("amount") < 0)
                     | ((pl.col("volume") > 0) != (pl.col("amount") > 0))).height:
        raise ValueError("Invalid TDX amount or volume")
    return validate_bars(result)


def import_symbol(data_root: Path, source_root: Path, symbol: str, end: dt.date) -> dict[str, Any]:
    code, market = symbol.lower().split(".")
    source = source_root / market / "fzline" / f"{market}{code}.lc5"
    if not source.is_file():
        return {"symbol": symbol, "missing_file": True, "changed_rows": 0}
    content = source.read_bytes()
    incoming = parse_lc5(content, symbol).filter(pl.col("trade_date") <= end)
    directory = data_root / "clean/bar_intraday/freq=5m/source=tdx" / f"symbol={symbol}"
    path = directory / "data.parquet"
    old = pl.read_parquet(path).select(list(SCHEMA)) if path.is_file() else incoming.head(0)
    changed = incoming.join(old, on=list(SCHEMA), how="anti", nulls_equal=True).height
    if not changed:
        return {"symbol": symbol, "changed_rows": 0}
    incoming = add_session_quality(incoming, data_root, "5m", symbol)
    raw_dir = data_root / "raw/tdx_intraday_local" / f"symbol={symbol}"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw = raw_dir / (dt.datetime.now().strftime("%Y%m%dT%H%M%S%f") + ".lc5")
    with raw.open("xb") as output:
        output.write(content)
    merged = merge_bars(directory, incoming)
    assert merged == changed
    status = dict(symbol=symbol, frequency="5m", source_file=str(source), raw_path=str(raw),
                  source_bytes=len(content), changed_rows=changed, rows_read=incoming.height,
                  first_date=str(incoming["trade_date"].min()), last_date=str(incoming["trade_date"].max()))
    (directory / "coverage.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
    return status


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=Path("D:/new_tdx/vipdoc"))
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--pool-run", type=Path, required=True)
    parser.add_argument("--to", type=dt.date.fromisoformat, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    symbols = json.loads(args.pool_run.read_text(encoding="utf-8"))["candidate_symbols"]
    results = []
    for symbol in symbols:
        try:
            results.append(import_symbol(args.data_root, args.source_root, symbol, args.to))
        except (OSError, ValueError) as error:
            results.append(dict(symbol=symbol, error=str(error), changed_rows=0))
    summary = dict(symbols=len(symbols), changed_rows=sum(row["changed_rows"] for row in results),
                   missing_files=sum(row.get("missing_file", False) for row in results),
                   errors=[row for row in results if "error" in row], results=results)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(summary, output, indent=2)
    print(json.dumps({key: value for key, value in summary.items() if key != "results"}))
    if summary["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
