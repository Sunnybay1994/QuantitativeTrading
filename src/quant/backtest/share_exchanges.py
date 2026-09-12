"""Announced share exchanges in ordinary, unrestricted research accounts."""
from __future__ import annotations

import datetime as dt
from fractions import Fraction
import math
import re

import polars as pl


def validate_exchanges(events: list[dict]) -> list[dict]:
    seen = set()
    for event in events:
        old, new = event['from_symbol'], event['to_symbol']
        dates = [event[k] for k in ('announcement_date', 'record_date', 'effective_date', 'tradable_date')]
        if (not all(isinstance(s, str) and re.fullmatch(r'[0-9]{6}\.(SH|SZ)', s) for s in (old, new))
                or old == new or not all(type(d) is dt.date for d in dates)
                or not dates[0] <= dates[1] < dates[2] <= dates[3]
                or not isinstance(event['ratio'], str) or not re.fullmatch(r'\d+(\.\d{1,10})?', event['ratio'])
                or Fraction(event['ratio']) <= 0 or event['fractional_allocation'] not in {'floor', 'ceil'}):
            raise ValueError('Invalid share exchange terms')
        key = (old, dates[2])
        if key in seen:
            raise ValueError('Duplicate share exchange')
        seen.add(key)
    return events


def capture_exchange_holdings(*, date: dt.date, state: dict, events: list[dict]) -> None:
    for event in events:
        if event['record_date'] != date:
            continue
        holding = state['holdings'].get(event['from_symbol'], {})
        key = f"{event['from_symbol']}|{event['effective_date']}"
        state.setdefault('share_exchange_entitlements', {})[key] = holding.get('quantity', 0)


def apply_share_exchanges(*, date: dt.date, state: dict, events: list[dict], dividends: pl.DataFrame) -> list[dict]:
    """Convert record-date shares before delisting removal and scheduled trading.

    Carry predecessor book value until ordinary quote marking. This is not a
    cash payment or a fill. Exact integer allocation is a configured scenario.
    """
    applied = []
    for event in events:
        if event['effective_date'] != date:
            continue
        old, new = event['from_symbol'], event['to_symbol']
        key = f'{old}|{date}'
        entitlements = state.get('share_exchange_entitlements', {})
        holding = state['holdings'].get(old, {})
        quantity = holding.get('quantity', 0)
        entitled = entitlements.get(key)
        if entitled is None:
            if quantity:
                raise ValueError('Share exchange requires record-date holdings')
            continue
        if type(quantity) is not int or quantity < 0 or entitled != quantity:
            raise ValueError('Share exchange holding changed after record date')
        if not quantity:
            entitlements.pop(key)
            continue
        if any(r['symbol'] == old and r['quantity'] > 0 and r['list_date'] > str(date)
               for r in state.get('restricted_shares', [])):
            raise ValueError('Restricted predecessor requires its specific exchange terms')
        if dividends.filter((pl.col('ex_date') == date) & pl.col('symbol').is_in([old, new])).height:
            raise ValueError('Same-day dividend and exchange require explicit entitlement ordering')
        theoretical = quantity * Fraction(event['ratio'])
        added = (math.floor(theoretical) if event['fractional_allocation'] == 'floor' else math.ceil(theoretical))
        if added <= 0:
            raise ValueError('Exchange has no whole-share entitlement under this allocation')
        old_value = quantity * holding['mark_price']
        existing = state['holdings'].get(new, {'quantity': 0, 'mark_price': 0.})
        if (not math.isfinite(old_value) or old_value <= 0 or type(existing['quantity']) is not int
                or existing['quantity'] < 0 or not math.isfinite(existing['mark_price']) or existing['mark_price'] < 0):
            raise ValueError('Invalid share exchange holding value')
        total = existing['quantity'] + added
        mark = (old_value + existing['quantity'] * existing['mark_price']) / total
        state['holdings'].pop(old)
        state['holdings'][new] = {'quantity': total, 'mark_price': mark}
        entitlements.pop(key)
        if event['tradable_date'] > date:
            state.setdefault('restricted_shares', []).append(
                {'symbol': new, 'quantity': added, 'list_date': str(event['tradable_date'])})
        row = {'date': str(date), 'from_symbol': old, 'to_symbol': new, 'old_quantity': quantity,
            'new_quantity': added, 'theoretical_quantity': float(theoretical),
            'fractional_allocation': event['fractional_allocation'], 'predecessor_book_value': old_value,
            'tradable_date': str(event['tradable_date']), 'fee': 0.}
        state.setdefault('share_exchange_history', []).append(row)
        applied.append(row)
    return applied
