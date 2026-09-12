"""Explicit no-trade continuation when actual holdings lack risk controls."""
import math
import copy
from typing import Callable

import polars as pl


def _missing_fields(row: dict | None, unknown_industry_policy: str) -> list[str]:
    if row is None:
        return ['industry_l1', 'total_market_value']
    missing = []
    industry = row.get('industry_l1')
    if unknown_industry_policy != 'explicit_unknown_bucket' and (
            not isinstance(industry, str) or not industry.strip() or industry == 'UNKNOWN'):
        missing.append('industry_l1')
    size = row.get('total_market_value')
    if size is None or not math.isfinite(size) or size <= 0:
        missing.append('total_market_value')
    return missing


def hold_missing_controls(*, targets: pl.DataFrame, state: dict, market: pl.DataFrame,
                          benchmark: pl.DataFrame, unknown_industry_policy: str
                          ) -> tuple[pl.DataFrame, dict] | None:
    """Return an unchanged-quantity action only for missing actual-held controls.

    No risk values are filled. A complete benchmark remains necessary, and an
    invalid account or target table is an error rather than a fallback trigger.
    """
    signal = targets['as_of'][0]
    observations = {row['symbol']: row for row in market.iter_rows(named=True)}
    held = {symbol: h for symbol, h in state.get('holdings', {}).items() if h['quantity'] > 0}
    missing = {s: fields for s in held
               if (fields := _missing_fields(observations.get(s), unknown_industry_policy))}
    if not missing:
        return None
    if (state.get('date') != str(signal) or not state.get('nav')
            or targets['as_of'].n_unique() != 1 or targets['symbol'].is_duplicated().any()
            or targets['weight'].null_count() or not targets['weight'].is_finite().all()
            or (targets['weight'] < 0).any() or targets['weight'].sum() > 1+1e-10):
        raise ValueError('Missing-control hold requires a valid signal-close account and targets')
    equity = state['nav'][-1]['equity']
    if not math.isfinite(equity) or equity <= 0:
        raise ValueError('Missing-control hold requires positive finite signal equity')
    weights = {}
    for symbol, holding in held.items():
        quantity, mark = holding['quantity'], holding['mark_price']
        if (type(quantity) is not int or quantity <= 0
                or not math.isfinite(mark) or mark <= 0):
            raise ValueError('Invalid actual holding for missing-control hold')
        weights[symbol] = quantity*mark/equity
    if sum(weights.values()) > 1+1e-10:
        raise ValueError('Missing-control hold cannot conceal an overinvested account')
    if (benchmark.is_empty() or benchmark['symbol'].is_duplicated().any()
            or benchmark['symbol'].null_count() or benchmark['as_of'].null_count()
            or (benchmark['as_of'] != signal).any() or benchmark['weight'].null_count()
            or not benchmark['weight'].is_finite().all() or (benchmark['weight'] < 0).any()
            or not math.isclose(benchmark['weight'].sum(), 1., rel_tol=0, abs_tol=1e-10)):
        raise ValueError('Missing-control hold requires a complete signal-date benchmark')
    for symbol in benchmark.filter(pl.col('weight') > 0)['symbol']:
        if _missing_fields(observations.get(symbol), unknown_industry_policy):
            raise ValueError(f'Missing benchmark controls cannot invoke held-only continuation: {symbol}')
    template = targets.row(0, named=True)
    output = pl.from_dicts([{**template, 'symbol': symbol, 'weight': weight}
                           for symbol, weight in sorted(weights.items())], schema=targets.schema)
    return output, {'as_of': str(signal), 'applied': True, 'feasible': False,
        'action': 'hold_actual_quantities', 'constraints_verified': False,
        'failure_reason': 'missing_actual_held_controls',
        'missing_held_controls': [{'symbol': symbol, 'fields': fields, 'weight': weights[symbol]}
                                  for symbol, fields in sorted(missing.items())],
        'unmodeled_held_weight': sum(weights[s] for s in missing),
        'cash_weight': max(0., 1-sum(weights.values())),
        'execution_direction_permissions': {symbol: (False, False) for symbol in weights}}


