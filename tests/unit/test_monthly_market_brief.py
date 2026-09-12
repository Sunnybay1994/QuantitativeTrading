import datetime as dt
import json
from pathlib import Path

import pytest

from quant.research.monthly_market_brief import (
    ZONE, fact_keys, generate, parse_brief, publication_mode, score, validate_facts,
)

CONFIG = Path('configs/research/deepseek_diagnosis_v1.toml')


def facts():
    return {'as_of': '2026-06-30', 'target_date': '2026-07-31', 'first_forecast_session': '2026-07-01',
        'series': [{'id': name, 'as_of': '2026-06-30', 'level': 100., 'return_20': .1,
                    'return_60': None, 'annualized_volatility_60': .2,
                    'source': f'saved-total-return-{name}', 'return_type': 'total_return'} for name in 'ABC']}


def response(data):
    return {'forecasts': [{'id': r['id'], 'probability_up': p, 'rationale': '近期回报偏正但波动仍有不确定性',
        'evidence': [{'key': f"series.{r['id']}.return_20", 'value': .1}]}
        for r, p in zip(data['series'], [.8, .2, .5])]}


class Client:
    calls = 0

    def complete_messages(self, messages, settings):
        self.calls += 1
        assert json.loads(messages[1]['content'])['facts'] == fact_keys(facts())
        return {'model': 'deepseek-flash', 'usage': {'prompt_tokens': 500, 'completion_tokens': 200,
            'total_tokens': 700}, 'choices': [{'finish_reason': 'stop',
            'message': {'content': json.dumps(response(facts()), ensure_ascii=False)}}]}


@pytest.mark.parametrize('change', ['probability', 'boolean', 'missing', 'citation', 'extra', 'id', 'trade_advice'])
def test_strict_predictions(change):
    data = response(facts())
    if change == 'probability':
        data['forecasts'][0]['probability_up'] = 1.1
    elif change == 'boolean':
        data['forecasts'][0]['probability_up'] = True
    elif change == 'missing':
        data['forecasts'].pop()
    elif change == 'citation':
        data['forecasts'][0]['evidence'][0]['value'] = .2
    elif change == 'trade_advice':
        data['forecasts'][0]['rationale'] = '建议加仓'
    elif change == 'extra':
        data['orders'] = []
    else:
        data['forecasts'][0]['id'] = 'UNKNOWN'
    with pytest.raises(ValueError):
        parse_brief(json.dumps(data), facts())


def test_facts_and_publication_time():
    data = facts()
    assert publication_mode(data, dt.datetime(2026, 6, 30, 16, tzinfo=ZONE)) == 'forward'
    assert publication_mode(data, dt.datetime(2026, 7, 1, 9, 30, tzinfo=ZONE)) == 'rehearsal'
    assert publication_mode(data, dt.datetime(2026, 6, 30, 16, tzinfo=ZONE), development_test=True) == 'rehearsal'
    data['series'][0]['level'] = None
    with pytest.raises(ValueError):
        validate_facts(data)


def test_dry_run_no_cache_and_fixture_reuses_existing_cache(tmp_path):
    source = tmp_path/'facts.json'
    source.write_text(json.dumps(facts()), encoding='utf-8')
    client = Client()
    args = dict(facts_path=source, config=CONFIG, cache_path=tmp_path/'cache.sqlite',
                artifact_root=tmp_path, client=client)
    dry = generate(**args, output=tmp_path/'dry')
    assert dry['forecasts'] is None and client.calls == 0 and not args['cache_path'].exists()
    for i in range(2):
        generated = generate(**args, output=tmp_path/f'fixture{i}', execute=True, max_requests=2, max_usd=.1)
        assert generated['development_test'] is True
        assert generated['status'] == 'success' and generated['rehearsal'] and not generated['forward_evidence']
    assert client.calls == 1
    assert score(brief=tmp_path/'dry', output=tmp_path/'no_forecast',
        known_through=dt.date(2026, 7, 31))['status'] == 'no_forecast'
    brief = tmp_path/'fixture0'
    assert score(brief=brief, output=tmp_path/'pending', known_through=dt.date(2026, 7, 1))['status'] == 'pending'
    realized = {'as_of': '2026-06-30', 'target_date': '2026-07-31', 'series': [
        {'id': r['id'], 'source': r['source'], 'return_type': 'total_return', 'reference_level': 100.,
         'total_return': v} for r, v in zip(facts()['series'], [.1, -.1, 0.])]}
    outcomes = tmp_path/'realized.json'
    outcomes.write_text(json.dumps(realized), encoding='utf-8')
    graded = score(brief=brief, output=tmp_path/'graded', known_through=dt.date(2026, 7, 31), outcomes=outcomes)
    assert graded['mean_brier'] == pytest.approx((.04+.04+.25)/3)
    assert graded['baseline_mean_brier'] == .25 and not graded['forward_evidence']
    assert graded['series'][2]['direction_correct'] is None
    realized['series'][0]['reference_level'] = 1.
    outcomes.write_text(json.dumps(realized), encoding='utf-8')
    with pytest.raises(ValueError, match='anchor'):
        score(brief=brief, output=tmp_path/'bad_anchor', known_through=dt.date(2026, 7, 31), outcomes=outcomes)
    with pytest.raises(FileExistsError):
        generate(**args, output=tmp_path/'dry')


def test_unknown_output_is_not_a_neutral_probability(tmp_path):
    source = tmp_path/'facts.json'
    source.write_text(json.dumps(facts()), encoding='utf-8')
    class EmptyClient(Client):
        def complete_messages(self, messages, settings):
            result = super().complete_messages(messages, settings)
            result['choices'][0]['message']['content'] = '{"forecasts":[]}'
            return result
    result = generate(facts_path=source, output=tmp_path/'empty', config=CONFIG,
        cache_path=tmp_path/'fixture_cache.sqlite', artifact_root=tmp_path, client=EmptyClient(),
        execute=True, max_requests=2, max_usd=.1)
    assert result['status'] != 'success' and result['forecasts'] is None
    assert result['forward_evidence'] is False
