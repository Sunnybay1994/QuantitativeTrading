import json
from pathlib import Path

import polars as pl
import pytest

from quant.reporting.experiment_registry import records_from_run, register_run


def test_factor_battery_registration_keeps_empty_costs_and_requires_completion(tmp_path):
    run = tmp_path/'battery'
    run.mkdir()
    (run/'pipeline_config.json').write_text('{}')
    (run/'report.md').write_text('Generated report')
    scorecard = run/'factor_scorecard.parquet'
    pl.DataFrame({'factor': ['empty'], 'variant': ['raw'], 'conclusion': ['REJECTED']}).write_parquet(scorecard)
    summary = {'scorecard_path': str(scorecard), 'cost_failures': {}, 'pending_external_runs': {},
               'non_executable_rejections': {'empty': 'no top group'}}
    (run/'summary.json').write_text(json.dumps(summary))
    records = records_from_run(run)
    assert len(records) == 1 and records[0]['conclusion'] == 'REJECTED'
    assert records[0]['cagr_1x'] is None and records[0]['excess_2x'] is None
    assert register_run(run, tmp_path/'registry.parquet', tmp_path/'board.md') == 1
    summary['cost_failures'] = {'empty': 'missing input'}
    (run/'summary.json').write_text(json.dumps(summary))
    with pytest.raises(ValueError, match='unfinished'):
        records_from_run(run)


def saved_run(root: Path, conclusion: str = 'REJECTED') -> Path:
    root.mkdir()
    (root/'config.toml').write_text('[research]\nid="example"\n', encoding='utf-8')
    (root/'report.md').write_text('Machine report', encoding='utf-8')
    rows = [{'variant': 'budgeted', 'cost_multiplier': c, 'active_start': '2020-01-02',
             'report_end': '2026-08-31', 'cagr': .2-c*.01, 'sharpe': 1.,
             'max_drawdown': -.2, 'annualized_one_way_turnover': 6.2} for c in (.5, 1., 2.)]
    (root/'assessment.json').write_text(json.dumps({'rows': rows,
        'assessments': {'budgeted': {'conclusion': conclusion, 'net_cagr_excess': .08}}}), encoding='utf-8')
    return root


def test_history_idempotence_missing_metrics_and_backup(tmp_path):
    registry, board = tmp_path/'registry/experiments.parquet', tmp_path/'board.md'
    board.write_text('Original user content', encoding='utf-8')
    old = saved_run(tmp_path/'old')
    assert register_run(old, registry, board) == 1
    first = registry.read_bytes()
    assert register_run(old, registry, board) == 1
    assert registry.read_bytes() == first
    backups = list(registry.parent.glob('leaderboard_before_machine_*.md'))
    assert len(backups) == 1
    assert backups[0].read_text() == 'Original user content'
    new = saved_run(tmp_path/'new', 'PAPER_CANDIDATE')
    assert register_run(new, registry, board) == 2
    frame = pl.read_parquet(registry)
    assert frame['excess_0_5x'].null_count() == 2
    assert frame['excess_2x'].null_count() == 2
    assert frame['excess_1x'].to_list() == [.08, .08]
    assert 'PAPER_CANDIDATE' in board.read_text(encoding='utf-8')


def test_incomplete_costs_rejected(tmp_path):
    run = saved_run(tmp_path/'run')
    path = run/'assessment.json'
    result = json.loads(path.read_text())
    result['rows'].pop()
    path.write_text(json.dumps(result))
    with pytest.raises(ValueError, match='exactly 0.5/1/2x'):
        records_from_run(run)


def test_each_cost_uses_own_benchmark_window(tmp_path):
    run = saved_run(tmp_path/'run')
    path = run/'assessment.json'
    result = json.loads(path.read_text())
    result['benchmark_comparisons'] = [{'variant': 'budgeted', 'cost_multiplier': c,
        'benchmark_cagr': c*.02} for c in (.5, 1., 2.)]
    path.write_text(json.dumps(result))
    row = records_from_run(run)[0]
    assert row['excess_0_5x'] == pytest.approx(.185)
    assert row['excess_1x'] == pytest.approx(.17)
    assert row['excess_2x'] == pytest.approx(.14)


def test_q10_related_experiment_keeps_own_freeze_and_evidence_in_registry_and_board(tmp_path):
    from quant.reporting.leaderboard import write_leaderboard
    run=saved_run(tmp_path/'q10_combo')
    (run/'config.toml').write_text('[research]\nid="q10_plus_admitted_v1"\nregistered_on=2026-10-10\n')
    record=records_from_run(run)[0]
    assert record['design_date']=='2026-10-10' and record['oos_start']=='2026-11'
    assert record['oos_months']==0 and record['sample_scope']=='IS_ONLY'
    registry,board=tmp_path/'registry.parquet',tmp_path/'board.md'
    # Simulate an existing poisoned registry; rendering must repair persistence too.
    record.update(design_date='2026-09-12',oos_start='2026-10',oos_months=1,sample_scope='HAS_OOS')
    pl.DataFrame([record]).write_parquet(registry)
    write_leaderboard(registry,board)
    saved=pl.read_parquet(registry).row(0,named=True)
    assert saved['design_date']=='2026-10-10'
    assert saved['oos_start']=='2026-11' and saved['oos_months']==0 and saved['sample_scope']=='IS_ONLY'
    assert 'HAS_OOS' not in board.read_text(encoding='utf-8')
    assert saved['conclusion']==record['conclusion']
    assert (tmp_path/'排行榜_因子.md').exists()


def test_render_does_not_overwrite_a_concurrent_append_or_publish_stale_board(tmp_path, monkeypatch):
    from quant.reporting import leaderboard
    from quant.reporting.experiment_registry import append_records

    registry, board = tmp_path/'registry.parquet', tmp_path/'board.md'
    old, new = saved_run(tmp_path/'old'), saved_run(tmp_path/'new', 'PAPER_CANDIDATE')
    append_records(records_from_run(old), registry)
    board.write_text('Existing board', encoding='utf-8')
    render = leaderboard._render
    appended = []

    def concurrent(*args, **kwargs):
        if not appended:
            append_records(records_from_run(new), registry)
            appended.append(True)
        return render(*args, **kwargs)

    monkeypatch.setattr(leaderboard, '_render', concurrent)
    with pytest.raises(ValueError, match='Registry changed while rendering'):
        leaderboard.write_leaderboard(registry, board)
    assert pl.read_parquet(registry).height == 2
    assert board.read_text(encoding='utf-8') == 'Existing board'
    assert not (tmp_path/'排行榜_因子.md').exists()
    assert not list(tmp_path.glob('registry.parquet.*.tmp'))
    leaderboard.write_leaderboard(registry, board)
    assert pl.read_parquet(registry).height == 2
    assert set(pl.read_parquet(registry)['conclusion']) == {'REJECTED', 'PAPER_CANDIDATE'}


def test_render_uses_the_same_registry_lock_as_append(tmp_path):
    from quant.execution.manual_session_service import instance_lock
    from quant.reporting.experiment_registry import append_records
    from quant.reporting.leaderboard import write_leaderboard

    registry = tmp_path/'registry.parquet'
    append_records(records_from_run(saved_run(tmp_path/'run')), registry)
    original = registry.read_bytes()
    with instance_lock(registry.with_suffix('.lock')), pytest.raises(OSError):
        write_leaderboard(registry, tmp_path/'board.md')
    assert registry.read_bytes() == original
    assert not (tmp_path/'board.md').exists()
    assert not list(tmp_path.glob('registry.parquet.*.tmp'))
