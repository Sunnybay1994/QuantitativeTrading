import copy
import json
from pathlib import Path

import pytest

from quant.data.resolve_financial_six_20260912 import resolve_batch


def inputs():
    headers = json.loads(Path('configs/data/financial_document_headers_20260912.json').read_text(encoding='utf-8'))
    source = {'unresolved': [{**d, 'confirmed_periods': d['previously_confirmed_periods']}
                             for d in headers['documents']],
              'requests': [{'symbol': d['symbol'], 'period': p}
                           for d in headers['documents'] for p in d['previously_confirmed_periods']]}
    return headers, source


def test_inspected_headers_resolve_only_seven_missing_requests_without_backdating():
    headers, source = inputs()
    result = resolve_batch(headers, source)
    assert result['unresolved'] == []
    assert len(result['requests']) == 7
    assert result['requests'][0] == {'symbol': '002752.SZ', 'period': '2025-12-31'}
    assert {r['period'] for r in result['requests'][1:]} == {'2026-06-30'}
    assert [r['announcement_date'] for r in result['document_resolutions']] == [
        r['announcement_date'] for r in source['unresolved']]


def test_changed_source_identity_and_single_page_are_rejected():
    headers, source = inputs()
    changed = copy.deepcopy(source)
    changed['unresolved'][0]['symbol'] = '000001.SZ'
    with pytest.raises(ValueError, match='mismatch'):
        resolve_batch(headers, changed)
    headers['documents'][0]['pages'] = headers['documents'][0]['pages'][:1]
    with pytest.raises(ValueError, match='Insufficient'):
        resolve_batch(headers, source)
