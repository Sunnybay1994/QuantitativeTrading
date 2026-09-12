import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from quant.execution import daily_observation_risk as risk


def make_record(tmp_path):
    stages = {'model': {'status': 'complete'}, 'refresh': {'status': 'complete'},
              'monthly': {'status': 'complete'}}
    for group, count in [('b20', 6), ('b32', 2)]:
        accounts = []
        for i in range(count):
            snapshot = tmp_path/group/str(i)/'2026-09-11'
            snapshot.mkdir(parents=True)
            (snapshot/'state.json').write_text(json.dumps({'date': '2026-09-11',
                'cash': 1000, 'holdings': {}, 'receivables': []}))
            (snapshot/'orders.csv').write_text('as_of,execution_date,symbol,side,quantity\n')
            (snapshot/'targets.csv').write_text('as_of,symbol,weight\n')
            accounts.append({'output': str(snapshot), 'account': f'{group}_{i}'})
        stages[group] = {'status': 'complete', 'result': {'accounts': accounts}}
    return {'auto_trade': False, 'as_of': '2026-09-11', 'stages': stages}


@pytest.fixture
def source(tmp_path, monkeypatch):
    record = make_record(tmp_path)
    monkeypatch.setattr(risk, 'read_order_risk_inputs', Mock(return_value=(None, None)))
    monkeypatch.setattr(risk, 'assess_reference_orders', Mock(return_value={
        'requires_review': False, 'issues': [], 'projection_valid': True}))
    monkeypatch.setattr(risk, 'summarize_execution_risk', Mock(return_value={
        'requires_review': False, 'participation_exceeded_symbols': [], 'observed_through': None}))
    monkeypatch.setattr(risk, 'render_report', Mock(return_value='risk'))
    return record


def test_saved_risk_and_repeated_output(source, tmp_path):
    paths = list(tmp_path.rglob('state.json'))
    before = [p.read_bytes() for p in paths]
    args = dict(record=source, output=tmp_path/'risk', data_root=Path('data'))
    result = risk.run(**args)
    assert result['status'] == 'complete' and not result['requires_review']
    assert len(result['accounts']) == 8
    assert [p.read_bytes() for p in paths] == before
    with pytest.raises(FileExistsError):
        risk.run(**args)


@pytest.mark.parametrize('failure', ['quality', 'stale', 'market', 'target'])
def test_bad_inputs_not_healthy(source, tmp_path, monkeypatch, failure):
    if failure == 'quality':
        source['stages']['refresh']['status'] = 'failed'
    elif failure == 'stale':
        snapshot = Path(source['stages']['b32']['result']['accounts'][0]['output'])
        data = json.loads((snapshot/'state.json').read_text())
        data['date'] = '2026-09-10'
        (snapshot/'state.json').write_text(json.dumps(data))
    elif failure == 'target':
        snapshot = Path(source['stages']['b32']['result']['accounts'][0]['output'])
        (snapshot/'targets.csv').write_text('as_of,symbol,weight\n2026-09-11,ABC,-0.5\n')
    else:
        monkeypatch.setattr(risk, 'read_order_risk_inputs', Mock(side_effect=ValueError('missing')))
    result = risk.run(record=source, output=tmp_path/'risk', data_root=Path('data'))
    assert result['status'] == 'incomplete' and result['requires_review']
    assert (tmp_path/'risk/summary.json').exists()


def test_advisory_does_not_turn_success_into_missing_input(source, tmp_path, monkeypatch):
    monkeypatch.setattr(risk, 'assess_reference_orders', Mock(return_value={
        'requires_review': True, 'issues': [{'rule': 'cash_buffer'}], 'projection_valid': True}))
    result = risk.run(record=source, output=tmp_path/'risk', data_root=Path('data'))
    assert result['status'] == 'complete' and result['requires_review']
    assert result['accounts'][-1]['issue_count'] == 1


def test_execution_risk_wired_without_future_fills(source, tmp_path, monkeypatch):
    execution = Mock(return_value={'requires_review': True,
        'participation_exceeded_symbols': ['ABC'], 'observed_through': None})
    monkeypatch.setattr(risk, 'summarize_execution_risk', execution)
    result = risk.run(record=source, output=tmp_path/'risk', data_root=Path('data'))
    assert execution.call_count == 2 and result['requires_review']
    assert result['accounts'][-1]['participation_exceeded_symbols'] == ['ABC']
    assert 'fills' not in execution.call_args.kwargs
    assert 'observed_through' not in execution.call_args.kwargs
    saved = json.loads((tmp_path/'risk/b32_0/execution_risk.json').read_text())
    assert saved['observed_through'] is None
