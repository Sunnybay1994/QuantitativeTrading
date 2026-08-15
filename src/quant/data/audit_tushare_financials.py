"""Read-only ledger and raw quality audit for Tushare financial statements."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sqlite3
import stat
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
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

SCHEMA_VERSION = "tushare-financial-raw-audit-v2"
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


@dataclass(frozen=True, slots=True)
class _VerifiedPlan:
    closure: Mapping[str, Any]
    expected_requests: tuple[_bulk_ingest.Request, ...]


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

    dataset_reports: dict[str, dict[str, Any]] = {}
    blocking: list[dict[str, Any]] = []
    total_incomplete = active_lease_count
    for dataset in _DATASETS:
        dataset_rows = [row for row in rows if row[1] == dataset]
        statuses = Counter(cast(str, row[2]) for row in dataset_rows)
        quality = _quality_summary(dataset=dataset, complete=by_dataset[dataset], threads=threads)
        incomplete = sum(statuses[name] for name in ("PENDING", "RUNNING", "RETRYABLE"))
        total_incomplete += incomplete
        for status in ("FAILED", "SPLIT_REQUIRED"):
            if statuses[status]:
                blocking.append(
                    {
                        "code": f"{dataset.upper()}_LEDGER_{status}",
                        "count": statuses[status],
                    }
                )
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
        ):
            if quality[field]:
                blocking.append(
                    {
                        "code": f"{dataset.upper()}_{code}",
                        "count": quality[field],
                    }
                )
        dataset_reports[dataset] = {
            "request_count": len(dataset_rows),
            "status_counts": dict(sorted(statuses.items())),
            "complete_rows": sum(item.rows for item in by_dataset[dataset]),
            "quality": quality,
        }

    if blocking:
        status = "BLOCKED"
    elif total_incomplete:
        status = "COLLECTING"
    elif all(
        report["request_count"] == report["status_counts"].get("COMPLETE", 0)
        and report["request_count"] > 0
        for report in dataset_reports.values()
    ):
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
        "publication_allowed": status == "READY" and verify_bytes,
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
        if {path.name for path in request_root.iterdir()} != {
            "data.parquet",
            "metadata.json",
        }:
            raise ValueError
        parquet = request_root / "data.parquet"
        metadata_path = request_root / "metadata.json"
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


def _quality_summary(
    *, dataset: str, complete: list[_CompleteRequest], threads: int
) -> dict[str, Any]:
    empty = {
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
        "same_available_duplicate_groups": 0,
        "required_economic_conflict_groups": 0,
        "revision_chain_groups": 0,
        "eligible_rows": 0,
        "quarantined_rows": 0,
        "column_set_count": 0,
        "column_set_sha256s": [],
        "required_numeric_union_types": {},
    }
    if not complete:
        return empty
    connection = duckdb.connect(":memory:")
    try:
        connection.execute(f"SET threads={threads}")
        connection.execute("SET enable_progress_bar=false")
        connection.execute(
            "CREATE TEMP TABLE expected_requests(request_id VARCHAR PRIMARY KEY,"
            "symbol VARCHAR,start_date VARCHAR,end_date VARCHAR,expected_rows BIGINT)"
        )
        connection.executemany(
            "INSERT INTO expected_requests VALUES (?,?,?,?,?)",
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
        connection.read_parquet(
            [str(item.parquet_path) for item in complete],
            filename=True,
            union_by_name=True,
            hive_partitioning=False,
        ).create_view("financial_raw")
        connection.execute(
            "CREATE TEMP VIEW base AS SELECT r.*,"
            "regexp_extract(filename,'request=([0-9a-f]{64})',1) AS _request_id,"
            "e.symbol AS _expected_symbol,e.start_date AS _start_date,"
            "e.end_date AS _window_end,e.expected_rows AS _expected_rows "
            "FROM financial_raw r LEFT JOIN expected_requests e ON "
            "regexp_extract(filename,'request=([0-9a-f]{64})',1)=e.request_id"
        )
        actual = connection.execute(
            "SELECT _request_id,count(*) AS actual_rows FROM base GROUP BY 1"
        ).fetchall()
        actual_rows = {cast(str, row[0]): cast(int, row[1]) for row in actual}
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
        summary = connection.execute(
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
              count(*) FILTER (WHERE NOT ({critical})
                                  AND regexp_matches(CAST(ts_code AS VARCHAR),'^[0-9]{{6}}\\.(SH|SZ)$')
                                  AND try_strptime(CAST(ann_date AS VARCHAR),'%Y%m%d') IS NOT NULL
                                  AND try_strptime(CAST(end_date AS VARCHAR),'%Y%m%d') IS NOT NULL
                                  AND try_strptime(CAST(end_date AS VARCHAR),'%Y%m%d') <= {available}
                                  AND CAST({date_field} AS VARCHAR) BETWEEN _start_date AND _window_end
                                  AND NOT ({numeric_parse}) AND NOT ({numeric_nonfinite}))
            FROM base
            """
        ).fetchone()
        if summary is None:
            raise ValueError
        raw_rows = cast(int, summary[0])
        eligible = cast(int, summary[12])
        quarantined = raw_rows - eligible
        key = (
            "ts_code,end_date,report_type,comp_type"
            if dataset in _STATEMENTS
            else "ts_code,end_date"
        )
        duplicates = connection.execute(
            f"SELECT count(*) FROM (SELECT {key},{available} AS available_date,"
            "count(*) n FROM base GROUP BY ALL HAVING count(*)>1)"
        ).fetchone()
        conflict_expression = _required_economic_struct(dataset)
        economic_conflicts = (
            connection.execute(
                f"SELECT count(*) FROM (SELECT {key},{available} AS available_date,"
                f"count(DISTINCT {conflict_expression}) versions FROM base "
                "GROUP BY ALL HAVING versions>1)"
            ).fetchone()
            if conflict_expression is not None
            else (0,)
        )
        chains = connection.execute(
            f"SELECT count(*) FROM (SELECT {key},count(DISTINCT {available}) n "
            "FROM base GROUP BY ALL HAVING n>1)"
        ).fetchone()
        if duplicates is None or economic_conflicts is None or chains is None:
            raise ValueError
        description = {
            cast(str, row[0]): cast(str, row[1])
            for row in connection.execute("DESCRIBE financial_raw").fetchall()
        }
        column_payloads = {
            hashlib.sha256(
                json.dumps(list(item.columns), separators=(",", ":")).encode()
            ).hexdigest()
            for item in complete
        }
        return {
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
            "same_available_duplicate_groups": cast(int, duplicates[0]),
            "required_economic_conflict_groups": cast(int, economic_conflicts[0]),
            "revision_chain_groups": cast(int, chains[0]),
            "eligible_rows": eligible,
            "quarantined_rows": quarantined,
            "column_set_count": len(column_payloads),
            "column_set_sha256s": sorted(column_payloads),
            "required_numeric_union_types": {
                name: description[name] for name in _NUMERIC_COLUMNS[dataset]
            },
        }
    finally:
        connection.close()


def _numeric_condition(dataset: str, *, parse_failure: bool) -> str:
    fields = _NUMERIC_COLUMNS[dataset]
    if not fields:
        return "false"
    conditions = []
    for field in fields:
        present = f"{field} IS NOT NULL AND trim(CAST({field} AS VARCHAR)) <> ''"
        if parse_failure:
            conditions.append(f"({present} AND try_cast({field} AS DOUBLE) IS NULL)")
        else:
            conditions.append(
                f"({present} AND try_cast({field} AS DOUBLE) IS NOT NULL "
                f"AND NOT isfinite(try_cast({field} AS DOUBLE)))"
            )
    return " OR ".join(conditions)


def _required_economic_struct(dataset: str) -> str | None:
    fields = _NUMERIC_COLUMNS[dataset]
    if not fields:
        return None
    values = ",".join(f"{field}:={field}" for field in fields)
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
