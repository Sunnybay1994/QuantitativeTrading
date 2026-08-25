"""Integration: formal summary StageRunner publication compatibility."""

from __future__ import annotations

import importlib.util
import pickle
from pathlib import Path
from typing import Any

import pytest

import quant.research.m3.summary_stage as stage_module
from quant.data.m3_release import platform_supports_renameat2_noreplace
from quant.research.m3.orchestration import M3StageRunnerError
from quant.research.m3.summary_stage import run_formal_summary_stage

_UNIT_SPEC = importlib.util.spec_from_file_location(
    "m3_summary_stage_unit_support",
    Path(__file__).parents[1] / "unit" / "test_m3_summary_stage.py",
)
assert _UNIT_SPEC is not None and _UNIT_SPEC.loader is not None
_UNIT = importlib.util.module_from_spec(_UNIT_SPEC)
_UNIT_SPEC.loader.exec_module(_UNIT)


@pytest.mark.skipif(
    not platform_supports_renameat2_noreplace(),
    reason="host lacks atomic directory no-replace publication",
)
def test_actual_summary_stage_publish_resume_noresume_and_receipt_tamper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _UNIT._stage_bundle(tmp_path, monkeypatch)
    calls: list[tuple[str, Path]] = []
    actual_build = stage_module.build_research_summary_stage_artifact
    actual_pre = stage_module.verify_research_summary_stage_precommit
    actual_pub = stage_module.verify_research_summary_stage_publication
    actual_final = stage_module.verify_research_summary_stage_artifact

    def build(**kwargs: Any) -> Any:
        calls.append(("build", kwargs["output_root"]))
        return actual_build(**kwargs)

    def pre(**kwargs: Any) -> Any:
        calls.append(("pre", kwargs["root"]))
        return actual_pre(**kwargs)

    def publication(**kwargs: Any) -> Any:
        calls.append(("publication", kwargs["root"]))
        return actual_pub(**kwargs)

    def final(**kwargs: Any) -> Any:
        calls.append(("artifact", kwargs["root"]))
        return actual_final(**kwargs)

    monkeypatch.setattr(
        stage_module, "build_research_summary_stage_artifact", build
    )
    monkeypatch.setattr(
        stage_module, "verify_research_summary_stage_precommit", pre
    )
    monkeypatch.setattr(
        stage_module, "verify_research_summary_stage_publication", publication
    )
    monkeypatch.setattr(
        stage_module, "verify_research_summary_stage_artifact", final
    )

    result = run_formal_summary_stage(
        stage_root=bundle["stage_root"],
        artifact_roots=bundle["artifact_roots"],
        config=bundle["config"],
        evaluations=bundle["evaluations"],
        evaluation_contexts=bundle["contexts"],
        experiment=bundle["experiment"],
        horizon_sessions=5,
        upstream_paths=bundle["upstream"],
        resume=True,
    )
    assert [name for name, _ in calls] == [
        "build", "pre", "publication", "artifact",
    ]
    assert calls[0][1].parent == bundle["stage_root"] / ".stage-tmp"
    assert calls[1][1].parent == bundle["stage_root"] / ".stage-tmp"
    assert calls[2][1] == result.final_root
    assert calls[3][1] == result.final_root
    assert result.reused is False
    assert result.verified.root == result.final_root
    assert result.receipt.stage == "research-summary"
    assert result.receipt.scope == "EXPERIMENT"
    assert len(result.receipt.outputs) == 4
    with pytest.raises(TypeError, match="M3_FORMAL_SUMMARY_STAGE_INVALID"):
        pickle.dumps(result)

    calls.clear()
    resumed = run_formal_summary_stage(
        stage_root=bundle["stage_root"],
        artifact_roots=bundle["artifact_roots"],
        config=bundle["config"],
        evaluations=bundle["evaluations"],
        evaluation_contexts=bundle["contexts"],
        experiment=bundle["experiment"],
        horizon_sessions=5,
        upstream_paths=bundle["upstream"],
        resume=True,
    )
    assert [name for name, _ in calls] == ["publication", "artifact"]
    assert "pre" not in [name for name, _ in calls]
    assert resumed.reused is True
    assert resumed.final_root == result.final_root

    calls.clear()
    with pytest.raises(M3StageRunnerError) as caught:
        run_formal_summary_stage(
            stage_root=bundle["stage_root"],
            artifact_roots=bundle["artifact_roots"],
            config=bundle["config"],
            evaluations=bundle["evaluations"],
            evaluation_contexts=bundle["contexts"],
            experiment=bundle["experiment"],
            horizon_sessions=5,
            upstream_paths=bundle["upstream"],
            resume=False,
        )
    assert caught.value.code == "STAGE_ALREADY_COMPLETE"
    assert caught.value.__cause__ is None and caught.value.__context__ is None

    result.receipt_path.write_bytes(b'{"tampered":true}')
    with pytest.raises(M3StageRunnerError) as tampered:
        run_formal_summary_stage(
            stage_root=bundle["stage_root"],
            artifact_roots=bundle["artifact_roots"],
            config=bundle["config"],
            evaluations=bundle["evaluations"],
            evaluation_contexts=bundle["contexts"],
            experiment=bundle["experiment"],
            horizon_sessions=5,
            upstream_paths=bundle["upstream"],
            resume=True,
        )
    assert tampered.value.code == "STAGE_RECOVERY_CONFLICT"
    assert tampered.value.__cause__ is None and tampered.value.__context__ is None


