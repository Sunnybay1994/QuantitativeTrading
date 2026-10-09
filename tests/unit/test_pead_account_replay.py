import copy
import datetime as dt
import json

import polars as pl
from polars.testing import assert_frame_equal
import pytest

from quant.research.pead_account_replay import event_priority, replay


DAYS = [dt.date(2020, 1, 1) + dt.timedelta(days=i) for i in range(180)
        if (dt.date(2020, 1, 1) + dt.timedelta(days=i)).weekday() < 5]
SYMBOL = '000001.SZ'
EVENT_SCHEMA = {'symbol': pl.String, 'announcement_date': pl.Date, 'end_date': pl.Date,
    'status': pl.String, 'market_eligible': pl.Boolean, 'threshold': pl.Float64,
    'selected': pl.Boolean, 'earliest_execution_date': pl.Date, 'reference_expiry_date': pl.Date}


def event(symbol=SYMBOL, index=21, selected=True, **extra):
    return dict(symbol=symbol, announcement_date=DAYS[index - 1], end_date=dt.date(2019, 12, 31),
        status='VALID', market_eligible=True, threshold=.2, selected=selected,
        earliest_execution_date=DAYS[index], reference_expiry_date=DAYS[index + 40], **extra)


def fixture(symbols=(SYMBOL,), *, sessions=None, events=None, prices=None):
    prices = prices or {}
    bars = pl.from_dicts([dict(symbol=s, trade_date=d, open=prices.get(s, 10.), high=prices.get(s, 10.),
        low=prices.get(s, 10.), close=prices.get(s, 10.), volume=10000000., amount=100000000.,
        adj_factor=1., source='test') for s in symbols for d in DAYS])
    calendar = pl.from_dicts([dict(market=m, date=d, is_open=True, is_connect_open=False,
        is_half_day=False) for m in ('SH', 'SZ') for d in DAYS])
    instruments = pl.from_dicts([dict(symbol=s, market=s[-2:], name=s, instrument_type='STOCK',
        currency='CNY', list_date=dt.date(2010, 1, 1), delist_date=None, board_lot=100,
        status='LISTED') for s in symbols]).with_columns(pl.col('delist_date').cast(pl.Date))
    limits = bars.select('symbol', 'trade_date').with_columns(pl.lit(10000.).alias('up_limit'),
                                                            pl.lit(.01).alias('down_limit'))
    dividends = pl.DataFrame(schema={'symbol': pl.String, 'ann_date': pl.Date,
        'record_date': pl.Date, 'ex_date': pl.Date, 'pay_date': pl.Date, 'div_cash': pl.Float64,
        'share_ratio': pl.Float64, 'share_list_date': pl.Date})
    basic = dict(commission_rate=0., commission_min=1., slippage=0., effective_from=dt.date(2010, 1, 1))
    config = dict(paper=dict(initial_cash=100000, auto_trade=False),
        portfolio=dict(slots=5, cash_buffer=.02, max_participation=.05, holding_sessions=40),
        execution=dict(priority_salt='pead40-personal-v1', suspension_policy='bar_present_known_suspensions_block'),
        costs={'etf': basic, 'a_share': {**basic, 'stamp_tax_sell': 0., 'transfer_fee': 0.}})
    return dict(events=pl.from_dicts(events if events is not None else [event(symbols[0])], schema=EVENT_SCHEMA),
        bars=bars, calendar=calendar, instruments=instruments, limits=limits,
        suspensions=pl.DataFrame(schema={'symbol': pl.String, 'trade_date': pl.Date}), dividends=dividends,
        config=config, case='pead', cost_multiplier=1., sessions=sessions or DAYS[21:24])


def seed(holdings, *, day=20, expiry=22):
    value = sum(h['quantity'] * h['mark_price'] for h in holdings.values())
    return dict(date=str(DAYS[day]), holdings=holdings, cash=100000. - value,
        receivables=[], pending=[], nav=[dict(date=str(DAYS[day]), equity=100000.)],
        inception_date=str(DAYS[0]), started_with_cash=True,
        pead_books={s: dict(expiry_date=str(DAYS[expiry]), event_keys=[f'initial|{s}']) for s in holdings})


