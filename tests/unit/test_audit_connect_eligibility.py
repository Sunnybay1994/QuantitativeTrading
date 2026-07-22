import datetime as dt
import json
import os
from pathlib import Path

import polars as pl
import pytest

from quant.data.audit_connect_eligibility import main
from quant.data.eligibility import (
    EligibilityHistoryError,
    build_membership_intervals_from_reverse_audit,
    verify_reverse_eligibility_history,
)
from quant.data.storage import CleanConnectEventStore, CleanConnectSnapshotStore


def _hk(n: int) -> str:
    return f"{n:05d}.HK"


def _snapshot_frame(
    symbols: list[str],
    *,
    route: str = "SH_CONNECT",
    snapshot_date: dt.date = dt.date(2026, 7, 10),
) -> pl.DataFrame:
    source = "sse" if route == "SH_CONNECT" else "szse"
    n = len(symbols)
    return pl.DataFrame(
        {
            "route": [route] * n,
            "snapshot_date": [snapshot_date] * n,
            "symbol": symbols,
            "name_cn": ["n"] * n,
            "name_en": ["e"] * n,
            "security_type": ["STOCK"] * n,
            "buy_eligible": [True] * n,
            "source": [source] * n,
        }
    )


def _events_frame(
    rows: list[tuple[dt.date, str, str]],
    *,
    route: str = "SH_CONNECT",
) -> pl.DataFrame:
    source = "sse" if route == "SH_CONNECT" else "szse"
    n = len(rows)
    return pl.DataFrame(
        {
            "route": [route] * n,
            "effective_date": [row[0] for row in rows],
            "symbol": [row[1] for row in rows],
            "action": [row[2] for row in rows],
            "name_cn": [""] * n,
            "name_en": [""] * n,
            "security_type": ["STOCK"] * n,
            "published_date": [None] * n,
            "source": [source] * n,
        },
        schema={
            "route": pl.String,
            "effective_date": pl.Date,
            "symbol": pl.String,
            "action": pl.String,
            "name_cn": pl.String,
            "name_en": pl.String,
            "security_type": pl.String,
            "published_date": pl.Date,
            "source": pl.String,
        },
    )


