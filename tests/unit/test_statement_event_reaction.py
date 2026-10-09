import datetime as dt

import numpy as np
import polars as pl
import pytest
from polars.testing import assert_frame_equal

from quant.data.statement_event_dates import validate_statement_dates
from quant.factors.statement_event_reaction import NAMES,compute_statement_reactions,attach_statement_reactions


def inputs():
    low,high=dt.date(2019,9,1),dt.date(2020,8,31)
    sessions=tuple(low+dt.timedelta(days=i) for i in range((high-low).days+1) if (low+dt.timedelta(days=i)).weekday()<5)
    announcement=dt.date(2020,1,31);anchor=sessions.index(announcement)
    rows=[{'symbol':'600000.SH','trade_date':d,'close':float(10*1.01**i),'adj_factor':1.,
           'volume':200. if anchor-1<=i<=anchor+1 else 100.,'total_shares':1e8,'float_shares':6e7} for i,d in enumerate(sessions)]
    market=pl.DataFrame({'trade_date':sessions,'index_level':[float(100*1.002**i) for i in range(len(sessions))]})
    events=pl.DataFrame({'symbol':['600000.SH'],'announcement_date':[announcement],'end_date':[dt.date(2019,12,31)],
        'event_date_valid':[True],'event_date_status':['date_checks_passed']})
    return events,pl.from_dicts(rows),market,sessions


def test_compounded_three_day_market_proxy_and_exact_volume_baseline():
    events,bars,market,sessions=inputs()
    result=compute_statement_reactions(events,bars,market,sessions=sessions).row(0,named=True)
    assert result[NAMES[0]]==pytest.approx(1.01**3-1.002**3)
    assert result[NAMES[1]]==pytest.approx(1.)
    assert result['baseline_volume_points']==56
    assert result['reaction_end']==dt.date(2020,2,3)
    assert result['earliest_execution']==dt.date(2020,2,4)


def test_cross_month_not_backfilled_and_expires_at_120_days():
    events,bars,market,sessions=inputs()
    reactions=compute_statement_reactions(events,bars,market,sessions=sessions)
    end=reactions['reaction_end'].item()
    dates=[dt.date(2020,1,31),end,end+dt.timedelta(days=119),end+dt.timedelta(days=120)]
    keys=pl.DataFrame({'symbol':['600000.SH']*4,'trade_date':dates})
    result=attach_statement_reactions(keys,reactions)
    assert result[NAMES[0]][0] is None
    assert result[NAMES[0]][1] is not None
    assert result[NAMES[0]][2] is not None
    assert result[NAMES[0]][3] is None


@pytest.mark.parametrize('offset,expected', [(-63,'baseline_volume_incomplete_or_zero'),(-8,'baseline_volume_incomplete_or_zero'),(-1,'event_volume_incomplete')])
def test_missing_volume_is_not_compressed_or_zero_filled(offset,expected):
    events,bars,market,sessions=inputs();anchor=sessions.index(events['announcement_date'].item())
    bars=bars.with_columns(pl.when(pl.col('trade_date')==sessions[anchor+offset]).then(None).otherwise(pl.col('volume')).alias('volume'))
    result=compute_statement_reactions(events,bars,market,sessions=sessions)
    assert result['volume_status'].item()==expected and result[NAMES[1]].item() is None


def test_split_adjusted_price_is_retained_but_changing_share_base_is_not_volume_signal():
    events,bars,market,sessions=inputs()
    split=events['announcement_date'].item()
    bars=bars.with_columns(pl.when(pl.col('trade_date')>=split).then(pl.col('close')/2).otherwise(pl.col('close')).alias('close'),
        pl.when(pl.col('trade_date')>=split).then(2.).otherwise(1.).alias('adj_factor'),
        pl.when(pl.col('trade_date')>=split).then(2e8).otherwise(1e8).alias('total_shares'))
    result=compute_statement_reactions(events,bars,market,sessions=sessions)
    assert result[NAMES[0]].item()==pytest.approx(1.01**3-1.002**3)
    assert result['volume_status'].item()=='capital_changed' and result[NAMES[1]].item() is None


