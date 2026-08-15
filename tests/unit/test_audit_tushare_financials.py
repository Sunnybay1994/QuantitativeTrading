from __future__ import annotations

import datetime as dt
import hashlib
import json
import sqlite3
from pathlib import Path

import polars as pl
import pytest

from quant.data.audit_tushare_financials import audit_tushare_financials
from quant.data.financial_pit import select_financial_revisions_as_of
from quant.data.financial_repository import (
    TushareFinancialHistoryQuery,
    TushareFinancialReadError,
    read_tushare_financial_history,
)
from quant.data.publish_tushare_financials import (
    TushareFinancialPublishError,
    publish_tushare_financial_snapshot,
    verify_tushare_financial_snapshot,
)
from quant.data.storage import RawStore

_DATASETS = ("balancesheet", "cashflow", "fina_indicator", "income")


def _frame(dataset: str, **overrides: object) -> pl.DataFrame:
    common: dict[str, object] = {
        "ts_code": "000001.SZ",
        "ann_date": "20240420",
        "end_date": "20231231",
    }
    if dataset != "fina_indicator":
        common |= {
            "f_ann_date": "20240422",
            "report_type": "1",
            "comp_type": "1",
            "update_flag": "0",
        }
    values = {
        "balancesheet": {
            "total_assets": 120.0,
            "total_hldr_eqy_exc_min_int": 60.0,
        },
        "cashflow": {"n_cashflow_act": 68.0},
        "fina_indicator": {"roe": 12.0},
        "income": {"n_income": 70.0, "n_income_attr_p": 56.0},
    }[dataset]
    common.update(values)
    common.update(overrides)
    return pl.DataFrame([common])