@pytest.mark.skipif(
    not platform_supports_renameat2_noreplace(),
    reason="host lacks atomic directory no-replace publication",
)
def test_actual_summary_stage_preexisting_final_without_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§10/§12: final exists + receipt missing → publication closure, not temp trust."""
    bundle = _UNIT._stage_bundle(tmp_path, monkeypatch)
    calls: list[tuple[str, Path]] = []
    actual_build = stage_module.build_research_summary_stage_artifact
    actual_pre = stage_module.verify_research_summary_stage_precommit
    actual_pub = stage_module.verify_research_summary_stage_publication
    actual_final = stage_module.verify_research_summary_stage_artifact

    def build(**kwargs: Any) -> Any:
        calls.append(("build", kwargs["output_root"]))
        return actual_build(**kwargs)

    def pre(**kwargs: Any) -> Any:
        calls.append(("pre", kwargs["root"]))
        return actual_pre(**kwargs)

    def publication(**kwargs: Any) -> Any:
        calls.append(("publication", kwargs["root"]))
        return actual_pub(**kwargs)

    def final(**kwargs: Any) -> Any:
        calls.append(("artifact", kwargs["root"]))
        return actual_final(**kwargs)

    monkeypatch.setattr(
        stage_module, "build_research_summary_stage_artifact", build
    )
    monkeypatch.setattr(
        stage_module, "verify_research_summary_stage_precommit", pre
    )
    monkeypatch.setattr(
        stage_module, "verify_research_summary_stage_publication", publication
    )
    monkeypatch.setattr(
        stage_module, "verify_research_summary_stage_artifact", final
    )

    seeded = run_formal_summary_stage(
        stage_root=bundle["stage_root"],
        artifact_roots=bundle["artifact_roots"],
        config=bundle["config"],
        evaluations=bundle["evaluations"],
        evaluation_contexts=bundle["contexts"],
        experiment=bundle["experiment"],
        horizon_sessions=5,
        upstream_paths=bundle["upstream"],
        resume=True,
    )
    receipt_path = seeded.receipt_path
    final_root = seeded.final_root
    assert receipt_path.is_file()
    receipt_path.unlink()
    assert not receipt_path.exists()
    assert final_root.is_dir()

    calls.clear()
    recovered = run_formal_summary_stage(
        stage_root=bundle["stage_root"],
        artifact_roots=bundle["artifact_roots"],
        config=bundle["config"],
        evaluations=bundle["evaluations"],
        evaluation_contexts=bundle["contexts"],
        experiment=bundle["experiment"],
        horizon_sessions=5,
        upstream_paths=bundle["upstream"],
        resume=True,
    )
    assert [name for name, _ in calls] == [
        "publication", "build", "pre", "publication", "artifact",
    ]
    assert calls[0][1] == final_root
    assert calls[1][1].parent == bundle["stage_root"] / ".stage-tmp"
    assert calls[2][1].parent == bundle["stage_root"] / ".stage-tmp"
    assert calls[3][1] == final_root
    assert calls[4][1] == final_root
    assert all(
        root.parent == bundle["stage_root"] / ".stage-tmp"
        for name, root in calls
        if name == "pre"
    )
    assert all(root == final_root for name, root in calls if name == "publication")
    assert "pre" not in {
        name for name, root in calls if root == final_root
    }
    assert recovered.reused is True
    assert recovered.final_root == final_root
    assert recovered.receipt_path == receipt_path
    assert receipt_path.is_file()
    assert recovered.verified.root == final_root

    receipt_path.unlink()
    assert not receipt_path.exists()
    (final_root / "manifest.json").write_bytes(b'{"tampered":true}')
    calls.clear()
    with pytest.raises(M3StageRunnerError) as drifted:
        run_formal_summary_stage(
            stage_root=bundle["stage_root"],
            artifact_roots=bundle["artifact_roots"],
            config=bundle["config"],
            evaluations=bundle["evaluations"],
            evaluation_contexts=bundle["contexts"],
            experiment=bundle["experiment"],
            horizon_sessions=5,
            upstream_paths=bundle["upstream"],
            resume=True,
        )
    assert drifted.value.code == "STAGE_RECOVERY_CONFLICT"
    assert drifted.value.__cause__ is None and drifted.value.__context__ is None
    assert [name for name, _ in calls] == ["publication"]
    assert calls[0][1] == final_root
    assert "pre" not in [name for name, _ in calls]
    assert "build" not in [name for name, _ in calls]
    assert "artifact" not in [name for name, _ in calls]
    assert not receipt_path.exists()
