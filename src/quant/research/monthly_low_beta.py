"""Monthly low-beta observations from the existing complete-window market-risk estimator."""

import datetime as dt
from typing import Any

import polars as pl

from quant.factors.classic_market_risk import MARKET_BETA_CONTROL_NAME, compute_classic_market_risk_factors


def validate_low_beta(config: dict[str, Any]) -> None:
    expected = {'benchmark': '510300.SH', 'window_sessions': 60,
        'return_type': 'adjusted_close_log_return', 'benchmark_price': 'TOTAL_RETURN_DIVIDEND',
        'estimator': 'ols_with_intercept', 'minimum_market_variance': 1e-12,
        'missing_session': 'invalidate_window', 'signal_frequency': 'completed_month_end'}
    if (any(config.get('low_beta', {}).get(k) != v for k, v in expected.items())
        or config['factors']['names'] != [MARKET_BETA_CONTROL_NAME]
        or config['factors']['directions'] != [-1] or config['portfolio']['benchmark'] != '510300.SH'):
        raise ValueError('Low beta requires fixed 60-session OLS and negative monthly ranking')


def build_monthly_low_beta(
    stock_bars: pl.DataFrame, benchmark_bars: pl.DataFrame, benchmark_prices: pl.DataFrame,
    *, sessions: tuple[dt.date, ...], signal_dates: tuple[dt.date, ...],
) -> pl.DataFrame:
    """Adapt research-only benchmark factors while leaving execution OHLC untouched."""
    prices = benchmark_prices.filter(pl.col('adjustment_method') == 'TOTAL_RETURN_DIVIDEND').select(
        'symbol', 'trade_date', 'adjusted_close')
    research_benchmark = benchmark_bars.join(prices, on=['symbol', 'trade_date'], how='left', validate='1:1')
    if research_benchmark.filter(~pl.col('adjusted_close').is_finite().fill_null(False)
                                 | (pl.col('adjusted_close') <= 0)).height:
        raise ValueError('Incomplete total-return benchmark')
    research_benchmark = research_benchmark.with_columns(
        (pl.col('adjusted_close') / pl.col('close')).alias('adj_factor')).drop('adjusted_close')
    values = compute_classic_market_risk_factors(stock_bars, research_benchmark,
        sessions=sessions, benchmark_symbol='510300.SH', window_sessions=60,
        minimum_market_variance=1e-12)
    return values.filter(pl.col('trade_date').is_in(signal_dates)).select(
        'symbol', 'trade_date', MARKET_BETA_CONTROL_NAME)
