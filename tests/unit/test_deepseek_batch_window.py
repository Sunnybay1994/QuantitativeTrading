import datetime as dt
from pathlib import Path

import pytest

from quant.data.connectors.deepseek import RequestFailure
from quant.data.forecast_text_scores import ScoreCache
from quant.research import score_forecast_text as scoring
from quant.research.deepseek_batch_window import request_window


@pytest.mark.parametrize('stamp,allowed', [
    ('2026-09-14T08:59:59+08:00', True),
    ('2026-09-14T09:00:00+08:00', False),
    ('2026-09-14T11:59:59+08:00', False),
    ('2026-09-14T12:00:00+08:00', True),
    ('2026-09-14T13:59:59+08:00', True),
    ('2026-09-14T14:00:00+08:00', False),
    ('2026-09-14T17:59:59+08:00', False),
    ('2026-09-14T18:00:00+08:00', True),
    ('2026-09-12T09:00:00+08:00', True),
    ('2026-09-13T14:00:00+08:00', True),
])
def test_beijing_peak_edges_and_weekends(stamp, allowed):
    instant = dt.datetime.fromisoformat(stamp)
    result = request_window(instant)
    assert result['allowed'] == allowed
    assert result == request_window(instant.astimezone(dt.timezone.utc))
    if not allowed:
        following = dt.datetime.fromisoformat(result['next_allowed_at'])
        assert following > instant and request_window(following)['allowed']


def test_naive_time_rejected():
    with pytest.raises(ValueError, match='timezone-aware'):
        request_window(dt.datetime(2026, 9, 14))


def test_peak_defers_without_reservation_and_development_still_obeys_budget(tmp_path, monkeypatch):
    monkeypatch.setattr(scoring, 'request_window', lambda: {
        'allowed': False, 'next_allowed_at': '2026-09-14T04:00:00+00:00'})
    settings = scoring.load_settings(Path('configs/research/deepseek_p7_v1.toml'))
    class Client:
        calls = 0
        def complete(self, reason, settings):
            self.calls += 1
            raise RequestFailure('connect_failed', retryable=True)
    client = Client()
    cache = ScoreCache(tmp_path/'cache.sqlite')
    try:
        args = dict(settings=settings, cache=cache, client=client, max_requests=1, max_usd=1,
                    sleep=lambda seconds: None)
        result = scoring.score_one('原因', **args)
        assert result['state'] == 'deferred_off_peak'
        assert client.calls == cache.totals()['requests'] == 0
        scoring.score_one('原因', **args, development_test=True)
        assert client.calls == cache.totals()['requests'] == 1
    finally:
        cache.close()


def test_retry_crossing_peak_stops_and_later_resumes_same_cache(tmp_path, monkeypatch):
    peak = False
    monkeypatch.setattr(scoring, 'request_window', lambda: {
        'allowed': not peak, 'next_allowed_at': '2026-09-14T04:00:00+00:00'})
    settings = scoring.load_settings(Path('configs/research/deepseek_p7_v1.toml'))
    class Client:
        calls = 0
        def complete(self, reason, settings):
            nonlocal peak
            self.calls += 1
            if self.calls == 1:
                peak = True
                raise RequestFailure('connect_failed', retryable=True)
            return {'model': 'fixture', 'usage': {'prompt_tokens': 1,
                'completion_tokens': 1, 'total_tokens': 2},
                'choices': [{'finish_reason': 'stop', 'message': {'content': '{}'}}]}
    client = Client()
    cache = ScoreCache(tmp_path/'cache.sqlite')
    try:
        args = dict(settings=settings, cache=cache, client=client, max_requests=2, max_usd=1,
                    sleep=lambda seconds: None, parse=lambda text: {})
        assert scoring.score_one('原因', **args)['state'] == 'deferred_off_peak'
        assert client.calls == cache.totals()['requests'] == 1
        peak = False
        assert scoring.score_one('原因', **args)['state'] == 'success'
        peak = True
        assert scoring.score_one('原因', **args)['state'] == 'success'
        assert client.calls == cache.totals()['requests'] == 2
    finally:
        cache.close()
