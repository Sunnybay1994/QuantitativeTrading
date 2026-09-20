"""Candidate forward scoring uses saved signals, exact dates and immutable inputs."""
import datetime as dt
import hashlib
import json
from pathlib import Path
import shutil

import numpy as np
import polars as pl
import pytest

from quant.reporting import candidate_forward_monitor as monitor
from quant.research import candidate_freeze

DAY = dt.date(2026, 9, 30)
ENTRY = dt.date(2026, 10, 1)
EXIT = dt.date(2026, 11, 2)
TZ = dt.timezone(dt.timedelta(hours=8))
BATTERY = '''variants = ["raw", "size_industry_neutral"]
minimum_symbols = 100
minimum_paired_coverage = 0.95
monthly_newey_west_lag = 6
monthly_label = "next_open_to_next_monthly_rebalance_open"
[universe]
minimum_listing_days = 120
amount_window_sessions = 20
amount_exclude_bottom_fraction = 0.2
[preprocessing]
mad_multiplier = 3.0
mad_normal_scale = 1.4826
'''


def write_json(path, value):
    path.write_text(json.dumps(value, default=str), encoding='utf-8')


@pytest.fixture
def setup(tmp_path, monkeypatch):
    search, data, root = tmp_path/'search', tmp_path/'data', tmp_path/'daily'
    (search/'library').mkdir(parents=True)
    root.mkdir()
    candidates = []
    for expression, direction in [('adj_close', 1), ('adj_open', -1)]:
        identifier = 'ngp_' + hashlib.sha256(expression.encode()).hexdigest()[:16]
        candidates.append({'factor_id': identifier, 'expression': expression, 'direction': direction,
                           'terminal_expression': 'gp_a' if direction == 1 else 'gp_b'})
        (search/'library'/f'{identifier}.toml').write_text(
            f'id = "{identifier}"\nexpr = "{expression}"\ndirection = {direction}\nfamily = "predictive_priority_v2"')
    write_json(search/'search.json', {'candidates': candidates})
    write_json(search/'search_contract.json', {'objective': 'predictive_priority_v2',
        'config': {'auto_trade': False}, 'mapping': {'gp_a': 'adj_close', 'gp_b': 'adj_open'}})
    monkeypatch.setattr(candidate_freeze, '_utc_now', lambda: dt.datetime(2026, 9, 20, 0, tzinfo=dt.timezone.utc))
    receipt_path = tmp_path/'freeze.json'
    receipt = candidate_freeze.freeze_completed_search(search, receipt_path=receipt_path)
    start = dt.date(2026, 9, 1)
    dates = [start+dt.timedelta(days=index) for index in range(122)]
    for market in ('SH', 'SZ'):
        folder = data/f'clean/trade_calendar/market={market}'
        folder.mkdir(parents=True)
        pl.DataFrame({'date': dates, 'market': [market]*len(dates),
                      'is_open': [day.weekday() < 5 for day in dates]}).write_parquet(folder/'data.parquet')
    symbols = [f'{index+1:06d}.SZ' for index in range(120)]
    price_rows = []
    returns = np.sin(np.arange(120)) / 20
    for day in (ENTRY, EXIT, dt.date(2030, 1, 1)):
        for index, symbol in enumerate(symbols):
            price = 100. if day == ENTRY else 100.*(1+returns[index])
            price_rows.append({'symbol': symbol, 'trade_date': day, 'open': price,
                               'high': price+1, 'low': price-1, 'close': price,
                               'volume': 1000., 'amount': 100000., 'adj_factor': 1., 'source': 'tushare'})
    bar_path = data/'clean/tushare_bulk/snapshots/fixture/bar_1d/asset=stock/year=2026/data.parquet'
    bar_path.parent.mkdir(parents=True)
    pl.from_dicts(price_rows).write_parquet(bar_path)
    monkeypatch.setattr(monitor, '_now', lambda: dt.datetime(2026, 11, 3, 20, tzinfo=TZ))

    def capture(*, day=DAY, stamp=None, name='one', reverse=False, controls_missing=False, constant=False):
        folder = root/name/'candidate_forward'
        folder.mkdir(parents=True)
        stamp = stamp or dt.datetime.combine(day, dt.time(20), TZ)
        following = day+dt.timedelta(days=1)
        while following.weekday() > 4:
            following += dt.timedelta(days=1)
        values = .05*np.arange(120)+np.sin(np.arange(120))
        if reverse:
            values = -values
        if constant:
            values = np.ones(120)
        raw = pl.DataFrame({'symbol': symbols, 'trade_date': [day]*120,
                            **{row['factor_id']: values for row in candidates}})
        universe = pl.DataFrame({'symbol': symbols, 'trade_date': [day]*120, 'eligible': [True]*120,
            'total_market_value': [None if controls_missing and i < 20 else float(np.exp(i/100)*1e8) for i in range(120)],
            'industry_l1': ['x' if i % 2 else 'y' for i in range(120)]})
        raw.write_parquet(folder/'values.parquet')
        universe.write_parquet(folder/'universe.parquet')
        raw.write_parquet(folder/'inputs.parquet')
        (folder/'battery_config.toml').write_text(BATTERY)
        (folder/'refresh_config.toml').write_text('stock_snapshot="fixture"\n')
        write_json(folder/'refresh.json', {'latest_session': str(day), 'intraday_errors': [],
                                          'input_quality': {'errors': []}})
        write_json(folder/'candidate_freeze.json', receipt)
        write_json(folder/'terminal_expressions.json', {row['factor_id']: row['terminal_expression'] for row in candidates})
        record = {'as_of': str(day), 'status': 'captured', 'independent_forward_capture': True,
                  'auto_trade': False, 'candidate_count': len(candidates),
                  'candidate_set_sha256': receipt['candidate_set_sha256'],
                  'recorded_at_utc': stamp.astimezone(dt.timezone.utc).isoformat(),
                  'captured_at_utc': stamp.astimezone(dt.timezone.utc).isoformat(),
                  'entry_session': str(following),
                  'capture_deadline': dt.datetime.combine(following, dt.time(9, 30), TZ).isoformat(),
                  'files': {path.name: monitor._digest(path) for path in folder.iterdir()}}
        write_json(folder/'summary.json', record)
        return folder

    def invoke(name='result', known_through=EXIT, **kwargs):
        return monitor.run(search_output=search, receipt_path=receipt_path, roots=[root],
            known_through=known_through, output=tmp_path/name, data_root=data, **kwargs)
    return {'capture': capture, 'run': invoke, 'root': root, 'data': data, 'search': search,
            'receipt': receipt, 'receipt_path': receipt_path, 'bars': bar_path,
            'candidates': candidates, 'tmp': tmp_path}


