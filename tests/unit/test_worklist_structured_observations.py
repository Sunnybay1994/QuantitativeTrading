import datetime as dt
import hashlib
import json
import os
import uuid

import polars as pl
import pytest

from quant.reporting import worklist_structured_observations as observed

SH = observed.SH
CLOCK = dt.datetime(2026, 11, 9, 12, tzinfo=SH)


def write(path, payload, at):
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, pl.DataFrame):
        payload.write_parquet(path)
    else:
        path.write_text(json.dumps(payload), encoding="utf-8")
    os.utime(path, (at.timestamp(), at.timestamp()))


@pytest.fixture
def case(tmp_path):
    config = tmp_path / "configs/data/structured_sources.toml"
    config.parent.mkdir(parents=True)
    config.write_text("auto_trade=false\n" + "".join(
        f"[tables.{name}]\npermission='standard'\n" for name in sorted(observed.TABLES)))
    dates = pl.date_range(dt.date(2026, 10, 30), dt.date(2026, 12, 1), eager=True)
    calendar = pl.DataFrame({"date": dates}).with_columns(
        (pl.col("date").dt.weekday() <= 5).alias("is_open"))
    target = tmp_path / "data/clean/trade_calendar/market=SH/data.parquet"
    target.parent.mkdir(parents=True)
    calendar.write_parquet(target)
    history = dict(enabled=True, truncated=False, error=None, events=[])
    folders = []
    for date in [dt.date(2026, 11, day) for day in range(2, 7)]:
        start = dt.datetime.combine(date, dt.time(19), SH)
        end = start + dt.timedelta(minutes=10)
        at = start + dt.timedelta(minutes=5)
        instance = str(uuid.uuid4())
        for kind, minute in [(107, 0), (201, 11), (102, 12)]:
            history["events"].append(dict(
                task="\\" + observed.TASK, instance_id=instance, event_id=kind,
                record_id=len(history["events"]) + 1,
                occurred_at=(start + dt.timedelta(minutes=minute)).isoformat(),
                result=0 if kind == 201 else None, action="powershell.exe"))
        folder = tmp_path / "artifacts/data/structured_incremental" / str(date)
        folders.append(folder)
        summary = dict(as_of=str(date), auto_trade=False, status="checked",
                       selected_tables=sorted(observed.TABLES), tables={},
                       config_sha256=hashlib.sha256(config.read_bytes()).hexdigest(),
                       observed_at=start.isoformat(), finished_at=end.isoformat())
        for name in sorted(observed.TABLES):
            published = tmp_path / "data/clean" / name / ("snapshot=d2_" + folder.name)
            raw = tmp_path / "data/raw" / name / (str(date) + ".parquet")
            frame = pl.DataFrame(dict(source_row_id=[str(date) + name],
                                      observed_at=[at], available_at=[at]))
            write(raw, frame, at)
            write(published / "data.parquet", frame, at)
            table = dict(rows=1, new_rows=1, status="captured", permission="standard",
                         checked_at=at.isoformat(), checked_through=str(date), auto_trade=False,
                         source_receipt=str(folder / "summary.json"))
            write(published / "summary.json", table, at)
            summary["tables"][name] = dict(table, published=str(published), requests={
                "request": dict(raw_path=str(raw), observed_at=at.isoformat(),
                                sha256=hashlib.sha256(raw.read_bytes()).hexdigest())})
        write(folder / "summary.json", summary, end)
        pipeline = dict(status="checked", structured_status="checked", auto_trade=False,
                        as_of=str(date), structured_receipt=str(folder / "summary.json"),
                        structured_receipt_sha256=hashlib.sha256(
                            (folder / "summary.json").read_bytes()).hexdigest())
        write(folder / "pipeline.json", pipeline, end)
    return tmp_path, history, folders


