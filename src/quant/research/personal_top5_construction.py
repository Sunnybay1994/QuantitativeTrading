"""Fixed personal-account quantities and isolated exchange-lot execution binding.

Only the new experiment uses this binding. No shared module global is patched.
STAR: minimum 200 shares, increments of one; an odd residual may exit in full.
Source: https://edu.sse.com.cn/tib/qa/c/4866268.shtml
"""
import math
from types import FunctionType

import polars as pl

from quant.backtest import daily_account, daily_simulator
from quant.domain.enums import ExecutionRejectReason, OrderSide
from quant.research import classic_monthly_baseline


def star(symbol):
    return symbol.startswith(('688', '689')) and symbol.endswith('.SH')


def _bind(function, **dependencies):
    """Inject experiment-only dependencies without changing shared callables."""
    result = FunctionType(function.__code__, {**function.__globals__, **dependencies},
                          function.__name__, function.__defaults__, function.__closure__)
    result.__kwdefaults__ = function.__kwdefaults__
    return result


def affordable(**kwargs):
    quantity = daily_simulator._affordable_quantity(**kwargs)
    return 0 if star(kwargs['symbol']) and quantity < 200 else quantity


def reject(**kwargs):
    reason = daily_simulator._reject_reason(**kwargs)
    if reason is not None:
        return reason
    if star(kwargs['symbol']):
        quantity = kwargs['quantity']
        residual_exit = (kwargs['side'] == OrderSide.SELL
                         and quantity == kwargs['position'].quantity and quantity < 200)
        if (quantity < 200 and not residual_exit) or quantity > 100000:
            return ExecutionRejectReason.LOT_CONSTRAINT
    return None


def personal_replay(**kwargs):
    # Every other engine operation (corporate actions, tax, T+1, sells first,
    # cash, limits, delisting and checkpoint state) is the original implementation.
    simulate = _bind(daily_simulator.simulate_daily_targets,
                     _affordable_quantity=affordable, _reject_reason=reject)
    advance = _bind(daily_account.advance, simulate_daily_targets=simulate)
    replay = _bind(classic_monthly_baseline.replay, advance=advance)
    instruments = kwargs['instruments'].with_columns(pl.Series('board_lot', [
        1 if star(row['symbol']) else row['board_lot']
        for row in kwargs['instruments'].to_dicts()], dtype=pl.Int64))
    return replay(**{**kwargs, 'instruments': instruments})


def rank_targets(predictions, universe, sessions, end, top_k, cash_buffer):
    if top_k not in (5, 50) or cash_buffer != .02:
        raise ValueError('Unregistered portfolio construction')
    if predictions.select('symbol', 'trade_date').is_duplicated().any():
        raise ValueError('Duplicate frozen predictions')
    scores = predictions.join(universe, on=['symbol', 'trade_date'], how='left', validate='1:1')
    if scores['eligible'].null_count():
        raise ValueError('Missing point-in-time eligibility')
    scores = scores.filter(pl.col('eligible') & pl.col('lightgbm').is_finite()).sort(
        ['trade_date', 'lightgbm', 'symbol'], descending=[False, True, False])
    next_day = dict(zip(sessions, sessions[1:]))
    rows, ranks = [], []
    for (day,), frame in scores.partition_by('trade_date', as_dict=True, maintain_order=True).items():
        execution = next_day.get(day)
        if execution is None or execution > end:
            continue
        if frame.height < top_k:
            raise ValueError('Insufficient eligible names for registered K')
        for i, item in enumerate(frame.to_dicts(), 1):
            ranks.append(dict(as_of=day, symbol=item['symbol'], score=item['lightgbm'], rank=i,
                              selected=i <= top_k, execution_date=execution))
            if i <= top_k:
                rows.append(dict(as_of=day, execution_date=execution, symbol=item['symbol'],
                    strategy=f'personal_top{top_k}', strategy_version='v1', weight=(1-cash_buffer)/top_k))
    if not rows:
        raise ValueError('No executable frozen signals')
    return pl.from_dicts(rows), pl.from_dicts(ranks)


def fixed_orders(batch, state, controls, instruments, trace):
    day, execution = batch['as_of'][0], batch['execution_date'][0]
    if state.get('date') != str(day) or not state.get('nav'):
        raise ValueError('Quantity must use actual signal-close account')
    equity = state['nav'][-1]['equity']
    desired = dict(batch.select('symbol', 'weight').iter_rows())
    symbols = sorted(set(desired) | set(state['holdings']))
    rows, deltas, permissions = [], {}, {}
    exemplar = batch.row(0, named=True)
    for symbol in symbols:
        holding = state['holdings'].get(symbol, {})
        current = holding.get('quantity', 0)
        control = controls.get((day, symbol), {})
        price = control.get('close')
        valid = price is not None and math.isfinite(price) and price > 0
        weight = desired.get(symbol, 0.)
        step, minimum = (1, 200) if star(symbol) else (int(instruments[symbol]['board_lot']), int(instruments[symbol]['board_lot']))
        raw = equity*weight/price if valid else None
        desired_quantity = math.floor(raw/step)*step if raw is not None else current
        delta = desired_quantity-current
        if weight == 0:
            delta = -current  # Missing signal price must not invent a replacement mark.
        elif delta:
            delta = (1 if delta > 0 else -1)*(abs(delta)//step)*step
        if 0 < abs(delta) < minimum and not (delta < 0 and -delta == current):
            delta = 0
        known = bool(control.get('traded') and control.get('limits_known') and valid
                     and control.get('down_limit') and control.get('up_limit'))
        buy = bool(known and control.get('eligible') and control.get('away_from_limits'))
        sell = bool(known and price > control['down_limit'])
        deltas[symbol] = int(delta)
        permissions[symbol] = (buy, sell)
        rows.append({**exemplar, 'symbol': symbol, 'weight': weight})
        trace.append(dict(as_of=day, execution_date=execution, symbol=symbol,
            signal_equity=equity, signal_price=price, signal_price_complete=valid,
            desired_weight=weight, current_quantity=current, continuous_target_quantity=raw,
            requested_delta=int(delta), intended_quantity=current+delta, quantity_increment=step,
            minimum_order=minimum, lot_shortfall_value=(raw-current-delta)*price if valid else None,
            can_buy=buy, can_sell=sell, industry=control.get('industry_l1'),
            total_market_value=control.get('total_market_value'), amount20=control.get('amount20')))
    return pl.from_dicts(rows, schema=batch.schema), dict(feasible=True, applied=True,
        as_of=str(day), target_share_deltas=deltas, execution_direction_permissions=permissions)
