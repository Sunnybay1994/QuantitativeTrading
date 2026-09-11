import sys
from pathlib import Path

import pytest

from quant.research import evaluate_forecast_text as pipeline


@pytest.mark.parametrize('full,reuse', [(False, False), (True, False), (True, True)])
def test_pipeline_connects_same_window_peers_benchmarks_and_complete_costs(tmp_path, monkeypatch, full, reuse):
    calls = []
    def stage(name, result):
        def run(*args, **kwargs):
            calls.append((name, kwargs))
            return result
        return run
    monkeypatch.setattr(pipeline, 'publish_panels', stage('publish', {}))
    monkeypatch.setattr(pipeline, 'run_incremental', stage('incremental', {'summary': []}))
    monkeypatch.setattr('quant.research.factor_battery_batch.run_statistics', stage('statistics', {}))
    monkeypatch.setattr('quant.research.factor_battery_screen.run_screen', stage('screen', {}))
    monkeypatch.setattr('quant.research.forecast_text_redundancy.run_redundancy', stage('redundancy', {}))
    monkeypatch.setattr('quant.research.factor_battery_benchmarks.run_benchmarks', stage('benchmarks', {}))
    external = tmp_path/'completed_cost'
    costs = {'completed_runs': {'text': str(external)},
             'failures': {'other_text': 'fixture failure'}, 'pending_external_runs': {}}
    monkeypatch.setattr('quant.research.factor_battery_cost_batch.run_cost_batch', stage('costs', costs))
    monkeypatch.setattr('quant.research.factor_battery_scorecard.run_scorecard',
                        stage('scorecard', {'admission_unresolved_rows': 1}))
    peer = tmp_path/'existing_peers' if reuse else None
    result = pipeline.run_pipeline(run=tmp_path/'scoring', output=tmp_path/'output',
        data_root=tmp_path/'data', design_path=Path('configs/factors/p7_text_evaluation_v2.toml'),
        execution_snapshot='snapshot' if full else None, peer_statistics=peer,
        existing_cost_runs=[external] if full else None)
    assert result['mode'] == ('full' if full else 'statistics_only')
    card = calls[-1][1]
    assert calls[-1][0] == 'scorecard' and card['cost_root'] is None
    assert card['cost_runs'] == ([external] if full else [])
    if full:
        peer_stats = peer or tmp_path/'output/peer_statistics'
        comparison = next(args for name, args in calls if name == 'redundancy')
        assert comparison['peer_statistics'] == peer_stats
        assert card['redundancy'] == tmp_path/'output/redundancy'
        assert card['benchmarks'] == tmp_path/'output/benchmarks'
        assert result['costs']['failures'] == costs['failures']
        statistics = [args for name, args in calls if name == 'statistics']
        assert len(statistics) == (1 if reuse else 2)
        assert all(args['config'] == tmp_path/'scoring/battery.toml' for args in statistics)
        assert len({args['as_of'] for args in statistics}) == 1
    else:
        assert not any(name in {'redundancy', 'benchmarks', 'costs'} for name, _ in calls)
        assert card['redundancy'] is card['benchmarks'] is None


def test_invalid_full_inputs_fail_before_publication(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, 'publish_panels', lambda **kwargs: pytest.fail('publication must not start'))
    with pytest.raises(ValueError, match='execution snapshot'):
        pipeline.run_pipeline(run=tmp_path, output=tmp_path/'new', data_root=tmp_path,
            design_path=Path('configs/factors/p7_text_evaluation_v2.toml'), peer_statistics=tmp_path/'peers')
    assert not (tmp_path/'new').exists()


@pytest.mark.parametrize('pending', [False, True])
def test_cli_reports_failed_or_pending_costs(tmp_path, monkeypatch, pending):
    monkeypatch.setattr(sys, 'argv', ['evaluate', '--run', str(tmp_path), '--output', str(tmp_path/'new')])
    monkeypatch.setattr(pipeline, 'run_pipeline', lambda **kwargs: {
        'costs': {'failures': {} if pending else {'failed': 'error'},
                  'pending_external_runs': {'waiting': 'external'} if pending else {}}})
    with pytest.raises(SystemExit) as exc:
        pipeline.main()
    assert exc.value.code == 1
