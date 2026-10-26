import datetime as dt
from copy import deepcopy
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
                       'input_usd_per_million=9.9\noutput_usd_per_million=9.9\n'
                       'max_tokens=4096\nmax_input_bytes=100000\nmax_attempts=1\n')
    pricing = tmp_path/'pricing.toml'
    pricing.write_text('input_usd_per_million=0.3\noutput_usd_per_million=1.2\n')
    design = tmp_path/'design.toml'
    design.write_text('[search]\nfields=["adj_close"]\noperators=["delay"]\n'
                      'maximum_candidates=20\nmaximum_depth=20\nmaximum_history=300\n')
    paths = {'output_root': tmp_path/'weekly', 'library': library, 'queue': tmp_path/'queue',
             'scorecard': scorecard, 'scoring_config': scoring, 'design': design,
             'cache': tmp_path/'shared.sqlite', 'pricing_config': pricing}
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


def test_parameter_variants_are_not_independent_mechanisms():
    from types import SimpleNamespace
    accepted = [dict(id='a', expr='adj_close/delay(adj_close,10)'),
                dict(id='b', expr='volume/delay(volume,5)'),
                dict(id='c', expr='volume/delay(volume,20)'),
                dict(id='d', expr='volume-ts_mean(volume,20)')]
    retained, rejected = weekly.distinct_mechanisms(accepted,
        [SimpleNamespace(expr='adj_close/delay(adj_close,5)')])
    assert [r['id'] for r in retained] == ['b', 'd']
    assert [r['id'] for r in rejected] == ['a', 'c']
    assert retained[0]['expr'] == accepted[1]['expr']


@pytest.mark.parametrize('change', ['date_only', 'price', 'model', 'future_date'])
def test_revalidated_identical_price_resumes_without_changing_frozen_request(setup, change):
    config, paths = setup
    initial = weekly.run(config, dt.datetime(2026, 9, 28, 21, tzinfo=weekly.SHANGHAI))
    folder = paths['output_root']/'2026-09-28'
    originals = {name: (folder/name).read_bytes() for name in ('request.json', 'scoring.toml', 'design.toml')}
    current = paths['scoring_config'].read_text().replace('2026-09-15',
        '2026-09-30' if change == 'future_date' else '2026-09-29')
    if change == 'price':
        current = current.replace('output_usd_per_million=1.2', 'output_usd_per_million=1.3')
    elif change == 'model':
        current = current.replace('model_epoch="fixture"', 'model_epoch="new_model"')
    paths['scoring_config'].write_text(current)
    client = Client({'candidates': [candidate('adj_close/delay(adj_close,5)')]})
    result = weekly.run(config, dt.datetime(2026, 9, 29, 21, tzinfo=weekly.SHANGHAI), client, execute=True)
    assert result['cache_key'] == initial['cache_key']
    assert originals == {name: (folder/name).read_bytes() for name in originals}
    from quant.research.score_forecast_text import cost_for
    frozen = json.loads((folder/'request.json').read_text(encoding='utf-8'))
    cheap = cost_for(frozen['token_bound'], 4096, {
        'input_usd_per_million': 0.3, 'output_usd_per_million': 1.2})
    expensive = cost_for(frozen['token_bound'], 4096, {
        'input_usd_per_million': 9.9, 'output_usd_per_million': 9.9})
    assert result['completed'] and client.calls == 1
    assert 'pricing_revalidation' not in result
    assert result['usd_bound_one_attempt'] == pytest.approx(cheap)
    assert result['usd_bound_one_attempt'] != pytest.approx(expensive)


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


@pytest.mark.parametrize('expressions', [[], ['rank(adj_close)'], ['adj_close']])
def test_no_accepted_candidates_has_no_pending_battery(setup, expressions):
    config, paths = setup
    now = dt.datetime(2026, 9, 15, 12, tzinfo=weekly.SHANGHAI)
    client = Client({'candidates': [candidate(expr) for expr in expressions]})
    result = weekly.run(config, now, client, execute=True)
    assert result['completed'] and result['accepted_count'] == 0
    assert result['evaluation_status'] == 'not_applicable_no_candidates'
    assert not result['evaluated'] and result['maxcorr_lt_0_6_fraction'] is None
    summary = paths['output_root']/'2026-09-14'/'summary.json'
    legacy = {**result, 'evaluation_status': 'pending'}
    summary.write_text(json.dumps(legacy), encoding='utf8')
    original = summary.read_bytes()
    resumed = weekly.run(config, now, client, execute=True)
    assert resumed['evaluation_status'] == 'not_applicable_no_candidates'
    assert not resumed['evaluated'] and resumed['queued_ids'] == []
    assert client.calls == 1 and summary.read_bytes() == original


