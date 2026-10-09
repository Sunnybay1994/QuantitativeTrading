"""Fixed first-stage price-delay family, Hou & Moskowitz (2005), equations 1-4.

Local adaptation: monthly publication; 52 Wednesday weeks ending before the
signal month, four market lags, and at least 42 complete regression rows. The
paper's annual/two-stage portfolio estimates are NOT replicated by this kernel.
All three directions are positive. Coefficients stay signed; D2/D3 are not
clipped. These are signals, not return, admission or execution evidence.
"""

import bisect
import datetime as dt

import numpy as np
import polars as pl

WINDOW = 52
LAGS = 4
MINIMUM_WEEKS = 42  # ceil(80% of the fixed 52-calendar-week window)
NUMERICAL_EPSILON = 1e-12
PRICE_DELAY_NAMES = tuple(f"price_delay_d{i}_52w_skip1m" for i in (1, 2, 3))
OUTPUT_SCHEMA = {
    "symbol": pl.String, "trade_date": pl.Date,
    **dict.fromkeys(PRICE_DELAY_NAMES, pl.Float64),
    "window_start": pl.Date, "window_end": pl.Date,
    "valid_weeks": pl.Int64, "regression_status": pl.String,
    "d2_status": pl.String, "d3_status": pl.String,
    "r2_restricted": pl.Float64, "r2_full": pl.Float64,
    **dict.fromkeys((f"coefficient_{i}" for i in range(LAGS + 1)), pl.Float64),
    **dict.fromkeys((f"standard_error_{i}" for i in range(LAGS + 1)), pl.Float64),
}


def _dates(dates: tuple[dt.date, ...], name: str) -> None:
    if not dates or any(type(day) is not dt.date for day in dates):
        raise ValueError(f"{name} must contain date values")
    if dates != tuple(sorted(set(dates))):
        raise ValueError(f"{name} must be unique and increasing")


def _frame(frame: pl.DataFrame, keys: list[str], numeric: list[str]) -> None:
    if not set(keys + numeric) <= set(frame.columns):
        raise ValueError(f"Missing columns: {set(keys + numeric) - set(frame.columns)}")
    if frame.schema['trade_date'] != pl.Date:
        raise ValueError("trade_date must have Date dtype")
    if frame.select(pl.any_horizontal(pl.col(k).is_null() for k in keys).any()).item():
        raise ValueError("Missing observation keys")
    if frame.select(keys).is_duplicated().any():
        raise ValueError(f"Duplicate observation keys: {keys}")
    if any(not frame.schema[n].is_numeric() for n in numeric):
        raise ValueError("Returns/prices must be numeric")
    if 'symbol' in keys and (frame.schema['symbol'] != pl.String
                            or frame.filter(pl.col('symbol') == '').height):
        raise ValueError("Symbols must be nonempty strings")


