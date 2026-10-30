"""Reach the real pair-month writer through daily.run without executing accounts."""
import datetime as dt
import json
import os
from pathlib import Path

import polars as pl
import pytest

from quant.execution import b16_forward, q10_paper
from quant.reporting import q10_forward_rules as forward
from quant.research import run_daily_observation as daily


@pytest.fixture
def case(tmp_path, monkeypatch):
    end = dt.date(2026, 11, 30)
    roots = {name: tmp_path/name for name in ('data', 'artifacts', 'q10', 'shadow', 'b20', 'b32')}
    rules = Path('configs/paper/q10_sue_v2_forward_rules_20261010.toml').resolve()
    text = ['auto_trade=false', 'refresh_config="unused"', 'intraday=false',
            'data_root='+json.dumps(str(roots['data'])),
            'artifact_root='+json.dumps(str(roots['artifacts'])),
            '[model]', 'selection="unused"']
    for name in ('b20', 'b32', 'q10'):
        text += [f'[{name}]', 'config="unused"', 'output='+json.dumps(str(roots[name]))]
    text += ['[q10_shadow]', 'config="unused"', 'output='+json.dumps(str(roots['shadow'])),
             'forward_rules='+json.dumps(str(rules)), 'inception=2026-10-29']
    config = tmp_path/'daily.toml'
    config.write_text('\n'.join(text), encoding='utf-8')
    dates = ['2026-09-30', '2026-10-30', str(end)]
    for name, values in (('q10', [1., 1.05, 1.1]), ('shadow', [1., 1.01, 1.02])):
        folder = roots[name]/str(end)
        folder.mkdir(parents=True)
        (folder/'state.json').write_text(json.dumps({'nav': [
            {'date': day, 'unit_nav': value} for day, value in zip(dates, values)]}), encoding='utf-8')
    for account in daily.ACCOUNTS:
        folder = roots['b32']/account/str(end)
        folder.mkdir(parents=True)
        (folder/'state.json').write_text('{}', encoding='utf-8')

    def model(**kwargs):
        assert kwargs['to'] == str(end)
        kwargs['output'].mkdir()
        (kwargs['output']/'refresh.json').write_text(json.dumps({
            'latest_session': str(end), 'intraday_errors': [], 'input_quality': {'errors': []}}), encoding='utf-8')
        return {'as_of': str(end), 'status': 'recorded'}

    monkeypatch.setattr(daily, 'latest_session', lambda **kwargs: end)
    monkeypatch.setattr(daily, 'run_daily', model)
    monkeypatch.setattr(daily, 'run_b20', lambda **kwargs: {
        'as_of': str(end), 'accounts': [{'output': str(roots['b20']/str(i)/str(end))} for i in range(6)]})
    monkeypatch.setattr(daily, 'run_b32', lambda **kwargs: {
        'accounts': [{'account': name, 'as_of': str(end)} for name in daily.ACCOUNTS]})
    monkeypatch.setattr(daily, 'run_monthly', lambda **kwargs: {'as_of': str(end)})
    monkeypatch.setattr(daily, 'run_risk', lambda **kwargs: {'status': 'complete', 'requires_review': False})
    monkeypatch.setattr(daily, 'run_monitor', lambda **kwargs: {'status': 'pending', 'requires_review': False})
    monkeypatch.setattr(b16_forward, 'daily', lambda **kwargs: {'status': 'pending_first_signal'})
    monkeypatch.setattr(q10_paper, 'run', lambda **kwargs: {
        'as_of': str(end), 'shadow': kwargs['output'] == roots['shadow'], 'counts_toward_account_limit': False})
    benchmark = pl.DataFrame({'date': [dt.date.fromisoformat(day) for day in dates], 'unit_nav': [1.]*3})
    monkeypatch.setattr(forward, 'load_return_benchmarks', lambda **kwargs:
                        dict.fromkeys(forward.load_rules(rules)['benchmarks'], benchmark))
    return dict(config=config, output=tmp_path/'record', to=str(end),
                now=dt.datetime(2026, 11, 30, 20, tzinfo=daily.SHANGHAI)), roots


def test_string_as_of_reaches_actual_month_calculation_and_writes_pair(case):
    args, _ = case
    result = daily.run(**args)
    assert result['status'] == 'complete' and result['as_of'] == '2026-11-30'
    stage = result['stages']['q10_pair_month']
    assert stage['status'] == 'complete' and stage['result']['status'] == 'complete'
    stem = args['output']/'monthly/2026-11_q10_and_shadow'
    payload = json.loads(stem.with_suffix('.json').read_text(encoding='utf-8'))
    assert payload == stage['result']
    assert payload['q10']['month_excess_primary'] == pytest.approx(1.1/1.05-1)
    assert payload['shadow']['month_excess_primary'] == pytest.approx(1.02/1.01-1)
    assert stem.with_suffix('.md').is_file()


