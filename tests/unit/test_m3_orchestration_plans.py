"""Adversarial G8A registry and continuation-plan contract tests."""

from __future__ import annotations

import inspect
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

import quant.research.m3.orchestration as orchestration
from quant.research.m3.config import LoadedM3Config
from quant.research.m3.contracts import (
    LabelReconciliationSpec,
    ProviderValidationSpec,
)
from quant.research.m3.development_example import (
    VerifiedDevelopmentExampleEvaluationArtifact,
    VerifiedDevelopmentExampleExperimentIdentity,
    VerifiedDevelopmentExampleFoldPlanArtifact,
    VerifiedDevelopmentExampleG1Release,
    VerifiedDevelopmentExampleLabelArtifact,
    VerifiedDevelopmentExampleLabelReconciliationArtifact,
    VerifiedDevelopmentExampleProviderArtifact,
    VerifiedDevelopmentExampleProviderValidationArtifact,
    VerifiedDevelopmentExampleSnapshotArtifact,
)
from quant.research.m3.evaluate import verify_development_example_research_summary_artifact
from quant.research.m3.orchestration import (
    BACKTEST_PLAN_STAGE_SPEC,
    BACKTEST_STAGE_SPEC,
    EVALUATION_STAGE_SPEC,
    PROVIDER_STAGE_SPEC,
    PROVIDER_VALIDATION_STAGE_SPEC,
    STAGE_SPEC_REGISTRY,
    SUMMARY_STAGE_SPEC,
    TARGETS_STAGE_SPEC,
    TRACKING_STAGE_SPEC,
    ExternalInput,
    RunPlan,
    StageNode,
    StageOutputInput,
    StaticDirectoryPublication,
    make_experiment_artifact_run_plan,
    make_label_reconciliation_run_plan,
    make_provider_validation_run_plan,
    make_summary_run_plan,
    make_work_run_plan,
)
from quant.research.m3.run_state import ArtifactDigest, compute_work_key

_KEY = "0" * 64
_EXAMPLE = "development-example-plans-v1"
_SHA = "1" * 64

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
        "development-provider", "development-provider-validation",
        "experiment-identity", "development-experiment-identity",
        "labels", "development-labels", "label-reconciliation",
        "development-label-reconciliation", "folds", "development-folds",
        "features", "development-features", "alignment",
        "development-alignment", "train", "development-model", "predictions",
        "development-predictions", "evaluation", "development-evaluation",
        "targets", "development-targets", "backtest_plan",
        "development-backtest-plan", "backtest", "development-backtest",
        "tracking", "development-tracking", "research-summary",
        "development-research-summary", "quality", "reproducibility",
        "readiness-evidence", "acceptance",
    }
    assert all(
        output.closure_manifest is not None
        for spec in STAGE_SPEC_REGISTRY.values()
        for output in spec.outputs
        if output.kind == "TREE"
    )


def test_identity_resolved_continuations_have_no_surrogate_plan_hash() -> None:
    assert not hasattr(orchestration, "_plan_key")
    assert hasattr(orchestration, "make_provider_materialization_run_plan")
    assert hasattr(orchestration, "make_provider_validation_run_plan")
    assert hasattr(orchestration, "make_experiment_identity_wave_plan")
    assert hasattr(orchestration, "make_experiment_artifact_run_plan")
    assert hasattr(orchestration, "make_label_reconciliation_run_plan")
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


def _evaluation(
    *, fold: str, horizon: int, example_id: str = "development-example-plans-v1",
    experiment_key: str = "3" * 64,
) -> VerifiedDevelopmentExampleEvaluationArtifact:
    return cast(VerifiedDevelopmentExampleEvaluationArtifact, _unchecked(
        VerifiedDevelopmentExampleEvaluationArtifact,
        example_id=example_id,
        manifest=SimpleNamespace(
            experiment_key=experiment_key,
            work_key=compute_work_key(
                experiment_key=experiment_key, fold=fold, horizon=horizon,
            ),
            fold=fold,
            horizon_sessions=horizon,
            model="lightgbm",
            model_version="v1",
            scientific_config_sha256="2" * 64,
            fold_plan_manifest_sha256="4" * 64,
            label_manifest_sha256=("5" if horizon == 5 else "6") * 64,
        ),
        root=Path("unused"),
    ))


