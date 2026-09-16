import datetime as dt
import json

import polars as pl
import pytest

from quant.research import weekly_factor_candidates as weekly


def test_budget_uses_shared_calendar_week_and_month(tmp_path):
    now = dt.datetime(2026, 9, 15, 12, tzinfo=weekly.SHANGHAI)
    cache = weekly.WeeklyCache(tmp_path/'cache.sqlite', now, 5, 30, clock=lambda: now)
    for day, state, reserved, charged in [('2026-08-31T10:00:00+08:00', 'success', 9, 9),
                                         ('2026-09-13T10:00:00+08:00', 'success', 4, 3),
                                         ('2026-09-14T10:00:00+08:00', 'unknown', 2, 0)]:
        cache.db.execute('INSERT INTO attempts(cache_key,state,reserved_usd,charged_usd,created_at) '
                         'VALUES (?,?,?,?,?)', ('old', state, reserved, charged, day))
    cache.db.commit()
    assert weekly.budget_totals(cache, now) == {'week_usd': 2, 'month_usd': 5}
    assert cache.reserve('new', 3.1, max_requests=100, max_usd=100, max_attempts=2) is None
    assert cache.reserve('new', 3, max_requests=100, max_usd=100, max_attempts=2)
    cache.close()


def test_month_budget_is_not_reset_by_new_week(tmp_path):
    now = dt.datetime(2026, 9, 21, 12, tzinfo=weekly.SHANGHAI)
    cache = weekly.WeeklyCache(tmp_path/'cache.sqlite', now, 5, 30, clock=lambda: now)
    cache.db.execute("INSERT INTO attempts(cache_key,state,reserved_usd,charged_usd,created_at) "
                     "VALUES ('previous','success',29.99,29.99,'2026-09-14T00:00:00+00:00')")
    cache.db.commit()
    assert cache.reserve('newweek', .02, max_requests=100, max_usd=100, max_attempts=2) is None
    october = dt.datetime(2026, 10, 1, 12, tzinfo=weekly.SHANGHAI)
    assert weekly.budget_totals(cache, october) == {'week_usd': 0, 'month_usd': 0}
    cache.close()


def test_reservation_rechecks_clock_across_month_boundary(tmp_path):
    instants = iter([dt.datetime(2026, 9, 30, 23, 59, tzinfo=weekly.SHANGHAI),
                     dt.datetime(2026, 10, 1, 0, 1, tzinfo=weekly.SHANGHAI)])
    cache = weekly.WeeklyCache(tmp_path/'cache.sqlite', dt.datetime.now(dt.timezone.utc),
                               5, 30, clock=lambda: next(instants))
    cache.db.execute("INSERT INTO attempts(cache_key,state,reserved_usd,charged_usd,created_at) "
                     "VALUES ('old','success',30,30,'2026-09-25T00:00:00+00:00')")
    cache.db.commit()
    assert cache.reserve('request', .01, max_requests=100, max_usd=100, max_attempts=1) is None
    assert cache.reserve('request', .01, max_requests=100, max_usd=100, max_attempts=1)
    assert cache.latest('request')['created_at'].startswith('2026-09-30T16:01')
    cache.close()


@pytest.fixture
def setup(tmp_path, monkeypatch):
    from quant.research import score_forecast_text
    monkeypatch.setattr(score_forecast_text, 'request_window', lambda: {'allowed': True})
    library = tmp_path/'library'
    library.mkdir()
    (library/'old.toml').write_text('id="old"\nexpr="adj_close"\nfamily="price"\ndirection=1\nsource_ref="local"\n')
    scorecard = tmp_path/'scorecard.parquet'
    pl.DataFrame({'factor': ['old'], 'statistical_pass': [False]}).write_parquet(scorecard)
    scoring = tmp_path/'scoring.toml'
    scoring.write_text('model="deepseek-flash"\nmodel_epoch="fixture"\npricing_checked=2026-09-15\n'
                       'input_usd_per_million=0.3\noutput_usd_per_million=1.2\n'
                       'max_tokens=4096\nmax_input_bytes=100000\nmax_attempts=1\n')
    design = tmp_path/'design.toml'
    design.write_text('[search]\nfields=["adj_close"]\noperators=["delay"]\n'
                      'maximum_candidates=20\nmaximum_depth=20\nmaximum_history=300\n')
    paths = {'output_root': tmp_path/'weekly', 'library': library, 'queue': tmp_path/'queue',
             'scorecard': scorecard, 'scoring_config': scoring, 'design': design, 'cache': tmp_path/'shared.sqlite'}
    config = tmp_path/'weekly.toml'
    config.write_text(''.join(f'{key}={json.dumps(str(value))}\n' for key, value in paths.items()))
    return config, paths