def test_fixed_signal_close_quantity_cash_floor_and_40_session_exit():
    source = fixture(sessions=DAYS[21:63])
    source['bars'] = source['bars'].with_columns([
        pl.when(pl.col('trade_date') == DAYS[21]).then(11.).otherwise(pl.col(c)).alias(c)
        for c in ('open', 'high', 'low', 'close')])
    out = replay(**source)
    assert out['trades'].select('date', 'side', 'quantity').rows() == [
        (DAYS[21], 'BUY', 1900), (DAYS[61], 'SELL', 1900)]
    assert out['trades']['fee'].to_list() == [1., 1.]
    assert out['state']['cash'] == pytest.approx(98098.)
    assert out['nav']['position_count'][-1] == 0


def test_hash_nominees_failure_does_not_substitute_or_retry():
    symbols = [f'{i:06}.SZ' for i in range(1, 8)]
    events = [event(s) for s in symbols]
    order = sorted(events, key=event_priority)
    source = fixture(symbols, events=events)
    blocked = order[0]['symbol']
    source['limits'] = source['limits'].filter(~((pl.col('symbol') == blocked) & (pl.col('trade_date') == DAYS[21])))
    out = replay(**source)
    assert set(out['trades']['symbol']) == {row['symbol'] for row in order[1:5]}
    assert out['trades']['date'].unique().to_list() == [DAYS[21]]
    assert out['rejections']['reason'].to_list() == ['UNKNOWN_PRICE_BAND']
    assert out['decisions'].filter(pl.col('reason') == 'NO_PRIOR_CLOSE_SLOT').height == 2


def test_all_event_control_uses_same_hash_and_requires_prior_threshold():
    symbols = [f'{i:06}.SZ' for i in range(1, 8)]
    events = [event(s) for s in symbols]
    source = fixture(symbols, events=events, sessions=[DAYS[21]])
    a = replay(**source)
    b = replay(**{**source, 'case': 'all_events'})
    assert a['trades'].select('symbol', 'quantity').equals(b['trades'].select('symbol', 'quantity'))
    events[0]['threshold'] = None
    events[1]['selected'] = False
    source['events'] = pl.from_dicts(events, schema=EVENT_SCHEMA)
    control = replay(**{**source, 'case': 'all_events'})
    assert control['decisions'].filter((pl.col('symbol') == symbols[0]) & (pl.col('reason') == 'NOT_CASE_CANDIDATE')).height == 1
    assert symbols[1] in set(control['decisions'].filter(pl.col('reason') != 'NOT_CASE_CANDIDATE')['symbol'])


def test_planned_exit_does_not_free_previous_close_slot_and_held_event_no_extension():
    symbols = [f'{i:06}.SZ' for i in range(1, 7)]
    source = fixture(symbols, events=[event(s) for s in (symbols[0], symbols[-1])], sessions=[DAYS[21]])
    state = seed({s: dict(quantity=100, mark_price=10.) for s in symbols[:5]}, expiry=21)
    out = replay(**source, account_state=state)
    assert set(out['trades']['side']) == {'SELL'}
    assert out['decisions'].filter(pl.col('reason') == 'HELD_EVENT_IGNORED_NO_EXTENSION').height == 1
    assert out['decisions'].filter(pl.col('reason') == 'NO_PRIOR_CLOSE_SLOT').height == 1
    assert state['pead_books'][symbols[0]]['expiry_date'] == str(DAYS[21])


def test_missing_band_exit_retries_daily_and_does_not_delete_position():
    source = fixture(events=[], sessions=DAYS[21:24])
    source['limits'] = source['limits'].filter(pl.col('trade_date') != DAYS[21])
    state = seed({SYMBOL: dict(quantity=155, mark_price=10.)}, expiry=21)
    out = replay(**source, account_state=state)
    assert out['trades'].select('date', 'quantity').rows() == [(DAYS[22], 155)]
    assert out['rejections']['reason'].to_list() == ['UNKNOWN_PRICE_BAND']
    assert out['nav']['position_count'].to_list() == [1, 0, 0]


