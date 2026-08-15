from __future__ import annotations

import datetime as dt
import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import polars as pl
import pytest

import quant.data.publish_tushare_financials as financial_publication
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
from quant.data.tushare_bulk import (
    REPORT_SCHEMA,
    build_request_plan,
    load_catalog,
    write_run_document,
)
from quant.data.tushare_bulk_ingest import prepare_requests

_DATASETS = ("balancesheet", "cashflow", "fina_indicator", "income")


@dataclass(frozen=True, slots=True)
class _FinancialFixture:
    root: Path
    plan_report: Path
    catalog: Path


def _audit_kwargs(fixture: _FinancialFixture) -> dict[str, Path]:
    return {
        "data_root": fixture.root,
        "plan_report_path": fixture.plan_report,
        "catalog_path": fixture.catalog,
    }


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
) -> _FinancialFixture:
    root = tmp_path / "data"
    root.mkdir(parents=True)
    instrument = root / "clean" / "instrument" / "market=SZ" / "data.parquet"
    instrument.parent.mkdir(parents=True)
    pl.DataFrame(
        {
            "symbol": ["000001.SZ"],
            "market": ["SZ"],
            "instrument_type": ["STOCK"],
        }
    ).write_parquet(instrument)
    catalog_path = tmp_path / "catalog.toml"
    dataset_rows = []
    for dataset in _DATASETS:
        history_start = "2023-01-01" if dataset == "fina_indicator" else "2024-01-01"
        max_rows = 100 if dataset == "fina_indicator" else 6000
        dataset_rows.append(
            "[[datasets]]\n"
            f'name = "{dataset}"\n'
            f'api_name = "{dataset}"\n'
            'category = "finance"\n'
            'priority = "core"\n'
            'probe_mode = "query"\n'
            'probe_params = { ts_code = "000001.SZ", period = "20231231" }\n'
            'request_unit = "per_symbol"\n'
            'inventory = "stock"\n'
            f"history_start = {history_start}\n"
            f"max_rows = {max_rows}\n"
            "chunk_days = 1825\n"
            'partition = "report_year"\n'
            "overlap_days = 500\n"
        )
    catalog_path.write_text(
        "[meta]\n"
        'schema_version = "tushare-bulk-catalog-v1"\n'
        'catalog_version = "fixture-v1"\n'
        'source_url = "https://example.invalid/tushare"\n'
        "captured_on = 2026-08-15\n\n"
        + "\n".join(dataset_rows),
        encoding="utf-8",
        newline="\n",
    )
    catalog = load_catalog(catalog_path)
    permission_report: dict[str, object] = {
        "schema_version": REPORT_SCHEMA,
        "catalog_version": catalog.version,
        "catalog_sha256": catalog.sha256,
        "probed_at": "2026-08-15T00:00:00+00:00",
        "requests_per_minute": 120,
        "query_count": 4,
        "results": [
            {
                "dataset": spec.name,
                "api_name": spec.api_name,
                "category": spec.category,
                "priority": spec.priority,
                "status": "ACCESSIBLE",
                "rows": 1,
            }
            for spec in catalog.datasets
        ],
    }
    write_run_document(data_root=root, kind="permission", value=permission_report)
    plan = build_request_plan(
        catalog=catalog,
        permission_report=permission_report,
        data_root=root,
        as_of=dt.date(2024, 12, 31),
        now=dt.datetime(2026, 8, 15, tzinfo=dt.timezone.utc),
    )
    plan_report = write_run_document(data_root=root, kind="plan", value=plan)
    ledger = root / "run_state" / "tushare_bulk" / "state.sqlite"
    prepare_requests(
        catalog=catalog,
        permission_report=permission_report,
        data_root=root,
        ledger_path=ledger,
        datasets=frozenset(_DATASETS),
        start=dt.date(2023, 1, 1),
        end=dt.date(2024, 12, 31),
    )
    raw = RawStore(root / "raw")
    with sqlite3.connect(ledger) as connection:
        requests = connection.execute(
            "SELECT request_id,dataset,parameters_json FROM requests ORDER BY dataset,request_id"
        ).fetchall()
    for request_id, dataset, parameters_json in requests:
        parameters = json.loads(parameters_json)
        is_pending = extra_pending and dataset == "income"
        if is_pending:
            continue
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
        with sqlite3.connect(ledger) as connection:
            connection.execute(
                "UPDATE requests SET status='COMPLETE',attempts=1,rows=?,"
                "checksum_sha256=?,error_code=NULL WHERE request_id=?",
                (snapshot.row_count, snapshot.checksum_sha256, request_id),
            )
    return _FinancialFixture(root=root, plan_report=plan_report, catalog=catalog_path)


