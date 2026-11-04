"""Quoted limit matching; economic friction is applied separately by the cost model."""
import math
from collections.abc import Mapping


def validate(limits):
    if limits is None:
        return
    if not isinstance(limits,Mapping) or not limits:
        raise ValueError('Preposted limits must be a nonempty side-specific mapping')
    for key,price in limits.items():
        if (not isinstance(key,tuple) or len(key)!=2 or not isinstance(key[0],str)
            or not key[0] or key[1] not in ('BUY','SELL') or isinstance(price,bool)
            or not isinstance(price,(int,float)) or not math.isfinite(price) or price<=0):
            raise ValueError('Invalid preposted limit price')


def match(*, limits, symbol, side, opening, bar):
    if limits is None:
        return opening
    if (symbol,side) not in limits:
        raise ValueError(f'Missing preposted {side} limit for {symbol}')
    price=limits[symbol,side]
    # Opening executions must not depend on any later OHLC observations.
    if (side=='BUY' and opening<=price) or (side=='SELL' and opening>=price):
        return opening
    if bar is None:
        return None
    touched=bar['low']<=price if side=='BUY' else bar['high']>=price
    return price if touched else None
