"""rebuild_connect_universe CLI：snapshot 兼容与 reverse-audit 安全发布。"""

from __future__ import annotations

import datetime as dt
import json
import os
import time
from pathlib import Path

import polars as pl
import pytest

from quant.data.eligibility import (
    build_membership_intervals_from_reverse_audit,
    verify_reverse_eligibility_history,
)
from quant.data.rebuild_connect_universe import main
from quant.data.storage import (
    CleanConnectEventStore,
    CleanConnectSnapshotStore,
    CleanUniverseMembershipStore,
)


def _snapshot_frame(
    symbols: list[str],
    *,
    route: str = "SH_CONNECT",
    snapshot_date: dt.date = dt.date(2021, 1, 1),
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


def _reverse_fixture(
    *,
    route: str = "SH_CONNECT",
) -> tuple[pl.DataFrame, pl.DataFrame, dt.date, dt.date, int]:
    """baseline {1,2} → ADD 3, REMOVE 2, ADD 2 → snapshot {1,2,3}."""
    baseline_date = dt.date(2020, 1, 1)
    snapshot_date = dt.date(2021, 1, 1)
    history = _events_frame(
        [
            (dt.date(2020, 3, 1), "00003.HK", "ADD"),
            (dt.date(2020, 6, 1), "00002.HK", "REMOVE"),
            (dt.date(2020, 9, 1), "00002.HK", "ADD"),
        ],
        route=route,
    )
    snap = _snapshot_frame(
        ["00001.HK", "00002.HK", "00003.HK"],
        route=route,
        snapshot_date=snapshot_date,
    )
    return snap, history, baseline_date, snapshot_date, 2


def _seed_connect(
    data_root: Path,
    snap: pl.DataFrame,
    events: pl.DataFrame,
) -> None:
    CleanConnectSnapshotStore(data_root / "clean" / "connect_snapshot").upsert(snap)
    CleanConnectEventStore(data_root / "clean" / "connect_event").upsert(events)


def _universe_path(data_root: Path, route: str) -> Path:
    return data_root / "clean" / "universe_membership" / f"universe={route}" / "data.parquet"


def _assert_success_json(stdout: str, *, published: bool, mode: str, route: str) -> dict:
    lines = [line for line in stdout.strip().splitlines() if line.strip()]
    assert len(lines) == 1
    payload = json.loads(lines[0])
    expected_keys = {
        "route",
        "mode",
        "baseline_date",
        "snapshot_date",
        "rows",
        "symbols",
        "coverage_start",
        "open_intervals",
        "published",
        "status",
    }
    assert set(payload) == expected_keys
    assert payload["route"] == route
    assert payload["mode"] == mode
    assert payload["published"] is published
    assert payload["status"] == "PASS"
    assert type(payload["rows"]) is int
    assert type(payload["symbols"]) is int
    assert type(payload["open_intervals"]) is int
    blob = lines[0]
    assert ".HK" not in blob
    assert "parquet" not in blob.lower()
    assert "/mnt/" not in blob
    assert "data/clean" not in blob
    assert "\\" not in blob
    return payload


@pytest.mark.parametrize("route", ["SH_CONNECT", "SZ_CONNECT"])
def test_reverse_audit_dry_run_and_publish_match_e4_preview(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], route: str
) -> None:
    snap, events, baseline_date, snapshot_date, expected_count = _reverse_fixture(
        route=route
    )
    _seed_connect(tmp_path, snap, events)
    audit = verify_reverse_eligibility_history(
        snap,
        events,
        route=route,
        baseline_date=baseline_date,
        expected_baseline_count=expected_count,
    )
    preview = build_membership_intervals_from_reverse_audit(
        audit=audit, snapshot=snap, events=events
    )

    argv = [
        "--route",
        route,
        "--mode",
        "reverse-audit",
        "--baseline-date",
        baseline_date.isoformat(),
        "--snapshot-date",
        snapshot_date.isoformat(),
        "--expected-baseline-count",
        str(expected_count),
        "--data-root",
        str(tmp_path),
        "--dry-run",
    ]
    universe = _universe_path(tmp_path, route)
    assert not universe.exists()
    assert main(argv) == 0
    out = capsys.readouterr().out
    payload = _assert_success_json(out, published=False, mode="reverse-audit", route=route)
    assert payload["rows"] == preview.height
    assert payload["symbols"] == preview.get_column("symbol").n_unique()
    assert payload["coverage_start"] == preview.get_column("effective_from").min().isoformat()
    assert payload["open_intervals"] == preview.filter(pl.col("effective_to").is_null()).height
    assert not universe.exists()

    publish_argv = [a for a in argv if a != "--dry-run"]
    assert main(publish_argv) == 0
    out2 = capsys.readouterr().out
    payload2 = _assert_success_json(
        out2, published=True, mode="reverse-audit", route=route
    )
    assert payload2["rows"] == preview.height
    written = pl.read_parquet(universe)
    assert written.height == preview.height
    assert set(written.select("universe", "symbol", "effective_from", "effective_to").iter_rows()) == set(
        preview.select("universe", "symbol", "effective_from", "effective_to").iter_rows()
    )