def _request_id(root: Path, dataset: str) -> str:
    with sqlite3.connect(root / "run_state" / "tushare_bulk" / "state.sqlite") as connection:
        row = connection.execute(
            "SELECT request_id FROM requests WHERE dataset=?", (dataset,)
        ).fetchone()
    assert row is not None
    return str(row[0])


def test_complete_four_table_fixture_is_ready_and_byte_bound(tmp_path: Path) -> None:
    fixture = _build_root(tmp_path)
    result = audit_tushare_financials(**_audit_kwargs(fixture), verify_bytes=True)
    assert result["schema_version"] == "tushare-financial-raw-audit-v3"
    assert result["status"] == "READY"
    assert result["publication_allowed"] is True
    assert result["raw_closure"]["complete_request_count"] == 4
    assert result["raw_closure"]["catalog_sha256s"] == [
        result["plan_closure"]["catalog_sha256"]
    ]
    assert result["plan_closure"]["provenance_model"] == (
        "RECONSTRUCTED_CURRENT_INVENTORY_V1"
    )
    assert result["plan_closure"]["instrument_inventory"]["stock_count"] == 1
    for dataset in _DATASETS:
        report = result["datasets"][dataset]
        assert report["status_counts"] == {"COMPLETE": 1}
        assert report["quality"]["raw_rows"] == 1
        assert report["quality"]["eligible_rows"] == 1
        assert report["quality"]["quarantined_rows"] == 0
        if dataset == "fina_indicator":
            assert report["quality"]["report_type_counts"] == []
            assert report["quality"]["comp_type_counts"] == []
            assert report["quality"]["report_type_comp_type_counts"] == []
        else:
            assert report["quality"]["report_type_counts"] == [
                {"value": "1", "rows": 1}
            ]
            assert report["quality"]["comp_type_counts"] == [
                {"value": "1", "rows": 1}
            ]
            assert report["quality"]["report_type_comp_type_counts"] == [
                {"report_type": "1", "comp_type": "1", "rows": 1}
            ]


def test_statement_dimension_counts_are_canonical_and_cross_reconciled(
    tmp_path: Path,
) -> None:
    income = pl.concat(
        [
            _frame("income", report_type="1", comp_type="1"),
            _frame("income", report_type="1", comp_type="1"),
            _frame("income", report_type="1", comp_type="2"),
            _frame("income", report_type="2", comp_type="1"),
        ]
    )
    fixture = _build_root(tmp_path, income_frame=income)
    quality = audit_tushare_financials(**_audit_kwargs(fixture), verify_bytes=True)[
        "datasets"
    ]["income"]["quality"]
    assert quality["invalid_report_type_rows"] == 0
    assert quality["invalid_comp_type_rows"] == 0
    assert quality["report_type_counts"] == [
        {"value": "1", "rows": 3},
        {"value": "2", "rows": 1},
    ]
    assert quality["comp_type_counts"] == [
        {"value": "1", "rows": 3},
        {"value": "2", "rows": 1},
    ]
    assert quality["report_type_comp_type_counts"] == [
        {"report_type": "1", "comp_type": "1", "rows": 2},
        {"report_type": "1", "comp_type": "2", "rows": 1},
        {"report_type": "2", "comp_type": "1", "rows": 1},
    ]


def test_blank_or_nondigit_statement_dimensions_block_ready(tmp_path: Path) -> None:
    income = pl.concat(
        [
            _frame("income", report_type="", comp_type="1"),
            _frame("income", report_type="2", comp_type="A"),
            _frame("income", report_type="3", comp_type="3").with_columns(
                pl.lit(None, dtype=pl.String).alias("report_type")
            ),
            _frame("income", report_type="١", comp_type="4"),
        ]
    )
    fixture = _build_root(tmp_path, income_frame=income)
    result = audit_tushare_financials(**_audit_kwargs(fixture), verify_bytes=True)
    quality = result["datasets"]["income"]["quality"]
    assert result["status"] == "BLOCKED"
    assert result["publication_allowed"] is False
    assert quality["invalid_report_type_rows"] == 3
    assert quality["invalid_comp_type_rows"] == 1
    assert {item["code"] for item in result["blocking_issues"]} >= {
        "INCOME_REPORT_TYPE_INVALID",
        "INCOME_COMP_TYPE_INVALID",
    }


