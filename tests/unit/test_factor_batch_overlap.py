import datetime as dt

import polars as pl
import pytest

from quant.research.factor_batch_overlap import compare_candidate, overlap_summary


def test_overlap_retains_unqualified_peers_and_deterministic_tie():
    pairs = pl.DataFrame({'factor': ['new']*3, 'variant': ['raw']*3, 'peer': ['B', 'A', 'C'],
        'comparison_qualified': [True, True, False], 'mean_absolute_rank_correlation': [.8, .8, .99],
        'months': [100, 101, 20], 'median_common_symbols': [200, 201, 202]})
    row = overlap_summary(pairs, .7).row(0, named=True)
    assert row['closest_factor'] == 'A'
    assert row['overlapping_peer_count'] == 2
    assert row['library_peer_count'] == 3 and row['insufficient_history_peer_count'] == 1
    missing = overlap_summary(pairs.with_columns(pl.lit(False).alias('comparison_qualified')), .7)
    assert missing['maximum_mean_absolute_rank_correlation'][0] is None


def test_comparison_excludes_post_cutoff_and_uses_common_stocks(tmp_path):
    cutoff = dt.date(2023, 12, 29)
    future = dt.date(2024, 1, 31)
    for root, factor, values in [('new', 'candidate', [1., 2., 3., 4., 1., 2., 3., 4.]),
                                  ('old', 'peer', [1., 2., 3., None, 4., 3., 2., 1.])]:
        folder = tmp_path/root/'factors'/factor
        folder.mkdir(parents=True)
        pl.DataFrame({'symbol': ['A', 'B', 'C', 'D']*2, 'trade_date': [cutoff]*4+[future]*4,
                      'raw': values}).write_parquet(folder/'monthly_scores.parquet')
    rows = compare_candidate(tmp_path/'new', tmp_path/'old', 'candidate', ['raw'], ['peer'], cutoff, 3, 1)
    assert rows[0]['mean_rank_correlation'] == pytest.approx(1)
    assert rows[0]['months'] == 1 and rows[0]['median_common_symbols'] == 3
