"""A3 forward rules: attention can fire without demote in the demo window."""
from pathlib import Path
import calendar
import datetime as dt
import json

import tomllib
import polars as pl
import pytest

from quant.reporting import q10_forward_rules as forward

ROOT = Path(__file__).resolve().parents[2]
RULES = ROOT / "configs/paper/q10_sue_v2_forward_rules_20261010.toml"


def test_forward_rules_frozen_fields():
    spec = tomllib.loads(RULES.read_text(encoding="utf-8"))
    assert spec["auto_trade"] is False
    assert spec["demote_to_research_only"]["minimum_complete_oos_months"] == 12
    assert spec["attention"]["cumulative_oos_excess_below"] == -0.05
    assert spec["halt_review"]["threshold_mdd"] == -0.3792


def _synthetic_demo(tmp_path, monkeypatch, june_return):
    periods = [(2025,m) for m in range(8,13)] + [(2026,m) for m in range(1,7)]
    dates = [dt.date(2025,7,31)] + [dt.date(y,m,calendar.monthrange(y,m)[1]) for y,m in periods]
    nav1 = pl.DataFrame({'date':dates, 'unit_nav':[1.]*(len(dates)-1)+[1+june_return]})
    nav2 = nav1.with_columns((pl.col('unit_nav')*.999).alias('unit_nav'))
    benchmark = pl.DataFrame({'date':dates, 'unit_nav':[1.]*len(dates)})
    spec = tomllib.loads(RULES.read_text(encoding='utf-8'))

    def benches(**kwargs):
        assert kwargs['data_root'] == tmp_path/'data'
        assert kwargs['names'] == spec['benchmarks']
        return dict.fromkeys(kwargs['names'], benchmark)

    monkeypatch.setattr(forward, 'load_return_benchmarks', benches)
    return forward.demo_replay_attention(rules_path=RULES, nav_1x=nav1, nav_2x=nav2,
        benchmark_config=tmp_path/'synthetic_benchmarks.toml', data_root=tmp_path/'data',
        months=[f'{y}-{m:02d}' for y,m in periods])


def test_demo_assertion_artifact(tmp_path, monkeypatch):
    # Exercise real rule calculations/writer with synthetic NAVs, not a production file.
    result = _synthetic_demo(tmp_path, monkeypatch, -.06)
    path = tmp_path/'demo.json'
    path.write_text(json.dumps(result,default=str),encoding='utf-8')
    assert path.exists()

    result = json.loads(path.read_text(encoding="utf-8"))
    assert result["assertion"]["2026-06_status_is_attention"] is True
    assert result["assertion"]["2026-06_demote_false"] is True
    june = result['months'][-1]
    assert june['month_excess_primary'] == pytest.approx(-.06)
    assert june['complete_oos_months'] == 11
    assert june['halt_review']['requires_user_confirmation'] is True
    stem = tmp_path/'monthly/2026-06_fixture'
    forward.write_monthly_package(stem=stem, evaluation=june)
    assert json.loads(stem.with_suffix('.json').read_text(encoding='utf-8')) == june
    assert 'attention' in stem.with_suffix('.md').read_text(encoding='utf-8')


def test_flat_synthetic_demo_does_not_manufacture_attention(tmp_path, monkeypatch):
    result = _synthetic_demo(tmp_path, monkeypatch, 0.)
    assert result['assertion']['2026-06_status_is_attention'] is False
    assert result['assertion']['2026-06_demote_false'] is True
    assert result['months'][-1]['attention_flags'] == []
