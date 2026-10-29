import datetime as dt
import hashlib
import json
import os

import polars as pl
import pytest

from quant.research import daily_market_context as context
from quant.data import market_snapshot


TZ = dt.timezone(dt.timedelta(hours=8))
DAY = dt.date(2026, 10, 26)
NOW = dt.datetime(2026, 10, 27, 8, 30, tzinfo=TZ)
CHECKS = ('bars_duplicate_keys', 'bars_missing_keys', 'daily_basic_duplicate_keys',
          'daily_basic_missing_keys', 'adjustment_duplicate_keys', 'adjustment_missing_keys',
          'close_mismatches', 'invalid_adjustments')


def evidence(tmp_path):
    record = tmp_path/'daily/2026-10-26_223000/summary.json'
    refresh = record.parent/'model/refresh.json'
    refresh.parent.mkdir(parents=True)
    inputs = dict(latest_session=str(DAY), intraday_errors=[], input_quality=dict(
        as_of=str(DAY), errors=[], stocks=dict(expected_sessions=5, latest_traded_symbols=5217,
            missing_sessions=[], **dict.fromkeys(CHECKS, 0))))
    refresh.write_text(json.dumps(inputs))
    summary = dict(as_of=str(DAY), status='incomplete', rehearsal=False, saved_data=False,
        auto_trade=False, stages=dict(refresh=dict(status='complete', mode='refresh',
            input_errors=[], path=str(refresh)), signal_monitor=dict(status='incomplete',
                result=dict(status='partial', forward_scored_series_months=0))))
    record.write_text(json.dumps(summary))
    (record.parent/'scheduler.json').write_text('{"exit_code":1}')
    for path in (record, refresh):
        os.utime(path, (NOW.timestamp()-100, NOW.timestamp()-100))
    return record, refresh, summary, inputs


def test_independent_inputs_do_not_claim_daily_or_monitor_completion(tmp_path):
    record, refresh, summary, _ = evidence(tmp_path)
    receipt = context.market_data_observation(DAY, NOW, record.parent.parent, record)
    assert receipt['kind'] == 'verified_market_inputs'
    assert receipt['daily_status'] == receipt['signal_monitor_status'] == 'incomplete'
    assert receipt['refresh_sha256'] == hashlib.sha256(refresh.read_bytes()).hexdigest()
    assert json.loads(record.read_text()) == summary
    with pytest.raises(ValueError):
        context.completed_observation(DAY, NOW, record.parent.parent, record)


def test_late_record_directory_is_discovered_by_payload_session(tmp_path):
    record,refresh,summary,_=evidence(tmp_path)
    late=record.parent.with_name('2026-10-27_081000')
    record.parent.rename(late)
    record=late/'summary.json'
    refresh=late/'model/refresh.json'
    summary['stages']['refresh']['path']=str(refresh)
    record.write_text(json.dumps(summary))
    os.utime(record,(NOW.timestamp()-10,NOW.timestamp()-10))
    result=context.market_data_observation(DAY,NOW,late.parent)
    assert result['path']==str(record)
    assert result['kind']=='verified_market_inputs'


@pytest.mark.parametrize('complete', [False, True])
@pytest.mark.parametrize('unrelated', ['broken_summary', 'other_session_broken_scheduler'])
def test_unrelated_bad_receipt_does_not_hide_exact_session_evidence(tmp_path, complete, unrelated):
    record, _, summary, _ = evidence(tmp_path)
    if complete:
        summary['status'] = 'complete'
        record.write_text(json.dumps(summary))
        (record.parent/'scheduler.json').write_text('{"exit_code":0}')
        os.utime(record, (NOW.timestamp()-10, NOW.timestamp()-10))
    other = record.parent.parent/'2026-10-28_001000'
    other.mkdir()
    if unrelated == 'broken_summary':
        (other/'summary.json').write_text('{interrupted')
    else:
        (other/'summary.json').write_text(json.dumps(dict(summary, as_of='2026-10-23')))
        (other/'scheduler.json').write_text('{interrupted')
    os.utime(other/'summary.json', (NOW.timestamp()-5, NOW.timestamp()-5))
    lookup = context.completed_observation if complete else context.market_data_observation
    assert lookup(DAY, NOW, record.parent.parent)['path'] == str(record)
    # An explicitly bound broken receipt must never be silently replaced.
    with pytest.raises(ValueError):
        lookup(DAY, NOW, record.parent.parent, other/'summary.json')


@pytest.mark.parametrize('bad', ['wrong_session', 'quality_session', 'saved_data', 'rehearsal',
    'failed_daily', 'saved_mode', 'stage_errors', 'quality_errors', 'missing_sessions',
    'future_refresh', 'wrong_path', 'no_refresh', 'no_stocks', *CHECKS])
