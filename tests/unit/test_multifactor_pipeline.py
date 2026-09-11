import json

import pytest

from quant.research import run_multifactor_pipeline as pipeline


@pytest.mark.parametrize('complete', [False, True])
def test_pipeline_waits_for_evidence_then_runs_prediction_replay_and_report(tmp_path, monkeypatch, complete):
    config = tmp_path/'model.toml'
    config.write_text("[research]\nstock_benchmarks='bench'\ncost_root='costs'\ncost_runs=['external']\n")
    calls = []

    def stage(name, result):
        def run(**kwargs):
            calls.append((name, kwargs))
            return result
        return run

    selected = {'annual_selection': [{'test_year': 2023, 'selection_complete': complete,
        'unresolved_factors': 0 if complete else 1, 'confirmed_selected_prefix': ['a']}]}
    for function, name, result in (
        ('run_prefixes', 'statistics', {}), ('run_cost_prefixes', 'costs', {'complete_cost_factors': 2}),
        ('run_selection', 'selection', selected), ('run_predictions', 'predictions', {}),
        ('run_model_replay', 'replay', {}), ('report_models', 'reports', {'conclusions': {'equal_z': 'REJECTED'}})):
        monkeypatch.setattr(pipeline, function, stage(name, result))
    output = tmp_path/'output'
    result = pipeline.run_pipeline(config=config, output=output, data_root=tmp_path/'data')
    assert [name for name, _ in calls] == (['statistics', 'costs', 'selection', 'predictions', 'replay', 'reports']
                                         if complete else ['statistics', 'costs', 'selection'])
    assert calls[1][1]['cost_runs'][0].name == 'external'
    assert result['model_results_ready'] is complete
    assert json.loads((output/'summary.json').read_text()) == result
    assert (output/'report.md').is_file()
    with pytest.raises(FileExistsError):
        pipeline.run_pipeline(config=config, output=output, data_root=tmp_path/'data')


@pytest.mark.parametrize('complete,replay_complete', [(False, False), (True, False), (True, True)])
def test_resume_preserves_prior_run_and_only_reuses_completed_evidence(tmp_path, monkeypatch, complete, replay_complete):
    config = tmp_path/'model.toml'
    config.write_text("[research]\nstock_benchmarks='bench'\ncost_root='costs'\n")
    prior = tmp_path/'prior'
    prior.mkdir()
    (prior/'model.toml').write_bytes(config.read_bytes())
    selected = {'annual_selection': [{'test_year': 2023, 'selection_complete': complete,
        'unresolved_factors': 0 if complete else 1, 'confirmed_selected_prefix': ['a']}]}
    for name, files, summary in (
        ('statistics', ['annual_statistical_screen.parquet'], {'factors': 2}),
        ('costs', ['annual_cost_screen.parquet'], {'complete_cost_factors': 2}),
        ('selection', ['annual_selection.parquet'], selected),
        ('predictions', ['monthly_predictions.parquet'], {'prediction_rows': 100})):
        folder = prior/name
        folder.mkdir()
        for file in [*files, 'model.toml', 'battery.toml']:
            (folder/file).write_text('fixture')
        (folder/'model.toml').write_bytes(config.read_bytes())
        (folder/'summary.json').write_text(json.dumps(summary))
    # A replay interrupted before summary publication must be rerun in the new output.
    (prior/'replay').mkdir()
    (prior/'replay'/'partial.txt').write_text('retained')
    (prior/'selection'/'annual_correlations.parquet').write_text('fixture')
    if replay_complete:
        (prior/'replay'/'summary.json').write_text('{}')
        (prior/'replay'/'model.toml').write_bytes(config.read_bytes())
        (prior/'replay'/'battery.toml').write_text('fixture')
    before = {str(p.relative_to(prior)): p.read_bytes() for p in prior.rglob('*') if p.is_file()}
    calls = []

    def stage(name, result):
        def run(**kwargs):
            calls.append(name)
            if name == 'selection':
                assert kwargs['correlations_from'] == prior/'selection'
            return result
        return run

    for function, name, result in (
        ('run_prefixes', 'statistics', {}), ('run_cost_prefixes', 'costs', {'complete_cost_factors': 3}),
        ('run_selection', 'selection', selected), ('run_predictions', 'predictions', {}),
        ('run_model_replay', 'replay', {}), ('report_models', 'reports', {'conclusions': {}})):
        monkeypatch.setattr(pipeline, function, stage(name, result))
    result = pipeline.run_pipeline(config=config, output=tmp_path/'new', data_root=tmp_path,
                                   resume_from=prior)
    assert calls == (['reports'] if replay_complete else ['replay', 'reports'] if complete else ['costs', 'selection'])
    assert result['completed_cost_factors'] == (2 if complete else 3)
    assert before == {str(p.relative_to(prior)): p.read_bytes() for p in prior.rglob('*') if p.is_file()}
    config.write_text(config.read_text()+'\nchanged=true\n')
    with pytest.raises(ValueError, match='same frozen'):
        pipeline.run_pipeline(config=config, output=tmp_path/'mismatch', data_root=tmp_path,
                              resume_from=prior)
    assert not (tmp_path/'mismatch').exists()
