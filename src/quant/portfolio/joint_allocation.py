"""One stock turnover budget plus separately allocated ETF targets."""
import copy
import polars as pl
from quant.portfolio.turnover_budget import budget_targets


def allocate(batch, state, *, stock_fraction, etf_symbols, stock_budget=.5, cash_control=False):
    if not 0 <= stock_fraction <= 1:
        raise ValueError('Invalid stock allocation')
    stocks = batch.filter(~pl.col('symbol').is_in(sorted(etf_symbols)))
    etfs = batch.filter(pl.col('symbol').is_in(sorted(etf_symbols)))
    if set(state['holdings']) & set(etf_symbols) - set(etfs['symbol']):
        raise ValueError('ETF target missing; refuse accidental ETF exit')
    isolated = copy.deepcopy(state)
    isolated['holdings'] = {s:h for s,h in state['holdings'].items() if s not in etf_symbols}
    stocks = stocks.with_columns((pl.col('weight')*stock_fraction).alias('weight'))
    if stock_fraction > 0:
        stocks = budget_targets(stocks, isolated, budget=stock_budget*stock_fraction)
    else:
        template = batch.row(0,named=True)
        stocks = pl.DataFrame([{**template,'symbol':s,'weight':0.} for s in sorted(isolated['holdings'])],schema=batch.schema) if isolated['holdings'] else batch.head(0)
    stock_weight = float(stocks['weight'].sum())
    etf_capacity = 0. if cash_control else max(0., min(1-stock_fraction,1-stock_weight))
    etfs = etfs.with_columns((pl.col('weight')*etf_capacity).alias('weight'))
    result = pl.concat([stocks,etfs]).sort('symbol')
    if result['symbol'].is_duplicated().any() or result['weight'].sum()>1+1e-9:
        raise ValueError('Joint target violates unique unlevered allocation')
    return result, dict(feasible=True,applied=True,as_of=str(batch['as_of'][0]),
                        stock_weight=stock_weight,etf_weight=float(etfs['weight'].sum()),
                        budget_full_equity=stock_budget*stock_fraction)
