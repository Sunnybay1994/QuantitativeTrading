"""Deterministic reductions of one signal-close portfolio; no orders or data IO."""
import math
from dataclasses import dataclass

import numpy as np
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
    base: dict[str, float] = {}
    buys: dict[str, float] = {}
    reasons: dict[str, list[str]] = {}
    sectors: dict[str, str | None] = {}
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


@dataclass(frozen=True)
class RelativeConstraintLimits:
    cash_buffer: float = .02
    single_stock_weight: float = .03
    industry_active_band: float = .05
    size_active_band: float = .30
    adv_participation: float = .05
    maximum_iterations: int = 2000
    tolerance: float = 1e-8


def constrain_relative_targets(*, targets: pl.DataFrame, current: pl.DataFrame,
                               market: pl.DataFrame, benchmark: pl.DataFrame,
                               equity: float,
                               limits: RelativeConstraintLimits = RelativeConstraintLimits(),
                               enabled: bool = True, sell_only: bool = False
                               ) -> tuple[pl.DataFrame, dict]:
    """Project fixed selected names onto PIT industry/size bands, without an optimizer.

    market additionally contains total_market_value for every benchmark and held
    security. benchmark is fully invested as_of/symbol/weight; its weighted log
    market-cap mean/std define size z (cash exposure zero). Active industry and
    size exposures use TOTAL ACCOUNT equity, never renormalized stock weights.
    Dykstra projections use a fixed order, iteration bound and explicit residuals.
    Nonconvergence/infeasibility returns conservative targets with feasible=False;
    formal replay MUST reject that result, rather than treat it as constrained.
    """
    if (not 0 <= limits.industry_active_band <= 1 or not math.isfinite(limits.size_active_band)
            or limits.size_active_band < 0 or type(limits.maximum_iterations) is not int
            or limits.maximum_iterations < 1 or not 0 < limits.tolerance <= 1e-4):
        raise ValueError('Invalid relative constraint limits')
    conservative, ordinary = constrain_targets(targets=targets, current=current, market=market,
        equity=equity, limits=ConstraintLimits(limits.cash_buffer, limits.single_stock_weight,
                                             1., limits.adv_participation),
        enabled=enabled, sell_only=sell_only)
    as_of = targets['as_of'][0]
    if (benchmark.is_empty() or benchmark['symbol'].null_count()
            or benchmark['symbol'].is_duplicated().any() or benchmark['as_of'].null_count()
            or (benchmark['as_of'] != as_of).any()
            or any(w is None or not math.isfinite(w) or w < 0 for w in benchmark['weight'])
            or not math.isclose(benchmark['weight'].sum(), 1., abs_tol=1e-10, rel_tol=0)):
        raise ValueError('Require unique fully invested signal-date benchmark weights')
    observations = {r['symbol']: r for r in market.iter_rows(named=True)}
    desired = dict(targets.select('symbol', 'weight').iter_rows())
    held = dict(current.select('symbol', 'weight').iter_rows())
    symbols = [s for s in conservative['symbol'] if desired.get(s, 0.) > 0 or held.get(s, 0.) > 0]
    benchmark_weights = dict(benchmark.select('symbol', 'weight').iter_rows())
    names = set(symbols) | set(benchmark_weights)
    for symbol in names:
        row = observations.get(symbol)
        if (row is None or not isinstance(row['industry_l1'], str) or not row['industry_l1'].strip()
                or row['total_market_value'] is None or not math.isfinite(row['total_market_value'])
                or row['total_market_value'] <= 0):
            raise ValueError(f'Missing PIT industry/size for {symbol}')
    logs = {s: math.log(observations[s]['total_market_value']) for s in names}
    mean = sum(w*logs[s] for s, w in benchmark_weights.items())
    variance = sum(w*(logs[s]-mean)**2 for s, w in benchmark_weights.items())
    if variance <= 1e-20:
        raise ValueError('Benchmark log-size variance is zero; size z is undefined')
    std = math.sqrt(variance)
    z = np.array([(logs[s]-mean)/std for s in symbols])
    benchmark_z = sum(w*(logs[s]-mean)/std for s, w in benchmark_weights.items())
    industries = sorted({observations[s]['industry_l1'].strip() for s in names})
    benchmark_industries = {i: sum(w for s, w in benchmark_weights.items()
        if observations[s]['industry_l1'].strip() == i) for i in industries}
    lower, upper = [], []
    for symbol in symbols:
        old, row = held.get(symbol, 0.), observations[symbol]
        adv = row['adv20']
        allowance = limits.adv_participation*adv/equity if (
            adv is not None and math.isfinite(adv) and adv > 0) else 0.
        lo = max(0., old-allowance) if enabled and row['can_sell'] else old
        hi = old + allowance if (enabled and not sell_only and row['can_buy']
            and desired.get(symbol, 0.) > 0) else old
        lower.append(lo)
        upper.append(min(hi, limits.single_stock_weight))
    lo, hi = np.array(lower), np.array(upper)
    # Each interval projection is closed-form; no covariance or solver dependency.
    bands = [(np.ones(len(symbols)), 0., 1-limits.cash_buffer, 'invested_weight')]
    for industry in industries:
        vector = np.array([float(observations[s]['industry_l1'].strip() == industry) for s in symbols])
        b = benchmark_industries[industry]
        bands.append((vector, max(0., b-limits.industry_active_band),
                      b+limits.industry_active_band, industry))
    bands.append((z, benchmark_z-limits.size_active_band,
                  benchmark_z+limits.size_active_band, 'size'))

    def residuals(weights: np.ndarray) -> dict:
        industry_active = {i: sum(weights[j] for j, s in enumerate(symbols)
            if observations[s]['industry_l1'].strip() == i)-benchmark_industries[i] for i in industries}
        box = max(0., float(np.max(lo-weights, initial=0.)), float(np.max(weights-hi, initial=0.)))
        industry_violation = max(0., *(abs(w)-limits.industry_active_band for w in industry_active.values()))
        size_active = float(weights@z-benchmark_z)
        cash_violation = max(0., float(weights.sum())-(1-limits.cash_buffer))
        return {'industry_active_weights': industry_active, 'size_active_z': size_active,
            'box_violation': box, 'industry_violation': industry_violation,
            'cash_violation': cash_violation,
            'maximum_violation': max(box, industry_violation, cash_violation,
                                     abs(size_active)-limits.size_active_band, 0.)}

    x = np.array([desired.get(s, 0.) for s in symbols], dtype=float)
    corrections = [np.zeros(len(symbols)) for _ in range(len(bands)+1)]
    impossible_box = bool(np.any(lo > hi))
    insufficient_industry_capacity = [
        {'industry': name, 'required': low, 'maximum_reachable': float(vector@hi)}
        for vector, low, _, name in bands[1:-1] if float(vector@hi) < low-limits.tolerance]
    absent_required_industry = [row['industry'] for row in insufficient_industry_capacity
                                if row['maximum_reachable'] == 0.]
    band_capacity_conflicts = []
    for vector, low, high, name in bands:
        minimum = float(np.where(vector >= 0, lo, hi)@vector)
        maximum = float(np.where(vector >= 0, hi, lo)@vector)
        if maximum < low-limits.tolerance or minimum > high+limits.tolerance:
            band_capacity_conflicts.append({'constraint': name, 'minimum_reachable': minimum,
                'maximum_reachable': maximum, 'required_minimum': low, 'required_maximum': high})
    iterations, converged = 0, False
    if not impossible_box and not band_capacity_conflicts:
        for iterations in range(1, limits.maximum_iterations+1):
            previous = x.copy()
            y = x+corrections[0]
            x = np.clip(y, lo, hi)
            corrections[0] = y-x
            for index, (vector, low, high, _) in enumerate(bands, 1):
                y = x+corrections[index]
                norm = float(vector@vector)
                value = float(vector@y)
                adjustment = (min(high, max(low, value))-value)/norm if norm else 0.
                x = y+adjustment*vector
                corrections[index] = y-x
            if float(np.max(np.abs(x-previous), initial=0.)) <= limits.tolerance:
                # A final box clip removes roundoff-negative/over-cap weights.
                candidate = np.clip(x, lo, hi)
                if residuals(candidate)['maximum_violation'] <= limits.tolerance:
                    x, converged = candidate, True
                    break
    projected_residuals = residuals(x)
    if converged:
        chosen = dict(zip(symbols, x.tolist()))
        output = conservative.with_columns(pl.Series('weight', [chosen.get(s, 0.) for s in conservative['symbol']]))
    else:
        output = conservative
    final_weights = dict(output.select('symbol', 'weight').iter_rows())
    final = residuals(np.array([final_weights[s] for s in symbols]))
    return output, {'as_of': str(as_of), 'auto_trade': False, 'feasible': converged,
        'iterations': iterations, 'maximum_iterations': limits.maximum_iterations,
        'tolerance': limits.tolerance, 'cash_weight': max(0., 1-output['weight'].sum()),
        'active_weight_basis': 'total_account_equity_including_cash',
        'benchmark_log_size_mean': mean, 'benchmark_log_size_std': std,
        'residuals': final, 'projection_residuals': projected_residuals,
        'impossible_trading_box': impossible_box,
        'absent_required_industries': absent_required_industry,
        'insufficient_industry_capacity': insufficient_industry_capacity,
        'band_capacity_conflicts': band_capacity_conflicts,
        'failure_reason': None if converged else ('infeasible_trading_bounds' if impossible_box
            or band_capacity_conflicts else 'iteration_limit_not_a_proof_of_infeasibility'),
        'fallback': None if converged else 'conservative_diagnostic_only_reject_formal_replay',
        'conservative_diagnostics': ordinary}