def test_work_scope_keys_only_use_verified_experiment_and_work_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    experiment_key = "3" * 64
    root = Path("unused")
    experiment = _unchecked(
        VerifiedDevelopmentExampleExperimentIdentity,
        example_id="development-example-plans-v1",
        manifest=SimpleNamespace(
            experiment_key=experiment_key,
            snapshot_id="4" * 64,
            snapshot_manifest_sha256="5" * 64,
            scientific_config_sha256="2" * 64,
        ),
        manifest_sha256="6" * 64,
        root=root,
    )
    folds = _unchecked(
        VerifiedDevelopmentExampleFoldPlanArtifact,
        example_id="development-example-plans-v1",
        manifest=SimpleNamespace(
            experiment_key=experiment_key,
            experiment_manifest_sha256="6" * 64,
            snapshot_id="4" * 64,
            snapshot_manifest_sha256="5" * 64,
            scientific_config_sha256="2" * 64,
            folds=(SimpleNamespace(name="fold_001"),),
        ),
        root=root,
    )
    labels = tuple(
        _unchecked(
            VerifiedDevelopmentExampleLabelArtifact,
            example_id="development-example-plans-v1",
            manifest=SimpleNamespace(
                experiment_key=experiment_key,
                experiment_manifest_sha256="6" * 64,
                snapshot_id="4" * 64,
                snapshot_manifest_sha256="5" * 64,
                g1_release_id="7" * 64,
                g1_release_manifest_sha256="8" * 64,
                horizon_sessions=horizon,
            ),
            manifest_sha256=("9" if horizon == 5 else "a") * 64,
            root=root,
        )
        for horizon in (5, 10)
    )
    reconciliations = tuple(
        _unchecked(
            VerifiedDevelopmentExampleLabelReconciliationArtifact,
            example_id="development-example-plans-v1",
            summary=SimpleNamespace(
                experiment_key=experiment_key,
                horizon_sessions=horizon,
                label_manifest_sha256=("9" if horizon == 5 else "a") * 64,
                provider_validation_receipt_sha256="b" * 64,
                passed=True,
            ),
            root=root,
        )
        for horizon in (5, 10)
    )
    monkeypatch.setattr(
        orchestration, "_external_files", lambda **_kwargs: (_external(),)
    )
    monkeypatch.setattr(
        orchestration,
        "_fold_boundary_inputs",
        lambda *_args, artifact_roots=None: (_external(),),
    )
    monkeypatch.setattr(
        orchestration,
        "_experiment_boundary_inputs",
        lambda *_args, artifact_roots=None: (_external(),),
    )
    monkeypatch.setattr(
        orchestration,
        "_label_boundary_inputs",
        lambda *_args, artifact_roots=None: (_external(),),
    )
    monkeypatch.setattr(
        orchestration,
        "_reconciliation_boundary_inputs",
        lambda *_args, artifact_roots=None: (_external(),),
    )

    plan = make_work_run_plan(
        config=_config(),
        experiment=experiment,  # type: ignore[arg-type]
        folds=folds,  # type: ignore[arg-type]
        labels=labels,  # type: ignore[arg-type]
        reconciliations=reconciliations,  # type: ignore[arg-type]
    )

    for node in plan.nodes:
        if node.node_id.startswith("features."):
            assert node.scope_key == experiment_key
        else:
            assert node.fold == "fold_001"
            assert node.horizon in {5, 10}
            assert node.scope_key == compute_work_key(
                experiment_key=experiment_key,
                fold=node.fold,
                horizon=node.horizon,
            )

    expected_stages = {
        "development-features", "development-alignment", "development-model",
        "development-predictions", "development-evaluation",
        "development-targets", "development-backtest-plan",
        "development-backtest", "development-tracking",
    }
    assert {node.spec_name for node in plan.nodes} == expected_stages
    assert all(
        node.receipt_path.startswith(f"receipts/{node.spec_name}/")
        for node in plan.nodes
    )
    second_label = cast(Any, labels[1])
    foreign_label = _unchecked(
        VerifiedDevelopmentExampleLabelArtifact,
        example_id="development-example-foreign-v1",
        manifest=second_label.manifest,
        manifest_sha256=second_label.manifest_sha256,
        root=root,
    )
    with pytest.raises(ValueError, match="example identity"):
        make_work_run_plan(
            config=_config(), experiment=experiment,  # type: ignore[arg-type]
            folds=folds,  # type: ignore[arg-type]
            labels=(labels[0], foreign_label),  # type: ignore[arg-type]
            reconciliations=reconciliations,  # type: ignore[arg-type]
        )
    foreign_manifest = SimpleNamespace(**vars(second_label.manifest))
    foreign_manifest.experiment_key = "b" * 64
    foreign_identity_label = _unchecked(
        VerifiedDevelopmentExampleLabelArtifact,
        example_id="development-example-plans-v1",
        manifest=foreign_manifest,
        manifest_sha256=second_label.manifest_sha256,
        root=root,
    )
    with pytest.raises(ValueError, match="label/reconciliation identity"):
        make_work_run_plan(
            config=_config(), experiment=experiment,  # type: ignore[arg-type]
            folds=folds,  # type: ignore[arg-type]
            labels=(labels[0], foreign_identity_label),  # type: ignore[arg-type]
            reconciliations=reconciliations,  # type: ignore[arg-type]
        )


