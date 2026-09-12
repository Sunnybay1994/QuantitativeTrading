"""Calendar-aware model risk and the frozen multi-factor admission conditions."""
import calendar
import datetime as dt
import math
from typing import Any

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
    longest: dict[str, Any] = {'years': 0., 'peak_date': None, 'end_date': None, 'recovered': None}
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


def holding_metrics(nav: pl.DataFrame, trades: pl.DataFrame, *, initial_cash: float) -> dict:
    """Keep entry costs and every subsequent cash session, using prior equity turnover."""
    if (nav.is_empty() or not nav['date'].is_sorted() or nav['date'].n_unique() != nav.height
            or nav.select('date', 'unit_nav', 'equity', 'market_value').null_count().sum_horizontal().item()
            or not nav['unit_nav'].is_finite().all() or (nav['unit_nav'] <= 0).any()
            or not math.isfinite(initial_cash) or initial_cash <= 0
            or not nav['equity'].is_finite().all() or (nav['equity'] <= 0).any()
            or not nav['market_value'].is_finite().all() or (nav['market_value'] < 0).any()):
        raise ValueError('Holding metrics require complete ordered account NAV')
    if (trades['date'].null_count() or trades['notional'].null_count()
            or not trades['notional'].is_finite().all() or (trades['notional'] < 0).any()):
        raise ValueError('Trades require nonnegative finite notional')
    if trades.filter(~pl.col('date').is_in(nav['date'].implode())).height:
        raise ValueError('Trade dates outside saved NAV')
    active = nav.filter(pl.col('market_value') > 0)
    start = active['date'].min() if active.height else None
    initial = nav.filter(pl.col('date') < start) if start else nav
    cash = {'start': initial['date'].min(), 'end': initial['date'].max(), 'sessions': initial.height,
            'total_return': float(initial['unit_nav'][-1]) - 1 if initial.height else None}
    base = {'active_start': start, 'report_end': nav['date'][-1], 'initial_cash_period': cash,
            'measurement': 'first_stock_holding_through_report_end_including_later_cash'}
    if start is None:
        return {**base, 'cagr': None, 'sharpe': None, 'max_drawdown': None, 'total_return': None,
                'annualized_one_way_turnover': None, 'mean_invested_fraction': None,
                'sessions': 0, 'cash_sessions_after_entry': 0}
    assert isinstance(start, dt.date)
    window = nav.filter(pl.col('date') >= start)
    denominators = nav.select('date', pl.col('equity').shift(1).fill_null(initial_cash).alias('prior_equity'))
    amounts = trades.filter(pl.col('date') >= start).group_by('date').agg(pl.col('notional').sum())
    daily = denominators.filter(pl.col('date') >= start).join(amounts, on='date', how='left')
    turnover = daily.select((pl.col('notional').fill_null(0)/(2*pl.col('prior_equity'))).sum()).item()
    return {**base, **path_statistics(nav, start=start, end=nav['date'][-1]),
            'annualized_one_way_turnover': turnover * 252/window.height,
            'mean_invested_fraction': window.select((pl.col('market_value')/pl.col('equity')).mean()).item(),
            'cash_sessions_after_entry': window.filter(pl.col('market_value') == 0).height}


