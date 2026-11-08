import datetime as dt
import math
import json
from pathlib import Path

import polars as pl
import pytest

from quant.factors.event_family_r6 import compute, one_signal
from quant.data.event_family_r6_inputs import read_sources

NOW = dt.datetime(2026, 11, 5, 3, tzinfo=dt.timezone.utc)
DAY = dt.date(2026, 11, 6)


def event(key='a', **kwargs):
    return {'ts_code': '600000.SH', 'source_row_id': key, 'source_raw_path': 'raw/fixture',
            'source_announcement_date': dt.date(2026, 11, 1), 'known_at': NOW,
            'available_at': NOW, 'observed_at': NOW, **kwargs}


def test_repurchase_cumulative_updates_are_not_summed_and_plan_is_not_paid():
    rows = [event('a', end_date='20261030', proc='完成', amount=100.),
            event('b', end_date='20261030', proc='完成', amount=150.,
                  source_announcement_date=dt.date(2026, 11, 2)),
            event('c', end_date='20261101', proc='预案', amount=99999.)]
    assert one_signal(rows, 'repurchase_strength_30d', DAY, 1000.) == .15
    assert one_signal(rows, 'repurchase_strength_30d', DAY, None) is None
    assert one_signal([], 'repurchase_strength_30d', DAY, 1000.) is None


def test_insider_unknown_price_and_ambiguous_transactions_are_missing():
    rows = [event(holder_name='A', holder_type='P', in_de='IN', change_vol=10., avg_price=2.)]
    assert one_signal(rows, 'insider_net_buy_90d', DAY, 1000.) == .02
    assert one_signal([{**rows[0], 'avg_price': None}], 'insider_net_buy_90d', DAY, 1000.) is None
    assert one_signal(rows+[dict(rows[0], source_row_id='other', change_vol=20.)],
                      'insider_net_buy_90d', DAY, 1000.) is None


def test_unlock_latest_revision_different_holders_and_no_percentage_clipping():
    rows = [event(float_date='20261120', holder_name='A', share_type='P', float_ratio=10.),
            event('b', float_date='20261120', holder_name='A', share_type='P', float_ratio=12.,
                  known_at=NOW+dt.timedelta(days=1)),
            event('c', float_date='20261120', holder_name='B', share_type='P', float_ratio=5.)]
    assert one_signal(rows, 'unlock_pressure_30d', DAY, None) == pytest.approx(-.17)
    assert one_signal([dict(rows[-1], float_ratio=101.)], 'unlock_pressure_30d', DAY, None) is None


def test_holder_periods_and_exact_prior_year_are_not_summed_or_substituted():
    rows = [event(end_date='20260930', holder_num=800.),
            event('b', end_date='20260630', holder_num=1000.),
            event('c', end_date='20250930', holder_num=1600.)]
    assert one_signal(rows, 'holder_count_qoq', DAY, None) == pytest.approx(-math.log(.8))
    assert one_signal(rows, 'holder_count_yoy', DAY, None) == pytest.approx(-math.log(.5))
    assert one_signal(rows[:2], 'holder_count_yoy', DAY, None) is None


def test_analyst_requires_same_author_target_period_and_nonzero_previous_eps():
    rows = [event(org_name='O', author_name='A', quarter='2026Q4', eps=1.),
            event('b', org_name='O', author_name='A', quarter='2026Q4', eps=1.2,
                  source_announcement_date=dt.date(2026, 11, 2))]
    assert one_signal(rows, 'analyst_eps_revision_30d', DAY, None) == pytest.approx(.2)
    assert one_signal([rows[0], dict(rows[1], quarter='2027Q4')],
                      'analyst_eps_revision_30d', DAY, None) is None
    assert one_signal([rows[0], dict(rows[1], author_name='B')],
                      'analyst_eps_revision_30d', DAY, None) is None
    assert one_signal([dict(rows[0], eps=0.), rows[1]], 'analyst_eps_revision_30d', DAY, None) is None


def test_old_announcements_downloaded_later_cannot_make_historical_values():
    row = event(proc='完成', end_date='20260101', amount=100.,
                source_announcement_date=dt.date(2026, 1, 2))
    keys = pl.DataFrame({'symbol': ['600000.SH'], 'trade_date': [dt.date(2026, 1, 30)],
                         'total_market_value': [1000.]})
    assert compute(keys=keys, events=pl.from_dicts([row]), name='repurchase_strength_30d')['value'].null_count() == 1


