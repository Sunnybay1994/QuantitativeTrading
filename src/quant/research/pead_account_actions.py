"""Experiment-local PEAD corporate actions; no shared engine configuration changes.

The 000522 same-day record/conversion uses opening holdings because that stock
is suspended throughout the day. Newly issued shares remain a separate book-value
entitlement until the explicitly assumed successful initial-registration listing.
"""

from __future__ import annotations

import datetime as dt
from fractions import Fraction
import math

import polars as pl

from quant.backtest.share_exchanges import apply_share_exchanges, validate_exchanges


def validate_actions(events: list[dict]) -> tuple[list[dict], list[dict]]:
    ordinary, same_day = [], []
    for event in events:
        if event['record_date'] != event['effective_date']:
            ordinary.append(event)
            continue
        if not (
            event['from_symbol'] == '000522.SZ' and event['to_symbol'] == '600332.SH'
            and event['ratio'] == '0.95'
            and event['announcement_date'] <= event['record_date'] < event['tradable_date']
            and event['record_capture'] == 'opening_holdings_same_day_suspended'
            and event['valuation_until_tradable'] == 'predecessor_book_value'
            and event['account_registration_assumption'] == 'normal_account_confirmed_initial_registration'
            and event['fractional_allocation'] == 'floor'
        ):
            raise ValueError('Unregistered same-day share-exchange assumptions')
        same_day.append(event)
    keys = [(event['from_symbol'], event['effective_date']) for event in events]
    if len(set(keys)) != len(keys):
        raise ValueError('Duplicate share exchange')
    return validate_exchanges(ordinary), same_day


def occupied_symbols(state: dict) -> set[str]:
    result = {s for s, h in state['holdings'].items() if h['quantity'] > 0}
    result.update(row['to_symbol'] for row in state.get('pead_exchange_pending', []))
    # An already captured share-distribution entitlement can re-create shares
    # after a sale. Retain its original expiry and do not open a second signal.
    result.update(key.split('|')[0] for key, value in
                  state.get('share_distribution_entitlements', {}).items() if value['quantity'] > 0)
    return result


def _merge_books(state: dict, old: str, new: str, *, destination_occupied: bool) -> None:
    books = state.setdefault('pead_books', {})
    source = books.pop(old, None)
    if source is None:
        raise ValueError(f'Missing PEAD lineage for converted holding: {old}')
    existing = books.get(new) if destination_occupied else None
    if existing is None:
        books[new] = source
    else:
        existing['expiry_date'] = min(existing['expiry_date'], source['expiry_date'])
        existing['event_keys'] = sorted(set(existing['event_keys'] + source['event_keys']))


def apply_actions(*, date: dt.date, state: dict, ordinary: list[dict], same_day: list[dict],
                  dividends: pl.DataFrame, stopped: set[tuple[dt.date, str]],
                  positive_bar_symbols: set[str]) -> list[dict]:
    rows = []
    pending = state.setdefault('pead_exchange_pending', [])
    for item in list(pending):
        if date < dt.date.fromisoformat(item['tradable_date']):
            if dividends.filter(
                (pl.col('symbol') == item['to_symbol'])
                & ((pl.col('ex_date') == date) | (pl.col('record_date') == date))
            ).height:
                raise ValueError('Pending exchanged shares require explicit dividend-entitlement treatment')
            continue
        symbol, added = item['to_symbol'], item['quantity']
        existing = state['holdings'].get(symbol, {'quantity': 0, 'mark_price': 0.})
        total = existing['quantity'] + added
        value = existing['quantity'] * existing['mark_price'] + item['book_value']
        state['holdings'][symbol] = {'quantity': total, 'mark_price': value / total}
        pending.remove(item)
        rows.append({'date': str(date), 'action': 'EXCHANGE_SHARES_DELIVERED',
                     'symbol': symbol, 'quantity': added, 'book_value': item['book_value']})

    for event in same_day:
        if event['effective_date'] != date:
            continue
        old, new = event['from_symbol'], event['to_symbol']
        holding = state['holdings'].get(old)
        if not holding:
            continue
        if old in positive_bar_symbols and (date, old) not in stopped:
            raise ValueError('Same-day exchange requires whole-day suspended predecessor')
        if any(row['symbol'] == old and row['quantity'] > 0
               for row in state.get('restricted_shares', [])):
            raise ValueError('Restricted predecessor requires separate exchange terms')
        if dividends.filter((pl.col('ex_date') == date) & pl.col('symbol').is_in([old, new])).height:
            raise ValueError('Same-day dividend/exchange ordering not supported')
        quantity = math.floor(holding['quantity'] * Fraction(event['ratio']))
        if quantity <= 0:
            raise ValueError('No whole exchanged share under registered floor assumption')
        value = holding['quantity'] * holding['mark_price']
        _merge_books(state, old, new, destination_occupied=new in occupied_symbols(state))
        item = {'from_symbol': old, 'to_symbol': new, 'quantity': quantity,
                'book_value': value, 'tradable_date': str(event['tradable_date']),
                'record_date': str(date), 'fractional_allocation': 'floor'}
        pending.append(item)
        state['holdings'].pop(old)
        rows.append({'date': str(date), 'action': 'EXCHANGE_ENTITLEMENT_CREATED',
                     'symbol': new, 'quantity': quantity, 'book_value': value})

    prior_occupied = occupied_symbols(state)
    converted = apply_share_exchanges(date=date, state=state, events=ordinary, dividends=dividends)
    for row in converted:
        _merge_books(state, row['from_symbol'], row['to_symbol'],
                     destination_occupied=row['to_symbol'] in prior_occupied)
        rows.append({**row, 'action': 'SHARE_EXCHANGE'})
    state.setdefault('pead_action_history', []).extend(rows)
    return rows


def pending_value(state: dict) -> float:
    return sum(row['book_value'] for row in state.get('pead_exchange_pending', []))


def augment_positions(*, positions: pl.DataFrame, state: dict, date: dt.date, strategy: str) -> pl.DataFrame:
    """Publish one row per symbol including non-tradable book-value entitlement."""
    rows = {row['symbol']: {**row, 'exchange_pending_quantity': 0,
                           'exchange_pending_value': 0.} for row in positions.to_dicts()}
    for item in state.get('pead_exchange_pending', []):
        symbol = item['to_symbol']
        row = rows.setdefault(symbol, dict(strategy=strategy, date=date, symbol=symbol,
            quantity=0, settled_quantity=0, unsettled_quantity=0, mark_price=0.,
            market_value=0., target_weight=None, exchange_pending_quantity=0,
            exchange_pending_value=0.))
        row['quantity'] += item['quantity']
        row['unsettled_quantity'] += item['quantity']
        row['market_value'] += item['book_value']
        row['exchange_pending_quantity'] += item['quantity']
        row['exchange_pending_value'] += item['book_value']
        row['mark_price'] = row['market_value'] / row['quantity']
    if not rows:
        return positions.with_columns(pl.lit(0).cast(pl.Int64).alias('exchange_pending_quantity'),
                                      pl.lit(0.).alias('exchange_pending_value'))
    return pl.from_dicts(list(rows.values()), schema={**positions.schema,
        'exchange_pending_quantity': pl.Int64, 'exchange_pending_value': pl.Float64}).sort('symbol')
