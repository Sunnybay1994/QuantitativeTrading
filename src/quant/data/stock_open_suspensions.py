"""Versioned suspension facts for the daily model's opening-price execution."""
import datetime as dt
import math
import re

import polars as pl

POLICY = 'opening_price_0930_suspension_v1'
OPEN_SECONDS = 9*3600 + 30*60


def _seconds(text: str) -> int:
    if not re.fullmatch(r'\d{1,2}:\d{2}(?::\d{2})?', text):
        raise ValueError('Unrecognized suspension time')
    parts = [int(value) for value in text.split(':')]
    hour, minute, second = *parts[:2], parts[2] if len(parts) == 3 else 0
    if hour > 23 or minute > 59 or second > 59:
        raise ValueError('Invalid suspension time')
    return hour*3600 + minute*60 + second


def classify_open(versions: list[tuple[str, str | None]], volume: float | None) -> tuple[str, str]:
    """No daily volume inference clears an unspecified or conflicting halt."""
    variants = sorted(set(versions), key=lambda row: (str(row[0]), str(row[1])))
    if len(variants) != 1:
        return 'unknown', 'conflicting_source_records' if variants else 'missing_original_detail'
    kind, timing = variants[0]
    if kind != 'S':
        return 'unknown', 'suspension_type_not_unambiguous_S'
    if timing is None:
        if volume is not None and (not math.isfinite(volume) or volume < 0):
            return 'unknown', 'invalid_daily_volume'
        if volume is not None and volume > 0:
            return 'unknown', 'full_day_positive_volume_conflict'
        return 'halt_at_open', 'reported_full_day'
    if not timing.strip():
        return 'unknown', 'empty_timing_not_proven_full_day'
    try:
        intervals = []
        for interval in timing.split(','):
            pieces = interval.strip().split('-')
            if len(pieces) != 2:
                raise ValueError('Invalid interval')
            first, last = map(_seconds, pieces)
            if first > last:
                raise ValueError('Reversed interval')
            intervals.append((first, last))
    except (ValueError, TypeError):
        return 'unknown', 'unparsed_suspension_timing'
    # Treat a boundary touching 09:30 conservatively as blocked, never a daily-bar rescue.
    if any(first <= OPEN_SECONDS <= last for first, last in intervals):
        return 'halt_at_open', 'interval_includes_open'
    if all(first > OPEN_SECONDS for first, _ in intervals):
        return 'clear_at_open', 'all_reported_intervals_start_after_open'
    return 'unknown', 'premarket_interval_open_unestablished'


def build_open_facts(keys: pl.DataFrame, details: pl.DataFrame, bars: pl.DataFrame) -> pl.DataFrame:
    """Preserve raw variants and paths on every inherited positive suspension key."""
    if keys.select('symbol', 'trade_date').is_duplicated().any():
        raise ValueError('Duplicate inherited suspension keys')
    if bars.select('symbol', 'trade_date').is_duplicated().any():
        raise ValueError('Duplicate daily observations')
    quotes = {(r['symbol'], r['trade_date']): r['volume'] for r in bars.iter_rows(named=True)}
    grouped = {}
    for row in details.iter_rows(named=True):
        grouped.setdefault((row['symbol'], row['trade_date']), []).append(row)
    rows = []
    for symbol, day in keys.select('symbol', 'trade_date').iter_rows():
        group = grouped.get((symbol, day), [])
        variants = [(r['suspend_type'], r['suspend_timing']) for r in group]
        volume = quotes.get((symbol, day))
        status, reason = classify_open(variants, volume)
        rows.append({'symbol': symbol, 'trade_date': day, 'suspension_policy': POLICY,
            'open_status': status, 'open_reason': reason, 'observed_daily_volume': volume,
            'source_variants': len(set(variants)), 'suspend_types': sorted(set(str(v[0]) for v in variants)),
            'suspend_timings': sorted(set('<NULL>' if v[1] is None else v[1] for v in variants)),
            'source_paths': sorted(set(r['source_path'] for r in group))})
    schema = {'symbol': pl.String, 'trade_date': pl.Date, 'suspension_policy': pl.String,
        'open_status': pl.String, 'open_reason': pl.String, 'observed_daily_volume': pl.Float64,
        'source_variants': pl.Int64, 'suspend_types': pl.List(pl.String),
        'suspend_timings': pl.List(pl.String), 'source_paths': pl.List(pl.String)}
    return pl.from_dicts(rows, schema=schema).sort('trade_date', 'symbol')


def versioned_open_states(*, bars: pl.DataFrame, limits: pl.DataFrame, suspensions: pl.DataFrame,
                          sessions: list[dt.date], symbols: list[str], execution_dates: list[dt.date],
                          slippage: float):
    from quant.backtest.rules import DailyMarketState
    required = {'suspension_policy', 'open_status', 'open_reason'}
    if not required <= set(suspensions.columns):
        raise ValueError('Incomplete versioned opening suspension input')
    if suspensions.filter((pl.col('suspension_policy') != POLICY).fill_null(True)
            | ~pl.col('open_status').is_in(['halt_at_open', 'unknown']).fill_null(False)).height:
        raise ValueError('Unknown opening suspension policy or unfiltered clear rows')
    if suspensions.select('trade_date', 'symbol').is_duplicated().any():
        raise ValueError('Duplicate opening suspension keys')
    quotes = {(r['trade_date'], r['symbol']): r for r in bars.iter_rows(named=True)}
    bands = {(r['trade_date'], r['symbol']): r for r in limits.iter_rows(named=True)}
    halts = {(r['trade_date'], r['symbol']): r for r in suspensions.iter_rows(named=True)}
    order_dates = set(execution_dates)
    states = {}
    positive = lambda x: x is not None and math.isfinite(x) and x > 0
    for day in sessions:
        for symbol in symbols:
            key = day, symbol
            bar, halt = quotes.get(key), halts.get(key)
            if halt is not None and (halt['open_status'] == 'unknown' or
                    (halt['open_reason'] == 'reported_full_day' and bar is not None and positive(bar['volume']))):
                states[key] = DailyMarketState(open_unknown=True)
            elif halt is not None or bar is None or not positive(bar['volume']):
                states[key] = DailyMarketState(suspended=True)
            elif not positive(bar.get('open')):
                states[key] = DailyMarketState(open_unknown=True)
            elif day in order_dates:
                band = bands.get(key)
                if band is None or not positive(band['up_limit']) or not positive(band['down_limit']):
                    raise ValueError(f'Missing stock price band: {symbol} {day}')
                states[key] = DailyMarketState(
                    at_upper_limit=bar['open']*(1+slippage) >= band['up_limit']-1e-9,
                    at_lower_limit=bar['open']*(1-slippage) <= band['down_limit']+1e-9)
            else:
                states[key] = DailyMarketState()
    return states
