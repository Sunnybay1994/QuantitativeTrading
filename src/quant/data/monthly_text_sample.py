"""Read-only scored cache snapshots on the full publication timeline."""
import datetime as dt
import json
from pathlib import Path
import sqlite3

import polars as pl

from quant.data.forecast_text_scores import read_corpus, asof_panel
from quant.factors.forecast_text_score import DIMENSIONS, score_key


def request_snapshot(cache: Path) -> list[dict]:
    """One committed SQLite read; never reserve or submit requests."""
    db = sqlite3.connect(cache.resolve().as_uri()+'?mode=ro',uri=True)
    db.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in db.execute('SELECT * FROM attempts ORDER BY id').fetchall()]
    finally:
        db.close()


def cache_snapshot(*, source: Path, cache: Path, settings: dict, allowed_keys: set[str]) -> tuple[pl.DataFrame, dict]:
    frame = read_corpus(source)
    attempts = request_snapshot(cache)
    latest = {r['cache_key']:r for r in attempts if r['cache_key'] in allowed_keys}
    rows = []
    for row in frame.iter_rows(named=True):
        key = score_key(row['reason_text'],settings) if row['reason_text'] else None
        result = latest.get(key,{})
        success = result.get('state') == 'success' and not row['same_day_conflict']
        scores = json.loads(result['scores_json']) if success else {}
        rows.append({**row, 'cache_state':result.get('state','unscored'),
            **{f'text_{d}':scores.get(d,{}).get('score') for d in DIMENSIONS}})
    scored_frame = pl.from_dicts(rows,schema_overrides={f'text_{d}':pl.Float64 for d in DIMENSIONS})
    return scored_frame, {'snapshot_at':dt.datetime.now(dt.timezone.utc).isoformat(),
        'total_requests':len(attempts),'charged_or_reserved_usd':sum(r['charged_usd'] for r in attempts),
        'selected_keys':len(allowed_keys),'selected_successes':sum(r['state']=='success' for r in latest.values()),
        'selected_unknown':sum(r['state']=='unknown' for r in latest.values()),
        'source_rows':frame.height,'api_calls':0}


def membership_panel(scores: pl.DataFrame, members: pl.DataFrame, *, max_age_days: int) -> pl.DataFrame:
    keys = ['symbol','trade_date']
    if members.select(keys).is_duplicated().any():
        raise ValueError('Duplicate frozen sample membership')
    events = scores.sort('symbol','publication_date','report_period').unique(
        subset=['symbol','publication_date'],keep='last',maintain_order=True).select(
            'symbol','publication_date',pl.col('input_id').alias('current_input_id'))
    checked = members.sort('trade_date').join_asof(events.sort('publication_date'),
        left_on='trade_date',right_on='publication_date',by='symbol',strategy='backward',check_sortedness=False)
    if checked.filter((pl.col('input_id') != pl.col('current_input_id')).fill_null(True)).height:
        raise ValueError('Frozen membership no longer matches latest publication')
    panel = asof_panel(scores,sorted(set(members['trade_date'])),max_age_days=max_age_days).rename({'ts_code':'symbol'})
    return members.select(keys).join(panel,on=keys,how='left',validate='1:1')