def test_snapshot_mode_old_command_compatible(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline = dt.date(2026, 1, 1)
    snap = _snapshot_frame(["00001.HK", "00002.HK"], snapshot_date=baseline)
    events = _events_frame(
        [
            (dt.date(2026, 1, 2), "00003.HK", "ADD"),
            (dt.date(2026, 1, 3), "00002.HK", "REMOVE"),
        ]
    )
    _seed_connect(tmp_path, snap, events)
    code = main(
        [
            "--route",
            "SH_CONNECT",
            "--baseline-date",
            baseline.isoformat(),
            "--data-root",
            str(tmp_path),
        ]
    )
    assert code == 0
    payload = _assert_success_json(
        capsys.readouterr().out, published=True, mode="snapshot", route="SH_CONNECT"
    )
    assert payload["baseline_date"] == baseline.isoformat()
    assert payload["snapshot_date"] == baseline.isoformat()
    written = pl.read_parquet(_universe_path(tmp_path, "SH_CONNECT"))
    assert written.height == payload["rows"]
    assert written.get_column("universe").unique().to_list() == ["SH_CONNECT"]


def test_reverse_param_missing_extra_fail_before_write(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    snap, events, baseline_date, snapshot_date, expected_count = _reverse_fixture()
    _seed_connect(tmp_path, snap, events)
    seed = pl.DataFrame(
        {
            "universe": ["SH_CONNECT"],
            "symbol": ["00700.HK"],
            "effective_from": [dt.date(2019, 1, 1)],
            "effective_to": [None],
        },
        schema={
            "universe": pl.String,
            "symbol": pl.String,
            "effective_from": pl.Date,
            "effective_to": pl.Date,
        },
    )
    CleanUniverseMembershipStore(tmp_path / "clean" / "universe_membership").replace(seed)
    target = _universe_path(tmp_path, "SH_CONNECT")
    before = target.read_bytes()

    missing = main(
        [
            "--route",
            "SH_CONNECT",
            "--mode",
            "reverse-audit",
            "--baseline-date",
            baseline_date.isoformat(),
            "--data-root",
            str(tmp_path),
        ]
    )
    assert missing == 1
    err = capsys.readouterr().err
    assert "reverse-audit" in err
    assert target.read_bytes() == before

    extra = main(
        [
            "--route",
            "SH_CONNECT",
            "--mode",
            "snapshot",
            "--baseline-date",
            baseline_date.isoformat(),
            "--snapshot-date",
            snapshot_date.isoformat(),
            "--expected-baseline-count",
            str(expected_count),
            "--data-root",
            str(tmp_path),
        ]
    )
    assert extra == 1
    err2 = capsys.readouterr().err
    assert "snapshot mode" in err2
    assert target.read_bytes() == before


def test_illegal_mode_and_route_rejected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit):
        main(
            [
                "--route",
                "SH_CONNECT",
                "--mode",
                "forged",
                "--baseline-date",
                "2020-01-01",
                "--data-root",
                str(tmp_path),
            ]
        )
    with pytest.raises(SystemExit):
        main(
            [
                "--route",
                "BAD_ROUTE",
                "--baseline-date",
                "2020-01-01",
                "--data-root",
                str(tmp_path),
            ]
        )


def test_dry_run_preserves_universe_bytes_mtime(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    snap, events, baseline_date, snapshot_date, expected_count = _reverse_fixture()
    _seed_connect(tmp_path, snap, events)
    assert (
        main(
            [
                "--route",
                "SH_CONNECT",
                "--mode",
                "reverse-audit",
                "--baseline-date",
                baseline_date.isoformat(),
                "--snapshot-date",
                snapshot_date.isoformat(),
                "--expected-baseline-count",
                str(expected_count),
                "--data-root",
                str(tmp_path),
            ]
        )
        == 0
    )
    capsys.readouterr()
    target = _universe_path(tmp_path, "SH_CONNECT")
    before = target.read_bytes()
    before_mtime_ns = os.lstat(target).st_mtime_ns
    time.sleep(0.02)
    assert (
        main(
            [
                "--route",
                "SH_CONNECT",
                "--mode",
                "reverse-audit",
                "--baseline-date",
                baseline_date.isoformat(),
                "--snapshot-date",
                snapshot_date.isoformat(),
                "--expected-baseline-count",
                str(expected_count),
                "--data-root",
                str(tmp_path),
                "--dry-run",
            ]
        )
        == 0
    )
    payload = _assert_success_json(
        capsys.readouterr().out, published=False, mode="reverse-audit", route="SH_CONNECT"
    )
    assert payload["published"] is False
    assert target.read_bytes() == before
    assert os.lstat(target).st_mtime_ns == before_mtime_ns


def test_publish_only_touches_target_route(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sh_snap, sh_events, baseline_date, snapshot_date, expected_count = _reverse_fixture(
        route="SH_CONNECT"
    )
    sz_snap, sz_events, _, _, _ = _reverse_fixture(route="SZ_CONNECT")
    _seed_connect(tmp_path, sh_snap, sh_events)
    CleanConnectSnapshotStore(tmp_path / "clean" / "connect_snapshot").upsert(sz_snap)
    CleanConnectEventStore(tmp_path / "clean" / "connect_event").upsert(sz_events)
    assert (
        main(
            [
                "--route",
                "SZ_CONNECT",
                "--mode",
                "reverse-audit",
                "--baseline-date",
                baseline_date.isoformat(),
                "--snapshot-date",
                snapshot_date.isoformat(),
                "--expected-baseline-count",
                str(expected_count),
                "--data-root",
                str(tmp_path),
            ]
        )
        == 0
    )
    capsys.readouterr()
    sz_path = _universe_path(tmp_path, "SZ_CONNECT")
    before = sz_path.read_bytes()
    before_mtime_ns = os.lstat(sz_path).st_mtime_ns
    time.sleep(0.02)
    assert (
        main(
            [
                "--route",
                "SH_CONNECT",
                "--mode",
                "reverse-audit",
                "--baseline-date",
                baseline_date.isoformat(),
                "--snapshot-date",
                snapshot_date.isoformat(),
                "--expected-baseline-count",
                str(expected_count),
                "--data-root",
                str(tmp_path),
            ]
        )
        == 0
    )
    _assert_success_json(
        capsys.readouterr().out, published=True, mode="reverse-audit", route="SH_CONNECT"
    )
    assert sz_path.read_bytes() == before
    assert os.lstat(sz_path).st_mtime_ns == before_mtime_ns


def test_forged_mixed_inputs_rejected_without_publish(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    snap, events, baseline_date, snapshot_date, expected_count = _reverse_fixture()
    forged_events = pl.concat(
        [
            events,
            _events_frame([(dt.date(2020, 4, 1), "00099.HK", "ADD")]),
        ]
    )
    _seed_connect(tmp_path, snap, forged_events)
    code = main(
        [
            "--route",
            "SH_CONNECT",
            "--mode",
            "reverse-audit",
            "--baseline-date",
            baseline_date.isoformat(),
            "--snapshot-date",
            snapshot_date.isoformat(),
            "--expected-baseline-count",
            str(expected_count),
            "--data-root",
            str(tmp_path),
        ]
    )
    assert code == 1
    captured = capsys.readouterr()
    assert captured.out.strip() == ""
    assert "REVERSE_AUDIT" in captured.err or "REVERSE_MEMBERSHIP" in captured.err
    assert not _universe_path(tmp_path, "SH_CONNECT").exists()


def test_repeat_publish_idempotent(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    snap, events, baseline_date, snapshot_date, expected_count = _reverse_fixture()
    _seed_connect(tmp_path, snap, events)
    argv = [
        "--route",
        "SH_CONNECT",
        "--mode",
        "reverse-audit",
        "--baseline-date",
        baseline_date.isoformat(),
        "--snapshot-date",
        snapshot_date.isoformat(),
        "--expected-baseline-count",
        str(expected_count),
        "--data-root",
        str(tmp_path),
    ]
    assert main(argv) == 0
    capsys.readouterr()
    first = pl.read_parquet(_universe_path(tmp_path, "SH_CONNECT"))
    assert main(argv) == 0
    capsys.readouterr()
    second = pl.read_parquet(_universe_path(tmp_path, "SH_CONNECT"))
    assert first.equals(second)
    assert first.height == second.height


def test_universe_path_attack_fail_closed_no_published_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    snap, events, baseline_date, snapshot_date, expected_count = _reverse_fixture()
    _seed_connect(tmp_path, snap, events)
    outside = tmp_path / "outside.parquet"
    outside.write_bytes(b"UNIVERSE_ATTACK_MARKER")
    universe_dir = tmp_path / "clean" / "universe_membership" / "universe=SH_CONNECT"
    universe_dir.mkdir(parents=True)
    target = universe_dir / "data.parquet"
    try:
        target.symlink_to(outside)
    except OSError:
        pytest.skip("filesystem does not permit symlink creation")
    code = main(
        [
            "--route",
            "SH_CONNECT",
            "--mode",
            "reverse-audit",
            "--baseline-date",
            baseline_date.isoformat(),
            "--snapshot-date",
            snapshot_date.isoformat(),
            "--expected-baseline-count",
            str(expected_count),
            "--data-root",
            str(tmp_path),
        ]
    )
    assert code == 1
    captured = capsys.readouterr()
    assert captured.out.strip() == ""
    assert "published" not in captured.out
    assert outside.read_bytes() == b"UNIVERSE_ATTACK_MARKER"


def test_sibling_symlink_publish_leaves_external_untouched(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    snap, events, baseline_date, snapshot_date, expected_count = _reverse_fixture()
    _seed_connect(tmp_path, snap, events)
    membership_root = tmp_path / "clean" / "universe_membership"
    membership_root.mkdir(parents=True)
    outside_dir = tmp_path / "external_sz"
    outside_dir.mkdir()
    outside = outside_dir / "data.parquet"
    outside.write_bytes(b"SIBLING_CLI_MARKER")
    sibling = membership_root / "universe=SZ_CONNECT"
    try:
        sibling.symlink_to(outside_dir, target_is_directory=True)
    except OSError:
        pytest.skip("filesystem does not permit symlink creation")
    before = outside.read_bytes()
    before_mtime_ns = os.lstat(outside).st_mtime_ns
    time.sleep(0.02)
    code = main(
        [
            "--route",
            "SH_CONNECT",
            "--mode",
            "reverse-audit",
            "--baseline-date",
            baseline_date.isoformat(),
            "--snapshot-date",
            snapshot_date.isoformat(),
            "--expected-baseline-count",
            str(expected_count),
            "--data-root",
            str(tmp_path),
        ]
    )
    assert code == 0
    _assert_success_json(
        capsys.readouterr().out, published=True, mode="reverse-audit", route="SH_CONNECT"
    )
    assert _universe_path(tmp_path, "SH_CONNECT").is_file()
    assert before == outside.read_bytes()
    assert before_mtime_ns == os.lstat(outside).st_mtime_ns


def test_programmatic_bool_int_datetime_rejected() -> None:
    from quant.data.rebuild_connect_universe import _validate_mode_args
    from argparse import Namespace

    with pytest.raises(ValueError, match="exact date"):
        _validate_mode_args(
            Namespace(
                mode="snapshot",
                baseline_date=dt.datetime(2020, 1, 1),
                snapshot_date=None,
                expected_baseline_count=None,
                dry_run=False,
            )
        )
    with pytest.raises(ValueError, match="dry_run 必须是 bool"):
        _validate_mode_args(
            Namespace(
                mode="snapshot",
                baseline_date=dt.date(2020, 1, 1),
                snapshot_date=None,
                expected_baseline_count=None,
                dry_run=1,
            )
        )
    with pytest.raises((ValueError, Exception), match="REVERSE_AUDIT_INPUT_INVALID|exact date"):
        _validate_mode_args(
            Namespace(
                mode="reverse-audit",
                baseline_date=dt.date(2020, 1, 1),
                snapshot_date=dt.date(2021, 1, 1),
                expected_baseline_count=True,
                dry_run=False,
            )
        )