def test_missing_market_or_zero_baseline_is_unknown_not_zero_signal():
    events,bars,market,sessions=inputs();anchor=sessions.index(events['announcement_date'].item())
    market=market.filter(pl.col('trade_date')!=sessions[anchor-1])
    bars=bars.with_columns(pl.when(pl.col('trade_date').is_between(sessions[anchor-63],sessions[anchor-8])).then(0.).otherwise(pl.col('volume')).alias('volume'))
    result=compute_statement_reactions(events,bars,market,sessions=sessions)
    assert result[NAMES[0]].item() is None and result[NAMES[1]].item() is None


def test_future_prices_cannot_change_completed_reaction_and_new_invalid_event_clears_old():
    events,bars,market,sessions=inputs();reaction=compute_statement_reactions(events,bars,market,sessions=sessions)
    cut=reaction['reaction_end'].item()
    changed=bars.with_columns(pl.when(pl.col('trade_date')>cut).then(pl.col('close')*9).otherwise(pl.col('close')).alias('close'))
    assert_frame_equal(reaction,compute_statement_reactions(events,changed,market,sessions=sessions))
    short=compute_statement_reactions(events,bars.filter(pl.col('trade_date')<=cut),market.filter(pl.col('trade_date')<=cut),sessions=sessions)
    assert_frame_equal(reaction,short)
    later=reaction.with_columns(pl.lit(dt.date(2020,3,2)).alias('reaction_end'),
        pl.lit(dt.date(2020,2,28)).alias('announcement_date'),*[pl.lit(None,dtype=pl.Float64).alias(n) for n in NAMES])
    keys=pl.DataFrame({'symbol':['600000.SH']*2,'trade_date':[dt.date(2020,2,28),dt.date(2020,3,2)]})
    result=attach_statement_reactions(keys,pl.concat([reaction,later]))
    assert result[NAMES[0]][0] is not None and result[NAMES[0]][1] is None


def test_date_checks_are_independent_of_sue_but_quarantine_and_date_conflicts_stay_excluded():
    ann=dt.date(2020,3,31);period=dt.date(2019,12,31)
    rows=[{'symbol':str(i),'ann_date':ann,'f_ann_date':ann,'available_date':ann,'end_date':period,
           'report_type':'1','comp_type':'1','n_income':1.,'n_income_attr_p':1.} for i in range(4)]
    rows[3]['ann_date']=dt.date(2020,3,30)
    h=pl.from_dicts(rows)
    old=pl.DataFrame({'symbol':[str(i) for i in range(4)],'announcement_date':[ann]*4,
                     'status':['VALID','MISSING','QUARANTINED','NOT_APPLICABLE']})
    result=validate_statement_dates(h,old)
    assert result['event_date_valid'].to_list()==[True,True,False,False]
    assert result['event_date_status'].to_list()[2:]==['legacy_quarantine_retained','announcement_date_disagreement']
    future=h.head(1).with_columns(pl.lit(dt.date(2020,6,30)).alias('end_date'),
        *[pl.lit(dt.date(2020,8,31)).alias(c) for c in ['ann_date','f_ann_date','available_date']])
    extended=validate_statement_dates(pl.concat([h,future]),old)
    assert_frame_equal(result,extended.filter(pl.col('announcement_date')==ann))


def test_conflicting_first_record_never_becomes_an_event_by_tie_break():
    ann=dt.date(2020,3,31)
    h=pl.DataFrame({'symbol':['x','x'],'ann_date':[ann]*2,'f_ann_date':[ann]*2,'available_date':[ann]*2,
        'end_date':[dt.date(2019,12,31)]*2,'report_type':['1']*2,'comp_type':['1']*2,
        'n_income':[1.,2.],'n_income_attr_p':[1.,2.]})
    old=pl.DataFrame(schema={'symbol':pl.String,'announcement_date':pl.Date,'status':pl.String})
    result=validate_statement_dates(h,old)
    assert result['event_date_status'].item()=='ambiguous_first_disclosure'
