from __future__ import annotations

import datetime as dt
import hashlib
import inspect
import json
from dataclasses import fields
from pathlib import Path
from typing import Any

import polars as pl
import pytest

import quant.data.publish_tushare_financials as financial_publication
from quant.data.publish_tushare_financials import (
    TushareFinancialPublishError,
    TushareFinancialSnapshot,
    publish_tushare_financial_snapshot,
    verify_tushare_financial_snapshot,
)


def test_publisher_requires_explicit_plan_and_catalog_paths() -> None:
    signature = inspect.signature(publish_tushare_financial_snapshot)
    assert tuple(signature.parameters) == (
        "data_root",
        "plan_report_path",
        "catalog_path",
        "threads",
    )
    assert signature.parameters["plan_report_path"].default is inspect.Parameter.empty
    assert signature.parameters["catalog_path"].default is inspect.Parameter.empty


def test_invalid_plan_fails_before_snapshot_directory_creation(tmp_path: Path) -> None:
    root = tmp_path / "data"
    root.mkdir()
    with pytest.raises(
        TushareFinancialPublishError,
        match="TUSHARE_FINANCIAL_PUBLISH_INVALID",
    ) as error:
        publish_tushare_financial_snapshot(
            data_root=root,
            plan_report_path=tmp_path / "missing-plan.json",
            catalog_path=tmp_path / "missing-catalog.toml",
        )
    assert error.value.__cause__ is None
    assert error.value.__context__ is None
    assert not (root / "clean" / "tushare_financials").exists()