def test_g7_and_tracking_registry_preserve_frozen_work_order() -> None:
    assert TARGETS_STAGE_SPEC.dependencies == ("evaluation",)
    assert BACKTEST_PLAN_STAGE_SPEC.dependencies == ("targets",)
    assert BACKTEST_STAGE_SPEC.dependencies == ("backtest_plan",)
    assert TRACKING_STAGE_SPEC.dependencies == ("backtest", "evaluation")
    assert EVALUATION_STAGE_SPEC.dependencies == ("predictions",)


def test_formal_summary_registry_matches_receipt_verifier_stage() -> None:
    assert SUMMARY_STAGE_SPEC.name == "research-summary"
    assert SUMMARY_STAGE_SPEC.dependencies == ("evaluation",)


def test_development_summary_uses_verifier_receipt_stage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    experiment = _unchecked(
        VerifiedDevelopmentExampleExperimentIdentity,
        example_id="development-example-plans-v1",
        manifest=SimpleNamespace(
            experiment_key="3" * 64,
            scientific_config_sha256="2" * 64,
        ),
        root=Path("unused"),
    )
    evaluations = tuple(
        _evaluation(fold=fold, horizon=horizon)
        for horizon in (5, 10)
        for fold in ("fold_001", "fold_002")
    )
    monkeypatch.setattr(
        orchestration,
        "_experiment_boundary_inputs",
        lambda *_args, artifact_roots=None: (_external(),),
    )
    monkeypatch.setattr(
        orchestration,
        "_evaluation_boundary_inputs",
        lambda *_args, artifact_roots=None: (_external(),),
    )
    plan = make_summary_run_plan(
        config=_config(),
        experiment=experiment,  # type: ignore[arg-type]
        evaluations=evaluations,  # type: ignore[arg-type]
    )
    assert len(plan.nodes) == 2
    assert {node.horizon for node in plan.nodes} == {5, 10}
    assert all(node.spec_name == "development-research-summary" for node in plan.nodes)
    assert all(
        node.receipt_path.startswith("receipts/development-research-summary/")
        for node in plan.nodes
    )
    assert all(len(node.inputs) == 3 for node in plan.nodes)
    assert (
        'receipt.stage != "development-research-summary"'
        in inspect.getsource(verify_development_example_research_summary_artifact)
    )


