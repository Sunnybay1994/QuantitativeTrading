"""Golden actual G8D-F1 formal tracking StageRunner publication."""

from __future__ import annotations

import importlib.util
import pickle
from pathlib import Path
from typing import Any

import pytest

import quant.research.m3.tracking as tracking_module
import quant.research.m3.tracking_stage as stage_module
from quant.data.m3_release import platform_supports_renameat2_noreplace
from quant.research.m3.orchestration import M3StageRunnerError
from quant.research.m3.tracking_stage import run_formal_tracking_stage

_UNIT_SPEC = importlib.util.spec_from_file_location(
    "m3_g8d_unit_support_for_golden",
    Path(__file__).parents[1]
    / "unit"
    / "test_m3_g8d_f1_formal_tracking_stage.py",
)
assert _UNIT_SPEC is not None and _UNIT_SPEC.loader is not None
_UNIT = importlib.util.module_from_spec(_UNIT_SPEC)
_UNIT_SPEC.loader.exec_module(_UNIT)


@pytest.fixture(scope="module")
def _module_artifacts(tmp_path_factory: pytest.TempPathFactory) -> dict:
    from _pytest.monkeypatch import MonkeyPatch

    root = tmp_path_factory.mktemp("g8d-f1-golden-shared")
    monkeypatch = MonkeyPatch()
    try:
        return _UNIT._build_artifacts(root, monkeypatch)
    finally:
        monkeypatch.undo()


@pytest.fixture
def case(
    _module_artifacts: dict,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict:
    stage_root = _module_artifacts["default_stage_root"].parent / f"stage-{tmp_path.name}"
    return _UNIT._attach_runtime(
        _module_artifacts,
        stage_root=stage_root,
        monkeypatch=monkeypatch,
    )


@pytest.mark.skipif(
    not platform_supports_renameat2_noreplace(),
    reason="host lacks atomic directory no-replace publication",
)
def test_actual_publish_resume_noresume_orphan_and_remote_counts(
    case: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = case["client"]
    calls: list[tuple[str, Path | None]] = []
    actual_remote = stage_module.register_remote_tracking_run
    actual_closure = stage_module._verify_tracking_local_closure

    def remote(**kwargs: Any) -> Any:
        calls.append(("remote", kwargs["lock_root"]))
        return actual_remote(**kwargs)

    def closure(*, root: Path, expected_request: Any) -> None:
        calls.append(("closure", root))
        return actual_closure(root=root, expected_request=expected_request)

    monkeypatch.setattr(stage_module, "register_remote_tracking_run", remote)
    monkeypatch.setattr(stage_module, "_verify_tracking_local_closure", closure)

    result = run_formal_tracking_stage(**_UNIT._run_kwargs(case))
    assert [name for name, _ in case["verifier_calls"]] == [
        "evaluation",
        "backtest",
    ]
    assert [name for name, _ in calls] == [
        "remote",
        "closure",
        "closure",
        "closure",
    ]
    assert calls[0][1] is not None
    assert ".tracking-locks" in calls[0][1].as_posix()
    assert calls[1][1] is not None and calls[1][1].parent == case["stage_root"] / ".stage-tmp"
    assert calls[2][1] == result.final_root
    assert calls[3][1] == result.final_root
    assert result.reused is False
    assert result.receipt.stage == "tracking"
    assert result.receipt.scope == "WORK"
    assert len(result.receipt.inputs) == 34
    assert len(result.receipt.outputs) == 2
    assert {
        path.relative_to(result.final_root).as_posix()
        for path in result.final_root.rglob("*")
        if path.is_file()
    } == {"tracking_marker.json", "tracking_request.json"}
    assert not (result.final_root / ".tracking-locks").exists()
    assert client.create_calls == 1
    with pytest.raises(TypeError, match="M3_FORMAL_TRACKING_STAGE_INVALID"):
        pickle.dumps(result)

    calls.clear()
    case["verifier_calls"].clear()
    find_before = client.find_calls
    create_before = client.create_calls
    resumed = run_formal_tracking_stage(**_UNIT._run_kwargs(case))
    assert [name for name, _ in case["verifier_calls"]] == [
        "evaluation",
        "backtest",
    ]
    assert [name for name, _ in calls] == ["closure", "closure"]
    assert resumed.reused is True
    assert resumed.final_root == result.final_root
    assert client.find_calls == find_before
    assert client.create_calls == create_before

    calls.clear()
    case["verifier_calls"].clear()
    with pytest.raises(M3StageRunnerError) as caught:
        run_formal_tracking_stage(**_UNIT._run_kwargs(case), resume=False)
    assert caught.value.code == "STAGE_ALREADY_COMPLETE"
    assert [name for name, _ in calls] == ["closure"]
    assert [name for name, _ in case["verifier_calls"]] == [
        "evaluation",
        "backtest",
    ]

    result.receipt_path.unlink()
    calls.clear()
    case["verifier_calls"].clear()
    find_before = client.find_calls
    create_before = client.create_calls
    orphan = run_formal_tracking_stage(**_UNIT._run_kwargs(case))
    assert [name for name, _ in calls] == [
        "closure",
        "remote",
        "closure",
        "closure",
        "closure",
    ]
    assert orphan.reused is True
    assert orphan.final_root == result.final_root
    assert orphan.marker.mlflow_run_id == result.marker.mlflow_run_id
    assert client.create_calls == create_before
    assert client.find_calls > find_before
    assert [name for name, _ in case["verifier_calls"]] == [
        "evaluation",
        "backtest",
    ]

    def hostile_final(*, root: Path, expected_request: Any) -> None:
        calls.append(("closure", root))
        if root == result.final_root and sum(
            1 for name, path in calls if name == "closure" and path == root
        ) > 1:
            raise RuntimeError("TOKEN=secret SQL=select PID=123 C:\\private")
        return actual_closure(root=root, expected_request=expected_request)

    calls.clear()
    case["verifier_calls"].clear()
    monkeypatch.setattr(stage_module, "_verify_tracking_local_closure", hostile_final)
    with pytest.raises(M3StageRunnerError) as caught:
        run_formal_tracking_stage(**_UNIT._run_kwargs(case))
    assert caught.value.code == "STAGE_RECOVERY_CONFLICT"
    assert str(caught.value) == "STAGE_RECOVERY_CONFLICT"
    assert caught.value.__cause__ is None and caught.value.__context__ is None


def test_fake_remote_contract_without_atomic_publish(
    case: dict,
) -> None:
    """Always-run fake remote/contract checks even when actual publish is skipped."""
    request = tracking_module.build_formal_tracking_request(
        evaluation=case["evaluation"],
        backtest=case["backtest"],
        config=case["config"],
        fresh_context=case["fresh_context"],
        artifact_roots=case["roots"],
    )
    assert len(request.params) == 22
    assert len(request.artifacts) == 11
    assert dict(request.tags)["release_kind"] == "formal"
    plan = stage_module.make_formal_tracking_run_plan(
        evaluation=case["evaluation"],
        backtest=case["backtest"],
        config=case["config"],
        fresh_context=case["fresh_context"],
        artifact_roots=case["roots"],
    )
    assert len(plan.nodes[0].inputs) == 34
    if platform_supports_renameat2_noreplace():
        return
    with pytest.raises(M3StageRunnerError):
        run_formal_tracking_stage(**_UNIT._run_kwargs(case))
