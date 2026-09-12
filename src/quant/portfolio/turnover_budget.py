"""Move actual signal-close holdings toward targets within a fixed weight budget."""
import math

import polars as pl


def budget_targets(targets: pl.DataFrame, state: dict, *, budget: float,
                   allocation: str = 'linear_blend') -> pl.DataFrame:
    if allocation not in {'linear_blend', 'complete_adjustments'}:
        raise ValueError('Unknown turnover allocation')
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
    if allocation == 'complete_adjustments':
        # Keep the same aggregate buy/sell amounts and cash target as the blend.
        # Finish exits first (smallest first), then other reductions. Finish the
        # largest requested buys first. Symbol ordering resolves all ties.
        deltas = {s: desired.get(s, 0.)-current.get(s, 0.) for s in symbols}
        weights = {s: current.get(s, 0.) for s in symbols}
        sells = sorted((s for s in symbols if deltas[s] < 0), key=lambda s: (
            desired.get(s, 0.) > 0, current.get(s, 0.) if desired.get(s, 0.) == 0
            else deltas[s], s))
        buys = sorted((s for s in symbols if deltas[s] > 0), key=lambda s: (-deltas[s], s))
        for ordered, sign in ((sells, -1), (buys, 1)):
            remaining = fraction*sum(abs(deltas[s]) for s in ordered)
            for symbol in ordered:
                change = min(abs(deltas[symbol]), max(0., remaining))
                weights[symbol] += sign*change
                remaining -= change
        return pl.from_dicts([{**template, 'symbol': s, 'weight': weights[s]} for s in symbols],
                             schema=targets.schema)
    rows = [{**template, 'symbol': symbol,
             'weight': current.get(symbol, 0.) + fraction*(desired.get(symbol, 0.)-current.get(symbol, 0.))}
            for symbol in symbols]
    return pl.from_dicts(rows, schema=targets.schema)
