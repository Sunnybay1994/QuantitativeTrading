import datetime as dt

import polars as pl
import pytest

from quant.portfolio.industry_candidate_selection import select_industry_candidates

DAY = dt.date(2026, 7, 31)


def inputs():
    names = [f'S{i}' for i in range(8)]
    scores = pl.DataFrame({'as_of': [DAY]*8, 'symbol': names, 'score': [float(8-i) for i in range(8)]})
    market = pl.DataFrame({'as_of': [DAY]*8, 'known_at': [DAY]*8, 'symbol': names,
        'industry_l1': ['X']*4+['Y']*4, 'total_market_value': [1e9]*8,
        'adv20': [1e8]*8, 'can_buy': [True]*8, 'can_sell': [True]*8})
    benchmark = scores.select('as_of','symbol').with_columns(pl.lit(.125).alias('weight'))
    return scores,market,benchmark,benchmark.clear()


def run(s,m,b,c,previous=None,**kwargs):
    return select_industry_candidates(scores=s,market=m,benchmark=b,current=c,
        previous=previous or [],top_k=4,minimum_signal_stocks=4,single_stock_weight=.3,**kwargs)


def test_sector_quotas_add_missing_lower_ranked_industry():
    s,m,b,c = inputs()
    out, info = run(s,m,b,c)
    assert info['feasible']
    assert out['symbol'].to_list() == ['S0','S1','S4','S5']
    assert [q['minimum_names'] for q in info['industry_quotas']] == [2,2]
    assert all(out['selection_reason']=='industry_lower_bound')


def test_original_rank_buffer_is_preserved_after_required_slots():
    s,m,b,c = inputs()
    out,info = run(s,m,b,c,previous=['S5','S7'],industry_active_band=1.)
    assert info['feasible']
    assert out['symbol'].to_list() == ['S0','S1','S2','S5']
    assert out.filter(pl.col('symbol')=='S5')['selection_reason'][0] == 'rank_buffer'


def test_unsellable_existing_position_counts_toward_sector_quota():
    s,m,b,c = inputs()
    c = b.filter(pl.col('symbol')=='S7').with_columns(pl.lit(.1).alias('weight'))
    m = m.with_columns((pl.col('symbol')!='S7').alias('can_sell'))
    out,info = run(s,m,b,c)
    assert info['feasible']
    assert out['symbol'].to_list() == ['S0','S1','S4','S7']
    assert info['forced_holdings'] == ['S7']


def test_unsellable_overflow_never_discards_real_holdings():
    s,m,b,c = inputs()
    c = b.head(5)
    m = m.with_columns(pl.lit(False).alias('can_sell'))
    out,info = run(s,m,b,c)
    assert not info['feasible']
    assert set(c['symbol']) <= set(out['symbol'])
    assert 'unsellable_holdings_exceed_name_cap' in info['failures']


def test_unscored_missing_market_forced_holding_is_still_retained():
    s,m,b,c = inputs()
    c = b.head(1).with_columns(pl.lit('OLD').alias('symbol'))
    out,info = run(s,m,b,c)
    assert not info['feasible']
    assert 'OLD' in out['symbol']
    assert 'mandatory_nominees_exceed_name_cap' in info['failures']


def test_missing_buyable_sector_is_explicit_failure():
    s,m,b,c = inputs()
    m = m.with_columns((pl.col('industry_l1')=='X').alias('can_buy'))
    _,info = run(s,m,b,c)
    assert not info['feasible']
    assert 'insufficient_industry_candidates:Y' in info['failures']


def test_zero_nominee_industry_band_does_not_relax_weight_projection():
    s,m,b,c = inputs()
    _,info = run(s,m,b,c,industry_active_band=0.)
    assert info['feasible']
    assert 'full weight projection still required' in info['capacity_statement']


def test_tie_break_and_input_permutation_are_deterministic():
    s,m,b,c = inputs()
    s = s.with_columns(pl.lit(1.).alias('score'))
    a,_ = run(s,m,b,c)
    z,_ = run(s.reverse(),m.reverse(),b.reverse(),c)
    assert a.equals(z)


def test_future_market_and_duplicate_scores_rejected():
    s,m,b,c = inputs()
    with pytest.raises(ValueError,match='PIT'):
        run(s,m.with_columns(pl.lit(DAY+dt.timedelta(days=1)).alias('known_at')),b,c)
    with pytest.raises(ValueError,match='Duplicate'):
        run(pl.concat([s,s.head(1)]),m,b,c)
