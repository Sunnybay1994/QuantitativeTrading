import datetime as dt
import json
from pathlib import Path

import pytest

from quant.research import run_factor_search as search


CONFIG = Path('configs/factors/search/p6c_finite_batch01_20260911.toml')


def fake_stages(monkeypatch, *, benchmark_failure=False, cost_failure=False, passes=2):
    calls = []
    def prepare(**kwargs):
        kwargs['output'].mkdir(parents=True, exist_ok=True)
        return {'attempt_count': 24, 'registered_count': 24}
    monkeypatch.setattr(search, 'prepare', prepare)
    monkeypatch.setattr(search, 'compute', lambda **kwargs: calls.append(('panels', kwargs['end'])) or {})
    def completed(name, kwargs, result):
        folder = kwargs['output']
        folder.mkdir(parents=True, exist_ok=True)
        (folder/'summary.json').write_text(json.dumps(result), encoding='utf-8')
        calls.append((name, kwargs.get('as_of')))
        return result
    monkeypatch.setattr(search, 'run_statistics', lambda **kwargs: completed('statistics', kwargs, {}))
    monkeypatch.setattr(search, 'run_screen', lambda **kwargs: completed('screen', kwargs, {'statistical_pass_rows': passes}))
    monkeypatch.setattr(search, 'run_scorecard', lambda **kwargs: completed('scorecard', kwargs, {}))
    monkeypatch.setattr(search, 'run_redundancy', lambda **kwargs: completed('redundancy', kwargs, {}))
    def benchmarks(**kwargs):
        nonlocal benchmark_failure
        if benchmark_failure:
            benchmark_failure = False
            kwargs['output'].mkdir()
            (kwargs['output']/'partial.txt').write_text('unfinished')
            raise RuntimeError('interrupted benchmark')
        return completed('benchmarks', kwargs, {})
    monkeypatch.setattr(search, 'run_benchmarks', benchmarks)
    def costs(**kwargs):
        nonlocal cost_failure
        assert kwargs['only_statistical_pass'] is True
        folder = kwargs['output']
        folder.mkdir(parents=True, exist_ok=True)
        calls.append(('costs', len(kwargs['existing_runs'])))
        if cost_failure:
            cost_failure = False
            one = folder/'one'
            one.mkdir()
            (one/'summary.json').write_text('{}')
            result = {'completed_runs': {'one': str(one)}, 'failures': {'two': 'interrupted'}, 'pending_external_runs': {}}
        else:
            result = {'completed_runs': {'one': 'finished_one', 'two': 'finished_two'},
                      'failures': {}, 'pending_external_runs': {}}
        (folder/'batch_summary.json').write_text(json.dumps(result))
        return result
    monkeypatch.setattr(search, 'run_cost_batch', costs)
    return calls


def test_automatic_stages_keep_training_validation_separate_and_completed_run_is_reused(tmp_path, monkeypatch):
    calls = fake_stages(monkeypatch, cost_failure=True)
    result = search.run(config=CONFIG, output=tmp_path/'run')
    assert result['message'] == 'completed'
    assert [date for name, date in calls if name == 'statistics'] == [dt.date(2019,12,31), dt.date(2022,12,30)]
    assert [count for name, count in calls if name == 'costs'] == [0, 1]
    count = len(calls)
    assert search.run(config=CONFIG, output=tmp_path/'run') == result
    assert len(calls) == count
    assert (tmp_path/'run'/'refresh.toml').is_file()


