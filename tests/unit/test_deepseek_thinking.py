import hashlib
import json

import httpx
import pytest

from quant.data.connectors.deepseek import DeepSeekClient
from quant.factors.forecast_text_score import PROMPT_VERSION, messages, request_key_settings, score_key
from quant.research.score_forecast_text import load_settings


def settings():
    return {'model': 'deepseek-flash', 'model_epoch': 'fixture', 'max_tokens': 4096}


def test_disabled_mode_preserves_original_cache_bytes_and_ignores_inactive_effort():
    original = settings()
    reason = '本期销量增长。'
    payload = {'messages': messages(reason), 'version': PROMPT_VERSION, **original}
    expected = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    assert score_key(reason, original) == expected
    for effort in ('low', 'high', 'max'):
        assert score_key(reason, {**original, 'thinking_mode': 'disabled', 'reasoning_effort': effort}) == expected


def test_thinking_and_effort_have_distinct_cache_keys():
    reason = '本期销量增长。'
    keys = [score_key(reason, settings())]
    for effort in ('low', 'high', 'max'):
        keys.append(score_key(reason, {**settings(), 'thinking_mode': 'enabled', 'reasoning_effort': effort}))
    assert len(set(keys)) == 4
    assert request_key_settings(settings()) == settings()


@pytest.mark.parametrize('mode', ['disabled', 'enabled'])
def test_transport_sends_effective_controls_without_temperature_in_thinking(mode):
    bodies = []
    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={'choices': []})
    client = DeepSeekClient('fixture', transport=httpx.MockTransport(handler))
    try:
        client.complete('本期销量增长。', {**settings(), 'thinking_mode': mode, 'reasoning_effort': 'low'})
    finally:
        client.close()
    body = bodies[0]
    assert body['thinking'] == {'type': mode}
    assert body['max_tokens'] == 4096 and body['response_format'] == {'type': 'json_object'}
    if mode == 'enabled':
        assert body['reasoning_effort'] == 'low' and 'temperature' not in body
    else:
        assert body['temperature'] == 0 and 'reasoning_effort' not in body


def test_real_config_keeps_reasoning_within_existing_budget_bounds():
    from pathlib import Path
    result = load_settings(Path('configs/research/deepseek_p7_thinking_low_20260912.toml'))
    assert result['thinking_mode'] == 'enabled' and result['reasoning_effort'] == 'low'
    assert result['max_tokens'] == 4096 and result['max_attempts'] == 1


def test_larger_reasoning_budget_is_reserved_before_network(tmp_path):
    from pathlib import Path
    from quant.data.forecast_text_scores import ScoreCache
    from quant.factors.forecast_text_score import input_token_bound
    from quant.research.score_forecast_text import cost_for, score_one

    extended = load_settings(Path('configs/research/deepseek_p7_thinking_8192_20260912.toml'))
    original = load_settings(Path('configs/research/deepseek_p7_thinking_low_20260912.toml'))
    assert {k: v for k, v in extended.items() if k != 'max_tokens'} == {
        k: v for k, v in original.items() if k != 'max_tokens'}
    reason = '本期订单明显增长。'
    old_bound = cost_for(input_token_bound(reason, format_version='compact_evidence_v1'), 4096, original)
    new_bound = cost_for(input_token_bound(reason, format_version='compact_evidence_v1'), 8192, extended)
    assert new_bound > old_bound
    assert score_key(reason, original) != score_key(reason, extended)

    class NoCall:
        def complete(self, *_):
            raise AssertionError('Insufficient reservation must prevent network calls')

    cache = ScoreCache(tmp_path / 'cost.sqlite')
    try:
        result = score_one(reason, settings=extended, cache=cache, client=NoCall(),
                           max_requests=1, max_usd=old_bound, development_test=True)
        assert result['state'] == 'budget_exhausted'
        assert cache.totals() == {'requests': 0, 'charged_or_reserved_usd': 0}
    finally:
        cache.close()


@pytest.mark.parametrize(('mode', 'tokens'), [('disabled', 4097), ('enabled', 8193)])
def test_mode_specific_output_bounds_still_reject_excess(mode, tokens):
    from pathlib import Path
    from pydantic import ValidationError
    from quant.research.score_forecast_text import Settings

    config = load_settings(Path('configs/research/deepseek_p7_thinking_low_20260912.toml'))
    with pytest.raises(ValidationError):
        Settings.model_validate({**config, 'thinking_mode': mode, 'max_tokens': tokens})
