"""R5 preliminary SUE adapter; preserves the frozen SUE formula and native basis."""
from __future__ import annotations

import datetime as dt
import hashlib
from pathlib import Path

import polars as pl

from quant.factors.earnings_surprise import compute_sue8
from quant.research.pit_quality_research import PITQualitySignalResult

SH = dt.timezone(dt.timedelta(hours=8))
SCHEMA = {
    'symbol': pl.String, 'announcement_date': pl.Date, 'report_period_end': pl.Date,
    'available_at': pl.Datetime('us', 'UTC'), 'observed_at': pl.Datetime('us', 'UTC'),
    'source_table': pl.String, 'source_row_id': pl.String, 'source_raw_path': pl.String,
    'update_flag': pl.String, 'native_profit_min': pl.Float64,
    'native_profit_max': pl.Float64, 'native_net_income': pl.Float64,
    'last_parent_net': pl.Float64, 'point_cny': pl.Float64,
    'parent_point_cny': pl.Float64, 'basis_evidence': pl.String,
    'input_reason': pl.String,
}


def _number(frame, name):
    value = pl.col(name).cast(pl.Float64, strict=False) if name in frame.columns else pl.lit(None, pl.Float64)
    return pl.when(value.is_finite()).then(value).otherwise(None)


def normalize(frame: pl.DataFrame, table: str) -> pl.DataFrame:
    """Generic supplier net income is never silently relabeled as parent income."""
    required = {'ts_code', 'ann_date', 'end_date', 'available_at', 'observed_at',
                'source_row_id', 'source_raw_path'}
    if table not in ('forecast', 'express') or not required <= set(frame.columns):
        raise ValueError('R5 native schema/provenance missing')
    for name in ('available_at', 'observed_at'):
        dtype = frame.schema[name]
        if not isinstance(dtype, pl.Datetime) or dtype.time_zone is None:
            raise ValueError('R5 requires timezone-aware native arrival times')
    def date(name):
        return (pl.col(name).str.to_date('%Y%m%d', strict=False)
                if frame.schema[name] == pl.String else pl.col(name).cast(pl.Date))
    low, high = _number(frame, 'net_profit_min'), _number(frame, 'net_profit_max')
    net = _number(frame, 'n_income')
    point = (low / 2 + high / 2) * 10000 if table == 'forecast' else net
    # These explicit native fields are a supported future contract, not fields
    # synthesized from today's generic forecast/express profit observations.
    parent = ((_number(frame, 'parent_net_profit_min_10000cny') / 2
               + _number(frame, 'parent_net_profit_max_10000cny') / 2) * 10000
              if table == 'forecast' else _number(frame, 'n_income_attr_p'))
    evidence = ('native:parent_net_profit_min/max_10000cny' if table == 'forecast'
                else 'native:n_income_attr_p')
    parent_reversed = (pl.lit(False) if table == 'express' else
                       _number(frame, 'parent_net_profit_min_10000cny')
                       > _number(frame, 'parent_net_profit_max_10000cny'))
    part = frame.select(
        pl.col('ts_code').alias('symbol'), date('ann_date').alias('announcement_date'),
        date('end_date').alias('report_period_end'),
        pl.col('available_at').cast(SCHEMA['available_at']),
        pl.col('observed_at').cast(SCHEMA['observed_at']),
        pl.lit(table).alias('source_table'), 'source_row_id', 'source_raw_path',
        (pl.col('update_flag').cast(pl.String) if 'update_flag' in frame.columns
         else pl.lit(None, pl.String)).alias('update_flag'),
        low.alias('native_profit_min'), high.alias('native_profit_max'),
        net.alias('native_net_income'), _number(frame, 'last_parent_net').alias('last_parent_net'),
        point.alias('point_cny'), parent.alias('parent_point_cny'),
        pl.when(parent.is_finite()).then(pl.lit(evidence)).otherwise(None).alias('basis_evidence'),
        parent_reversed.alias('_parent_reversed'),
    )
    return part.with_columns(
        pl.when(pl.col('available_at').is_null() | pl.col('observed_at').is_null()
                | (pl.col('available_at') < pl.col('observed_at')))
        .then(pl.lit('invalid_arrival'))
        .when(pl.col('announcement_date').is_null() | pl.col('report_period_end').is_null()
              | pl.col('source_row_id').is_null() | pl.col('source_raw_path').is_null())
        .then(pl.lit('invalid_native_key'))
        .when(~pl.col('symbol').str.contains(r'^[0-9]{6}\.(SH|SZ)$').fill_null(False))
        .then(pl.lit('outside_frozen_SH_SZ_universe'))
        .when((pl.col('native_profit_min') > pl.col('native_profit_max')) | pl.col('_parent_reversed'))
        .then(pl.lit('reversed_profit_range'))
        .when(~pl.col('point_cny').is_finite().fill_null(False))
        .then(pl.lit('missing_native_profit'))
        .when(~pl.col('parent_point_cny').is_finite().fill_null(False))
        .then(pl.lit('parent_profit_basis_unverified'))
        .otherwise(pl.lit('usable')).alias('input_reason')
    ).select(list(SCHEMA)).cast(SCHEMA)


