import datetime as dt

import numpy as np
import polars as pl
import pytest
from polars.testing import assert_frame_equal

from quant.factors.industry_information import CONTROL, SIGNALS, compute_industry_information
from quant.research.factor_battery_statistics import preprocess_cross_section

DATES = tuple(dt.date(2020, m, 28) for m in range(1, 10))


def fixture():
    return pl.DataFrame([dict(symbol=f'{g}{k:02}', trade_date=day, industry_l1=g,
        close=20.0 * (1 + (.01 if g == 'A' else -.005) + k*.001)**m,
        adj_factor=1., volume=1000., total_market_value=float(20-k))
        for m, day in enumerate(DATES) for g in ('A', 'B') for k in range(12)])


def compute(p=None, dates=DATES):
    return compute_industry_information(fixture() if p is None else p, month_ends=dates)


def at(frame, day=DATES[-1], symbol='A00'):
    return frame.filter((pl.col('symbol') == symbol) & (pl.col('trade_date') == day)).row(0, named=True)


def test_independent_portfolio_formula_and_calendar_window():
    result, evidence = compute()
    # Direct weighted cash gains in a separately specified fixed-capital portfolio.
    cash = np.arange(20, 8, -1, dtype=float)
    returns = .01 + np.arange(12)*.001
    expected = (cash*returns).sum()/cash.sum()
    expected_leader = (cash[:4]*returns[:4]).sum()/cash[:4].sum()
    assert at(result)[CONTROL] == pytest.approx(expected)
    assert at(result)[SIGNALS[0]] == pytest.approx((1+expected)**6-1)
    assert at(result)[SIGNALS[1]] == pytest.approx(expected_leader)
    assert at(result, DATES[5])[SIGNALS[0]] is None
    assert at(result, DATES[6])[SIGNALS[0]] is not None
    assert set(evidence['formation_members']) == {12}


def test_price_relabeling_and_common_cap_scale_invariance():
    source = fixture()
    transformed = source.with_columns(pl.col('close')*17., pl.col('total_market_value')*1e12,
                                      pl.col('adj_factor')*.3)
    original, _ = compute(source)
    changed, _ = compute(transformed)
    assert_frame_equal(original, changed, abs_tol=1e-12)


def test_split_at_endpoint_preserves_adjusted_return():
    p = fixture()
    event = (pl.col('symbol') == 'A00') & (pl.col('trade_date') >= DATES[5])
    p = p.with_columns(pl.when(event).then(pl.col('close')/2).otherwise(pl.col('close')).alias('close'),
                      pl.when(event).then(pl.col('adj_factor')*2).otherwise(pl.col('adj_factor')).alias('adj_factor'))
    assert_frame_equal(compute()[0], compute(p)[0])


def test_later_quote_and_capital_cannot_change_earlier_signals():
    base = fixture()
    cutoff = DATES[5]
    full, _ = compute(base)
    prefix, _ = compute(base.filter(pl.col('trade_date') <= cutoff), DATES[:6])
    assert_frame_equal(prefix, full.filter(pl.col('trade_date') <= cutoff))
    changed = base.with_columns(pl.when(pl.col('trade_date') > cutoff).then(pl.col('close')*20).otherwise(pl.col('close')).alias('close'))
    assert_frame_equal(prefix, compute(changed)[0].filter(pl.col('trade_date') <= cutoff))


def test_current_cap_does_not_pick_current_month_leaders():
    base, _ = compute()
    p = fixture().with_columns(pl.when((pl.col('trade_date') == DATES[-1]) & (pl.col('symbol') == 'A11'))
        .then(1e20).otherwise(pl.col('total_market_value')).alias('total_market_value'))
    assert_frame_equal(base, compute(p)[0])


@pytest.mark.parametrize('symbol,leaders_available', [('A00', False), ('A11', True)])
def test_missing_frozen_member_is_not_dropped_or_reweighted(symbol, leaders_available):
    p = fixture().filter(~((pl.col('symbol') == symbol) & (pl.col('trade_date') == DATES[-1])))
    result, diag = compute(p)
    row = at(result, symbol='A01')
    assert row[CONTROL] is None and row[SIGNALS[0]] is None
    assert (row[SIGNALS[1]] is not None) == leaders_available
    assert diag.filter((pl.col('industry_l1') == 'A') & (pl.col('trade_date') == DATES[-1]))['missing_endpoints'].item() == 1


