"""Publish research-ready financial tables from the existing raw capture."""

import argparse
import datetime as dt
import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import polars as pl

from quant.data.financial_clean import normalize_financial_publication

DATASETS = ("income", "balancesheet", "cashflow", "fina_indicator")


@dataclass(frozen=True)
class FinancialPublication:
    root: Path
    snapshot_id: str
    dataset_rows: tuple[tuple[str, int], ...]

    @property
    def content_sha256(self) -> str:
        digest = hashlib.sha256()
        for table in DATASETS:
            with (self.root / f"{table}.parquet").open("rb") as source:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(block)
        return digest.hexdigest()


def load_financial_publication(*, data_root: Path, snapshot_id: str) -> FinancialPublication:
    if not snapshot_id or Path(snapshot_id).name != snapshot_id or snapshot_id in (".", ".."):
        raise ValueError("Invalid financial publication name")
    root = data_root / "clean/tushare_financials" / snapshot_id
    summary = json.loads((root / "summary.json").read_text(encoding="utf-8"))
    rows = tuple((table, summary["datasets"][table]["clean_rows"]) for table in DATASETS)
    for table, expected in rows:
        actual = pl.scan_parquet(root / f"{table}.parquet").select(pl.len()).collect().item()
        if actual != expected:
            raise ValueError(f"Financial row count differs: {table}")
    return FinancialPublication(root=root, snapshot_id=snapshot_id, dataset_rows=rows)


def _read_raw(item: tuple[Path, int]) -> pl.DataFrame:
    path, expected = item
    frame = pl.read_parquet(path)
    if frame.height != expected:
        raise ValueError(f"Raw row count differs: {path}")
    return frame.with_columns(pl.lit(path.as_posix()).alias("source_file"))


def publish_financials(*, data_root: Path, name: str, workers: int = 8) -> dict[str, Any]:
    if not name or Path(name).name != name or name in (".", "..") or not 1 <= workers <= 16:
        raise ValueError("Invalid financial publication arguments")
    database = data_root / "run_state/tushare_bulk/state.sqlite"
    with sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True) as connection:
        records = connection.execute(
            "SELECT dataset, request_id, status, rows FROM requests "
            "WHERE dataset IN ('income','balancesheet','cashflow','fina_indicator') "
            "ORDER BY dataset, request_id"
        ).fetchall()
    if not records or any(status != "COMPLETE" or rows is None for _, _, status, rows in records):
        raise ValueError("Financial raw requests are incomplete")
    output = data_root / "clean/tushare_financials" / name
    output.mkdir(parents=True, exist_ok=False)
    summary: dict[str, Any] = {"name": name, "datasets": {},
        "available_date": "max(ann_date, f_ann_date); indicator uses ann_date",
        "pit_rule": "available_date strictly before the signal session",
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat()}
    pl.DataFrame(records, schema=["dataset", "request_id", "status", "rows"], orient="row").write_parquet(
        output / "source_requests.parquet")
    for table in DATASETS:
        selected = [(data_root / "raw/tushare" / table / f"request={request}" / "data.parquet", rows)
                    for dataset, request, _, rows in records if dataset == table and rows > 0]
        if not selected:
            raise ValueError(f"No nonempty financial raw: {table}")
        clean_parts, quarantine_parts = [], []
        numeric_nulls = 0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for offset in range(0, len(selected), 1000):
                frames = list(pool.map(_read_raw, selected[offset:offset + 1000]))
                combined = pl.concat(frames, how="diagonal_relaxed")
                clean, quarantine, nulls = normalize_financial_publication(combined, dataset=table)
                clean_parts.append(clean)
                quarantine_parts.append(quarantine)
                numeric_nulls += nulls
                if offset % 5000 == 0:
                    print(f"{table}: {min(offset + 1000, len(selected))}/{len(selected)} files", flush=True)
        clean = pl.concat(clean_parts, how="diagonal_relaxed")
        keys = [column for column in clean.columns if column != "source_file"]
        before = clean.height
        clean = clean.unique(subset=keys, keep="first").sort("symbol", "end_date", "available_date")
        quarantine = pl.concat(quarantine_parts, how="diagonal_relaxed")
        raw_rows = sum(rows for dataset, _, _, rows in records if dataset == table)
        if raw_rows != clean.height + quarantine.height + before - clean.height:
            raise ValueError(f"Financial row reconciliation failed: {table}")
        clean.write_parquet(output / f"{table}.parquet")
        quarantine.write_parquet(output / f"{table}_quarantine.parquet")
        summary["datasets"][table] = {"requests": sum(r[0] == table for r in records),
            "nonempty_requests": len(selected), "raw_rows": raw_rows, "clean_rows": clean.height,
            "quarantined_rows": quarantine.height, "exact_duplicate_rows": before - clean.height,
            "optional_numeric_values_nulled": numeric_nulls,
            "symbols": clean["symbol"].n_unique(),
            "first_announcement": str(clean["available_date"].min()),
            "last_announcement": str(clean["available_date"].max()),
            "quarantine_reasons": quarantine.group_by("quarantine_reason").len().to_dicts()}
        print(table, summary["datasets"][table], flush=True)
    (output / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--name", default=dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    print(json.dumps(publish_financials(data_root=args.data_root, name=args.name, workers=args.workers),
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
