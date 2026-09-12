import datetime as dt

import polars as pl
import pytest

from quant.portfolio.simple_constraints import (
    ConstraintLimits, RelativeConstraintLimits, constrain_relative_targets, constrain_targets,
)

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



def relative_inputs():
    t, h, m = frames((.7, .3))
    m = m.with_columns(pl.Series('industry_l1', ['X', 'Y']),
                      pl.Series('total_market_value', [1e9, 1e11]))
    b = t.with_columns(pl.Series('weight', [.5, .5]))
    return t, h, m, b


def relative_run(t, h, m, b, **kwargs):
    return constrain_relative_targets(targets=t, current=h, market=m, benchmark=b,
        equity=1e6, limits=RelativeConstraintLimits(single_stock_weight=.8), **kwargs)


def test_relative_bands_use_total_equity_and_full_benchmark_size():
    t, h, m, b = relative_inputs()
    out, info = relative_run(t, h, m, b)
    assert info['feasible']
    assert info['cash_weight'] >= .02-1e-8
    assert abs(info['residuals']['size_active_z']) <= .3+1e-8
    assert out['weight'].to_list() == pytest.approx([.53, .45], abs=1e-7)
    assert info['residuals']['industry_active_weights']['Y'] == pytest.approx(-.05, abs=1e-8)


def test_relative_missing_candidate_industry_is_not_fixed_by_cash():
    t, h, m, b = relative_inputs()
    out, info = relative_run(t.head(1), h, m, b)
    assert not info['feasible']
    assert info['absent_required_industries'] == ['Y']
    assert info['residuals']['industry_violation'] >= .45
    assert info['fallback'] == 'conservative_diagnostic_only_reject_formal_replay'
    assert out['weight'].sum() <= .98


def test_relative_untradeable_overweight_is_explicitly_infeasible():
    t, h, m, b = relative_inputs()
    h = h.with_columns(pl.Series('weight', [.9, 0.]))
    m = m.with_columns(pl.lit(False).alias('can_sell'))
    out, info = relative_run(t, h, m, b)
    assert not info['feasible'] and info['impossible_trading_box']
    assert out['weight'][0] == .9


def test_relative_size_constraint_and_permutation_are_deterministic():
    t, h, m, b = relative_inputs()
    m = m.with_columns(pl.lit('X').alias('industry_l1'))
    out, info = relative_run(t, h, m, b)
    out2, info2 = relative_run(t.reverse(), h.reverse(), m.reverse(), b.reverse())
    assert info['feasible'] and info2['feasible']
    assert out['weight'].to_list() == pytest.approx(out2['weight'].to_list(), abs=1e-8)
    assert abs(info['residuals']['size_active_z']) <= .3+1e-8


def test_relative_zero_size_variance_and_incomplete_benchmark_fail():
    t, h, m, b = relative_inputs()
    with pytest.raises(ValueError, match='variance is zero'):
        relative_run(t, h, m.with_columns(pl.lit(1e9).alias('total_market_value')), b)
    with pytest.raises(ValueError, match='fully invested'):
        relative_run(t, h, m, b.head(1))


def test_relative_iteration_limit_keeps_failure_explicit():
    t, h, m, b = relative_inputs()
    _, info = constrain_relative_targets(targets=t, current=h, market=m, benchmark=b,
        equity=1e6, limits=RelativeConstraintLimits(single_stock_weight=.8, maximum_iterations=1))
    assert info['iterations'] == 1
    assert not info['feasible']



def test_relative_cash_floor_conflict_is_proved_without_iteration():
    t, h, m, b = relative_inputs()
    h = h.with_columns(pl.Series('weight', [.5, .5]))
    m = m.with_columns(pl.lit(False).alias('can_sell'))
    _, info = relative_run(t, h, m, b)
    assert not info['feasible']
    assert info['iterations'] == 0
    assert info['failure_reason'] == 'infeasible_trading_bounds'
    assert any(r['constraint'] == 'invested_weight' for r in info['band_capacity_conflicts'])


def test_relative_unknown_adv_cannot_create_industry_capacity():
    t, h, m, b = relative_inputs()
    m = m.with_columns(pl.lit(None, dtype=pl.Float64).alias('adv20'))
    out, info = relative_run(t, h, m, b)
    assert not info['feasible'] and info['iterations'] == 0
    assert out['weight'].sum() == 0
    assert info['absent_required_industries'] == ['X', 'Y']



def test_relative_irrelevant_zero_rows_need_no_stale_exposure():
    t, h, m, b = relative_inputs()
    t = pl.concat([t, t.head(1).with_columns(pl.lit('OLD').alias('symbol'), pl.lit(0.).alias('weight'))])
    out, info = relative_run(t, h, m, b)
    assert info['feasible']
    assert out.filter(pl.col('symbol') == 'OLD')['weight'][0] == 0


def test_relative_all_cash_keeps_industry_lower_bound_failure_explicit():
    t, h, m, b = relative_inputs()
    t = t.with_columns(pl.lit(0.).alias('weight'))
    out, info = relative_run(t, h, m, b)
    assert not info['feasible']
    assert info['absent_required_industries'] == ['X', 'Y']
    assert out['weight'].sum() == 0



def test_targets_cannot_shadow_point_in_time_industry():
    t, h, m = frames()
    with pytest.raises(ValueError, match='shadow PIT industry'):
        run(t.with_columns(pl.lit('STALE').alias('industry_l1')), h, m)