def weekly_price_returns(
    bars: pl.DataFrame, market: pl.DataFrame, *, sessions: tuple[dt.date, ...],
) -> tuple[pl.DataFrame, pl.DataFrame, tuple[dt.date, ...]]:
    """Build a COMMON Wednesday grid, mapping holidays to the prior open session.

    bars: symbol/trade_date/close/adj_factor/volume; market: trade_date/index_level.
    Caller supplies an explicit total-return market version and the full exchange
    calendar, not a calendar inferred from observed quotes. Stock close*adj_factor
    is a supplied price proxy, not an independently audited cash wealth series.
    Both stock endpoints must exist and have positive price, factor and volume.
    A repeated holiday anchor has a missing weekly return; it never compresses
    the week grid. A missing quote is never filled from another stock date.
    """
    _dates(sessions, 'sessions')
    _frame(bars, ['symbol', 'trade_date'], ['close', 'adj_factor', 'volume'])
    _frame(market, ['trade_date'], ['index_level'])
    for frame in (bars, market):
        if not set(frame['trade_date'].to_list()) <= set(sessions):
            raise ValueError("Observation outside supplied exchange calendar")
    first = sessions[0] + dt.timedelta(days=(2 - sessions[0].weekday()) % 7)
    weeks = tuple(first + dt.timedelta(weeks=i)
                  for i in range((sessions[-1] - first).days // 7 + 1))
    if len(weeks) < 2:
        raise ValueError("At least two Wednesday anchors required")
    anchors = [sessions[bisect.bisect_right(sessions, week) - 1] for week in weeks]
    grid = pl.DataFrame({'trade_date': weeks, 'anchor': anchors}).with_columns(
        (pl.col('anchor') > pl.col('anchor').shift(1)).fill_null(False).alias('new_anchor'))
    index = grid.join(market.rename({'trade_date': 'anchor'}), on='anchor', how='left', validate='m:1')
    index = index.with_columns(pl.when(pl.col('index_level').is_finite() & (pl.col('index_level') > 0))
                               .then(pl.col('index_level')).otherwise(None).alias('level'))
    index = index.with_columns(pl.when(pl.col('new_anchor'))
        .then(pl.col('level') / pl.col('level').shift(1) - 1).otherwise(None).alias('market_return'))
    symbols = bars['symbol'].unique().sort()
    stocks = pl.DataFrame({'symbol': symbols}).join(grid, how='cross').join(
        bars.rename({'trade_date': 'anchor'}), on=['symbol', 'anchor'], how='left', validate='m:1',
    ).sort('symbol', 'trade_date')
    valid = pl.all_horizontal(pl.col(n).is_finite() & (pl.col(n) > 0)
                              for n in ['close', 'adj_factor', 'volume'])
    stocks = stocks.with_columns(pl.when(valid).then(pl.col('close') * pl.col('adj_factor'))
                                 .otherwise(None).alias('level'))
    stocks = stocks.with_columns(pl.when(pl.col('new_anchor'))
        .then(pl.col('level') / pl.col('level').shift(1).over('symbol') - 1)
        .otherwise(None).alias('stock_return'))
    return (stocks.select('symbol', 'trade_date', 'stock_return'),
            index.select('trade_date', 'market_return'), weeks)


def _ratio(numerator: float, terms: np.ndarray) -> float | None:
    denominator = float(terms.sum())
    if abs(denominator) <= NUMERICAL_EPSILON * max(1., float(np.abs(terms).sum())):
        return None
    result = float(numerator / denominator)
    return result if np.isfinite(result) else None


def compute_price_delay(
    stocks: pl.DataFrame, market: pl.DataFrame, *,
    week_ends: tuple[dt.date, ...], signal_dates: tuple[dt.date, ...],
) -> pl.DataFrame:
    """Calculate all three measures on identical valid rows of a fixed week grid.

    Signal dates are completed exchange month ends, supplied/validated by caller.
    Exclude the entire signal month: e.g. Jan31 uses weeks ending <= Dec31.
    Missing weeks stay in place before lagging; full/restricted OLS use the same
    stock/market-valid cohort. No market precoverage is invented. Invalid signals
    are explicit null rows, so the caller must replace rather than forward-fill
    the preceding month's signal. Publication is after signal-date close only.
    """
    _dates(week_ends, 'week_ends')
    _dates(signal_dates, 'signal_dates')
    if any(day.weekday() != 2 for day in week_ends) or any(
        b - a != dt.timedelta(days=7) for a, b in zip(week_ends, week_ends[1:])
    ):
        raise ValueError("week_ends must be contiguous calendar Wednesdays")
    if len({(day.year, day.month) for day in signal_dates}) != len(signal_dates):
        raise ValueError("At most one signal per calendar month")
    for frame, keys, numeric in [(stocks, ['symbol', 'trade_date'], ['stock_return']),
                                  (market, ['trade_date'], ['market_return'])]:
        _frame(frame, keys, numeric)
        if not set(frame['trade_date'].to_list()) <= set(week_ends):
            raise ValueError("Observation outside supplied Wednesday grid")
    if stocks.is_empty():
        return pl.DataFrame(schema=OUTPUT_SCHEMA)
    grid = pl.DataFrame({'trade_date': week_ends})
    m = grid.join(market, on='trade_date', how='left', validate='1:1')['market_return'].to_numpy()
    m = m.astype(float)
    m[~np.isfinite(m) | (m < -1)] = np.nan
    x = np.full((len(week_ends), LAGS + 2), np.nan)
    x[:, 0], x[:, 1] = 1., m
    for lag in range(1, LAGS + 1):
        x[lag:, lag + 1] = m[:-lag]
    windows = []
    for signal in signal_dates:
        cutoff = signal.replace(day=1) - dt.timedelta(days=1)
        end = bisect.bisect_right(week_ends, cutoff)
        start = max(0, end - WINDOW)
        windows.append((signal, start, end))
    output = []
    for (symbol,), frame in stocks.group_by('symbol', maintain_order=True):
        y_all = grid.join(frame.select('trade_date', 'stock_return'), on='trade_date',
                          how='left', validate='1:1')['stock_return'].to_numpy().astype(float)
        for signal, start, end in windows:
            row = dict.fromkeys(OUTPUT_SCHEMA)
            row.update(symbol=symbol, trade_date=signal, valid_weeks=0,
                       regression_status='insufficient_history', d2_status='not_estimated',
                       d3_status='not_estimated',
                       window_start=week_ends[start] if start < end else None,
                       window_end=week_ends[end - 1] if end else None)
            a, y = x[start:end], y_all[start:end]
            valid = np.isfinite(a).all(axis=1) & np.isfinite(y) & (y >= -1)
            row['valid_weeks'] = int(valid.sum())
            output.append(row)
            if end < WINDOW + LAGS:
                continue
            if valid.sum() < MINIMUM_WEEKS:
                row['regression_status'] = 'insufficient_valid_weeks'
                continue
            a, y = a[valid], y[valid]
            coefficients, _, rank, _ = np.linalg.lstsq(a, y, rcond=None)
            if rank != LAGS + 2:
                row['regression_status'] = 'rank_deficient'
                continue
            tss = float(np.sum((y - y.mean()) ** 2))
            if tss <= NUMERICAL_EPSILON ** 2 * len(y):
                row['regression_status'] = 'constant_stock_return'
                continue
            residuals = y - a @ coefficients
            sse = float(residuals @ residuals)
            restricted = a[:, :2]
            restricted_residuals = y - restricted @ np.linalg.lstsq(restricted, y, rcond=None)[0]
            r2_full = 1. - sse / tss
            r2_restricted = 1. - float(restricted_residuals @ restricted_residuals) / tss
            row.update(regression_status='ok', r2_full=r2_full, r2_restricted=r2_restricted)
            if r2_full > NUMERICAL_EPSILON:
                d1 = 1. - r2_restricted / r2_full
                # Nested OLS mathematically bounds D1; clip only roundoff at the endpoints.
                row[PRICE_DELAY_NAMES[0]] = float(np.clip(d1, 0., 1.))
            else:
                row['regression_status'] = 'zero_explained_variation'
            slopes = coefficients[1:]
            for i, value in enumerate(slopes):
                row[f'coefficient_{i}'] = float(value)
            weights = np.arange(LAGS + 1)
            row[PRICE_DELAY_NAMES[1]] = _ratio(float(weights @ slopes), slopes)
            row['d2_status'] = 'ok' if row[PRICE_DELAY_NAMES[1]] is not None else 'zero_denominator'
            if sse <= NUMERICAL_EPSILON ** 2 * len(y):
                row['d3_status'] = 'zero_residual_variance'
                continue
            _, triangular = np.linalg.qr(a, mode='reduced')
            inverse = np.linalg.solve(triangular, np.eye(LAGS + 2))
            se = np.sqrt(sse / (len(y) - (LAGS + 2)) * (inverse * inverse).sum(axis=1))[1:]
            for i, value in enumerate(se):
                row[f'standard_error_{i}'] = float(value)
            if not np.isfinite(se).all() or (se <= 0).any():
                row['d3_status'] = 'invalid_standard_error'
                continue
            tvalues = slopes / se
            row[PRICE_DELAY_NAMES[2]] = _ratio(float(weights @ tvalues), tvalues)
            row['d3_status'] = 'ok' if row[PRICE_DELAY_NAMES[2]] is not None else 'zero_denominator'
    return pl.DataFrame(output, schema=OUTPUT_SCHEMA).sort('symbol', 'trade_date')
