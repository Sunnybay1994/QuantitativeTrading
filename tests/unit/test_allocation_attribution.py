import datetime as dt

import pandas as pd
import polars as pl
import pytest

from quant.research.etf_allocation_attribution import frozen_targets
from quant.research.mechanism_followthrough import period_metrics


def test_fixed_weights_ignore_future_weight_changes():
    frame=pl.DataFrame({'symbol':['a','b','a','b'],'execution_date':[dt.date(2024,1,2)]*2+[dt.date(2024,2,1)]*2,'weight':[.1,.9,.8,.2]})
    fixed,weights=frozen_targets(frame)
    assert fixed['weight'].to_list()==[.1,.9,.1,.9]
    assert weights['weight'].sum()==pytest.approx(1)


def test_period_drawdown_includes_initial_loss():
    result=period_metrics(pd.Series([-.1,.05]))
    assert result['return_value']==pytest.approx(-.055)
    assert result['max_drawdown']==pytest.approx(-.1)
    assert result['sessions']==2
