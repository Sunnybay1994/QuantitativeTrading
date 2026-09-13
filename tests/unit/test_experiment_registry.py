import json
from pathlib import Path

import polars as pl
import pytest

from quant.reporting.experiment_registry import records_from_run, register_run


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
