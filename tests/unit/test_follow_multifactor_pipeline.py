import json

import pytest

from quant.research import follow_multifactor_pipeline as follower

@pytest.fixture(autouse=True)
def measurement_config(tmp_path):
    (tmp_path/'measurement.toml').write_text("index_version='fixture'\nindex_codes=['H00300.CSI','H00906.CSI','H00985.CSI']\n")



def setup(tmp_path, monkeypatch):
    root = tmp_path/'costs'
    root.mkdir()
    config = tmp_path/'config.toml'
    config.write_text(f"[research]\ncost_root='{root.as_posix()}'\ncost_runs=[]\n")
    clock = [0.0]
    monkeypatch.setattr(follower.time, 'monotonic', lambda: clock[0])
    return root, config, clock


def test_waits_without_recomputing_and_resumes_on_new_cost(tmp_path, monkeypatch):
    root, config, clock = setup(tmp_path, monkeypatch)
    calls, sleeps = [], []

    def run(**kwargs):
        calls.append(kwargs)
        kwargs['output'].mkdir()
        return {'model_results_ready': len(calls) == 2}

    def sleep(seconds):
        sleeps.append(seconds)
        clock[0] += seconds
        if len(sleeps) == 2:
            (root/'factor').mkdir()
            (root/'factor'/'summary.json').write_text('{}')

    monkeypatch.setattr(follower, 'run_pipeline', run)
    monkeypatch.setattr(follower.time, 'sleep', sleep)
    prior = tmp_path/'prior'
    result = follower.follow(config=config, measurement_config=tmp_path/'measurement.toml', output=tmp_path/'follow', data_root=tmp_path,
                             resume_from=prior)
    assert len(calls) == 2 and sleeps == [300, 300]
    assert calls[0]['resume_from'] == prior
    assert calls[1]['resume_from'] == calls[0]['output']
    assert calls[0]['measurement_config'] == tmp_path/'follow'/'measurement.toml'
    assert result['model_results_ready']


def test_changed_measurement_requires_new_follower_directory(tmp_path, monkeypatch):
    _, config, _ = setup(tmp_path, monkeypatch)
    monkeypatch.setattr(follower, 'run_pipeline', lambda **kwargs: {'model_results_ready': True})
    args = dict(config=config, output=tmp_path/'follow', data_root=tmp_path,
                measurement_config=tmp_path/'measurement.toml')
    follower.follow(**args)
    (tmp_path/'measurement.toml').write_text("index_version='changed'\n")
    with pytest.raises(ValueError, match='new follower directory'):
        follower.follow(**args)


def test_finished_batch_with_missing_evidence_stops_and_reports(tmp_path, monkeypatch):
    root, config, _ = setup(tmp_path, monkeypatch)
    (root/'batch_summary.json').write_text(json.dumps({'failures': {'a': 'failed'}, 'pending_external_runs': {}}))
    monkeypatch.setattr(follower, 'run_pipeline', lambda **kwargs: {'model_results_ready': False})
    monkeypatch.setattr(follower.time, 'sleep', lambda _: pytest.fail('Finished batch must not sleep'))
    result = follower.follow(config=config, measurement_config=tmp_path/'measurement.toml', output=tmp_path/'follow', data_root=tmp_path)
    assert not result['model_results_ready']
    assert 'inspect cost failures' in result['continuation_note']


def test_timeout_and_restart_reuse_partial_attempt(tmp_path, monkeypatch):
    _, config, clock = setup(tmp_path, monkeypatch)
    output = tmp_path/'follow'
    prior = output/'attempt_0001'
    prior.mkdir(parents=True)
    (output/'model.toml').write_bytes(config.read_bytes())
    calls = []

    def run(**kwargs):
        calls.append(kwargs)
        kwargs['output'].mkdir()
        return {'model_results_ready': False}

    monkeypatch.setattr(follower, 'run_pipeline', run)
    monkeypatch.setattr(follower.time, 'sleep', lambda seconds: clock.__setitem__(0, clock[0]+seconds))
    result = follower.follow(config=config, measurement_config=tmp_path/'measurement.toml', output=output, data_root=tmp_path, max_wait_hours=0.1)
    assert len(calls) == 1 and calls[0]['resume_from'] == prior
    assert calls[0]['output'].name == 'attempt_0002'
    assert 'Waiting limit reached' in result['continuation_note']
    config.write_text('[research]\ncost_root="other"\n')
    with pytest.raises(ValueError, match='same frozen'):
        follower.follow(config=config, measurement_config=tmp_path/'measurement.toml', output=output, data_root=tmp_path)


def test_new_cost_during_run_is_not_lost_when_batch_finishes(tmp_path, monkeypatch):
    root, config, clock = setup(tmp_path, monkeypatch)
    calls = []

    def run(**kwargs):
        calls.append(kwargs)
        kwargs['output'].mkdir()
        if len(calls) == 1:
            (root/'factor').mkdir()
            (root/'factor'/'summary.json').write_text('{}')
            (root/'batch_summary.json').write_text('{"pending_external_runs": {}}')
        return {'model_results_ready': len(calls) == 2}

    monkeypatch.setattr(follower, 'run_pipeline', run)
    monkeypatch.setattr(follower.time, 'sleep', lambda seconds: clock.__setitem__(0, clock[0]+seconds))
    result = follower.follow(config=config, measurement_config=tmp_path/'measurement.toml', output=tmp_path/'follow', data_root=tmp_path)
    assert len(calls) == 2 and result['model_results_ready']


@pytest.mark.parametrize('benchmark_change', [False, True])
def test_completed_diagnostic_is_not_repeated_without_new_cost(tmp_path, monkeypatch, benchmark_change):
    _, config, clock = setup(tmp_path, monkeypatch)
    prior = tmp_path/'prior'
    (prior/'costs').mkdir(parents=True)
    (prior/'model.toml').write_bytes(config.read_bytes())
    (prior/'summary.json').write_text('{"model_results_ready": false}')
    (prior/'costs'/'summary.json').write_text('{"source_runs": {}}')
    calls = []
    def run(**kwargs):
        calls.append(kwargs)
        return {'model_results_ready': True}
    monkeypatch.setattr(follower, 'run_pipeline', run)
    if benchmark_change:
        (tmp_path/'measurement.toml').write_text('[benchmarks]\nequal_weight_snapshot="new"\n')
    monkeypatch.setattr(follower.time, 'sleep', lambda seconds: clock.__setitem__(0, clock[0]+seconds))
    result = follower.follow(config=config, measurement_config=tmp_path/'measurement.toml', output=tmp_path/'follow', data_root=tmp_path,
                             resume_from=prior, max_wait_hours=0.1)
    assert len(calls) == int(benchmark_change)
    assert result['latest_run'] == (str(tmp_path/'follow'/'attempt_0001') if benchmark_change else str(prior))
