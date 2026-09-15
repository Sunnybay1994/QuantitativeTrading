import json
from pathlib import Path

import polars as pl
import pytest

from quant.research.monthly_text_statistics import run
from quant.research.monthly_text_cost_inputs import export
from quant.research.factor_battery_cost_batch import run_cost_batch
from tests.unit.test_forecast_text_incremental import SETTINGS, fixture_panel


def test_incomplete_monthly_family_exports_exact_scores_and_skips_costs(tmp_path):
    source = tmp_path / 'statistics'
    run(fixture_panel(99), settings=SETTINGS, output=source)
    output = tmp_path / 'cost_inputs'
    result = export(statistics=source, battery=Path('configs/factors/battery.toml'), output=output)
    assert result['statistical_pass_rows'] == 0 and result['primary_statistical_pass'] == []
    original = pl.read_parquet(source / 'monthly_scores.parquet')
    for factor in original['factor'].unique():
        assert pl.read_parquet(output / 'factors' / factor / 'monthly_scores.parquet').equals(
            original.filter(pl.col('factor') == factor).drop('factor'))
    # All missing ICIR values still constitute the complete family, not an error
    # or an excuse to start three empty account backtests.
    costs = run_cost_batch(statistics=output, screen=output / 'screen', output=tmp_path / 'costs',
        data_root=tmp_path / 'absent_data', execution_snapshot='unused', existing_runs=[],
        workers=1, only_statistical_pass=True)
    assert costs['completed_runs'] == {} and costs['failures'] == {}


def test_partial_family_or_changed_threshold_is_rejected(tmp_path):
    source = tmp_path / 'statistics'
    run(fixture_panel(99), settings=SETTINGS, output=source)
    saved = json.loads((source / 'summary.json').read_text())
    saved['minimum_symbols'] = 99
    (source / 'summary.json').write_text(json.dumps(saved))
    with pytest.raises(ValueError, match='thresholds'):
        export(statistics=source, battery=Path('configs/factors/battery.toml'), output=tmp_path / 'bad')
    assert not (tmp_path / 'bad').exists()
    saved['minimum_symbols'] = 100
    saved['summary'] = saved['summary'][:-1]
    (source / 'summary.json').write_text(json.dumps(saved))
    with pytest.raises(ValueError, match='complete unique'):
        export(statistics=source, battery=Path('configs/factors/battery.toml'), output=tmp_path / 'partial')
