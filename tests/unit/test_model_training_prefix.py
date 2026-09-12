import datetime as dt
import tomllib
from pathlib import Path

import polars as pl
import pytest

from quant.research.model_training_prefix import known_outcomes, outcome_calendar, prefix_statistics, run_prefixes
from quant.research.model_training_prefix import training_prefix_settings


def test_training_prefix_can_be_48_without_changing_final_battery():
    settings = {'admission': {'minimum_months': 96, 'minimum_icir': .3}}
    result = training_prefix_settings(settings, {'selection': {'minimum_known_months': 48}})
    assert result['admission'] == {'minimum_months': 48, 'minimum_icir': .3}
    assert settings['admission']['minimum_months'] == 96
    for months in (0, 47, 97, True, 48.0):
        with pytest.raises(ValueError, match='at least 48 months'):
            training_prefix_settings(settings, {'selection': {'minimum_known_months': months}})


def test_48_month_candidate_passes_training_but_not_final_screen():
    from quant.research.factor_battery_screen import screen_statistics

    settings = tomllib.loads(Path('configs/factors/battery.toml').read_text(encoding='utf-8'))
    rows = pl.from_dicts([{'factor': 'a', 'variant': variant, 'months': 48,
        'p_value': .0001, 'newey_west_t': 5., 'icir': 2., 'yearly_positive_fraction': 1.,
        'group_statistics': {'long_short_sharpe': 2.}} for variant in settings['variants']])
    training = screen_statistics(statistics=rows, factors=['a'],
        settings=training_prefix_settings(settings, {'selection': {'minimum_known_months': 48}}))
    final = screen_statistics(statistics=rows, factors=['a'], settings=settings)
    assert training['statistical_pass'].all()
    assert not final['statistical_pass'].any()
    assert all(failures == ['history'] for failures in final['statistical_failures'].to_list())


def fixture():
    dates = [dt.date(2022, 9, 30), dt.date(2022, 10, 31), dt.date(2022, 11, 30)]
    labels = pl.DataFrame({'trade_date': dates, 'exit_date_rebalance': [
        dt.date(2022, 11, 1), dt.date(2022, 12, 1), dt.date(2023, 1, 3)]})
    monthly = pl.DataFrame({'trade_date': dates, 'rank_ic': [.1, .2, .9], 'variant': ['raw']*3})
    groups = pl.DataFrame([{'trade_date': date, 'group': group, 'mean_return': .01*group*(i+1),
                           'variant': 'raw'} for i, date in enumerate(dates) for group in range(1, 11)])
    settings = tomllib.loads(Path('configs/factors/battery.toml').read_text(encoding='utf-8'))
    return monthly, groups, outcome_calendar(labels), settings


def test_future_ic_and_group_changes_do_not_change_year_end_training():
    monthly, groups, calendar, settings = fixture()
    kwargs = dict(factor='a', calendar=calendar, cutoff=dt.date(2022, 12, 30), settings=settings)
    original = prefix_statistics(monthly=monthly, groups=groups, **kwargs)
    future = pl.col('trade_date') == dt.date(2022, 11, 30)
    revised = prefix_statistics(monthly=monthly.with_columns(
        pl.when(future).then(-.99).otherwise(pl.col('rank_ic')).alias('rank_ic')),
        groups=groups.with_columns(pl.when(future).then(-.99).otherwise(
            pl.col('mean_return')).alias('mean_return')), **kwargs)
    assert original == revised
    assert original[0]['months'] == 2
    assert original[0]['mean_ic'] == pytest.approx(.15)
    assert original[0]['group_statistics']['long_short_months'] == 2
    assert original[1]['months'] == 0  # Missing neutral history stays in the family.
    assert known_outcomes(monthly, calendar, dt.date(2023, 1, 3)).height == 3


def test_empty_history_and_unknown_exit_do_not_become_training_observations():
    monthly, groups, calendar, settings = fixture()
    rows = prefix_statistics(factor='a', monthly=monthly, groups=groups, calendar=calendar,
                             cutoff=dt.date(2022, 1, 1), settings=settings)
    assert all(row['months'] == 0 and row['group_statistics']['long_short_sharpe'] is None for row in rows)
    calendar = calendar.with_columns(pl.lit(None, dtype=pl.Date).alias('exit_date_rebalance'))
    assert known_outcomes(monthly, calendar, dt.date(2026, 1, 1)).is_empty()


def test_missing_conflicting_or_nonfuture_exit_calendar_is_rejected():
    monthly, _, calendar, _ = fixture()
    with pytest.raises(ValueError, match='missing signal'):
        known_outcomes(monthly, calendar.head(2), dt.date(2023, 1, 1))
    conflicting = calendar.head(1).with_columns(pl.lit(dt.date(2022, 11, 2)).alias('exit_date_rebalance'))
    with pytest.raises(ValueError, match='unique later exit'):
        outcome_calendar(pl.concat([calendar, conflicting]))
    with pytest.raises(ValueError, match='unique later exit'):
        outcome_calendar(calendar.with_columns(pl.col('trade_date').alias('exit_date_rebalance')))


def test_saved_annual_screen_uses_last_session_and_retains_missing_variant(tmp_path):
    monthly, groups, calendar, _ = fixture()
    root = tmp_path/'statistics'
    inputs = root/'inputs'/'2022'
    inputs.mkdir(parents=True)
    calendar.write_parquet(inputs/'monthly_labels.parquet')
    pl.DataFrame({'trade_date': [dt.date(2022, 12, 29), dt.date(2022, 12, 30)]}).write_parquet(
        inputs/'universe.parquet')
    factor = root/'factors'/'a'
    factor.mkdir(parents=True)
    monthly.write_parquet(factor/'monthly_ic.parquet')
    groups.write_parquet(factor/'monthly_groups.parquet')
    pl.DataFrame({'factor': ['a', 'a'], 'variant': ['raw', 'size_industry_neutral']}).write_parquet(
        root/'statistics.parquet')
    (root/'battery.toml').write_text(Path('configs/factors/battery.toml').read_text(encoding='utf-8')
                                   + '\n[run]\nselected = "all"\n', encoding='utf-8')
    config = tmp_path/'model.toml'
    config.write_text(f'''[research]
statistics_source = '{root.as_posix()}'
[selection]
minimum_known_months = 96
variant = "size_industry_neutral"
[walk_forward]
test_start = 2023-01-01
test_end = 2023-12-31
''', encoding='utf-8')
    output = tmp_path/'result'
    summary = run_prefixes(config=config, output=output)
    assert summary['annual_screens'][0]['refit_close'] == '2022-12-30'
    table = pl.read_parquet(output/'annual_statistical_screen.parquet')
    assert table.height == 2
    assert table['months'].to_list() == [2, 0]
    assert not table['statistical_pass'].any()
