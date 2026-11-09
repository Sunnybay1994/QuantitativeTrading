"""Explicit R5 frozen input binding; never changes the historical S4 placeholder."""
import datetime as dt
from bisect import bisect_right
import hashlib
import json
import math
from pathlib import Path
import tomllib

import polars as pl

from quant.research.sue_family_controls import CONTROLS
from quant.research.sue_preliminary_s4 import build_monthly_s4

IDENTIFIER = 'sue_prelim_r5_v1'
FAMILY = 'sue_preliminary_s4_v1'
PREFIX = 'registered_battery:r5:'
# Exact November 8 registration, including its actual registered_at. Copies are
# allowed; a modified/backdated definition requires a separately authorized version.
PREREGISTRATION_SHA256 = 'eb3093cb42437e7f8c93acf044a87bacc0b938789ceb33ffe72f115ebe88ec95'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def spec_at(config, now):
    if sha(config) != PREREGISTRATION_SHA256:
        raise ValueError('Require unchanged registered R5 definition SHA; no backdated registration')
    spec = tomllib.loads(Path(config).read_text(encoding='utf-8'))
    registered = dt.datetime.fromisoformat(spec['registered_at'])
    if (now.tzinfo is None or registered.tzinfo is None or registered >= now
            or now > dt.datetime.now(dt.UTC) or spec['auto_trade'] is not False
            or spec['id'] != FAMILY or spec['signal'] != 'sue_prelim'
            or tuple(spec['controls']) != CONTROLS or spec['minimum_months'] != 96
            or spec['minimum_symbols'] != 100 or spec['incremental_minimum_nw_t'] != 2.5):
        raise ValueError('Require actual post-registration time and unchanged R5 preregistration')
    return spec


def load_receipt(path):
    path = Path(path)
    row = json.loads(path.read_text(encoding='utf-8'))
    observed = dt.datetime.fromisoformat(row['observed_at'])
    spec = spec_at(row['config'], observed)
    if (row['config_sha256'] != sha(row['config']) or row['status'] != 'QUALIFIED_INPUTS'
            or row['finite_signal_months'] < spec['minimum_months']
            or row['registered_at'] != spec['registered_at']):
        raise ValueError('R5 requires qualified immutable inputs, not an all-null placeholder')
    if any(sha(p) != expected for p, expected in row['files'].items()):
        raise ValueError('R5 frozen inputs changed')
    return row


def definition_receipt(row, settings):
    path = settings.get('r5_input_receipt')
    if not path:
        raise ValueError('R5 requires explicit opt-in frozen input receipt')
    receipt = load_receipt(path)
    expected = PREFIX + sha(path) + ':' + str(Path(path).resolve())
    if any(row[k] != v for k, v in dict(id=IDENTIFIER, expr=IDENTIFIER, family=FAMILY,
                                      direction=1, source_ref=expected).items()):
        raise ValueError('R5 candidate does not match its registered definition/input SHA')
    return receipt


def attach(panel, receipt):
    inputs = load_receipt(receipt)
    income = pl.read_parquet(inputs['income'])
    history = pl.read_parquet(inputs['observations'])
    parts = []
    # SUE is univariate. Recompute only on each stock's visibility/period events,
    # then carry even null revisions until the next event. Never form a full
    # all-days x all-stocks Cartesian builder grid.
    for section in panel.select('symbol', 'trade_date').partition_by('symbol'):
        symbol = section['symbol'][0]
        preliminary = history.filter(pl.col('symbol') == symbol)
        statements = income.filter(pl.col('symbol') == symbol)
        if preliminary.is_empty():
            parts.append(section.with_columns(pl.lit(None, pl.Float64).alias(IDENTIFIER)))
            continue
        events = set(preliminary['report_period_end'].drop_nulls().to_list())
        for field in ('available_at', 'observed_at'):
            events.update(stamp.astimezone(dt.timezone(dt.timedelta(hours=8))).date()+dt.timedelta(days=1)
                          for stamp in preliminary[field].drop_nulls())
        events.update(day+dt.timedelta(days=1) for day in preliminary['announcement_date'].drop_nulls())
        events.update(day+dt.timedelta(days=1) for day in statements['available_date'].drop_nulls())
        events = sorted(events)
        representatives = {}
        for day in section['trade_date'].sort():
            representatives.setdefault(bisect_right(events, day), day)
        values = build_monthly_s4(income_history=statements, preliminary_history=preliminary,
            signal_dates=tuple(representatives.values()), candidate_symbols=(symbol,)).factors
        values = values.select('trade_date', pl.col('sue_prelim').alias(IDENTIFIER)).sort('trade_date')
        parts.append(section.sort('trade_date').join_asof(values, on='trade_date', strategy='backward'))
    return panel.join(pl.concat(parts), on=['symbol', 'trade_date'], how='left', validate='1:1')


