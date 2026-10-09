"""D2: design_date / data_end / oos_start / oos_months / sample_scope for registry rows."""
from __future__ import annotations

import datetime as dt
import tomllib
from pathlib import Path


def _parse_date(value: object) -> dt.date | None:
    if value is None:
        return None
    if isinstance(value, dt.date) and not isinstance(value, dt.datetime):
        return value
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def first_oos_month(design_date: dt.date) -> str:
    """Calendar month after the design month (YYYY-MM)."""
    nxt = (design_date.replace(day=1) + dt.timedelta(days=32)).replace(day=1)
    return nxt.strftime("%Y-%m")


def months_between(start_ym: str, end: dt.date) -> int:
    year, month = map(int, start_ym.split("-"))
    start = dt.date(year, month, 1)
    if end < start:
        return 0
    return (end.year - start.year) * 12 + (end.month - start.month) + 1


def infer_design_date(settings: dict, config: Path) -> dt.date | None:
    research = settings.get("research", settings)
    for key in ("registered_on", "design_date", "registered"):
        parsed = _parse_date(research.get(key) if isinstance(research, dict) else None)
        if parsed:
            return parsed
        parsed = _parse_date(settings.get(key))
        if parsed:
            return parsed
    # Paper forward rules may pin OOS explicitly.
    try:
        mtime = dt.datetime.fromtimestamp(config.stat().st_mtime, dt.UTC).date()
    except OSError:
        return None
    return mtime


def attach_sample_fields(
    record: dict,
    *,
    settings: dict,
    config: Path,
    data_end: dt.date | None,
    as_of: dt.date | None = None,
) -> dict:
    design = infer_design_date(settings, config)
    end = data_end or _parse_date(record.get("end"))
    oos_start = None
    oos_months = None
    scope = None
    # Q10 paper forward rules: explicit oos_start month 2026-10.
    paper = settings.get("forward") or settings.get("paper") or {}
    if isinstance(paper, dict) and paper.get("oos_start"):
        oos = _parse_date(paper["oos_start"])
        if oos:
            oos_start = oos.strftime("%Y-%m")
    if design and oos_start is None:
        oos_start = first_oos_month(design)
    if design and end and design > end and oos_start is None:
        scope = "IS_ONLY"
    if design and end and design > end:
        scope = "IS_ONLY"
    clock = as_of or dt.date.today()
    if oos_start:
        # Growing OOS count uses wall-clock / paper as_of, not retrospective backtest end.
        oos_months = months_between(oos_start, clock)
        if scope is None:
            scope = "IS_ONLY" if oos_months <= 0 else "HAS_OOS"
    if design and end and design > end and scope is None:
        scope = "IS_ONLY"
    record.update(
        design_date=design.isoformat() if design else None,
        data_end=end.isoformat() if end else None,
        oos_start=oos_start,
        oos_months=oos_months,
        sample_scope=scope,
    )
    return record


def q10_oos_defaults() -> dict:
    """Acceptance anchor: Q10 oos_start=2026-10."""
    return {
        "design_date": "2026-09-12",
        "oos_start": "2026-10",
        "sample_scope": "HAS_OOS" if dt.date.today() >= dt.date(2026, 10, 1) else "IS_ONLY",
    }
