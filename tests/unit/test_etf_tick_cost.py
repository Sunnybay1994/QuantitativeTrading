import datetime as dt

import polars as pl
import pytest

from quant.backtest.costs import EtfCostModel
from quant.data.etf_paper_inputs import etf_session_states


def test_etf_tick_cost_scales_in_yuan_and_preserves_fractional_mode():
    model = EtfCostModel(.00025, 5., 0., dt.date(2023, 1, 1), slippage_per_share=.001)
    assert model.execution_price(.5, "BUY") == pytest.approx(.501)
    assert model.execution_price(10., "SELL") == pytest.approx(9.999)
    double = model.with_execution_cost_multiplier(2.)
    assert double.execution_price(.5, "BUY") == pytest.approx(.502)
    assert double.fee(10000., dt.date(2026, 1, 5)) == 10.
    old = EtfCostModel(.00025, 5., .001, dt.date(2023, 1, 1))
    assert old.execution_price(10., "BUY") == pytest.approx(10.01)
    with pytest.raises(ValueError, match="either"):
        EtfCostModel(.00025, 5., .001, dt.date(2023, 1, 1), slippage_per_share=.001)


def test_tick_slippage_cannot_cross_price_band():
    date = dt.date(2026, 1, 5)
    bars = pl.DataFrame({"symbol": ["510300.SH"], "trade_date": [date], "open": [1.099], "volume": [100.]})
    limits = pl.DataFrame({"symbol": ["510300.SH"], "trade_date": [date], "up_limit": [1.1], "down_limit": [.9]})
    states = etf_session_states(bars, pl.DataFrame(), official_limits=limits, slippage_per_share=.001)
    assert states[(date, "510300.SH")].at_upper_limit
