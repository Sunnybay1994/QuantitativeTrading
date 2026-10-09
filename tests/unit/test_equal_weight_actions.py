import copy
import datetime as dt

import pytest

from quant.data.equal_weight_actions import action_index_day, validate_exchanges
from quant.data.equal_weight_index import index_day

D = dt.date(2020, 1, 30)


def exchange(old='A', new='B', ratio='2', *, available=D, tradable=D):
    return dict(from_symbol=old, to_symbol=new, ratio=ratio, announcement_date=D,
                effective_date=D, listing_notices=[dict(available_date=available, tradable_date=tradable)])


def quotes(**prices):
    return {s: dict(open=p[0], close=p[1], volume=1.) for s, p in prices.items()}


def run(state, e, q, *, day=D, targets=None, actions=None):
    return action_index_day(date=day, state=state, quotes=q, actions=actions or {},
                            delisted={e['from_symbol']: D}, stopped=set(), targets=targets, exchanges=[e])


def test_delivered_units_merge_existing_successor_without_value_creation():
    # Ten old shares worth 100 become twenty B; existing B has 30 shares worth 300.
    state = dict(weights={'A': .25, 'B': .75}, last={'A': 10., 'B': 10.}, level=400.)
    original = copy.deepcopy(state)
    new, row, events = run(state, exchange(), quotes(B=(8., 9.)))
    assert state == original
    assert row['opening_index_level'] == pytest.approx(50 * 8.)
    assert new['level'] == pytest.approx(50 * 9.)
    release = next(e for e in events if e['kind'] == 'exchange_claim_released')
    assert release['existing_successor_units'] == 30
    assert release['successor_units'] == 20
    assert release['value_before'] == pytest.approx(release['value_after'])


@pytest.mark.parametrize('old,new,ratio', [('600102.SH', '600022.SH', '2.41'),
                                         ('600270.SH', '601598.SH', '3.8225')])
def test_pending_claim_crosses_monthly_rebalance_with_fixed_units(old, new, ratio):
    e = exchange(old, new, ratio, available=D + dt.timedelta(days=4), tradable=D + dt.timedelta(days=5))
    state = dict(weights={old: .2, 'X': .8}, last={old: 10., 'X': 10.}, level=1000.)
    state, _, _ = run(state, e, quotes(X=(10., 10.)))
    claim = state['pending_claims']['@exchange:' + old]
    units = claim['units']
    assert units == pytest.approx(20 * float(ratio))
    state, row, _ = run(state, e, quotes(X=(20., 20.), Y=(10., 11.)),
                       day=D + dt.timedelta(days=1), targets={'Y': dict(weight=1., signal_close=10.)})
    assert row['opening_index_level'] == pytest.approx(1800.)
    assert state['level'] == pytest.approx(200 + 1600 * 1.1)
    assert row['pending_claim_value'] == pytest.approx(200.)
    assert state['pending_claims']['@exchange:' + old]['units'] == units
    state, row, _ = run(state, e, {**quotes(Y=(11., 11.)), new: dict(open=12., close=12., volume=1.)},
                       day=D + dt.timedelta(days=5))
    assert not state['pending_claims']
    assert state['level'] == pytest.approx(1760 + units * 12.)


def test_same_day_listing_rebalance_keeps_old_overnight_then_new_intraday():
    state = dict(weights={'300186.SZ': 1.}, last={'300186.SZ': 10.}, level=1000.)
    e = exchange('300186.SZ', '300498.SZ', '.8070')
    state, row, _ = run(state, e, quotes(**{'300498.SZ': (20., 200.), 'X': (10., 11.)}),
                        targets={'X': dict(weight=1., signal_close=10.)})
    assert row['opening_index_level'] == pytest.approx(100 * .807 * 20)
    assert state['level'] == pytest.approx(100 * .807 * 20 * 1.1)
    assert set(state['weights']) == {'X'}


