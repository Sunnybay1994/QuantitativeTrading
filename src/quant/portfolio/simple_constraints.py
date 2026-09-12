"""Deterministic reductions of one signal-close portfolio; no orders or data IO."""
import math
from dataclasses import dataclass

import polars as pl

from quant.portfolio.concentration_caps import cap_targets


@dataclass(frozen=True)
class ConstraintLimits:
    cash_buffer: float = .02
    single_stock_weight: float = .03
    industry_weight: float = .20
    adv_participation: float = .05


def constrain_targets(*, targets: pl.DataFrame, current: pl.DataFrame,
                      market: pl.DataFrame, equity: float,
                      limits: ConstraintLimits = ConstraintLimits(),
                      enabled: bool = True, sell_only: bool = False
                      ) -> tuple[pl.DataFrame, dict]:
    """Return target-shaped weights and diagnostics for ONE as_of batch.

    current: as_of/symbol/weight (actual marked holdings, same close).
    market: as_of/symbol/known_at/industry_l1/adv20/can_buy/can_sell.
    known_at must be <= as_of, ADV20 is currency per day, permissions are
    signal-close observations only. Missing market rows freeze that holding.
    Missing industry prohibits new exposure. Never substitute future industry.
    ADV limits absolute weight change; unavailable ADV freezes the holding.
    Unavoidable existing exposure can breach limits and is reported explicitly.
    No redistribution into unselected names; residual cash stays uninvested.
    These are reference weights; execution must recheck T+1, lots and next-day
    limits. enabled=False freezes all actual weights; sell_only prevents buys.
    """
    if not math.isfinite(equity) or equity <= 0:
        raise ValueError('Require positive marked equity')
    if not (0 < limits.adv_participation <= 1):
        raise ValueError('Invalid ADV participation')
    if type(enabled) is not bool or type(sell_only) is not bool:
        raise ValueError('Switches must be boolean')
    if targets.is_empty() or targets['as_of'].n_unique() != 1:
        raise ValueError('Require one nonempty signal batch, use zero targets to liquidate')
    as_of = targets['as_of'][0]
    if as_of is None:
        raise ValueError('Missing signal date')
    for frame in (targets, current, market):
        if frame['symbol'].null_count() or frame['symbol'].is_duplicated().any():
            raise ValueError('Require unique nonnull symbols')
        if frame.height and (frame['as_of'].null_count() or (frame['as_of'] != as_of).any()):
            raise ValueError('Inputs must have the same signal close')
    for frame in (targets, current):
        if any(w is None or not math.isfinite(w) or w < 0 for w in frame['weight']):
            raise ValueError('Invalid portfolio weight')
        if frame['weight'].sum() > 1 + 1e-10:
            raise ValueError('Portfolio exceeds equity')
    if market['known_at'].null_count() or (market['known_at'] > as_of).any():
        raise ValueError('Market observations must be known at signal close')
    for name in ('can_buy', 'can_sell'):
        if market[name].dtype != pl.Boolean or market[name].null_count():
            raise ValueError('Require explicit boolean trading permissions')
    desired = dict(targets.select('symbol', 'weight').iter_rows())
    held = dict(current.select('symbol', 'weight').iter_rows())
    symbols = sorted(set(desired) | set(held))
    template = targets.row(0, named=True)
    expanded = pl.from_dicts([{**template, 'symbol': s, 'weight': desired.get(s, 0.)}
                             for s in symbols], schema=targets.schema)
    capped = cap_targets(expanded, market, cash_buffer=limits.cash_buffer,
                         single_stock_weight=limits.single_stock_weight,
                         industry_weight=limits.industry_weight)
    cap = dict(capped.select('symbol', 'weight').iter_rows())
    observations = {r['symbol']: r for r in market.iter_rows(named=True)}
    base, buys, reasons, sectors = {}, {}, {}, {}
    for symbol in symbols:
        old, target = held.get(symbol, 0.), cap[symbol]
        row = observations.get(symbol)
        reasons[symbol] = []
        if abs(target - desired.get(symbol, 0.)) > 1e-12:
            reasons[symbol].append('concentration_or_unknown_industry')
        sector = row['industry_l1'] if row else None
        sectors[symbol] = sector.strip() if isinstance(sector, str) and sector.strip() else None
        adv = row['adv20'] if row else None
        allowance = limits.adv_participation * adv / equity if (
            adv is not None and math.isfinite(adv) and adv > 0) else 0.
        if not enabled:
            target = old
            reasons[symbol].append('halt')
        elif row is None or allowance == 0:
            target = old
            reasons[symbol].append('missing_market_or_adv')
        else:
            if target > old and (sell_only or not row['can_buy']):
                target = old
                reasons[symbol].append('buy_disabled')
            if target < old and not row['can_sell']:
                target = old
                reasons[symbol].append('sell_disabled')
            clipped = min(old + allowance, max(old - allowance, target))
            if abs(clipped - target) > 1e-12:
                reasons[symbol].append('adv_participation')
            target = clipped
        base[symbol] = min(old, target)
        buys[symbol] = max(0., target-old)
    # Preserved holdings consume industry/cash budgets before any proposed buys.
    for sector in set(sectors.values()):
        members = [s for s in symbols if sectors[s] == sector]
        requested = sum(buys[s] for s in members)
        room = max(0., limits.industry_weight-sum(base[s] for s in members)) if sector else 0.
        scale = min(1., room/requested) if requested else 1.
        for symbol in members:
            if scale < 1 and buys[symbol] > 0:
                reasons[symbol].append('industry_room')
            buys[symbol] *= scale
    requested = sum(buys.values())
    room = max(0., 1-limits.cash_buffer-sum(base.values()))
    scale = min(1., room/requested) if requested else 1.
    result = {s: base[s] + buys[s]*scale for s in symbols}
    industry_totals: dict[str, float] = {}
    for symbol, weight in result.items():
        sector = sectors[symbol] or 'UNKNOWN'
        industry_totals[sector] = industry_totals.get(sector, 0.) + weight
        if scale < 1 and buys[symbol] > 0:
            reasons[symbol].append('cash_room')
    output = expanded.with_columns(pl.Series('weight', [result[s] for s in symbols]))
    cash = max(0., 1-sum(result.values()))
    diagnostics = {'as_of': str(as_of), 'auto_trade': False,
        'cash_weight': cash, 'maximum_stock_weight': max(result.values(), default=0.),
        'industry_weights': industry_totals,
        'changed_from_requested': sum(abs(result[s]-desired.get(s, 0.)) > 1e-12 for s in symbols),
        'unresolved_existing_limits': {
            'stocks': [s for s in symbols if result[s] > limits.single_stock_weight+1e-10],
            'industries': [k for k, w in industry_totals.items()
                           if w > limits.industry_weight+1e-10],
            'cash_buffer': cash < limits.cash_buffer-1e-10,
            'unknown_industry': industry_totals.get('UNKNOWN', 0.) > 1e-10},
        'reasons': {s: r for s, r in reasons.items() if r}}
    return output, diagnostics