def test_publisher_rejects_dimension_drift_before_snapshot_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    income = pl.concat(
        [
            _frame("income", report_type="1", comp_type="1"),
            _frame("income", report_type="1", comp_type="2"),
            _frame("income", report_type="2", comp_type="1"),
        ]
    )
    fixture = _build_root(tmp_path, income_frame=income)
    original = audit_tushare_financials(**_audit_kwargs(fixture), verify_bytes=True)
    drifts = []

    marginal = json.loads(json.dumps(original))
    marginal["datasets"]["income"]["quality"]["report_type_counts"][0]["rows"] += 1
    drifts.append(marginal)

    reordered = json.loads(json.dumps(original))
    pairs = reordered["datasets"]["income"]["quality"][
        "report_type_comp_type_counts"
    ]
    reordered["datasets"]["income"]["quality"][
        "report_type_comp_type_counts"
    ] = list(reversed(pairs))
    drifts.append(reordered)

    missing_pair = json.loads(json.dumps(original))
    missing_pair["datasets"]["income"]["quality"][
        "report_type_comp_type_counts"
    ].pop()
    drifts.append(missing_pair)

    zero_count = json.loads(json.dumps(original))
    zero_count["datasets"]["income"]["quality"][
        "report_type_comp_type_counts"
    ][0]["rows"] = 0
    drifts.append(zero_count)

    unicode_digit = json.loads(json.dumps(original))
    unicode_digit["datasets"]["income"]["quality"]["report_type_counts"][0][
        "value"
    ] = "١"
    unicode_digit["datasets"]["income"]["quality"][
        "report_type_comp_type_counts"
    ][0]["report_type"] = "١"
    drifts.append(unicode_digit)

    fabricated = json.loads(json.dumps(original))
    fabricated["datasets"]["fina_indicator"]["quality"]["report_type_counts"] = [
        {"value": "1", "rows": 1}
    ]
    drifts.append(fabricated)

    for drift in drifts:
        monkeypatch.setattr(
            financial_publication,
            "audit_tushare_financials",
            lambda _audit=drift, **_kwargs: _audit,
        )
        with pytest.raises(
            TushareFinancialPublishError,
            match="TUSHARE_FINANCIAL_PUBLISH_INVALID",
        ):
            financial_publication.publish_tushare_financial_snapshot(
                **_audit_kwargs(fixture)
            )
        assert not (fixture.root / "clean" / "tushare_financials").exists()


def test_pending_request_keeps_batch_collecting_and_forbids_publication(
    tmp_path: Path,
) -> None:
    fixture = _build_root(tmp_path, extra_pending=True)
    result = audit_tushare_financials(**_audit_kwargs(fixture))
    assert result["status"] == "COLLECTING"
    assert result["publication_allowed"] is False
    assert result["datasets"]["income"]["status_counts"] == {"PENDING": 1}


def test_plan_request_set_missing_or_reidentified_fails_closed(tmp_path: Path) -> None:
    fixture = _build_root(tmp_path)
    ledger = fixture.root / "run_state" / "tushare_bulk" / "state.sqlite"
    with sqlite3.connect(ledger) as connection:
        connection.execute("DELETE FROM requests WHERE dataset='income'")
    with pytest.raises(ValueError, match="TUSHARE_FINANCIAL_AUDIT_INVALID"):
        audit_tushare_financials(**_audit_kwargs(fixture))

    second = _build_root(tmp_path / "second")
    with sqlite3.connect(
        second.root / "run_state" / "tushare_bulk" / "state.sqlite"
    ) as connection:
        connection.execute(
            "UPDATE requests SET request_id=? WHERE dataset='income'", ("f" * 64,)
        )
    with pytest.raises(ValueError, match="TUSHARE_FINANCIAL_AUDIT_INVALID"):
        audit_tushare_financials(**_audit_kwargs(second))


def test_active_writer_lease_forbids_ready_without_corrupting_plan(tmp_path: Path) -> None:
    fixture = _build_root(tmp_path)
    with sqlite3.connect(
        fixture.root / "run_state" / "tushare_bulk" / "state.sqlite"
    ) as connection:
        connection.execute(
            "INSERT INTO lease(owner,expires_at) VALUES(?,?)", ("writer", 4_102_444_800.0)
        )
    result = audit_tushare_financials(**_audit_kwargs(fixture), verify_bytes=True)
    assert result["status"] == "COLLECTING"
    assert result["active_lease_count"] == 1
    assert result["publication_allowed"] is False


