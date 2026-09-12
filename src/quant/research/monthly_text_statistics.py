"""The existing factor battery's monthly statistics on frozen P7 membership."""
import json
from pathlib import Path

import polars as pl

from quant.factors.forecast_text_score import DIMENSIONS
from quant.research.factor_battery_evaluation import score_factor_sections
from quant.research.factor_battery_groups import (
    assign_groups, group_returns, persistence, summarize_groups,
)
from quant.research.factor_battery_statistics import monthly_ic_summary, rank_ic_by_date


def run(panel: pl.DataFrame, *, settings: dict, output: Path) -> dict:
    """Reuse preprocessing, IC, bins and HAC without inventing daily observations or costs."""
    keys = ['symbol', 'trade_date']
    if panel.is_empty() or panel.select(keys).is_duplicated().any():
        raise ValueError('Require nonempty unique frozen monthly members')
    dates = tuple(panel['trade_date'].unique().sort().to_list())
    labels = panel.select(*keys, 'label_rebalance')
    scores, points, groups, transitions, summaries = [], [], [], [], []
    for dimension, direction in zip(DIMENSIONS, (1, -1, -1), strict=True):
        factor = f'text_{dimension}'
        scored = score_factor_sections(universe=panel,
            values=panel.select(*keys, pl.col(factor).alias('value')),
            direction=direction, settings=settings)
        scores.append(scored.with_columns(pl.lit(factor).alias('factor')))
        paired = scored.join(labels, on=keys, how='left', validate='1:1')
        for variant in settings['variants']:
            ic = rank_ic_by_date(paired, score=variant, label='label_rebalance',
                minimum_symbols=settings['minimum_symbols'],
                minimum_paired_coverage=settings['minimum_paired_coverage'])
            ic = pl.DataFrame({'trade_date': dates}).join(ic, on='trade_date', how='left',
                validate='1:1').sort('trade_date')
            cohort = assign_groups(scored, score=variant, groups=settings['groups'],
                                   minimum_symbols=settings['minimum_symbols'])
            grouped = group_returns(cohort, labels, label='label_rebalance', signal_dates=dates,
                groups=settings['groups'], minimum_paired_coverage=settings['minimum_paired_coverage'])
            transition = persistence(cohort, signal_dates=dates, groups=settings['groups'],
                                     minimum_symbols=settings['minimum_symbols'])
            identity = [pl.lit(factor).alias('factor'), pl.lit(variant).alias('variant')]
            points.append(ic.with_columns(identity))
            groups.append(grouped.with_columns(identity))
            transitions.append(transition.with_columns(identity))
            summary = monthly_ic_summary(ic['trade_date'].to_list(), ic['rank_ic'].to_list(),
                lag=settings['monthly_newey_west_lag'],
                minimum_months_per_year=settings['minimum_months_per_year'])
            summaries.append({'factor': factor, 'variant': variant, **summary,
                'coverage_sufficient': summary['months'] >= settings['admission']['minimum_months'],
                'group_statistics': summarize_groups(grouped, groups=settings['groups']),
                'mean_top_target_turnover': transition['top_target_turnover'].mean()})
    output.mkdir(parents=True, exist_ok=False)
    pl.concat(scores).write_parquet(output / 'monthly_scores.parquet')
    pl.concat(points).write_parquet(output / 'monthly_ic.parquet')
    pl.concat(groups).write_parquet(output / 'monthly_groups.parquet')
    pl.concat(transitions).write_parquet(output / 'monthly_persistence.parquet')
    result = {'conclusion': 'RESEARCH_ONLY', 'scope': 'frozen_monthly_sample_statistics',
        'minimum_symbols': settings['minimum_symbols'],
        'minimum_months': settings['admission']['minimum_months'],
        'months_on_calendar': len(dates), 'sample_rows': panel.height,
        'costs_evaluated': False, 'summary': summaries}
    (output / 'summary.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result
