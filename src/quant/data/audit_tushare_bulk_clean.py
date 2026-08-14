"""Audit immutable Tushare bulk raw data before any clean publication."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

import duckdb

from quant.settings import resolve_data_root

SCHEMA_VERSION = "tushare-bulk-clean-admission-v2"
_DATASETS = ("adj_factor", "daily", "fund_adj", "fund_daily")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def audit_tushare_bulk_clean_admission(
    *, data_root: Path, threads: int = 2, verify_bytes: bool = True
) -> dict[str, Any]:
    """Return a deterministic, read-only clean-admission decision."""
    try:
        return _audit_tushare_bulk_clean_admission(
            data_root=data_root, threads=threads, verify_bytes=verify_bytes
        )
    except Exception:
        pass
    raise ValueError("TUSHARE_BULK_CLEAN_AUDIT_INVALID") from None


def _audit_tushare_bulk_clean_admission(
    *, data_root: Path, threads: int, verify_bytes: bool
) -> dict[str, Any]:
    root = data_root.resolve(strict=True)
    if type(threads) is not int or not 1 <= threads <= 8 or type(verify_bytes) is not bool:
        raise ValueError("TUSHARE_BULK_CLEAN_AUDIT_INVALID")
    ledger = root / "run_state" / "tushare_bulk" / "state.sqlite"
    rows = _ledger_rows(ledger)
    selected = [row for row in rows if row[2] in _DATASETS]
    if not selected or {row[2] for row in selected} != set(_DATASETS):
        raise ValueError("TUSHARE_BULK_CLEAN_AUDIT_INVALID")
    status_counts = Counter(cast(str, row[4]) for row in selected)
    blocking: list[dict[str, Any]] = []
    if set(status_counts) != {"COMPLETE"}:
        blocking.append(
            _issue("LEDGER_NOT_COMPLETE", sum(count for state, count in status_counts.items() if state != "COMPLETE"))
        )

    paths: dict[str, list[str]] = {name: [] for name in _DATASETS}
    identity_rows: list[dict[str, Any]] = []
    for request_id, catalog_sha, dataset, parameters_json, status, row_count, checksum in selected:
        if (
            not _HEX64.fullmatch(cast(str, request_id))
            or not _HEX64.fullmatch(cast(str, catalog_sha))
            or status != "COMPLETE"
            or type(row_count) is not int
            or row_count < 0
            or not _HEX64.fullmatch(cast(str, checksum))
        ):
            continue
        directory = root / "raw" / "tushare" / cast(str, dataset) / f"request={request_id}"
        data_path = directory / "data.parquet"
        metadata_path = directory / "metadata.json"
        metadata = _verify_request_pair(
            data_path=data_path,
            metadata_path=metadata_path,
            request_id=cast(str, request_id),
            dataset=cast(str, dataset),
            parameters_json=cast(str, parameters_json),
            row_count=cast(int, row_count),
            checksum=cast(str, checksum),
            verify_bytes=verify_bytes,
        )
        paths[cast(str, dataset)].append(str(data_path))
        identity_rows.append(
            {
                "catalog_sha256": catalog_sha,
                "checksum_sha256": checksum,
                "dataset": dataset,
                "metadata_sha256": hashlib.sha256(metadata_path.read_bytes()).hexdigest(),
                "parameters": json.loads(cast(str, parameters_json)),
                "request_id": request_id,
                "rows": row_count,
                "size_bytes": metadata["size_bytes"],
            }
        )
    if len(identity_rows) != len(selected):
        blocking.append(_issue("RAW_REQUEST_NOT_COMPLETE", len(selected) - len(identity_rows)))
    _require_exact_request_directories(root=root, selected=selected)

    snapshot_sha = _sha_json(
        {"schema_version": SCHEMA_VERSION, "requests": identity_rows}
    )
    connection = duckdb.connect(":memory:")
    try:
        connection.execute(f"SET threads={threads}")
        connection.execute("SET enable_progress_bar=false")
        for dataset in _DATASETS:
            connection.from_parquet(paths[dataset]).create_view(dataset)
        dataset_stats = {
            "daily": _daily_stats(connection),
            "adj_factor": _factor_stats(connection, "adj_factor"),
            "fund_daily": _fund_stats(connection),
            "fund_adj": _factor_stats(connection, "fund_adj"),
        }
        blocking.extend(_blocking_issues(connection, dataset_stats))
        warnings = _warning_issues(dataset_stats)
        scoped_clean_plan = _scoped_clean_plan(connection, dataset_stats)
    finally:
        connection.close()
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "READY" if not blocking else "BLOCKED",
        "raw_snapshot_sha256": snapshot_sha,
        "catalog_sha256s": sorted({cast(str, row[1]) for row in selected}),
        "request_count": len(selected),
        "ledger_status_counts": dict(sorted(status_counts.items())),
        "datasets": dataset_stats,
        "scoped_clean_plan": scoped_clean_plan,
        "blocking_issues": blocking,
        "warnings": warnings,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Tushare bulk raw clean 准入审计")
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--skip-byte-verification", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    output = args.output.resolve() if args.output is not None else None
    if output is not None and not output.parent.is_dir():
        raise ValueError("TUSHARE_BULK_CLEAN_AUDIT_OUTPUT_INVALID")
    result = audit_tushare_bulk_clean_admission(
        data_root=resolve_data_root(args.data_root),
        threads=args.threads,
        verify_bytes=not args.skip_byte_verification,
    )
    raw = _canonical(result)
    if output is not None:
        try:
            with output.open("xb") as handle:
                handle.write(raw)
        except OSError:
            raise ValueError("TUSHARE_BULK_CLEAN_AUDIT_OUTPUT_INVALID") from None
    print(raw.decode("utf-8"))
    return 0 if result["status"] == "READY" else 3


def _ledger_rows(path: Path) -> list[tuple[object, ...]]:
    try:
        uri = f"file:{path.resolve(strict=True).as_posix()}?mode=ro"
        with sqlite3.connect(uri, uri=True) as connection:
            return connection.execute(
                "SELECT request_id, catalog_sha256, dataset, parameters_json, status, "
                "rows, checksum_sha256 FROM requests ORDER BY dataset, request_id"
            ).fetchall()
    except (OSError, sqlite3.Error):
        raise ValueError("TUSHARE_BULK_CLEAN_AUDIT_INVALID") from None


def _verify_request_pair(
    *,
    data_path: Path,
    metadata_path: Path,
    request_id: str,
    dataset: str,
    parameters_json: str,
    row_count: int,
    checksum: str,
    verify_bytes: bool,
) -> dict[str, Any]:
    try:
        if data_path.is_symlink() or metadata_path.is_symlink():
            raise ValueError
        raw_metadata = metadata_path.read_bytes()
        metadata = json.loads(raw_metadata)
        parameters = json.loads(parameters_json)
        if (
            data_path.parent.is_symlink()
            or {entry.name for entry in data_path.parent.iterdir()}
            != {"data.parquet", "metadata.json"}
            or not data_path.is_file()
            or not metadata_path.is_file()
            or
            type(metadata) is not dict
            or metadata.get("schema_version") != "request-raw-v1"
            or metadata.get("request_id") != request_id
            or metadata.get("snapshot_id") != request_id
            or metadata.get("source") != "tushare"
            or metadata.get("table") != dataset
            or metadata.get("parameters") != parameters
            or metadata.get("rows") != row_count
            or metadata.get("checksum_sha256") != checksum
            or type(metadata.get("size_bytes")) is not int
            or data_path.stat().st_size != metadata["size_bytes"]
        ):
            raise ValueError
        if verify_bytes and _sha_file(data_path) != checksum:
            raise ValueError
        return cast(dict[str, Any], metadata)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        raise ValueError("TUSHARE_BULK_CLEAN_AUDIT_INVALID") from None


def _require_exact_request_directories(
    *, root: Path, selected: list[tuple[object, ...]]
) -> None:
    expected: dict[str, set[str]] = {name: set() for name in _DATASETS}
    for row in selected:
        expected[cast(str, row[2])].add(f"request={row[0]}")
    try:
        for dataset in _DATASETS:
            directory = root / "raw" / "tushare" / dataset
            actual = {entry.name for entry in directory.iterdir() if entry.is_dir()}
            if actual != expected[dataset]:
                raise ValueError
    except (OSError, ValueError):
        raise ValueError("TUSHARE_BULK_CLEAN_AUDIT_INVALID") from None


def _daily_stats(connection: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    row = connection.execute(
        """
        SELECT count(*), count(*) - count(DISTINCT (ts_code, trade_date)),
          count(*) FILTER (WHERE ts_code IS NULL OR trade_date IS NULL OR open IS NULL
            OR high IS NULL OR low IS NULL OR close IS NULL OR vol IS NULL OR amount IS NULL),
          count(*) FILTER (WHERE open <= 0 OR high <= 0 OR low <= 0 OR close <= 0),
          count(*) FILTER (WHERE vol < 0 OR amount < 0),
          count(*) FILTER (WHERE low > open OR low > close OR high < open OR high < close),
          count(*) FILTER (WHERE NOT regexp_matches(ts_code, '^[0-9]{6}\\.(SH|SZ)$')),
          count(*) FILTER (WHERE NOT regexp_matches(trade_date, '^[0-9]{8}$')),
          min(trade_date), max(trade_date)
        FROM daily
        """
    ).fetchone()
    assert row is not None
    null_examples = connection.execute(
        """
        SELECT ts_code, trade_date FROM daily
        WHERE ts_code IS NULL OR trade_date IS NULL OR open IS NULL OR high IS NULL
          OR low IS NULL OR close IS NULL OR vol IS NULL OR amount IS NULL
        ORDER BY ts_code, trade_date LIMIT 25
        """
    ).fetchall()
    ohlc_examples = connection.execute(
        """
        SELECT ts_code, trade_date FROM daily
        WHERE low > open OR low > close OR high < open OR high < close
        ORDER BY ts_code, trade_date LIMIT 25
        """
    ).fetchall()
    unsupported_examples = connection.execute(
        """
        SELECT ts_code, min(trade_date) FROM daily
        WHERE NOT regexp_matches(ts_code, '^[0-9]{6}\\.(SH|SZ)$')
        GROUP BY ts_code ORDER BY ts_code LIMIT 25
        """
    ).fetchall()
    date_examples = connection.execute(
        "SELECT ts_code, trade_date FROM daily "
        "WHERE NOT regexp_matches(trade_date, '^[0-9]{8}$') "
        "ORDER BY ts_code, trade_date LIMIT 25"
    ).fetchall()
    return _stats(
        row,
        {
            "critical_nulls": null_examples,
            "ohlc_anomalies": ohlc_examples,
            "unsupported_symbol_rows": unsupported_examples,
            "invalid_trade_dates": date_examples,
        },
    )


def _factor_stats(
    connection: duckdb.DuckDBPyConnection, dataset: str
) -> dict[str, Any]:
    if dataset not in {"adj_factor", "fund_adj"}:
        raise ValueError("TUSHARE_BULK_CLEAN_AUDIT_INVALID")
    row = connection.execute(
        f"""
        SELECT count(*), count(*) - count(DISTINCT (ts_code, trade_date)),
          count(*) FILTER (WHERE ts_code IS NULL OR trade_date IS NULL OR adj_factor IS NULL),
          count(*) FILTER (WHERE adj_factor <= 0), 0, 0,
          count(*) FILTER (WHERE NOT regexp_matches(ts_code, '^[0-9]{{6}}\\.(SH|SZ)$')),
          count(*) FILTER (WHERE NOT regexp_matches(trade_date, '^[0-9]{{8}}$')),
          min(trade_date), max(trade_date)
        FROM {dataset}
        """
    ).fetchone()
    assert row is not None
    unsupported_examples = connection.execute(
        f"SELECT ts_code, min(trade_date) FROM {dataset} "
        "WHERE NOT regexp_matches(ts_code, '^[0-9]{6}\\.(SH|SZ)$') "
        "GROUP BY ts_code ORDER BY ts_code LIMIT 25"
    ).fetchall()
    date_examples = connection.execute(
        f"SELECT ts_code, trade_date FROM {dataset} "
        "WHERE NOT regexp_matches(trade_date, '^[0-9]{8}$') "
        "ORDER BY ts_code, trade_date LIMIT 25"
    ).fetchall()
    return _stats(
        row,
        {
            "unsupported_symbol_rows": unsupported_examples,
            "invalid_trade_dates": date_examples,
        },
    )


def _fund_stats(connection: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    row = connection.execute(
        """
        SELECT count(*), count(*) - count(DISTINCT (ts_code, trade_date)),
          count(*) FILTER (WHERE ts_code IS NULL OR trade_date IS NULL OR open IS NULL
            OR high IS NULL OR low IS NULL OR close IS NULL OR vol IS NULL OR amount IS NULL),
          count(*) FILTER (WHERE open <= 0 OR high <= 0 OR low <= 0 OR close <= 0),
          count(*) FILTER (WHERE vol < 0 OR amount < 0),
          count(*) FILTER (WHERE low > open OR low > close OR high < open OR high < close),
          count(*) FILTER (WHERE NOT regexp_matches(ts_code, '^[0-9]{6}\\.(SH|SZ)$')),
          count(*) FILTER (WHERE NOT regexp_matches(trade_date, '^[0-9]{8}$')),
          min(trade_date), max(trade_date)
        FROM fund_daily
        """
    ).fetchone()
    assert row is not None
    ohlc_examples = connection.execute(
        """
        SELECT ts_code, trade_date FROM fund_daily
        WHERE low > open OR low > close OR high < open OR high < close
        ORDER BY ts_code, trade_date LIMIT 25
        """
    ).fetchall()
    unsupported_examples = connection.execute(
        "SELECT ts_code, min(trade_date) FROM fund_daily "
        "WHERE NOT regexp_matches(ts_code, '^[0-9]{6}\\.(SH|SZ)$') "
        "GROUP BY ts_code ORDER BY ts_code LIMIT 25"
    ).fetchall()
    date_examples = connection.execute(
        "SELECT ts_code, trade_date FROM fund_daily "
        "WHERE NOT regexp_matches(trade_date, '^[0-9]{8}$') "
        "ORDER BY ts_code, trade_date LIMIT 25"
    ).fetchall()
    return _stats(
        row,
        {
            "ohlc_anomalies": ohlc_examples,
            "unsupported_symbol_rows": unsupported_examples,
            "invalid_trade_dates": date_examples,
        },
    )


def _stats(
    row: tuple[object, ...], examples: dict[str, list[tuple[object, ...]]]
) -> dict[str, Any]:
    return {
        "rows": row[0],
        "duplicate_keys": row[1],
        "critical_nulls": row[2],
        "nonpositive_values": row[3],
        "negative_volume_or_amount": row[4],
        "ohlc_anomalies": row[5],
        "unsupported_symbol_rows": row[6],
        "invalid_trade_dates": row[7],
        "min_trade_date": row[8],
        "max_trade_date": row[9],
        "examples": {
            key: [[str(value) for value in item] for item in values]
            for key, values in examples.items()
            if values
        },
    }


def _blocking_issues(
    connection: duckdb.DuckDBPyConnection, stats: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for dataset, values in stats.items():
        for field, code in (
            ("duplicate_keys", "DUPLICATE_KEYS"),
            ("critical_nulls", "CRITICAL_NULLS"),
            ("nonpositive_values", "NONPOSITIVE_VALUES"),
            ("negative_volume_or_amount", "NEGATIVE_VOLUME_OR_AMOUNT"),
            ("ohlc_anomalies", "OHLC_RELATION_INVALID"),
            ("unsupported_symbol_rows", "SYMBOL_MAPPING_REQUIRED"),
            ("invalid_trade_dates", "TRADE_DATE_FORMAT_INVALID"),
        ):
            count = cast(int, values[field])
            if count:
                issues.append(
                    _issue(
                        f"{dataset.upper()}_{code}",
                        count,
                        cast(dict[str, list[list[str]]], values["examples"]).get(field),
                    )
                )
    missing = connection.execute(
        """
        SELECT count(*) FROM daily d LEFT JOIN adj_factor a
          ON d.ts_code=a.ts_code AND d.trade_date=a.trade_date
        WHERE regexp_matches(d.ts_code, '^[0-9]{6}\\.(SH|SZ)$')
          AND a.ts_code IS NULL
        """
    ).fetchone()
    assert missing is not None
    if cast(int, missing[0]):
        examples = connection.execute(
            """
            SELECT d.ts_code, min(d.trade_date), max(d.trade_date), count(*)
            FROM daily d LEFT JOIN adj_factor a
              ON d.ts_code=a.ts_code AND d.trade_date=a.trade_date
            WHERE regexp_matches(d.ts_code, '^[0-9]{6}\\.(SH|SZ)$')
              AND a.ts_code IS NULL
            GROUP BY d.ts_code ORDER BY d.ts_code LIMIT 25
            """
        ).fetchall()
        issues.append(
            _issue(
                "DAILY_ADJ_FACTOR_MISSING",
                cast(int, missing[0]),
                [[str(value) for value in item] for item in examples],
            )
        )
    fund_missing = connection.execute(
        """
        SELECT count(*) FROM fund_daily d LEFT JOIN fund_adj a
          ON d.ts_code=a.ts_code AND d.trade_date=a.trade_date
        WHERE regexp_matches(d.ts_code, '^[0-9]{6}\\.(SH|SZ)$')
          AND a.ts_code IS NULL
        """
    ).fetchone()
    assert fund_missing is not None
    if cast(int, fund_missing[0]):
        examples = connection.execute(
            """
            SELECT d.ts_code, min(d.trade_date), max(d.trade_date), count(*)
            FROM fund_daily d LEFT JOIN fund_adj a
              ON d.ts_code=a.ts_code AND d.trade_date=a.trade_date
            WHERE regexp_matches(d.ts_code, '^[0-9]{6}\\.(SH|SZ)$')
              AND a.ts_code IS NULL
            GROUP BY d.ts_code ORDER BY d.ts_code LIMIT 25
            """
        ).fetchall()
        issues.append(
            _issue(
                "FUND_DAILY_ADJ_FACTOR_MISSING",
                cast(int, fund_missing[0]),
                [[str(value) for value in item] for item in examples],
            )
        )
    return issues


def _warning_issues(stats: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    cutoffs = {name: values["max_trade_date"] for name, values in stats.items()}
    if len(set(cutoffs.values())) == 1:
        return []
    return [{"code": "DATASET_CUTOFFS_DIFFER", "cutoffs": cutoffs}]


def _scoped_clean_plan(
    connection: duckdb.DuckDBPyConnection,
    stats: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    stock = _bar_clean_classification(
        connection, daily_dataset="daily", factor_dataset="adj_factor"
    )
    fund = _bar_clean_classification(
        connection, daily_dataset="fund_daily", factor_dataset="fund_adj"
    )
    structural_ok = all(
        cast(int, stats[dataset]["duplicate_keys"]) == 0
        for dataset in _DATASETS
    )
    exact_coverage = all(
        value["source_rows"] == value["classified_rows"]
        for value in (stock, fund)
    )
    return {
        "schema_version": "tushare-bulk-scoped-clean-plan-v1",
        "status": "READY" if structural_ok and exact_coverage else "BLOCKED",
        "scope": {
            "markets": ["SH", "SZ"],
            "symbol_pattern": "^[0-9]{6}\\.(SH|SZ)$",
            "bar_schema": "Bar1dSchema",
            "source": "tushare",
            "volume_multiplier": 100,
            "amount_multiplier": 1000,
        },
        "stock_bar_1d": stock,
        "fund_bar_1d": fund,
    }


def _bar_clean_classification(
    connection: duckdb.DuckDBPyConnection,
    *,
    daily_dataset: str,
    factor_dataset: str,
) -> dict[str, Any]:
    if (daily_dataset, factor_dataset) not in {
        ("daily", "adj_factor"),
        ("fund_daily", "fund_adj"),
    }:
        raise ValueError("TUSHARE_BULK_CLEAN_AUDIT_INVALID")
    rows = connection.execute(
        f"""
        WITH classified AS (
          SELECT CASE
            WHEN d.ts_code IS NULL OR d.trade_date IS NULL OR d.open IS NULL
              OR d.high IS NULL OR d.low IS NULL OR d.close IS NULL
              OR d.vol IS NULL OR d.amount IS NULL THEN 'CRITICAL_NULL'
            WHEN NOT regexp_matches(d.ts_code, '^[0-9]{{6}}\\.(SH|SZ)$')
              THEN 'UNSUPPORTED_SYMBOL'
            WHEN NOT regexp_matches(d.trade_date, '^[0-9]{{8}}$')
              THEN 'TRADE_DATE_FORMAT_INVALID'
            WHEN d.open <= 0 OR d.high <= 0 OR d.low <= 0 OR d.close <= 0
              THEN 'NONPOSITIVE_PRICE'
            WHEN d.vol < 0 OR d.amount < 0 THEN 'NEGATIVE_VOLUME_OR_AMOUNT'
            WHEN d.low > d.open OR d.low > d.close OR d.high < d.open OR d.high < d.close
              THEN 'OHLC_RELATION_INVALID'
            WHEN a.ts_code IS NULL THEN 'ADJ_FACTOR_MISSING'
            WHEN a.adj_factor IS NULL OR a.adj_factor <= 0 THEN 'ADJ_FACTOR_INVALID'
            ELSE 'ELIGIBLE'
          END reason
          FROM {daily_dataset} d LEFT JOIN {factor_dataset} a
            ON d.ts_code=a.ts_code AND d.trade_date=a.trade_date
        )
        SELECT reason, count(*) FROM classified
        GROUP BY reason ORDER BY reason
        """
    ).fetchall()
    counts = {cast(str, reason): cast(int, count) for reason, count in rows}
    source_rows_row = connection.execute(
        f"SELECT count(*) FROM {daily_dataset}"
    ).fetchone()
    assert source_rows_row is not None
    source_rows = cast(int, source_rows_row[0])
    classified_rows = sum(counts.values())
    eligible_rows = counts.get("ELIGIBLE", 0)
    return {
        "source_rows": source_rows,
        "classified_rows": classified_rows,
        "eligible_rows": eligible_rows,
        "quarantined_rows": classified_rows - eligible_rows,
        "reasons": counts,
    }


def _issue(code: str, count: int, examples: list[list[str]] | None = None) -> dict[str, Any]:
    value: dict[str, Any] = {"code": code, "count": count}
    if examples:
        value["examples"] = examples
    return value


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha_json(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
