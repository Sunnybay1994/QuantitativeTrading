from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import sqlite3
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import duckdb
import polars as pl
import pytest

import quant.data.audit_tushare_financials as financial_audit
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
_FLOW_FIELDS = (
    ("cashflow", "n_cashflow_act"),
    ("income", "n_income"),
    ("income", "n_income_attr_p"),
)
_FLOW_BUCKETS = ("Q1", "Q2", "Q3", "FY")
_EARLY_EMPTY_SOURCE_EVIDENCE_SHA256 = (
    "793cd498f4dbca6b28661417f49606323248da0cdf8e838575df9f7ef4d0d5db"
)


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


def _publishable_audit(value: dict[str, Any]) -> dict[str, Any]:
    audit = json.loads(json.dumps(value))
    flow = audit["flow_semantics"]
    assert isinstance(flow, dict)
    source_buckets = {
        (bucket["dataset"], bucket["field"], bucket["fiscal_bucket"]): bucket
        for bucket in flow["buckets"]
    }
    buckets: list[dict[str, object]] = []
    for dataset, field in _FLOW_FIELDS:
        for fiscal_bucket in _FLOW_BUCKETS:
            bucket = dict(source_buckets[(dataset, field, fiscal_bucket)])
            bucket.update(
                {
                    "chain_applicable": fiscal_bucket != "Q1",
                    "current_type1_candidates": 100,
                    "distinct_symbols": 100,
                    "fiscal_years": 3,
                    "synchronized_type2_pairs": 100,
                    "previous_chain_eligible": None if fiscal_bucket == "Q1" else 100,
                    "missing_type2": 0,
                    "missing_previous": None if fiscal_bucket == "Q1" else 0,
                    "latest_current_conflicts": 0,
                    "latest_type2_conflicts": 0,
                    "latest_previous_conflicts": 0,
                    "available_date_drift": 0,
                    "missing_operands": 0,
                    "invalid_numeric_operands": 0,
                    "nonfinite_operands": 0,
                    "float64_cent_resolution_lost": 0,
                    "comparable_observations": 100,
                    "mismatch_count": 0,
                    "status": "PASS",
                }
            )
            buckets.append(bucket)
    flow["buckets"] = buckets
    flow["status"] = "PASS"
    audit["publication_allowed"] = True
    return audit


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
    balancesheet_frame: pl.DataFrame | None = None,
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
        if dataset == "balancesheet" and balancesheet_frame is not None:
            frame = balancesheet_frame
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
    assert result["schema_version"] == "tushare-financial-raw-audit-v4"
    assert result["status"] == "READY"
    assert result["publication_allowed"] is False
    assert result["flow_semantics"]["status"] == "INSUFFICIENT"
    assert [
        (bucket["dataset"], bucket["field"], bucket["fiscal_bucket"])
        for bucket in result["flow_semantics"]["buckets"]
    ] == [
        (dataset, field, fiscal_bucket)
        for dataset, field in _FLOW_FIELDS
        for fiscal_bucket in _FLOW_BUCKETS
    ]
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
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _build_root(
        tmp_path,
        income_frame=_frame("income", ann_date="20250101", f_ann_date="20250102"),
    )
    helper_names = (
        "_flow_source_identity",
        "_materialize_safe_projection",
        "_quality_summary",
        "_flow_semantics",
        "_flow_observations",
        "_flow_bucket",
        "_flow_identity_fields",
        "_flow_projection_contract",
        "_flow_source_evidence_sha256",
        "_projection_for_schema_group",
        "_canonicalize_operand",
        "_classify_flow_operands",
        "_float64_cent_resolution",
        "_economic_decimal",
        "_flow_mismatch",
        "_select_latest_observation",
        "_previous_end_date",
    )
    calls = {name: 0 for name in helper_names}
    for name in helper_names:
        original = getattr(financial_audit, name)

        def spy(*args: object, _name=name, _original=original, **kwargs: object):
            calls[_name] += 1
            return _original(*args, **kwargs)

        monkeypatch.setattr(financial_audit, name, spy)

    not_verified = audit_tushare_financials(
        **_audit_kwargs(fixture), verify_bytes=False
    )
    assert not_verified["status"] == "READY"
    assert not_verified["flow_semantics"]["status"] == "NOT_EVALUATED"
    assert not_verified["flow_semantics"]["buckets"] == []
    assert not_verified["flow_semantics"]["source_type_evidence"] == []
    assert not_verified["publication_allowed"] is False
    assert all(value == 0 for value in calls.values())

    result = audit_tushare_financials(**_audit_kwargs(fixture), verify_bytes=True)
    assert result["status"] == "BLOCKED"
    assert result["datasets"]["income"]["quality"]["request_window_mismatches"] == 1
    assert {item["code"] for item in result["blocking_issues"]} >= {
        "INCOME_REQUEST_WINDOW_MISMATCH"
    }
    assert calls["_flow_source_identity"] > 0
    assert calls["_materialize_safe_projection"] > 0
    assert calls["_quality_summary"] > 0
    assert calls["_flow_observations"] == 0
    assert calls["_flow_bucket"] == 0
    assert calls["_flow_semantics"] == 0


def test_per_request_physical_row_drift_has_verified_and_short_circuit_branches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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
    helper_names = (
        "_flow_source_identity",
        "_materialize_safe_projection",
        "_quality_summary",
        "_flow_semantics",
        "_flow_observations",
        "_flow_bucket",
        "_flow_identity_fields",
        "_flow_projection_contract",
        "_flow_source_evidence_sha256",
        "_projection_for_schema_group",
        "_canonicalize_operand",
        "_classify_flow_operands",
        "_float64_cent_resolution",
        "_economic_decimal",
        "_flow_mismatch",
        "_select_latest_observation",
        "_previous_end_date",
    )
    calls = {name: 0 for name in helper_names}
    for name in helper_names:
        original = getattr(financial_audit, name)

        def spy(*args: object, _name=name, _original=original, **kwargs: object):
            calls[_name] += 1
            return _original(*args, **kwargs)

        monkeypatch.setattr(financial_audit, name, spy)

    not_verified = audit_tushare_financials(
        **_audit_kwargs(fixture), verify_bytes=False
    )
    assert not_verified["status"] == "READY"
    assert not_verified["flow_semantics"]["status"] == "NOT_EVALUATED"
    assert not_verified["flow_semantics"]["buckets"] == []
    assert not_verified["flow_semantics"]["source_type_evidence"] == []
    assert not_verified["publication_allowed"] is False
    assert all(value == 0 for value in calls.values())

    result = audit_tushare_financials(**_audit_kwargs(fixture), verify_bytes=True)
    assert result["status"] == "BLOCKED"
    assert result["datasets"]["income"]["quality"]["row_count_mismatch"] == 1
    assert calls["_flow_source_identity"] > 0
    assert calls["_materialize_safe_projection"] > 0
    assert calls["_quality_summary"] > 0
    assert calls["_flow_observations"] == 0
    assert calls["_flow_bucket"] == 0
    assert calls["_flow_semantics"] == 0


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
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _build_root(tmp_path)
    root = fixture.root
    publishable = _publishable_audit(
        audit_tushare_financials(**_audit_kwargs(fixture), verify_bytes=True)
    )
    projection_calls: list[tuple[str, tuple[str, ...]]] = []
    original_projection = financial_publication._projection_for_schema_group

    def spy_projection(**kwargs: object) -> str:
        group = cast(list[financial_audit._CompleteRequest], kwargs["group"])
        projection_calls.append(
            (
                cast(str, kwargs["dataset"]),
                tuple(item.relative_path for item in group),
            )
        )
        return original_projection(**kwargs)

    monkeypatch.setattr(
        financial_publication, "_projection_for_schema_group", spy_projection
    )
    monkeypatch.setattr(
        financial_publication,
        "audit_tushare_financials",
        lambda **_kwargs: publishable,
    )
    first = publish_tushare_financial_snapshot(**_audit_kwargs(fixture))
    assert first.dataset_rows == tuple((dataset, 1) for dataset in _DATASETS)
    assert first.reused is False
    assert projection_calls == [
        (dataset, (entry["relative_file"],))
        for dataset, entry in zip(_DATASETS, publishable["flow_semantics"]["source_type_evidence"])
    ]
    assert first.audit_sha256 == financial_publication._sha(
        financial_publication._canonical(publishable)
    )
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
    verified = verify_tushare_financial_snapshot(
        data_root=root, snapshot_id=first.snapshot_id
    )
    assert verified.dataset_rows == first.dataset_rows
    assert verified.audit_sha256 == first.audit_sha256

    second = publish_tushare_financial_snapshot(**_audit_kwargs(fixture))
    assert second.snapshot_id == first.snapshot_id
    assert second.reused is True
    assert second.audit_sha256 == first.audit_sha256
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


