"""D4/F2–F4/E0: 确定性 staging 与 manifest。"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import polars as pl
import pytest

import quant.research.m3.snapshot as snapshot_mod
from quant.research.m3.contracts import DatasetSnapshot
from quant.research.m3.config import load_m3_config
from quant.research.m3.contracts import SnapshotBuildSpec
from quant.research.m3.run_state import (
    compute_snapshot_request_key,
    publish_stage_receipt,
)
from quant.research.m3.snapshot import (
    M3SnapshotError,
    STAGING_COLUMNS,
    build_snapshot_artifact,
    build_snapshot_manifest,
    build_snapshot_request_record,
    from_qlib_symbol,
    prepare_qlib_staging,
    snapshot_id_from_manifest,
    to_qlib_symbol,
    validate_provider,
    verify_snapshot_artifact,
    write_staging_by_symbol,
)

FIXTURE_ROOT = Path("tests/fixtures/m3")
G1_RELEASE_ID = "g1-test"
G1_RELEASE_SHA = "a" * 64
UNIVERSE = "CSI300_PIT"


def _read(name: str) -> pl.DataFrame:
    return pl.read_csv(FIXTURE_ROOT / name, try_parse_dates=True)


def _manifest_kwargs(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "source": "fixture",
        "universe": UNIVERSE,
        "g1_release_id": G1_RELEASE_ID,
        "g1_release_manifest_sha256": G1_RELEASE_SHA,
        "schema_version": "1.0.0",
        "snapshot_config_sha256": "c" * 64,
        "config_version": "1.0.0",
    }
    base.update(overrides)
    return base


def test_to_qlib_symbol_maps_sh_sz() -> None:
    assert to_qlib_symbol("000001.SZ") == "sz000001"
    assert to_qlib_symbol("600000.SH") == "sh600000"
    with pytest.raises(ValueError):
        to_qlib_symbol("00700.HK")


def test_from_qlib_symbol_round_trip() -> None:
    assert from_qlib_symbol("sz000001") == "000001.SZ"
    assert from_qlib_symbol("SH600000") == "600000.SH"
    assert from_qlib_symbol("SZ000001") == "000001.SZ"
    assert from_qlib_symbol("sh600000") == "600000.SH"
    assert from_qlib_symbol(to_qlib_symbol("000001.SZ")) == "000001.SZ"
    with pytest.raises(ValueError):
        from_qlib_symbol("hk00700")
    with pytest.raises(ValueError):
        from_qlib_symbol("xx600000")
    with pytest.raises(ValueError):
        from_qlib_symbol("sh60000")
    with pytest.raises(ValueError):
        from_qlib_symbol("sh60000a")


def test_prepare_staging_keeps_pre_effective_history_and_sh_calendar() -> None:
    staging = prepare_qlib_staging(
        bars=_read("bars.csv"),
        membership=_read("membership.csv"),
        calendars=_read("calendar.csv"),
        source="fixture",
        universe=UNIVERSE,
    )
    # 000003 首次生效 2026-01-12，但 bars 从 01-05 起存在；staging 必须保留
    early = staging.filter(
        (pl.col("symbol") == "000003.SZ")
        & (pl.col("date") == pl.date(2026, 1, 5))
    )
    assert early.height == 1
    assert list(staging.columns) == list(STAGING_COLUMNS)


def test_f2_excludes_other_universe_symbols() -> None:
    membership = pl.concat(
        [
            _read("membership.csv"),
            pl.DataFrame(
                {
                    "universe": ["OTHER"],
                    "symbol": ["600999.SH"],
                    "effective_from": [dt.date(2026, 1, 5)],
                    "effective_to": [None],
                }
            ),
        ]
    )
    extra = _read("bars.csv").head(1).with_columns(
        pl.lit("600999.SH").alias("symbol"),
        pl.lit("fixture").alias("source"),
    )
    bars = pl.concat([_read("bars.csv"), extra])
    staging = prepare_qlib_staging(
        bars=bars,
        membership=membership,
        calendars=_read("calendar.csv"),
        source="fixture",
        universe=UNIVERSE,
    )
    assert "600999.SH" not in staging.get_column("symbol").to_list()


def test_r2_explicit_source_selection_allows_cross_source_same_key() -> None:
    base = _read("bars.csv").filter(pl.col("symbol") == "000001.SZ").head(1)
    source_a = base.with_columns(pl.lit("source_a").alias("source"))
    source_b = base.with_columns(
        (pl.col("close") + 1.0).alias("close"),
        pl.lit("source_b").alias("source"),
    )
    bars = pl.concat([source_a, source_b, _read("bars.csv")])
    staging = prepare_qlib_staging(
        bars=bars,
        membership=_read("membership.csv"),
        calendars=_read("calendar.csv"),
        source="source_a",
        universe=UNIVERSE,
    )
    assert not staging.is_empty()

    dup_a = pl.concat([source_a, source_a])
    with pytest.raises(ValueError, match="重复"):
        prepare_qlib_staging(
            bars=dup_a,
            membership=_read("membership.csv"),
            calendars=_read("calendar.csv"),
            source="source_a",
            universe=UNIVERSE,
        )


def test_r2_adjustment_formula_hand_calculation() -> None:
    calendars = pl.DataFrame(
        {
            "market": ["SH", "SH"],
            "date": [dt.date(2026, 1, 5), dt.date(2026, 1, 6)],
            "is_open": [True, True],
            "is_connect_open": [False, False],
            "is_half_day": [False, False],
        }
    )
    membership = pl.DataFrame(
        {
            "universe": ["U", "U"],
            "symbol": ["000001.SZ", "000002.SZ"],
            "effective_from": [dt.date(2026, 1, 5), dt.date(2026, 1, 5)],
            "effective_to": [None, None],
        }
    )
    bars = pl.DataFrame(
        {
            "symbol": [
                "000001.SZ",
                "000001.SZ",
                "000002.SZ",
                "000002.SZ",
            ],
            "trade_date": [
                dt.date(2026, 1, 5),
                dt.date(2026, 1, 6),
                dt.date(2026, 1, 5),
                dt.date(2026, 1, 6),
            ],
            "open": [10.0, 11.0, 20.0, 22.0],
            "high": [10.5, 11.5, 20.5, 22.5],
            "low": [9.5, 10.5, 19.5, 21.5],
            "close": [10.0, 12.0, 20.0, 24.0],
            "volume": [1000.0, 2000.0, 3000.0, 4000.0],
            "amount": [10000.0, 24000.0, 60000.0, 96000.0],
            "adj_factor": [2.0, 2.0, 1.0, 1.5],
            "source": ["fixture"] * 4,
        }
    )
    staging = prepare_qlib_staging(
        bars=bars,
        membership=membership,
        calendars=calendars,
        source="fixture",
        universe="U",
    )

    # 000001: base = 10*2=20; day1 factor=2/20=0.1; close=10*0.1=1
    # day2 factor=2/20=0.1; close=12*0.1=1.2; volume=2000/0.1=20000
    # raw_vwap day1 = 10000/1000=10; qlib_vwap=1.0
    s1 = staging.filter(pl.col("symbol") == "000001.SZ").sort("date")
    assert s1.item(0, "close") == pytest.approx(1.0, abs=1e-12)
    assert s1.item(0, "factor") == pytest.approx(0.1, abs=1e-12)
    assert s1.item(0, "vwap") == pytest.approx(1.0, abs=1e-12)
    assert s1.item(1, "close") == pytest.approx(1.2, abs=1e-12)
    assert s1.item(1, "volume") == pytest.approx(20000.0, abs=1e-9)
    assert s1.item(1, "vwap") == pytest.approx(1.2, abs=1e-12)

    # 000002: base=20*1=20; day1 factor=0.05; close=1
    # day2 factor=1.5/20=0.075; close=24*0.075=1.8; volume=4000/0.075
    s2 = staging.filter(pl.col("symbol") == "000002.SZ").sort("date")
    assert s2.item(0, "close") == pytest.approx(1.0, abs=1e-12)
    assert s2.item(1, "close") == pytest.approx(1.8, abs=1e-12)
    assert s2.item(1, "volume") == pytest.approx(4000 / 0.075, abs=1e-9)

    raw = bars.sort(["symbol", "trade_date"])
    for i in range(staging.height):
        row = staging.sort(["symbol", "date"]).row(i, named=True)
        raw_row = raw.row(i, named=True)
        assert row["close"] / row["factor"] == pytest.approx(raw_row["close"], abs=1e-9)
        assert row["volume"] * row["factor"] == pytest.approx(raw_row["volume"], abs=1e-6)
        assert row["vwap"] / row["factor"] == pytest.approx(
            raw_row["amount"] / raw_row["volume"], abs=1e-9
        )


def test_f3_rejects_non_finite_bars() -> None:
    bars = _read("bars.csv").with_columns(
        pl.when(pl.col("symbol") == "000001.SZ")
        .then(pl.lit(float("nan")))
        .otherwise(pl.col("close"))
        .alias("close")
    )
    with pytest.raises(ValueError, match="finite|非法"):
        prepare_qlib_staging(
            bars=bars,
            membership=_read("membership.csv"),
            calendars=_read("calendar.csv"),
            source="fixture",
            universe=UNIVERSE,
        )


@pytest.mark.parametrize(
    "col,value",
    [
        ("amount", float("nan")),
        ("amount", float("inf")),
        ("amount", 0.0),
        ("volume", 0.0),
        ("volume", float("-inf")),
    ],
)
def test_e0_rejects_bad_amount_volume(col: str, value: float) -> None:
    bars = _read("bars.csv").with_columns(pl.lit(value).alias(col))
    with pytest.raises(ValueError):
        prepare_qlib_staging(
            bars=bars,
            membership=_read("membership.csv"),
            calendars=_read("calendar.csv"),
            source="fixture",
            universe=UNIVERSE,
        )


def test_manifest_hash_invariant_to_input_order(tmp_path: Path) -> None:
    staging = prepare_qlib_staging(
        bars=_read("bars.csv"),
        membership=_read("membership.csv"),
        calendars=_read("calendar.csv"),
        source="fixture",
        universe=UNIVERSE,
    )
    out_a = tmp_path / "a"
    out_b = tmp_path / "b"
    paths_a = write_staging_by_symbol(staging, out_a)
    shuffled = staging.sample(fraction=1.0, shuffle=True, seed=7)
    paths_b = write_staging_by_symbol(shuffled, out_b)
    man_a = build_snapshot_manifest(files=paths_a, **_manifest_kwargs())
    man_b = build_snapshot_manifest(
        files=list(reversed(paths_b)), **_manifest_kwargs()
    )
    assert man_a["snapshot_id"] == man_b["snapshot_id"]
    assert snapshot_id_from_manifest(man_a) == man_a["snapshot_id"]
    for key in (
        "source",
        "universe",
        "g1_release_id",
        "g1_release_manifest_sha256",
        "row_count",
        "symbol_count",
        "min_date",
        "max_date",
        "schema_version",
        "config_version",
        "snapshot_config_sha256",
        "adjustment",
        "files",
        "snapshot_id",
    ):
        assert key in man_a
    assert man_a["universe"] == UNIVERSE
    assert man_a["g1_release_id"] == G1_RELEASE_ID
    assert "qlib_vwap" in man_a["adjustment"]  # type: ignore[operator]
    assert man_a["row_count"] == staging.height
    assert man_a["symbol_count"] == staging.get_column("symbol").n_unique()
    for entry in man_a["files"]:  # type: ignore[union-attr]
        for field in (
            "relative_path",
            "size_bytes",
            "sha256",
            "symbol",
            "row_count",
            "min_date",
            "max_date",
        ):
            assert field in entry  # type: ignore[operator]
        assert "/" not in entry["relative_path"]  # type: ignore[index]


def test_manifest_hash_changes_when_price_changes(tmp_path: Path) -> None:
    staging = prepare_qlib_staging(
        bars=_read("bars.csv"),
        membership=_read("membership.csv"),
        calendars=_read("calendar.csv"),
        source="fixture",
        universe=UNIVERSE,
    )
    out = tmp_path / "staging"
    paths = write_staging_by_symbol(staging, out)
    base = build_snapshot_manifest(files=paths, **_manifest_kwargs())
    changed = staging.with_columns(
        pl.when(pl.col("symbol") == "000001.SZ")
        .then(pl.col("close") + 1.0)
        .otherwise(pl.col("close"))
        .alias("close")
    )
    out2 = tmp_path / "staging2"
    paths2 = write_staging_by_symbol(changed, out2)
    altered = build_snapshot_manifest(
        files=paths2, **_manifest_kwargs()
    )
    assert base["snapshot_id"] != altered["snapshot_id"]


def test_manifest_binds_narrow_snapshot_config_without_physical_toml(
    tmp_path: Path,
) -> None:
    staging = prepare_qlib_staging(
        bars=_read("bars.csv"),
        membership=_read("membership.csv"),
        calendars=_read("calendar.csv"),
        source="fixture",
        universe=UNIVERSE,
    )
    paths = write_staging_by_symbol(staging, tmp_path / "staging")
    base = build_snapshot_manifest(files=paths, **_manifest_kwargs())
    other_config = build_snapshot_manifest(
        files=paths,
        **_manifest_kwargs(snapshot_config_sha256="d" * 64),
    )
    other_version = build_snapshot_manifest(
        files=paths,
        **_manifest_kwargs(config_version="1.0.1"),
    )
    assert base["snapshot_id"] != other_config["snapshot_id"]
    assert base["snapshot_id"] != other_version["snapshot_id"]
    assert "config" not in base
    assert "provider_format" not in base


def test_e0_manifest_hash_changes_with_g1_or_vwap(tmp_path: Path) -> None:
    staging = prepare_qlib_staging(
        bars=_read("bars.csv"),
        membership=_read("membership.csv"),
        calendars=_read("calendar.csv"),
        source="fixture",
        universe=UNIVERSE,
    )
    out = tmp_path / "staging"
    paths = write_staging_by_symbol(staging, out)
    base = build_snapshot_manifest(files=paths, **_manifest_kwargs())
    other_g1 = build_snapshot_manifest(
        files=paths,
        **_manifest_kwargs(g1_release_id="g1-other"),
    )
    other_sha = build_snapshot_manifest(
        files=paths,
        **_manifest_kwargs(g1_release_manifest_sha256="b" * 64),
    )
    assert base["snapshot_id"] != other_g1["snapshot_id"]
    assert base["snapshot_id"] != other_sha["snapshot_id"]

    vwap_changed = staging.with_columns(pl.col("vwap") + 0.01)
    out2 = tmp_path / "staging2"
    paths2 = write_staging_by_symbol(vwap_changed, out2)
    vwap_man = build_snapshot_manifest(
        files=paths2, **_manifest_kwargs()
    )
    assert base["snapshot_id"] != vwap_man["snapshot_id"]


def test_f4_rejects_empty_and_inconsistent_manifest(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="空"):
        build_snapshot_manifest(files=[], **_manifest_kwargs())

    staging = prepare_qlib_staging(
        bars=_read("bars.csv"),
        membership=_read("membership.csv"),
        calendars=_read("calendar.csv"),
        source="fixture",
        universe=UNIVERSE,
    )
    paths = write_staging_by_symbol(staging, tmp_path / "ok")
    empty = tmp_path / "sz000001.parquet"
    pl.read_parquet(paths[0]).clear().write_parquet(empty)
    with pytest.raises(ValueError, match="空"):
        build_snapshot_manifest(
            files=[empty], **_manifest_kwargs()
        )

    bad_name = tmp_path / "wrong.parquet"
    pl.read_parquet(paths[0]).write_parquet(bad_name)
    with pytest.raises(ValueError, match="文件名"):
        build_snapshot_manifest(
            files=[bad_name], **_manifest_kwargs()
        )

    with pytest.raises(ValueError, match="重复"):
        build_snapshot_manifest(
            files=[paths[0], paths[0]], **_manifest_kwargs()
        )


def test_staging_filenames_are_qlib_lowercase(tmp_path: Path) -> None:
    staging = prepare_qlib_staging(
        bars=_read("bars.csv"),
        membership=_read("membership.csv"),
        calendars=_read("calendar.csv"),
        source="fixture",
        universe=UNIVERSE,
    )
    paths = write_staging_by_symbol(staging, tmp_path)
    names = sorted(path.name for path in paths)
    assert "sz000001.parquet" in names


def test_r2_validate_provider_fail_closed(tmp_path: Path) -> None:
    expected = DatasetSnapshot(
        snapshot_id="a" * 64,
        manifest_path=tmp_path / "m.json",
        source_fingerprint="b" * 64,
        row_count=1,
        symbol_count=1,
        start=__import__("datetime").date(2026, 1, 5),
        end=__import__("datetime").date(2026, 1, 6),
    )
    with pytest.raises(FileNotFoundError):
        validate_provider(provider_dir=tmp_path / "missing", expected=expected)

    empty = tmp_path / "empty_provider"
    empty.mkdir()
    with pytest.raises(RuntimeError, match="G0/G2|G2"):
        validate_provider(provider_dir=empty, expected=expected)


def test_snapshot_id_is_bare_hex_consumable_by_provider_key(tmp_path: Path) -> None:
    staging = prepare_qlib_staging(
        bars=_read("bars.csv"),
        membership=_read("membership.csv"),
        calendars=_read("calendar.csv"),
        source="fixture",
        universe=UNIVERSE,
    )
    paths = write_staging_by_symbol(staging, tmp_path)
    manifest = build_snapshot_manifest(files=paths, **_manifest_kwargs())
    snapshot_id = snapshot_id_from_manifest(manifest)
    assert len(snapshot_id) == 64
    assert snapshot_id == snapshot_id.lower()
    assert ":" not in snapshot_id
    assert not snapshot_id.startswith("sha256:")
    from quant.research.m3 import compute_provider_key

    key = compute_provider_key(
        snapshot_id=snapshot_id,
        provider_config_hash="c" * 64,
        dump_tool_sha256="d" * 64,
        qlib_version="0.9.7",
        provider_runtime_fingerprint_sha256="e" * 64,
        code_version="code-a",
    )
    assert len(key) == 64
    assert ":" not in key


def test_empty_universe_rejected() -> None:
    with pytest.raises(ValueError, match="universe"):
        prepare_qlib_staging(
            bars=_read("bars.csv"),
            membership=_read("membership.csv").filter(pl.col("universe") == "NOPE"),
            calendars=_read("calendar.csv"),
            source="fixture",
            universe="NOPE",
        )


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        default=lambda item: item.isoformat() if type(item) is dt.date else None,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _g2a_fixture(
    root: Path, monkeypatch: pytest.MonkeyPatch,
) -> tuple[Any, object, SnapshotBuildSpec, Path]:
    config = load_m3_config(Path("configs/research/m3_qlib_example.toml"))
    signal_start = config.section("data")["start_date"]
    signal_end = config.section("data")["end_date"]
    assert type(signal_start) is dt.date and type(signal_end) is dt.date
    g1_root = root / "g1"
    g1_root.mkdir(parents=True)
    manifest_path = g1_root / "manifest.json"
    manifest_path.write_bytes(b"g1-manifest")
    manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    bars = pl.DataFrame({
        "symbol": ["600000.SH", "600000.SH", "000001.SZ"],
        "trade_date": [signal_start, signal_end, signal_end],
        "open": [10.0, 11.0, 8.0],
        "high": [10.5, 11.5, 8.5],
        "low": [9.5, 10.5, 7.5],
        "close": [10.0, 11.0, 8.0],
        "volume": [100.0, 110.0, 90.0],
        "amount": [1000.0, 1210.0, 720.0],
        "adj_factor": [1.0, 1.1, 1.0],
        "source": ["tushare", "tushare", "tushare"],
    })
    membership = pl.DataFrame({
        "universe": [
            "CSI300_TUSHARE_MONTHLY_OBSERVED_PIT_V1",
            "CSI300_TUSHARE_MONTHLY_OBSERVED_PIT_V1",
        ],
        "symbol": ["600000.SH", "000001.SZ"],
        "effective_from": [signal_end, signal_end],
        "effective_to": [None, None],
    })
    calendar = pl.DataFrame({
        "market": ["SH", "SZ", "SH"],
        "date": [signal_start, signal_start, signal_end],
        "is_open": [True, True, True],
        "is_connect_open": [False, False, False],
        "is_half_day": [False, False, False],
    })
    artifact_paths: list[tuple[str, Path]] = []
    artifact_entries: list[SimpleNamespace] = []
    for name, frame in (
        ("bar_1d.parquet", bars),
        ("universe_membership.parquet", membership),
        ("trade_calendar.parquet", calendar),
    ):
        path = g1_root / name
        frame.write_parquet(path)
        artifact_paths.append((name, path))
        raw = path.read_bytes()
        artifact_entries.append(SimpleNamespace(
            path=name, size_bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()
        ))
    release_id = "1" * 64
    manifest = SimpleNamespace(
        release_id=release_id,
        history_start=signal_start,
        history_end=signal_end,
        signal_start=signal_start,
        signal_end=signal_end,
        files=tuple(artifact_entries),
    )
    release_handle = SimpleNamespace(manifest_path=manifest_path)
    verified = SimpleNamespace(
        manifest=manifest,
        manifest_sha256=manifest_sha,
        artifact_paths=tuple(sorted(artifact_paths)),
        release=release_handle,
    )
    monkeypatch.setattr(snapshot_mod, "_reverify_release", lambda _: verified)
    code_version = "g2a-test-code-v1"
    request_key = compute_snapshot_request_key(
        g1_release_id=release_id,
        g1_release_manifest_sha256=manifest_sha,
        snapshot_config_sha256=config.snapshot_config_sha256,
        code_version=code_version,
    )
    spec = SnapshotBuildSpec(
        snapshot_request_key=request_key,
        config_version=config.config_version,
        snapshot_config_sha256=config.snapshot_config_sha256,
        code_version=code_version,
        history_start=signal_start,
        history_end=signal_end,
        staging_schema_version="m3-qlib-staging-v1",
        adjustment_formula_version="qlib_yahoo_like_v1",
    )
    return verified, config, spec, root


def test_g2a_build_request_receipt_and_verify_closed_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    common = tmp_path / "artifacts"
    common.mkdir()
    release, config, spec, _ = _g2a_fixture(common, monkeypatch)
    snapshot_root = common / "snapshot-temp"
    snapshot_root.mkdir()
    result = build_snapshot_artifact(
        release=release, config=config, spec=spec, output_root=snapshot_root
    )
    request = build_snapshot_request_record(
        release=release, config=config, spec=spec, result=result
    )
    request_path = common / "snapshot-request.json"
    request_path.write_bytes(_canonical_bytes(asdict(request)))
    receipt_path = common / "snapshot-receipt.json"
    staging_paths = tuple(sorted((snapshot_root / "staging").glob("*.parquet")))
    publish_stage_receipt(
        receipt_path=receipt_path,
        stage="snapshot",
        scope="SNAPSHOT",
        scope_key=spec.snapshot_request_key,
        artifact_roots={"root": common},
        inputs=[
            ("root", release.release.manifest_path),
            *(('root', path) for _, path in release.artifact_paths),
        ],
        outputs=[
            ("root", request_path),
            ("root", snapshot_root / "manifest.json"),
            ("root", snapshot_root / "session_calendar.parquet"),
            *(('root', path) for path in staging_paths),
        ],
    )
    verified = verify_snapshot_artifact(
        snapshot_root=snapshot_root,
        snapshot_request_path=request_path,
        snapshot_receipt_path=receipt_path,
        release=release,
        config=config,
        spec=spec,
        artifact_roots={"root": common},
    )
    assert verified.manifest.snapshot_id == result.manifest.snapshot_id
    assert verified.request.snapshot_request_key == spec.snapshot_request_key
    assert [path.name for path in verified.staging_paths] == [
        "sh600000.parquet", "sz000001.parquet"
    ]


def test_g2a_rejects_nonempty_output_before_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    common = tmp_path / "artifacts"
    common.mkdir()
    release, config, spec, _ = _g2a_fixture(common, monkeypatch)
    output = common / "snapshot-temp"
    output.mkdir()
    marker = output / "keep.txt"
    marker.write_text("user", encoding="utf-8")
    with pytest.raises(M3SnapshotError) as exc:
        build_snapshot_artifact(
            release=release, config=config, spec=spec, output_root=output
        )
    assert exc.value.code == "SNAPSHOT_OUTPUT_INVALID"
    assert marker.read_text(encoding="utf-8") == "user"


def test_g2a_rejects_request_key_from_other_code_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    common = tmp_path / "artifacts"
    common.mkdir()
    release, config, spec, _ = _g2a_fixture(common, monkeypatch)
    bad = SnapshotBuildSpec(
        snapshot_request_key="f" * 64,
        config_version=spec.config_version,
        snapshot_config_sha256=spec.snapshot_config_sha256,
        code_version=spec.code_version,
        history_start=spec.history_start,
        history_end=spec.history_end,
        staging_schema_version=spec.staging_schema_version,
        adjustment_formula_version="qlib_yahoo_like_v1",
    )
    output = common / "snapshot-temp"
    output.mkdir()
    with pytest.raises(M3SnapshotError) as exc:
        build_snapshot_artifact(
            release=release, config=config, spec=bad, output_root=output
        )
    assert exc.value.code == "SNAPSHOT_INPUT_INVALID"
    assert not any(output.iterdir())


def test_g2a_strict_manifest_rejects_duplicate_key(
    tmp_path: Path,
) -> None:
    path = tmp_path / "manifest.json"
    path.write_bytes(b'{"schema_version":"m3-snapshot-manifest-v1","schema_version":"x"}')
    with pytest.raises(M3SnapshotError) as exc:
        snapshot_mod.read_snapshot_manifest(path)
    assert exc.value.code == "SNAPSHOT_OUTPUT_INVALID"
    assert str(exc.value) == "SNAPSHOT_OUTPUT_INVALID"
    assert repr(exc.value) == "M3SnapshotError('SNAPSHOT_OUTPUT_INVALID')"
    assert exc.value.__cause__ is None
    assert exc.value.__suppress_context__ is True


def test_g2a_parent_source_has_no_qlib_import() -> None:
    source = Path(snapshot_mod.__file__).read_text(encoding="utf-8")
    assert "import qlib" not in source


def test_g2a_rejects_authoritative_session_missing_from_all_symbols(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    common = tmp_path / "artifacts"
    common.mkdir()
    release, config, spec, _ = _g2a_fixture(common, monkeypatch)
    bar_path = dict(release.artifact_paths)["bar_1d.parquet"]
    bars = pl.read_parquet(bar_path).filter(
        pl.col("trade_date") != spec.history_start
    )
    bars.write_parquet(bar_path)
    raw = bar_path.read_bytes()
    entry = next(item for item in release.manifest.files if item.path == bar_path.name)
    entry.size_bytes = len(raw)
    entry.sha256 = hashlib.sha256(raw).hexdigest()
    output = common / "snapshot-temp"
    output.mkdir()
    with pytest.raises(M3SnapshotError) as exc:
        build_snapshot_artifact(
            release=release, config=config, spec=spec, output_root=output
        )
    assert exc.value.code == "SNAPSHOT_OUTPUT_INVALID"


def test_g2a_rejects_receipt_with_extra_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    common = tmp_path / "artifacts"
    common.mkdir()
    release, config, spec, _ = _g2a_fixture(common, monkeypatch)
    snapshot_root = common / "snapshot-temp"
    snapshot_root.mkdir()
    result = build_snapshot_artifact(
        release=release, config=config, spec=spec, output_root=snapshot_root
    )
    request = build_snapshot_request_record(
        release=release, config=config, spec=spec, result=result
    )
    request_path = common / "snapshot-request.json"
    request_path.write_bytes(_canonical_bytes(asdict(request)))
    extra = common / "extra.bin"
    extra.write_bytes(b"extra")
    receipt_path = common / "snapshot-receipt.json"
    staging_paths = tuple(sorted((snapshot_root / "staging").glob("*.parquet")))
    publish_stage_receipt(
        receipt_path=receipt_path,
        stage="snapshot",
        scope="SNAPSHOT",
        scope_key=spec.snapshot_request_key,
        artifact_roots={"root": common},
        inputs=[
            ("root", release.release.manifest_path),
            *(("root", path) for _, path in release.artifact_paths),
        ],
        outputs=[
            ("root", request_path),
            ("root", snapshot_root / "manifest.json"),
            ("root", snapshot_root / "session_calendar.parquet"),
            *(("root", path) for path in staging_paths),
            ("root", extra),
        ],
    )
    with pytest.raises(M3SnapshotError) as exc:
        verify_snapshot_artifact(
            snapshot_root=snapshot_root,
            snapshot_request_path=request_path,
            snapshot_receipt_path=receipt_path,
            release=release,
            config=config,
            spec=spec,
            artifact_roots={"root": common},
        )
    assert exc.value.code == "SNAPSHOT_IDENTITY_MISMATCH"
