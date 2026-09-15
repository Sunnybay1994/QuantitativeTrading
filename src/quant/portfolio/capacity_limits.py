"""Execution-only ADV caps, preserving the already budgeted Q10 target weights."""
import datetime as dt
import math

import polars as pl


def cap_targets(targets: pl.DataFrame, state: dict, market: pl.DataFrame,
                participation: float = .05) -> tuple[pl.DataFrame, dict]:
    if not math.isfinite(participation) or not 0 < participation <= 1:
        raise ValueError('Invalid participation limit')
    dates = targets['as_of'].unique().to_list()
    if len(dates) != 1 or str(dates[0]) != state['date']:
        raise ValueError('Capacity controls require actual signal-close state')
    day = dt.date.fromisoformat(str(dates[0]))
    if targets['execution_date'].null_count() or not (targets['execution_date'] > day).all():
        raise ValueError('Execution must follow signal close')
    if market['symbol'].is_duplicated().any():
        raise ValueError('Duplicate ADV controls')
    if market.height and (market['as_of'].null_count() or not (market['as_of'] == day).all()):
        raise ValueError('ADV must belong to this signal date')
    values = dict(market.select('symbol', 'amount20').iter_rows())
    caps, missing = {}, []
    for symbol in sorted(set(targets['symbol']) | set(state['holdings'])):
        value = values.get(symbol)
        if value is None or not math.isfinite(value) or value <= 0:
            caps[symbol] = 0.
            missing.append(symbol)
        else:
            caps[symbol] = participation*value
    return targets, {'as_of': str(day), 'feasible': True, 'applied': True,
        'execution_notional_caps': caps, 'missing_adv_symbols': missing,
        'target_weights_changed': False,
        'missing_policy': 'zero_execution_capacity_keep_existing_holdings'}