def test_publisher_real_chain_rejects_identity_schema_and_post_audit_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _build_root(tmp_path)
    original = _publishable_audit(
        audit_tushare_financials(**_audit_kwargs(fixture), verify_bytes=True)
    )

    def with_evidence(
        source: dict[str, Any], evidence: list[dict[str, Any]]
    ) -> dict[str, Any]:
        source["flow_semantics"]["source_type_evidence"] = evidence
        source["flow_semantics"]["flow_source_type_evidence_sha256"] = (
            financial_publication._flow_source_evidence_sha256(evidence)
        )
        return source

    not_inventory = json.loads(json.dumps(original))
    missing_entry = not_inventory["flow_semantics"]["source_type_evidence"][0]
    missing_entry["request_id"] = "e" * 64
    missing_entry["relative_file"] = (
        "raw/tushare/balancesheet/request=" + "e" * 64 + "/data.parquet"
    )
    not_inventory = with_evidence(
        not_inventory, not_inventory["flow_semantics"]["source_type_evidence"]
    )

    duplicate = json.loads(json.dumps(original))
    evidence = duplicate["flow_semantics"]["source_type_evidence"]
    duplicate = with_evidence(duplicate, [evidence[0], evidence[1], evidence[1], evidence[2]])

    schema_drift = json.loads(json.dumps(original))
    drift_entry = schema_drift["flow_semantics"]["source_type_evidence"][0]
    drift_entry["schema"] = [
        column
        for column in drift_entry["schema"]
        if column["name"] != "ann_date"
    ]
    schema_drift = with_evidence(
        schema_drift, schema_drift["flow_semantics"]["source_type_evidence"]
    )

    for candidate in (not_inventory, duplicate, schema_drift):
        monkeypatch.setattr(
            financial_publication,
            "audit_tushare_financials",
            lambda _audit=candidate, **_kwargs: _audit,
        )
        with pytest.raises(TushareFinancialPublishError):
            publish_tushare_financial_snapshot(**_audit_kwargs(fixture))
        assert not (fixture.root / "clean" / "tushare_financials").exists()

    post_fixture = _build_root(tmp_path / "post")
    pre = _publishable_audit(
        audit_tushare_financials(**_audit_kwargs(post_fixture), verify_bytes=True)
    )
    post = json.loads(json.dumps(pre))
    post["flow_semantics"]["flow_source_type_evidence_sha256"] = "0" * 64
    audits = iter((pre, post))
    monkeypatch.setattr(
        financial_publication,
        "audit_tushare_financials",
        lambda **_kwargs: next(audits),
    )
    with pytest.raises(TushareFinancialPublishError):
        publish_tushare_financial_snapshot(**_audit_kwargs(post_fixture))
    snapshots = post_fixture.root / "clean" / "tushare_financials" / "snapshots"
    assert snapshots.is_dir()
    assert list(snapshots.iterdir()) == []


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
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _build_root(tmp_path)
    root = fixture.root
    publishable = _publishable_audit(
        audit_tushare_financials(**_audit_kwargs(fixture), verify_bytes=True)
    )
    monkeypatch.setattr(
        financial_publication,
        "audit_tushare_financials",
        lambda **_kwargs: publishable,
    )
    snapshot = publish_tushare_financial_snapshot(**_audit_kwargs(fixture))
    path = snapshot.root / "dataset=income" / "year=2023.parquet"
    frame = pl.read_parquet(path).with_columns(pl.lit(999.0).alias("n_income"))
    frame.write_parquet(path)

    with pytest.raises(TushareFinancialPublishError):
        verify_tushare_financial_snapshot(data_root=root, snapshot_id=snapshot.snapshot_id)
    with pytest.raises(TushareFinancialPublishError):
        publish_tushare_financial_snapshot(**_audit_kwargs(fixture))


def test_bounded_history_read_feeds_typed_pit_revision_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
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
    publishable = _publishable_audit(
        audit_tushare_financials(**_audit_kwargs(fixture), verify_bytes=True)
    )
    monkeypatch.setattr(
        financial_publication,
        "audit_tushare_financials",
        lambda **_kwargs: publishable,
    )
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
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _build_root(tmp_path)
    root = fixture.root
    publishable = _publishable_audit(
        audit_tushare_financials(**_audit_kwargs(fixture), verify_bytes=True)
    )
    monkeypatch.setattr(
        financial_publication,
        "audit_tushare_financials",
        lambda **_kwargs: publishable,
    )
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


def test_publisher_rejects_flow_forgery_before_snapshot_mkdir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _build_root(tmp_path)
    original = _publishable_audit(
        audit_tushare_financials(**_audit_kwargs(fixture), verify_bytes=True)
    )
    candidates = []

    reordered = json.loads(json.dumps(original))
    reordered["flow_semantics"]["buckets"].reverse()
    candidates.append(reordered)

    source_hash = json.loads(json.dumps(original))
    source_hash["flow_semantics"]["flow_source_type_evidence_sha256"] = "0" * 64
    candidates.append(source_hash)

    contract_drift = json.loads(json.dumps(original))
    contract_drift["flow_semantics"]["normalized_projection_contract"]["version"] = (
        "tushare-financial-flow-normalized-projection-v0"
    )
    candidates.append(contract_drift)

    funnel_drift = json.loads(json.dumps(original))
    funnel_drift["flow_semantics"]["buckets"][0]["current_type1_candidates"] = 101
    candidates.append(funnel_drift)

    not_pass = json.loads(json.dumps(original))
    not_pass["flow_semantics"]["status"] = "INSUFFICIENT"
    not_pass["publication_allowed"] = False
    candidates.append(not_pass)

    for candidate in candidates:
        monkeypatch.setattr(
            financial_publication,
            "audit_tushare_financials",
            lambda _audit=candidate, **_kwargs: _audit,
        )
        with pytest.raises(
            TushareFinancialPublishError,
            match="TUSHARE_FINANCIAL_PUBLISH_INVALID",
        ):
            publish_tushare_financial_snapshot(**_audit_kwargs(fixture))
        assert not (fixture.root / "clean" / "tushare_financials").exists()


