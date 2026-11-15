import datetime as dt
import json
from pathlib import Path

import polars as pl
import pytest

from quant.data import structured_incremental as module
from quant.data.structured_availability import normalize_increment, read_versions, release_at

CONFIG = Path('configs/data/structured_sources.toml')
NOW = dt.datetime(2026, 11, 8, 12, tzinfo=dt.timezone.utc)


def setup(tmp_path, tables=None, **settings):
    import tomllib
    from copy import deepcopy
    spec = deepcopy(tomllib.loads(CONFIG.read_text(encoding='utf-8')))
    spec.update(lookback_calendar_days=1, request_pause_seconds=0, **settings)
    spec['tables'] = {k: v for k, v in spec['tables'].items() if k in (tables or ['forecast'])}
    if 'report_rc' in spec['tables']:
        spec['tables']['report_rc']['lookback_calendar_days'] = 1
        spec['tables']['report_rc']['minimum_interval_seconds'] = 0
    # TOML fixture serialization uses only the exact production parser types.
    import json as j
    lines = [f'{k} = {j.dumps(v)}' for k, v in spec.items() if not isinstance(v, dict)]
    for table, rule in spec['tables'].items():
        lines.append(f'[tables.{table}]')
        lines.extend(f'{k} = {j.dumps(v)}' for k, v in rule.items())
    path = tmp_path/'config.toml'
    path.write_text('\n'.join(lines), encoding='utf-8')
    folder = tmp_path/'clean/trade_calendar/market=SH'
    folder.mkdir(parents=True)
    dates = [dt.date(2026, 9, 1)+dt.timedelta(days=i) for i in range(100)]
    pl.DataFrame({'date': dates, 'is_open': [d.weekday() < 5 for d in dates]}).write_parquet(folder/'data.parquet')
    return dict(config=path, data_root=tmp_path, output=tmp_path/'run1',
                as_of=dt.date(2026, 11, 8), now=lambda: NOW, yield_check=lambda: None), spec


class Client:
    def __init__(self, fn):
        self.fn, self.calls = fn, []

    def query_raw(self, table, **params):
        self.calls.append((table, params))
        return self.fn(table, params)


def forecast(day='20261107', value=1.):
    return pl.DataFrame({'ts_code': ['600000.SH'], 'ann_date': [day], 'end_date': ['20261231'],
                         'net_profit_min': [value], 'net_profit_max': [value+1]})


def test_exact_ann_date_and_resume_do_not_overwrite_raw(tmp_path):
    args, _ = setup(tmp_path)
    client = Client(lambda t, p: forecast())
    receipt = module.run(**args, connector=client)
    assert receipt['status'] == 'checked'
    assert client.calls[0][1]['ann_date'] == '20261107'
    assert 'start_date' not in client.calls[0][1]
    raw = next((tmp_path/'raw/tushare/forecast').glob('date=*/*.parquet'))
    before = raw.read_bytes()
    assert module.run(**args, connector=client, resume=True)['tables']['forecast']['rows'] == 1
    assert len(client.calls) == 1 and raw.read_bytes() == before
    args['output'] = tmp_path/'run2'
    assert module.run(**args, connector=client)['tables']['forecast']['new_rows'] == 0
    args['output'] = tmp_path/'run1'
    with pytest.raises(FileExistsError):
        module.run(**args, connector=client)


def test_revisions_and_original_observation_bound(tmp_path):
    args, spec = setup(tmp_path)
    rule = spec['tables']['forecast']
    old = normalize_increment(forecast('20190101'), table='forecast', rule=rule,
        observed_at='2026-11-06T01:00:00+00:00', raw_path='old', calendar=[])
    corrected = normalize_increment(forecast('20190101', 3.), table='forecast', rule=rule,
        observed_at='2026-11-07T01:00:00+00:00', raw_path='new', calendar=[])
    assert old['available_at'].item() == dt.datetime(2026, 11, 6, 1, tzinfo=dt.timezone.utc)
    assert old['source_entity_id'].item() == corrected['source_entity_id'].item()
    assert old['source_row_id'].item() != corrected['source_row_id'].item()
    for name, frame in [('old', old), ('new', corrected)]:
        path = tmp_path/f'clean/forecast/snapshot=d2_{name}'
        path.mkdir(parents=True)
        frame.write_parquet(path/'data.parquet')
    early = dt.datetime(2026, 11, 6, 2, tzinfo=dt.timezone.utc)
    assert read_versions(data_root=tmp_path, table='forecast', known_at=early, latest=True)['net_profit_min'].item() == 1.
    assert read_versions(data_root=tmp_path, table='forecast', known_at=NOW).height == 2
    assert read_versions(data_root=tmp_path, table='forecast', known_at=NOW, latest=True)['net_profit_min'].item() == 3.
    assert read_versions(data_root=tmp_path, table='forecast', known_at=early.replace(year=2020)).is_empty()
    with pytest.raises(ValueError, match='retain all native versions'):
        read_versions(data_root=tmp_path, table='stk_holdertrade', known_at=NOW, latest=True)


