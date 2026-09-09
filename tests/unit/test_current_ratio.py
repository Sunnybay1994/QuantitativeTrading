import datetime as dt
from pathlib import Path

import polars as pl
import pytest

from quant.factors.current_ratio import compute_current_ratio
from quant.research.monthly_current_ratio import build_monthly_current_ratio
from quant.research.monthly_financial_factors import read_monthly_financial_factors


def history():
    rows=[]
    for end, assets, liabilities in [(dt.date(2023,12,31),100.,60.),(dt.date(2024,3,31),120.,84.)]:
        ann=end+dt.timedelta(days=20)
        rows.append({'symbol':'000001.SZ','end_date':end,'report_type':'1','comp_type':'1',
            'total_cur_liab':assets,'total_cur_assets':liabilities,'total_hldr_eqy_exc_min_int':assets-liabilities,
            'ann_date':ann,'f_ann_date':ann,'available_date':ann,'update_flag':'0','source':'tushare'})
    return pl.DataFrame(rows)


def build(h,*dates):
    return build_monthly_current_ratio(balance_history=h,signal_dates=dates,candidate_symbols=('000001.SZ',))


@pytest.mark.parametrize('assets,liabilities,expected',[(100.,60.,.6),(100.,120.,1.2),
    (100.,0.,0.),(0.,1.,None),(-1.,1.,None),(100.,-1.,None),(float('inf'),1.,None)])
def test_formula_and_invalid_values(assets,liabilities,expected):
    h=history().with_columns(pl.lit(assets).alias('total_cur_liab'),pl.lit(liabilities).alias('total_cur_assets'))
    assert compute_current_ratio(h)['pit_current_ratio'][-1]==expected


def test_pit_lag_latest_invalid_and_future_revision():
    h=history()
    before,after=dt.date(2024,4,20),dt.date(2024,4,21)
    result=build(h,before,after)
    assert result.factors['pit_current_ratio'].to_list()==[.6,.7]
    revision=h.tail(1).with_columns(pl.lit(110.).alias('total_cur_assets'),pl.lit('1').alias('update_flag'),
        *[pl.lit(dt.date(2024,5,20)).alias(c) for c in ('ann_date','f_ann_date','available_date')])
    assert build(pl.concat([h,revision]),before,after).factors.equals(result.factors)
    invalid=h.with_columns(pl.when(pl.col('end_date')==dt.date(2024,3,31)).then(None)
                           .otherwise(pl.col('total_cur_liab')).alias('total_cur_liab'))
    assert build(invalid,after).factors['pit_current_ratio'][0] is None
    assert build(h,dt.date(2020,1,1)).factors['pit_current_ratio'][0] is None


def test_latest_conflict_and_irrelevant_old_conflict():
    h=history()
    for extra,expected in [(h.tail(1),None),(h.head(1),.7)]:
        conflict=pl.concat([h,extra.with_columns(pl.lit(1.).alias('total_cur_assets'))])
        assert build(conflict,dt.date(2024,4,21)).factors['pit_current_ratio'][0]==expected
    with pytest.raises(ValueError,match='Duplicate'):
        compute_current_ratio(pl.concat([h,h.tail(1)]))


def test_loader_reads_balance_liabilities(monkeypatch):
    calls=[]
    def read(*,data_root,query):
        calls.append(query)
        return history()
    monkeypatch.setattr('quant.research.monthly_financial_factors.read_tushare_financial_history',read)
    result,histories=read_monthly_financial_factors(data_root=Path('unused'),candidates=('000001.SZ',),
        sessions=(dt.date(2024,4,30),dt.date(2024,5,2)),start=dt.date(2024,4,1),end=dt.date(2024,4,30),
        settings={'company_type':'1','signal_frequency':'completed_month_end','availability':'strictly_before_signal_date',
            'missing_quarter':'null','allowed_report_types':['1'],'factor_family':'current_ratio',
            'snapshot_id':'fixture','history_start':dt.date(2023,1,1)})
    assert list(histories)==['balancesheet']
    assert calls[0].extra_fields==('total_cur_assets','total_cur_liab')
    assert result.factors['pit_current_ratio'][0]==.7