@pytest.mark.parametrize('kind', ['missing_bar', 'zero_volume', 'suspension', 'upper_limit'])
def test_bad_execution_day_never_creates_delayed_entry(kind):
    source = fixture()
    if kind == 'missing_bar':
        source['bars'] = source['bars'].filter(pl.col('trade_date') != DAYS[21])
    elif kind == 'zero_volume':
        source['bars'] = source['bars'].with_columns(pl.when(pl.col('trade_date') == DAYS[21]).then(0.).otherwise(pl.col('volume')).alias('volume'))
    elif kind == 'suspension':
        source['suspensions'] = pl.DataFrame({'symbol': [SYMBOL], 'trade_date': [DAYS[21]]})
    else:
        source['limits'] = source['limits'].with_columns(pl.when(pl.col('trade_date') == DAYS[21]).then(10.).otherwise(pl.col('up_limit')).alias('up_limit'))
    out = replay(**source)
    assert out['trades'].is_empty()
    assert out['rejections'].height == 1
    assert out['nav']['equity'].to_list() == [100000.] * 3


def test_adv_exact_session_gap_blocks_entry_and_exit_until_complete_window():
    source = fixture(events=[], sessions=DAYS[21:33])
    source['bars'] = source['bars'].filter(pl.col('trade_date') != DAYS[10])
    state = seed({SYMBOL: dict(quantity=100, mark_price=10.)}, expiry=21)
    out = replay(**source, account_state=state)
    assert out['trades']['date'].to_list() == [DAYS[31]]
    assert out['rejections'].filter(pl.col('reason') == 'UNKNOWN_OR_ZERO_PRIOR_20_SESSION_ADV').height == 10


def test_adv_participation_partial_fill_no_entry_topup_then_exit_retries():
    source = fixture(events=[], sessions=DAYS[21:24])
    source['bars'] = source['bars'].with_columns(pl.lit(20000.).alias('amount'))
    state = seed({SYMBOL: dict(quantity=250, mark_price=10.)}, expiry=21)
    out = replay(**source, account_state=state)
    assert out['trades']['quantity'].to_list() == [100, 100, 50]
    assert out['rejections']['reason'].to_list() == ['PARTICIPATION_CAP', 'PARTICIPATION_CAP']
    fresh = replay(**{**source, 'events': pl.from_dicts([event()], schema=EVENT_SCHEMA)})
    assert fresh['trades']['quantity'].to_list() == [100]


@pytest.mark.parametrize('price,quantity', [(90., 217), (100., 0)])
def test_star_minimum_200_and_unit_increment(price, quantity):
    source = fixture(('688001.SH',), prices={'688001.SH': price})
    out = replay(**source)
    assert sum(out['trades']['quantity']) == quantity


def test_dividend_receivable_and_share_distribution_survive_json_checkpoint():
    source = fixture(sessions=DAYS[21:26])
    source['dividends'] = pl.from_dicts([dict(symbol=SYMBOL, ann_date=DAYS[20], record_date=DAYS[21],
        ex_date=DAYS[22], pay_date=DAYS[24], div_cash=.1, share_ratio=.1, share_list_date=DAYS[23])], schema=source['dividends'].schema)
    whole = replay(**source)
    first = replay(**{**source, 'sessions': DAYS[21:23]})
    state = json.loads(json.dumps(first['state']))
    second = replay(**{**source, 'sessions': DAYS[23:26]}, account_state=state)
    for key in ['nav', 'trades', 'positions', 'decisions', 'rejections']:
        assert_frame_equal(whole[key], pl.concat([first[key], second[key]], how='vertical_relaxed'))
    assert state == whole['state']
    assert first['nav']['receivable'][-1] == 190.
    assert state['holdings'][SYMBOL]['quantity'] == 2090


