import datetime as dt
import json

import polars as pl
import pytest

from quant.reporting import capacity_report as report


def test_report_rejects_gross_fills_above_saved_cap(tmp_path, monkeypatch):
    (tmp_path/'summary.json').write_text(json.dumps({'rows': []}))
    (tmp_path/'config.toml').write_text('initial_capitals=[1000000]\n')
    (tmp_path/'model.toml').write_text('[walk_forward]\ntest_end=2026-09-14\n')
    d0, d1 = dt.date(2026, 9, 11), dt.date(2026, 9, 14)
    monkeypatch.setattr(report, 'available_sessions', lambda *a: (d0, d1))
    folder = tmp_path/'capital_1000000/budgeted/cost_1/2026'
    folder.mkdir(parents=True)
    (folder/'constraints.json').write_text(json.dumps([{'as_of': str(d0), 'execution_notional_caps': {'A': 100.}}]))
    pl.DataFrame({'date': [d1, d1], 'symbol': ['A', 'A'], 'notional': [60., 60.]}).write_parquet(folder/'trades.parquet')
    with pytest.raises(ValueError, match='exceeds cap'):
        report.run(tmp_path)
    assert not (tmp_path/'assessment.json').exists()
