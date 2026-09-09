import datetime as dt
import json
import sqlite3
from pathlib import Path

import polars as pl
import pytest

from quant.data.financial_clean import normalize_financial_publication
from quant.data.financial_pit import select_financial_revisions_as_of
from quant.data.financial_repository import TushareFinancialHistoryQuery, read_tushare_financial_history
from quant.data.publish_tushare_financials import DATASETS, load_financial_publication, publish_financials


def statement():
    return {"ts_code": "000001.SZ", "ann_date": "20240420", "f_ann_date": "20240422",
            "end_date": "20231231", "report_type": "1", "comp_type": "1", "update_flag": "0",
            "n_income": "100", "n_income_attr_p": "90", "total_assets": "1000",
            "total_hldr_eqy_exc_min_int": "800", "n_cashflow_act": "120", "revenue": "500"}


def test_publication_keeps_economics_and_lags_revision_date():
    row = statement()
    good, bad, _ = normalize_financial_publication(pl.DataFrame([row]), dataset="income")
    assert good["revenue"][0] == 500.0
    assert good["available_date"][0] == dt.date(2024, 4, 22)
    assert bad.is_empty()
    diversified, _, _ = normalize_financial_publication(
        pl.DataFrame([{**row, "comp_type": "7"}]), dataset="income")
    assert diversified.height == 1
    before = select_financial_revisions_as_of(good, dataset="income", as_of=dt.date(2024, 4, 22))
    after = select_financial_revisions_as_of(good, dataset="income", as_of=dt.date(2024, 4, 23))
    assert before.selected.is_empty()
    assert after.selected.height == 1
    invalid = pl.DataFrame([{**row, "end_date": "20250420"}, {**row, "n_income": "bad"}])
    good, bad, _ = normalize_financial_publication(invalid, dataset="income")
    assert good.is_empty()
    assert set(bad["quarantine_reason"]) == {"END_AFTER_AVAILABLE", "REQUIRED_NUMERIC_INVALID"}


def test_four_tables_reconcile_and_read(tmp_path: Path):
    database = tmp_path / "run_state/tushare_bulk/state.sqlite"
    database.parent.mkdir(parents=True)
    with sqlite3.connect(database) as conn:
        conn.execute("create table requests(dataset text, request_id text, status text, rows integer)")
        for table in DATASETS:
            source = tmp_path / "raw/tushare" / table / "request=one/data.parquet"
            source.parent.mkdir(parents=True)
            row = statement()
            if table == "fina_indicator":
                row = {k: v for k, v in row.items() if k not in ("f_ann_date", "report_type", "comp_type", "update_flag")}
                row["roe"] = "10.0"
                data = [row, row, {**row, "end_date": "20250420"}]
            else:
                data = [row, row]
            pl.DataFrame(data).write_parquet(source)
            conn.execute("insert into requests values (?, 'one', 'COMPLETE', ?)", (table, len(data)))
            conn.execute("insert into requests values (?, 'empty', 'COMPLETE', 0)", (table,))
    result = publish_financials(data_root=tmp_path, name="fixture", workers=1)
    assert result["datasets"]["fina_indicator"]["quarantined_rows"] == 1
    for table in DATASETS:
        stats = result["datasets"][table]
        assert stats["raw_rows"] == stats["clean_rows"] + stats["exact_duplicate_rows"] + stats["quarantined_rows"]
    publication = load_financial_publication(data_root=tmp_path, snapshot_id="fixture")
    assert dict(publication.dataset_rows)["income"] == 1
    assert len(publication.content_sha256) == 64
    query = TushareFinancialHistoryQuery("fixture", "income", dt.date(2023, 1, 1),
                                        dt.date(2024, 12, 31), ("000001.SZ",))
    history = read_tushare_financial_history(data_root=tmp_path, query=query)
    assert history["n_income"][0] == 100.0
    assert json.loads((publication.root / "summary.json").read_text())["name"] == "fixture"
    with pytest.raises(FileExistsError):
        publish_financials(data_root=tmp_path, name="fixture", workers=1)