def test_unverified_market_inputs_cannot_unlock_publication(tmp_path, bad):
    record, refresh, summary, inputs = evidence(tmp_path)
    if bad == 'wrong_session': inputs['latest_session'] = '2026-10-23'
    elif bad == 'quality_session': inputs['input_quality']['as_of'] = '2026-10-23'
    elif bad in ('saved_data', 'rehearsal'): summary[bad] = True
    elif bad == 'failed_daily': summary['status'] = 'failed'
    elif bad == 'saved_mode': summary['stages']['refresh']['mode'] = 'saved_data'
    elif bad == 'stage_errors': summary['stages']['refresh']['input_errors'] = ['bad']
    elif bad == 'quality_errors': inputs['input_quality']['errors'] = ['bad']
    elif bad == 'missing_sessions': inputs['input_quality']['stocks']['missing_sessions'] = ['2026-10-26']
    elif bad == 'wrong_path': summary['stages']['refresh']['path'] = str(tmp_path/'other.json')
    elif bad == 'no_stocks': inputs['input_quality']['stocks']['latest_traded_symbols'] = 0
    elif bad in CHECKS: inputs['input_quality']['stocks'][bad] = 1
    record.write_text(json.dumps(summary)); refresh.write_text(json.dumps(inputs))
    for path in (record, refresh): os.utime(path, (1, 1))
    if bad == 'future_refresh': os.utime(refresh, (NOW.timestamp()+1, NOW.timestamp()+1))
    if bad == 'no_refresh': refresh.unlink()
    with pytest.raises(ValueError):
        context.market_data_observation(DAY, NOW, record.parent.parent, record)


def test_publication_and_quote_reference_accept_verified_inputs_but_detect_change(tmp_path, monkeypatch):
    record, refresh, summary, _ = evidence(tmp_path)
    data = tmp_path/'data'; calendar = data/'clean/trade_calendar/market=SH/data.parquet'
    calendar.parent.mkdir(parents=True)
    pl.DataFrame({'date': [DAY, NOW.date()], 'is_open': [True, True]}).write_parquet(calendar)

    def history(config, output, **kwargs):
        output.mkdir(parents=True)
        pl.DataFrame(dict(trade_date=[DAY], effective_date=[NOW.date()], market_state=['trend_down'],
            coverage=[0.999], reference_stocks=[5222])).write_parquet(output/'market_states.parquet')
        pl.DataFrame(dict(symbol=['600000.SH'], trade_date=[DAY])).write_parquet(output/'latest_reference.parquet')
        for name in ('summary.json', 'source_manifest.json'): (output/name).write_text('{}')
        (output/'report.md').write_text('fixture')

    monkeypatch.setattr(context, 'history', history)
    root = tmp_path/'context'
    result = context.run(data_root=data, root=root, now=NOW, require_daily_receipt=True,
                         daily_root=record.parent.parent)
    assert result['status'] == 'complete' and result['daily_completion'] is None
    assert result['market_data_completion']['daily_status'] == 'incomplete'
    assert market_snapshot._reference(root/'latest.json', data, NOW)[3] == ['600000.SH']
    assert json.loads(record.read_text()) == summary
    refresh.write_text(refresh.read_text()+' '); os.utime(refresh, (1, 1))
    with pytest.raises(ValueError, match='changed'):
        market_snapshot._reference(root/'latest.json', data, NOW)


@pytest.mark.parametrize('clock,allowed', [
    ('2026-10-26T14:59:59+08:00', False),
    ('2026-10-26T15:00:00+08:00', True),
    ('2026-10-26T21:30:00+08:00', True),
])
def test_evening_history_accepts_same_session_only_after_close(tmp_path, monkeypatch, clock, allowed):
    from types import SimpleNamespace
    from quant.research import market_indicators_run as indicators
    fixed = dt.datetime.fromisoformat(clock)

    class Clock(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed

    monkeypatch.setattr(indicators, 'dt', SimpleNamespace(datetime=Clock, time=dt.time, timedelta=dt.timedelta))
    refresh = tmp_path/'refresh.toml'; refresh.write_text('factor_benchmark_snapshot="fixture"')
    monkeypatch.setattr(indicators, 'load_config', lambda config: dict(
        refresh_config=str(refresh), benchmark_snapshot='from_refresh_config'))

    def read_benchmark(*args):
        raise RuntimeError('Reached source read after completed-close check')

    monkeypatch.setattr(indicators, 'read_benchmark', read_benchmark)
    config = tmp_path/'config.toml'; config.write_text('')
    with pytest.raises(RuntimeError if allowed else ValueError,
                       match='Reached source read' if allowed else 'completed exchange close'):
        indicators.history(config, tmp_path/'output', start=DAY, end=DAY, data_root=tmp_path/'data')
