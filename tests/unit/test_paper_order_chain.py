import datetime as dt
import json

from quant.execution import paper_order_chain as chain


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
