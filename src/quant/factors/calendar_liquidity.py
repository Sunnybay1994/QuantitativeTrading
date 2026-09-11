"""New monthly liquidity definitions: 80% of exchange sessions, at least ten."""
import datetime as dt
import math
from collections import Counter

import polars as pl

from quant.factors.liquidity import (
    LIQUIDITY_FACTOR_NAMES, compute_monthly_amihud_illiquidity,
    compute_monthly_free_float_turnover_factors,
)


CALENDAR_LIQUIDITY_NAMES = tuple(name+'_calendar80_v1' for name in LIQUIDITY_FACTOR_NAMES)


def compute_calendar_liquidity(*, bars: pl.DataFrame, basic: pl.DataFrame,
                              sessions: tuple[dt.date, ...], signals: tuple[dt.date, ...],
                              symbols: tuple[str, ...], names: tuple[str, ...]) -> pl.DataFrame:
    """Keep the existing formulas, changing only the monthly observation threshold.

    Exchange sessions include holidays and suspension gaps correctly; the threshold
    never shrinks to the number of rows actually received for a particular stock.
    """
    if not names or not set(names) <= set(CALENDAR_LIQUIDITY_NAMES):
        raise ValueError('Unknown calendar liquidity input')
    counts = Counter((day.year, day.month) for day in sessions)
    thresholds = pl.DataFrame({'trade_date': signals,
        '_required': [max(10, math.ceil(.8*counts[(day.year, day.month)])) for day in signals]})
    result = pl.DataFrame({'symbol': symbols}).join(thresholds, how='cross')
    if CALENDAR_LIQUIDITY_NAMES[0] in names:
        values = compute_monthly_amihud_illiquidity(bars, sessions=sessions,
            signal_dates=signals, candidate_symbols=symbols, minimum_valid_days=1)
        result = result.join(values, on=['symbol', 'trade_date'], validate='1:1').with_columns(
            pl.when(pl.col('amihud_valid_days') >= pl.col('_required'))
            .then(pl.col(LIQUIDITY_FACTOR_NAMES[0])).alias(CALENDAR_LIQUIDITY_NAMES[0]))
    turnover_names = [name for name in names if name != CALENDAR_LIQUIDITY_NAMES[0]]
    if turnover_names:
        if not basic.is_empty():
            basic = basic.filter(pl.col('symbol').is_in(symbols))
        if basic.is_empty():
            result = result.with_columns(*[pl.lit(None, dtype=pl.Float64).alias(name) for name in turnover_names])
        else:
            values = compute_monthly_free_float_turnover_factors(basic, signal_dates=signals,
                candidate_symbols=symbols, minimum_valid_days=1)
            result = result.join(values, on=['symbol', 'trade_date'], validate='1:1').with_columns(
                pl.when(pl.col('free_float_turnover_valid_days') >= pl.col('_required'))
                .then(pl.col(LIQUIDITY_FACTOR_NAMES[1])).alias(CALENDAR_LIQUIDITY_NAMES[1]))
            # Rebuild the trailing baseline AFTER applying the new monthly threshold.
            result = result.sort('symbol', 'trade_date').with_columns(
                pl.col(CALENDAR_LIQUIDITY_NAMES[1]).shift(1).rolling_mean(12, min_samples=12)
                .over('symbol').alias('_prior12'))
            result = result.with_columns(pl.when(pl.col('_prior12') > 0)
                .then(pl.col(CALENDAR_LIQUIDITY_NAMES[1])/pl.col('_prior12')-1)
                .alias(CALENDAR_LIQUIDITY_NAMES[2]))
    return result.select('symbol', 'trade_date', *names)
