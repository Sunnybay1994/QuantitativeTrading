"""Publish and verify immutable clean snapshots derived from ``daily_basic`` raw."""

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

from quant.data.audit_tushare_daily_basic import (
    SCHEMA_VERSION as _AUDIT_SCHEMA_VERSION,
    audit_tushare_daily_basic,
)
from quant.data.m3_release import M3ReleaseError, commit_directory_noreplace
from quant.domain import DailyBasic1dSchema
from quant.settings import resolve_data_root

_SNAPSHOT_SCHEMA = "tushare-daily-basic-clean-snapshot-v1"
_PROJECTION_VERSION = "tushare-daily-basic-clean-projection-v1"
_HEX64 = frozenset("0123456789abcdef")
_QUARANTINE_COLUMNS = ["symbol", "trade_date", "reason"]


class TushareDailyBasicPublishError(ValueError):
    """Stable sanitized daily-basic publication failure."""

    def __init__(self) -> None:
        super().__init__("TUSHARE_DAILY_BASIC_PUBLISH_INVALID")


@dataclass(frozen=True, slots=True)
class TushareDailyBasicSnapshot:
    """Verified summary of one immutable clean snapshot."""

    root: Path
    snapshot_id: str
    manifest_sha256: str
    rows: int
    quarantine_rows: int
    reused: bool


def publish_tushare_daily_basic_snapshot(
    *, data_root: Path, threads: int = 2
) -> TushareDailyBasicSnapshot:
    """Build or strictly reuse the clean snapshot for the completed raw ledger."""
    try:
        return _publish(data_root=data_root, threads=threads)
    except Exception:
        pass
    raise TushareDailyBasicPublishError() from None


def verify_tushare_daily_basic_snapshot(
    *, data_root: Path, snapshot_id: str
) -> TushareDailyBasicSnapshot:
    """Verify one existing snapshot without consulting mutable current raw."""
    try:
        root = _resolved_data_root(data_root)
        if not _is_hex64(snapshot_id):
            raise ValueError
        return _verify_snapshot(
            root / "clean" / "tushare_daily_basic" / "snapshots" / snapshot_id,
            expected_snapshot_id=snapshot_id,
            reused=True,
        )
    except Exception:
        pass
    raise TushareDailyBasicPublishError() from None


def _publish(*, data_root: Path, threads: int) -> TushareDailyBasicSnapshot:
    root = _resolved_data_root(data_root)
    if type(threads) is not int or not 1 <= threads <= 8:
        raise ValueError
    audit = audit_tushare_daily_basic(
        data_root=root, threads=threads, verify_bytes=True
    )
    _validate_audit(audit)
    snapshot_id = _source_identity(audit)
    snapshots = root / "clean" / "tushare_daily_basic" / "snapshots"
    snapshots.mkdir(parents=True, exist_ok=True)
    _require_plain_dir(snapshots)
    output = snapshots / snapshot_id
    if output.exists():
        return _verify_snapshot(
            output, expected_snapshot_id=snapshot_id, reused=True
        )
    temp = snapshots / f".{snapshot_id}.tmp-{os.getpid()}-{secrets.token_hex(8)}"
    temp.mkdir()
    temp_identity = _directory_identity(temp)
    try:
        manifest = _build_temp_snapshot(
            temp=temp,
            snapshot_id=snapshot_id,
            audit=audit,
            raw_paths=_raw_paths(
                root, expected_count=cast(int, audit["ledger"]["request_count"])
            ),
            threads=threads,
        )
        post = audit_tushare_daily_basic(
            data_root=root, threads=threads, verify_bytes=True
        )
        if post != audit:
            raise ValueError
        _write_exclusive(temp / "manifest.json", _canonical(manifest))
        _fsync_file(temp / "manifest.json")
        _verify_snapshot(
            temp, expected_snapshot_id=snapshot_id, reused=False
        )
        try:
            commit_directory_noreplace(temp, output)
        except M3ReleaseError as error:
            if error.code != "G1_RELEASE_CONCURRENT_PUBLISH":
                raise
            _remove_owned_temp(
                temp, snapshots=snapshots, expected_identity=temp_identity
            )
            return _verify_snapshot(
                output, expected_snapshot_id=snapshot_id, reused=True
            )
    except BaseException:
        _remove_owned_temp(
            temp, snapshots=snapshots, expected_identity=temp_identity
        )
        raise
    return _verify_snapshot(
        output, expected_snapshot_id=snapshot_id, reused=False
    )


