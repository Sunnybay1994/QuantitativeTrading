import datetime as dt
import json
from dataclasses import dataclass

from quant.execution import paper_order_chain as chain


def test_rejected_observation_failure_does_not_block_primary_or_send(tmp_path, monkeypatch):
    config = tmp_path/'daily.toml'
    config.write_text('auto_trade = false\n[q10]\nconfig = "primary"\n'
        f'output = "{(tmp_path/"primary").as_posix()}"\n'
        '[top15_observation]\nconfig = "missing.toml"\n'
        f'output = "{(tmp_path/"observe").as_posix()}"\n')
    day = dt.date(2026, 11, 6)
    monkeypatch.setattr(chain, 'run_q10', lambda **kw: {'as_of': str(day), 'reference_orders': 0})
    result = chain.run(config=config, end=day, output=tmp_path/'receipt')
    assert result['status'] == 'complete'
    assert result['observation_accounts']['top15']['status'] == 'failed'
    import pytest
    with pytest.raises(ValueError):
        chain.push_reference(account=tmp_path, summary={'observation_only': True, 'auto_trade': False})


def test_shadow_missing_day_preserves_primary_orders(tmp_path, monkeypatch):
    config = tmp_path/'daily.toml'
    config.write_text('auto_trade = false\n[q10]\nconfig = "primary"\n'
        f'output = "{(tmp_path/"primary").as_posix()}"\n'
        '[q10_shadow]\nconfig = "shadow"\n'
        f'output = "{(tmp_path/"shadow").as_posix()}"\n')
    date = dt.date(2026, 10, 30)
    calls = []

    def advance(**kwargs):
        calls.append(kwargs['config_path'].name)
        if kwargs['config_path'].name == 'shadow':
            raise ValueError('Missing frozen universe trade dates: [2026-10-30]')
        account = kwargs['output']
        account.mkdir()
        (account/'latest_orders.md').write_text('98 reference orders')
        return {'as_of': str(date), 'reference_orders': 98}

    monkeypatch.setattr(chain, 'run_q10', advance)
    result = chain.run(config=config, end=date, output=tmp_path/'receipt')
    assert calls == ['primary', 'shadow']
    assert result['status'] == 'failed'
    assert result['accounts']['q10']['status'] == 'complete'
    assert result['accounts']['q10_shadow']['status'] == 'failed'
    assert (tmp_path/'primary/latest_orders.md').read_text() == '98 reference orders'
    assert json.loads((tmp_path/'receipt/summary.json').read_text()) == result


def test_order_notification_retries_failure_and_deduplicates_success(tmp_path, monkeypatch):
    account = tmp_path/'primary'
    account.mkdir()
    (account/'latest_orders.md').write_text('dated order payload')
    summary = {'as_of': '2026-10-30', 'auto_trade': False, 'reference_orders': 98}

    @dataclass
    class Result:
        channel: str = 'fixture'
        ok: bool = False
        detail: str = 'captured'

    calls = []
    def send(**kwargs):
        calls.append(kwargs)
        return [Result(ok=len(calls) > 1)]
    monkeypatch.setattr('quant.notify.send', send)
    assert chain.push_reference(account=account, summary=summary)['status'] == 'pending'
    assert chain.push_reference(account=account, summary=summary)['status'] == 'sent'
    assert chain.push_reference(account=account, summary=summary)['status'] == 'sent'
    assert len(calls) == 2