def _build_reverse_fixture(
    *,
    route: str,
    baseline_count: int,
    baseline_date: dt.date,
    snapshot_date: dt.date,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """baseline N → ADD one + REMOVE one → snapshot still N; reverse recovers N."""
    baseline = [_hk(i) for i in range(1, baseline_count + 1)]
    added = _hk(baseline_count + 1)
    removed = baseline[0]
    current = sorted(set(baseline) - {removed} | {added})
    events = _events_frame(
        [
            (baseline_date + dt.timedelta(days=30), added, "ADD"),
            (baseline_date + dt.timedelta(days=60), removed, "REMOVE"),
        ],
        route=route,
    )
    snap = _snapshot_frame(current, route=route, snapshot_date=snapshot_date)
    return snap, events


def test_sh_fixture_reverse_to_268() -> None:
    snap, events = _build_reverse_fixture(
        route="SH_CONNECT",
        baseline_count=268,
        baseline_date=dt.date(2014, 11, 17),
        snapshot_date=dt.date(2026, 7, 10),
    )
    audit = verify_reverse_eligibility_history(
        snap,
        events,
        route="SH_CONNECT",
        baseline_date=dt.date(2014, 11, 17),
        expected_baseline_count=268,
    )
    assert audit.reverse_count == 268
    assert len(audit.baseline_symbols) == 268
    assert audit.route == "SH_CONNECT"


def test_sz_fixture_reverse_to_417() -> None:
    snap, events = _build_reverse_fixture(
        route="SZ_CONNECT",
        baseline_count=417,
        baseline_date=dt.date(2016, 12, 5),
        snapshot_date=dt.date(2026, 7, 10),
    )
    audit = verify_reverse_eligibility_history(
        snap,
        events,
        route="SZ_CONNECT",
        baseline_date=dt.date(2016, 12, 5),
        expected_baseline_count=417,
    )
    assert audit.reverse_count == 417


def test_row_order_does_not_change_result() -> None:
    snap, events = _build_reverse_fixture(
        route="SH_CONNECT",
        baseline_count=10,
        baseline_date=dt.date(2020, 1, 1),
        snapshot_date=dt.date(2021, 1, 1),
    )
    shuffled = events.reverse()
    a = verify_reverse_eligibility_history(
        snap,
        events,
        route="SH_CONNECT",
        baseline_date=dt.date(2020, 1, 1),
        expected_baseline_count=10,
    )
    b = verify_reverse_eligibility_history(
        snap.reverse(),
        shuffled,
        route="SH_CONNECT",
        baseline_date=dt.date(2020, 1, 1),
        expected_baseline_count=10,
    )
    assert a.baseline_symbols == b.baseline_symbols
    assert a.reverse_count == b.reverse_count == 10


def test_reverse_add_missing_active_state_conflict() -> None:
    snap = _snapshot_frame(["00002.HK"], snapshot_date=dt.date(2021, 1, 1))
    events = _events_frame(
        [(dt.date(2020, 6, 1), "00001.HK", "ADD")],
    )
    with pytest.raises(EligibilityHistoryError, match="REVERSE_AUDIT_STATE_CONFLICT"):
        verify_reverse_eligibility_history(
            snap,
            events,
            route="SH_CONNECT",
            baseline_date=dt.date(2020, 1, 1),
            expected_baseline_count=1,
        )


def test_reverse_remove_already_active_state_conflict() -> None:
    snap = _snapshot_frame(["00001.HK", "00002.HK"], snapshot_date=dt.date(2021, 1, 1))
    events = _events_frame(
        [(dt.date(2020, 6, 1), "00001.HK", "REMOVE")],
    )
    with pytest.raises(EligibilityHistoryError, match="REVERSE_AUDIT_STATE_CONFLICT"):
        verify_reverse_eligibility_history(
            snap,
            events,
            route="SH_CONNECT",
            baseline_date=dt.date(2020, 1, 1),
            expected_baseline_count=1,
        )


def test_same_day_add_remove_event_conflict() -> None:
    snap = _snapshot_frame(["00001.HK"], snapshot_date=dt.date(2021, 1, 1))
    day = dt.date(2020, 6, 1)
    events = _events_frame(
        [(day, "00002.HK", "ADD"), (day, "00002.HK", "REMOVE")],
    )
    with pytest.raises(EligibilityHistoryError, match="REVERSE_AUDIT_EVENT_CONFLICT"):
        verify_reverse_eligibility_history(
            snap,
            events,
            route="SH_CONNECT",
            baseline_date=dt.date(2020, 1, 1),
            expected_baseline_count=1,
        )


def test_count_mismatch() -> None:
    snap = _snapshot_frame(["00001.HK", "00002.HK"], snapshot_date=dt.date(2021, 1, 1))
    events = _events_frame([])
    with pytest.raises(EligibilityHistoryError, match="REVERSE_AUDIT_COUNT_MISMATCH"):
        verify_reverse_eligibility_history(
            snap,
            events,
            route="SH_CONNECT",
            baseline_date=dt.date(2020, 1, 1),
            expected_baseline_count=3,
        )


def test_event_before_baseline_not_silently_filtered() -> None:
    snap = _snapshot_frame(["00001.HK"], snapshot_date=dt.date(2021, 1, 1))
    events = _events_frame(
        [(dt.date(2019, 12, 31), "00002.HK", "ADD")],
    )
    with pytest.raises(EligibilityHistoryError, match="REVERSE_AUDIT_COVERAGE_INVALID"):
        verify_reverse_eligibility_history(
            snap,
            events,
            route="SH_CONNECT",
            baseline_date=dt.date(2020, 1, 1),
            expected_baseline_count=1,
        )


def test_rejects_bool_int_datetime_and_illegal_route() -> None:
    snap = _snapshot_frame(["00001.HK"], snapshot_date=dt.date(2021, 1, 1))
    events = _events_frame([])
    with pytest.raises(EligibilityHistoryError, match="REVERSE_AUDIT_INPUT_INVALID"):
        verify_reverse_eligibility_history(
            snap.with_columns(pl.col("buy_eligible").cast(pl.Int8)),
            events,
            route="SH_CONNECT",
            baseline_date=dt.date(2020, 1, 1),
            expected_baseline_count=1,
        )
    with pytest.raises(EligibilityHistoryError, match="REVERSE_AUDIT_INPUT_INVALID"):
        verify_reverse_eligibility_history(
            snap.with_columns(pl.col("snapshot_date").cast(pl.Datetime("us"))),
            events,
            route="SH_CONNECT",
            baseline_date=dt.date(2020, 1, 1),
            expected_baseline_count=1,
        )
    with pytest.raises(EligibilityHistoryError, match="REVERSE_AUDIT_INPUT_INVALID"):
        verify_reverse_eligibility_history(
            snap,
            events,
            route="BAD_ROUTE",  # type: ignore[arg-type]
            baseline_date=dt.date(2020, 1, 1),
            expected_baseline_count=1,
        )
    with pytest.raises(EligibilityHistoryError, match="REVERSE_AUDIT_INPUT_INVALID"):
        verify_reverse_eligibility_history(
            snap,
            events,
            route="SH_CONNECT",
            baseline_date=dt.datetime(2020, 1, 1),  # type: ignore[arg-type]
            expected_baseline_count=1,
        )
    with pytest.raises(EligibilityHistoryError, match="REVERSE_AUDIT_INPUT_INVALID"):
        verify_reverse_eligibility_history(
            snap,
            events,
            route="SH_CONNECT",
            baseline_date=dt.date(2020, 1, 1),
            expected_baseline_count=True,  # type: ignore[arg-type]
        )


def test_error_message_has_no_symbol_or_path() -> None:
    snap = _snapshot_frame(["00002.HK"], snapshot_date=dt.date(2021, 1, 1))
    events = _events_frame([(dt.date(2020, 6, 1), "00099.HK", "ADD")])
    with pytest.raises(EligibilityHistoryError) as caught:
        verify_reverse_eligibility_history(
            snap,
            events,
            route="SH_CONNECT",
            baseline_date=dt.date(2020, 1, 1),
            expected_baseline_count=1,
        )
    text = str(caught.value)
    assert "00099" not in text
    assert "00002" not in text
    assert "/" not in text
    assert "\\" not in text
    assert text == "REVERSE_AUDIT_STATE_CONFLICT"


def test_cli_success_json_omits_symbols_and_paths(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    snap, events = _build_reverse_fixture(
        route="SH_CONNECT",
        baseline_count=5,
        baseline_date=dt.date(2020, 1, 1),
        snapshot_date=dt.date(2021, 6, 1),
    )
    data_root = tmp_path / "data"
    CleanConnectSnapshotStore(data_root / "clean" / "connect_snapshot").upsert(snap)
    CleanConnectEventStore(data_root / "clean" / "connect_event").upsert(events)
    snap_path = (
        data_root
        / "clean"
        / "connect_snapshot"
        / "route=SH_CONNECT"
        / "date=2021-06-01"
        / "data.parquet"
    )
    event_path = data_root / "clean" / "connect_event" / "route=SH_CONNECT" / "data.parquet"
    before_snap = snap_path.read_bytes()
    before_event = event_path.read_bytes()
    before_snap_mtime = os.lstat(snap_path).st_mtime_ns
    before_event_mtime = os.lstat(event_path).st_mtime_ns

    code = main(
        [
            "--route",
            "SH_CONNECT",
            "--snapshot-date",
            "2021-06-01",
            "--baseline-date",
            "2020-01-01",
            "--expected-baseline-count",
            "5",
            "--data-root",
            str(data_root),
        ]
    )
    assert code == 0
    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    assert payload["status"] == "PASS"
    assert payload["reverse_count"] == 5
    assert "baseline_symbols" not in payload
    assert "symbols" not in payload
    blob = json.dumps(payload)
    assert "0000" not in blob
    assert "data.parquet" not in blob
    assert str(data_root) not in blob
    assert snap_path.read_bytes() == before_snap
    assert event_path.read_bytes() == before_event
    assert os.lstat(snap_path).st_mtime_ns == before_snap_mtime
    assert os.lstat(event_path).st_mtime_ns == before_event_mtime


def test_cli_failure_has_no_success_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    snap = _snapshot_frame(["00001.HK"], snapshot_date=dt.date(2021, 6, 1))
    data_root = tmp_path / "data"
    CleanConnectSnapshotStore(data_root / "clean" / "connect_snapshot").upsert(snap)
    CleanConnectEventStore(data_root / "clean" / "connect_event").upsert(_events_frame([]))
    code = main(
        [
            "--route",
            "SH_CONNECT",
            "--snapshot-date",
            "2021-06-01",
            "--baseline-date",
            "2020-01-01",
            "--expected-baseline-count",
            "9",
            "--data-root",
            str(data_root),
        ]
    )
    assert code != 0
    out = capsys.readouterr().out
    assert "PASS" not in out
    assert "baseline_symbols" not in out
    try:
        json.loads(out.strip()) if out.strip() else None
    except json.JSONDecodeError:
        pass
    else:
        if out.strip():
            payload = json.loads(out.strip())
            assert payload.get("status") != "PASS"


_DEFAULT_CLI_KEYS = {
    "route",
    "baseline_date",
    "snapshot_date",
    "expected_baseline_count",
    "current_count",
    "event_count",
    "reverse_count",
    "event_min",
    "event_max",
    "status",
}


def test_cli_default_json_keys_unchanged_without_preview(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    snap, events = _build_reverse_fixture(
        route="SH_CONNECT",
        baseline_count=5,
        baseline_date=dt.date(2020, 1, 1),
        snapshot_date=dt.date(2021, 6, 1),
    )
    data_root = tmp_path / "data"
    CleanConnectSnapshotStore(data_root / "clean" / "connect_snapshot").upsert(snap)
    CleanConnectEventStore(data_root / "clean" / "connect_event").upsert(events)
    code = main(
        [
            "--route",
            "SH_CONNECT",
            "--snapshot-date",
            "2021-06-01",
            "--baseline-date",
            "2020-01-01",
            "--expected-baseline-count",
            "5",
            "--data-root",
            str(data_root),
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out.strip())
    assert set(payload) == _DEFAULT_CLI_KEYS
    assert "membership_rows" not in payload


def test_cli_preview_membership_fields_and_readonly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline_date = dt.date(2020, 1, 1)
    snapshot_date = dt.date(2021, 6, 1)
    events = _events_frame(
        [
            (dt.date(2020, 3, 1), "00003.HK", "ADD"),
            (dt.date(2020, 6, 1), "00002.HK", "REMOVE"),
            (dt.date(2020, 9, 1), "00002.HK", "ADD"),
        ]
    )
    snap = _snapshot_frame(
        ["00001.HK", "00002.HK", "00003.HK"], snapshot_date=snapshot_date
    )
    data_root = tmp_path / "data"
    CleanConnectSnapshotStore(data_root / "clean" / "connect_snapshot").upsert(snap)
    CleanConnectEventStore(data_root / "clean" / "connect_event").upsert(events)
    snap_path = (
        data_root
        / "clean"
        / "connect_snapshot"
        / "route=SH_CONNECT"
        / "date=2021-06-01"
        / "data.parquet"
    )
    event_path = data_root / "clean" / "connect_event" / "route=SH_CONNECT" / "data.parquet"
    before_snap = snap_path.read_bytes()
    before_event = event_path.read_bytes()
    before_snap_mtime = os.lstat(snap_path).st_mtime_ns
    before_event_mtime = os.lstat(event_path).st_mtime_ns

    code = main(
        [
            "--route",
            "SH_CONNECT",
            "--snapshot-date",
            "2021-06-01",
            "--baseline-date",
            "2020-01-01",
            "--expected-baseline-count",
            "2",
            "--data-root",
            str(data_root),
            "--preview-membership",
        ]
    )
    assert code == 0
    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    assert payload["status"] == "PASS"
    assert set(payload) == _DEFAULT_CLI_KEYS | {
        "membership_rows",
        "membership_symbols",
        "coverage_start",
        "open_intervals",
    }
    assert payload["membership_rows"] == 4
    assert payload["membership_symbols"] == 3
    assert payload["coverage_start"] == baseline_date.isoformat()
    assert payload["open_intervals"] == 3
    assert "baseline_symbols" not in payload
    assert "symbols" not in payload
    blob = json.dumps(payload)
    assert "0000" not in blob
    assert "data.parquet" not in blob
    assert str(data_root) not in blob
    assert snap_path.read_bytes() == before_snap
    assert event_path.read_bytes() == before_event
    assert os.lstat(snap_path).st_mtime_ns == before_snap_mtime
    assert os.lstat(event_path).st_mtime_ns == before_event_mtime

    audit = verify_reverse_eligibility_history(
        snap,
        events,
        route="SH_CONNECT",
        baseline_date=baseline_date,
        expected_baseline_count=2,
    )
    intervals = build_membership_intervals_from_reverse_audit(
        audit=audit, snapshot=snap, events=events
    )
    assert intervals.height == payload["membership_rows"]


def test_tmp_swap_symbol_same_count_rejected(tmp_path: Path) -> None:
    """独立反例：snapshot 换 symbol 保 count，不得按 count 放行。"""
    baseline_date = dt.date(2020, 1, 1)
    snapshot_date = dt.date(2021, 1, 1)
    events = _events_frame(
        [
            (dt.date(2020, 3, 1), "00003.HK", "ADD"),
            (dt.date(2020, 6, 1), "00002.HK", "REMOVE"),
        ]
    )
    snap = _snapshot_frame(["00001.HK", "00003.HK"], snapshot_date=snapshot_date)
    audit = verify_reverse_eligibility_history(
        snap,
        events,
        route="SH_CONNECT",
        baseline_date=baseline_date,
        expected_baseline_count=2,
    )
    swapped = snap.with_columns(
        pl.when(pl.col("symbol") == "00003.HK")
        .then(pl.lit("00088.HK"))
        .otherwise(pl.col("symbol"))
        .alias("symbol")
    )
    assert swapped.height == snap.height
    # 落盘到独立 tmp，证明不依赖项目 data
    root = tmp_path / "isolated"
    CleanConnectSnapshotStore(root / "clean" / "connect_snapshot").upsert(swapped)
    CleanConnectEventStore(root / "clean" / "connect_event").upsert(events)
    with pytest.raises(
        EligibilityHistoryError,
        match="REVERSE_MEMBERSHIP_(AUDIT_MISMATCH|FINAL_STATE_MISMATCH)",
    ) as caught:
        build_membership_intervals_from_reverse_audit(
            audit=audit, snapshot=swapped, events=events
        )
    text = str(caught.value)
    assert "00088" not in text
    assert "00003" not in text
