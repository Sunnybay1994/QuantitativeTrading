import tomllib
from pathlib import Path

import polars as pl
import pytest

from quant.research.factor_battery_cost_batch import cost_order, existing_cost_factor, run_cost_batch


def test_cost_order_prioritizes_passes_then_primary_icir_and_keeps_rejections():
    table = pl.DataFrame({'factor': ['b', 'a', 'c', 'd'], 'variant': ['neutral']*4,
                          'statistical_pass': [True, True, False, False], 'icir': [.5, .5, .9, None]})
    assert cost_order(table, primary='neutral') == ['a', 'b', 'c', 'd']


def test_inflight_cost_run_is_reserved_and_incompatible_snapshot_rejected(tmp_path):
    config = Path('configs/factors/battery.toml').read_bytes()
    config += b'\n[run]\nas_of = 2026-08-31\nselected = "all"\n'
    settings = tomllib.loads(config.decode())
    (tmp_path/'battery.toml').write_bytes(config+b'\n[cost_replay]\nfactor = "sample"\nexecution_snapshot = "fixture"\n')
    assert existing_cost_factor(tmp_path, settings=settings, snapshot='fixture') == 'sample'
    assert not (tmp_path/'summary.json').exists()
    with pytest.raises(ValueError, match='different settings'):
        existing_cost_factor(tmp_path, settings=settings, snapshot='other')


def test_cost_batch_rejects_a_screen_missing_registered_rows(tmp_path):
    statistics, screen = tmp_path/'statistics', tmp_path/'screen'
    statistics.mkdir()
    screen.mkdir()
    config = Path('configs/factors/battery.toml').read_bytes()
    (statistics/'battery.toml').write_bytes(config)
    (screen/'battery.toml').write_bytes(config)
    expected = pl.DataFrame({'factor': ['a', 'a'], 'variant': ['raw', 'size_industry_neutral']})
    expected.write_parquet(statistics/'statistics.parquet')
    expected.head(1).write_parquet(screen/'statistical_screen.parquet')
    with pytest.raises(ValueError, match='cannot omit'):
        run_cost_batch(statistics=statistics, screen=screen, output=tmp_path/'output', data_root=tmp_path,
                       execution_snapshot='fixture', existing_runs=[], workers=1)
