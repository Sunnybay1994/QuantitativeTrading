import json
from pathlib import Path

import pytest

from quant.research import run_strategy_batch as batch


@pytest.fixture(autouse=True)
def isolated_registry(tmp_path, monkeypatch):
    from quant.reporting import experiment_registry
    monkeypatch.setattr(experiment_registry, 'DEFAULT_REGISTRY', tmp_path/'registry/experiments.parquet')
    monkeypatch.setattr(experiment_registry, 'DEFAULT_LEADERBOARD', tmp_path/'leaderboard.md')


def completed(tmp_path, kind):
    root = tmp_path/kind
    root.mkdir()
    source = root/'source'
    source.mkdir()
    (source/'model.toml').write_text('[walk_forward]\ntest_start=2026-01-01\ntest_end=2026-08-31\n')
    (source/'battery.toml').write_text('value=1\n')
    measurement = root/'measurement.toml'
    measurement.write_text('reference="total_return"\n')
    events = Path('configs/data/share_exchanges_20260912.toml')
    research = 'id="fixture"\npredictions='+json.dumps(str(source))+'\nreturn_benchmark_config='+json.dumps(str(measurement))+'\n'
    content = (research+'auto_trade=false\nshare_exchanges_config='+json.dumps(str(events)) if kind == 'volatility_overlay'
               else '[research]\n'+research+'[policy]\nauto_trade=false\n')
    config = root/'registered.toml'
    config.write_text(content)
    output = root/'saved'
    output.mkdir()
    (output/'config.toml').write_text(content)
    for name, original in [('model.toml', source/'model.toml'), ('battery.toml', source/'battery.toml'),
        ('measurement.toml', measurement), ('share_exchanges.toml', events)]:
        (output/name).write_text(original.read_text(encoding='utf-8'), encoding='utf-8')
    rows = []
    for variant in ('control', batch.KINDS[kind]):
        for cost in (.5, 1., 2.):
            directory = output/variant/f'cost_{cost:g}'/'2026'
            directory.mkdir(parents=True)
            for name in ('account.json', 'nav.parquet', 'trades.parquet', 'rejections.parquet'):
                (directory/name).write_text('fixture')
            rows.append({'variant': variant, 'cost_multiplier': cost, 'active_start': '2026-01-02'})
    comparisons = [{'cost' if kind == 'volatility_overlay' else 'cost_multiplier': c,
        'nav_exact' if kind == 'volatility_overlay' else 'nav_exact_equal': True} for c in (.5, 1., 2.)]
    assessment = {'rows': rows, 'assessments': {v: {'conclusion': 'REJECTED'} for v in ('control', batch.KINDS[kind])}}
    if kind == 'volatility_overlay':
        assessment.update(control_comparison=comparisons, conclusion='REJECTED')
    else:
        (output/'control_comparison.json').write_text(json.dumps(comparisons))
    (output/'assessment.json').write_text(json.dumps(assessment))
    (output/'summary.json').write_text('{}')
    (output/'report.md').write_text('original')
    return {'id': kind, 'kind': kind, 'config': str(config), 'existing_output': str(output)}


def batch_config(tmp_path, jobs):
    config = tmp_path/'batch.toml'
    content = 'id="fixture"\nauto_trade=false\nevidence="retrospective_registered_rules_no_selection"\n'
    for job in jobs:
        content += '\n[[strategies]]\n'+'\n'.join(k+'='+json.dumps(v) for k, v in job.items())+'\n'
    config.write_text(content)
    return config


def test_two_kinds_reuse_without_runner_calls_and_preserve_originals(tmp_path, monkeypatch):
    jobs = [completed(tmp_path, k) for k in batch.KINDS]
    def forbidden(**kwargs):
        raise AssertionError('Completed replay must not be rerun')
    monkeypatch.setattr(batch, 'run_overlay', forbidden)
    monkeypatch.setattr(batch, 'run_budget', forbidden)
    result = batch.run(config=batch_config(tmp_path, jobs), output=tmp_path/'out')
    assert result['counts'] == {'reused': 2, 'ran': 0, 'failed': 0}
    assert not result['selection_performed']
    assert [r['id'] for r in result['items']] == [j['id'] for j in jobs]
    assert all(Path(j['existing_output'], 'report.md').read_text() == 'original' for j in jobs)
    with pytest.raises(FileExistsError):
        batch.run(config=tmp_path/'batch.toml', output=tmp_path/'out')


@pytest.mark.parametrize('damage', ['configuration', 'missing_year_file', 'missing_cost'])
def test_incomplete_or_mismatched_existing_result_does_not_rerun(tmp_path, damage):
    job = completed(tmp_path, 'volatility_overlay')
    output = Path(job['existing_output'])
    if damage == 'configuration':
        with Path(job['config']).open('a') as f:
            f.write('\nchanged_threshold=100\n')
    elif damage == 'missing_year_file':
        (output/'overlay/cost_1/2026/nav.parquet').unlink()
    else:
        path = output/'assessment.json'
        data = json.loads(path.read_text())
        data['rows'].pop()
        path.write_text(json.dumps(data))
    result = batch.run(config=batch_config(tmp_path, [job]), output=tmp_path/'out')
    assert result['status'] == 'partial' and result['counts']['failed'] == 1
    assert json.loads((tmp_path/'out/failures.json').read_text())[0]['error']


def test_static_dispatch_failure_does_not_stop_next_registered_job(tmp_path, monkeypatch):
    monkeypatch.setattr('quant.reporting.experiment_registry.register_run', lambda *args: 0)
    calls = []
    def overlay(**kwargs):
        calls.append('overlay')
        raise ValueError('fixture source missing')
    def budget(**kwargs):
        calls.append('budget')
    monkeypatch.setattr(batch, 'run_overlay', overlay)
    monkeypatch.setattr(batch, 'run_budget', budget)
    monkeypatch.setattr(batch, 'saved_result', lambda **kwargs: {'conclusion': 'REJECTED', 'report': 'fixture.md', 'rows': []})
    jobs = [{'id': kind, 'kind': kind, 'config': 'fixture.toml', 'existing_output': ''} for kind in batch.KINDS]
    result = batch.run(config=batch_config(tmp_path, jobs), output=tmp_path/'out')
    assert calls == ['overlay', 'budget']
    assert result['counts'] == {'failed': 1, 'ran': 1, 'reused': 0}


def test_unknown_module_kind_is_not_executed_and_following_item_runs(tmp_path, monkeypatch):
    good = completed(tmp_path, 'turnover_budget')
    bad = {'id': 'bad', 'kind': 'os.system', 'config': 'unused', 'existing_output': ''}
    result = batch.run(config=batch_config(tmp_path, [bad, good]), output=tmp_path/'out')
    assert result['items'][0]['status'] == 'failed'
    assert result['items'][1]['status'] == 'reused'


def test_semantically_equal_config_newlines_are_reusable(tmp_path):
    job = completed(tmp_path, 'turnover_budget')
    config = Path(job['config'])
    text = config.read_text()
    config.write_bytes(text.replace('\r\n', '\n').encode())
    Path(job['existing_output'], 'config.toml').write_bytes(text.replace('\r\n', '\n').replace('\n', '\r\n').encode())
    assert batch.saved_result(kind=job['kind'], config=config, output=Path(job['existing_output']))['conclusion'] == 'REJECTED'
