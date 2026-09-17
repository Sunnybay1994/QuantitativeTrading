import datetime as dt
import json

import polars as pl

from quant.reporting.registered_periods import attach


def test_attach_uses_only_one_cost_and_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr('quant.reporting.dashboard_curves.catalog', lambda root: [])
    run = tmp_path/'run'
    folder = run/'long'/'cost_1'/'2025'
    folder.mkdir(parents=True)
    pl.DataFrame({'date': [dt.date(2025, 1, 2), dt.date(2025, 2, 3)],
                  'unit_nav': [1.1, .99], 'market_value': [100., 100.]}).write_parquet(folder/'nav.parquet')
    report = run/'report.md'
    report.write_text('# Original\nREJECTED\n', encoding='utf-8')
    row = dict(run_path=str(run), report_path=str(report), variant='long', source_run='',
               config_path=str(run/'absent.toml'), experiment_id='example', conclusion='REJECTED')
    assert attach([row], tmp_path)['completed'] == 1
    first = report.read_text(encoding='utf-8')
    attach([row], tmp_path)
    assert report.read_text(encoding='utf-8') == first
    assert first.startswith('# Original\nREJECTED\n')
    metrics = json.loads(next(run.glob('periods_1x/*/metrics.json')).read_text())
    months = [r for r in metrics if r['frequency'] == 'month']
    assert abs(months[1]['total_return']+.1) < 1e-9
    assert len(list(run.glob('periods_1x/*/monthly_2025.md'))) == 1
