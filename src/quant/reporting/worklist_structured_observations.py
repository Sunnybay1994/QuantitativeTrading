"""D2 acceptance from naturally scheduled captures, separate from query counts."""

import datetime as dt
import hashlib
import tomllib
from pathlib import Path

import polars as pl

from quant.data.structured_availability import sessions
from quant.reporting.worklist_dated_observations import SH, native_match, read, stamp

TABLES = frozenset((
    "forecast", "express", "repurchase", "stk_holdertrade", "share_float",
    "margin_detail", "stk_holdernumber", "fund_share", "report_rc",
))
TASK = "QuantitativeTrading-StructuredDaily"


def _path(root, value, parent):
    path = Path(value)
    path = (path if path.is_absolute() else root / path).resolve()
    if not path.is_relative_to(parent.resolve()):
        raise ValueError("D2 evidence outside its project data directory")
    return path


def _table(root, folder, name, item, start, end):
    count, added = item.get("rows"), item.get("new_rows")
    if (item.get("status") != "captured" or item.get("permission") != "standard"
            or item.get("auto_trade") is not False
            or type(count) is not int or type(added) is not int
            or not 0 < added <= count):
        raise ValueError(f"{name}: no fully captured positive increment")
    published = _path(root, item["published"], root / "data/clean" / name)
    if published != (root / "data/clean" / name / ("snapshot=d2_" + folder.name)).resolve():
        raise ValueError(f"{name}: publication does not belong to this capture")
    source = read(published / "summary.json")
    for key in ("rows", "new_rows", "status", "checked_at", "checked_through", "auto_trade"):
        if source.get(key) != item.get(key):
            raise ValueError(f"{name}: published summary differs from capture")
    if (_path(root, source["source_receipt"], folder) != (folder / "summary.json").resolve()
            or not start <= stamp(source["checked_at"]) <= end):
        raise ValueError(f"{name}: publication belongs to another capture time")
    requests = item.get("requests", {})
    if not requests:
        raise ValueError(f"{name}: native request evidence missing")
    paths = []
    for request in requests.values():
        if not start <= stamp(request["observed_at"]) <= end:
            raise ValueError(f"{name}: reused request is not a new query in this task")
        raw = _path(root, request["raw_path"], root / "data/raw")
        if hashlib.sha256(raw.read_bytes()).hexdigest() != request["sha256"]:
            raise ValueError(f"{name}: native raw hash mismatch")
        paths.append(raw)
    data = published / "data.parquet"
    frame = pl.read_parquet(data)
    if (frame.height != count or "source_row_id" not in frame.columns
            or frame["source_row_id"].null_count()
            or frame["source_row_id"].n_unique() != count):
        raise ValueError(f"{name}: published row counts or identities differ")
    for column in ("observed_at", "available_at"):
        dtype = frame.schema.get(column)
        if not isinstance(dtype, pl.Datetime) or dtype.time_zone is None:
            raise ValueError(f"{name}: missing zoned arrival timestamps")
    if frame.filter(
        pl.col("observed_at").is_null() | pl.col("available_at").is_null()
        | (pl.col("observed_at") < start) | (pl.col("observed_at") > end)
        | (pl.col("available_at") < pl.col("observed_at"))
        | (pl.col("available_at") > end)
    ).height:
        raise ValueError(f"{name}: published rows do not have this task's arrival times")
    return dict(new_rows=added, rows=count, checked_through=item["checked_through"],
                raw_pages=len(set(paths)), published=str(published))


def _capture(root, folder, clock, history, config_hash):
    summary, pipeline = read(folder / "summary.json"), read(folder / "pipeline.json")
    if (summary.get("auto_trade") is not False or summary.get("status") != "checked"
            or set(summary.get("selected_tables", [])) != TABLES
            or set(summary.get("tables", {})) != TABLES
            or summary.get("config_sha256") != config_hash
            or pipeline.get("auto_trade") is not False
            or pipeline.get("status") != "checked" or pipeline.get("structured_status") != "checked"):
        raise ValueError("D2 capture is partial or does not cover the fixed nine tables")
    if hashlib.sha256((folder / "summary.json").read_bytes()).hexdigest() != pipeline["structured_receipt_sha256"]:
        raise ValueError("D2 combined receipt does not match the completed capture")
    if _path(root, pipeline["structured_receipt"], folder) != (folder / "summary.json").resolve():
        raise ValueError("D2 pipeline references another capture")
    day = dt.date.fromisoformat(summary["as_of"])
    start, end = stamp(summary["observed_at"]), stamp(summary["finished_at"])
    native = native_match(history, TASK, day, clock,
                          [folder / "summary.json", folder / "pipeline.json"])
    if (not stamp(native["started_at"]) <= start <= end <= stamp(native["finished_at"])
            or start.astimezone(SH).date() != day or end.astimezone(SH).date() != day
            or end.astimezone(SH).time() >= dt.time(20, 30)
            or pipeline.get("as_of") != str(day)):
        raise ValueError("D2 capture does not belong to this natural scheduler instance")
    tables = {name: _table(root, folder, name, summary["tables"][name], start, end)
              for name in sorted(TABLES)}
    return dict(day=str(day), native=native, tables=tables, receipt=str(folder / "pipeline.json"))


def evaluate(root, clock, history=None):
    """Never promote five successful/manual/empty queries to five daily increments."""
    if clock.tzinfo is None:
        raise ValueError("D2 observation requires a zoned actual clock")
    root = Path(root).resolve()
    result = dict(status="unverified", verified=False, observed_at=clock.isoformat(),
                  required_tables=sorted(TABLES), required_consecutive_trading_days=5,
                  verified_days=[], longest_consecutive_days=0, captures=[], issues=[],
                  scope="Natural zero-exit tasks and positive new rows for all nine tables; "
                        "query counts and empty successful checks do not prove this requirement.")
    try:
        config = root / "configs/data/structured_sources.toml"
        payload = config.read_bytes()
        spec = tomllib.loads(payload.decode("utf-8"))
        if spec.get("auto_trade") is not False or set(spec.get("tables", {})) != TABLES:
            raise ValueError("D2 fixed nine-table configuration missing")
        calendar = sessions(root / "data")
        if not calendar or calendar[-1] < clock.astimezone(SH).date():
            raise ValueError("Exchange calendar does not cover actual observation date")
        captures = []
        for path in sorted((root / "artifacts/data/structured_incremental").glob("*/pipeline.json")):
            try:
                captures.append(_capture(root, path.parent, clock, history,
                                         hashlib.sha256(payload).hexdigest()))
            except (OSError, ValueError, KeyError, TypeError, pl.exceptions.PolarsError) as exc:
                result["issues"].append(dict(receipt=str(path), issue=str(exc)))
        by_day = {row["day"]: row for row in captures}
        streak = []
        for day in calendar:
            if day > clock.astimezone(SH).date():
                break
            streak = streak + [str(day)] if str(day) in by_day else []
            if len(streak) > result["longest_consecutive_days"]:
                result.update(longest_consecutive_days=len(streak), verified_days=streak.copy())
        result["captures"] = [by_day[day] for day in result["verified_days"]]
        result["verified"] = result["longest_consecutive_days"] >= 5
        result["status"] = "verified" if result["verified"] else "unverified"
        result["query_success_is_increment_acceptance"] = False
    except (OSError, ValueError, KeyError, TypeError, pl.exceptions.PolarsError) as exc:
        result["issues"].append(dict(issue=str(exc)))
    return result
