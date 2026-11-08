import datetime as dt
import hashlib
import json
from pathlib import Path
import re

import polars as pl
import pytest

from quant.backtest.top15_pessimistic import filter_orders
from quant.execution.preposted_book import PrepostedBook
from quant.portfolio.top15_limit import targets
from quant.research.top15_limit_replay import scenarios

DAY=dt.date(2026,1,6)


@pytest.mark.parametrize('side,extreme,amount,allowed,reason',[
    ('BUY',10.,20000.,False,'ONE_TICK_NOT_CROSSED'),
    ('BUY',9.99,20000.,True,'PASSED'),
    ('BUY',9.99,19999.99,False,'AMOUNT_BELOW_20X'),
    ('SELL',10.,20000.,False,'ONE_TICK_NOT_CROSSED'),
    ('SELL',10.01,20000.,True,'PASSED')])
def test_exact_real_tick_and_twenty_times_full_remaining_notional(side,extreme,amount,allowed,reason):
    order=pl.DataFrame({'as_of':['2026-01-05'],'execution_date':[str(DAY)],'symbol':['600000.SH'],
                        'side':[side],'quantity':[100]})
    bars=pl.DataFrame({'symbol':['600000.SH'],'trade_date':[DAY],
        'open':[10.2 if side=='BUY' else 9.8],'low':[extreme if side=='BUY' else 9.],
        'high':[extreme if side=='SELL' else 11.],'amount':[amount]})
    permitted,rejected,audit=filter_orders(orders=order,limits={('600000.SH',side):10.},
                                         bars=bars,date=DAY,strategy='fixture')
    assert permitted.height==int(allowed) and rejected.height==int(not allowed)
    assert audit[0]['requested_notional']==1000. and audit[0]['diagnostic_reason']==reason


def test_blocked_pessimistic_days_count_toward_original_three_session_expiry():
    book=PrepostedBook()
    book.replace(signal=DAY-dt.timedelta(days=1),targets=pl.DataFrame({'symbol':['600000.SH'],'weight':[.08]}),
                 holdings={},equity=30000.,closes={'600000.SH':10.},offset=.01)
    for offset in range(3):
        day=DAY+dt.timedelta(days=offset);orders,limits=book.attempt(day)
        bars=pl.DataFrame({'symbol':['600000.SH'],'trade_date':[day],'open':[11.],
                          'low':[10.1],'high':[12.],'amount':[10000000.]})
        allowed,_,_=filter_orders(orders=orders,limits=limits,bars=bars,date=day,strategy='fixture')
        assert allowed.is_empty()
        book.settle(pl.DataFrame(schema={'symbol':pl.String,'side':pl.String,'quantity':pl.Int64}))
    assert book.orders[0]['status']=='expired' and book.orders[0]['attempts']==3


def test_corporate_action_uses_adjusted_remaining_shares_and_adjusted_quote():
    book=PrepostedBook();signal=DAY-dt.timedelta(days=1)
    book.replace(signal=signal,targets=pl.DataFrame({'symbol':['600000.SH'],'weight':[.08]}),
                 holdings={},equity=30000.,closes={'600000.SH':10.},offset=.01)
    book.apply_actions(DAY,pl.DataFrame({'symbol':['600000.SH'],'ann_date':[signal],
        'ex_date':[DAY],'share_ratio':[1.],'div_cash':[.1]}))
    orders,limits=book.attempt(DAY)
    assert orders['quantity'].item()==400 and limits['600000.SH','BUY']==5.
    bars=pl.DataFrame({'symbol':['600000.SH'],'trade_date':[DAY],'open':[5.1],
                      'low':[4.99],'high':[5.2],'amount':[40000.]})
    allowed,_,audit=filter_orders(orders=orders,limits=limits,bars=bars,date=DAY,strategy='fixture')
    assert allowed['quantity'].item()==400 and audit[0]['requested_notional']==2000.


