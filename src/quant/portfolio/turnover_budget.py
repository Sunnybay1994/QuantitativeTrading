"""Move actual signal-close holdings toward targets within a fixed weight budget."""
import math

import polars as pl


def budget_targets(targets: pl.DataFrame, state: dict, *, budget: float) -> pl.DataFrame:
    if not math.isfinite(budget) or not 0 < budget <= 1:
        raise ValueError('Invalid monthly turnover budget')
    if targets.is_empty() or targets['as_of'].n_unique() != 1 or targets['symbol'].is_duplicated().any():
        raise ValueError('Require one unique signal batch')
    signal = targets['as_of'][0]
    if state.get('date') != str(signal):
        raise ValueError('Turnover requires actual holdings at signal close')
    equity = float(state['nav'][-1]['equity'])
    if not math.isfinite(equity) or equity <= 0:
        raise ValueError('Invalid signal-close equity')
    desired = dict(targets.select('symbol', 'weight').iter_rows())
    current = {symbol: holding['quantity']*holding['mark_price']/equity
               for symbol, holding in state['holdings'].items()}
    if any(not math.isfinite(value) or value < 0 for value in [*desired.values(), *current.values()]):
        raise ValueError('Invalid portfolio weight')
    if max(sum(desired.values()), sum(current.values())) > 1+1e-9:
        raise ValueError('Turnover budget requires unlevered portfolios')
    symbols = sorted(set(desired) | set(current))
    distance = sum(abs(desired.get(symbol, 0.)-current.get(symbol, 0.)) for symbol in symbols)/2
    fraction = min(1., budget/distance) if distance else 1.
    template = targets.row(0, named=True)
    rows = [{**template, 'symbol': symbol,
             'weight': current.get(symbol, 0.) + fraction*(desired.get(symbol, 0.)-current.get(symbol, 0.))}
            for symbol in symbols]
    return pl.from_dicts(rows, schema=targets.schema)
