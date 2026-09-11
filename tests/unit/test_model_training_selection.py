import datetime as dt

import polars as pl

from quant.research.model_training_selection import annual_selection, run_selection


SETTINGS = {'admission': {'maximum_absolute_rank_correlation_with_better': .7}}
MODEL = {'selection': {'variant': 'neutral', 'maximum_factors': 20,
                        'maximum_absolute_rank_correlation': .6}}


def screen():
    return pl.DataFrame({'factor': ['a', 'b', 'c'], 'variant': ['neutral']*3,
        'icir': [.9, .8, .7], 'mean_ic': [.09, .08, .07], 'statistical_pass': [True]*3,
        'costs_complete': [True]*3, 'cost_excess_pass': [True]*3})


def test_missing_higher_cost_never_certifies_lower_provisional_pick():
    table = screen().with_columns(pl.when(pl.col('factor') == 'a').then(False).otherwise(
        pl.col('costs_complete')).alias('costs_complete'))
    decisions, result = annual_selection(table, settings=SETTINGS, model=MODEL,
        correlation=lambda a, b: {'comparison_qualified': True, 'mean_absolute_rank_correlation': .1})
    assert decisions[0]['factor_admitted'] is None
    assert result['selection_complete'] is False
    assert result['provisional_selected'] == ['b', 'c']
    assert result['confirmed_selected_prefix'] == []


def test_battery_and_greedy_thresholds_and_complete_cash_history():
    pairs = {('a', 'b'): .6, ('a', 'c'): .2, ('b', 'c'): .7}
    decisions, result = annual_selection(screen(), settings=SETTINGS, model=MODEL,
        correlation=lambda a, b: {'comparison_qualified': True,
                                  'mean_absolute_rank_correlation': pairs[tuple(sorted((a, b)))]})
    assert decisions[1]['factor_admitted'] is True
    assert decisions[1]['selection_reason'] == 'greedy_redundancy'
    # Higher peers include b even though greedy selection did not select it.
    assert decisions[2]['factor_admitted'] is False
    assert result['confirmed_selected_prefix'] == ['a']
    assert result['selection_complete'] is True
    _, empty = annual_selection(screen().with_columns(pl.lit(False).alias('statistical_pass')),
        settings=SETTINGS, model=MODEL, correlation=lambda a, b: {})
    assert empty['selection_complete'] is True and empty['provisional_selected'] == []


def test_insufficient_correlation_history_stays_unresolved():
    decisions, result = annual_selection(screen(), settings=SETTINGS, model=MODEL,
        correlation=lambda a, b: {'comparison_qualified': False, 'mean_absolute_rank_correlation': .1})
    assert decisions[1]['factor_admitted'] is None
    assert result['selection_complete'] is False
    assert result['confirmed_selected_prefix'] == ['a']


def test_future_scores_do_not_change_saved_annual_selection(tmp_path):
    root, costs = tmp_path/'statistics', tmp_path/'costs'
    root.mkdir()
    costs.mkdir()
    battery = '''minimum_symbols = 2
[admission]
minimum_months = 2
maximum_absolute_rank_correlation_with_better = 0.7
'''
    (root/'battery.toml').write_text(battery)
    (costs/'battery.toml').write_text(battery)
    (costs/'model.toml').write_text(f'''[research]
statistics_source = '{root.as_posix()}'
[selection]
variant = 'neutral'
maximum_factors = 20
maximum_absolute_rank_correlation = 0.6
''')
    screen().head(2).with_columns(pl.lit(2020).alias('test_year'),
        pl.lit(dt.date(2019, 12, 31)).alias('refit_close')).write_parquet(costs/'annual_cost_screen.parquet')
    dates = [dt.date(2019, 10, 31), dt.date(2019, 11, 29), dt.date(2020, 1, 31)]
    for factor in ('a', 'b'):
        folder = root/'factors'/factor
        folder.mkdir(parents=True)
        pl.DataFrame({'trade_date': [d for d in dates for _ in range(3)],
            'symbol': ['A', 'B', 'C']*3, 'neutral': [1., 2., 3.]*3}).write_parquet(folder/'monthly_scores.parquet')
    first = run_selection(costs=costs, output=tmp_path/'first')
    path = root/'factors'/'b'/'monthly_scores.parquet'
    pl.read_parquet(path).with_columns(pl.when(pl.col('trade_date') > dt.date(2019, 12, 31)).then(
        -pl.col('neutral')).otherwise(pl.col('neutral')).alias('neutral')).write_parquet(path)
    second = run_selection(costs=costs, output=tmp_path/'second')
    assert first == second
    assert pl.read_parquet(tmp_path/'first'/'annual_correlations.parquet').equals(
        pl.read_parquet(tmp_path/'second'/'annual_correlations.parquet'))
