"""Development-example G1 package and explicit G2A consumption tests."""

from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path

import polars as pl
import pytest

from quant.data.m3_release import VerifiedG1Release
from quant.research.m3.config import LoadedM3Config, load_m3_config
from quant.research.m3.contracts import (
    SnapshotBuildResult,
    SnapshotBuildSpec,
    SnapshotRequestRecordV1,
)
from quant.research.m3.development_example import (
    M3DevelopmentExampleError,
    VerifiedDevelopmentExampleG1Release,
    VerifiedDevelopmentExampleSnapshotArtifact,
    build_development_example_g1_release,
    compute_development_provider_validation_key,
    compute_development_snapshot_request_key,
    derive_development_example_m3_config,
    verify_development_example_g1_release,
)
from quant.research.m3.orchestration import (
    M3StageRunnerError,
    StageBuildReport,
    StageContext,
    StageRunner,
    make_development_snapshot_run_plan,
)
from quant.research.m3.run_state import (
    compute_snapshot_request_key,
    publish_stage_receipt,
)
from quant.research.m3.snapshot import (
    M3SnapshotError,
    build_development_example_snapshot_artifact,
    build_development_example_snapshot_request_record,
    build_snapshot_artifact,
    snapshot_request_record_bytes,
    verify_development_example_snapshot_artifact,
    verify_development_example_snapshot_build_result,
)


def _release(root: Path) -> VerifiedDevelopmentExampleG1Release:
    output = root / "development-example-g1"
    output.mkdir(parents=True)
    return build_development_example_g1_release(output_root=output)


def _spec(
    release: VerifiedDevelopmentExampleG1Release,
) -> tuple[LoadedM3Config, SnapshotBuildSpec]:
    base = load_m3_config(Path("configs/research/m3_qlib_example.toml"))
    config = derive_development_example_m3_config(base=base)
    code_version = "development-example/g2a-v1"
    key = compute_development_snapshot_request_key(
        release=release,
        snapshot_config_sha256=config.snapshot_config_sha256,
        code_version=code_version,
    )
    spec = SnapshotBuildSpec(
        snapshot_request_key=key,
        config_version=config.config_version,
        snapshot_config_sha256=config.snapshot_config_sha256,
        code_version=code_version,
        history_start=release.manifest.history_start,
        history_end=release.manifest.history_end,
        staging_schema_version="m3-qlib-staging-v1",
        adjustment_formula_version="qlib_yahoo_like_v1",
    )
    return config, spec


def _tree_report(root: Path) -> StageBuildReport:
    return StageBuildReport(output_relative_paths=tuple(sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    )))


def _test_commit_directory_noreplace(source: Path, destination: Path) -> None:
    if destination.exists():
        raise FileExistsError(destination)
    os.rename(source, destination)


def test_development_g1_build_verify_and_boundary_rows(tmp_path: Path) -> None:
    release = _release(tmp_path)
    assert release.release_kind == "development_example"
    assert release.formal_gate_eligible is False
    assert release.manifest.example_id.startswith("development-example-")
    assert len(release.artifact_paths) == 17
    assert not isinstance(release, VerifiedG1Release)
    assert release.receipt.stage == "development-example-g1"
    assert len(release.receipt.inputs) == 1
    assert len(release.receipt.outputs) == 19

    paths = dict(release.artifact_paths)
    bars = pl.read_parquet(paths["bar_1d.parquet"])
    suspension = pl.read_parquet(paths["suspension_1d.parquet"])
    factors = pl.read_parquet(paths["adjustment_factor.parquet"])
    instruments = pl.read_parquet(paths["instrument.parquet"])
    assert bars.height == 113
    emitted_counts = bars.group_by("symbol").len().sort("symbol")
    assert emitted_counts.to_dicts() == [
        {"symbol": "000001.SZ", "len": 37},
        {"symbol": "000002.SZ", "len": 38},
        {"symbol": "600000.SH", "len": 38},
    ]
    assert suspension.row(0, named=True)["suspension_scope"] == "FULL_DAY"
    suspended_key = suspension.select("symbol", "trade_date").row(0)
    assert suspended_key not in set(bars.select("symbol", "trade_date").iter_rows())
    sh_factors = factors.filter(pl.col("symbol") == "600000.SH").sort(
        "effective_date"
    )
    assert sh_factors.item(1, "adj_factor") > sh_factors.item(0, "adj_factor")
    lifecycle = instruments.filter(pl.col("symbol") == "000002.SZ")
    assert lifecycle.item(0, "status") == "DELISTED"
    assert lifecycle.item(0, "delist_date") == bars.get_column("trade_date").max()


