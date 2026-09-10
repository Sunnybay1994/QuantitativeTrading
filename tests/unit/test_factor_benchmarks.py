import datetime as dt
import json

import polars as pl
import pytest

from quant.data import factor_benchmarks


def test_monthly_capture_preserves_raw_and_reports_missing_month(tmp_path, monkeypatch):
    calls = []
    frame = pl.DataFrame({"index_code": ["000906.SH"]*2, "con_code": ["600000.SH", "000001.SZ"],
        "trade_date": ["20200131"]*2, "weight": [55.0, 45.0]})

    class Client:
        def __init__(self, **kwargs):
            pass

        def query_raw(self, endpoint, **params):
            calls.append((endpoint, params))
            return frame if len(calls) == 1 else frame.head(0)

    monkeypatch.setattr(factor_benchmarks, "TushareConnector", Client)
    monkeypatch.setattr(factor_benchmarks.time, "sleep", lambda value: None)
    summary = factor_benchmarks.capture_csi800(data_root=tmp_path, name="fixture",
        start=dt.date(2020,1,1), end=dt.date(2020,2,29))
    assert len(calls) == 2
    assert calls[1][1]["start_date"] == "20200201" and calls[1][1]["end_date"] == "20200229"
    assert summary["empty_months"] == ["2020-02"]
    assert summary["minimum_members"] == summary["maximum_members"] == 2
    assert len(summary["raw"]) == 2
    for row in summary["raw"]:
        assert pl.read_parquet(row["raw"]).height == row["rows"]
    stored = json.loads((tmp_path/"clean/factor_benchmarks/fixture/summary.json").read_text())
    assert stored == summary
    with pytest.raises(FileExistsError):
        factor_benchmarks.capture_csi800(data_root=tmp_path, name="fixture",
            start=dt.date(2020,1,1), end=dt.date(2020,2,29))