def test_daily_release_uses_next_session_and_empty_is_not_event_success(tmp_path):
    args, spec = setup(tmp_path, ['margin_detail'])
    rule = spec['tables']['margin_detail']
    friday = dt.date(2026, 11, 6)
    assert release_at(friday, rule, [friday, dt.date(2026, 11, 9)]).isoformat() == '2026-11-09T09:00:00+08:00'
    receipt = module.run(**args, connector=Client(lambda t, p: pl.DataFrame()))
    assert receipt['tables']['margin_detail']['status'] == 'missing_daily_rows'
    assert receipt['tables']['margin_detail']['requested_dates'] == ['2026-11-05']


def test_event_empty_and_wrong_date_are_distinct(tmp_path):
    args, _ = setup(tmp_path)
    receipt = module.run(**args, connector=Client(lambda t, p: pl.DataFrame()))
    assert receipt['tables']['forecast']['status'] == 'checked_empty'
    args['output'] = tmp_path/'wrong'
    receipt = module.run(**args, connector=Client(lambda t, p: forecast('20261001')))
    assert receipt['tables']['forecast']['status'] == 'error'
    assert not (tmp_path/'clean/forecast/snapshot=d2_wrong').exists()


def test_budget_preserves_raw_and_resume_keeps_pages(tmp_path):
    args, _ = setup(tmp_path, page_size=1, max_requests_per_run=1)
    client = Client(lambda t, p: forecast())
    receipt = module.run(**args, connector=client)
    assert receipt['tables']['forecast']['status'] == 'partial_budget'
    raw = list((tmp_path/'raw/tushare/forecast').glob('date=*/*.parquet'))
    assert len(raw) == 1
    client = Client(lambda t, p: pl.DataFrame())
    receipt = module.run(**args, connector=client, resume=True)
    assert client.calls[0][1]['offset'] == '1'
    assert receipt['tables']['forecast']['status'] == 'captured'


def test_trial_rows_never_become_full_permission_and_cap_is_durable(tmp_path):
    args, spec = setup(tmp_path, ['report_rc'])
    def fetch(t, p):
        return pl.DataFrame({'ts_code': ['600000.SH'], 'report_date': ['20261107'],
            'org_name': ['org'], 'author_name': ['a'], 'report_title': ['r'], 'quarter': ['2026Q4']})
    receipt = module.run(**args, connector=Client(fetch))
    assert receipt['tables']['report_rc']['status'] == 'permission_limited'
    assert receipt['status'] == 'partial'
    day = NOW.astimezone(dt.timezone(dt.timedelta(hours=8))).date()
    folder = tmp_path/f'raw/tushare/report_rc/request_intents/{day}'
    for i in range(20):
        (folder/f'{i}.json').write_text('{}')
    args['output'] = tmp_path/'capped'
    client = Client(fetch)
    assert module.run(**args, connector=client)['tables']['report_rc']['status'] == 'partial_budget'
    assert not client.calls


def test_capital_pause_publishes_deferred_receipt_without_query(tmp_path):
    from quant.core.capital_window import CapitalPathPause
    args, _ = setup(tmp_path)
    def pause():
        raise CapitalPathPause('capital_path_pause_requested')
    args['yield_check'] = pause
    client = Client(lambda *a: forecast())
    assert module.run(**args, connector=client)['status'] == 'deferred'
    assert not client.calls


