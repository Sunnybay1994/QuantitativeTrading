"""Permission discovery and dry-run planning for versioned Tushare datasets.

This module deliberately stops before historical acquisition.  It provides the
bounded P0 control plane: a strict explicit catalog, one minimal permission
probe per dataset and a request-count plan based on the shared clean inventory.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import time
import tomllib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, cast

import polars as pl

from quant.data.connectors import TushareConnector
from quant.settings import resolve_data_root

CATALOG_SCHEMA = "tushare-bulk-catalog-v1"
REPORT_SCHEMA = "tushare-permission-report-v1"
PLAN_SCHEMA = "tushare-request-plan-v1"

Priority = Literal["core", "extended", "archive"]
ProbeMode = Literal["query", "manual"]
RequestUnit = Literal["once", "per_symbol", "per_trade_date", "per_month", "manual"]
Inventory = Literal[
    "none", "stock", "fund", "hk_stock", "future", "option", "index", "convertible_bond"
]
ProbeStatus = Literal[
    "ACCESSIBLE",
    "EMPTY_BUT_VALID",
    "PERMISSION_DENIED",
    "RATE_LIMITED",
    "PARAMETER_INVALID",
    "PROBE_FAILED",
    "NOT_PROBED",
]


class QueryClient(Protocol):
    """Narrow Tushare SDK surface used by the permission probe."""

    def query(self, api_name: str, **params: str) -> object: ...


@dataclass(frozen=True)
class DatasetSpec:
    """One explicit, reviewable Tushare dataset entry."""

    name: str
    api_name: str
    category: str
    priority: Priority
    probe_mode: ProbeMode
    probe_params: Mapping[str, str]
    request_unit: RequestUnit
    inventory: Inventory
    history_start: dt.date | None
    max_rows: int
    chunk_days: int
    partition: str
    overlap_days: int


@dataclass(frozen=True)
class Catalog:
    """Strict catalog plus the physical bytes identity used for reports."""

    version: str
    source_url: str
    captured_on: dt.date
    datasets: tuple[DatasetSpec, ...]
    sha256: str


def load_catalog(path: Path) -> Catalog:
    """Load a strict catalog; unknown keys and duplicate datasets fail closed."""
    payload = path.read_bytes()
    raw = tomllib.loads(payload.decode("utf-8"))
    if set(raw) != {"meta", "datasets"}:
        raise ValueError("TUSHARE_CATALOG_INVALID")
    meta = raw["meta"]
    if type(meta) is not dict or set(meta) != {
        "schema_version", "catalog_version", "source_url", "captured_on"
    }:
        raise ValueError("TUSHARE_CATALOG_INVALID")
    if meta["schema_version"] != CATALOG_SCHEMA:
        raise ValueError("TUSHARE_CATALOG_INVALID")
    captured_on = _date_value(meta["captured_on"])
    raw_datasets = raw["datasets"]
    if type(raw_datasets) is not list or not raw_datasets:
        raise ValueError("TUSHARE_CATALOG_INVALID")
    datasets = tuple(_dataset_spec(item) for item in raw_datasets)
    names = tuple(item.name for item in datasets)
    if len(set(names)) != len(names):
        raise ValueError("TUSHARE_CATALOG_INVALID")
    return Catalog(
        version=_nonempty_string(meta["catalog_version"]),
        source_url=_nonempty_string(meta["source_url"]),
        captured_on=captured_on,
        datasets=datasets,
        sha256=hashlib.sha256(payload).hexdigest(),
    )


def probe_permissions(
    *,
    catalog: Catalog,
    client: QueryClient,
    priorities: frozenset[Priority] = frozenset({"core", "extended", "archive"}),
    dataset_names: frozenset[str] | None = None,
    base_report: Mapping[str, object] | None = None,
    requests_per_minute: int = 120,
    now: dt.datetime | None = None,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, object]:
    """Probe each selected dataset once and return a sanitized report value."""
    if not priorities or not priorities <= {"core", "extended", "archive"}:
        raise ValueError("TUSHARE_PROBE_INVALID")
    if type(requests_per_minute) is not int or not 1 <= requests_per_minute <= 500:
        raise ValueError("TUSHARE_PROBE_INVALID")
    observed_at = now or dt.datetime.now(dt.timezone.utc)
    if observed_at.tzinfo is None:
        raise ValueError("TUSHARE_PROBE_INVALID")
    if dataset_names is not None:
        known = {item.name for item in catalog.datasets}
        if not dataset_names or not dataset_names <= known:
            raise ValueError("TUSHARE_PROBE_INVALID")
    previous: dict[str, dict[str, object]] = {}
    if base_report is not None:
        _validate_permission_report(base_report, catalog)
        previous = {
            cast(str, row["dataset"]): row
            for row in cast(list[dict[str, object]], base_report["results"])
        }
    interval = 60.0 / requests_per_minute
    results: list[dict[str, object]] = []
    query_number = 0
    for item in catalog.datasets:
        selected = item.priority in priorities and (
            dataset_names is None or item.name in dataset_names
        )
        if not selected or item.probe_mode == "manual":
            results.append(previous.get(item.name, _probe_row(item, "NOT_PROBED", None)))
            continue
        if query_number:
            sleeper(interval)
        query_number += 1
        try:
            response = client.query(item.api_name, **dict(item.probe_params))
        except Exception as exc:  # SDK exception types are not stable across versions.
            results.append(_probe_row(item, _classify_probe_exception(exc), None))
            continue
        rows = _response_rows(response)
        status: ProbeStatus = "ACCESSIBLE" if rows else "EMPTY_BUT_VALID"
        results.append(_probe_row(item, status, rows))
    return {
        "schema_version": REPORT_SCHEMA,
        "catalog_version": catalog.version,
        "catalog_sha256": catalog.sha256,
        "probed_at": observed_at.astimezone(dt.timezone.utc).isoformat(),
        "requests_per_minute": requests_per_minute,
        "query_count": query_number,
        "results": results,
    }


def build_request_plan(
    *,
    catalog: Catalog,
    permission_report: Mapping[str, object],
    data_root: Path,
    as_of: dt.date,
    now: dt.datetime | None = None,
) -> dict[str, object]:
    """Build a no-network request-count plan from probe results and clean inventory."""
    _validate_permission_report(permission_report, catalog)
    if type(as_of) is not dt.date:
        raise ValueError("TUSHARE_PLAN_INVALID")
    observed_at = now or dt.datetime.now(dt.timezone.utc)
    if observed_at.tzinfo is None:
        raise ValueError("TUSHARE_PLAN_INVALID")
    root = data_root.resolve(strict=True)
    inventory = _inventory_counts(root)
    open_dates = _open_dates(root)
    status_by_name = {
        cast(str, row["dataset"]): cast(str, row["status"])
        for row in cast(list[dict[str, object]], permission_report["results"])
    }
    rows: list[dict[str, object]] = []
    total = 0
    unresolved = 0
    for item in catalog.datasets:
        status = status_by_name[item.name]
        estimate, blocker = _estimate_requests(
            item=item,
            status=status,
            inventory=inventory,
            open_dates=open_dates,
            as_of=as_of,
        )
        if estimate is not None:
            total += estimate
        if blocker is not None:
            unresolved += 1
        rows.append({
            "dataset": item.name,
            "api_name": item.api_name,
            "category": item.category,
            "priority": item.priority,
            "permission_status": status,
            "request_unit": item.request_unit,
            "estimated_requests": estimate,
            "blocker": blocker,
            "partition": item.partition,
            "overlap_days": item.overlap_days,
        })
    return {
        "schema_version": PLAN_SCHEMA,
        "catalog_version": catalog.version,
        "catalog_sha256": catalog.sha256,
        "permission_report_sha256": _json_sha256(permission_report),
        "planned_at": observed_at.astimezone(dt.timezone.utc).isoformat(),
        "as_of": as_of.isoformat(),
        "inventory": inventory,
        "summary": {
            "datasets": len(rows),
            "estimated_requests": total,
            "unresolved_datasets": unresolved,
            "historical_download_authorized": False,
        },
        "datasets": rows,
    }


def write_run_document(*, data_root: Path, kind: Literal["permission", "plan"], value: object) -> Path:
    """Write one immutable, sanitized run document under the shared run_state."""
    root = data_root.resolve(strict=True)
    payload = _json_bytes(value)
    digest = hashlib.sha256(payload).hexdigest()
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    directory = root / "run_state" / "tushare_bulk" / f"{kind}_reports"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{stamp}-{digest[:12]}.json"
    with path.open("xb") as stream:
        stream.write(payload)
        stream.flush()
    return path


def main(argv: Sequence[str] | None = None) -> int:
    """Run catalog summary, permission probe or no-network request planning."""
    parser = argparse.ArgumentParser(description="Tushare 全量目录、权限探测与请求规划")
    parser.add_argument(
        "--catalog", type=Path, default=Path("configs/data/tushare_bulk_v1.toml")
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    summary = subparsers.add_parser("catalog-summary")
    summary.add_argument("--priority", choices=["all", "core", "extended", "archive"], default="all")

    probe = subparsers.add_parser("probe")
    probe.add_argument("--data-root", type=Path)
    probe.add_argument("--config", type=Path)
    probe.add_argument("--priority", choices=["all", "core", "extended", "archive"], default="all")
    probe.add_argument("--dataset", action="append", default=[])
    probe.add_argument("--base-report", type=Path)
    probe.add_argument("--requests-per-minute", type=int, default=120)

    plan = subparsers.add_parser("plan")
    plan.add_argument("--data-root", type=Path)
    plan.add_argument("--permission-report", type=Path, required=True)
    plan.add_argument("--as-of", type=dt.date.fromisoformat, default=dt.date.today())

    args = parser.parse_args(argv)
    catalog = load_catalog(args.catalog.resolve(strict=True))
    if args.command == "catalog-summary":
        selected = _priority_set(args.priority)
        datasets = [item for item in catalog.datasets if item.priority in selected]
        print(json.dumps({
            "catalog_version": catalog.version,
            "catalog_sha256": catalog.sha256,
            "datasets": len(datasets),
            "query_probes": sum(item.probe_mode == "query" for item in datasets),
            "manual_probes": sum(item.probe_mode == "manual" for item in datasets),
        }, ensure_ascii=False, sort_keys=True))
        return 0
    data_root = resolve_data_root(args.data_root)
    if args.command == "probe":
        connector = TushareConnector(config_path=args.config)
        base_report = (
            _read_json_object(args.base_report) if args.base_report is not None else None
        )
        report = probe_permissions(
            catalog=catalog,
            client=cast(QueryClient, connector.client),
            priorities=_priority_set(args.priority),
            dataset_names=frozenset(args.dataset) if args.dataset else None,
            base_report=base_report,
            requests_per_minute=args.requests_per_minute,
        )
        path = write_run_document(data_root=data_root, kind="permission", value=report)
        print(json.dumps({"report": str(path), "summary": _status_counts(report)}, ensure_ascii=False))
        return 0
    report = _read_json_object(args.permission_report)
    request_plan = build_request_plan(
        catalog=catalog,
        permission_report=report,
        data_root=data_root,
        as_of=args.as_of,
    )
    path = write_run_document(data_root=data_root, kind="plan", value=request_plan)
    print(json.dumps({"plan": str(path), "summary": request_plan["summary"]}, ensure_ascii=False))
    return 0


def _dataset_spec(value: object) -> DatasetSpec:
    if type(value) is not dict:
        raise ValueError("TUSHARE_CATALOG_INVALID")
    allowed = {
        "name", "api_name", "category", "priority", "probe_mode", "probe_params",
        "request_unit", "inventory", "history_start", "max_rows", "chunk_days",
        "partition", "overlap_days",
    }
    if set(value) != allowed:
        raise ValueError("TUSHARE_CATALOG_INVALID")
    raw = cast(dict[str, object], value)
    priority = _choice(raw["priority"], {"core", "extended", "archive"})
    probe_mode = _choice(raw["probe_mode"], {"query", "manual"})
    request_unit = _choice(
        raw["request_unit"], {"once", "per_symbol", "per_trade_date", "per_month", "manual"}
    )
    inventory = _choice(
        raw["inventory"],
        {"none", "stock", "fund", "hk_stock", "future", "option", "index", "convertible_bond"},
    )
    params = raw["probe_params"]
    if type(params) is not dict or not all(
        type(key) is str and type(item) is str for key, item in params.items()
    ):
        raise ValueError("TUSHARE_CATALOG_INVALID")
    history = raw["history_start"]
    history_start = None if history == "" else _date_value(history)
    return DatasetSpec(
        name=_safe_name(raw["name"]),
        api_name=_safe_name(raw["api_name"]),
        category=_safe_name(raw["category"]),
        priority=cast(Priority, priority),
        probe_mode=cast(ProbeMode, probe_mode),
        probe_params=cast(dict[str, str], params),
        request_unit=cast(RequestUnit, request_unit),
        inventory=cast(Inventory, inventory),
        history_start=history_start,
        max_rows=_nonnegative_int(raw["max_rows"]),
        chunk_days=_positive_int(raw["chunk_days"]),
        partition=_nonempty_string(raw["partition"]),
        overlap_days=_nonnegative_int(raw["overlap_days"]),
    )


def _probe_row(item: DatasetSpec, status: ProbeStatus, rows: int | None) -> dict[str, object]:
    return {
        "dataset": item.name,
        "api_name": item.api_name,
        "category": item.category,
        "priority": item.priority,
        "status": status,
        "rows": rows,
    }


def _classify_probe_exception(exc: Exception) -> ProbeStatus:
    try:
        text = str(exc).casefold()
    except Exception:
        return "PROBE_FAILED"
    if any(marker in text for marker in ("2002", "权限", "permission", "积分不足")):
        return "PERMISSION_DENIED"
    if any(marker in text for marker in ("频率", "每分钟", "rate limit", "too many")):
        return "RATE_LIMITED"
    if any(marker in text for marker in ("参数", "parameter", "必选", "格式")):
        return "PARAMETER_INVALID"
    return "PROBE_FAILED"


def _response_rows(value: object) -> int:
    if isinstance(value, pl.DataFrame):
        return value.height
    shape = getattr(value, "shape", None)
    if type(shape) is tuple and shape and type(shape[0]) is int:
        return cast(int, shape[0])
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return len(value)
    raise ValueError("TUSHARE_PROBE_RESPONSE_INVALID")


def _validate_permission_report(report: Mapping[str, object], catalog: Catalog) -> None:
    expected = {
        "schema_version", "catalog_version", "catalog_sha256", "probed_at",
        "requests_per_minute", "query_count", "results",
    }
    if set(report) != expected:
        raise ValueError("TUSHARE_PERMISSION_REPORT_INVALID")
    if (
        report["schema_version"] != REPORT_SCHEMA
        or report["catalog_version"] != catalog.version
        or report["catalog_sha256"] != catalog.sha256
    ):
        raise ValueError("TUSHARE_PERMISSION_REPORT_INVALID")
    results = report["results"]
    if type(results) is not list or len(results) != len(catalog.datasets):
        raise ValueError("TUSHARE_PERMISSION_REPORT_INVALID")
    expected_names = [item.name for item in catalog.datasets]
    actual_names: list[str] = []
    allowed_status = {
        "ACCESSIBLE", "EMPTY_BUT_VALID", "PERMISSION_DENIED", "RATE_LIMITED",
        "PARAMETER_INVALID", "PROBE_FAILED", "NOT_PROBED",
    }
    for spec, row in zip(catalog.datasets, results, strict=True):
        if type(row) is not dict or set(row) != {
            "dataset", "api_name", "category", "priority", "status", "rows"
        }:
            raise ValueError("TUSHARE_PERMISSION_REPORT_INVALID")
        if (
            row["api_name"] != spec.api_name
            or row["category"] != spec.category
            or row["priority"] != spec.priority
            or row["status"] not in allowed_status
            or (row["rows"] is not None and type(row["rows"]) is not int)
        ):
            raise ValueError("TUSHARE_PERMISSION_REPORT_INVALID")
        actual_names.append(cast(str, row["dataset"]))
    if actual_names != expected_names:
        raise ValueError("TUSHARE_PERMISSION_REPORT_INVALID")


def _inventory_counts(root: Path) -> dict[str, int]:
    instrument_root = root / "clean" / "instrument"
    paths = sorted(instrument_root.glob("market=*/data.parquet"))
    if not paths:
        return {name: 0 for name in ("stock", "fund", "hk_stock", "future", "option", "index", "convertible_bond")}
    frame = pl.concat([pl.read_parquet(path) for path in paths], how="vertical_relaxed")
    return {
        "stock": frame.filter(
            pl.col("market").is_in(["SH", "SZ"]) & (pl.col("instrument_type") == "STOCK")
        ).height,
        "fund": frame.filter(
            pl.col("market").is_in(["SH", "SZ"]) & (pl.col("instrument_type") == "ETF")
        ).height,
        "hk_stock": frame.filter(
            (pl.col("market") == "HK") & (pl.col("instrument_type") == "STOCK")
        ).height,
        "future": 0,
        "option": 0,
        "index": 0,
        "convertible_bond": 0,
    }


def _open_dates(root: Path) -> tuple[dt.date, ...]:
    path = root / "clean" / "trade_calendar" / "market=SH" / "data.parquet"
    if not path.exists():
        return ()
    frame = pl.read_parquet(path).filter(pl.col("is_open"))
    return tuple(sorted(cast(list[dt.date], frame.get_column("date").to_list())))


def _estimate_requests(
    *, item: DatasetSpec,
    status: str,
    inventory: Mapping[str, int],
    open_dates: tuple[dt.date, ...],
    as_of: dt.date,
) -> tuple[int | None, str | None]:
    if status == "PERMISSION_DENIED":
        return None, "PERMISSION_DENIED"
    if status in {"RATE_LIMITED", "PARAMETER_INVALID", "PROBE_FAILED", "NOT_PROBED"}:
        return None, status
    if status == "EMPTY_BUT_VALID":
        return None, "EMPTY_PROBE_REVIEW_REQUIRED"
    if item.request_unit == "manual":
        return None, "MANUAL_SUBPLAN_REQUIRED"
    if item.request_unit == "once":
        return 1, None
    start = item.history_start
    if start is None:
        return None, "HISTORY_START_REQUIRED"
    if item.request_unit == "per_trade_date":
        if not open_dates:
            return None, "TRADE_CALENDAR_REQUIRED"
        return sum(start <= value <= as_of for value in open_dates), None
    if item.request_unit == "per_month":
        months = (as_of.year - start.year) * 12 + as_of.month - start.month + 1
        return max(months, 0), None
    count = inventory[item.inventory]
    if count <= 0:
        return None, f"{item.inventory.upper()}_INVENTORY_REQUIRED"
    chunks = max(1, math.ceil(((as_of - start).days + 1) / item.chunk_days))
    return count * chunks, None


def _priority_set(value: str) -> frozenset[Priority]:
    if value == "all":
        return frozenset({"core", "extended", "archive"})
    return frozenset({cast(Priority, value)})


def _status_counts(report: Mapping[str, object]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in cast(list[dict[str, object]], report["results"]):
        status = cast(str, row["status"])
        counts[status] = counts.get(status, 0) + 1
    return dict(sorted(counts.items()))


def _read_json_object(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if type(value) is not dict:
        raise ValueError("TUSHARE_PERMISSION_REPORT_INVALID")
    return cast(dict[str, object], value)


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _json_sha256(value: object) -> str:
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _safe_name(value: object) -> str:
    text = _nonempty_string(value)
    if not all(char.isascii() and (char.isalnum() or char == "_") for char in text):
        raise ValueError("TUSHARE_CATALOG_INVALID")
    return text


def _nonempty_string(value: object) -> str:
    if type(value) is not str or not value:
        raise ValueError("TUSHARE_CATALOG_INVALID")
    return value


def _choice(value: object, allowed: set[str]) -> str:
    if type(value) is not str or value not in allowed:
        raise ValueError("TUSHARE_CATALOG_INVALID")
    return value


def _positive_int(value: object) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError("TUSHARE_CATALOG_INVALID")
    return value


def _nonnegative_int(value: object) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("TUSHARE_CATALOG_INVALID")
    return value


def _date_value(value: object) -> dt.date:
    if type(value) is dt.date:
        return value
    if type(value) is str:
        try:
            return dt.date.fromisoformat(value)
        except ValueError:
            pass
    raise ValueError("TUSHARE_CATALOG_INVALID")


if __name__ == "__main__":
    raise SystemExit(main())