def _valid_flow() -> dict[str, object]:
    buckets: list[dict[str, object]] = []
    for dataset, field in financial_publication._FLOW_FIELDS:
        for fiscal_bucket in financial_publication._FLOW_BUCKETS:
            buckets.append(
                {
                    "dataset": dataset,
                    "field": field,
                    "fiscal_bucket": fiscal_bucket,
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
    return {
        "status": "PASS",
        "flow_decimal_absolute_tolerance": "0.01",
        "minimum_current_symbols": 100,
        "minimum_fiscal_years": 3,
        "minimum_comparable_observations": 100,
        "source_type_evidence": [],
        "flow_source_type_evidence_sha256": financial_publication._flow_source_evidence_sha256(
            []
        ),
        "normalized_projection_contract": financial_publication._FLOW_NORMALIZED_PROJECTION_CONTRACT,
        "token_algorithm": "float64-decimal-str-canonical-v1",
        "token_algorithm_version": "1",
        "buckets": buckets,
    }


def test_snapshot_dataclass_has_only_the_additive_audit_sha_field() -> None:
    assert tuple(item.name for item in fields(TushareFinancialSnapshot)) == (
        "root",
        "snapshot_id",
        "manifest_sha256",
        "audit_sha256",
        "dataset_rows",
        "reused",
    )


def test_publisher_flow_validator_rejects_order_identity_funnel_and_status_forgery() -> None:
    original = _valid_flow()
    financial_publication._validate_flow_semantics(original)
    mutations = []

    reordered = json.loads(json.dumps(original))
    reordered["buckets"].reverse()
    mutations.append(reordered)

    duplicated = json.loads(json.dumps(original))
    duplicated["buckets"][1] = dict(duplicated["buckets"][0])
    mutations.append(duplicated)

    missing_key = json.loads(json.dumps(original))
    missing_key.pop("token_algorithm")
    mutations.append(missing_key)

    threshold_drift = json.loads(json.dumps(original))
    threshold_drift["minimum_current_symbols"] = 101
    mutations.append(threshold_drift)

    token_drift = json.loads(json.dumps(original))
    token_drift["token_algorithm"] = "FLOAT64-DECIMAL-STR-CANONICAL-V1"
    mutations.append(token_drift)

    hash_forgery = json.loads(json.dumps(original))
    hash_forgery["flow_source_type_evidence_sha256"] = "0" * 64
    mutations.append(hash_forgery)

    funnel_drift = json.loads(json.dumps(original))
    funnel_drift["buckets"][0]["current_type1_candidates"] = 101
    mutations.append(funnel_drift)

    bool_count = json.loads(json.dumps(original))
    bool_count["buckets"][0]["comparable_observations"] = True
    mutations.append(bool_count)

    derived_status = json.loads(json.dumps(original))
    derived_status["buckets"][0]["mismatch_count"] = 1
    mutations.append(derived_status)

    symbol_bound = json.loads(json.dumps(original))
    symbol_bound["buckets"][0]["distinct_symbols"] = 2
    symbol_bound["buckets"][0]["current_type1_candidates"] = 1
    mutations.append(symbol_bound)

    fiscal_bound = json.loads(json.dumps(original))
    fiscal_bound["buckets"][0]["fiscal_years"] = 2
    fiscal_bound["buckets"][0]["comparable_observations"] = 1
    mutations.append(fiscal_bound)

    zero_observation_bound = json.loads(json.dumps(original))
    zero_observation_bound["buckets"][0]["fiscal_years"] = 1
    zero_observation_bound["buckets"][0]["comparable_observations"] = 0
    mutations.append(zero_observation_bound)

    for candidate in mutations:
        with pytest.raises(ValueError):
            financial_publication._validate_flow_semantics(candidate)


def test_publisher_rejects_bad_empty_flow_sha_and_source_type_aliases() -> None:
    empty = _valid_flow()
    empty["status"] = "NOT_EVALUATED"
    empty["buckets"] = []
    empty["flow_source_type_evidence_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        financial_publication._validate_flow_semantics(empty)

    request_id = "a" * 64
    good_entry = {
        "dataset": "cashflow",
        "request_id": request_id,
        "relative_file": f"raw/tushare/cashflow/request={request_id}/data.parquet",
        "schema": [
            {"name": "ts_code", "logical_type": "VARCHAR"},
            {"name": "ann_date", "logical_type": "VARCHAR"},
            {"name": "f_ann_date", "logical_type": "VARCHAR"},
            {"name": "end_date", "logical_type": "VARCHAR"},
            {"name": "report_type", "logical_type": "VARCHAR"},
            {"name": "comp_type", "logical_type": "VARCHAR"},
            {"name": "update_flag", "logical_type": "VARCHAR"},
            {"name": "n_cashflow_act", "logical_type": "DOUBLE"},
        ],
        "required_economic_types": {"n_cashflow_act": "DOUBLE"},
    }
    for bad_entry in (
        {**good_entry, "relative_file": "raw/tushare/cashflow/alias/data.parquet"},
        {
            **good_entry,
            "schema": [
                *good_entry["schema"][:-1],
                {"name": "n_cashflow_act", "logical_type": "double"},
            ],
        },
        {
            **good_entry,
            "required_economic_types": {"n_cashflow_act": "VARCHAR"},
        },
    ):
        candidate = _valid_flow()
        candidate["source_type_evidence"] = [bad_entry]
        candidate["flow_source_type_evidence_sha256"] = (
            financial_publication._flow_source_evidence_sha256([bad_entry])
        )
        with pytest.raises(ValueError):
            financial_publication._validate_flow_semantics(candidate)

    extra_types = json.loads(json.dumps(good_entry))
    extra_types["schema"].extend(
        [
            {"name": "extra_nested", "logical_type": "STRUCT"},
            {"name": "extra_binary", "logical_type": "BLOB"},
        ]
    )
    candidate = _valid_flow()
    candidate["source_type_evidence"] = [extra_types]
    candidate["flow_source_type_evidence_sha256"] = (
        financial_publication._flow_source_evidence_sha256([extra_types])
    )
    financial_publication._validate_flow_semantics(candidate)

    for logical_type in ("STRUCT", "BLOB"):
        required_nested = json.loads(json.dumps(good_entry))
        required_nested["schema"] = [
            *required_nested["schema"][:-1],
            {"name": "n_cashflow_act", "logical_type": logical_type},
        ]
        required_nested["required_economic_types"] = {
            "n_cashflow_act": logical_type
        }
        candidate = _valid_flow()
        candidate["source_type_evidence"] = [required_nested]
        candidate["flow_source_type_evidence_sha256"] = (
            financial_publication._flow_source_evidence_sha256([required_nested])
        )
        with pytest.raises(ValueError):
            financial_publication._validate_flow_semantics(candidate)

    duplicate = _valid_flow()
    duplicate["source_type_evidence"] = [good_entry, good_entry]
    duplicate["flow_source_type_evidence_sha256"] = (
        financial_publication._flow_source_evidence_sha256([good_entry, good_entry])
    )
    with pytest.raises(ValueError):
        financial_publication._validate_flow_semantics(duplicate)


def _quality_domain_fixture(**overrides: object) -> dict[str, Any]:
    value: dict[str, Any] = {
        "raw_rows": 10,
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
        "column_set_count": 1,
        "column_set_sha256s": ["0" * 64],
        "required_numeric_union_types": {},
        "report_type_counts": [],
        "comp_type_counts": [],
        "report_type_comp_type_counts": [],
        "eligible_rows": 10,
        "quarantined_rows": 0,
    }
    value.update(overrides)
    return value


def test_publisher_quality_domain_allows_only_flow_numeric_quarantine() -> None:
    financial_publication._validate_quality_domain(
        dataset="cashflow",
        quality=_quality_domain_fixture(
            required_numeric_parse_rows=2,
            required_numeric_nonfinite_rows=1,
            eligible_rows=7,
            quarantined_rows=3,
        ),
    )
    financial_publication._validate_quality_domain(
        dataset="income",
        quality=_quality_domain_fixture(
            required_numeric_parse_rows=1,
            eligible_rows=9,
            quarantined_rows=1,
        ),
    )
    financial_publication._validate_quality_domain(
        dataset="balancesheet", quality=_quality_domain_fixture()
    )
    financial_publication._validate_quality_domain(
        dataset="fina_indicator", quality=_quality_domain_fixture()
    )


def test_publisher_quality_domain_rejects_bool_nonconservation_and_balance_numeric_drift() -> None:
    mutations = (
        _quality_domain_fixture(
            required_numeric_parse_rows=True,
            eligible_rows=9,
            quarantined_rows=1,
        ),
        _quality_domain_fixture(
            required_numeric_parse_rows=2,
            eligible_rows=9,
            quarantined_rows=0,
        ),
        _quality_domain_fixture(
            required_numeric_parse_rows=1,
            eligible_rows=9,
            quarantined_rows=2,
        ),
    )
    for quality in mutations:
        with pytest.raises(ValueError):
            financial_publication._validate_quality_domain(
                dataset="cashflow", quality=quality
            )

    for dataset in ("balancesheet", "fina_indicator"):
        with pytest.raises(ValueError):
            financial_publication._validate_quality_domain(
                dataset=dataset,
                quality=_quality_domain_fixture(
                    required_numeric_nonfinite_rows=1,
                    eligible_rows=9,
                    quarantined_rows=1,
                ),
            )


def _valid_audit_payload() -> dict[str, Any]:
    counts = {dataset: 1 for dataset in financial_publication._DATASETS}
    inventory_files = [
        {
            "relative_path": "clean/instrument/market=SH/data.parquet",
            "size_bytes": 1,
            "sha256": "a" * 64,
        }
    ]
    inventory = {
        "schema_version": financial_publication.INVENTORY_CLOSURE_SCHEMA,
        "file_set_sha256": financial_publication._sha(
            financial_publication._canonical(
                [financial_publication.INVENTORY_CLOSURE_SCHEMA, inventory_files]
            )
        ),
        "logical_frame_sha256": "b" * 64,
        "stock_count": 1,
        "files": inventory_files,
    }
    plan = {
        "schema_version": financial_publication.PLAN_CLOSURE_SCHEMA,
        "provenance_model": financial_publication.PROVENANCE_MODEL,
        "provenance_limitation": financial_publication.PROVENANCE_LIMITATION,
        "plan_report_sha256": "c" * 64,
        "plan_schema_version": financial_publication.PLAN_SCHEMA,
        "planned_as_of": "2024-01-01",
        "catalog_version": "test-v1",
        "catalog_sha256": "d" * 64,
        "permission_report_sha256": "e" * 64,
        "instrument_inventory": inventory,
        "request_counts": counts,
        "request_set_sha256": "f" * 64,
    }
    reports: dict[str, dict[str, Any]] = {}
    evidence: list[dict[str, Any]] = []
    for ordinal, dataset in enumerate(financial_publication._DATASETS, start=1):
        quality = _quality_domain_fixture(raw_rows=1, eligible_rows=1)
        if dataset in financial_publication._STATEMENTS:
            quality.update(
                {
                    "report_type_counts": [{"value": "1", "rows": 1}],
                    "comp_type_counts": [{"value": "1", "rows": 1}],
                    "report_type_comp_type_counts": [
                        {"report_type": "1", "comp_type": "1", "rows": 1}
                    ],
                }
            )
        reports[dataset] = {
            "request_count": 1,
            "status_counts": {"COMPLETE": 1},
            "complete_rows": 1,
            "quality": quality,
        }
        request_id = f"{ordinal:064x}"
        schema_names = (
            (
                "ts_code",
                "ann_date",
                "f_ann_date",
                "end_date",
                "report_type",
                "comp_type",
                "update_flag",
            )
            if dataset in financial_publication._STATEMENTS
            else ("ts_code", "ann_date", "end_date")
        ) + financial_publication._ECONOMIC_COLUMNS[dataset]
        quality["column_set_sha256s"] = [
            hashlib.sha256(
                json.dumps(list(schema_names), separators=(",", ":")).encode()
            ).hexdigest()
        ]
        quality["required_numeric_union_types"] = {
            field: "VARCHAR"
            for field in financial_publication._ECONOMIC_COLUMNS[dataset]
        }
        evidence.append(
            {
                "dataset": dataset,
                "request_id": request_id,
                "relative_file": f"raw/tushare/{dataset}/request={request_id}/data.parquet",
                "schema": [
                    {"name": name, "logical_type": "VARCHAR"}
                    for name in schema_names
                ],
                "required_economic_types": {
                    field: "VARCHAR"
                    for field in financial_publication._ECONOMIC_COLUMNS[dataset]
                },
            }
        )
    flow = _valid_flow()
    flow["source_type_evidence"] = evidence
    flow["flow_source_type_evidence_sha256"] = (
        financial_publication._flow_source_evidence_sha256(evidence)
    )
    return {
        "schema_version": financial_publication._AUDIT_SCHEMA_VERSION,
        "status": "READY",
        "verify_bytes": True,
        "plan_closure": plan,
        "active_lease_count": 0,
        "raw_closure": {
            "schema_version": "tushare-financial-raw-closure-v1",
            "complete_request_count": 4,
            "catalog_sha256s": ["d" * 64],
            "request_set_sha256": "1" * 64,
        },
        "datasets": reports,
        "blocking_issues": [],
        "flow_semantics": flow,
        "publication_allowed": True,
    }


def _write_valid_snapshot_for_manifest_tests(
    tmp_path: Path,
) -> tuple[Path, str, Path, dict[str, Any]]:
    data_root = tmp_path / "data"
    snapshot_id = financial_publication._source_identity(_valid_audit_payload())
    snapshot_root = data_root / "clean" / "tushare_financials" / "snapshots" / snapshot_id
    snapshot_root.mkdir(parents=True)
    audit = _valid_audit_payload()
    audit_raw = financial_publication._canonical(audit)
    (snapshot_root / "audit.json").write_bytes(audit_raw)
    entries = [
        financial_publication._file_entry(
            snapshot_root / "audit.json", snapshot_root, rows=None
        )
    ]
    for dataset in financial_publication._DATASETS:
        values: dict[str, object] = {
            "symbol": ["000001.SZ"],
            "ann_date": [dt.date(2024, 4, 20)],
        }
        if dataset in financial_publication._STATEMENTS:
            values["f_ann_date"] = [dt.date(2024, 4, 22)]
        values.update(
            {
                "available_date": [dt.date(2024, 4, 22)],
                "end_date": [dt.date(2023, 12, 31)],
            }
        )
        if dataset in financial_publication._STATEMENTS:
            values.update(
                {
                    "report_type": ["1"],
                    "comp_type": ["1"],
                    "update_flag": ["0"],
                }
            )
        values.update(
            {
                field: [1.0]
                for field in financial_publication._ECONOMIC_COLUMNS[dataset]
            }
        )
        values["source"] = ["tushare"]
        path = snapshot_root / f"dataset={dataset}" / "year=2023.parquet"
        path.parent.mkdir()
        pl.DataFrame(values).write_parquet(path)
        entries.append(financial_publication._file_entry(path, snapshot_root, rows=1))
    entries.sort(key=lambda item: item["relative_path"])
    manifest = {
        "schema_version": financial_publication._SNAPSHOT_SCHEMA,
        "projection_version": financial_publication._PROJECTION_VERSION,
        "snapshot_id": snapshot_id,
        "source_identity": snapshot_id,
        "audit_schema_version": audit["schema_version"],
        "audit_sha256": financial_publication._sha(audit_raw),
        "provenance_model": audit["plan_closure"]["provenance_model"],
        "provenance_limitation": audit["plan_closure"]["provenance_limitation"],
        "plan_report_sha256": audit["plan_closure"]["plan_report_sha256"],
        "instrument_file_set_sha256": audit["plan_closure"]["instrument_inventory"][
            "file_set_sha256"
        ],
        "instrument_logical_frame_sha256": audit["plan_closure"][
            "instrument_inventory"
        ]["logical_frame_sha256"],
        "request_set_sha256": audit["plan_closure"]["request_set_sha256"],
        "request_counts": audit["plan_closure"]["request_counts"],
        "request_count": audit["raw_closure"]["complete_request_count"],
        "dataset_rows": {dataset: 1 for dataset in financial_publication._DATASETS},
        "files": entries,
    }
    manifest_path = snapshot_root / "manifest.json"
    manifest_path.write_bytes(financial_publication._canonical(manifest))
    return data_root, snapshot_id, manifest_path, manifest


def test_publisher_quality_evidence_is_exact_and_rejects_drift_before_mkdir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "data"
    root.mkdir()
    valid = _valid_audit_payload()
    financial_publication._validate_audit(valid)
    mutations: list[dict[str, Any]] = []

    extra_key = json.loads(json.dumps(valid))
    extra_key["datasets"]["income"]["quality"]["unexpected"] = 0
    mutations.append(extra_key)

    missing_key = json.loads(json.dumps(valid))
    missing_key["datasets"]["income"]["quality"].pop("column_set_sha256s")
    mutations.append(missing_key)

    digest_case = json.loads(json.dumps(valid))
    digest_case["datasets"]["income"]["quality"]["column_set_sha256s"] = [
        "A" * 64
    ]
    mutations.append(digest_case)

    digest_duplicate = json.loads(json.dumps(valid))
    digest_duplicate["datasets"]["income"]["quality"]["column_set_count"] = 2
    digest_duplicate["datasets"]["income"]["quality"]["column_set_sha256s"] = [
        "a" * 64,
        "a" * 64,
    ]
    mutations.append(digest_duplicate)

    digest_count_bool = json.loads(json.dumps(valid))
    digest_count_bool["datasets"]["income"]["quality"]["column_set_count"] = True
    mutations.append(digest_count_bool)

    union_missing = json.loads(json.dumps(valid))
    union_missing["datasets"]["income"]["quality"][
        "required_numeric_union_types"
    ].pop("n_income_attr_p")
    mutations.append(union_missing)

    union_case = json.loads(json.dumps(valid))
    union_case["datasets"]["income"]["quality"]["required_numeric_union_types"][
        "n_income"
    ] = "varchar"
    mutations.append(union_case)

    union_order = json.loads(json.dumps(valid))
    union = union_order["datasets"]["income"]["quality"][
        "required_numeric_union_types"
    ]
    union_order["datasets"]["income"]["quality"][
        "required_numeric_union_types"
    ] = dict(reversed(list(union.items())))
    mutations.append(union_order)

    income_entries = [
        entry
        for entry in valid["flow_semantics"]["source_type_evidence"]
        if entry["dataset"] == "income"
    ]
    assert len(income_entries) == 1
    second_entry = json.loads(json.dumps(income_entries[0]))
    second_entry["schema"].append(
        {"name": "z_extra", "logical_type": "VARCHAR"}
    )
    income_quality = json.loads(
        json.dumps(valid["datasets"]["income"]["quality"])
    )
    second_digest = hashlib.sha256(
        json.dumps(
            [column["name"] for column in second_entry["schema"]],
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    first_digest = income_quality["column_set_sha256s"][0]
    income_quality["column_set_count"] = 2
    income_quality["column_set_sha256s"] = sorted([first_digest, second_digest])
    financial_publication._validate_quality_evidence(
        dataset="income",
        quality=income_quality,
        evidence=[income_entries[0], second_entry],
    )
    income_quality["column_set_sha256s"].reverse()
    with pytest.raises(ValueError):
        financial_publication._validate_quality_evidence(
            dataset="income",
            quality=income_quality,
            evidence=[income_entries[0], second_entry],
        )

    for candidate in mutations:
        with pytest.raises(ValueError):
            financial_publication._validate_audit(candidate)
        monkeypatch.setattr(
            financial_publication,
            "audit_tushare_financials",
            lambda _audit=candidate, **_kwargs: _audit,
        )
        with pytest.raises(TushareFinancialPublishError):
            publish_tushare_financial_snapshot(
                data_root=root,
                plan_report_path=tmp_path / "plan.json",
                catalog_path=tmp_path / "catalog.toml",
            )
        assert not (root / "clean" / "tushare_financials").exists()


def test_publisher_rejects_derived_flow_bounds_before_snapshot_mkdir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "data"
    root.mkdir()
    valid = _valid_audit_payload()
    candidates: list[dict[str, Any]] = []
    for field, value in (
        ("distinct_symbols", 2),
        ("fiscal_years", 2),
        ("comparable_observations", 0),
    ):
        candidate = json.loads(json.dumps(valid))
        bucket = candidate["flow_semantics"]["buckets"][0]
        if field == "distinct_symbols":
            bucket["current_type1_candidates"] = 1
        elif field == "fiscal_years":
            bucket["comparable_observations"] = 1
        else:
            bucket["fiscal_years"] = 1
        bucket[field] = value
        candidates.append(candidate)
    for candidate in candidates:
        with pytest.raises(ValueError):
            financial_publication._validate_audit(candidate)
        monkeypatch.setattr(
            financial_publication,
            "audit_tushare_financials",
            lambda _audit=candidate, **_kwargs: _audit,
        )
        with pytest.raises(TushareFinancialPublishError):
            publish_tushare_financial_snapshot(
                data_root=root,
                plan_report_path=tmp_path / "plan.json",
                catalog_path=tmp_path / "catalog.toml",
            )
        assert not (root / "clean" / "tushare_financials").exists()


def test_public_snapshot_verifier_rejects_manifest_counter_and_file_metadata_drift(
    tmp_path: Path,
) -> None:
    data_root, snapshot_id, manifest_path, baseline = (
        _write_valid_snapshot_for_manifest_tests(tmp_path)
    )
    assert verify_tushare_financial_snapshot(
        data_root=data_root, snapshot_id=snapshot_id
    ).snapshot_id == snapshot_id
    data_entry = next(
        entry for entry in baseline["files"] if entry["relative_path"] != "audit.json"
    )
    mutations: list[dict[str, Any]] = []
    audit_rows = json.loads(json.dumps(baseline))
    next(
        entry
        for entry in audit_rows["files"]
        if entry["relative_path"] == "audit.json"
    )["rows"] = 0
    mutations.append(audit_rows)
    for value in (True, -1, 3):
        candidate = json.loads(json.dumps(baseline))
        candidate["request_count"] = value
        mutations.append(candidate)
    for value in (True, -1):
        candidate = json.loads(json.dumps(baseline))
        candidate["request_counts"]["cashflow"] = value
        mutations.append(candidate)
        candidate = json.loads(json.dumps(baseline))
        candidate["dataset_rows"]["income"] = value
        mutations.append(candidate)
    for value in (True, -1):
        candidate = json.loads(json.dumps(baseline))
        candidate_entry = next(
            entry
            for entry in candidate["files"]
            if entry["relative_path"] == data_entry["relative_path"]
        )
        candidate_entry["rows"] = value
        mutations.append(candidate)
        candidate = json.loads(json.dumps(baseline))
        candidate_entry = next(
            entry
            for entry in candidate["files"]
            if entry["relative_path"] == data_entry["relative_path"]
        )
        candidate_entry["size_bytes"] = value
        mutations.append(candidate)
    for candidate in mutations:
        manifest_path.write_bytes(financial_publication._canonical(candidate))
        with pytest.raises(TushareFinancialPublishError):
            verify_tushare_financial_snapshot(
                data_root=data_root, snapshot_id=snapshot_id
            )
    manifest_path.write_bytes(financial_publication._canonical(baseline))
    assert verify_tushare_financial_snapshot(
        data_root=data_root, snapshot_id=snapshot_id
    ).snapshot_id == snapshot_id


def test_publisher_required_nested_is_blocked_but_extra_nested_is_provenance_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "data"
    root.mkdir()
    valid = _valid_audit_payload()
    extra = json.loads(json.dumps(valid))
    extra_entry = extra["flow_semantics"]["source_type_evidence"][0]
    extra_entry["schema"].append(
        {"name": "extra_nested", "logical_type": "STRUCT"}
    )
    extra_evidence = extra["flow_semantics"]["source_type_evidence"]
    extra["flow_semantics"]["flow_source_type_evidence_sha256"] = (
        financial_publication._flow_source_evidence_sha256(extra_evidence)
    )
    extra_schema_names = [
        column["name"] for column in extra_entry["schema"]
    ]
    extra["datasets"]["balancesheet"]["quality"]["column_set_sha256s"] = [
        hashlib.sha256(
            json.dumps(extra_schema_names, separators=(",", ":")).encode()
        ).hexdigest()
    ]
    financial_publication._validate_audit(extra)

    blocked_candidates: list[dict[str, Any]] = []
    for logical_type in ("STRUCT", "BLOB"):
        blocked = json.loads(json.dumps(valid))
        blocked["status"] = "BLOCKED"
        blocked["publication_allowed"] = False
        blocked["blocking_issues"] = [
            {"code": "BALANCESHEET_FLOW_SOURCE_TYPE_UNTOKENIZABLE", "count": 1}
        ]
        entry = blocked["flow_semantics"]["source_type_evidence"][0]
        entry["schema"] = [
            column
            if column["name"] != "total_assets"
            else {"name": "total_assets", "logical_type": logical_type}
            for column in entry["schema"]
        ]
        entry["required_economic_types"]["total_assets"] = logical_type
        blocked_quality = blocked["datasets"]["balancesheet"]["quality"]
        blocked_quality["column_set_sha256s"] = [
            hashlib.sha256(
                json.dumps(
                    [column["name"] for column in entry["schema"]],
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
        ]
        blocked_quality["required_numeric_union_types"]["total_assets"] = logical_type
        evidence = blocked["flow_semantics"]["source_type_evidence"]
        blocked["flow_semantics"]["status"] = "NOT_EVALUATED"
        blocked["flow_semantics"]["buckets"] = []
        blocked["flow_semantics"]["flow_source_type_evidence_sha256"] = (
            financial_publication._flow_source_evidence_sha256(evidence)
        )
        blocked_candidates.append(blocked)

    for candidate in blocked_candidates:
        with pytest.raises(ValueError):
            financial_publication._validate_audit(candidate)
        monkeypatch.setattr(
            financial_publication,
            "audit_tushare_financials",
            lambda _audit=candidate, **_kwargs: _audit,
        )
        with pytest.raises(TushareFinancialPublishError):
            publish_tushare_financial_snapshot(
                data_root=root,
                plan_report_path=tmp_path / "plan.json",
                catalog_path=tmp_path / "catalog.toml",
            )
        assert not (root / "clean" / "tushare_financials").exists()


def test_publisher_rejects_bool_and_negative_audit_counters_before_snapshot_mkdir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "data"
    root.mkdir()
    valid = _valid_audit_payload()
    financial_publication._validate_audit(valid)

    mutations: list[dict[str, Any]] = []
    active_lease = json.loads(json.dumps(valid))
    active_lease["active_lease_count"] = False
    mutations.append(active_lease)
    request_count = json.loads(json.dumps(valid))
    request_count["datasets"]["cashflow"]["request_count"] = True
    mutations.append(request_count)
    status_count = json.loads(json.dumps(valid))
    status_count["datasets"]["income"]["status_counts"]["COMPLETE"] = True
    mutations.append(status_count)
    complete_rows = json.loads(json.dumps(valid))
    complete_rows["datasets"]["income"]["complete_rows"] = True
    mutations.append(complete_rows)
    row_conservation = json.loads(json.dumps(valid))
    row_conservation["datasets"]["income"]["complete_rows"] = 2
    mutations.append(row_conservation)
    quality_counter = json.loads(json.dumps(valid))
    quality_counter["datasets"]["balancesheet"]["quality"]["raw_rows"] = True
    mutations.append(quality_counter)
    negative_counter = json.loads(json.dumps(valid))
    negative_counter["datasets"]["balancesheet"]["quality"]["raw_rows"] = -1
    mutations.append(negative_counter)

    for candidate in mutations:
        with pytest.raises(ValueError):
            financial_publication._validate_audit(candidate)
        monkeypatch.setattr(
            financial_publication,
            "audit_tushare_financials",
            lambda _audit=candidate, **_kwargs: _audit,
        )
        with pytest.raises(TushareFinancialPublishError):
            publish_tushare_financial_snapshot(
                data_root=root,
                plan_report_path=tmp_path / "plan.json",
                catalog_path=tmp_path / "catalog.toml",
            )
    assert not (root / "clean" / "tushare_financials").exists()
