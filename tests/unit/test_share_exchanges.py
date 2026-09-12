import copy
import datetime as dt
from pathlib import Path
import tomllib

import polars as pl
from polars.testing import assert_frame_equal
import pytest

from quant.backtest import DailyMarketState
from quant.backtest.share_exchanges import validate_exchanges
from quant.research.classic_monthly_baseline import replay
from tests.unit.test_paper_ledger import inputs, D1, D2, D3

OLD, NEW = '000418.SZ', '000333.SZ'
D0 = D1 - dt.timedelta(days=1)


def fixture(*, allocation='floor', existing=0, tradable=D2):
    source, _ = inputs()
    event = {'from_symbol': OLD, 'to_symbol': NEW, 'announcement_date': D0,
        'record_date': D1, 'effective_date': D2, 'tradable_date': tradable,
        'ratio': '1.15144821', 'fractional_allocation': allocation}
    source['config'] = {'portfolio': {'initial_cash': 1000. + 400*57.39 + existing*50.,
        'delisted_holding_recovery': 0.}, 'costs': source['config']['costs'], 'share_exchanges': [event]}
    source['calendar'] = pl.concat([source['calendar'].head(1).with_columns(
        pl.lit('SZ').alias('market'), pl.lit(d).alias('date')) for d in (D0, D1, D2, D3)])
    source['instruments'] = pl.concat([source['instruments'].with_columns(
        pl.lit(s).alias('symbol'), pl.lit('SZ').alias('market'), pl.lit('STOCK').alias('instrument_type'),
        pl.lit(D2 if s == OLD else None, dtype=pl.Date).alias('delist_date')) for s in (OLD, NEW)])
    source['bars'] = pl.concat([source['bars'].head(1).with_columns(pl.lit(s).alias('symbol'),
        pl.lit(d).alias('trade_date'), *[pl.lit(price).alias(c) for c in ('open', 'high', 'low', 'close')])
        for s, d, price in [(OLD, D1, 57.39), (NEW, D1, 52.), (NEW, D2, 52.11), (NEW, D3, 52.18)]])
    source['dividends'] = source['dividends'].with_columns(pl.lit(OLD).alias('symbol'),
        pl.lit(D0).alias('ann_date'), pl.lit(D0).alias('record_date'), pl.lit(D1).alias('ex_date'))
    source['market_states'] = {(d, s): DailyMarketState(suspended=s == OLD and d > D1)
                               for d in (D1, D2, D3) for s in (OLD, NEW)}
    source['targets'] = pl.DataFrame(schema={'as_of': pl.Date, 'execution_date': pl.Date,
        'symbol': pl.String, 'strategy': pl.String, 'strategy_version': pl.String, 'weight': pl.Float64})
    source.update(sessions=[D1, D2, D3], name='probe', validate_once=True)
    holdings = {OLD: {'quantity': 400, 'mark_price': 57.39}}
    if existing:
        holdings[NEW] = {'quantity': existing, 'mark_price': 50.}
    state = {'date': str(D0), 'cash': 1000., 'holdings': holdings, 'receivables': [], 'pending': [],
        'nav': [], 'inception_date': str(D0), 'started_with_cash': True}
    return source, state


@pytest.mark.parametrize(('allocation', 'quantity'), [('floor', 460), ('ceil', 461)])
def test_exchange_before_writeoff_preserves_dividend_and_charges_no_trade(allocation, quantity):
    source, state = fixture(allocation=allocation)
    nav, trades, rejects = replay(**source, account_state=state)
    assert trades.is_empty() and rejects.is_empty()
    assert OLD not in state['holdings'] and state['holdings'][NEW]['quantity'] == quantity
    assert nav['delisting_writeoff'].sum() == 0
    assert nav['share_exchange_count'].to_list() == [0, 1, 0]
    assert nav['cumulative_fees'].sum() == 0
    assert nav['receivable'].to_list() == [400., 400., 0.]
    assert state['cash'] == 1400.
    assert nav['equity'][-1] == pytest.approx(1400. + quantity*52.18)
    assert len(state['share_exchange_history']) == 1
    assert state['share_exchange_history'][0]['old_quantity'] == 400


