"""Publish a versioned clean snapshot from immutable Tushare bulk raw."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import shutil
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, cast

import duckdb
import polars as pl

from quant.data.audit_tushare_bulk_clean import (
    SCHEMA_VERSION as _AUDIT_SCHEMA_VERSION,
    _CLASSIFICATION_CASE,
    audit_tushare_bulk_clean_admission,
)
from quant.domain import Bar1dSchema
from quant.settings import resolve_data_root

_SNAPSHOT_SCHEMA = "tushare-bulk-clean-snapshot-v1"
_PROJECTION_VERSION = "tushare-bulk-clean-projection-v1"
_PLAN_SCHEMA = "tushare-bulk-scoped-clean-plan-v1"
_DATASETS = ("adj_factor", "daily", "fund_adj", "fund_daily")
_ASSETS = {"stock": ("daily", "adj_factor"), "fund": ("fund_daily", "fund_adj")}
_HEX64 = frozenset("0123456789abcdef")
_QUARANTINE_COLUMNS = ["asset", "raw_dataset", "symbol", "trade_date", "reason"]


class TushareBulkCleanPublishError(ValueError):
    """Stable sanitized clean publication failure."""

    def __init__(self) -> None:
        super().__init__("TUSHARE_BULK_CLEAN_PUBLISH_INVALID")


@dataclass(frozen=True, slots=True)
class TushareBulkCleanSnapshot:
    """Verified summary of one immutable scoped clean snapshot."""

    root: Path
    snapshot_id: str
    manifest_sha256: str
    stock_rows: int
    fund_rows: int
    quarantine_rows: int
    reused: bool


def publish_tushare_bulk_clean_snapshot(
    *, data_root: Path, threads: int = 2
) -> TushareBulkCleanSnapshot:
    """Build or strictly reuse the clean snapshot derived from current bulk raw."""
    try:
        return _publish(data_root=data_root, threads=threads)
    except Exception:
        pass
    raise TushareBulkCleanPublishError() from None


def verify_tushare_bulk_clean_snapshot(
    *, data_root: Path, snapshot_id: str
) -> TushareBulkCleanSnapshot:
    """Verify one existing snapshot without consulting mutable current raw."""
    try:
        root = _resolved_data_root(data_root)
        if not _is_hex64(snapshot_id):
            raise ValueError
        return _verify_snapshot(
            root / "clean" / "tushare_bulk" / "snapshots" / snapshot_id,
            expected_snapshot_id=snapshot_id,
            reused=True,
        )
    except Exception:
        pass
    raise TushareBulkCleanPublishError() from None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="发布 Tushare bulk scoped clean snapshot")
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--threads", type=int, default=2)
    args = parser.parse_args(argv)
    result = publish_tushare_bulk_clean_snapshot(
        data_root=resolve_data_root(args.data_root), threads=args.threads
    )
    print(
        _canonical(
            {
                "fund_rows": result.fund_rows,
                "manifest_sha256": result.manifest_sha256,
                "quarantine_rows": result.quarantine_rows,
                "reused": result.reused,
                "root": result.root.as_posix(),
                "snapshot_id": result.snapshot_id,
                "stock_rows": result.stock_rows,
            }
        ).decode("utf-8")
    )
    return 0


def _publish(*, data_root: Path, threads: int) -> TushareBulkCleanSnapshot:
    root = _resolved_data_root(data_root)
    if type(threads) is not int or not 1 <= threads <= 8:
        raise ValueError
    admission = audit_tushare_bulk_clean_admission(
        data_root=root, threads=threads, verify_bytes=True
    )
    _validate_admission(admission)
    source_identity = _source_identity(admission)
    snapshots = root / "clean" / "tushare_bulk" / "snapshots"
    snapshots.mkdir(parents=True, exist_ok=True)
    _require_plain_dir(snapshots)
    existing = _find_snapshot_for_source(snapshots, source_identity=source_identity)
    if existing is not None:
        return existing
    temp = snapshots / f".{source_identity}.tmp-{os.getpid()}-{secrets.token_hex(8)}"
    temp.mkdir()
    try:
        paths = _raw_paths(root, expected_count=cast(int, admission["request_count"]))
        manifest = _build_temp_snapshot(
            temp=temp,
            source_identity=source_identity,
            admission=admission,
            paths=paths,
            threads=threads,
        )
        post = audit_tushare_bulk_clean_admission(
            data_root=root, threads=threads, verify_bytes=True
        )
        if post != admission:
            raise ValueError
        snapshot_id = _manifest_snapshot_id(manifest)
        manifest["snapshot_id"] = snapshot_id
        _write_exclusive(temp / "manifest.json", _canonical(manifest))
        _fsync_file(temp / "manifest.json")
        _verify_snapshot(temp, expected_snapshot_id=snapshot_id, reused=False)
        output = snapshots / snapshot_id
        if output.exists():
            _remove_owned_temp(temp, snapshots=snapshots)
            return _verify_snapshot(
                output, expected_snapshot_id=snapshot_id, reused=True
            )
        temp.rename(output)
    except BaseException:
        _remove_owned_temp(temp, snapshots=snapshots)
        raise
    return _verify_snapshot(output, expected_snapshot_id=snapshot_id, reused=False)


def _build_temp_snapshot(
    *,
    temp: Path,
    source_identity: str,
    admission: Mapping[str, Any],
    paths: Mapping[str, list[str]],
    threads: int,
) -> dict[str, Any]:
    audit_raw = _canonical(admission)
    _write_exclusive(temp / "audit.json", audit_raw)
    _fsync_file(temp / "audit.json")
    entries: list[dict[str, Any]] = [
        _file_entry(temp / "audit.json", temp, rows=None, min_date=None, max_date=None)
    ]
    connection = duckdb.connect(":memory:")
    try:
        connection.execute(f"SET threads={threads}")
        connection.execute("SET enable_progress_bar=false")
        connection.execute("SET preserve_insertion_order=false")
        for dataset in _DATASETS:
            connection.from_parquet(paths[dataset]).create_view(dataset)
        for asset, (daily, factor) in _ASSETS.items():
            entries.extend(
                _write_asset_partitions(
                    connection=connection,
                    temp=temp,
                    asset=asset,
                    daily=daily,
                    factor=factor,
                )
            )
        quarantine = temp / "quarantine.parquet"
        _copy_query(connection, _quarantine_query(), quarantine)
        _fsync_file(quarantine)
        quarantine_frame = pl.read_parquet(quarantine)
        _validate_quarantine(quarantine_frame)
        entries.append(
            _file_entry(
                quarantine,
                temp,
                rows=quarantine_frame.height,
                min_date=None,
                max_date=None,
            )
        )
    finally:
        connection.close()
    entries.sort(key=lambda item: cast(str, item["relative_path"]))
    plan = cast(Mapping[str, Any], admission["scoped_clean_plan"])
    stock = cast(Mapping[str, Any], plan["stock_bar_1d"])
    fund = cast(Mapping[str, Any], plan["fund_bar_1d"])
    if (
        sum(cast(int, item["rows"]) for item in entries if _is_bar_entry(item, "stock"))
        != stock["eligible_rows"]
        or sum(cast(int, item["rows"]) for item in entries if _is_bar_entry(item, "fund"))
        != fund["eligible_rows"]
        or cast(int, next(item for item in entries if item["relative_path"] == "quarantine.parquet")["rows"])
        != cast(int, stock["quarantined_rows"]) + cast(int, fund["quarantined_rows"])
    ):
        raise ValueError
    return {
        "schema_version": _SNAPSHOT_SCHEMA,
        "projection_version": _PROJECTION_VERSION,
        "source_identity": source_identity,
        "raw_snapshot_sha256": admission["raw_snapshot_sha256"],
        "audit_schema_version": admission["schema_version"],
        "audit_sha256": _sha(audit_raw),
        "request_count": admission["request_count"],
        "stock_rows": stock["eligible_rows"],
        "fund_rows": fund["eligible_rows"],
        "quarantine_rows": cast(int, stock["quarantined_rows"])
        + cast(int, fund["quarantined_rows"]),
        "files": entries,
    }


def _write_asset_partitions(
    *,
    connection: duckdb.DuckDBPyConnection,
    temp: Path,
    asset: str,
    daily: str,
    factor: str,
) -> list[dict[str, Any]]:
    classified = _classified_query(daily=daily, factor=factor)
    years = [
        cast(str, row[0])
        for row in connection.execute(
            f"WITH classified AS ({classified}) "
            "SELECT DISTINCT substr(trade_date, 1, 4) FROM classified "
            "WHERE reason='ELIGIBLE' ORDER BY 1"
        ).fetchall()
    ]
    entries: list[dict[str, Any]] = []
    for year in years:
        if len(year) != 4 or not year.isdigit():
            raise ValueError
        path = temp / "bar_1d" / f"asset={asset}" / f"year={year}" / "data.parquet"
        query = f"""
        WITH classified AS ({classified})
        SELECT symbol,
          CAST(strptime(trade_date, '%Y%m%d') AS DATE) AS trade_date,
          CAST(open AS DOUBLE) AS open,
          CAST(high AS DOUBLE) AS high,
          CAST(low AS DOUBLE) AS low,
          CAST(close AS DOUBLE) AS close,
          CAST(vol AS DOUBLE) * 100.0 AS volume,
          CAST(amount AS DOUBLE) * 1000.0 AS amount,
          CAST(adj_factor AS DOUBLE) AS adj_factor,
          'tushare' AS source
        FROM classified
        WHERE reason='ELIGIBLE' AND substr(trade_date, 1, 4)='{year}'
        ORDER BY trade_date, symbol, source
        """
        _copy_query(connection, query, path)
        _fsync_file(path)
        frame = Bar1dSchema.validate(pl.read_parquet(path))
        if frame.is_empty() or not _keys_sorted(frame):
            raise ValueError
        dates = frame.get_column("trade_date")
        entries.append(
            _file_entry(
                path,
                temp,
                rows=frame.height,
                min_date=_date_text(dates.min()),
                max_date=_date_text(dates.max()),
            )
        )
    return entries


def _classified_query(*, daily: str, factor: str) -> str:
    if (daily, factor) not in set(_ASSETS.values()):
        raise ValueError
    return f"""
    SELECT d.ts_code AS symbol, d.trade_date, d.open, d.high, d.low, d.close,
      d.vol, d.amount, a.adj_factor, {_CLASSIFICATION_CASE} AS reason
    FROM {daily} d LEFT JOIN {factor} a
      ON d.ts_code=a.ts_code AND d.trade_date=a.trade_date
    """


def _quarantine_query() -> str:
    parts = []
    for asset, (daily, factor) in _ASSETS.items():
        classified = _classified_query(daily=daily, factor=factor)
        parts.append(
            f"SELECT '{asset}' AS asset, '{daily}' AS raw_dataset, symbol, "
            f"trade_date, reason FROM ({classified}) WHERE reason!='ELIGIBLE'"
        )
    return " UNION ALL ".join(parts) + " ORDER BY asset, raw_dataset, symbol, trade_date, reason"


def _raw_paths(root: Path, *, expected_count: int) -> dict[str, list[str]]:
    import sqlite3

    ledger = root / "run_state" / "tushare_bulk" / "state.sqlite"
    uri = f"file:{ledger.resolve(strict=True).as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        rows = connection.execute(
            "SELECT request_id,dataset,status FROM requests "
            "WHERE dataset IN ('adj_factor','daily','fund_adj','fund_daily') "
            "ORDER BY dataset,request_id"
        ).fetchall()
    if len(rows) != expected_count or any(row[2] != "COMPLETE" for row in rows):
        raise ValueError
    paths: dict[str, list[str]] = {dataset: [] for dataset in _DATASETS}
    for request_id, dataset, _ in rows:
        path = root / "raw" / "tushare" / dataset / f"request={request_id}" / "data.parquet"
        if path.is_symlink() or not path.is_file():
            raise ValueError
        paths[cast(str, dataset)].append(str(path))
    if any(not values for values in paths.values()):
        raise ValueError
    return paths


def _validate_admission(value: Mapping[str, Any]) -> None:
    if (
        value.get("schema_version") != _AUDIT_SCHEMA_VERSION
        or value.get("status") not in {"READY", "BLOCKED"}
        or not _is_hex64(value.get("raw_snapshot_sha256"))
        or type(value.get("request_count")) is not int
    ):
        raise ValueError
    plan = value.get("scoped_clean_plan")
    if (
        type(plan) is not dict
        or plan.get("schema_version") != _PLAN_SCHEMA
        or plan.get("status") != "READY"
    ):
        raise ValueError


def _source_identity(admission: Mapping[str, Any]) -> str:
    return _sha(
        _canonical(
            [
                _SNAPSHOT_SCHEMA,
                _PROJECTION_VERSION,
                admission["schema_version"],
                admission["raw_snapshot_sha256"],
                admission["scoped_clean_plan"],
            ]
        )
    )


def _manifest_snapshot_id(manifest: Mapping[str, Any]) -> str:
    if "snapshot_id" in manifest:
        body = {key: value for key, value in manifest.items() if key != "snapshot_id"}
    else:
        body = dict(manifest)
    return _sha(_canonical([_SNAPSHOT_SCHEMA, body]))


def _find_snapshot_for_source(
    snapshots: Path, *, source_identity: str
) -> TushareBulkCleanSnapshot | None:
    matches: list[TushareBulkCleanSnapshot] = []
    for child in sorted(snapshots.iterdir(), key=lambda item: item.name):
        if child.name.startswith("."):
            continue
        if not _is_hex64(child.name):
            raise ValueError
        manifest = json.loads(_read_regular(child / "manifest.json"))
        if type(manifest) is not dict:
            raise ValueError
        if manifest.get("source_identity") == source_identity:
            matches.append(
                _verify_snapshot(
                    child, expected_snapshot_id=child.name, reused=True
                )
            )
    if len(matches) > 1:
        raise ValueError
    return matches[0] if matches else None


def _verify_snapshot(
    root: Path, *, expected_snapshot_id: str, reused: bool
) -> TushareBulkCleanSnapshot:
    _require_plain_dir(root)
    manifest_path = root / "manifest.json"
    manifest_raw = _read_regular(manifest_path)
    manifest = json.loads(manifest_raw)
    if (
        type(manifest) is not dict
        or manifest_raw != _canonical(manifest)
        or manifest.get("schema_version") != _SNAPSHOT_SCHEMA
        or manifest.get("projection_version") != _PROJECTION_VERSION
        or manifest.get("snapshot_id") != expected_snapshot_id
        or not _is_hex64(manifest.get("source_identity"))
        or not _is_hex64(manifest.get("raw_snapshot_sha256"))
        or manifest.get("audit_schema_version") != _AUDIT_SCHEMA_VERSION
        or not _is_hex64(manifest.get("audit_sha256"))
        or type(manifest.get("request_count")) is not int
        or type(manifest.get("stock_rows")) is not int
        or type(manifest.get("fund_rows")) is not int
        or type(manifest.get("quarantine_rows")) is not int
        or _manifest_snapshot_id(manifest) != expected_snapshot_id
    ):
        raise ValueError
    files = manifest.get("files")
    if type(files) is not list or not files:
        raise ValueError
    expected = {"manifest.json"}
    physical: set[tuple[int, int]] = set()
    stock_rows = fund_rows = quarantine_rows = 0
    quarantine_reasons: dict[str, dict[str, int]] = {}
    admission: dict[str, Any] | None = None
    previous = ""
    for raw_entry in files:
        if type(raw_entry) is not dict:
            raise ValueError
        entry = cast(dict[str, Any], raw_entry)
        if set(entry) != {"relative_path", "rows", "min_date", "max_date", "size_bytes", "sha256"}:
            raise ValueError
        relative = _relative(cast(object, entry["relative_path"]))
        selector = relative.as_posix()
        if selector <= previous or selector in expected:
            raise ValueError
        previous = selector
        expected.add(selector)
        path = root / relative
        payload = _read_regular(path)
        identity = (path.stat().st_dev, path.stat().st_ino)
        if identity in physical:
            raise ValueError
        physical.add(identity)
        if len(payload) != entry["size_bytes"] or _sha(payload) != entry["sha256"]:
            raise ValueError
        rows = entry["rows"]
        if selector == "audit.json":
            audit = json.loads(payload)
            if type(audit) is not dict:
                raise ValueError
            if (
                rows is not None
                or payload != _canonical(audit)
                or _sha(payload) != manifest["audit_sha256"]
            ):
                raise ValueError
            _validate_admission(audit)
            if (
                audit["raw_snapshot_sha256"] != manifest["raw_snapshot_sha256"]
                or audit["request_count"] != manifest["request_count"]
                or _source_identity(audit) != manifest["source_identity"]
            ):
                raise ValueError
            admission = audit
        elif selector == "quarantine.parquet":
            frame = pl.read_parquet(path)
            _validate_quarantine(frame)
            if rows != frame.height:
                raise ValueError
            quarantine_rows = frame.height
            for asset, reason, count in frame.group_by(
                ["asset", "reason"]
            ).len().iter_rows():
                quarantine_reasons.setdefault(cast(str, asset), {})[
                    cast(str, reason)
                ] = cast(int, count)
        elif selector.startswith("bar_1d/"):
            frame = Bar1dSchema.validate(pl.read_parquet(path))
            if rows != frame.height or frame.is_empty() or not _keys_sorted(frame):
                raise ValueError
            dates = frame.get_column("trade_date")
            if entry["min_date"] != _date_text(dates.min()) or entry["max_date"] != _date_text(dates.max()):
                raise ValueError
            if "/asset=stock/" in f"/{selector}":
                stock_rows += frame.height
            elif "/asset=fund/" in f"/{selector}":
                fund_rows += frame.height
            else:
                raise ValueError
        else:
            raise ValueError
    if _tree_files(root) != expected:
        raise ValueError
    if admission is None:
        raise ValueError
    plan = cast(dict[str, Any], admission["scoped_clean_plan"])
    expected_stock = cast(dict[str, Any], plan["stock_bar_1d"])
    expected_fund = cast(dict[str, Any], plan["fund_bar_1d"])
    expected_reasons = {
        "stock": {
            key: value
            for key, value in cast(dict[str, int], expected_stock["reasons"]).items()
            if key != "ELIGIBLE"
        },
        "fund": {
            key: value
            for key, value in cast(dict[str, int], expected_fund["reasons"]).items()
            if key != "ELIGIBLE"
        },
    }
    expected_reasons = {key: value for key, value in expected_reasons.items() if value}
    if (
        stock_rows != manifest["stock_rows"]
        or fund_rows != manifest["fund_rows"]
        or quarantine_rows != manifest["quarantine_rows"]
        or stock_rows != expected_stock["eligible_rows"]
        or fund_rows != expected_fund["eligible_rows"]
        or quarantine_rows
        != cast(int, expected_stock["quarantined_rows"])
        + cast(int, expected_fund["quarantined_rows"])
        or quarantine_reasons != expected_reasons
    ):
        raise ValueError
    return TushareBulkCleanSnapshot(
        root=root,
        snapshot_id=expected_snapshot_id,
        manifest_sha256=_sha(manifest_raw),
        stock_rows=stock_rows,
        fund_rows=fund_rows,
        quarantine_rows=quarantine_rows,
        reused=reused,
    )


def _validate_quarantine(frame: pl.DataFrame) -> None:
    if frame.columns != _QUARANTINE_COLUMNS:
        raise ValueError
    if frame.schema != {
        "asset": pl.String,
        "raw_dataset": pl.String,
        "symbol": pl.String,
        "trade_date": pl.String,
        "reason": pl.String,
    }:
        raise ValueError
    if frame.filter(pl.col("reason") == "ELIGIBLE").height:
        raise ValueError
    assets = frame.get_column("asset").drop_nulls().unique().sort().to_list()
    if any(asset not in {"fund", "stock"} for asset in assets):
        raise ValueError
    if frame.filter(
        ((pl.col("asset") == "stock") & (pl.col("raw_dataset") != "daily"))
        | ((pl.col("asset") == "fund") & (pl.col("raw_dataset") != "fund_daily"))
    ).height:
        raise ValueError
    if not frame.equals(frame.sort(_QUARANTINE_COLUMNS)):
        raise ValueError


def _file_entry(
    path: Path,
    root: Path,
    *,
    rows: int | None,
    min_date: str | None,
    max_date: str | None,
) -> dict[str, Any]:
    payload = _read_regular(path)
    return {
        "relative_path": path.relative_to(root).as_posix(),
        "rows": rows,
        "min_date": min_date,
        "max_date": max_date,
        "size_bytes": len(payload),
        "sha256": _sha(payload),
    }


def _copy_query(connection: duckdb.DuckDBPyConnection, query: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise ValueError
    selector = path.as_posix().replace("'", "''")
    connection.execute(
        f"COPY ({query}) TO '{selector}' "
        "(FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 100000)"
    )


def _keys_sorted(frame: pl.DataFrame) -> bool:
    keys = ["trade_date", "symbol", "source"]
    selected = frame.select(keys)
    return selected.equals(selected.sort(keys))


def _is_bar_entry(entry: Mapping[str, Any], asset: str) -> bool:
    return cast(str, entry["relative_path"]).startswith(f"bar_1d/asset={asset}/")


def _date_text(value: object) -> str:
    if not hasattr(value, "isoformat"):
        raise ValueError
    result = value.isoformat()
    if type(result) is not str:
        raise ValueError
    return result


def _relative(value: object) -> Path:
    if type(value) is not str:
        raise ValueError
    pure = PurePosixPath(cast(str, value))
    if pure.is_absolute() or not pure.parts or len(pure.parts) > 4 or any(
        part in {"", ".", ".."} for part in pure.parts
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
    if (before.st_dev, before.st_ino, before.st_size) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
    ) or len(raw) != after.st_size:
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


def _remove_owned_temp(path: Path, *, snapshots: Path) -> None:
    if not path.exists():
        return
    resolved_parent = snapshots.resolve(strict=True)
    if path.parent.resolve(strict=True) != resolved_parent or not path.name.startswith("."):
        raise ValueError
    shutil.rmtree(path)


def _resolved_data_root(path: Path) -> Path:
    if not isinstance(path, Path):
        raise ValueError
    root = path.resolve(strict=True)
    _require_plain_dir(root)
    return root


def _is_hex64(value: object) -> bool:
    return type(value) is str and len(cast(str, value)) == 64 and set(cast(str, value)) <= _HEX64


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
