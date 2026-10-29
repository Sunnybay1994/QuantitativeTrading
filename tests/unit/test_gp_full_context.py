import datetime as dt
import json

import numpy as np
import polars as pl
import pytest

from quant.factors.expressions import evaluate_expressions
from quant.research.gp_expression_identity import VERSION as IDENTITY_VERSION, canonical_expression, expression_key
from quant.research.gp_full_context import FullContextEvaluator, VERSION, replace_cross_subtrees, scope_cross_sections
from quant.research.gp_full_context import PUBLISHED_TERMINALS
from quant.research.nightly_gp import preprocess_training_scores
from quant.research.factor_battery_statistics import rank_ic_by_date


@pytest.fixture
def panels():
    rng = np.random.default_rng(733)
    rows = []
    for i in range(90):
        date = dt.date(2019, 11, 1) + dt.timedelta(days=i)
        for j in range(240):
            x, y = rng.normal(size=2)
            rows.append({'symbol': f's{j:03}', 'trade_date': date,
                'a': None if (j + i) % 71 == 0 else float(round(x, 1) + j / 80),
                'b': None if (j + i) % 89 == 0 else float(y),
                'adj_close': None if (j + i) % 101 == 0 else 1.,
                'industry_l1': None if j == 7 else str(j % 6),
                'label': float(x * .1 + y * .01 + rng.normal())})
    full = pl.from_dicts(rows).sort('symbol', 'trade_date')
    # Keep raw leaves alongside gp_* aliases (production panel does the same).
    sample = full.filter(pl.col('symbol') < 's120').with_columns(
        gp_a=pl.col('a'), gp_b=pl.col('b'))
    return full, sample


def evaluator(tmp_path, full, sample, **kwargs):
    def reader(expression, expanded, low, high):
        return full.filter(pl.col('trade_date') <= high).drop('label'), expanded, 'fixture_complete_market'
    return FullContextEvaluator(sample.drop('label'), {'gp_a': 'a', 'gp_b': 'b'}, tmp_path,
        identity={'sample': 'fixed', 'labels': 'fixed', 'data_version': kwargs.pop('data_version', 'v1')},
        maximum_subtrees=kwargs.pop('maximum_subtrees', 8), maximum_disk_mb=8, reader=reader, **kwargs)


@pytest.mark.parametrize('expression,expanded', [
    ('rank(gp_a) + gp_b * 0.2', 'rank(a) + b * 0.2'),
    ('scale(gp_a) + gp_b * 0.001', 'scale(a) + b * 0.001'),
    ('ind_neutralize(gp_a,industry_l1)', 'ind_neutralize(a,industry_l1)'),
    ('delay(ind_neutralize(ts_cov(gp_a,gp_b,5),industry_l1),5)',
     'delay(ind_neutralize(ts_cov(a,b,5),industry_l1),5)'),
    ('rank(ts_mean(rank(gp_a),5))', 'rank(ts_mean(rank(a),5))'),
])
def test_full_context_values_masks_and_ic_match_deployment(tmp_path, panels, expression, expanded):
    full, sample = panels
    runner = evaluator(tmp_path, full, sample)
    actual = runner.evaluate(expression).sort('symbol', 'trade_date')
    expected = evaluate_expressions(full.drop('label'), {'candidate': scope_cross_sections(expanded)}).join(
        sample.select('symbol', 'trade_date'), on=['symbol', 'trade_date'], how='semi').sort('symbol', 'trade_date')
    assert actual['candidate'].is_null().equals(expected['candidate'].is_null())
    np.testing.assert_allclose(actual['candidate'].to_numpy(), expected['candidate'].to_numpy(), equal_nan=True, atol=1e-13, rtol=1e-12)
    labels = sample.select('symbol', 'trade_date', 'label')
    a = preprocess_training_scores(actual.join(labels, on=['symbol', 'trade_date']))
    b = preprocess_training_scores(expected.join(labels, on=['symbol', 'trade_date']))
    ai = rank_ic_by_date(a, score='candidate', label='label', minimum_symbols=100, minimum_paired_coverage=.8)
    bi = rank_ic_by_date(b, score='candidate', label='label', minimum_symbols=100, minimum_paired_coverage=.8)
    assert ai.equals(bi)
    assert ai.height > 20
    def forbidden(*args):
        raise AssertionError('A completed cross-section must reuse its same-input projection')
    runner.reader = forbidden
    assert runner.evaluate(expression).equals(actual)


