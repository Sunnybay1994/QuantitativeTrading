"""Signal-close industry-stratified selection and convex weight projection."""
import math

import numpy as np
import polars as pl

from quant.portfolio.industry_candidate_selection import select_industry_candidates


def constrained_targets(*, targets: pl.DataFrame, state: dict, market: pl.DataFrame,
                        scores: pl.DataFrame, policy: dict) -> tuple[pl.DataFrame, dict]:
    """Use actual weights; missing held risk or infeasibility freezes quantities.

    `feasible` denotes an executable continuation for the shared replay hook;
    `constraints_satisfied` separately records hard constraint success. A frozen
    continuation can never qualify the rule for replacing the paper account.
    """
    day = targets['as_of'][0]
    if targets['as_of'].n_unique() != 1 or state.get('date') != str(day):
        raise ValueError('Require the actual signal-close account')
    if market['symbol'].is_duplicated().any() or market.filter(pl.col('as_of') != day).height:
        raise ValueError('Require unique contemporaneous market observations')
    if market.filter(pl.col('known_at').is_null() | (pl.col('known_at') > day)).height:
        raise ValueError('Market input is not known at signal close')
    equity = float(state['nav'][-1]['equity'])
    if not math.isfinite(equity) or equity <= 0:
        raise ValueError('Invalid account equity')
    held = {s: h['quantity']*h['mark_price']/equity for s, h in state['holdings'].items()
            if h['quantity'] > 0}
    if sum(held.values()) > 1+1e-8:
        raise ValueError('Account is overinvested')
    template = targets.row(0, named=True)
    observations = {r['symbol']: r for r in market.to_dicts()}
    base = {'as_of': str(day), 'applied': True, 'auto_trade': False}
    if targets['weight'].null_count() or not targets['weight'].is_finite().all() or (targets['weight'] < 0).any():
        raise ValueError('Invalid long-only target weights')
    if (targets['weight'] == 0).all():
        # The model's registered cash instruction overrides investment exposure
        # floors, never execution restrictions. Include the R4 account's actual
        # holdings, which need not coincide with the model's Top-K exit list.
        names = sorted(set(held) | set(targets['symbol']))
        restricted = {r['symbol'] for r in state.get('restricted_shares', [])
                      if r['quantity'] > 0 and str(r['list_date']) > str(day)}
        permissions, caps, remaining = {}, {}, {}
        for symbol in names:
            row = observations.get(symbol, {})
            adv = row.get('adv20')
            cap = float(adv)*policy['adv_participation'] if adv is not None and math.isfinite(adv) and adv > 0 else 0.
            can_sell = bool(row.get('can_sell')) and symbol not in restricted
            permissions[symbol] = (False, can_sell)
            caps[symbol] = cap
            remaining[symbol] = max(0., held.get(symbol, 0.)-cap/equity) if can_sell else held.get(symbol, 0.)
        out = pl.from_dicts([{**template, 'symbol': s, 'weight': 0.} for s in names], schema=targets.schema)
        return out, {**base, 'feasible': True,
            'constraints_satisfied': all(w <= policy['tolerance'] for w in remaining.values()),
            'action': 'cash_exit', 'exposure_constraints_applicable': False,
            'nominee_symbols': [], 'requested_cash_weight': 1.,
            'signal_capacity_residual_weights': remaining,
            'execution_direction_permissions': permissions, 'execution_notional_caps': caps,
            'execution_rules': 'shared replay retains settlement, suspension, price bands and lot checks'}

    def freeze(reason: str, detail: dict) -> tuple[pl.DataFrame, dict]:
        names = sorted(set(held) | set(targets['symbol']))
        out = pl.from_dicts([{**template, 'symbol': s, 'weight': held.get(s, 0.)}
                            for s in names], schema=targets.schema)
        return out, {**base, 'feasible': True, 'constraints_satisfied': False,
            'action': 'freeze_all_actual_quantities', 'failure_reason': reason,
            'execution_direction_permissions': {s: (False, False) for s in names}, **detail}

    def complete(row: dict | None) -> bool:
        return bool(row and row.get('industry_l1') and row.get('industry_l1') != 'UNKNOWN' and row.get('size') is not None
                    and math.isfinite(row['size']))

    missing = [s for s in held if not complete(observations.get(s))]
    if missing:
        return freeze('missing_actual_held_risk_controls', {'missing_symbols': missing})
    benchmark = market.filter(pl.col('eligible'))
    if benchmark.is_empty():
        raise ValueError('Eligible benchmark is empty')
    benchmark = benchmark.select('as_of', 'symbol').with_columns(
        pl.lit(1/benchmark.height).alias('weight'))
    current = pl.from_dicts([{'as_of': day, 'symbol': s, 'weight': w} for s, w in held.items()],
        schema={'as_of': pl.Date, 'symbol': pl.String, 'weight': pl.Float64})
    restricted = {r['symbol'] for r in state.get('restricted_shares', [])
                  if r['quantity'] > 0 and str(r['list_date']) > str(day)}
    market = market.with_columns((pl.col('can_sell') & ~pl.col('symbol').is_in(restricted)).alias('can_sell'))
    observations = {r['symbol']: r for r in market.to_dicts()}
    nominees, selection = select_industry_candidates(scores=scores, market=market,
        current=current, benchmark=benchmark, previous=state.get('constraint_nominees', list(held)),
        top_k=policy['top_k'], retention_multiplier=policy['retention_multiplier'],
        minimum_signal_stocks=policy['top_k'], single_stock_weight=policy['single_stock_weight'],
        industry_active_band=policy['industry_active_band'])
    if not selection['feasible']:
        return freeze('industry_nomination_infeasible', {'selection': selection})
    selected = set(nominees['symbol'])
    candidates = {s for s in scores.filter(pl.col('score').is_finite())['symbol']
                  if complete(observations.get(s)) and observations[s]['can_buy']}
    names = sorted(candidates | set(held))
    n = len(names)
    old = np.array([held.get(s, 0.) for s in names])
    z = np.array([observations[s]['size'] for s in names])
    sectors = [observations[s]['industry_l1'] for s in names]
    adv = np.array([observations[s]['adv20'] or 0. for s in names])
    adv = np.where(np.isfinite(adv) & (adv > 0), adv, 0.)
    allowance = adv*policy['adv_participation']/equity
    lower = np.array([max(0., old[i]-allowance[i]) if observations[s]['can_sell'] else old[i]
                      for i, s in enumerate(names)])
    upper = np.array([min(policy['single_stock_weight'], old[i]+allowance[i])
                      if s in candidates else min(policy['single_stock_weight'], old[i])
                      for i, s in enumerate(names)])
    sector_weights: dict[str, float] = {}
    for s, weight in benchmark.select('symbol', 'weight').iter_rows():
        sector = observations[s]['industry_l1']
        sector_weights[sector] = sector_weights.get(sector, 0.)+weight
    receivable = sum(r['amount'] for r in state.get('receivables', []))/equity
    bands = [(np.ones(n), 0., 1-policy['cash_buffer']-receivable, 'invested')]
    for sector in sorted(set(sectors) | set(sector_weights)):
        weight = sector_weights.get(sector, 0.)
        bands.append((np.array([float(s == sector) for s in sectors]),
                      max(0., weight-policy['industry_active_band']),
                      weight+policy['industry_active_band'], 'industry:'+sector))
    bands.append((z, -policy['size_band'], policy['size_band'], 'size'))

    def residual(x: np.ndarray) -> float:
        return max(0., float(np.max(lower-x)), float(np.max(x-upper)),
                   *(max(lo-float(v@x), float(v@x)-hi) for v, lo, hi, _ in bands))

    conflicts = []
    for v, lo, hi, label in bands:
        minimum = float(np.where(v >= 0, lower, upper)@v)
        maximum = float(np.where(v >= 0, upper, lower)@v)
        if minimum > hi+policy['tolerance'] or maximum < lo-policy['tolerance']:
            conflicts.append({'constraint': label, 'minimum': minimum, 'maximum': maximum})
    if np.any(lower > upper) or conflicts:
        return freeze('unavoidable_trading_or_exposure_bounds', {'capacity_conflicts': conflicts})
    x = np.array([(1-policy['cash_buffer'])/policy['top_k'] if s in selected else 0. for s in names])
    corrections = [np.zeros(n) for _ in range(len(bands)+1)]
    success = False
    for iteration in range(policy['maximum_iterations']):
        previous = x.copy()
        y = x+corrections[0]
        x = np.clip(y, lower, upper)
        corrections[0] = y-x
        for i, (v, lo, hi, _) in enumerate(bands, 1):
            y = x+corrections[i]
            norm = float(v@v)
            value = float(v@y)
            x = y+((min(hi, max(lo, value))-value)/norm if norm else 0.)*v
            corrections[i] = y-x
        if np.max(np.abs(x-previous)) <= policy['tolerance']:
            x = np.clip(x, lower, upper)
            if residual(x) <= policy['tolerance']:
                success = True
                break
    if not success:
        return freeze('projection_did_not_converge', {'maximum_violation': residual(x)})
    weights = dict(zip(names, x.tolist()))
    output_names = sorted(set(names) | set(targets['symbol']))
    out = pl.from_dicts([{**template, 'symbol': s, 'weight': weights.get(s, 0.)}
                        for s in output_names], schema=targets.schema)
    return out, {**base, 'feasible': True, 'constraints_satisfied': True,
        'iterations': iteration+1, 'maximum_violation': residual(x), 'size_z': float(x@z),
        'industry_active': {label[9:]: float(v@x)-sector_weights.get(label[9:], 0.)
                            for v, _, _, label in bands if label.startswith('industry:')},
        'nominee_symbols': sorted(selected), 'selection': selection,
        'execution_direction_permissions': {s: (observations[s]['can_buy'], observations[s]['can_sell'])
            if s in observations else (False, False) for s in output_names},
        'execution_notional_caps': {s: float(adv[i]*policy['adv_participation']) for i, s in enumerate(names)},
        'positive_target_names': int((x > 1e-8).sum()), 'cash_weight': 1-float(x.sum())}
