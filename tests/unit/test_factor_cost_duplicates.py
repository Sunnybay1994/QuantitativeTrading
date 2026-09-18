import datetime as dt
import json

import polars as pl
import pytest

from quant.research.factor_cost_duplicates import audit_duplicates, canonical_scores


def scores():
    return pl.DataFrame({'trade_date': [dt.date(2020, 1, 31)]*4,
                         'symbol': ['a', 'b', 'c', 'd'],
                         'raw': [1., 2., 2., None], 'neutral': [3., 1., 2., None]})


def test_rank_equivalence_keeps_ties_and_ignores_row_order_and_positive_scale():
    source = scores()
    equivalent = source.reverse().with_columns(pl.col('raw', 'neutral')*3+7)
    assert canonical_scores(source, ['raw', 'neutral']).equals(
        canonical_scores(equivalent, ['raw', 'neutral']))


@pytest.mark.parametrize('change', [
    pl.col('raw').fill_null(0), pl.col('raw').fill_null(float('nan')),
    -pl.col('raw'), pl.col('neutral')*-1,
    pl.col('trade_date')+dt.timedelta(days=1),
    pl.col('symbol').replace({'a': 'z'}),
    pl.when(pl.col('symbol') == 'c').then(2.01).otherwise(pl.col('raw')).alias('raw'),
])
def test_masks_direction_grid_and_ties_are_not_equivalent(change):
    assert not canonical_scores(scores(), ['raw', 'neutral']).equals(
        canonical_scores(scores().with_columns(change), ['raw', 'neutral']))


def test_duplicate_keys_rejected():
    with pytest.raises(ValueError, match='unique'):
        canonical_scores(pl.concat([scores(), scores()]), ['raw'])


def test_audit_counts_only_exact_full_variant_equivalence(tmp_path):
    (tmp_path/'battery.toml').write_text(
        'variants=["raw","neutral"]\n[portfolio]\ncost_multipliers=[0.5,1.0,2.0]\n')
    for name, direction, frame in [('a', 1, scores()), ('b', 1, scores().reverse()),
                                   ('c', -1, scores()),
                                   ('d', 1, scores().with_columns(-pl.col('neutral')))]:
        folder = tmp_path/'factors'/name
        folder.mkdir(parents=True)
        (folder/'statistics.json').write_text(json.dumps({'definition': {'id': name, 'direction': direction}}))
        frame.write_parquet(folder/'monthly_scores.parquet')
    result = audit_duplicates(tmp_path, ['a', 'b', 'c', 'd'])
    assert result['aliases'] == {'b': 'a'}
    assert result['representatives'] == ['a', 'c', 'd']
    assert result['potential_saved_variant_cost_replays'] == 6
    assert result['actual_saved_replays'] == 0
    assert result['execution_reuse_enabled'] is False