def test_return_benchmark_snapshot_reaches_scorecard_and_change_cannot_reuse_scores(tmp_path, monkeypatch):
    calls = fake_stages(monkeypatch)
    original = search.run_scorecard
    def scorecard(**kwargs):
        if kwargs['cost_runs']:
            assert kwargs['return_benchmark_config'] == tmp_path/'run'/'return_benchmarks.toml'
            assert kwargs['return_benchmark_config'].read_bytes() == benchmark.read_bytes()
        return original(**kwargs)
    monkeypatch.setattr(search, 'run_scorecard', scorecard)
    benchmark = tmp_path/'returns.toml'
    benchmark.write_text('[benchmarks]\nequal_weight_snapshot="fixture"\n')
    args = dict(config=CONFIG, output=tmp_path/'run', return_benchmark_config=benchmark)
    assert search.run(**args)['message'] == 'completed'
    count = len(calls)
    assert search.run(**args)['message'] == 'completed'
    assert len(calls) == count
    benchmark.write_text('[benchmarks]\nequal_weight_snapshot="changed"\n')
    with pytest.raises(ValueError, match='new search run'):
        search.run(**args)
    assert len(calls) == count


def test_interrupted_fresh_directory_stage_resumes_without_recomputing_training(tmp_path, monkeypatch):
    calls = fake_stages(monkeypatch, benchmark_failure=True)
    with pytest.raises(RuntimeError, match='interrupted'):
        search.run(config=CONFIG, output=tmp_path/'run')
    before = sum(name == 'statistics' for name, _ in calls)
    assert search.run(config=CONFIG, output=tmp_path/'run')['message'] == 'completed'
    assert sum(name == 'statistics' for name, _ in calls) == before
    assert (tmp_path/'run'/'benchmarks_partial_001'/'partial.txt').read_text() == 'unfinished'


def test_fully_rejected_family_skips_expensive_costs_but_keeps_validation(tmp_path, monkeypatch):
    calls = fake_stages(monkeypatch, passes=0)
    result = search.run(config=CONFIG, output=tmp_path/'run')
    assert result['message'] == 'completed'
    assert sum(name == 'statistics' for name, _ in calls) == 2
    assert not any(name in ('costs', 'benchmarks', 'redundancy') for name, _ in calls)


def test_overlapping_validation_is_rejected_before_registration(tmp_path, monkeypatch):
    config = tmp_path/'bad.toml'
    config.write_text(CONFIG.read_text().replace('validation_start = 2020-01-01', 'validation_start = 2019-12-31'))
    monkeypatch.setattr(search, 'prepare', lambda **kwargs: pytest.fail('must reject dates before registration'))
    with pytest.raises(ValueError, match='separation'):
        search.run(config=config, output=tmp_path/'run')


def test_interrupted_cost_parent_resumes_same_attempt_and_reuses_completed_factors(tmp_path, monkeypatch):
    calls = fake_stages(monkeypatch)
    attempts = []

    def costs(**kwargs):
        folder = kwargs['output']
        attempts.append(folder)
        assert kwargs['resume'] is True
        if len(attempts) == 1:
            assert kwargs['existing_runs'] == []
            (folder/'one').mkdir(parents=True)
            (folder/'one'/'summary.json').write_text('{}')
            (folder/'two').mkdir()
            (folder/'two'/'replay_config.json').write_text('{}')
            (folder/'two'/'saved_year.txt').write_text('retained checkpoint')
            raise RuntimeError('parent interrupted before batch summary')
        assert folder == attempts[0]
        assert kwargs['existing_runs'] == [folder/'one']
        assert (folder/'two'/'saved_year.txt').read_text() == 'retained checkpoint'
        result = {'completed_runs': {'one': str(folder/'one'), 'two': str(folder/'two')},
                  'failures': {}, 'pending_external_runs': {}}
        (folder/'batch_summary.json').write_text(json.dumps(result))
        return result

    monkeypatch.setattr(search, 'run_cost_batch', costs)
    output = tmp_path/'run'
    with pytest.raises(RuntimeError, match='parent interrupted'):
        search.run(config=CONFIG, output=output)
    assert not (output/'costs/attempt_001/batch_summary.json').exists()
    before = list(calls)
    assert search.run(config=CONFIG, output=output)['message'] == 'completed'
    assert len(attempts) == 2
    assert not (output/'costs/attempt_002').exists()
    assert sum(name == 'statistics' for name, _ in calls) == sum(name == 'statistics' for name, _ in before)
