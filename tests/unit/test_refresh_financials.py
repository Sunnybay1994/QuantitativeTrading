import datetime as dt
import json
from pathlib import Path

import polars as pl
import pytest

from quant.data.financial_clean import normalize_financial_publication
from quant.data.refresh_financials import TABLES, refresh_quarter


def _raw(table: str, revised: bool = False) -> pl.DataFrame:
    row = {"ts_code": "000333.SZ", "ann_date": "20260829" if revised else "20260820",
           "end_date": "20260630"}
    if table != "fina_indicator":
        row.update(f_ann_date=row["ann_date"], report_type="1", comp_type="1", update_flag="0")
    fields = {"income": ["n_income", "n_income_attr_p"],
              "balancesheet": ["total_assets", "total_hldr_eqy_exc_min_int"],
              "cashflow": ["n_cashflow_act"], "fina_indicator": ["roe"]}[table]
    row.update({key: "120" if revised else "100" for key in fields})
    return pl.DataFrame([row])


def _base(root: Path):
    base = root / "clean/tushare_financials/base"
    base.mkdir(parents=True)
    summary = {"datasets": {}}
    for table in (*TABLES, "fina_indicator"):
        clean, rejected, _ = normalize_financial_publication(
            _raw(table).with_columns(pl.lit("original_raw").alias("source_file")), dataset=table)
        clean.write_parquet(base / f"{table}.parquet")
        rejected.write_parquet(base / f"{table}_quarantine.parquet")
        summary["datasets"][table] = {"raw_rows": 1, "clean_rows": 1, "exact_duplicate_rows": 0}
    (base / "summary.json").write_text(json.dumps(summary), encoding="utf-8")


def test_financial_refresh_resumes_without_overwriting_raw_and_keeps_revisions(tmp_path, monkeypatch):
    _base(tmp_path)
    monkeypatch.setattr("quant.data.refresh_financials.time.sleep", lambda _: None)

    class Client:
        def __init__(self, fail=False):
            self.fail = fail
            self.calls = []

        def query_raw(self, table, **params):
            self.calls.append((table, params))
            if self.fail and table == "balancesheet":
                raise RuntimeError("sensitive upstream error")
            return pl.concat([_raw(table), _raw(table, True)])

    arguments = dict(data_root=tmp_path, base_name="base", name="new", symbols=["000333.SZ"],
                     period=dt.date(2026, 6, 30), pause_seconds=0)
    with pytest.raises(RuntimeError, match="Financial request failed") as exc:
        refresh_quarter(**arguments, client=Client(fail=True))
    assert "sensitive" not in str(exc.value)
    output = tmp_path / "clean/tushare_financials/new"
    first = pl.read_parquet(output / "captured.parquet")
    assert first.height == 1
    raw_path = Path(first["raw_path"].item())
    raw_before = raw_path.read_bytes()
    client = Client()
    summary = refresh_quarter(**arguments, client=client)
    assert [call[0] for call in client.calls] == ["balancesheet", "cashflow"]
    assert raw_path.read_bytes() == raw_before
    for table in TABLES:
        assert summary["datasets"][table]["clean_rows"] == 2
        assert summary["datasets"][table]["raw_rows"] == 3
        assert summary["datasets"][table]["exact_duplicate_rows"] == 1
        assert pl.read_parquet(output / f"{table}.parquet")["available_date"].to_list() == [
            dt.date(2026, 8, 20), dt.date(2026, 8, 29)]
        assert pl.read_parquet(tmp_path / f"clean/tushare_financials/base/{table}.parquet").height == 1
    assert summary["datasets"]["fina_indicator"]["added_raw_rows"] == 0
    with pytest.raises(FileExistsError):
        refresh_quarter(**arguments, client=client)


def test_financial_refresh_rejects_wrong_response_scope(tmp_path):
    _base(tmp_path)

    class WrongClient:
        def query_raw(self, table, **params):
            return _raw(table).with_columns(pl.lit("600519.SH").alias("ts_code"))

    with pytest.raises(ValueError, match="scope differs"):
        refresh_quarter(data_root=tmp_path, base_name="base", name="wrong", symbols=["000333.SZ"],
                        period=dt.date(2026, 6, 30), client=WrongClient(), pause_seconds=0)
    assert not (tmp_path / "clean/tushare_financials/wrong/summary.json").exists()
