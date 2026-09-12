"""Read dated risk inputs for suspended holdings without changing research data."""
import datetime as dt
import math
from pathlib import Path

import polars as pl


_DATES = ('as_of', 'known_at', 'source_date', 'industry_valid_from', 'industry_valid_to',
          'suspension_source_date', 'capital_coverage_start', 'capital_coverage_end',
          'capital_information_cutoff')
_FLAGS = ('suspended', 'same_day_size_missing', 'normalization_pass',
          'mv_reconciliation_pass', 'close_match', 'capital_events_verified')
_TEXT = ('symbol', 'industry_l1', 'industry_raw_path', 'suspension_raw_path',
         'size_raw_path', 'daily_raw_path', 'adjustment_raw_path', 'capital_evidence_path',
         'capital_events_reason', 'market_value_unit')
_OUTPUT = {'total_market_value': pl.Float64, 'staleness_days': pl.Int64,
           'risk_estimate': pl.Boolean, 'status': pl.String, 'reason': pl.String}


def _unavailable_reason(row: dict, as_of: dt.date) -> str | None:
    source = row['source_date']
    known = row['known_at']
    if source is None or known is None or not source <= known <= as_of:
        return 'Observation or availability date is missing or later than as_of'
    if not 0 < (as_of-source).days <= 7:
        return 'Prior observation must be within 7 calendar days before as_of'
    if row['same_day_size_missing'] is not True:
        return 'Same-day size is not confirmed missing; use current controls'
    if row['suspended'] is not True or row['suspension_source_date'] != as_of:
        return 'No confirmed suspension on the signal date'
    start, end = row['industry_valid_from'], row['industry_valid_to']
    if (not row['industry_l1'] or not row['industry_l1'].strip() or start is None
            or start > as_of or (end is not None and as_of >= end)):
        return 'Historical industry interval does not cover the signal date'
    for name in ('industry_raw_path', 'suspension_raw_path', 'size_raw_path',
                 'daily_raw_path', 'adjustment_raw_path'):
        if not row[name] or not row[name].strip():
            return f'Missing source evidence: {name}'
    value = row['last_observed_total_market_value']
    if (value is None or not math.isfinite(value) or value <= 0
            or row['market_value_unit'] != 'CNY'
            or any(row[name] is not True for name in
                   ('normalization_pass', 'mv_reconciliation_pass', 'close_match'))):
        return 'Prior market capitalization lacks valid normalized CNY evidence'
    verified = row['capital_events_verified']
    if verified is not True:
        state = 'unknown' if verified is None else 'unhandled capital change'
        detail = row['capital_events_reason'] or 'No complete capital-event evidence'
        return f'Capital events {state}: {detail}'
    start, end = row['capital_coverage_start'], row['capital_coverage_end']
    cutoff = row['capital_information_cutoff']
    if (start is None or end is None or cutoff is None or start > source
            or end < as_of or cutoff != as_of or not row['capital_evidence_path']
            or not row['capital_evidence_path'].strip()):
        return 'Capital-event verification lacks complete dated coverage through as_of'
    return None


def read_held_risk_estimates(*, path: Path, as_of: dt.date,
                           symbols: list[str]) -> pl.DataFrame:
    """Read requested controls, retaining unavailable rows and their reasons.

    Derive eligibility from the saved evidence, ignoring any supplied output
    value/status. A risk estimate requires a normalized prior CNY cap within
    seven calendar days, historical industry, signal-day suspension, and complete
    capital-event evidence known by as_of. Nullable capital_events_verified
    distinguishes unknown coverage from a known unhandled event. Unavailable
    rows have null total_market_value; last_observed_total_market_value remains
    dated diagnostic evidence. Missing requested keys return no row.

    The caller independently restricts use to positive actual holdings without
    positive benchmark weights, freezes purchases and sales, and prefers complete
    current controls. This reader does not change holdings, prices or scores.
    Historical dataset publication dates stay separate from known_at, which
    follows the existing historical-membership availability rule.
    """
    if (type(as_of) is not dt.date or not isinstance(symbols, list)
            or any(not isinstance(s, str) or not s.strip() for s in symbols)
            or len(symbols) != len(set(symbols))):
        raise ValueError('Require one date and distinct nonempty requested symbols')
    frame = pl.read_parquet(path)
    required = {*_DATES, *_FLAGS, *_TEXT, 'last_observed_total_market_value'}
    if not required <= set(frame.columns):
        missing = sorted(required-set(frame.columns))
        raise ValueError(f'Missing held risk evidence columns: {missing}')
    if (any(frame.schema[k] != pl.Date for k in _DATES)
            or any(frame.schema[k] != pl.Boolean for k in _FLAGS)
            or any(frame.schema[k] != pl.String for k in _TEXT)
            or frame.schema['last_observed_total_market_value'] not in (pl.Float32, pl.Float64)
            or frame.select('symbol', 'as_of').is_duplicated().any()
            or frame.select(pl.any_horizontal(pl.col('symbol', 'as_of').is_null()).any()).item()):
        raise ValueError('Invalid held risk evidence types or duplicate/null dated keys')
    frame = frame.filter((pl.col('as_of') == as_of) & pl.col('symbol').is_in(symbols))
    rows = []
    for row in frame.iter_rows(named=True):
        reason = _unavailable_reason(row, as_of)
        source = row['source_date']
        row.update(total_market_value=row['last_observed_total_market_value'] if reason is None
                   else None, staleness_days=(as_of-source).days if source else None,
                   risk_estimate=reason is None, status='available' if reason is None
                   else 'unavailable', reason=reason or 'Verified suspended-holding risk estimate')
        rows.append(row)
    return pl.from_dicts(rows, schema={**frame.schema, **_OUTPUT}).sort('symbol')
