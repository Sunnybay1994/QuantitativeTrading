"""Continuous B93 risk, calendar-year and preregistered shock-window statistics."""

import argparse
import datetime as dt
import json
import math
import statistics
import tomllib
from pathlib import Path
from typing import Any

import polars as pl

from quant.data.etf_research_inputs import read_etf_research_inputs


def path_statistics(nav: pl.DataFrame, *, start: dt.date, end: dt.date) -> dict[str, Any]:
    """Slice actual holdings/NAV without resetting wealth at the window boundary."""
    nav = nav.sort('date')
    if (nav.is_empty() or nav['date'].n_unique() != nav.height
            or nav.filter(~pl.col('unit_nav').is_finite() | (pl.col('unit_nav') <= 0)).height
            or nav['unit_nav'].null_count() or start > end):
        raise ValueError('Invalid continuous NAV')
    window = nav.filter(pl.col('date').is_between(start, end))
    if window.is_empty():
        raise ValueError('Empty risk window')
    previous = nav.filter(pl.col('date') < start)
    base = float(previous['unit_nav'][-1]) if previous.height else 1.0
    dates = [previous['date'][-1] if previous.height else None, *window['date'].to_list()]
    values = [base, *window['unit_nav'].to_list()]
    returns = [b / a - 1 for a, b in zip(values, values[1:])]
    peak, peak_index, worst, trough_index, worst_peak_index = base, 0, 0.0, 0, 0
    underwater, longest = 0, 0
    for i, value in enumerate(values[1:], 1):
        if value >= peak:
            peak, peak_index, underwater = value, i, 0
        else:
            underwater += 1
            longest = max(longest, underwater)
        drawdown = value / peak - 1
        if drawdown < worst:
            worst, trough_index, worst_peak_index = drawdown, i, peak_index
    recovery_index = (next((i for i in range(trough_index + 1, len(values))
                           if values[i] >= values[worst_peak_index]), None) if worst < 0 else None)
    daily_index = min(range(len(returns)), key=returns.__getitem__)
    five = [(values[i] / values[i-5] - 1, i) for i in range(5, len(values))]
    worst_five = min(five) if five else None
    sigma = statistics.stdev(returns) if len(returns) > 1 else 0.0
    tail = sorted(returns)[:max(1, math.ceil(len(returns) * .05))]
    return {
        'first': window['date'][0], 'last': window['date'][-1], 'sessions': len(returns),
        'starting_unit_nav': base, 'ending_unit_nav': values[-1],
        'total_return': values[-1] / base - 1,
        'cagr': (values[-1] / base) ** (252 / len(returns)) - 1,
        'sharpe': statistics.mean(returns) / sigma * math.sqrt(252) if sigma else 0.0,
        'max_drawdown': worst, 'worst_day': returns[daily_index],
        'worst_day_date': dates[daily_index+1],
        'worst_5_sessions': worst_five[0] if worst_five else None,
        'worst_5_sessions_end': dates[worst_five[1]] if worst_five else None,
        'expected_shortfall_95': statistics.mean(tail),
        'longest_underwater_sessions': longest,
        'max_drawdown_peak_date': dates[worst_peak_index] if worst < 0 else None,
        'max_drawdown_peak_is_initial_capital': worst < 0 and dates[worst_peak_index] is None,
        'max_drawdown_trough_date': dates[trough_index] if worst < 0 else None,
        'max_drawdown_recovery_date': dates[recovery_index] if recovery_index is not None else None,
        'trough_to_recovery_sessions': recovery_index-trough_index if recovery_index is not None else None,
        'unrecovered_at_end': worst < 0 and recovery_index is None,
    }


def benchmark_regimes(bars: pl.DataFrame) -> pl.DataFrame:
    """Assign today's return using yesterday's observable benchmark trend."""
    prices = bars.sort('trade_date').select('trade_date', 'close').with_columns(
        pl.col('close').rolling_mean(200).alias('mean200'))
    return prices.with_columns(
        pl.when((pl.col('close') > pl.col('mean200'))
                & (pl.col('mean200') > pl.col('mean200').shift(20))).then(pl.lit('bull'))
        .when((pl.col('close') < pl.col('mean200'))
              & (pl.col('mean200') < pl.col('mean200').shift(20))).then(pl.lit('bear'))
        .otherwise(pl.lit('transition')).shift(1).alias('regime')
    ).select(pl.col('trade_date').alias('date'), 'regime')


