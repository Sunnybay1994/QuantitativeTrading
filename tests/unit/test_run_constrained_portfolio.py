import datetime as dt
import json

import polars as pl
import pytest

from quant.research.run_constrained_portfolio import verify_execution_caps, window_metrics


def test_window_includes_opening_loss_against_previous_close():
    nav = pl.DataFrame({'date': [dt.date(2023, 12, 29), dt.date(2024, 1, 2), dt.date(2024, 1, 3)],
        'equity': [100., 80., 90.], 'market_value': [98., 78., 88.]})
    result = window_metrics(nav, dt.date(2024, 1, 1), dt.date(2024, 1, 31))
    assert result['return'] == pytest.approx(-.1)
    assert result['max_drawdown'] == pytest.approx(-.2)


def test_cash_pressure_window_is_not_applicable():
    nav = pl.DataFrame({'date': [dt.date(2023, 12, 29), dt.date(2024, 1, 2)],
        'equity': [100., 100.], 'market_value': [0., 0.]})
    assert window_metrics(nav, dt.date(2024, 1, 1), dt.date(2024, 1, 31))['applicable'] is False


def test_saved_fill_cap_check_uses_gross_currency_and_prior_signal(tmp_path):
    folder = tmp_path/'constrained/cost_1/2024'
    folder.mkdir(parents=True)
    (folder/'constraints.json').write_text(json.dumps([{'as_of': '2024-01-31',
        'execution_notional_caps': {'000001.SZ': 5000.}}]))
    trades = pl.DataFrame({'date': [dt.date(2024, 2, 1)], 'symbol': ['000001.SZ'], 'notional': [4999.]})
    trades.write_parquet(folder/'trades.parquet')
    sessions = (dt.date(2024, 1, 31), dt.date(2024, 2, 1))
    assert verify_execution_caps(tmp_path, sessions)['violations'] == 0
    trades.with_columns(pl.lit(5001.).alias('notional')).write_parquet(folder/'trades.parquet')
    with pytest.raises(ValueError, match='exceeds'):
        verify_execution_caps(tmp_path, sessions)
