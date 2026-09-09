import datetime as dt
from pathlib import Path

import polars as pl
import pytest

from quant.data import etf_limits
from quant.data.etf_paper_inputs import etf_session_states

D = dt.date(2026, 9, 8)


def raw():
    return pl.DataFrame({"ts_code": ["510300.SH"], "trade_date": ["20260908"],
                         "up_limit": [11.0], "down_limit": [9.0]})


def test_refresh_coverage_and_noop(monkeypatch, tmp_path: Path):
    calls = []

    class Connector:
        def __init__(self, **kwargs):
            pass

        def query_raw(self, api, **kwargs):
            calls.append(api)
            return raw()

    monkeypatch.setattr(etf_limits, "TushareConnector", Connector)
    monkeypatch.setattr(etf_limits, "expected_open_dates", lambda *a: [D])
    monkeypatch.setattr(etf_limits.time, "sleep", lambda _: None)
    args = dict(data_root=tmp_path, symbols=["510300.SH"], start=D, end=D)
    assert etf_limits.refresh_limits(**args) == 1
    assert etf_limits.refresh_limits(**args) == 0
    assert calls == ["etf_limit"]
    monkeypatch.setattr(etf_limits, "expected_open_dates", lambda *a: [D, D + dt.timedelta(days=1)])
    with pytest.raises(ValueError, match="coverage"):
        etf_limits.refresh_limits(**{**args, "end": D + dt.timedelta(days=1)})
    assert etf_limits.read_limits(tmp_path).height == 1


def test_actual_bands_slippage_missing_and_bad_data():
    limits = raw().rename({"ts_code": "symbol"}).with_columns(
        pl.col("trade_date").str.to_date("%Y%m%d"))
    bars = pl.DataFrame({"symbol": ["510300.SH"], "trade_date": [D],
                         "open": [10.995], "volume": [100.0]})
    assert not etf_session_states(bars, pl.DataFrame(), official_limits=limits)[D, "510300.SH"].at_upper_limit
    assert etf_session_states(bars, pl.DataFrame(), official_limits=limits,
                              slippage=0.001)[D, "510300.SH"].at_upper_limit
    with pytest.raises(ValueError, match="missing"):
        etf_session_states(bars, pl.DataFrame(), official_limits=limits.head(0))
    with pytest.raises(ValueError, match="Invalid"):
        etf_limits.validate_limits(pl.concat([limits, limits]))
    with pytest.raises(ValueError, match="Invalid"):
        etf_limits.validate_limits(limits.with_columns(pl.lit(float("nan")).alias("up_limit")))