def _build_temp_snapshot(
    *,
    temp: Path,
    snapshot_id: str,
    audit: Mapping[str, Any],
    raw_paths: list[str],
    threads: int,
) -> dict[str, Any]:
    audit_raw = _canonical(audit)
    _write_exclusive(temp / "audit.json", audit_raw)
    _fsync_file(temp / "audit.json")
    entries = [_file_entry(temp / "audit.json", temp, rows=None)]
    connection = duckdb.connect(":memory:")
    try:
        connection.execute(f"SET threads={threads}")
        connection.execute("SET enable_progress_bar=false")
        connection.execute("SET preserve_insertion_order=false")
        connection.read_parquet(raw_paths).create_view("daily_basic_raw")
        years = [
            cast(str, row[0])
            for row in connection.execute(
                "SELECT DISTINCT substr(trade_date,1,4) FROM daily_basic_raw "
                f"WHERE {_classification_case()}='ELIGIBLE' ORDER BY 1"
            ).fetchall()
        ]
        for year in years:
            if len(year) != 4 or not year.isdigit():
                raise ValueError
            path = temp / f"year={year}" / "data.parquet"
            _copy_query(
                connection,
                f"""
                SELECT ts_code AS symbol,
                  CAST(strptime(trade_date, '%Y%m%d') AS DATE) AS trade_date,
                  CAST(close AS DOUBLE) AS close,
                  CAST(turnover_rate AS DOUBLE) AS turnover_rate,
                  CAST(turnover_rate_f AS DOUBLE) AS turnover_rate_free,
                  CAST(volume_ratio AS DOUBLE) AS volume_ratio,
                  CAST(pe AS DOUBLE) AS pe,
                  CAST(pe_ttm AS DOUBLE) AS pe_ttm,
                  CAST(pb AS DOUBLE) AS pb,
                  CAST(ps AS DOUBLE) AS ps,
                  CAST(ps_ttm AS DOUBLE) AS ps_ttm,
                  CAST(dv_ratio AS DOUBLE) AS dividend_yield,
                  CAST(dv_ttm AS DOUBLE) AS dividend_yield_ttm,
                  CAST(total_share AS DOUBLE) * 10000.0 AS total_shares,
                  CAST(float_share AS DOUBLE) * 10000.0 AS float_shares,
                  CAST(free_share AS DOUBLE) * 10000.0 AS free_float_shares,
                  CAST(total_mv AS DOUBLE) * 10000.0 AS total_market_value,
                  CAST(circ_mv AS DOUBLE) * 10000.0 AS circulating_market_value,
                  'tushare' AS source
                FROM daily_basic_raw
                WHERE {_classification_case()}='ELIGIBLE'
                  AND substr(trade_date,1,4)='{year}'
                ORDER BY trade_date, symbol, source
                """,
                path,
            )
            _fsync_file(path)
            frame = DailyBasic1dSchema.validate(pl.read_parquet(path))
            if frame.is_empty() or not _keys_sorted(frame):
                raise ValueError
            entries.append(_file_entry(path, temp, rows=frame.height))
        quarantine = temp / "quarantine.parquet"
        _copy_query(
            connection,
            f"""
            SELECT ts_code AS symbol, trade_date, {_classification_case()} AS reason
            FROM daily_basic_raw
            WHERE {_classification_case()}!='ELIGIBLE'
            ORDER BY symbol, trade_date, reason
            """,
            quarantine,
        )
        _fsync_file(quarantine)
        quarantine_frame = pl.read_parquet(quarantine)
        _validate_quarantine(quarantine_frame)
        entries.append(
            _file_entry(quarantine, temp, rows=quarantine_frame.height)
        )
    finally:
        connection.close()
    entries.sort(key=lambda item: cast(str, item["relative_path"]))
    quality = cast(Mapping[str, Any], audit["quality"])
    clean_rows = sum(
        cast(int, entry["rows"])
        for entry in entries
        if cast(str, entry["relative_path"]).startswith("year=")
    )
    quarantine_rows = cast(
        int,
        next(
            entry for entry in entries
            if entry["relative_path"] == "quarantine.parquet"
        )["rows"],
    )
    if (
        clean_rows != quality["eligible_rows"]
        or quarantine_rows != quality["quarantined_rows"]
        or clean_rows + quarantine_rows != quality["raw_rows"]
    ):
        raise ValueError
    return {
        "schema_version": _SNAPSHOT_SCHEMA,
        "projection_version": _PROJECTION_VERSION,
        "snapshot_id": snapshot_id,
        "source_identity": snapshot_id,
        "audit_schema_version": audit["schema_version"],
        "audit_sha256": _sha(audit_raw),
        "request_count": audit["ledger"]["request_count"],
        "raw_rows": quality["raw_rows"],
        "rows": clean_rows,
        "quarantine_rows": quarantine_rows,
        "files": entries,
    }