def test_plan_or_current_inventory_drift_is_not_treated_as_ready(tmp_path: Path) -> None:
    fixture = _build_root(tmp_path)
    plan = json.loads(fixture.plan_report.read_text(encoding="utf-8"))
    plan["inventory"]["stock"] = 2
    fixture.plan_report.write_text(
        json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    with pytest.raises(ValueError, match="TUSHARE_FINANCIAL_AUDIT_INVALID"):
        audit_tushare_financials(**_audit_kwargs(fixture))

    second = _build_root(tmp_path / "second")
    instrument = second.root / "clean" / "instrument" / "market=SZ" / "data.parquet"
    pl.concat(
        [
            pl.read_parquet(instrument),
            pl.DataFrame(
                {
                    "symbol": ["000002.SZ"],
                    "market": ["SZ"],
                    "instrument_type": ["STOCK"],
                }
            ),
        ]
    ).write_parquet(instrument)
    with pytest.raises(ValueError, match="TUSHARE_FINANCIAL_AUDIT_INVALID"):
        audit_tushare_financials(**_audit_kwargs(second))


def test_parameter_window_mismatch_blocks_instead_of_silently_quarantining(
    tmp_path: Path,
) -> None:
    fixture = _build_root(
        tmp_path,
        income_frame=_frame("income", ann_date="20250101", f_ann_date="20250102"),
    )
    result = audit_tushare_financials(**_audit_kwargs(fixture))
    assert result["status"] == "BLOCKED"
    assert result["datasets"]["income"]["quality"]["request_window_mismatches"] == 1
    assert {item["code"] for item in result["blocking_issues"]} >= {
        "INCOME_REQUEST_WINDOW_MISMATCH"
    }


def test_per_request_physical_row_drift_is_detected(tmp_path: Path) -> None:
    fixture = _build_root(tmp_path)
    root = fixture.root
    request_root = root / "raw" / "tushare" / "income" / f"request={_request_id(root, 'income')}"
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
    result = audit_tushare_financials(**_audit_kwargs(fixture))
    assert result["status"] == "BLOCKED"
    assert result["datasets"]["income"]["quality"]["row_count_mismatch"] == 1


def test_latest_revision_collision_is_reported_for_clean_quarantine(
    tmp_path: Path,
) -> None:
    income = pl.concat([_frame("income", n_income=70.0), _frame("income", n_income=71.0)])
    fixture = _build_root(tmp_path, income_frame=income)
    result = audit_tushare_financials(**_audit_kwargs(fixture), verify_bytes=True)
    assert result["status"] == "READY"
    quality = result["datasets"]["income"]["quality"]
    assert quality["same_available_duplicate_groups"] == 1
    assert quality["required_economic_conflict_groups"] == 1


def test_ready_batch_publishes_and_strictly_reuses_typed_snapshot(
    tmp_path: Path,
) -> None:
    fixture = _build_root(tmp_path)
    root = fixture.root
    first = publish_tushare_financial_snapshot(**_audit_kwargs(fixture))
    assert first.dataset_rows == tuple((dataset, 1) for dataset in _DATASETS)
    assert first.reused is False
    manifest = json.loads((first.root / "manifest.json").read_text(encoding="utf-8"))
    audit = json.loads((first.root / "audit.json").read_text(encoding="utf-8"))
    assert manifest["plan_report_sha256"] == audit["plan_closure"]["plan_report_sha256"]
    assert manifest["provenance_model"] == "RECONSTRUCTED_CURRENT_INVENTORY_V1"
    assert manifest["provenance_limitation"] == audit["plan_closure"][
        "provenance_limitation"
    ]
    assert manifest["instrument_file_set_sha256"] == audit["plan_closure"][
        "instrument_inventory"
    ]["file_set_sha256"]
    assert manifest["request_set_sha256"] == audit["plan_closure"]["request_set_sha256"]
    assert manifest["request_counts"] == audit["plan_closure"]["request_counts"]
    assert manifest["instrument_logical_frame_sha256"] == audit["plan_closure"][
        "instrument_inventory"
    ]["logical_frame_sha256"]
    assert (
        verify_tushare_financial_snapshot(
            data_root=root, snapshot_id=first.snapshot_id
        ).dataset_rows
        == first.dataset_rows
    )

    second = publish_tushare_financial_snapshot(**_audit_kwargs(fixture))
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
    fixture = _build_root(tmp_path, extra_pending=True)
    root = fixture.root
    with pytest.raises(
        TushareFinancialPublishError,
        match="TUSHARE_FINANCIAL_PUBLISH_INVALID",
    ):
        publish_tushare_financial_snapshot(**_audit_kwargs(fixture))
    assert not (root / "clean" / "tushare_financials").exists()


def test_existing_snapshot_content_drift_is_rejected_not_overwritten(
    tmp_path: Path,
) -> None:
    fixture = _build_root(tmp_path)
    root = fixture.root
    snapshot = publish_tushare_financial_snapshot(**_audit_kwargs(fixture))
    path = snapshot.root / "dataset=income" / "year=2023.parquet"
    frame = pl.read_parquet(path).with_columns(pl.lit(999.0).alias("n_income"))
    frame.write_parquet(path)

    with pytest.raises(TushareFinancialPublishError):
        verify_tushare_financial_snapshot(data_root=root, snapshot_id=snapshot.snapshot_id)
    with pytest.raises(TushareFinancialPublishError):
        publish_tushare_financial_snapshot(**_audit_kwargs(fixture))


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
    fixture = _build_root(tmp_path, income_frame=income)
    root = fixture.root
    snapshot = publish_tushare_financial_snapshot(**_audit_kwargs(fixture))
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
    fixture = _build_root(tmp_path)
    root = fixture.root
    snapshot = publish_tushare_financial_snapshot(**_audit_kwargs(fixture))
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
