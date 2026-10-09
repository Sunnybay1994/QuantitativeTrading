import datetime as dt
import json
from pathlib import Path
import tomllib

import polars as pl
from polars.testing import assert_frame_equal
import pytest

from quant.factors.turnover_reference import NAMES, CONTROLS, compute_turnover_reference
from quant.factors.expressions import required_history
from quant.research.factor_monthly import attach_monthly_factors
from tests.unit.test_return_seasonality_integration import fixture


def sample():
    bars, calendar = fixture()
    basic = bars.select('symbol', 'trade_date').with_columns(pl.lit(1_000_000.).alias('total_shares'))
    return bars, basic, calendar


def test_thin_reader_preserves_exact_window_and_completed_month_ends(monkeypatch):
    from quant.data import factor_turnover_reference_inputs as inputs
    bars, basic, calendar = sample()
    seen = []
    def read(**kwargs):
        seen.append(kwargs)
        source = bars if kwargs['table'] == 'bar_1d' else basic
        return source.filter(pl.col('trade_date').is_between(kwargs['start'], kwargs['end'])).select(kwargs['columns'])
    monkeypatch.setattr(inputs, 'read_stock_data', read)
    start, end = dt.date(2020, 1, 1), dt.date(2021, 2, 15)
    actual = inputs.read_turnover_reference(data_root=Path('unused'), refresh_config=Path('unused'),
        calendar=calendar, start=start, end=end)
    dates = tuple(a for a, b in zip(calendar, calendar[1:])
        if (a.year, a.month) != (b.year, b.month) and start <= a <= end)
    expected = compute_turnover_reference(bars, basic, sessions=calendar, signal_dates=dates)
    assert_frame_equal(actual, expected)
    assert actual['trade_date'].max() == dt.date(2021, 1, 29)
    assert min(x['start'] for x in seen) == inputs.turnover_reference_start(dates[0])
    assert {x['columns'] for x in seen} == {('symbol', 'trade_date', 'close', 'adj_factor', 'volume'),
        ('symbol', 'trade_date', 'total_shares')}


def test_new_invalid_month_replaces_old_signal_and_all_three_controls():
    bars, basic, calendar = sample()
    signals = (dt.date(2021, 1, 29), dt.date(2021, 2, 26))
    missing = bars.filter(pl.col('trade_date') != dt.date(2021, 2, 1))
    values = compute_turnover_reference(missing, basic, sessions=calendar, signal_dates=signals)
    panel = bars.filter(pl.col('trade_date').is_between(dt.date(2021, 1, 1), dt.date(2021, 3, 2)))
    result = attach_monthly_factors(panel, bars, basic, calendar, NAMES, turnover_reference_values=values)
    for name in (*NAMES, *CONTROLS):
        assert result.filter(pl.col('trade_date') == signals[0])[name].null_count() == 0
        assert result.filter(pl.col('trade_date') == dt.date(2021, 2, 25))[name].null_count() == 0
        assert result.filter(pl.col('trade_date') == signals[1])[name].count() == 0
        assert result.filter(pl.col('trade_date') == dt.date(2021, 3, 1))[name].count() == 0
        assert required_history(name) == 32
        assert required_history(f'ts_mean({name},20)') == 51
    earlier = attach_monthly_factors(panel.filter(pl.col('trade_date') <= dt.date(2021, 2, 15)), bars, basic,
        calendar, NAMES, turnover_reference_values=values.filter(pl.col('trade_date') < signals[1]))
    assert_frame_equal(earlier, result.filter(pl.col('trade_date') <= dt.date(2021, 2, 15)))


