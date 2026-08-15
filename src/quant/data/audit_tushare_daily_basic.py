"""Read-only quality audit for the resumable Tushare ``daily_basic`` ledger."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb

from quant.settings import resolve_data_root

SCHEMA_VERSION = "tushare-daily-basic-audit-v2"
_RAW_CLOSURE_SCHEMA = "tushare-daily-basic-raw-closure-v1"
_DATASET = "daily_basic"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_RAW_COLUMNS = (
    "ts_code",
    "trade_date",
    "close",
    "turnover_rate",
    "turnover_rate_f",
    "volume_ratio",
    "pe",
    "pe_ttm",
    "pb",
    "ps",
    "ps_ttm",
    "dv_ratio",
    "dv_ttm",
    "total_share",
    "float_share",
    "free_share",
    "total_mv",
    "circ_mv",
)


@dataclass(frozen=True)
class _CompleteRequest:
    request_id: str
    catalog_sha256: str
    rows: int
    checksum_sha256: str
    metadata_sha256: str
    trade_date: str
    max_rows: int
    parquet_path: Path


def audit_tushare_daily_basic(
    *, data_root: Path, threads: int = 2, verify_bytes: bool = False
) -> dict[str, Any]:
    """Audit the completed ledger snapshot without mutating raw or run state."""
    try:
        return _audit_tushare_daily_basic(
            data_root=data_root, threads=threads, verify_bytes=verify_bytes
        )
    except Exception:
        pass
    raise ValueError("TUSHARE_DAILY_BASIC_AUDIT_INVALID") from None


def _audit_tushare_daily_basic(
    *, data_root: Path, threads: int, verify_bytes: bool
) -> dict[str, Any]:
    if (
        not isinstance(data_root, Path)
        or type(threads) is not int
        or not 1 <= threads <= 8
    ):
        raise ValueError("TUSHARE_DAILY_BASIC_AUDIT_INVALID")
    if type(verify_bytes) is not bool:
        raise ValueError("TUSHARE_DAILY_BASIC_AUDIT_INVALID")
    root = data_root.resolve(strict=True)
    ledger = root / "run_state" / "tushare_bulk" / "state.sqlite"
    ledger_rows = _read_ledger(ledger)
    if not ledger_rows:
        raise ValueError("TUSHARE_DAILY_BASIC_AUDIT_INVALID")

    status_counts = Counter(str(row[1]) for row in ledger_rows)
    complete = _load_complete_requests(root=root, rows=ledger_rows, verify_bytes=verify_bytes)
    quality = _quality_summary(complete, threads=threads)
    blocking: list[dict[str, Any]] = []

    for status in ("FAILED", "SPLIT_REQUIRED"):
        if status_counts[status]:
            blocking.append(
                {"code": f"LEDGER_{status}", "count": status_counts[status]}
            )
    if quality["silent_row_limit_hits"]:
        blocking.append(
            {
                "code": "SILENT_ROW_LIMIT_HIT",
                "count": quality["silent_row_limit_hits"],
            }
        )
    for field, code in (
        ("row_count_mismatch", "LEDGER_RAW_ROW_COUNT_MISMATCH"),
        ("duplicate_keys", "DUPLICATE_SYMBOL_DATE"),
        ("parameter_date_mismatches", "PARAMETER_DATE_MISMATCH"),
        ("critical_null_rows", "CRITICAL_NULL"),
        ("invalid_symbol_rows", "SYMBOL_FORMAT_INVALID"),
        ("invalid_trade_date_rows", "TRADE_DATE_FORMAT_INVALID"),
        ("nonfinite_rows", "NONFINITE_NUMERIC"),
        ("nonpositive_required_rows", "NONPOSITIVE_REQUIRED_VALUE"),
        ("negative_rate_rows", "NEGATIVE_RATE"),
    ):
        count = int(quality[field])
        if count:
            blocking.append({"code": code, "count": count})

    incomplete = sum(
        status_counts[name]
        for name in ("PENDING", "RUNNING", "RETRYABLE")
    )
    if blocking:
        status = "BLOCKED"
    elif incomplete:
        status = "COLLECTING"
    elif status_counts["COMPLETE"] == len(ledger_rows) and complete:
        status = "READY"
    else:
        status = "BLOCKED"
        blocking.append({"code": "LEDGER_STATE_INVALID", "count": 1})

    return {
        "schema_version": SCHEMA_VERSION,
        "dataset": _DATASET,
        "status": status,
        "verify_bytes": verify_bytes,
        "raw_closure": _raw_closure(complete),
        "ledger": {
            "request_count": len(ledger_rows),
            "status_counts": dict(sorted(status_counts.items())),
            "complete_rows": sum(item.rows for item in complete),
        },
        "quality": quality,
        "blocking_issues": blocking,
        "clean_scope": {
            "supported_markets": ["SH", "SZ"],
            "eligible_rows": quality["eligible_rows"],
            "quarantined_rows": quality["quarantined_rows"],
            "quarantine_reasons": quality["quarantine_reasons"],
            "raw_share_and_market_value_multiplier": 10_000,
            "raw_close_is_not_bar_authority": True,
        },
    }


def _read_ledger(ledger: Path) -> list[tuple[Any, ...]]:
    uri = f"file:{ledger.resolve(strict=True).as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        return connection.execute(
            "SELECT request_id, status, rows, checksum_sha256, parameters_json, "
            "max_rows, error_code, catalog_sha256 FROM requests "
            "WHERE dataset = ? ORDER BY request_id",
            (_DATASET,),
        ).fetchall()


def _load_complete_requests(
    *, root: Path, rows: list[tuple[Any, ...]], verify_bytes: bool
) -> list[_CompleteRequest]:
    complete: list[_CompleteRequest] = []
    raw_root = root / "raw" / "tushare" / _DATASET
    for (
        request_id,
        status,
        row_count,
        checksum,
        parameters_json,
        max_rows,
        _,
        catalog_sha256,
    ) in rows:
        if status != "COMPLETE":
            continue
        if (
            type(request_id) is not str
            or _HEX64.fullmatch(request_id) is None
            or type(row_count) is not int
            or row_count < 0
            or type(checksum) is not str
            or _HEX64.fullmatch(checksum) is None
            or type(catalog_sha256) is not str
            or _HEX64.fullmatch(catalog_sha256) is None
            or type(max_rows) is not int
            or max_rows <= 0
        ):
            raise ValueError("TUSHARE_DAILY_BASIC_AUDIT_INVALID")
        parameters = json.loads(parameters_json)
        trade_date = parameters.get("trade_date")
        if type(trade_date) is not str or re.fullmatch(r"\d{8}", trade_date) is None:
            raise ValueError("TUSHARE_DAILY_BASIC_AUDIT_INVALID")
        request_root = raw_root / f"request={request_id}"
        children = {path.name for path in request_root.iterdir()}
        if children != {"data.parquet", "metadata.json"}:
            raise ValueError("TUSHARE_DAILY_BASIC_AUDIT_INVALID")
        parquet = request_root / "data.parquet"
        metadata_path = request_root / "metadata.json"
        metadata_payload = metadata_path.read_bytes()
        metadata = json.loads(metadata_payload.decode("utf-8"))
        if (
            metadata.get("schema_version") != "request-raw-v1"
            or metadata.get("source") != "tushare"
            or metadata.get("table") != _DATASET
            or metadata.get("request_id") != request_id
            or metadata.get("snapshot_id") != request_id
            or metadata.get("parameters") != parameters
            or metadata.get("rows") != row_count
            or metadata.get("checksum_sha256") != checksum
            or metadata.get("columns") != list(_RAW_COLUMNS)
            or metadata.get("size_bytes") != parquet.stat().st_size
        ):
            raise ValueError("TUSHARE_DAILY_BASIC_AUDIT_INVALID")
        if verify_bytes and _sha256(parquet) != checksum:
            raise ValueError("TUSHARE_DAILY_BASIC_AUDIT_INVALID")
        complete.append(
            _CompleteRequest(
                request_id=request_id,
                catalog_sha256=catalog_sha256,
                rows=row_count,
                checksum_sha256=checksum,
                metadata_sha256=hashlib.sha256(metadata_payload).hexdigest(),
                trade_date=trade_date,
                max_rows=max_rows,
                parquet_path=parquet,
            )
        )
    return complete


def _raw_closure(complete: list[_CompleteRequest]) -> dict[str, Any]:
    entries = [
        {
            "catalog_sha256": item.catalog_sha256,
            "data_sha256": item.checksum_sha256,
            "max_rows": item.max_rows,
            "metadata_sha256": item.metadata_sha256,
            "request_id": item.request_id,
            "rows": item.rows,
            "trade_date": item.trade_date,
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
    complete: list[_CompleteRequest], *, threads: int
) -> dict[str, Any]:
    empty: dict[str, Any] = {
        "raw_rows": 0,
        "distinct_keys": 0,
        "min_trade_date": None,
        "max_trade_date": None,
        "row_count_mismatch": 0,
        "duplicate_keys": 0,
        "parameter_date_mismatches": 0,
        "critical_null_rows": 0,
        "invalid_symbol_rows": 0,
        "unsupported_market_rows": 0,
        "invalid_trade_date_rows": 0,
        "nonfinite_rows": 0,
        "nonpositive_required_rows": 0,
        "negative_rate_rows": 0,
        "share_relationship_rows": 0,
        "market_value_relationship_rows": 0,
        "silent_row_limit_hits": 0,
        "eligible_rows": 0,
        "quarantined_rows": 0,
        "quarantine_reasons": {},
    }
    if not complete:
        return empty

    connection = duckdb.connect(":memory:")
    try:
        connection.execute(f"SET threads={threads}")
        connection.execute("SET enable_progress_bar=false")
        connection.execute(
            "CREATE TEMP TABLE expected_requests(request_id VARCHAR PRIMARY KEY, "
            "trade_date VARCHAR, expected_rows BIGINT)"
        )
        connection.executemany(
            "INSERT INTO expected_requests VALUES (?, ?, ?)",
            [(item.request_id, item.trade_date, item.rows) for item in complete],
        )
        connection.read_parquet(
            [str(item.parquet_path) for item in complete], filename=True
        ).create_view("daily_basic_raw")
        row_count_result = connection.execute(
            """
            WITH actual AS (
              SELECT regexp_extract(
                  filename, 'request=([0-9a-f]{64})', 1
                ) AS request_id,
                count(*) AS actual_rows
              FROM daily_basic_raw
              GROUP BY request_id
            )
            SELECT coalesce(sum(abs(
              e.expected_rows - coalesce(a.actual_rows, 0)
            )), 0)
            FROM expected_requests e
            LEFT JOIN actual a USING (request_id)
            """
        ).fetchone()
        if row_count_result is None:
            raise ValueError("TUSHARE_DAILY_BASIC_AUDIT_INVALID")
        row_count_mismatch = row_count_result[0]
        summary = connection.execute(
            """
            WITH base AS (
              SELECT r.*, e.trade_date AS expected_trade_date,
                regexp_matches(r.ts_code, '^[0-9]{6}\\.(SH|SZ)$') AS supported_symbol,
                regexp_matches(r.ts_code, '^[0-9]{5,6}\\.[A-Z]+$') AS formatted_symbol,
                regexp_matches(r.trade_date, '^[0-9]{8}$') AS formatted_date,
                (free_share IS NOT NULL AND free_share > float_share)
                  OR float_share > total_share AS bad_share_relation,
                circ_mv > total_mv AS bad_mv_relation
              FROM (
                SELECT *, regexp_extract(
                  filename, 'request=([0-9a-f]{64})', 1
                ) AS request_id
                FROM daily_basic_raw
              ) r
              LEFT JOIN expected_requests e USING (request_id)
            ), classified AS (
              SELECT *, CASE
                WHEN NOT supported_symbol THEN 'UNSUPPORTED_MARKET'
                WHEN bad_share_relation THEN 'SHARE_RELATION_INVALID'
                WHEN bad_mv_relation THEN 'MARKET_VALUE_RELATION_INVALID'
                ELSE 'ELIGIBLE'
              END AS classification
              FROM base
            )
            SELECT
              count(*), count(DISTINCT ts_code || ':' || trade_date),
              min(trade_date), max(trade_date),
              count(*) FILTER (WHERE expected_trade_date IS NULL
                OR trade_date <> expected_trade_date),
              count(*) FILTER (WHERE ts_code IS NULL OR trade_date IS NULL
                OR close IS NULL OR total_share IS NULL OR float_share IS NULL
                OR total_mv IS NULL OR circ_mv IS NULL),
              count(*) FILTER (WHERE NOT formatted_symbol),
              count(*) FILTER (WHERE formatted_symbol AND NOT supported_symbol),
              count(*) FILTER (WHERE NOT formatted_date),
              count(*) FILTER (WHERE NOT isfinite(close)
                OR NOT isfinite(total_share) OR NOT isfinite(float_share)
                OR NOT isfinite(total_mv) OR NOT isfinite(circ_mv)
                OR (turnover_rate IS NOT NULL AND NOT isfinite(turnover_rate))
                OR (turnover_rate_f IS NOT NULL AND NOT isfinite(turnover_rate_f))
                OR (volume_ratio IS NOT NULL AND NOT isfinite(volume_ratio))
                OR (pe IS NOT NULL AND NOT isfinite(pe))
                OR (pe_ttm IS NOT NULL AND NOT isfinite(pe_ttm))
                OR (pb IS NOT NULL AND NOT isfinite(pb))
                OR (ps IS NOT NULL AND NOT isfinite(ps))
                OR (ps_ttm IS NOT NULL AND NOT isfinite(ps_ttm))
                OR (dv_ratio IS NOT NULL AND NOT isfinite(dv_ratio))
                OR (dv_ttm IS NOT NULL AND NOT isfinite(dv_ttm))
                OR (free_share IS NOT NULL AND NOT isfinite(free_share))),
              count(*) FILTER (WHERE close <= 0 OR total_share <= 0
                OR float_share <= 0 OR total_mv <= 0 OR circ_mv <= 0
                OR (free_share IS NOT NULL AND free_share <= 0)),
              count(*) FILTER (WHERE turnover_rate < 0 OR turnover_rate_f < 0
                OR volume_ratio < 0 OR dv_ratio < 0 OR dv_ttm < 0),
              count(*) FILTER (WHERE bad_share_relation),
              count(*) FILTER (WHERE bad_mv_relation),
              count(*) FILTER (WHERE classification='UNSUPPORTED_MARKET'),
              count(*) FILTER (WHERE classification='SHARE_RELATION_INVALID'),
              count(*) FILTER (WHERE classification='MARKET_VALUE_RELATION_INVALID'),
              count(*) FILTER (WHERE classification!='ELIGIBLE')
            FROM classified
            """
        ).fetchone()
    finally:
        connection.close()
    if summary is None:
        raise ValueError("TUSHARE_DAILY_BASIC_AUDIT_INVALID")

    (
        raw_rows,
        distinct_keys,
        min_date,
        max_date,
        date_mismatch,
        critical_null,
        invalid_symbol,
        unsupported_market,
        invalid_date,
        nonfinite,
        nonpositive,
        negative_rate,
        bad_share,
        bad_mv,
        quarantined_unsupported,
        quarantined_share,
        quarantined_mv,
        quarantined,
    ) = summary
    limit_hits = sum(item.rows >= item.max_rows for item in complete)
    quarantine_reasons = {
        code: int(count)
        for code, count in (
            ("UNSUPPORTED_MARKET", quarantined_unsupported),
            ("SHARE_RELATION_INVALID", quarantined_share),
            ("MARKET_VALUE_RELATION_INVALID", quarantined_mv),
        )
        if count
    }
    return {
        "raw_rows": int(raw_rows),
        "distinct_keys": int(distinct_keys),
        "min_trade_date": min_date,
        "max_trade_date": max_date,
        "row_count_mismatch": int(row_count_mismatch),
        "duplicate_keys": int(raw_rows) - int(distinct_keys),
        "parameter_date_mismatches": int(date_mismatch),
        "critical_null_rows": int(critical_null),
        "invalid_symbol_rows": int(invalid_symbol),
        "unsupported_market_rows": int(unsupported_market),
        "invalid_trade_date_rows": int(invalid_date),
        "nonfinite_rows": int(nonfinite),
        "nonpositive_required_rows": int(nonpositive),
        "negative_rate_rows": int(negative_rate),
        "share_relationship_rows": int(bad_share),
        "market_value_relationship_rows": int(bad_mv),
        "silent_row_limit_hits": int(limit_hits),
        "eligible_rows": int(raw_rows) - int(quarantined),
        "quarantined_rows": int(quarantined),
        "quarantine_reasons": quarantine_reasons,
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="只读审计 Tushare daily_basic raw")
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--verify-bytes", action="store_true")
    args = parser.parse_args(argv)
    root = args.data_root or resolve_data_root()
    result = audit_tushare_daily_basic(
        data_root=root, threads=args.threads, verify_bytes=args.verify_bytes
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return {"READY": 0, "COLLECTING": 2, "BLOCKED": 3}[result["status"]]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["SCHEMA_VERSION", "audit_tushare_daily_basic", "main"]