def check_controls(panel, evaluate):
    names, missing = [], []
    for base in CONTROLS:
        name = next((c for c in (f'control_{base}_size_industry_neutral',
                    f'control_{base}_raw', base) if c in panel.columns), None)
        if name is None:
            missing.append(base)
        else:
            names.append(name)
    if missing:
        return dict(passed=False, reason='r5_frozen_controls_missing', missing=missing,
                    controls_used=names, incremental=None)
    invalid = [name for name in names if not panel[name].is_finite().fill_null(False).any()]
    if invalid:
        return dict(passed=False, reason='r5_frozen_controls_nonfinite', invalid=invalid,
                    controls_used=names, incremental=None)
    result = evaluate(panel, 'candidate', names, 1)
    value = result.get('newey_west_t')
    passed = result['months'] >= 96 and value is not None and math.isfinite(value) and value >= 2.5
    correlation = None
    if 'pit_sue8_context_v2' in panel.columns and {'symbol', 'trade_date'} <= set(panel.columns):
        from quant.research.factor_battery_statistics import rank_ic_by_date
        values = rank_ic_by_date(panel, score='candidate', label='pit_sue8_context_v2',
                                 minimum_symbols=100, minimum_paired_coverage=.95)
        values = values.filter(pl.col('rank_ic').is_finite())
        if values.height:
            correlation = values['rank_ic'].mean()
    return dict(passed=bool(passed), controls_used=names, incremental=result,
                sue_rank_correlation=correlation,
                reason=None if passed else 'r5_incremental_months_or_nw_t_failed')


def diagnostics(batch, admission_scorecard):
    """Read only this candidate's completed battery and N4, never other factors."""
    root = Path(batch)/'evaluation/statistics/factors'/IDENTIFIER
    result = dict(formal_months=None, incremental_nw_t=None, sue_rank_correlation=None,
                  january_ic=None, admission=None, diagnostic_batch=str(batch))
    path = root/'monthly_ic.parquet'
    if path.is_file():
        values = pl.read_parquet(path).filter(pl.col('variant') == 'size_industry_neutral')
        if values['trade_date'].is_duplicated().any():
            raise ValueError('R5 monthly IC has duplicate signal dates')
        values = values.filter(pl.col('rank_ic').is_finite())
        if values.height:
            result['formal_months'] = values.height
        january = values.filter(pl.col('trade_date').dt.month() == 1)
        if january.height:
            result['january_ic'] = january['rank_ic'].mean()
    rows = pl.read_parquet(admission_scorecard).filter(pl.col('factor') == IDENTIFIER)
    if rows.height != 1:
        raise ValueError('R5 diagnostics require its own unique N4 result')
    row = rows.row(0, named=True)
    family = row.get('family_controls') or {}
    incremental = family.get('incremental') or {}
    for key, value in [('incremental_nw_t', incremental.get('newey_west_t')),
                       ('sue_rank_correlation', family.get('sue_rank_correlation'))]:
        if value is not None and math.isfinite(value):
            result[key] = value
    result['admission'] = row['factor_admitted']
    result['formal_months_measured'] = result['formal_months'] is not None
    return result
