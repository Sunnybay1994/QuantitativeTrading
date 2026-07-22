import datetime as dt
import json
import os
import stat
import time
from pathlib import Path

import pandera.errors
import polars as pl
import pytest

from quant.data.storage import (
    CleanConnectEventStore,
    CleanConnectSnapshotStore,
    CleanUniverseMembershipStore,
    RawStore,
)


def _frame(value: int = 1) -> pl.DataFrame:
    return pl.DataFrame({"a": [value], "b": ["x"]})


def test_legacy_raw_write_semantics_remain_idempotent(tmp_path: Path) -> None:
    store = RawStore(tmp_path)
    fetched_at = dt.datetime(2026, 7, 13, tzinfo=dt.timezone.utc)
    first = store.write(
        source="fixture", table="daily", frame=_frame(), parameters={"x": 1}, fetched_at=fetched_at
    )
    second = store.write(
        source="fixture", table="daily", frame=_frame(), parameters={"x": 1}, fetched_at=fetched_at
    )
    assert first == second
    assert first.data_path.exists() and first.metadata_path.exists()


def test_request_raw_identical_pair_reuses_and_conflict_fails(tmp_path: Path) -> None:
    store = RawStore(tmp_path)
    request_id = "a" * 64
    first = store.write_request(
        source="tushare",
        table="daily",
        request_id=request_id,
        frame=_frame(),
        parameters={"fields": "a,b"},
    )
    second = store.write_request(
        source="tushare",
        table="daily",
        request_id=request_id,
        frame=_frame(),
        parameters={"fields": "a,b"},
    )
    assert first == second
    with pytest.raises(ValueError, match="incoming raw 内容冲突"):
        store.write_request(
            source="tushare",
            table="daily",
            request_id=request_id,
            frame=_frame(2),
            parameters={"fields": "a,b"},
        )
    with pytest.raises(ValueError, match="metadata 与请求不一致"):
        store.write_request(
            source="tushare",
            table="daily",
            request_id=request_id,
            frame=_frame(2),
            parameters={"fields": "different"},
        )


def test_request_raw_verified_bundle_binds_snapshot_and_frame(tmp_path: Path) -> None:
    store = RawStore(tmp_path)
    request_id = "f" * 64
    written = store.write_request(
        source="tushare",
        table="daily",
        request_id=request_id,
        frame=_frame(),
        parameters={"fields": "a,b"},
    )
    snapshot, frame = store.verify_request_bundle(
        source="tushare",
        table="daily",
        request_id=request_id,
        parameters={"fields": "a,b"},
    )
    assert snapshot == written
    assert frame.equals(_frame())
    assert store.verify_request(
        source="tushare",
        table="daily",
        request_id=request_id,
        parameters={"fields": "a,b"},
    ) == snapshot


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("checksum_sha256", "0" * 64, "hash/大小"),
        ("size_bytes", 0, "hash/大小"),
        ("rows", 2, "行列"),
        ("columns", ["b", "a"], "行列"),
    ],
)
def test_request_raw_verified_bundle_rejects_internal_mismatch(
    tmp_path: Path, field: str, value: object, error: str
) -> None:
    store = RawStore(tmp_path)
    request_id = "9" * 64
    snapshot = store.write_request(
        source="tushare",
        table="daily",
        request_id=request_id,
        frame=_frame(),
        parameters={"fields": "a,b"},
    )
    metadata = json.loads(snapshot.metadata_path.read_text(encoding="utf-8"))
    metadata[field] = value
    snapshot.metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    with pytest.raises(ValueError, match=error):
        store.verify_request_bundle(
            source="tushare",
            table="daily",
            request_id=request_id,
            parameters={"fields": "a,b"},
        )


