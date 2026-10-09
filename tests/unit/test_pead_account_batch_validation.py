import copy
import datetime as dt
import hashlib
import json
from pathlib import Path
import time

import pandera.config as pa_config
import polars as pl
from polars.testing import assert_frame_equal
import pytest

from quant.backtest import daily_account, daily_simulator
from quant.research.pead_account_batch_validation import _validate_outputs, replay_batched
from quant.research.pead_account_replay import event_priority, replay
from tests.unit.test_pead_account_actions import exchange_source
from tests.unit.test_pead_account_replay import DAYS, SYMBOL, event, fixture, seed


def scenario(kind):
    source = fixture(sessions=DAYS[21:26])
    if kind == 'dividends':
        source['dividends'] = pl.from_dicts([dict(symbol=SYMBOL, ann_date=DAYS[20], record_date=DAYS[21],
            ex_date=DAYS[22], pay_date=DAYS[24], div_cash=.1, share_ratio=.1, share_list_date=DAYS[23])],
            schema=source['dividends'].schema)
    elif kind == 'missing_bar':
        source['bars'] = source['bars'].filter(pl.col('trade_date') != DAYS[21])
    elif kind == 'manual_rejection':
        source['limits'] = source['limits'].filter(pl.col('trade_date') != DAYS[21])
    elif kind == 'zero_quantity_rejection':
        source = fixture(('688001.SH',), prices={'688001.SH': 100.})
    elif kind == 'partial_cap':
        source['bars'] = source['bars'].with_columns(pl.lit(20000.).alias('amount'))
    elif kind == 'conversion':
        source, source['account_state'] = exchange_source(existing=True)
    elif kind != 'normal':
        raise ValueError(kind)
    return source


def equal_results(reference, batched):
    assert reference.keys() == batched.keys()
    for key in ('nav', 'trades', 'rejections', 'positions', 'decisions', 'actions'):
        assert_frame_equal(reference[key], batched[key], check_exact=True)
    assert reference['state'] == batched['state']


@pytest.mark.parametrize('kind', ['normal', 'dividends', 'missing_bar', 'manual_rejection',
                                  'zero_quantity_rejection', 'partial_cap', 'conversion'])
@pytest.mark.parametrize('multiplier', [.5, 1., 2.])
def test_all_published_frames_and_checkpoint_exactly_equal(kind, multiplier):
    source = scenario(kind)
    source['cost_multiplier'] = multiplier
    reference = replay(**copy.deepcopy(source))
    batched = replay_batched(**copy.deepcopy(source))
    equal_results(reference, batched)


def test_batch_checkpoint_json_restart_keeps_dividends_and_original_full_state():
    source = scenario('dividends')
    whole = replay(**copy.deepcopy(source))
    first = replay_batched(**{**source, 'sessions': DAYS[21:23]})
    state = json.loads(json.dumps(first['state']))
    second = replay_batched(**{**source, 'sessions': DAYS[23:26]}, account_state=state)
    assert state == whole['state']
    for key in ('nav', 'trades', 'rejections', 'positions', 'decisions'):
        assert_frame_equal(whole[key], pl.concat([first[key], second[key]], how='vertical_relaxed'), check_exact=True)


def test_batch_wrapper_preserves_non_schema_admission_and_context_on_error():
    source = fixture(events=[], sessions=[DAYS[21]])
    source['instruments'] = source['instruments'].with_columns(pl.lit(DAYS[20]).alias('delist_date'), pl.lit('DELISTED').alias('status'))
    state = seed({SYMBOL: dict(quantity=100, mark_price=10.)}, expiry=61)
    original = copy.deepcopy(state)
    before = pa_config.get_config_context()
    functions = (daily_account.advance, daily_simulator.simulate_daily_targets, daily_simulator._validate_orders)
    with pytest.raises(ValueError, match='UNCLASSIFIED_HELD_DELISTING'):
        replay_batched(**source, account_state=state)
    assert state == original
    assert pa_config.get_config_context() == before
    assert functions == (daily_account.advance, daily_simulator.simulate_daily_targets, daily_simulator._validate_orders)


def test_does_not_accept_invalid_input_even_when_caller_validation_is_disabled():
    source = fixture()
    source['bars'] = source['bars'].with_columns(pl.lit(-1.).alias('high'))
    with pa_config.config_context(validation_enabled=False):
        with pytest.raises(Exception, match='ohlc_valid|greater_than'):
            replay_batched(**source)
        assert pa_config.get_config_context().validation_enabled is False


