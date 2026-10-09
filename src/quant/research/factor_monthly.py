"""Carry completed-month liquidity observations onto the daily factor grid."""
import ast
import datetime as dt

import polars as pl

from quant.factors.calendar_liquidity import CALENDAR_LIQUIDITY_NAMES, compute_calendar_liquidity
from quant.factors.price_delay import PRICE_DELAY_NAMES, compute_price_delay, weekly_price_returns
from quant.factors.return_seasonality import SEASONALITY_NAMES, CONTROL_NAMES, compute_return_seasonality
from quant.factors.turnover_reference import NAMES as TURNOVER_NAMES, CONTROLS as TURNOVER_CONTROLS
from quant.factors.industry_information import SIGNALS as INDUSTRY_NAMES, CONTROL as INDUSTRY_CONTROL

from quant.factors.liquidity import (
    LIQUIDITY_FACTOR_NAMES, compute_monthly_amihud_illiquidity,
    compute_monthly_free_float_turnover_factors,
)


def monthly_input_names(expressions: tuple[str, ...]) -> tuple[str, ...]:
    fields = {node.id for expression in expressions
              for node in ast.walk(ast.parse(expression, mode="eval")) if isinstance(node, ast.Name)}
    return tuple(name for name in (*LIQUIDITY_FACTOR_NAMES, *CALENDAR_LIQUIDITY_NAMES, *PRICE_DELAY_NAMES,
        *SEASONALITY_NAMES, *TURNOVER_NAMES, *TURNOVER_CONTROLS, *INDUSTRY_NAMES, INDUSTRY_CONTROL) if name in fields)


