"""Descriptive IC comparisons across saved search keys, labels and time windows."""
import json
from pathlib import Path

import polars as pl

from quant.research.factor_battery_statistics import monthly_ic_summary, rank_ic_by_date


def summarize_series(frame: pl.DataFrame) -> dict:
    frame = frame.sort('trade_date')
    return {**monthly_ic_summary(frame['trade_date'].to_list(), frame['rank_ic'].to_list()),
            'first_signal': str(frame['trade_date'].min()) if frame.height else None,
            'last_signal': str(frame['trade_date'].max()) if frame.height else None,
            'median_paired_stocks': frame['paired_count'].median() if frame.height else None}


def compare_sample(sample: pl.DataFrame, scores: pl.DataFrame, labels: pl.DataFrame,
                   monthly: pl.DataFrame) -> dict:
    keys = ['symbol', 'trade_date']
    if sample.is_empty() or sample.select(keys).is_duplicated().any():
        raise ValueError('Search sample requires nonempty unique date/symbol keys')
    joined = sample.select(*keys, 'label').join(scores.select(*keys, 'raw'), on=keys,
                                               how='left', validate='1:1').join(
        labels.select(*keys, 'label_rebalance'), on=keys, how='left', validate='1:1')
    both = joined.filter(pl.col('label').is_finite() & pl.col('label_rebalance').is_finite())
    comparisons = {}
    for name, label, coverage in [('saved_search_labels', 'label', .8),
                                  ('battery_labels_same_coverage', 'label_rebalance', .8),
                                  ('battery_labels_battery_coverage', 'label_rebalance', .95)]:
        comparisons[name] = summarize_series(rank_ic_by_date(joined, score='raw', label=label,
                                        minimum_symbols=100, minimum_paired_coverage=coverage))
    dates = sample['trade_date'].unique().sort()
    raw = monthly.filter(pl.col('variant') == 'raw')
    windows = {'before_search': raw.filter(pl.col('trade_date') < dates.min()),
               'search_dates': raw.filter(pl.col('trade_date').is_in(dates.implode())),
               'after_search': raw.filter(pl.col('trade_date') > dates.max()),
               'other_dates_inside_span': raw.filter(pl.col('trade_date').is_between(dates.min(), dates.max())
                   & ~pl.col('trade_date').is_in(dates.implode()))}
    return {'status': 'complete', 'search_key_rows': sample.height,
            'battery_score_available_rows': joined.filter(pl.col('raw').is_finite()).height,
            'finite_label_pairs': both.height,
            'label_difference_over_1e_12_rows': both.filter(
                (pl.col('label')-pl.col('label_rebalance')).abs() > 1e-12).height,
            'search_keys_with_battery_scores': comparisons,
            'all_battery_stocks_by_window': {name: summarize_series(frame) for name, frame in windows.items()},
            'interpretation': 'Descriptive, not additive causal attribution. Battery scores use full-universe preprocessing; observed post-search data is not independent validation.'}


def batch_diagnostics(run: Path, statistics: Path) -> dict:
    search_path, sample_path = run/'N2/search.json', run/'N2/monthly_sample.parquet'
    if not search_path.exists() or not sample_path.exists():
        return {}
    candidates = json.loads(search_path.read_text(encoding='utf-8'))['candidates']
    sample = pl.read_parquet(sample_path)
    labels = pl.concat([pl.read_parquet(path) for path in sorted((statistics/'inputs').glob('*/monthly_labels.parquet'))])
    result = {}
    for candidate in candidates:
        factor = candidate['factor_id']
        folder = statistics/'factors'/factor
        scores = pl.read_parquet(folder/'monthly_scores.parquet')
        monthly = pl.read_parquet(folder/'monthly_ic.parquet')
        result[factor] = compare_sample(sample, scores, labels, monthly)
    return result
