import datetime as dt

import polars as pl
import pytest

from quant.research import capacity_diagnostic as module


def test_uses_prior_session_not_execution_day_liquidity(tmp_path, monkeypatch):
    source = tmp_path/'source'
    trades = source/'budgeted/cost_1/2026'
    trades.mkdir(parents=True)
    (source/'battery.toml').write_text('[portfolio]\ninitial_cash=1000000\n')
    d0, d1 = dt.date(2026, 9, 11), dt.date(2026, 9, 14)
    pl.DataFrame({'date': [d1, d1], 'symbol': ['A', 'B'], 'notional': [100., 200.]}).write_parquet(trades/'trades.parquet')
    universe = tmp_path/'statistics/inputs/2026'
    universe.mkdir(parents=True)
    pl.DataFrame({'trade_date': [d0, d1], 'symbol': ['A', 'A'], 'amount20': [1000., 1000000.]}).write_parquet(universe/'universe.parquet')
    monkeypatch.setattr(module, 'available_sessions', lambda *a: (d0, d1))
    config = tmp_path/'config.toml'
    config.write_text(f'source="{source.as_posix()}"\nstatistics="{(tmp_path/"statistics").as_posix()}"\ninitial_capitals=[1000000]\nparticipation_limit=0.05\nauto_trade=false\nmethod="test"\n')
    result = module.run(config, tmp_path/'output')
    row = result['rows'][0]
    assert row['maximum_participation'] == pytest.approx(.1)
    assert row['above_5pct'] == 1 and row['missing_adv'] == 1
    assert result['capacity_verified'] is False