def validate_quantity_hold(*, targets: pl.DataFrame, state: dict, info: dict) -> None:
    """Ensure an unverified continuation cannot submit a buy or sell target."""
    held = {s: h for s, h in state['holdings'].items() if h['quantity'] > 0}
    permissions = info.get('execution_direction_permissions', {})
    if (info.get('constraints_verified') is not False or info.get('feasible') is not False
            or not info.get('missing_held_controls') or targets['symbol'].is_duplicated().any()
            or set(targets['symbol']) != set(held) or set(permissions) != set(held)
            or any(tuple(value) != (False, False) for value in permissions.values())):
        raise ValueError('Unverified continuation must freeze every actual holding quantity')
    equity = state['nav'][-1]['equity']
    for row in targets.iter_rows(named=True):
        holding = held[row['symbol']]
        if not math.isclose(row['weight'], holding['quantity']*holding['mark_price']/equity,
                            rel_tol=0, abs_tol=1e-10):
            raise ValueError('Unverified continuation must preserve signal-close holding weights')


def isolate_missing_controls(*, targets: pl.DataFrame, state: dict,
        continuation: tuple[pl.DataFrame, dict], cash_buffer: float,
        project: Callable[[pl.DataFrame, dict, list[str], float], tuple[pl.DataFrame, dict]]
        ) -> tuple[pl.DataFrame, dict]:
    """Project only modeled capital; unknown full-book risk remains unverified."""
    held_targets, fallback = continuation
    frozen = [row['symbol'] for row in fallback['missing_held_controls']]
    fraction = 1-fallback['unmodeled_held_weight']
    liquid = copy.deepcopy(state)
    liquid['holdings'] = {s: h for s, h in liquid['holdings'].items() if s not in frozen}
    liquid['restricted_shares'] = [r for r in liquid.get('restricted_shares', [])
                                    if r['symbol'] not in frozen]
    liquid['constraint_nominees'] = [s for s in state.get('constraint_nominees', sorted(state['holdings']))
                                     if s not in frozen]
    liquid['nav'][-1]['equity'] = state['nav'][-1]['equity']*fraction
    remaining = targets.filter(~pl.col('symbol').is_in(frozen))
    try:
        if fraction <= cash_buffer or remaining.is_empty():
            raise ValueError('No deployable liquid capital or target universe')
        result, info = project(remaining, liquid, frozen, cash_buffer/fraction)
        if info.get('feasible') is not True:
            raise ValueError(f"Liquid projection infeasible: {info.get('failure_reason')}")
        if set(result['symbol']) & set(frozen):
            raise ValueError('Liquid projection reintroduced frozen holdings')
        result = pl.concat([result.with_columns(pl.col('weight')*fraction),
                            held_targets.filter(pl.col('symbol').is_in(frozen))]).sort('symbol')
        merged = {**fallback, 'action': 'isolate_actual_quantities',
            'liquid_constraints_verified': True, 'liquid_equity_fraction': fraction,
            'full_book_size_bound': None, 'liquid_constraint_diagnostics': info,
            'nominee_symbols': info.get('nominee_symbols', liquid['constraint_nominees']),
            'execution_direction_permissions': {
                **info.get('execution_direction_permissions', {}),
                **{s: (False, False) for s in frozen}},
            'cash_weight': 1-result['weight'].sum()}
        validate_quantity_isolation(targets=result, state=state, info=merged)
        return result, merged
    except ValueError as error:
        return held_targets, {**fallback, 'isolation_failure': str(error),
                              'full_book_size_bound': None}


def validate_quantity_isolation(*, targets: pl.DataFrame, state: dict, info: dict) -> None:
    """Permit liquid trading only after projection, with frozen quantities locked."""
    if (info.get('feasible') is not False or info.get('constraints_verified') is not False
            or info.get('liquid_constraints_verified') is not True
            or not info.get('missing_held_controls') or targets['symbol'].is_duplicated().any()
            or targets['weight'].null_count() or not targets['weight'].is_finite().all()
            or (targets['weight'] < 0).any() or targets['weight'].sum() > 1+1e-10):
        raise ValueError('Invalid unverified isolated continuation')
    weights = dict(targets.select('symbol', 'weight').iter_rows())
    for row in info['missing_held_controls']:
        symbol = row['symbol']
        holding = state['holdings'][symbol]
        expected = holding['quantity']*holding['mark_price']/state['nav'][-1]['equity']
        if (tuple(info['execution_direction_permissions'].get(symbol, ())) != (False, False)
                or not math.isclose(weights.get(symbol, -1), expected, rel_tol=0, abs_tol=1e-10)):
            raise ValueError('Isolated holding must retain actual quantity and direction lock')
