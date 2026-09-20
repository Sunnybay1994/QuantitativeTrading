"""Forward timing, missing data and recovery tests without running production research."""
import datetime as dt
import json

import polars as pl
import pytest

from quant.research import candidate_forward as forward


DAY = dt.date(2026, 9, 21)
TZ = dt.timezone(dt.timedelta(hours=8))
SESSIONS = (dt.date(2026, 9, 18), DAY, dt.date(2026, 9, 22), dt.date(2026, 9, 23))
RECEIPT = {'frozen_local_date': '2026-09-20', 'forward_not_before': '2026-09-21',
           'candidate_set_sha256': 'fixture', 'candidates': [{'id': 'candidate', 'direction': -1}]}


@pytest.mark.parametrize(('as_of', 'clock', 'expected'), [
    ('2026-09-18', '2026-09-20T10:00:00+08:00', 'pending'),
    ('2026-09-21', '2026-09-21T16:59:59+08:00', 'pending'),
    ('2026-09-21', '2026-09-21T17:00:00+08:00', 'ready'),
    ('2026-09-21', '2026-09-22T09:29:59+08:00', 'ready'),
    ('2026-09-21', '2026-09-22T09:30:00+08:00', 'missed_window'),
    ('2026-09-21', '2026-09-23T20:00:00+08:00', 'missed_window'),
])
def test_exchange_capture_window(as_of, clock, expected):
    result = forward.capture_window(receipt=RECEIPT, as_of=dt.date.fromisoformat(as_of),
        sessions=SESSIONS, now=dt.datetime.fromisoformat(clock))
    assert result['status'] == expected
    assert result['first_eligible_session'] == '2026-09-21'
    if expected != 'pending':
        assert result['entry_session'] == '2026-09-22'


def test_freeze_on_signal_day_requires_later_session_and_calendar_gap_fails():
    result = forward.capture_window(receipt={**RECEIPT, 'frozen_local_date': str(DAY)},
        as_of=DAY, sessions=SESSIONS, now=dt.datetime(2026, 9, 21, 20, tzinfo=TZ))
    assert result['status'] == 'pending' and result['first_eligible_session'] == '2026-09-22'
    with pytest.raises(ValueError, match='next exchange session'):
        forward.capture_window(receipt=RECEIPT, as_of=DAY, sessions=SESSIONS[:2],
            now=dt.datetime(2026, 9, 21, 20, tzinfo=TZ))
    with pytest.raises(ValueError, match='timezone'):
        forward.capture_window(receipt=RECEIPT, as_of=DAY, sessions=SESSIONS,
            now=dt.datetime(2026, 9, 21, 20))


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    root = tmp_path/'data'
    search = tmp_path/'search'
    search.mkdir()
    (search/'search_contract.json').write_text(json.dumps({'mapping': {'gp_a': 'adj_close'}}))
    (search/'search.json').write_text(json.dumps({'candidates': [{'factor_id': 'candidate',
        'terminal_expression': 'ts_mean(gp_a, 2)', 'expression': 'ts_mean(adj_close, 2)'}]}))
    folder = root/'factors/a/year=2026'
    folder.mkdir(parents=True)
    (folder.parent/'definition.json').write_text(json.dumps({'id': 'a', 'expr': 'adj_close', 'direction': -1}))
    (folder/'coverage.json').write_text(json.dumps({'start': '2026-01-01', 'end': str(DAY)}))
    # B has no bar on Friday: a calendar-padded null must invalidate its 2-day mean.
    bars = pl.DataFrame({'symbol': ['A', 'A', 'B', 'C', 'C'],
                        'trade_date': [SESSIONS[0], DAY, DAY, SESSIONS[0], DAY],
                        'adj_close': [10., 20., 30., None, 40.]})
    bars.select('trade_date', pl.col('symbol').alias('ts_code'), pl.col('adj_close').alias('value')).write_parquet(folder/'data.parquet')
    padded = pl.DataFrame({'symbol': ['A', 'B', 'C']}).join(
        pl.DataFrame({'trade_date': SESSIONS[:2]}), how='cross').join(bars, on=forward.KEYS, how='left').sort(*forward.KEYS)
    monkeypatch.setattr(forward, 'available_sessions', lambda root, end: tuple(day for day in SESSIONS if day <= end))
    monkeypatch.setattr(forward, 'read_factor_inputs', lambda *a: (padded, bars))
    refresh = tmp_path/'refresh.toml'
    refresh.write_text('financial_snapshot="dated_fixture"')
    battery = tmp_path/'battery.toml'
    battery.write_text('[universe]\nminimum_listing_days=60')
    evidence = tmp_path/'refresh.json'
    evidence.write_text(json.dumps({'latest_session': str(DAY), 'intraday_errors': [],
        'input_quality': {'errors': []}, 'financials': {'unresolved_announcements': [{'symbol': 'C'}]}}))
    universe = pl.DataFrame({'symbol': ['A', 'B', 'C'], 'trade_date': [DAY]*3,
        'eligible': [True, True, False], 'industry_l1': ['x']*3, 'total_market_value': [100.]*3})
    monkeypatch.setattr(forward, 'read_daily_health_universe', lambda **kw: universe)
    monkeypatch.setattr(forward, 'load_candidate_freeze', lambda *a, **kw: RECEIPT)
    return {'data_root': root, 'search_output': search, 'refresh_config': refresh,
            'refresh_evidence': evidence, 'receipt_path': tmp_path/'receipt.json',
            'battery_config': battery, 'as_of': DAY, 'output': tmp_path/'capture',
            'now': dt.datetime(2026, 9, 21, 20, tzinfo=TZ)}