def test_development_g1_is_deterministic_and_formal_reader_rejects(
    tmp_path: Path,
) -> None:
    left = _release(tmp_path / "left")
    right = _release(tmp_path / "right")
    assert left.manifest == right.manifest
    assert left.request == right.request
    assert left.receipt == right.receipt
    assert not hasattr(left.release, "release_id")
    assert not hasattr(left.release, "quality_path")


def test_development_provider_validation_key_is_domain_separated() -> None:
    values = {
        "example_id": f"development-example-{'a' * 64}",
        "provider_key": "b" * 64,
        "provider_receipt_sha256": "c" * 64,
        "provider_validation_config_sha256": "d" * 64,
        "provider_runtime_fingerprint_sha256": "e" * 64,
        "code_version": "development-example/g2c-v1",
    }
    key = compute_development_provider_validation_key(**values)
    assert len(key) == 64
    assert key == compute_development_provider_validation_key(**values)
    with pytest.raises(ValueError):
        compute_development_provider_validation_key(
            **(values | {"code_version": "formal/g2c-v1"})
        )


def test_development_g1_detects_artifact_and_tree_drift(tmp_path: Path) -> None:
    release = _release(tmp_path)
    bars = dict(release.artifact_paths)["bar_1d.parquet"]
    bars.write_bytes(bars.read_bytes() + b"x")
    with pytest.raises(M3DevelopmentExampleError) as exc:
        verify_development_example_g1_release(root=release.release.root)
    assert exc.value.code == "DEVELOPMENT_EXAMPLE_ARTIFACT_INVALID"

    other = _release(tmp_path / "other")
    (other.release.root / "unexpected.txt").write_text("x", encoding="utf-8")
    with pytest.raises(M3DevelopmentExampleError):
        verify_development_example_g1_release(root=other.release.root)


def test_development_g1_moved_to_unlabelled_root_is_rejected(tmp_path: Path) -> None:
    release = _release(tmp_path)
    unlabelled = tmp_path / "g1-formal-looking"
    release.release.root.rename(unlabelled)
    with pytest.raises(M3DevelopmentExampleError):
        verify_development_example_g1_release(root=unlabelled)


def test_formal_snapshot_builder_rejects_development_before_write(
    tmp_path: Path,
) -> None:
    release = _release(tmp_path)
    config, spec = _spec(release)
    output = tmp_path / "formal-output"
    output.mkdir()
    with pytest.raises(M3SnapshotError) as exc:
        build_snapshot_artifact(
            release=release,  # type: ignore[arg-type]
            config=config,
            spec=spec,
            output_root=output,
        )
    assert exc.value.code == "SNAPSHOT_OUTPUT_INVALID"
    assert not any(output.iterdir())


def test_development_snapshot_closed_loop_uses_distinct_stage(tmp_path: Path) -> None:
    common = tmp_path / "artifacts"
    common.mkdir()
    release = _release(common)
    config, spec = _spec(release)
    snapshot_root = common / "snapshot"
    snapshot_root.mkdir()
    result = build_development_example_snapshot_artifact(
        release=release, config=config, spec=spec, output_root=snapshot_root
    )
    request = build_development_example_snapshot_request_record(
        release=release, config=config, spec=spec, result=result
    )
    request_path = common / "snapshot-request.json"
    request_path.write_bytes(snapshot_request_record_bytes(request))
    receipt_path = common / "snapshot-receipt.json"
    release_paths = dict(release.artifact_paths)
    staging = tuple(sorted((snapshot_root / "staging").glob("*.parquet")))
    publish_stage_receipt(
        receipt_path=receipt_path,
        stage="development-snapshot",
        scope="SNAPSHOT",
        scope_key=spec.snapshot_request_key,
        artifact_roots={"root": common},
        inputs=[
            ("root", release.release.manifest_path),
            ("root", release_paths["bar_1d.parquet"]),
            ("root", release_paths["universe_membership.parquet"]),
            ("root", release_paths["trade_calendar.parquet"]),
        ],
        outputs=[
            ("root", request_path),
            ("root", snapshot_root / "manifest.json"),
            ("root", snapshot_root / "session_calendar.parquet"),
            *(("root", path) for path in staging),
        ],
    )
    verified = verify_development_example_snapshot_artifact(
        snapshot_root=snapshot_root,
        snapshot_request_path=request_path,
        snapshot_receipt_path=receipt_path,
        release=release,
        config=config,
        spec=spec,
        artifact_roots={"root": common},
    )
    assert isinstance(verified, VerifiedDevelopmentExampleSnapshotArtifact)
    assert verified.formal_gate_eligible is False
    assert verified.example_id == release.manifest.example_id
    assert [path.name for path in verified.staging_paths] == [
        "sh600000.parquet", "sz000001.parquet", "sz000002.parquet"
    ]


