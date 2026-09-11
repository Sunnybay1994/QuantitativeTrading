import datetime as dt
import json
import sys

import pytest

from quant.research import run_factor_pipeline as pipeline


def arguments(tmp_path):
    return dict(config=tmp_path/'battery.toml', library=tmp_path/'library',
                as_of=dt.date(2026, 8, 31), output=tmp_path/'run', data_root=tmp_path/'data',
                execution_snapshot='frozen_inputs', workers=2)


def test_failed_statistics_preserves_partial_run_and_never_starts_costs(monkeypatch, tmp_path):
    calls = []

    def statistics(**kwargs):
        calls.append('statistics')
        kwargs['output'].mkdir()
        (kwargs['output']/'partial.txt').write_text('retained')
        raise ValueError('missing exchange session')

    def forbidden(**kwargs):
        pytest.fail('Do not run later stages after incomplete statistical inputs')

    monkeypatch.setattr(pipeline, 'run_statistics', statistics)
    for name in ('run_screen', 'run_benchmarks', 'run_redundancy', 'run_cost_batch', 'run_scorecard'):
        monkeypatch.setattr(pipeline, name, forbidden)
    args = arguments(tmp_path)
    with pytest.raises(ValueError, match='missing exchange session'):
        pipeline.run_pipeline(**args)
    assert (args['output']/'statistics'/'partial.txt').read_text() == 'retained'
    with pytest.raises(FileExistsError):
        pipeline.run_pipeline(**args)
    assert calls == ['statistics']


def test_cost_failures_remain_visible_with_useful_scorecard(monkeypatch, tmp_path):
    finished = []

    def stage(name):
        def run(**kwargs):
            if name != 'statistics':
                assert (kwargs['statistics']/'finished').is_file()
            kwargs['output'].mkdir()
            (kwargs['output']/'finished').write_text(name)
            finished.append(name)
        return run

    for name in ('statistics', 'screen', 'benchmarks', 'redundancy'):
        monkeypatch.setattr(pipeline, 'run_'+name, stage(name))

    def costs(**kwargs):
        assert (kwargs['screen']/'finished').is_file()
        kwargs['output'].mkdir()
        return {'failures': {'sparse_factor': 'No executable top-group observations'}}

    def scorecard(**kwargs):
        assert all((kwargs[key]/'finished').is_file() for key in ('screen', 'benchmarks', 'redundancy'))
        assert kwargs['cost_root'].is_dir()
        kwargs['output'].mkdir()
        return {'rows': 4, 'cost_complete_rows': 2, 'admitted_rows': 0, 'admission_unresolved_rows': 0}

    monkeypatch.setattr(pipeline, 'run_cost_batch', costs)
    monkeypatch.setattr(pipeline, 'run_scorecard', scorecard)
    args = arguments(tmp_path)
    result = pipeline.run_pipeline(**args)
    assert result['scorecard']['cost_complete_rows'] == 2
    assert 'sparse_factor' in json.loads((args['output']/'summary.json').read_text())['cost_failures']
    assert 'No executable top-group observations' in (args['output']/'report.md').read_text(encoding='utf-8')
    assert finished == ['statistics', 'screen', 'benchmarks', 'redundancy']


def test_cli_reports_partial_cost_failure_with_nonzero_exit(monkeypatch, capsys):
    monkeypatch.setattr(sys, 'argv', ['battery', '--as-of', '2026-08-31',
                                    '--execution-snapshot', 'snapshot', '--output', 'unused'])
    monkeypatch.setattr(pipeline, 'run_pipeline', lambda **kwargs: {
        'cost_failures': {'sparse_factor': 'No executable top group'}})
    with pytest.raises(SystemExit) as error:
        pipeline.main()
    assert error.value.code == 1
    assert 'sparse_factor' in json.loads(capsys.readouterr().out)['cost_failures']
