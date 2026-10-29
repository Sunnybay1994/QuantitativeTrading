"""D1's five-session coverage and date criteria; no collection or calendar refresh."""

import datetime as dt
import math
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl

from quant.data.post_close_coverage import THRESHOLDS

NOT_BEFORE = dt.date(2026, 11, 6)
SHANGHAI = ZoneInfo('Asia/Shanghai')


def _sessions(root: Path, market: str, now: dt.datetime) -> list[dt.date]:
    local = now.astimezone(SHANGHAI)
    if market == 'us':
        from quant.data.us_sessions import latest_closed, session_close

        config = root/'configs/data/us_sessions.toml'
        last = latest_closed(through=local.date(), now=now, config=config)
        opened = []
        for offset in range(41):
            day = last-dt.timedelta(days=offset)
            if session_close(day, config=config) is not None:
                opened.append(day)
            if len(opened) == 5:
                break
        opened.reverse()
    else:
        end = local.date()
        grid = [end-dt.timedelta(days=n) for n in range(40, -1, -1)]
        calendars = []
        for name in (('SH', 'SZ') if market == 'cn' else ('HK',)):
            path = root/f'data/clean/trade_calendar/market={name}/data.parquet'
            frame = pl.read_parquet(path)
            if frame.schema.get('date') != pl.Date or frame.schema.get('is_open') != pl.Boolean:
                raise ValueError(f'{name} calendar date/is_open schema invalid')
            frame = frame.filter(pl.col('date').is_between(grid[0], grid[-1])).sort('date')
            if frame['date'].to_list() != grid or frame['is_open'].null_count():
                raise ValueError(f'{name} calendar requires a unique complete 41-day grid')
            if market == 'hk' and (frame.schema.get('is_half_day') != pl.Boolean
                                    or frame['is_half_day'].null_count()):
                raise ValueError('HK calendar half-day flags missing')
            calendars.append(frame)
        opened = calendars[0].filter(pl.col('is_open'))['date'].to_list()
        if market == 'cn' and opened != calendars[1].filter(pl.col('is_open'))['date'].to_list():
            raise ValueError('SH/SZ open sessions differ')
        close = dt.time(15, 5)
        if market == 'hk':
            half = bool(calendars[0].filter(pl.col('date') == end)['is_half_day'][0])
            close = dt.time(12, 5) if half else dt.time(16, 5)
        if local.time().replace(tzinfo=None) < close:
            opened = [day for day in opened if day != end]
    if len(opened) < 5:
        raise ValueError('Fewer than five completed sessions in verified calendar window')
    return opened[-5:]


def _day(day: dt.date, matches: list[dict], floor: float) -> dict:
    result = {'date': str(day), 'passed': False, 'reason': None}
    if len(matches) != 1:
        result['reason'] = 'missing_coverage' if not matches else 'duplicate_coverage'
        return result
    row = matches[0]
    names = ('expected', 'complete', 'partial', 'missing')
    counts = [row.get(name) for name in names]
    if any(type(value) is not int or value < 0 for value in counts):
        result['reason'] = 'invalid_counts'
        return result
    expected, complete, partial, missing = counts
    result.update(zip(names, counts))
    if expected <= 0 or complete+partial+missing != expected:
        result['reason'] = 'unreconciled_counts'
        return result
    rate = complete/expected
    result['complete_rate'] = rate
    claimed = row.get('complete_rate')
    if (isinstance(claimed, bool) or not isinstance(claimed, (int, float))
            or not math.isfinite(claimed) or abs(claimed-rate) > 1e-12):
        result['reason'] = 'rate_does_not_match_counts'
    elif row.get('denominator_verified') is not True or row.get('denominator_basis') != 'pre_collection_pool':
        result['reason'] = 'full_universe_unverified'
    elif complete*100 < expected*round(floor*100):
        result['reason'] = 'below_threshold'
    else:
        result['passed'] = True
    return result


def evaluate(root: Path, rows: list[dict], now: dt.datetime) -> dict:
    if now.tzinfo is None:
        raise ValueError('D1 acceptance requires an aware timestamp')
    indexed: dict[tuple[str, dt.date], list[dict]] = {}
    rejected = []
    for position, row in enumerate(rows):
        try:
            day = dt.date.fromisoformat(row['date'])
            market = row['market']
            if market not in THRESHOLDS:
                raise ValueError('Unknown market')
            indexed.setdefault((market, day), []).append(row)
        except (KeyError, TypeError, ValueError) as exc:
            rejected.append({'row': position, 'reason': str(exc)})
    markets = {}
    for market, floor in THRESHOLDS.items():
        try:
            dates = _sessions(root, market, now)
            days = [_day(day, indexed.get((market, day), []), floor) for day in dates]
            markets[market] = {'threshold': floor, 'sessions': days,
                               'passed_sessions': sum(row['passed'] for row in days),
                               'passed': all(row['passed'] for row in days), 'calendar_error': None}
        except (OSError, KeyError, TypeError, ValueError, RuntimeError, pl.exceptions.PolarsError) as exc:
            markets[market] = {'threshold': floor, 'sessions': [], 'passed_sessions': 0,
                               'passed': False, 'calendar_error': str(exc)}
    gate = now.astimezone(SHANGHAI).date() >= NOT_BEFORE
    coverage = all(value['passed'] for value in markets.values())
    return {'scope': 'D1 coverage and calendar criteria; natural scheduler receipts and commit remain separate',
            'not_before': str(NOT_BEFORE), 'calendar_gate_met': gate,
            'required_sessions': 5, 'markets': markets, 'coverage_passed': coverage,
            'criteria_met': gate and coverage, 'rejected_rows': rejected}


def markdown(result: dict) -> list[str]:
    lines = ['', '## D1 five-session coverage criteria', '',
             f"Not before {result['not_before']}; date gate={result['calendar_gate_met']}; "
             f"coverage={result['coverage_passed']}; criteria_met={result['criteria_met']}.",
             'Natural scheduler receipts and commit are separately required.', '',
             '| market | date | complete / expected | passed | reason |',
             '|---|---|---:|---|---|']
    for market, value in result['markets'].items():
        if value['calendar_error']:
            error = value['calendar_error'].replace('|', '/').replace('\n', ' ')
            lines.append(f'| {market} | unknown | unknown | False | {error} |')
        for day in value['sessions']:
            lines.append(f"| {market} | {day['date']} | {day.get('complete', '?')} / "
                         f"{day.get('expected', '?')} | {day['passed']} | {day['reason'] or ''} |")
    if result['rejected_rows']:
        lines.append(f"Rejected non-session rows: {len(result['rejected_rows'])} (details in JSON).")
    return lines
