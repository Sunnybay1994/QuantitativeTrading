"""Fixed same/other-calendar-month family; signal computation, never admission.

At a completed month-end, predict the NEXT month using target-month lags 13..60.
ANN uses 24/36/48/60, NANN the remaining 44 months, AMN their difference.
NANN is an unsigned mean with registered direction -1; ANN and AMN use +1.
Require a common complete 48-month cohort, no missing-month compression.
"""
import bisect
import datetime as dt

import numpy as np
import polars as pl

SEASONALITY_NAMES = tuple(f'return_seasonality_{name}_y2_5' for name in ('ann', 'nann', 'amn'))
CONTROL_NAMES = ('return_mean_all_y2_5', 'return_compounded_y2_5')
ALL_LAGS = tuple(range(13, 61))
ANNUAL_LAGS = (24, 36, 48, 60)
SCHEMA = {'symbol': pl.String, 'trade_date': pl.Date, 'effective_date': pl.Date,
          'target_month': pl.Date, 'window_start_month': pl.Date, 'window_end_month': pl.Date,
          **dict.fromkeys((*SEASONALITY_NAMES, *CONTROL_NAMES), pl.Float64),
          'valid_same_months': pl.Int64, 'valid_other_months': pl.Int64, 'status': pl.String}


def _month(day):
    return day.year * 12 + day.month - 1