def modify(folder, update):
    path = folder / "summary.json"
    summary = observed.read(path)
    at = observed.stamp(summary["finished_at"])
    update(summary)
    write(path, summary, at)
    pipeline = observed.read(folder / "pipeline.json")
    pipeline["structured_receipt_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    write(folder / "pipeline.json", pipeline, at)


def test_five_natural_nine_table_positive_increment_days(case):
    root, history, _ = case
    result = observed.evaluate(root, CLOCK, history)
    assert result["verified"] and result["longest_consecutive_days"] == 5
    assert result["verified_days"] == [f"2026-11-0{d}" for d in range(2, 7)]
    assert len(result["captures"][-1]["tables"]) == 9
    assert result["issues"] == []


@pytest.mark.parametrize("kind", ["manual", "nonzero", "truncated", "disabled", "missing"])
def test_native_task_evidence_required(case, kind):
    root, history, _ = case
    if kind == "manual":
        for row in history["events"]:
            if row["event_id"] == 107:
                row["event_id"] = 110
    elif kind == "nonzero":
        history["events"][-2]["result"] = 1
    elif kind in ("truncated", "disabled"):
        history["truncated" if kind == "truncated" else "enabled"] = kind == "truncated"
    else:
        history = None
    assert not observed.evaluate(root, CLOCK, history)["verified"]


@pytest.mark.parametrize("kind", [
    "empty", "trial", "seed", "missing_table", "wrong_config", "raw_mutated",
    "published_mutated", "wrong_receipt", "late_product", "invalid_arrival", "missing_page",
])
def test_capture_integrity_and_real_increments(case, kind):
    root, history, folders = case
    folder = folders[2]
    published = root / "data/clean/report_rc" / ("snapshot=d2_" + folder.name)
    if kind in {"empty", "trial", "seed", "missing_table", "wrong_config", "wrong_receipt", "missing_page"}:
        def update(summary):
            row = summary["tables"]["report_rc"]
            if kind == "empty":
                row.update(status="checked_empty", rows=0, new_rows=0)
            elif kind == "trial":
                row.update(status="permission_limited")
            elif kind == "seed":
                row["requests"]["request"]["observed_at"] = "2026-11-03T19:05:00+08:00"
            elif kind == "missing_table":
                summary["tables"].pop("report_rc")
            elif kind == "wrong_config":
                summary["config_sha256"] = "bad"
            elif kind == "wrong_receipt":
                row["published"] = str(root.parent / "other_capture")
            else:
                row["requests"] = {}
        modify(folder, update)
    elif kind == "raw_mutated":
        (root / "data/raw/report_rc" / (folder.name + ".parquet")).write_bytes(b"changed")
    elif kind == "published_mutated":
        path = published / "summary.json"
        saved = observed.read(path)
        saved["new_rows"] = 500
        path.write_text(json.dumps(saved))
    elif kind == "late_product":
        path = folder / "pipeline.json"
        os.utime(path, (CLOCK.timestamp(), CLOCK.timestamp()))
    else:
        data = published / "data.parquet"
        frame = pl.read_parquet(data).with_columns(
            pl.col("available_at") - dt.timedelta(days=1))
        frame.write_parquet(data)
    result = observed.evaluate(root, CLOCK, history)
    assert not result["verified"] and result["longest_consecutive_days"] == 2
    assert result["issues"]


def test_missing_exchange_day_breaks_streak_and_future_capture_is_not_accepted(case):
    root, history, folders = case
    (folders[2] / "pipeline.json").unlink()
    assert observed.evaluate(root, CLOCK, history)["longest_consecutive_days"] == 2
    early = dt.datetime(2026, 11, 3, 20, tzinfo=SH)
    assert observed.evaluate(root, early, history)["longest_consecutive_days"] == 2


def test_naive_clock_rejected(case):
    with pytest.raises(ValueError, match="zoned"):
        observed.evaluate(case[0], CLOCK.replace(tzinfo=None), case[1])


def test_capture_completed_inside_capital_window_is_not_accepted(case):
    root, history, folders = case
    day = "2026-11-04"
    modify(folders[2], lambda summary: summary.update(finished_at=day + "T20:31:00+08:00"))
    for row in history["events"]:
        if row["occurred_at"].startswith(day) and row["event_id"] in (201, 102):
            row["occurred_at"] = day + "T20:32:00+08:00"
    assert not observed.evaluate(root, CLOCK, history)["verified"]
