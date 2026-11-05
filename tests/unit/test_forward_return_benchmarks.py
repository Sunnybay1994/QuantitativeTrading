import datetime as dt
import json
from pathlib import Path

import polars as pl
import pytest

from quant.data import forward_return_benchmarks as forward
from quant.data.equal_weight_index import index_day


def _tail():
    days = [dt.date(2026,8,d) for d in (3,4,5)]
    targets = {'A':{'weight':.5,'signal_close':100.},'B':{'weight':.5,'signal_close':100.}}
    # The published first day includes a prior basket overnight return.
    state = {'weights':{'A':1.},'last':{'A':90.},'level':2100.}
    quotes = {day:{'A':{'open':101.+i,'close':102.+i,'volume':100.},
                   'B':{'open':99.+i,'close':100.+i,'volume':100.}} for i,day in enumerate(days)}
    history=[]
    for i,day in enumerate(days):
        state,row,_=index_day(date=day,state=state,quotes=quotes[day],actions={},delisted={},stopped=set(),
            targets=targets if i==0 else None)
        history.append(row)
    plan=pl.DataFrame([{'symbol':symbol,'weight':value['weight'],'signal_close':value['signal_close'],
        'effective_date':days[0]} for symbol,value in targets.items()])
    return days,quotes,pl.DataFrame(history),plan,state


def test_recovery_preserves_actual_normalized_holdings_and_published_level():
    days,quotes,history,plan,expected=_tail()
    state,receipt=forward.recover_terminal(name='index',plan=plan,history=history,sessions=days,
        quotes=quotes,actions={},stopped={},delisted={})
    assert state['level']==expected['level']
    assert state['weights']==pytest.approx(expected['weights'],abs=1e-14)
    assert state['last']==expected['last']
    assert receipt['compared_returns']==2 and receipt['maximum_return_difference']<1e-12


@pytest.mark.parametrize('mode',['changed_return','nan_return','constituents'])
def test_recovery_refuses_a_different_frozen_return_path(mode):
    days,quotes,history,plan,_=_tail()
    if mode=='constituents':
        history=history.with_columns(pl.lit(999).alias('constituents'))
    else:
        history=history.with_columns(pl.when(pl.col('trade_date')==days[-1])
            .then(float('nan') if mode=='nan_return' else .9).otherwise(pl.col('daily_return')).alias('daily_return'))
    with pytest.raises(ValueError,match='Frozen'):
        forward.recover_terminal(name='index',plan=plan,history=history,sessions=days,
            quotes=quotes,actions={},stopped={},delisted={})


def test_incomplete_close_does_not_create_an_output_directory(tmp_path):
    with pytest.raises(ValueError,match='not observable'):
        forward.prepare(config=Path('unused'),end=dt.date(2026,11,5),output=tmp_path/'new',
            now=dt.datetime(2026,11,5,16,tzinfo=dt.timezone(dt.timedelta(hours=8))))
    assert not (tmp_path/'new').exists()


def test_member_extension_keeps_the_original_membership_prefix_and_uses_cached_october(tmp_path,monkeypatch):
    from quant.data import factor_benchmarks
    def write(name,days,weights):
        folder=tmp_path/'clean/factor_benchmarks'/name;folder.mkdir(parents=True)
        pl.DataFrame({'snapshot_date':days,'symbol':['A']*len(days),'vendor_weight':weights}).write_parquet(folder/'members.parquet')
        (folder/'summary.json').write_text('{}')
    write('original',[dt.date(2026,8,31)],[1.])
    write('history',[dt.date(2026,8,31),dt.date(2026,9,30)],[999.,2.])
    write('q10_forward_members_oct',[dt.date(2026,10,30)],[3.])
    monkeypatch.setattr(factor_benchmarks,'capture_csi800',lambda **kw:pytest.fail('cached membership must not be queried again'))
    members,_=forward._members(tmp_path,{'csi800_snapshot':'original'},
        {'historical_members':'history'},[dt.date(2026,8,31),dt.date(2026,9,30),dt.date(2026,10,30)])
    assert members['vendor_weight'].to_list()==[1.,2.,3.]