def test_summary_rejects_single_fold_and_foreign_example_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    experiment = _unchecked(
        VerifiedDevelopmentExampleExperimentIdentity,
        example_id="development-example-plans-v1",
        manifest=SimpleNamespace(
            experiment_key="3" * 64,
            scientific_config_sha256="2" * 64,
        ),
        root=Path("unused"),
    )
    monkeypatch.setattr(
        orchestration, "_experiment_boundary_inputs", lambda *_args: (_external(),)
    )
    monkeypatch.setattr(
        orchestration, "_evaluation_boundary_inputs", lambda *_args: (_external(),)
    )
    single_each = tuple(
        _evaluation(fold="fold_001", horizon=horizon) for horizon in (5, 10)
    )
    with pytest.raises(ValueError, match="exact fold closure"):
        make_summary_run_plan(
            config=_config(), experiment=experiment,  # type: ignore[arg-type]
            evaluations=single_each,  # type: ignore[arg-type]
        )
    foreign = tuple(
        _evaluation(
            fold=fold, horizon=horizon,
            example_id="development-example-foreign-v1",
        )
        for horizon in (5, 10)
        for fold in ("fold_001", "fold_002")
    )
    with pytest.raises(ValueError, match="example identity"):
        make_summary_run_plan(
            config=_config(), experiment=experiment,  # type: ignore[arg-type]
            evaluations=foreign,  # type: ignore[arg-type]
        )


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


def test_select_run_plan_nodes_requires_exact_sorted_closure() -> None:
    plan = RunPlan(
        "PROVIDER",
        (
            _node(node_id="provider"),
            _node(
                node_id="provider-validation",
                final_directory="provider-validations/one",
            ),
        ),
    )
    selected = orchestration.select_run_plan_nodes(
        plan,
        expected_continuation="PROVIDER",
        expected_node_ids=("provider-validation", "provider"),
    )
    assert tuple(item.node_id for item in selected) == (
        "provider",
        "provider-validation",
    )
    with pytest.raises(ValueError, match="continuation"):
        orchestration.select_run_plan_nodes(
            plan,
            expected_continuation="WORK",
            expected_node_ids=("provider", "provider-validation"),
        )
    with pytest.raises(ValueError, match="closure"):
        orchestration.select_run_plan_nodes(
            plan,
            expected_continuation="PROVIDER",
            expected_node_ids=("provider",),
        )
    with pytest.raises(ValueError, match="closure"):
        orchestration.select_run_plan_nodes(
            plan,
            expected_continuation="PROVIDER",
            expected_node_ids=(
                "provider",
                "provider-validation",
                "provider-extra",
            ),
        )
    with pytest.raises(ValueError, match="duplicate"):
        orchestration.select_run_plan_nodes(
            plan,
            expected_continuation="PROVIDER",
            expected_node_ids=("provider", "provider", "provider-validation"),
        )
    with pytest.raises(ValueError, match="expected node ids invalid"):
        orchestration.select_run_plan_nodes(
            plan,
            expected_continuation="PROVIDER",
            expected_node_ids=["provider", "provider-validation"],  # type: ignore[arg-type]
        )


def test_six_builders_accept_optional_artifact_roots_keyword_only() -> None:
    for name in (
        "make_provider_materialization_run_plan",
        "make_provider_validation_run_plan",
        "make_experiment_artifact_run_plan",
        "make_label_reconciliation_run_plan",
        "make_work_run_plan",
        "make_summary_run_plan",
    ):
        parameters = inspect.signature(getattr(orchestration, name)).parameters
        assert "artifact_roots" in parameters
        assert parameters["artifact_roots"].kind is inspect.Parameter.KEYWORD_ONLY
        assert parameters["artifact_roots"].default is None
    assert not hasattr(orchestration, "make_features_run_plan")


