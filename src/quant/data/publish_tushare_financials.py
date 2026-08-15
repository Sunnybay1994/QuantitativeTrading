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
            raw_paths=_raw_paths(root, audit=audit),
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
    for dataset in _DATASETS:
        connection = duckdb.connect(":memory:")
        try:
            connection.execute(f"SET threads={threads}")
            connection.execute("SET enable_progress_bar=false")
            connection.execute("SET preserve_insertion_order=false")
            connection.read_parquet(
                list(raw_paths[dataset]),
                union_by_name=True,
                hive_partitioning=False,
            ).create_view("financial_raw")
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
                    f"SELECT {_projection_sql(dataset)} FROM financial_raw "
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
        or type(manifest.get("request_counts")) is not dict
        or set(cast(dict[str, Any], manifest.get("request_counts"))) != set(_DATASETS)
        or type(manifest.get("request_count")) is not int
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
            "publication_allowed",
        }
        or value.get("schema_version") != _AUDIT_SCHEMA_VERSION
        or value.get("status") != "READY"
        or value.get("verify_bytes") is not True
        or value.get("publication_allowed") is not True
        or value.get("blocking_issues") != []
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
        quality = report.get("quality") if type(report) is dict else None
        if (
            type(quality) is not dict
            or report.get("status_counts") != {"COMPLETE": counts[dataset]}
            or report.get("request_count") != counts[dataset]
            or report.get("request_count", 0) <= 0
            or quality.get("eligible_rows") != quality.get("raw_rows")
            or quality.get("quarantined_rows") != 0
        ):
            raise ValueError


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


def _projection_sql(dataset: str) -> str:
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
        f"TRY_CAST({name} AS DOUBLE) AS {name}," for name in _ECONOMIC_COLUMNS[dataset]
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
