import copy
import json

import polars as pl
from polars.testing import assert_frame_equal
import pytest

from quant.research.pead_account_replay import replay
from tests.unit.test_pead_account_replay import DAYS, fixture, seed


def exchange_source(*, existing=False):
    old, new = '000522.SZ', '600332.SH'
    source = fixture((old, new), events=[], sessions=DAYS[21:26], prices={old: 20., new: 40.})
    source['instruments'] = source['instruments'].with_columns(
        pl.when(pl.col('symbol') == old).then(pl.lit(DAYS[22])).otherwise(pl.col('delist_date')).alias('delist_date'))
    source['bars'] = source['bars'].filter(~((pl.col('symbol') == old) & (pl.col('trade_date') >= DAYS[21])))
    source['config']['share_exchanges'] = [dict(from_symbol=old, to_symbol=new,
        announcement_date=DAYS[20], record_date=DAYS[22], effective_date=DAYS[22], tradable_date=DAYS[25],
        ratio='0.95', fractional_allocation='floor', record_capture='opening_holdings_same_day_suspended',
        valuation_until_tradable='predecessor_book_value',
        account_registration_assumption='normal_account_confirmed_initial_registration')]
    holdings = {old: dict(quantity=1000, mark_price=20.)}
    if existing:
        holdings[new] = dict(quantity=100, mark_price=40.)
    state = seed(holdings, expiry=23)
    if existing:
        state['pead_books'][new]['expiry_date'] = str(DAYS[26])
    return source, state


def test_unlisted_exchange_receivable_keeps_book_value_until_delivery_and_expiry():
    source, state = exchange_source()
    out = replay(**source, account_state=state)
    assert out['nav']['equity'].to_list()[:4] == [100000.] * 4
    assert out['nav']['exchange_pending_value'].to_list() == [0., 20000., 20000., 20000., 0.]
    assert out['trades'].select('date', 'symbol', 'side', 'quantity').rows() == [(DAYS[25], '600332.SH', 'SELL', 950)]
    assert out['nav']['equity'][-1] == pytest.approx(117999.)
    assert state['pead_books']['600332.SH']['expiry_date'] == str(DAYS[23])
    waiting = out['positions'].filter(pl.col('date') == DAYS[24]).row(0, named=True)
    assert waiting['quantity'] == 950 and waiting['settled_quantity'] == 0
    assert waiting['market_value'] == 20000.
    assert out['decisions'].filter(pl.col('reason') == 'WAIT_EXCHANGE_SHARE_LISTING').height == 2


def test_merge_into_existing_successor_uses_earliest_expiry_without_marking_pending_stock():
    source, state = exchange_source(existing=True)
    out = replay(**source, account_state=state)
    assert out['nav']['equity'].to_list()[:2] == [100000., 100000.]
    conversion = out['positions'].filter(pl.col('date') == DAYS[22]).row(0, named=True)
    assert conversion['market_value'] == 24000.
    assert conversion['settled_quantity'] == 100 and conversion['exchange_pending_quantity'] == 950
    assert out['trades'].select('date', 'quantity').rows() == [(DAYS[23], 100), (DAYS[25], 950)]
    assert len(state['pead_books']['600332.SH']['event_keys']) == 2


def test_exchange_entitlement_checkpoint_matches_continuous_account_exactly():
    source, initial = exchange_source(existing=True)
    whole = replay(**source, account_state=copy.deepcopy(initial))
    first = replay(**{**source, 'sessions': DAYS[21:24]}, account_state=copy.deepcopy(initial))
    restored = json.loads(json.dumps(first['state']))
    second = replay(**{**source, 'sessions': DAYS[24:26]}, account_state=restored)
    assert restored == whole['state']
    for key in ('nav', 'trades', 'rejections', 'positions', 'decisions'):
        assert_frame_equal(whole[key], pl.concat([first[key], second[key]], how='vertical_relaxed'))


def test_missing_listing_day_band_carries_delivered_shares_and_retries_next_session():
    source, state = exchange_source()
    source['sessions'] = DAYS[21:27]
    source['limits'] = source['limits'].filter(~((pl.col('symbol') == '600332.SH') & (pl.col('trade_date') == DAYS[25])))
    out = replay(**source, account_state=state)
    assert out['trades']['date'].to_list() == [DAYS[26]]
    assert out['rejections'].filter(pl.col('reason') == 'UNKNOWN_PRICE_BAND').height == 1
    assert out['nav'].filter(pl.col('date') == DAYS[25])['position_count'].item() == 1


def test_same_day_exchange_cannot_claim_normal_registration_or_suspension_implicitly():
    source, state = exchange_source()
    source['config']['share_exchanges'][0]['account_registration_assumption'] = 'unknown'
    with pytest.raises(ValueError, match='Unregistered same-day'):
        replay(**source, account_state=state)
    source, state = exchange_source()
    source['bars'] = pl.concat([source['bars'], source['bars'].filter(pl.col('symbol') == '600332.SH').head(1)
        .with_columns(pl.lit('000522.SZ').alias('symbol'), pl.lit(DAYS[22]).alias('trade_date'))])
    with pytest.raises(ValueError, match='whole-day suspended'):
        replay(**source, account_state=state)


def test_ordinary_000418_exchange_uses_record_snapshot_and_preserves_expiry():
    old, new = '000418.SZ', '000333.SZ'
    source = fixture((old, new), events=[], sessions=DAYS[21:25])
    source['config']['share_exchanges'] = [dict(from_symbol=old, to_symbol=new,
        announcement_date=DAYS[20], record_date=DAYS[21], effective_date=DAYS[22], tradable_date=DAYS[22],
        ratio='1.15144821', fractional_allocation='floor')]
    source['instruments'] = source['instruments'].with_columns(
        pl.when(pl.col('symbol') == old).then(pl.lit(DAYS[21])).otherwise(pl.col('delist_date')).alias('delist_date'))
    state = seed({old: dict(quantity=400, mark_price=10.)}, expiry=23)
    out = replay(**source, account_state=state)
    assert out['trades'].select('date', 'symbol', 'side', 'quantity').rows() == [(DAYS[23], new, 'SELL', 460)]
    assert len(state['share_exchange_history']) == 1
    assert state['pead_books'][new]['expiry_date'] == str(DAYS[23])


def test_old_closed_successor_lineage_does_not_expire_new_conversion_prematurely():
    source, state = exchange_source()
    state['pead_books']['600332.SH'] = dict(expiry_date=str(DAYS[10]), event_keys=['closed_old_trade'])
    out = replay(**source, account_state=state)
    assert out['state']['pead_books']['600332.SH']['expiry_date'] == str(DAYS[23])
    assert 'closed_old_trade' not in out['state']['pead_books']['600332.SH']['event_keys']
