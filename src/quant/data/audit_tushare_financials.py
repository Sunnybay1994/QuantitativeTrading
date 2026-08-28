"""Read-only ledger and raw quality audit for Tushare financial statements."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import re
import sqlite3
import stat
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, cast

import duckdb
import polars as pl

import quant.data.tushare_bulk_ingest as _bulk_ingest
from quant.data.tushare_bulk import (
    PLAN_SCHEMA,
    Catalog,
    DatasetSpec,
    build_request_plan,
    load_catalog,
)
from quant.settings import resolve_data_root

SCHEMA_VERSION = "tushare-financial-raw-audit-v4"
_RAW_CLOSURE_SCHEMA = "tushare-financial-raw-closure-v1"
PLAN_CLOSURE_SCHEMA = "tushare-financial-plan-closure-v1"
INVENTORY_CLOSURE_SCHEMA = "tushare-financial-current-inventory-v1"
PROVENANCE_MODEL = "RECONSTRUCTED_CURRENT_INVENTORY_V1"
PROVENANCE_LIMITATION = (
    "The source plan stores inventory counts, not the planner-time membership bytes or "
    "request-set digest; this closure reconstructs the exact request set from the current "
    "canonical clean instrument inventory and does not prove planner-time member identity."
)
_DATASETS = ("balancesheet", "cashflow", "fina_indicator", "income")
_STATEMENTS = frozenset({"balancesheet", "cashflow", "income"})
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_SYMBOL = re.compile(r"^[0-9]{6}\.(SH|SZ)$")
_DATE = re.compile(r"^[0-9]{8}$")
_DIMENSION_CODE = re.compile(r"^[0-9]+$")
_STRUCTURAL_COLUMNS: dict[str, frozenset[str]] = {
    "balancesheet": frozenset(
        {
            "ts_code",
            "ann_date",
            "f_ann_date",
            "end_date",
            "report_type",
            "comp_type",
            "update_flag",
            "total_assets",
            "total_hldr_eqy_exc_min_int",
        }
    ),
    "cashflow": frozenset(
        {
            "ts_code",
            "ann_date",
            "f_ann_date",
            "end_date",
            "report_type",
            "comp_type",
            "update_flag",
            "n_cashflow_act",
        }
    ),
    "fina_indicator": frozenset({"ts_code", "ann_date", "end_date"}),
    "income": frozenset(
        {
            "ts_code",
            "ann_date",
            "f_ann_date",
            "end_date",
            "report_type",
            "comp_type",
            "update_flag",
            "n_income",
            "n_income_attr_p",
        }
    ),
}
_NUMERIC_COLUMNS: dict[str, tuple[str, ...]] = {
    "balancesheet": ("total_assets", "total_hldr_eqy_exc_min_int"),
    "cashflow": ("n_cashflow_act",),
    "fina_indicator": (),
    "income": ("n_income", "n_income_attr_p"),
}

_FLOW_BUCKETS = ("Q1", "Q2", "Q3", "FY")
_FLOW_FIELDS: tuple[tuple[str, str], ...] = (
    ("cashflow", "n_cashflow_act"),
    ("income", "n_income"),
    ("income", "n_income_attr_p"),
)
_FLOW_BUCKET_MONTHS = {3: "Q1", 6: "Q2", 9: "Q3", 12: "FY"}
_FLOW_DECIMAL_ABSOLUTE_TOLERANCE = Decimal("0.01")
_FLOW_DECIMAL_ABSOLUTE_TOLERANCE_TEXT = "0.01"
_FLOW_MINIMUM_CURRENT_SYMBOLS = 100
_FLOW_MINIMUM_FISCAL_YEARS = 3
_FLOW_MINIMUM_COMPARABLE_OBSERVATIONS = 100
_FLOW_SOURCE_TYPE_EVIDENCE_VERSION = "tushare-financial-flow-source-type-evidence-v1"
_FLOW_NORMALIZED_PROJECTION_VERSION = "tushare-financial-flow-normalized-projection-v1"
_FLOW_TOKEN_ALGORITHM = "float64-decimal-str-canonical-v1"
_FLOW_TOKEN_ALGORITHM_VERSION = "1"
_FLOW_EARLY_EMPTY_SOURCE_EVIDENCE_SHA256 = (
    "793cd498f4dbca6b28661417f49606323248da0cdf8e838575df9f7ef4d0d5db"
)
_FLOW_NORMALIZED_PROJECTION_CONTRACT = {
    "version": _FLOW_NORMALIZED_PROJECTION_VERSION,
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
_VARCHAR_FINITE = re.compile(
    r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?"
)
_VARCHAR_NONFINITE = re.compile(r"[+-]?(?:nan|inf|infinity)", re.IGNORECASE)
_NUMERIC_LOGICAL_TYPE = re.compile(
    r"^(?:U?TINYINT|U?SMALLINT|U?INTEGER|U?BIGINT|HUGEINT|UHUGEINT|INT|INTEGER|"
    r"FLOAT|REAL|DOUBLE|DECIMAL(?:\([^)]*\))?)$"
)
_UNTOKENIZABLE_LOGICAL_TYPE_PREFIXES = (
    "ARRAY",
    "BINARY",
    "BLOB",
    "BIT",
    "LIST",
    "MAP",
    "STRUCT",
    "UNION",
)


@dataclass(frozen=True, slots=True)
class _CompleteRequest:
    request_id: str
    dataset: str
    catalog_sha256: str
    symbol: str
    start_date: str
    end_date: str
    rows: int
    max_rows: int
    checksum_sha256: str
    metadata_sha256: str
    columns: tuple[str, ...]
    parquet_path: Path
    relative_path: str


@dataclass(frozen=True, slots=True)
class _VerifiedPlan:
    closure: Mapping[str, Any]
    expected_requests: tuple[_bulk_ingest.Request, ...]


@dataclass(frozen=True, slots=True)
class _SourceSchema:
    relative_path: str
    schema: tuple[tuple[str, str], ...]
    economic_types: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class _FlowSourceIdentity:
    evidence: tuple[dict[str, Any], ...]
    schemas: Mapping[str, _SourceSchema]
    untokenizable: tuple[tuple[str, str, str], ...]


@dataclass(frozen=True, slots=True)
class _CanonicalOperand:
    token: str
    category: str
    projected: float | None


@dataclass(frozen=True, slots=True)
class _FlowObservation:
    dataset: str
    symbol: str
    ann_date: dt.date
    f_ann_date: dt.date | None
    available_date: dt.date
    end_date: dt.date
    report_type: str
    comp_type: str
    update_flag: str
    source_file: str
    raw_values: tuple[object, ...]
    projected_values: tuple[object, ...]
    source_types: tuple[str, ...]
    canonical_values: tuple[_CanonicalOperand, ...]


_FlowKey = tuple[str, dt.date, str, str]


def audit_tushare_financials(
    *,
    data_root: Path,
    plan_report_path: Path,
    catalog_path: Path,
    threads: int = 2,
    verify_bytes: bool = False,
) -> dict[str, Any]:
    """Audit completed financial requests without publishing or mutating state."""
    try:
        return _audit(
            data_root=data_root,
            plan_report_path=plan_report_path,
            catalog_path=catalog_path,
            threads=threads,
            verify_bytes=verify_bytes,
        )
    except Exception:
        pass
    raise ValueError("TUSHARE_FINANCIAL_AUDIT_INVALID") from None


def _audit(
    *,
    data_root: Path,
    plan_report_path: Path,
    catalog_path: Path,
    threads: int,
    verify_bytes: bool,
) -> dict[str, Any]:
    if (
        not isinstance(data_root, Path)
        or not isinstance(plan_report_path, Path)
        or not isinstance(catalog_path, Path)
        or type(threads) is not int
        or not 1 <= threads <= 8
        or type(verify_bytes) is not bool
    ):
        raise ValueError
    root = data_root.resolve(strict=True)
    plan = _verify_plan(
        root=root,
        plan_report_path=plan_report_path,
        catalog_path=catalog_path,
    )
    rows, active_lease_count = _read_ledger(
        root / "run_state" / "tushare_bulk" / "state.sqlite"
    )
    if not rows:
        raise ValueError
    _verify_ledger_plan(
        rows=rows,
        expected=plan.expected_requests,
        expected_catalog_sha256=cast(str, plan.closure["catalog_sha256"]),
    )
    complete = _load_complete(root=root, rows=rows, verify_bytes=verify_bytes)
    by_dataset: dict[str, list[_CompleteRequest]] = {name: [] for name in _DATASETS}
    for item in complete:
        by_dataset[item.dataset].append(item)

    expected_counts = cast(Mapping[str, int], plan.closure["request_counts"])
    dataset_reports: dict[str, dict[str, Any]] = {}
    blocking: list[dict[str, Any]] = []
    total_incomplete = active_lease_count
    for dataset in _DATASETS:
        dataset_rows = [row for row in rows if row[1] == dataset]
        statuses = Counter(cast(str, row[2]) for row in dataset_rows)
        incomplete = sum(statuses[name] for name in ("PENDING", "RUNNING", "RETRYABLE"))
        total_incomplete += incomplete
        for ledger_status in ("FAILED", "SPLIT_REQUIRED"):
            if statuses[ledger_status]:
                blocking.append(
                    {
                        "code": f"{dataset.upper()}_LEDGER_{ledger_status}",
                        "count": statuses[ledger_status],
                    }
                )
        dataset_reports[dataset] = {
            "request_count": len(dataset_rows),
            "status_counts": dict(sorted(statuses.items())),
            "complete_rows": sum(item.rows for item in by_dataset[dataset]),
            "quality": _empty_quality_summary(),
        }

    ledger_complete = (
        active_lease_count == 0
        and len(rows) == sum(expected_counts.values())
        and len(complete) == sum(expected_counts.values())
        and all(
            len([row for row in rows if row[1] == dataset]) == expected_counts[dataset]
            and all(
                type(row[2]) is str and row[2] == "COMPLETE"
                for row in rows
                if row[1] == dataset
            )
            and len(by_dataset[dataset]) == expected_counts[dataset]
            for dataset in _DATASETS
        )
    )
    flow_prerequisites_closed = (
        verify_bytes is True
        and active_lease_count == 0
        and ledger_complete
    )
    flow = _not_evaluated_flow()
    if flow_prerequisites_closed:
        connection = duckdb.connect(":memory:")
        try:
            _configure_connection(connection, threads)
            source_identity = _flow_source_identity(
                connection=connection, complete=complete
            )
            tables: dict[str, str] = {}
            for dataset in _DATASETS:
                dataset_complete = by_dataset[dataset]
                tables[dataset] = _materialize_safe_projection(
                    connection=connection,
                    dataset=dataset,
                    complete=dataset_complete,
                    source_identity=source_identity,
                )
            for dataset in _DATASETS:
                quality = _quality_summary(
                    dataset=dataset,
                    complete=by_dataset[dataset],
                    threads=threads,
                    connection=connection,
                    source_identity=source_identity,
                    table=tables[dataset],
                )
                dataset_reports[dataset]["quality"] = quality
                numeric_blocked = dataset not in {"cashflow", "income"}
                for field, code in (
                    ("row_count_mismatch", "LEDGER_RAW_ROW_COUNT_MISMATCH"),
                    ("missing_request_rows", "RAW_REQUEST_MISSING"),
                    ("request_symbol_mismatches", "REQUEST_SYMBOL_MISMATCH"),
                    ("request_window_mismatches", "REQUEST_WINDOW_MISMATCH"),
                    ("critical_null_rows", "CRITICAL_NULL"),
                    ("invalid_symbol_rows", "SYMBOL_FORMAT_INVALID"),
                    ("invalid_ann_date_rows", "ANN_DATE_INVALID"),
                    ("invalid_f_ann_date_rows", "F_ANN_DATE_INVALID"),
                    ("invalid_end_date_rows", "END_DATE_INVALID"),
                    ("end_after_available_rows", "END_AFTER_AVAILABLE"),
                    ("required_numeric_parse_rows", "REQUIRED_NUMERIC_PARSE_INVALID"),
                    ("required_numeric_nonfinite_rows", "REQUIRED_NUMERIC_NONFINITE"),
                    ("invalid_report_type_rows", "REPORT_TYPE_INVALID"),
                    ("invalid_comp_type_rows", "COMP_TYPE_INVALID"),
                ):
                    if quality[field] and (
                        field
                        not in {
                            "required_numeric_parse_rows",
                            "required_numeric_nonfinite_rows",
                        }
                        or numeric_blocked
                    ):
                        blocking.append(
                            {
                                "code": f"{dataset.upper()}_{code}",
                                "count": quality[field],
                            }
                        )
            untokenizable_pairs: dict[str, set[tuple[str, str]]] = {
                dataset: set() for dataset in _DATASETS
            }
            for dataset, relative_path, field in source_identity.untokenizable:
                if dataset not in untokenizable_pairs:
                    raise ValueError
                untokenizable_pairs[dataset].add((relative_path, field))
            for dataset in _DATASETS:
                pair_count = len(untokenizable_pairs[dataset])
                if pair_count:
                    blocking.append(
                        {
                            "code": f"{dataset.upper()}_FLOW_SOURCE_TYPE_UNTOKENIZABLE",
                            "count": pair_count,
                        }
                    )
            structural_closed = all(
                all(
                    dataset_reports[dataset]["quality"][field] == 0
                    for field in (
                        "row_count_mismatch",
                        "missing_request_rows",
                        "request_symbol_mismatches",
                        "request_window_mismatches",
                        "critical_null_rows",
                        "invalid_symbol_rows",
                        "invalid_ann_date_rows",
                        "invalid_f_ann_date_rows",
                        "invalid_end_date_rows",
                        "end_after_available_rows",
                        "invalid_report_type_rows",
                        "invalid_comp_type_rows",
                    )
                )
                for dataset in _DATASETS
            )
            field_domain_closed = all(
                dataset_reports[dataset]["quality"][name] == 0
                for dataset in ("balancesheet", "fina_indicator")
                for name in (
                    "required_numeric_parse_rows",
                    "required_numeric_nonfinite_rows",
                    "quarantined_rows",
                )
            ) and all(
                dataset_reports[dataset]["quality"]["eligible_rows"]
                == dataset_reports[dataset]["quality"]["raw_rows"]
                for dataset in ("balancesheet", "fina_indicator")
            )
            if structural_closed and field_domain_closed and not source_identity.untokenizable:
                flow = _flow_semantics(
                    connection=connection,
                    source_identity=source_identity,
                    complete=complete,
                    tables=tables,
                )
            else:
                flow = _not_evaluated_flow(source_identity)
        finally:
            connection.close()

    if blocking:
        status = "BLOCKED"
    elif total_incomplete:
        status = "COLLECTING"
    elif ledger_complete:
        status = "READY"
    else:
        status = "BLOCKED"
        blocking.append({"code": "LEDGER_STATE_INVALID", "count": 1})
    result = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "verify_bytes": verify_bytes,
        "plan_closure": dict(plan.closure),
        "active_lease_count": active_lease_count,
        "raw_closure": _raw_closure(complete),
        "datasets": dataset_reports,
        "blocking_issues": blocking,
        "flow_semantics": flow,
        "publication_allowed": status == "READY" and verify_bytes and flow["status"] == "PASS",
    }
    after = _verify_plan(
        root=root,
        plan_report_path=plan_report_path,
        catalog_path=catalog_path,
    )
    after_rows, after_active_lease_count = _read_ledger(
        root / "run_state" / "tushare_bulk" / "state.sqlite"
    )
    if (
        after != plan
        or after_rows != rows
        or after_active_lease_count != active_lease_count
    ):
        raise ValueError
    return result


def _verify_plan(
    *, root: Path, plan_report_path: Path, catalog_path: Path
) -> _VerifiedPlan:
    plan_root = root / "run_state" / "tushare_bulk" / "plan_reports"
    _require_plain_directory(plan_root)
    plan_path = _require_plain_regular(plan_report_path)
    if plan_path.parent != plan_root.resolve(strict=True):
        raise ValueError
    plan, plan_raw = _read_canonical_object(plan_path)
    plan_sha256 = hashlib.sha256(plan_raw).hexdigest()
    if not plan_path.name.endswith(f"-{plan_sha256[:12]}.json"):
        raise ValueError

    catalog_file = _require_plain_regular(catalog_path)
    catalog = load_catalog(catalog_file)
    permission_sha256 = plan.get("permission_report_sha256")
    if type(permission_sha256) is not str or _HEX64.fullmatch(permission_sha256) is None:
        raise ValueError
    permission_report = _permission_report(root=root, expected_sha256=permission_sha256)
    planned_at = _utc_datetime(plan.get("planned_at"))
    as_of = _iso_date(plan.get("as_of"))

    inventory_before = _instrument_inventory_closure(root)
    rebuilt = build_request_plan(
        catalog=catalog,
        permission_report=permission_report,
        data_root=root,
        as_of=as_of,
        now=planned_at,
    )
    if rebuilt != plan or plan.get("schema_version") != PLAN_SCHEMA:
        raise ValueError
    inventory = plan.get("inventory")
    if (
        type(inventory) is not dict
        or inventory.get("stock") != inventory_before["stock_count"]
    ):
        raise ValueError

    expected = _expected_financial_requests(catalog=catalog, root=root, as_of=as_of)
    dataset_rows = plan.get("datasets")
    if type(dataset_rows) is not list:
        raise ValueError
    estimates = {
        row.get("dataset"): row.get("estimated_requests")
        for row in dataset_rows
        if type(row) is dict and row.get("dataset") in _DATASETS
    }
    counts = Counter(request.dataset for request in expected)
    if (
        set(estimates) != set(_DATASETS)
        or any(estimates[name] != counts[name] or counts[name] <= 0 for name in _DATASETS)
    ):
        raise ValueError
    request_ids = tuple(request.request_id for request in expected)
    if len(request_ids) != len(set(request_ids)):
        raise ValueError
    request_payload = _canonical_json(
        [
            PLAN_CLOSURE_SCHEMA,
            [[request.dataset, request.request_id] for request in expected],
        ]
    )
    inventory_after = _instrument_inventory_closure(root)
    if inventory_after != inventory_before:
        raise ValueError
    closure = {
        "schema_version": PLAN_CLOSURE_SCHEMA,
        "provenance_model": PROVENANCE_MODEL,
        "provenance_limitation": PROVENANCE_LIMITATION,
        "plan_report_sha256": plan_sha256,
        "plan_schema_version": PLAN_SCHEMA,
        "planned_as_of": as_of.isoformat(),
        "catalog_version": catalog.version,
        "catalog_sha256": catalog.sha256,
        "permission_report_sha256": permission_sha256,
        "instrument_inventory": inventory_before,
        "request_counts": {name: counts[name] for name in _DATASETS},
        "request_set_sha256": hashlib.sha256(request_payload).hexdigest(),
    }
    return _VerifiedPlan(closure=closure, expected_requests=expected)


def _permission_report(*, root: Path, expected_sha256: str) -> dict[str, object]:
    directory = root / "run_state" / "tushare_bulk" / "permission_reports"
    _require_plain_directory(directory)
    matches: list[dict[str, object]] = []
    for candidate in sorted(directory.glob("*.json")):
        path = _require_plain_regular(candidate)
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected_sha256:
            continue
        value, canonical = _read_canonical_object(path)
        if canonical != raw or not path.name.endswith(f"-{expected_sha256[:12]}.json"):
            raise ValueError
        matches.append(cast(dict[str, object], value))
    if not matches or any(value != matches[0] for value in matches[1:]):
        raise ValueError
    return matches[0]


def _expected_financial_requests(
    *, catalog: Catalog, root: Path, as_of: dt.date
) -> tuple[_bulk_ingest.Request, ...]:
    by_name = {spec.name: spec for spec in catalog.datasets}
    if not set(_DATASETS) <= set(by_name):
        raise ValueError
    result: list[_bulk_ingest.Request] = []
    for dataset in _DATASETS:
        spec = cast(DatasetSpec, by_name[dataset])
        if (
            spec.api_name != dataset
            or spec.request_unit != "per_symbol"
            or spec.inventory != "stock"
            or spec.history_start is None
        ):
            raise ValueError
        result.extend(
            _bulk_ingest._requests_for_spec(
                catalog=catalog,
                spec=spec,
                data_root=root,
                start=spec.history_start,
                end=as_of,
            )
        )
    return tuple(sorted(result, key=lambda request: (request.dataset, request.request_id)))


def _instrument_inventory_closure(root: Path) -> dict[str, Any]:
    directory = root / "clean" / "instrument"
    resolved_directory = _require_plain_directory(directory)
    paths = tuple(sorted(directory.glob("market=*/data.parquet")))
    if not paths:
        raise ValueError
    entries: list[dict[str, Any]] = []
    resolved: set[Path] = set()
    frames: list[pl.DataFrame] = []
    for candidate in paths:
        resolved_parent = _require_plain_directory(candidate.parent)
        path = _require_plain_regular(candidate)
        if (
            resolved_parent.parent != resolved_directory
            or resolved_parent != candidate.parent
            or path.parent != resolved_parent
            or path != candidate
            or path in resolved
        ):
            raise ValueError
        resolved.add(path)
        relative = path.relative_to(root).as_posix()
        before = path.stat()
        raw_sha256 = _sha256(path)
        after = path.stat()
        if not os.path.samestat(before, after) or before.st_size != after.st_size:
            raise ValueError
        entries.append(
            {
                "relative_path": relative,
                "size_bytes": after.st_size,
                "sha256": raw_sha256,
            }
        )
        frames.append(pl.read_parquet(path))
    frame = pl.concat(frames, how="vertical_relaxed")
    required = {"symbol", "market", "instrument_type"}
    if not required <= set(frame.columns):
        raise ValueError
    stock = (
        frame.select(
            pl.col("symbol").cast(pl.String),
            pl.col("market").cast(pl.String),
            pl.col("instrument_type").cast(pl.String),
        )
        .filter(
            pl.col("market").is_in(["SH", "SZ"])
            & (pl.col("instrument_type") == "STOCK")
        )
        .sort("symbol", "market", "instrument_type")
    )
    if (
        stock.is_empty()
        or stock.null_count().row(0) != (0, 0, 0)
        or stock.get_column("symbol").n_unique() != stock.height
        or any(_SYMBOL.fullmatch(value) is None for value in stock.get_column("symbol"))
    ):
        raise ValueError
    logical_rows = [list(row) for row in stock.iter_rows()]
    file_set_sha256 = hashlib.sha256(
        _canonical_json([INVENTORY_CLOSURE_SCHEMA, entries])
    ).hexdigest()
    logical_sha256 = hashlib.sha256(
        _canonical_json([INVENTORY_CLOSURE_SCHEMA, logical_rows])
    ).hexdigest()
    return {
        "schema_version": INVENTORY_CLOSURE_SCHEMA,
        "files": entries,
        "file_set_sha256": file_set_sha256,
        "logical_frame_sha256": logical_sha256,
        "stock_count": stock.height,
    }


def _verify_ledger_plan(
    *,
    rows: list[tuple[Any, ...]],
    expected: tuple[_bulk_ingest.Request, ...],
    expected_catalog_sha256: str,
) -> None:
    expected_by_id = {request.request_id: request for request in expected}
    observed: set[str] = set()
    for row in rows:
        request_id = row[0]
        request = expected_by_id.get(request_id)
        if request is None or request_id in observed:
            raise ValueError
        observed.add(request_id)
        parameters_json = json.dumps(
            dict(request.parameters), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        if (
            row[1] != request.dataset
            or row[5] != parameters_json
            or row[6] != request.max_rows
            or row[8] != expected_catalog_sha256
            or row[9] != request.api_name
        ):
            raise ValueError
    if observed != set(expected_by_id):
        raise ValueError


def _read_ledger(ledger: Path) -> tuple[list[tuple[Any, ...]], int]:
    uri = f"file:{ledger.resolve(strict=True).as_posix()}?mode=ro"
    placeholders = ",".join("?" for _ in _DATASETS)
    with sqlite3.connect(uri, uri=True) as connection:
        rows = connection.execute(
            "SELECT request_id,dataset,status,rows,checksum_sha256,parameters_json,"
            "max_rows,error_code,catalog_sha256,api_name FROM requests "
            f"WHERE dataset IN ({placeholders}) ORDER BY dataset,request_id",
            _DATASETS,
        ).fetchall()
        leases = connection.execute("SELECT owner,expires_at FROM lease ORDER BY owner").fetchall()
    now = time.time()
    if any(
        type(owner) is not str
        or not owner
        or type(expires_at) not in {int, float}
        for owner, expires_at in leases
    ):
        raise ValueError
    active = sum(float(expires_at) >= now for _, expires_at in leases)
    return rows, active


def _read_canonical_object(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()
    value = json.loads(raw.decode("utf-8"))
    if type(value) is not dict or raw != _canonical_json(value):
        raise ValueError
    return cast(dict[str, Any], value), raw


def _utc_datetime(value: object) -> dt.datetime:
    if type(value) is not str:
        raise ValueError
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != dt.timedelta(0):
        raise ValueError
    return parsed


def _iso_date(value: object) -> dt.date:
    if type(value) is not str:
        raise ValueError
    parsed = dt.date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError
    return parsed


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _require_plain_directory(path: Path) -> Path:
    resolved = path.resolve(strict=True)
    info = path.stat(follow_symlinks=False)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    if (
        path.is_symlink()
        or not stat.S_ISDIR(info.st_mode)
        or bool(getattr(info, "st_file_attributes", 0) & reparse)
    ):
        raise ValueError
    return resolved


def _require_plain_regular(path: Path) -> Path:
    resolved = path.resolve(strict=True)
    info = path.stat(follow_symlinks=False)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    if (
        path.is_symlink()
        or not stat.S_ISREG(info.st_mode)
        or info.st_nlink != 1
        or bool(getattr(info, "st_file_attributes", 0) & reparse)
    ):
        raise ValueError
    return resolved


def _load_complete(
    *, root: Path, rows: list[tuple[Any, ...]], verify_bytes: bool
) -> list[_CompleteRequest]:
    result: list[_CompleteRequest] = []
    expected_metadata_keys = {
        "schema_version",
        "snapshot_id",
        "source",
        "table",
        "request_id",
        "fetched_at",
        "parameters",
        "rows",
        "columns",
        "checksum_sha256",
        "size_bytes",
    }
    for (
        request_id,
        dataset,
        status,
        row_count,
        checksum,
        parameters_json,
        max_rows,
        _,
        catalog_sha256,
        _api_name,
    ) in rows:
        if status != "COMPLETE":
            continue
        if (
            type(request_id) is not str
            or _HEX64.fullmatch(request_id) is None
            or dataset not in _DATASETS
            or type(row_count) is not int
            or row_count < 0
            or type(checksum) is not str
            or _HEX64.fullmatch(checksum) is None
            or type(catalog_sha256) is not str
            or _HEX64.fullmatch(catalog_sha256) is None
            or type(max_rows) is not int
            or max_rows <= 0
            or row_count >= max_rows
        ):
            raise ValueError
        parameters = json.loads(parameters_json)
        if set(parameters) != {"ts_code", "start_date", "end_date"}:
            raise ValueError
        symbol = parameters["ts_code"]
        start_date = parameters["start_date"]
        end_date = parameters["end_date"]
        if (
            type(symbol) is not str
            or _SYMBOL.fullmatch(symbol) is None
            or type(start_date) is not str
            or _DATE.fullmatch(start_date) is None
            or type(end_date) is not str
            or _DATE.fullmatch(end_date) is None
            or start_date > end_date
        ):
            raise ValueError
        request_root = root / "raw" / "tushare" / dataset / f"request={request_id}"
        request_directory = _require_plain_directory(request_root)
        if request_directory != request_root:
            raise ValueError
        if {path.name for path in request_root.iterdir()} != {
            "data.parquet",
            "metadata.json",
        }:
            raise ValueError
        parquet = request_root / "data.parquet"
        metadata_path = request_root / "metadata.json"
        _require_plain_regular(parquet)
        _require_plain_regular(metadata_path)
        metadata_payload = metadata_path.read_bytes()
        metadata = json.loads(metadata_payload.decode("utf-8"))
        columns = metadata.get("columns")
        if (
            set(metadata) != expected_metadata_keys
            or metadata["schema_version"] != "request-raw-v1"
            or metadata["snapshot_id"] != request_id
            or metadata["request_id"] != request_id
            or metadata["source"] != "tushare"
            or metadata["table"] != dataset
            or metadata["parameters"] != parameters
            or metadata["rows"] != row_count
            or metadata["checksum_sha256"] != checksum
            or metadata["size_bytes"] != parquet.stat().st_size
            or type(columns) is not list
            or not all(type(value) is str for value in columns)
            or not _STRUCTURAL_COLUMNS[dataset] <= set(columns)
        ):
            raise ValueError
        if verify_bytes and _sha256(parquet) != checksum:
            raise ValueError
        result.append(
            _CompleteRequest(
                request_id=request_id,
                dataset=dataset,
                catalog_sha256=catalog_sha256,
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                rows=row_count,
                max_rows=max_rows,
                checksum_sha256=checksum,
                metadata_sha256=hashlib.sha256(metadata_payload).hexdigest(),
                columns=tuple(cast(list[str], columns)),
                parquet_path=parquet,
                relative_path=parquet.relative_to(root).as_posix(),
            )
        )
    return result


def _raw_closure(complete: list[_CompleteRequest]) -> dict[str, Any]:
    entries = [
        {
            "catalog_sha256": item.catalog_sha256,
            "data_sha256": item.checksum_sha256,
            "dataset": item.dataset,
            "end_date": item.end_date,
            "max_rows": item.max_rows,
            "metadata_sha256": item.metadata_sha256,
            "request_id": item.request_id,
            "rows": item.rows,
            "start_date": item.start_date,
            "symbol": item.symbol,
        }
        for item in complete
    ]
    payload = json.dumps(
        [_RAW_CLOSURE_SCHEMA, entries],
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return {
        "schema_version": _RAW_CLOSURE_SCHEMA,
        "complete_request_count": len(entries),
        "catalog_sha256s": sorted({item.catalog_sha256 for item in complete}),
        "request_set_sha256": hashlib.sha256(payload).hexdigest(),
    }


def _empty_quality_summary() -> dict[str, Any]:
    return {
        "raw_rows": 0,
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
        "eligible_rows": 0,
        "quarantined_rows": 0,
        "column_set_count": 0,
        "column_set_sha256s": [],
        "required_numeric_union_types": {},
        "report_type_counts": [],
        "comp_type_counts": [],
        "report_type_comp_type_counts": [],
    }


def _quality_summary(
    *,
    dataset: str,
    complete: list[_CompleteRequest],
    threads: int,
    connection: Any,
    source_identity: _FlowSourceIdentity,
    table: str,
) -> dict[str, Any]:
    empty = _empty_quality_summary()
    if not complete:
        return empty
    active_connection = connection
    try:
        _configure_connection(active_connection, threads)
        expected_table = f"_flow_expected_requests_{dataset}"
        active_connection.execute(
            f"CREATE TEMP TABLE {expected_table}(request_id VARCHAR PRIMARY KEY,"
            "symbol VARCHAR,start_date VARCHAR,end_date VARCHAR,expected_rows BIGINT)"
        )
        active_connection.executemany(
            f"INSERT INTO {expected_table} VALUES (?,?,?,?,?)",
            [
                (
                    item.request_id,
                    item.symbol,
                    item.start_date,
                    item.end_date,
                    item.rows,
                )
                for item in complete
            ],
        )
        _validate_projected_sources(
            connection=active_connection, table=table, complete=complete
        )
        active_connection.execute(
            f"CREATE TEMP VIEW _flow_base_{dataset} AS SELECT r.*,"
            "e.symbol AS _expected_symbol,e.start_date AS _start_date,"
            "e.end_date AS _window_end,e.expected_rows AS _expected_rows "
            f"FROM {table} r LEFT JOIN {expected_table} e ON "
            "r._request_id=e.request_id"
        )
        base = f"_flow_base_{dataset}"
        actual = active_connection.execute(
            f"SELECT _request_id,count(*) AS actual_rows FROM {base} GROUP BY 1"
        ).fetchall()
        actual_rows = {row[0]: cast(int, row[1]) for row in actual}
        row_count_mismatch = sum(
            abs(item.rows - actual_rows.get(item.request_id, 0)) for item in complete
        )
        missing_request_rows = sum(
            item.rows > 0 and item.request_id not in actual_rows for item in complete
        )
        date_field = "ann_date" if dataset in _STATEMENTS else "end_date"
        f_ann_invalid = (
            "count(*) FILTER (WHERE f_ann_date IS NOT NULL AND "
            "try_strptime(CAST(f_ann_date AS VARCHAR),'%Y%m%d') IS NULL)"
            if dataset in _STATEMENTS
            else "0"
        )
        critical = (
            "ts_code IS NULL OR ann_date IS NULL OR end_date IS NULL OR "
            "report_type IS NULL OR comp_type IS NULL OR update_flag IS NULL"
            if dataset in _STATEMENTS
            else "ts_code IS NULL OR ann_date IS NULL OR end_date IS NULL"
        )
        available = (
            "greatest(try_strptime(CAST(ann_date AS VARCHAR),'%Y%m%d'),"
            "try_strptime(CAST(f_ann_date AS VARCHAR),'%Y%m%d'))"
            if dataset in _STATEMENTS
            else "try_strptime(CAST(ann_date AS VARCHAR),'%Y%m%d')"
        )
        numeric_parse = _numeric_condition(dataset, parse_failure=True)
        numeric_nonfinite = _numeric_condition(dataset, parse_failure=False)
        report_type_invalid = (
            "count(*) FILTER (WHERE report_type IS NULL OR NOT regexp_matches("
            "CAST(report_type AS VARCHAR),'^[0-9]+$'))"
            if dataset in _STATEMENTS
            else "0"
        )
        comp_type_invalid = (
            "count(*) FILTER (WHERE comp_type IS NULL OR NOT regexp_matches("
            "CAST(comp_type AS VARCHAR),'^[0-9]+$'))"
            if dataset in _STATEMENTS
            else "0"
        )
        valid_dimensions = (
            "regexp_matches(CAST(report_type AS VARCHAR),'^[0-9]+$') AND "
            "regexp_matches(CAST(comp_type AS VARCHAR),'^[0-9]+$')"
            if dataset in _STATEMENTS
            else "true"
        )
        summary = active_connection.execute(
            f"""
            SELECT count(*),
              count(*) FILTER (WHERE _request_id IS NULL),
              count(*) FILTER (WHERE ts_code IS DISTINCT FROM _expected_symbol),
              count(*) FILTER (WHERE CAST({date_field} AS VARCHAR) < _start_date
                                  OR CAST({date_field} AS VARCHAR) > _window_end),
              count(*) FILTER (WHERE {critical}),
              count(*) FILTER (WHERE ts_code IS NULL OR NOT regexp_matches(
                                  CAST(ts_code AS VARCHAR),'^[0-9]{{6}}\\.(SH|SZ)$')),
              count(*) FILTER (WHERE ann_date IS NULL OR try_strptime(
                                  CAST(ann_date AS VARCHAR),'%Y%m%d') IS NULL),
              {f_ann_invalid},
              count(*) FILTER (WHERE end_date IS NULL OR try_strptime(
                                  CAST(end_date AS VARCHAR),'%Y%m%d') IS NULL),
              count(*) FILTER (WHERE try_strptime(CAST(end_date AS VARCHAR),'%Y%m%d')
                                  > {available}),
              count(*) FILTER (WHERE {numeric_parse}),
              count(*) FILTER (WHERE {numeric_nonfinite}),
              {report_type_invalid},
              {comp_type_invalid},
              count(*) FILTER (WHERE NOT ({critical})
                                  AND regexp_matches(CAST(ts_code AS VARCHAR),'^[0-9]{{6}}\\.(SH|SZ)$')
                                  AND try_strptime(CAST(ann_date AS VARCHAR),'%Y%m%d') IS NOT NULL
                                  AND try_strptime(CAST(end_date AS VARCHAR),'%Y%m%d') IS NOT NULL
                                  AND try_strptime(CAST(end_date AS VARCHAR),'%Y%m%d') <= {available}
                                  AND CAST({date_field} AS VARCHAR) BETWEEN _start_date AND _window_end
                                  AND NOT ({numeric_parse}) AND NOT ({numeric_nonfinite})
                                  AND {valid_dimensions})
             FROM {base}
            """
        ).fetchone()
        if summary is None:
            raise ValueError
        raw_rows = cast(int, summary[0])
        eligible = cast(int, summary[14])
        quarantined = raw_rows - eligible
        key = (
            "ts_code,end_date,report_type,comp_type"
            if dataset in _STATEMENTS
            else "ts_code,end_date"
        )
        duplicates = active_connection.execute(
            f"SELECT count(*) FROM (SELECT {key},{available} AS available_date,"
            f"count(*) n FROM {base} GROUP BY ALL HAVING count(*)>1)"
        ).fetchone()
        conflict_expression = _required_economic_struct(dataset)
        economic_conflicts = (
            active_connection.execute(
                f"SELECT count(*) FROM (SELECT {key},{available} AS available_date,"
                f"count(DISTINCT {conflict_expression}) versions FROM {base} "
                "GROUP BY ALL HAVING versions>1)"
            ).fetchone()
            if conflict_expression is not None
            else (0,)
        )
        chains = active_connection.execute(
            f"SELECT count(*) FROM (SELECT {key},count(DISTINCT {available}) n "
            f"FROM {base} GROUP BY ALL HAVING n>1)"
        ).fetchone()
        if duplicates is None or economic_conflicts is None or chains is None:
            raise ValueError
        column_payloads = {
            hashlib.sha256(
                json.dumps(list(item.columns), separators=(",", ":")).encode()
            ).hexdigest()
            for item in complete
        }
        dimensions = _dimension_counts(
            connection=active_connection, dataset=dataset, table=base
        )
        source_types = {
            name: sorted(
                {
                    source_identity.schemas[item.relative_path].economic_types[name]
                    for item in complete
                }
            )
            for name in _NUMERIC_COLUMNS[dataset]
        }
        result: dict[str, Any] = {
            "raw_rows": raw_rows,
            "row_count_mismatch": row_count_mismatch,
            "missing_request_rows": missing_request_rows,
            "request_symbol_mismatches": cast(int, summary[2]),
            "request_window_mismatches": cast(int, summary[3]),
            "critical_null_rows": cast(int, summary[4]),
            "invalid_symbol_rows": cast(int, summary[5]),
            "invalid_ann_date_rows": cast(int, summary[6]),
            "invalid_f_ann_date_rows": cast(int, summary[7]),
            "invalid_end_date_rows": cast(int, summary[8]),
            "end_after_available_rows": cast(int, summary[9]),
            "required_numeric_parse_rows": cast(int, summary[10]),
            "required_numeric_nonfinite_rows": cast(int, summary[11]),
            "invalid_report_type_rows": cast(int, summary[12]),
            "invalid_comp_type_rows": cast(int, summary[13]),
            "same_available_duplicate_groups": cast(int, duplicates[0]),
            "required_economic_conflict_groups": cast(int, economic_conflicts[0]),
            "revision_chain_groups": cast(int, chains[0]),
            "eligible_rows": eligible,
            "quarantined_rows": quarantined,
            "column_set_count": len(column_payloads),
            "column_set_sha256s": sorted(column_payloads),
            "required_numeric_union_types": {
                name: "|".join(source_types[name]) for name in _NUMERIC_COLUMNS[dataset]
            },
            **dimensions,
        }
        _validate_dimension_evidence(dataset=dataset, quality=result)
        return result
    finally:
        pass


def _configure_connection(connection: Any, threads: int) -> None:
    connection.execute(f"SET threads={threads}")
    connection.execute("SET enable_progress_bar=false")
    connection.execute("SET preserve_insertion_order=false")


def _canonical_logical_type(value: object) -> str:
    if type(value) is not str:
        raise ValueError
    text = " ".join(value.strip().upper().split())
    if not text:
        raise ValueError
    return re.sub(r"\s*([(),\[\]<>:])\s*", r"\1", text)


def _is_untokenizable_logical_type(value: str) -> bool:
    return value.startswith(_UNTOKENIZABLE_LOGICAL_TYPE_PREFIXES) or value.endswith("[]")


def _is_numeric_logical_type(value: str) -> bool:
    return _NUMERIC_LOGICAL_TYPE.fullmatch(value) is not None


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _source_schema_for_file(
    *, connection: Any, item: _CompleteRequest
) -> _SourceSchema:
    selector = item.parquet_path.as_posix().replace("'", "''")
    rows = connection.execute(
        "DESCRIBE SELECT * FROM read_parquet("
        f"'{selector}', hive_partitioning=false)"
    ).fetchall()
    schema: list[tuple[str, str]] = []
    names: set[str] = set()
    for row in rows:
        if len(row) < 2 or type(row[0]) is not str:
            raise ValueError
        name = cast(str, row[0])
        if name in names:
            raise ValueError
        names.add(name)
        schema.append((name, _canonical_logical_type(row[1])))
    if tuple(name for name, _ in schema) != item.columns:
        raise ValueError
    if not _STRUCTURAL_COLUMNS[item.dataset] <= names:
        raise ValueError
    economic_types = {
        field: next(logical_type for name, logical_type in schema if name == field)
        for field in _NUMERIC_COLUMNS[item.dataset]
    }
    return _SourceSchema(
        relative_path=item.relative_path,
        schema=tuple(schema),
        economic_types=economic_types,
    )


def _flow_source_identity(
    *, connection: Any, complete: list[_CompleteRequest]
) -> _FlowSourceIdentity:
    schemas: dict[str, _SourceSchema] = {}
    evidence: list[dict[str, Any]] = []
    untokenizable: set[tuple[str, str, str]] = set()
    for item in sorted(
        complete,
        key=lambda current: (_DATASETS.index(current.dataset), current.relative_path),
    ):
        expected_relative = (
            f"raw/tushare/{item.dataset}/request={item.request_id}/data.parquet"
        )
        if item.relative_path != expected_relative or item.relative_path in schemas:
            raise ValueError
        schema = _source_schema_for_file(connection=connection, item=item)
        schemas[item.relative_path] = schema
        required_types = {
            field: schema.economic_types[field] for field in _NUMERIC_COLUMNS[item.dataset]
        }
        evidence.append(
            {
                "dataset": item.dataset,
                "request_id": item.request_id,
                "relative_file": item.relative_path,
                "schema": [
                    {"name": name, "logical_type": logical_type}
                    for name, logical_type in schema.schema
                ],
                "required_economic_types": required_types,
            }
        )
        for field, logical_type in required_types.items():
            if _is_untokenizable_logical_type(logical_type):
                untokenizable.add((item.dataset, item.relative_path, field))
    ordered_evidence = tuple(evidence)
    return _FlowSourceIdentity(
        evidence=ordered_evidence,
        schemas=schemas,
        untokenizable=tuple(sorted(untokenizable, key=_untokenizable_sort_key)),
    )


def _untokenizable_sort_key(value: tuple[str, str, str]) -> tuple[int, str, str]:
    dataset, relative_path, field = value
    return _DATASETS.index(dataset), relative_path, field


def _flow_source_evidence_sha256(entries: Sequence[Mapping[str, Any]]) -> str:
    return hashlib.sha256(
        _canonical_json([_FLOW_SOURCE_TYPE_EVIDENCE_VERSION, list(entries)])
    ).hexdigest()


def _flow_projection_contract() -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads(json.dumps(_FLOW_NORMALIZED_PROJECTION_CONTRACT)),
    )


def _flow_identity_fields(source_identity: _FlowSourceIdentity) -> dict[str, Any]:
    evidence = [dict(entry) for entry in source_identity.evidence]
    return {
        "source_type_evidence": evidence,
        "flow_source_type_evidence_sha256": _flow_source_evidence_sha256(evidence),
        "normalized_projection_contract": _flow_projection_contract(),
        "token_algorithm": _FLOW_TOKEN_ALGORITHM,
        "token_algorithm_version": _FLOW_TOKEN_ALGORITHM_VERSION,
    }


def _not_evaluated_flow(
    source_identity: _FlowSourceIdentity | None = None,
) -> dict[str, Any]:
    identity = (
        _flow_identity_fields(source_identity)
        if source_identity is not None
        else {
            "source_type_evidence": [],
            "flow_source_type_evidence_sha256": _FLOW_EARLY_EMPTY_SOURCE_EVIDENCE_SHA256,
            "normalized_projection_contract": json.loads(
                json.dumps(_FLOW_NORMALIZED_PROJECTION_CONTRACT)
            ),
            "token_algorithm": _FLOW_TOKEN_ALGORITHM,
            "token_algorithm_version": _FLOW_TOKEN_ALGORITHM_VERSION,
        }
    )
    return {
        "status": "NOT_EVALUATED",
        "flow_decimal_absolute_tolerance": _FLOW_DECIMAL_ABSOLUTE_TOLERANCE_TEXT,
        "minimum_current_symbols": _FLOW_MINIMUM_CURRENT_SYMBOLS,
        "minimum_fiscal_years": _FLOW_MINIMUM_FISCAL_YEARS,
        "minimum_comparable_observations": _FLOW_MINIMUM_COMPARABLE_OBSERVATIONS,
        **identity,
        "buckets": [],
    }


def _safe_projection_query(
    *,
    dataset: str,
    complete: list[_CompleteRequest],
    source_identity: _FlowSourceIdentity,
) -> str:
    grouped: dict[tuple[tuple[str, str], ...], list[_CompleteRequest]] = {}
    for item in complete:
        schema = source_identity.schemas.get(item.relative_path)
        if schema is None:
            raise ValueError
        grouped.setdefault(schema.schema, []).append(item)
    projections = [
        _projection_for_schema_group(
            dataset=dataset,
            group=sorted(items, key=lambda item: item.relative_path),
            source_identity=source_identity,
        )
        for _, items in sorted(grouped.items(), key=lambda pair: pair[0])
    ]
    if not projections:
        raise ValueError
    return " UNION ALL ".join(projections)


def _materialize_safe_projection(
    *,
    connection: Any,
    dataset: str,
    complete: list[_CompleteRequest],
    source_identity: _FlowSourceIdentity,
) -> str:
    table = f"_flow_raw_{dataset}"
    connection.execute(f"DROP TABLE IF EXISTS {table}")
    connection.execute(
        f"CREATE TEMP TABLE {table} AS "
        + _safe_projection_query(
            dataset=dataset,
            complete=complete,
            source_identity=source_identity,
        )
    )
    return table


def _projection_for_schema_group(
    *,
    dataset: str,
    group: list[_CompleteRequest],
    source_identity: _FlowSourceIdentity,
) -> str:
    if not group:
        raise ValueError
    schema = source_identity.schemas[group[0].relative_path]
    schema_names = {name for name, _ in schema.schema}
    paths = ",".join(
        _sql_string(item.parquet_path.as_posix())
        for item in sorted(group, key=lambda item: item.relative_path)
    )
    relation = (
        f"read_parquet([{paths}], filename=true, union_by_name=false, "
        "hive_partitioning=false)"
    )
    expressions = [
        f"{_sql_string(dataset)} AS _flow_dataset",
        "CAST(ts_code AS VARCHAR) AS ts_code",
        "CAST(ann_date AS VARCHAR) AS ann_date",
        (
            "CAST(f_ann_date AS VARCHAR) AS f_ann_date"
            if "f_ann_date" in schema_names
            else "NULL::VARCHAR AS f_ann_date"
        ),
        "CAST(end_date AS VARCHAR) AS end_date",
        (
            "CAST(report_type AS VARCHAR) AS report_type"
            if "report_type" in schema_names
            else "NULL::VARCHAR AS report_type"
        ),
        (
            "CAST(comp_type AS VARCHAR) AS comp_type"
            if "comp_type" in schema_names
            else "NULL::VARCHAR AS comp_type"
        ),
        (
            "CAST(update_flag AS VARCHAR) AS update_flag"
            if "update_flag" in schema_names
            else "NULL::VARCHAR AS update_flag"
        ),
        "regexp_extract(CAST(filename AS VARCHAR),'request=([0-9a-f]{64})',1) AS _request_id",
        f"concat('raw/tushare/',{_sql_string(dataset)},'/request=',"
        "regexp_extract(CAST(filename AS VARCHAR),'request=([0-9a-f]{64})',1),"
        "'/data.parquet') AS _source_file",
    ]
    for field in _NUMERIC_COLUMNS[dataset]:
        logical_type = schema.economic_types[field]
        expressions.append(f"{_sql_string(logical_type)} AS _flow_source_type_{field}")
        if _is_untokenizable_logical_type(logical_type):
            expressions.append(f"NULL::VARCHAR AS _flow_raw_{field}")
            expressions.append(f"NULL::DOUBLE AS _flow_projected_{field}")
        else:
            expressions.append(f"CAST({field} AS VARCHAR) AS _flow_raw_{field}")
            expressions.append(f"TRY_CAST({field} AS DOUBLE) AS _flow_projected_{field}")
    return "SELECT " + ",".join(expressions) + f" FROM {relation}"


def _validate_projected_sources(
    *, connection: Any, table: str, complete: list[_CompleteRequest]
) -> None:
    expected = {item.request_id: item.relative_path for item in complete}
    if len(expected) != len(complete):
        raise ValueError
    rows = connection.execute(
        f"SELECT _request_id,_source_file,count(*) FROM {table} "
        "GROUP BY 1,2 ORDER BY 1,2"
    ).fetchall()
    observed: dict[str, str] = {}
    for request_id, source_file, count in rows:
        if (
            type(request_id) is not str
            or type(source_file) is not str
            or type(count) is not int
            or count <= 0
            or request_id not in expected
            or source_file != expected[request_id]
            or request_id in observed
        ):
            raise ValueError
        observed[request_id] = source_file
    if not set(observed) <= set(expected):
        raise ValueError


def _canonical_numeric_token(value: float) -> str:
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError from None
    if decimal == 0:
        return "0"
    return format(decimal.normalize(), "f")


def _nonfinite_token(lexical: str) -> str:
    lowered = lexical.lower()
    if "nan" in lowered:
        return "NONFINITE:NAN"
    return "NONFINITE:-INF" if lowered.startswith("-") else "NONFINITE:+INF"


def _canonicalize_operand(
    *, source_type: object, raw: object, projected: object
) -> _CanonicalOperand:
    if type(source_type) is not str or not source_type:
        raise ValueError
    logical_type = cast(str, source_type)
    if raw is None:
        return _CanonicalOperand("MISSING", "missing", None)
    lexical = raw.strip() if type(raw) is str else str(raw).strip()
    if not lexical:
        return _CanonicalOperand("MISSING", "missing", None)
    if logical_type == "BOOLEAN":
        return _CanonicalOperand(
            f"INVALID_BOOLEAN:{lexical.lower()}", "invalid", None
        )
    if logical_type == "VARCHAR":
        if _VARCHAR_NONFINITE.fullmatch(lexical) is not None:
            return _CanonicalOperand(_nonfinite_token(lexical), "nonfinite", None)
        if _VARCHAR_FINITE.fullmatch(lexical) is None:
            return _CanonicalOperand(f"INVALID:VARCHAR:{lexical}", "invalid", None)
        if type(projected) is not float:
            return _CanonicalOperand(
                f"INVALID_OVERFLOW:{lexical}", "invalid", None
            )
        if not math.isfinite(cast(float, projected)):
            return _CanonicalOperand(
                f"INVALID_OVERFLOW:{lexical}", "invalid", None
            )
        return _CanonicalOperand(
            _canonical_numeric_token(cast(float, projected)),
            "finite",
            cast(float, projected),
        )
    if _is_numeric_logical_type(logical_type):
        if _VARCHAR_NONFINITE.fullmatch(lexical) is not None:
            return _CanonicalOperand(_nonfinite_token(lexical), "nonfinite", None)
        if type(projected) is not float:
            return _CanonicalOperand(
                f"INVALID_OVERFLOW:{lexical}", "invalid", None
            )
        projected_float = cast(float, projected)
        if math.isnan(projected_float):
            return _CanonicalOperand("NONFINITE:NAN", "nonfinite", None)
        if math.isinf(projected_float):
            return _CanonicalOperand(
                f"INVALID_OVERFLOW:{lexical}", "invalid", None
            )
        return _CanonicalOperand(
            _canonical_numeric_token(projected_float), "finite", projected_float
        )
    return _CanonicalOperand(
        f"INVALID:{logical_type}:{lexical}", "invalid", None
    )


def _classify_flow_operands(operands: Sequence[_CanonicalOperand]) -> str:
    categories = {operand.category for operand in operands}
    if "missing" in categories:
        return "missing_operands"
    if "invalid" in categories:
        return "invalid_numeric_operands"
    if "nonfinite" in categories:
        return "nonfinite_operands"
    if any(
        not _float64_cent_resolution(operand.projected)
        for operand in operands
    ):
        return "float64_cent_resolution_lost"
    return "comparable_observations"


def _cent_resolution_from_spacing(down: Decimal, up: Decimal) -> bool:
    return (
        isinstance(down, Decimal)
        and isinstance(up, Decimal)
        and max(down, up) <= _FLOW_DECIMAL_ABSOLUTE_TOLERANCE
    )


def _float64_cent_resolution(value: object) -> bool:
    if type(value) is not float or not math.isfinite(cast(float, value)):
        return False
    current = cast(float, value)
    lower = math.nextafter(current, -math.inf)
    upper = math.nextafter(current, math.inf)
    if not math.isfinite(lower) or not math.isfinite(upper):
        return False
    down = abs(Decimal.from_float(current) - Decimal.from_float(lower))
    up = abs(Decimal.from_float(upper) - Decimal.from_float(current))
    return _cent_resolution_from_spacing(down, up)


def _economic_decimal(value: object) -> Decimal:
    if type(value) is not float or not math.isfinite(cast(float, value)):
        raise ValueError
    decimal = Decimal(str(cast(float, value)))
    return Decimal(0) if decimal == 0 else decimal


def _flow_mismatch(
    *, current: _CanonicalOperand, type2: _CanonicalOperand, previous: _CanonicalOperand | None
) -> bool:
    if current.projected is None or type2.projected is None:
        raise ValueError
    current_value = _economic_decimal(current.projected)
    type2_value = _economic_decimal(type2.projected)
    difference = current_value - type2_value
    if previous is not None:
        if previous.projected is None:
            raise ValueError
        difference = current_value - _economic_decimal(previous.projected) - type2_value
    return abs(difference) > _FLOW_DECIMAL_ABSOLUTE_TOLERANCE


def _flow_date(value: object) -> dt.date:
    if type(value) is not str or _DATE.fullmatch(cast(str, value)) is None:
        raise ValueError
    return dt.datetime.strptime(cast(str, value), "%Y%m%d").date()


def _flow_observations(
    *, connection: Any, dataset: str, table: str | None = None
) -> tuple[_FlowObservation, ...]:
    fields = _NUMERIC_COLUMNS[dataset]
    selected = [
        "ts_code",
        "ann_date",
        "f_ann_date",
        "end_date",
        "report_type",
        "comp_type",
        "update_flag",
        "_source_file",
    ]
    for field in fields:
        selected.extend(
            [
                f"_flow_raw_{field}",
                f"_flow_projected_{field}",
                f"_flow_source_type_{field}",
            ]
        )
    rows = connection.execute(
        f"SELECT {','.join(selected)} FROM {table or f'_flow_raw_{dataset}'}"
    ).fetchall()
    result: list[_FlowObservation] = []
    for row in rows:
        if len(row) != len(selected):
            raise ValueError
        symbol, ann_raw, f_ann_raw, end_raw, report_type, comp_type, update_flag, source_file = row[:8]
        if (
            type(symbol) is not str
            or _SYMBOL.fullmatch(symbol) is None
            or type(report_type) is not str
            or _DIMENSION_CODE.fullmatch(report_type) is None
            or type(comp_type) is not str
            or _DIMENSION_CODE.fullmatch(comp_type) is None
            or type(update_flag) is not str
            or update_flag not in {"0", "1"}
            or type(source_file) is not str
        ):
            raise ValueError
        ann_date = _flow_date(ann_raw)
        f_ann_date = None if f_ann_raw is None else _flow_date(f_ann_raw)
        end_date = _flow_date(end_raw)
        available_date = max(ann_date, f_ann_date or ann_date)
        raw_values: list[object] = []
        projected_values: list[object] = []
        source_types: list[str] = []
        canonical_values: list[_CanonicalOperand] = []
        offset = 8
        for _ in fields:
            raw = row[offset]
            projected = row[offset + 1]
            source_type = row[offset + 2]
            raw_values.append(raw)
            projected_values.append(projected)
            source_types.append(cast(str, source_type))
            canonical_values.append(
                _canonicalize_operand(
                    source_type=source_type, raw=raw, projected=projected
                )
            )
            offset += 3
        if not (
            len(source_types)
            == len(raw_values)
            == len(projected_values)
            == len(canonical_values)
            == len(fields)
        ):
            raise ValueError
        result.append(
            _FlowObservation(
                dataset=dataset,
                symbol=symbol,
                ann_date=ann_date,
                f_ann_date=f_ann_date,
                available_date=available_date,
                end_date=end_date,
                report_type=report_type,
                comp_type=comp_type,
                update_flag=update_flag,
                source_file=source_file,
                raw_values=tuple(raw_values),
                projected_values=tuple(projected_values),
                source_types=tuple(source_types),
                canonical_values=tuple(canonical_values),
            )
        )
    return tuple(result)


def _fiscal_bucket(value: dt.date) -> str | None:
    return _FLOW_BUCKET_MONTHS.get(value.month)


def _flow_key(observation: _FlowObservation) -> _FlowKey:
    return (
        observation.symbol,
        observation.end_date,
        observation.report_type,
        observation.comp_type,
    )


def _observation_sort_key(
    observation: _FlowObservation,
) -> tuple[object, ...]:
    return (
        observation.update_flag,
        observation.ann_date,
        observation.f_ann_date or dt.date.min,
        observation.source_file,
        tuple("" if value is None else str(value) for value in observation.raw_values),
    )


def _select_latest_observation(
    observations: Sequence[_FlowObservation],
) -> tuple[_FlowObservation | None, bool]:
    if not observations:
        return None, False
    latest_date = max(observation.available_date for observation in observations)
    latest = [
        observation
        for observation in observations
        if observation.available_date == latest_date
    ]
    tokens = {tuple(value.token for value in observation.canonical_values) for observation in latest}
    if len(tokens) > 1:
        return None, True
    return max(latest, key=_observation_sort_key), False


def _previous_end_date(end_date: dt.date, bucket: str) -> dt.date:
    if bucket == "Q2":
        return dt.date(end_date.year, 3, 31)
    if bucket == "Q3":
        return dt.date(end_date.year, 6, 30)
    if bucket == "FY":
        return dt.date(end_date.year, 9, 30)
    raise ValueError


def _flow_bucket_status(
    *,
    chain_applicable: bool,
    current_candidates: int,
    distinct_symbols: int,
    synchronized: int,
    previous_chain_eligible: int | None,
    comparable: int,
    fiscal_years: int,
    mismatch_count: int,
) -> str:
    if mismatch_count > 0:
        return "CONTRADICTED"
    pair_coverage = current_candidates > 0 and 5 * synchronized >= 4 * current_candidates
    chain_coverage = (
        not chain_applicable
        or (
            synchronized > 0
            and previous_chain_eligible is not None
            and 5 * previous_chain_eligible >= 4 * synchronized
        )
    )
    if (
        pair_coverage
        and chain_coverage
        and distinct_symbols >= _FLOW_MINIMUM_CURRENT_SYMBOLS
        and fiscal_years >= _FLOW_MINIMUM_FISCAL_YEARS
        and comparable >= _FLOW_MINIMUM_COMPARABLE_OBSERVATIONS
    ):
        return "PASS"
    return "INSUFFICIENT"


def _flow_bucket(
    *,
    observations: Sequence[_FlowObservation],
    field: str,
    fiscal_bucket: str,
) -> dict[str, Any]:
    dataset = next(dataset for dataset, name in _FLOW_FIELDS if name == field)
    fields = _NUMERIC_COLUMNS[dataset]
    field_index = fields.index(field)
    bucket_rows = [
        observation
        for observation in observations
        if _fiscal_bucket(observation.end_date) == fiscal_bucket
    ]
    by_key: dict[_FlowKey, list[_FlowObservation]] = {}
    for observation in observations:
        by_key.setdefault(_flow_key(observation), []).append(observation)
    current_groups: dict[_FlowKey, list[_FlowObservation]] = {}
    for observation in bucket_rows:
        if observation.report_type == "1":
            current_groups.setdefault(_flow_key(observation), []).append(observation)
    current_candidates = len(current_groups)
    distinct_symbols = len({key[0] for key in current_groups})
    latest_current_conflicts = 0
    missing_type2 = 0
    latest_type2_conflicts = 0
    available_date_drift = 0
    synchronized_pairs: list[tuple[_FlowObservation, _FlowObservation]] = []
    for key, current_rows in sorted(current_groups.items()):
        current, current_conflict = _select_latest_observation(current_rows)
        if current_conflict or current is None:
            latest_current_conflicts += 1
            continue
        type2_key = (current.symbol, current.end_date, "2", current.comp_type)
        type2_rows = by_key.get(type2_key, [])
        if not type2_rows:
            missing_type2 += 1
            continue
        type2, type2_conflict = _select_latest_observation(type2_rows)
        if type2_conflict or type2 is None:
            latest_type2_conflicts += 1
            continue
        if type2.available_date != current.available_date:
            available_date_drift += 1
            continue
        synchronized_pairs.append((current, type2))

    missing_previous = 0
    latest_previous_conflicts = 0
    previous_pairs: list[tuple[_FlowObservation, _FlowObservation, _FlowObservation]] = []
    if fiscal_bucket != "Q1":
        for current, type2 in synchronized_pairs:
            previous_end = _previous_end_date(current.end_date, fiscal_bucket)
            previous_key = (current.symbol, previous_end, "1", current.comp_type)
            previous_rows = [
                observation
                for observation in by_key.get(previous_key, [])
                if observation.available_date <= current.available_date
            ]
            if not previous_rows:
                missing_previous += 1
                continue
            previous, previous_conflict = _select_latest_observation(previous_rows)
            if previous_conflict or previous is None:
                latest_previous_conflicts += 1
                continue
            previous_pairs.append((current, type2, previous))

    missing_operands = 0
    invalid_numeric_operands = 0
    nonfinite_operands = 0
    float64_cent_resolution_lost = 0
    comparable_observations = 0
    mismatch_count = 0
    fiscal_year_values: set[int] = set()
    numeric_pairs: Sequence[tuple[_FlowObservation, _FlowObservation, _FlowObservation | None]]
    if fiscal_bucket == "Q1":
        numeric_pairs = [(current, type2, None) for current, type2 in synchronized_pairs]
    else:
        numeric_pairs = previous_pairs
    for current, type2, previous in numeric_pairs:
        operands = [current.canonical_values[field_index], type2.canonical_values[field_index]]
        if previous is not None:
            operands.insert(1, previous.canonical_values[field_index])
        classification = _classify_flow_operands(operands)
        if classification == "missing_operands":
            missing_operands += 1
        elif classification == "invalid_numeric_operands":
            invalid_numeric_operands += 1
        elif classification == "nonfinite_operands":
            nonfinite_operands += 1
        elif classification == "float64_cent_resolution_lost":
            float64_cent_resolution_lost += 1
        else:
            comparable_observations += 1
            fiscal_year_values.add(current.end_date.year)
            if _flow_mismatch(
                current=current.canonical_values[field_index],
                type2=type2.canonical_values[field_index],
                previous=None if previous is None else previous.canonical_values[field_index],
            ):
                mismatch_count += 1
    previous_eligible = None if fiscal_bucket == "Q1" else len(previous_pairs)
    status = _flow_bucket_status(
        chain_applicable=fiscal_bucket != "Q1",
        current_candidates=current_candidates,
        distinct_symbols=distinct_symbols,
        synchronized=len(synchronized_pairs),
        previous_chain_eligible=previous_eligible,
        comparable=comparable_observations,
        fiscal_years=len(fiscal_year_values),
        mismatch_count=mismatch_count,
    )
    return {
        "dataset": dataset,
        "field": field,
        "fiscal_bucket": fiscal_bucket,
        "chain_applicable": fiscal_bucket != "Q1",
        "current_type1_candidates": current_candidates,
        "distinct_symbols": distinct_symbols,
        "fiscal_years": len(fiscal_year_values),
        "synchronized_type2_pairs": len(synchronized_pairs),
        "previous_chain_eligible": previous_eligible,
        "missing_type2": missing_type2,
        "missing_previous": None if fiscal_bucket == "Q1" else missing_previous,
        "latest_current_conflicts": latest_current_conflicts,
        "latest_type2_conflicts": latest_type2_conflicts,
        "latest_previous_conflicts": (
            0 if fiscal_bucket == "Q1" else latest_previous_conflicts
        ),
        "available_date_drift": available_date_drift,
        "missing_operands": missing_operands,
        "invalid_numeric_operands": invalid_numeric_operands,
        "nonfinite_operands": nonfinite_operands,
        "float64_cent_resolution_lost": float64_cent_resolution_lost,
        "comparable_observations": comparable_observations,
        "mismatch_count": mismatch_count,
        "status": status,
    }


def _flow_semantics(
    *,
    connection: Any,
    source_identity: _FlowSourceIdentity,
    complete: list[_CompleteRequest] | None = None,
    tables: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    flow_datasets = tuple(dict.fromkeys(dataset for dataset, _ in _FLOW_FIELDS))
    if tables is None:
        if complete is None:
            raise ValueError
        materialized: dict[str, str] = {}
        for dataset in flow_datasets:
            materialized[dataset] = _materialize_safe_projection(
                connection=connection,
                dataset=dataset,
                complete=[item for item in complete if item.dataset == dataset],
                source_identity=source_identity,
            )
        tables = materialized
    if any(dataset not in tables for dataset in flow_datasets):
        raise ValueError
    observations: dict[str, tuple[_FlowObservation, ...]] = {
        dataset: _flow_observations(
            connection=connection, dataset=dataset, table=tables[dataset]
        )
        for dataset in flow_datasets
    }
    buckets: list[dict[str, Any]] = []
    for dataset, field in _FLOW_FIELDS:
        buckets.extend(
            _flow_bucket(
                observations=observations[dataset],
                field=field,
                fiscal_bucket=fiscal_bucket,
            )
            for fiscal_bucket in _FLOW_BUCKETS
        )
    statuses = [cast(str, bucket["status"]) for bucket in buckets]
    flow_status = (
        "CONTRADICTED"
        if "CONTRADICTED" in statuses
        else "PASS"
        if len(statuses) == len(_FLOW_FIELDS) * len(_FLOW_BUCKETS)
        and all(status == "PASS" for status in statuses)
        else "INSUFFICIENT"
    )
    return {
        "status": flow_status,
        "flow_decimal_absolute_tolerance": _FLOW_DECIMAL_ABSOLUTE_TOLERANCE_TEXT,
        "minimum_current_symbols": _FLOW_MINIMUM_CURRENT_SYMBOLS,
        "minimum_fiscal_years": _FLOW_MINIMUM_FISCAL_YEARS,
        "minimum_comparable_observations": _FLOW_MINIMUM_COMPARABLE_OBSERVATIONS,
        **_flow_identity_fields(source_identity),
        "buckets": buckets,
    }


def _dimension_counts(
    *, connection: Any, dataset: str, table: str = "base"
) -> dict[str, Any]:
    if dataset not in _STATEMENTS:
        return {
            "report_type_counts": [],
            "comp_type_counts": [],
            "report_type_comp_type_counts": [],
        }
    rows = connection.execute(
        "SELECT CAST(report_type AS VARCHAR),CAST(comp_type AS VARCHAR),count(*) "
        f"FROM {table} GROUP BY 1,2 ORDER BY 1,2"
    ).fetchall()
    report_counts: Counter[str] = Counter()
    comp_counts: Counter[str] = Counter()
    pair_counts: list[dict[str, Any]] = []
    for raw_report_type, raw_comp_type, raw_count in rows:
        count = cast(int, raw_count)
        report_type = raw_report_type if type(raw_report_type) is str else None
        comp_type = raw_comp_type if type(raw_comp_type) is str else None
        report_valid = (
            report_type is not None
            and _DIMENSION_CODE.fullmatch(report_type) is not None
        )
        comp_valid = (
            comp_type is not None and _DIMENSION_CODE.fullmatch(comp_type) is not None
        )
        if type(count) is not int or count <= 0:
            raise ValueError
        if report_valid:
            report_counts[cast(str, report_type)] += count
        if comp_valid:
            comp_counts[cast(str, comp_type)] += count
        if report_valid and comp_valid:
            pair_counts.append(
                {
                    "report_type": cast(str, report_type),
                    "comp_type": cast(str, comp_type),
                    "rows": count,
                }
            )
    return {
        "report_type_counts": [
            {"value": value, "rows": count}
            for value, count in sorted(report_counts.items())
        ],
        "comp_type_counts": [
            {"value": value, "rows": count}
            for value, count in sorted(comp_counts.items())
        ],
        "report_type_comp_type_counts": pair_counts,
    }


def _validate_dimension_evidence(*, dataset: str, quality: Mapping[str, Any]) -> None:
    report_counts = quality["report_type_counts"]
    comp_counts = quality["comp_type_counts"]
    pair_counts = quality["report_type_comp_type_counts"]
    invalid_report = quality["invalid_report_type_rows"]
    invalid_comp = quality["invalid_comp_type_rows"]
    raw_rows = quality["raw_rows"]
    if dataset not in _STATEMENTS:
        if (
            invalid_report != 0
            or invalid_comp != 0
            or report_counts != []
            or comp_counts != []
            or pair_counts != []
        ):
            raise ValueError
        return
    if invalid_report != 0 or invalid_comp != 0:
        return
    report_marginal = {
        cast(str, item["value"]): cast(int, item["rows"])
        for item in cast(list[dict[str, object]], report_counts)
    }
    comp_marginal = {
        cast(str, item["value"]): cast(int, item["rows"])
        for item in cast(list[dict[str, object]], comp_counts)
    }
    pair_report: Counter[str] = Counter()
    pair_comp: Counter[str] = Counter()
    pair_total = 0
    for item in cast(list[dict[str, object]], pair_counts):
        count = cast(int, item["rows"])
        pair_report[cast(str, item["report_type"])] += count
        pair_comp[cast(str, item["comp_type"])] += count
        pair_total += count
    if (
        sum(report_marginal.values()) != raw_rows
        or sum(comp_marginal.values()) != raw_rows
        or pair_total != raw_rows
        or dict(pair_report) != report_marginal
        or dict(pair_comp) != comp_marginal
    ):
        raise ValueError


def _numeric_condition(dataset: str, *, parse_failure: bool) -> str:
    fields = _NUMERIC_COLUMNS[dataset]
    if not fields:
        return "false"
    conditions = []
    for field in fields:
        raw = f"_flow_raw_{field}"
        present = f"{raw} IS NOT NULL AND trim(CAST({raw} AS VARCHAR)) <> ''"
        if parse_failure:
            conditions.append(f"({present} AND try_cast({raw} AS DOUBLE) IS NULL)")
        else:
            conditions.append(
                f"({present} AND try_cast({raw} AS DOUBLE) IS NOT NULL "
                f"AND NOT isfinite(try_cast({raw} AS DOUBLE)))"
            )
    return " OR ".join(conditions)


def _required_economic_struct(dataset: str) -> str | None:
    fields = _NUMERIC_COLUMNS[dataset]
    if not fields:
        return None
    values = ",".join(f"{field}:=_flow_raw_{field}" for field in fields)
    return f"struct_pack({values})"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="审计 Tushare 财务四表 raw 闭包")
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--plan-report", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--verify-bytes", action="store_true")
    args = parser.parse_args(argv)
    result = audit_tushare_financials(
        data_root=resolve_data_root(args.data_root),
        plan_report_path=args.plan_report,
        catalog_path=args.catalog,
        threads=args.threads,
        verify_bytes=args.verify_bytes,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "INVENTORY_CLOSURE_SCHEMA",
    "PLAN_CLOSURE_SCHEMA",
    "PROVENANCE_LIMITATION",
    "PROVENANCE_MODEL",
    "SCHEMA_VERSION",
    "audit_tushare_financials",
]