def test_capture_preserves_raw_direction_nulls_and_reproducible_inputs(inputs):
    result = forward.run(**inputs)
    assert result['status'] == 'captured' and result['independent_forward_capture'] is True
    assert result['performance_evaluated'] is False and result['auto_trade'] is False
    values = pl.read_parquet(inputs['output']/'values.parquet').sort('symbol')
    assert values['candidate'].to_list() == [15., None, None]  # Neither terminal nor candidate direction applied.
    assert result['finite_eligible_counts'] == {'candidate': 1}
    assert result['eligible_symbols'] == 2 and result['inputs']['lookback_sessions'] == 1
    assert result['unresolved_financial_announcements'] == [{'symbol': 'C'}]
    saved = pl.read_parquet(inputs['output']/'inputs.parquet')
    replay = forward.evaluate_expressions(saved, {'candidate': 'ts_mean(gp_a, 2)'}).filter(pl.col('trade_date') == DAY)
    assert replay.sort('symbol')['candidate'].to_list() == values['candidate'].to_list()
    hashes = {name: forward._digest(inputs['output']/name) for name in result['files']}
    assert hashes == result['files']
    with pytest.raises(FileExistsError):
        forward.run(**inputs)
    assert hashes == {name: forward._digest(inputs['output']/name) for name in result['files']}


@pytest.mark.parametrize('reason', ['coverage', 'missing_row', 'duplicate_row', 'definition', 'export', 'refresh'])
def test_stale_inconsistent_or_drifted_inputs_never_produce_capture(inputs, reason):
    folder = inputs['data_root']/'factors/a/year=2026'
    if reason == 'coverage':
        (folder/'coverage.json').write_text(json.dumps({'start': '2026-01-01', 'end': '2026-09-18'}))
    elif reason in ('missing_row', 'duplicate_row'):
        frame = pl.read_parquet(folder/'data.parquet')
        frame = frame.head(4) if reason == 'missing_row' else pl.concat([frame, frame.head(1)])
        frame.write_parquet(folder/'data.parquet')
    elif reason == 'definition':
        (folder.parent/'definition.json').write_text(json.dumps({'id': 'a', 'expr': '-adj_close'}))
    elif reason == 'export':
        path = inputs['search_output']/'search.json'
        value = json.loads(path.read_text())
        value['candidates'][0]['expression'] = '-adj_close'
        path.write_text(json.dumps(value))
    else:
        inputs['refresh_evidence'].write_text(json.dumps({'latest_session': '2026-09-18'}))
    with pytest.raises(ValueError):
        forward.run(**inputs)
    assert not (inputs['output']/'summary.json').exists()
    assert not (inputs['output']/'values.parquet').exists()


@pytest.mark.parametrize(('day', 'clock', 'status'), [
    (SESSIONS[0], dt.datetime(2026, 9, 20, 20, tzinfo=TZ), 'pending'),
    (DAY, dt.datetime(2026, 9, 22, 10, tzinfo=TZ), 'missed_window'),
])
def test_pending_and_missed_dates_do_not_read_values(inputs, monkeypatch, day, clock, status):
    def forbidden(**kwargs):
        raise AssertionError('No signal reading allowed')
    monkeypatch.setattr(forward, 'read_candidate_inputs', forbidden)
    result = forward.run(**{**inputs, 'as_of': day, 'now': clock})
    assert result['status'] == status and result['independent_forward_capture'] is False
    assert result['requires_review'] is (status == 'missed_window')
    assert not (inputs['output']/'values.parquet').exists()


def test_terminal_file_change_during_read_fails(inputs, monkeypatch):
    original = forward._digest
    seen = set()
    def changed(path):
        if path.name == 'data.parquet':
            if path in seen:
                return 'changed'
            seen.add(path)
        return original(path)
    monkeypatch.setattr(forward, '_digest', changed)
    with pytest.raises(ValueError, match='changed during capture'):
        forward.run(**inputs)
    assert not (inputs['output']/'values.parquet').exists()


def test_calculation_crossing_next_open_is_not_published_as_forward(inputs, monkeypatch):
    ticks = iter([dt.datetime(2026, 9, 22, 9, 29, tzinfo=TZ), dt.datetime(2026, 9, 22, 9, 30, tzinfo=TZ)])
    class CaptureClock(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return next(ticks).astimezone(tz)
    monkeypatch.setattr(forward.dt, 'datetime', CaptureClock)
    with pytest.raises(ValueError, match='crossed its next-open deadline'):
        forward.run(**{**inputs, 'now': None})
    assert not (inputs['output']/'summary.json').exists()
