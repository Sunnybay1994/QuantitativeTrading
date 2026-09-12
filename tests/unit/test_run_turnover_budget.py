import copy
import datetime as dt

import polars as pl
import pytest

from quant.research import run_turnover_budget as runner


def test_assessment_uses_return_names_and_requires_common_holding_window(monkeypatch):
    rows = [{'variant': v, 'cost_multiplier': c, 'active_start': dt.date(2019, 1, 2)}
            for v in ('control', 'budgeted') for c in (.5, 1., 2.)]
    model = {'admission': {'benchmarks': ['old_account']}}
    original = copy.deepcopy(model)
    seen = []
    def assess(**kwargs):
        seen.append(kwargs)
        return {'conclusion': 'REJECTED'}
    monkeypatch.setattr(runner, 'assess_model', assess)
    baselines = {'all_market_equal_weight': pl.DataFrame({'date': [dt.date(2019, 1, 2)], 'unit_nav': [1.]})}
    result = runner.assess_budget_variants(histories={'control': pl.DataFrame(), 'budgeted': pl.DataFrame()},
        rows=rows, baselines=baselines, model=model, windows=[])
    assert set(result) == {'control', 'budgeted'}
    assert seen[0]['model']['admission']['benchmarks'] == list(baselines)
    assert model == original
    rows[-1]['active_start'] = dt.date(2019, 1, 3)
    with pytest.raises(ValueError, match='identical holding windows'):
        runner.assess_budget_variants(histories={}, rows=rows, baselines=baselines, model=model, windows=[])


def test_legacy_account_measurement_cannot_start(tmp_path):
    config = tmp_path/'config.toml'
    config.write_text('[research]\n[policy]\nauto_trade=false\n', encoding='utf-8')
    with pytest.raises(ValueError, match='return_benchmark_config'):
        runner.run(config=config, output=tmp_path/'run', data_root=tmp_path)


def test_unknown_allocation_fails_before_reading_inputs(tmp_path):
    config = tmp_path/'config.toml'
    config.write_text('[research]\nreturn_benchmark_config="absent.toml"\n'
        '[policy]\nauto_trade=false\nallocation="typo"\n', encoding='utf-8')
    with pytest.raises(ValueError, match='allocation'):
        runner.run(config=config, output=tmp_path/'run', data_root=tmp_path)
    assert not (tmp_path/'run').exists()


def test_cash_stress_window_renders_na_without_fake_pass(tmp_path):
    assessment = {'conclusion': 'REJECTED', 'checks': {'stress': False},
        'strongest_benchmark': 'all_market_equal_weight', 'net_cagr_excess': .01,
        'stress_windows_not_worse': 0, 'stress_windows_total': 4,
        'stress': [{'window': 'before_entry', 'applicable': False, 'not_worse': None, 'reason': 'before_holding_window'}]}
    runner.write_budget_report(tmp_path, {'rows': [], 'assessments': {'control': assessment}})
    report = (tmp_path/'report.md').read_text(encoding='utf-8')
    assert '|before_entry|NA|NA|不适用：before_holding_window|' in report
    assert '压力通过 0/4' in report
