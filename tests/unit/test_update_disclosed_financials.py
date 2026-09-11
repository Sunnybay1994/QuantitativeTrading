import datetime as dt
import json

import pytest

from quant.data import update_disclosed_financials as updater


def test_quarter_batches_resume_and_publish_configuration_only_after_completion(tmp_path, monkeypatch):
    config = tmp_path/'refresh.toml'
    config.write_text('financial_snapshot="base"\nrequests_per_minute=60\n')
    disclosures = tmp_path/'disclosures'
    disclosures.mkdir()
    requests = [{'symbol': '600000.SH', 'period': '2025-12-31'},
                {'symbol': '000333.SZ', 'period': '2026-06-30'}]
    (disclosures/'summary.json').write_text(json.dumps({'requests': requests, 'unresolved': []}))
    calls, fail = [], [True]

    def refresh(**kwargs):
        calls.append(kwargs['period'].isoformat())
        if len(calls) == 2 and fail[0]:
            raise RuntimeError('temporary failure')
        result = {'base_version': kwargs['base_name'], 'period': str(kwargs['period']),
                  'symbols': kwargs['symbols'], 'datasets': {'income': {'clean_rows': 12, 'base_clean_rows': 10}}}
        folder = tmp_path/'clean/tushare_financials'/kwargs['name']
        folder.mkdir(parents=True)
        (folder/'summary.json').write_text(json.dumps(result))
        return result

    monkeypatch.setattr(updater, 'refresh_quarter', refresh)
    args = dict(disclosures=disclosures, config=config, data_root=tmp_path, output=tmp_path/'update')
    with pytest.raises(RuntimeError, match='temporary'):
        updater.update(**args)
    assert 'financial_snapshot="base"' in config.read_text()
    fail[0] = False
    result = updater.update(**args)
    assert calls == ['2025-12-31', '2026-06-30', '2026-06-30']
    assert result['new_rows'] == 4 and result['financial_snapshot'] == 'update_001'
    assert 'financial_snapshot="update_001"' in config.read_text()
    assert updater.update(**args)['message'] == 'no-op'
    assert len(calls) == 3
    # Recover a process exit between updating the pointer and publishing the summary.
    (tmp_path/'update/summary.json').unlink()
    assert updater.update(**args)['new_rows'] == 4
    assert len(calls) == 3


def test_unmapped_announcements_remain_visible_without_numeric_requests(tmp_path):
    config = tmp_path/'refresh.toml'
    config.write_text('financial_snapshot="base"\n')
    source = tmp_path/'source'
    source.mkdir()
    (source/'summary.json').write_text(json.dumps({'requests': [], 'unresolved': [{'title': 'unknown period'}]}))
    result = updater.update(disclosures=source, config=config, data_root=tmp_path, output=tmp_path/'update')
    assert result['message'] == 'no-op' and result['unresolved_announcements']
    assert result['financial_snapshot'] == 'base'


@pytest.mark.parametrize('fail', [False, True])
def test_daily_document_resolution_precedes_numeric_update(tmp_path, monkeypatch, fail):
    config = tmp_path/'refresh.toml'
    config.write_text('[financials]\nresolve_documents=true\n')
    calls = []
    monkeypatch.setattr(updater, 'collect', lambda **kwargs: calls.append('collect'))

    def resolve(**kwargs):
        assert calls == ['collect']
        assert kwargs['disclosures'].name == 'financial_disclosures_v1_20260910'
        assert kwargs['output'].name == 'financial_disclosures_v2_20260910'
        calls.append('resolve')
        if fail:
            raise RuntimeError('incomplete document capture')

    def update(**kwargs):
        assert calls == ['collect', 'resolve']
        assert kwargs['disclosures'].name == 'financial_disclosures_v2_20260910'
        assert kwargs['output'].name == 'financial_updates_v2_20260910'
        return {'new_rows': 2}

    monkeypatch.setattr(updater, 'resolve', resolve)
    monkeypatch.setattr(updater, 'update', update)
    kwargs = dict(end=dt.date(2026, 9, 10), config=config, data_root=tmp_path,
                  artifact_root=tmp_path, lookback_days=3)
    if fail:
        with pytest.raises(RuntimeError, match='incomplete'):
            updater.refresh_daily(**kwargs)
    else:
        assert updater.refresh_daily(**kwargs)['new_rows'] == 2