def test_mapped_terminal_ignores_divergent_panel_shortcut(tmp_path, panels):
    """Mapped gp_* names must expand; a stale panel column must not win."""
    full, sample = panels
    # Inject a wildly wrong gp_a column while mapping still says gp_a -> a.
    divergent = sample.with_columns((pl.col('gp_a') + 1000.0).alias('gp_a'))
    runner = evaluator(tmp_path, full, divergent)
    terminal = 'ts_mean(delay(gp_a, 1), 5)'
    expanded = 'ts_mean(delay(a, 1), 5)'
    actual = runner.evaluate(terminal).sort('symbol', 'trade_date')
    via_expanded = runner.evaluate(expanded).sort('symbol', 'trade_date')
    expected = evaluate_expressions(
        divergent.select('symbol', 'trade_date', 'a', 'adj_close'),
        {'candidate': expanded}).sort('symbol', 'trade_date')
    np.testing.assert_allclose(actual['candidate'].to_numpy(), via_expanded['candidate'].to_numpy(),
                               equal_nan=True, atol=1e-13, rtol=1e-12)
    np.testing.assert_allclose(actual['candidate'].to_numpy(), expected['candidate'].to_numpy(),
                               equal_nan=True, atol=1e-13, rtol=1e-12)
    wrong = evaluate_expressions(
        divergent.select('symbol', 'trade_date', 'gp_a', 'adj_close'),
        {'candidate': 'ts_mean(delay(gp_a, 1), 5)'}).sort('symbol', 'trade_date')
    assert not np.allclose(actual['candidate'].to_numpy(), wrong['candidate'].to_numpy(), equal_nan=True)


@pytest.mark.parametrize('field',['pit_annual_low_accruals','minute_smart_vwap','free_float_turnover_level_monthly_calendar80_v1'])
def test_published_policy_keeps_intrinsic_terminal_observations_without_unattached_raw_fields(tmp_path,field):
    dates=[dt.date(2020,1,2),dt.date(2020,1,3),dt.date(2020,1,6)]
    sample=pl.DataFrame({'symbol':['A']*3,'trade_date':dates,'gp_factor':[1.,2.+1e-12,3.], 'adj_close':[10.]*3})
    def forbidden(*args): raise AssertionError('No new cross section needs raw intrinsic expansion')
    runner=FullContextEvaluator(sample,{'gp_factor':field},tmp_path,
        identity={'terminal_input_policy':PUBLISHED_TERMINALS,'sample':'frozen'},
        maximum_subtrees=8,maximum_disk_mb=8,reader=forbidden)
    actual=runner.evaluate('ts_mean(gp_factor,2)')
    expected=evaluate_expressions(sample,{'candidate':'ts_mean(gp_factor,2)'})
    assert actual['candidate'].equals(expected['candidate'])


def test_context_budget_never_falls_back_to_sample_or_increases_on_resume(tmp_path, panels):
    full, sample = panels
    runner = evaluator(tmp_path, full, sample, maximum_subtrees=1)
    saved = runner.evaluate('rank(gp_a)')
    with pytest.raises(ValueError, match='SUBTREE_BUDGET'):
        runner.evaluate('scale(gp_a)')
    resumed = evaluator(tmp_path, full, sample, maximum_subtrees=1)
    assert resumed.evaluate('rank(gp_a)').equals(saved)
    with pytest.raises(ValueError, match='SUBTREE_BUDGET'):
        resumed.evaluate('scale(gp_a)')
    assert len(resumed.registry) == 1
    with pytest.raises(ValueError, match='context changed'):
        evaluator(tmp_path, full, sample, maximum_subtrees=2)


