import datetime as dt
import math

import polars as pl
import pytest

from quant.research.pressure_reversal_equivalence import (
    compare_rank_sections, scan_library_equivalence,
)

DAY = dt.date(2020, 1, 31)


def frame(values, day=DAY):
    return pl.DataFrame({'trade_date': [day]*len(values),
                         'ts_code': [f's{i:03}' for i in range(len(values))],
                         'value': values}, schema_overrides={'value': pl.Float64})


def compare(a, b, **kwargs):
    return compare_rank_sections(frame(a), frame(b), expected_dates=[DAY], **kwargs)


def test_positive_and_negative_monotone_transforms_are_duplicate_orders():
    a = list(range(100))
    assert compare(a, [v*v for v in a], complete_coverage=True)['status'] == 'same'
    assert compare(a, [-v for v in a], complete_coverage=True)['status'] == 'reversed'
    partial = compare(a, a)
    assert partial['status'] == 'insufficient' and partial['observed_relation'] == 'same'


def test_missing_mask_alone_does_not_establish_new_signal():
    a = list(range(110))
    result = compare(a, [None]*10+a[10:], complete_coverage=True)
    assert result['status'] == 'same'
    assert result['sections'][0]['common_finite'] == 100
    assert result['sections'][0]['finite_masks_equal'] is False
    assert compare(a[:99], a[:99], complete_coverage=True)['status'] == 'insufficient'


def test_ties_use_average_ranks_and_tie_break_changes_are_witnesses():
    a = [v//2 for v in range(100)]
    assert compare(a, [3*v for v in a], complete_coverage=True)['status'] == 'same'
    result = compare(a, list(range(100)))
    assert result['status'] == 'different'
    assert len(result['sections'][0]['witnesses']) == 2


def test_numeric_noise_and_constant_sections_are_not_novelty():
    assert compare([0]*100, [0]*100, complete_coverage=True)['status'] == 'insufficient'
    a = list(range(100))
    a[1] = 1e-15
    b = a.copy()
    b[0], b[1] = b[1], b[0]
    assert compare(a, b)['status'] == 'insufficient'


def test_one_date_witness_disproves_both_orientations_without_full_coverage():
    a = list(range(100))
    b = a.copy()
    b[40], b[80] = b[80], b[40]
    result = compare(a, b)
    assert result['status'] == 'different'
    assert result['global_complete_coverage'] is False


def test_orientation_changing_across_dates_is_not_one_fixed_reverse():
    later = dt.date(2020, 2, 28)
    first = frame(list(range(100)))
    candidate = pl.concat([first, frame(list(range(100)), later)])
    reference = pl.concat([first, frame(list(range(99, -1, -1)), later)])
    result = compare_rank_sections(candidate, reference, expected_dates=[DAY, later])
    assert result['status'] == 'different'
    missing = compare_rank_sections(first, first, expected_dates=[DAY, later], complete_coverage=True)
    assert missing['status'] == 'insufficient'


def test_duplicate_input_keys_are_rejected():
    a = frame(list(range(100)))
    with pytest.raises(ValueError, match='Duplicate'):
        compare_rank_sections(pl.concat([a, a.head(1)]), a, expected_dates=[DAY])


def test_bounded_scanner_stops_only_proved_pairs_and_retains_missing_dates(tmp_path):
    dates = [dt.date(2014, 1, 31), dt.date(2026, 1, 30)]
    candidates = pl.concat([frame([math.sin(i*2.3) for i in range(110)], d) for d in dates])
    candidate_path = tmp_path/'candidates.parquet'
    pl.concat([
        candidates.with_columns(pl.lit('candidate_a').alias('candidate_id')),
        candidates.with_columns((-pl.col('value')).alias('value'),
                                pl.lit('reverse_control').alias('candidate_id')),
    ]).write_parquet(candidate_path)
    universe = candidates.rename({'ts_code': 'symbol'}).drop('value').with_columns(
        pl.lit(True).alias('eligible'), pl.lit(1e9).alias('total_market_value'),
        pl.lit('sector').alias('industry_l1'))
    universe_path = tmp_path/'universe.parquet'
    universe.write_parquet(universe_path)
    battery = tmp_path/'battery.toml'
    battery.write_text('variants=["raw","size_industry_neutral"]\n'
                       '[preprocessing]\nmad_multiplier=3.0\nmad_normal_scale=1.4826\n')
    library = tmp_path/'library'
    library.mkdir()
    for factor in ['f_same', 'f_different']:
        (library/f'{factor}.toml').write_text(
            f'id="{factor}"\nexpr="adj_close"\nfamily="test"\ndirection=1\nsource_ref="test"\n')
        folder = tmp_path/'factors'/factor/'year=2014'
        folder.mkdir(parents=True)
        first = candidates.filter(pl.col('trade_date') == dates[0])
        if factor == 'f_different':
            first = first.with_columns(pl.Series('value', [math.cos(i*.7) for i in range(110)]))
        first.write_parquet(folder/'data.parquet')
    result = scan_library_equivalence(candidate_path=candidate_path, universe_path=universe_path,
        battery_path=battery, library=library, factors_root=tmp_path/'factors',
        output=tmp_path/'result', candidate_ids=['candidate_a'])
    assert result['reference_count'] == 2 and result['return_labels_read'] is False
    assert result['summary']['candidate_a']['different_on_all_layers'] == 1
    same = next(p for p in result['pairs'] if p['reference_id'] == 'f_same')
    assert same['layers']['source_values']['status'] == 'insufficient'
    assert same['layers']['source_values']['observed_relation'] == 'same'
    assert any(s.get('missing') and s['factor_id'] == 'f_same' for s in result['reference_sources'])
    assert not any(s['year'] == 2026 and s['factor_id'] == 'f_different'
                   for s in result['reference_sources'])
    assert len(result['materialized_reference_pairs']) == 1
    control = result['materialized_reference_pairs'][0]
    assert control['reference_id'] == 'reverse_control'
    assert all(r['status'] == 'reversed' for r in control['layers'].values())