def test_no_silent_canonicalization_of_changed_source_dtype():
    source = fixture()
    source['bars'] = source['bars'].with_columns(pl.col('open').cast(pl.Float32))
    with pytest.raises(ValueError, match='canonical bars'):
        replay_batched(**source)


@pytest.mark.parametrize('corruption', ['nav', 'trade', 'position', 'manual_reason', 'manual_quantity'])
def test_batch_output_validation_catches_account_and_manual_rejection_corruption(corruption):
    source = scenario('manual_rejection') if corruption.startswith('manual') else scenario('normal')
    output = replay(**source)
    if corruption == 'nav':
        output['nav'] = output['nav'].with_columns((pl.col('equity') + 1.).alias('equity'))
    elif corruption == 'trade':
        output['trades'] = output['trades'].with_columns(pl.lit(float('inf')).alias('fee'))
    elif corruption == 'position':
        output['positions'] = output['positions'].with_columns(pl.lit(-1).alias('settled_quantity'))
    elif corruption == 'manual_reason':
        output['rejections'] = output['rejections'].with_columns(pl.lit('UNRECOGNIZED').alias('reason'))
    else:
        output['rejections'] = output['rejections'].with_columns(pl.lit(0).alias('requested_quantity'), pl.lit(0).alias('rejected_quantity'))
    with pytest.raises(Exception):
        _validate_outputs(output, initial_cash=100000., sessions=source['sessions'])


def fixed_workload():
    """Fixed synthetic workload; no real-market returns or parameter selection."""
    symbols = [f'{i:06}.SZ' for i in range(1, 9)]
    events = [event(s) for s in symbols]
    nominees = sorted(events, key=event_priority)
    source = fixture(symbols, events=events, sessions=DAYS[21:85])
    source['limits'] = source['limits'].filter(~((pl.col('symbol') == nominees[0]['symbol']) & (pl.col('trade_date') == DAYS[21])))
    source['bars'] = source['bars'].filter(~((pl.col('symbol') == nominees[1]['symbol']) & (pl.col('trade_date') == DAYS[23])))
    source['dividends'] = pl.from_dicts([dict(symbol=s, ann_date=DAYS[20], record_date=DAYS[22],
        ex_date=DAYS[23], pay_date=DAYS[25], div_cash=.1, share_ratio=.1, share_list_date=DAYS[24])
        for s in symbols], schema=source['dividends'].schema)
    return source


def run_fixed_timing(output: Path):
    workload = fixed_workload()
    # Both paths see exactly the same already-materialized workload, with no
    # account reuse and no selecting the path by its historical trading returns.
    started = time.perf_counter()
    reference = replay(**copy.deepcopy(workload))
    reference_seconds = time.perf_counter() - started
    started = time.perf_counter()
    batch = replay_batched(**copy.deepcopy(workload))
    batch_seconds = time.perf_counter() - started
    equal_results(reference, batch)
    assert 'UNKNOWN_PRICE_BAND' in reference['rejections']['reason']
    assert reference['nav']['receivable'].max() > 0
    files = [Path('src/quant/research/pead_account_batch_validation.py'),
             Path('src/quant/research/pead_account_replay.py'), Path(__file__)]
    report = dict(created_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
        workload='fixed_synthetic_64_sessions_8_symbols_dividend_missing_bar_and_band_v1',
        sessions=len(workload['sessions']), symbols=8, real_market_data=False,
        reference_seconds=reference_seconds, batch_seconds=batch_seconds,
        reference_over_batch=reference_seconds / batch_seconds,
        exact_equal_outputs=['nav', 'trades', 'rejections', 'positions', 'decisions', 'actions', 'state'],
        source_sha256={str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in files},
        limitations=['One fixed-order timing per path; concurrent production work can affect wall time.',
                     'No real account recomputation and no return/performance claim.',
                     'Not integrated into active runner; requires future explicit code freeze.'])
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise ValueError('Do not overwrite an earlier timing receipt')
    output.write_text(json.dumps(report, indent=2), encoding='utf8')
    return report


def test_fixed_workload_timing_and_equivalence_receipt(tmp_path):
    receipt = run_fixed_timing(tmp_path / 'timing.json')
    assert receipt['sessions'] == 64 and receipt['real_market_data'] is False
    assert receipt['reference_seconds'] > 0 and receipt['batch_seconds'] > 0
