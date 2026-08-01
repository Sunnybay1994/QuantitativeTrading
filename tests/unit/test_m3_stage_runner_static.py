"""G8B static-directory publication and recovery tests."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from quant.research.m3.config import LoadedM3Config
from quant.research.m3.orchestration import (
    BACKTEST_STAGE_SPEC,
    EVALUATION_STAGE_SPEC,
    TARGETS_STAGE_SPEC,
    ExternalInput,
    M3StageRunnerError,
    RunPlan,
    StageBuildReport,
    StageContext,
    StageNode,
    StageOutputInput,
    StageRunner,
    StaticDirectoryPublication,
)
from quant.research.m3.run_state import ArtifactDigest

_KEY = "4" * 64


def _config() -> LoadedM3Config:
    digest = "5" * 64
    return LoadedM3Config(
        document={}, config_version="test", full_config_sha256=digest,
        g1_config_sha256=digest, snapshot_config_sha256=digest,
        provider_config_sha256=digest, scientific_config_sha256=digest,
        provider_validation_config_sha256=digest,
        label_reconciliation_config_sha256=digest,
        acceptance_config_sha256=digest, canonical_tracking_uri="test",
        tracking_target_key=digest,
    )


def _digest(root: Path, path: Path) -> ArtifactDigest:
    raw = path.read_bytes()
    return ArtifactDigest(
        root_alias="root", relative_path=path.relative_to(root).as_posix(),
        size_bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
    )


def _node(input_digest: ArtifactDigest) -> StageNode:
    return StageNode(
        node_id="evaluation", spec_name="evaluation", scope="WORK",
        scope_key=_KEY, fold="fold_001", horizon=5, dependencies=(),
        inputs=(ExternalInput(input_digest),),
        publication=StaticDirectoryPublication(f"work/{_KEY}/evaluation"),
        output_specs=EVALUATION_STAGE_SPEC.outputs,
        receipt_path=f"receipts/work/{_KEY}.evaluation.json",
    )


def _test_commit(src: Path, dst: Path) -> None:
    if dst.exists():
        raise FileExistsError(dst)
    os.rename(src, dst)


def _write_evaluation(root: Path, *, metrics: bytes = b"metrics") -> None:
    (root / "daily_ic.parquet").write_bytes(b"daily")
    (root / "metrics.json").write_bytes(metrics)
    (root / "evaluation_manifest.json").write_text(
        json.dumps(
            {"files": ["daily_ic.parquet", "metrics.json"], "schema": "test-v1"},
            sort_keys=True, separators=(",", ":"),
        ),
        encoding="utf-8",
    )


def _evaluation_closure(root: Path) -> None:
    payload = json.loads((root / "evaluation_manifest.json").read_text("utf-8"))
    assert payload == {
        "files": ["daily_ic.parquet", "metrics.json"], "schema": "test-v1",
    }


def _report(root: Path) -> StageBuildReport:
    return StageBuildReport(tuple(sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*") if path.is_file()
    )))


def _fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> tuple[StageRunner, StageNode, Path]:
    monkeypatch.setattr(
        "quant.research.m3.orchestration.commit_directory_noreplace",
        _test_commit,
    )
    common = tmp_path / "artifacts"
    common.mkdir()
    source = common / "input.json"
    source.write_bytes(b"input")
    stage_root = common / "m3"
    stage_root.mkdir()
    runner = StageRunner(
        stage_root=stage_root, artifact_roots={"root": common}, config=_config()
    )
    return runner, _node(_digest(common, source)), stage_root


def test_static_first_publish_resume_and_no_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, node, _ = _fixture(tmp_path, monkeypatch)

    def handler(context: StageContext) -> StageBuildReport:
        assert not any(context.temp_output_root.iterdir())
        assert tuple(item.path.name for item in context.inputs) == ("input.json",)
        _write_evaluation(context.temp_output_root)
        return _report(context.temp_output_root)

    first = runner.run_static(
        node=node, handler=handler, closure_verifier=_evaluation_closure
    )
    assert first.reused is False
    assert first.final_root.is_dir()
    assert first.receipt_path.is_file()

    called = False

    def forbidden(_context: StageContext) -> StageBuildReport:
        nonlocal called
        called = True
        raise AssertionError

    second = runner.run_static(
        node=node, handler=forbidden, closure_verifier=_evaluation_closure
    )
    assert second.reused is True
    assert called is False
    with pytest.raises(M3StageRunnerError) as exc:
        runner.run_static(
            node=node, handler=forbidden, closure_verifier=_evaluation_closure,
            resume=False,
        )
    assert exc.value.code == "STAGE_ALREADY_COMPLETE"
    assert called is False


def test_static_rejects_receipt_path_that_is_parent_of_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, node, _ = _fixture(tmp_path, monkeypatch)
    invalid = StageNode(
        node_id=node.node_id,
        spec_name=node.spec_name,
        scope=node.scope,
        scope_key=node.scope_key,
        fold=node.fold,
        horizon=node.horizon,
        dependencies=node.dependencies,
        inputs=node.inputs,
        publication=StaticDirectoryPublication(
            f"receipts/work/{_KEY}/evaluation"
        ),
        output_specs=node.output_specs,
        receipt_path=f"receipts/work/{_KEY}",
    )

    with pytest.raises(M3StageRunnerError) as exc:
        runner.run_static(
            node=invalid,
            handler=lambda _context: StageBuildReport(()),
            closure_verifier=lambda _root: None,
        )
    assert exc.value.code == "STAGE_INPUT_INVALID"


def test_static_complete_final_without_receipt_rebuilds_then_supplements(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, node, _ = _fixture(tmp_path, monkeypatch)

    def handler(context: StageContext) -> StageBuildReport:
        _write_evaluation(context.temp_output_root)
        return _report(context.temp_output_root)

    first = runner.run_static(
        node=node, handler=handler, closure_verifier=_evaluation_closure
    )
    first.receipt_path.unlink()
    recovered = runner.run_static(
        node=node, handler=handler, closure_verifier=_evaluation_closure
    )
    assert recovered.reused is True
    assert recovered.receipt_path.is_file()


def test_static_recovery_rejects_byte_difference_without_overwrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, node, _ = _fixture(tmp_path, monkeypatch)

    def original(context: StageContext) -> StageBuildReport:
        _write_evaluation(context.temp_output_root)
        return _report(context.temp_output_root)

    first = runner.run_static(
        node=node, handler=original, closure_verifier=_evaluation_closure
    )
    original_bytes = (first.final_root / "metrics.json").read_bytes()
    first.receipt_path.unlink()

    def changed(context: StageContext) -> StageBuildReport:
        _write_evaluation(context.temp_output_root, metrics=b"changed")
        return _report(context.temp_output_root)

    with pytest.raises(M3StageRunnerError) as exc:
        runner.run_static(
            node=node, handler=changed, closure_verifier=_evaluation_closure
        )
    assert exc.value.code == "STAGE_RECOVERY_CONFLICT"
    assert (first.final_root / "metrics.json").read_bytes() == original_bytes
    assert not first.receipt_path.exists()


def test_static_partial_final_and_corrupt_receipt_fail_before_handler(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, node, _ = _fixture(tmp_path, monkeypatch)

    def handler(context: StageContext) -> StageBuildReport:
        _write_evaluation(context.temp_output_root)
        return _report(context.temp_output_root)

    first = runner.run_static(
        node=node, handler=handler, closure_verifier=_evaluation_closure
    )
    first.receipt_path.unlink()
    (first.final_root / "metrics.json").unlink()
    called = False

    def forbidden(_context: StageContext) -> StageBuildReport:
        nonlocal called
        called = True
        raise AssertionError

    with pytest.raises(M3StageRunnerError) as exc:
        runner.run_static(
            node=node, handler=forbidden, closure_verifier=_evaluation_closure
        )
    assert exc.value.code == "STAGE_RECOVERY_CONFLICT"
    assert called is False


def test_static_stage_output_requires_verified_dependency_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, producer, _ = _fixture(tmp_path, monkeypatch)

    def producer_handler(context: StageContext) -> StageBuildReport:
        _write_evaluation(context.temp_output_root)
        return _report(context.temp_output_root)

    produced = runner.run_static(
        node=producer, handler=producer_handler,
        closure_verifier=_evaluation_closure,
    )
    consumer = StageNode(
        node_id="targets", spec_name="targets", scope="WORK", scope_key=_KEY,
        fold="fold_001", horizon=5, dependencies=("evaluation",),
        inputs=(StageOutputInput("evaluation", "root", "metrics.json"),),
        publication=StaticDirectoryPublication(f"work/{_KEY}/targets"),
        output_specs=TARGETS_STAGE_SPEC.outputs,
        receipt_path=f"receipts/work/{_KEY}.targets.json",
    )
    plan = RunPlan("WORK", (producer, consumer))

    def target_handler(context: StageContext) -> StageBuildReport:
        assert context.inputs[0].path.name == "metrics.json"
        for output in TARGETS_STAGE_SPEC.outputs:
            (context.temp_output_root / output.relative_path).write_bytes(b"target")
        return _report(context.temp_output_root)

    def target_closure(root: Path) -> None:
        assert {path.name for path in root.iterdir()} == {
            "target_daily.parquet", "target_manifest.json", "target_weights.parquet",
        }

    completed = runner.run_static(
        node=consumer, plan=plan, handler=target_handler,
        closure_verifier=target_closure,
    )
    assert completed.reused is False
    produced.receipt_path.unlink()
    called = False

    def blocked(context: StageContext) -> StageBuildReport:
        nonlocal called
        called = True
        return target_handler(context)

    with pytest.raises(M3StageRunnerError) as exc:
        runner.run_static(
            node=consumer, plan=plan, handler=blocked,
            closure_verifier=target_closure,
        )
    assert exc.value.code == "STAGE_INPUT_INVALID"
    assert called is False


def test_static_tree_outputs_are_published_as_one_exact_closure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, _producer, _ = _fixture(tmp_path, monkeypatch)
    node = StageNode(
        node_id="backtest", spec_name="backtest", scope="WORK", scope_key=_KEY,
        fold="fold_001", horizon=5, dependencies=(), inputs=(),
        publication=StaticDirectoryPublication(f"work/{_KEY}/backtest"),
        output_specs=BACKTEST_STAGE_SPEC.outputs,
        receipt_path=f"receipts/work/{_KEY}.backtest.json",
    )

    def handler(context: StageContext) -> StageBuildReport:
        (context.temp_output_root / "backtest_manifest.json").write_text(
            '{"schema":"bundle-v1"}', encoding="utf-8"
        )
        (context.temp_output_root / "backtest_metrics.json").write_bytes(b"root")
        for scenario in ("0p5x", "1p0x", "2p0x"):
            scenario_root = context.temp_output_root / scenario
            scenario_root.mkdir()
            (scenario_root / "manifest.json").write_text(
                json.dumps({"scenario": scenario}), encoding="utf-8"
            )
            (scenario_root / "metrics.json").write_bytes(b"metrics")
        return _report(context.temp_output_root)

    def closure(root: Path) -> None:
        assert json.loads((root / "backtest_manifest.json").read_text("utf-8")) == {
            "schema": "bundle-v1"
        }
        assert tuple(sorted(path.name for path in root.iterdir() if path.is_dir())) == (
            "0p5x", "1p0x", "2p0x",
        )
        for scenario in ("0p5x", "1p0x", "2p0x"):
            assert json.loads(
                (root / scenario / "manifest.json").read_text("utf-8")
            ) == {"scenario": scenario}

    result = runner.run_static(
        node=node, handler=handler, closure_verifier=closure
    )
    assert result.reused is False
    assert len(result.receipt.outputs) == 8