def test_existing_successor_is_added_and_record_date_survives_chunk_restart():
    source, state = fixture(existing=200)
    whole = copy.deepcopy(state)
    result = replay(**source, account_state=whole)
    parts = []
    for dates in ([D1], [D2, D3]):
        parts.append(replay(**{**source, 'sessions': dates}, account_state=state))
    assert state == whole and state['holdings'][NEW]['quantity'] == 660
    for i, frame in enumerate(result):
        assert_frame_equal(frame, pl.concat([p[i] for p in parts], how='vertical_relaxed'), check_exact=True)


def test_fractional_lot_exit_waits_for_share_listing_then_sells_all():
    source, state = fixture(tradable=D3)
    source['targets'] = pl.DataFrame([{'as_of': d-dt.timedelta(days=1), 'execution_date': d,
        'symbol': NEW, 'strategy': 'probe', 'strategy_version': '1', 'weight': 0.} for d in (D2, D3)])
    _, trades, rejects = replay(**source, account_state=state)
    assert trades.select('date', 'symbol', 'side', 'quantity').rows() == [(D3, NEW, 'SELL', 460)]
    assert rejects.height == 1 and rejects['date'][0] == D2
    assert not state['holdings']


def test_missing_record_snapshot_is_rejected_without_mutating_caller():
    source, state = fixture()
    state['date'] = str(D1)
    original = copy.deepcopy(state)
    with pytest.raises(ValueError, match='record-date holdings'):
        replay(**{**source, 'sessions': [D2, D3]}, account_state=state)
    assert state == original


def test_no_exchange_config_preserves_legacy_writeoff_and_original_account_path():
    source, state = fixture()
    source['config'].pop('share_exchanges')
    old = copy.deepcopy(state)
    a = replay(**source, account_state=state)
    b = replay(**{**source, 'config': {**source['config'], 'share_exchanges': []}}, account_state=old)
    assert old == state
    for left, right in zip(a, b, strict=True):
        assert_frame_equal(left, right, check_exact=True)
    assert a[0]['delisting_writeoff'].sum() == 22956.


def test_final_public_terms_and_invalid_future_or_duplicate_terms():
    events = tomllib.loads(Path('configs/data/share_exchanges_20260912.toml').read_text())['share_exchanges']
    assert validate_exchanges(events)[0]['ratio'] == '1.15144821'
    assert events[0]['record_date'] == dt.date(2019, 6, 20)
    with pytest.raises(ValueError, match='Duplicate'):
        validate_exchanges(events * 2)
    with pytest.raises(ValueError, match='Invalid'):
        validate_exchanges([{**events[0], 'announcement_date': dt.date(2019, 6, 22)}])


def test_attribution_reconciles_exchange_without_fabricated_security_gain_or_loss():
    from quant.reporting.lagged_exposure import reconstruct
    source, state = fixture(existing=200)
    initial = copy.deepcopy(state)
    nav, trades, _ = replay(**source, account_state=state)
    detail, daily = reconstruct(nav=nav, trades=trades, bars=source['bars'],
        dividends=source['dividends'], calendar=source['calendar'], initial=initial,
        share_exchanges=source['config']['share_exchanges'])
    assert daily['market_value_difference'].abs().max() < 1e-8
    assert daily['residual_pnl'].abs().max() < 1e-8
    assert detail.filter((pl.col('date') == D2) & (pl.col('symbol') == OLD))['pnl'].item() == 0.
    assert detail.filter((pl.col('date') == D2) & (pl.col('symbol') == NEW))['pnl'].item() == pytest.approx(660*52.11 - 200*52 - 22956)


def test_exchange_day_predecessor_target_requires_explicit_mapping():
    source, state = fixture()
    source['targets'] = pl.DataFrame([{'as_of': D1, 'execution_date': D2,
        'symbol': OLD, 'strategy': 'probe', 'strategy_version': '1', 'weight': .5}])
    with pytest.raises(ValueError, match='explicit successor mapping'):
        replay(**source, account_state=state)