def test_only_real_insufficient_month_boundaries_are_waiting(case):
    args, roots = case
    state = roots['shadow']/'2026-11-30/state.json'
    state.write_text(json.dumps({'nav': [{'date': '2026-11-30', 'unit_nav': 1.}]}), encoding='utf-8')
    result = daily.run(**args)
    stage = result['stages']['q10_pair_month']
    assert result['status'] == 'complete'
    assert stage['result']['status'] == 'waiting'
    assert stage['result']['reason_code'] == 'insufficient_monthly_sample'
    assert not (args['output']/'monthly/2026-11_q10_and_shadow.json').exists()
    assert '等待样本' in (args['output']/'report.md').read_text(encoding='utf-8')


@pytest.mark.parametrize('error', [ValueError('invalid date formatting'), OSError('unreadable report source')])
def test_programming_and_filesystem_errors_fail_the_daily_record(case, monkeypatch, error):
    args, _ = case

    def broken(**kwargs):
        assert kwargs['stem'].name == '2026-11_q10_and_shadow'
        raise error

    monkeypatch.setattr(forward, 'write_two_account_month', broken)
    result = daily.run(**args)
    stage = result['stages']['q10_pair_month']
    assert result['status'] == 'incomplete' and stage['status'] == 'failed'
    assert str(error) in stage['error']
    assert str(error) in (args['output']/'report.md').read_text(encoding='utf-8')


@pytest.mark.parametrize('kind', ['missing_snapshot', 'invalid_nav', 'missing_benchmark_boundary'])
def test_missing_or_invalid_inputs_cannot_masquerade_as_waiting(case, monkeypatch, kind):
    args, roots = case
    state = roots['shadow']/'2026-11-30/state.json'
    if kind == 'missing_snapshot':
        state.unlink()
    elif kind == 'invalid_nav':
        state.write_text(json.dumps({'nav': [{'date': '2026-11-30', 'unit_nav': -1.}]}), encoding='utf-8')
    else:
        benchmark = pl.DataFrame({'date': [dt.date(2026, 11, 30)], 'unit_nav': [1.]})
        monkeypatch.setattr(forward, 'load_return_benchmarks', lambda **kwargs:
                            dict.fromkeys(forward.load_rules(Path('configs/paper/q10_sue_v2_forward_rules_20261010.toml'))['benchmarks'], benchmark))
    result = daily.run(**args)
    assert result['status'] == 'incomplete'
    assert result['stages']['q10_pair_month']['status'] == 'failed'


@pytest.mark.parametrize('kind', ['complete', 'sample_wait', 'legacy_error_wait', 'failed', 'invalid_result'])
def test_doctor_checks_pair_month_contents_even_when_outer_summary_and_exit_are_successful(
        tmp_path, monkeypatch, kind):
    from quant.reporting import doctor
    from tests.unit.test_doctor import _tree, NOW

    root = _tree(tmp_path)
    path = root/'artifacts/daily/sue_v2/2026-10-26_213000/summary.json'
    summary = json.loads(path.read_text(encoding='utf-8'))
    pair = {'status': 'complete', 'result': {'status': 'complete'}}
    if kind == 'sample_wait':
        pair['result'] = {'status': 'waiting', 'reason_code': 'insufficient_monthly_sample'}
    elif kind == 'legacy_error_wait':
        pair['result'] = {'status': 'waiting', 'reason': "ValueError: Invalid format specifier '%Y-%m'"}
    elif kind == 'failed':
        pair = {'status': 'failed', 'error': 'ValueError: invalid source'}
    elif kind == 'invalid_result':
        pair['result'] = {'status': 'unknown'}
    summary['stages'] = {'q10_pair_month': pair}
    path.write_text(json.dumps(summary), encoding='utf-8')
    os.utime(path, (1, 1))
    (path.parent/'scheduler.json').write_text('{"exit_code":0}', encoding='utf-8')
    monkeypatch.setattr(doctor, '_git_facts', lambda _: {
        'dirty': 0, 'days_since_commit': 0, 'root_scratch_py': 0, 'git_ok': True})
    result = doctor.collect(root=root, now=NOW, tasks=[{'name': 'daily', 'result': 0}])
    accepted = kind in ('complete', 'sample_wait')
    assert (result['daily']['status'] == 'complete') is accepted
    if not accepted:
        assert 'pair month' in result['daily']['receipt_error']
        assert any(row.startswith('daily:') for row in result['red'])
