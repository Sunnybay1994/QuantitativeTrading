import copy
import datetime as dt
import polars as pl
import pytest
from quant.backtest.daily_account import advance
from tests.unit.test_paper_ledger import inputs, SYMBOL, D1, D2


def target(day, weight):
    return {'as_of': str(day-dt.timedelta(days=1)), 'execution_date': str(day), 'symbol': SYMBOL,
        'strategy': 's0_equal', 'strategy_version': '1', 'weight': weight}


@pytest.mark.parametrize('weight,permissions,expected', [(1.,(False,True),100),
    (0.,(True,False),100),(1.,(True,False),200),(0.,(False,True),0)])
def test_direction_limits_only_clamp_restricted_side(weight,permissions,expected):
    kwargs,state=inputs()
    kwargs['dividends']=kwargs['dividends'].clear()
    state['cash']=1100.
    state['pending']=[target(D1,weight)]
    result,_=advance(date=D1,state=state,**kwargs,target_permissions={SYMBOL:permissions})
    assert result['holdings'].get(SYMBOL,{}).get('quantity',0)==expected


def test_none_permissions_preserve_exact_default():
    kwargs,state=inputs()
    state['pending']=[target(D1,1.)]
    a,ra=advance(date=D1,state=copy.deepcopy(state),**kwargs)
    b,rb=advance(date=D1,state=copy.deepcopy(state),**kwargs,target_permissions=None)
    assert a==b
    assert ra.trades.equals(rb.trades) and ra.nav.equals(rb.nav)


def test_direction_lock_uses_post_corporate_action_shares():
    kwargs,state=inputs()
    kwargs['dividends']=kwargs['dividends'].with_columns(pl.lit(.5).alias('share_ratio'),
        pl.lit(0.).alias('div_cash'),pl.lit(D2).alias('share_list_date'))
    state,_=advance(date=D1,state=state,**kwargs)
    state['pending']=[target(D2,0.)]
    result,rows=advance(date=D2,state=state,**kwargs,target_permissions={SYMBOL:(False,False)})
    assert result['holdings'][SYMBOL]['quantity']==150
    assert rows.trades.is_empty()
