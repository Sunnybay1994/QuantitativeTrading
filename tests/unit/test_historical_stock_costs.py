import datetime as dt

import pytest

from quant.backtest.costs import AShareCostModel


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
