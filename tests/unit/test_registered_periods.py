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


def test_account_receipt_finds_main_nav_and_never_uses_proxy_or_double_cost(tmp_path,monkeypatch):
    monkeypatch.setattr('quant.reporting.dashboard_curves.catalog',lambda _:[])
    run=tmp_path/'run';run.mkdir()
    report=run/'report.md';report.write_text('# Completed\nREJECTED\n',encoding='utf-8')
    entries=[]
    for period,cost,final in [('proxy_2015_2018',1.,3.),('main',2.,2.),('main',1.,1.1)]:
        folder=run/period/'fixed'/f'cost_{cost:g}';folder.mkdir(parents=True)
        pl.DataFrame({'date':[dt.date(2025,1,2),dt.date(2025,2,3)],
            'unit_nav':[1.,final],'market_value':[100.,100.]}).write_parquet(folder/'nav.parquet')
        entries.append({'period':period,'variant':'fixed','cost_multiplier':cost,'path':str(folder)})
    (run/'summary.json').write_text(json.dumps({'status':'replayed','completed':entries}))
    row={'run_path':str(run),'report_path':str(report),'variant':'fixed','source_run':'',
        'config_path':str(run/'absent.toml'),'experiment_id':'account','conclusion':'REJECTED'}
    assert attach([row],tmp_path)['completed']==1
    text=report.read_text(encoding='utf-8')
    assert '没有已完成' not in text and 'REJECTED' in text
    source=json.loads(next(run.glob('periods_1x/*/sources.json')).read_text(encoding='utf-8'))
    assert source['nav']==[str(run/'main/fixed/cost_1/nav.parquet')]


def test_other_summary_completed_boolean_does_not_invent_a_nav_receipt(tmp_path,monkeypatch):
    monkeypatch.setattr('quant.reporting.dashboard_curves.catalog',lambda _:[])
    run=tmp_path/'run';run.mkdir()
    report=run/'report.md';report.write_text('# Prior\n',encoding='utf-8')
    (run/'summary.json').write_text('{"completed":true}')
    row={'run_path':str(run),'report_path':str(report),'variant':'long','source_run':'',
        'config_path':str(run/'absent.toml'),'experiment_id':'other','conclusion':'REJECTED'}
    result=attach([row],tmp_path)
    assert result['completed']==0 and len(result['unavailable'])==1
