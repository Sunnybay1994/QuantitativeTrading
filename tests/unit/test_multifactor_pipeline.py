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
