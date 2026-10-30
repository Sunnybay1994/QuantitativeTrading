"""Forward dates after frozen battery run.as_of use read_forward_universe."""
import datetime as dt
from pathlib import Path

import polars as pl
import pytest

from quant.data import factor_battery_inputs as fbi


def _frame(day: dt.date, symbol: str = "000001.SZ") -> pl.DataFrame:
    return pl.DataFrame({
        "symbol": [symbol],
        "trade_date": [day],
        "eligible": [True],
        "industry_l1": ["银行"],
        "total_market_value": [1e10],
        "amount20": [1e8],
        "traded": [True],
        "limits_known": [True],
        "away_from_limits": [True],
        "close": [10.0],
        "up_limit": [11.0],
        "down_limit": [9.0],
    })


def test_read_battery_universe_dates_uses_forward_after_run_as_of(tmp_path, monkeypatch):
    statistics = tmp_path / "stats"
    (statistics / "inputs" / "2026").mkdir(parents=True)
    frozen_day = dt.date(2026, 8, 31)
    forward_day = dt.date(2026, 10, 30)
    _frame(frozen_day).write_parquet(statistics / "inputs" / "2026" / "universe.parquet")
    (statistics / "battery.toml").write_text(
        "start = 2017-01-01\n"
        "[data]\nrefresh_config = \"configs/data/refresh.toml\"\n"
        "limits_snapshot = \"limits_20260911\"\n"
        "[universe]\nminimum_listing_days = 120\n"
        "amount_window_sessions = 20\n"
        "amount_exclude_bottom_fraction = 0.2\n"
        "[run]\nas_of = 2026-08-31\n",
        encoding="utf-8",
    )
    calls = []

    def fake_forward(*, data_root, settings, as_of):
        calls.append(as_of)
        assert as_of == forward_day
        assert data_root == tmp_path / "data"
        return _frame(as_of)

    monkeypatch.setattr("quant.data.model_forward_inputs.read_forward_universe", fake_forward)
    # Import binding inside fbi uses local import; patch the module attribute used at call time.
    import quant.data.model_forward_inputs as mfi
    monkeypatch.setattr(mfi, "read_forward_universe", fake_forward)

    with pytest.raises(ValueError, match="Missing frozen universe trade dates"):
        fbi.read_battery_universe_dates(
            statistics=statistics, as_of_dates=[frozen_day, forward_day],
            data_root=None, include_tradeability=True)

    result = fbi.read_battery_universe_dates(
        statistics=statistics, as_of_dates=[frozen_day, forward_day],
        data_root=tmp_path / "data", include_tradeability=True)
    assert calls == [forward_day]
    assert sorted(result["trade_date"].unique().to_list()) == [frozen_day, forward_day]
    assert set(result.columns) >= {
        "symbol", "trade_date", "eligible", "total_market_value", "amount20", "traded",
    }
