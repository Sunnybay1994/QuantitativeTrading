import datetime as dt
import json
import sys
from pathlib import Path

import pytest
import polars as pl

from quant.research import run_factor_pipeline as pipeline
from quant.research.factor_battery_cost_batch import run_cost_batch


def arguments(tmp_path):
    (tmp_path/'battery.toml').write_text('start = 2010-01-01\n')
    (tmp_path/'library').mkdir(exist_ok=True)
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


@pytest.mark.parametrize('pending', [False, True])
def test_cost_failures_remain_visible_with_useful_scorecard(monkeypatch, tmp_path, pending):
    finished = []
    external = tmp_path/'completed_elsewhere'
    waiting = {'waiting_factor': str(tmp_path/'inflight')} if pending else {}

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
        assert kwargs['existing_runs'] == [external]
        kwargs['output'].mkdir()
        return {'failures': {'sparse_factor': 'No executable top-group observations'},
                'completed_runs': {'good_factor': str(external)}, 'pending_external_runs': waiting}

    def scorecard(**kwargs):
        assert all((kwargs[key]/'finished').is_file() for key in ('screen', 'benchmarks', 'redundancy'))
        assert kwargs['cost_root'] is None
        assert kwargs['cost_runs'] == [external]
        assert kwargs['return_benchmark_config'] == tmp_path/'run'/'return_benchmarks.toml'
        assert kwargs['return_benchmark_config'].read_text() == '[benchmarks]\nequal_weight_snapshot="fixture"\n'
        kwargs['output'].mkdir()
        return {'rows': 4, 'cost_complete_rows': 2, 'admitted_rows': 0, 'admission_unresolved_rows': 0}

    monkeypatch.setattr(pipeline, 'run_cost_batch', costs)
    monkeypatch.setattr(pipeline, 'run_scorecard', scorecard)
    args = arguments(tmp_path)
    benchmark = tmp_path/'returns.toml'
    benchmark.write_text('[benchmarks]\nequal_weight_snapshot="fixture"\n')
    args['return_benchmark_config'] = benchmark
    result = pipeline.run_pipeline(**args, existing_runs=[external])
    benchmark.write_text('[benchmarks]\nequal_weight_snapshot="changed"\n')
    with pytest.raises(ValueError, match='unchanged pipeline'):
        pipeline.run_pipeline(**args, existing_runs=[external], resume=True)
    assert result['scorecard']['cost_complete_rows'] == 2
    assert 'sparse_factor' in json.loads((args['output']/'summary.json').read_text())['cost_failures']
    assert 'No executable top-group observations' in (args['output']/'report.md').read_text(encoding='utf-8')
    assert result['pending_external_runs'] == waiting
    assert ('外部成本回放尚未完成' in (args['output']/'report.md').read_text(encoding='utf-8')) == pending
    assert finished == ['statistics', 'screen', 'benchmarks', 'redundancy']


@pytest.mark.parametrize('pending', [False, True])
def test_cli_reports_partial_cost_failure_with_nonzero_exit(monkeypatch, capsys, pending):
    monkeypatch.setattr(sys, 'argv', ['battery', '--as-of', '2026-08-31',
                                    '--execution-snapshot', 'snapshot', '--output', 'unused'])
    monkeypatch.setattr(pipeline, 'run_pipeline', lambda **kwargs: {
        'cost_failures': {} if pending else {'sparse_factor': 'No executable top group'},
        'pending_external_runs': {'running': 'external'} if pending else {}})
    with pytest.raises(SystemExit) as error:
        pipeline.main()
    assert error.value.code == 1
    result = json.loads(capsys.readouterr().out)
    assert result['pending_external_runs'] if pending else result['cost_failures']


