import datetime as dt

import polars as pl
import pytest

from quant.portfolio.simple_constraints import ConstraintLimits, constrain_targets

DAY = dt.date(2026, 7, 31)


def frames(weights=(.2, .2), current=(0., 0.)):
    targets = pl.DataFrame({'as_of': [DAY]*2, 'symbol': ['A', 'B'], 'weight': weights})
    held = targets.with_columns(pl.Series('weight', current))
    market = pl.DataFrame({'as_of': [DAY]*2, 'known_at': [DAY]*2,
        'symbol': ['A', 'B'], 'industry_l1': ['X', 'X'], 'adv20': [1e8, 1e8],
        'can_buy': [True, True], 'can_sell': [True, True]})
    return targets, held, market


def run(t, h, m, **kw):
    return constrain_targets(targets=t, current=h, market=m, equity=1e6, **kw)


def test_caps_and_residual_cash_are_not_redistributed():
    t, h, m = frames()
    out, info = run(t, h, m, limits=ConstraintLimits(.02, .15, .20, .05))
    assert out['weight'].to_list() == pytest.approx([.1, .1])
    assert info['cash_weight'] == pytest.approx(.8)
    assert info['changed_from_requested'] == 2
    assert t['weight'].to_list() == [.2, .2]


def test_adv_caps_both_buys_and_sells():
    t, h, m = frames((.2, 0.), (0., .02))
    m = m.with_columns(pl.lit(100_000.).alias('adv20'))
    out, _ = run(t, h, m)
    assert out['weight'].to_list() == pytest.approx([.005, .015])


def test_untradeable_current_consumes_industry_room():
    t, h, m = frames((0., .1), (.25, 0.))
    m = m.with_columns(pl.Series('can_sell', [False, True]))
    out, info = run(t, h, m)
    assert out['weight'].to_list() == pytest.approx([.25, 0.])
    assert info['unresolved_existing_limits']['industries'] == ['X']


def test_switches_and_missing_market_preserve_actual_holdings():
    t, h, m = frames((.2, 0.), (.01, .02))
    out, _ = run(t, h, m, enabled=False)
    assert out['weight'].to_list() == [.01, .02]
    out, _ = run(t, h, m, sell_only=True)
    assert out['weight'].to_list() == [.01, 0.]
    out, _ = run(t, h, m.head(1))
    assert out['weight'].to_list() == [.03, .02]


def test_unspecified_current_holding_remains_when_sell_blocked():
    t, h, m = frames((.02, .02), (.01, .4))
    m = m.with_columns(pl.Series('can_sell', [True, False]))
    out, _ = run(t.head(1), h, m)
    assert out['symbol'].to_list() == ['A', 'B']
    assert out['weight'].to_list() == [.01, .4]


def test_preserved_holding_leaves_no_new_cash_budget():
    t, h, m = frames((0., .2), (.99, 0.))
    m = m.with_columns(pl.Series('can_sell', [False, True]), pl.Series('industry_l1', ['X', 'Y']))
    out, info = run(t, h, m)
    assert out['weight'].to_list() == [.99, 0.]
    assert info['unresolved_existing_limits']['cash_buffer']


def test_unknown_industry_does_not_open_position():
    t, h, m = frames()
    m = m.with_columns(pl.lit(None, dtype=pl.String).alias('industry_l1'))
    out, _ = run(t, h, m)
    assert out['weight'].sum() == 0


@pytest.mark.parametrize('problem', ['future', 'duplicate', 'date', 'null_permission', 'negative'])
def test_invalid_inputs_fail(problem):
    t, h, m = frames()
    if problem == 'future':
        m = m.with_columns(pl.lit(DAY+dt.timedelta(days=1)).alias('known_at'))
    elif problem == 'duplicate':
        m = pl.concat([m, m.head(1)])
    elif problem == 'date':
        h = h.with_columns(pl.lit(DAY-dt.timedelta(days=1)).alias('as_of'))
    elif problem == 'null_permission':
        m = m.with_columns(pl.lit(None, dtype=pl.Boolean).alias('can_buy'))
    else:
        t = t.with_columns(pl.lit(-.1).alias('weight'))
    with pytest.raises(ValueError):
        run(t, h, m)