@pytest.mark.parametrize("orphan", ["data.parquet", "metadata.json"])
def test_request_raw_one_sided_pair_fails(tmp_path: Path, orphan: str) -> None:
    store = RawStore(tmp_path)
    request_id = "b" * 64
    data_path, metadata_path = store.request_paths(
        source="tushare", table="daily", request_id=request_id
    )
    data_path.parent.mkdir(parents=True)
    if orphan == "data.parquet":
        _frame().write_parquet(data_path)
    else:
        metadata_path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="未知或不完整|孤儿"):
        store.write_request(
            source="tushare",
            table="daily",
            request_id=request_id,
            frame=_frame(),
            parameters={"fields": "a,b"},
        )


def test_request_raw_rejects_extra_file_and_tampered_metadata(tmp_path: Path) -> None:
    store = RawStore(tmp_path)
    request_id = "c" * 64
    snapshot = store.write_request(
        source="tushare",
        table="daily",
        request_id=request_id,
        frame=_frame(),
        parameters={"fields": "a,b"},
    )
    (snapshot.data_path.parent / "extra.bin").write_bytes(b"x")
    with pytest.raises(ValueError, match="文件集合"):
        store.verify_request(
            source="tushare",
            table="daily",
            request_id=request_id,
            parameters={"fields": "a,b"},
        )
    (snapshot.data_path.parent / "extra.bin").unlink()
    value = json.loads(snapshot.metadata_path.read_text(encoding="utf-8"))
    value["rows"] = "1"
    snapshot.metadata_path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError, match="数值类型"):
        store.verify_request(
            source="tushare",
            table="daily",
            request_id=request_id,
            parameters={"fields": "a,b"},
        )


def test_request_raw_rejects_symlink(tmp_path: Path) -> None:
    store = RawStore(tmp_path / "raw")
    request_id = "d" * 64
    data_path, _ = store.request_paths(source="tushare", table="daily", request_id=request_id)
    data_path.parent.parent.mkdir(parents=True)
    target = tmp_path / "outside"
    target.mkdir()
    try:
        data_path.parent.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("filesystem does not permit symlink creation")
    with pytest.raises(ValueError, match="symlink"):
        store.write_request(
            source="tushare",
            table="daily",
            request_id=request_id,
            frame=_frame(),
            parameters={"fields": "a,b"},
        )


@pytest.mark.parametrize("kind", ["root", "parent"])
def test_request_raw_rejects_root_or_parent_symlink_directly(tmp_path: Path, kind: str) -> None:
    real = tmp_path / "real"
    real.mkdir()
    if kind == "root":
        root = tmp_path / "raw"
        root.symlink_to(real, target_is_directory=True)
    else:
        parent = tmp_path / "parent"
        parent.symlink_to(real, target_is_directory=True)
        root = parent / "raw"
    with pytest.raises(ValueError, match="symlink"):
        RawStore(root).write_request(
            source="tushare",
            table="daily",
            request_id="e" * 64,
            frame=_frame(),
            parameters={"fields": "a,b"},
        )
    assert list(real.iterdir()) == []


def _connect_event_frame(
    *,
    route: str = "SH_CONNECT",
    symbols: list[str] | None = None,
    actions: list[str] | None = None,
    dates: list[dt.date] | None = None,
) -> pl.DataFrame:
    symbols = symbols or ["00700.HK"]
    actions = actions or ["ADD"]
    dates = dates or [dt.date(2026, 7, 10)]
    n = len(symbols)
    source = "sse" if route == "SH_CONNECT" else "szse"
    return pl.DataFrame(
        {
            "route": [route] * n,
            "effective_date": dates,
            "symbol": symbols,
            "action": actions,
            "name_cn": ["腾讯控股"] * n,
            "name_en": ["TENCENT"] * n,
            "security_type": ["STOCK"] * n,
            "published_date": [dt.date(2026, 7, 9)] * n,
            "source": [source] * n,
        }
    )


