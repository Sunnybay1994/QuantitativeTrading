import datetime as dt

import numpy as np
import polars as pl
import pytest

from quant.factors.turnover_reference import (
    CONTROLS, NAMES, compute_turnover_reference, formation_dates,
)


@pytest.fixture
def data():
    dates = tuple(dt.date(2014, 1, 1) + dt.timedelta(days=i) for i in range(4383)
                  if (dt.date(2014, 1, 1) + dt.timedelta(days=i)).weekday() < 5)
    n = len(dates)
    bars = pl.DataFrame({'symbol': ['X.SH']*n, 'trade_date': dates,
                         'close': np.linspace(10., 45., n), 'adj_factor': np.ones(n),
                         'volume': 100. + 40.*np.sin(np.arange(n)/17.)})
    basic = bars.select('symbol', 'trade_date').with_columns(pl.lit(10000.).alias('total_shares'))
    return bars, basic, dates, (dt.date(2023, 12, 29),)


def compute(data):
    bars, basic, dates, signals = data
    return compute_turnover_reference(bars, basic, sessions=dates, signal_dates=signals)


def oracle(data):
    bars, basic, dates, signals = data
    start, end, interaction_start = formation_dates(signals[0])
    source = bars.join(basic, on=['symbol', 'trade_date']).filter(
        pl.col('trade_date').is_between(start, end)).sort('trade_date')
    num = den = 0.
    for r in source.iter_rows(named=True):
        h = r['volume']/r['total_shares']
        num = (1-h)*num + h*r['close']*r['adj_factor']
        den = (1-h)*den + h
    end_price = source['close'][-1]*source['adj_factor'][-1]
    gain = 1-num/den/end_price
    tail = source.filter(pl.col('trade_date') >= interaction_start)
    mean_h = (tail['volume']/tail['total_shares']).mean()
    return gain, gain*mean_h, den


def test_independent_forward_recurrence(data):
    r = compute(data).row(0, named=True)
    g, interaction, mass = oracle(data)
    assert r['status'] == 'valid'
    assert r[NAMES[0]] == pytest.approx(g, abs=2e-14)
    assert r[NAMES[1]] == pytest.approx(interaction, abs=2e-15)
    assert r['weight_mass'] == pytest.approx(mass, abs=2e-14)
    assert r['expected_sessions'] == r['valid_sessions'] == 1300


@pytest.mark.parametrize('signal, cutoff', [(dt.date(2025, 1, 31), dt.date(2025, 1, 24)),
                                           (dt.date(2025, 3, 31), dt.date(2025, 3, 21))])
def test_calendar_week_boundaries(signal, cutoff):
    start, end, short = formation_dates(signal)
    assert end == cutoff
    assert start.weekday() == 0
    assert (end-start).days == 259*7+4
    assert (end-short).days == 51*7+4


def test_split_invariance(data):
    b, s, dates, signals = data
    after = pl.col('trade_date') >= dt.date(2021, 6, 15)
    adjusted = b.with_columns(
        pl.when(after).then(pl.col('close')/2).otherwise(pl.col('close')).alias('close'),
        pl.when(after).then(pl.col('adj_factor')*2).otherwise(pl.col('adj_factor')).alias('adj_factor'),
        pl.when(after).then(pl.col('volume')*2).otherwise(pl.col('volume')).alias('volume'))
    shares = s.with_columns(pl.when(after).then(pl.col('total_shares')*2)
                           .otherwise(pl.col('total_shares')).alias('total_shares'))
    old = compute(data); new = compute((adjusted, shares, dates, signals))
    for name in NAMES+CONTROLS:
        assert new[name][0] == pytest.approx(old[name][0], abs=2e-14)
    assert new['reference_price_at_cutoff_basis'][0] == pytest.approx(old['reference_price_at_cutoff_basis'][0]/2)


