import copy
import polars as pl
from polars.testing import assert_frame_equal

from quant.backtest import DailyMarketState
from quant.backtest.zero_target_exits import exit_orders
from quant.research.classic_monthly_baseline import replay
from tests.unit.test_share_exchanges import fixture, OLD, NEW, D0, D1, D2, D3


def source_case():
    source, state = fixture(existing=200)
    source['config'].pop('share_exchanges')
    source['config']['execution'] = {'retry_zero_target_exits': True}
    source['instruments'] = source['instruments'].with_columns(pl.lit(None, dtype=pl.Date).alias('delist_date'))
    source['dividends'] = source['dividends'].clear()
    source['bars'] = pl.concat([source['bars'].filter(pl.col('symbol') == NEW),
        *[source['bars'].filter(pl.col('symbol') == OLD).with_columns(pl.lit(d).alias('trade_date')) for d in (D1,D2,D3)]])
    source['market_states'] = {(d,s): DailyMarketState(at_lower_limit=s == OLD and d == D1)
                                for d in (D1,D2,D3) for s in (OLD,NEW)}
    source['targets'] = pl.DataFrame([{'as_of': D0, 'execution_date': D1, 'symbol': s,
        'strategy': 'probe', 'strategy_version': '1', 'weight': w} for s,w in [(OLD,0.),(NEW,.3)]])
    return source,state


def test_failed_exit_retries_next_day_without_selling_other_holding_and_resumes():
    source,state = source_case()
    whole = copy.deepcopy(state)
    nav,trades,_ = replay(**source, account_state=whole)
    retry = trades.filter(pl.col('date') == D2)
    assert retry.select('symbol','side','quantity').rows() == [(OLD,'SELL',400)]
    assert nav['retry_exit_orders'].to_list() == [0,1,0]
    assert nav['zero_target_weight'][0] > 0 and nav['zero_target_weight'][-1] == 0
    parts = [replay(**{**source,'sessions': ds}, account_state=state) for ds in ([D1],[D2,D3])]
    assert state == whole
    assert_frame_equal(trades, pl.concat([p[1] for p in parts]), check_exact=True)


def test_new_positive_target_cancels_retry():
    source,state = source_case()
    source['targets'] = pl.concat([source['targets'], source['targets'].with_columns(
        pl.lit(D1).alias('as_of'), pl.lit(D2).alias('execution_date'),
        pl.when(pl.col('symbol') == OLD).then(.6).otherwise(.3).alias('weight'))])
    nav,trades,_ = replay(**source, account_state=state)
    assert not trades.filter(pl.col('date') == D3).height
    assert nav['retry_exit_orders'].sum() == 0
    assert state['holdings'][OLD]['quantity'] > 0


def test_restricted_odd_lot_exit_uses_only_sellable_shares():
    source,state = source_case()
    state['holdings'][OLD]['quantity'] = 460
    state['restricted_shares'] = [{'symbol': OLD, 'quantity': 60, 'list_date': str(D3)}]
    orders = exit_orders(date=D2,state=state,weights={NEW:.3},calendar=source['calendar'],dividends=source['dividends'])
    assert orders['quantity'].to_list() == [400]
    state['holdings'][OLD]['quantity'] = 60
    orders = exit_orders(date=D3,state=state,weights={NEW:.3},calendar=source['calendar'],dividends=source['dividends'])
    assert orders['quantity'].to_list() == [60]


def test_disabled_keeps_original_monthly_exit_behavior():
    source,state = source_case()
    source['config']['execution']['retry_zero_target_exits'] = False
    nav,trades,_ = replay(**source, account_state=state)
    assert not trades.filter(pl.col('symbol') == OLD).height
    assert 'retry_exit_orders' not in nav.columns
    assert state['holdings'][OLD]['quantity'] == 400


def test_retry_share_distribution_and_dividend_are_applied_only_once():
    source,state = source_case()
    source['dividends'] = pl.DataFrame([{'symbol':OLD,'ann_date':D0,'record_date':D1,
        'ex_date':D2,'pay_date':D3,'div_cash':1.,'share_ratio':.5,'share_list_date':D2}])
    nav,trades,_ = replay(**source,account_state=state)
    assert trades.filter((pl.col('date') == D2) & (pl.col('symbol') == OLD))['quantity'].item() == 600
    assert nav.filter(pl.col('date') == D2)['receivable'].item() == 400.
    assert nav.filter(pl.col('date') == D3)['receivable'].item() == 0.
