"""Numerical parity with the pre-projection implementation on synthetic panels."""
import datetime as dt

import numpy as np
import polars as pl
import pytest

from quant.research.factor_battery_statistics import monthly_ic_summary, rank_ic_by_date
from quant.research.nightly_steps import incremental_statistics


def original_incremental_statistics(panel, candidate, controls, direction):
    """Frozen reference: the original body before narrowing its input columns."""
    rows = []
    for section in panel.partition_by('trade_date'):
        paired = section.filter(pl.all_horizontal(
            pl.col(c).is_finite() for c in [candidate, 'label', *controls]))
        if paired.height < max(100, len(controls)+2):
            continue
        ranks = paired.select(pl.col(c).rank('average') for c in [candidate, *controls]).to_numpy()
        ranks = (ranks-ranks.mean(axis=0))/np.maximum(ranks.std(axis=0), 1e-12)
        x = np.column_stack([np.ones(paired.height), ranks[:, 1:]])
        residual = direction*(ranks[:, 0]-x@np.linalg.lstsq(x, ranks[:, 0], rcond=None)[0])
        if np.std(residual) < 1e-10:
            continue
        scores = paired.select('symbol', 'trade_date', 'label').with_columns(
            pl.Series('residual', residual))
        ic = rank_ic_by_date(scores, score='residual', label='label', minimum_symbols=100,
                            minimum_paired_coverage=.95)
        rows.extend(ic.select('trade_date', 'rank_ic').to_dicts())
    rows.sort(key=lambda row: row['trade_date'])
    result = monthly_ic_summary([r['trade_date'] for r in rows], [r['rank_ic'] for r in rows], lag=6)
    complete = panel.filter(pl.all_horizontal(
        pl.col(c).is_finite() for c in [candidate, 'label', *controls])).height
    result.update(input_rows=panel.height, complete_control_rows=complete,
                  complete_control_fraction=complete/panel.height if panel.height else 0.)
    return result


def synthetic_panel(*, irrelevant_columns=0, stocks=140, months=12):
    """Ties, collinear controls and valid/invalid monthly masks coexist."""
    rng = np.random.default_rng(20260920)
    rows = []
    for month in range(months):
        for stock in range(stocks):
            a, b, c = rng.integers(-8, 9, size=3).astype(float)
            candidate = float(stock % 11) if month != 3 else 1.
            label = candidate*.1 + a*.01 + float(rng.normal())
            row = {'symbol': f's{stock:04}', 'trade_date': dt.date(2020+month//12, month % 12+1, 15),
                   'label': label, 'candidate': candidate, 'control_a': a,
                   'control_b': b if month != 7 else a, 'control_c': c}
            if month == 1 and stock < 10:
                row['candidate'] = None
            if month == 2 and stock < 15:
                row['control_a'] = float('nan')
            if month == 4:
                row['label'] = None
            if month == 5 and stock >= 99:
                row['control_b'] = float('inf')
            if month == 6 and stock >= 100:
                row['candidate'] = float('-inf')
            rows.append(row)
    panel = pl.from_dicts(rows)
    # Preserve a nontrivial input ordering to catch accidental key sorts.
    panel = panel.reverse()
    if irrelevant_columns:
        panel = panel.with_columns(pl.Series(f'unused_{i}', rng.normal(size=panel.height))
                                   for i in range(irrelevant_columns))
        panel = panel.with_columns(pl.lit(None).alias('unused_null'),
                                   pl.lit(float('inf')).alias('unused_infinite'),
                                   pl.lit('unrelated industry').alias('unused_text'))
    return panel


@pytest.mark.parametrize('direction', [1, -1])
@pytest.mark.parametrize('irrelevant_columns', [0, 383])
def test_projection_matches_original_with_missing_ties_constants_and_invalid_months(
        direction, irrelevant_columns):
    panel = synthetic_panel(irrelevant_columns=irrelevant_columns)
    controls = ['control_a', 'control_b', 'control_c']
    expected = original_incremental_statistics(panel, 'candidate', controls, direction)
    actual = incremental_statistics(panel, 'candidate', controls, direction)
    assert actual == expected
    assert 0 < actual['months'] < 12
    assert 0 < actual['complete_control_fraction'] < 1
    assert actual['input_rows'] == 1680


@pytest.mark.parametrize('direction', [1, -1])
def test_wide_and_narrow_results_and_row_order_are_identical(direction, monkeypatch):
    wide = synthetic_panel(irrelevant_columns=383)
    controls = ['control_a', 'control_b', 'control_c']
    fields = ['symbol', 'trade_date', 'label', 'candidate', *controls]
    expected = original_incremental_statistics(wide.select(fields), 'candidate', controls, direction)
    original_partition = pl.DataFrame.partition_by
    observed = []

    def inspect_partition(frame, *args, **kwargs):
        observed.append((frame.columns, frame.select('symbol', 'trade_date').rows()))
        return original_partition(frame, *args, **kwargs)

    monkeypatch.setattr(pl.DataFrame, 'partition_by', inspect_partition)
    assert incremental_statistics(wide, 'candidate', controls, direction) == expected
    assert incremental_statistics(wide.select(fields), 'candidate', controls, direction) == expected
    assert observed == [(fields, wide.select('symbol', 'trade_date').rows())] * 2


@pytest.mark.parametrize('invalid', ['all_constant', 'all_missing', 'empty'])
def test_projection_preserves_zero_valid_months_and_input_counts(invalid):
    panel = synthetic_panel(irrelevant_columns=20)
    if invalid == 'all_constant':
        panel = panel.with_columns(pl.lit(1.).alias('candidate'))
    elif invalid == 'all_missing':
        panel = panel.with_columns(pl.lit(None, dtype=pl.Float64).alias('control_a'))
    else:
        panel = panel.head(0)
    controls = ['control_a', 'control_b', 'control_c']
    expected = original_incremental_statistics(panel, 'candidate', controls, 1)
    assert incremental_statistics(panel, 'candidate', controls, 1) == expected
    assert expected['months'] == 0 and expected['mean_ic'] is None
