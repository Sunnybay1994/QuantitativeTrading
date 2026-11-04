"""R1 quarterly asset allocation around the unchanged monthly Q10 selection."""
import copy
import math

import polars as pl

from quant.portfolio.turnover_budget import budget_targets


class Allocation:
    def __init__(self, *, variant, spec, returns, etf_prices, proxy=False):
        self.variant, self.spec, self.returns = variant, spec, returns
        self.etf_prices, self.proxy = etf_prices, proxy
        self.etfs = [spec['etfs'][key]['symbol'] for key in ('dividend','treasury')]
        self.reserved, self.initialized = 0., False

    def weights(self, day):
        fixed = self.spec['fixed_weights']
        if self.variant == 'fixed_40_30_30':
            return fixed
        sample = self.returns.filter(pl.col('date') <= day).tail(60)
        if sample.height < 60 or sample.select(pl.any_horizontal(pl.all().exclude('date').is_null()).any()).item():
            return fixed
        vols = [sample[key].std(ddof=1) for key in ('stock','dividend','treasury')]
        if any(v is None or not math.isfinite(v) or v <= 0 for v in vols):
            raise ValueError('Risk-parity volatility is unavailable or zero')
        inverse = [1/v for v in vols]
        return [v/sum(inverse) for v in inverse]

    def __call__(self, batch, state):
        day = batch['as_of'][0]
        if state.get('date') != str(day):
            raise ValueError('Allocation requires the actual signal-close account')
        equity = state['nav'][-1]['equity']
        if self.proxy:
            # The prelisting sleeve cannot reserve more cash than remains after
            # actual shared-account execution fees. No holdings are financed.
            self.reserved = min(self.reserved,max(0.,state['cash']))
        etf_value = sum(h['quantity']*h['mark_price'] for s,h in state['holdings'].items() if s in self.etfs)
        stock_equity = equity-etf_value-self.reserved
        if stock_equity <= 0:
            raise ValueError('Stock sleeve has no positive equity')
        isolated = copy.deepcopy(state)
        isolated['holdings'] = {s:h for s,h in state['holdings'].items() if s not in self.etfs}
        isolated['nav'][-1]['equity'] = stock_equity
        stock = budget_targets(batch.filter(~pl.col('symbol').is_in(self.etfs)),isolated,budget=.5)
        quarter = not self.initialized or day.month in (3,6,9,12)
        weights = self.weights(day) if quarter else None
        fraction = weights[0] if quarter else stock_equity/equity
        stock = stock.with_columns((pl.col('weight')*fraction).alias('weight'))
        template = batch.row(0,named=True)
        rows, deltas = [], {}
        if quarter:
            self.reserved = 0.
        for index,symbol in enumerate(self.etfs,1):
            listed = self.spec['etfs'][('dividend','treasury')[index-1]]['listing_date'] <= day
            if quarter:
                weight = weights[index] if listed else 0.
                if not listed:
                    self.reserved += weights[index]*equity
            else:
                held = state['holdings'].get(symbol, {})
                weight = held.get('quantity',0)*held.get('mark_price',0.)/equity
                if listed:
                    deltas[symbol] = 0  # Preserve actual quantities between quarterly allocations.
            if not listed:
                continue  # Even a zero target must not request an unlisted security.
            rows.append({**template,'symbol':symbol,'weight':weight})
        result = pl.concat([stock,pl.from_dicts(rows,schema=batch.schema)])
        if result['weight'].sum()>1+1e-8:
            raise ValueError('Joint allocation would require leverage')
        self.initialized = True
        return result, {'feasible':True,'applied':True,'as_of':str(day),'quarterly_allocation':quarter,
            'leg_weights':weights,'reserved_unlisted_cash':self.reserved,'stock_equity_before_allocation':stock_equity,
            'target_share_deltas':deltas or None,
            'budget_basis':'0.5 within actual stock sleeve, asset-allocation transfers applied separately',
            'cash_basis':'shared account cash; ETF cash payments join cash, ETF quantities change only quarterly'}
