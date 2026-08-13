"""Focused G8 R1 formal backtest wave contract tests."""

from __future__ import annotations

import importlib.util
import os
import shutil
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

import quant.backtest.a_share_reporting as reporting_module
import quant.backtest.a_share_simulator as simulator_module
import quant.data.m3_release as release_module
from quant.backtest import (
    backtest_artifact_input_paths,
    backtest_artifact_output_relative_paths,
)
from quant.backtest.a_share_reporting import (
    BacktestArtifactFreshVerificationContext,
    BacktestArtifactUpstreamPaths,
    FormalBacktestArtifactUpstreamPaths,
)
from quant.data.m3_release import (
    G1Release,
    VerifiedG1Release,
    platform_supports_renameat2_noreplace,
)
from quant.research.m3.backtest_stage import (
    FormalBacktestStageResult,
    make_formal_backtest_run_plan,
    run_formal_backtest_stage,
)
from quant.research.m3.orchestration import (
    BACKTEST_STAGE_SPEC,
    ExternalInput,
    M3StageRunnerError,
    StageRunner,
    StaticDirectoryPublication,
)
from quant.research.m3.run_state import compute_work_key

_G7F_SPEC = importlib.util.spec_from_file_location(
    "m3_g8_g7f_support",
    Path(__file__).with_name("test_m3_g7f_formal_backtest_artifact.py"),
)
assert _G7F_SPEC is not None and _G7F_SPEC.loader is not None
_G7F = importlib.util.module_from_spec(_G7F_SPEC)
_G7F_SPEC.loader.exec_module(_G7F)


def _case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    case = _G7F._formal_case(tmp_path, monkeypatch)
    kwargs = dict(case["kwargs"])
    kwargs.pop("artifact_roots")
    target = kwargs["target"]
    plan = kwargs["plan"]
    experiment = kwargs["experiment"]
    work_key = compute_work_key(
        experiment_key=experiment.manifest.experiment_key,
        fold=target.manifest.fold,
        horizon=target.manifest.horizon_sessions,
    )
    target = replace(
        target,
        manifest=replace(target.manifest, work_key=work_key),
    )
    plan = replace(
        plan,
        manifest=replace(plan.manifest, work_key=work_key),
    )
    facts_context = replace(
        kwargs["fresh_context"].facts_fresh_context,
        target=target,
    )
    fresh_context = replace(
        kwargs["fresh_context"],
        facts_fresh_context=facts_context,
    )
    kwargs.update(target=target, plan=plan, fresh_context=fresh_context)
    calls = cast(list[tuple[str, object]], case["calls"])
    calls.clear()

    def fresh_plan(**values: Any) -> Any:
        calls.append(("g7f-plan", values))
        return plan

    def fresh_facts(**values: Any) -> Any:
        calls.append(("g7f-facts", values))
        return case["g7e"]["facts"]

    def g7e_plan(**values: Any) -> Any:
        calls.append(("g7e-plan", values))
        return plan

    monkeypatch.setattr(
        reporting_module, "verify_backtest_plan_artifact", fresh_plan
    )
    monkeypatch.setattr(
        reporting_module, "load_verified_a_share_market_facts", fresh_facts
    )
    monkeypatch.setattr(
        simulator_module, "verify_backtest_plan_artifact", g7e_plan
    )
    case["kwargs"] = kwargs
    case["calls"] = calls
    stage_root = tmp_path / "stage"
    stage_root.mkdir()
    case["stage_root"] = stage_root
    return case


