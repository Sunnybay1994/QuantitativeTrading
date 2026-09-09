import datetime as dt
import tomllib
from pathlib import Path

import polars as pl
import pytest

from quant.data.intraday_bars import SCHEMA, TZ
from quant.research.gold_global_follow_design_screen import screen_global_follow, select_gold_references


def config():
    return tomllib.loads(Path('configs/research/b33_gold_global_follow_20260909.toml').read_text(encoding='utf-8-sig'))


def references(rows):
    return pl.DataFrame(rows, schema={'reference_date': pl.Date, 'available_at': pl.Datetime('us','UTC'),
                                     'close': pl.Float64, 'reference_return': pl.Float64}, orient='row')


def fixture_bars(day, last=10.1):
    rows=[]
    for minute in list(range(570,690,5))+list(range(780,900,5)):
        start=dt.datetime.combine(day,dt.time(minute//60,minute%60),TZ)
        price=last if minute==895 else 10.
        rows.append({'symbol':'518880.SH','trade_date':day,'bar_start':start,
                     'bar_end':start+dt.timedelta(minutes=5),'open':price,'close':price,'high':price,
                     'low':price,'volume':10000.,'amount':price*10000,'source':'baostock'})
    return pl.DataFrame(rows,schema=SCHEMA).with_columns(pl.lit(True).alias('session_complete'))


def test_reference_strict_cutoff_future_and_weekend():
    day=dt.date(2026,1,12) # Monday
    cutoff=dt.datetime(2026,1,12,1,30,tzinfo=dt.UTC)
    old=(dt.date(2026,1,9),dt.datetime(2026,1,9,23,tzinfo=dt.UTC),4400.,.005)
    ref=references([old,(day,cutoff,4500.,.02)])
    result=select_gold_references(ref,[day])
    assert result['reference_date'][0]==old[0]
    assert result['reference_age_days'][0]==3 and result['signal'][0]
    assert result.height==1 # No fabricated weekend rows
    future=references([(dt.date(2026,1,13),dt.datetime(2026,1,13,23,tzinfo=dt.UTC),4600.,1.)])
    assert select_gold_references(pl.concat([ref,future]),[day]).equals(result)


def test_stale_four_days_inclusive_no_fallback_and_negative_signal():
    ref=references([(dt.date(2026,1,8),dt.datetime(2026,1,8,23,tzinfo=dt.UTC),4400.,.01)])
    result=select_gold_references(ref,[dt.date(2026,1,12),dt.date(2026,1,13)])
    assert result['signal'].to_list()==[True,False]
    for value in [None,-.01,.0049]:
        newer=references([(dt.date(2026,1,9),dt.datetime(2026,1,9,23,tzinfo=dt.UTC),4500.,value)])
        assert not select_gold_references(pl.concat([ref,newer]),[dt.date(2026,1,12)])['signal'][0]
    assert not select_gold_references(ref,[dt.date(2026,1,1)])['valid_reference'][0]
    with pytest.raises(ValueError,match='UTC'):
        select_gold_references(ref.with_columns(pl.col('available_at').dt.replace_time_zone(None)),[dt.date(2026,1,12)])


def test_same_day_unfinished_gc_cannot_trigger_and_baseline_ignores_gc():
    day=dt.date(2026,1,12)
    ref=references([(day,dt.datetime(2026,1,12,23,tzinfo=dt.UTC),4500.,.1)])
    trades,signals,summary=screen_global_follow(fixture_bars(day),pl.DataFrame({'trade_date':[day]}),ref,config())
    assert not signals['signal'][0] and summary['signals']==0
    assert summary['unconditional_baseline']['signals']==1
    row=trades.row(0,named=True)
    assert row['entry_time'].time()==dt.time(9,35) and row['exit_time'].time()==dt.time(14,55)
    assert row['gross_return']==pytest.approx(.01)
    assert row['estimated_cost_1x']==pytest.approx(.0007)
    assert row['estimated_net_2x']==pytest.approx(.0086)


def test_complete_bars_volume_and_out_of_design_filter():
    day=dt.date(2026,1,12)
    ref=references([(dt.date(2026,1,9),dt.datetime(2026,1,9,23,tzinfo=dt.UTC),4400.,.01)])
    daily=pl.DataFrame({'trade_date':[day]})
    bars=fixture_bars(day)
    assert screen_global_follow(bars,daily,ref,config())[2]['signals']==1
    for invalid in [bars.head(47),bars.with_columns(pl.lit(False).alias('session_complete')),
                    bars.with_columns(pl.lit(0.).alias('volume'))]:
        assert screen_global_follow(invalid,daily,ref,config())[2]['signals']==0
    future=fixture_bars(dt.date(2026,4,1),1000.)
    assert screen_global_follow(pl.concat([bars,future]),daily,ref,config())[0].equals(screen_global_follow(bars,daily,ref,config())[0])


def test_fixed_twenty_signal_threshold_and_cost_ratio():
    dates=[dt.date(2026,1,5)+dt.timedelta(days=i) for i in range(30)]
    dates=[d for d in dates if d.weekday()<5][:20]
    bars=pl.concat([fixture_bars(d) for d in dates])
    ref=references([(d-dt.timedelta(days=1),dt.datetime.combine(d-dt.timedelta(days=1),dt.time(23),dt.UTC),4400.,.01) for d in dates])
    daily=pl.DataFrame({'trade_date':dates})
    assert screen_global_follow(bars,daily,ref,config())[2]['conclusion']=='RESEARCH_ONLY'
    assert screen_global_follow(bars.filter(pl.col('trade_date')!=dates[-1]),daily,ref,config())[2]['conclusion']=='REJECTED'
    flat=pl.concat([fixture_bars(d,10.001) for d in dates])
    assert screen_global_follow(flat,daily,ref,config())[2]['conclusion']=='REJECTED'
