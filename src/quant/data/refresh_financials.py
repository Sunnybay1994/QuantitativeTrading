"""Append a reported quarter for the stock pool and publish a new financial version."""

import argparse
import calendar
import datetime as dt
import json
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import polars as pl
import tomllib

from quant.data.connectors.tushare import TushareConnector
from quant.data.financial_clean import normalize_financial_publication
from quant.data.storage import RawStore

TABLES = ("income", "balancesheet", "cashflow", "fina_indicator")


def merge_financial_rows(base: pl.DataFrame, incoming: pl.DataFrame) -> tuple[pl.DataFrame, int]:
    """Retain known values; newly observed values become usable prospectively."""
    if (incoming.schema.get('source_observed_on') != pl.Date
            or incoming['source_observed_on'].null_count()):
        raise ValueError('Every incoming financial row needs an observation date')
    combined = pl.concat([base.with_columns(pl.lit(False).alias('_incoming')),
                          incoming.with_columns(pl.lit(True).alias('_incoming'))], how="diagonal_relaxed")
    old = combined.filter(~pl.col('_incoming')).drop('_incoming')
    fresh = combined.filter(pl.col('_incoming')).drop('_incoming')
    keys = [c for c in old.columns if c not in ('source_file', 'source_observed_on', 'available_date')]
    fresh = fresh.join(old.select(keys).unique(), on=keys, how='anti', nulls_equal=True)
    fresh = fresh.sort('source_observed_on').unique(subset=keys, keep='first').with_columns(
        pl.max_horizontal('available_date', 'source_observed_on').alias('available_date'))
    result = pl.concat([old, fresh])
    return result.sort("symbol", "end_date", "available_date"), combined.height - result.height


