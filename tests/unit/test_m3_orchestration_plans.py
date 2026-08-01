"""Adversarial G8A registry and continuation-plan contract tests."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import quant.research.m3.orchestration as orchestration
from quant.research.m3.config import LoadedM3Config
from quant.research.m3.development_example import (
    VerifiedDevelopmentExampleExperimentIdentity,
    VerifiedDevelopmentExampleFoldPlanArtifact,
    VerifiedDevelopmentExampleLabelArtifact,
    VerifiedDevelopmentExampleLabelReconciliationArtifact,
)
from quant.research.m3.orchestration import (
    BACKTEST_PLAN_STAGE_SPEC,
    BACKTEST_STAGE_SPEC,
    EVALUATION_STAGE_SPEC,
    PROVIDER_STAGE_SPEC,
    PROVIDER_VALIDATION_STAGE_SPEC,
    STAGE_SPEC_REGISTRY,
    TARGETS_STAGE_SPEC,
    TRACKING_STAGE_SPEC,
    ExternalInput,
    RunPlan,
    StageNode,
    StageOutputInput,
    StaticDirectoryPublication,
    make_work_run_plan,
)
from quant.research.m3.run_state import ArtifactDigest, compute_work_key

_KEY = "0" * 64


def _external() -> ExternalInput:
    return ExternalInput(ArtifactDigest("fixture", "input.json", 2, "1" * 64))


def _node(
    *, node_id: str, validation_path: str = "provider_manifest.json",
    final_directory: str = "providers/one",
) -> StageNode:
    if node_id == "provider":
        return StageNode(
            node_id="provider", spec_name="provider", scope="PROVIDER",
            scope_key=_KEY, fold=None, horizon=None, dependencies=(),
            inputs=(_external(),),
            publication=StaticDirectoryPublication(final_directory),
            output_specs=PROVIDER_STAGE_SPEC.outputs,
            receipt_path="receipts/provider/one.json",
        )
    return StageNode(
        node_id="provider-validation", spec_name="provider-validation",
        scope="PROVIDER", scope_key=_KEY, fold=None, horizon=None,
        dependencies=("provider",),
        inputs=(StageOutputInput("provider", "stage", validation_path),),
        publication=StaticDirectoryPublication(final_directory),
        output_specs=PROVIDER_VALIDATION_STAGE_SPEC.outputs,
        receipt_path="receipts/provider-validation/one.json",
    )


def test_registry_is_complete_and_tree_outputs_have_closure_manifests() -> None:
    assert set(STAGE_SPEC_REGISTRY) == {
        "snapshot", "development-snapshot", "provider", "provider-validation",
        "experiment", "labels", "label-reconciliation", "folds", "features",
        "alignment", "train", "predictions", "evaluation", "targets",
        "backtest_plan", "backtest", "tracking", "summary",
    }
    assert all(
        output.closure_manifest is not None
        for spec in STAGE_SPEC_REGISTRY.values()
        for output in spec.outputs
        if output.kind == "TREE"
    )


def test_unresolved_continuations_have_no_surrogate_plan_builder() -> None:
    assert not hasattr(orchestration, "_plan_key")
    assert not hasattr(orchestration, "make_provider_run_plan")
    assert not hasattr(orchestration, "make_experiment_run_plan")
    source = Path(orchestration.__file__).read_text(encoding="utf-8")
    assert "provider-plan-v1" not in source
    assert "experiment-plan-v1" not in source


def _unchecked(cls: type[object], **values: object) -> object:
    value = object.__new__(cls)
    for name, item in values.items():
        object.__setattr__(value, name, item)
    return value


def _config() -> LoadedM3Config:
    digest = "2" * 64
    return LoadedM3Config(
        document={"labels": {"horizons_sessions": (5, 10)}},
        config_version="test", full_config_sha256=digest,
        g1_config_sha256=digest, snapshot_config_sha256=digest,
        provider_config_sha256=digest, scientific_config_sha256=digest,
        provider_validation_config_sha256=digest,
        label_reconciliation_config_sha256=digest,
        acceptance_config_sha256=digest, canonical_tracking_uri="test",
        tracking_target_key=digest,
    )


def test_work_scope_keys_only_use_verified_experiment_and_work_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    experiment_key = "3" * 64
    root = Path("unused")
    experiment = _unchecked(
        VerifiedDevelopmentExampleExperimentIdentity,
        manifest=SimpleNamespace(experiment_key=experiment_key), root=root,
    )
    folds = _unchecked(
        VerifiedDevelopmentExampleFoldPlanArtifact,
        manifest=SimpleNamespace(folds=(SimpleNamespace(name="fold_001"),)),
        root=root,
    )
    labels = tuple(
        _unchecked(
            VerifiedDevelopmentExampleLabelArtifact,
            manifest=SimpleNamespace(horizon_sessions=horizon), root=root,
        )
        for horizon in (5, 10)
    )
    reconciliations = tuple(
        _unchecked(
            VerifiedDevelopmentExampleLabelReconciliationArtifact,
            summary=SimpleNamespace(horizon_sessions=horizon), root=root,
        )
        for horizon in (5, 10)
    )
    monkeypatch.setattr(
        orchestration, "_external_files", lambda **_kwargs: (_external(),)
    )

    plan = make_work_run_plan(
        config=_config(),
        experiment=experiment,  # type: ignore[arg-type]
        folds=folds,  # type: ignore[arg-type]
        labels=labels,  # type: ignore[arg-type]
        reconciliations=reconciliations,  # type: ignore[arg-type]
    )

    for node in plan.nodes:
        if node.spec_name == "features":
            assert node.scope_key == experiment_key
        else:
            assert node.fold == "fold_001"
            assert node.horizon in {5, 10}
            assert node.scope_key == compute_work_key(
                experiment_key=experiment_key,
                fold=node.fold,
                horizon=node.horizon,
            )


def test_g7_and_tracking_registry_preserve_frozen_work_order() -> None:
    assert TARGETS_STAGE_SPEC.dependencies == ("evaluation",)
    assert BACKTEST_PLAN_STAGE_SPEC.dependencies == ("targets",)
    assert BACKTEST_STAGE_SPEC.dependencies == ("backtest_plan",)
    assert TRACKING_STAGE_SPEC.dependencies == ("backtest", "evaluation")
    assert EVALUATION_STAGE_SPEC.dependencies == ("predictions",)


def test_run_plan_accepts_covered_stage_output() -> None:
    plan = RunPlan(
        "PROVIDER",
        (
            _node(node_id="provider"),
            _node(node_id="provider-validation", final_directory="validations/one"),
        ),
    )
    assert tuple(node.node_id for node in plan.nodes) == (
        "provider", "provider-validation",
    )


def test_run_plan_rejects_uncovered_stage_output() -> None:
    with pytest.raises(ValueError, match="producer-covered"):
        RunPlan(
            "PROVIDER",
            (
                _node(node_id="provider"),
                _node(
                    node_id="provider-validation", validation_path="missing.json",
                    final_directory="validations/one",
                ),
            ),
        )


def test_run_plan_rejects_nested_static_publications() -> None:
    with pytest.raises(ValueError, match="publication conflict"):
        RunPlan(
            "PROVIDER",
            (
                _node(node_id="provider"),
                _node(
                    node_id="provider-validation",
                    final_directory="providers/one/validation",
                ),
            ),
        )