def test_projected_stock_reader_keeps_complete_increment_precedence(tmp_path):
    from quant.data.refresh_stocks import read_stock_data
    day = dt.date(2020, 1, 2)
    bars = pl.DataFrame({'symbol': ['x'], 'trade_date': [day], 'close': [10.], 'extra': ['old']})
    old = tmp_path/'clean/tushare_bulk/snapshots/stock/bar_1d/asset=stock/year=2020'
    old.mkdir(parents=True)
    bars.write_parquet(old/'data.parquet')
    config = tmp_path/'refresh.toml'
    config.write_text('stock_snapshot="stock"\ndaily_basic_snapshot="basic"\n')
    increment = tmp_path/'clean/tushare_incremental/date=2020-01-02'
    increment.mkdir(parents=True)
    fresh = bars.with_columns(pl.lit(12.).alias('close'), pl.lit('new').alias('extra'))
    fresh.write_parquet(increment/'bar_1d.parquet')
    args = dict(data_root=tmp_path, config=config, table='bar_1d', start=day, end=day)
    assert read_stock_data(**args, columns=('symbol', 'trade_date', 'close'))['close'].item() == 10.
    for name in ('daily_basic', 'adjust_factor'):
        bars.write_parquet(increment/f'{name}.parquet')
    projected = read_stock_data(**args, columns=('symbol', 'trade_date', 'close'))
    assert projected['close'].item() == 12.
    assert_frame_equal(projected, read_stock_data(**args).select(projected.columns))
    with pytest.raises(ValueError, match='key columns'):
        read_stock_data(**args, columns=('close',))


def test_n4_requires_exact_matched_cohort_and_original_thresholds():
    from quant.research.turnover_reference_controls import RISK_CONTROLS, check_turnover_reference_controls
    spec = tomllib.loads(Path('configs/research/turnover_reference_price_family_v1.toml').read_text())
    assert list(RISK_CONTROLS) == spec['additional_controls'] and list(CONTROLS) == spec['matched_controls']
    columns = ['candidate', 'label', 'admitted', *CONTROLS, *RISK_CONTROLS]
    panel = pl.DataFrame({name: [1., None] if name == 'candidate' else [2., 2.] for name in columns})
    def evaluate(frame, name, controls, direction):
        assert frame.height == 1 and direction == 1 and name == 'candidate'
        assert controls == ['admitted', *CONTROLS, *RISK_CONTROLS]
        return {'months': 96, 'newey_west_t': 2.5}
    assert check_turnover_reference_controls(panel, ['admitted'], evaluate)['passed']
    assert not check_turnover_reference_controls(panel, [], lambda *a: {'months': 95, 'newey_west_t': 20.})['passed']
    missing = panel.with_columns(pl.lit(None, dtype=pl.Float64).alias(CONTROLS[2]))
    result = check_turnover_reference_controls(missing, [], lambda *a: pytest.fail('Do not reduce the matched cohort'))
    assert result['reason'] == 'matched_control_cohort_differs' and not result['passed']
    assert not check_turnover_reference_controls(panel.drop(CONTROLS[0]), [], lambda *a: pytest.fail())['passed']


def test_n3_cached_panels_recover_three_controls_without_rewriting_factors_or_labels(tmp_path, monkeypatch):
    import hashlib
    from quant.factors import compute
    from quant.data import factor_turnover_reference_inputs as inputs
    from tests.unit.test_factor_expressions import prepared
    bars, basic, calendar = sample()
    reads = []
    monkeypatch.setattr(compute, 'available_sessions', lambda root, end: tuple(d for d in calendar if d <= end))
    def read(root, config, start, end, sessions):
        reads.append((start, end))
        selected = bars.filter(pl.col('trade_date').is_between(start, end))
        return prepared(selected), selected
    def source(**kwargs):
        frame = bars if kwargs['table'] == 'bar_1d' else basic
        frame = frame.filter(pl.col('trade_date').is_between(kwargs['start'], kwargs['end']))
        return frame.select(kwargs['columns']) if kwargs.get('columns') else frame
    monkeypatch.setattr(compute, 'read_factor_inputs', read)
    monkeypatch.setattr(compute, 'read_stock_data', source)
    monkeypatch.setattr(inputs, 'read_stock_data', source)
    library = tmp_path/'library'
    library.mkdir()
    for name in NAMES:
        (library/f'{name}.toml').write_text(f'id="{name}"\nexpr="{name}"\ndirection=1\n'
            'family="turnover_reference_adjusted_price_v1"\nsource_ref="fixture"\n')
    args = dict(data_root=tmp_path/'data', refresh_config=Path('unused'), library=library,
        selected='all', start=dt.date(2020, 1, 1), end=dt.date(2022, 2, 15))
    compute.run(**args, artifact_root=tmp_path/'first')
    def shared():
        return {str(p): (p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest())
            for p in (tmp_path/'data').rglob('*') if p.is_file()}
    before = shared()
    compute.run(**args, artifact_root=tmp_path/'second')
    first = sorted((tmp_path/'first/turnover_reference_controls').glob('*.parquet'))
    assert len(first) == 3
    for path in first:
        recovered = tmp_path/'second/turnover_reference_controls'/path.name
        assert_frame_equal(pl.read_parquet(path), pl.read_parquet(recovered))
        assert tuple(pl.read_parquet(path).columns[2:]) == CONTROLS
    assert shared() == before
    count = len(reads)
    compute.run(**args, artifact_root=tmp_path/'second')
    assert len(reads) == count
    damaged = tmp_path/'second/turnover_reference_controls/year=2021.parquet'
    damaged.write_bytes(b'interrupted_control_write')
    compute.run(**args, artifact_root=tmp_path/'second')
    assert len(reads) == count+1
    assert_frame_equal(pl.read_parquet(damaged), pl.read_parquet(tmp_path/'first/turnover_reference_controls/year=2021.parquet'))
    assert shared() == before