def refresh_quarter(
    *, data_root: Path, base_name: str, name: str, symbols: list[str], period: dt.date,
    client: Any = None, pause_seconds: float = 1.0,
    observed_on: dt.date | None = None,
    progress: Callable[[dict], None] | None = None,
) -> dict[str, Any]:
    for value in (base_name, name):
        if not value or Path(value).name != value or value in (".", ".."):
            raise ValueError("Invalid financial version name")
    if (base_name == name or not symbols or len(set(symbols)) != len(symbols) or pause_seconds < 0
        or any(not re.fullmatch(r"[0-9]{6}\.(SH|SZ)", symbol) for symbol in symbols)
        or period.month not in (3, 6, 9, 12) or period.day != calendar.monthrange(period.year, period.month)[1]):
        raise ValueError("Invalid financial quarter request")
    base = data_root / "clean/tushare_financials" / base_name
    prior_summary = json.loads((base / "summary.json").read_text(encoding="utf-8"))
    output = data_root / "clean/tushare_financials" / name
    if (output / "summary.json").exists():
        raise FileExistsError("Completed financial version already exists")
    output.mkdir(parents=True, exist_ok=True)
    # This small data capture list allows an interrupted network refresh to resume.
    capture_path = output / "captured.parquet"
    captured = pl.read_parquet(capture_path).to_dicts() if capture_path.exists() else []
    if any(not row.get('observed_on') for row in captured):
        raise ValueError('Prior partial capture has no observation date; use a new version')
    if any(row["period"] != str(period) or row["base_name"] != base_name
           or row["symbol"] not in symbols or row["dataset"] not in TABLES for row in captured):
        raise ValueError("Financial capture belongs to a different request")
    done = {(row["dataset"], row["symbol"]) for row in captured}
    def report(phase: str, **details) -> None:
        if progress is not None:
            progress(dict(phase=phase, completed=len(captured), total=len(symbols)*len(TABLES),
                          period=str(period), **details))
    report('capture')
    client = client or TushareConnector(config_path=Path("configs/tushare.local.toml"))
    store = RawStore(data_root / "raw")
    for symbol in symbols:
        for table in TABLES:
            if (table, symbol) in done:
                continue
            parameters = {"ts_code": symbol, "period": period.strftime("%Y%m%d")}
            report('request', table=table, symbol=symbol)
            for attempt in range(3):
                try:
                    raw = client.query_raw(table, **parameters)
                    break
                except Exception:
                    if attempt == 2:
                        raise RuntimeError(f"Financial request failed: {table} {symbol}") from None
                    time.sleep(2 * (attempt + 1))
            saved = store.write(source="tushare", table=table, frame=raw, parameters=parameters)
            if not raw.is_empty() and (set(raw["ts_code"]) != {symbol}
                                      or set(raw["end_date"].cast(pl.String)) != {parameters["period"]}):
                raise ValueError(f"Financial response scope differs: {table} {symbol}")
            captured.append({"dataset": table, "symbol": symbol, "period": str(period),
                             "base_name": base_name, "rows": raw.height,
                             "observed_on": str(observed_on or dt.datetime.now(
                                 dt.timezone(dt.timedelta(hours=8))).date()),
                             "raw_path": str(saved.data_path)})
            pl.DataFrame(captured).write_parquet(capture_path)
            report('captured', table=table, symbol=symbol)
            if len(captured) % 60 == 0:
                print(f"Captured financial quarter {len(captured)}/{len(symbols) * len(TABLES)}", flush=True)
            time.sleep(pause_seconds)
    summary: dict[str, Any] = {"name": name, "base_version": base_name, "period": str(period),
        "symbols_requested": len(symbols), "symbols": sorted(symbols), "datasets": {},
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "pit_rule": "new economic rows available no earlier than observation date; strictly before signal session"}
    for table in TABLES:
        report('publish', table=table)
        old = pl.read_parquet(base / f"{table}.parquet")
        prior_quarantine = pl.read_parquet(base / f"{table}_quarantine.parquet")
        selected = [row for row in captured if row["dataset"] == table]
        frames = [pl.read_parquet(row["raw_path"]).with_columns(pl.lit(row["raw_path"]).alias("source_file"))
                  for row in selected if row["rows"] > 0]
        quarantine = prior_quarantine
        numeric_nulls = 0
        if frames:
            incoming, rejected, numeric_nulls = normalize_financial_publication(
                pl.concat(frames, how="diagonal_relaxed"), dataset=table)
            observations = pl.DataFrame({'source_file': [row['raw_path'] for row in selected],
                'source_observed_on': [dt.date.fromisoformat(row['observed_on']) for row in selected]})
            incoming = incoming.join(observations, on='source_file', how='left', validate='m:1')
            merged, duplicates = merge_financial_rows(old, incoming)
            quarantine = pl.concat([prior_quarantine, rejected], how="diagonal_relaxed")
        else:
            merged, duplicates = old, 0
        merged.write_parquet(output / f"{table}.parquet")
        quarantine.write_parquet(output / f"{table}_quarantine.parquet")
        prior = prior_summary["datasets"][table]
        added_raw = sum(row["rows"] for row in selected)
        summary["datasets"][table] = {
            "base_clean_rows": old.height, "captured_requests": len(selected),
            "added_raw_rows": added_raw, "clean_rows": merged.height,
            "raw_rows": prior["raw_rows"] + added_raw,
            "quarantined_rows": quarantine.height,
            "exact_duplicate_rows": prior["exact_duplicate_rows"] + duplicates,
            "optional_numeric_values_nulled": prior.get("optional_numeric_values_nulled", 0) + numeric_nulls,
            "last_announcement": str(merged["available_date"].max()),
        }
        counts = summary["datasets"][table]
        if counts["raw_rows"] != counts["clean_rows"] + counts["quarantined_rows"] + counts["exact_duplicate_rows"]:
            raise ValueError(f"Financial refresh row reconciliation failed: {table}")
        print(f"Published {table}: {merged.height} clean rows", flush=True)
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    report('complete')
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--base", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--period", type=dt.date.fromisoformat, required=True)
    parser.add_argument("--pool", type=Path, default=Path("configs/universe/stock_top800_5m.toml"))
    args = parser.parse_args()
    symbols = tomllib.loads(args.pool.read_text(encoding="utf-8"))["symbols"]
    print(json.dumps(refresh_quarter(data_root=args.data_root, base_name=args.base, name=args.name,
                                    symbols=symbols, period=args.period), ensure_ascii=False))


if __name__ == "__main__":
    main()
