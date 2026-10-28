import datetime as dt
import json
from pathlib import Path

import polars as pl
import pytest

from quant.data import refresh, refresh_financials
from quant.data import update_disclosed_financials as updater
from quant.data.financial_clean import normalize_financial_publication


def test_request_progress_survives_resume_and_counts_all_four_tables(tmp_path, monkeypatch):
    base = tmp_path / 'clean/tushare_financials/base'
    base.mkdir(parents=True)
    summary = {'datasets': {}}
    raws = {}
    for table in refresh_financials.TABLES:
        row = {'ts_code': '000333.SZ', 'ann_date': '20260820', 'end_date': '20260630'}
        if table != 'fina_indicator':
            row.update(f_ann_date='20260820', report_type='1', comp_type='1', update_flag='0')
        row.update(n_income='100', n_income_attr_p='100', total_assets='100',
                   total_hldr_eqy_exc_min_int='100', n_cashflow_act='100', roe='100')
        raws[table] = pl.DataFrame([row])
        clean, quarantine, _ = normalize_financial_publication(
            raws[table].with_columns(pl.lit('original').alias('source_file')), dataset=table)
        clean.write_parquet(base / f'{table}.parquet')
        quarantine.write_parquet(base / f'{table}_quarantine.parquet')
        summary['datasets'][table] = {'raw_rows': 1, 'clean_rows': 1, 'exact_duplicate_rows': 0}
    (base / 'summary.json').write_text(json.dumps(summary), encoding='utf-8')
    failed = False
    calls, events = [], []

    class Client:
        def query_raw(self, table, **kwargs):
            calls.append(table)
            if failed and table == 'balancesheet':
                raise RuntimeError('private provider details')
            return raws[table]

    monkeypatch.setattr(refresh_financials.time, 'sleep', lambda _: None)
    kwargs = {'data_root': tmp_path, 'base_name': 'base', 'name': 'new', 'symbols': ['000333.SZ'],
                  'period': dt.date(2026, 6, 30), 'client': Client(), 'pause_seconds': 0,
                  'observed_on': dt.date(2026, 9, 11), 'progress': events.append}
    failed = True
    with pytest.raises(RuntimeError, match='Financial request failed'):
        refresh_financials.refresh_quarter(**kwargs)
    assert events[-1]['phase'] == 'request' and events[-1]['completed'] == 1
    assert all(event['total'] == 4 for event in events)
    captured = pl.read_parquet(tmp_path / 'clean/tushare_financials/new/captured.parquet')
    raw_path = Path(captured['raw_path'].item())
    raw_before = raw_path.read_bytes()
    failed = False
    calls.clear()
    events.clear()
    refresh_financials.refresh_quarter(**kwargs)
    assert calls == ['balancesheet', 'cashflow', 'fina_indicator']
    assert events[0]['completed'] == 1
    assert events[-1]['phase'] == 'complete' and events[-1]['completed'] == 4
    assert raw_path.read_bytes() == raw_before


def test_quarter_progress_counts_saved_quarters_without_requerying(tmp_path, monkeypatch):
    config = tmp_path / 'refresh.toml'
    config.write_text('financial_snapshot="base"\n', encoding='utf-8')
    disclosures = tmp_path / 'disclosures'
    disclosures.mkdir()
    requests = [{'symbol': '000333.SZ', 'period': '2025-12-31'},
                {'symbol': '000333.SZ', 'period': '2026-06-30'}]
    (disclosures / 'summary.json').write_text(
        json.dumps({'requests': requests, 'unresolved': []}), encoding='utf-8')
    saved = tmp_path / 'clean/tushare_financials/update_000'
    saved.mkdir(parents=True)
    (saved / 'summary.json').write_text(json.dumps({
        'base_version': 'base', 'period': '2025-12-31', 'symbols': ['000333.SZ'], 'datasets': {}}))
    calls, events = [], []

    def quarter(**kwargs):
        calls.append(kwargs['period'])
        kwargs['progress']({'phase': 'request', 'completed': 2, 'total': 4})
        assert 'financial_snapshot="base"' in config.read_text()
        return {'datasets': {}}

    monkeypatch.setattr(updater, 'refresh_quarter', quarter)
    updater.update(disclosures=disclosures, config=config, data_root=tmp_path,
                   output=tmp_path / 'update', progress=events.append)
    assert calls == [dt.date(2026, 6, 30)]
    assert [event['completed_requests'] for event in events] == [4, 6, 8]
    assert all(event['total_requests'] == 8 for event in events)
    assert events[1]['quarter_number'] == 2
    assert 'financial_snapshot="update_001"' in config.read_text()


def test_daily_refresh_writes_request_counts_during_financial_stage(tmp_path, monkeypatch):
    etfs = tmp_path / 'etfs.toml'
    etfs.write_text('[universe]\nsymbols=[]\n', encoding='utf-8')
    config = tmp_path / 'refresh.toml'
    config.write_text(f'etf_config="{etfs.as_posix()}"\n'
                      '[financials]\nenabled=true\nlookback_days=3\n', encoding='utf-8')
    path = tmp_path / 'progress.json'
    monkeypatch.setattr(refresh, 'latest_session', lambda **_: dt.date(2026, 10, 28))
    monkeypatch.setattr(refresh, 'refresh_stocks', lambda **_: {'new_dates': 0, 'new_rows': 0})
    monkeypatch.setattr(refresh, 'refresh_etfs', lambda **_: {'new_rows': 0, 'new_bar_rows': 0})
    monkeypatch.setattr(refresh, 'refresh_limits', lambda **_: 0)
    monkeypatch.setattr(refresh, 'refresh_stock_limits', lambda **_: {'new_rows': 0})

    def financials(**kwargs):
        kwargs['progress']({'phase': 'request', 'completed_requests': 12, 'total_requests': 16})
        saved = json.loads(path.read_text(encoding='utf-8'))
        assert saved['stage'] == 'financials' and saved['status'] == 'running'
        assert saved['counts']['completed_requests'] == 12
        return {'new_rows': 0}

    monkeypatch.setattr(refresh, 'refresh_disclosed_financials', financials)
    refresh.run_refresh(to='2026-10-28', data_root=tmp_path, artifact_root=tmp_path,
                        config=config, intraday=False, progress_path=path,
                        now=dt.datetime(2026, 10, 28, 22, tzinfo=refresh.SHANGHAI))
    assert json.loads(path.read_text(encoding='utf-8'))['stages']['financials'] == 'complete'
