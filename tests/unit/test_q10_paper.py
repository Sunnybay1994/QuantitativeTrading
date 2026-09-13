import datetime as dt
import json
from pathlib import Path

import polars as pl
import pytest

from quant.execution import q10_paper as q10
from quant.research.model_training_models import buffered_model_targets


def test_targets_match_frozen_buffer_then_apply_actual_holdings_budget():
    date, following = dt.date(2026, 9, 30), dt.date(2026, 10, 8)
    prior = dt.date(2026, 8, 31)
    symbols = [f'{600000+i}.SH' for i in range(100)]
    old = pl.DataFrame({'symbol': symbols, 'trade_date': [prior]*100,
                        'lightgbm': [float(i) for i in range(100)]})
    new = pl.DataFrame({'symbol': symbols, 'trade_date': [date]*100,
                        'lightgbm': [float((i+30)%100) for i in range(100)]})
    expected = buffered_model_targets(pl.concat([old, new]), method='lightgbm',
        sessions=(prior, dt.date(2026, 9, 1), date, following), start=dt.date(2026, 9, 1),
        end=following, top_k=50, minimum_symbols=100, retention_multiplier=1.5)
    state = {'date': str(date), 'previous_targets': symbols[50:],
             'nav': [{'equity': 1000000.}],
             'holdings': {s: {'quantity': 2000, 'mark_price': 10.} for s in symbols[50:]}}
    actual = q10.signal_targets(new.rename({'lightgbm': 'prediction'}), state, following)
    expected = expected.filter(pl.col('as_of') == date)
    assert actual.select('symbol', 'weight').equals(expected.select('symbol', 'weight'))
    assert len(state['previous_targets']) == 50
    assert actual['weight'].sum() == pytest.approx(1.)


def test_first_signal_empty_account_and_invalid_pool():
    date = dt.date(2026, 9, 30)
    scores = pl.DataFrame({'symbol': [str(i) for i in range(100)],
        'trade_date': [date]*100, 'prediction': [float(i) for i in range(100)]})
    state = {'date': str(date), 'previous_targets': [], 'holdings': {}, 'nav': [{'equity': 1e6}]}
    targets = q10.signal_targets(scores, state, dt.date(2026, 10, 8))
    assert targets.height == 50
    assert targets['weight'].sum() == pytest.approx(1.)
    with pytest.raises(ValueError, match='minimum 100'):
        q10.signal_targets(scores.head(50), state, dt.date(2026, 10, 8))


def test_open_account_idempotent_and_controls(tmp_path, monkeypatch):
    monkeypatch.setattr(q10, 'read_stock_paper_calendar', lambda _: pl.DataFrame({
        'date': [dt.date(2026, 9, 14)], 'is_open': [True]}))
    first = q10.run(output=tmp_path, end=dt.date(2026, 9, 13))
    second = q10.run(output=tmp_path, end=dt.date(2026, 9, 13), halt=True)
    assert first['equity'] == second['equity'] == 1e6
    assert second['positions'] == second['reference_orders'] == 0
    assert second['controls']['halt']
    state = json.loads((tmp_path/'2026-09-13/state.json').read_text())
    assert len(state['nav']) == 1
    assert not state['auto_trade']


def test_rehearsal_forecast_rejected(tmp_path):
    folder = tmp_path/'model/forecast'
    folder.mkdir(parents=True)
    (folder/'summary.json').write_text(json.dumps({'as_of': '2026-09-30', 'rehearsal': True}))
    (folder.parent/'summary.json').write_text('{}')
    with pytest.raises(ValueError, match='prospective'):
        q10.load_forecast(folder, dt.date(2026, 9, 30), Path('selection'), dt.date(2026, 10, 8))


def test_month_end_orders_execute_next_session_and_restart(tmp_path, monkeypatch):
    from tests.unit.test_stock_paper import fixture_inputs

    inputs = fixture_inputs()[0]
    class Clock(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 2, 22, tzinfo=tz)
    monkeypatch.setattr(q10.dt, 'datetime', Clock)
    monkeypatch.setattr(q10, 'read_stock_paper_calendar', lambda _: inputs.calendar)
    monkeypatch.setattr(q10, 'read_stock_paper_inputs', lambda *args: inputs)
    date = dt.date(2026, 9, 30)
    scores = pl.DataFrame({'symbol': [f'{600000+i}.SH' for i in range(100)],
        'trade_date': [date]*100, 'prediction': [float(100-i) for i in range(100)]})
    forecast = tmp_path/'forecast'
    forecast.mkdir()
    (forecast/'summary.json').write_text(json.dumps({'as_of': str(date)}))
    monkeypatch.setattr(q10, 'load_forecast', lambda *args: scores)
    output = tmp_path/'account'
    first = q10.run(output=output, end=date, forecast=forecast)
    assert first['positions'] == 0
    assert first['reference_orders'] == 50
    next_day = q10.run(output=output, end=dt.date(2026, 10, 1), forecast=forecast)
    assert next_day['positions'] == 50
    fills = pl.read_csv(output/'2026-10-01/fills.csv')
    assert fills.height == 50
    assert (fills['quantity'] % 100 == 0).all()
    repeated = q10.run(output=output, end=dt.date(2026, 10, 1), forecast=forecast)
    assert repeated['equity'] == next_day['equity']