def test_missing_or_stale_mark_never_substitutes_for_current_matching_bar():
    orders=pl.DataFrame({'as_of':['2026-01-05'],'execution_date':[str(DAY)],'symbol':['600000.SH'],
                        'side':['BUY'],'quantity':[100]})
    bars=pl.DataFrame(schema={'symbol':pl.String,'trade_date':pl.Date})
    allowed,rejected,audit=filter_orders(orders=orders,limits={('600000.SH','BUY'):10.},
                                        bars=bars,date=DAY,strategy='fixture')
    assert allowed.equals(orders) and rejected.is_empty()
    assert audit[0]['allowed_by_diagnostic'] is None
    with pytest.raises(ValueError,match='stale bar'):
        filter_orders(orders=orders,limits={('600000.SH','BUY'):10.},bars=pl.DataFrame({
            'symbol':['600000.SH'],'trade_date':[DAY-dt.timedelta(days=1)]}),date=DAY,strategy='fixture')


def score_fixture():
    names=[f'{600000+i}.SH' for i in range(50)]
    scores=pl.DataFrame({'symbol':names,'trade_date':[DAY]*50,'prediction':[float(50-i) for i in range(50)]})
    return names,scores,{s:10. for s in names}


def test_seven_new_selected_names_preserves_mandatory_exits_caps_and_cash():
    names,scores,closes=score_fixture()
    previous=names[35:50]
    batch,selected=targets(scores=scores,previous=previous,closes=closes,equity=300000.,
                           execution_date=DAY+dt.timedelta(days=1),maximum_new_names=7)
    assert selected==names[:7] and not set(selected)&set(previous)
    assert batch.filter(pl.col('symbol').is_in(previous))['weight'].sum()==0.
    assert batch['weight'].sum()==pytest.approx(.56)


def test_retained_buffer_names_do_not_consume_new_name_budget_and_default_unchanged():
    names,scores,closes=score_fixture()
    previous=names[15:25]
    default,old=targets(scores=scores,previous=previous,closes=closes,equity=300000.,execution_date=DAY)
    explicit,same=targets(scores=scores,previous=previous,closes=closes,equity=300000.,execution_date=DAY,
                           maximum_new_names=None)
    assert default.equals(explicit) and old==same
    batch,selected=targets(scores=scores,previous=previous,closes=closes,equity=300000.,execution_date=DAY,
                           maximum_new_names=7)
    assert len(selected)==15 and len(set(selected)-set(previous))==5
    assert set(previous)<=set(selected) and batch['weight'].max()<=.08


def test_scenario_validation_requires_unchanged_parent_and_frozen_parameters(tmp_path):
    parent=tmp_path/'parent.toml';parent.write_text('original')
    spec=dict(scenarios=['turnover7_1pct'],cost_multipliers=[.5,1.,2.],r4=dict(kind='new_name_budget',
        parent_config=str(parent),parent_config_sha256=hashlib.sha256(parent.read_bytes()).hexdigest(),maximum_new_names=7))
    assert scenarios(spec)==[('turnover7_1pct',.01)]
    parent.write_text('changed')
    with pytest.raises(ValueError,match='parent specification changed'):scenarios(spec)


