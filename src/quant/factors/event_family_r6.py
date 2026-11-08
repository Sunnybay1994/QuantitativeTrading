"""Frozen R6 native-event factors; missing event coverage is never a zero signal."""
import datetime as dt
import math
import re
import statistics

import polars as pl

SIGNALS = ('repurchase_strength_30d', 'repurchase_strength_90d',
           'insider_net_buy_30d', 'insider_net_buy_90d', 'unlock_pressure_30d',
           'unlock_pressure_90d', 'holder_count_qoq', 'holder_count_yoy',
           'analyst_eps_revision_30d', 'analyst_eps_revision_90d')
SOURCES = dict(zip(SIGNALS, ('repurchase',)*2+('stk_holdertrade',)*2+
                   ('share_float',)*2+('stk_holdernumber',)*2+('report_rc',)*2))
SH = dt.timezone(dt.timedelta(hours=8))


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def day(value):
    if type(value) is dt.date:
        return value
    try:
        return dt.datetime.strptime(str(value), '%Y%m%d').date()
    except ValueError:
        return None


def latest(rows, keys):
    """Latest observable revision of each native identity, without summing copies."""
    groups = {}
    for row in rows:
        key = tuple(row.get(k) for k in keys)
        if any(v is None or v == '' for v in key):
            return None
        groups.setdefault(key, []).append(row)
    selected = []
    for values in groups.values():
        stamp = max((r['source_announcement_date'], r['known_at']) for r in values)
        candidates = [r for r in values if (r['source_announcement_date'], r['known_at']) == stamp]
        # Multiple differing records at the same publication/observation are ambiguous.
        if len({r['source_row_id'] for r in candidates}) != 1:
            return None
        selected.append(candidates[0])
    return selected


def one_signal(rows, name, as_of, market_cap):
    if not rows:
        return None
    window = 30 if name.endswith('30d') else 90
    window_rows = [r for r in rows if 0 <= (as_of-r['source_announcement_date']).days < window]
    if name.startswith('repurchase'):
        selected = latest([r for r in window_rows if r.get('proc') == '完成'
                           and day(r.get('end_date')) is not None and day(r['end_date']) <= as_of],
                          ['ts_code', 'end_date'])
        amounts = [number(r.get('amount')) for r in selected or []]
        if not amounts or any(v is None or v < 0 for v in amounts) or not market_cap or market_cap <= 0:
            return None
        return sum(amounts)/market_cap
    if name.startswith('insider'):
        selected = latest(window_rows, ['ts_code', 'source_announcement_date', 'holder_name', 'holder_type', 'in_de'])
        if not selected or not market_cap or market_cap <= 0:
            return None
        values = []
        for row in selected:
            quantity, price = number(row.get('change_vol')), number(row.get('avg_price'))
            if quantity is None or quantity < 0 or price is None or price <= 0 or row.get('in_de') not in ('IN', 'DE'):
                return None
            values.append(quantity*price*(1 if row['in_de'] == 'IN' else -1))
        return sum(values)/market_cap
    if name.startswith('unlock'):
        selected = latest(rows, ['ts_code', 'float_date', 'holder_name', 'share_type'])
        if selected is None:
            return None
        values = []
        for row in selected:
            planned = day(row.get('float_date'))
            if planned is None:
                return None
            if as_of < planned <= as_of+dt.timedelta(days=window):
                ratio = number(row.get('float_ratio'))
                if ratio is None or not 0 <= ratio <= 100:
                    return None
                values.append(ratio/100)
        return -sum(values) if values else None
    if name.startswith('holder'):
        selected = latest(rows, ['ts_code', 'end_date'])
        if not selected:
            return None
        reports = {day(r.get('end_date')): number(r.get('holder_num')) for r in selected}
        if None in reports:
            return None
        periods = sorted(p for p in reports if p <= as_of)
        if len(periods) < 2:
            return None
        current = periods[-1]
        try:
            other = periods[-2] if name.endswith('qoq') else current.replace(year=current.year-1)
        except ValueError:
            return None
        numerator, denominator = reports[current], reports.get(other)
        if numerator is None or numerator <= 0 or denominator is None or denominator <= 0:
            return None
        return -math.log(numerator/denominator)
    if name.startswith('analyst'):
        eligible = [r for r in rows if r.get('org_name') and r.get('author_name')
                    and re.fullmatch(r'\d{4}Q[1-4]', str(r.get('quarter', '')))]
        selected = latest(eligible, ['ts_code', 'org_name', 'author_name', 'quarter', 'source_announcement_date'])
        if not selected:
            return None
        series = {}
        for r in selected:
            key = (r['ts_code'], r['org_name'], r['author_name'], r['quarter'])
            series.setdefault(key, []).append(r)
        revisions = {}
        for values in series.values():
            values.sort(key=lambda r: r['source_announcement_date'])
            for before, after in zip(values, values[1:]):
                if after not in window_rows:
                    continue
                old, new = number(before.get('eps')), number(after.get('eps'))
                value = (new-old)/abs(old) if old is not None and old != 0 and new is not None else None
                revisions.setdefault(after['org_name'], []).append((after['source_announcement_date'], value))
        values = []
        for group in revisions.values():
            stamp = max(d for d, _ in group)
            newest = {v for d, v in group if d == stamp}
            if len(newest) == 1 and None not in newest:
                values.append(newest.pop())
        return statistics.median(values) if values else None
    raise ValueError('Unregistered R6 signal')


def compute(*, keys, events, name):
    """Return signal-date values only; known_at includes actual acquisition time."""
    if name not in SOURCES:
        raise ValueError('Unregistered R6 signal')
    empty = keys.select('symbol', 'trade_date').with_columns(pl.lit(None, dtype=pl.Float64).alias('value'))
    if events.is_empty() or keys.is_empty():
        return empty
    if events['known_at'].min() > dt.datetime.combine(keys['trade_date'].max(), dt.time(15), SH):
        return empty
    parts = []
    for section in keys.partition_by('trade_date'):
        date = section['trade_date'][0]
        cutoff = dt.datetime.combine(date, dt.time(15), SH)
        eligible = events.filter((pl.col('known_at') <= cutoff)
                                 & (pl.col('source_announcement_date') <= date))
        grouped = {k[0]: v.to_dicts() for k, v in eligible.partition_by('ts_code', as_dict=True).items()}
        values = [one_signal(grouped.get(r['symbol'], []), name, date, number(r['total_market_value']))
                  for r in section.iter_rows(named=True)]
        parts.append(section.select('symbol', 'trade_date').with_columns(pl.Series('value', values, dtype=pl.Float64)))
    return pl.concat(parts)