def no_bars(**kwargs):
    raise AssertionError('Pending observations must never read label prices')


def test_no_forward_data_is_pending_without_reading_prices(setup, monkeypatch):
    monkeypatch.setattr(monitor, 'read_stock_data', no_bars)
    result = setup['run'](known_through=dt.date(2026, 9, 20))
    assert result['status'] == 'pending' and result['candidate_count'] == 2
    assert result['scored_months'] == 0 and result['errors'] == []
    assert pl.read_parquet(Path(result['output'])/'labels.parquet').is_empty()


@pytest.mark.parametrize('day', [dt.date(2026, 9, 21), DAY])
def test_non_monthend_and_immature_month_never_read_future_prices(setup, monkeypatch, day):
    setup['capture'](day=day)
    monkeypatch.setattr(monitor, 'read_stock_data', no_bars)
    result = setup['run'](known_through=dt.date(2026, 10, 30))
    assert result['status'] == 'pending' and result['scored_months'] == 0
    assert result['captures'][0]['status'] == ('awaiting_realized_return' if day == DAY else 'not_month_end_or_calendar_incomplete')


def test_mature_labels_direction_neutralization_and_calculation_inputs(setup, monkeypatch):
    capture = setup['capture']()
    original = monitor.read_stock_data
    calls = []
    def checked(**kwargs):
        calls.append((kwargs['start'], kwargs['end']))
        assert kwargs['end'] <= EXIT
        return original(**kwargs)
    monkeypatch.setattr(monitor, 'read_stock_data', checked)
    result = setup['run']()
    assert result['status'] == 'observed' and result['scored_months'] == 1
    assert result['matured_months'] == 1 and result['valid_ic_observations'] == 4
    assert result['auto_trade'] is False and result['admission_changed'] is False
    assert result['cost_adjusted_strategy_returns_computed'] is False
    assert calls == [(ENTRY, ENTRY), (EXIT, EXIT)]
    table = pl.read_csv(Path(result['output'])/'monthly_ic.csv')
    positive = table.filter(pl.col('factor') == setup['candidates'][0]['factor_id'])
    negative = table.filter(pl.col('factor') == setup['candidates'][1]['factor_id'])
    assert positive['rank_ic'].to_list() == pytest.approx([-value for value in negative['rank_ic']])
    by_variant = dict(zip(positive['variant'], positive['rank_ic']))
    assert by_variant['size_industry_neutral'] > .95
    assert by_variant['raw'] < .5
    labels = pl.read_parquet(Path(result['output'])/'labels.parquet')
    assert labels['execution_date_rebalance'].unique().to_list() == [ENTRY]
    assert labels['exit_date_rebalance'].unique().to_list() == [EXIT]
    saved = Path(result['captures'][0]['calculation_inputs'])
    assert (saved/'values.parquet').read_bytes() == (capture/'values.parquet').read_bytes()
    assert pl.read_parquet(saved/'label_prices.parquet')['trade_date'].unique().sort().to_list() == [ENTRY, EXIT]
    for name, checksum in result['calculation_files'].items():
        assert monitor._digest(Path(result['output'])/name) == checksum


