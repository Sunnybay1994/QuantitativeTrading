"""G8A/G8B snapshot plan and crash-safe publication tests."""

from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path
from typing import Any

import pytest

from quant.research.m3.orchestration import (
    M3StageRunnerError,
    SnapshotStageResult,
    StageBuildReport,
    StageContext,
    StageRunner,
    make_snapshot_run_plan,
)
from quant.research.m3.run_state import ArtifactDigest
from quant.research.m3.snapshot import (
    build_snapshot_artifact,
    build_snapshot_request_record,
    verify_snapshot_artifact,
    verify_snapshot_build_result,
)
from tests.unit.test_m3_snapshot import _g2a_fixture


def _digest(root: Path, path: Path) -> ArtifactDigest:
    raw = path.read_bytes()
    return ArtifactDigest(
        root_alias="root",
        relative_path=path.relative_to(root).as_posix(),
        size_bytes=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
    )


def _tree_report(root: Path) -> StageBuildReport:
    paths = tuple(sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    ))
    return StageBuildReport(output_relative_paths=paths)


def _test_commit_directory_noreplace(src: Path, dst: Path) -> None:
    """Keep runner-state tests independent of the host renameat2 capability."""
    if dst.exists():
        raise FileExistsError(dst)
    os.rename(src, dst)


def _runner_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> tuple[
    StageRunner,
    Any,
    Any,
    Any,
    Any,
    Any,
    Any,
    Path,
]:
    monkeypatch.setattr(
        "quant.research.m3.orchestration.commit_directory_noreplace",
        _test_commit_directory_noreplace,
    )
    common = tmp_path / "artifacts"
    common.mkdir()
    release, config, spec, _ = _g2a_fixture(common, monkeypatch)
    stage_root = common / "m3"
    stage_root.mkdir()
    input_paths = (
        release.release.manifest_path,
        *(path for _, path in release.artifact_paths),
    )
    plan = make_snapshot_run_plan(
        snapshot_request_key=spec.snapshot_request_key,
        inputs=tuple(_digest(common, path) for path in input_paths),
    )
    node = plan.nodes[0]
    runner = StageRunner(
        stage_root=stage_root, artifact_roots={"root": common}, config=config
    )

    def handler(context: StageContext) -> StageBuildReport:
        build_snapshot_artifact(
            release=release,
            config=config,
            spec=spec,
            output_root=context.temp_output_root,
        )
        return _tree_report(context.temp_output_root)

    def closure(root: Path) -> tuple[Any, Any]:
        result = verify_snapshot_build_result(
            snapshot_root=root, release=release, config=config, spec=spec
        )
        request = build_snapshot_request_record(
            release=release, config=config, spec=spec, result=result
        )
        return result, request

    return runner, node, handler, closure, release, config, spec, common


def test_snapshot_stage_first_publish_resume_and_final_verify(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, node, handler, closure, release, config, spec, common = _runner_fixture(
        tmp_path, monkeypatch
    )
    first = runner.run_snapshot(
        node=node, handler=handler, closure_verifier=closure
    )
    assert first.reused is False
    assert first.snapshot_root.name == first.build.manifest.snapshot_id
    assert first.request.snapshot_id == first.snapshot_root.name
    assert first.request_record_path.read_bytes()
    assert first.receipt_path.read_bytes()
    assert not any((common / "m3" / ".stage-tmp").iterdir())
    lock_files = tuple((common / "m3" / ".stage-locks").glob("*/.writer.lock"))
    assert len(lock_files) == 1
    assert not lock_files[0].is_symlink()
    assert lock_files[0].read_bytes() in {b"", b"\x00"}

    called = False

    def forbidden_handler(_context: StageContext) -> StageBuildReport:
        nonlocal called
        called = True
        raise AssertionError("resume must not invoke handler")

    second = runner.run_snapshot(
        node=node, handler=forbidden_handler, closure_verifier=closure
    )
    assert second.reused is True
    assert called is False
    assert tuple((common / "m3" / ".stage-locks").glob("*/.writer.lock")) == lock_files
    verified = verify_snapshot_artifact(
        snapshot_root=second.snapshot_root,
        snapshot_request_path=second.request_record_path,
        snapshot_receipt_path=second.receipt_path,
        release=release,
        config=config,
        spec=spec,
        artifact_roots={"root": common},
    )
    assert verified.manifest.snapshot_id == first.build.manifest.snapshot_id


def test_snapshot_stage_no_resume_rejects_valid_completion_without_handler(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, node, handler, closure, *_ = _runner_fixture(tmp_path, monkeypatch)
    runner.run_snapshot(node=node, handler=handler, closure_verifier=closure)
    with pytest.raises(M3StageRunnerError) as exc:
        runner.run_snapshot(
            node=node, handler=lambda _: (_ for _ in ()).throw(AssertionError),
            closure_verifier=closure,
            resume=False,
        )
    assert exc.value.code == "STAGE_ALREADY_COMPLETE"


def test_snapshot_stage_recovers_final_without_mapping_or_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, node, handler, closure, *_ = _runner_fixture(tmp_path, monkeypatch)
    first = runner.run_snapshot(node=node, handler=handler, closure_verifier=closure)
    first.request_record_path.unlink()
    first.receipt_path.unlink()
    recovered = runner.run_snapshot(
        node=node, handler=handler, closure_verifier=closure
    )
    assert recovered.snapshot_root == first.snapshot_root
    assert recovered.request_record_path.exists()
    assert recovered.receipt_path.exists()


def test_snapshot_stage_mapping_without_final_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, node, handler, closure, *_ = _runner_fixture(tmp_path, monkeypatch)
    first = runner.run_snapshot(node=node, handler=handler, closure_verifier=closure)
    first.receipt_path.unlink()
    shutil.rmtree(first.snapshot_root)
    with pytest.raises(M3StageRunnerError) as exc:
        runner.run_snapshot(node=node, handler=handler, closure_verifier=closure)
    assert exc.value.code == "STAGE_RECOVERY_CONFLICT"
    assert first.request_record_path.exists()


def test_snapshot_stage_rejects_handler_report_not_matching_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, node, handler, closure, *_ = _runner_fixture(tmp_path, monkeypatch)

    def lying_handler(context: StageContext) -> StageBuildReport:
        report = handler(context)
        return StageBuildReport(
            output_relative_paths=tuple(sorted((*report.output_relative_paths, "extra.bin")))
        )

    with pytest.raises(M3StageRunnerError) as exc:
        runner.run_snapshot(
            node=node, handler=lying_handler, closure_verifier=closure
        )
    assert exc.value.code == "STAGE_OUTPUT_INVALID"


def test_snapshot_stage_corrupt_receipt_fails_before_handler(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, node, handler, closure, *_ = _runner_fixture(tmp_path, monkeypatch)
    first: SnapshotStageResult = runner.run_snapshot(
        node=node, handler=handler, closure_verifier=closure
    )
    first.receipt_path.write_bytes(b"corrupt")
    called = False

    def forbidden(_context: StageContext) -> StageBuildReport:
        nonlocal called
        called = True
        raise AssertionError

    with pytest.raises(M3StageRunnerError) as exc:
        runner.run_snapshot(
            node=node, handler=forbidden, closure_verifier=closure
        )
    assert exc.value.code == "STAGE_RECOVERY_CONFLICT"
    assert called is False
