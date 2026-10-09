import datetime as dt
import json
import os

import polars as pl
import pytest

from quant.research import daily_market_context as context

TZ = dt.timezone(dt.timedelta(hours=8))
DAY = dt.date(2026, 9, 30)
NEXT = dt.date(2026, 10, 8)


def inputs(tmp_path, monkeypatch):
    data, root, daily = tmp_path/'data', tmp_path/'context', tmp_path/'daily'
    calendar = data/'clean/trade_calendar/market=SH/data.parquet'
    calendar.parent.mkdir(parents=True)
    pl.DataFrame({'date': [DAY-dt.timedelta(days=1), DAY, NEXT],
                  'is_open': [True, True, True]}).write_parquet(calendar)
    record = daily/'2026-09-30_213000/summary.json'
    record.parent.mkdir(parents=True)
    record.write_text(json.dumps(dict(as_of=str(DAY), status='complete',
                                     rehearsal=False, saved_data=False)))
    known = dt.datetime(2026, 9, 30, 22, 6, tzinfo=TZ).timestamp()
    os.utime(record, (known, known))
    calls = []

    def history(config, output, *, start, end, data_root):
        calls.append(start)
        output.mkdir(parents=True)
        pl.DataFrame({'trade_date': [start], 'effective_date': [NEXT],
                      'market_state': ['trend_down'], 'coverage': [0.99],
                      'reference_stocks': [5000]}).write_parquet(output/'market_states.parquet')
        for name in ['summary.json', 'source_manifest.json']:
            (output/name).write_text('{}')
        (output/'report.md').write_text('Test fixture')

    monkeypatch.setattr(context, 'history', history)
    return dict(data_root=data, root=root, daily_root=daily), record, calls


@pytest.mark.parametrize('clock', ['2026-09-30T22:07:00+08:00',
                                  '2026-10-01T00:20:00+08:00',
                                  '2026-10-02T08:30:00+08:00'])
def test_completed_session_publishes_exact_receipt_across_midnight_and_holiday(tmp_path, monkeypatch, clock):
    args, record, calls = inputs(tmp_path, monkeypatch)
    result = context.run(**args, now=dt.datetime.fromisoformat(clock),
                         completed_session=DAY, daily_record=record)
    assert result['date'] == str(DAY) and result['effective_date'] == str(NEXT)
    assert result['daily_completion']['path'] == str(record)
    assert result['daily_completion']['sha256']
    assert result['status'] == 'complete' and calls == [DAY]
    assert result['auto_trade'] is False and result['changes_positions'] is False


def test_preopen_still_requires_previous_session_and_uses_same_cached_state(tmp_path, monkeypatch):
    args, record, calls = inputs(tmp_path, monkeypatch)
    context.run(**args, now=dt.datetime(2026, 9, 30, 22, 7, tzinfo=TZ),
                completed_session=DAY, daily_record=record)
    result = context.run(**args, now=dt.datetime(2026, 10, 8, 8, 30, tzinfo=TZ),
                         require_daily_receipt=True)
    assert result['date'] == str(DAY) and result['effective_date'] == str(NEXT)
    assert result['reused'] is True and calls == [DAY]


@pytest.mark.parametrize('case', ['missing', 'wrong_date', 'incomplete', 'rehearsal',
                                  'saved_data', 'future_receipt', 'failed_scheduler',
                                  'malformed_receipt', 'malformed_scheduler'])
def test_explicit_bad_receipt_clears_latest_without_falling_back(tmp_path, monkeypatch, case):
    args, record, calls = inputs(tmp_path, monkeypatch)
    clock = dt.datetime(2026, 9, 30, 22, 7, tzinfo=TZ)
    # An alternative good record must not conceal failure of the bound record.
    other = record.parent.with_name('2026-09-30_alternative')/'summary.json'
    other.parent.mkdir(); other.write_bytes(record.read_bytes())
    os.utime(other, (1, 1))
    payload = json.loads(record.read_text())
    if case == 'wrong_date': payload['as_of'] = '2026-09-29'
    elif case == 'incomplete': payload['status'] = 'incomplete'
    elif case in ('rehearsal', 'saved_data'): payload[case] = True
    record.write_text(json.dumps(payload)); os.utime(record, (1, 1))
    if case == 'missing': record.unlink()
    elif case == 'future_receipt': os.utime(record, (clock.timestamp()+1, clock.timestamp()+1))
    elif case == 'failed_scheduler':
        (record.parent/'scheduler.json').write_text('{"exit_code": 1}')
    elif case == 'malformed_receipt': record.write_text('{')
    elif case == 'malformed_scheduler': (record.parent/'scheduler.json').write_text('[]')
    args['root'].mkdir()
    (args['root']/'latest.json').write_text('{"status":"complete","market_state":"bull"}')
    with pytest.raises((ValueError, OSError)):
        context.run(**args, now=clock, completed_session=DAY, daily_record=record)
    result = json.loads((args['root']/'latest.json').read_text(encoding='utf-8'))
    assert result['status'] == 'incomplete' and result['market_state'] == 'unknown'
    assert result['daily_completion'] is None and calls == []


@pytest.mark.parametrize('clock,session', [
    ('2026-09-30T14:00:00+08:00', DAY),
    ('2026-10-02T08:30:00+08:00', dt.date(2026, 10, 1)),
    ('2026-09-30T22:07:00+08:00', DAY-dt.timedelta(days=1)),
])
def test_explicit_session_must_be_latest_closed_exchange_session(tmp_path, monkeypatch, clock, session):
    args, record, calls = inputs(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        context.run(**args, now=dt.datetime.fromisoformat(clock),
                    completed_session=session, daily_record=record)
    assert calls == []
    assert json.loads((args['root']/'latest.json').read_text(encoding='utf-8'))['market_state'] == 'unknown'


def test_bad_effective_date_cannot_be_published(tmp_path, monkeypatch):
    args, record, calls = inputs(tmp_path, monkeypatch)
    original = context.history

    def bad_history(config, output, **kwargs):
        original(config, output, **kwargs)
        path = output/'market_states.parquet'
        pl.read_parquet(path).with_columns(pl.lit(DAY).alias('effective_date')).write_parquet(path)

    monkeypatch.setattr(context, 'history', bad_history)
    with pytest.raises(ValueError, match='effective date'):
        context.run(**args, now=dt.datetime(2026, 9, 30, 22, 7, tzinfo=TZ),
                    completed_session=DAY, daily_record=record)
    assert json.loads((args['root']/'latest.json').read_text(encoding='utf-8'))['market_state'] == 'unknown'
