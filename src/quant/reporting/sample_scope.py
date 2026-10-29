"""D2: design_date / data_end / oos_start / oos_months / sample_scope for registry rows."""
from __future__ import annotations

import datetime as dt
import hashlib
import tomllib
from pathlib import Path


def _parse_date(value: object) -> dt.date | None:
    if value is None:
        return None
    if isinstance(value, dt.date) and not isinstance(value, dt.datetime):
        return value
    try:
        text = str(value)
        return dt.date.fromisoformat(text+'-01' if len(text) == 7 else text[:10])
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
    return_dates=None,
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
    record.update(
        design_date=design.isoformat() if design else None,
        data_end=end.isoformat() if end else None,
        oos_start=oos_start,
        oos_months=oos_months,
        sample_scope=scope,
    )
    return refresh_sample_fields(record, return_dates=return_dates, as_of=as_of)


def refresh_sample_fields(record: dict, *, return_dates=None, as_of=None) -> dict:
    """Count observed return months after this experiment's own frozen design.

    Historical admission metrics and a live forward account are separate
    evidence. A name, an inherited anchor or passage of time proves no OOS.
    """
    design = frozen_design_date(record) or _parse_date(record.get('design_date'))
    end = _parse_date(record.get('data_end')) or _parse_date(record.get('end'))
    if design is None:
        return record
    earliest = first_oos_month(design)
    explicit = _parse_date(record.get('oos_start'))
    start = max(earliest, explicit.strftime('%Y-%m')) if explicit else earliest
    stop = min(end, as_of) if end and as_of else end
    months, scope = None, 'OOS_UNVERIFIED'
    if stop and stop < _parse_date(start):
        months, scope = 0, 'IS_ONLY'
    elif stop:
        if return_dates is None:
            return_dates = saved_return_dates(record)
        if return_dates is not None:
            observed = {_parse_date(day) for day in return_dates}
            months = len({day.strftime('%Y-%m') for day in observed
                          if day and _parse_date(start) <= day <= stop and day > design})
            scope = 'HAS_OOS' if months else 'IS_ONLY'
    record.update(design_date=design.isoformat(),data_end=end.isoformat() if end else None, oos_start=start,
                  oos_months=months, sample_scope=scope)
    return record


def frozen_design_date(record: dict):
    """Prefer an explicit date in the registered, hash-matching frozen config."""
    config = Path(record.get('config_path') or '')
    if not config.is_file() or config.suffix != '.toml' or not record.get('config_sha256'):
        return None
    payload = config.read_bytes()
    if hashlib.sha256(payload).hexdigest() != record['config_sha256']:
        return None
    settings = tomllib.loads(payload.decode('utf-8'))
    research = settings.get('research', settings)
    for key in ('registered_on','design_date','registered'):
        day = _parse_date(research.get(key)) or _parse_date(settings.get(key))
        if day:
            return day
    return None


def saved_return_dates(record: dict):
    """Read existing 1x NAV observations; never borrow another strategy's forward ledger."""
    import polars as pl
    run = Path(record.get('run_path') or '.')
    variant = record.get('variant')
    if not isinstance(variant, str) or Path(variant).is_absolute() or '..' in Path(variant).parts:
        return None
    folder = run/variant/'cost_1'
    paths = sorted(folder.glob('????/nav.parquet')) or list(folder.glob('nav.parquet'))
    if not paths:
        return None
    nav = pl.concat([pl.read_parquet(path, columns=['date','unit_nav']) for path in paths],
                    how='vertical_relaxed').sort('date')
    if nav['date'].is_duplicated().any():
        raise ValueError('Duplicate NAV dates cannot establish sample scope')
    # A first NAV level alone is not a realized return observation.
    return nav.filter(pl.col('unit_nav').is_finite() & (pl.col('unit_nav') > 0)
        & pl.col('unit_nav').shift(1).is_finite() & (pl.col('unit_nav').shift(1) > 0))['date'].to_list()


def q10_oos_defaults() -> dict:
    """Acceptance anchor: Q10 oos_start=2026-10."""
    return {
        "design_date": "2026-09-12",
        "oos_start": "2026-10",
        "sample_scope": "IS_ONLY",
    }