def read_inputs(data_root: Path, *, known_at: dt.datetime):
    """Read only published D1/D2 versions, retaining actual first observations."""
    if known_at.tzinfo is None:
        raise ValueError('Require zoned knowledge cutoff')
    frames, manifest = [], []
    for table in ('forecast', 'express'):
        for summary in sorted((data_root / 'clean' / table).glob('snapshot=*/summary.json')):
            files = sorted(summary.parent.glob('year=*/data.parquet'))
            flat = summary.parent / 'data.parquet'
            if flat.is_file():
                files.append(flat)
            for path in [summary, *files]:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                manifest.append({'path': str(path), 'sha256': digest})
                if path == summary:
                    continue
                native = pl.read_parquet(path)
                if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                    raise ValueError('R5 published input changed during read')
                frame = normalize(native, table)
                # Invalid arrival rows remain quarantined evidence, never signals.
                frame = frame.filter((pl.col('observed_at') <= known_at)
                                     | pl.col('observed_at').is_null())
                frames.append(frame)
    result = pl.concat([pl.DataFrame(schema=SCHEMA), *frames], how='vertical')
    # Same content observed later is not a new revision. A corrupt first arrival
    # remains in evidence rather than being repaired by a later observation.
    result = result.sort('observed_at', nulls_last=False).unique(
        ['source_table', 'source_row_id'], keep='first', maintain_order=True)
    return result, manifest


def visible_inputs(history: pl.DataFrame, date: dt.date) -> pl.DataFrame:
    cutoff = dt.datetime.combine(date, dt.time(), SH)
    return history.filter((pl.col('available_at') < cutoff) & (pl.col('observed_at') < cutoff)
                          & (pl.col('available_at') >= pl.col('observed_at'))
                          & (pl.col('announcement_date') < date))


def select_points(history: pl.DataFrame, date: dt.date) -> pl.DataFrame:
    """Never choose a different version/older period to rescue a missing point."""
    visible = visible_inputs(history, date)
    if visible.is_empty():
        return visible
    visible = visible.filter(pl.col('report_period_end') == pl.col('report_period_end').max().over('symbol'))
    keys = ['symbol', 'report_period_end', 'source_table']
    visible = visible.filter(pl.col('announcement_date') == pl.col('announcement_date').max().over(keys))
    visible = visible.filter(pl.col('available_at') == pl.col('available_at').max().over(keys))
    visible = visible.with_columns(
        pl.when(pl.len().over(keys) > 1).then(pl.lit('ambiguous_latest_revision'))
        .when(pl.col('report_period_end') > date).then(pl.lit('period_not_ended'))
        .otherwise(pl.col('input_reason')).alias('input_reason'))
    visible = visible.with_columns(
        pl.when((pl.col('input_reason') == 'ambiguous_latest_revision').any().over('symbol'))
        .then(pl.lit('ambiguous_latest_revision')).otherwise(pl.col('input_reason')).alias('input_reason'))
    # Keep one rejected evidence row for simultaneous conflicts; no winner scored.
    visible = visible.sort('source_row_id').unique(keys, keep='first')
    visible = visible.with_columns(
        ((pl.col('input_reason') == 'usable').cast(pl.Int8) * 2
         + (pl.col('source_table') == 'express').cast(pl.Int8)).alias('_priority'))
    return visible.sort('_priority', descending=True).unique('symbol', keep='first').drop('_priority')


def score_point(selected_income: pl.DataFrame, point: dict) -> tuple[float | None, str]:
    """Insert one preliminary current period into the unchanged SUE8 kernel."""
    if point['input_reason'] != 'usable':
        return None, point['input_reason']
    symbol, period = point['symbol'], point['report_period_end']
    income = selected_income.filter(pl.col('symbol') == symbol)
    if income.filter(pl.col('end_date') >= period).height:
        return None, 'final_report_already_visible'
    if income.is_empty():
        return None, 'missing_income_chain'
    groups = income.select('report_type', 'comp_type').unique()
    if groups.height != 1:
        return None, 'ambiguous_income_basis'
    current = pl.DataFrame({'symbol': [symbol], 'end_date': [period],
                           'report_type': groups['report_type'], 'comp_type': groups['comp_type'],
                           'n_income_attr_p': [point['parent_point_cny']]})
    values = income.select(current.columns)
    result = compute_sue8(pl.concat([values, current], how='vertical_relaxed'))
    score = result.filter(pl.col('end_date') == period)['pit_sue8'].item()
    import math
    return (float(score), 'VALID') if score is not None and math.isfinite(score) else (None, 'missing_or_constant_seasonal_chain')


def build_monthly_s4(*, income_history, preliminary_history, signal_dates, candidate_symbols):
    """Explicit R5 adapter; frozen pre-R5 placeholder/production consumers unchanged."""
    from quant.research.monthly_sue_family import _latest_selected
    factors, eligibility, quarantine = [], [], []
    for date in signal_dates:
        points = select_points(preliminary_history, date)
        selected = pl.DataFrame()
        if points.filter(pl.col('input_reason') == 'usable').height:
            selected, selection = _latest_selected(income_history, date)
            quarantine.extend(selection.quarantined.to_dicts())
        by_symbol = {r['symbol']: r for r in points.iter_rows(named=True)}
        for symbol in candidate_symbols:
            point = by_symbol.get(symbol)
            value, reason = score_point(selected, point) if point else (None, 'no_visible_preliminary_input')
            period = point['report_period_end'] if point else None
            factors.append(dict(symbol=symbol, trade_date=date, financial_period_end=period, sue_prelim=value))
            eligibility.append(dict(symbol=symbol, as_of=date, financial_period_end=period,
                                    factor='sue_prelim', status='VALID' if value is not None else 'SAMPLE_INSUFFICIENT',
                                    input_reason=reason, source_row_id=point['source_row_id'] if point else None))
    return PITQualitySignalResult(
        factors=pl.DataFrame(factors, schema={'symbol': pl.String, 'trade_date': pl.Date,
                            'financial_period_end': pl.Date, 'sue_prelim': pl.Float64}),
        eligibility=pl.from_dicts(eligibility, infer_schema_length=None),
        quarantined=pl.from_dicts(quarantine) if quarantine else pl.DataFrame())
