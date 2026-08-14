"""Recoverable request ledger and immutable raw ingestion for Tushare bulk data."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sqlite3
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

import polars as pl

from quant.data.connectors import TushareConnector
from quant.data.storage import RawStore
from quant.data.tushare_bulk import Catalog, DatasetSpec, load_catalog
from quant.settings import resolve_data_root

LEDGER_SCHEMA = "tushare-bulk-ledger-v1"
_TRANSIENT_MARKERS = ("频率", "每分钟", "timeout", "timed out", "connection", "tempor")


@dataclass(frozen=True)
class Request:
    """One deterministic supplier request."""

    request_id: str
    dataset: str
    api_name: str
    parameters: Mapping[str, str]
    max_rows: int
    attempts: int = 0


class RawQueryConnector(Protocol):
    """Narrow connector boundary used by the generic runner."""

    def query_raw(self, api_name: str, **params: str) -> pl.DataFrame: ...


def prepare_requests(
    *,
    catalog: Catalog,
    permission_report: Mapping[str, object],
    data_root: Path,
    ledger_path: Path,
    datasets: frozenset[str],
    start: dt.date,
    end: dt.date,
) -> dict[str, int]:
    """Insert deterministic request rows without contacting Tushare."""
    if start > end or not datasets:
        raise ValueError("TUSHARE_INGEST_PLAN_INVALID")
    status = _permission_status(permission_report, catalog)
    specs = {item.name: item for item in catalog.datasets}
    if not datasets <= specs.keys():
        raise ValueError("TUSHARE_INGEST_PLAN_INVALID")
    requests: list[Request] = []
    for name in sorted(datasets):
        spec = specs[name]
        if status[name] != "ACCESSIBLE":
            raise ValueError("TUSHARE_INGEST_DATASET_NOT_ACCESSIBLE")
        requests.extend(
            _requests_for_spec(
                catalog=catalog,
                spec=spec,
                data_root=data_root,
                start=max(start, spec.history_start or start),
                end=end,
            )
        )
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    inserted = 0
    existing = 0
    with _connect(ledger_path) as conn:
        _initialize(conn)
        for request in requests:
            payload = _json_text(dict(request.parameters))
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO requests(
                    request_id, catalog_sha256, dataset, api_name, parameters_json,
                    max_rows, status, attempts, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'PENDING', 0, ?)
                """,
                (
                    request.request_id,
                    catalog.sha256,
                    request.dataset,
                    request.api_name,
                    payload,
                    request.max_rows,
                    _utc_now(),
                ),
            )
            if cursor.rowcount == 1:
                inserted += 1
            else:
                row = conn.execute(
                    "SELECT catalog_sha256, dataset, api_name, parameters_json, max_rows "
                    "FROM requests WHERE request_id = ?",
                    (request.request_id,),
                ).fetchone()
                if row != (catalog.sha256, request.dataset, request.api_name, payload, request.max_rows):
                    raise ValueError("TUSHARE_INGEST_LEDGER_CONFLICT")
                existing += 1
        conn.commit()
    return {"planned": len(requests), "inserted": inserted, "existing": existing}


def run_requests(
    *,
    connector: RawQueryConnector,
    data_root: Path,
    ledger_path: Path,
    max_requests: int,
    requests_per_minute: int,
    max_attempts: int = 3,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, int]:
    """Run a bounded number of pending requests under a single renewable lease."""
    if max_requests <= 0 or not 1 <= requests_per_minute <= 500 or max_attempts <= 0:
        raise ValueError("TUSHARE_INGEST_RUN_INVALID")
    if not callable(sleeper):
        raise ValueError("TUSHARE_INGEST_RUN_INVALID")
    owner = uuid.uuid4().hex
    completed = retryable = failed = 0
    raw_store = RawStore(data_root.resolve(strict=True) / "raw")
    with _connect(ledger_path) as conn:
        _initialize(conn)
        _acquire_lease(conn, owner)
        try:
            for index in range(max_requests):
                request = _claim(conn, owner=owner, max_attempts=max_attempts)
                if request is None:
                    break
                raw_state = raw_store.inspect_request_state(
                    source="tushare", table=request.dataset, request_id=request.request_id
                )
                if raw_state == "COMPLETE":
                    snapshot = raw_store.verify_request(
                        source="tushare",
                        table=request.dataset,
                        request_id=request.request_id,
                        parameters=dict(request.parameters),
                    )
                    _finish(
                        conn,
                        request.request_id,
                        "COMPLETE",
                        snapshot.row_count,
                        snapshot.checksum_sha256,
                    )
                    completed += 1
                    continue
                if index:
                    sleeper(60.0 / requests_per_minute)
                try:
                    frame = connector.query_raw(request.api_name, **dict(request.parameters))
                    snapshot = raw_store.write_request(
                        source="tushare",
                        table=request.dataset,
                        request_id=request.request_id,
                        frame=frame,
                        parameters=dict(request.parameters),
                    )
                    if frame.height >= request.max_rows:
                        _finish(
                            conn,
                            request.request_id,
                            "SPLIT_REQUIRED",
                            frame.height,
                            "ROW_LIMIT_REACHED",
                        )
                        failed += 1
                        continue
                except Exception as exc:  # SDK exception types are not stable.
                    code = _error_code(exc)
                    state = "RETRYABLE" if code == "TRANSIENT" else "FAILED"
                    _finish(conn, request.request_id, state, None, code)
                    if state == "RETRYABLE":
                        sleeper(min(60.0, float(2**request.attempts)))
                    retryable += state == "RETRYABLE"
                    failed += state == "FAILED"
                    continue
                _finish(
                    conn,
                    request.request_id,
                    "COMPLETE",
                    snapshot.row_count,
                    snapshot.checksum_sha256,
                )
                completed += 1
        finally:
            _release_lease(conn, owner)
    return {"completed": completed, "retryable": retryable, "failed": failed}


