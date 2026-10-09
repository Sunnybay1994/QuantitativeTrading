"""Opt-in, fractional-index share exchanges with explicit nontradable claims.

Original indexes keep their original index_day. This wrapper is used only by
versioned benchmark measurement repairs, not strategy execution.
"""
from __future__ import annotations

import copy
import datetime as dt
from fractions import Fraction
import math

from quant.data.equal_weight_index import index_day


def validate_exchanges(exchanges: list[dict]) -> None:
    keys = []
    for e in exchanges:
        keys.append(e['from_symbol'])
        if (e['from_symbol'] == e['to_symbol'] or float(Fraction(e['ratio'])) <= 0
                or e['announcement_date'] > e['effective_date']):
            raise ValueError('Invalid or future-known exchange terms')
        if not e['listing_notices']:
            raise ValueError('Require explicit listing evidence')
        for notice in e['listing_notices']:
            if notice['available_date'] > notice['tradable_date']:
                raise ValueError('Listing evidence not available by asserted date')
    if len(keys) != len(set(keys)):
        raise ValueError('Duplicate predecessor exchange')


def action_index_day(*, date: dt.date, state: dict, quotes: dict, actions: dict,
                     delisted: dict, stopped: set, targets: dict | None,
                     exchanges: list[dict]) -> tuple[dict, dict, list[dict]]:
    """Retain pending units through monthly resets; value successors only when known.

Pending book values and successor units use absolute index points. A change of
index scale changes both together, with no effect on returns or target weights.
"""
    working = copy.deepcopy(state)
    weights = working.setdefault('weights', {})
    last = working.setdefault('last', {})
    pending = working.setdefault('pending_claims', {})
    nav = working.get('level', 1000.)
    events = []
    for e in exchanges:
        old = e['from_symbol']
        if date != e['effective_date'] or weights.get(old, 0.) <= 0:
            continue
        if e['announcement_date'] > date:
            raise ValueError('Exchange terms not available')
        if old in actions or e['to_symbol'] in actions:
            raise ValueError('Conversion-date distribution needs explicit ordering')
        ratio = float(Fraction(e['ratio']))
        weight = weights.pop(old)
        mark = last.pop(old)
        claim = '@exchange:' + old
        if claim in pending:
            raise ValueError('Duplicate live claim')
        book = weight * nav
        units = book / mark * ratio
        pending[claim] = dict(from_symbol=old, to_symbol=e['to_symbol'], units=units,
                              book_value=book, recognized_date=date,
                              listing_notices=e['listing_notices'])
        weights[claim], last[claim] = weight, 1.
        events.append(dict(date=date, symbol=old, kind='exchange_claim_recognized',
                           to_symbol=e['to_symbol'], prior_weight=weight,
                           prior_mark=mark, ratio=ratio, successor_units=units,
                           book_value=book, value_before=book, value_after=book))
    for claim, item in list(pending.items()):
        successor = item['to_symbol']
        if successor in actions:
            raise ValueError('Pending successor dividend needs explicit entitlement treatment')
        known = [n for n in item['listing_notices'] if n['available_date'] <= date]
        notice = max(known, key=lambda n: n['available_date']) if known else None
        quote = quotes.get(successor)
        eligible = notice is not None and notice['tradable_date'] <= date
        valid_quote = (quote is not None and quote['volume'] > 0 and
                       all(math.isfinite(quote[k]) and quote[k] > 0 for k in ('open', 'close')))
        if not (eligible and valid_quote):
            continue
        claim_value = weights.pop(claim) * nav
        if not math.isclose(claim_value, item['book_value'], rel_tol=1e-10, abs_tol=1e-10):
            raise ValueError('Pending entitlement book value drifted')
        last.pop(claim)
        existing_value = weights.get(successor, 0.) * nav
        existing_units = existing_value / last[successor] if existing_value else 0.
        total_units = existing_units + item['units']
        weights[successor] = (existing_value + claim_value) / nav
        last[successor] = (existing_value + claim_value) / total_units
        pending.pop(claim)
        events.append(dict(date=date, symbol=item['from_symbol'], to_symbol=successor,
                           kind='exchange_claim_released', successor_units=item['units'],
                           existing_successor_units=existing_units, merged_successor_units=total_units,
                           book_value=claim_value, value_before=existing_value + claim_value,
                           value_after=last[successor] * total_units,
                           notice_available_date=notice['available_date']))
    synthetic = dict(quotes)
    for claim in pending:
        synthetic[claim] = dict(open=1., close=1., volume=1.)
    requested = targets
    if targets is not None and pending:
        _, trial, _ = index_day(date=date, state=working, quotes=synthetic,
                                 actions=actions, delisted=delisted, stopped=stopped, targets=None)
        opening = trial['opening_index_level']
        books = sum(p['book_value'] for p in pending.values())
        liquid = opening - books
        if liquid < -1e-8:
            raise ValueError('Pending claim exceeds opening capital')
        scale = max(liquid, 0.) / opening
        requested = {s: {**r, 'weight': r['weight'] * scale} for s, r in targets.items()}
        requested.update({s: dict(weight=p['book_value'] / opening, signal_close=1.) for s, p in pending.items()})
        events.append(dict(date=date, symbol='@pending', kind='pending_claim_rebalance',
                           book_value=books, liquid_opening_capital=liquid,
                           value_before=opening, value_after=books + liquid))
    new, row, ordinary = index_day(date=date, state=working, quotes=synthetic, actions=actions,
                                   delisted=delisted, stopped=stopped, targets=requested)
    new['pending_claims'] = pending
    books = sum(p['book_value'] for p in pending.values())
    for claim, item in pending.items():
        if not math.isclose(new['weights'].get(claim, 0.) * new['level'], item['book_value'],
                            rel_tol=1e-10, abs_tol=1e-10):
            raise ValueError('Rebalance changed pending units/value')
    row.update(pending_claim_value=books, pending_claim_weight=books / new['level'],
               pending_claim_count=len(pending))
    return new, row, events + ordinary
