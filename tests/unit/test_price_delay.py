import datetime as dt

import numpy as np
import polars as pl
import pytest
from polars.testing import assert_frame_equal

from quant.factors.price_delay import (
    MINIMUM_WEEKS, PRICE_DELAY_NAMES, WINDOW, compute_price_delay, weekly_price_returns,
)


def fixture():
    dates = tuple(dt.date(2018, 1, 3) + dt.timedelta(weeks=i) for i in range(170))
    rng = np.random.default_rng(42)
    m = rng.normal(0, .03, len(dates))
    predictors = np.column_stack([np.roll(m, i) for i in range(5)])
    y = .004 + predictors @ np.array([.8, .3, -.1, .2, .15]) + rng.normal(0, .02, len(m))
    stocks = pl.DataFrame({'symbol': ['A'] * len(m), 'trade_date': dates, 'stock_return': y})
    market = pl.DataFrame({'trade_date': dates, 'market_return': m})
    signals = (dt.date(2020, 11, 30), dt.date(2020, 12, 31), dt.date(2021, 1, 29))
    return stocks, market, dates, signals


def run(stocks, market, dates, signals):
    return compute_price_delay(stocks, market, week_ends=dates, signal_dates=signals)


def oracle(stocks, market, dates, signal):
    cutoff = signal.replace(day=1) - dt.timedelta(days=1)
    selected = [i for i, day in enumerate(dates) if day <= cutoff][-52:]
    m = {r['trade_date']: r['market_return'] for r in market.to_dicts()}
    s = {r['trade_date']: r['stock_return'] for r in stocks.to_dicts()}
    observations = []
    for i in selected:
        values = [s.get(dates[i]), *[m.get(dates[i-j]) for j in range(5)]]
        if all(v is not None and np.isfinite(v) and v >= -1 for v in values):
            observations.append(values)
    data = np.array(observations)
    y = data[:, 0]
    a = np.column_stack([np.ones(len(y)), data[:, 1:]])
    # Separate normal-equation/projection calculation, not production lstsq/QR.
    inverse = np.linalg.inv(a.T @ a)
    coefficients = inverse @ a.T @ y
    residuals = y - a @ coefficients
    restricted = a[:, :2]
    residuals0 = y - restricted @ np.linalg.inv(restricted.T @ restricted) @ restricted.T @ y
    tss = ((y - y.mean()) ** 2).sum()
    r2, r20 = 1 - (residuals ** 2).sum() / tss, 1 - (residuals0 ** 2).sum() / tss
    slopes = coefficients[1:]
    se = np.sqrt((residuals ** 2).sum() / (len(y) - 6) * np.diag(inverse))[1:]
    t = slopes / se
    return [1-r20/r2, np.arange(5) @ slopes / slopes.sum(), np.arange(5) @ t / t.sum()], len(y)


def test_three_formulas_match_independent_regression_on_same_rows():
    stocks, market, dates, signals = fixture()
    result = run(stocks, market, dates, signals)
    for row in result.to_dicts():
        expected, count = oracle(stocks, market, dates, row['trade_date'])
        assert row['regression_status'] == 'ok'
        assert row['valid_weeks'] == count == WINDOW
        assert [row[n] for n in PRICE_DELAY_NAMES] == pytest.approx(expected, abs=1e-11)
        assert row['window_end'] < row['trade_date'].replace(day=1)


def test_missing_weeks_leave_lags_in_place_and_restricted_uses_identical_cohort():
    stocks, market, dates, signals = fixture()
    stocks = stocks.filter(pl.col('trade_date') != dates[134])
    market = market.filter(pl.col('trade_date') != dates[128])
    row = run(stocks, market, dates, signals).row(-1, named=True)
    expected, count = oracle(stocks, market, dates, signals[-1])
    assert row['valid_weeks'] == count == 46
    assert [row[n] for n in PRICE_DELAY_NAMES] == pytest.approx(expected, abs=1e-11)


def test_signal_month_and_future_changes_cannot_change_published_signals():
    stocks, market, dates, signals = fixture()
    cutoff = signals[1].replace(day=1) - dt.timedelta(days=1)
    baseline = run(stocks, market, dates, signals[:2])
    changed_s = stocks.with_columns(pl.when(pl.col('trade_date') > cutoff).then(.4)
                                    .otherwise(pl.col('stock_return')).alias('stock_return'))
    changed_m = market.with_columns(pl.when(pl.col('trade_date') > cutoff).then(-.6)
                                    .otherwise(pl.col('market_return')).alias('market_return'))
    assert_frame_equal(baseline, run(changed_s, changed_m, dates, signals[:2]))
    prefix = tuple(d for d in dates if d <= cutoff)
    assert_frame_equal(baseline, run(stocks.filter(pl.col('trade_date') <= cutoff),
        market.filter(pl.col('trade_date') <= cutoff), prefix, signals[:2]))


def test_absent_stock_retained_and_invalid_month_replaces_previous_signal():
    stocks, market, dates, signals = fixture()
    old = stocks.filter(pl.col('trade_date') <= dt.date(2020, 10, 1))
    row = run(old, market, dates, signals).row(-1, named=True)
    assert row['symbol'] == 'A'
    assert row['regression_status'] == 'insufficient_valid_weeks'
    assert row['valid_weeks'] < MINIMUM_WEEKS
    assert all(row[n] is None for n in PRICE_DELAY_NAMES)


