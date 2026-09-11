import datetime as dt
import itertools

import polars as pl
import pytest

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


def test_confirmed_redundancy_excludes_missing_cost_without_admitting_it():
    pairs = {('a', 'b'): .65, ('a', 'c'): .1, ('b', 'c'): .1}
    def compare(a, b):
        return {'comparison_qualified': True,
                'mean_absolute_rank_correlation': pairs[tuple(sorted((a, b)))]}
    full = annual_selection(screen(), settings=SETTINGS, model=MODEL, correlation=compare)[1]
    incomplete = screen().with_columns(pl.when(pl.col('factor') == 'b').then(None).otherwise(
        pl.col('cost_excess_pass')).alias('cost_excess_pass'))
    decisions, result = annual_selection(incomplete, settings=SETTINGS, model=MODEL, correlation=compare)
    assert result == full
    assert result['selection_complete'] and result['confirmed_selected_prefix'] == ['a', 'c']
    assert decisions[1]['factor_admitted'] is None
    assert decisions[1]['selection_reason'] == 'greedy_redundancy_with_confirmed'
    # A failed cost result also leaves the same selected portfolio.
    rejected = incomplete.with_columns(pl.col('cost_excess_pass').fill_null(False))
    assert annual_selection(rejected, settings=SETTINGS, model=MODEL, correlation=compare)[1] == result


def test_provisional_or_unqualified_peer_cannot_resolve_missing_cost():
    incomplete = screen().with_columns(pl.when(pl.col('factor').is_in(['a', 'c'])).then(None).otherwise(
        pl.col('cost_excess_pass')).alias('cost_excess_pass'))
    def compare(a, b):
        return {'comparison_qualified': True,
                'mean_absolute_rank_correlation': .65 if set((a, b)) == {'b', 'c'} else .1}
    _, result = annual_selection(incomplete, settings=SETTINGS, model=MODEL, correlation=compare)
    assert not result['selection_complete'] and result['unresolved_factors'] == 2
    assert result['confirmed_selected_prefix'] == []
    incomplete = screen().with_columns(pl.when(pl.col('factor') == 'b').then(None).otherwise(
        pl.col('cost_excess_pass')).alias('cost_excess_pass'))
    _, result = annual_selection(incomplete, settings=SETTINGS, model=MODEL,
        correlation=lambda a, b: {'comparison_qualified': False, 'mean_absolute_rank_correlation': .99})
    assert not result['selection_complete']


def test_confirmed_full_quota_does_not_wait_for_lower_costs():
    model = {'selection': {**MODEL['selection'], 'maximum_factors': 1}}
    incomplete = screen().with_columns(pl.when(pl.col('factor') != 'a').then(None).otherwise(
        pl.col('cost_excess_pass')).alias('cost_excess_pass'))
    _, result = annual_selection(incomplete, settings=SETTINGS, model=model,
        correlation=lambda a, b: pytest.fail('No comparisons needed after a confirmed full quota'))
    assert result['selection_complete'] and result['confirmed_selected_prefix'] == ['a']
    _, complete_costs = annual_selection(screen(), settings=SETTINGS, model=model,
        correlation=lambda a, b: {'comparison_qualified': False, 'mean_absolute_rank_correlation': .1})
    assert complete_costs == result


def test_partial_cost_selection_matches_every_possible_completion():
    names = ['a', 'b', 'c']
    for values in itertools.product((.1, .65, .75), repeat=3):
        pairs = dict(zip(itertools.combinations(names, 2), values, strict=True))

        def compare(a, b):
            return {'comparison_qualified': True,
                    'mean_absolute_rank_correlation': pairs[tuple(sorted((a, b)))]}

        resolved = {}
        for costs in itertools.product((False, True), repeat=3):
            table = screen().with_columns(pl.Series('cost_excess_pass', costs))
            resolved[costs] = annual_selection(table, settings=SETTINGS, model=MODEL,
                                               correlation=compare)[1]['confirmed_selected_prefix']
        for partial in itertools.product((False, True, None), repeat=3):
            table = screen().with_columns(pl.Series('cost_excess_pass', partial, dtype=pl.Boolean))
            _, result = annual_selection(table, settings=SETTINGS, model=MODEL, correlation=compare)
            prefix = result['confirmed_selected_prefix']
            for costs, selected in resolved.items():
                if any(p is not None and p != c for p, c in zip(partial, costs, strict=True)):
                    continue
                assert selected[:len(prefix)] == prefix, (values, partial, costs)
                if result['selection_complete']:
                    assert selected == prefix, (values, partial, costs)


def test_future_scores_do_not_change_saved_annual_selection(tmp_path, monkeypatch):
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
    from quant.research import model_training_selection as module

    def calculate(**kwargs):
        raise RuntimeError('Correlation must be recomputed for a different cutoff')

    monkeypatch.setattr(module, 'monthly_rank_correlation', lambda *args, **kwargs: calculate(**kwargs))
    cached = run_selection(costs=costs, output=tmp_path/'cached', correlations_from=tmp_path/'first')
    assert cached == second
    for filename in ('annual_selection.parquet', 'annual_correlations.parquet'):
        assert pl.read_parquet(tmp_path/'cached'/filename).equals(pl.read_parquet(tmp_path/'second'/filename))
    # A cache with a later information boundary cannot drive an earlier refit.
    path = costs/'annual_cost_screen.parquet'
    pl.read_parquet(path).with_columns(pl.lit(dt.date(2019, 12, 30)).alias('refit_close')).write_parquet(path)
    with pytest.raises(RuntimeError, match='different cutoff'):
        run_selection(costs=costs, output=tmp_path/'earlier', correlations_from=tmp_path/'first')
    (tmp_path/'first'/'battery.toml').write_text(battery+'\nchanged = true\n')
    with pytest.raises(ValueError, match='same statistics'):
        run_selection(costs=costs, output=tmp_path/'changed', correlations_from=tmp_path/'first')