@pytest.mark.parametrize('status,matching,expected', [
    ('complete', True, True), ('pending', True, False), ('complete', False, False),
])
def test_completed_generation_reads_only_matching_complete_feedback(setup, status, matching, expected):
    config, paths = setup
    now = dt.datetime(2026, 9, 15, 12, tzinfo=weekly.SHANGHAI)
    client = Client({'candidates': [candidate('adj_close/delay(adj_close,5)')]})
    generated = weekly.run(config, now, client, execute=True)
    folder = paths['output_root']/'2026-09-14'
    original = (folder/'summary.json').read_bytes()
    ids = generated['queued_ids'] if matching else ['unrelated_factor']
    (folder/'evaluation_feedback.json').write_text(json.dumps({
        'evaluation_status': status, 'factors': [{'factor': factor} for factor in ids],
        'maxcorr_lt_0_6_fraction': 1.0,
    }), encoding='utf-8')
    resumed = weekly.run(config, now, client, execute=True)
    assert resumed['evaluated'] is expected
    assert resumed['evaluation_status'] == ('complete' if expected else 'pending')
    assert resumed['maxcorr_lt_0_6_fraction'] == (1.0 if expected else None)
    assert client.calls == 1
    assert (folder/'summary.json').read_bytes() == original


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


def test_previous_generation_validation_is_frozen_once_for_next_week(setup):
    config, paths = setup
    folder = paths['output_root']/'2026-09-07'
    folder.mkdir(parents=True)
    (folder/'summary.json').write_text(json.dumps({'completed': True, 'accepted_count': 0, 'queued_ids': []}))
    (folder/'design.toml').write_bytes(paths['design'].read_bytes())
    validation = folder/'validation.json'
    validation.write_text(json.dumps([{'candidate': {'expression': 'rank(adj_close)'},
                                      'result': 'rejected', 'reason': 'unregistered'}]))
    now = dt.datetime(2026, 9, 15, 12, tzinfo=weekly.SHANGHAI)
    weekly.run(config, now)
    request = paths['output_root']/'2026-09-14'/'request.json'
    frozen = request.read_bytes()
    payload = json.loads(json.loads(frozen)['messages'][1]['content'])
    assert payload['generation_feedback']['weeks'][0]['unregistered_operator_candidate_counts'] == {'rank': 1}
    validation.write_text('invalid historical receipt after request freeze')
    weekly.run(config, now)
    assert request.read_bytes() == frozen
    assert not paths['cache'].exists() and not paths['queue'].exists()


def test_optional_feedback_cannot_crowd_out_complete_library():
    request = {'library': [{'id': 'existing', 'expression': 'adj_close'}],
               'fields': ['adj_close'], 'operators': ['delay'],
               'generation_feedback': {'weeks': [
                   {'week': '2026-09-28', 'proposed_count': 20,
                    'rejected_examples': [{'expression': 'x' * 10000}]}]}}
    messages, encoded = weekly.request_messages(request, 3000)
    assert len(encoded) <= 3000
    restored = json.loads(messages[1]['content'])
    assert restored['library'] == request['library']
    assert restored['fields'] == ['adj_close'] and restored['operators'] == ['delay']
    assert restored['generation_feedback']['weeks'][0]['proposed_count'] == 20
    assert restored['generation_feedback']['detail_truncated']


def test_benchmark_details_do_not_displace_definition_feedback():
    missing = [{'factor': f'candidate_{i:04d}', 'variant': variant}
               for i in range(20) for variant in ('raw', 'size_industry_neutral')]
    stats = {'variants': 40, 'candidates': 20, 'statistical_pass': 0,
             'statistical_failure_counts': {'hac_t': 37}, 'cost_excess_pass': 0,
             'benchmark_complete': 0, 'benchmark_incomplete': missing}
    request = {
        'library': [{'id': 'existing', 'expression': 'adj_close'}],
        'fields': ['adj_close'], 'operators': ['delay'],
        'research_feedback': {
            'policy': {'keep_rules': ['no lookahead', 'three costs']},
            'interpretation': 'Missing benchmark is not prediction failure.',
            'pending_batteries': [{'run': 'pending', 'reason': 'Battery not completed'}],
            'completed_batteries': [
                {'run': f'batch_{i}', 'source': f'batch_{i}/scorecard.parquet',
                 **stats, 'families': {'price': deepcopy(stats)}} for i in range(3)]},
        'generation_feedback': {'detail_truncated': False, 'weeks': [
            {'week': '2026-09-28', 'proposed_count': 20,
             'rejected_examples': [{'expression': 'rank(adj_close)', 'reason': 'unregistered'}]}]},
    }
    original = deepcopy(request)
    messages, encoded = weekly.request_messages(request, 8000)
    restored = json.loads(messages[1]['content'])
    assert len(encoded) <= 8000
    assert request == original  # Full machine evidence must remain inspectable.
    assert restored['generation_feedback'] == original['generation_feedback']
    for key in ('library', 'fields', 'operators'):
        assert restored[key] == original[key]
    research = restored['research_feedback']
    for key in ('policy', 'interpretation', 'pending_batteries'):
        assert research[key] == original['research_feedback'][key]
    for batch in research['completed_batteries']:
        for summary in (batch, batch['families']['price']):
            detail = summary['benchmark_incomplete_summary']
            assert detail == {'variant_count': 40, 'examples': missing[:2],
                              'omitted_variant_count': 38, 'source': batch['source']}
            assert 'benchmark_incomplete' not in summary
            for key, value in stats.items():
                if key != 'benchmark_incomplete':
                    assert summary[key] == value