def test_manifest_and_audit_bytes_sha_forgery_is_rejected_before_public_object(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _build_root(tmp_path)
    publishable = _publishable_audit(
        audit_tushare_financials(**_audit_kwargs(fixture), verify_bytes=True)
    )
    monkeypatch.setattr(
        financial_publication,
        "audit_tushare_financials",
        lambda **_kwargs: publishable,
    )
    snapshot = publish_tushare_financial_snapshot(**_audit_kwargs(fixture))
    manifest_path = snapshot.root / "manifest.json"
    audit_path = snapshot.root / "audit.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    audit_bytes = audit_path.read_bytes()
    drifted_audit = json.loads(audit_bytes)
    drifted_audit["publication_allowed"] = False
    audit_path.write_bytes(financial_publication._canonical(drifted_audit))
    with pytest.raises(TushareFinancialPublishError):
        verify_tushare_financial_snapshot(
            data_root=fixture.root, snapshot_id=snapshot.snapshot_id
        )
    audit_path.write_bytes(audit_bytes)

    invalid_sha = json.loads(json.dumps(manifest))
    invalid_sha["audit_sha256"] = "0" * 64
    missing_sha = json.loads(json.dumps(manifest))
    missing_sha.pop("audit_sha256")
    canonical_drift = json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode()
    manifest_path.write_bytes(financial_publication._canonical(invalid_sha))
    with pytest.raises(TushareFinancialPublishError):
        verify_tushare_financial_snapshot(
            data_root=fixture.root, snapshot_id=snapshot.snapshot_id
        )
    manifest_path.write_bytes(financial_publication._canonical(missing_sha))
    with pytest.raises(TushareFinancialPublishError):
        verify_tushare_financial_snapshot(
            data_root=fixture.root, snapshot_id=snapshot.snapshot_id
        )
    manifest_path.write_bytes(canonical_drift)
    with pytest.raises(TushareFinancialPublishError):
        verify_tushare_financial_snapshot(
            data_root=fixture.root, snapshot_id=snapshot.snapshot_id
        )
    with pytest.raises(TushareFinancialPublishError):
        publish_tushare_financial_snapshot(**_audit_kwargs(fixture))


def _stub_quality(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "raw_rows": 1,
        "row_count_mismatch": 0,
        "missing_request_rows": 0,
        "request_symbol_mismatches": 0,
        "request_window_mismatches": 0,
        "critical_null_rows": 0,
        "invalid_symbol_rows": 0,
        "invalid_ann_date_rows": 0,
        "invalid_f_ann_date_rows": 0,
        "invalid_end_date_rows": 0,
        "end_after_available_rows": 0,
        "required_numeric_parse_rows": 0,
        "required_numeric_nonfinite_rows": 0,
        "invalid_report_type_rows": 0,
        "invalid_comp_type_rows": 0,
        "same_available_duplicate_groups": 0,
        "required_economic_conflict_groups": 0,
        "revision_chain_groups": 0,
        "eligible_rows": 1,
        "quarantined_rows": 0,
        "column_set_count": 1,
        "column_set_sha256s": ["a" * 64],
        "required_numeric_union_types": {},
        "report_type_counts": [],
        "comp_type_counts": [],
        "report_type_comp_type_counts": [],
    }
    value.update(overrides)
    return value


def _stub_complete(
    tmp_path: Path, dataset: str, ordinal: int
) -> financial_audit._CompleteRequest:
    request_id = f"{ordinal:064x}"
    return financial_audit._CompleteRequest(
        request_id=request_id,
        dataset=dataset,
        catalog_sha256="c" * 64,
        symbol="000001.SZ",
        start_date="20230101",
        end_date="20241231",
        rows=1,
        max_rows=6000,
        checksum_sha256="a" * 64,
        metadata_sha256="b" * 64,
        columns=("ts_code", "ann_date", "end_date"),
        parquet_path=tmp_path / f"{dataset}-{ordinal}.parquet",
        relative_path=f"raw/tushare/{dataset}/request={request_id}/data.parquet",
    )


def _real_complete(
    tmp_path: Path, dataset: str, ordinal: int, frame: pl.DataFrame
) -> financial_audit._CompleteRequest:
    request_id = f"{ordinal:064x}"
    parquet_path = (
        tmp_path
        / "raw"
        / "tushare"
        / dataset
        / f"request={request_id}"
        / "data.parquet"
    )
    parquet_path.parent.mkdir(parents=True)
    frame.write_parquet(parquet_path)
    return financial_audit._CompleteRequest(
        request_id=request_id,
        dataset=dataset,
        catalog_sha256="c" * 64,
        symbol="000001.SZ",
        start_date="20230101",
        end_date="20241231",
        rows=frame.height,
        max_rows=6000,
        checksum_sha256="a" * 64,
        metadata_sha256="b" * 64,
        columns=tuple(frame.columns),
        parquet_path=parquet_path,
        relative_path=f"raw/tushare/{dataset}/request={request_id}/data.parquet",
    )


def _enable_json_profile(connection: duckdb.DuckDBPyConnection, path: Path) -> None:
    selector = path.as_posix().replace("'", "''")
    connection.execute("PRAGMA enable_profiling='json'")
    connection.execute(f"PRAGMA profiling_output='{selector}'")


def _profiled_parquet_reads(path: Path) -> list[tuple[str, int]]:
    profile = json.loads(path.read_text(encoding="utf-8"))
    reads: list[tuple[str, int]] = []

    def visit(node: object) -> None:
        if isinstance(node, dict):
            name = node.get("operator_name") or node.get("operator_type") or node.get(
                "name"
            )
            extra = node.get("extra_info")
            function = extra.get("Function") if isinstance(extra, dict) else None
            if name in {"READ_PARQUET", "PARQUET_SCAN"} or function in {
                "READ_PARQUET",
                "PARQUET_SCAN",
            }:
                total = extra.get("Total Files Read") if isinstance(extra, dict) else None
                if type(total) is str and total.isdigit():
                    reads.append(("READ_PARQUET", int(total)))
                elif type(total) is int and total >= 0:
                    reads.append(("READ_PARQUET", total))
                else:
                    pytest.fail("JSON profiling omitted Total Files Read")
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(profile)
    if not reads:
        pytest.fail("JSON profiling omitted READ_PARQUET/PARQUET_SCAN")
    return reads


def _install_stubbed_audit(
    monkeypatch: pytest.MonkeyPatch,
    complete: list[financial_audit._CompleteRequest],
    qualities: dict[str, dict[str, object]],
    events: list[str],
    *,
    flow_result: dict[str, object] | None = None,
    source_identity: financial_audit._FlowSourceIdentity | None = None,
    quality_tables: dict[str, str] | None = None,
    quality_threads: dict[str, int] | None = None,
) -> None:
    plan = financial_audit._VerifiedPlan(
        closure={
            "catalog_sha256": "c" * 64,
            "request_counts": {dataset: 1 for dataset in _DATASETS},
        },
        expected_requests=(),
    )
    rows = [(item.request_id, item.dataset, "COMPLETE") for item in complete]
    identity = source_identity or financial_audit._FlowSourceIdentity(
        evidence=(), schemas={}, untokenizable=()
    )

    class _Connection:
        def execute(self, *_args: object, **_kwargs: object) -> None:
            return None

        def close(self) -> None:
            return None

    monkeypatch.setattr(financial_audit, "_verify_plan", lambda **_kwargs: plan)
    monkeypatch.setattr(financial_audit, "_verify_ledger_plan", lambda **_kwargs: None)
    monkeypatch.setattr(financial_audit, "_read_ledger", lambda _path: (rows, 0))
    monkeypatch.setattr(financial_audit, "_load_complete", lambda **_kwargs: complete)
    monkeypatch.setattr(
        financial_audit,
        "duckdb",
        type("_DuckDB", (), {"connect": staticmethod(lambda _dsn: _Connection())}),
    )
    monkeypatch.setattr(
        financial_audit,
        "_flow_source_identity",
        lambda **_kwargs: events.append("identity") or identity,
    )
    monkeypatch.setattr(
        financial_audit,
        "_materialize_safe_projection",
        lambda **kwargs: events.append(f"projection:{kwargs['dataset']}")
        or f"table_{kwargs['dataset']}",
    )
    def fake_quality(**kwargs: object) -> dict[str, object]:
        dataset = cast(str, kwargs["dataset"])
        if quality_tables is not None:
            quality_tables[dataset] = cast(str, kwargs["table"])
        if quality_threads is not None:
            quality_threads[dataset] = cast(int, kwargs["threads"])
        events.append(f"quality:{dataset}")
        return qualities[dataset]

    monkeypatch.setattr(financial_audit, "_quality_summary", fake_quality)
    monkeypatch.setattr(
        financial_audit,
        "_flow_observations",
        lambda **_kwargs: events.append("observations") or (),
    )
    monkeypatch.setattr(
        financial_audit,
        "_flow_bucket",
        lambda **_kwargs: events.append("bucket") or {},
    )
    monkeypatch.setattr(
        financial_audit,
        "_flow_semantics",
        lambda **_kwargs: events.append("economic")
        or (flow_result or {"status": "INSUFFICIENT"}),
    )


def test_flow_prerequisites_short_circuit_all_flow_helpers_and_use_early_sha(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    complete: list[financial_audit._CompleteRequest] = [
        _stub_complete(tmp_path, dataset, ordinal)
        for ordinal, dataset in enumerate(_DATASETS, start=1)
    ]
    complete_rows = [(item.request_id, item.dataset, "COMPLETE") for item in complete]
    plan = financial_audit._VerifiedPlan(
        closure={
            "catalog_sha256": "c" * 64,
            "request_counts": {dataset: 1 for dataset in _DATASETS},
        },
        expected_requests=(),
    )
    state: dict[str, object] = {
        "rows": complete_rows,
        "lease": 0,
        "verify": False,
        "quality": {},
    }
    calls = {
        name: 0
        for name in (
            "_flow_source_identity",
            "_materialize_safe_projection",
            "_quality_summary",
            "_flow_semantics",
            "_flow_observations",
            "_flow_bucket",
            "_flow_identity_fields",
            "_flow_projection_contract",
            "_flow_source_evidence_sha256",
            "_projection_for_schema_group",
            "_canonicalize_operand",
            "_classify_flow_operands",
            "_float64_cent_resolution",
            "_economic_decimal",
            "_flow_mismatch",
            "_select_latest_observation",
            "_previous_end_date",
        )
    }

    monkeypatch.setattr(financial_audit, "_verify_plan", lambda **_kwargs: plan)
    monkeypatch.setattr(financial_audit, "_verify_ledger_plan", lambda **_kwargs: None)
    monkeypatch.setattr(
        financial_audit,
        "_read_ledger",
        lambda _path: (state["rows"], state["lease"]),
    )
    monkeypatch.setattr(
        financial_audit, "_load_complete", lambda **_kwargs: complete
    )
    monkeypatch.setattr(
        financial_audit,
        "_quality_summary",
        lambda **_kwargs: _stub_quality(**cast(dict[str, object], state["quality"])),
    )

    def fail(name: str):
        def _fail(*_args: object, **_kwargs: object) -> object:
            calls[name] += 1
            raise AssertionError(name)

        return _fail

    for name in calls:
        monkeypatch.setattr(financial_audit, name, fail(name))

    cases = (
        (False, 0, {}, complete_rows),
        (True, 1, {}, complete_rows),
        (True, 0, {}, [*complete_rows[:3], (complete[3].request_id, "income", "PENDING")]),
    )
    for verify, lease, quality, rows in cases:
        state.update({"verify": verify, "lease": lease, "quality": quality, "rows": rows})
        result = financial_audit._audit(
            data_root=tmp_path,
            plan_report_path=tmp_path / "plan.json",
            catalog_path=tmp_path / "catalog.toml",
            threads=1,
            verify_bytes=verify,
        )
        flow = result["flow_semantics"]
        assert flow["status"] == "NOT_EVALUATED"
        assert flow["buckets"] == []
        assert flow["source_type_evidence"] == []
        assert flow["flow_source_type_evidence_sha256"] == _EARLY_EMPTY_SOURCE_EVIDENCE_SHA256
        assert result["publication_allowed"] is False
    assert all(value == 0 for value in calls.values())


def test_v3_quality_consumes_the_already_materialized_safe_projection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    complete = [
        _stub_complete(tmp_path, dataset, ordinal)
        for ordinal, dataset in enumerate(_DATASETS, start=1)
    ]
    qualities = {dataset: _stub_quality() for dataset in _DATASETS}
    events: list[str] = []
    quality_tables: dict[str, str] = {}
    quality_threads: dict[str, int] = {}
    _install_stubbed_audit(
        monkeypatch,
        complete,
        qualities,
        events,
        flow_result={"status": "PASS"},
        quality_tables=quality_tables,
        quality_threads=quality_threads,
    )
    result = financial_audit._audit(
        data_root=tmp_path,
        plan_report_path=tmp_path / "plan.json",
        catalog_path=tmp_path / "catalog.toml",
        threads=3,
        verify_bytes=True,
    )
    assert quality_tables == {
        dataset: f"table_{dataset}" for dataset in _DATASETS
    }
    assert quality_threads == {dataset: 3 for dataset in _DATASETS}
    assert events.index("projection:balancesheet") < events.index("quality:balancesheet")
    assert events.index("projection:cashflow") < events.index("quality:cashflow")
    assert events.index("projection:fina_indicator") < events.index("quality:fina_indicator")
    assert events.index("projection:income") < events.index("quality:income")
    assert result["flow_semantics"]["status"] == "PASS"


def test_a_b_c_stage_order_and_b_failure_short_circuits_economic_helpers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    complete = [
        _stub_complete(tmp_path, dataset, ordinal)
        for ordinal, dataset in enumerate(_DATASETS, start=1)
    ]
    qualities = {dataset: _stub_quality() for dataset in _DATASETS}
    events: list[str] = []
    _install_stubbed_audit(monkeypatch, complete, qualities, events, flow_result={"status": "PASS"})
    result = financial_audit._audit(
        data_root=tmp_path,
        plan_report_path=tmp_path / "plan.json",
        catalog_path=tmp_path / "catalog.toml",
        threads=1,
        verify_bytes=True,
    )
    assert events == [
        "identity",
        *[f"projection:{dataset}" for dataset in _DATASETS],
        *[f"quality:{dataset}" for dataset in _DATASETS],
        "economic",
    ]
    assert result["flow_semantics"]["status"] == "PASS"

    events.clear()
    qualities["income"] = _stub_quality(critical_null_rows=1)
    for helper in (
        "_canonicalize_operand",
        "_classify_flow_operands",
        "_float64_cent_resolution",
        "_economic_decimal",
        "_flow_mismatch",
        "_select_latest_observation",
        "_previous_end_date",
    ):
        monkeypatch.setattr(
            financial_audit,
            helper,
            lambda *_args, _helper=helper, **_kwargs: pytest.fail(_helper),
        )
    result = financial_audit._audit(
        data_root=tmp_path,
        plan_report_path=tmp_path / "plan.json",
        catalog_path=tmp_path / "catalog.toml",
        threads=1,
        verify_bytes=True,
    )
    assert result["flow_semantics"]["status"] == "NOT_EVALUATED"
    assert "economic" not in events
    assert "observations" not in events
    assert "bucket" not in events
    assert result["status"] == "BLOCKED"


def test_flow_numeric_invalidity_only_reduces_flow_coverage_but_balance_invalid_blocks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    complete = [
        _stub_complete(tmp_path, dataset, ordinal)
        for ordinal, dataset in enumerate(_DATASETS, start=1)
    ]
    qualities = {dataset: _stub_quality() for dataset in _DATASETS}
    qualities["cashflow"] = _stub_quality(
        required_numeric_parse_rows=1, eligible_rows=0, quarantined_rows=1
    )
    events: list[str] = []
    _install_stubbed_audit(monkeypatch, complete, qualities, events, flow_result={"status": "PASS"})
    result = financial_audit._audit(
        data_root=tmp_path,
        plan_report_path=tmp_path / "plan.json",
        catalog_path=tmp_path / "catalog.toml",
        threads=1,
        verify_bytes=True,
    )
    assert result["status"] == "READY"
    assert result["publication_allowed"] is True
    assert not any(
        issue["code"] == "CASHFLOW_REQUIRED_NUMERIC_PARSE_INVALID"
        for issue in result["blocking_issues"]
    )

    events.clear()
    qualities["balancesheet"] = _stub_quality(
        required_numeric_nonfinite_rows=1, eligible_rows=0, quarantined_rows=1
    )
    result = financial_audit._audit(
        data_root=tmp_path,
        plan_report_path=tmp_path / "plan.json",
        catalog_path=tmp_path / "catalog.toml",
        threads=1,
        verify_bytes=True,
    )
    assert result["status"] == "BLOCKED"
    assert result["publication_allowed"] is False
    assert "economic" not in events
    assert any(
        issue["code"] == "BALANCESHEET_REQUIRED_NUMERIC_NONFINITE"
        for issue in result["blocking_issues"]
    )


def test_flow_and_publisher_bucket_order_is_exact_and_stable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = financial_audit._FlowSourceIdentity(
        evidence=(), schemas={}, untokenizable=()
    )
    projection_datasets: list[str] = []
    observation_tables: list[tuple[str, str]] = []
    bucket_order: list[tuple[str, str]] = []
    monkeypatch.setattr(
        financial_audit,
        "_materialize_safe_projection",
        lambda **kwargs: pytest.fail(
            f"late materialization for {kwargs['dataset']}"
        ),
    )

    def fake_observations(**kwargs: object) -> tuple[object, ...]:
        observation_tables.append(
            (cast(str, kwargs["dataset"]), cast(str, kwargs["table"]))
        )
        return ()

    monkeypatch.setattr(financial_audit, "_flow_observations", fake_observations)

    def fake_bucket(**kwargs: object) -> dict[str, object]:
        bucket_order.append((kwargs["field"], kwargs["fiscal_bucket"]))
        return {"status": "PASS"}

    monkeypatch.setattr(financial_audit, "_flow_bucket", fake_bucket)
    result = financial_audit._flow_semantics(
        connection=object(),
        source_identity=identity,
        tables={"cashflow": "b1_cashflow", "income": "b1_income"},
    )
    assert result["status"] == "PASS"
    assert projection_datasets == []
    assert observation_tables == [
        ("cashflow", "b1_cashflow"),
        ("income", "b1_income"),
    ]
    assert bucket_order == [
        (field, fiscal_bucket)
        for _, field in _FLOW_FIELDS
        for fiscal_bucket in _FLOW_BUCKETS
    ]
    assert financial_publication._FLOW_FIELDS == _FLOW_FIELDS


def test_flow_coverage_status_locks_exact_80_100_zero_and_priority() -> None:
    status = financial_audit._flow_bucket_status
    assert status(
        chain_applicable=False,
        current_candidates=100,
        distinct_symbols=100,
        synchronized=80,
        previous_chain_eligible=None,
        comparable=100,
        fiscal_years=3,
        mismatch_count=0,
    ) == "PASS"
    assert status(
        chain_applicable=True,
        current_candidates=100,
        distinct_symbols=100,
        synchronized=100,
        previous_chain_eligible=80,
        comparable=100,
        fiscal_years=3,
        mismatch_count=0,
    ) == "PASS"
    assert status(
        chain_applicable=True,
        current_candidates=0,
        distinct_symbols=100,
        synchronized=0,
        previous_chain_eligible=0,
        comparable=100,
        fiscal_years=3,
        mismatch_count=0,
    ) == "INSUFFICIENT"
    for field, value in (("distinct_symbols", 99), ("fiscal_years", 2), ("comparable", 99)):
        kwargs: dict[str, object] = {
            "chain_applicable": False,
            "current_candidates": 100,
            "distinct_symbols": 100,
            "synchronized": 100,
            "previous_chain_eligible": None,
            "comparable": 100,
            "fiscal_years": 3,
            "mismatch_count": 0,
        }
        kwargs[field] = value
        assert status(**kwargs) == "INSUFFICIENT"
    assert status(
        chain_applicable=False,
        current_candidates=100,
        distinct_symbols=100,
        synchronized=100,
        previous_chain_eligible=None,
        comparable=100,
        fiscal_years=3,
        mismatch_count=1,
    ) == "CONTRADICTED"


def test_canonicalizer_grammar_types_and_priority_are_single_source() -> None:
    canonicalize = financial_audit._canonicalize_operand
    assert canonicalize(source_type="VARCHAR", raw=" 1e0 ", projected=1.0).token == "1"
    assert canonicalize(source_type="DOUBLE", raw="1", projected=1.0).token == "1"
    assert canonicalize(source_type="DECIMAL(18,2)", raw="-0.00", projected=-0.0).token == "0"
    assert canonicalize(source_type="VARCHAR", raw="", projected=None).category == "missing"
    assert canonicalize(source_type="VARCHAR", raw="١", projected=None).category == "invalid"
    assert canonicalize(source_type="VARCHAR", raw="true", projected=None).token == "INVALID:VARCHAR:true"
    assert canonicalize(source_type="VARCHAR", raw="1e9999", projected=float("inf")).token == (
        "INVALID_OVERFLOW:1e9999"
    )
    assert canonicalize(source_type="DOUBLE", raw="NaN", projected=float("nan")).token == (
        "NONFINITE:NAN"
    )
    assert canonicalize(source_type="DOUBLE", raw="-Infinity", projected=float("-inf")).token == (
        "NONFINITE:-INF"
    )
    assert canonicalize(source_type="BOOLEAN", raw=True, projected=1.0).token == (
        "INVALID_BOOLEAN:true"
    )
    assert canonicalize(source_type="DATE", raw="20240101", projected=None).token == (
        "INVALID:DATE:20240101"
    )
    assert financial_audit._classify_flow_operands(
        (
            canonicalize(source_type="BOOLEAN", raw=True, projected=1.0),
            canonicalize(source_type="DOUBLE", raw="nan", projected=float("nan")),
        )
    ) == "invalid_numeric_operands"
    assert financial_audit._classify_flow_operands(
        (
            canonicalize(source_type="VARCHAR", raw="", projected=None),
            canonicalize(source_type="DOUBLE", raw="nan", projected=float("nan")),
        )
    ) == "missing_operands"


def _cashflow_observation(
    value: object,
    *,
    end_date: dt.date,
    available_date: dt.date,
    report_type: str = "1",
    token: str | None = None,
    category: str = "finite",
    projected: float | None = None,
) -> object:
    if token is None:
        token = str(value)
    if projected is None and category == "finite":
        projected = float(value)
    operand = financial_audit._CanonicalOperand(token, category, projected)
    return financial_audit._FlowObservation(
        dataset="cashflow",
        symbol="000001.SZ",
        ann_date=available_date,
        f_ann_date=None,
        available_date=available_date,
        end_date=end_date,
        report_type=report_type,
        comp_type="1",
        update_flag="0",
        source_file="raw/tushare/cashflow/request=" + "a" * 64 + "/data.parquet",
        raw_values=(value,),
        projected_values=(projected,),
        source_types=("DOUBLE",),
        canonical_values=(operand,),
    )


def test_selection_conflicts_missing_drift_and_chain_have_no_fallback() -> None:
    q1 = dt.date(2023, 3, 31)
    q2 = dt.date(2023, 6, 30)
    current_date = dt.date(2024, 4, 20)
    old_date = dt.date(2024, 4, 19)
    new_date = dt.date(2024, 4, 21)
    bucket = financial_audit._flow_bucket
    current = _cashflow_observation(10, end_date=q1, available_date=current_date)
    type2 = _cashflow_observation(10, end_date=q1, available_date=current_date, report_type="2")
    conflict = _cashflow_observation(11, end_date=q1, available_date=current_date)
    current_conflict_bucket = bucket(
        observations=[current, conflict], field="n_cashflow_act", fiscal_bucket="Q1"
    )
    assert current_conflict_bucket["dataset"] == "cashflow"
    assert current_conflict_bucket["latest_current_conflicts"] == 1
    assert bucket(observations=[current], field="n_cashflow_act", fiscal_bucket="Q1")[
        "missing_type2"
    ] == 1
    type2_conflict = _cashflow_observation(
        11, end_date=q1, available_date=current_date, report_type="2"
    )
    assert bucket(
        observations=[current, type2, type2_conflict],
        field="n_cashflow_act",
        fiscal_bucket="Q1",
    )["latest_type2_conflicts"] == 1
    assert bucket(
        observations=[
            current,
            _cashflow_observation(10, end_date=q1, available_date=old_date, report_type="2"),
        ],
        field="n_cashflow_act",
        fiscal_bucket="Q1",
    )["available_date_drift"] == 1
    q2_current = _cashflow_observation(20, end_date=q2, available_date=current_date)
    q2_type2 = _cashflow_observation(20, end_date=q2, available_date=current_date, report_type="2")
    late_previous = _cashflow_observation(10, end_date=q1, available_date=new_date)
    assert bucket(
        observations=[q2_current, q2_type2, late_previous],
        field="n_cashflow_act",
        fiscal_bucket="Q2",
    )["missing_previous"] == 1
    previous_conflict = _cashflow_observation(11, end_date=q1, available_date=current_date)
    assert bucket(
        observations=[q2_current, q2_type2, current, previous_conflict],
        field="n_cashflow_act",
        fiscal_bucket="Q2",
    )["latest_previous_conflicts"] == 1


def test_decimal_tolerance_and_float64_resolution_boundaries_are_exact() -> None:
    def finite(value: float) -> financial_audit._CanonicalOperand:
        return financial_audit._CanonicalOperand("x", "finite", value)
    assert not financial_audit._flow_mismatch(
        current=finite(1.01), type2=finite(1.0), previous=None
    )
    assert financial_audit._flow_mismatch(
        current=finite(1.0100000001), type2=finite(1.0), previous=None
    )
    assert not financial_audit._flow_mismatch(
        current=finite(-1.01), type2=finite(-1.0), previous=None
    )
    assert financial_audit._cent_resolution_from_spacing(Decimal("0.01"), Decimal("0.01"))
    assert not financial_audit._cent_resolution_from_spacing(
        Decimal("0.0100000001"), Decimal("0.01")
    )
    assert financial_audit._float64_cent_resolution(0.0)
    assert financial_audit._float64_cent_resolution(math.ldexp(1.0, -1074))
    assert financial_audit._float64_cent_resolution(2.0**-10)
    assert not financial_audit._float64_cent_resolution(float("nan"))
    assert not financial_audit._float64_cent_resolution(float("inf"))
    assert not financial_audit._float64_cent_resolution(1.7976931348623157e308)


def test_untokenizable_identity_preserves_evidence_but_blocks_flow() -> None:
    evidence = (
        {
            "dataset": "cashflow",
            "request_id": "a" * 64,
            "relative_file": "raw/tushare/cashflow/request=" + "a" * 64 + "/data.parquet",
            "schema": [{"name": "n_cashflow_act", "logical_type": "STRUCT"}],
            "required_economic_types": {"n_cashflow_act": "STRUCT"},
        },
    )
    identity = financial_audit._FlowSourceIdentity(
        evidence=evidence,
        schemas={},
        untokenizable=(("cashflow", evidence[0]["relative_file"], "n_cashflow_act"),),
    )
    flow = financial_audit._not_evaluated_flow(identity)
    assert flow["status"] == "NOT_EVALUATED"
    assert flow["buckets"] == []
    assert flow["source_type_evidence"] == list(evidence)
    assert flow["flow_source_type_evidence_sha256"] == financial_audit._flow_source_evidence_sha256(
        list(evidence)
    )


def test_untokenizable_blocking_aggregates_distinct_pairs_in_dataset_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def evidence_entry(dataset: str, request_id: str, fields: tuple[str, ...]) -> dict[str, object]:
        relative_file = f"raw/tushare/{dataset}/request={request_id}/data.parquet"
        return {
            "dataset": dataset,
            "request_id": request_id,
            "relative_file": relative_file,
            "schema": [
                {"name": field, "logical_type": "STRUCT"} for field in fields
            ],
            "required_economic_types": {
                field: "STRUCT" for field in fields
            },
        }

    cashflow_one = "a" * 64
    cashflow_two = "b" * 64
    income_one = "c" * 64
    balance_one = "d" * 64
    cashflow_file_one = f"raw/tushare/cashflow/request={cashflow_one}/data.parquet"
    cashflow_file_two = f"raw/tushare/cashflow/request={cashflow_two}/data.parquet"
    income_file = f"raw/tushare/income/request={income_one}/data.parquet"
    balance_file = f"raw/tushare/balancesheet/request={balance_one}/data.parquet"
    evidence = (
        evidence_entry("balancesheet", balance_one, ("total_assets",)),
        evidence_entry("cashflow", cashflow_one, ("n_cashflow_act",)),
        evidence_entry("cashflow", cashflow_two, ("n_cashflow_act",)),
        evidence_entry("income", income_one, ("n_income", "n_income_attr_p")),
    )
    untokenizable = (
        ("income", income_file, "n_income_attr_p"),
        ("cashflow", cashflow_file_one, "n_cashflow_act"),
        ("income", income_file, "n_income"),
        ("cashflow", cashflow_file_one, "n_cashflow_act"),
        ("balancesheet", balance_file, "total_assets"),
        ("cashflow", cashflow_file_two, "n_cashflow_act"),
    )
    complete = [
        _stub_complete(tmp_path, dataset, ordinal)
        for ordinal, dataset in enumerate(_DATASETS, start=1)
    ]
    qualities = {dataset: _stub_quality() for dataset in _DATASETS}
    events: list[str] = []
    identity = financial_audit._FlowSourceIdentity(
        evidence=evidence,
        schemas={},
        untokenizable=untokenizable,
    )
    _install_stubbed_audit(monkeypatch, complete, qualities, events, source_identity=identity)
    for helper in (
        "_canonicalize_operand",
        "_classify_flow_operands",
        "_float64_cent_resolution",
        "_economic_decimal",
        "_flow_mismatch",
        "_select_latest_observation",
        "_previous_end_date",
    ):
        monkeypatch.setattr(
            financial_audit,
            helper,
            lambda *_args, _helper=helper, **_kwargs: pytest.fail(_helper),
        )
    first = financial_audit._audit(
        data_root=tmp_path,
        plan_report_path=tmp_path / "plan.json",
        catalog_path=tmp_path / "catalog.toml",
        threads=1,
        verify_bytes=True,
    )
    assert first["blocking_issues"] == [
        {
            "code": "BALANCESHEET_FLOW_SOURCE_TYPE_UNTOKENIZABLE",
            "count": 1,
        },
        {"code": "CASHFLOW_FLOW_SOURCE_TYPE_UNTOKENIZABLE", "count": 2},
        {"code": "INCOME_FLOW_SOURCE_TYPE_UNTOKENIZABLE", "count": 2},
    ]
    assert first["flow_semantics"]["source_type_evidence"] == list(evidence)
    assert first["flow_semantics"]["buckets"] == []
    assert first["publication_allowed"] is False
    assert "economic" not in events
    assert "observations" not in events
    assert "bucket" not in events

    events.clear()
    shuffled_identity = financial_audit._FlowSourceIdentity(
        evidence=evidence,
        schemas={},
        untokenizable=tuple(reversed(untokenizable)),
    )
    _install_stubbed_audit(
        monkeypatch,
        complete,
        qualities,
        events,
        source_identity=shuffled_identity,
    )
    second = financial_audit._audit(
        data_root=tmp_path,
        plan_report_path=tmp_path / "plan.json",
        catalog_path=tmp_path / "catalog.toml",
        threads=1,
        verify_bytes=True,
    )
    assert second["blocking_issues"] == first["blocking_issues"]
    assert second["flow_semantics"] == first["flow_semantics"]
    assert second["publication_allowed"] is False
    assert "economic" not in events

    duplicate_identity = financial_audit._FlowSourceIdentity(
        evidence=(evidence[1],),
        schemas={},
        untokenizable=(
            ("cashflow", cashflow_file_one, "n_cashflow_act"),
            ("cashflow", cashflow_file_one, "n_cashflow_act"),
        ),
    )
    events.clear()
    _install_stubbed_audit(
        monkeypatch,
        complete,
        qualities,
        events,
        source_identity=duplicate_identity,
    )
    duplicate = financial_audit._audit(
        data_root=tmp_path,
        plan_report_path=tmp_path / "plan.json",
        catalog_path=tmp_path / "catalog.toml",
        threads=1,
        verify_bytes=True,
    )
    assert duplicate["blocking_issues"] == [
        {"code": "CASHFLOW_FLOW_SOURCE_TYPE_UNTOKENIZABLE", "count": 1}
    ]
    assert duplicate["flow_semantics"]["source_type_evidence"] == [evidence[1]]
    assert duplicate["flow_semantics"]["buckets"] == []
    assert duplicate["publication_allowed"] is False
    assert "economic" not in events


def test_two_stage_projection_contract_and_mixed_source_types_are_safe(
    tmp_path: Path,
) -> None:
    contract = financial_audit._flow_projection_contract()
    assert list(contract) == ["version", "representation", "stage_b1", "stage_b2"]
    assert contract == {
        "version": "tushare-financial-flow-normalized-projection-v1",
        "representation": "TWO_STAGE",
        "stage_b1": {
            "name": "safe_source_relation",
            "base_columns": [
                "_flow_dataset",
                "ts_code",
                "ann_date",
                "f_ann_date",
                "end_date",
                "report_type",
                "comp_type",
                "update_flag",
                "_request_id",
                "_source_file",
            ],
            "dataset_field_order": {
                "balancesheet": ["total_assets", "total_hldr_eqy_exc_min_int"],
                "cashflow": ["n_cashflow_act"],
                "fina_indicator": [],
                "income": ["n_income", "n_income_attr_p"],
            },
            "per_field_columns": [
                "_flow_source_type_<field>",
                "_flow_raw_<field>",
                "_flow_projected_<field>",
            ],
            "union": "UNION_ALL_OF_SCHEMA_GROUP_PROJECTIONS",
            "raw_file_reads_per_file": 1,
        },
        "stage_b2": {
            "name": "canonical_observation_relation",
            "python_type": "_FlowObservation",
            "parallel_field_sequences": [
                "source_types",
                "raw_values",
                "projected_values",
                "canonical_values",
            ],
            "canonical_operand_fields": ["token", "category", "projected"],
            "single_canonicalizer": "_canonicalize_operand",
            "available_date_rule": "MAX_ANN_DATE_F_ANN_DATE",
        },
    }

    def cashflow_frame(
        logical_type: str, *, reverse_columns: bool, first: object, second: object
    ) -> pl.DataFrame:
        dtype = {
            "BOOLEAN": pl.Boolean,
            "VARCHAR": pl.String,
            "DOUBLE": pl.Float64,
        }[logical_type]
        values: dict[str, pl.Series] = {
            "ts_code": pl.Series(
                "ts_code", ["000001.SZ", "000002.SZ"], dtype=pl.String
            ),
            "ann_date": pl.Series(
                "ann_date", ["20240420", "20240421"], dtype=pl.String
            ),
            "f_ann_date": pl.Series(
                "f_ann_date", ["20240420", "20240421"], dtype=pl.String
            ),
            "end_date": pl.Series(
                "end_date", ["20230331", "20230630"], dtype=pl.String
            ),
            "report_type": pl.Series("report_type", ["1", "1"], dtype=pl.String),
            "comp_type": pl.Series("comp_type", ["1", "1"], dtype=pl.String),
            "update_flag": pl.Series("update_flag", ["0", "0"], dtype=pl.String),
            "n_cashflow_act": pl.Series(
                "n_cashflow_act", [first, second], dtype=dtype
            ),
        }
        order = tuple(reversed(values)) if reverse_columns else tuple(values)
        return pl.DataFrame(values).select(order)

    complete = [
        _real_complete(
            tmp_path,
            "cashflow",
            1,
            cashflow_frame("BOOLEAN", reverse_columns=False, first=True, second=False),
        ),
        _real_complete(
            tmp_path,
            "cashflow",
            2,
            cashflow_frame("BOOLEAN", reverse_columns=False, first=False, second=True),
        ),
        _real_complete(
            tmp_path,
            "cashflow",
            3,
            cashflow_frame(
                "VARCHAR", reverse_columns=True, first="1.00", second="2.00"
            ),
        ),
        _real_complete(
            tmp_path,
            "cashflow",
            4,
            cashflow_frame("DOUBLE", reverse_columns=False, first=3.0, second=4.0),
        ),
    ]

    def materialize(
        items: list[financial_audit._CompleteRequest],
        *,
        profile_path: Path,
        reverse_schema_order: bool = False,
    ) -> tuple[
        tuple[dict[str, object], ...],
        list[str],
        list[tuple[object, ...]],
        int,
        list[tuple[str, int]],
    ]:
        connection = duckdb.connect(":memory:")
        try:
            _enable_json_profile(connection, profile_path)
            identity = financial_audit._flow_source_identity(
                connection=connection, complete=items
            )
            assert set(identity.schemas) == {item.relative_path for item in items}
            if reverse_schema_order:
                identity = financial_audit._FlowSourceIdentity(
                    evidence=identity.evidence,
                    schemas=dict(reversed(list(identity.schemas.items()))),
                    untokenizable=identity.untokenizable,
                )
            table = financial_audit._materialize_safe_projection(
                connection=connection,
                dataset="cashflow",
                complete=items,
                source_identity=identity,
            )
            profile_reads = _profiled_parquet_reads(profile_path)
            financial_audit._validate_projected_sources(
                connection=connection, table=table, complete=items
            )
            columns = [
                cast(str, row[0])
                for row in connection.execute(f"DESCRIBE SELECT * FROM {table}").fetchall()
            ]
            rows = connection.execute(
                f"SELECT _source_file,_flow_source_type_n_cashflow_act,"
                f"_flow_raw_n_cashflow_act,_flow_projected_n_cashflow_act FROM {table} "
                "ORDER BY _source_file,_flow_raw_n_cashflow_act"
            ).fetchall()
            group_sizes: dict[tuple[tuple[str, str], ...], int] = {}
            for schema in identity.schemas.values():
                group_sizes[schema.schema] = group_sizes.get(schema.schema, 0) + 1
            assert sum(group_sizes.values()) == len(items)
            return (
                identity.evidence,
                columns,
                rows,
                len(group_sizes),
                profile_reads,
            )
        finally:
            connection.close()

    def publisher_projection(
        items: list[financial_audit._CompleteRequest],
        *,
        profile_path: Path,
        reverse_schema_order: bool = False,
    ) -> tuple[list[str], list[tuple[object, ...]], list[tuple[str, int]]]:
        connection = duckdb.connect(":memory:")
        try:
            _enable_json_profile(connection, profile_path)
            identity = financial_audit._flow_source_identity(
                connection=connection, complete=items
            )
            assert set(identity.schemas) == {item.relative_path for item in items}
            if reverse_schema_order:
                identity = financial_audit._FlowSourceIdentity(
                    evidence=identity.evidence,
                    schemas=dict(reversed(list(identity.schemas.items()))),
                    untokenizable=identity.untokenizable,
                )
            query = financial_publication._snapshot_b1_group_union(
                dataset="cashflow",
                complete=items,
                source_identity=identity,
            )
            connection.execute("CREATE TEMP TABLE publisher_raw AS " + query)
            profile_reads = _profiled_parquet_reads(profile_path)
            columns = [
                cast(str, row[0])
                for row in connection.execute(
                    "DESCRIBE SELECT * FROM publisher_raw"
                ).fetchall()
            ]
            rows = connection.execute(
                "SELECT * FROM publisher_raw ORDER BY ALL"
            ).fetchall()
            return columns, rows, profile_reads
        finally:
            connection.close()

    first_evidence, columns, rows, schema_signature_count, first_reads = materialize(
        complete, profile_path=tmp_path / "audit-b1-first.json"
    )
    (
        first_snapshot_columns,
        first_snapshot_rows,
        first_snapshot_reads,
    ) = publisher_projection(
        complete, profile_path=tmp_path / "publisher-b1-first.json"
    )
    for item in complete:
        pl.read_parquet(item.parquet_path).reverse().write_parquet(item.parquet_path)
    (
        second_evidence,
        second_columns,
        second_rows,
        second_signature_count,
        second_reads,
    ) = materialize(
        list(reversed(complete)),
        profile_path=tmp_path / "audit-b1-second.json",
        reverse_schema_order=True,
    )
    (
        second_snapshot_columns,
        second_snapshot_rows,
        second_snapshot_reads,
    ) = publisher_projection(
        list(reversed(complete)),
        profile_path=tmp_path / "publisher-b1-second.json",
        reverse_schema_order=True,
    )
    assert first_evidence == second_evidence
    assert columns == second_columns == [
        "_flow_dataset",
        "ts_code",
        "ann_date",
        "f_ann_date",
        "end_date",
        "report_type",
        "comp_type",
        "update_flag",
        "_request_id",
        "_source_file",
        "_flow_source_type_n_cashflow_act",
        "_flow_raw_n_cashflow_act",
        "_flow_projected_n_cashflow_act",
    ]
    assert rows == second_rows
    assert schema_signature_count == second_signature_count == 3
    assert all(name in {"READ_PARQUET", "PARQUET_SCAN"} for name, _ in first_reads)
    assert all(name in {"READ_PARQUET", "PARQUET_SCAN"} for name, _ in second_reads)
    assert len(first_reads) == len(second_reads) == 3
    assert sorted(total for _, total in first_reads) == [1, 1, 2]
    assert sorted(total for _, total in second_reads) == [1, 1, 2]
    assert sum(total for _, total in first_reads) == sum(total for _, total in second_reads) == len(
        complete
    )
    assert first_snapshot_columns == second_snapshot_columns == [
        "symbol",
        "ann_date",
        "f_ann_date",
        "available_date",
        "end_date",
        "report_type",
        "comp_type",
        "update_flag",
        "n_cashflow_act",
        "source",
    ]
    assert first_snapshot_rows == second_snapshot_rows
    assert len(first_snapshot_reads) == len(second_snapshot_reads) == 3
    assert sorted(total for _, total in first_snapshot_reads) == [1, 1, 2]
    assert sorted(total for _, total in second_snapshot_reads) == [1, 1, 2]
    assert sum(total for _, total in first_snapshot_reads) == sum(
        total for _, total in second_snapshot_reads
    ) == len(complete)
    assert len(rows) == 8
    assert tuple(entry["relative_file"] for entry in first_evidence) == tuple(
        item.relative_path for item in sorted(complete, key=lambda item: item.relative_path)
    )
    observed: dict[str, list[tuple[str, object, object]]] = {}
    for source, source_type, raw, projected in rows:
        observed.setdefault(cast(str, source), []).append(
            (cast(str, source_type), raw, projected)
        )
    assert observed[complete[0].relative_path] == [
        ("BOOLEAN", "false", 0.0),
        ("BOOLEAN", "true", 1.0),
    ]
    assert observed[complete[1].relative_path] == [
        ("BOOLEAN", "false", 0.0),
        ("BOOLEAN", "true", 1.0),
    ]
    assert observed[complete[2].relative_path][0][0] == "VARCHAR"
    assert [
        float(raw) == projected
        for _, raw, projected in observed[complete[2].relative_path]
    ] == [True, True]
    assert observed[complete[3].relative_path][0][0] == "DOUBLE"
    assert [
        float(raw) == projected
        for _, raw, projected in observed[complete[3].relative_path]
    ] == [True, True]


def test_b2_observation_relation_binds_parallel_sequences_and_uses_one_canonicalizer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    frame = pl.DataFrame(
        {
            "ts_code": pl.Series(
                "ts_code", ["000001.SZ", "000002.SZ"], dtype=pl.String
            ),
            "ann_date": pl.Series(
                "ann_date", ["20240420", "20240421"], dtype=pl.String
            ),
            "f_ann_date": pl.Series(
                "f_ann_date", ["20240420", "20240421"], dtype=pl.String
            ),
            "end_date": pl.Series(
                "end_date", ["20230331", "20230630"], dtype=pl.String
            ),
            "report_type": pl.Series("report_type", ["1", "1"], dtype=pl.String),
            "comp_type": pl.Series("comp_type", ["1", "1"], dtype=pl.String),
            "update_flag": pl.Series("update_flag", ["0", "0"], dtype=pl.String),
            "n_income": pl.Series("n_income", [10.0, 20.0], dtype=pl.Float64),
            "n_income_attr_p": pl.Series(
                "n_income_attr_p", ["11.00", "21.00"], dtype=pl.String
            ),
        }
    )
    item = _real_complete(tmp_path, "income", 1, frame)
    connection = duckdb.connect(":memory:")
    try:
        identity = financial_audit._flow_source_identity(
            connection=connection, complete=[item]
        )
        table = financial_audit._materialize_safe_projection(
            connection=connection,
            dataset="income",
            complete=[item],
            source_identity=identity,
        )
        financial_audit._validate_projected_sources(
            connection=connection, table=table, complete=[item]
        )
        canonicalizer_calls: list[tuple[object, object, object]] = []
        original_canonicalizer = financial_audit._canonicalize_operand

        def spy_canonicalizer(
            *, source_type: object, raw: object, projected: object
        ) -> financial_audit._CanonicalOperand:
            canonicalizer_calls.append((source_type, raw, projected))
            return original_canonicalizer(
                source_type=source_type, raw=raw, projected=projected
            )

        monkeypatch.setattr(
            financial_audit, "_canonicalize_operand", spy_canonicalizer
        )
        observations = financial_audit._flow_observations(
            connection=connection, dataset="income", table=table
        )
    finally:
        connection.close()

    assert type(observations) is tuple
    assert len(observations) == 2
    expected = {
        "000001.SZ": (("DOUBLE", "10.0", 10.0, "10"), ("VARCHAR", "11.00", 11.0, "11")),
        "000002.SZ": (("DOUBLE", "20.0", 20.0, "20"), ("VARCHAR", "21.00", 21.0, "21")),
    }
    for observation in observations:
        assert len(observation.source_types) == len(
            observation.raw_values
        ) == len(observation.projected_values) == len(
            observation.canonical_values
        ) == 2
        assert tuple(
            zip(
                observation.source_types,
                observation.raw_values,
                observation.projected_values,
                (operand.token for operand in observation.canonical_values),
            )
        ) == expected[observation.symbol]
    assert sorted(canonicalizer_calls, key=lambda call: (str(call[0]), str(call[1]))) == [
        ("DOUBLE", "10.0", 10.0),
        ("DOUBLE", "20.0", 20.0),
        ("VARCHAR", "11.00", 11.0),
        ("VARCHAR", "21.00", 21.0),
    ]


@pytest.mark.parametrize("logical_type", ["STRUCT", "BLOB"])
def test_required_nested_or_binary_real_source_blocks_before_economic_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    logical_type: str,
) -> None:
    if logical_type == "STRUCT":
        value = pl.Series(
            "total_assets",
            [{"value": 120.0}],
            dtype=pl.Struct({"value": pl.Float64}),
        )
    else:
        value = pl.Series("total_assets", [b"120.0"], dtype=pl.Binary)
    balance = _frame("balancesheet").with_columns(value)
    fixture = _build_root(tmp_path, balancesheet_frame=balance)
    calls: list[str] = []

    def fail(name: str):
        def _fail(*_args: object, **_kwargs: object) -> object:
            calls.append(name)
            raise AssertionError(name)

        return _fail

    for name in (
        "_flow_semantics",
        "_flow_observations",
        "_flow_bucket",
        "_canonicalize_operand",
        "_classify_flow_operands",
        "_float64_cent_resolution",
        "_economic_decimal",
        "_flow_mismatch",
        "_select_latest_observation",
        "_previous_end_date",
    ):
        monkeypatch.setattr(financial_audit, name, fail(name))

    result = audit_tushare_financials(**_audit_kwargs(fixture), verify_bytes=True)
    balancesheet_entry = next(
        entry
        for entry in result["flow_semantics"]["source_type_evidence"]
        if entry["dataset"] == "balancesheet"
    )
    observed_type = next(
        column["logical_type"]
        for column in balancesheet_entry["schema"]
        if column["name"] == "total_assets"
    )
    assert observed_type.startswith(logical_type)
    assert result["status"] == "BLOCKED"
    assert result["publication_allowed"] is False
    assert result["flow_semantics"]["status"] == "NOT_EVALUATED"
    assert result["flow_semantics"]["buckets"] == []
    assert result["blocking_issues"] == [
        {"code": "BALANCESHEET_FLOW_SOURCE_TYPE_UNTOKENIZABLE", "count": 1}
    ]
    assert calls == []


def test_extra_nested_real_source_is_provenance_only_and_does_not_block_safe_projection(
    tmp_path: Path,
) -> None:
    extra = pl.Series(
        "extra_nested",
        [{"value": 120.0}],
        dtype=pl.Struct({"value": pl.Float64}),
    )
    fixture = _build_root(
        tmp_path,
        balancesheet_frame=_frame("balancesheet").with_columns(extra),
    )
    result = audit_tushare_financials(**_audit_kwargs(fixture), verify_bytes=True)
    balancesheet_entry = next(
        entry
        for entry in result["flow_semantics"]["source_type_evidence"]
        if entry["dataset"] == "balancesheet"
    )
    assert any(column["name"] == "extra_nested" for column in balancesheet_entry["schema"])
    assert result["status"] == "READY"
    assert result["blocking_issues"] == []
    assert result["flow_semantics"]["status"] == "INSUFFICIENT"


@pytest.mark.parametrize(
    "case", ["required_struct", "required_binary", "invalid_numeric", "audit_invalid"]
)
def test_public_publisher_real_chain_rejects_each_invalid_boundary_before_mkdir(
    tmp_path: Path, case: str
) -> None:
    if case in {"required_struct", "required_binary"}:
        value = (
            pl.Series(
                "total_assets",
                [{"value": 120.0}],
                dtype=pl.Struct({"value": pl.Float64}),
            )
            if case == "required_struct"
            else pl.Series("total_assets", [b"120.0"], dtype=pl.Binary)
        )
        balance = _frame("balancesheet").with_columns(value)
        fixture = _build_root(tmp_path, balancesheet_frame=balance)
    elif case == "invalid_numeric":
        fixture = _build_root(
            tmp_path,
            income_frame=_frame("income", n_income="not-a-number"),
        )
    else:
        fixture = _build_root(
            tmp_path,
            income_frame=_frame("income", report_type="not-a-dimension"),
        )
    with pytest.raises(TushareFinancialPublishError):
        publish_tushare_financial_snapshot(
            data_root=fixture.root,
            plan_report_path=fixture.plan_report,
            catalog_path=fixture.catalog,
        )
    assert not (fixture.root / "clean" / "tushare_financials").exists()


def test_flow_key_orders_report_type_before_comp_type_for_distinct_selection() -> None:
    first = SimpleNamespace(
        symbol="000001.SZ",
        end_date=dt.date(2023, 12, 31),
        report_type="2",
        comp_type="1",
    )
    second = SimpleNamespace(
        symbol="000001.SZ",
        end_date=dt.date(2023, 12, 31),
        report_type="1",
        comp_type="2",
    )
    assert financial_audit._flow_key(first) == (
        "000001.SZ",
        dt.date(2023, 12, 31),
        "2",
        "1",
    )
    assert sorted((first, second), key=financial_audit._flow_key) == [second, first]


def test_latest_conflict_uses_canonical_tokens_for_null_bool_and_nonfinite() -> None:
    end_date = dt.date(2023, 3, 31)
    available = dt.date(2024, 4, 20)
    select_latest = financial_audit._select_latest_observation
    missing = _cashflow_observation(
        None,
        end_date=end_date,
        available_date=available,
        token="MISSING",
        category="missing",
        projected=None,
    )
    zero = _cashflow_observation(0, end_date=end_date, available_date=available)
    assert select_latest([missing, missing])[1] is False
    assert select_latest([missing, zero])[1] is True

    true = _cashflow_observation(
        True,
        end_date=end_date,
        available_date=available,
        token="INVALID_BOOLEAN:true",
        category="invalid",
        projected=None,
    )
    false = _cashflow_observation(
        False,
        end_date=end_date,
        available_date=available,
        token="INVALID_BOOLEAN:false",
        category="invalid",
        projected=None,
    )
    assert select_latest([true, true])[1] is False
    assert select_latest([true, false])[1] is True

    nan = _cashflow_observation(
        "NaN",
        end_date=end_date,
        available_date=available,
        token="NONFINITE:NAN",
        category="nonfinite",
        projected=None,
    )
    inf = _cashflow_observation(
        "Inf",
        end_date=end_date,
        available_date=available,
        token="NONFINITE:+INF",
        category="nonfinite",
        projected=None,
    )
    assert select_latest([nan, nan])[1] is False
    assert select_latest([nan, inf])[1] is True


def test_numeric_tokens_and_source_evidence_file_order_are_invariant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    canonicalize = financial_audit._canonicalize_operand
    tokens = {
        canonicalize(source_type=source_type, raw=raw, projected=projected).token
        for source_type, raw, projected in (
            ("INTEGER", "1", 1.0),
            ("DOUBLE", "1.0", 1.0),
            ("DECIMAL(18,2)", "1.00", 1.0),
            ("VARCHAR", "1e0", 1.0),
            ("DOUBLE", "-0", -0.0),
        )
    }
    assert tokens == {"0", "1"}
    assert canonicalize(source_type="VARCHAR", raw="+0001.0", projected=1.0).token == "1"
    assert canonicalize(source_type="VARCHAR", raw=".5e1", projected=5.0).token == "5"

    items = [
        _stub_complete(tmp_path, "income", 2),
        _stub_complete(tmp_path, "cashflow", 1),
    ]

    def fake_schema(*, connection: object, item: financial_audit._CompleteRequest):
        fields = (
            ("n_cashflow_act",)
            if item.dataset == "cashflow"
            else ("n_income", "n_income_attr_p")
        )
        return financial_audit._SourceSchema(
            relative_path=item.relative_path,
            schema=tuple((field, "DOUBLE") for field in fields),
            economic_types={field: "DOUBLE" for field in fields},
        )

    monkeypatch.setattr(financial_audit, "_source_schema_for_file", fake_schema)
    first = financial_audit._flow_source_identity(connection=object(), complete=items)
    second = financial_audit._flow_source_identity(
        connection=object(), complete=list(reversed(items))
    )
    assert first.evidence == second.evidence
    assert financial_audit._flow_identity_fields(first)[
        "flow_source_type_evidence_sha256"
    ] == financial_audit._flow_identity_fields(second)[
        "flow_source_type_evidence_sha256"
    ]

    def missing_required_schema(
        *, connection: object, item: financial_audit._CompleteRequest
    ):
        fields = ("n_income",) if item.dataset == "income" else ("n_cashflow_act",)
        return financial_audit._SourceSchema(
            relative_path=item.relative_path,
            schema=tuple((field, "DOUBLE") for field in fields),
            economic_types={field: "DOUBLE" for field in fields},
        )

    monkeypatch.setattr(
        financial_audit, "_source_schema_for_file", missing_required_schema
    )
    with pytest.raises(KeyError):
        financial_audit._flow_source_identity(connection=object(), complete=items)