def test_missing_exit_prices_keep_nulls_and_saved_95_percent_gate(setup):
    setup['capture']()
    prices = pl.read_parquet(setup['bars'])
    prices.filter(~((pl.col('trade_date') == EXIT) & pl.col('symbol').is_in([f'{i:06d}.SZ' for i in range(1, 8)]))).write_parquet(setup['bars'])
    result = setup['run']()
    table = pl.read_csv(Path(result['output'])/'monthly_ic.csv')
    assert result['status'] == 'observed' and result['scored_months'] == 0
    assert table['rank_ic'].null_count() == 4
    assert table['signal_count'].to_list() == [120]*4
    assert table['paired_count'].to_list() == [113]*4
    assert table['paired_coverage'].to_list() == pytest.approx([113/120]*4)
    assert pl.read_parquet(Path(result['output'])/'labels.parquet')['label_rebalance'].null_count() == 7


def test_missing_size_only_reduces_neutral_signal_cohort(setup):
    setup['capture'](controls_missing=True)
    result = setup['run']()
    table = pl.read_csv(Path(result['output'])/'monthly_ic.csv')
    assert table.filter(pl.col('variant') == 'raw')['signal_count'].to_list() == [120]*2
    assert table.filter(pl.col('variant') == 'size_industry_neutral')['signal_count'].to_list() == [100]*2


def test_constant_scores_do_not_fabricate_ic(setup):
    setup['capture'](constant=True)
    result = setup['run']()
    table = pl.read_csv(Path(result['output'])/'monthly_ic.csv')
    assert result['scored_months'] == 0
    assert table['rank_ic'].null_count() == 4
    assert table['signal_count'].to_list() == [0]*4


def test_missing_calendar_day_never_bridges_to_a_false_exit(setup, monkeypatch):
    setup['capture']()
    path = setup['data']/'clean/trade_calendar/market=SH/data.parquet'
    pl.read_parquet(path).filter(pl.col('date') != dt.date(2026, 10, 30)).write_parquet(path)
    monkeypatch.setattr(monitor, 'read_stock_data', no_bars)
    result = setup['run']()
    assert result['status'] == 'failed' and result['requires_review']
    assert 'missing day' in result['errors'][0]['error']


def test_earliest_complete_capture_wins_even_if_later_values_reverse(setup):
    early = setup['capture'](name='early', stamp=dt.datetime(2026, 9, 30, 18, tzinfo=TZ))
    setup['capture'](name='later', reverse=True)
    result = setup['run']()
    assert result['status'] == 'observed' and result['scored_months'] == 1
    assert result['captures'][0]['source'] == str((early/'summary.json').resolve())
    assert len(result['duplicates']) == 1
    assert len(result['series']) == 4  # Both fixed candidates retained even with identical raw values.


def test_equal_timestamp_conflicting_values_exclude_date(setup):
    setup['capture'](name='a')
    setup['capture'](name='b', reverse=True)
    result = setup['run']()
    assert result['status'] == 'failed' and result['scored_months'] == 0
    assert 'Conflicting' in result['errors'][0]['error']


def test_identical_duplicate_same_timestamp_and_current_path_count_once(setup):
    first = setup['capture']()
    second = setup['root']/'duplicate'/'candidate_forward'
    shutil.copytree(first, second)
    result = setup['run'](current=first)
    assert result['status'] == 'observed' and result['complete_capture_records'] == 2
    assert result['scored_months'] == 1 and len(result['duplicates']) == 1


@pytest.mark.parametrize('filename', ['values.parquet', 'inputs.parquet', 'universe.parquet', 'battery_config.toml', 'candidate_freeze.json'])
def test_tampered_capture_is_rejected_without_crashing_accounts(setup, filename):
    folder = setup['capture']()
    with (folder/filename).open('ab') as stream:
        stream.write(b'tampered')
    result = setup['run']()
    assert result['status'] == 'failed' and result['requires_review']
    assert 'hash differs' in result['errors'][0]['error']


