"""One frozen, cost-aware multiple-choice integer construction; no return inputs."""
import math

import numpy as np
import polars as pl
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import csc_matrix


def construct(*, raw, budgeted, state, market, prices, instruments, scores, costs, spec):
    day = raw['as_of'][0]
    if state['date'] != str(day) or raw['as_of'].n_unique() != 1:
        raise ValueError('Actual signal-close account required')
    if market.filter((pl.col('known_at') > day) | (pl.col('as_of') != day)).height:
        raise ValueError('Future or mismatched risk observation')
    equity = state['nav'][-1]['equity']
    desired = dict(raw.select('symbol', 'weight').iter_rows())
    budget = dict(budgeted.select('symbol', 'weight').iter_rows())
    observations = {r['symbol']: r for r in market.to_dicts()}
    holdings = state['holdings']
    names = sorted(set(desired) | set(holdings))
    ranking = {s: i for i, s in enumerate(sorted(names, key=lambda s: (-scores.get(s, -math.inf), s)))}
    sectors = {}; sizes = {}; marks = {}; old = {}; options = []; diagnostics = []
    restricted = {r['symbol'] for r in state.get('restricted_shares', []) if r['quantity'] > 0}
    unknown = []
    for s in names:
        h = holdings.get(s, {}); old[s] = h.get('quantity', 0)
        price = prices.get(s); row = observations.get(s, {})
        usable = bool(price and math.isfinite(price) and price > 0)
        marks[s] = price if usable else h.get('mark_price')
        sector = row.get('industry_l1'); size = row.get('size')
        risk_ok = bool(sector and sector != 'UNKNOWN' and size is not None and math.isfinite(size))
        if not risk_ok and old[s]: unknown.append(s)
        sectors[s] = sector if risk_ok else 'UNKNOWN'
        sizes[s] = size if risk_ok else None
        lot = int(instruments[s]['board_lot'])
        adv = row.get('adv20')
        known = usable and risk_ok and adv is not None and math.isfinite(adv) and adv > 0
        p = marks[s]
        maxq = math.floor(spec['single_stock_weight']*equity/p/lot)*lot if p else 0
        # Retain existing odd shares; reductions must be round lots or a full exit.
        candidates = {old[s]}
        if known:
            candidates.update(q for q in range(0, max(maxq, old[s]) + lot, lot)
                              if q <= maxq and ((q-old[s]) % lot == 0 or q == 0))
            candidates.update(old[s]-n*lot for n in range(1, old[s]//lot+1))
            if desired.get(s, 0) == 0 and row.get('can_sell') and s not in restricted:
                candidates = {0}  # Explicit exits, not subject to the fee hurdle.
        accepted = []; cost_rejected = 0; capacity_rejected = 0
        for q in sorted(candidates):
            delta = q-old[s]; amount = abs(delta)*(p or 0.)
            reason = None
            if delta and not known: reason = 'missing_signal_price_or_risk'
            if delta > 0 and (not row.get('can_buy') or desired.get(s, 0) <= 0): reason = 'buy_not_allowed'
            if delta < 0 and (not row.get('can_sell') or s in restricted): reason = 'sell_not_allowed'
            if delta and known and amount > adv*spec['adv_participation']+1e-8: reason = 'adv_cap'
            fee = slip = 0.
            if delta and p:
                side = 'BUY' if delta > 0 else 'SELL'
                execution = costs.execution_price(p, side)
                fee = costs.fee(abs(delta)*execution, day, side, market=s[-2:], quantity=abs(delta))
                slip = abs(execution-p)*abs(delta)
                mandatory = delta < 0 and (desired.get(s, 0) == 0 or old[s]*p > spec['single_stock_weight']*equity)
                if not mandatory and (fee+slip)/amount > spec['maximum_one_way_cost_fraction']+1e-12:
                    reason = 'voluntary_adjustment_cost_ceiling'
            if reason:
                cost_rejected += reason == 'voluntary_adjustment_cost_ceiling'
                capacity_rejected += reason == 'adv_cap'
                continue
            accepted.append(dict(symbol=s, quantity=q, delta=delta, value=q*(p or 0.),
                turnover=amount/2, fee=fee, slip=slip,
                error=abs(q*(p or 0.)-budget.get(s, 0)*equity), rank=ranking[s]))
        if not accepted:
            accepted = [dict(symbol=s, quantity=old[s], delta=0, value=old[s]*(p or 0.),
                             turnover=0., fee=0., slip=0., error=0., rank=ranking[s])]
        options.extend(accepted)
        diagnostics.append(dict(symbol=s, signal_price=price, valuation_mark=p, price_complete=usable,
            risk_complete=risk_ok, industry=sectors[s], size=sizes[s], board_lot=lot,
            score=scores.get(s), rank=ranking[s], current_quantity=old[s],
            raw_weight=desired.get(s, 0.), budget_weight=budget.get(s, 0.),
            naive_integer_quantity=math.floor(budget.get(s, 0)*equity/price/lot)*lot if usable else None,
            below_one_lot=bool(usable and 0 < budget.get(s, 0)*equity < lot*price),
            candidate_options=len(accepted), input_block=None if known else 'missing_price_risk_or_adv',
            cost_rejected_options=cost_rejected, capacity_rejected_options=capacity_rejected,
            exit_required=desired.get(s, 0) == 0 and old[s] > 0))
    n = len(options); rows = []; low = []; high = []; labels = []
    def constraint(values, lo, hi, label):
        rows.append(values); low.append(lo); high.append(hi); labels.append(label)
    for s in names:
        constraint([float(o['symbol'] == s) for o in options], 1., 1., 'choice:'+s)
    values = np.array([o['value'] for o in options])
    costs_array = np.array([o['fee']+o['slip'] for o in options])
    capacity = equity*spec['stock_fraction']
    constraint(values, 0., capacity, 'stock_allocation')
    # Leave the ETF nominal allocation and receivables unavailable for stock purchases.
    constraint(values+costs_array, 0., capacity-sum(r['amount'] for r in state.get('receivables', [])), 'cash_reserve')
    constraint([o['turnover'] for o in options], 0., equity*spec['stock_fraction']*spec['stock_budget'], 'turnover')
    for sector in sorted(set(sectors.values())):
        intended = sum(desired.get(s, 0)*equity for s in names if sectors[s] == sector)
        vector = [o['value'] if sectors[o['symbol']] == sector else 0. for o in options]
        constraint(vector, max(0., intended-spec['industry_intent_band']*equity),
                   min(spec['industry_weight']*equity, intended+spec['industry_intent_band']*equity), 'industry:'+sector)
    for s in names:
        constraint([o['value'] if o['symbol'] == s else 0. for o in options], 0.,
                   spec['single_stock_weight']*equity, 'single:'+s)
    if not unknown:
        center = sum(desired.get(s, 0)*equity*(sizes[s] or 0.) for s in names)
        constraint([o['value']*(sizes[o['symbol']] or 0.) for o in options],
                   center-spec['size_intent_band']*equity, center+spec['size_intent_band']*equity, 'size_intent')
    def solve(objective):
        return milp(objective/equity, integrality=np.ones(n), bounds=Bounds(0., 1.),
                    constraints=LinearConstraint(csc_matrix(np.array(rows)), low, high),
                    options={'time_limit': 30., 'mip_rel_gap': 0.})
    solution = None; status = 'unknown_held_risk' if unknown else ''
    if not unknown:
        first = solve(-values)
        if first.success:
            maximum = float(values@first.x)
            constraint(values, maximum-.01, maximum+.01, 'maximum_investment')
            second = solve(np.array([o['error'] for o in options])+costs_array+
                           np.array([o['value']*o['rank'] for o in options])*1e-7)
            if second.success: solution = second.x
            else: status = 'secondary_solver_'+str(second.status)
        else: status = 'primary_solver_'+str(first.status)
    selected = {o['symbol']: o for i, o in enumerate(options) if solution is not None and solution[i] > .5}
    satisfied = solution is not None
    if satisfied and len(selected) != len(names): raise ValueError('Integer solution lacks one option per symbol')
    for r in diagnostics:
        s = r['symbol']; chosen = selected.get(s)
        r.update(integer_quantity=chosen['quantity'] if chosen else old[s],
            net_order_quantity=chosen['delta'] if chosen else 0,
            expected_fee=chosen['fee'] if chosen else 0., expected_slippage=chosen['slip'] if chosen else 0.,
            constraints_satisfied=satisfied, construction_status='optimal' if satisfied else status)
    deltas = {r['symbol']: int(r['net_order_quantity']) for r in diagnostics}
    weights = {r['symbol']: r['integer_quantity']*(r['valuation_mark'] or 0.)/equity for r in diagnostics}
    residuals = []
    if solution is not None:
        for label, vector, lo, hi in zip(labels, rows, low, high):
            actual = float(np.array(vector)@solution)
            residuals.append(dict(constraint=label, value=actual, lower=lo, upper=hi,
                                  violation=max(0., lo-actual, actual-hi)))
        if max(r['violation'] for r in residuals) > .011: raise ValueError('Invalid integer solver residual')
    return weights, deltas, diagnostics, dict(constraints_satisfied=satisfied, status=status or 'optimal',
                                            unknown_held_risk=unknown, residuals=residuals)