def _patch_plan_boundaries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        orchestration, "_snapshot_boundary_inputs", lambda *_a, **_k: (_external(),),
    )
    monkeypatch.setattr(
        orchestration, "_provider_boundary_inputs", lambda *_a, **_k: (_external(),),
    )
    monkeypatch.setattr(
        orchestration,
        "_provider_validation_boundary_inputs",
        lambda *_a, **_k: (_external(),),
    )
    monkeypatch.setattr(
        orchestration, "_experiment_boundary_inputs", lambda *_a, **_k: (_external(),),
    )
    monkeypatch.setattr(
        orchestration, "_label_boundary_inputs", lambda *_a, **_k: (_external(),),
    )
    monkeypatch.setattr(
        orchestration, "_fold_boundary_inputs", lambda *_a, **_k: (_external(),),
    )
    monkeypatch.setattr(
        orchestration,
        "_reconciliation_boundary_inputs",
        lambda *_a, **_k: (_external(),),
    )
    monkeypatch.setattr(
        orchestration, "_evaluation_boundary_inputs", lambda *_a, **_k: (_external(),),
    )
    monkeypatch.setattr(
        orchestration, "_release_label_inputs", lambda *_a, **_k: (_external(),),
    )
    monkeypatch.setattr(
        orchestration, "_release_reconciliation_inputs", lambda *_a, **_k: (_external(),),
    )
    monkeypatch.setattr(
        orchestration, "_assert_release_snapshot_identity", lambda *_a, **_k: None,
    )


def _assert_omitted_equals_explicit_none(omitted: RunPlan, explicit: RunPlan) -> None:
    assert asdict(omitted) == asdict(explicit)
    assert omitted == explicit