def attach_monthly_factors(
    panel: pl.DataFrame, bars: pl.DataFrame, basic: pl.DataFrame,
    calendar: tuple[dt.date, ...], names: tuple[str, ...],
    *, price_delay_market: pl.DataFrame | None = None,
    seasonality_returns: pl.DataFrame | None = None,
    turnover_reference_values: pl.DataFrame | None = None,
    industry_information_values: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """Month-end is usable after that close; an invalid new month replaces the old value."""
    if not set(names) <= set((*LIQUIDITY_FACTOR_NAMES, *CALENDAR_LIQUIDITY_NAMES, *PRICE_DELAY_NAMES,
            *SEASONALITY_NAMES, *TURNOVER_NAMES, *TURNOVER_CONTROLS, *INDUSTRY_NAMES, INDUSTRY_CONTROL)):
        raise ValueError("Unknown monthly liquidity input")
    season_names=tuple(name for name in names if name in SEASONALITY_NAMES)
    if season_names:
        names=(*names,*CONTROL_NAMES)
    turnover_names = tuple(name for name in names if name in (*TURNOVER_NAMES, *TURNOVER_CONTROLS))
    if turnover_names:
        names = tuple(dict.fromkeys([*names, *TURNOVER_CONTROLS]))
    industry_names = tuple(name for name in names if name in (*INDUSTRY_NAMES, INDUSTRY_CONTROL))
    if industry_names:
        names = tuple(dict.fromkeys([*names, INDUSTRY_CONTROL]))
    if not calendar or calendar != tuple(sorted(set(calendar))):
        raise ValueError("Monthly factors require an ordered exchange calendar")
    low, high = panel["trade_date"].min(), panel["trade_date"].max()
    if not isinstance(low, dt.date) or not isinstance(high, dt.date):
        raise ValueError("Monthly factors require a dated non-empty panel")
    first_dates: dict[tuple[int, int], dt.date] = {}
    signal_dates = []
    for index, day in enumerate(calendar[:-1]):
        month = (day.year, day.month)
        first_dates.setdefault(month, day)
        following = calendar[index + 1]
        if (following.year, following.month) != month and first_dates[month] >= low and day <= high:
            signal_dates.append(day)
    if not signal_dates:
        return panel.with_columns(*[pl.lit(None, dtype=pl.Float64).alias(name) for name in names])
    signals = tuple(signal_dates)
    symbols = tuple(panel["symbol"].unique().sort().to_list())
    monthly = pl.DataFrame({"symbol": symbols}).join(
        pl.DataFrame({"trade_date": signals}), how="cross")
    if LIQUIDITY_FACTOR_NAMES[0] in names:
        amihud = compute_monthly_amihud_illiquidity(
            bars, sessions=calendar, signal_dates=signals, candidate_symbols=symbols)
        monthly = monthly.join(amihud.select("symbol", "trade_date", LIQUIDITY_FACTOR_NAMES[0]),
            on=["symbol", "trade_date"], how="left", validate="1:1")
    turnover = tuple(name for name in names if name in LIQUIDITY_FACTOR_NAMES[1:])
    if turnover:
        basic = basic.filter(pl.col("symbol").is_in(symbols)) if not basic.is_empty() else basic
        if basic.is_empty():
            monthly = monthly.with_columns(*[pl.lit(None, dtype=pl.Float64).alias(name) for name in turnover])
        else:
            values = compute_monthly_free_float_turnover_factors(
                basic, signal_dates=signals, candidate_symbols=symbols)
            monthly = monthly.join(values.select("symbol", "trade_date", *turnover),
                on=["symbol", "trade_date"], how="left", validate="1:1")
    calendar_names = tuple(name for name in names if name in CALENDAR_LIQUIDITY_NAMES)
    if calendar_names:
        values = compute_calendar_liquidity(bars=bars, basic=basic, sessions=calendar, signals=signals,
            symbols=symbols, names=calendar_names)
        monthly = monthly.join(values, on=['symbol', 'trade_date'], how='left', validate='1:1')
    delay_names = tuple(name for name in names if name in PRICE_DELAY_NAMES)
    if delay_names:
        if price_delay_market is None:
            raise ValueError('Price delay requires an explicit total-return market snapshot')
        stock_weeks, market_weeks, weeks = weekly_price_returns(bars, price_delay_market,
            sessions=tuple(day for day in calendar if low <= day <= high))
        values = compute_price_delay(stock_weeks, market_weeks, week_ends=weeks, signal_dates=signals)
        monthly = monthly.join(values.select('symbol', 'trade_date', *delay_names),
            on=['symbol', 'trade_date'], how='left', validate='1:1')
    if season_names:
        if seasonality_returns is None:
            raise ValueError('Seasonality requires full calendar-month return history')
        values=compute_return_seasonality(seasonality_returns,sessions=calendar,signal_dates=signals)
        monthly=monthly.join(values.select('symbol','trade_date',*season_names,*CONTROL_NAMES),
            on=['symbol','trade_date'],how='left',validate='1:1')
    if turnover_names:
        if turnover_reference_values is None:
            raise ValueError('Turnover-reference family requires complete fixed-window daily input')
        fields = tuple(dict.fromkeys([*turnover_names, *TURNOVER_CONTROLS]))
        monthly = monthly.join(turnover_reference_values.select('symbol', 'trade_date', *fields),
            on=['symbol', 'trade_date'], how='left', validate='1:1')
    if industry_names:
        if industry_information_values is None:
            raise ValueError('Industry information requires exact frozen-member monthly inputs')
        fields = tuple(dict.fromkeys([*industry_names, INDUSTRY_CONTROL]))
        monthly = monthly.join(industry_information_values.select('symbol', 'trade_date', *fields),
            on=['symbol', 'trade_date'], how='left', validate='1:1')
    result = panel.sort("symbol", "trade_date").join_asof(
        monthly.sort("symbol", "trade_date"), on="trade_date", by="symbol", strategy="backward",
        check_sortedness=False)
    return result.with_columns(*[
        pl.when(pl.col("close").is_not_null()).then(pl.col(name)).otherwise(None).alias(name)
        for name in names])
