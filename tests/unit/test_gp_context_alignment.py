import datetime as dt
import json

import polars as pl
import pytest

from quant.data.gp_context_inputs import sha256
from quant.factors.library import FactorDefinition
from quant.research.gp_context_alignment import compare_values, verify_new_gp_values
from quant.research.gp_full_context import VERSION


def data():
    frame = pl.from_dicts([{'symbol': str(i), 'trade_date': dt.date(2020, month, 15),
                           'candidate': None if i == 0 else float(i), 'label': float(i % 11)}
                          for month in range(1, 4) for i in range(120)])
    return frame.select('symbol', 'trade_date', 'candidate'), frame.select('symbol', 'trade_date', 'label')


def test_alignment_checks_raw_values_not_just_rank_ic_and_preserves_missing_mask():
    values, labels = data()
    assert compare_values(values, values, labels, factor='x', direction=-1)['passed']
    shifted = values.with_columns((pl.col('candidate') + 0.1).alias('candidate'))
    result = compare_values(values, shifted, labels, factor='x', direction=-1)
    assert result['maximum_month_ic_difference'] == 0
    assert not result['passed']
    filled = values.with_columns(pl.col('candidate').fill_null(0))
    assert not compare_values(values, filled, labels, factor='x', direction=1)['missing_mask_equal']


def test_alignment_preserves_unavailable_months_without_poisoning_valid_ic():
    values, labels = data()
    # February has too few paired labels; March has no cross-sectional variation.
    labels = labels.with_columns(pl.when(pl.col('trade_date').dt.month() == 2)
                                 .then(None).otherwise(pl.col('label')).alias('label'))
    values = values.with_columns(pl.when(pl.col('trade_date').dt.month() == 3)
                                 .then(1.).otherwise(pl.col('candidate')).alias('candidate'))
    result = compare_values(values, values, labels, factor='x', direction=-1)
    json.dumps(result, allow_nan=False)
    assert result['passed']
    assert result['months'] == 3
    assert result['valid_ic_months'] == 1
    assert result['ic_missing_mask_equal']
    assert result['maximum_month_ic_difference'] == 0


@pytest.mark.parametrize('replacement', [float('nan'), float('inf'), -float('inf')])
def test_alignment_rejects_one_sided_nonfinite_value(replacement):
    values, labels = data()
    # This row has no label, so IC alone cannot detect losing its factor value.
    labels = labels.with_columns(pl.when(pl.col('symbol') == '1').then(None)
                                 .otherwise(pl.col('label')).alias('label'))
    changed = values.with_columns(pl.when(pl.col('symbol') == '1').then(replacement)
                                  .otherwise(pl.col('candidate')).alias('candidate'))
    result = compare_values(values, changed, labels, factor='x', direction=1)
    json.dumps(result, allow_nan=False)
    assert not result['passed']
    assert result['maximum_scaled_difference'] == 0
    assert result['maximum_month_ic_difference'] == 0
    assert not result['finite_mask_equal']
    assert 'candidate_finite_mask_mismatch' in result['failure_reasons']


def test_alignment_does_not_discard_one_sided_unavailable_ic_month():
    values, labels = data()
    values = values.with_columns(pl.col('candidate').fill_null(0.))
    labels = labels.with_columns(pl.when(pl.col('symbol').cast(pl.Int64) < 100)
                                 .then(pl.col('label')).otherwise(None).alias('label'))
    changed = values.with_columns(pl.when((pl.col('symbol') == '1') & (pl.col('trade_date').dt.month() == 1))
                                  .then(None).otherwise(pl.col('candidate')).alias('candidate'))
    result = compare_values(values, changed, labels, factor='x', direction=1)
    json.dumps(result, allow_nan=False)
    assert not result['passed']
    assert result['valid_ic_months'] == 2
    assert result['maximum_month_ic_difference'] == 0
    assert not result['ic_missing_mask_equal']
    assert 'ic_missing_mask_mismatch' in result['failure_reasons']


def test_alignment_all_missing_ic_fails_with_serializable_reason():
    values, labels = data()
    labels = labels.with_columns(pl.lit(None, dtype=pl.Float64).alias('label'))
    result = compare_values(values, values, labels, factor='x', direction=1)
    json.dumps(result, allow_nan=False)
    assert not result['passed']
    assert result['valid_ic_months'] == 0
    assert result['maximum_month_ic_difference'] is None
    assert result['failure_reasons'] == ['no_comparable_ic_months']


def test_alignment_arithmetic_overflow_fails_without_nonfinite_json():
    values, labels = data()
    values = values.with_columns(pl.when(pl.col('symbol') == '1').then(1e308)
                                 .otherwise(pl.col('candidate')).alias('candidate'))
    changed = values.with_columns(pl.when(pl.col('symbol') == '1').then(-1e308)
                                  .otherwise(pl.col('candidate')).alias('candidate'))
    result = compare_values(values, changed, labels, factor='x', direction=1)
    json.dumps(result, allow_nan=False)
    assert not result['passed']
    assert result['maximum_absolute_difference'] is None
    assert 'candidate_difference_unavailable' in result['failure_reasons']


@pytest.mark.parametrize('missing_label_month', [None, 2])
def test_natural_n3_verifies_only_versioned_output_and_rejects_changed_receipt(tmp_path, missing_label_month):
    legacy = tmp_path/'legacy_search.json'
    legacy.write_text(json.dumps({'candidates': [{'factor_id': 'old'}]}))
    record = FactorDefinition('old', 'adj_close', 'price', 1, str(legacy))
    report = tmp_path/'alignment.json'
    assert verify_new_gp_values([record], data_root=tmp_path/'data', output=report)['factors_checked'] == 0
    assert not report.exists()
    source = tmp_path/'search.json'
    source.write_text(json.dumps({'candidates': [{'factor_id': 'new', 'calculation_context': VERSION}]}))
    values, labels = data()
    if missing_label_month is not None:
        labels = labels.with_columns(pl.when(pl.col('trade_date').dt.month() == missing_label_month)
                                     .then(None).otherwise(pl.col('label')).alias('label'))
    training_path = tmp_path/'training_candidate_values.parquet'
    values.with_columns(pl.lit('new').alias('factor')).write_parquet(training_path)
    labels_path = tmp_path/'monthly_sample.parquet'
    labels.write_parquet(labels_path)
    manifest = {'values_sha256': sha256(training_path), 'labels_sha256': sha256(labels_path),
                'expressions': {'new': 'adj_close'}, 'directions': {'new': 1}}
    (tmp_path/'training_values_manifest.json').write_text(json.dumps(manifest))
    computed = tmp_path/'data/factors/new/year=2020'
    computed.mkdir(parents=True)
    values.rename({'symbol': 'ts_code', 'candidate': 'value'}).write_parquet(computed/'data.parquet')
    definition = FactorDefinition('new', 'adj_close', 'price', 1, str(source))
    assert verify_new_gp_values([definition], data_root=tmp_path/'data', output=report)['passed']
    values.with_columns((pl.col('candidate') + 0.1).alias('candidate')).rename(
        {'symbol': 'ts_code', 'candidate': 'value'}).write_parquet(computed/'data.parquet')
    with pytest.raises(ValueError, match='N2/N3 factor values differ'):
        verify_new_gp_values([definition], data_root=tmp_path/'data', output=report)
    assert not json.loads(report.read_text())['passed']
    labels_path.write_bytes(b'changed')
    with pytest.raises(ValueError, match='receipt changed'):
        verify_new_gp_values([definition], data_root=tmp_path/'data', output=report)