def _date(month):
    return dt.date(month // 12, month % 12 + 1, 1)


def _ordered(dates, label):
    if not dates or any(type(d) is not dt.date for d in dates) or tuple(dates) != tuple(sorted(set(dates))):
        raise ValueError(f'{label} must contain unique increasing dates')


def _ends(sessions):
    _ordered(sessions, 'sessions')
    # A following exchange session in a different month proves completion.
    ends = tuple(a for a, b in zip(sessions, sessions[1:]) if _month(a) != _month(b))
    if any(_month(b) - _month(a) != 1 for a, b in zip(ends, ends[1:])):
        raise ValueError('Exchange calendar cannot skip whole months')
    return ends


def _validate(frame, numeric):
    required = ['symbol', 'trade_date', *numeric]
    if not set(required) <= set(frame.columns):
        raise ValueError('Missing required input columns')
    if frame.schema['trade_date'] != pl.Date or frame.schema['symbol'] != pl.String:
        raise ValueError('Expected Date and String observation keys')
    if frame.select(pl.any_horizontal(pl.col(c).is_null() for c in ['symbol', 'trade_date']).any()).item():
        raise ValueError('Null observation keys')
    if frame.filter(pl.col('symbol') == '').height or frame.select('symbol', 'trade_date').is_duplicated().any():
        raise ValueError('Empty symbol or duplicate observation keys')
    if any(not frame.schema[c].is_numeric() for c in numeric):
        raise ValueError('Expected numeric return/price columns')


def calendar_month_returns(bars: pl.DataFrame, *, sessions: tuple[dt.date, ...]) -> pl.DataFrame:
    """Exact common exchange endpoints; invalid endpoint poisons both adjacent returns.

    Caller supplies the FULL exchange calendar including the following session.
    Entire unobserved months remain explicit nulls. No previous-price backfill.
    Historical reconstructed adjustment factors are not an audited wealth index.
    """
    ends = _ends(sessions)
    _validate(bars, ['close', 'adj_factor', 'volume'])
    if not set(bars['trade_date'].to_list()) <= set(sessions):
        raise ValueError('Observation outside supplied exchange calendar')
    schema = {'symbol': pl.String, 'trade_date': pl.Date, 'monthly_return': pl.Float64}
    if bars.is_empty():
        return pl.DataFrame(schema=schema)
    ends = tuple(d for d in ends if d <= bars['trade_date'].max())
    if not ends:
        return pl.DataFrame(schema=schema)
    grid = pl.DataFrame({'symbol': bars['symbol'].unique().sort()}).join(
        pl.DataFrame({'trade_date': ends}), how='cross')
    data = grid.join(bars.select('symbol', 'trade_date', 'close', 'adj_factor', 'volume'),
                     on=['symbol', 'trade_date'], how='left', validate='1:1').sort('symbol', 'trade_date')
    valid = pl.all_horizontal(pl.col(c).is_finite() & (pl.col(c) > 0)
                              for c in ['close', 'adj_factor', 'volume'])
    data = data.with_columns(pl.when(valid).then(pl.col('close') * pl.col('adj_factor'))
                            .otherwise(None).alias('_level'))
    data = data.with_columns((pl.col('_level') / pl.col('_level').shift(1).over('symbol') - 1).alias('_return'))
    return data.select('symbol', 'trade_date', pl.when(pl.col('_return').is_finite() & (pl.col('_return') >= -1))
                       .then(pl.col('_return')).otherwise(None).alias('monthly_return'))


def compute_return_seasonality(monthly: pl.DataFrame, *, sessions: tuple[dt.date, ...],
                               signal_dates: tuple[dt.date, ...]) -> pl.DataFrame:
    """Calculate the whole registered family, controls and missingness together.

    Monthly inputs may extend beyond signal dates, but every used month is at least
    13 months before the next target month. All signals use the same 48 valid months.
    With this identical cohort, historical market demeaning only shifts every
    stock's score by a common date-specific constant (no rank change).
    """
    ends = _ends(sessions)
    _ordered(signal_dates, 'signal_dates')
    _validate(monthly, ['monthly_return'])
    if not set(monthly['trade_date'].to_list()) <= set(ends):
        raise ValueError('Monthly returns must have actual completed exchange month-end dates')
    if not set(signal_dates) <= set(ends):
        raise ValueError('Signal dates must be completed exchange month ends')
    if monthly.is_empty():
        return pl.DataFrame(schema=SCHEMA)
    frame = monthly.with_columns((pl.col('trade_date').dt.year() * 12 + pl.col('trade_date').dt.month() - 1)
                                  .alias('_month')).pivot(on='_month', index='symbol', values='monthly_return').sort('symbol')
    symbols = frame['symbol'].to_list()
    columns = {int(c): frame[c].to_numpy().astype(float) for c in frame.columns if c != 'symbol'}
    empty = np.full(len(symbols), np.nan)
    same_mask = np.array([lag in ANNUAL_LAGS for lag in ALL_LAGS])
    result = []
    for signal in signal_dates:
        target = _month(signal) + 1
        returns = np.column_stack([columns.get(target - lag, empty) for lag in ALL_LAGS])
        valid = np.isfinite(returns) & (returns >= -1)
        same_count, other_count = valid[:, same_mask].sum(axis=1), valid[:, ~same_mask].sum(axis=1)
        complete = (same_count == 4) & (other_count == 44)
        # Mask invalid values before arithmetic; incomplete rows never publish a partial estimate.
        returns = np.where(valid, returns, np.nan)
        ann, nann = (returns[:, same_mask] / 4).sum(axis=1), (returns[:, ~same_mask] / 44).sum(axis=1)
        all_mean = (returns / 48).sum(axis=1)
        with np.errstate(over='ignore', invalid='ignore'):
            compounded = np.prod(1 + returns, axis=1) - 1
        arrays = [ann, nann, ann - nann, all_mean, compounded]
        finite_output = np.isfinite(np.column_stack(arrays)).all(axis=1)
        status = ['ok' if ok and finite else 'invalid_numeric_result' if ok else
                  'insufficient_history' if target - 60 < min(columns) else 'incomplete_months'
                  for ok, finite in zip(complete, finite_output)]
        complete &= finite_output
        columns_out = {name: [float(v) if ok and np.isfinite(v) else None for v, ok in zip(array, complete)]
                       for name, array in zip((*SEASONALITY_NAMES, *CONTROL_NAMES), arrays)}
        effective = sessions[bisect.bisect_right(sessions, signal)]
        result.append(pl.DataFrame({'symbol': symbols, 'trade_date': [signal] * len(symbols),
            'effective_date': [effective] * len(symbols), 'target_month': [_date(target)] * len(symbols),
            'window_start_month': [_date(target - 60)] * len(symbols),
            'window_end_month': [_date(target - 13)] * len(symbols), **columns_out,
            'valid_same_months': same_count, 'valid_other_months': other_count, 'status': status}, schema=SCHEMA))
    return pl.concat(result).sort('symbol', 'trade_date')