def test_remaining_five_builders_legacy_omitted_equals_explicit_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F2: five builders besides provider prove omitted ≡ artifact_roots=None."""
    _patch_plan_boundaries(monkeypatch)
    experiment_key = "3" * 64
    root = Path("unused")
    snapshot = _unchecked(
        VerifiedDevelopmentExampleSnapshotArtifact,
        example_id=_EXAMPLE,
        root=root / "snapshots" / experiment_key,
        request=SimpleNamespace(
            snapshot_request_key=experiment_key,
            signal_start="start",
            signal_end="end",
        ),
        request_sha256=_SHA,
        manifest=SimpleNamespace(
            snapshot_id=experiment_key,
            snapshot_manifest_sha256="5" * 64,
            scientific_config_sha256="2" * 64,
            signal_start="start",
            signal_end="end",
            g1_release_id="7" * 64,
            g1_release_manifest_sha256="8" * 64,
        ),
        manifest_sha256="5" * 64,
        snapshot_receipt_sha256=_SHA,
        staging_paths=(),
    )
    provider = _unchecked(
        VerifiedDevelopmentExampleProviderArtifact,
        example_id=_EXAMPLE,
        root=root / "providers" / experiment_key,
        manifest=SimpleNamespace(
            provider_key=experiment_key,
            snapshot_id=experiment_key,
            snapshot_manifest_sha256="5" * 64,
            provider_runtime_fingerprint_sha256=_SHA,
            qlib_version="0.9.7",
            files=(),
        ),
        manifest_sha256=_SHA,
        provider_receipt_sha256=_SHA,
    )
    validation = _unchecked(
        VerifiedDevelopmentExampleProviderValidationArtifact,
        example_id=_EXAMPLE,
        root=root / "provider-validations" / experiment_key,
        summary=SimpleNamespace(
            provider_validation_key="4" * 64,
            provider_key=experiment_key,
            provider_receipt_sha256=_SHA,
            provider_manifest_sha256=_SHA,
            snapshot_id=experiment_key,
            provider_validation_config_sha256="2" * 64,
            provider_runtime_fingerprint_sha256=_SHA,
            passed=True,
        ),
        summary_sha256=_SHA,
        validation_receipt_sha256=_SHA,
    )
    experiment = _unchecked(
        VerifiedDevelopmentExampleExperimentIdentity,
        example_id=_EXAMPLE,
        root=root / "runs" / experiment_key,
        manifest=SimpleNamespace(
            experiment_key=experiment_key,
            snapshot_id=experiment_key,
            snapshot_manifest_sha256="5" * 64,
            scientific_config_sha256="2" * 64,
            provider_key=experiment_key,
            provider_receipt_sha256=_SHA,
            dependency_fingerprint_sha256=_SHA,
        ),
        manifest_sha256="6" * 64,
        experiment_receipt_sha256=_SHA,
    )
    release = _unchecked(
        VerifiedDevelopmentExampleG1Release,
        manifest=SimpleNamespace(
            example_id=_EXAMPLE,
            contract_release_id="7" * 64,
        ),
        manifest_sha256="8" * 64,
        release=SimpleNamespace(root=root / "g1"),
        artifact_paths={},
    )
    folds = _unchecked(
        VerifiedDevelopmentExampleFoldPlanArtifact,
        example_id=_EXAMPLE,
        manifest=SimpleNamespace(
            experiment_key=experiment_key,
            experiment_manifest_sha256="6" * 64,
            snapshot_id=experiment_key,
            snapshot_manifest_sha256="5" * 64,
            scientific_config_sha256="2" * 64,
            folds=(SimpleNamespace(name="fold_001"),),
        ),
        root=root,
        folds_receipt_sha256=_SHA,
        manifest_sha256=_SHA,
    )
    labels = tuple(
        _unchecked(
            VerifiedDevelopmentExampleLabelArtifact,
            example_id=_EXAMPLE,
            manifest=SimpleNamespace(
                experiment_key=experiment_key,
                experiment_manifest_sha256="6" * 64,
                snapshot_id=experiment_key,
                snapshot_manifest_sha256="5" * 64,
                g1_release_id="7" * 64,
                g1_release_manifest_sha256="8" * 64,
                horizon_sessions=horizon,
            ),
            manifest_sha256=("9" if horizon == 5 else "a") * 64,
            root=root,
            label_receipt_sha256=_SHA,
        )
        for horizon in (5, 10)
    )
    reconciliations = tuple(
        _unchecked(
            VerifiedDevelopmentExampleLabelReconciliationArtifact,
            example_id=_EXAMPLE,
            summary=SimpleNamespace(
                experiment_key=experiment_key,
                horizon_sessions=horizon,
                label_manifest_sha256=("9" if horizon == 5 else "a") * 64,
                provider_validation_receipt_sha256=_SHA,
                reconciliation_key=("c" if horizon == 5 else "d") * 64,
                passed=True,
            ),
            root=root,
            summary_sha256=_SHA,
            reconciliation_receipt_sha256=_SHA,
        )
        for horizon in (5, 10)
    )
    evaluations = tuple(
        _evaluation(fold=fold, horizon=horizon, experiment_key=experiment_key)
        for horizon in (5, 10)
        for fold in ("fold_001", "fold_002")
    )

    validation_spec = _unchecked(
        ProviderValidationSpec,
        provider_validation_key="4" * 64,
        provider_validation_config_sha256="2" * 64,
        qlib_version="0.9.7",
        code_version="development-example/provider-validation-v1",
    )
    monkeypatch.setattr(
        orchestration,
        "compute_development_provider_validation_key",
        lambda **_kw: "4" * 64,
    )
    omitted_validation = make_provider_validation_run_plan(
        config=_config(),
        snapshot=snapshot,  # type: ignore[arg-type]
        provider=provider,  # type: ignore[arg-type]
        spec=validation_spec,  # type: ignore[arg-type]
    )
    explicit_validation = make_provider_validation_run_plan(
        config=_config(),
        snapshot=snapshot,  # type: ignore[arg-type]
        provider=provider,  # type: ignore[arg-type]
        spec=validation_spec,  # type: ignore[arg-type]
        artifact_roots=None,
    )
    _assert_omitted_equals_explicit_none(omitted_validation, explicit_validation)

    omitted_artifacts = make_experiment_artifact_run_plan(
        config=_config(),
        release=release,  # type: ignore[arg-type]
        snapshot=snapshot,  # type: ignore[arg-type]
        experiment=experiment,  # type: ignore[arg-type]
    )
    explicit_artifacts = make_experiment_artifact_run_plan(
        config=_config(),
        release=release,  # type: ignore[arg-type]
        snapshot=snapshot,  # type: ignore[arg-type]
        experiment=experiment,  # type: ignore[arg-type]
        artifact_roots=None,
    )
    _assert_omitted_equals_explicit_none(omitted_artifacts, explicit_artifacts)

    specs = tuple(
        _unchecked(
            LabelReconciliationSpec,
            reconciliation_key=("c" if horizon == 5 else "d") * 64,
            experiment_key=experiment_key,
            horizon_sessions=horizon,
            provider_validation_receipt_sha256=_SHA,
            label_manifest_sha256=("9" if horizon == 5 else "a") * 64,
            label_reconciliation_config_sha256="2" * 64,
            dependency_fingerprint_sha256=_SHA,
            code_version="development-example/reconciliation-v1",
        )
        for horizon in (5, 10)
    )
    monkeypatch.setattr(
        orchestration,
        "compute_development_label_reconciliation_key",
        lambda **kwargs: ("c" if kwargs["horizon"] == 5 else "d") * 64,
    )
    omitted_reconciliation = make_label_reconciliation_run_plan(
        config=_config(),
        release=release,  # type: ignore[arg-type]
        snapshot=snapshot,  # type: ignore[arg-type]
        provider=provider,  # type: ignore[arg-type]
        provider_validation=validation,  # type: ignore[arg-type]
        experiment=experiment,  # type: ignore[arg-type]
        labels=labels,  # type: ignore[arg-type]
        specs=specs,  # type: ignore[arg-type]
    )
    explicit_reconciliation = make_label_reconciliation_run_plan(
        config=_config(),
        release=release,  # type: ignore[arg-type]
        snapshot=snapshot,  # type: ignore[arg-type]
        provider=provider,  # type: ignore[arg-type]
        provider_validation=validation,  # type: ignore[arg-type]
        experiment=experiment,  # type: ignore[arg-type]
        labels=labels,  # type: ignore[arg-type]
        specs=specs,  # type: ignore[arg-type]
        artifact_roots=None,
    )
    _assert_omitted_equals_explicit_none(omitted_reconciliation, explicit_reconciliation)

    omitted_work = make_work_run_plan(
        config=_config(),
        experiment=experiment,  # type: ignore[arg-type]
        folds=folds,  # type: ignore[arg-type]
        labels=labels,  # type: ignore[arg-type]
        reconciliations=reconciliations,  # type: ignore[arg-type]
    )
    explicit_work = make_work_run_plan(
        config=_config(),
        experiment=experiment,  # type: ignore[arg-type]
        folds=folds,  # type: ignore[arg-type]
        labels=labels,  # type: ignore[arg-type]
        reconciliations=reconciliations,  # type: ignore[arg-type]
        artifact_roots=None,
    )
    _assert_omitted_equals_explicit_none(omitted_work, explicit_work)

    omitted_summary = make_summary_run_plan(
        config=_config(),
        experiment=experiment,  # type: ignore[arg-type]
        evaluations=evaluations,  # type: ignore[arg-type]
    )
    explicit_summary = make_summary_run_plan(
        config=_config(),
        experiment=experiment,  # type: ignore[arg-type]
        evaluations=evaluations,  # type: ignore[arg-type]
        artifact_roots=None,
    )
    _assert_omitted_equals_explicit_none(omitted_summary, explicit_summary)
