"""Raw daily inputs for the fixed liquidity co-movement family.

Read all observed stocks, one year at a time. Never read candidate factor caches,
future-return labels or a current survivor list to form the historical market.
"""
import datetime as dt
from pathlib import Path
import tomllib

import polars as pl

from quant.data.refresh_stocks import read_stock_data
from quant.factors.calendar_liquidity import CALENDAR_LIQUIDITY_NAMES, compute_calendar_liquidity
from quant.factors.liquidity_comovement import (
    CONTROLS, MARKET_SCHEMA, MIN_COVERAGE, MIN_MEMBERS, MIN_MONTHS, SCHEMA,
    SIGNALS, WINDOW, _calendar, compute_liquidity_comovement,
)
from quant.factors.return_seasonality import calendar_month_returns

DEFINITION = Path('configs/research/liquidity_comovement_family_v1.toml')
MONTHLY_SCHEMA = {'symbol': pl.String, 'trade_date': pl.Date,
                  'illiquidity': pl.Float64, 'monthly_return': pl.Float64}


def _validate_definition(path: Path) -> None:
    spec = tomllib.loads(path.read_text(encoding='utf-8'))
    expected = {'family': 'liquidity_comovement_logchange_60m_v1',
                'signals': list(SIGNALS), 'matched_controls': list(CONTROLS),
                'directions': [1, -1, -1], 'formation_months': WINDOW,
                'minimum_joint_months': MIN_MONTHS, 'minimum_market_members': MIN_MEMBERS,
                'minimum_market_coverage': MIN_COVERAGE, 'auto_trade': False}
    if any(spec.get(key) != value for key, value in expected.items()):
        raise ValueError('Liquidity co-movement definition does not match the fixed kernel')


def read_liquidity_comovement(*, data_root: Path, refresh_config: Path,
                             calendar: tuple[dt.date, ...], start: dt.date, end: dt.date,
                             definition: Path = DEFINITION) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    """Return signals/controls, market diagnostics and exact monthly kernel inputs.

    A 60-month exposure window needs 61 monthly liquidity levels. Its earliest
    liquidity month additionally needs the preceding exchange close to compute
    the first daily return. Every year boundary gets that same one-session
    overlap. Missing quotes and suspended endpoints never forward fill.

    A short supplied history produces the kernel's insufficient-history result;
    a query with no completed monthly anchor returns typed empty frames. The
    caller supplies the full exchange calendar, including the next session.
    """
    _validate_definition(definition)
    if type(start) is not dt.date or type(end) is not dt.date or start > end:
        raise ValueError('Invalid liquidity co-movement date range')
    anchors = _calendar(calendar)
    wanted = tuple(d for d in anchors if start <= d <= end)
    if not wanted:
        return pl.DataFrame(schema=SCHEMA), pl.DataFrame(schema=MARKET_SCHEMA), pl.DataFrame(schema=MONTHLY_SCHEMA)
    first_index = anchors.index(wanted[0])
    months = tuple(d for d in anchors[max(0, first_index-WINDOW):] if d <= wanted[-1])
    monthly_parts, endpoints = [], []
    first_read_session = None
    all_anchor_dates = set(anchors)
    for year in range(months[0].year, months[-1].year+1):
        year_months = tuple(d for d in months if d.year == year)
        low = year_months[0].replace(day=1)
        first_session = next((i for i, d in enumerate(calendar) if d >= low), None)
        if first_session is None:
            raise ValueError('Missing exchange sessions for requested liquidity month')
        read_start = calendar[max(0, first_session-1)]
        if first_read_session is None:
            first_read_session = read_start
        bars = read_stock_data(data_root=data_root, config=refresh_config, table='bar_1d',
                               start=read_start, end=year_months[-1])
        if bars.is_empty():
            continue
        if bars.filter(~pl.col('trade_date').is_in(calendar)).height:
            raise ValueError('Daily liquidity input outside supplied exchange calendar')
        if bars.filter(~pl.col('trade_date').is_between(read_start, year_months[-1])).height:
            raise ValueError('Daily liquidity reader exceeded requested date range')
        symbols = tuple(bars['symbol'].unique().sort().to_list())
        values = compute_calendar_liquidity(bars=bars, basic=pl.DataFrame(), sessions=calendar,
            signals=year_months, symbols=symbols, names=(CALENDAR_LIQUIDITY_NAMES[0],))
        monthly_parts.append(values.select('symbol', 'trade_date',
            pl.col(CALENDAR_LIQUIDITY_NAMES[0]).alias('illiquidity')))
        endpoints.append(bars.filter(pl.col('trade_date').is_in(all_anchor_dates))
            .select('symbol', 'trade_date', 'close', 'adj_factor', 'volume'))
    if not monthly_parts:
        return pl.DataFrame(schema=SCHEMA), pl.DataFrame(schema=MARKET_SCHEMA), pl.DataFrame(schema=MONTHLY_SCHEMA)
    # One-session year overlaps can repeat an endpoint, but cannot disagree.
    prices = pl.concat(endpoints).unique()
    if prices.select('symbol', 'trade_date').is_duplicated().any():
        raise ValueError('Repeated year-boundary endpoints disagree')
    # The endpoint helper needs the leading close, not a dense grid stretching
    # back to the beginning of the project's entire calendar.
    price_calendar = tuple(d for d in calendar if d >= first_read_session)
    returns = calendar_month_returns(prices, sessions=price_calendar).filter(pl.col('trade_date').is_in(months))
    monthly = pl.concat(monthly_parts).join(returns, on=['symbol', 'trade_date'],
        how='full', coalesce=True, validate='1:1').select(*MONTHLY_SCHEMA).sort('symbol', 'trade_date')
    signals, market = compute_liquidity_comovement(monthly, sessions=calendar, signal_dates=wanted)
    return signals, market, monthly
