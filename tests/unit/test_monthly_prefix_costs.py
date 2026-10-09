import json
from pathlib import Path

import polars as pl
import pytest

from quant.research import monthly_prefix_costs as costs


def inputs(tmp_path):
    prefix = tmp_path/'prefix'
    prefix.mkdir()
    (prefix/'model.toml').write_text('[selection]\nvariant="neutral"\n')
    pl.DataFrame({'factor': ['old', 'early', 'early', 'raw_only', 'never'],
        'variant': ['neutral', 'neutral', 'neutral', 'raw', 'neutral'],
        'statistical_pass': [True, True, False, True, False],
        'test_year': [2023, 2023, 2026, 2023, 2023]}).write_parquet(prefix/'annual_statistical_screen.parquet')
    (tmp_path/'frozen_settings.json').write_text(json.dumps({'execution_snapshot': 'frozen', 'workers': 2}))


def test_early_qualifier_gets_costs_even_when_final_fails_and_missing_stays_blocked(tmp_path, monkeypatch):
    inputs(tmp_path)
    calls = []
    sentinel = tmp_path/'original_summary.json'
    sentinel.write_text('original unchanged')
    def run(**kw):
        calls.append(kw)
        assert kw['required_factors'] == ['early']
        assert kw['resume'] and kw['workers'] == 2 and not kw.get('only_statistical_pass')
        assert kw['existing_runs'] == []
        checkpoint = kw['output']/'checkpoint'
        if len(calls) == 1:
            checkpoint.write_text('keep')
            return {'completed_runs': {}, 'failures': {'early': 'interrupted'}, 'pending_external_runs': {}}
        assert checkpoint.read_text() == 'keep'
        return {'completed_runs': {'early': 'extra/early'}, 'failures': {}, 'pending_external_runs': {}}
    monkeypatch.setattr(costs, 'run_cost_batch', run)
    with pytest.raises(ValueError, match='dependencies incomplete'):
        costs.prepare_costs(tmp_path, Path('data'), {'old': 'existing/old'})
    assert costs.prepare_costs(tmp_path, Path('data'), {'old': 'existing/old'}) == [Path('existing/old')]
    assert sentinel.read_text() == 'original unchanged'
    receipt = json.loads((tmp_path/'additional_costs/dependency_receipt.json').read_text())
    assert receipt['required_factors'] == ['early', 'old']
    assert receipt['original_costs_reused'] == 1


def test_cache_dependency_append_archives_once_and_reuses_correlations(tmp_path):
    original = tmp_path/'prefix_costs'
    selection = tmp_path/'selection'
    original.mkdir()
    selection.mkdir()
    sources = {'old': str(tmp_path/'old')}
    old_bytes = json.dumps({'source_runs': sources}).encode()
    (original/'summary.json').write_bytes(old_bytes)
    (selection/'annual_correlations.parquet').write_bytes(b'keep correlations')
    assert costs.refresh_cached_stages(tmp_path, sources) == {}
    expanded = {**sources, 'early': str(tmp_path/'early')}
    previous = costs.refresh_cached_stages(tmp_path, expanded)
    assert not original.exists() and not selection.exists()
    assert (previous['prefix_costs']/'summary.json').read_bytes() == old_bytes
    assert (previous['selection']/'annual_correlations.parquet').read_bytes() == b'keep correlations'
    original.mkdir()
    (original/'partial').write_text('resume')
    assert costs.refresh_cached_stages(tmp_path, expanded) == previous
    assert (original/'partial').read_text() == 'resume'


def test_changed_existing_history_is_not_silently_reused(tmp_path):
    folder = tmp_path/'prefix_costs'
    folder.mkdir()
    (folder/'summary.json').write_text(json.dumps({'source_runs': {'old': 'original'}}))
    with pytest.raises(ValueError, match='only append'):
        costs.refresh_cached_stages(tmp_path, {'old': 'replacement', 'new': 'new'})
    assert (folder/'summary.json').exists()


def test_interruption_between_cache_archives_resumes_same_transition(tmp_path, monkeypatch):
    for name in ('prefix_costs', 'selection'):
        (tmp_path/name).mkdir()
    (tmp_path/'prefix_costs/summary.json').write_text(json.dumps({'source_runs': {'old': 'old'}}))
    original_rename = Path.rename
    def rename(path, target):
        if path.name == 'selection':
            raise OSError('simulated sharing conflict')
        return original_rename(path, target)
    monkeypatch.setattr(Path, 'rename', rename)
    sources = {'old': 'old', 'early': 'early'}
    with pytest.raises(OSError):
        costs.refresh_cached_stages(tmp_path, sources)
    monkeypatch.setattr(Path, 'rename', original_rename)
    previous = costs.refresh_cached_stages(tmp_path, sources)
    assert all(path.is_dir() for path in previous.values())
    assert len(list(tmp_path.glob('prefix_costs_before_*'))) == 1
