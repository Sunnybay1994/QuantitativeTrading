"""Golden actual G8 R1 formal backtest StageRunner publication."""

from __future__ import annotations

import importlib.util
import pickle
from pathlib import Path
from typing import Any

import pytest

import quant.research.m3.backtest_stage as stage_module
from quant.data.m3_release import platform_supports_renameat2_noreplace
from quant.research.m3.backtest_stage import run_formal_backtest_stage
from quant.research.m3.orchestration import M3StageRunnerError

_UNIT_SPEC = importlib.util.spec_from_file_location(
    "m3_g8_unit_support_for_golden",
    Path(__file__).parents[1]
    / "unit"
    / "test_m3_g8_r1_formal_backtest_stage.py",
)
assert _UNIT_SPEC is not None and _UNIT_SPEC.loader is not None
_UNIT = importlib.util.module_from_spec(_UNIT_SPEC)
_UNIT_SPEC.loader.exec_module(_UNIT)


@pytest.mark.skipif(
    not platform_supports_renameat2_noreplace(),
    reason="host lacks atomic directory no-replace publication",
)
def test_actual_publish_resume_noresume_and_orphan_have_fresh_call_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _UNIT._case(tmp_path, monkeypatch)
    calls: list[tuple[str, Path]] = []
    actual_build = stage_module.build_backtest_artifact
    actual_pre = stage_module.verify_backtest_build_output
    actual_final = stage_module.verify_backtest_artifact

    def build(**kwargs: Any) -> Any:
        calls.append(("build", kwargs["output_root"]))
        return actual_build(**kwargs)

    def pre(**kwargs: Any) -> Any:
        calls.append(("pre", kwargs["root"]))
        return actual_pre(**kwargs)

    def final(**kwargs: Any) -> Any:
        calls.append(("final", kwargs["root"]))
        return actual_final(**kwargs)

    monkeypatch.setattr(stage_module, "build_backtest_artifact", build)
    monkeypatch.setattr(stage_module, "_ORIGINAL_BUILD_BACKTEST_ARTIFACT", build)
    monkeypatch.setattr(stage_module, "verify_backtest_build_output", pre)
    monkeypatch.setattr(stage_module, "verify_backtest_artifact", final)

    result = run_formal_backtest_stage(
        stage_root=case["stage_root"],
        **case["kwargs"],
        artifact_roots=case["roots"],
    )
    assert [name for name, _ in calls] == ["build"]
    assert calls[0][1].parent == case["stage_root"] / ".stage-tmp"
    assert result.reused is False
    assert result.verified.root == result.final_root
    assert result.receipt.stage == "backtest"
    assert result.receipt.scope == "WORK"
    assert len(result.receipt.inputs) == 21
    assert len(result.receipt.outputs) == 29
    assert {
        path.relative_to(result.final_root).as_posix()
        for path in result.final_root.rglob("*")
        if path.is_file()
    } == set(stage_module.backtest_artifact_output_relative_paths())
    with pytest.raises(TypeError, match="M3_FORMAL_BACKTEST_STAGE_INVALID"):
        pickle.dumps(result)

    calls.clear()
    case["calls"].clear()
    resumed = run_formal_backtest_stage(
        stage_root=case["stage_root"],
        **case["kwargs"],
        artifact_roots=case["roots"],
    )
    assert [name for name, _ in calls] == ["pre", "final"]
    assert resumed.reused is True
    assert resumed.final_root == result.final_root
    assert [name for name, _ in case["calls"]].count("g7f-plan") == 2
    assert [name for name, _ in case["calls"]].count("g7f-facts") == 2
    assert [name for name, _ in case["calls"]].count("g7e-plan") == 2

    calls.clear()
    case["calls"].clear()
    with pytest.raises(M3StageRunnerError) as caught:
        run_formal_backtest_stage(
            stage_root=case["stage_root"],
            **case["kwargs"],
            artifact_roots=case["roots"],
            resume=False,
        )
    assert caught.value.code == "STAGE_ALREADY_COMPLETE"
    assert [name for name, _ in calls] == ["pre"]
    assert [name for name, _ in case["calls"]].count("g7f-plan") == 1
    assert [name for name, _ in case["calls"]].count("g7f-facts") == 1
    assert [name for name, _ in case["calls"]].count("g7e-plan") == 1

    result.receipt_path.unlink()
    calls.clear()
    case["calls"].clear()
    orphan = run_formal_backtest_stage(
        stage_root=case["stage_root"],
        **case["kwargs"],
        artifact_roots=case["roots"],
    )
    assert [name for name, _ in calls] == ["pre", "build"]
    assert orphan.reused is True
    assert orphan.final_root == result.final_root
    assert [name for name, _ in case["calls"]].count("g7f-plan") == 2
    assert [name for name, _ in case["calls"]].count("g7f-facts") == 2
    assert [name for name, _ in case["calls"]].count("g7e-plan") == 2

    def hostile_final(**kwargs: Any) -> Any:
        calls.append(("final", kwargs["root"]))
        raise RuntimeError("TOKEN=secret SQL=select PID=123 C:\\private")

    calls.clear()
    case["calls"].clear()
    monkeypatch.setattr(
        stage_module,
        "verify_backtest_artifact",
        hostile_final,
    )
    with pytest.raises(M3StageRunnerError) as caught:
        run_formal_backtest_stage(
            stage_root=case["stage_root"],
            **case["kwargs"],
            artifact_roots=case["roots"],
        )
    assert caught.value.code == "STAGE_RECOVERY_CONFLICT"
    assert str(caught.value) == "STAGE_RECOVERY_CONFLICT"
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert [name for name, _ in calls] == ["pre", "final"]
    assert [name for name, _ in case["calls"]].count("g7f-plan") == 1
    assert [name for name, _ in case["calls"]].count("g7f-facts") == 1
    assert [name for name, _ in case["calls"]].count("g7e-plan") == 1
