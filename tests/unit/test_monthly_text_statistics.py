import polars as pl

from quant.research.factor_battery_evaluation import evaluate_factor_year
from quant.research.monthly_text_statistics import run
from tests.unit.test_forecast_text_incremental import SETTINGS, fixture_panel


def test_monthly_results_match_existing_battery_and_keep_admission_threshold(tmp_path):
    panel = fixture_panel()
    result = run(panel, settings=SETTINGS, output=tmp_path / 'monthly')
    reference = evaluate_factor_year(universe=panel,
        values=panel.select('symbol', 'trade_date', pl.col('text_operating_improvement').alias('value')),
        daily_labels=panel.select('symbol', 'trade_date', *[f'label_{h}' for h in SETTINGS['decay_sessions']]),
        monthly_labels=panel.select('symbol', 'trade_date', 'label_rebalance'), direction=1, settings=SETTINGS)
    actual = pl.read_parquet(tmp_path / 'monthly/monthly_ic.parquet').filter(
        pl.col('factor') == 'text_operating_improvement').drop('factor')
    assert actual.sort('variant', 'trade_date').select(reference.monthly_ic.columns).equals(
        reference.monthly_ic.sort('variant', 'trade_date'))
    groups = pl.read_parquet(tmp_path / 'monthly/monthly_groups.parquet').filter(
        pl.col('factor') == 'text_operating_improvement').drop('factor')
    assert groups.equals(reference.monthly_groups)
    assert len(result['summary']) == 6
    assert all(not row['coverage_sufficient'] for row in result['summary'])
    assert result['minimum_months'] == 96 and result['minimum_symbols'] == 100
    assert result['costs_evaluated'] is False


def test_missing_future_labels_do_not_change_scores_or_cohorts(tmp_path):
    panel = fixture_panel()
    run(panel, settings=SETTINGS, output=tmp_path / 'base')
    run(panel.with_columns(pl.lit(None, dtype=pl.Float64).alias('label_rebalance')),
        settings=SETTINGS, output=tmp_path / 'missing')
    assert pl.read_parquet(tmp_path / 'base/monthly_scores.parquet').equals(
        pl.read_parquet(tmp_path / 'missing/monthly_scores.parquet'))
    keys = ['factor', 'variant', 'trade_date', 'group', 'members']
    assert pl.read_parquet(tmp_path / 'base/monthly_groups.parquet').select(keys).equals(
        pl.read_parquet(tmp_path / 'missing/monthly_groups.parquet').select(keys))
    ic = pl.read_parquet(tmp_path / 'missing/monthly_ic.parquet')
    assert ic['rank_ic'].null_count() == ic.height


def test_insufficient_signal_months_remain_in_calendar_without_fabricated_groups(tmp_path):
    result = run(fixture_panel(count=99), settings=SETTINGS, output=tmp_path / 'small')
    assert result['months_on_calendar'] == 3
    assert all(row['months'] == 0 for row in result['summary'])
    groups = pl.read_parquet(tmp_path / 'small/monthly_groups.parquet')
    assert groups.height == 3 * 10 * 6 and groups['members'].sum() == 0
    assert groups['mean_return'].null_count() == groups.height