def analyze(*, run: Path, config: Path, data_root: Path, output: Path) -> dict[str, Any]:
    settings = tomllib.loads(config.read_text(encoding='utf-8'))
    protocol = settings['cycle_validation']
    report = json.loads((run / 'report.json').read_text(encoding='utf-8'))
    if report['hypothesis_id'] != settings['research']['hypothesis_id']:
        raise ValueError('Config differs from source experiment')
    expected = {(1, c, m) for c in ('top50', 'three_factor', '510300') for m in (.5, 1., 2.)}
    if {(r['fold'], r['comparison'], r['cost_multiplier']) for r in report['results']} != expected:
        raise ValueError('Require all nine full-cycle replay cases')
    navs, trades, rejected = (pl.read_parquet(run / f'{name}.parquet') for name in ('nav', 'trades', 'rejections'))
    if navs['fold'].unique().to_list() != [1]:
        raise ValueError('Expected one continuous test period')
    fold = settings['walk_forward']['folds'][0]
    start, end = fold['test_start'], fold['test_end']
    bars, _, _, _ = read_etf_research_inputs(data_root, ['510300.SH'], settings['data']['warmup_start'], end)
    regimes = benchmark_regimes(bars)
    total, years, windows, attribution = [], [], [], []
    daily_frames = []
    for comparison in ('top50', 'three_factor', '510300'):
        for multiplier in (.5, 1., 2.):
            mask = (pl.col('comparison') == comparison) & (pl.col('cost_multiplier') == multiplier)
            nav = navs.filter(mask).sort('date')
            fills, rejects = trades.filter(mask), rejected.filter(mask)
            labels = dict(comparison=comparison, cost_multiplier=multiplier)
            summary = path_statistics(nav, start=start, end=end)
            original = next(r for r in report['results'] if r['comparison'] == comparison and r['cost_multiplier'] == multiplier)
            for key in ('total_return', 'cagr', 'sharpe', 'max_drawdown'):
                if not math.isclose(summary[key], original[key], rel_tol=1e-9, abs_tol=1e-10):
                    raise ValueError(f'Continuous metrics differ from replay: {comparison} {key}')
            total.append({**labels, **summary, 'annualized_one_way_turnover': original['annualized_one_way_turnover'],
                'rejected_orders': rejects.height, 'trade_count': fills.height,
                'rejections_by_reason': rejects.group_by('side', 'reason').len().sort('side', 'reason').to_dicts(),
                'delisting_writeoff': nav['delisting_writeoff'].sum()})
            for year in range(start.year, end.year+1):
                years.append({**labels, 'year': year, **path_statistics(nav, start=dt.date(year, 1, 1),
                    end=min(end, dt.date(year, 12, 31)))})
            for window in protocol['stress_windows']:
                lo, hi = window['start'], window['end']
                window_rejects = rejects.filter(pl.col('date').is_between(lo, hi))
                windows.append({**labels, 'window': window['name'], **path_statistics(nav, start=lo, end=hi),
                    'rejected_orders': window_rejects.height,
                    'rejections_by_reason': window_rejects.group_by('side', 'reason').len().sort('side', 'reason').to_dicts()})
            daily = nav.with_columns((pl.col('unit_nav') / pl.col('unit_nav').shift(1).fill_null(1.) - 1).alias('return'))
            daily = daily.join(regimes, on='date', how='left', validate='1:1')
            if daily['regime'].null_count():
                raise ValueError('Missing benchmark regime')
            for (regime,), group in daily.partition_by('regime', as_dict=True).items():
                attribution.append({**labels, 'regime': regime, 'sessions': group.height,
                    'mean_daily_return': group['return'].mean(), 'negative_day_fraction': (group['return'] < 0).mean()})
            daily_frames.append(daily)
    result = dict(source_run=str(run), config=str(config), conclusion=report['conclusion'],
        total=total, calendar_years=years, stress_windows=windows, regimes=attribution,
        factor_diagnostics=report['factor_diagnostics'],
        definitions={'expected_shortfall_95': 'mean of worst ceil(5% * sessions) daily returns',
            'window_start': 'previous actual NAV; no rebalance, liquidation or capital reset at window boundary',
            'regime': 'previous completed 510300 close versus 200-session mean and its 20-session slope; attribution only',
            'turnover_denominator': 'original test initial cash, consistent with source replay',
            'training': 'fixed-formula diagnostics, not a fitted model or fresh untouched historical sample'})
    output.mkdir(parents=True, exist_ok=False)
    (output / 'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    pl.DataFrame(years).write_csv(output / 'calendar_years.csv')
    pl.DataFrame(windows).drop('rejections_by_reason').write_csv(output / 'stress_windows.csv')
    pl.concat(daily_frames).write_parquet(output / 'continuous_nav_with_regimes.parquet')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = analyze(**vars(args))
    print(json.dumps({'output': str(args.output), 'cases': len(result['total']),
                      'window_cases': len(result['stress_windows'])}))


if __name__ == '__main__':
    main()
