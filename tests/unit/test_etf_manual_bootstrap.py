import datetime as dt
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl
import pytest

from quant.execution.etf_manual_bootstrap import coverage, initialize


CONFIG = Path('configs/research/b16_manual_forward_v1.toml')


def calendar():
    return pl.DataFrame({'date': [dt.date(2026, 9, 30), dt.date(2026, 10, 8)],
                         'is_open': [True, True]})


def test_repeat_preserves_cash_and_does_not_enable_fills(tmp_path):
    output = tmp_path / 'account'
    first = initialize(CONFIG, output, calendar())
    path = output / 'delay_120/cost_1/opening.json'
    before = path.read_bytes()
    assert initialize(CONFIG, output, calendar()) == first
    assert path.read_bytes() == before
    assert not first['fills_enabled']
    assert json.loads(before)['valuation']['equity'] == 100000


def test_existing_account_cannot_be_reset(tmp_path):
    initialize(CONFIG, tmp_path, calendar())
    path = tmp_path / 'delay_120/cost_1/opening.json'
    book = json.loads(path.read_text())
    book['cash'] -= 10
    path.write_text(json.dumps(book))
    with pytest.raises(ValueError, match='Preserve existing'):
        initialize(CONFIG, tmp_path, calendar())
    assert json.loads(path.read_text())['cash'] == 99990


def test_wrong_exchange_date_fails_before_account_creation(tmp_path):
    cal = pl.DataFrame({'date': [dt.date(2026, 9, 30), dt.date(2026, 10, 1)],
                        'is_open': [True, True]})
    with pytest.raises(ValueError, match='month end'):
        initialize(CONFIG, tmp_path / 'account', cal)
    assert not (tmp_path / 'account').exists()


def test_coverage_uses_exchange_timezone_and_counts_missing(tmp_path):
    targets = tmp_path / 'targets.parquet'
    pl.DataFrame({'execution_date': [dt.date(2026, 10, 8)]}).write_parquet(targets)
    source = tmp_path / 'clean/bar_intraday/freq=1m/source=tdx/symbol=510300.SH'
    source.mkdir(parents=True)
    pl.DataFrame({'bar_start': [dt.datetime(2026, 10, 8, 9, 32,
                    tzinfo=ZoneInfo('Asia/Shanghai'))]}).write_parquet(source / 'data.parquet')
    coverage(tmp_path, targets, tmp_path / 'report', ['510300.SH'])
    result = json.loads((tmp_path / 'report/summary.json').read_text())
    assert result['matched_rows'] == 1
    assert result['required_rows'] == 2