def test_context_cache_does_not_cross_input_versions_or_accept_changed_projection(tmp_path, panels):
    full, sample = panels
    runner = evaluator(tmp_path, full, sample)
    runner.evaluate('rank(gp_a)')
    with pytest.raises(ValueError, match='context changed'):
        evaluator(tmp_path, full, sample, data_version='v2')
    path = next(tmp_path.glob('*/*.parquet'))
    path.write_bytes(b'changed')
    with pytest.raises(ValueError, match='projection changed'):
        runner.evaluate('rank(gp_a)')


def test_only_outer_cross_node_is_materialized():
    seen = []
    rewritten = replace_cross_subtrees('delay(rank(ts_mean(scale(gp_a),5)),20)',
        lambda expr: seen.append(expr) or 'projected')
    assert seen == ['rank(ts_mean(scale(gp_a), 5))']
    assert rewritten == 'delay(projected, 20)'


def test_scope_is_explicit_idempotent_and_excludes_unobserved_financial_carry():
    expr = scope_cross_sections('rank(gp_financial)')
    assert 'adj_close > 0' in expr
    assert scope_cross_sections(expr) == expr
    frame = pl.DataFrame({'symbol': ['a', 'b', 'future'], 'trade_date': [dt.date(2020,1,1)] * 3,
                          'adj_close': [1., 1., None], 'gp_financial': [10., 20., 30.]})
    result = evaluate_expressions(frame, {'value': expr})
    assert result['value'].to_list() == [0., 1., None]


def test_symmetry_is_limited_to_verified_corr_cov_and_preserves_windows_and_inputs():
    a = 'ts_mean(ts_corr(gp_x, gp_y, 5), 20)'
    b = 'ts_mean(ts_corr(gp_y, gp_x, 5), 20)'
    assert expression_key(a, IDENTITY_VERSION) == expression_key(b, IDENTITY_VERSION)
    assert expression_key(a, IDENTITY_VERSION) != expression_key(b.replace(', 5)', ', 20)'), IDENTITY_VERSION)
    assert expression_key('ts_cov(gp_x,gp_y,5)', IDENTITY_VERSION) == expression_key('ts_cov(gp_y,gp_x,5)', IDENTITY_VERSION)
    for a, b in [('gp_x + gp_y', 'gp_y + gp_x'), ('gp_x * gp_y', 'gp_y * gp_x'),
                 ('gp_x-gp_y', 'gp_y-gp_x')]:
        assert expression_key(a, IDENTITY_VERSION) != expression_key(b, IDENTITY_VERSION)


def test_safe_published_terminal_reuse_requires_null_support_proof():
    from quant.data.gp_context_inputs import null_without_bar
    assert null_without_bar('ts_std0(adj_close,20) / ts_mean(adj_close,20)')
    assert null_without_bar('ts_argmax(adj_high,20) - ts_argmin(adj_low,20)')
    assert not null_without_bar('delay(adj_close,1)')
    assert not null_without_bar('pit_liabilities_to_assets')
    assert not null_without_bar('where(1, 0, adj_close)')


