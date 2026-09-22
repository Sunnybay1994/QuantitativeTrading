import datetime as dt

import pytest

from quant.research.minute_failure_diagnostics import decompose
from quant.research.intraday_afternoon import signal


def test_saved_quantity_pnl_reconciles_without_claiming_zero_cost_nav():
    result = decompose(dict(quantity=100,buy_price=10.1,sell_price=10.2,pnl=0),10,10.4)
    assert result['interval_open_move'] == pytest.approx(40)
    assert result['adverse_pricing_and_slippage'] == pytest.approx(30)
    assert result['commissions'] == pytest.approx(10)
    assert result['net_pnl'] == 0


def test_gap_signal_requires_prior_close_and_uses_only_known_rows():
    at = dt.datetime(2026,9,22,10)
    rows = [dict(bar_end=at,open=9,close=9.5,volume=100,amount=950)]
    assert signal(rows,at,'overnight_gap_recovery',10)
    assert not signal(rows,at,'overnight_gap_recovery')
    assert not signal(rows,at,'overnight_gap_acceptance',10)
    rows.append(dict(bar_end=at+dt.timedelta(minutes=5),open=100,close=100))
    assert signal(rows,at,'overnight_gap_recovery',10)
