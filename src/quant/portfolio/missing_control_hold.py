"""Explicit no-trade continuation when actual holdings lack risk controls."""
import math

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