def ledger_summary(ledger_path: Path) -> dict[str, int]:
    """Return stable request counts by status."""
    with _connect(ledger_path) as conn:
        _initialize(conn)
        rows = conn.execute(
            "SELECT status, COUNT(*) FROM requests GROUP BY status ORDER BY status"
        ).fetchall()
    return {cast(str, status): cast(int, count) for status, count in rows}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Tushare 可恢复全量 raw 采集")
    parser.add_argument("--catalog", type=Path, default=Path("configs/data/tushare_bulk_v1.toml"))
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--ledger", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--permission-report", type=Path, required=True)
    prepare.add_argument("--dataset", action="append", required=True)
    prepare.add_argument("--start", type=dt.date.fromisoformat, required=True)
    prepare.add_argument("--end", type=dt.date.fromisoformat, default=dt.date.today())
    run = sub.add_parser("run")
    run.add_argument("--config", type=Path)
    run.add_argument("--max-requests", type=int, default=1)
    run.add_argument("--requests-per-minute", type=int, default=60)
    sub.add_parser("status")
    args = parser.parse_args(argv)
    data_root = resolve_data_root(args.data_root)
    ledger = args.ledger or data_root / "run_state" / "tushare_bulk" / "state.sqlite"
    if args.command == "prepare":
        catalog = load_catalog(args.catalog.resolve(strict=True))
        report = _read_object(args.permission_report)
        result = prepare_requests(
            catalog=catalog,
            permission_report=report,
            data_root=data_root,
            ledger_path=ledger,
            datasets=frozenset(args.dataset),
            start=args.start,
            end=args.end,
        )
    elif args.command == "run":
        result = run_requests(
            connector=TushareConnector(config_path=args.config),
            data_root=data_root,
            ledger_path=ledger,
            max_requests=args.max_requests,
            requests_per_minute=args.requests_per_minute,
        )
    else:
        result = ledger_summary(ledger)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


def _requests_for_spec(
    *, catalog: Catalog, spec: DatasetSpec, data_root: Path, start: dt.date, end: dt.date
) -> list[Request]:
    if start > end or spec.request_unit == "manual":
        return []
    params = dict(spec.probe_params)
    variants: list[dict[str, str]] = []
    if spec.request_unit == "once":
        variants = [params]
    elif spec.request_unit == "per_trade_date":
        base = _without_dates(params)
        variants = [base | {"trade_date": value.strftime("%Y%m%d")} for value in _open_dates(data_root, start, end)]
    elif spec.request_unit == "per_month":
        base = _without_dates(params)
        variants = [
            base | {"start_date": first.strftime("%Y%m%d"), "end_date": last.strftime("%Y%m%d")}
            for first, last in _months(start, end)
        ]
    else:
        symbols = _inventory_symbols(data_root, spec.inventory)
        base = _without_dates(params)
        variants = [base | {"ts_code": symbol} for symbol in symbols]
    return [_request(catalog, spec, item) for item in variants]


def _request(catalog: Catalog, spec: DatasetSpec, params: Mapping[str, str]) -> Request:
    identity = _json_text({
        "schema_version": LEDGER_SCHEMA,
        "catalog_sha256": catalog.sha256,
        "dataset": spec.name,
        "api_name": spec.api_name,
        "parameters": dict(params),
    })
    return Request(hashlib.sha256(identity.encode()).hexdigest(), spec.name, spec.api_name, dict(params), spec.max_rows)


def _permission_status(report: Mapping[str, object], catalog: Catalog) -> dict[str, str]:
    if report.get("catalog_sha256") != catalog.sha256 or type(report.get("results")) is not list:
        raise ValueError("TUSHARE_PERMISSION_REPORT_INVALID")
    rows = cast(list[object], report["results"])
    result: dict[str, str] = {}
    for row in rows:
        if type(row) is not dict:
            raise ValueError("TUSHARE_PERMISSION_REPORT_INVALID")
        value = cast(dict[str, object], row)
        if type(value.get("dataset")) is not str or type(value.get("status")) is not str:
            raise ValueError("TUSHARE_PERMISSION_REPORT_INVALID")
        result[cast(str, value["dataset"])] = cast(str, value["status"])
    if set(result) != {item.name for item in catalog.datasets}:
        raise ValueError("TUSHARE_PERMISSION_REPORT_INVALID")
    return result


