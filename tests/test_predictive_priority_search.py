"""Synthetic evolution and recovery checks; no production GP search runs here."""
import copy
import datetime as dt
import itertools
import json
from dataclasses import asdict

import numpy as np
import polars as pl
import pytest
from deap import gp

from quant.research import nightly_gp
from quant.research import predictive_priority_search as search_impl
from quant.research.gp_predictive_priority import Candidate, GroupIC, SelectionRules


@pytest.fixture
def sample():
    rng = np.random.default_rng(72)
    rows = []
    for year in range(2018, 2022):
        for month in range(1, 13):
            day = dt.date(year, month, 15)
            for stock in range(300):
                x, noise, other, control = rng.normal(size=4)
                rows.append({'symbol': f's{stock:04}', 'trade_date': day,
                             'gp_fin': float(x), 'gp_other': float(other),
                             'control_a': float(x + noise), 'control_b': float(control),
                             'label': float(x + noise*.15), 'label_exit_date': day + dt.timedelta(days=1)})
    frame = pl.from_dicts(rows)
    return (frame.drop('label', 'label_exit_date'),
            frame.select('symbol', 'trade_date', 'label', 'label_exit_date'))


@pytest.fixture
def settings():
    config = {
        'version': 'predictive_priority_v2', 'population_size': 8, 'generations': 2,
        'max_depth': 5, 'seed': 20260919, 'training_end': '2025-12-31', 'training_months': 48,
        'sample_groups': 3, 'symbols_per_group': 100, 'sample_seed': 20260913,
        'minimum_valid_months_per_group': 48, 'minimum_symbols_per_month': 100,
        'minimum_paired_coverage': .8, 'maximum_candidates': 4,
    }
    return {'predictive_priority': config,
            **{key: config[key] for key in ['population_size', 'generations', 'max_depth', 'seed']},
            'mechanism_manifest': {'terminals': [{'terminal_id': 'gp_fin', 'mechanism': 'financial',
                'input_version': 'synthetic-v1', 'availability': 'known before synthetic signal'}]},
            'frozen_control_ids': ['control_a', 'control_b']}


def install_small_grammar(monkeypatch):
    observed = []

    def grammar(names):
        observed.append(list(names))
        pset = gp.PrimitiveSet('SYNTHETIC', 0)
        for name in names:
            pset.addTerminal(name)
        pset.addPrimitive(lambda a: f'(-{a})', 1, name='neg')
        return pset

    monkeypatch.setattr(nightly_gp, 'primitive_set', grammar)
    return observed


def run(sample, settings, output):
    output.mkdir(exist_ok=True)
    return nightly_gp.search(*sample, {'gp_fin': 'pit_cash_yield_ttm', 'gp_other': 'reversal_20'},
                             settings, output, family='synthetic')


def test_real_small_search_exports_only_eligible_mechanisms_and_excludes_controls_from_grammar(
        sample, settings, tmp_path, monkeypatch):
    seen = install_small_grammar(monkeypatch)
    winners = run(sample, settings, tmp_path)
    assert winners and len(winners) <= settings['predictive_priority']['maximum_candidates']
    assert seen == [['gp_fin', 'gp_other']]
    for row in winners:
        assert row['selection_eligible'] and row['selection_primary'] > 0
        assert row['mechanism_terminals'] == ['gp_fin']
        assert all(group['months'] == 48 for group in row['group_statistics'])
        assert [item['control'] for item in row['control_statistics']] == ['control_a', 'control_b']
        assert all(item['valid_months'] == 48 for item in row['control_statistics'])
        assert 'fitness' not in row
        assert (tmp_path/'library'/f"{row['factor_id']}.toml").exists()
    result = json.loads((tmp_path/'search.json').read_text())
    assert any('required_mechanism_not_referenced' in row.get('selection_reasons', [])
               for row in result['trials'])
    assert len(result['selection_trace']) == settings['generations']
    assert all(row['tournament_winners'] for row in result['selection_trace'])
    contract = json.loads((tmp_path/'search_contract.json').read_text())
    assert contract['correlation_method'] == 'mean_absolute_monthly_spearman_then_max_control'
    assert set(contract['assignments'].values()) == {0, 1, 2}
    assert contract['seed'] == 20260919