def test_benchmark_details_without_source_or_with_few_rows_remain_intact():
    request = {'research_feedback': {'completed_batteries': [
        {'benchmark_incomplete': [{'factor': str(i)} for i in range(8)]},
        {'source': 's.parquet', 'benchmark_incomplete': [{'factor': 'a'}, {'factor': 'b'}]},
        {'source': 's.parquet', 'benchmark_incomplete': []},
    ]}}
    messages, _ = weekly.request_messages(request, 100000)
    assert json.loads(messages[1]['content']) == request


def test_request_messages_serializes_dates():
    import datetime as dt
    request = {'as_of': dt.date(2026, 10, 12), 'nested': {'day': dt.date(2026, 9, 30)}}
    messages, encoded = weekly.request_messages(request, 100000)
    body = json.loads(messages[1]['content'])
    assert body['as_of'] == '2026-10-12'
    assert body['nested']['day'] == '2026-09-30'
    assert isinstance(encoded, (bytes, bytearray))


def test_mandatory_input_over_limit_defers_without_call_or_library_truncation(setup):
    config, paths = setup
    paths['scoring_config'].write_text(paths['scoring_config'].read_text().replace(
        'max_input_bytes=100000', 'max_input_bytes=1000'))
    client = Client({'candidates': []})
    result = weekly.run(config, dt.datetime(2026, 9, 15, 12), client, execute=True)
    assert result['state'] == 'deferred_input_size' and client.calls == 0
    request = json.loads((paths['output_root']/'2026-09-14/request.json').read_bytes())
    content = json.loads(request['messages'][1]['content'])
    assert content['library'] == [{'id': 'old', 'expression': 'adj_close', 'direction': 1}]
    assert content['fields'] == ['adj_close'] and content['operators'] == ['delay']
    assert not paths['queue'].exists() and not paths['cache'].exists()


def test_legacy_frozen_request_is_sent_unchanged_after_packing_upgrade(setup, monkeypatch):
    from quant.research import research_feedback
    config, paths = setup
    config.write_text(config.read_text()+'\nresearch_policy="policy.toml"\n')
    missing = [{'factor': f'old_{i}', 'variant': 'raw'} for i in range(20)]
    monkeypatch.setattr(research_feedback, 'prompt_context', lambda _: {
        'completed_batteries': [{'source': 'old.parquet', 'benchmark_incomplete': missing}]})

    def legacy_messages(request, maximum_bytes):
        messages = [{'role': 'system', 'content': weekly.PROMPT},
                    {'role': 'user', 'content': json.dumps(request, ensure_ascii=False)}]
        return messages, json.dumps(messages, ensure_ascii=False).encode()

    monkeypatch.setattr(weekly, 'request_messages', legacy_messages)
    now = dt.datetime(2026, 9, 15, 12, tzinfo=weekly.SHANGHAI)
    initial = weekly.run(config, now)
    path = paths['output_root']/'2026-09-14/request.json'
    frozen = path.read_bytes()

    def must_not_repack(*args, **kwargs):
        raise AssertionError('A frozen request must not be repacked on resume')

    monkeypatch.setattr(weekly, 'request_messages', must_not_repack)

    class FrozenClient(Client):
        def complete_messages(self, messages, settings):
            assert messages == json.loads(frozen)['messages']
            assert json.loads(messages[1]['content'])['research_feedback'][
                'completed_batteries'][0]['benchmark_incomplete'] == missing
            return super().complete_messages(messages, settings)

    client = FrozenClient({'candidates': []})
    result = weekly.run(config, now, client, execute=True)
    assert result['completed'] and result['cache_key'] == initial['cache_key']
    assert path.read_bytes() == frozen and client.calls == 1