def test_real_batch_reuses_external_result_without_a_local_replay(tmp_path):
    statistics, screen, external = (tmp_path/name for name in ('statistics', 'screen', 'external'))
    config = 'primary_variant = "raw"\n'
    for folder in (statistics, screen, external):
        folder.mkdir()
        (folder/'battery.toml').write_text(config)
    (external/'battery.toml').write_text(config +
        '[cost_replay]\nfactor = "sample"\nexecution_snapshot = "frozen"\n')
    (external/'summary.json').write_text('{}')
    table = pl.DataFrame({'factor': ['sample'], 'variant': ['raw'],
                          'statistical_pass': [True], 'icir': [0.5]})
    table.select('factor', 'variant').write_parquet(statistics/'statistics.parquet')
    table.write_parquet(screen/'statistical_screen.parquet')
    result = run_cost_batch(statistics=statistics, screen=screen, output=tmp_path/'costs',
                           data_root=tmp_path, execution_snapshot='frozen',
                           existing_runs=[external], workers=1)
    assert result['completed_runs'] == {'sample': str(external)}
    assert result['failures'] == result['pending_external_runs'] == {}
    assert not (tmp_path/'costs'/'sample').exists()


def test_resume_reuses_heavy_stages_continues_costs_and_preserves_old_scorecard(tmp_path, monkeypatch):
    args = arguments(tmp_path)
    calls = []
    cost_calls = []

    def stage(name):
        def run(**kwargs):
            calls.append(name)
            kwargs['output'].mkdir()
            (kwargs['output']/'summary.json').write_text('{}')
        return run

    for name in ('statistics', 'screen', 'benchmarks', 'redundancy'):
        monkeypatch.setattr(pipeline, 'run_'+name, stage(name))

    def costs(**kwargs):
        cost_calls.append(kwargs['resume'])
        kwargs['output'].mkdir(exist_ok=True)
        return {'completed_runs': {}, 'failures': {'a': 'interrupted'} if len(cost_calls) == 1 else {},
                'pending_external_runs': {}}

    def scorecard(**kwargs):
        kwargs['output'].mkdir()
        (kwargs['output']/'factor_scorecard.parquet').write_bytes(b'fixture')
        return {'rows': 2, 'cost_complete_rows': len(cost_calls), 'admitted_rows': 0,
                'admission_unresolved_rows': 0}

    monkeypatch.setattr(pipeline, 'run_cost_batch', costs)
    monkeypatch.setattr(pipeline, 'run_scorecard', scorecard)
    first = pipeline.run_pipeline(**args)
    second = pipeline.run_pipeline(**args, resume=True)
    assert first['cost_failures'] and not second['cost_failures']
    assert calls == ['statistics', 'screen', 'benchmarks', 'redundancy']
    assert cost_calls == [False, True]
    assert first['scorecard_path'] != second['scorecard_path']
    assert (args['output']/'scorecard/factor_scorecard.parquet').is_file()
    assert (args['output']/'scorecard_002/factor_scorecard.parquet').is_file()
    assert pipeline.run_pipeline(**args, resume=True) == second
    assert cost_calls == [False, True]


@pytest.mark.parametrize('change', ['config', 'library', 'snapshot', 'external'])
def test_resume_rejects_changed_inputs_before_any_stage(tmp_path, monkeypatch, change):
    args = arguments(tmp_path)

    def interrupted(**kwargs):
        raise RuntimeError('interrupted statistics')

    monkeypatch.setattr(pipeline, 'run_statistics', interrupted)
    with pytest.raises(RuntimeError):
        pipeline.run_pipeline(**args)
    if change == 'config':
        args['config'].write_text('start = 2011-01-01\n')
    elif change == 'library':
        (args['library']/'new.toml').write_text('id="new"\n')
    elif change == 'snapshot':
        args['execution_snapshot'] = 'different'
    else:
        args['existing_runs'] = [tmp_path/'different']
    monkeypatch.setattr(pipeline, 'run_statistics', lambda **kwargs: pytest.fail('must reject before work'))
    with pytest.raises(ValueError, match='unchanged'):
        pipeline.run_pipeline(**args, resume=True)