@pytest.mark.parametrize('field,value', [('volume', 0.), ('close', 0.), ('adj_factor', float('nan'))])
def test_invalid_endpoints_remain_missing(field, value):
    p = fixture().with_columns(pl.when((pl.col('symbol') == 'A00') & (pl.col('trade_date') == DATES[-1]))
        .then(value).otherwise(pl.col(field)).alias(field))
    assert at(compute(p)[0], symbol='A01')[SIGNALS[1]] is None


@pytest.mark.parametrize('value', [None, 0., -1., float('inf')])
def test_unknown_formation_capital_invalidates_industry(value):
    p = fixture().with_columns(pl.when((pl.col('symbol') == 'A11') & (pl.col('trade_date') == DATES[-2]))
        .then(pl.lit(value, dtype=pl.Float64)).otherwise(pl.col('total_market_value')).alias('total_market_value'))
    row = at(compute(p)[0])
    assert row[CONTROL] is None and row[SIGNALS[1]] is None


def test_taxonomy_transition_does_not_splice_return_history():
    p = fixture().with_columns(pl.when(pl.col('trade_date') >= DATES[5])
        .then(pl.lit('new:')+pl.col('industry_l1')).otherwise(pl.col('industry_l1')).alias('industry_l1'))
    result, _ = compute(p)
    assert at(result, DATES[5])[SIGNALS[1]] is None
    assert at(result, DATES[6])[SIGNALS[1]] is not None
    assert at(result)[SIGNALS[0]] is None


def test_new_listing_does_not_enter_already_formed_portfolio():
    base, _ = compute()
    newcomer = pl.DataFrame([dict(symbol='Anew', trade_date=DATES[-1], industry_l1='A',
        close=99999., adj_factor=1., volume=100., total_market_value=1e20)])
    result, _ = compute(pl.concat([fixture(), newcomer]))
    assert at(result)[SIGNALS[1]] == at(base)[SIGNALS[1]]
    assert at(result, symbol='Anew')[SIGNALS[1]] == at(base)[SIGNALS[1]]


def test_industry_exposure_cannot_become_roundoff_stock_alpha():
    result, _ = compute()
    current = result.filter(pl.col('trade_date') == DATES[-1])
    for name in SIGNALS:
        neutral = preprocess_cross_section(current[name].to_numpy(), np.linspace(10, 30, current.height),
            current['industry_l1'].to_numpy(), neutralize=True)
        assert np.isnan(neutral).all()
        assert np.isfinite(preprocess_cross_section(current[name].to_numpy(), np.zeros(current.height),
            current['industry_l1'].to_numpy(), neutralize=False)).all()


def test_tied_size_has_deterministic_leaders_and_row_order():
    p = fixture().with_columns(pl.lit(1.).alias('total_market_value'))
    result, diag = compute(p)
    assert at(result)[SIGNALS[1]] == pytest.approx(.0115)
    shuffled, shuffled_diag = compute(p.reverse())
    assert_frame_equal(result, shuffled)
    assert_frame_equal(diag, shuffled_diag)


def test_too_small_industry_and_unknown_classification_are_missing():
    p = fixture().filter(~pl.col('symbol').is_in(['A09', 'A10', 'A11']))
    assert at(compute(p)[0])[SIGNALS[1]] is None
    p = fixture().with_columns(pl.when(pl.col('symbol') == 'A00').then(None).otherwise(pl.col('industry_l1')).alias('industry_l1'))
    assert at(compute(p)[0])[SIGNALS[1]] is None


@pytest.mark.parametrize('fault', ['duplicate', 'calendar_gap', 'off_anchor'])
def test_structural_errors_raise(fault):
    p = fixture()
    dates = DATES
    if fault == 'duplicate':
        p = pl.concat([p, p.head(1)])
    elif fault == 'calendar_gap':
        dates = DATES[:3] + DATES[4:]
    else:
        p = p.with_columns((pl.col('trade_date')+dt.timedelta(days=1)).alias('trade_date'))
    with pytest.raises(ValueError):
        compute(p, dates)
