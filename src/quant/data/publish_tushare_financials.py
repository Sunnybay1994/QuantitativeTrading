"""Publish immutable clean snapshots from completed Tushare financial raw."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import shutil
import sqlite3
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, cast

import duckdb
import polars as pl

from quant.data.audit_tushare_financials import (
    _CompleteRequest,
    _FLOW_BUCKETS,
    _FLOW_DECIMAL_ABSOLUTE_TOLERANCE_TEXT,
    _FLOW_EARLY_EMPTY_SOURCE_EVIDENCE_SHA256,
    _FLOW_FIELDS,
    _FLOW_MINIMUM_COMPARABLE_OBSERVATIONS,
    _FLOW_MINIMUM_CURRENT_SYMBOLS,
    _FLOW_MINIMUM_FISCAL_YEARS,
    _FLOW_NORMALIZED_PROJECTION_CONTRACT,
    _FLOW_TOKEN_ALGORITHM,
    _FLOW_TOKEN_ALGORITHM_VERSION,
    _STRUCTURAL_COLUMNS,
    _FlowSourceIdentity,
    _SourceSchema,
    _projection_for_schema_group,
    _canonical_logical_type,
    _flow_source_evidence_sha256,
    _is_untokenizable_logical_type,
    INVENTORY_CLOSURE_SCHEMA,
    PLAN_CLOSURE_SCHEMA,
    PROVENANCE_LIMITATION,
    PROVENANCE_MODEL,
    SCHEMA_VERSION as _AUDIT_SCHEMA_VERSION,
    audit_tushare_financials,
)
from quant.data.m3_release import M3ReleaseError, commit_directory_noreplace
from quant.data.tushare_bulk import PLAN_SCHEMA
from quant.settings import resolve_data_root

_SNAPSHOT_SCHEMA = "tushare-financial-clean-snapshot-v2"
_PROJECTION_VERSION = "tushare-financial-clean-projection-v1"
_DATASETS = ("balancesheet", "cashflow", "fina_indicator", "income")
_STATEMENTS = frozenset({"balancesheet", "cashflow", "income"})
_ECONOMIC_COLUMNS: dict[str, tuple[str, ...]] = {
    "balancesheet": ("total_assets", "total_hldr_eqy_exc_min_int"),
    "cashflow": ("n_cashflow_act",),
    "fina_indicator": (),
    "income": ("n_income", "n_income_attr_p"),
}
_QUALITY_KEYS = frozenset(
    {
        "raw_rows",
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
        "required_numeric_parse_rows",
        "required_numeric_nonfinite_rows",
        "invalid_report_type_rows",
        "invalid_comp_type_rows",
        "same_available_duplicate_groups",
        "required_economic_conflict_groups",
        "revision_chain_groups",
        "eligible_rows",
        "quarantined_rows",
        "column_set_count",
        "column_set_sha256s",
        "required_numeric_union_types",
        "report_type_counts",
        "comp_type_counts",
        "report_type_comp_type_counts",
    }
)
_HEX = frozenset("0123456789abcdef")


class TushareFinancialPublishError(ValueError):
    """Stable sanitized financial snapshot publication failure."""

    def __init__(self) -> None:
        super().__init__("TUSHARE_FINANCIAL_PUBLISH_INVALID")


@dataclass(frozen=True, slots=True)
class TushareFinancialSnapshot:
    """Verified immutable clean financial snapshot summary."""

    root: Path
    snapshot_id: str
    manifest_sha256: str
    audit_sha256: str
    dataset_rows: tuple[tuple[str, int], ...]
    reused: bool


def publish_tushare_financial_snapshot(
    *, data_root: Path, plan_report_path: Path, catalog_path: Path, threads: int = 2
) -> TushareFinancialSnapshot:
    """Publish only when the complete raw batch passes full byte verification."""
    try:
        return _publish(
            data_root=data_root,
            plan_report_path=plan_report_path,
            catalog_path=catalog_path,
            threads=threads,
        )
    except Exception:
        pass
    raise TushareFinancialPublishError() from None


def verify_tushare_financial_snapshot(
    *, data_root: Path, snapshot_id: str
) -> TushareFinancialSnapshot:
    """Verify one existing snapshot without consulting mutable current raw."""
    try:
        root = _resolved_data_root(data_root)
        if not _is_hex64(snapshot_id):
            raise ValueError
        return _verify_snapshot(
            root / "clean" / "tushare_financials" / "snapshots" / snapshot_id,
            expected_snapshot_id=snapshot_id,
            reused=True,
        )
    except Exception:
        pass
    raise TushareFinancialPublishError() from None


def _snapshot_b1_inputs(
    *, audit: Mapping[str, Any], raw_paths: Mapping[str, tuple[str, ...]]
) -> tuple[dict[str, list[_CompleteRequest]], _FlowSourceIdentity]:
    flow = audit.get("flow_semantics")
    if type(flow) is not dict:
        raise ValueError
    evidence_value = flow.get("source_type_evidence")
    if type(evidence_value) is not list:
        raise ValueError
    path_by_relative: dict[str, Path] = {}
    for dataset in _DATASETS:
        paths = raw_paths.get(dataset)
        if type(paths) is not tuple or not paths:
            raise ValueError
        for raw_path in paths:
            path = Path(raw_path)
            request_directory = path.parent.name
            if (
                path.name != "data.parquet"
                or path.parent.parent.name != dataset
                or not request_directory.startswith("request=")
            ):
                raise ValueError
            request_id = request_directory.removeprefix("request=")
            if not _is_hex64(request_id):
                raise ValueError
            relative = (
                f"raw/tushare/{dataset}/request={request_id}/data.parquet"
            )
            if relative in path_by_relative:
                raise ValueError
            path_by_relative[relative] = path

    plan = audit.get("plan_closure")
    if type(plan) is not dict or type(plan.get("catalog_sha256")) is not str:
        raise ValueError
    catalog_sha256 = cast(str, plan["catalog_sha256"])
    grouped: dict[str, list[_CompleteRequest]] = {dataset: [] for dataset in _DATASETS}
    schemas: dict[str, _SourceSchema] = {}
    evidence: list[dict[str, Any]] = []
    for raw_entry in cast(list[object], evidence_value):
        if type(raw_entry) is not dict:
            raise ValueError
        entry = cast(dict[str, Any], raw_entry)
        raw_dataset = entry.get("dataset")
        raw_request_id = entry.get("request_id")
        raw_relative = entry.get("relative_file")
        if (
            type(raw_dataset) is not str
            or raw_dataset not in _DATASETS
            or type(raw_request_id) is not str
            or not _is_hex64(raw_request_id)
            or type(raw_relative) is not str
            or raw_relative
            != f"raw/tushare/{raw_dataset}/request={raw_request_id}/data.parquet"
        ):
            raise ValueError
        dataset = raw_dataset
        request_id = raw_request_id
        relative = raw_relative
        if relative not in path_by_relative:
            raise ValueError
        path = path_by_relative.pop(relative)
        raw_schema = entry.get("schema")
        required = entry.get("required_economic_types")
        if type(raw_schema) is not list or type(required) is not dict:
            raise ValueError
        schema: list[tuple[str, str]] = []
        names: set[str] = set()
        for raw_column in cast(list[object], raw_schema):
            if type(raw_column) is not dict or set(raw_column) != {"name", "logical_type"}:
                raise ValueError
            column = cast(dict[str, Any], raw_column)
            name = column.get("name")
            logical_type = column.get("logical_type")
            if (
                type(name) is not str
                or not name
                or name in names
                or type(logical_type) is not str
                or not logical_type
            ):
                raise ValueError
            names.add(name)
            schema.append((name, logical_type))
        economic_types: dict[str, str] = {}
        for field, logical_type in cast(dict[str, Any], required).items():
            if type(field) is not str or type(logical_type) is not str:
                raise ValueError
            economic_types[field] = logical_type
        schemas[relative] = _SourceSchema(
            relative_path=relative,
            schema=tuple(schema),
            economic_types=economic_types,
        )
        grouped[dataset].append(
            _CompleteRequest(
                request_id=request_id,
                dataset=dataset,
                catalog_sha256=catalog_sha256,
                symbol="",
                start_date="",
                end_date="",
                rows=0,
                max_rows=1,
                checksum_sha256="0" * 64,
                metadata_sha256="0" * 64,
                columns=tuple(name for name, _ in schema),
                parquet_path=path,
                relative_path=relative,
            )
        )
        evidence.append(dict(entry))
    if path_by_relative or any(not grouped[dataset] for dataset in _DATASETS):
        raise ValueError
    return grouped, _FlowSourceIdentity(
        evidence=tuple(evidence), schemas=schemas, untokenizable=()
    )


def _snapshot_b1_group_union(
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
    projections: list[str] = []
    for _, items in sorted(grouped.items(), key=lambda pair: pair[0]):
        b1_projection = _projection_for_schema_group(
            dataset=dataset,
            group=sorted(items, key=lambda item: item.relative_path),
            source_identity=source_identity,
        )
        projections.append(
            "SELECT "
            + _projection_sql(dataset, economic_prefix="_flow_projected_")
            + f" FROM ({b1_projection}) AS _flow_snapshot_group"
        )
    if not projections:
        raise ValueError
    return " UNION ALL ".join(projections)


def _publish(
    *, data_root: Path, plan_report_path: Path, catalog_path: Path, threads: int
) -> TushareFinancialSnapshot:
    root = _resolved_data_root(data_root)
    if type(threads) is not int or not 1 <= threads <= 2:
        raise ValueError
    audit = audit_tushare_financials(
        data_root=root,
        plan_report_path=plan_report_path,
        catalog_path=catalog_path,
        threads=threads,
        verify_bytes=True,
    )
    _validate_audit(audit)
    raw_paths = _raw_paths(root, audit=audit)
    _snapshot_b1_inputs(audit=audit, raw_paths=raw_paths)
    snapshot_id = _source_identity(audit)
    snapshots = root / "clean" / "tushare_financials" / "snapshots"
    snapshots.mkdir(parents=True, exist_ok=True)
    _require_plain_dir(snapshots)
    output = snapshots / snapshot_id
    if output.exists():
        return _verify_snapshot(output, expected_snapshot_id=snapshot_id, reused=True)
    temp = snapshots / f".{snapshot_id}.tmp-{os.getpid()}-{secrets.token_hex(8)}"
    temp.mkdir()
    temp_identity = _directory_identity(temp)
    try:
        manifest = _build_temp_snapshot(
            temp=temp,
            snapshot_id=snapshot_id,
            audit=audit,
            raw_paths=raw_paths,
            threads=threads,
        )
        post = audit_tushare_financials(
            data_root=root,
            plan_report_path=plan_report_path,
            catalog_path=catalog_path,
            threads=threads,
            verify_bytes=True,
        )
        if post != audit:
            raise ValueError
        _write_exclusive(temp / "manifest.json", _canonical(manifest))
        _verify_snapshot(temp, expected_snapshot_id=snapshot_id, reused=False)
        try:
            commit_directory_noreplace(temp, output)
        except M3ReleaseError as error:
            if error.code != "G1_RELEASE_CONCURRENT_PUBLISH":
                raise
            _remove_owned_temp(temp, snapshots=snapshots, expected_identity=temp_identity)
            return _verify_snapshot(output, expected_snapshot_id=snapshot_id, reused=True)
    except BaseException:
        _remove_owned_temp(temp, snapshots=snapshots, expected_identity=temp_identity)
        raise
    return _verify_snapshot(output, expected_snapshot_id=snapshot_id, reused=False)


def _build_temp_snapshot(
    *,
    temp: Path,
    snapshot_id: str,
    audit: Mapping[str, Any],
    raw_paths: Mapping[str, tuple[str, ...]],
    threads: int,
) -> dict[str, Any]:
    audit_raw = _canonical(audit)
    _write_exclusive(temp / "audit.json", audit_raw)
    entries = [_file_entry(temp / "audit.json", temp, rows=None)]
    dataset_rows: dict[str, int] = {}
    complete_by_dataset, source_identity = _snapshot_b1_inputs(
        audit=audit, raw_paths=raw_paths
    )
    for dataset in _DATASETS:
        connection = duckdb.connect(":memory:")
        try:
            connection.execute(f"SET threads={threads}")
            connection.execute("SET enable_progress_bar=false")
            connection.execute("SET preserve_insertion_order=false")
            connection.execute(
                "CREATE TEMP TABLE financial_raw AS "
                + _snapshot_b1_group_union(
                    dataset=dataset,
                    complete=complete_by_dataset[dataset],
                    source_identity=source_identity,
                )
            )
            years = [
                cast(str, row[0])
                for row in connection.execute(
                    "SELECT DISTINCT substr(CAST(end_date AS VARCHAR),1,4) "
                    "FROM financial_raw ORDER BY 1"
                ).fetchall()
            ]
            rows = 0
            for year in years:
                if len(year) != 4 or not year.isdigit():
                    raise ValueError
                path = temp / f"dataset={dataset}" / f"year={year}.parquet"
                _copy_query(
                    connection,
                    f"SELECT * FROM financial_raw "
                    f"WHERE substr(CAST(end_date AS VARCHAR),1,4)='{year}' "
                    f"ORDER BY {_order_sql(dataset)}",
                    path,
                )
                frame = pl.read_parquet(path)
                _validate_partition(frame, dataset=dataset, year=int(year))
                rows += frame.height
                entries.append(_file_entry(path, temp, rows=frame.height))
            dataset_rows[dataset] = rows
        finally:
            connection.close()
    expected_rows = {
        dataset: cast(
            int, cast(Mapping[str, Any], audit["datasets"])[dataset]["quality"]["raw_rows"]
        )
        for dataset in _DATASETS
    }
    if dataset_rows != expected_rows:
        raise ValueError
    entries.sort(key=lambda item: cast(str, item["relative_path"]))
    return {
        "schema_version": _SNAPSHOT_SCHEMA,
        "projection_version": _PROJECTION_VERSION,
        "snapshot_id": snapshot_id,
        "source_identity": snapshot_id,
        "audit_schema_version": audit["schema_version"],
        "audit_sha256": _sha(audit_raw),
        "provenance_model": audit["plan_closure"]["provenance_model"],
        "provenance_limitation": audit["plan_closure"]["provenance_limitation"],
        "plan_report_sha256": audit["plan_closure"]["plan_report_sha256"],
        "instrument_file_set_sha256": audit["plan_closure"]["instrument_inventory"][
            "file_set_sha256"
        ],
        "instrument_logical_frame_sha256": audit["plan_closure"]["instrument_inventory"][
            "logical_frame_sha256"
        ],
        "request_set_sha256": audit["plan_closure"]["request_set_sha256"],
        "request_counts": audit["plan_closure"]["request_counts"],
        "request_count": cast(Mapping[str, Any], audit["raw_closure"])["complete_request_count"],
        "dataset_rows": dataset_rows,
        "files": entries,
    }


def _verify_snapshot(
    root: Path, *, expected_snapshot_id: str, reused: bool
) -> TushareFinancialSnapshot:
    _require_plain_dir(root)
    manifest_raw = _read_regular(root / "manifest.json")
    manifest = json.loads(manifest_raw)
    dataset_rows = manifest.get("dataset_rows") if type(manifest) is dict else None
    request_counts = manifest.get("request_counts") if type(manifest) is dict else None
    request_count = manifest.get("request_count") if type(manifest) is dict else None
    if (
        type(manifest) is not dict
        or set(manifest)
        != {
            "schema_version",
            "projection_version",
            "snapshot_id",
            "source_identity",
            "audit_schema_version",
            "audit_sha256",
            "provenance_model",
            "provenance_limitation",
            "plan_report_sha256",
            "instrument_file_set_sha256",
            "instrument_logical_frame_sha256",
            "request_set_sha256",
            "request_counts",
            "request_count",
            "dataset_rows",
            "files",
        }
        or manifest_raw != _canonical(manifest)
        or manifest.get("schema_version") != _SNAPSHOT_SCHEMA
        or manifest.get("projection_version") != _PROJECTION_VERSION
        or manifest.get("snapshot_id") != expected_snapshot_id
        or manifest.get("source_identity") != expected_snapshot_id
        or manifest.get("audit_schema_version") != _AUDIT_SCHEMA_VERSION
        or not _is_hex64(manifest.get("audit_sha256"))
        or manifest.get("provenance_model") != PROVENANCE_MODEL
        or manifest.get("provenance_limitation") != PROVENANCE_LIMITATION
        or not _is_hex64(manifest.get("plan_report_sha256"))
        or not _is_hex64(manifest.get("instrument_file_set_sha256"))
        or not _is_hex64(manifest.get("instrument_logical_frame_sha256"))
        or not _is_hex64(manifest.get("request_set_sha256"))
        or type(request_counts) is not dict
        or set(cast(dict[str, Any], request_counts)) != set(_DATASETS)
        or any(
            type(cast(dict[str, Any], request_counts)[dataset]) is not int
            or cast(dict[str, Any], request_counts)[dataset] < 0
            for dataset in _DATASETS
        )
        or type(request_count) is not int
        or request_count < 0
        or type(dataset_rows) is not dict
        or set(dataset_rows) != set(_DATASETS)
        or any(type(value) is not int or value < 0 for value in dataset_rows.values())
    ):
        raise ValueError
    files = manifest.get("files")
    if type(files) is not list or not files:
        raise ValueError
    expected_files = {"manifest.json"}
    observed_rows = {dataset: 0 for dataset in _DATASETS}
    audit: dict[str, Any] | None = None
    previous = ""
    for raw_entry in files:
        if type(raw_entry) is not dict or set(raw_entry) != {
            "relative_path",
            "rows",
            "size_bytes",
            "sha256",
        }:
            raise ValueError
        entry = cast(dict[str, Any], raw_entry)
        if (
            type(entry.get("relative_path")) is not str
            or type(entry.get("size_bytes")) is not int
            or entry.get("size_bytes", 0) < 0
            or not _is_hex64(entry.get("sha256"))
            or (
                entry.get("relative_path") != "audit.json"
                and (
                    type(entry.get("rows")) is not int
                    or entry.get("rows", 0) < 0
                )
            )
            or (
                entry.get("relative_path") == "audit.json"
                and entry.get("rows") is not None
            )
        ):
            raise ValueError
        selector = _relative(entry["relative_path"]).as_posix()
        if selector <= previous or selector in expected_files:
            raise ValueError
        previous = selector
        expected_files.add(selector)
        path = root / _relative(selector)
        payload = _read_regular(path)
        if len(payload) != entry["size_bytes"] or _sha(payload) != entry["sha256"]:
            raise ValueError
        if selector == "audit.json":
            audit = json.loads(payload)
            if (
                type(audit) is not dict
                or payload != _canonical(audit)
                or entry["rows"] is not None
                or _sha(payload) != manifest["audit_sha256"]
            ):
                raise ValueError
            _validate_audit(audit)
            if _source_identity(audit) != expected_snapshot_id:
                raise ValueError
            plan_closure = cast(Mapping[str, Any], audit["plan_closure"])
            inventory = cast(Mapping[str, Any], plan_closure["instrument_inventory"])
            if (
                manifest["provenance_model"] != plan_closure["provenance_model"]
                or manifest["provenance_limitation"]
                != plan_closure["provenance_limitation"]
                or manifest["plan_report_sha256"] != plan_closure["plan_report_sha256"]
                or manifest["instrument_file_set_sha256"]
                != inventory["file_set_sha256"]
                or manifest["instrument_logical_frame_sha256"]
                != inventory["logical_frame_sha256"]
                or manifest["request_set_sha256"] != plan_closure["request_set_sha256"]
                or manifest["request_counts"] != plan_closure["request_counts"]
            ):
                raise ValueError
            if (
                manifest["request_count"]
                != cast(Mapping[str, Any], audit["raw_closure"])[
                    "complete_request_count"
                ]
                or manifest["request_count"]
                != sum(cast(dict[str, int], request_counts).values())
            ):
                raise ValueError
            continue
        dataset, year = _partition_selector(selector)
        frame = pl.read_parquet(path)
        _validate_partition(frame, dataset=dataset, year=year)
        if entry["rows"] != frame.height:
            raise ValueError
        observed_rows[dataset] += frame.height
    if audit is None or _tree_files(root) != expected_files:
        raise ValueError
    if observed_rows != dataset_rows:
        raise ValueError
    reports = cast(Mapping[str, Any], audit["datasets"])
    if any(
        observed_rows[dataset] != reports[dataset]["quality"]["raw_rows"] for dataset in _DATASETS
    ):
        raise ValueError
    rows_tuple = tuple((dataset, observed_rows[dataset]) for dataset in _DATASETS)
    return TushareFinancialSnapshot(
        root=root,
        snapshot_id=expected_snapshot_id,
        manifest_sha256=_sha(manifest_raw),
        audit_sha256=cast(str, manifest["audit_sha256"]),
        dataset_rows=rows_tuple,
        reused=reused,
    )


def _validate_audit(value: Mapping[str, Any]) -> None:
    if (
        set(value)
        != {
            "schema_version",
            "status",
            "verify_bytes",
            "plan_closure",
            "active_lease_count",
             "raw_closure",
             "datasets",
             "blocking_issues",
             "flow_semantics",
             "publication_allowed",
        }
        or value.get("schema_version") != _AUDIT_SCHEMA_VERSION
        or value.get("status") != "READY"
        or value.get("verify_bytes") is not True
        or value.get("publication_allowed") is not True
        or value.get("blocking_issues") != []
        or type(value.get("active_lease_count")) is not int
        or value.get("active_lease_count") != 0
        or type(value.get("plan_closure")) is not dict
        or type(value.get("datasets")) is not dict
        or type(value.get("raw_closure")) is not dict
    ):
        raise ValueError
    plan = cast(Mapping[str, Any], value["plan_closure"])
    inventory = plan.get("instrument_inventory") if type(plan) is dict else None
    counts = plan.get("request_counts") if type(plan) is dict else None
    if (
        set(plan)
        != {
            "schema_version",
            "provenance_model",
            "provenance_limitation",
            "plan_report_sha256",
            "plan_schema_version",
            "planned_as_of",
            "catalog_version",
            "catalog_sha256",
            "permission_report_sha256",
            "instrument_inventory",
            "request_counts",
            "request_set_sha256",
        }
        or plan.get("schema_version") != PLAN_CLOSURE_SCHEMA
        or plan.get("provenance_model") != PROVENANCE_MODEL
        or plan.get("provenance_limitation") != PROVENANCE_LIMITATION
        or plan.get("plan_schema_version") != PLAN_SCHEMA
        or type(plan.get("planned_as_of")) is not str
        or type(plan.get("catalog_version")) is not str
        or not cast(str, plan.get("catalog_version"))
        or any(
            not _is_hex64(plan.get(name))
            for name in (
                "plan_report_sha256",
                "catalog_sha256",
                "permission_report_sha256",
                "request_set_sha256",
            )
        )
        or type(inventory) is not dict
        or inventory.get("schema_version") != INVENTORY_CLOSURE_SCHEMA
        or not _is_hex64(inventory.get("file_set_sha256"))
        or not _is_hex64(inventory.get("logical_frame_sha256"))
        or type(inventory.get("stock_count")) is not int
        or inventory.get("stock_count", 0) <= 0
        or type(inventory.get("files")) is not list
        or type(counts) is not dict
        or set(counts) != set(_DATASETS)
        or any(type(counts[name]) is not int or counts[name] <= 0 for name in _DATASETS)
    ):
        raise ValueError
    inventory_files = cast(list[object], inventory["files"])
    previous = ""
    for raw_entry in inventory_files:
        if type(raw_entry) is not dict or set(raw_entry) != {
            "relative_path",
            "size_bytes",
            "sha256",
        }:
            raise ValueError
        entry = cast(dict[str, Any], raw_entry)
        relative_path = entry.get("relative_path")
        if (
            type(relative_path) is not str
            or relative_path <= previous
            or not relative_path.startswith("clean/instrument/market=")
            or not relative_path.endswith("/data.parquet")
            or type(entry.get("size_bytes")) is not int
            or entry.get("size_bytes", 0) <= 0
            or not _is_hex64(entry.get("sha256"))
        ):
            raise ValueError
        previous = relative_path
    if not inventory_files or _sha(
        _canonical([INVENTORY_CLOSURE_SCHEMA, inventory_files])
    ) != inventory["file_set_sha256"]:
        raise ValueError
    raw_closure = cast(Mapping[str, Any], value["raw_closure"])
    if (
        set(raw_closure)
        != {
            "schema_version",
            "complete_request_count",
            "catalog_sha256s",
            "request_set_sha256",
        }
        or raw_closure.get("schema_version") != "tushare-financial-raw-closure-v1"
        or type(raw_closure.get("complete_request_count")) is not int
        or raw_closure.get("complete_request_count") != sum(counts.values())
        or raw_closure.get("catalog_sha256s") != [plan["catalog_sha256"]]
        or not _is_hex64(raw_closure.get("request_set_sha256"))
    ):
        raise ValueError
    reports = cast(Mapping[str, Any], value["datasets"])
    if set(reports) != set(_DATASETS):
        raise ValueError
    for dataset in _DATASETS:
        report = reports[dataset]
        status_counts = report.get("status_counts") if type(report) is dict else None
        request_count = report.get("request_count") if type(report) is dict else None
        complete_rows = report.get("complete_rows") if type(report) is dict else None
        if (
            type(status_counts) is not dict
            or set(status_counts) != {"COMPLETE"}
            or type(status_counts.get("COMPLETE")) is not int
            or status_counts.get("COMPLETE") != counts[dataset]
            or type(request_count) is not int
            or request_count != counts[dataset]
            or request_count <= 0
            or type(complete_rows) is not int
            or complete_rows < 0
        ):
            raise ValueError
        quality = report.get("quality") if type(report) is dict else None
        if (
            type(quality) is not dict
        ):
            raise ValueError
        _validate_quality_domain(dataset=dataset, quality=quality)
        if complete_rows != quality["raw_rows"]:
            raise ValueError
        _validate_dimension_evidence(dataset=dataset, quality=quality)
    flow = cast(Mapping[str, Any], value["flow_semantics"])
    if (
        type(flow.get("source_type_evidence")) is not list
        or len(cast(list[object], flow["source_type_evidence"]))
        != raw_closure["complete_request_count"]
        or flow.get("status") != "PASS"
    ):
        raise ValueError
    _validate_flow_semantics(flow)
    evidence = cast(list[object], flow["source_type_evidence"])
    for dataset in _DATASETS:
        _validate_quality_evidence(
            dataset=dataset,
            quality=cast(Mapping[str, Any], reports[dataset]["quality"]),
            evidence=evidence,
        )


def _validate_quality_evidence(
    *, dataset: str, quality: Mapping[str, Any], evidence: list[object]
) -> None:
    if type(quality) is not dict or set(quality) != _QUALITY_KEYS:
        raise ValueError
    digests = quality.get("column_set_sha256s")
    if (
        type(quality.get("column_set_count")) is not int
        or cast(int, quality["column_set_count"]) < 0
        or type(digests) is not list
        or len(digests) != quality.get("column_set_count")
        or any(type(item) is not str or not _is_hex64(item) for item in digests)
        or len(set(digests)) != len(digests)
        or cast(list[str], digests) != sorted(cast(list[str], digests))
    ):
        raise ValueError
    union = quality.get("required_numeric_union_types")
    fields = _ECONOMIC_COLUMNS[dataset]
    if type(union) is not dict or tuple(union) != fields:
        raise ValueError
    for field in fields:
        value = union.get(field)
        if type(value) is not str or not value:
            raise ValueError
        parts = value.split("|")
        if (
            any(
                not part or _canonical_logical_type(part) != part
                for part in parts
            )
            or len(parts) != len(set(parts))
            or parts != sorted(parts)
        ):
            raise ValueError
    dataset_entries = [
        cast(Mapping[str, Any], item)
        for item in evidence
        if type(item) is dict and item.get("dataset") == dataset
    ]
    if not dataset_entries:
        raise ValueError
    expected_digests: list[str] = []
    expected_types: dict[str, list[str]] = {field: [] for field in fields}
    for entry in dataset_entries:
        schema = entry.get("schema")
        required = entry.get("required_economic_types")
        if type(schema) is not list or type(required) is not dict:
            raise ValueError
        names: list[str] = []
        for raw_column in cast(list[object], schema):
            if type(raw_column) is not dict:
                raise ValueError
            column = cast(Mapping[str, Any], raw_column)
            name = column.get("name")
            if type(name) is not str:
                raise ValueError
            names.append(name)
        expected_digests.append(
            hashlib.sha256(json.dumps(names, separators=(",", ":")).encode()).hexdigest()
        )
        for field in fields:
            logical_type = required.get(field)
            if type(logical_type) is not str:
                raise ValueError
            expected_types[field].append(logical_type)
    if cast(list[str], digests) != sorted(set(expected_digests)):
        raise ValueError
    expected_union = {
        field: "|".join(sorted(set(types))) for field, types in expected_types.items()
    }
    if dict(union) != expected_union:
        raise ValueError


def _validate_quality_domain(*, dataset: str, quality: Mapping[str, Any]) -> None:
    counter_names = (
        "raw_rows",
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
        "required_numeric_parse_rows",
        "required_numeric_nonfinite_rows",
        "invalid_report_type_rows",
        "invalid_comp_type_rows",
        "same_available_duplicate_groups",
        "required_economic_conflict_groups",
        "revision_chain_groups",
        "column_set_count",
        "eligible_rows",
        "quarantined_rows",
    )
    if any(
        type(quality.get(name)) is not int or cast(int, quality[name]) < 0
        for name in counter_names
    ):
        raise ValueError
    raw_rows = cast(int, quality["raw_rows"])
    eligible_rows = cast(int, quality["eligible_rows"])
    quarantined_rows = cast(int, quality["quarantined_rows"])
    if eligible_rows > raw_rows or quarantined_rows != raw_rows - eligible_rows:
        raise ValueError
    structural_names = (
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
    if any(quality[name] != 0 for name in structural_names):
        raise ValueError
    parse_rows = cast(int, quality["required_numeric_parse_rows"])
    nonfinite_rows = cast(int, quality["required_numeric_nonfinite_rows"])
    if dataset in {"cashflow", "income"}:
        if (
            max(parse_rows, nonfinite_rows) > quarantined_rows
            or quarantined_rows > parse_rows + nonfinite_rows
        ):
            raise ValueError
        return
    if (
        parse_rows != 0
        or nonfinite_rows != 0
        or eligible_rows != raw_rows
        or quarantined_rows != 0
    ):
        raise ValueError


def _validate_flow_semantics(flow: Mapping[str, Any]) -> None:
    expected_keys = {
        "status",
        "flow_decimal_absolute_tolerance",
        "minimum_current_symbols",
        "minimum_fiscal_years",
        "minimum_comparable_observations",
        "source_type_evidence",
        "flow_source_type_evidence_sha256",
        "normalized_projection_contract",
        "token_algorithm",
        "token_algorithm_version",
        "buckets",
    }
    if (
        type(flow) is not dict
        or set(flow) != expected_keys
        or flow.get("flow_decimal_absolute_tolerance")
        != _FLOW_DECIMAL_ABSOLUTE_TOLERANCE_TEXT
        or flow.get("minimum_current_symbols") != _FLOW_MINIMUM_CURRENT_SYMBOLS
        or flow.get("minimum_fiscal_years") != _FLOW_MINIMUM_FISCAL_YEARS
        or flow.get("minimum_comparable_observations")
        != _FLOW_MINIMUM_COMPARABLE_OBSERVATIONS
        or flow.get("normalized_projection_contract")
        != _FLOW_NORMALIZED_PROJECTION_CONTRACT
        or flow.get("token_algorithm") != _FLOW_TOKEN_ALGORITHM
        or flow.get("token_algorithm_version") != _FLOW_TOKEN_ALGORITHM_VERSION
        or not _is_hex64(flow.get("flow_source_type_evidence_sha256"))
    ):
        raise ValueError
    evidence = flow.get("source_type_evidence")
    if type(evidence) is not list:
        raise ValueError
    _validate_source_type_evidence(cast(list[object], evidence))
    status = flow.get("status")
    buckets = flow.get("buckets")
    if status == "NOT_EVALUATED":
        if buckets != []:
            raise ValueError
        if evidence == []:
            if flow.get("flow_source_type_evidence_sha256") != _FLOW_EARLY_EMPTY_SOURCE_EVIDENCE_SHA256:
                raise ValueError
        elif _flow_source_evidence_sha256(
            cast(list[Mapping[str, Any]], evidence)
        ) != flow.get("flow_source_type_evidence_sha256"):
            raise ValueError
        return
    if _flow_source_evidence_sha256(cast(list[Mapping[str, Any]], evidence)) != flow.get(
        "flow_source_type_evidence_sha256"
    ):
        raise ValueError
    if status not in {"PASS", "INSUFFICIENT", "CONTRADICTED"} or type(buckets) is not list:
        raise ValueError
    expected_buckets = [
        (dataset, field, fiscal_bucket)
        for dataset, field in _FLOW_FIELDS
        for fiscal_bucket in _FLOW_BUCKETS
    ]
    if len(buckets) != len(expected_buckets):
        raise ValueError
    statuses: list[str] = []
    for raw_bucket, expected in zip(cast(list[object], buckets), expected_buckets):
        if type(raw_bucket) is not dict:
            raise ValueError
        bucket = cast(Mapping[str, Any], raw_bucket)
        _validate_flow_bucket(bucket=bucket, expected=expected)
        _validate_flow_derived_bounds(bucket)
        statuses.append(cast(str, bucket["status"]))
    expected_status = (
        "CONTRADICTED"
        if "CONTRADICTED" in statuses
        else "PASS"
        if all(item == "PASS" for item in statuses)
        else "INSUFFICIENT"
    )
    if status != expected_status:
        raise ValueError


def _validate_flow_derived_bounds(bucket: Mapping[str, Any]) -> None:
    distinct_symbols = cast(int, bucket["distinct_symbols"])
    current_type1_candidates = cast(int, bucket["current_type1_candidates"])
    fiscal_years = cast(int, bucket["fiscal_years"])
    comparable_observations = cast(int, bucket["comparable_observations"])
    if (
        distinct_symbols > current_type1_candidates
        or fiscal_years > comparable_observations
        or (
            comparable_observations == 0
            and fiscal_years != 0
        )
    ):
        raise ValueError


def _validate_source_type_evidence(entries: list[object]) -> None:
    previous: tuple[int, str] | None = None
    seen_paths: set[str] = set()
    seen_request_keys: set[tuple[str, str]] = set()
    for raw_entry in entries:
        if type(raw_entry) is not dict:
            raise ValueError
        entry = cast(Mapping[str, Any], raw_entry)
        if set(entry) != {
            "dataset",
            "request_id",
            "relative_file",
            "schema",
            "required_economic_types",
        }:
            raise ValueError
        dataset = entry.get("dataset")
        request_id = entry.get("request_id")
        relative_file = entry.get("relative_file")
        if (
            type(dataset) is not str
            or dataset not in _DATASETS
            or type(request_id) is not str
            or not _is_hex64(request_id)
            or type(relative_file) is not str
            or relative_file
            != f"raw/tushare/{dataset}/request={request_id}/data.parquet"
            or relative_file in seen_paths
            or (dataset, request_id) in seen_request_keys
        ):
            raise ValueError
        order = (_DATASETS.index(dataset), relative_file)
        if previous is not None and order <= previous:
            raise ValueError
        previous = order
        seen_paths.add(relative_file)
        seen_request_keys.add((dataset, request_id))
        schema = entry.get("schema")
        if type(schema) is not list or not schema:
            raise ValueError
        schema_names: set[str] = set()
        schema_types: dict[str, str] = {}
        for raw_column in cast(list[object], schema):
            if type(raw_column) is not dict or set(raw_column) != {"name", "logical_type"}:
                raise ValueError
            column = cast(Mapping[str, Any], raw_column)
            name = column.get("name")
            logical_type = column.get("logical_type")
            if (
                type(name) is not str
                or not name
                or name in schema_names
                or type(logical_type) is not str
                or not logical_type
                or _canonical_logical_type(logical_type) != logical_type
            ):
                raise ValueError
            schema_names.add(name)
            schema_types[name] = logical_type
        if not _STRUCTURAL_COLUMNS[dataset] <= schema_names:
            raise ValueError
        required = entry.get("required_economic_types")
        fields = dict(_economic_columns_for_dataset(dataset))
        if type(required) is not dict or set(required) != set(fields):
            raise ValueError
        for field in fields:
            logical_type = required.get(field)
            if (
                type(logical_type) is not str
                or _canonical_logical_type(logical_type) != logical_type
                or field not in schema_names
                or schema_types.get(field) != logical_type
                or _is_untokenizable_logical_type(logical_type)
            ):
                raise ValueError


def _economic_columns_for_dataset(dataset: str) -> tuple[tuple[str, str], ...]:
    return tuple((field, field) for field in _ECONOMIC_COLUMNS[dataset])


def _validate_flow_bucket(
    *, bucket: Mapping[str, Any], expected: tuple[str, str, str]
) -> None:
    bucket_keys = {
        "dataset",
        "field",
        "fiscal_bucket",
        "chain_applicable",
        "current_type1_candidates",
        "distinct_symbols",
        "fiscal_years",
        "synchronized_type2_pairs",
        "previous_chain_eligible",
        "missing_type2",
        "missing_previous",
        "latest_current_conflicts",
        "latest_type2_conflicts",
        "latest_previous_conflicts",
        "available_date_drift",
        "missing_operands",
        "invalid_numeric_operands",
        "nonfinite_operands",
        "float64_cent_resolution_lost",
        "comparable_observations",
        "mismatch_count",
        "status",
    }
    if (
        set(bucket) != bucket_keys
        or (bucket.get("dataset"), bucket.get("field"), bucket.get("fiscal_bucket"))
        != expected
        or bucket.get("chain_applicable") is not (expected[2] != "Q1")
    ):
        raise ValueError
    count_names = (
        "current_type1_candidates",
        "distinct_symbols",
        "fiscal_years",
        "synchronized_type2_pairs",
        "missing_type2",
        "latest_current_conflicts",
        "latest_type2_conflicts",
        "latest_previous_conflicts",
        "available_date_drift",
        "missing_operands",
        "invalid_numeric_operands",
        "nonfinite_operands",
        "float64_cent_resolution_lost",
        "comparable_observations",
        "mismatch_count",
    )
    for name in count_names:
        if type(bucket.get(name)) is not int or cast(int, bucket[name]) < 0:
            raise ValueError
    if expected[2] == "Q1":
        if bucket.get("previous_chain_eligible") is not None or bucket.get("missing_previous") is not None:
            raise ValueError
    else:
        for name in ("previous_chain_eligible", "missing_previous"):
            if type(bucket.get(name)) is not int or cast(int, bucket[name]) < 0:
                raise ValueError
    if type(bucket.get("status")) is not str:
        raise ValueError
    current = cast(int, bucket["current_type1_candidates"])
    synchronized = cast(int, bucket["synchronized_type2_pairs"])
    if current != sum(
        cast(int, bucket[name])
        for name in (
            "latest_current_conflicts",
            "missing_type2",
            "latest_type2_conflicts",
            "available_date_drift",
        )
    ) + synchronized:
        raise ValueError
    numeric_total = sum(
        cast(int, bucket[name])
        for name in (
            "missing_operands",
            "invalid_numeric_operands",
            "nonfinite_operands",
            "float64_cent_resolution_lost",
            "comparable_observations",
        )
    )
    if expected[2] == "Q1":
        if synchronized != numeric_total:
            raise ValueError
    else:
        previous_eligible = cast(int, bucket["previous_chain_eligible"])
        if synchronized != previous_eligible + cast(int, bucket["missing_previous"]) + cast(
            int, bucket["latest_previous_conflicts"]
        ) or previous_eligible != numeric_total:
            raise ValueError
    if cast(int, bucket["mismatch_count"]) > cast(int, bucket["comparable_observations"]):
        raise ValueError
    expected_status = _expected_flow_bucket_status(bucket)
    if bucket.get("status") != expected_status:
        raise ValueError


def _expected_flow_bucket_status(bucket: Mapping[str, Any]) -> str:
    mismatch = cast(int, bucket["mismatch_count"])
    if mismatch > 0:
        return "CONTRADICTED"
    current = cast(int, bucket["current_type1_candidates"])
    synchronized = cast(int, bucket["synchronized_type2_pairs"])
    pair_coverage = current > 0 and 5 * synchronized >= 4 * current
    if bucket["chain_applicable"]:
        eligible = cast(int, bucket["previous_chain_eligible"])
        chain_coverage = synchronized > 0 and 5 * eligible >= 4 * synchronized
    else:
        chain_coverage = True
    if (
        pair_coverage
        and chain_coverage
        and cast(int, bucket["distinct_symbols"]) >= _FLOW_MINIMUM_CURRENT_SYMBOLS
        and cast(int, bucket["fiscal_years"]) >= _FLOW_MINIMUM_FISCAL_YEARS
        and cast(int, bucket["comparable_observations"])
        >= _FLOW_MINIMUM_COMPARABLE_OBSERVATIONS
    ):
        return "PASS"
    return "INSUFFICIENT"


def _validate_dimension_evidence(*, dataset: str, quality: Mapping[str, Any]) -> None:
    invalid_report = quality.get("invalid_report_type_rows")
    invalid_comp = quality.get("invalid_comp_type_rows")
    report_counts = _validated_counts(
        quality.get("report_type_counts"), keys=("value",)
    )
    comp_counts = _validated_counts(quality.get("comp_type_counts"), keys=("value",))
    pair_counts = _validated_counts(
        quality.get("report_type_comp_type_counts"),
        keys=("report_type", "comp_type"),
    )
    if type(invalid_report) is not int or type(invalid_comp) is not int:
        raise ValueError
    if dataset not in _STATEMENTS:
        if (
            invalid_report != 0
            or invalid_comp != 0
            or report_counts
            or comp_counts
            or pair_counts
        ):
            raise ValueError
        return
    if invalid_report != 0 or invalid_comp != 0:
        raise ValueError
    raw_rows = quality.get("raw_rows")
    if type(raw_rows) is not int or raw_rows < 0:
        raise ValueError
    report_marginal = {key[0]: count for key, count in report_counts.items()}
    comp_marginal = {key[0]: count for key, count in comp_counts.items()}
    pair_report: dict[str, int] = {}
    pair_comp: dict[str, int] = {}
    for (report_type, comp_type), count in pair_counts.items():
        pair_report[report_type] = pair_report.get(report_type, 0) + count
        pair_comp[comp_type] = pair_comp.get(comp_type, 0) + count
    if (
        sum(report_marginal.values()) != raw_rows
        or sum(comp_marginal.values()) != raw_rows
        or sum(pair_counts.values()) != raw_rows
        or pair_report != report_marginal
        or pair_comp != comp_marginal
    ):
        raise ValueError


def _validated_counts(
    value: object, *, keys: tuple[str, ...]
) -> dict[tuple[str, ...], int]:
    if type(value) is not list:
        raise ValueError
    result: dict[tuple[str, ...], int] = {}
    previous: tuple[str, ...] | None = None
    expected = {*keys, "rows"}
    for raw_item in cast(list[object], value):
        if type(raw_item) is not dict or set(raw_item) != expected:
            raise ValueError
        item = cast(dict[str, Any], raw_item)
        dimension = tuple(item.get(key) for key in keys)
        rows = item.get("rows")
        if (
            any(not _is_dimension_code(part) for part in dimension)
            or type(rows) is not int
            or rows <= 0
            or (previous is not None and dimension <= previous)
        ):
            raise ValueError
        typed_dimension = cast(tuple[str, ...], dimension)
        result[typed_dimension] = rows
        previous = typed_dimension
    return result


def _is_dimension_code(value: object) -> bool:
    return (
        type(value) is str
        and bool(value)
        and all("0" <= character <= "9" for character in value)
    )


def _source_identity(audit: Mapping[str, Any]) -> str:
    return _sha(_canonical([_SNAPSHOT_SCHEMA, _PROJECTION_VERSION, audit]))


def _raw_paths(root: Path, *, audit: Mapping[str, Any]) -> dict[str, tuple[str, ...]]:
    ledger = root / "run_state" / "tushare_bulk" / "state.sqlite"
    uri = f"file:{ledger.resolve(strict=True).as_posix()}?mode=ro"
    placeholders = ",".join("?" for _ in _DATASETS)
    with sqlite3.connect(uri, uri=True) as connection:
        rows = connection.execute(
            "SELECT request_id,dataset,status FROM requests "
            f"WHERE dataset IN ({placeholders}) ORDER BY dataset,request_id",
            _DATASETS,
        ).fetchall()
    reports = cast(Mapping[str, Any], audit["datasets"])
    result: dict[str, list[str]] = {dataset: [] for dataset in _DATASETS}
    for request_id, dataset, status in rows:
        if dataset not in _DATASETS or status != "COMPLETE" or not _is_hex64(request_id):
            raise ValueError
        path = root / "raw" / "tushare" / dataset / f"request={request_id}" / "data.parquet"
        if path.is_symlink() or not path.is_file():
            raise ValueError
        result[dataset].append(str(path))
    if any(
        len(result[dataset]) != reports[dataset]["request_count"] or not result[dataset]
        for dataset in _DATASETS
    ):
        raise ValueError
    return {dataset: tuple(paths) for dataset, paths in result.items()}


def _projection_sql(dataset: str, *, economic_prefix: str = "") -> str:
    common = (
        "CAST(ts_code AS VARCHAR) AS symbol,"
        "CAST(strptime(CAST(ann_date AS VARCHAR),'%Y%m%d') AS DATE) AS ann_date,"
    )
    if dataset in _STATEMENTS:
        common += (
            "CAST(try_strptime(CAST(f_ann_date AS VARCHAR),'%Y%m%d') AS DATE) AS f_ann_date,"
            "CAST(greatest(strptime(CAST(ann_date AS VARCHAR),'%Y%m%d'),"
            "try_strptime(CAST(f_ann_date AS VARCHAR),'%Y%m%d')) AS DATE) AS available_date,"
            "CAST(strptime(CAST(end_date AS VARCHAR),'%Y%m%d') AS DATE) AS end_date,"
            "CAST(report_type AS VARCHAR) AS report_type,"
            "CAST(comp_type AS VARCHAR) AS comp_type,"
            "CAST(update_flag AS VARCHAR) AS update_flag,"
        )
    else:
        common += (
            "CAST(strptime(CAST(ann_date AS VARCHAR),'%Y%m%d') AS DATE) AS available_date,"
            "CAST(strptime(CAST(end_date AS VARCHAR),'%Y%m%d') AS DATE) AS end_date,"
        )
    economics = "".join(
        f"TRY_CAST({economic_prefix}{name} AS DOUBLE) AS {name},"
        for name in _ECONOMIC_COLUMNS[dataset]
    )
    return common + economics + "'tushare' AS source"


def _order_sql(dataset: str) -> str:
    if dataset in _STATEMENTS:
        return "symbol,end_date,available_date,report_type,comp_type,update_flag,ann_date"
    return "symbol,end_date,available_date,ann_date"


def _validate_partition(frame: pl.DataFrame, *, dataset: str, year: int) -> None:
    columns = ["symbol", "ann_date"]
    string = pl.String()
    date = pl.Date()
    number = pl.Float64()
    schema: dict[str, pl.DataType] = {"symbol": string, "ann_date": date}
    if dataset in _STATEMENTS:
        columns.extend(
            [
                "f_ann_date",
                "available_date",
                "end_date",
                "report_type",
                "comp_type",
                "update_flag",
            ]
        )
        schema |= {
            "f_ann_date": date,
            "available_date": date,
            "end_date": date,
            "report_type": string,
            "comp_type": string,
            "update_flag": string,
        }
    else:
        columns.extend(["available_date", "end_date"])
        schema |= {"available_date": date, "end_date": date}
    columns.extend(_ECONOMIC_COLUMNS[dataset])
    schema |= {name: number for name in _ECONOMIC_COLUMNS[dataset]}
    columns.append("source")
    schema["source"] = string
    if frame.is_empty() or frame.columns != columns or frame.schema != schema:
        raise ValueError
    structural = [
        "symbol",
        "ann_date",
        "available_date",
        "end_date",
        "source",
    ]
    if dataset in _STATEMENTS:
        structural.extend(["report_type", "comp_type", "update_flag"])
    if frame.select(
        pl.any_horizontal(*[pl.col(name).is_null() for name in structural]).any()
    ).item():
        raise ValueError
    if (
        frame.get_column("end_date").dt.year().unique().to_list() != [year]
        or frame.filter(
            ~pl.col("symbol").str.contains(r"^[0-9]{6}\.(SH|SZ)$")
            | (pl.col("end_date") > pl.col("available_date"))
            | (pl.col("source") != "tushare")
        ).height
    ):
        raise ValueError
    if dataset in _STATEMENTS:
        recomputed = frame.select(
            pl.max_horizontal("ann_date", "f_ann_date").alias("available_date")
        ).get_column("available_date")
        if (
            not recomputed.equals(frame.get_column("available_date"))
            or frame.filter(~pl.col("update_flag").is_in(["0", "1"])).height
        ):
            raise ValueError
    keys = _order_sql(dataset).split(",")
    if not frame.select(keys).equals(frame.select(keys).sort(keys)):
        raise ValueError
    for name in _ECONOMIC_COLUMNS[dataset]:
        if frame.filter(pl.col(name).is_not_null() & ~pl.col(name).is_finite()).height:
            raise ValueError


def _copy_query(connection: duckdb.DuckDBPyConnection, query: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise ValueError
    selector = path.as_posix().replace("'", "''")
    connection.execute(
        f"COPY ({query}) TO '{selector}' (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 100000)"
    )
    _fsync_file(path)


def _partition_selector(selector: str) -> tuple[str, int]:
    parts = selector.split("/")
    if (
        len(parts) != 2
        or not parts[0].startswith("dataset=")
        or not parts[1].startswith("year=")
        or not parts[1].endswith(".parquet")
    ):
        raise ValueError
    dataset = parts[0].removeprefix("dataset=")
    year_text = parts[1].removeprefix("year=").removesuffix(".parquet")
    if dataset not in _DATASETS or len(year_text) != 4 or not year_text.isdigit():
        raise ValueError
    return dataset, int(year_text)


def _file_entry(path: Path, root: Path, *, rows: int | None) -> dict[str, Any]:
    payload = _read_regular(path)
    return {
        "relative_path": path.relative_to(root).as_posix(),
        "rows": rows,
        "size_bytes": len(payload),
        "sha256": _sha(payload),
    }


def _relative(value: object) -> Path:
    if type(value) is not str:
        raise ValueError
    pure = PurePosixPath(cast(str, value))
    if (
        pure.is_absolute()
        or not pure.parts
        or len(pure.parts) > 2
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise ValueError
    return Path(*pure.parts)


def _tree_files(root: Path) -> set[str]:
    result: set[str] = set()
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError
        if path.is_file():
            result.add(path.relative_to(root).as_posix())
        elif not path.is_dir():
            raise ValueError
    return result


def _require_plain_dir(path: Path) -> None:
    mode = path.lstat().st_mode
    if path.is_symlink() or not stat.S_ISDIR(mode):
        raise ValueError


def _read_regular(path: Path) -> bytes:
    if path.is_symlink() or not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError
    before = path.stat()
    raw = path.read_bytes()
    after = path.stat()
    if not os.path.samestat(before, after) or len(raw) != after.st_size:
        raise ValueError
    return raw


def _write_exclusive(path: Path, payload: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _fsync_file(path: Path) -> None:
    with path.open("r+b") as handle:
        os.fsync(handle.fileno())


def _directory_identity(path: Path) -> tuple[int, int]:
    value = path.stat()
    return value.st_dev, value.st_ino


def _remove_owned_temp(path: Path, *, snapshots: Path, expected_identity: tuple[int, int]) -> None:
    if not path.exists():
        return
    if (
        path.parent.resolve(strict=True) != snapshots.resolve(strict=True)
        or not path.name.startswith(".")
        or _directory_identity(path) != expected_identity
    ):
        raise ValueError
    shutil.rmtree(path)


def _resolved_data_root(path: Path) -> Path:
    if not isinstance(path, Path):
        raise ValueError
    root = path.resolve(strict=True)
    _require_plain_dir(root)
    return root


def _is_hex64(value: object) -> bool:
    return type(value) is str and len(cast(str, value)) == 64 and set(cast(str, value)) <= _HEX


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="发布 Tushare 财务四表不可覆盖 clean snapshot")
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--plan-report", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=2)
    args = parser.parse_args(argv)
    result = publish_tushare_financial_snapshot(
        data_root=args.data_root or resolve_data_root(),
        plan_report_path=args.plan_report,
        catalog_path=args.catalog,
        threads=args.threads,
    )
    print(
        _canonical(
            {
                "dataset_rows": dict(result.dataset_rows),
                "audit_sha256": result.audit_sha256,
                "manifest_sha256": result.manifest_sha256,
                "reused": result.reused,
                "root": result.root.as_posix(),
                "snapshot_id": result.snapshot_id,
            }
        ).decode("utf-8"),
        end="",
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "TushareFinancialPublishError",
    "TushareFinancialSnapshot",
    "publish_tushare_financial_snapshot",
    "verify_tushare_financial_snapshot",
]
