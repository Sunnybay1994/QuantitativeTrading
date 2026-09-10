import datetime as dt

import pytest

from quant.backtest.costs import AShareCostModel
from dataclasses import replace


def model(historical: bool = True) -> AShareCostModel:
    return AShareCostModel(0.00025, 5.0, 0.0005, 0.00001, 0.001,
                          dt.date(2013, 1, 1), historical_statutory_fees=historical)


@pytest.mark.parametrize(('date', 'buy', 'sell'), [
    (dt.date(2020, 2, 3), 27.0, 127.0),
    (dt.date(2022, 4, 28), 27.0, 127.0),
    (dt.date(2022, 4, 29), 26.0, 126.0),
    (dt.date(2023, 8, 27), 26.0, 126.0),
    (dt.date(2023, 8, 28), 26.0, 76.0),
])
def test_statutory_rates_change_on_effective_date(date: dt.date, buy: float, sell: float) -> None:
    assert model().fee(100000, date, 'BUY') == pytest.approx(buy)
    assert model().fee(100000, date, 'SELL') == pytest.approx(sell)


def test_stress_keeps_historical_taxes_and_legacy_fixed_mode() -> None:
    date = dt.date(2020, 2, 3)
    assert model().with_execution_cost_multiplier(2).fee(100000, date, 'SELL') == pytest.approx(152)
    assert model(False).fee(100000, date, 'SELL') == pytest.approx(76)
    with pytest.raises(ValueError, match='2015-08-01'):
        model().fee(100000, dt.date(2015, 7, 31), 'SELL')


@pytest.mark.parametrize(('date', 'transfer'), [
    (dt.date(2010, 1, 4), 10.),
    (dt.date(2012, 5, 31), 10.),
    (dt.date(2012, 6, 1), 7.5),
    (dt.date(2012, 8, 31), 7.5),
    (dt.date(2012, 9, 3), 6.),
    (dt.date(2015, 7, 31), 6.),
])
def test_early_shanghai_uses_share_face_value_and_shenzhen_gross_commission(date, transfer):
    costs = replace(model(), effective_from=dt.date(2010,1,1))
    assert costs.fee(100000,date,'BUY',market='SH',quantity=10000) == pytest.approx(25+transfer)
    assert costs.fee(100000,date,'SELL',market='SH',quantity=10000) == pytest.approx(125+transfer)
    assert costs.fee(100000,date,'SELL',market='SZ',quantity=10000) == pytest.approx(125)
    assert costs.with_execution_cost_multiplier(2).fee(100000,date,'SELL',market='SH',quantity=10000) == pytest.approx(150+transfer)


def test_early_transfer_minimum_and_face_value_assumptions_are_explicit():
    costs = model()
    day = dt.date(2014,1,2)
    assert costs.fee(1000,day,'BUY',market='SH',quantity=100) == pytest.approx(6)
    assert replace(costs,pre_2015_sh_transfer_min=0).fee(1000,day,'BUY',market='SH',quantity=100) == pytest.approx(5.06)
    assert replace(costs,pre_2015_sh_par_value=.1).fee(100000,day,'BUY',market='SH',quantity=10000) == pytest.approx(26)
    for market, quantity in ((None,100),('HK',100),('SH',0),('SH',True)):
        with pytest.raises(ValueError):
            costs.fee(1000,day,'BUY',market=market,quantity=quantity)
