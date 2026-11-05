"""R1 Top15 sleeve: size real shares inside the assigned account allocation."""
import math
import sys

import polars as pl

from quant.portfolio.account_portfolio_v1 import Allocation
from quant.portfolio.top15_limit import targets


def joint_orders(stock_orders, stock_limits, etf_orders):
    """ETF orders use the existing opening matcher, never an intraday touch.

    Finite sentinels only express an unbounded ETF market order to the existing
    side-specific matcher. They are not submitted prices or stock limit quotes.
    Permissions, affordability, shared cash and costs still apply in advance().
    """
    orders=pl.concat([stock_orders,etf_orders])
    if stock_limits is None:
        return orders,None
    limits=dict(stock_limits)
    for row in etf_orders.iter_rows(named=True):
        limits[row['symbol'],row['side']]=sys.float_info.max if row['side']=='BUY' else sys.float_info.min
    return orders,limits


class Top15Allocation(Allocation):
    def plan(self, *, scores, previous, closes, state, execution_date):
        day=scores['trade_date'][0]
        if state['date']!=str(day):
            raise ValueError('Require the actual signal-close account')
        equity=state['nav'][-1]['equity']
        quarter=not self.initialized or day.month in (3,6,9,12)
        weights=self.weights(day) if quarter else None
        etf_value=sum(h['quantity']*h['mark_price'] for s,h in state['holdings'].items() if s in self.etfs)
        sleeve=equity*weights[0] if quarter else equity-etf_value-self.reserved
        if not math.isfinite(sleeve) or sleeve<=0:
            raise ValueError('Stock sleeve has no positive equity')
        stock,selected=targets(scores=scores,previous=previous,closes=closes,
            equity=sleeve,execution_date=execution_date)
        rows=[]
        if quarter:
            self.reserved=0.
            for index,symbol in enumerate(self.etfs,1):
                key=('dividend','treasury')[index-1]
                if self.spec['etfs'][key]['listing_date']>day:
                    self.reserved+=equity*weights[index]
                    continue
                if symbol not in closes or not math.isfinite(closes[symbol]) or closes[symbol]<=0:
                    raise ValueError('Missing exact ETF allocation close')
                desired=math.floor(equity*weights[index]/closes[symbol]/100)*100
                held=state['holdings'].get(symbol,{}).get('quantity',0)
                delta=desired-held
                if delta:
                    rows.append({'as_of':str(day),'execution_date':str(execution_date),'symbol':symbol,
                        'side':'BUY' if delta>0 else 'SELL','quantity':abs(delta)})
        self.initialized=True
        schema={'as_of':pl.String,'execution_date':pl.String,'symbol':pl.String,'side':pl.String,'quantity':pl.Int64}
        etf_orders=pl.from_dicts(rows,schema=schema) if rows else pl.DataFrame(schema=schema)
        return stock,selected,etf_orders,{
            'as_of':str(day),'quarterly_allocation':quarter,'leg_weights':weights,
            'stock_equity_before_allocation':sleeve,'reserved_unlisted_cash':self.reserved,
            'budget_basis':'Top15 eligibility and integer quantities use assigned actual stock sleeve; no Q10 0.5 budget',
            'cash_basis':'all ETF and stock fills share the same cash ledger; rejected orders do not borrow'}