def test_future_listing_notice_does_not_release_despite_visible_price():
    e = exchange(available=D + dt.timedelta(days=2), tradable=D + dt.timedelta(days=2))
    state = dict(weights={'A': 1.}, last={'A': 10.}, level=1000.)
    state, row, _ = run(state, e, quotes(B=(100., 100.)))
    assert state['level'] == 1000
    assert row['pending_claim_count'] == 1
    assert 'B' not in state['weights']


def test_known_listing_still_requires_actual_positive_bar():
    state = dict(weights={'A': 1.}, last={'A': 10.}, level=1000.)
    state, _, _ = run(state, exchange(), {'B': dict(open=12., close=13., volume=0.)})
    assert state['level'] == 1000
    assert state['pending_claims']
    state, _, _ = run(state, exchange(), quotes(B=(12., 13.)), day=D + dt.timedelta(days=1))
    assert state['level'] == 2600
    assert not state['pending_claims']


def test_pending_distribution_fails_instead_of_silently_adding_or_losing_rights():
    state = dict(weights={'A': 1.}, last={'A': 10.}, level=1000.)
    e = exchange(available=D + dt.timedelta(days=3), tradable=D + dt.timedelta(days=3))
    state, _, _ = run(state, e, {})
    with pytest.raises(ValueError, match='Pending successor dividend'):
        run(state, e, {}, day=D + dt.timedelta(days=1),
            actions={'B': dict(ann_date=D, div_cash=1., share_ratio=0.)})


def test_without_exchange_matches_original_dividend_and_rebalance():
    args = dict(date=D, state=dict(weights={'X': 1.}, last={'X': 10.}, level=1000.),
                quotes=quotes(X=(9., 9.), Y=(10., 12.)),
                actions={'X': dict(ann_date=D, div_cash=1., share_ratio=0.)},
                delisted={}, stopped=set(), targets={'Y': dict(weight=1., signal_close=10.)})
    old, oldrow, events = index_day(**args)
    new, row, newevents = action_index_day(**args, exchanges=[])
    assert new['weights'] == old['weights']
    assert new['level'] == old['level']
    assert all(row[k] == v for k, v in oldrow.items())
    assert events == newevents


def test_rejects_future_terms():
    e = exchange()
    e['announcement_date'] = D + dt.timedelta(days=1)
    with pytest.raises(ValueError, match='future-known'):
        validate_exchanges([e])


def test_local_block_units_scale_with_published_nav_but_prices_and_weights_do_not():
    from quant.research.benchmark_corporate_repair import scale_event
    row = dict(successor_units=2., existing_successor_units=3., merged_successor_units=5.,
               book_value=10., value_before=30., value_after=30., prior_mark=6., prior_weight=.2)
    scaled = scale_event(row, 1.25)
    assert scaled['successor_units'] == 2.5
    assert scaled['merged_successor_units'] == 6.25
    assert scaled['book_value'] == 12.5
    assert scaled['value_before'] == scaled['value_after'] == 37.5
    assert scaled['prior_mark'] == 6.
    assert scaled['prior_weight'] == .2
    assert row['book_value'] == 10.


def test_calendar_alignment_excludes_only_proven_closed_days():
    import polars as pl
    from quant.research.benchmark_repair_evaluation import calendar_grid
    dates = [dt.date(2020, 1, 3), dt.date(2020, 1, 4), dt.date(2020, 1, 5)]
    calendar = pl.DataFrame([dict(market=m, date=d, is_open=i == 0)
                             for m in ('SH', 'SZ') for i, d in enumerate(dates)])
    nav = pl.DataFrame({'date': dates[:1], 'unit_nav': [1.]})
    assert calendar_grid(calendar, nav, dates[0], dates[-1]) == dates[:1]
    with pytest.raises(ValueError, match='missing actual open sessions'):
        calendar_grid(calendar, nav.head(0), dates[0], dates[-1])
