"""Preregistered stock-group sampling and worst-group training objective."""
import math

import polars as pl

from quant.research.factor_battery_statistics import monthly_ic_summary, rank_ic_by_date
from quant.data.cross_stock_sampling import stock_groups as stock_groups


def group_fitness(scored: pl.DataFrame, assignments: dict[str, int], *, config: dict,
                  complexity: int, maximum_correlation: float) -> dict:
    expected = set(range(config['sample_groups']))
    if set(assignments.values()) != expected or not math.isfinite(maximum_correlation):
        raise ValueError('Incomplete groups or nonfinite control correlation')
    if not 0 <= maximum_correlation <= 1 or complexity < 1:
        raise ValueError('Invalid search penalty inputs')
    diagnostics = []
    blocks = []
    stable = config['version'] == 'stock_time_stability_v3'
    dates = sorted(scored['trade_date'].unique().to_list())
    if stable and len(dates) != config['training_months']:
        raise ValueError('Stability search requires the complete registered training window')
    for group in sorted(expected):
        symbols = [symbol for symbol, value in assignments.items() if value == group]
        frame = scored.filter(pl.col('symbol').is_in(symbols))
        series = rank_ic_by_date(frame, score='candidate', label='label',
            minimum_symbols=config['minimum_symbols_per_month'],
            minimum_paired_coverage=config['minimum_paired_coverage'])
        stats = monthly_ic_summary(series['trade_date'].to_list(), series['rank_ic'].to_list())
        if stats['months'] < config['minimum_valid_months_per_group'] or stats['mean_ic'] is None:
            raise ValueError(f'Group {group} lacks registered valid training months')
        diagnostics.append({'group': group, **stats})
        if stable:
            # Split the calendar, not each candidate's available observations.
            # Missing early history must not silently move the test boundary.
            for block, selected in enumerate((dates[:len(dates)//2], dates[len(dates)//2:])):
                part = series.filter(pl.col('trade_date').is_in(selected))
                measured = monthly_ic_summary(part['trade_date'].to_list(), part['rank_ic'].to_list())
                if (measured['months'] < config['minimum_valid_months_per_block']
                        or measured['mean_ic'] is None):
                    raise ValueError(f'Group {group} block {block} lacks valid training months')
                blocks.append({'group': group, 'block': block, **measured})
    mean = sum(row['mean_ic'] for row in diagnostics)/len(diagnostics)
    direction = 1 if mean >= 0 else -1
    worst = min(direction*row['mean_ic'] for row in diagnostics)
    if stable:
        weakest = min(direction*row['mean_ic'] for row in blocks)
        # Correlation is a redundancy ceiling, not a large reward for noise.
        if weakest <= 0:
            raise ValueError('Nonpositive directional IC in a stock-time training block')
        if maximum_correlation >= config['maximum_control_correlation']:
            raise ValueError('Training control correlation exceeds registered ceiling')
        return {'objective': config['version'], 'direction': direction,
                'group_statistics': diagnostics, 'stock_time_statistics': blocks,
                'worst_directional_mean_ic': worst,
                'worst_stock_time_mean_ic': weakest,
                'fitness': weakest-config['complexity_penalty']*complexity}
    return {'objective': config['version'], 'direction': direction,
            'group_statistics': diagnostics, 'worst_directional_mean_ic': worst,
            'fitness': worst-config['complexity_penalty']*complexity-.5*maximum_correlation}