def test_formal_plan_resolves_exact_21_input_single_work_node(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _case(tmp_path, monkeypatch)
    kwargs = case["kwargs"]
    plan = make_formal_backtest_run_plan(
        **kwargs,
        artifact_roots=case["roots"],
    )
    assert plan.continuation == "WORK"
    assert len(plan.nodes) == 1
    node = plan.nodes[0]
    target = kwargs["target"]
    assert node.node_id == (
        f"backtest.{target.manifest.fold}.h{target.manifest.horizon_sessions}"
    )
    assert node.spec_name == "backtest"
    assert node.scope == "WORK"
    assert node.scope_key == target.manifest.work_key
    assert node.fold == target.manifest.fold
    assert node.horizon == target.manifest.horizon_sessions
    assert node.dependencies == ()
    assert len(node.inputs) == 21
    assert all(type(item) is ExternalInput for item in node.inputs)
    digests = tuple(cast(ExternalInput, item).artifact for item in node.inputs)
    assert digests == tuple(
        sorted(digests, key=lambda item: (item.root_alias, item.relative_path))
    )
    assert node.publication == StaticDirectoryPublication(
        f"work/{target.manifest.work_key}/backtest"
    )
    assert node.receipt_path == (
        f"receipts/backtest/{target.manifest.work_key}.json"
    )
    assert node.output_specs == BACKTEST_STAGE_SPEC.outputs
    assert not tuple(case["stage_root"].iterdir())


def test_public_21_29_ssot_and_root_mapping_order_are_stable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _case(tmp_path, monkeypatch)
    kwargs = case["kwargs"]
    paths = backtest_artifact_input_paths(
        target=kwargs["target"],
        plan=kwargs["plan"],
        release=kwargs["release"],
        experiment=kwargs["experiment"],
        fresh_context=kwargs["fresh_context"],
    )
    assert len(paths) == len(set(paths)) == 21
    assert all(path.is_absolute() and path.is_file() for path in paths)
    outputs = backtest_artifact_output_relative_paths()
    assert len(outputs) == len(set(outputs)) == 29
    assert outputs == tuple(sorted(outputs))
    extra_root = tmp_path.parent / f"{tmp_path.name}-extra-root"
    extra_root.mkdir()
    first = make_formal_backtest_run_plan(
        **kwargs,
        artifact_roots={"extra": extra_root, "test": tmp_path},
    )
    second = make_formal_backtest_run_plan(
        **kwargs,
        artifact_roots={"test": tmp_path, "extra": extra_root},
    )
    assert first == second


def test_plan_rejects_stale_identity_and_nested_roots_without_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _case(tmp_path, monkeypatch)
    kwargs = case["kwargs"]
    stale = replace(
        kwargs["plan"],
        manifest=replace(kwargs["plan"].manifest, work_key="f" * 64),
    )
    with pytest.raises(M3StageRunnerError) as caught:
        make_formal_backtest_run_plan(
            **{**kwargs, "plan": stale},
            artifact_roots=case["roots"],
        )
    assert str(caught.value) == "STAGE_INPUT_INVALID"
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    nested = tmp_path / "upstream"
    with pytest.raises(M3StageRunnerError, match="STAGE_INPUT_INVALID"):
        make_formal_backtest_run_plan(
            **kwargs,
            artifact_roots={"outer": tmp_path, "inner": nested},
        )
    assert not tuple(case["stage_root"].iterdir())


def test_formal_stage_result_is_not_serializable_or_nominally_forgeable() -> None:
    with pytest.raises(ValueError, match="M3_FORMAL_BACKTEST_STAGE_INVALID"):
        FormalBacktestStageResult(
            final_root=cast(Any, "root"),
            receipt_path=cast(Any, "receipt"),
            verified=cast(Any, object()),
            receipt=cast(Any, object()),
            reused=False,
    )
    assert "__reduce__" in FormalBacktestStageResult.__dict__


def test_build_and_closure_hostile_failures_are_stable_and_cleaned(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _case(tmp_path, monkeypatch)

    def hostile_build(**_kwargs: Any) -> None:
        raise RuntimeError("TOKEN=secret SQL=select PID=123 C:\\private")

    monkeypatch.setattr(
        "quant.research.m3.backtest_stage.build_backtest_artifact",
        hostile_build,
    )
    with pytest.raises(M3StageRunnerError) as caught:
        run_formal_backtest_stage(
            stage_root=case["stage_root"],
            **case["kwargs"],
            artifact_roots=case["roots"],
        )
    assert caught.value.code == "STAGE_BUILD_FAILED"
    assert str(caught.value) == "STAGE_BUILD_FAILED"
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert not tuple(case["stage_root"].rglob("*.json"))

    def minimal_build(*, output_root: Path, **_kwargs: Any) -> None:
        for relative in backtest_artifact_output_relative_paths():
            path = output_root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"invalid-but-closed")

    def hostile_closure(**_kwargs: Any) -> None:
        raise RuntimeError("TOKEN=secret SQL=select PID=123 C:\\private")

    monkeypatch.setattr(
        "quant.research.m3.backtest_stage.build_backtest_artifact",
        minimal_build,
    )
    monkeypatch.setattr(
        "quant.research.m3.backtest_stage.verify_backtest_build_output",
        hostile_closure,
    )
    with pytest.raises(M3StageRunnerError) as caught:
        run_formal_backtest_stage(
            stage_root=case["stage_root"],
            **case["kwargs"],
            artifact_roots=case["roots"],
        )
    assert caught.value.code == "STAGE_OUTPUT_INVALID"
    assert str(caught.value) == "STAGE_OUTPUT_INVALID"
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert not tuple(case["stage_root"].rglob("*.json"))


def _rewrite_same_bytes_new_inode(path: Path) -> bool:
    payload = path.read_bytes()
    before = os.lstat(path)
    path.unlink()
    path.write_bytes(payload)
    after = os.lstat(path)
    return (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino)


def _rewrite_until_entity_drifts(path: Path) -> bool:
    before = reporting_module._formal_entity(path, directory=False)
    if not _rewrite_same_bytes_new_inode(path):
        # Some DrvFS remounts reuse inode; still compare full entity snapshot.
        after_same = reporting_module._formal_entity(path, directory=False)
        if after_same != before:
            return True
        return False
    after = reporting_module._formal_entity(path, directory=False)
    return after != before


def _assert_stage_fail_clean(
    *,
    stage_root: Path,
    code: str,
    caught: pytest.ExceptionInfo[M3StageRunnerError],
) -> None:
    assert caught.value.code == code
    assert str(caught.value) == code
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    receipts = stage_root / "receipts"
    if receipts.exists():
        assert not tuple(receipts.rglob("*.json"))
    tmp = stage_root / ".stage-tmp"
    if tmp.exists():
        assert not tuple(path for path in tmp.rglob("*") if path.is_file())


def test_r2_rejects_old_context_four_path_subclass_and_duck(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _case(tmp_path, monkeypatch)
    kwargs = case["kwargs"]
    release = kwargs["release"]
    paths = kwargs["fresh_context"].upstream_paths
    facts = kwargs["fresh_context"].facts_fresh_context

    development_paths = BacktestArtifactUpstreamPaths(
        target_receipt_path=paths.target_receipt_path,
        plan_receipt_path=paths.plan_receipt_path,
        experiment_receipt_path=paths.experiment_receipt_path,
        g1_receipt_path=release.release.root / "receipt.json",
    )
    with pytest.raises(Exception):
        BacktestArtifactFreshVerificationContext(
            facts_fresh_context=facts,
            upstream_paths=cast(Any, development_paths),
            release=release,
        )

    duck = SimpleNamespace(
        facts_fresh_context=facts,
        upstream_paths=paths,
        release=release,
    )
    with pytest.raises(M3StageRunnerError) as caught:
        make_formal_backtest_run_plan(
            **{**kwargs, "fresh_context": cast(Any, duck)},
            artifact_roots=case["roots"],
        )
    assert caught.value.code == "STAGE_INPUT_INVALID"
    assert caught.value.__cause__ is None and caught.value.__context__ is None

    @dataclass(frozen=True)
    class _SubContext(BacktestArtifactFreshVerificationContext):
        pass

    sub = _SubContext(
        facts_fresh_context=facts,
        upstream_paths=paths,
        release=release,
    )
    assert type(sub) is not BacktestArtifactFreshVerificationContext
    with pytest.raises(M3StageRunnerError) as caught:
        make_formal_backtest_run_plan(
            **{**kwargs, "fresh_context": cast(Any, sub)},
            artifact_roots=case["roots"],
        )
    assert caught.value.code == "STAGE_INPUT_INVALID"

    old_missing_release = SimpleNamespace(
        facts_fresh_context=facts,
        upstream_paths=paths,
    )
    with pytest.raises(M3StageRunnerError) as caught:
        make_formal_backtest_run_plan(
            **{**kwargs, "fresh_context": cast(Any, old_missing_release)},
            artifact_roots=case["roots"],
        )
    assert caught.value.code == "STAGE_INPUT_INVALID"
    assert not tuple(case["stage_root"].iterdir())


def test_r2_21_input_is_quality_and_eight_tables_without_g1_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _case(tmp_path, monkeypatch)
    kwargs = case["kwargs"]
    paths = backtest_artifact_input_paths(
        target=kwargs["target"],
        plan=kwargs["plan"],
        release=kwargs["release"],
        experiment=kwargs["experiment"],
        fresh_context=kwargs["fresh_context"],
    )
    assert len(paths) == 21
    assert paths[11].name == "manifest.json"
    assert paths[12].name == "quality.json"
    assert paths[12] == kwargs["release"].release.quality_path
    assert all(path.name != "receipt.json" for path in paths)
    assert not (kwargs["release"].release.root / "receipt.json").exists()
    market = {
        "bar_1d.parquet",
        "benchmark_bar_1d.parquet",
        "corporate_action_ledger.parquet",
        "corporate_action_reconciliation.parquet",
        "instrument.parquet",
        "price_limit_1d.parquet",
        "suspension_1d.parquet",
        "trade_calendar.parquet",
    }
    assert {path.name for path in paths[13:]} == market
    plan = make_formal_backtest_run_plan(
        **kwargs,
        artifact_roots=case["roots"],
    )
    assert len(plan.nodes[0].inputs) == 21


def test_r2_same_context_copied_root_outer_release_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _case(tmp_path, monkeypatch)
    kwargs = case["kwargs"]
    release = kwargs["release"]
    assert type(release) is VerifiedG1Release
    rid = release.release.release_id
    quality_sha = release.quality_sha256
    copied_root = tmp_path / "copied-g1" / rid
    copied_root.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(release.release.root, copied_root)
    remapped = tuple(
        (name, copied_root / name)
        for name in sorted(release_module._ARTIFACT_PATHS)
    )
    copied = replace(
        release,
        release=G1Release(
            release_id=rid,
            root=copied_root,
            manifest_path=copied_root / "manifest.json",
            quality_path=copied_root / "quality.json",
        ),
        artifact_paths=remapped,
        quality_sha256=quality_sha,
    )
    assert type(copied) is VerifiedG1Release
    with pytest.raises(M3StageRunnerError) as caught:
        make_formal_backtest_run_plan(
            **{**kwargs, "release": copied},
            artifact_roots=case["roots"],
        )
    assert caught.value.code == "STAGE_INPUT_INVALID"
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    with pytest.raises(M3StageRunnerError) as caught:
        run_formal_backtest_stage(
            stage_root=case["stage_root"],
            **{**kwargs, "release": copied},
            artifact_roots=case["roots"],
        )
    _assert_stage_fail_clean(
        stage_root=case["stage_root"],
        code="STAGE_INPUT_INVALID",
        caught=caught,
    )


@pytest.mark.parametrize(
    "window",
    [
        "after_handler_before_temp",
        "after_temp_before_final",
        "after_final_before_receipt",
    ],
)
def test_r2_quality_or_market_inode_replace_windows_fail_before_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    window: str,
) -> None:
    # Post-temp windows need exclusive commit; capability false never reaches mutation.
    if window != "after_handler_before_temp" and (
        not platform_supports_renameat2_noreplace()
    ):
        pytest.skip("exclusive commit unsupported; inode window unreachable")

    case = _case(tmp_path, monkeypatch)
    kwargs = case["kwargs"]
    release = kwargs["release"]
    quality = release.release.quality_path
    market = dict(release.artifact_paths)["bar_1d.parquet"]
    targets = (quality, market)
    import quant.research.m3.backtest_stage as stage_module

    actual_pre = stage_module.verify_backtest_build_output
    pre_calls = {"n": 0}
    mut_calls = {"n": 0}
    entity_guard_calls = {"n": 0}
    base_publish_calls = {"n": 0}

    def _mutate() -> None:
        changed = [_rewrite_until_entity_drifts(path) for path in targets]
        if not any(changed):
            pytest.skip("same-path rewrite did not drift G1 entity snapshot")
        mut_calls["n"] += 1

    def guarded_pre(**values: Any) -> Any:
        pre_calls["n"] += 1
        if window == "after_handler_before_temp" and pre_calls["n"] == 1:
            _mutate()
        if window == "after_temp_before_final" and pre_calls["n"] == 2:
            _mutate()
        result = actual_pre(**values)
        if window == "after_final_before_receipt" and pre_calls["n"] == 2:
            _mutate()
        return result

    guarded_cls = stage_module._EntityGuardedFormalBacktestStageRunner
    actual_entity_publish = guarded_cls._publish_static_receipt
    actual_base_publish = StageRunner._publish_static_receipt

    def counted_entity_publish(self: Any, **values: Any) -> Any:
        entity_guard_calls["n"] += 1
        return actual_entity_publish(self, **values)

    def counted_base_publish(self: Any, **values: Any) -> Any:
        base_publish_calls["n"] += 1
        return actual_base_publish(self, **values)

    monkeypatch.setattr(stage_module, "verify_backtest_build_output", guarded_pre)
    monkeypatch.setattr(guarded_cls, "_publish_static_receipt", counted_entity_publish)
    monkeypatch.setattr(StageRunner, "_publish_static_receipt", counted_base_publish)

    expected_code = (
        "STAGE_OUTPUT_INVALID"
        if window == "after_handler_before_temp"
        else "STAGE_RECOVERY_CONFLICT"
    )
    with pytest.raises(M3StageRunnerError) as caught:
        run_formal_backtest_stage(
            stage_root=case["stage_root"],
            **kwargs,
            artifact_roots=case["roots"],
        )
    assert mut_calls["n"] >= 1
    if window == "after_final_before_receipt":
        assert entity_guard_calls["n"] >= 1
        assert base_publish_calls["n"] == 0
    _assert_stage_fail_clean(
        stage_root=case["stage_root"],
        code=expected_code,
        caught=caught,
    )


def test_r2_new_context_is_new_request_bound_context_drift_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _case(tmp_path, monkeypatch)
    kwargs = case["kwargs"]
    original = kwargs["fresh_context"]
    rebuilt = BacktestArtifactFreshVerificationContext(
        facts_fresh_context=original.facts_fresh_context,
        upstream_paths=original.upstream_paths,
        release=kwargs["release"],
    )
    assert rebuilt is not original
    assert type(rebuilt.upstream_paths) is FormalBacktestArtifactUpstreamPaths
    plan = make_formal_backtest_run_plan(
        **{**kwargs, "fresh_context": rebuilt},
        artifact_roots=case["roots"],
    )
    assert len(plan.nodes[0].inputs) == 21

    release = kwargs["release"]
    rid = release.release.release_id
    copied_root = tmp_path / "drift-g1" / rid
    copied_root.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(release.release.root, copied_root)
    drifted = replace(
        release,
        release=G1Release(
            release_id=rid,
            root=copied_root,
            manifest_path=copied_root / "manifest.json",
            quality_path=copied_root / "quality.json",
        ),
        artifact_paths=tuple(
            (name, copied_root / name)
            for name in sorted(release_module._ARTIFACT_PATHS)
        ),
        quality_sha256=release.quality_sha256,
    )
    import quant.research.m3.backtest_stage as stage_module

    actual_pre = stage_module.verify_backtest_build_output
    pre_calls = {"n": 0}

    def mutate_bound_context(**values: Any) -> Any:
        pre_calls["n"] += 1
        if pre_calls["n"] == 1:
            object.__setattr__(kwargs["fresh_context"], "release", drifted)
        return actual_pre(**values)

    monkeypatch.setattr(
        stage_module, "verify_backtest_build_output", mutate_bound_context
    )
    with pytest.raises(M3StageRunnerError) as caught:
        run_formal_backtest_stage(
            stage_root=case["stage_root"],
            **kwargs,
            artifact_roots=case["roots"],
        )
    _assert_stage_fail_clean(
        stage_root=case["stage_root"],
        code="STAGE_OUTPUT_INVALID",
        caught=caught,
    )
