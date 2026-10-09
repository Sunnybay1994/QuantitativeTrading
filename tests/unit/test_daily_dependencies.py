import datetime as dt
import hashlib
import json

import polars as pl
import pytest

from quant.research import daily_dependencies as dependencies
from quant.research.candidate_freeze import freeze_completed_search
from quant.research.nightly_gp import expand_expression


DAY = dt.date(2026, 9, 29)


def fixture(tmp_path, *, candidate='extra_daily', health='daily_signal', model='daily_signal'):
    library = tmp_path/'library'
    library.mkdir()
    expressions = {'daily_signal': 'adj_close / delay(adj_close, 20) - 1',
                   'extra_daily': 'ts_mean(volume, 20)',
                   'minute_signal': 'ts_mean(minute_smart_vwap, 20)'}
    for identifier, expr in expressions.items():
        (library/f'{identifier}.toml').write_text(
            f'id = "{identifier}"\nexpr = "{expr}"\nfamily = "fixture"\n'
            'direction = 1\nsource_ref = "fixture"\n', encoding='utf-8')
        folder = tmp_path/'data/factors'/identifier
        folder.mkdir(parents=True)
        (folder/'definition.json').write_text(json.dumps({'id': identifier, 'expr': expr}))
    predictions, selection = tmp_path/'predictions', tmp_path/'selection'
    predictions.mkdir()
    selection.mkdir()
    (predictions/'summary.json').write_text(json.dumps({'annual_fits': [{
        'refit_close': '2025-12-31', 'test_year': 2026, 'last_known_exit': '2025-11-28',
        'training_months': 24, 'factors': [model]}, {
        'refit_close': '2026-12-31', 'test_year': 2027, 'last_known_exit': '2026-11-28',
        'training_months': 36, 'factors': ['minute_signal']}]}))
    (selection/'config.toml').write_text(f'[research]\npredictions = "{predictions.as_posix()}"\n'
        '[selection]\nminimum_training_months = 24\n')
    health_selection = tmp_path/'health_selection'
    health_selection.mkdir()
    pl.DataFrame({'factor': [health], 'variant': ['raw'], 'refit_close': [dt.date(2025,12,31)],
                  'test_year': [2026], 'provisional_selected': [True]}).write_parquet(
        health_selection/'annual_selection.parquet')
    (tmp_path/'health.toml').write_text(f'[diagnostics]\nselection = "{health_selection.as_posix()}"\nmaximum_factors = 20\n')
    (tmp_path/'refresh.toml').write_text(f'[factors]\nlibrary = "{library.as_posix()}"\nselected = "all"\n'
        f'[quality]\nenabled = true\nfactor_health_config = "{(tmp_path/"health.toml").as_posix()}"\n')
    (tmp_path/'q10.toml').write_text(f'[model]\nselection = "{selection.as_posix()}"\n')
    search = tmp_path/'search'
    (search/'library').mkdir(parents=True)
    mapping = {f'gp_{candidate}': expressions[candidate]}
    terminal_expression = f'gp_{candidate}'
    expression = expand_expression(terminal_expression, mapping)
    identifier = 'ngp_'+hashlib.sha256(expression.encode()).hexdigest()[:16]
    (search/'search.json').write_text(json.dumps({'candidates': [{'factor_id': identifier,
        'terminal_expression': terminal_expression, 'expression': expression,
        'direction': 1, 'family': 'fixture'}]}))
    (search/'search_contract.json').write_text(json.dumps({'objective': 'predictive_priority_v2',
        'mapping': mapping, 'config': {'auto_trade': False}}))
    (search/'library'/f'{identifier}.toml').write_text(f'id = "{identifier}"\nexpr = "{expression}"\n'
        'direction = 1\nfamily = "fixture"\nsource_ref = "fixture"\n')
    receipt = tmp_path/'freeze.json'
    freeze_completed_search(search, receipt_path=receipt)
    config = tmp_path/'daily.toml'
    config.write_text(f'auto_trade = false\ndata_root = "{(tmp_path/"data").as_posix()}"\n'
        f'refresh_config = "{(tmp_path/"refresh.toml").as_posix()}"\n'
        f'[model]\nselection = "{selection.as_posix()}"\n'
        f'[q10]\nconfig = "{(tmp_path/"q10.toml").as_posix()}"\n'
        f'[candidate_forward]\nenabled = true\nsearch_output = "{search.as_posix()}"\nreceipt = "{receipt.as_posix()}"\n'
        '[forward_tracking]\nenabled = true\n')
    return config