def _open_dates(root: Path, start: dt.date, end: dt.date) -> tuple[dt.date, ...]:
    frame = pl.read_parquet(root / "clean" / "trade_calendar" / "market=SH" / "data.parquet")
    values = frame.filter(pl.col("is_open") & pl.col("date").is_between(start, end))["date"].to_list()
    return tuple(sorted(cast(list[dt.date], values)))


def _inventory_symbols(root: Path, inventory: str) -> tuple[str, ...]:
    paths = sorted((root / "clean" / "instrument").glob("market=*/data.parquet"))
    frame = pl.concat([pl.read_parquet(path) for path in paths], how="vertical_relaxed")
    condition = {
        "stock": pl.col("market").is_in(["SH", "SZ"]) & (pl.col("instrument_type") == "STOCK"),
        "fund": pl.col("market").is_in(["SH", "SZ"]) & (pl.col("instrument_type") == "ETF"),
        "hk_stock": (pl.col("market") == "HK") & (pl.col("instrument_type") == "STOCK"),
    }.get(inventory)
    if condition is None:
        raise ValueError("TUSHARE_INGEST_INVENTORY_REQUIRED")
    return tuple(sorted(cast(list[str], frame.filter(condition)["symbol"].unique().to_list())))


def _months(start: dt.date, end: dt.date) -> list[tuple[dt.date, dt.date]]:
    result: list[tuple[dt.date, dt.date]] = []
    cursor = start.replace(day=1)
    while cursor <= end:
        following = (cursor.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        result.append((max(cursor, start), min(following - dt.timedelta(days=1), end)))
        cursor = following
    return result


def _without_dates(params: Mapping[str, str]) -> dict[str, str]:
    return {key: value for key, value in params.items() if key not in {"ts_code", "trade_date", "date", "ann_date", "period", "start_date", "end_date"}}


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=5)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=FULL")
    return conn


def _initialize(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS requests(
      request_id TEXT PRIMARY KEY, catalog_sha256 TEXT NOT NULL, dataset TEXT NOT NULL,
      api_name TEXT NOT NULL, parameters_json TEXT NOT NULL, max_rows INTEGER NOT NULL,
      status TEXT NOT NULL, attempts INTEGER NOT NULL, rows INTEGER,
      checksum_sha256 TEXT, error_code TEXT, updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS lease(owner TEXT PRIMARY KEY, expires_at REAL NOT NULL);
    """)


def _acquire_lease(conn: sqlite3.Connection, owner: str) -> None:
    now = time.time()
    conn.execute("DELETE FROM lease WHERE expires_at < ?", (now,))
    try:
        conn.execute("INSERT INTO lease(owner, expires_at) VALUES (?, ?)", (owner, now + 300))
        conn.execute(
            "UPDATE requests SET status='RETRYABLE', error_code='INTERRUPTED', updated_at=? "
            "WHERE status='RUNNING'",
            (_utc_now(),),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        raise ValueError("TUSHARE_INGEST_WRITER_BUSY") from None


def _claim(conn: sqlite3.Connection, *, owner: str, max_attempts: int) -> Request | None:
    conn.execute("UPDATE lease SET expires_at = ? WHERE owner = ?", (time.time() + 300, owner))
    row = conn.execute(
        "SELECT request_id, dataset, api_name, parameters_json, max_rows, attempts FROM requests "
        "WHERE status IN ('PENDING','RETRYABLE') AND attempts < ? ORDER BY dataset, request_id LIMIT 1",
        (max_attempts,),
    ).fetchone()
    if row is None:
        conn.commit()
        return None
    conn.execute(
        "UPDATE requests SET status='RUNNING', attempts=attempts+1, updated_at=? WHERE request_id=?",
        (_utc_now(), row[0]),
    )
    conn.commit()
    params = json.loads(cast(str, row[3]))
    return Request(
        cast(str, row[0]),
        cast(str, row[1]),
        cast(str, row[2]),
        cast(dict[str, str], params),
        cast(int, row[4]),
        cast(int, row[5]) + 1,
    )


def _finish(conn: sqlite3.Connection, request_id: str, status: str, rows: int | None, detail: str | None) -> None:
    checksum = detail if status == "COMPLETE" else None
    error = None if status == "COMPLETE" else detail
    conn.execute(
        "UPDATE requests SET status=?, rows=?, checksum_sha256=?, error_code=?, updated_at=? WHERE request_id=?",
        (status, rows, checksum, error, _utc_now(), request_id),
    )
    conn.commit()


def _release_lease(conn: sqlite3.Connection, owner: str) -> None:
    conn.execute("DELETE FROM lease WHERE owner = ?", (owner,))
    conn.commit()


def _error_code(exc: Exception) -> str:
    try:
        text = str(exc).casefold()
    except Exception:
        return "UNKNOWN"
    return "TRANSIENT" if any(marker in text for marker in _TRANSIENT_MARKERS) else "NON_RETRYABLE"


def _read_object(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if type(value) is not dict:
        raise ValueError("TUSHARE_PERMISSION_REPORT_INVALID")
    return cast(dict[str, object], value)


def _json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
