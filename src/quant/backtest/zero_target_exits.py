"""Persistent complete exits; fixed sell orders never liquidate other holdings."""
import datetime as dt
import polars as pl

from quant.backtest.daily_account import prepare_account_actions


def update_exit_targets(*, state: dict, targets: pl.DataFrame | None, exchanges: list[dict]) -> dict:
    weights = dict(state.get('latest_monthly_weights', {}))
    if targets is not None:
        weights = dict(targets.select('symbol', 'weight').iter_rows())
    for event in exchanges:
        old, new = event['from_symbol'], event['to_symbol']
        if weights.get(old, 0.) > 0:
            raise ValueError('Positive predecessor target requires explicit exchange mapping')
        weights.pop(old, None)
        # A currently positive successor target overrides predecessor exit.
        weights.setdefault(new, 0.)
    return weights


def exit_orders(*, date: dt.date, state: dict, weights: dict, calendar: pl.DataFrame,
                dividends: pl.DataFrame) -> pl.DataFrame | None:
    prepared = prepare_account_actions(date=date, state=state, calendar=calendar, dividends=dividends)
    rows = []
    for symbol, holding in prepared['holdings'].items():
        if weights.get(symbol, 0.) > 0 or not holding['quantity']:
            continue
        restricted = sum(r['quantity'] for r in prepared['restricted_shares'] if r['symbol'] == symbol)
        available = holding['quantity'] - restricted
        # An odd-lot partial sale is invalid. Retain remainder until fully sellable.
        quantity = available if available == holding['quantity'] else available // 100 * 100
        if quantity > 0:
            rows.append({'as_of': dt.date.fromisoformat(state['date']), 'execution_date': date,
                         'symbol': symbol, 'side': 'SELL', 'quantity': quantity})
    return pl.from_dicts(rows) if rows else None


def exit_exposure(state: dict, weights: dict) -> float:
    equity = state['nav'][-1]['equity']
    return sum(h['quantity']*h['mark_price'] for s, h in state['holdings'].items()
               if weights.get(s, 0.) == 0) / equity if equity > 0 else 0.
