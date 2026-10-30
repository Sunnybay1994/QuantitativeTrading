"""Read actual S4 tables and labels; never turn declared dates into coverage."""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import re

import polars as pl

FAMILIES = ('repurchase', 'insider_trading')


def _inside(root: Path, value: str) -> Path:
    path = Path(value)
    path = (path if path.is_absolute() else root/path).resolve()
    if not path.is_relative_to(root):
        raise ValueError('event artifact path is outside project')
    return path


def _months(start: dt.date, end: dt.date) -> list[str]:
    current, result = start.replace(day=1), []
    while current <= end:
        result.append(current.strftime('%Y-%m'))
        current = (current.replace(year=current.year+1, month=1) if current.month == 12
                   else current.replace(month=current.month+1))
    return result


def evaluate(root: Path, today: dt.date) -> dict:
    root = root.resolve()
    candidates = sorted(p for p in (root/'artifacts/data').glob('events_v0_*')
                        if p.is_dir() and re.fullmatch(r'events_v0_\d{4}-\d{2}-\d{2}', p.name))
    enabled = (root/'configs/research/event_family_v1.toml').exists() or bool(candidates)
    result = dict(enabled=enabled, tables={}, errors=[], sample={}, ledger={},
                  required_start='2019-01-01', required_end=today.isoformat(),
                  coverage_met=False, automated_checks_met=False)
    if not enabled:
        return result
    errors = result['errors']
    if not candidates:
        errors.append('S4 event summary missing')
        return result
    summary_path = candidates[-1]/'summary.json'
    result['summary'] = str(summary_path)
    expected = set(_months(dt.date(2019, 1, 1), today))
    rows_by_key = {}
    try:
        summary = json.loads(summary_path.read_text(encoding='utf-8'))
        start = dt.date.fromisoformat(summary['start'])
        end = dt.date.fromisoformat(summary['end'])
        if start > end:
            raise ValueError('event request date range is reversed')
        result.update(requested_start=start.isoformat(), requested_end=end.isoformat(),
                      stopped=summary.get('stopped'))
        for family in FAMILIES:
            declared = summary['tables'][family]
            path = _inside(root, declared['path'])
            frame = pl.read_parquet(path)
            required = {'announcement_id', 'family', 'published', 'known_at', 'parse_status'}
            if not required.issubset(frame.columns):
                raise ValueError(f'{family}: missing event columns')
            if frame.schema['published'] != pl.Date or frame.schema['known_at'] != pl.Date:
                raise ValueError(f'{family}: PIT columns must be dates')
            rows = frame.to_dicts()
            months = sorted({r['published'].strftime('%Y-%m') for r in rows if r['published']})
            unresolved = sum(r['parse_status'] == 'unresolved' for r in rows)
            pit_invalid = sum(r['known_at'] is None or r['published'] is None
                or r['known_at'] < r['published'] or r['known_at'] > today for r in rows)
            invalid = sum(r['family'] != family or r['parse_status'] not in ('parsed', 'unresolved')
                          or not r['announcement_id'] for r in rows)
            duplicate = 0
            for row in rows:
                key = (family, row['announcement_id'])
                duplicate += key in rows_by_key
                rows_by_key[key] = row
            stats = dict(path=str(path), rows=len(rows), unresolved=unresolved,
                unresolved_ratio=unresolved/len(rows) if rows else None, months=months,
                missing_months=sorted(expected-set(months)), pit_invalid=pit_invalid,
                invalid_rows=invalid, duplicate_keys=duplicate,
                sha256=hashlib.sha256(path.read_bytes()).hexdigest())
            result['tables'][family] = stats
            if (declared['rows'] != len(rows) or declared['unresolved'] != unresolved
                    or declared['months'] != months):
                errors.append(f'{family}: summary does not match table contents')
            if pit_invalid or invalid or duplicate:
                errors.append(f'{family}: invalid PIT rows or event identities')
        sample_path = _inside(root, summary['sample_path'])
        with sample_path.open(encoding='utf-8-sig', newline='') as stream:
            sample = list(csv.DictReader(stream))
        keys = [(row.get('family'), row.get('announcement_id')) for row in sample]
        matches = sum(row.get('human_label') == 'match' for row in sample)
        labeled = sum(row.get('human_label') in ('match', 'mismatch') for row in sample)
        sample_valid = len(sample) >= 50 and len(set(keys)) == len(keys) and all(k in rows_by_key for k in keys)
        result['sample'] = dict(rows=len(sample), labeled=labeled, reported_matches=matches,
            reported_accuracy=matches/len(sample) if sample else None,
            identities_verified=sample_valid, human_authorship_verified=None,
            note='Label contents are reported; this automated check cannot establish a human review.')
        if not sample_valid or labeled != len(sample) or matches/len(sample) < .95:
            errors.append('S4 requires 50 unique in-table labels with reported accuracy >=95%')
    except (OSError, ValueError, TypeError, KeyError, pl.exceptions.PolarsError) as exc:
        errors.append(type(exc).__name__+': '+str(exc))
    ledger_path = root/'artifacts/research/llm_ledger'/f'{today:%Y-%m}.jsonl'
    try:
        calls = [json.loads(line) for line in ledger_path.read_text(encoding='utf-8').splitlines() if line.strip()]
        if not all(isinstance(row, dict) for row in calls):
            raise ValueError('event ledger lines must be JSON objects')
        calls = [r for r in calls if r.get('task') == 'event_extract' and r.get('kind') != 'pricing_adjustment']
        amounts = [float(row.get('usd') or 0) for row in calls]
        if any(not math.isfinite(amount) or amount <= 0 for amount in amounts):
            raise ValueError('event calls require finite positive USD')
        usd = sum(amounts)
        result['ledger'] = dict(path=str(ledger_path), calls=len(calls), usd=usd, budget_usd=5.)
        if usd > 5.:
            errors.append('S4 monthly event extraction spend exceeds $5')
    except (OSError, ValueError, TypeError) as exc:
        errors.append('event ledger: '+str(exc))
    result['coverage_met'] = (len(result['tables']) == 2
        and all(not row['missing_months'] for row in result['tables'].values())
        and result.get('stopped') is None
        and result.get('requested_start', '9999') <= '2019-01-01'
        and result.get('requested_end', '') >= today.isoformat())
    if not result['coverage_met']:
        errors.append('S4 verified 2019-to-current event coverage remains incomplete')
    result['automated_checks_met'] = not errors
    return result


def markdown(result: dict) -> list[str]:
    if not result.get('enabled'):
        return []
    lines = ['', '## S4 event evidence', '',
             '| family | rows | unresolved | first month | last month | missing months |',
             '|---|---:|---:|---|---|---:|']
    for name, row in result['tables'].items():
        months = row['months']
        lines.append(f"| {name} | {row['rows']} | {row['unresolved']} | "
                     f"{months[0] if months else None} | {months[-1] if months else None} | {len(row['missing_months'])} |")
    lines.append('Human labels are reported contents; human review is not established by this automated check.')
    lines.extend('- '+error for error in result['errors'])
    return lines