def test_union_includes_candidate_and_health_and_ignores_future_refit(tmp_path):
    config = fixture(tmp_path)
    before = {path: path.read_bytes() for path in tmp_path.rglob('*') if path.is_file()}
    plan = dependencies.resolve_daily_dependencies(config=config, as_of=DAY)
    assert plan['required_factor_ids'] == ['daily_signal', 'extra_daily']
    assert plan['required_minute_inputs'] == []
    assert plan['research_only_minute_factor_ids'] == ['minute_signal']
    assert plan['consumers']['candidate_forward']['factor_ids'] == ['extra_daily']
    assert plan['shadow']['enabled'] is True
    assert plan['sources']
    assert before == {path: path.read_bytes() for path in tmp_path.rglob('*') if path.is_file()}


@pytest.mark.parametrize('consumer', ['candidate', 'health', 'model'])
def test_minute_requirement_of_any_consumer_is_preserved(tmp_path, consumer):
    config = fixture(tmp_path, **{consumer: 'minute_signal'})
    plan = dependencies.resolve_daily_dependencies(config=config, as_of=DAY)
    assert plan['required_minute_factor_ids'] == ['minute_signal']
    assert plan['required_minute_inputs'] == ['minute_smart_vwap']
    assert plan['research_only_minute_factor_ids'] == []


def test_excluded_candidate_cannot_be_silently_dropped(tmp_path):
    config = fixture(tmp_path)
    refresh = tmp_path/'refresh.toml'
    refresh.write_text(refresh.read_text().replace('selected = "all"',
        'selected = "all"\nexcluded_factors = ["extra_daily"]'))
    with pytest.raises(ValueError, match='Candidate terminal differs'):
        dependencies.resolve_daily_dependencies(config=config, as_of=DAY)


@pytest.mark.parametrize('where', ['library', 'published', 'frozen'])
def test_candidate_expression_changes_fail_closed(tmp_path, where):
    config = fixture(tmp_path)
    if where == 'library':
        path = tmp_path/'library/extra_daily.toml'
        path.write_text(path.read_text().replace('ts_mean(volume, 20)', 'ts_mean(volume, 10)'))
    elif where == 'published':
        path = tmp_path/'data/factors/extra_daily/definition.json'
        path.write_text(json.dumps({'id': 'extra_daily', 'expr': 'ts_mean(volume, 10)'}))
    else:
        path = tmp_path/'search/search_contract.json'
        value = json.loads(path.read_text())
        value['mapping']['gp_extra_daily'] = 'ts_mean(volume, 10)'
        path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        dependencies.resolve_daily_dependencies(config=config, as_of=DAY)


def test_q10_different_model_is_not_assumed_covered(tmp_path):
    config = fixture(tmp_path)
    (tmp_path/'q10.toml').write_text('[model]\nselection = "other_selection"\n')
    with pytest.raises(ValueError, match='same frozen selection'):
        dependencies.resolve_daily_dependencies(config=config, as_of=DAY)


def test_health_requires_selected_factor_and_known_refit(tmp_path):
    config = fixture(tmp_path, health='extra_daily')
    refresh = tmp_path/'refresh.toml'
    refresh.write_text(refresh.read_text().replace('selected = "all"', 'selected = "daily_signal"'))
    config.write_text(config.read_text().replace('enabled = true', 'enabled = false'))
    with pytest.raises(ValueError, match='outside refresh selection'):
        dependencies.resolve_daily_dependencies(config=config, as_of=DAY)
    with pytest.raises(ValueError, match='No trained model'):
        dependencies.resolve_daily_dependencies(config=config, as_of=dt.date(2025, 1, 1))


def test_dependency_source_changed_during_read_is_detected(tmp_path, monkeypatch):
    config = fixture(tmp_path)
    actual = dependencies.read_factor_health_selection
    def read_and_change(**kwargs):
        result = actual(**kwargs)
        (tmp_path/'refresh.toml').write_text((tmp_path/'refresh.toml').read_text()+'\n# changed\n')
        return result
    monkeypatch.setattr(dependencies, 'read_factor_health_selection', read_and_change)
    with pytest.raises(ValueError, match='source changed during resolution'):
        dependencies.resolve_daily_dependencies(config=config, as_of=DAY)


def test_unknown_b32_components_require_explicit_dependency_review(tmp_path):
    config = fixture(tmp_path)
    account = tmp_path/'b32.toml'
    account.write_text('[universe]\nsame_effective_pool = ["unknown_new_factor"]\n'
                       '[[accounts]]\ncomponents = ["unknown_new_factor"]\n')
    config.write_text(config.read_text()+f'\n[b32]\nconfig = "{account.as_posix()}"\n')
    with pytest.raises(ValueError, match='Unrecognized B32 signal dependency'):
        dependencies.resolve_daily_dependencies(config=config, as_of=DAY)
