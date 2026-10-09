import datetime as dt

import polars as pl
import pytest

from quant.backtest.rules import DailyMarketState, execution_reject_reason
from quant.data.stock_execution_inputs import stock_session_states
from quant.data.stock_open_suspensions import POLICY, build_open_facts, classify_open
from quant.domain.enums import ExecutionRejectReason, OrderSide

DAY = dt.date(2018, 2, 1)


@pytest.mark.parametrize('versions,volume,status,reason', [
    ([('S', '13:00-15:00')], 100., 'clear_at_open', 'all_reported_intervals_start_after_open'),
    ([('S', '09:30-10:00')], 100., 'halt_at_open', 'interval_includes_open'),
    ([('S', '9:30-9:40')], 100., 'halt_at_open', 'interval_includes_open'),
    ([('S', '09:31-09:41,09:42-09:52')], 100., 'clear_at_open', 'all_reported_intervals_start_after_open'),
    ([('S', '10:05:50-10:15:50')], 100., 'clear_at_open', 'all_reported_intervals_start_after_open'),
    ([('S', None)], 100., 'unknown', 'full_day_positive_volume_conflict'),
    ([('S', '')], 100., 'unknown', 'empty_timing_not_proven_full_day'),
    ([('S', None)], 0., 'halt_at_open', 'reported_full_day'),
    ([('S', None)], None, 'halt_at_open', 'reported_full_day'),
    ([('S', None)], float('nan'), 'unknown', 'invalid_daily_volume'),
    ([('S', '13:00-15:00'), ('S', None)], 100., 'unknown', 'conflicting_source_records'),
    ([('S', '13:00-15:00'), ('R', None)], 100., 'unknown', 'conflicting_source_records'),
    ([('S', 'bad-timing')], 100., 'unknown', 'unparsed_suspension_timing'),
    ([('S', '15:00-13:00')], 100., 'unknown', 'unparsed_suspension_timing'),
    ([('S', '09:00-09:29')], 100., 'unknown', 'premarket_interval_open_unestablished'),
    ([('S', '09:00-09:30')], 100., 'halt_at_open', 'interval_includes_open'),
    ([], 100., 'unknown', 'missing_original_detail'),
])
def test_open_timing_does_not_use_daily_volume_to_rescue_unknown_or_morning_halts(versions, volume, status, reason):
    assert classify_open(versions, volume) == (status, reason)


def fixture():
    symbols = ['afternoon', 'morning', 'unknown', 'at_limit']
    keys = pl.DataFrame({'symbol': symbols, 'trade_date': [DAY]*4})
    bars = keys.with_columns(pl.lit(10.).alias('open'), pl.lit(100.).alias('volume'))
    limits = keys.with_columns(pl.when(pl.col('symbol') == 'at_limit').then(10.).otherwise(11.).alias('up_limit'),
        pl.lit(9.).alias('down_limit'))
    details = keys.with_columns(pl.lit('S').alias('suspend_type'),
        pl.Series('suspend_timing', ['13:00-15:00', '09:30-10:00', None, '13:00-15:00']),
        pl.lit('original_receipt').alias('source_path'))
    facts = build_open_facts(keys, details, bars)
    args = dict(bars=bars, limits=limits, sessions=[DAY], symbols=symbols, execution_dates=[DAY], slippage=0.)
    return keys, facts, args


def test_versioned_dispatch_preserves_old_binary_behavior_and_original_price_bands():
    keys, facts, args = fixture()
    old = stock_session_states(suspensions=keys, **args)
    new = stock_session_states(suspensions=facts.filter(pl.col('open_status') != 'clear_at_open'), **args)
    assert all(state.suspended and not state.open_unknown for state in old.values())
    assert not new[DAY, 'afternoon'].suspended and not new[DAY, 'afternoon'].open_unknown
    assert new[DAY, 'morning'].suspended
    assert new[DAY, 'unknown'].open_unknown and not new[DAY, 'unknown'].suspended
    assert new[DAY, 'at_limit'].at_upper_limit
    def reject(symbol):
        return execution_reject_reason(side=OrderSide.BUY, quantity=100, settled_quantity=0,
            state=new[DAY, symbol], enforce_t_plus_one=True)
    assert reject('afternoon') is None
    assert reject('morning') is ExecutionRejectReason.SUSPENDED
    assert reject('unknown') is ExecutionRejectReason.OPEN_UNKNOWN
    assert reject('at_limit') is ExecutionRejectReason.BUY_AT_UPPER_LIMIT
    assert facts.filter(pl.col('symbol') == 'unknown')['source_paths'].item().to_list() == ['original_receipt']


def test_versioned_clear_cases_still_require_real_price_bands():
    _, facts, args = fixture()
    args['limits'] = args['limits'].clear()
    with pytest.raises(ValueError, match='Missing stock price band'):
        stock_session_states(suspensions=facts.filter(pl.col('open_status') != 'clear_at_open'), **args)


def test_unknown_input_version_and_unfiltered_clear_keys_fail_closed():
    _, facts, args = fixture()
    with pytest.raises(ValueError, match='policy'):
        stock_session_states(suspensions=facts, **args)
    invalid = facts.filter(pl.col('open_status') != 'clear_at_open').with_columns(pl.lit('other').alias('suspension_policy'))
    with pytest.raises(ValueError, match='policy'):
        stock_session_states(suspensions=invalid, **args)


def test_source_disagreement_remains_visible_and_unknown():
    keys, facts, args = fixture()
    key = keys.filter(pl.col('symbol') == 'afternoon')
    one = key.with_columns(pl.lit('S').alias('suspend_type'), pl.lit('13:00-15:00').alias('suspend_timing'),
        pl.lit('receipt_one').alias('source_path'))
    two = one.with_columns(pl.lit(None, dtype=pl.String).alias('suspend_timing'), pl.lit('receipt_two').alias('source_path'))
    result = build_open_facts(key, pl.concat([one, two]), args['bars'])
    assert result['open_status'].item() == 'unknown'
    assert result['source_variants'].item() == 2
    assert result['source_paths'].item().to_list() == ['receipt_one', 'receipt_two']


def test_open_unknown_is_rejected_before_any_other_execution_rule():
    assert execution_reject_reason(side=OrderSide.SELL, quantity=100, settled_quantity=0,
        state=DailyMarketState(open_unknown=True), enforce_t_plus_one=True) is ExecutionRejectReason.OPEN_UNKNOWN
