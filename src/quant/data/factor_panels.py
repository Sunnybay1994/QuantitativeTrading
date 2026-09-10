"""Data I/O for full-market factor and next-open return panels."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

import polars as pl

from quant.data.industry_history import attach_industry
from quant.data.refresh_stocks import read_stock_data
from quant.data.stock_paper_inputs import read_stock_paper_calendar


def available_sessions(data_root: Path, through: dt.date) -> tuple[dt.date, ...]:
    calendar = read_stock_paper_calendar(data_root)
    return tuple(calendar.filter(pl.col("is_open") & (pl.col("date") <= through))[
        "date"
    ].unique().sort().to_list())


def read_factor_industry(data_root: Path, panel: pl.DataFrame) -> pl.DataFrame:
    """Attach the latest publication using both dated Shenwan source versions."""
    for summary_path in sorted((data_root / "clean/tushare_industry").glob("*/summary.json"), reverse=True):
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        if summary.get("with_current"):
            intervals = pl.read_parquet(summary_path.parent / "intervals.parquet")
            return attach_industry(panel, intervals)
    raise ValueError("Publish industry history with --with-current before computing industry factors")


def read_factor_inputs(
    data_root: Path, config: Path, start: dt.date, end: dt.date,
    sessions: tuple[dt.date, ...],
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Keep all historical symbols, including delisted names and missing sessions."""
    bars = read_stock_data(data_root=data_root, config=config, table="bar_1d", start=start, end=end)
    basic = read_stock_data(
        data_root=data_root, config=config, table="daily_basic", start=start, end=end,
    )
    if bars.is_empty():
        raise ValueError(f"No daily bars in {start}..{end}")
    dates = tuple(day for day in sessions if start <= day <= end)
    missing = set(dates) - set(bars["trade_date"].unique().to_list())
    if missing:
        raise ValueError(f"Entire exchange sessions missing: {sorted(missing)[:5]}")
    keys = ["symbol", "trade_date"]
    numeric = [name for name in basic.columns if name not in bars.columns]
    observed = bars.join(basic.select(*keys, *numeric), on=keys, how="left", validate="1:1")
    grid = bars.select("symbol").unique().join(
        pl.DataFrame({"trade_date": dates}, schema={"trade_date": pl.Date}), how="cross",
    )
    panel = grid.join(observed, on=keys, how="left", validate="1:1").sort(*keys)
    panel = panel.with_columns(
        *[(pl.col(name) * pl.col("adj_factor")).alias(f"adj_{name}")
          for name in ("open", "high", "low", "close")],
    )
    return panel, bars


def _folder(data_root: Path, panel_id: str, year: int) -> Path:
    return data_root / "factors" / panel_id / f"year={year}"


def check_definition(data_root: Path, panel_id: str, definition: dict[str, Any]) -> None:
    """Prevent mixing different expressions in one incrementally updated column."""
    path = data_root / "factors" / panel_id / "definition.json"
    if path.exists():
        if json.loads(path.read_text(encoding="utf-8")) != definition:
            raise ValueError(f"Definition changed for {panel_id}; use a new factor ID")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(definition, ensure_ascii=False, indent=2), encoding="utf-8")


def read_coverage(data_root: Path, panel_id: str, year: int) -> dict[str, Any]:
    folder = _folder(data_root, panel_id, year)
    info = folder / "coverage.json"
    if not info.exists() or not (folder / "data.parquet").exists():
        return {}
    return json.loads(info.read_text(encoding="utf-8"))


def panel_complete(data_root: Path, panel_id: str, year: int, start: dt.date, end: dt.date) -> bool:
    record = read_coverage(data_root, panel_id, year)
    return bool(record and record["start"] <= str(start) and record["end"] >= str(end))


def write_panel(
    data_root: Path, panel_id: str, year: int, frame: pl.DataFrame,
    start: dt.date, end: dt.date, *, known_through: dt.date | None = None,
) -> int:
    """Upsert a requested interval; retain earlier/later records in this year."""
    folder = _folder(data_root, panel_id, year)
    folder.mkdir(parents=True, exist_ok=True)
    output = folder / "data.parquet"
    info = folder / "coverage.json"
    coverage_start, coverage_end = start, end
    if output.exists():
        prior = pl.read_parquet(output).filter(~pl.col("trade_date").is_between(start, end))
        frame = pl.concat([prior, frame], how="vertical_relaxed")
        if info.exists():
            coverage = json.loads(info.read_text(encoding="utf-8"))
            old_start, old_end = dt.date.fromisoformat(coverage["start"]), dt.date.fromisoformat(coverage["end"])
            # Non-overlapping requests with a hole must not claim that hole is covered.
            if end < old_start - dt.timedelta(days=1) or start > old_end + dt.timedelta(days=1):
                raise ValueError(f"Disjoint incremental intervals for {panel_id}; recompute this year")
            coverage_start, coverage_end = min(start, old_start), max(end, old_end)
    frame = frame.sort("trade_date", "ts_code")
    if frame.select(pl.struct("trade_date", "ts_code").is_duplicated().any()).item():
        raise ValueError("Duplicate output keys")
    temporary = folder / "data.tmp.parquet"
    frame.write_parquet(temporary, compression="zstd")
    temporary.replace(output)
    info.write_text(json.dumps({"start": str(coverage_start), "end": str(coverage_end),
                                "rows": frame.height, "known_through": str(known_through)
                                if known_through else None}), encoding="utf-8")
    return frame.height
