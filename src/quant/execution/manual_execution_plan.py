"""Indicative split-day quantities; execution-day prices must be supplied separately."""
import datetime as dt
import math

import polars as pl

SCHEMA = {'symbol': pl.String, 'side': pl.String, 'execution_date': pl.String,
    'day_number': pl.Int64, 'quantity': pl.Int64, 'estimated_participation': pl.Float64,
    'status': pl.String, 'reason': pl.String, 'price_rule': pl.String,
    'auto_trade': pl.Boolean}


def opening_band(*, opening: float, down_limit: float, up_limit: float,
                 tick: float = .01) -> tuple[float, float]:
    """Intersect opening ±1% with execution-day official limits, rounding inward."""
    if any(not math.isfinite(v) or v <= 0 for v in (opening, down_limit, up_limit, tick)):
        raise ValueError('Require finite positive execution-day prices')
    if not down_limit <= opening <= up_limit:
        raise ValueError('Opening outside official execution-day limits')
    low = math.ceil(max(opening*.99, down_limit)/tick-1e-10)*tick
    high = math.floor(min(opening*1.01, up_limit)/tick+1e-10)*tick
    if low > high:
        raise ValueError('No valid tick inside execution band')
    return round(low, 10), round(high, 10)


def build_plan(*, orders: pl.DataFrame, market: pl.DataFrame,
               sessions: list[dt.date], participation_rate: float) -> pl.DataFrame:
    """Plan at most three sessions without releasing, changing or executing orders."""
    if not math.isfinite(participation_rate) or not 0 < participation_rate <= 1:
        raise ValueError('Invalid participation rate')
    if sessions != sorted(set(sessions)) or market['symbol'].is_duplicated().any():
        raise ValueError('Require ordered unique sessions and unique market rows')
    data = {r['symbol']: r for r in market.iter_rows(named=True)}
    rows = []
    for symbol in sorted(set(orders['symbol'])):
        group = orders.filter(pl.col('symbol') == symbol)
        if group['side'].n_unique() != 1 or group['execution_date'].n_unique() != 1:
            raise ValueError('Conflicting orders for one symbol')
        side = group['side'][0]
        quantities = group['quantity'].to_list()
        prices = group['estimated_fill_price'].to_list()
        if side not in ('BUY', 'SELL') or any(type(q) is not int or q <= 0 for q in quantities):
            raise ValueError('Invalid side or quantity')
        if any(p is None or not math.isfinite(p) or p <= 0 for p in prices):
            raise ValueError('Invalid reference prices')
        first = dt.date.fromisoformat(str(group['execution_date'][0]))
        dates = [d for d in sessions if d >= first][:3]
        quantity = sum(quantities)
        info = data[symbol]
        lot, amount = info['board_lot'], info['average_amount']
        if type(lot) is not int or lot <= 0:
            raise ValueError('Invalid board lot')
        reason = ''
        cap = 0
        if amount is None or not math.isfinite(amount) or amount <= 0:
            reason = 'missing_liquidity'
        else:
            cap = math.floor(amount*participation_rate/max(prices)/lot)*lot
            if cap == 0:
                reason = 'less_than_one_lot_per_day'
        if side == 'BUY' and quantity % lot:
            reason = 'invalid_buy_lot'
        pieces: list[int] = []
        remaining = quantity
        if not reason:
            while remaining > 0 and len(pieces) < 3:
                part = min(cap, remaining)
                pieces.append(part)
                remaining -= part
            if remaining:
                reason = 'exceeds_three_day_capacity'
            elif len(dates) < len(pieces) or not dates or dates[0] != first:
                reason = 'missing_execution_calendar'
        if reason:
            rows.append({'symbol': symbol, 'side': side, 'quantity': quantity,
                'status': 'rejected', 'reason': reason, 'auto_trade': False})
            continue
        for index, part in enumerate(pieces):
            rows.append({'symbol': symbol, 'side': side, 'execution_date': str(dates[index]),
                'day_number': index+1, 'quantity': part,
                'estimated_participation': part*max(prices)/amount,
                'status': 'requires_daily_recheck',
                'reason': 'Recheck account cash, sellable shares, participation and market status each day',
                'price_rule': 'execution-day open * [0.99, 1.01], intersect official limits; round inward',
                'auto_trade': False})
    return pl.from_dicts(rows, schema=SCHEMA) if rows else pl.DataFrame(schema=SCHEMA)


def main() -> None:
    """Calculate a band from manually verified execution-day prices, without orders."""
    import argparse
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--opening', type=float, required=True)
    parser.add_argument('--down-limit', type=float, required=True)
    parser.add_argument('--up-limit', type=float, required=True)
    parser.add_argument('--tick', type=float, default=.01)
    args = parser.parse_args()
    lower, upper = opening_band(**vars(args))
    print(json.dumps({'lower': lower, 'upper': upper, 'auto_trade': False,
        'status': 'price_band_only', 'source': 'user_supplied_execution_day_prices'}))


if __name__ == '__main__':
    main()