def test_corrupt_one_capture_does_not_stop_valid_other_date(setup):
    bad = setup['capture'](day=dt.date(2026, 9, 29), name='bad')
    (bad/'values.parquet').unlink()
    setup['capture'](name='good')
    result = setup['run']()
    assert result['status'] == 'partial' and result['scored_months'] == 1
    assert result['requires_review'] and len(result['errors']) == 1


@pytest.mark.parametrize('stamp', [dt.datetime(2026, 9, 30, 16, 59, tzinfo=TZ),
                                  dt.datetime(2026, 10, 1, 9, 30, tzinfo=TZ)])
def test_early_or_late_actual_capture_is_not_forward(setup, stamp):
    setup['capture'](stamp=stamp)
    result = setup['run']()
    assert result['status'] == 'failed' and result['scored_months'] == 0


def test_wrong_candidate_set_and_pending_records_are_ignored(setup, monkeypatch):
    folder = setup['capture']()
    record = json.loads((folder/'summary.json').read_text())
    record['candidate_set_sha256'] = 'another experiment'
    write_json(folder/'summary.json', record)
    other = setup['capture'](name='pending')
    record = json.loads((other/'summary.json').read_text())
    record['status'] = 'pending'
    write_json(other/'summary.json', record)
    monkeypatch.setattr(monitor, 'read_stock_data', no_bars)
    result = setup['run']()
    assert result['status'] == 'pending' and result['errors'] == []


def test_future_known_through_is_rejected(setup):
    result = setup['run'](known_through=dt.date(2026, 11, 4))
    assert result['status'] == 'failed' and 'completed scoring close' in result['errors'][0]['error']


def test_future_capture_clock_is_rejected(setup):
    setup['capture'](stamp=dt.datetime(2026, 11, 4, 20, tzinfo=TZ))
    result = setup['run']()
    assert result['status'] == 'failed' and 'in the future' in result['errors'][0]['error']


@pytest.mark.parametrize('empty', [True, False])
def test_missing_roots_are_failures_not_pending(setup, empty):
    result = monitor.run(search_output=setup['search'], receipt_path=setup['receipt_path'],
        roots=[] if empty else [setup['tmp']/'missing'], known_through=EXIT,
        output=setup['tmp']/'result', data_root=setup['data'])
    assert result['status'] == 'failed' and 'capture roots' in result['errors'][0]['error']


def test_missing_entire_execution_day_is_input_error(setup):
    setup['capture']()
    pl.read_parquet(setup['bars']).filter(pl.col('trade_date') != EXIT).write_parquet(setup['bars'])
    result = setup['run']()
    assert result['status'] == 'failed' and 'Entire execution-session' in result['errors'][0]['error']


@pytest.mark.parametrize(('before', 'after'), [
    ('minimum_symbols = 100', 'minimum_symbols = 99'),
    ('minimum_paired_coverage = 0.95', 'minimum_paired_coverage = 0.9'),
    ('monthly_newey_west_lag = 6', 'monthly_newey_west_lag = 5'),
    ('mad_multiplier = 3.0', 'mad_multiplier = 2.5'),
    ('minimum_listing_days = 120', 'minimum_listing_days = 100'),
    ('["raw", "size_industry_neutral"]', '["size_industry_neutral", "raw"]'),
])
def test_changed_saved_measurement_cannot_be_aggregated(setup, before, after):
    setup['capture'](day=dt.date(2026, 9, 29), name='baseline')
    changed = setup['capture'](name='changed')
    (changed/'battery_config.toml').write_text(BATTERY.replace(before, after))
    record = json.loads((changed/'summary.json').read_text())
    record['files']['battery_config.toml'] = monitor._digest(changed/'battery_config.toml')
    write_json(changed/'summary.json', record)
    result = setup['run']()
    assert result['status'] == 'failed' and 'measurement differs' in result['errors'][0]['error']


@pytest.mark.parametrize('bad', ['label', 'json', 'rebalance'])
def test_unsupported_label_or_malformed_record_is_reported(setup, bad):
    folder = setup['capture']()
    if bad == 'json':
        write_json(folder/'summary.json', [])
    else:
        battery = (BATTERY+'\n[portfolio]\nrebalance="daily"\n' if bad == 'rebalance' else
                   BATTERY.replace('next_open_to_next_monthly_rebalance_open', 'other'))
        (folder/'battery_config.toml').write_text(battery)
        record = json.loads((folder/'summary.json').read_text())
        record['files']['battery_config.toml'] = monitor._digest(folder/'battery_config.toml')
        write_json(folder/'summary.json', record)
    result = setup['run']()
    assert result['status'] == 'failed' and result['requires_review']
