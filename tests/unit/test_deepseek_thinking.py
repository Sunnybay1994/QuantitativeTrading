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