def test_missed_incremental_dates_are_not_skipped_by_rolling_overlap(tmp_path):
    args, spec = setup(tmp_path)
    from quant.data.structured_availability import sessions
    path = tmp_path/'clean/forecast/snapshot=d2_old'
    path.mkdir(parents=True)
    (path/'summary.json').write_text(json.dumps({'status': 'captured', 'checked_through': '2026-10-30'}))
    days = module.request_dates(tmp_path, 'forecast', spec['tables']['forecast'], spec,
        args['as_of'], NOW, sessions(tmp_path))
    assert days[0] == dt.date(2026, 10, 31) and days[-1] == dt.date(2026, 11, 7)
    spec['max_catchup_calendar_days'] = 3
    with pytest.raises(module.RequestBudget, match='bounded catchup'):
        module.request_dates(tmp_path, 'forecast', spec['tables']['forecast'], spec,
            args['as_of'], NOW, sessions(tmp_path))


def test_seeded_receipt_reuses_validated_raw_without_new_transport(tmp_path):
    args, _ = setup(tmp_path)
    module.run(**args, connector=Client(lambda *a: forecast()))
    first = args['output']/'summary.json'
    args['output'] = tmp_path/'seeded'
    client = Client(lambda *a: (_ for _ in ()).throw(AssertionError('must reuse raw')))
    receipt = module.run(**args, connector=client, seed_receipt=first)
    assert receipt['tables']['forecast']['status'] == 'captured'
    assert not client.calls
    assert receipt['seed_sha256']


def test_runtime_budget_keeps_inflight_raw_and_resume_does_not_query_again(tmp_path):
    args, _ = setup(tmp_path, max_run_seconds=1)
    elapsed = [0.]
    args['monotonic'] = lambda: elapsed[0]

    def slow_response(table, params):
        elapsed[0] = 2.
        return forecast()

    first = module.run(**args, connector=Client(slow_response))
    assert first['status'] == 'partial' and first['time_budget_exhausted']
    assert first['tables']['forecast']['status'] == 'partial_budget'
    assert first['elapsed_seconds'] == 2.
    raw = next((tmp_path/'raw/tushare/forecast').glob('date=*/*.parquet'))
    original = raw.read_bytes()
    elapsed[0] = 0.
    client = Client(lambda *a: (_ for _ in ()).throw(AssertionError('saved raw must be reused')))
    resumed = module.run(**args, connector=client, resume=True)
    assert resumed['status'] == 'checked' and not resumed['time_budget_exhausted']
    assert not client.calls and raw.read_bytes() == original


def test_runtime_budget_stops_trial_cooldown_without_recording_new_intent(tmp_path, monkeypatch):
    args, _ = setup(tmp_path, ['report_rc'], max_run_seconds=1)
    elapsed = [0.]
    args['monotonic'] = lambda: elapsed[0]
    # The existing intent requires waiting even though the transport is never called.
    day = NOW.astimezone(dt.timezone(dt.timedelta(hours=8))).date()
    intents = tmp_path/f'raw/tushare/report_rc/request_intents/{day}'
    intents.mkdir(parents=True)
    (intents/'prior.json').write_text(json.dumps({'at': (NOW+dt.timedelta(seconds=61)).isoformat()}))
    monkeypatch.setattr(module.time, 'sleep', lambda seconds: elapsed.__setitem__(0, elapsed[0]+seconds))
    client = Client(lambda *a: (_ for _ in ()).throw(AssertionError('deadline must stop cooldown')))
    result = module.run(**args, connector=client)
    assert result['status'] == 'partial' and result['time_budget_exhausted']
    assert not client.calls and len(list(intents.glob('*.json'))) == 1


def test_runtime_expiry_between_tables_keeps_completed_publication(tmp_path):
    args, _ = setup(tmp_path, ['forecast', 'express'], max_run_seconds=1)
    elapsed = [0.]
    published = tmp_path/'clean/forecast/snapshot=d2_run1'
    args['monotonic'] = lambda: elapsed[0]

    def cooperate():
        if published.exists():
            elapsed[0] = 2.

    args['yield_check'] = cooperate
    client = Client(lambda *a: forecast())
    result = module.run(**args, connector=client)
    assert result['time_budget_exhausted'] and result['status'] == 'partial'
    assert result['tables']['forecast']['published'] == str(published)
    assert len(client.calls) == 1 and (published/'data.parquet').is_file()
    assert 'express' not in result['tables']


@pytest.mark.parametrize('limit', [0, -1, True])
def test_invalid_runtime_limit_refuses_before_creating_output(tmp_path, limit):
    args, _ = setup(tmp_path, max_run_seconds=limit)
    with pytest.raises(ValueError, match='finite and positive'):
        module.run(**args, connector=Client(lambda *a: forecast()))
    assert not args['output'].exists()
