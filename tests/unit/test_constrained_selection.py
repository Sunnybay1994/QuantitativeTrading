import datetime as dt

import polars as pl

from quant.portfolio.constrained_selection import constrained_targets


def fixture():
    day = dt.date(2020, 1, 31)
    names = [f'{i:06}.SZ' for i in range(100)]
    market = pl.DataFrame({'as_of': [day]*100, 'known_at': [day]*100, 'symbol': names,
        'eligible': [True]*100, 'industry_l1': ['A']*50+['B']*50,
        'total_market_value': [1e9+i*1e8 for i in range(100)],
        'size': [(i-49.5)/30 for i in range(100)], 'adv20': [1e8]*100,
        'can_buy': [True]*100, 'can_sell': [True]*100})
    scores = market.select('as_of', 'symbol').with_columns(pl.Series('score', list(range(100))))
    targets = scores.head(50).select('as_of', 'symbol').with_columns(pl.lit(.02).alias('weight'),
        pl.lit(dt.date(2020, 2, 3)).alias('execution_date'), pl.lit('r4').alias('strategy'),
        pl.lit('1').alias('strategy_version'))
    state = {'date': str(day), 'nav': [{'equity': 1e6}], 'holdings': {}}
    policy = {'top_k': 50, 'retention_multiplier': 1.5, 'single_stock_weight': .03,
        'cash_buffer': .02, 'industry_active_band': .05, 'size_band': .3,
        'adv_participation': .05, 'maximum_iterations': 4000, 'tolerance': 1e-8}
    return targets, state, market, scores, policy


def test_projection_controls_industry_size_and_cash():
    targets, state, market, scores, policy = fixture()
    out, info = constrained_targets(targets=targets, state=state, market=market, scores=scores, policy=policy)
    assert info['constraints_satisfied']
    measured = out.join(market, on=['symbol', 'as_of'])
    assert out['weight'].max() <= .03+1e-8
    assert out['weight'].min() >= 0
    assert out['weight'].sum() <= .98+1e-8
    assert abs(measured.select((pl.col('size')*pl.col('weight')).sum()).item()) <= .3+1e-8
    sector = measured.group_by('industry_l1').agg(pl.col('weight').sum())
    assert all(abs(w-.5) <= .05+1e-8 for w in sector['weight'])


def test_missing_held_size_freezes_exact_quantities_without_claiming_pass():
    targets, state, market, scores, policy = fixture()
    state['holdings'] = {'000000.SZ': {'quantity': 1000, 'mark_price': 10.}}
    market = market.with_columns(pl.when(pl.col('symbol') == '000000.SZ').then(None).otherwise(pl.col('size')).alias('size'))
    out, info = constrained_targets(targets=targets, state=state, market=market, scores=scores, policy=policy)
    assert not info['constraints_satisfied']
    assert out.filter(pl.col('symbol') == '000000.SZ')['weight'][0] == .01
    assert out['weight'].sum() == .01
    assert all(v == (False, False) for v in info['execution_direction_permissions'].values())


def test_unsellable_overweight_is_explicit_infeasibility():
    targets, state, market, scores, policy = fixture()
    state['holdings'] = {'000000.SZ': {'quantity': 4000, 'mark_price': 10.}}
    market = market.with_columns((pl.col('symbol') != '000000.SZ').alias('can_sell'))
    _, info = constrained_targets(targets=targets, state=state, market=market, scores=scores, policy=policy)
    assert not info['constraints_satisfied']
    assert info['failure_reason'] == 'unavoidable_trading_or_exposure_bounds'


def test_trade_weight_distance_respects_adv_not_total_position_value():
    targets, state, market, scores, policy = fixture()
    market = market.with_columns(pl.lit(100_000.).alias('adv20'))
    out, info = constrained_targets(targets=targets, state=state, market=market, scores=scores, policy=policy)
    assert not info['constraints_satisfied']  # 100 names * 0.5% cannot reach sector minimums.
    assert out['weight'].sum() == 0