def test_tournaments_elites_best_and_export_share_the_band_selector(sample, settings, tmp_path,
                                                                  monkeypatch):
    names = ['gp_fin', 'gp_b', 'gp_c']
    panel, labels = sample
    panel = panel.with_columns(pl.col('gp_fin').alias('gp_b'), pl.col('gp_fin').alias('gp_c'))
    settings = copy.deepcopy(settings)
    settings['population_size'] = settings['predictive_priority']['population_size'] = 12
    settings['generations'] = settings['predictive_priority']['generations'] = 1
    settings['mechanism_manifest']['terminals'] = [
        {**settings['mechanism_manifest']['terminals'][0], 'terminal_id': name} for name in names]
    pset = gp.PrimitiveSet('SYNTHETIC', 0)
    for name in names:
        pset.addTerminal(name)
    monkeypatch.setattr(nightly_gp, 'primitive_set', lambda _: pset)
    cycle = itertools.cycle(names)
    monkeypatch.setattr(gp, 'genHalfAndHalf', lambda **kw:
                        gp.PrimitiveTree.from_string(repr(next(cycle)), pset))
    monkeypatch.setattr(gp, 'cxOnePoint', lambda a, b: (a, b))
    monkeypatch.setattr(gp, 'mutUniform', lambda tree, **kw: (tree,))
    primary = {'gp_fin': .0300, 'gp_b': .0294, 'gp_c': .0285}
    redundancy = {'gp_fin': .8, 'gp_b': .1, 'gp_c': .05}

    def measured(scored, expression, assignments, controls, rules):
        row = Candidate(expression, tuple(GroupIC(i, primary[expression], 48, 100, .8)
                                          for i in range(3)),
                        tuple((control, redundancy[expression]) for control in controls))
        return row, {'train': {'months': 48, 'mean_ic': primary[expression]}}

    monkeypatch.setattr(search_impl, 'measure_candidate', measured)
    calls = []
    actual_rank = search_impl.rank_candidates

    def spy(rows, **kwargs):
        result = actual_rank(rows, **kwargs)
        calls.append(([row.expression for row in rows], [row.expression for row in result.selected]))
        return result

    monkeypatch.setattr(search_impl, 'rank_candidates', spy)
    monkeypatch.setattr(nightly_gp.tools, 'selTournament', lambda *a, **kw:
                        pytest.fail('Legacy scalar tournament must not run'))
    monkeypatch.setattr(nightly_gp.tools, 'selBest', lambda *a, **kw:
                        pytest.fail('Legacy scalar elitism must not run'))
    winners = nightly_gp.search(panel, labels, {name: name for name in names}, settings,
                                tmp_path, family='synthetic')
    assert [row['terminal_expression'] for row in winners] == ['gp_b', 'gp_fin', 'gp_c']
    saved = json.loads((tmp_path/'search.json').read_text())
    assert saved['selection_trace'][0]['elites'] == ['gp_b', 'gp_fin', 'gp_c']
    assert len(saved['selection_trace'][0]['tournament_winners']) == 9
    best = json.loads((tmp_path/'best_so_far.json').read_text())
    assert [row['terminal_expression'] for row in best] == ['gp_b', 'gp_fin', 'gp_c']
    assert len(calls) >= 14  # Startup, rankings, nine actual parent tournaments, final export.
    assert any(set(inputs) == {'gp_fin', 'gp_c'} and result[0] == 'gp_fin'
               for inputs, result in calls)


def test_interrupted_search_restores_population_rng_and_records_exactly(sample, settings, tmp_path,
                                                                     monkeypatch):
    from quant.research import slice_budget

    install_small_grammar(monkeypatch)
    baseline = run(sample, settings, tmp_path/'baseline')
    baseline_saved = json.loads((tmp_path/'baseline'/'search.json').read_text())
    checks = []

    def interrupt_second_checkpoint():
        checks.append(1)
        if len(checks) == 2:
            raise RuntimeError('synthetic slice interruption')

    monkeypatch.setattr(slice_budget, 'checkpoint', interrupt_second_checkpoint)
    with pytest.raises(RuntimeError, match='slice interruption'):
        run(sample, settings, tmp_path/'resumed')
    checkpoint = tmp_path/'resumed'/'search_checkpoint.json'
    prior_records = json.loads(checkpoint.read_text())['records']
    monkeypatch.setattr(slice_budget, 'checkpoint', lambda: None)
    resumed = run(sample, settings, tmp_path/'resumed')
    assert resumed == baseline
    result = json.loads((tmp_path/'resumed'/'search.json').read_text())
    assert result == baseline_saved
    assert result['trials'][:len(prior_records)] == prior_records
    monkeypatch.setattr(nightly_gp, 'evaluate_expressions', lambda *args, **kwargs:
                        pytest.fail('Completed records must be restored without recomputation'))
    assert run(sample, settings, tmp_path/'resumed') == baseline