def test_future_append_and_price_perturbation_cannot_change_prefix():
    source = fixture(sessions=DAYS[21:24])
    original = replay(**source)
    future = event(index=50)
    source['events'] = pl.concat([source['events'], pl.from_dicts([future], schema=EVENT_SCHEMA)])
    source['bars'] = source['bars'].with_columns([
        pl.when(pl.col('trade_date') >= DAYS[24]).then(1000.).otherwise(pl.col(c)).alias(c)
        for c in ('open', 'high', 'low', 'close')])
    changed = replay(**source)
    for key in ['nav', 'trades', 'decisions', 'positions']:
        assert_frame_equal(original[key], changed[key])


def test_latest_weekend_announcement_wins_without_fallback_to_old_selected():
    index = next(i for i in range(21, 40) if DAYS[i].weekday() == 0)
    old, latest = event(index=index), event(index=index)
    latest.update(announcement_date=DAYS[index] - dt.timedelta(days=1), selected=False)
    source = fixture(events=[old, latest], sessions=[DAYS[index]])
    out = replay(**source)
    assert out['trades'].is_empty()
    assert 'SUPERSEDED_SAME_EXECUTION_EVENT' in out['decisions']['reason']
    control = replay(**{**source, 'case': 'all_events'})
    assert control['trades'].height == 1
    assert str(latest['announcement_date']) in control['state']['pead_books'][SYMBOL]['event_keys'][0]
    submitted = control['decisions'].filter(pl.col('reason') == 'ORDER_SUBMITTED').row(0, named=True)
    assert submitted['order_as_of'] == latest['announcement_date']
    assert submitted['signal_price_date'] == DAYS[index - 1]


def test_unknown_partial_suspension_coverage_is_explicit_not_silently_complete():
    source = fixture(sessions=[DAYS[21]])
    out = replay(**source)
    assert out['trades']['suspension_coverage_complete'].to_list() == [False]
    assert out['nav']['uncovered_fill_count'].to_list() == [1]
    source['config']['execution']['suspension_policy'] = 'require_daily_coverage'
    strict = replay(**source)
    assert strict['trades'].is_empty()
    assert strict['rejections']['reason'].to_list() == ['UNKNOWN_SUSPENSION_COVERAGE']


def test_unknown_held_delisting_fails_without_mutating_checkpoint():
    source = fixture(events=[], sessions=[DAYS[21]])
    source['instruments'] = source['instruments'].with_columns(pl.lit(DAYS[20]).alias('delist_date'), pl.lit('DELISTED').alias('status'))
    state = seed({SYMBOL: dict(quantity=100, mark_price=10.)}, expiry=61)
    before = copy.deepcopy(state)
    with pytest.raises(ValueError, match='UNCLASSIFIED_HELD_DELISTING'):
        replay(**source, account_state=state)
    assert state == before


def test_retired_instrument_is_not_removed_from_historical_trading_universe():
    source = fixture(sessions=[DAYS[21]])
    source['instruments'] = source['instruments'].with_columns(pl.lit(DAYS[90]).alias('delist_date'), pl.lit('DELISTED').alias('status'))
    assert replay(**source)['trades'].height == 1


@pytest.mark.parametrize('multiplier', [.5, 1., 2.])
def test_cost_floor_scaling_and_tail_holding_retained(multiplier):
    source = fixture(sessions=[DAYS[21]])
    out = replay(**{**source, 'cost_multiplier': multiplier})
    assert out['trades']['fee'].item() == multiplier
    assert SYMBOL in out['state']['holdings']
    assert out['state']['pead_books'][SYMBOL]['expiry_date'] == str(DAYS[61])


def test_duplicate_source_rows_and_wrong_checkpoint_fail_closed():
    source = fixture()
    with pytest.raises(ValueError, match='Duplicate bar'):
        replay(**{**source, 'bars': pl.concat([source['bars'], source['bars'].head(1)])})
    state = seed({}, day=19)
    with pytest.raises(ValueError, match='previous exchange session'):
        replay(**source, account_state=state)