def test_n4_dispatch_loads_matching_controls_and_cannot_skip_family_failure(tmp_path, monkeypatch):
    from quant.research import nightly_steps as steps, turnover_reference_controls as family
    from quant.data import nightly_genetic_inputs as data
    from quant.data.factor_control_receipts import write_control_receipt
    run, batch, library = tmp_path/'run', tmp_path/'batch', tmp_path/'library'
    name, day = NAMES[0], dt.date(2026, 8, 31)
    for path in (run/'N3', run/'N4', batch/'library', library, tmp_path/'reference', tmp_path/'queue/processing'):
        path.mkdir(parents=True)
    (batch/'library'/f'{name}.toml').write_text(f'id="{name}"\nexpr="{name}"\ndirection=1\n'
        'family="turnover_reference_adjusted_price_v1"\nsource_ref="registered_battery:test"\n')
    (library/'ref.toml').write_text('id="ref"\nexpr="close"\ndirection=1\nfamily="other"\nsource_ref="test"\n')
    card = batch/'scorecard.parquet'
    pl.DataFrame({'factor': [name], 'variant': ['raw'], 'factor_admitted': [True]}).write_parquet(card)
    (run/'N3/result.json').write_text(json.dumps({'evaluated': 1, 'batch': str(batch), 'scorecard': str(card)}))
    (tmp_path/'reference/battery.toml').write_text('[run]\nas_of=2026-08-31\n')
    keys = pl.DataFrame({'symbol': ['x'], 'trade_date': [day]})
    folder = batch/'evaluation/statistics/factors'/name
    folder.mkdir(parents=True)
    keys.with_columns(pl.lit(1.).alias('raw'), pl.lit(9.).alias('size_industry_neutral')).write_parquet(folder/'monthly_scores.parquet')
    write_control_receipt(batch/'compute/turnover_reference_controls/year=2026.parquet',
        keys.with_columns(*[pl.lit(float(i)).alias(n) for i, n in enumerate(CONTROLS)]), start=day, end=day, columns=CONTROLS)
    monkeypatch.setattr(data, 'admitted_controls', lambda *a: (keys, []))
    monkeypatch.setattr(data, 'read_raw_monthly', lambda **kw: keys.with_columns(pl.lit(day).alias('label_exit_date')))
    monkeypatch.setattr(steps, 'incremental_statistics', lambda *a: {'months': 120, 'newey_west_t': 4., 'complete_control_fraction': 1.})
    monkeypatch.setattr(steps, 'maximum_correlation', lambda *a: .1)
    seen = []
    def reject(frame, admitted, evaluate):
        seen.append(frame['candidate'].item())
        assert all(n in frame.columns for n in CONTROLS)
        return {'passed': False, 'reason': 'fixed_controls_failed'}
    monkeypatch.setattr(family, 'check_turnover_reference_controls', reject)
    settings = {'library': str(library), 'reference_scorecard': str(card), 'reference_statistics': str(tmp_path/'reference'),
        'as_of': day, 'history_start': day, 'data_root': str(tmp_path/'data'),
        'rejected_root': str(tmp_path/'rejected'), 'queue': str(tmp_path/'queue')}
    result = steps.admit(settings, run)
    assert seen == [9.] and result['admitted'] == 0 and result['rejected'] == 1
    assert not (library/'auto'/f'{name}.toml').exists()