@pytest.mark.parametrize('value', [None, float('nan'), float('inf'), -1.1])
def test_bad_stock_values_excluded_without_zero_fill(value):
    stocks, market, dates, signals = fixture()
    stocks = stocks.with_columns(pl.when(pl.col('trade_date').is_in(dates[119:135])).then(value)
                                    .otherwise(pl.col('stock_return')).alias('stock_return'))
    row = run(stocks, market, dates, signals).row(-1, named=True)
    assert row['valid_weeks'] == 36
    assert row['regression_status'] == 'insufficient_valid_weeks'


def test_market_precoverage_stays_missing_not_a_constant_return_proxy():
    stocks, market, dates, signals = fixture()
    early = run(stocks, market.tail(20), dates, signals)
    assert early.select(PRICE_DELAY_NAMES).null_count().row(0) == (3, 3, 3)


@pytest.mark.parametrize('constant', ['stock', 'market'])
def test_constant_or_singular_regressions_are_null(constant):
    stocks, market, dates, signals = fixture()
    if constant == 'stock':
        stocks = stocks.with_columns(pl.lit(.01).alias('stock_return'))
    else:
        market = market.with_columns(pl.lit(.01).alias('market_return'))
    row = run(stocks, market, dates, signals).row(-1, named=True)
    assert row['regression_status'] == ('constant_stock_return' if constant == 'stock' else 'rank_deficient')
    assert all(row[n] is None for n in PRICE_DELAY_NAMES)


def test_signed_d2_not_absolute_or_clipped_and_zero_standard_error_is_null():
    stocks, market, dates, signals = fixture()
    m = market['market_return'].to_numpy()
    slopes = np.array([1., -.6, .1, -.2, -.1])
    y = .003 + np.column_stack([np.roll(m, i) for i in range(5)]) @ slopes
    stocks = stocks.with_columns(pl.Series('stock_return', y))
    row = run(stocks, market, dates, signals).row(-1, named=True)
    assert row[PRICE_DELAY_NAMES[1]] == pytest.approx(-7.)
    assert row[PRICE_DELAY_NAMES[0]] is not None
    assert row[PRICE_DELAY_NAMES[2]] is None
    assert row['d3_status'] == 'zero_residual_variance'


def test_near_zero_signed_denominator_not_an_infinite_d2_score():
    stocks, market, dates, signals = fixture()
    m = market['market_return'].to_numpy()
    y = .003 + m - np.roll(m, 1)
    row = run(stocks.with_columns(pl.Series('stock_return', y)), market, dates, signals).row(-1, named=True)
    assert row[PRICE_DELAY_NAMES[1]] is None
    assert row['d2_status'] == 'zero_denominator'


@pytest.mark.parametrize('source', ['stocks', 'market'])
def test_duplicate_keys_rejected(source):
    stocks, market, dates, signals = fixture()
    if source == 'stocks':
        stocks = pl.concat([stocks, stocks.head(1)])
    else:
        market = pl.concat([market, market.head(1)])
    with pytest.raises(ValueError, match='Duplicate'):
        run(stocks, market, dates, signals)


def test_week_grid_must_not_compress_missing_calendar_weeks():
    stocks, market, dates, signals = fixture()
    with pytest.raises(ValueError, match='contiguous'):
        run(stocks, market, dates[:120] + dates[121:], signals)


def daily_fixture():
    days = tuple(dt.date(2020, 9, 21) + dt.timedelta(days=i) for i in range(36))
    sessions = tuple(d for d in days if d.weekday() < 5 and not dt.date(2020, 10, 1) <= d <= dt.date(2020, 10, 8))
    bars = pl.DataFrame({'symbol': ['A'] * len(sessions), 'trade_date': sessions,
        'close': np.arange(len(sessions), dtype=float)+10, 'adj_factor': [1.] * len(sessions),
        'volume': [100.] * len(sessions)})
    market = bars.select('trade_date', pl.col('close').alias('index_level'))
    return bars, market, sessions


def test_common_holiday_anchor_never_makes_a_fictitious_zero_week():
    bars, market, sessions = daily_fixture()
    stocks, index, weeks = weekly_price_returns(bars, market, sessions=sessions)
    assert all(b-a == dt.timedelta(days=7) for a, b in zip(weeks, weeks[1:]))
    holiday = dt.date(2020, 10, 7)
    assert stocks.filter(pl.col('trade_date') == holiday)['stock_return'].item() is None
    assert index.filter(pl.col('trade_date') == holiday)['market_return'].item() is None
    assert stocks.filter(pl.col('trade_date') == dt.date(2020, 10, 14))['stock_return'].item() is not None


@pytest.mark.parametrize('mode', ['missing', 'zero_volume', 'zero_adjustment'])
def test_stock_endpoint_missing_or_nontrading_never_filled_from_previous_quote(mode):
    bars, market, sessions = daily_fixture()
    missing = dt.date(2020, 9, 30)
    if mode == 'missing':
        bars = bars.filter(pl.col('trade_date') != missing)
    else:
        field = 'volume' if mode == 'zero_volume' else 'adj_factor'
        bars = bars.with_columns(pl.when(pl.col('trade_date') == missing).then(0.)
                                  .otherwise(pl.col(field)).alias(field))
    stocks, _, _ = weekly_price_returns(bars, market, sessions=sessions)
    for day in [missing, dt.date(2020, 10, 7), dt.date(2020, 10, 14)]:
        assert stocks.filter(pl.col('trade_date') == day)['stock_return'].item() is None


def test_duplicate_daily_prices_are_not_silently_selected():
    bars, market, sessions = daily_fixture()
    with pytest.raises(ValueError, match='Duplicate'):
        weekly_price_returns(pl.concat([bars, bars.head(1)]), market, sessions=sessions)