@pytest.mark.parametrize('change', ['manifest', 'controls', 'assignments', 'objective', 'control_data'])
def test_recovery_refuses_changed_contract_without_overwriting(sample, settings, tmp_path,
                                                              monkeypatch, change):
    install_small_grammar(monkeypatch)
    settings['generations'] = settings['predictive_priority']['generations'] = 0
    run(sample, settings, tmp_path)
    before = {p.name: p.read_bytes() for p in tmp_path.glob('*.json')}
    changed = copy.deepcopy(settings)
    if change == 'manifest':
        changed['mechanism_manifest']['terminals'][0]['input_version'] = 'changed'
    elif change == 'controls':
        changed['frozen_control_ids'].reverse()
    elif change == 'assignments':
        changed['predictive_priority']['sample_seed'] += 1
    elif change == 'objective':
        changed['predictive_priority']['selection'] = {'primary': 'different objective'}
    else:
        sample = (sample[0].with_columns((pl.col('control_a')+1).alias('control_a')), sample[1])
    with pytest.raises(ValueError, match='contract changed'):
        run(sample, changed, tmp_path)
    assert {p.name: p.read_bytes() for p in tmp_path.glob('*.json')} == before


@pytest.mark.parametrize('change', ['terminal', 'industry', 'warmup_terminal'])
def test_daily_input_change_refuses_cached_fitness_without_overwriting(
        sample, settings, tmp_path, monkeypatch, change):
    install_small_grammar(monkeypatch)
    settings['generations'] = settings['predictive_priority']['generations'] = 0
    panel, labels = sample
    panel = panel.with_columns(pl.lit('industry_a').alias('industry_l1'))
    warmup_day = labels['trade_date'].min() - dt.timedelta(days=1)
    panel = pl.concat([panel, panel.head(1).with_columns(
        pl.lit(warmup_day).alias('trade_date'))])
    run((panel, labels), settings, tmp_path)
    before = {path.name: path.read_bytes() for path in tmp_path.glob('*.json')}
    contract = json.loads(before['search_contract.json'])
    assert len(contract['daily_input_sha256']) == 64
    assert contract['daily_input_fingerprint_method'] == search_impl._DAILY_FINGERPRINT_METHOD
    if change == 'industry':
        changed = panel.with_columns(pl.lit('industry_b').alias('industry_l1'))
    else:
        day = warmup_day if change == 'warmup_terminal' else labels['trade_date'].min()
        changed = panel.with_columns(pl.when(pl.col('trade_date') == day)
            .then(pl.col('gp_fin') + .25).otherwise(pl.col('gp_fin')).alias('gp_fin'))
    # All three mutations leave monthly labels and admitted-control measurements unchanged.
    controls = settings['frozen_control_ids']
    old_monthly = panel.select('symbol', 'trade_date', *controls).join(
        labels, on=['symbol', 'trade_date']).sort('trade_date', 'symbol')
    new_monthly = changed.select('symbol', 'trade_date', *controls).join(
        labels, on=['symbol', 'trade_date']).sort('trade_date', 'symbol')
    assert old_monthly.equals(new_monthly)
    monkeypatch.setattr(nightly_gp, 'evaluate_expressions', lambda *args, **kwargs:
                        pytest.fail('Changed daily input must be rejected before using GP records'))
    with pytest.raises(ValueError, match='contract changed'):
        run((changed, labels), settings, tmp_path)
    assert {path.name: path.read_bytes() for path in tmp_path.glob('*.json')} == before


def test_daily_fingerprint_is_order_and_batch_independent_without_wide_bytes(sample, monkeypatch):
    panel = sample[0].head(57).with_columns(pl.lit('industry_a').alias('industry_l1'))
    original_hash = pl.DataFrame.hash_rows
    batch_heights = []

    def record_hash_rows(frame, **kwargs):
        batch_heights.append(frame.height)
        return original_hash(frame, **kwargs)

    monkeypatch.setattr(pl.DataFrame, 'hash_rows', record_hash_rows)
    monkeypatch.setattr(pl.DataFrame, 'to_numpy', lambda *args, **kwargs:
                        pytest.fail('Wide daily frame must not be converted to numpy/bytes'))
    expected = search_impl._daily_input_fingerprint(panel, batch_size=7)
    assert len(expected) == 64 and max(batch_heights) <= 7
    shuffled = panel.reverse().select(list(reversed(panel.columns)))
    assert search_impl._daily_input_fingerprint(shuffled, batch_size=19) == expected
    assert search_impl._daily_input_fingerprint(panel, batch_size=1000) == expected
    assert search_impl._daily_input_fingerprint(panel.head(56)) != expected
    assert search_impl._daily_input_fingerprint(
        panel.with_columns(pl.col('gp_fin').cast(pl.Float32))) != expected


