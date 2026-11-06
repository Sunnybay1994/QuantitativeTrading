import datetime as dt
import json
from pathlib import Path

import polars as pl
import pytest

from quant.execution import top15_paper as paper
from tests.unit.test_stock_paper import fixture_inputs


@pytest.fixture
def account(tmp_path, monkeypatch):
    inputs, _, _, _ = fixture_inputs()
    inception = dt.date(2026, 1, 29)
    text = paper.DEFAULT_CONFIG.read_text(encoding='utf-8')
    assessment = tmp_path/'assessment.json'
    assessment.write_text(json.dumps({'assessments': {'limit_1pct': {'conclusion': 'REJECTED'}}}))
    text = text.replace('artifacts/research/top15_limit_v1_20261104_02/assessment.json', assessment.as_posix())
    text = text.replace('inception_date = 2026-11-06', 'inception_date = 2026-01-29')
    config = tmp_path/'paper.toml'
    config.write_text(text, encoding='utf-8')
    monkeypatch.setattr(paper, 'read_stock_paper_calendar', lambda *_: inputs.calendar)
    monkeypatch.setattr(paper, 'read_stock_paper_inputs', lambda *_: inputs)
    return config, tmp_path/'account', inputs, inception


def test_initialize_rejected_cash_without_backdating_or_promoting(account):
    config, output, _, start = account
    result = paper.run(config_path=config, output=output, end=start)
    assert result['equity'] == 300000 and result['positions'] == result['reference_orders'] == 0
    assert result['conclusion'] == 'REJECTED' and result['observation_only']
    assert not result['counts_toward_account_limit'] and not result['auto_trade']
    state = json.loads((output/str(start)/'state.json').read_text())
    assert len(state['nav']) == 1 and state['inception_date'] == str(start)
    with pytest.raises(ValueError, match='on/after inception'):
        paper.run(config_path=config, output=output, end=start-dt.timedelta(days=1))


def test_unreached_limits_expire_after_three_sessions_resume_never_refills(account, monkeypatch, tmp_path):
    config, output, inputs, start = account
    signal = dt.date(2026, 1, 30)
    inputs.bars = inputs.bars.with_columns(
        pl.when(pl.col('trade_date') > signal).then(12.).otherwise(10.).alias('open'),
        pl.when(pl.col('trade_date') > signal).then(13.).otherwise(10.1).alias('high'),
        pl.when(pl.col('trade_date') > signal).then(11.).otherwise(9.9).alias('low'),
        pl.when(pl.col('trade_date') > signal).then(12.).otherwise(10.).alias('close'))
    symbols = inputs.instruments['symbol'].to_list()
    scores = pl.DataFrame({'trade_date': [signal]*len(symbols), 'symbol': symbols,
                           'prediction': [float(len(symbols)-n) for n in range(len(symbols))]})
    forecast = tmp_path/'forecast'
    forecast.mkdir()
    (forecast/'summary.json').write_text(json.dumps({'as_of': str(signal)}))
    monkeypatch.setattr(paper, 'load_forecast', lambda *_: scores)
    paper.run(config_path=config, output=output, end=signal, forecast=forecast)
    orders = pl.read_csv(output/'latest_orders.csv')
    assert orders.height == 15 and set(orders['limit_price']) == {10.1}
    first = paper.run(config_path=config, output=output, end=dt.date(2026, 2, 2))
    assert first['cash'] == 300000 and first['positions'] == 0
    saved = json.loads((output/'2026-02-02/state.json').read_text())
    assert {o['attempts'] for o in saved['limit_book']['orders']} == {1}
    assert {o['limit'] for o in saved['limit_book']['orders']} == {10.1}
    final = paper.run(config_path=config, output=output, end=dt.date(2026, 2, 4))
    assert final['cash'] == 300000 and final['reference_orders'] == 0
    state = json.loads((output/'2026-02-04/state.json').read_text())
    assert {o['status'] for o in state['limit_book']['orders']} == {'expired'}
    assert {o['attempts'] for o in state['limit_book']['orders']} == {3}
    assert state['cumulative_fees'] == 0
    before = (output/'2026-02-04/state.json').read_bytes()
    paper.run(config_path=config, output=output, end=dt.date(2026, 2, 4))
    assert (output/'2026-02-04/state.json').read_bytes() == before


def test_rejected_observation_cannot_be_silently_promoted(account):
    config, output, _, start = account
    config.write_text(config.read_text(encoding='utf-8').replace('observation_only = true',
                                                              'observation_only = false'), encoding='utf-8')
    with pytest.raises(ValueError, match='no admission promotion'):
        paper.run(config_path=config, output=output, end=start)
    assert not output.exists()


def test_touched_limit_fills_real_ledger_and_resume_preserves_fills(account, monkeypatch, tmp_path):
    config, output, inputs, start = account
    signal = dt.date(2026, 1, 30)
    inputs.bars = inputs.bars.with_columns(pl.lit(10.).alias('open'),
        pl.lit(10.1).alias('high'), pl.lit(9.9).alias('low'), pl.lit(10.).alias('close'))
    symbols = inputs.instruments['symbol'].to_list()
    scores = pl.DataFrame({'trade_date': [signal]*len(symbols), 'symbol': symbols,
        'prediction': [float(len(symbols)-n) for n in range(len(symbols))]})
    forecast = tmp_path/'forecast'
    forecast.mkdir()
    (forecast/'summary.json').write_text(json.dumps({'as_of': str(signal)}))
    monkeypatch.setattr(paper, 'load_forecast', lambda *_: scores)
    paper.run(config_path=config, output=output, end=signal, forecast=forecast)
    planned = pl.read_csv(output/'latest_orders.csv')
    result = paper.run(config_path=config, output=output, end=dt.date(2026, 2, 2))
    fills = output/'2026-02-02/fills.csv'
    trades = pl.read_csv(fills)
    assert trades.height == result['positions'] == 15
    assert set(trades['side']) == {'BUY'} and result['cash'] >= 0
    assert trades['quantity'].sum() <= planned['quantity'].sum()
    state = json.loads((output/'2026-02-02/state.json').read_text())
    assert state['cumulative_fees'] > 0
    remaining = sum(o['remaining'] for o in state['limit_book']['orders'])
    assert remaining + trades['quantity'].sum() == planned['quantity'].sum()
    saved = fills.read_bytes(), (fills.parent/'state.json').read_bytes()
    paper.run(config_path=config, output=output, end=dt.date(2026, 2, 2))
    assert (fills.read_bytes(), (fills.parent/'state.json').read_bytes()) == saved


def test_optional_failure_is_reported_without_advancing_other_accounts(tmp_path):
    result = paper.observe_from_daily({'config': str(tmp_path/'missing.toml'), 'output': str(tmp_path/'out')},
        end=dt.date(2026, 11, 5), data_root=tmp_path)
    assert result['status'] == 'failed' and 'FileNotFoundError' in result['error']
    assert not (tmp_path/'out').exists()
