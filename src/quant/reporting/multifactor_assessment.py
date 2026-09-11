"""Calendar-aware model risk and the frozen multi-factor admission conditions."""
import calendar
import datetime as dt
import math

import polars as pl

from quant.reporting.cycle_stress import path_statistics


def calendar_years(start: dt.date, end: dt.date) -> float:
    if end < start:
        raise ValueError('Calendar duration cannot be negative')
    def anniversary(years: int) -> dt.date:
        year = start.year+years
        return dt.date(year, start.month, min(start.day, calendar.monthrange(year, start.month)[1]))
    whole = end.year-start.year
    if anniversary(whole) > end:
        whole -= 1
    low, high = anniversary(whole), anniversary(whole+1)
    return whole+(end-low).days/(high-low).days


def underwater_calendar(nav: pl.DataFrame, *, start: dt.date) -> dict:
    if nav.is_empty() or nav['date'].to_list() != sorted(set(nav['date'])):
        raise ValueError('Underwater duration requires ordered unique NAV dates')
    peak, peak_date = 1., start
    longest = {'years': 0., 'peak_date': None, 'end_date': None, 'recovered': None}
    underwater = False
    for date, value in nav.select('date', 'unit_nav').iter_rows():
        if not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0 or date < peak_date:
            raise ValueError('Invalid NAV for calendar underwater duration')
        recovered = value >= peak
        if value < peak or underwater:
            duration = calendar_years(peak_date, date)
            if duration > longest['years']:
                longest = {'years': duration, 'peak_date': peak_date, 'end_date': date, 'recovered': recovered}
        if recovered:
            peak, peak_date, underwater = value, date, False
        else:
            underwater = True
    return longest


def assess_model(*, nav: pl.DataFrame, one: dict, two: dict, benchmarks: dict[str, pl.DataFrame],
                 model: dict, windows: list[dict]) -> dict:
    walk, rules = model['walk_forward'], model['admission']
    start, end = walk['test_start'], walk['test_end']
    if set(benchmarks) != set(rules['benchmarks']):
        raise ValueError('Require the three registered benchmarks')
    if len(windows) != 4 or len({window['name'] for window in windows}) != 4:
        raise ValueError('Require four distinct registered stress windows')
    risk = path_statistics(nav, start=start, end=end)
    for metric in ('cagr', 'sharpe', 'max_drawdown'):
        if not math.isclose(risk[metric], one[metric], rel_tol=1e-8, abs_tol=1e-10):
            raise ValueError('Replay metrics differ from the full report window')
    benchmark_rows = []
    for name, baseline in benchmarks.items():
        if baseline.filter(pl.col('date').is_between(start, end))['date'].to_list() != nav['date'].to_list():
            raise ValueError('Model and benchmark session grids differ')
        window = baseline.filter(pl.col('date').is_between(start, end))
        invested = window.select((pl.col('market_value')/pl.col('equity')).mean()).item() if 'market_value' in window.columns else None
        benchmark_rows.append({'benchmark': name, 'mean_invested_fraction': invested,
                               **path_statistics(baseline, start=start, end=end)})
    strongest = sorted(benchmark_rows, key=lambda row: (-row['cagr'], row['benchmark']))[0]
    baseline = benchmarks[strongest['benchmark']]
    annual, shocks = [], []
    for year in range(start.year, end.year+1):
        low, high = max(start, dt.date(year, 1, 1)), min(end, dt.date(year, 12, 31))
        strategy = path_statistics(nav, start=low, end=high)
        reference = path_statistics(baseline, start=low, end=high)
        annual.append({'year': year, 'start': low, 'end': high,
            'model_return': strategy['total_return'], 'benchmark_return': reference['total_return'],
            'outperformed': strategy['total_return'] > reference['total_return']})
    for window in windows:
        if not start <= window['start'] <= window['end'] <= end:
            raise ValueError('The full registered stress window must be covered')
        strategy = path_statistics(nav, start=window['start'], end=window['end'])
        reference = path_statistics(baseline, start=window['start'], end=window['end'])
        shocks.append({'window': window['name'], 'start': window['start'], 'end': window['end'],
            'model_return': strategy['total_return'], 'benchmark_return': reference['total_return'],
            'model_max_drawdown': strategy['max_drawdown'], 'benchmark_max_drawdown': reference['max_drawdown'],
            'not_worse': strategy['total_return'] >= reference['total_return']
                         and abs(strategy['max_drawdown']) <= abs(reference['max_drawdown'])})
    invested = nav.filter(pl.col('market_value') > 0)
    active_start = invested['date'].min() if invested.height else None
    active_years = calendar_years(active_start, end) if active_start else 0.
    underwater = underwater_calendar(nav, start=start)
    annual_win = sum(row['outperformed'] for row in annual)/len(annual)
    stress_wins = sum(row['not_worse'] for row in shocks)
    excess = one['cagr']-strongest['cagr']
    checks = {
        'net_excess': excess >= rules['minimum_net_cagr_excess_strongest_benchmark'],
        'double_cost_positive': two['cagr'] > rules['minimum_2x_cagr_exclusive'],
        'sharpe': one['sharpe'] >= rules['minimum_1x_sharpe'],
        'turnover': one['annualized_one_way_turnover'] <= rules['maximum_annualized_one_way_turnover'],
        'drawdown': abs(one['max_drawdown']) <= abs(strongest['max_drawdown'])*rules[
            'maximum_drawdown_relative_to_strongest_benchmark'],
        'underwater': underwater['years'] <= rules['maximum_underwater_calendar_years'],
        'stress_windows': len(shocks) == 4 and stress_wins >= rules['minimum_stress_windows_not_worse'],
        'annual_outperformance': annual_win >= rules['minimum_annual_outperformance_fraction'],
        'active_evidence': active_years > rules['minimum_active_evidence_calendar_years_exclusive'],
    }
    conclusion = ('PAPER_CANDIDATE' if all(checks.values()) else
                  'RESEARCH_ONLY' if not checks['active_evidence'] else 'REJECTED')
    return {'conclusion': conclusion, 'checks': checks, 'strongest_benchmark': strongest['benchmark'],
        'net_cagr_excess': excess, 'annual_outperformance_fraction': annual_win,
        'stress_windows_not_worse': stress_wins, 'active_start': active_start, 'active_years': active_years,
        'underwater': underwater, 'risk': risk, 'benchmarks': benchmark_rows, 'annual': annual, 'stress': shocks}