def test_resume_preserves_interrupted_benchmark_directory(tmp_path, monkeypatch):
    args = arguments(tmp_path)
    visits = []

    def run_stage(**kwargs):
        folder = kwargs['output']
        folder.mkdir()
        visits.append(folder.name)
        if folder.name == 'benchmarks' and visits.count('benchmarks') == 1:
            (folder/'partial.txt').write_text('keep this output')
            raise RuntimeError('benchmark interrupted')
        (folder/'summary.json').write_text('{}')

    for name in ('statistics', 'screen', 'benchmarks', 'redundancy'):
        monkeypatch.setattr(pipeline, 'run_'+name, run_stage)
    monkeypatch.setattr(pipeline, 'run_cost_batch', lambda **kwargs: {
        'completed_runs': {}, 'failures': {}, 'pending_external_runs': {}})
    monkeypatch.setattr(pipeline, 'run_scorecard', lambda **kwargs: {
        'rows': 2, 'cost_complete_rows': 0, 'admitted_rows': 0, 'admission_unresolved_rows': 2})
    with pytest.raises(RuntimeError, match='benchmark interrupted'):
        pipeline.run_pipeline(**args)
    pipeline.run_pipeline(**args, resume=True)
    assert visits == ['statistics', 'screen', 'benchmarks', 'benchmarks', 'redundancy']
    preserved = list(args['output'].glob('benchmarks_partial_*/partial.txt'))
    assert len(preserved) == 1 and preserved[0].read_text() == 'keep this output'


@pytest.mark.parametrize('state', ['dry_run', 'success', 'deferred_off_peak', 'budget_exhausted'])
def test_cli_appends_budgeted_diagnosis_without_replaying_complete_pipeline(tmp_path, monkeypatch, capsys, state):
    from quant.research import deepseek_diagnostics
    from quant.research import score_forecast_text
    output = tmp_path/'run'
    output.mkdir()
    (output/'diagnosis').mkdir()
    scorecard = output/'scorecard/factor_scorecard.parquet'
    invoked = []
    live = state != 'dry_run'
    arguments = ['pipeline', '--as-of', '2026-08-31', '--execution-snapshot', 'saved',
                 '--output', str(output), '--resume', '--diagnosis-config', 'diagnosis.toml',
                 '--assessment', 'assessment.json']
    if live:
        arguments += ['--diagnosis-execute', '--diagnosis-max-requests', '20', '--diagnosis-max-usd', '0.05']
    monkeypatch.setattr(sys, 'argv', arguments)
    monkeypatch.setattr(score_forecast_text, 'load_settings', lambda path: {})

    def pipeline_result(**kwargs):
        assert kwargs['resume'] is True
        return {'cost_failures': {}, 'pending_external_runs': {}, 'scorecard_path': str(scorecard)}

    def diagnosis(**kwargs):
        invoked.append(kwargs)
        assert kwargs['scorecard'] == scorecard
        assert kwargs['assessments'] == [Path('assessment.json')]
        assert kwargs['execute'] is live
        assert kwargs['max_requests'] == (20 if live else 0)
        assert kwargs['max_usd'] == (0.05 if live else 0)
        assert kwargs['output'] == output/'diagnosis_002'
        assert kwargs['cache_path'] == Path('artifacts/research/p7_deepseek_cache.sqlite')
        return {'result': state, 'dry_run': not live, 'deferred_until': 'later' if state == 'deferred_off_peak' else None,
                'usd_bound_including_retries': .02}

    monkeypatch.setattr(pipeline, 'run_pipeline', pipeline_result)
    monkeypatch.setattr(deepseek_diagnostics, 'run_diagnosis', diagnosis)
    if state in ('dry_run', 'success'):
        pipeline.main()
    else:
        with pytest.raises(SystemExit) as error:
            pipeline.main()
        assert error.value.code == 1
    assert len(invoked) == 1
    saved = json.loads((output/'summary.json').read_text())
    assert saved['scorecard_path'] == str(scorecard)
    assert saved['diagnosis']['result'] == state
    assert json.loads(capsys.readouterr().out) == saved


def test_live_diagnosis_without_budget_rejected_before_research(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['pipeline', '--as-of', '2026-08-31', '--execution-snapshot', 'saved',
        '--output', str(tmp_path/'run'), '--diagnosis-config', 'config.toml', '--diagnosis-execute'])
    monkeypatch.setattr(pipeline, 'run_pipeline', lambda **kwargs: pytest.fail('reject before expensive work'))
    with pytest.raises(SystemExit) as error:
        pipeline.main()
    assert error.value.code == 2