def test_cash_dividend_proxy_is_not_unadjusted_purchase_cost(data):
    b, s, dates, signals = data
    after = pl.col('trade_date') >= dt.date(2021, 6, 15)
    b = b.with_columns(pl.when(after).then(19.).otherwise(20.).alias('close'),
                       pl.when(after).then(20./19.).otherwise(1.).alias('adj_factor'))
    r = compute((b, s, dates, signals))
    assert abs(r[NAMES[0]][0]) < 1e-14
    raw = compute((b.with_columns(pl.lit(1.).alias('adj_factor')), s, dates, signals))
    assert raw[NAMES[0]][0] < 0


def test_share_changes_use_contemporaneous_denominator(data):
    b, s, dates, signals = data
    s = s.with_columns(pl.when(pl.col('trade_date') >= dt.date(2021, 6, 15))
                       .then(17000.).otherwise(10000.).alias('total_shares'))
    r = compute((b, s, dates, signals)).row(0, named=True)
    g, interaction, _ = oracle((b, s, dates, signals))
    assert r['share_change_sessions'] == 1
    assert r[NAMES[0]] == pytest.approx(g, abs=2e-14)
    assert r[NAMES[1]] == pytest.approx(interaction, abs=2e-15)


def test_daily_turnover_one_resets_reference(data):
    b, s, dates, signals = data
    _, end, _ = formation_dates(signals[0])
    b = b.with_columns(pl.when(pl.col('trade_date') == end).then(10000.)
                       .otherwise(pl.col('volume')).alias('volume'))
    r = compute((b, s, dates, signals))
    assert r[NAMES[0]][0] == 0
    assert r['weight_mass'][0] == 1


@pytest.mark.parametrize('column,value', [('volume', -1.), ('volume', 10001.),
                                         ('close', 0.), ('adj_factor', float('inf')),
                                         ('total_shares', None)])
def test_invalid_observation_invalidates_whole_window(data, column, value):
    b, s, dates, signals = data
    target = dt.date(2020, 3, 2)
    expr = pl.when(pl.col('trade_date') == target).then(pl.lit(value)).otherwise(pl.col(column)).alias(column)
    if column == 'total_shares':
        s = s.with_columns(expr)
    else:
        b = b.with_columns(expr)
    r = compute((b, s, dates, signals))
    assert r['status'][0] == 'incomplete_or_invalid_window'
    assert r.select(*NAMES, *CONTROLS).null_count().row(0) == (1,)*(len(NAMES)+len(CONTROLS))


def test_missing_old_day_is_not_excused_by_later_full_turnover(data):
    b, s, dates, signals = data
    start, end, _ = formation_dates(signals[0])
    b = b.filter(pl.col('trade_date') != start).with_columns(
        pl.when(pl.col('trade_date') == end).then(10000.).otherwise(pl.col('volume')).alias('volume'))
    r = compute((b, s, dates, signals))
    assert r['status'][0] == 'incomplete_or_invalid_window'


def test_explicit_zero_is_distinct_from_absence(data):
    b, s, dates, signals = data
    mask = pl.col('trade_date') == dt.date(2020, 3, 2)
    zero = b.with_columns(pl.when(mask).then(0.).otherwise(pl.col('volume')).alias('volume'))
    assert compute((zero, s, dates, signals))['status'][0] == 'valid'
    assert compute((b.filter(~mask), s, dates, signals))['status'][0] == 'incomplete_or_invalid_window'


def test_zero_turnover_mass(data):
    b, s, dates, signals = data
    _, end, _ = formation_dates(signals[0])
    b = b.with_columns(pl.when(pl.col('trade_date') <= end).then(0.)
                       .otherwise(pl.col('volume')).alias('volume'))
    r = compute((b, s, dates, signals))
    assert r['status'][0] == 'zero_turnover_mass'
    assert r[NAMES[0]][0] is None


