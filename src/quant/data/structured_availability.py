"""D2 first-observation bounds, native units and immutable revision identity."""
import datetime as dt
from pathlib import Path

import polars as pl

from quant.data.structured_events import normalize
from quant.data.structured_native_rows import native_row_id

UTC = dt.timezone.utc
SH = dt.timezone(dt.timedelta(hours=8))


def sessions(data_root):
    frame = pl.read_parquet(Path(data_root)/'clean/trade_calendar/market=SH/data.parquet')
    if (frame.is_empty() or frame.schema['date'] != pl.Date or frame.schema['is_open'] != pl.Boolean
            or frame['date'].null_count() or frame['date'].is_duplicated().any()
            or frame['is_open'].null_count()
            or frame.height != (frame['date'].max()-frame['date'].min()).days+1):
        raise ValueError('Invalid exchange calendar')
    return sorted(frame.filter(pl.col('is_open'))['date'])


def release_at(day, rule, calendar):
    if rule['availability'] == 'next_exchange_session_09':
        following = next((d for d in calendar if d > day), None)
        if following is None:
            raise ValueError('Calendar cannot establish next exchange session')
        return dt.datetime.combine(following, dt.time(9), SH)
    if rule['availability'] == 'report_next_calendar_day_0915':
        return dt.datetime.combine(day+dt.timedelta(days=1), dt.time(9, 15), SH)
    if rule['availability'] == 'announcement_next_calendar_day_00':
        return dt.datetime.combine(day+dt.timedelta(days=1), dt.time(), SH)
    raise ValueError('Unknown configured availability rule')


def due_dates(as_of, now, rule, calendar, lookback):
    if now.tzinfo is None or as_of > now.astimezone(SH).date():
        raise ValueError('Require actual zoned observation and no future target')
    end = min(as_of, now.astimezone(SH).date())
    days = [end-dt.timedelta(days=i) for i in reversed(range(lookback+40))]
    eligible = [d for d in days if release_at(d, rule, calendar) <= now]
    if rule['cadence'] == 'daily':
        eligible = [d for d in eligible if d in calendar]
    return eligible[-lookback:]


def normalize_increment(frame, *, table, rule, observed_at, raw_path, calendar):
    if frame.is_empty():
        return frame
    required = {'ts_code', rule['date_field'], *rule['revision_keys']}
    if not required <= set(frame.columns):
        raise ValueError(f'Missing native revision keys for {table}: {sorted(required-set(frame.columns))}')
    result = normalize(frame, table=table, rule=rule, observed_at=observed_at, raw_path=raw_path)
    if result['source_announcement_date'].null_count() or result['ts_code'].null_count():
        raise ValueError('Missing native source date or symbol; cannot invent arrival')
    entity = [native_row_id({key: row[key] for key in rule['revision_keys']})
              for row in frame.iter_rows(named=True)]
    dates = result['source_announcement_date'].to_list()
    releases = [release_at(day, rule, calendar).astimezone(UTC) for day in dates]
    result = result.with_columns(pl.Series('source_entity_id', entity),
        pl.Series('release_available_at', releases, dtype=pl.Datetime('us', 'UTC')),
        pl.lit(rule['units']).alias('native_units'), pl.lit(rule['scope']).alias('source_scope'))
    # Downloaded in 2026 never becomes usable in 2019 merely because ann_date is old.
    result = result.with_columns(pl.max_horizontal('observed_at', 'release_available_at').alias('available_at'))
    for col in {'fund_share': ['fd_share'], 'margin_detail': ['rzye', 'rqye', 'rzrqye'],
                'share_float': ['float_share'], 'repurchase': ['amount', 'vol']}.get(table, []):
        if col not in result.columns:
            raise ValueError(f'Missing native unit field: {table}.{col}')
        invalid = result.filter(pl.col(col).is_not_null() & (
            ~pl.col(col).cast(pl.Float64, strict=False).is_finite().fill_null(False)
            | (pl.col(col).cast(pl.Float64, strict=False) < 0)
            | ((pl.col(col).cast(pl.Float64, strict=False) == 0) if col == 'fd_share' else pl.lit(False))))
        if invalid.height:
            raise ValueError(f'Invalid native unit values: {table}.{col}')
    return result


def read_versions(*, data_root, table, known_at, latest=False):
    """Read D2 revision versions; only observations actually known at the cutoff."""
    if known_at.tzinfo is None:
        raise ValueError('Require zoned knowledge cutoff')
    if latest and table == 'stk_holdertrade':
        raise ValueError('Transaction dates absent from default holder-trade response; retain all native versions')
    files = sorted((Path(data_root)/'clean'/table).glob('snapshot=d2_*/data.parquet'))
    if not files:
        return pl.DataFrame()
    frame = pl.concat([pl.scan_parquet(p).filter(pl.col('available_at') <= known_at).collect()
                       for p in files], how='diagonal_relaxed')
    frame = frame.sort('observed_at').unique('source_row_id', keep='first', maintain_order=True)
    if latest and frame.group_by('source_entity_id', 'source_raw_path').len().filter(pl.col('len') > 1).height:
        raise ValueError('Ambiguous simultaneous native records; cannot infer a revision winner')
    return (frame.sort('available_at').unique('source_entity_id', keep='last', maintain_order=True)
            if latest else frame)
