import datetime as dt

import polars as pl
import pytest

from quant.factors.revenue_acceleration import compute_revenue_acceleration
from quant.research.monthly_revenue_acceleration import build_monthly_revenue_acceleration


def history(prior=(10.,20.,30.,40.), current=(20.,30.,40.,50.)):
    rows=[]
    for year, values in [(2022,prior),(2023,current),(2024,(30.,))]:
        cumulative=0.
        for i,value in enumerate(values):
            month,day=[(3,31),(6,30),(9,30),(12,31)][i]
            end=dt.date(year,month,day)
            ann=end+dt.timedelta(days=20)
            cumulative+=value
            rows.append({'symbol':'000001.SZ','end_date':end,'report_type':'1','comp_type':'1',
                'n_income':1.,'n_income_attr_p':1.,'revenue':cumulative,'ann_date':ann,'f_ann_date':ann,
                'available_date':ann,'update_flag':'0','source':'tushare'})
    return pl.DataFrame(rows)


def build(income,*dates):
    return build_monthly_revenue_acceleration(income_history=income,signal_dates=dates,
                                            candidate_symbols=('000001.SZ',))


def test_single_quarters_not_cumulative_and_exact_yoy_lags():
    result=compute_revenue_acceleration(history())
    assert result['revenue_q'].to_list()==[10.,20.,30.,40.,20.,30.,40.,50.,30.]
    assert result['pit_revenue_acceleration'].to_list()==[None]*5+[
        pytest.approx(-.5),pytest.approx(-1/6),pytest.approx(-1/12),pytest.approx(.25)]
    missing=history().filter(pl.col('end_date')!=dt.date(2023,6,30))
    assert compute_revenue_acceleration(missing)['pit_revenue_acceleration'][-1] is None
    with pytest.raises(ValueError,match='Duplicate'):
        compute_revenue_acceleration(pl.concat([history(),history().tail(1)]))


@pytest.mark.parametrize('prior,current,expected',[
    ((10.,20.,-20.,-40.),(20.,30.,-10.,-10.),None),
    ((10.,20.,-20.,-40.),(20.,30.,-30.,-80.),None),
    ((10.,20.,30.,40.),(20.,30.,40.,0.),-4/3),
    ((10.,20.,30.,40.),(20.,30.,40.,-1.),None),
    ((10.,20.,0.,40.),(20.,30.,40.,50.),None),
    ((10.,20.,30.,0.),(20.,30.,40.,50.),None),
    ((10.,20.,30.,40.),(20.,30.,40.,float('inf')),None),
])
def test_nonnegative_revenues_and_positive_denominators(prior,current,expected):
    frame=history(prior,current).filter(pl.col('end_date')<=dt.date(2023,12,31))
    actual = compute_revenue_acceleration(frame)['pit_revenue_acceleration'][-1]
    assert actual is None if expected is None else actual == pytest.approx(expected)


def test_pit_lag_future_revision_and_invalid_latest():
    h=history()
    before,after=dt.date(2024,4,20),dt.date(2024,4,21)
    result=build(h,before,after)
    assert result.factors['pit_revenue_acceleration'].to_list()==[pytest.approx(-1/12),pytest.approx(.25)]
    revision=h.tail(1).with_columns(pl.lit(90.).alias('revenue'),pl.lit('1').alias('update_flag'),
        *[pl.lit(dt.date(2024,5,20)).alias(c) for c in ('ann_date','f_ann_date','available_date')])
    assert build(pl.concat([h,revision]),before,after).factors.equals(result.factors)
    invalid=h.with_columns(pl.when(pl.col('end_date')==dt.date(2024,3,31))
                           .then(None).otherwise(pl.col('revenue')).alias('revenue'))
    assert build(invalid,after).factors['pit_revenue_acceleration'][0] is None
    assert build(h,dt.date(2020,1,1)).factors['pit_revenue_acceleration'][0] is None


def test_conflicting_previous_yoy_denominator_is_quarantined():
    h=history()
    conflict=h.filter(pl.col('end_date')==dt.date(2022,12,31)).with_columns(pl.lit(99.).alias('revenue'))
    result=build(pl.concat([h,conflict]),dt.date(2024,4,21))
    assert result.factors['pit_revenue_acceleration'][0] is None
    assert result.eligibility['status'][0]=='QUARANTINED'
