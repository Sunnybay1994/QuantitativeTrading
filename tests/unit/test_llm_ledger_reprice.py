import json

import pytest

from quant.llm.ledger import priced_rows
from quant.llm.ledger_reprice import reprice_unpriced
from quant.reporting.doctor import _ledger
from quant.reporting.research_brief import collect_facts


def setup(tmp_path):
    ledger = tmp_path / 'artifacts/research/llm_ledger/2026-10.jsonl'
    ledger.parent.mkdir(parents=True)
    rows = [{'task': 'gp_hints', 'ts': '2026-10-09T12:00:00+08:00', 'usd': 0,
             'tokens': {'prompt_tokens': 1000, 'completion_tokens': 100}},
            {'task': 'event_extract', 'usd': .5}]
    ledger.write_text(''.join(json.dumps(r)+'\n' for r in rows), encoding='utf-8')
    tariff = tmp_path / 'pricing.toml'
    tariff.write_text('input_usd_per_million=0.3\noutput_usd_per_million=1.2\n')
    return ledger, tariff


def test_append_only_estimation_is_idempotent_and_never_counts_another_call(tmp_path):
    ledger, tariff = setup(tmp_path)
    original = ledger.read_bytes()
    preview = reprice_unpriced(ledger, pricing=tariff)
    assert preview['adjustments'] == 1 and ledger.read_bytes() == original
    result = reprice_unpriced(ledger, pricing=tariff, execute=True)
    assert result['new_api_calls'] == 0 and ledger.read_bytes().startswith(original)
    assert len(ledger.read_text().splitlines()) == 3
    calls = priced_rows(ledger)
    assert len(calls) == 2 and calls[0]['usd'] == pytest.approx(.00042)
    assert calls[0]['estimated'] is True and calls[0]['original_usd'] == 0
    assert 'not_provider_invoice' in calls[0]['pricing_adjustment']['basis']
    assert reprice_unpriced(ledger, pricing=tariff, execute=True)['adjustments'] == 0
    report = _ledger(ledger)
    assert report['rows'] == 2 and report['raw_rows'] == 3
    assert report['zero_usd_with_tokens'] == 0 and report['raw_zero_usd_with_tokens'] == 1
    facts = collect_facts('2026-10', root=tmp_path)
    assert facts['llm_tasks'] == 2 and facts['llm_month_usd'] == pytest.approx(.5004)


@pytest.mark.parametrize('tamper', ['source', 'amount', 'shape'])
def test_invalid_adjustment_cannot_make_doctor_green(tmp_path, tamper):
    ledger, tariff = setup(tmp_path)
    reprice_unpriced(ledger, pricing=tariff, execute=True)
    rows = [json.loads(line) for line in ledger.read_text().splitlines()]
    if tamper == 'source':
        rows[0]['tokens']['prompt_tokens'] = 2000
    elif tamper == 'amount':
        rows[-1]['usd'] = 1.0
    else:
        rows[-1]['tariff'] = None
    ledger.write_text(''.join(json.dumps(r)+'\n' for r in rows))
    with pytest.raises((ValueError, TypeError)):
        priced_rows(ledger)
    report = _ledger(ledger)
    assert report['zero_usd_with_tokens'] == 1 and report['pricing_errors']


def test_missing_usage_stays_unpriced_instead_of_inventing_cost(tmp_path):
    ledger, tariff = setup(tmp_path)
    ledger.write_text(json.dumps({'task': 'gp_hints', 'usd': 0, 'tokens': 20})+'\n')
    report = reprice_unpriced(ledger, pricing=tariff, execute=True)
    assert report['adjustments'] == 0 and report['unresolved_lines'] == [1]
    assert _ledger(ledger)['zero_usd_with_tokens'] == 1
