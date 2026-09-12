import datetime as dt
import json
from pathlib import Path

import polars as pl
import pytest

from quant.reporting import run_factor_health as runner


def test_reference_calendar_window_excludes_current_month():
    assert runner.reference_start(dt.date(2024, 2, 29), 12) == dt.date(2023, 2, 1)
    assert runner.reference_start(dt.date(2023, 1, 31), 1) == dt.date(2022, 12, 1)
    with pytest.raises(ValueError, match='positive'):
        runner.reference_start(dt.date(2023, 1, 31), 0)


def test_runner_uses_only_prior_calendar_months_and_preserves_existing_run(tmp_path, monkeypatch):
    dates = [dt.date(2022, 12, 30), dt.date(2023, 1, 31), dt.date(2023, 2, 28)]
    config = tmp_path / 'config.toml'
    config.write_text('''[diagnostics]
selection = "selection"
statistics = "statistics"
start = 2023-01-01
end = 2023-02-28
reference_months = 1
maximum_factors = 20
diagnostics_only = true
[statistics]
minimum_symbols = 2
minimum_reference_months = 1
''', encoding='utf-8')
    calls = []
    monkeypatch.setattr(runner, 'read_factor_health_month_ends', lambda **kwargs: dates)
    monkeypatch.setattr(runner, 'read_factor_health_selection', lambda **kwargs: pl.DataFrame({
        'as_of': dates[1:], 'factor': ['original'] * 2, 'factor_id': ['raw_panel'] * 2,
        'test_year': [2023] * 2, 'refit_close': [dates[0]] * 2,
        'variant': ['size_industry_neutral'] * 2}))

    def inputs(**kwargs):
        calls.append(kwargs)
        return pl.DataFrame({'symbol': ['A', 'B'] * 3,
            'trade_date': [day for day in dates for _ in range(2)],
            'value': [1., 3., 2., 4., 1.e20, -1.e20],
            'raw_value_status': ['observed'] * 6,
            'industry_l1': ['X', 'Y'] * 3, 'total_market_value': [100., 200.] * 3})

    diagnostics = []
    real_diagnose = runner.diagnose_factor_health

    def diagnose(current, reference, *, as_of, parameters):
        diagnostics.append((as_of, current, reference))
        assert reference['trade_date'].max() < as_of.replace(day=1)
        result = real_diagnose(current, reference, as_of=as_of, parameters=parameters)
        result['drift']['past_value_mean'] = reference['value'].mean()
        return result

    monkeypatch.setattr(runner, 'read_factor_health_inputs', inputs)
    monkeypatch.setattr(runner, 'diagnose_factor_health', diagnose)
    output = tmp_path / 'output'
    summary = runner.run_factor_health(config=config, output=output, data_root=Path('data'))
    assert len(calls) == 1 and calls[0]['factor_id'] == 'raw_panel'
    assert diagnostics[0][2]['trade_date'].unique().to_list() == [dates[0]]
    assert diagnostics[1][2]['trade_date'].unique().to_list() == [dates[1]]
    assert summary['factor_months'] == 2
    saved = pl.read_parquet(output / 'health.parquet')
    assert saved['drift_past_value_mean'].to_list() == [2., 3.]
    records = [json.loads(line) for line in (output / 'health.jsonl').read_text().splitlines()]
    assert records[0]['factor'] == 'original'
    assert records[0]['raw_status_counts']['missing_row'] == 0
    original = (output / 'health.parquet').read_bytes()
    with pytest.raises(FileExistsError):
        runner.run_factor_health(config=config, output=output, data_root=Path('data'))
    assert (output / 'health.parquet').read_bytes() == original


def test_runner_rejects_reference_requirement_larger_than_window(tmp_path):
    config = tmp_path / 'config.toml'
    config.write_text('''[diagnostics]
start = 2023-01-01
end = 2023-02-28
reference_months = 1
diagnostics_only = true
[statistics]
minimum_reference_months = 12
''', encoding='utf-8')
    with pytest.raises(ValueError, match='exceeds'):
        runner.run_factor_health(config=config, output=tmp_path / 'output', data_root=tmp_path)