@pytest.mark.parametrize('fill_on_third',[False,True])
def test_full_replay_uses_real_account_guard_and_original_retry_budget(tmp_path,monkeypatch,fill_on_third):
    """Isolate I/O only: exercise production replay, book, veto, matcher and ledger."""
    import copy
    import quant.research.top15_limit_replay as replay
    from tests.unit.test_daily_simulator import _calendar,_instruments,_bar
    from quant.backtest.account_reconciliation import validate_nav

    signal=dt.date(2018,12,28)
    days=[dt.date(2019,1,d) for d in (2,3,4,7)]
    source=tmp_path/'source';source.mkdir()
    (source/'battery.toml').write_text('''
[data]
refresh_config = "unused-fixture.toml"
[portfolio]
stock_dividend_withholding = 0.2
[costs.a_share]
commission_rate = 0.00025
commission_min = 5.0
stamp_tax_sell = 0.0005
transfer_fee = 0.00001
slippage = 0.001
effective_from = 2010-01-01
[costs.etf]
commission_rate = 0.00025
commission_min = 5.0
slippage = 0.001
effective_from = 2010-01-01
''')
    (source/'share_exchanges.toml').write_text('share_exchanges = []\n')
    pred=tmp_path/'predictions';pred.mkdir()
    pl.DataFrame({'symbol':['600000.SH'],'trade_date':[signal],'lightgbm':[1.]}).write_parquet(pred/'monthly_predictions.parquet')
    state=dict(date=str(signal),cash=300000.,holdings={},receivables=[],restricted_shares=[],pending=[],
               nav=[dict(date=str(signal),equity=300000.)])
    control=tmp_path/'control'
    baseline=tmp_path/'baseline'
    for cost in (.5,1.,2.):
        folder=control/f'budgeted/cost_{cost:g}/2018';folder.mkdir(parents=True)
        (folder/'account.json').write_text(json.dumps({'account':state}))
        for variant in ('open_full_fill','limit_1pct'):
            folder=baseline/variant/f'cost_{cost:g}';folder.mkdir(parents=True)
            pl.DataFrame({'date':days,'equity':[300000.]*4}).write_parquet(folder/'full_nav.parquet')
    text=Path('configs/research/top15_pessimistic_fill_v1.toml').read_text()
    for key,value in [('execution_source',source),('predictions',pred),('q10_control',control),('baseline_run',baseline)]:
        text=re.sub(rf'(?m)^{key} = .*$',f'{key} = "{value.as_posix()}"',text)
    text=text.replace('end = 2026-08-31','end = 2019-01-07')
    config=tmp_path/'config.toml';config.write_text(text)
    bars=pl.concat([_bar(d,open_price=11.,close_price=11.).with_columns(
        pl.lit(10.09 if fill_on_third and d>=days[2] else 10.10).alias('low'),
        pl.lit(12.).alias('high'),pl.lit(1e7).alias('volume'),pl.lit(1e8).alias('amount'))
        for d in [signal,*days]]).with_columns(
            pl.when(pl.col('trade_date')==signal).then(10.).otherwise(pl.col('close')).alias('close'))
    limits=pl.DataFrame(schema={'symbol':pl.String,'trade_date':pl.Date,'up_limit':pl.Float64,'down_limit':pl.Float64})
    inputs=dict(bars=bars,instruments=_instruments(),limits=limits,
        dividends=pl.DataFrame(schema={'symbol':pl.String,'ann_date':pl.Date,'ex_date':pl.Date,
            'record_date':pl.Date,'pay_date':pl.Date,'div_cash':pl.Float64,'share_ratio':pl.Float64}),
        suspensions=pl.DataFrame(schema={'symbol':pl.String,'suspend_date':pl.Date,'resume_date':pl.Date}))
    monkeypatch.setattr(replay,'read_stock_paper_calendar',lambda *a:_calendar(signal,*days))
    monkeypatch.setattr(replay,'read_battery_execution',lambda **kw:copy.deepcopy(inputs))
    monkeypatch.setattr(replay,'read_daily_replay_limits',lambda **kw:limits)
    from quant.backtest.rules import DailyMarketState
    monkeypatch.setattr(replay,'stock_session_states',lambda **kw:{(d,'600000.SH'):DailyMarketState() for d in days})
    output=tmp_path/'run'
    receipt=replay.run(config=config,output=output)
    assert receipt['status']=='replayed' and len(receipt['completed'])==3
    for cost in (.5,1.,2.):
        folder=output/'pessimistic_1pct'/f'cost_{cost:g}'
        nav=pl.read_parquet(folder/'nav.parquet');trades=pl.read_parquet(folder/'trades.parquet')
        assert validate_nav(nav)['passed']
        order=json.loads((folder/'orders.json').read_text())[0]
        assert order['attempts']==3 and order['status']==('filled' if fill_on_third else 'expired')
        assert nav['cash'][0]==300000. and nav['cumulative_fees'][0]==0.
        if fill_on_third:
            assert trades['date'].to_list()==[days[2]]
            assert nav['cash'][-1]==pytest.approx(300000.-trades['notional'].sum()-trades['fee'].sum())
        else:
            assert trades.is_empty() and nav['cash'].to_list()==[300000.]*4
            assert nav['cumulative_fees'].sum()==0.
