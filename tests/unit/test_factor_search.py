import copy
import tomllib
from pathlib import Path

import pytest

from quant.factors.library import FactorDefinition
from quant.factors.search import expand, prepare


CONFIG = Path('configs/factors/search/p6c_finite_batch01_20260911.toml')


def settings():
    return tomllib.loads(CONFIG.read_text(encoding='utf-8'))


def test_fixed_grid_has_twenty_four_unique_dimensionless_or_named_inputs():
    definitions, trials = expand(settings(), [])
    assert len(definitions) == len(trials) == 24
    assert all(row['result'] == 'registered' for row in trials)
    assert len({row.id for row in definitions}) == 24
    assert all(row.lookback >= 0 for row in definitions)


def test_budget_rejection_happens_before_grid_enumeration():
    config = settings()
    config['templates'][0]['parameters']['n'] = list(range(1, 1000))
    with pytest.raises(ValueError, match='budget'):
        expand(config, [])


def test_future_lag_and_unknown_field_are_retained_as_failed_attempts():
    config = settings()
    config['templates'] = [dict(id='bad_lag', expr='delay(adj_close, -1)', direction=1,
                                family='test', source_ref='test'),
                           dict(id='bad_field', expr='future_return', direction=1,
                                family='test', source_ref='test')]
    definitions, trials = expand(config, [])
    assert definitions == []
    assert [row['result'] for row in trials] == ['invalid_expression', 'invalid_expression']


def test_duplicate_expression_is_counted_without_creating_another_factor():
    config = settings()
    existing = FactorDefinition('original', 'ts_mean((2 * adj_close - adj_high - adj_low) / (adj_high - adj_low), 8)',
                                'test', -1, 'test')
    definitions, trials = expand(config, [existing])
    assert len(definitions) == 23 and len(trials) == 24
    assert next(row for row in trials if row['result'] == 'duplicate_expression')['duplicate_of'] == 'original'


def test_registration_resume_preserves_definitions_and_rejects_changed_grid(tmp_path):
    library = tmp_path/'library'
    library.mkdir()
    (library/'original.toml').write_text('id="original"\nexpr="adj_close"\nfamily="test"\ndirection=1\nsource_ref="test"')
    result = prepare(config=CONFIG, library=library, output=tmp_path/'run')
    assert result == prepare(config=CONFIG, library=library, output=tmp_path/'run')
    assert len(list(library.glob('*.toml'))) == 25
    original = (tmp_path/'run'/'trials.json').read_bytes()
    changed = tmp_path/'changed.toml'
    changed.write_text(CONFIG.read_text(encoding='utf-8').replace('maximum_candidates = 24', 'maximum_candidates = 25'))
    with pytest.raises(ValueError, match='new run'):
        prepare(config=changed, library=library, output=tmp_path/'run')
    assert (tmp_path/'run'/'trials.json').read_bytes() == original


def test_changed_existing_id_does_not_overwrite_definition(tmp_path):
    config = settings()
    first, _ = expand(config, [])
    wrong = copy.copy(first[0])
    wrong = FactorDefinition(wrong.id, 'adj_close', wrong.family, wrong.direction, wrong.source_ref)
    _, trials = expand(config, [wrong])
    assert trials[0]['result'] == 'invalid_expression'
    assert 'different definition' in trials[0]['reason']


def test_wrong_operator_arity_is_a_failed_candidate_not_a_batch_crash():
    config = settings()
    config['templates'] = [dict(id='bad_arity', expr='ts_corr(adj_close, 20)', direction=1,
                                family='test', source_ref='test')]
    definitions, trials = expand(config, [])
    assert definitions == [] and trials[0]['result'] == 'invalid_expression'
    assert 'requires 3 arguments' in trials[0]['reason']


def test_price_plus_volume_is_rejected_as_incompatible_units():
    config = settings()
    config['templates'] = [dict(id='mixed_units', expr='adj_close + volume', direction=1,
                                family='test', source_ref='test')]
    definitions, trials = expand(config, [])
    assert definitions == [] and 'units' in trials[0]['reason']