def test_connect_event_replace_route_drops_old_wrong_action(tmp_path: Path) -> None:
    store = CleanConnectEventStore(tmp_path)
    stale = _connect_event_frame(
        symbols=["00700.HK", "00941.HK"],
        actions=["REMOVE", "REMOVE"],
        dates=[dt.date(2026, 7, 10), dt.date(2026, 7, 11)],
    )
    store.upsert(stale)
    corrected = _connect_event_frame(
        symbols=["00700.HK", "00941.HK"],
        actions=["ADD", "REMOVE"],
        dates=[dt.date(2026, 7, 10), dt.date(2026, 7, 11)],
    )
    rows = store.replace_route(corrected)
    assert rows == 2
    written = pl.read_parquet(tmp_path / "route=SH_CONNECT" / "data.parquet")
    assert written.get_column("action").to_list() == ["ADD", "REMOVE"]
    assert written.height == 2
    assert "REMOVE" not in written.filter(
        (pl.col("symbol") == "00700.HK") & (pl.col("effective_date") == dt.date(2026, 7, 10))
    ).get_column("action").to_list()


def test_connect_event_replace_leaves_other_route_bytes_and_mtime(tmp_path: Path) -> None:
    store = CleanConnectEventStore(tmp_path)
    sh = _connect_event_frame(route="SH_CONNECT", actions=["REMOVE"])
    sz = _connect_event_frame(route="SZ_CONNECT", symbols=["00388.HK"], actions=["ADD"])
    store.upsert(sh)
    store.upsert(sz)
    sz_path = tmp_path / "route=SZ_CONNECT" / "data.parquet"
    before = sz_path.read_bytes()
    before_mtime_ns = os.lstat(sz_path).st_mtime_ns
    time.sleep(0.02)
    store.replace_route(
        _connect_event_frame(route="SH_CONNECT", symbols=["00700.HK"], actions=["ADD"])
    )
    assert sz_path.read_bytes() == before
    assert os.lstat(sz_path).st_mtime_ns == before_mtime_ns


def test_connect_event_replace_rejects_empty_multi_route_and_schema_before_mutation(
    tmp_path: Path,
) -> None:
    store = CleanConnectEventStore(tmp_path)
    seed = _connect_event_frame(actions=["REMOVE"])
    store.upsert(seed)
    target = tmp_path / "route=SH_CONNECT" / "data.parquet"
    before = target.read_bytes()

    empty = seed.clear()
    with pytest.raises(ValueError, match="非空"):
        store.replace_route(empty)
    assert target.read_bytes() == before

    multi = pl.concat(
        [
            _connect_event_frame(route="SH_CONNECT"),
            _connect_event_frame(route="SZ_CONNECT", symbols=["00388.HK"]),
        ]
    )
    with pytest.raises(ValueError, match="恰好一个 route"):
        store.replace_route(multi)
    assert target.read_bytes() == before

    invalid = _connect_event_frame().with_columns(pl.lit("BAD").alias("action"))
    with pytest.raises(pandera.errors.SchemaError):
        store.replace_route(invalid)
    assert target.read_bytes() == before


def test_connect_event_replace_is_deterministic_without_duplicates(tmp_path: Path) -> None:
    store = CleanConnectEventStore(tmp_path)
    frame = _connect_event_frame(
        symbols=["00941.HK", "00700.HK"],
        actions=["REMOVE", "ADD"],
        dates=[dt.date(2026, 7, 11), dt.date(2026, 7, 10)],
    )
    store.replace_route(frame)
    first = pl.read_parquet(tmp_path / "route=SH_CONNECT" / "data.parquet")
    store.replace_route(frame)
    second = pl.read_parquet(tmp_path / "route=SH_CONNECT" / "data.parquet")
    assert first.equals(second)
    assert first.height == 2
    assert first.get_column("symbol").to_list() == ["00700.HK", "00941.HK"]


def test_connect_event_replace_target_symlink_fail_closed(tmp_path: Path) -> None:
    store = CleanConnectEventStore(tmp_path / "clean")
    outside = tmp_path / "outside.parquet"
    outside.write_bytes(b"EXTERNAL_MARKER")
    route_dir = tmp_path / "clean" / "route=SH_CONNECT"
    route_dir.mkdir(parents=True)
    target = route_dir / "data.parquet"
    try:
        target.symlink_to(outside)
    except OSError:
        pytest.skip("filesystem does not permit symlink creation")
    with pytest.raises(ValueError, match="symlink"):
        store.replace_route(_connect_event_frame())
    assert outside.read_bytes() == b"EXTERNAL_MARKER"
    assert stat.S_ISLNK(os.lstat(target).st_mode)