def _build_root(
    tmp_path: Path,
    *,
    extra_pending: bool = False,
    income_frame: pl.DataFrame | None = None,
) -> Path:
    root = tmp_path / "data"
    root.mkdir()
    ledger = root / "run_state" / "tushare_bulk" / "state.sqlite"
    ledger.parent.mkdir(parents=True)
    raw = RawStore(root / "raw")
    records: list[tuple[object, ...]] = []
    for index, dataset in enumerate(_DATASETS, start=1):
        request_id = f"{index:064x}"
        parameters = {
            "ts_code": "000001.SZ",
            "start_date": "20230101" if dataset == "fina_indicator" else "20240101",
            "end_date": "20231231" if dataset == "fina_indicator" else "20241231",
        }
        frame = (
            income_frame if dataset == "income" and income_frame is not None else _frame(dataset)
        )
        snapshot = raw.write_request(
            source="tushare",
            table=dataset,
            request_id=request_id,
            frame=frame,
            parameters=parameters,
        )
        records.append(
            (
                request_id,
                "a" * 64,
                dataset,
                dataset,
                json.dumps(parameters, separators=(",", ":"), sort_keys=True),
                100 if dataset == "fina_indicator" else 6000,
                "COMPLETE",
                1,
                snapshot.row_count,
                snapshot.checksum_sha256,
                None,
                "2026-08-15T00:00:00+00:00",
            )
        )
    if extra_pending:
        records.append(
            (
                "f" * 64,
                "a" * 64,
                "income",
                "income",
                json.dumps(
                    {
                        "ts_code": "000002.SZ",
                        "start_date": "20240101",
                        "end_date": "20241231",
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                6000,
                "PENDING",
                0,
                None,
                None,
                None,
                "2026-08-15T00:00:00+00:00",
            )
        )
    with sqlite3.connect(ledger) as connection:
        connection.execute(
            "CREATE TABLE requests(request_id TEXT PRIMARY KEY,catalog_sha256 TEXT,"
            "dataset TEXT,api_name TEXT,parameters_json TEXT,max_rows INTEGER,"
            "status TEXT,attempts INTEGER,rows INTEGER,checksum_sha256 TEXT,"
            "error_code TEXT,updated_at TEXT)"
        )
        connection.executemany("INSERT INTO requests VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", records)
    return root


def test_complete_four_table_fixture_is_ready_and_byte_bound(tmp_path: Path) -> None:
    result = audit_tushare_financials(data_root=_build_root(tmp_path), verify_bytes=True)
    assert result["status"] == "READY"
    assert result["publication_allowed"] is True
    assert result["raw_closure"]["complete_request_count"] == 4
    assert result["raw_closure"]["catalog_sha256s"] == ["a" * 64]
    for dataset in _DATASETS:
        report = result["datasets"][dataset]
        assert report["status_counts"] == {"COMPLETE": 1}
        assert report["quality"]["raw_rows"] == 1
        assert report["quality"]["eligible_rows"] == 1
        assert report["quality"]["quarantined_rows"] == 0


def test_pending_request_keeps_batch_collecting_and_forbids_publication(
    tmp_path: Path,
) -> None:
    result = audit_tushare_financials(data_root=_build_root(tmp_path, extra_pending=True))
    assert result["status"] == "COLLECTING"
    assert result["publication_allowed"] is False
    assert result["datasets"]["income"]["status_counts"] == {
        "COMPLETE": 1,
        "PENDING": 1,
    }


def test_parameter_window_mismatch_blocks_instead_of_silently_quarantining(
    tmp_path: Path,
) -> None:
    root = _build_root(
        tmp_path,
        income_frame=_frame("income", ann_date="20250101", f_ann_date="20250102"),
    )
    result = audit_tushare_financials(data_root=root)
    assert result["status"] == "BLOCKED"
    assert result["datasets"]["income"]["quality"]["request_window_mismatches"] == 1
    assert {item["code"] for item in result["blocking_issues"]} >= {
        "INCOME_REQUEST_WINDOW_MISMATCH"
    }


def test_per_request_physical_row_drift_is_detected(tmp_path: Path) -> None:
    root = _build_root(tmp_path)
    request_root = root / "raw" / "tushare" / "income" / f"request={4:064x}"
    parquet = request_root / "data.parquet"
    frame = pl.read_parquet(parquet)
    pl.concat([frame, frame]).write_parquet(parquet)
    payload = parquet.read_bytes()
    checksum = hashlib.sha256(payload).hexdigest()
    metadata_path = request_root / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["checksum_sha256"] = checksum
    metadata["size_bytes"] = len(payload)
    metadata_path.write_text(
        json.dumps(metadata, separators=(",", ":"), sort_keys=True),
        encoding="utf-8",
    )
    with sqlite3.connect(root / "run_state" / "tushare_bulk" / "state.sqlite") as connection:
        connection.execute(
            "UPDATE requests SET checksum_sha256=? WHERE dataset='income'",
            (checksum,),
        )
    result = audit_tushare_financials(data_root=root)
    assert result["status"] == "BLOCKED"
    assert result["datasets"]["income"]["quality"]["row_count_mismatch"] == 1


def test_latest_revision_collision_is_reported_for_clean_quarantine(
    tmp_path: Path,
) -> None:
    income = pl.concat([_frame("income", n_income=70.0), _frame("income", n_income=71.0)])
    result = audit_tushare_financials(
        data_root=_build_root(tmp_path, income_frame=income), verify_bytes=True
    )
    assert result["status"] == "READY"
    quality = result["datasets"]["income"]["quality"]
    assert quality["same_available_duplicate_groups"] == 1
    assert quality["required_economic_conflict_groups"] == 1


def test_ready_batch_publishes_and_strictly_reuses_typed_snapshot(
    tmp_path: Path,
) -> None:
    root = _build_root(tmp_path)
    first = publish_tushare_financial_snapshot(data_root=root)
    assert first.dataset_rows == tuple((dataset, 1) for dataset in _DATASETS)
    assert first.reused is False
    assert (
        verify_tushare_financial_snapshot(
            data_root=root, snapshot_id=first.snapshot_id
        ).dataset_rows
        == first.dataset_rows
    )

    second = publish_tushare_financial_snapshot(data_root=root)
    assert second.snapshot_id == first.snapshot_id
    assert second.reused is True
    income = pl.read_parquet(second.root / "dataset=income" / "year=2023.parquet")
    assert income.schema == {
        "symbol": pl.String,
        "ann_date": pl.Date,
        "f_ann_date": pl.Date,
        "available_date": pl.Date,
        "end_date": pl.Date,
        "report_type": pl.String,
        "comp_type": pl.String,
        "update_flag": pl.String,
        "n_income": pl.Float64,
        "n_income_attr_p": pl.Float64,
        "source": pl.String,
    }


def test_collecting_batch_cannot_create_partial_clean_snapshot(
    tmp_path: Path,
) -> None:
    root = _build_root(tmp_path, extra_pending=True)
    with pytest.raises(
        TushareFinancialPublishError,
        match="TUSHARE_FINANCIAL_PUBLISH_INVALID",
    ):
        publish_tushare_financial_snapshot(data_root=root)
    assert not (root / "clean").exists()


def test_existing_snapshot_content_drift_is_rejected_not_overwritten(
    tmp_path: Path,
) -> None:
    root = _build_root(tmp_path)
    snapshot = publish_tushare_financial_snapshot(data_root=root)
    path = snapshot.root / "dataset=income" / "year=2023.parquet"
    frame = pl.read_parquet(path).with_columns(pl.lit(999.0).alias("n_income"))
    frame.write_parquet(path)

    with pytest.raises(TushareFinancialPublishError):
        verify_tushare_financial_snapshot(data_root=root, snapshot_id=snapshot.snapshot_id)
    with pytest.raises(TushareFinancialPublishError):
        publish_tushare_financial_snapshot(data_root=root)


def test_bounded_history_read_feeds_typed_pit_revision_selection(
    tmp_path: Path,
) -> None:
    income = pl.concat(
        [
            _frame("income"),
            _frame(
                "income",
                ann_date="20240510",
                f_ann_date="20240510",
                update_flag="1",
                n_income=77.0,
                n_income_attr_p=63.0,
            ),
        ]
    )
    root = _build_root(tmp_path, income_frame=income)
    snapshot = publish_tushare_financial_snapshot(data_root=root)
    query = TushareFinancialHistoryQuery(
        snapshot_id=snapshot.snapshot_id,
        dataset="income",
        start_period=dt.date(2023, 1, 1),
        end_period=dt.date(2023, 12, 31),
        symbols=("000001.SZ",),
    )
    history = read_tushare_financial_history(data_root=root, query=query)
    assert history.height == 2
    assert history.schema["end_date"] == pl.Date
    before = select_financial_revisions_as_of(history, dataset="income", as_of=dt.date(2024, 5, 10))
    after = select_financial_revisions_as_of(history, dataset="income", as_of=dt.date(2024, 5, 11))
    assert before.selected.get_column("n_income").item() == 70.0
    assert after.selected.get_column("n_income").item() == 77.0


def test_bounded_history_read_allows_empty_period_and_rejects_bad_query(
    tmp_path: Path,
) -> None:
    root = _build_root(tmp_path)
    snapshot = publish_tushare_financial_snapshot(data_root=root)
    empty = read_tushare_financial_history(
        data_root=root,
        query=TushareFinancialHistoryQuery(
            snapshot_id=snapshot.snapshot_id,
            dataset="income",
            start_period=dt.date(2022, 1, 1),
            end_period=dt.date(2022, 12, 31),
            symbols=("000001.SZ",),
        ),
    )
    assert empty.is_empty()
    assert empty.schema["end_date"] == pl.Date
    with pytest.raises(TushareFinancialReadError, match="TUSHARE_FINANCIAL_READ_INVALID") as exc:
        TushareFinancialHistoryQuery(
            snapshot_id=snapshot.snapshot_id,
            dataset="income",
            start_period=dt.date(2023, 1, 1),
            end_period=dt.date(2023, 12, 31),
            symbols=("BAD",),
        )
    assert exc.value.__cause__ is None
    assert exc.value.__context__ is None
