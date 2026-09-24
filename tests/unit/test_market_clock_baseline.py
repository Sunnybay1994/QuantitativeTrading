import copy
import datetime as dt
import json

import polars as pl
import pytest

from quant.data import market_clock_baseline as b
from quant.research.market_indicators import realtime_snapshot


DAY=dt.date(2026,9,24)
NOW=dt.datetime.fromisoformat('2026-09-24T10:02:30+08:00')


def quote(day, amount, symbol='600001.SH', time='10:02:20', **kw):
    return dict(symbol=symbol,source='tushare_sina',provider_time=f'{day}T{time}+08:00',
        received_at=f'{day}T{time}+08:00',amount=amount,volume=100.,last_price=10.,
        prev_close=10.,bid=9.99,ask=10.01,**kw)


def save(root, day, suffix, quotes, cfg, symbols=('600001.SH',)):
    folder=root/f'{day:%Y%m%d}T{suffix}';folder.mkdir(parents=True)
    ref=folder/'reference.parquet'
    pl.DataFrame(dict(symbol=list(symbols),trade_date=[day-dt.timedelta(days=1)]*len(symbols))).write_parquet(ref)
    (folder/'quotes.json').write_text(json.dumps(quotes))
    (folder/'summary.json').write_text(json.dumps(dict(status='complete',auto_trade=False,scope=cfg['scope'],
        completed_at=f'{day}T10:03:00+08:00',reference=str(ref),reference_sha256=b.digest(ref))))
    return folder


def context():
    cfg=b.load();cfg['minimum_days']=2
    reference=pl.DataFrame(dict(symbol=['600001.SH'],trade_date=[DAY-dt.timedelta(days=1)]))
    calendar=pl.DataFrame(dict(date=[dt.date(2026,9,d) for d in (21,22,23,24,25)],is_open=[True]*5))
    return cfg,reference,calendar


def test_prior_days_provider_clock_and_pool_only(tmp_path):
    cfg,ref,cal=context();root=tmp_path/'snapshots'
    for day,amount in [(dt.date(2026,9,22),100.),(dt.date(2026,9,23),200.)]:
        save(root,day,'a',[quote(day,amount)],cfg)
        # Same-day duplicate samples never create another independent day.
        save(root,day,'b',[quote(day,amount)],cfg)
    save(root,DAY,'a',[quote(DAY,999999.)],cfg)
    save(root,dt.date(2026,9,25),'a',[quote(dt.date(2026,9,25),999999.)],cfg)
    current=[quote(DAY,300.)]
    rows,summary=b.enrich(current,ref,now=NOW,calendar=cal,output=tmp_path/'out',cfg=cfg,root=root)
    assert rows[0]['past_same_time_amount']==150. and rows[0]['baseline_valid_days']==2
    assert rows[0]['baseline_end_date']=='2026-09-23' and summary['matched_stocks']==1
    assert len(summary['eligible_historical_dates'])==2
    _,again=b.enrich(current,ref,now=NOW,calendar=cal,output=tmp_path/'again',cfg=cfg,root=root)
    assert all(r['reused'] for r in again['day_receipts'])
    stale_source=copy.deepcopy(current);stale_source[0]['source']='futu'
    rows,_=b.enrich(stale_source,ref,now=NOW,calendar=cal,output=tmp_path/'other',cfg=cfg,root=root)
    assert rows[0]['baseline_reason']=='unsupported_provider' and 'past_same_time_amount' not in rows[0]