def _verify_snapshot(
    root: Path, *, expected_snapshot_id: str, reused: bool
) -> TushareDailyBasicSnapshot:
    _require_plain_dir(root)
    manifest_raw = _read_regular(root / "manifest.json")
    manifest = json.loads(manifest_raw)
    if (
        type(manifest) is not dict
        or manifest_raw != _canonical(manifest)
        or manifest.get("schema_version") != _SNAPSHOT_SCHEMA
        or manifest.get("projection_version") != _PROJECTION_VERSION
        or manifest.get("snapshot_id") != expected_snapshot_id
        or manifest.get("source_identity") != expected_snapshot_id
        or manifest.get("audit_schema_version") != _AUDIT_SCHEMA_VERSION
        or not _is_hex64(manifest.get("audit_sha256"))
        or type(manifest.get("request_count")) is not int
        or type(manifest.get("raw_rows")) is not int
        or type(manifest.get("rows")) is not int
        or type(manifest.get("quarantine_rows")) is not int
    ):
        raise ValueError
    files = manifest.get("files")
    if type(files) is not list or not files:
        raise ValueError
    expected_files = {"manifest.json"}
    clean_rows = quarantine_rows = 0
    audit: dict[str, Any] | None = None
    previous = ""
    for raw_entry in files:
        if type(raw_entry) is not dict or set(raw_entry) != {
            "relative_path", "rows", "size_bytes", "sha256"
        }:
            raise ValueError
        entry = cast(dict[str, Any], raw_entry)
        selector = _relative(entry["relative_path"]).as_posix()
        if selector <= previous or selector in expected_files:
            raise ValueError
        previous = selector
        expected_files.add(selector)
        payload = _read_regular(root / _relative(selector))
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
        elif selector == "quarantine.parquet":
            frame = pl.read_parquet(root / _relative(selector))
            _validate_quarantine(frame)
            if entry["rows"] != frame.height:
                raise ValueError
            quarantine_rows = frame.height
        elif selector.startswith("year=") and selector.endswith("/data.parquet"):
            frame = DailyBasic1dSchema.validate(
                pl.read_parquet(root / _relative(selector))
            )
            if frame.is_empty() or entry["rows"] != frame.height or not _keys_sorted(frame):
                raise ValueError
            year = selector.split("/", 1)[0].removeprefix("year=")
            if frame.get_column("trade_date").dt.year().unique().to_list() != [int(year)]:
                raise ValueError
            clean_rows += frame.height
        else:
            raise ValueError
    if audit is None or _tree_files(root) != expected_files:
        raise ValueError
    quality = cast(Mapping[str, Any], audit["quality"])
    if (
        clean_rows != manifest["rows"]
        or quarantine_rows != manifest["quarantine_rows"]
        or clean_rows + quarantine_rows != manifest["raw_rows"]
        or clean_rows != quality["eligible_rows"]
        or quarantine_rows != quality["quarantined_rows"]
        or manifest["request_count"] != audit["ledger"]["request_count"]
    ):
        raise ValueError
    return TushareDailyBasicSnapshot(
        root=root,
        snapshot_id=expected_snapshot_id,
        manifest_sha256=_sha(manifest_raw),
        rows=clean_rows,
        quarantine_rows=quarantine_rows,
        reused=reused,
    )


def _classification_case() -> str:
    return """CASE
      WHEN NOT regexp_matches(ts_code, '^[0-9]{6}\\.(SH|SZ)$')
        THEN 'UNSUPPORTED_MARKET'
      WHEN (free_share IS NOT NULL AND free_share > float_share)
        OR float_share > total_share THEN 'SHARE_RELATION_INVALID'
      WHEN circ_mv > total_mv THEN 'MARKET_VALUE_RELATION_INVALID'
      ELSE 'ELIGIBLE' END"""