class Client:
    calls = 0
    def __init__(self, payload):
        self.payload = payload

    def complete_messages(self, messages, settings):
        self.calls += 1
        assert 'old' in messages[1]['content']
        return {'model': 'fixture', 'usage': {'prompt_tokens': 100, 'completion_tokens': 100, 'total_tokens': 200},
                'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(self.payload)}}]}


def candidate(expr):
    return {'expression': expr, 'direction': 1, 'rationale': 'Mechanism pending evaluation', 'sources': ['weekly_gap']}


def test_deduplicates_library_and_candidate_then_cached_resume(setup):
    config, paths = setup
    now = dt.datetime(2026, 9, 15, 12, tzinfo=weekly.SHANGHAI)
    client = Client({'candidates': [candidate('adj_close'), candidate('adj_close/delay(adj_close,5)'),
                                     candidate('adj_close / delay(adj_close, 5)')]})
    result = weekly.run(config, now, client, execute=True)
    assert result['completed'] and result['accepted_count'] == 1
    assert result['maxcorr_lt_0_6_fraction'] is None
    assert len(list(paths['queue'].glob('*.toml'))) == 1
    summary = paths['output_root']/'2026-09-14'/'summary.json'
    summary.unlink()  # Interrupted after queue publication but before summary persistence.
    processing = paths['queue']/'processing'
    processing.mkdir()
    for path in paths['queue'].glob('*.toml'):
        path.rename(processing/path.name)
    assert weekly.run(config, now, client, execute=True)['completed']
    assert client.calls == 1
    assert not list(paths['queue'].glob('*.toml'))


def test_bad_schema_records_error_without_queue(setup):
    config, paths = setup
    client = Client({'candidates': [{'expression': 'adj_close', 'python': 'danger'}]})
    result = weekly.run(config, dt.datetime(2026, 9, 15, 12, tzinfo=weekly.SHANGHAI), client, execute=True)
    assert not result['completed']
    assert result['error'] == 'invalid_output_schema'
    assert not paths['queue'].exists()
    weekly.run(config, dt.datetime(2026, 9, 15, 12, tzinfo=weekly.SHANGHAI), client, execute=True)
    assert client.calls == 1


def test_unknown_charge_after_interruption_never_resubmits(setup):
    config, paths = setup
    now = dt.datetime(2026, 9, 15, 12, tzinfo=weekly.SHANGHAI)
    plan = weekly.run(config, now)
    cache = weekly.ScoreCache(paths['cache'])
    assert cache.reserve(plan['cache_key'], .01, max_requests=1, max_usd=1, max_attempts=1)
    cache.close()
    client = Client({'candidates': []})
    assert weekly.run(config, now, client, execute=True)['state'] == 'unknown'
    assert client.calls == 0


def test_peak_deferred_and_dryrun_make_no_requests(setup):
    config, _ = setup
    client = Client({'candidates': []})
    assert weekly.run(config, dt.datetime(2026, 9, 15, 9), client)['state'] == 'dry_run'
    result = weekly.run(config, dt.datetime(2026, 9, 15, 9), client, execute=True)
    assert result['state'] == 'deferred_off_peak'
    assert not result['completed'] and client.calls == 0


def test_new_week_cannot_reset_budget_with_another_cache(setup):
    config, paths = setup
    weekly.run(config, dt.datetime(2026, 9, 15, 12))
    config.write_text(config.read_text().replace('shared.sqlite', 'new_empty.sqlite'))
    with pytest.raises(ValueError, match='same shared cache'):
        weekly.run(config, dt.datetime(2026, 9, 21, 12))
    assert not (paths['output_root']/'2026-09-21').exists()


def test_historical_weekly_and_queue_expressions_are_known(setup):
    _, paths = setup
    paths['queue'].mkdir()
    row = {'id': 'queued', 'expr': 'delay(adj_close,5)', 'family': 'price', 'direction': 1, 'source_ref': 'local'}
    (paths['queue']/'queued.toml').write_text(''.join(f'{k}={json.dumps(v)}\n' for k, v in row.items()))
    historical = paths['output_root']/'2026-09-07'
    historical.mkdir(parents=True)
    (historical/'accepted.json').write_text(json.dumps([{**row, 'id': 'history', 'expr': 'delay(adj_close,10)'}]))
    known = weekly.known_definitions(paths['library'], paths['queue'], paths['output_root'])
    assert {row.id for row in known} == {'old', 'queued', 'history'}


def test_research_feedback_is_frozen_with_weekly_request(setup, monkeypatch):
    from quant.research import research_feedback
    config, paths = setup
    config.write_text(config.read_text()+'\nresearch_policy="policy.toml"\n')
    calls = []
    def context(path):
        calls.append(path)
        return {'marker': 'completed-only'}
    monkeypatch.setattr(research_feedback, 'prompt_context', context)
    now = dt.datetime(2026, 9, 15, 12)
    weekly.run(config, now)
    request = paths['output_root']/'2026-09-14'/'request.json'
    frozen = request.read_bytes()
    assert b'completed-only' in frozen
    weekly.run(config, now)
    assert request.read_bytes() == frozen
    assert len(calls) == 1