def test_development_snapshot_rejects_formal_key_and_stage(tmp_path: Path) -> None:
    common = tmp_path / "artifacts"
    common.mkdir()
    release = _release(common)
    config, spec = _spec(release)
    formal_key = compute_snapshot_request_key(
        g1_release_id=release.manifest.contract_release_id,
        g1_release_manifest_sha256=release.manifest_sha256,
        snapshot_config_sha256=config.snapshot_config_sha256,
        code_version=spec.code_version,
    )
    bad_spec = replace(spec, snapshot_request_key=formal_key)
    output = common / "bad"
    output.mkdir()
    with pytest.raises(M3SnapshotError) as exc:
        build_development_example_snapshot_artifact(
            release=release, config=config, spec=bad_spec, output_root=output
        )
    assert exc.value.code == "SNAPSHOT_INPUT_INVALID"
    assert not any(output.iterdir())


def test_development_snapshot_runner_publish_resume_and_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "quant.research.m3.orchestration.commit_directory_noreplace",
        _test_commit_directory_noreplace,
    )
    common = tmp_path / "artifacts"
    common.mkdir()
    release = _release(common)
    config, spec = _spec(release)
    stage_root = common / "m3-development"
    stage_root.mkdir()
    node = make_development_snapshot_run_plan(
        release=release,
        snapshot_request_key=spec.snapshot_request_key,
        artifact_root=common,
        root_alias="root",
    ).nodes[0]
    runner = StageRunner(
        stage_root=stage_root, artifact_roots={"root": common}, config=config
    )

    def handler(context: StageContext) -> StageBuildReport:
        build_development_example_snapshot_artifact(
            release=release, config=config, spec=spec,
            output_root=context.temp_output_root,
        )
        return _tree_report(context.temp_output_root)

    def closure(root: Path) -> tuple[SnapshotBuildResult, SnapshotRequestRecordV1]:
        result = verify_development_example_snapshot_build_result(
            snapshot_root=root, release=release, config=config, spec=spec,
        )
        request = build_development_example_snapshot_request_record(
            release=release, config=config, spec=spec, result=result,
        )
        return result, request

    first = runner.run_development_snapshot(
        node=node, handler=handler, closure_verifier=closure
    )
    assert first.reused is False
    assert first.receipt.stage == "development-snapshot"
    assert "development-snapshot" in first.receipt_path.as_posix()
    verified = verify_development_example_snapshot_artifact(
        snapshot_root=first.snapshot_root,
        snapshot_request_path=first.request_record_path,
        snapshot_receipt_path=first.receipt_path,
        release=release,
        config=config,
        spec=spec,
        artifact_roots={"root": common},
    )
    assert isinstance(verified, VerifiedDevelopmentExampleSnapshotArtifact)

    reused = runner.run_development_snapshot(
        node=node,
        handler=lambda _: (_ for _ in ()).throw(AssertionError),
        closure_verifier=closure,
    )
    assert reused.reused is True
    with pytest.raises(M3StageRunnerError) as exc:
        runner.run_snapshot(
            node=node, handler=handler, closure_verifier=closure,
        )
    assert exc.value.code == "STAGE_INPUT_INVALID"

    first.request_record_path.unlink()
    first.receipt_path.unlink()
    recovered = runner.run_development_snapshot(
        node=node, handler=handler, closure_verifier=closure,
    )
    assert recovered.reused is False
    assert recovered.snapshot_root == first.snapshot_root