def test_connect_event_replace_ancestor_symlink_fail_closed(tmp_path: Path) -> None:
    real = tmp_path / "real_route"
    real.mkdir()
    outside = real / "data.parquet"
    outside.write_bytes(b"EXTERNAL_DIR_TARGET")
    clean_root = tmp_path / "clean"
    clean_root.mkdir()
    link = clean_root / "route=SH_CONNECT"
    try:
        link.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("filesystem does not permit symlink creation")
    store = CleanConnectEventStore(clean_root)
    with pytest.raises(ValueError, match="symlink"):
        store.replace_route(_connect_event_frame())
    assert outside.read_bytes() == b"EXTERNAL_DIR_TARGET"


def test_connect_event_replace_non_regular_target_fail_closed(tmp_path: Path) -> None:
    store = CleanConnectEventStore(tmp_path)
    route_dir = tmp_path / "route=SH_CONNECT"
    route_dir.mkdir(parents=True)
    target = route_dir / "data.parquet"
    try:
        os.mkfifo(target)
    except (OSError, AttributeError):
        pytest.skip("filesystem does not permit fifo creation")
    assert not stat.S_ISREG(os.lstat(target).st_mode)
    with pytest.raises(ValueError, match="普通文件"):
        store.replace_route(_connect_event_frame())
    assert stat.S_ISFIFO(os.lstat(target).st_mode)


def test_connect_snapshot_read_route_date_roundtrip(tmp_path: Path) -> None:
    store = CleanConnectSnapshotStore(tmp_path)
    frame = pl.DataFrame(
        {
            "route": ["SH_CONNECT"],
            "snapshot_date": [dt.date(2026, 7, 10)],
            "symbol": ["00700.HK"],
            "name_cn": ["腾讯控股"],
            "name_en": ["TENCENT"],
            "security_type": ["STOCK"],
            "buy_eligible": [True],
            "source": ["sse"],
        }
    )
    store.upsert(frame)
    read = store.read_route_date(route="SH_CONNECT", snapshot_date=dt.date(2026, 7, 10))
    assert read.height == 1
    assert read.get_column("symbol").to_list() == ["00700.HK"]


def test_connect_event_read_route_roundtrip(tmp_path: Path) -> None:
    store = CleanConnectEventStore(tmp_path)
    store.upsert(_connect_event_frame())
    read = store.read_route(route="SH_CONNECT")
    assert read.height == 1
    assert read.get_column("action").to_list() == ["ADD"]


def test_connect_read_missing_fail_closed(tmp_path: Path) -> None:
    snap = CleanConnectSnapshotStore(tmp_path / "snap")
    ev = CleanConnectEventStore(tmp_path / "ev")
    with pytest.raises(ValueError, match="不存在|symlink|普通文件"):
        snap.read_route_date(route="SH_CONNECT", snapshot_date=dt.date(2026, 7, 10))
    with pytest.raises(ValueError, match="不存在|symlink|普通文件"):
        ev.read_route(route="SH_CONNECT")


def test_connect_read_target_symlink_fail_closed(tmp_path: Path) -> None:
    outside = tmp_path / "outside.parquet"
    outside.write_bytes(b"EXTERNAL_MARKER")
    root = tmp_path / "clean"
    route_dir = root / "route=SH_CONNECT"
    route_dir.mkdir(parents=True)
    target = route_dir / "data.parquet"
    try:
        target.symlink_to(outside)
    except OSError:
        pytest.skip("filesystem does not permit symlink creation")
    store = CleanConnectEventStore(root)
    with pytest.raises(ValueError, match="symlink"):
        store.read_route(route="SH_CONNECT")
    assert outside.read_bytes() == b"EXTERNAL_MARKER"