@pytest.mark.parametrize('operation', ['ts_corr', 'ts_cov'])
def test_search_deduplicates_corr_cov_before_fitness_and_keeps_aliases(tmp_path, monkeypatch, operation):
    from deap import gp
    from quant.research import nightly_gp
    rng = np.random.default_rng(5)
    rows = [{'symbol': f's{i}', 'trade_date': dt.date(2010 + m // 12, m % 12 + 1, 15),
             'gp_a': float(rng.normal()), 'gp_b': float(rng.normal()), 'label': float(rng.normal())}
            for m in range(60) for i in range(120)]
    panel = pl.from_dicts(rows)
    pset = nightly_gp.primitive_set(['gp_a', 'gp_b'])
    trees = iter([gp.PrimitiveTree.from_string(x, pset) for x in [
        f"{operation}_5('gp_a','gp_b')", f"{operation}_5('gp_b','gp_a')"]])
    monkeypatch.setattr(nightly_gp.gp, 'genHalfAndHalf', lambda **kw: next(trees))
    calls = []
    original = nightly_gp.evaluate_expressions
    def count(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(nightly_gp, 'evaluate_expressions', count)
    settings = {'seed': 7, 'population_size': 2, 'generations': 0, 'max_depth': 5,
                'complexity_penalty': .0005, 'expression_identity': IDENTITY_VERSION}
    result = nightly_gp.search(panel.drop('label'), panel.select('symbol', 'trade_date', 'label'),
        {'gp_a': 'adj_close', 'gp_b': 'volume'}, settings, tmp_path, family='fixture')
    assert len(calls) == len(result) == 1
    saved = json.loads((tmp_path/'search.json').read_text())
    assert len(saved['trials']) == 1
    aliases = json.loads((tmp_path/'expression_aliases.json').read_text())
    assert len(aliases) == 2
    assert len({v['canonical_key'] for v in aliases.values()}) == 1
    original_checkpoint = (tmp_path/'search_checkpoint.json').read_bytes()
    with pytest.raises(ValueError, match='version changed'):
        nightly_gp.search(panel.drop('label'), panel.select('symbol', 'trade_date', 'label'),
            {'gp_a': 'adj_close', 'gp_b': 'volume'}, {k: v for k, v in settings.items() if k != 'expression_identity'},
            tmp_path, family='fixture')
    assert (tmp_path/'search_checkpoint.json').read_bytes() == original_checkpoint


def test_future_version_is_frozen_without_changing_old_batch_or_search_budget(tmp_path, monkeypatch):
    import tomllib
    from quant.research import continuous_mining as mining
    config = tmp_path/'nightly.toml'
    original = '[genetic]\nseed=10\npopulation_size=200\ngenerations=30\nmax_depth=5\n'
    config.write_text(original)
    observed = []
    def execute(path, **kwargs):
        settings = tomllib.loads(path.read_text())
        observed.append(settings['genetic'])
        if len(observed) == 1:
            raise KeyboardInterrupt
        result = {'steps': {step: {'ok': True} for step in ['N1', 'N2', 'N3', 'N4', 'N5']}}
        (kwargs['run_path']/'summary.json').write_text(json.dumps(result))
        return result
    monkeypatch.setattr(mining.nightly, 'execute', execute)
    with pytest.raises(KeyboardInterrupt):
        mining.dispatch(config, tmp_path/'continuous', now=dt.datetime(2026, 10, 4, 12))
    config.write_text(original + f'calculation_context="{VERSION}"\nexpression_identity="{IDENTITY_VERSION}"\n')
    mining.dispatch(config, tmp_path/'continuous', now=dt.datetime(2026, 10, 4, 14))
    mining.dispatch(config, tmp_path/'continuous', now=dt.datetime(2026, 10, 4, 15))
    assert all('calculation_context' not in row and 'expression_identity' not in row for row in observed[:2])
    assert observed[2]['calculation_context'] == VERSION
    assert observed[2]['expression_identity'] == IDENTITY_VERSION
    assert all((row['population_size'], row['generations'], row['max_depth']) == (200, 30, 5) for row in observed)


def test_source_guard_detects_changed_bytes_and_newly_appearing_missing_partition(tmp_path):
    from quant.data.gp_context_inputs import FullMarketInputs
    guard = FullMarketInputs.__new__(FullMarketInputs)
    guard.sources_path = tmp_path/'sources.json'
    guard.sources, guard.stamps = {}, {}
    source = tmp_path/'one.parquet'
    source.write_bytes(b'first')
    guard.track(source)
    missing = tmp_path/'missing.parquet'
    guard.track(missing)
    missing.write_bytes(b'new')
    with pytest.raises(ValueError, match='source changed'):
        guard.track(missing)
    source.write_bytes(b'changed bytes')
    with pytest.raises(ValueError, match='source changed'):
        guard.track(source)


def test_source_inventory_detects_new_increment_before_cache_reuse(tmp_path):
    from quant.data.gp_context_inputs import FullMarketInputs
    guard = FullMarketInputs.__new__(FullMarketInputs)
    guard.root = tmp_path
    guard.source_settings = {'stock_snapshot': 'stock', 'daily_basic_snapshot': 'basic'}
    guard.low, guard.end = dt.date(2020, 1, 1), dt.date(2020, 12, 31)
    guard.sources, guard.industry = {}, None
    guard.base_paths = guard._base_paths()
    guard.verify_sources()
    folder = tmp_path/'clean/tushare_incremental/date=2020-05-20'
    folder.mkdir(parents=True)
    (folder/'bar_1d.parquet').write_bytes(b'new historical partition')
    with pytest.raises(ValueError, match='inventory changed'):
        guard.verify_sources()


def test_winner_receipt_survives_full_search_registry_and_skips_budget(tmp_path, panels):
    """Exhausted search subtree budget must not crash N2 receipts; over-budget winners drop."""
    import random
    from deap import gp
    from quant.research import nightly_gp
    from quant.research.gp_full_context import scope_cross_sections
    from quant.research.nightly_gp import _FITNESS_PREPROCESSING, expand_expression

    full, sample = panels
    mapping = {'gp_a': 'a', 'gp_b': 'b'}
    panel = sample.drop('label')
    labels = sample.select('symbol', 'trade_date', 'label')
    search_ctx = tmp_path/'search_context'
    runner = evaluator(search_ctx, full, sample, maximum_subtrees=1)
    runner.evaluate('rank(gp_a)')
    assert len(runner.registry) == 1
    with pytest.raises(ValueError, match='SUBTREE_BUDGET'):
        runner.evaluate('scale(gp_a)')

    out = tmp_path/'run'
    out.mkdir()
    labels.write_parquet(out/'monthly_sample.parquet')
    scoped_rank = scope_cross_sections('rank(gp_a)')
    scoped_scale = scope_cross_sections('scale(gp_a)')
    records = []
    for terminal, fitness in ((scoped_rank, 0.5), (scoped_scale, 0.4)):
        records.append({
            'expression': expand_expression(terminal, mapping),
            'terminal_expression': terminal, 'complexity': 2, 'depth': 1,
            'fitness': fitness, 'direction': 1,
            'fitness_preprocessing': _FITNESS_PREPROCESSING,
            'search_objective': 'pooled_mean_ic_v1',
            'calculation_context': VERSION, 'expression_identity': 'literal_expression_v1',
            'input_identity': runner.identity, 'canonical_key': terminal,
            'train': {'months': 48, 'mean_ic': fitness}, 'maximum_rank_correlation': 0.1})
    pset = nightly_gp.primitive_set(['gp_a', 'gp_b', 'adj_close', 'a', 'b'])
    population = [str(gp.PrimitiveTree.from_string(tree, pset))
                  for tree in ("rank('gp_a')", "scale('gp_a')")]
    (out/'search_checkpoint.json').write_text(json.dumps({
        'generation': 0, 'population': population, 'random_state': random.getstate(),
        'records': records}), encoding='utf-8')

    winners = nightly_gp.search(
        panel, labels, mapping,
        {'seed': 1, 'population_size': 2, 'generations': 0, 'max_depth': 5,
         'complexity_penalty': .0005, 'calculation_context': VERSION},
        out, family='fixture', context_evaluator=runner)

    assert len(winners) == 1
    assert 'rank' in winners[0]['expression']
    assert (out/'training_candidate_values.parquet').exists()
    manifest = json.loads((out/'training_values_manifest.json').read_text(encoding='utf-8'))
    assert list(manifest['expressions']) == [winners[0]['factor_id']]
    assert list((out/'library').glob('*.toml')) == [out/'library'/f"{winners[0]['factor_id']}.toml"]
    saved = json.loads((out/'search.json').read_text(encoding='utf-8'))
    assert len(saved['candidates']) == 1
    assert (out/'full_context_receipt').exists()
    assert len(runner.registry) == 1