def test_insufficient_days_wrong_clock_and_same_day_injection(tmp_path):
    cfg,ref,cal=context();root=tmp_path/'snapshots';day=DAY-dt.timedelta(days=1)
    save(root,day,'a',[quote(day,100.,time='10:01:20')],cfg)
    q=quote(DAY,100.);q.update(past_same_time_amount=1.,baseline_end_date='2026-09-01')
    rows,summary=b.enrich([q],ref,now=NOW,calendar=cal,output=tmp_path/'out',cfg=cfg,root=root)
    assert 'past_same_time_amount' not in rows[0] and rows[0]['baseline_valid_days']==0
    save(root,day,'b',[quote(day,200.)],cfg)
    rows,_=b.enrich([q],ref,now=NOW,calendar=cal,output=tmp_path/'out2',cfg=cfg,root=root)
    assert rows[0]['baseline_valid_days']==1 and rows[0]['baseline_reason']=='insufficient_prior_days'


def test_history_conflict_nonmonotonic_and_stale_rejected(tmp_path):
    cfg,ref,cal=context();day=DAY-dt.timedelta(days=1);root=tmp_path/'snapshots'
    save(root,day,'a',[quote(day,200.)],cfg)
    save(root,day,'b',[quote(day,100.,time='10:02:25')],cfg)
    _,summary=b.enrich([quote(DAY,300.)],ref,now=NOW,calendar=cal,output=tmp_path/'out',cfg=cfg,root=root)
    assert summary['day_receipts'][0]['rejected']['nonmonotonic_symbol_days']==1
    assert summary['matched_stocks']==0


def test_ready_components_do_not_claim_classifier_exists():
    ref=pl.DataFrame(dict(symbol=['600001.SH'],trade_date=[DAY-dt.timedelta(days=1)],ma20=[9.],adj_close=[10.]))
    q=quote(DAY,300.);q.update(past_same_time_amount=150.,baseline_end_date='2026-09-23',baseline_clock='10:02')
    result=realtime_snapshot([q],ref,now=NOW,settings=dict(minimum_stocks=1,minimum_coverage=.8,quote_max_age_seconds=120))
    assert result['component_input_status']=='ready' and result['missing_components']==[]
    assert result['classification_status']=='not_implemented' and result['market_state']=='unknown'


def test_later_seconds_and_end_of_day_are_not_substitutes(tmp_path):
    cfg,ref,cal=context();root=tmp_path/'snapshots';day=DAY-dt.timedelta(days=1)
    save(root,day,'a',[quote(day,200.,time='10:02:25')],cfg)
    # Current provider clock is 10:02:20; the future-in-clock :25 sample is unusable.
    rows,_=b.enrich([quote(DAY,300.)],ref,now=NOW,calendar=cal,output=tmp_path/'out',cfg=cfg,root=root)
    assert rows[0]['baseline_valid_days']==0
    late=save(root,day,'b',[quote(day,999999.,time='15:00:00')],cfg)
    summary=json.loads((late/'summary.json').read_text());summary['completed_at']=f'{day}T15:01:00+08:00'
    (late/'summary.json').write_text(json.dumps(summary))
    rows,detail=b.enrich([quote(DAY,300.)],ref,now=NOW,calendar=cal,output=tmp_path/'out2',cfg=cfg,root=root)
    assert rows[0]['baseline_valid_days']==0


def test_scope_reference_and_bounds_fail_closed(tmp_path):
    cfg,ref,cal=context();root=tmp_path/'snapshots';day=DAY-dt.timedelta(days=1)
    folder=save(root,day,'a',[quote(day,100.)],cfg)
    (folder/'reference.parquet').write_bytes(b'changed')
    rows,summary=b.enrich([quote(DAY,300.)],ref,now=NOW,calendar=cal,output=tmp_path/'out',cfg=cfg,root=root)
    assert summary['day_receipts'][0]['rejected']['historical_reference_missing_or_changed']==1
    cfg['max_snapshots_per_day']=1
    save(root,day,'b',[quote(day,100.)],cfg)
    rows,summary=b.enrich([quote(DAY,300.)],ref,now=NOW,calendar=cal,output=tmp_path/'out2',cfg=cfg,root=root)
    assert summary['day_receipts'][0]['status']=='snapshot_bound_exceeded'
    assert 'past_same_time_amount' not in rows[0]