def test_connect_read_ancestor_symlink_fail_closed(tmp_path: Path) -> None:
    real = tmp_path / "real_route"
    real.mkdir()
    outside = real / "data.parquet"
    outside.write_bytes(b"EXTERNAL_DIR_TARGET")
    clean_root = tmp_path / "clean"
    clean_root.mkdir()
    link = clean_root / "route=SH_CONNECT"
    try:
        link.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("filesystem does not permit symlink creation")
    store = CleanConnectEventStore(clean_root)
    with pytest.raises(ValueError, match="symlink"):
        store.read_route(route="SH_CONNECT")
    assert outside.read_bytes() == b"EXTERNAL_DIR_TARGET"


def test_connect_read_root_symlink_fail_closed(tmp_path: Path) -> None:
    real = tmp_path / "real_root"
    real.mkdir()
    link = tmp_path / "link_root"
    try:
        link.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("filesystem does not permit symlink creation")
    store = CleanConnectEventStore(link)
    with pytest.raises(ValueError, match="symlink"):
        store.read_route(route="SH_CONNECT")


def test_connect_snapshot_read_date_dir_symlink_fail_closed(tmp_path: Path) -> None:
    real = tmp_path / "real_date"
    real.mkdir()
    outside = real / "data.parquet"
    outside.write_bytes(b"DATE_LINK_TARGET")
    root = tmp_path / "clean"
    route_dir = root / "route=SH_CONNECT"
    route_dir.mkdir(parents=True)
    link = route_dir / "date=2026-07-10"
    try:
        link.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("filesystem does not permit symlink creation")
    store = CleanConnectSnapshotStore(root)
    with pytest.raises(ValueError, match="symlink"):
        store.read_route_date(route="SH_CONNECT", snapshot_date=dt.date(2026, 7, 10))
    assert outside.read_bytes() == b"DATE_LINK_TARGET"


def test_connect_read_fifo_fail_closed(tmp_path: Path) -> None:
    store = CleanConnectEventStore(tmp_path)
    route_dir = tmp_path / "route=SH_CONNECT"
    route_dir.mkdir(parents=True)
    target = route_dir / "data.parquet"
    try:
        os.mkfifo(target)
    except (OSError, AttributeError):
        pytest.skip("filesystem does not permit fifo creation")
    with pytest.raises(ValueError, match="普通文件"):
        store.read_route(route="SH_CONNECT")
    assert stat.S_ISFIFO(os.lstat(target).st_mode)


def test_connect_read_directory_target_fail_closed(tmp_path: Path) -> None:
    store = CleanConnectEventStore(tmp_path)
    target = tmp_path / "route=SH_CONNECT" / "data.parquet"
    target.mkdir(parents=True)
    with pytest.raises(ValueError, match="普通文件"):
        store.read_route(route="SH_CONNECT")


def _universe_membership_frame(
    *,
    universe: str = "SH_CONNECT",
    symbols: list[str] | None = None,
    effective_from: list[dt.date] | None = None,
    effective_to: list[dt.date | None] | None = None,
) -> pl.DataFrame:
    symbols = symbols or ["00700.HK"]
    effective_from = effective_from or [dt.date(2020, 1, 1)]
    effective_to = effective_to or [None]
    n = len(symbols)
    return pl.DataFrame(
        {
            "universe": [universe] * n,
            "symbol": symbols,
            "effective_from": effective_from,
            "effective_to": effective_to,
        },
        schema={
            "universe": pl.String,
            "symbol": pl.String,
            "effective_from": pl.Date,
            "effective_to": pl.Date,
        },
    )


