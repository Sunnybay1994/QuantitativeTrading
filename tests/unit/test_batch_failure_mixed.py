import json
from pathlib import Path

import polars as pl
import pytest

from quant.research import batch_failure_diagnostics as module


def definition(path, identifier, expression, source):
    path.parent.mkdir(parents=True, exist_ok=True)
    value = {'id': identifier, 'expr': expression, 'direction': 1,
             'family': 'fixture', 'source_ref': source}
    path.write_text(''.join(f'{key} = {json.dumps(item)}\n' for key, item in value.items()))


@pytest.fixture
def mixed(tmp_path):
    run, batch = tmp_path/'run', tmp_path/'battery'
    run.mkdir()
    definition(batch/'library/gp.toml', 'gp', 'close', str(run/'N2/search.json'))
    definition(batch/'library/queued.toml', 'queued', 'amount', 'registered_battery:fixture.toml')
    definition(run/'candidates/queued.toml', 'queued', 'amount', 'registered_battery:fixture.toml')
    result = {'batch': str(batch), 'candidates': 2, 'evaluated': 2}
    candidates = [{'factor_id': 'gp', 'expression': 'close', 'direction': 1,
                   'terminal_expression': 'gp_close', 'train': {'mean_ic': .02}}]
    rows = [{'factor': factor, 'variant': variant, 'direction': 1}
            for factor in ['gp', 'queued'] for variant in ['raw', 'size_industry_neutral']]
    steps = {'N1': {'ok': True, 'result': {'queued_candidates': 1}}}
    return run, result, candidates, rows, steps, ['raw', 'size_industry_neutral']


def test_mixed_requires_exact_frozen_sets_and_preserves_separate_denominators(mixed):
    scope, definitions, paths = module.battery_scope(*mixed)
    assert scope['mode'] == 'mixed_battery'
    assert scope['complete_battery']['candidates'] == 2
    assert scope['complete_battery']['variants'] == 4
    assert scope['N2_search']['variants'] == scope['fixed_queue']['variants'] == 2
    assert scope['training_comparison_candidates'] == 1
    assert scope['queued_sources'][0]['training_comparison'] == 'not_applicable'
    assert set(definitions) == {'gp', 'queued'} and len(paths) == 3


@pytest.mark.parametrize('change', ['extra_scorecard', 'missing_scorecard', 'missing_variant',
    'duplicate_variant', 'N2_missing', 'N2_expression', 'N2_direction', 'N1_count', 'N1_failed',
    'queue_definition', 'blank_source', 'extra_claims_N2'])
def test_mixed_does_not_admit_arbitrary_subsets_or_unproven_extra_factors(mixed, change):
    run, result, candidates, rows, steps, _ = mixed
    frozen = Path(result['batch'])/'library'
    if change == 'extra_scorecard':
        rows.append({'factor': 'undeclared', 'variant': 'raw'})
    elif change == 'missing_scorecard':
        rows[:] = [row for row in rows if row['factor'] != 'queued']
    elif change == 'missing_variant':
        rows.pop()
    elif change == 'duplicate_variant':
        rows.append(dict(rows[0]))
    elif change == 'N2_missing':
        candidates[0]['factor_id'] = 'missing'
    elif change == 'N2_expression':
        candidates[0]['expression'] = 'high'
    elif change == 'N2_direction':
        candidates[0]['direction'] = -1
    elif change == 'N1_count':
        steps['N1']['result']['queued_candidates'] = 2
    elif change == 'N1_failed':
        steps['N1']['ok'] = False
    elif change == 'queue_definition':
        definition(run/'candidates/queued.toml', 'queued', 'high', 'registered_battery:fixture.toml')
    elif change == 'blank_source':
        definition(frozen/'queued.toml', 'queued', 'amount', '')
    else:
        for path in [frozen/'queued.toml', run/'candidates/queued.toml']:
            definition(path, 'queued', 'amount', str(run/'N2/search.json'))
    with pytest.raises(ValueError):
        module.battery_scope(*mixed)


def test_pure_GP_scope_remains_supported_without_N1_queue(mixed):
    run, result, candidates, rows, _, variants = mixed
    frozen = Path(result['batch'])/'library'
    (frozen/'queued.toml').unlink()
    result.update(candidates=1, evaluated=1)
    scope, _, _ = module.battery_scope(run, result, candidates,
        [row for row in rows if row['factor'] == 'gp'], {}, variants)
    assert scope['mode'] == 'N2_only'
    assert scope['fixed_queue']['variants'] == 0


@pytest.mark.parametrize('completed_N4', [False, True])
def test_formal_diagnosis_marks_queue_training_not_applicable(mixed, monkeypatch, completed_N4):
    run, n3, candidates, rows, steps, variants = mixed
    evaluation = Path(n3['batch'])/'evaluation'
    scorecard = evaluation/'scorecard/factor_scorecard.parquet'
    scorecard.parent.mkdir(parents=True)
    pl.DataFrame(rows).write_parquet(scorecard)
    (scorecard.parent/'battery.toml').write_text(
        f'variants = {json.dumps(variants)}\n[run]\nas_of="2026-08-31"\n'
        '[admission]\n[multiple_testing]\nadmission_requires_fdr=false\n')
    n3['scorecard'] = str(scorecard)
    steps['N3'] = {'ok': True, 'result': n3}
    if completed_N4:
        steps['N4'] = {'ok': True, 'result': {'admitted': 1, 'rejected': 1}}
    (run/'summary.json').write_text(json.dumps({'steps': steps}))
    (run/'N2').mkdir()
    (run/'N2/search.json').write_text(json.dumps({'candidates': candidates, 'trials': []}))
    (run/'N2/input_summary.json').write_text('{}')
    (run/'N2/monthly_sample.parquet').write_bytes(b'fixture-not-read')
    factor = evaluation/'statistics/factors/gp'
    factor.mkdir(parents=True)
    for name in ['monthly_scores.parquet', 'monthly_ic.parquet']:
        (factor/name).write_bytes(b'fixture-not-read')
    monkeypatch.setattr(module, 'batch_diagnostics', lambda *args: {})
    result = module.diagnose_run(run)
    assert result['summary']['variants'] == 4
    assert result['summary']['population_scope']['N2_search']['variants'] == 2
    queued = [row for row in result['candidate_diagnostics'] if row['origin'] == 'fixed_queue']
    assert len(queued) == 2
    assert all(row['training_comparison_status'] == 'not_applicable' for row in queued)
    assert all(row['train'] is None and row['search_selection'] is None for row in queued)
    report = module.render_report({'batches': [result]})
    assert '筛选结果与未通过原因' in report and '实际准入失败' not in report
    assert '本批名义家族' not in report and '包含偏好家族终端' not in report
    if completed_N4:
        assert result['admission_observation'] == {'status': 'complete', 'admitted': 1, 'rejected': 1}
        assert '最终 N4 已完成：1 个因子入库、1 个拒绝' in report
    else:
        assert result['admission_observation']['status'] == 'not_confirmed_complete'
        assert '不能据此认定零入库' in report