def test_flat_d2_and_partitioned_history_use_max_observed_availability(tmp_path):
    root = tmp_path/'clean/repurchase/snapshot=d2_fixture'
    root.mkdir(parents=True)
    (root/'summary.json').write_text('{"status":"captured"}')
    row = event(proc='完成', end_date='20261030', amount=100., observed_at=NOW+dt.timedelta(days=1))
    pl.from_dicts([row]).drop('known_at').write_parquet(root/'data.parquet')
    before, _, _ = read_sources(tmp_path, NOW)
    assert before['repurchase'].is_empty()
    after, _, facts = read_sources(tmp_path, NOW+dt.timedelta(days=1))
    assert after['repurchase']['known_at'].item() == NOW+dt.timedelta(days=1)
    assert facts['repurchase']['rows'] == 1


def test_zero_history_intake_records_null_costs_without_claiming_completed_acceptance(tmp_path, monkeypatch):
    from quant.research.event_family_r6 import run
    from quant.factors.event_family_r6 import SIGNALS
    inputs=tmp_path/'inputs/2025'
    inputs.mkdir(parents=True)
    dates=[dt.date(2025,1,31),dt.date(2025,2,28)]
    labels=pl.DataFrame({'symbol':['600000.SH']*2,'trade_date':dates,
        'exit_date_rebalance':[dt.date(2025,2,3),dt.date(2025,3,3)],'label_rebalance':[.1,.2]})
    labels.write_parquet(inputs/'monthly_labels.parquet')
    labels.select('symbol','trade_date').with_columns(pl.lit(True).alias('eligible'),
        pl.lit(1000.).alias('total_market_value'),pl.lit('industry').alias('industry_l1')).write_parquet(inputs/'universe.parquet')
    controls=tmp_path/'controls'
    controls.mkdir()
    (controls/'summary.json').write_text(json.dumps({'annual_fits':[{'factors':['pit_sue8_context_v2']}]}))
    config=tmp_path/'r6.toml'
    config.write_text('\n'.join([
        'id="r6_fixture"','auto_trade=false','signals='+json.dumps(list(SIGNALS)),
        'variants=["raw","size_industry_neutral"]','cost_multipliers=[0.5,1.0,2.0]',
        'start=2025-01-01','end=2025-12-31',
        'historical_inputs='+json.dumps(str(inputs.parent)),
        'data_root='+json.dumps(str(tmp_path/'data')),
        'battery='+json.dumps(str(Path('configs/factors/battery.toml').resolve())),
        'control_source='+json.dumps(str(controls))]),encoding='utf-8')
    output=tmp_path/'run'
    from quant.reporting import experiment_registry, dashboard_curves
    from quant.reporting.registered_periods import attach
    append=experiment_registry.append_records
    monkeypatch.setattr(dashboard_curves,'catalog',lambda root: [])
    def append_fixture(records):
        receipt=attach(records,tmp_path)
        assert receipt['completed']==0 and len(receipt['unavailable'])==20
        return append(records,tmp_path/'registry.parquet')
    monkeypatch.setattr(experiment_registry,'append_records',append_fixture)
    summary=run(config=config,output=output,register=True)
    assert summary['qualified_months']==0 and summary['repurchase_incremental_nw_t'] is None
    assert summary['acceptance_complete'] is False and summary['costs_executed'] is False
    assert summary['cost_runs']==[]
    registered=pl.read_parquet(tmp_path/'registry.parquet')
    assert registered.height==20 and set(registered['conclusion'])=={'RESEARCH_ONLY'}
    assert registered['cagr_1x'].null_count()==20
    assert json.loads((output/'registration.json').read_text())['registered_factor_versions']==20
    scorecard=pl.read_parquet(output/'scorecard.parquet')
    assert scorecard.height==20 and set(scorecard['conclusion'])=={'RESEARCH_ONLY'}
    assert not scorecard['factor_admitted'].any()
    costs=pl.read_parquet(output/'cost_plan.parquet')
    assert costs.height==60 and costs['cagr'].null_count()==60 and not costs['executed'].any()
    from quant.research.event_family_r6 import digest, render_report
    saved={p:digest(p) for p in output.rglob('*') if p.is_file() and p.name!='report.md'}
    original=(output/'report.md').read_text(encoding='utf-8')
    appendix=original[original.index('<!-- periods-1x:start -->'):]
    render_report(output)
    rendered=(output/'report.md').read_text(encoding='utf-8')
    assert '准入0列；10列×2版本均因历史输入不足未完成统计验收' in rendered
    assert '通过数：0/10' not in rendered
    assert rendered.endswith(appendix)
    assert all(digest(p)==value for p,value in saved.items())