def test_universe_replace_drops_old_and_is_deterministic(tmp_path: Path) -> None:
    store = CleanUniverseMembershipStore(tmp_path)
    stale = _universe_membership_frame(
        symbols=["00700.HK", "00941.HK"],
        effective_from=[dt.date(2019, 1, 1), dt.date(2019, 6, 1)],
        effective_to=[dt.date(2019, 12, 31), None],
    )
    store.replace(stale)
    corrected = _universe_membership_frame(
        symbols=["00700.HK", "00388.HK"],
        effective_from=[dt.date(2020, 1, 1), dt.date(2020, 2, 1)],
        effective_to=[None, None],
    )
    rows = store.replace_universe(corrected)
    assert rows == 2
    written = pl.read_parquet(tmp_path / "universe=SH_CONNECT" / "data.parquet")
    assert written.height == 2
    assert set(written.get_column("symbol").to_list()) == {"00700.HK", "00388.HK"}
    store.replace_universe(corrected)
    again = pl.read_parquet(tmp_path / "universe=SH_CONNECT" / "data.parquet")
    assert written.equals(again)


def test_universe_replace_leaves_other_universe_bytes_and_mtime(tmp_path: Path) -> None:
    store = CleanUniverseMembershipStore(tmp_path)
    sh = _universe_membership_frame(universe="SH_CONNECT")
    sz = _universe_membership_frame(universe="SZ_CONNECT", symbols=["00388.HK"])
    store.replace(sh)
    store.replace(sz)
    sz_path = tmp_path / "universe=SZ_CONNECT" / "data.parquet"
    before = sz_path.read_bytes()
    before_mtime_ns = os.lstat(sz_path).st_mtime_ns
    time.sleep(0.02)
    store.replace_universe(
        _universe_membership_frame(
            universe="SH_CONNECT",
            symbols=["00700.HK", "00941.HK"],
            effective_from=[dt.date(2020, 1, 1), dt.date(2020, 3, 1)],
            effective_to=[None, None],
        )
    )
    assert sz_path.read_bytes() == before
    assert os.lstat(sz_path).st_mtime_ns == before_mtime_ns


def test_universe_replace_rejects_empty_multi_illegal_before_mutation(
    tmp_path: Path,
) -> None:
    store = CleanUniverseMembershipStore(tmp_path)
    seed = _universe_membership_frame()
    store.replace(seed)
    target = tmp_path / "universe=SH_CONNECT" / "data.parquet"
    before = target.read_bytes()

    with pytest.raises(ValueError, match="非空"):
        store.replace_universe(seed.clear())
    assert target.read_bytes() == before

    multi = pl.concat(
        [
            _universe_membership_frame(universe="SH_CONNECT"),
            _universe_membership_frame(universe="SZ_CONNECT", symbols=["00388.HK"]),
        ]
    )
    with pytest.raises(ValueError, match="恰好一个 universe"):
        store.replace_universe(multi)
    assert target.read_bytes() == before

    other = _universe_membership_frame(universe="CSI300")
    with pytest.raises(ValueError, match="只允许 SH_CONNECT/SZ_CONNECT"):
        store.replace_universe(other)
    assert target.read_bytes() == before

    invalid = _universe_membership_frame().with_columns(pl.lit("BAD").alias("symbol"))
    with pytest.raises(pandera.errors.SchemaError):
        store.replace_universe(invalid)
    assert target.read_bytes() == before


def test_universe_replace_target_symlink_fail_closed(tmp_path: Path) -> None:
    store = CleanUniverseMembershipStore(tmp_path / "clean")
    outside = tmp_path / "outside.parquet"
    outside.write_bytes(b"EXTERNAL_UNIVERSE_MARKER")
    universe_dir = tmp_path / "clean" / "universe=SH_CONNECT"
    universe_dir.mkdir(parents=True)
    target = universe_dir / "data.parquet"
    try:
        target.symlink_to(outside)
    except OSError:
        pytest.skip("filesystem does not permit symlink creation")
    with pytest.raises(ValueError, match="symlink"):
        store.replace_universe(_universe_membership_frame())
    assert outside.read_bytes() == b"EXTERNAL_UNIVERSE_MARKER"
    assert stat.S_ISLNK(os.lstat(target).st_mode)