def test_prefix_and_future_rebasing_invariance(data):
    b, s, dates, signals = data
    old = compute(data)
    short = compute((b.filter(pl.col('trade_date') <= signals[0]),
                     s.filter(pl.col('trade_date') <= signals[0]),
                     tuple(d for d in dates if d <= signals[0]), signals))
    assert old.equals(short)
    _, cutoff, _ = formation_dates(signals[0])
    b = b.with_columns((pl.col('adj_factor')*900.).alias('adj_factor'),
        pl.when(pl.col('trade_date') > cutoff).then(pl.col('close')*80.)
        .otherwise(pl.col('close')).alias('close'))
    new = compute((b, s, dates, signals))
    for name in NAMES+CONTROLS:
        assert new[name][0] == pytest.approx(old[name][0], abs=2e-14)


def test_current_quote_missing_does_not_forward_fill(data):
    b, s, dates, signals = data
    r = compute((b.filter(pl.col('trade_date') != signals[0]), s, dates, signals))
    assert r['status'][0] == 'invalid_current_quote'
    assert r[NAMES[0]][0] is None


def test_calendar_holiday_does_not_require_quote(data):
    b, s, dates, signals = data
    _, end, _ = formation_dates(signals[0])
    dates = tuple(d for d in dates if d != end)
    b = b.filter(pl.col('trade_date') != end); s = s.filter(pl.col('trade_date') != end)
    r = compute((b, s, dates, signals))
    assert r['status'][0] == 'valid'
    assert r['cutoff_date'][0] == end-dt.timedelta(days=1)
    assert r['expected_sessions'][0] == 1299


def test_insufficient_calendar_history(data):
    b, s, dates, signals = data
    dates = tuple(d for d in dates if d >= dt.date(2021, 1, 1))
    r = compute((b.filter(pl.col('trade_date') >= dates[0]), s.filter(pl.col('trade_date') >= dates[0]), dates, signals))
    assert r['status'][0] == 'insufficient_calendar_history'


def test_duplicate_keys_and_off_calendar_dates_raise(data):
    b, s, dates, signals = data
    with pytest.raises(ValueError, match='Duplicate'):
        compute((pl.concat([b, b.head(1)]), s, dates, signals))
    with pytest.raises(ValueError, match='outside'):
        compute((b, s, dates[1:], signals))
    with pytest.raises(ValueError, match='month ends'):
        compute((b, s, dates, (dt.date(2023, 12, 28),)))


def test_order_and_unrelated_symbol_do_not_change_values(data):
    b, s, dates, signals = data
    other = b.with_columns(pl.lit('Y.SH').alias('symbol'), (pl.col('close')*.7).alias('close'))
    other_s = s.with_columns(pl.lit('Y.SH').alias('symbol'))
    old = compute(data)
    new = compute((pl.concat([b, other]).reverse(), pl.concat([s, other_s]).reverse(), dates, signals))
    assert new.filter(pl.col('symbol') == 'X.SH').equals(old)


def test_fixed_long_return_control(data):
    b, _, _, signals = data
    _, cutoff, _ = formation_dates(signals[0])
    start = b.filter(pl.col('trade_date') <= cutoff-dt.timedelta(weeks=156)).tail(1)
    end = b.filter(pl.col('trade_date') <= cutoff-dt.timedelta(weeks=52)).tail(1)
    expected = end['close'][0]*end['adj_factor'][0]/(start['close'][0]*start['adj_factor'][0])-1
    r = compute(data)
    assert r[CONTROLS[2]][0] == pytest.approx(expected, abs=1e-14)


def test_negative_gain_and_tiny_hazard(data):
    b, s, dates, signals = data
    b = b.with_columns((50.-pl.col('close')).alias('close'), pl.lit(1e-16).alias('volume'))
    r = compute((b, s, dates, signals))
    assert r['status'][0] == 'valid'
    assert r[NAMES[0]][0] < 0
    expected, _, _ = oracle((b, s, dates, signals))
    assert r[NAMES[0]][0] == pytest.approx(expected, abs=2e-13)
