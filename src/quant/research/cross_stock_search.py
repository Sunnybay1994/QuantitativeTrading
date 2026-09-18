"""Preregistered stock-group sampling and worst-group training objective."""
import hashlib
import math

import polars as pl

from quant.research.factor_battery_statistics import monthly_ic_summary, rank_ic_by_date


def stock_groups(symbols: list[str], *, groups: int, per_group: int, seed: int) -> dict[str, int]:
    if groups < 2 or per_group < 100:
        raise ValueError('Cross-stock search requires multiple groups with at least 100 stocks each')
    ordered = sorted(set(symbols), key=lambda symbol: (
        hashlib.sha256(f'{seed}:{symbol}'.encode('utf-8')).hexdigest(), symbol))
    if len(ordered) < groups*per_group:
        raise ValueError('Insufficient distinct stocks for disjoint training groups')
    return {symbol: index//per_group for index, symbol in enumerate(ordered[:groups*per_group])}


def group_fitness(scored: pl.DataFrame, assignments: dict[str, int], *, config: dict,
                  complexity: int, maximum_correlation: float) -> dict:
    expected = set(range(config['sample_groups']))
    if set(assignments.values()) != expected or not math.isfinite(maximum_correlation):
        raise ValueError('Incomplete groups or nonfinite control correlation')
    if not 0 <= maximum_correlation <= 1 or complexity < 1:
        raise ValueError('Invalid search penalty inputs')
    diagnostics = []
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
    mean = sum(row['mean_ic'] for row in diagnostics)/len(diagnostics)
    direction = 1 if mean >= 0 else -1
    worst = min(direction*row['mean_ic'] for row in diagnostics)
    return {'objective': config['version'], 'direction': direction,
            'group_statistics': diagnostics, 'worst_directional_mean_ic': worst,
            'fitness': worst-config['complexity_penalty']*complexity-.5*maximum_correlation}