def test_universe_replace_ancestor_symlink_fail_closed(tmp_path: Path) -> None:
    real = tmp_path / "real_universe"
    real.mkdir()
    outside = real / "data.parquet"
    outside.write_bytes(b"EXTERNAL_UNIVERSE_DIR")
    clean_root = tmp_path / "clean"
    clean_root.mkdir()
    link = clean_root / "universe=SH_CONNECT"
    try:
        link.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("filesystem does not permit symlink creation")
    store = CleanUniverseMembershipStore(clean_root)
    with pytest.raises(ValueError, match="symlink"):
        store.replace_universe(_universe_membership_frame())
    assert outside.read_bytes() == b"EXTERNAL_UNIVERSE_DIR"


def test_universe_replace_root_symlink_fail_closed(tmp_path: Path) -> None:
    real = tmp_path / "real_root"
    real.mkdir()
    link = tmp_path / "link_root"
    try:
        link.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("filesystem does not permit symlink creation")
    store = CleanUniverseMembershipStore(link)
    with pytest.raises(ValueError, match="symlink"):
        store.replace_universe(_universe_membership_frame())


def test_universe_replace_temp_symlink_fail_closed(tmp_path: Path) -> None:
    store = CleanUniverseMembershipStore(tmp_path / "clean")
    outside = tmp_path / "outside_tmp.parquet"
    outside.write_bytes(b"TEMP_LINK_MARKER")
    universe_dir = tmp_path / "clean" / "universe=SH_CONNECT"
    universe_dir.mkdir(parents=True)
    temporary = universe_dir / "data.tmp.parquet"
    try:
        temporary.symlink_to(outside)
    except OSError:
        pytest.skip("filesystem does not permit symlink creation")
    with pytest.raises(ValueError, match="临时文件|symlink"):
        store.replace_universe(_universe_membership_frame())
    assert outside.read_bytes() == b"TEMP_LINK_MARKER"


def test_universe_replace_non_regular_target_fail_closed(tmp_path: Path) -> None:
    store = CleanUniverseMembershipStore(tmp_path)
    universe_dir = tmp_path / "universe=SH_CONNECT"
    universe_dir.mkdir(parents=True)
    target = universe_dir / "data.parquet"
    try:
        os.mkfifo(target)
    except (OSError, AttributeError):
        pytest.skip("filesystem does not permit fifo creation")
    assert not stat.S_ISREG(os.lstat(target).st_mode)
    with pytest.raises(ValueError, match="普通文件"):
        store.replace_universe(_universe_membership_frame())
    assert stat.S_ISFIFO(os.lstat(target).st_mode)


def test_universe_replace_directory_target_fail_closed(tmp_path: Path) -> None:
    store = CleanUniverseMembershipStore(tmp_path)
    target = tmp_path / "universe=SH_CONNECT" / "data.parquet"
    target.mkdir(parents=True)
    with pytest.raises(ValueError, match="普通文件"):
        store.replace_universe(_universe_membership_frame())


def test_universe_replace_sibling_symlink_untouched(tmp_path: Path) -> None:
    """目标 universe 合法时，sibling symlink 不得被触碰，外部 bytes/mtime 不变。"""
    clean_root = tmp_path / "clean"
    clean_root.mkdir()
    outside_dir = tmp_path / "external_sz"
    outside_dir.mkdir()
    outside = outside_dir / "data.parquet"
    outside.write_bytes(b"SIBLING_EXTERNAL_MARKER")
    sibling = clean_root / "universe=SZ_CONNECT"
    try:
        sibling.symlink_to(outside_dir, target_is_directory=True)
    except OSError:
        pytest.skip("filesystem does not permit symlink creation")
    before = outside.read_bytes()
    before_mtime_ns = os.lstat(outside).st_mtime_ns
    time.sleep(0.02)
    store = CleanUniverseMembershipStore(clean_root)
    rows = store.replace_universe(_universe_membership_frame(universe="SH_CONNECT"))
    assert rows == 1
    assert (clean_root / "universe=SH_CONNECT" / "data.parquet").is_file()
    assert before == outside.read_bytes()
    assert before_mtime_ns == os.lstat(outside).st_mtime_ns
    assert stat.S_ISLNK(os.lstat(sibling).st_mode)
