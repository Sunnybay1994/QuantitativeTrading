import numpy as np
import polars as pl

from quant.research.forecast_text_incremental import _ic, diagnose_sections, residualize_text
from quant.research.text_quadratic_diagnostic import project, run
from tests.unit.test_forecast_text_incremental import SETTINGS, fixture_panel


def test_quadratic_numeric_signal_fools_linear_projection_but_not_quadratic():
    x = np.linspace(-1., 1., 120)
    text = 3 * x ** 2
    industry = np.array(['one'] * len(x))
    linear, _ = residualize_text(text, x, np.zeros(120), np.ones(120), industry)
    assert _ic(linear, text) > .99
    quadratic, rank = project(text, np.column_stack([x, np.zeros(120), np.zeros(120)]), industry)
    assert rank == 3
    assert np.isnan(quadratic).all()


def test_saved_support_preserves_pairs_and_return_values_do_not_change_projection(tmp_path):
    panel = fixture_panel()
    _, support = diagnose_sections(panel, label='label_rebalance', frequency='monthly', settings=SETTINGS)
    support = support.rename({'pit_sue8': 'pit_sue8_context_v2'})
    for name, frame in [('original', support), ('inverse', support.with_columns(-pl.col('next_open_label')))]:
        path = tmp_path / f'{name}.parquet'
        frame.write_parquet(path)
        result = run(path, output=tmp_path / name)
        assert result['sections'] == 9
        assert result['usable_quadratic_sections'] == 9
    a = pl.read_parquet(tmp_path / 'original/paired_ic.parquet')
    b = pl.read_parquet(tmp_path / 'inverse/paired_ic.parquet')
    assert a['common_count'].to_list() == [120] * 9
    assert a['quadratic_rank'].equals(b['quadratic_rank'])
    np.testing.assert_allclose(a['quadratic_residual_ic'], -b['quadratic_residual_ic'], atol=1e-12)


def test_missing_primary_coverage_never_resurrected(tmp_path):
    _, support = diagnose_sections(fixture_panel(99), label='label_rebalance', frequency='monthly', settings=SETTINGS)
    support.rename({'pit_sue8': 'pit_sue8_context_v2'}).write_parquet(tmp_path / 'support.parquet')
    result = run(tmp_path / 'support.parquet', output=tmp_path / 'out')
    assert result['sections'] == 9
    assert result['usable_quadratic_sections'] == 0