def assess_model(*, nav: pl.DataFrame, one: dict, two: dict, benchmarks: dict[str, pl.DataFrame],
                 model: dict, windows: list[dict]) -> dict:
    walk, rules = model['walk_forward'], model['admission']
    end = walk['test_end']
    if set(benchmarks) != set(rules['benchmarks']) or not benchmarks:
        raise ValueError('Require all explicitly selected return indexes')
    if not windows or len({window['name'] for window in windows}) != len(windows):
        raise ValueError('Require distinct registered stress windows')
    for baseline in benchmarks.values():
        if {'equity', 'market_value', 'cash'} & set(baseline.columns):
            raise ValueError('Stock benchmarks must be return indexes, not account replays')
        if baseline.filter(pl.col('date').is_between(walk['test_start'], end))['date'].to_list() != nav['date'].to_list():
            raise ValueError('Model and benchmark session grids differ')
    for window in windows:
        if not walk['test_start'] <= window['start'] <= window['end'] <= end:
            raise ValueError('The full registered stress window must be covered')
    invested = nav.filter(pl.col('market_value') > 0)
    start = invested['date'].min() if invested.height else None
    annual, shocks = [], []
    if start is None:
        return {'conclusion': 'RESEARCH_ONLY', 'checks': {'active_evidence': False},
                'evidence_status': 'no_stock_holdings', 'strongest_benchmark': None,
                'net_cagr_excess': None, 'annual_outperformance_fraction': None,
                'stress_windows_not_worse': 0, 'stress_windows_applicable': 0,
                'stress_windows_total': len(windows), 'active_start': None, 'active_years': 0.,
                'underwater': None, 'risk': None, 'benchmarks': [], 'annual': [],
                'stress': [{'window': w['name'], 'start': w['start'], 'end': w['end'],
                            'applicable': False, 'reason': 'no_stock_holdings', 'not_worse': None}
                           for w in windows]}
    assert isinstance(start, dt.date)
    risk = path_statistics(nav, start=start, end=end)
    for metric in ('cagr', 'sharpe', 'max_drawdown'):
        if not math.isclose(risk[metric], one[metric], rel_tol=1e-8, abs_tol=1e-10):
            raise ValueError('Metrics differ from the actual holding window')
    benchmark_rows = [{'benchmark': name, 'mean_invested_fraction': None,
                       **path_statistics(baseline, start=start, end=end)}
                      for name, baseline in benchmarks.items()]
    strongest = sorted(benchmark_rows, key=lambda row: (-row['cagr'], row['benchmark']))[0]
    baseline = benchmarks[strongest['benchmark']]
    for year in range(start.year, end.year+1):
        low, high = max(start, dt.date(year, 1, 1)), min(end, dt.date(year, 12, 31))
        strategy = path_statistics(nav, start=low, end=high)
        reference = path_statistics(baseline, start=low, end=high)
        annual.append({'year': year, 'start': low, 'end': high,
            'model_return': strategy['total_return'], 'benchmark_return': reference['total_return'],
            'outperformed': strategy['total_return'] > reference['total_return']})
    exposure = nav.with_columns(((pl.col('market_value') > 0)
        | (pl.col('market_value').shift(1).fill_null(0) > 0)).alias('exposed'))
    for window in windows:
        part = exposure.filter(pl.col('date').is_between(window['start'], window['end']))
        covered = part.height > 0 and part['date'][0] >= start
        applicable = covered and part['exposed'].any()
        row = {'window': window['name'], 'start': window['start'], 'end': window['end'],
               'applicable': bool(applicable), 'not_worse': None}
        if not applicable:
            row['reason'] = 'before_holding_window' if not covered else 'cash_only_window'
        else:
            strategy = path_statistics(nav, start=window['start'], end=window['end'])
            reference = path_statistics(baseline, start=window['start'], end=window['end'])
            row.update(model_return=strategy['total_return'], benchmark_return=reference['total_return'],
                model_max_drawdown=strategy['max_drawdown'], benchmark_max_drawdown=reference['max_drawdown'],
                not_worse=strategy['total_return'] >= reference['total_return']
                and abs(strategy['max_drawdown']) <= abs(reference['max_drawdown']))
        shocks.append(row)
    active_years = calendar_years(start, end)
    before = nav.filter(pl.col('date') < start)
    anchor = before['unit_nav'][-1] if before.height else 1.
    underwater = underwater_calendar(nav.filter(pl.col('date') >= start).with_columns(
        (pl.col('unit_nav')/anchor).alias('unit_nav')), start=start)
    annual_win = sum(row['outperformed'] for row in annual)/len(annual)
    stress_wins = sum(row['not_worse'] is True for row in shocks)
    excess = one['cagr']-strongest['cagr']
    checks = {
        'net_excess': excess >= rules['minimum_net_cagr_excess_strongest_benchmark'],
        'double_cost_positive': two['cagr'] is not None and two['cagr'] > rules['minimum_2x_cagr_exclusive'],
        'sharpe': one['sharpe'] >= rules['minimum_1x_sharpe'],
        'turnover': one['annualized_one_way_turnover'] <= rules['maximum_annualized_one_way_turnover'],
        'drawdown': abs(one['max_drawdown']) <= abs(strongest['max_drawdown'])*rules[
            'maximum_drawdown_relative_to_strongest_benchmark'],
        'underwater': underwater['years'] <= rules['maximum_underwater_calendar_years'],
        'stress_windows': stress_wins >= rules['minimum_stress_windows_not_worse'],
        'annual_outperformance': annual_win >= rules['minimum_annual_outperformance_fraction'],
        'active_evidence': active_years > rules['minimum_active_evidence_calendar_years_exclusive'],
    }
    conclusion = ('PAPER_CANDIDATE' if all(checks.values()) else
                  'RESEARCH_ONLY' if not checks['active_evidence'] else 'REJECTED')
    return {'conclusion': conclusion, 'checks': checks, 'strongest_benchmark': strongest['benchmark'],
        'net_cagr_excess': excess, 'annual_outperformance_fraction': annual_win,
        'stress_windows_not_worse': stress_wins, 'stress_windows_total': len(windows),
        'stress_windows_applicable': sum(row['applicable'] for row in shocks),
        'active_start': start, 'active_years': active_years, 'underwater': underwater,
        'risk': risk, 'benchmarks': benchmark_rows, 'annual': annual, 'stress': shocks}