def _validate_audit(value: Mapping[str, Any]) -> None:
    if (
        value.get("schema_version") != _AUDIT_SCHEMA_VERSION
        or value.get("dataset") != "daily_basic"
        or value.get("status") != "READY"
        or value.get("verify_bytes") is not True
        or value.get("blocking_issues") != []
        or type(value.get("ledger")) is not dict
        or type(value.get("quality")) is not dict
    ):
        raise ValueError


def _source_identity(audit: Mapping[str, Any]) -> str:
    return _sha(_canonical([_SNAPSHOT_SCHEMA, _PROJECTION_VERSION, audit]))


def _raw_paths(root: Path, *, expected_count: int) -> list[str]:
    ledger = root / "run_state" / "tushare_bulk" / "state.sqlite"
    uri = f"file:{ledger.resolve(strict=True).as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        rows = connection.execute(
            "SELECT request_id,status FROM requests WHERE dataset='daily_basic' "
            "ORDER BY request_id"
        ).fetchall()
    if len(rows) != expected_count or any(status != "COMPLETE" for _, status in rows):
        raise ValueError
    paths: list[str] = []
    for request_id, _ in rows:
        path = root / "raw" / "tushare" / "daily_basic" / f"request={request_id}" / "data.parquet"
        if path.is_symlink() or not path.is_file():
            raise ValueError
        paths.append(str(path))
    if not paths:
        raise ValueError
    return paths


def _validate_quarantine(frame: pl.DataFrame) -> None:
    if frame.columns != _QUARANTINE_COLUMNS or frame.schema != {
        "symbol": pl.String,
        "trade_date": pl.String,
        "reason": pl.String,
    }:
        raise ValueError
    if frame.filter(
        ~pl.col("reason").is_in(
            [
                "UNSUPPORTED_MARKET",
                "SHARE_RELATION_INVALID",
                "MARKET_VALUE_RELATION_INVALID",
            ]
        )
    ).height or not frame.equals(frame.sort(_QUARANTINE_COLUMNS)):
        raise ValueError


def _copy_query(
    connection: duckdb.DuckDBPyConnection, query: str, path: Path
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise ValueError
    selector = path.as_posix().replace("'", "''")
    connection.execute(
        f"COPY ({query}) TO '{selector}' "
        "(FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 100000)"
    )


def _file_entry(path: Path, root: Path, *, rows: int | None) -> dict[str, Any]:
    payload = _read_regular(path)
    return {
        "relative_path": path.relative_to(root).as_posix(),
        "rows": rows,
        "size_bytes": len(payload),
        "sha256": _sha(payload),
    }


def _keys_sorted(frame: pl.DataFrame) -> bool:
    selected = frame.select(["trade_date", "symbol", "source"])
    return selected.equals(selected.sort(["trade_date", "symbol", "source"]))


def _relative(value: object) -> Path:
    if type(value) is not str:
        raise ValueError
    pure = PurePosixPath(cast(str, value))
    if pure.is_absolute() or not pure.parts or len(pure.parts) > 2 or any(
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


def _remove_owned_temp(
    path: Path, *, snapshots: Path, expected_identity: tuple[int, int]
) -> None:
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
    return type(value) is str and len(cast(str, value)) == 64 and set(cast(str, value)) <= _HEX64


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="发布 Tushare daily_basic clean snapshot")
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--threads", type=int, default=2)
    args = parser.parse_args(argv)
    result = publish_tushare_daily_basic_snapshot(
        data_root=args.data_root or resolve_data_root(), threads=args.threads
    )
    print(
        _canonical(
            {
                "manifest_sha256": result.manifest_sha256,
                "quarantine_rows": result.quarantine_rows,
                "reused": result.reused,
                "root": result.root.as_posix(),
                "rows": result.rows,
                "snapshot_id": result.snapshot_id,
            }
        ).decode("utf-8"),
        end="",
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "TushareDailyBasicPublishError",
    "TushareDailyBasicSnapshot",
    "publish_tushare_daily_basic_snapshot",
    "verify_tushare_daily_basic_snapshot",
]
