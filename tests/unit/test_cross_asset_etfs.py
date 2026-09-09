import datetime as dt
import json

import polars as pl
import pytest

import quant.data.publish_cross_asset_etfs as module
from quant.research.monthly_etf import read_inputs


def test_publication_refuses_missing_trading_day_before_writing_clean(tmp_path, monkeypatch):
    days = [dt.date(2026, 1, 5), dt.date(2026, 1, 6)]
    calendar = pl.DataFrame({"market": ["SH", "SH"], "is_open": [True, True], "date": days})
    monkeypatch.setattr(module, "read_etf_research_inputs", lambda *args: (
        pl.DataFrame(), pl.DataFrame(), calendar, pl.DataFrame()))
    daily = pl.DataFrame({"ts_code": ["511010.SH"], "trade_date": ["20260105"],
        "open": [100.], "high": [101.], "low": [99.], "close": [100.],
        "vol": [100.], "amount": [1000.]})
    entries = []
    for name, frame in (("fund_daily", daily), ("fund_div", pl.DataFrame()),
                        ("fund_basic", pl.DataFrame({"ts_code": ["511010.SH"]}))):
        path = tmp_path / f"{name}.parquet"
        frame.write_parquet(path)
        entries.append({"symbol": "511010.SH", "dataset": name, "raw_path": str(path)})
    capture = tmp_path / "capture.json"
    capture.write_text(json.dumps(entries), encoding="utf-8")
    with pytest.raises(ValueError, match="Incomplete cross-asset bars"):
        module.publish(data_root=tmp_path, capture=capture, name="sample", start=days[0], end=days[-1])
    assert not (tmp_path / "clean/etf_cross_asset/sample").exists()


def test_research_rejects_truncated_snapshot_instead_of_shortening_test(tmp_path):
    root = tmp_path / "clean/etf_cross_asset/sample"
    root.mkdir(parents=True)
    (root / "summary.json").write_text("{}", encoding="utf-8")
    days = [dt.date(2026, 1, 5), dt.date(2026, 1, 6)]
    for label, frame in {
        "bars": pl.DataFrame({"symbol": ["511010.SH"], "trade_date": days[:1]}),
        "prices": pl.DataFrame({"symbol": ["511010.SH"], "trade_date": days[:1]}),
        "calendar": pl.DataFrame({"market": ["SH"] * 2, "is_open": [True] * 2, "date": days}),
        "instruments": pl.DataFrame({"symbol": ["511010.SH"]}),
        "dividends": pl.DataFrame(schema={"symbol": pl.String, "ex_date": pl.Date}),
    }.items():
        frame.write_parquet(root / f"{label}.parquet")
    with pytest.raises(ValueError, match="Incomplete cross-asset bars"):
        read_inputs(tmp_path, ("511010.SH",), {"cross_asset_snapshot": "sample", "start": days[0], "end": days[-1]})