def test_reordered_daily_input_can_resume_without_recomputing(sample, settings, tmp_path, monkeypatch):
    install_small_grammar(monkeypatch)
    settings['generations'] = settings['predictive_priority']['generations'] = 0
    original = run(sample, settings, tmp_path)
    panel, labels = sample
    panel = panel.reverse().select(list(reversed(panel.columns)))
    monkeypatch.setattr(nightly_gp, 'evaluate_expressions', lambda *args, **kwargs:
                        pytest.fail('Equivalent reordered daily input must use frozen records'))
    assert run((panel, labels), settings, tmp_path) == original


@pytest.mark.parametrize('mutation', ['future_label', 'future_signal', 'future_panel', 'duplicate',
                                    'missing_exit', 'wrong_month_count'])
def test_training_date_boundary_fails_before_any_search_output(sample, settings, tmp_path, mutation):
    panel, labels = sample
    if mutation == 'future_label':
        labels = labels.with_columns(pl.lit(dt.date(2026, 1, 2)).alias('label_exit_date'))
    elif mutation == 'future_signal':
        labels = labels.with_columns(pl.lit(dt.date(2026, 1, 1)).alias('trade_date'),
                                     pl.lit(dt.date(2026, 1, 2)).alias('label_exit_date'))
    elif mutation == 'future_panel':
        panel = pl.concat([panel, panel.head(1).with_columns(
            pl.lit(dt.date(2026, 1, 1)).alias('trade_date'))])
    elif mutation == 'duplicate':
        labels = pl.concat([labels, labels.head(1)])
    elif mutation == 'missing_exit':
        labels = labels.drop('label_exit_date')
    else:
        labels = labels.filter(pl.col('trade_date') != labels['trade_date'].min())
    with pytest.raises(ValueError):
        run((panel, labels), settings, tmp_path)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('missing', ['manifest', 'controls', 'control_column', 'mechanism_terminal'])
def test_missing_manifest_or_frozen_measurements_fail_closed(sample, settings, tmp_path, missing):
    if missing == 'manifest':
        del settings['mechanism_manifest']
    elif missing == 'controls':
        settings['frozen_control_ids'] = []
    elif missing == 'control_column':
        sample = (sample[0].drop('control_a'), sample[1])
    else:
        settings['mechanism_manifest']['terminals'][0]['terminal_id'] = 'absent_mechanism'
    with pytest.raises(ValueError):
        run(sample, settings, tmp_path)
    assert not list(tmp_path.iterdir())


def test_each_control_uses_mean_absolute_monthly_rho_and_missing_is_not_zero():
    rows, assignments = [], {}
    for group in range(3):
        for stock in range(100):
            symbol = f'{group}_{stock}'
            assignments[symbol] = group
            for month, direction in [(1, 1), (2, -1)]:
                rows.append({'symbol': symbol, 'trade_date': dt.date(2020, month, 15),
                             'candidate': float(stock), 'label': float(stock),
                             'control_flip': float(stock*direction), 'control_missing': None})
    scored = pl.from_dicts(rows).with_columns(pl.col('control_missing').cast(pl.Float64))
    rules = SelectionRules(3, 1, 100, .8, 5, 20)
    candidate, measured = search_impl.measure_candidate(scored, 'gp_fin', assignments,
                                                        ['control_flip', 'control_missing'], rules)
    assert dict(candidate.control_correlations) == {'control_flip': 1., 'control_missing': None}
    assert measured['control_statistics'][0]['valid_months'] == 2
    assert measured['control_statistics'][1]['valid_months'] == 0
    assert [asdict(row)['valid_months'] for row in candidate.groups] == [2, 2, 2]


def test_missing_control_observations_reject_every_candidate_without_extra_generations(
        sample, settings, tmp_path, monkeypatch):
    install_small_grammar(monkeypatch)
    panel = sample[0].with_columns(pl.lit(None, dtype=pl.Float64).alias('control_b'))
    assert run((panel, sample[1]), settings, tmp_path) == []
    result = json.loads((tmp_path/'search.json').read_text())
    mechanism_trials = [row for row in result['trials'] if row.get('selection_candidate')]
    assert mechanism_trials
    assert all('invalid_control_correlations' in row['selection_reasons']
               for row in mechanism_trials)
    assert len(result['selection_trace']) == settings['generations']
    assert all(row['action'] == 'fresh_population_within_registered_generations'
               for row in result['selection_trace'])
    assert json.loads((tmp_path/'search_checkpoint.json').read_text())['generation'] == 2


def test_legacy_cache_cannot_be_reinterpreted_as_predictive(sample, settings, tmp_path):
    cache = tmp_path/'fitness_cache.json'
    cache.write_text('[{"terminal_expression":"gp_fin","fitness":0.9}]')
    before = cache.read_bytes()
    with pytest.raises(ValueError, match='lacks its frozen search contract'):
        run(sample, settings, tmp_path)
    assert cache.read_bytes() == before
    assert not (tmp_path/'search_contract.json').exists()
