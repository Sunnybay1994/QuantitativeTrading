"""Adversarial G8A identity-resolved PROVIDER/EXPERIMENT wave tests."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import TypeVar

import pytest

import quant.research.m3.orchestration as orchestration
from quant.data.m3_release import VerifiedG1Release
from quant.research.m3.config import LoadedM3Config
from quant.research.m3.contracts import (
    ExperimentIdentitySpec,
    LabelReconciliationSpec,
    ProviderBuildSpec,
    ProviderValidationSpec,
    VerifiedExperimentIdentity,
    VerifiedSnapshotArtifact,
)
from quant.research.m3.development_example import (
    VerifiedDevelopmentExampleExperimentIdentity,
    VerifiedDevelopmentExampleG1Release,
    VerifiedDevelopmentExampleLabelArtifact,
    VerifiedDevelopmentExampleProviderArtifact,
    VerifiedDevelopmentExampleProviderValidationArtifact,
    VerifiedDevelopmentExampleSnapshotArtifact,
)
from quant.research.m3.orchestration import (
    ExternalInput,
    make_experiment_artifact_run_plan,
    make_experiment_identity_wave_plan,
    make_label_reconciliation_run_plan,
    make_provider_materialization_run_plan,
    make_provider_validation_run_plan,
)
from quant.research.m3.run_state import ArtifactDigest

_KEY = "3" * 64
_KEY_TWO = "4" * 64
_SHA = "5" * 64
_EXAMPLE = "development-example-g8a-waves-v1"


_T = TypeVar("_T")


def _unchecked(cls: type[_T], **values: object) -> _T:
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


def _external(path: str = "input.json") -> ExternalInput:
    return ExternalInput(ArtifactDigest("fixture", path, 2, _SHA))


def _snapshot(
    *, g1_release_id: str = _KEY_TWO, g1_manifest_sha256: str = _SHA,
) -> VerifiedDevelopmentExampleSnapshotArtifact:
    return _unchecked(
        VerifiedDevelopmentExampleSnapshotArtifact,
        example_id=_EXAMPLE,
        root=Path("unused/snapshots") / _KEY,
        request=SimpleNamespace(
            snapshot_request_key=_KEY,
            signal_start="start",
            signal_end="end",
            g1_release_id=g1_release_id,
            g1_release_manifest_sha256=g1_manifest_sha256,
        ),
        request_sha256=_SHA,
        manifest=SimpleNamespace(
            snapshot_id=_KEY,
            signal_start="start",
            signal_end="end",
            g1_release_id=g1_release_id,
            g1_release_manifest_sha256=g1_manifest_sha256,
        ),
        manifest_sha256=_SHA,
        snapshot_receipt_sha256=_SHA,
        session_calendar_path=Path("unused/calendar"),
        staging_paths=(Path("unused/staging/one.parquet"),),
    )  # type: ignore[return-value]


def _provider() -> VerifiedDevelopmentExampleProviderArtifact:
    return _unchecked(
        VerifiedDevelopmentExampleProviderArtifact,
        example_id=_EXAMPLE,
        root=Path("unused/providers") / _KEY,
        manifest=SimpleNamespace(
            provider_key=_KEY,
            snapshot_id=_KEY,
            snapshot_manifest_sha256=_SHA,
            provider_runtime_fingerprint_sha256=_SHA,
            qlib_version="0.9.7",
            files=(),
        ),
        manifest_sha256=_SHA,
        provider_receipt_sha256=_SHA,
    )  # type: ignore[return-value]


def _validation(
    *, passed: bool = True, config_sha256: str = "2" * 64,
    runtime_sha256: str = _SHA, provider_manifest_sha256: str = _SHA,
) -> VerifiedDevelopmentExampleProviderValidationArtifact:
    return _unchecked(
        VerifiedDevelopmentExampleProviderValidationArtifact,
        example_id=_EXAMPLE,
        root=Path("unused/provider-validations") / _KEY_TWO,
        summary=SimpleNamespace(
            provider_validation_key=_KEY_TWO,
            provider_key=_KEY,
            provider_receipt_sha256=_SHA,
            provider_manifest_sha256=provider_manifest_sha256,
            snapshot_id=_KEY,
            provider_validation_config_sha256=config_sha256,
            provider_runtime_fingerprint_sha256=runtime_sha256,
            passed=passed,
        ),
        summary_sha256=_SHA,
        validation_receipt_sha256=_SHA,
    )  # type: ignore[return-value]


def _experiment() -> VerifiedDevelopmentExampleExperimentIdentity:
    return _unchecked(
        VerifiedDevelopmentExampleExperimentIdentity,
        example_id=_EXAMPLE,
        root=Path("unused/runs") / _KEY,
        manifest=SimpleNamespace(
            experiment_key=_KEY,
            snapshot_id=_KEY,
            snapshot_manifest_sha256=_SHA,
            provider_key=_KEY,
            provider_manifest_sha256=_SHA,
            provider_receipt_sha256=_SHA,
            scientific_config_sha256="2" * 64,
            dependency_fingerprint_sha256=_SHA,
        ),
        manifest_sha256=_SHA,
        experiment_receipt_sha256=_SHA,
    )  # type: ignore[return-value]


def _release(
    *, contract_release_id: str = _KEY_TWO, manifest_sha256: str = _SHA,
) -> VerifiedDevelopmentExampleG1Release:
    return _unchecked(
        VerifiedDevelopmentExampleG1Release,
        manifest=SimpleNamespace(
            example_id=_EXAMPLE,
            contract_release_id=contract_release_id,
        ),
        manifest_sha256=manifest_sha256,
    )  # type: ignore[return-value]


def _patch_external_boundaries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        orchestration, "_snapshot_boundary_inputs", lambda *_args, **_kwargs: (_external(),)
    )
    monkeypatch.setattr(
        orchestration, "_provider_boundary_inputs", lambda *_args, **_kwargs: (_external(),)
    )
    monkeypatch.setattr(
        orchestration,
        "_provider_validation_boundary_inputs",
        lambda *_args, **_kwargs: (_external(),),
    )
    monkeypatch.setattr(
        orchestration, "_experiment_boundary_inputs", lambda *_args, **_kwargs: (_external(),)
    )
    monkeypatch.setattr(
        orchestration, "_label_boundary_inputs", lambda *_args, **_kwargs: (_external(),)
    )
    monkeypatch.setattr(
        orchestration, "_fold_boundary_inputs", lambda *_args, **_kwargs: (_external(),)
    )
    monkeypatch.setattr(
        orchestration,
        "_reconciliation_boundary_inputs",
        lambda *_args, **_kwargs: (_external(),),
    )
    monkeypatch.setattr(
        orchestration, "_release_label_inputs", lambda *_args, **_kwargs: (_external(),)
    )
    monkeypatch.setattr(
        orchestration,
        "_release_reconciliation_inputs",
        lambda *_args, **_kwargs: (_external(),),
    )


def test_provider_materialization_and_validation_are_separate_resolved_waves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _snapshot()
    build_spec = _unchecked(
        ProviderBuildSpec,
        snapshot_id=_KEY,
        snapshot_manifest_sha256=_SHA,
        provider_key=_KEY,
        provider_config_sha256="2" * 64,
        dump_tool=SimpleNamespace(sha256=_SHA, size_bytes=2),
        qlib_version="0.9.7",
        runtime_fingerprint=SimpleNamespace(sha256=_SHA),
        code_version="development-example/provider-v1",
    )
    monkeypatch.setattr(orchestration, "compute_development_provider_key", lambda **_kw: _KEY)
    monkeypatch.setattr(
        orchestration,
        "_verified_digest",
        lambda *_args, **_kwargs: ArtifactDigest("tool", "dump.py", 2, _SHA),
    )
    _patch_external_boundaries(monkeypatch)
    provider_plan = make_provider_materialization_run_plan(
        config=_config(), snapshot=snapshot, spec=build_spec,  # type: ignore[arg-type]
        dump_tool_path=Path("dump.py"),
    )
    assert [node.spec_name for node in provider_plan.nodes] == ["development-provider"]

    validation_spec = _unchecked(
        ProviderValidationSpec,
        provider_validation_key=_KEY_TWO,
        provider_validation_config_sha256="2" * 64,
        qlib_version="0.9.7",
        code_version="development-example/provider-validation-v1",
    )
    monkeypatch.setattr(
        orchestration,
        "compute_development_provider_validation_key",
        lambda **_kw: _KEY_TWO,
    )
    validation_plan = make_provider_validation_run_plan(
        config=_config(), snapshot=snapshot, provider=_provider(),
        spec=validation_spec,  # type: ignore[arg-type]
    )
    assert [node.spec_name for node in validation_plan.nodes] == [
        "development-provider-validation"
    ]
    assert all(type(item) is ExternalInput for item in validation_plan.nodes[0].inputs)


def test_provider_validation_rejects_unverified_provider_nominal_mix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_external_boundaries(monkeypatch)
    formal_provider = _unchecked(
        orchestration.VerifiedProviderArtifact,
        manifest=_provider().manifest,
        provider_receipt_sha256=_SHA,
    )
    spec = _unchecked(
        ProviderValidationSpec,
        provider_validation_key=_KEY_TWO,
        provider_validation_config_sha256="2" * 64,
        qlib_version="0.9.7",
        code_version="provider-validation-v1",
    )
    with pytest.raises(ValueError, match="identity mismatch"):
        make_provider_validation_run_plan(
            config=_config(), snapshot=_snapshot(),
            provider=formal_provider,  # type: ignore[arg-type]
            spec=spec,  # type: ignore[arg-type]
        )


def test_experiment_identity_has_four_content_inputs_and_pass_only_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        orchestration,
        "_snapshot_identity_inputs",
        lambda *_args: (_external("snapshot-receipt.json"), _external("manifest.json")),
    )
    monkeypatch.setattr(
        orchestration,
        "_provider_identity_inputs",
        lambda *_args: (
            _external("provider-receipt.json"),
            _external("provider_manifest.json"),
        ),
    )
    monkeypatch.setattr(
        orchestration,
        "_provider_validation_boundary_inputs",
        lambda *_args: pytest.fail("validation artifact must be a gate, not content input"),
    )
    monkeypatch.setattr(
        orchestration, "compute_development_experiment_key", lambda **_kw: _KEY_TWO
    )
    spec = ExperimentIdentitySpec(
        scientific_config_sha256="2" * 64,
        dependency_fingerprint_sha256=_SHA,
        code_version="development-example/experiment-v1",
    )
    plan = make_experiment_identity_wave_plan(
        config=_config(), snapshot=_snapshot(), provider=_provider(),
        provider_validation=_validation(), spec=spec,
    )
    node = plan.nodes[0]
    assert node.spec_name == "development-experiment-identity"
    assert node.scope_key == _KEY_TWO
    assert len(node.inputs) == 4
    assert all(type(item) is ExternalInput for item in node.inputs)


def test_experiment_identity_rejects_failed_provider_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failed = _validation(passed=False)
    spec = ExperimentIdentitySpec(
        scientific_config_sha256="2" * 64,
        dependency_fingerprint_sha256=_SHA,
        code_version="development-example/experiment-v1",
    )
    with pytest.raises(ValueError, match="dependency gate"):
        make_experiment_identity_wave_plan(
            config=_config(), snapshot=_snapshot(), provider=_provider(),
            provider_validation=failed, spec=spec,
        )


@pytest.mark.parametrize(
    "validation",
    (
        _validation(config_sha256="a" * 64),
        _validation(runtime_sha256="b" * 64),
    ),
)
def test_experiment_identity_rejects_validation_config_or_runtime_drift(
    validation: VerifiedDevelopmentExampleProviderValidationArtifact,
) -> None:
    spec = ExperimentIdentitySpec(
        scientific_config_sha256="2" * 64,
        dependency_fingerprint_sha256=_SHA,
        code_version="development-example/experiment-v1",
    )
    with pytest.raises(ValueError, match="dependency gate"):
        make_experiment_identity_wave_plan(
            config=_config(), snapshot=_snapshot(), provider=_provider(),
            provider_validation=validation, spec=spec,
        )


@pytest.mark.parametrize(
    "validation",
    (
        _validation(config_sha256="a" * 64),
        _validation(runtime_sha256="b" * 64),
        _validation(provider_manifest_sha256="c" * 64),
    ),
)
def test_label_reconciliation_rejects_provider_validation_identity_drift(
    validation: VerifiedDevelopmentExampleProviderValidationArtifact,
) -> None:
    label = _unchecked(
        VerifiedDevelopmentExampleLabelArtifact,
        example_id=_EXAMPLE,
        manifest=SimpleNamespace(horizon_sessions=5),
    )
    spec = _unchecked(LabelReconciliationSpec, horizon_sessions=5)
    with pytest.raises(ValueError, match="upstream identity"):
        make_label_reconciliation_run_plan(
            config=_config(), release=_release(), snapshot=_snapshot(),
            provider=_provider(), provider_validation=validation,
            experiment=_experiment(), labels=(label,), specs=(spec,),
        )


@pytest.mark.parametrize(
    "release",
    (
        _release(contract_release_id="a" * 64),
        _release(manifest_sha256="b" * 64),
    ),
)
def test_experiment_artifacts_reject_foreign_release_snapshot_identity(
    monkeypatch: pytest.MonkeyPatch,
    release: VerifiedDevelopmentExampleG1Release,
) -> None:
    _patch_external_boundaries(monkeypatch)
    with pytest.raises(ValueError, match="release/snapshot identity"):
        make_experiment_artifact_run_plan(
            config=_config(), release=release, snapshot=_snapshot(),
            experiment=_experiment(),
        )


@pytest.mark.parametrize(
    "release_id, manifest_sha256",
    (("a" * 64, _SHA), (_KEY_TWO, "b" * 64)),
)
def test_formal_experiment_artifacts_reject_foreign_release_snapshot_identity(
    release_id: str, manifest_sha256: str,
) -> None:
    release = _unchecked(
        VerifiedG1Release,
        manifest=SimpleNamespace(release_id=release_id),
        manifest_sha256=manifest_sha256,
    )
    snapshot = _unchecked(
        VerifiedSnapshotArtifact,
        request=SimpleNamespace(
            g1_release_id=_KEY_TWO,
            g1_release_manifest_sha256=_SHA,
            signal_start="start",
            signal_end="end",
        ),
        manifest=SimpleNamespace(
            snapshot_id=_KEY,
            g1_release_id=_KEY_TWO,
            g1_release_manifest_sha256=_SHA,
            signal_start="start",
            signal_end="end",
        ),
        manifest_sha256=_SHA,
    )
    experiment = _unchecked(
        VerifiedExperimentIdentity,
        manifest=SimpleNamespace(
            experiment_key=_KEY,
            snapshot_id=_KEY,
            snapshot_manifest_sha256=_SHA,
            scientific_config_sha256="2" * 64,
        ),
    )
    with pytest.raises(ValueError, match="release/snapshot identity"):
        make_experiment_artifact_run_plan(
            config=_config(), release=release, snapshot=snapshot,
            experiment=experiment,
        )


def test_experiment_waves_wait_for_verified_identity_then_verified_labels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_external_boundaries(monkeypatch)
    first = make_experiment_artifact_run_plan(
        config=_config(), release=_release(), snapshot=_snapshot(),
        experiment=_experiment(),
    )
    assert [node.node_id for node in first.nodes] == ["labels.h5", "labels.h10", "folds"]
    assert [node.spec_name for node in first.nodes] == [
        "development-labels", "development-labels", "development-folds",
    ]
    assert all(type(item) is ExternalInput for node in first.nodes for item in node.inputs)

    labels = tuple(
        _unchecked(
            VerifiedDevelopmentExampleLabelArtifact,
            example_id=_EXAMPLE,
            root=Path(f"unused/labels/{_KEY}/h{horizon}"),
            manifest=SimpleNamespace(
                experiment_key=_KEY,
                experiment_manifest_sha256=_SHA,
                snapshot_id=_KEY,
                snapshot_manifest_sha256=_SHA,
                g1_release_id=_KEY_TWO,
                g1_release_manifest_sha256=_SHA,
                horizon_sessions=horizon,
            ),
            manifest_sha256=("6" if horizon == 5 else "7") * 64,
            label_receipt_sha256=_SHA,
        )
        for horizon in (5, 10)
    )
    specs = tuple(
        _unchecked(
            LabelReconciliationSpec,
            reconciliation_key=("8" if horizon == 5 else "9") * 64,
            experiment_key=_KEY,
            horizon_sessions=horizon,
            provider_validation_receipt_sha256=_SHA,
            label_manifest_sha256=labels[index].manifest_sha256,
            label_reconciliation_config_sha256="2" * 64,
            dependency_fingerprint_sha256=_SHA,
            code_version="development-example/reconciliation-v1",
        )
        for index, horizon in enumerate((5, 10))
    )
    monkeypatch.setattr(
        orchestration,
        "compute_development_label_reconciliation_key",
        lambda **kwargs: ("8" if kwargs["horizon"] == 5 else "9") * 64,
    )
    second = make_label_reconciliation_run_plan(
        config=_config(), release=_release(), snapshot=_snapshot(),
        provider=_provider(), provider_validation=_validation(),
        experiment=_experiment(), labels=labels,  # type: ignore[arg-type]
        specs=specs,  # type: ignore[arg-type]
    )
    assert [node.node_id for node in second.nodes] == [
        "label-reconciliation.h5", "label-reconciliation.h10",
    ]
    assert all(
        node.spec_name == "development-label-reconciliation"
        and node.receipt_path.startswith("receipts/development-label-reconciliation/")
        for node in second.nodes
    )


def test_reconciliation_rejects_unknown_or_wrong_label_manifest_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_external_boundaries(monkeypatch)
    label = _unchecked(
        VerifiedDevelopmentExampleLabelArtifact,
        example_id=_EXAMPLE,
        root=Path(f"unused/labels/{_KEY}/h5"),
        manifest=SimpleNamespace(
            experiment_key=_KEY,
            experiment_manifest_sha256=_SHA,
            snapshot_id=_KEY,
            snapshot_manifest_sha256=_SHA,
            g1_release_id=_KEY_TWO,
            g1_release_manifest_sha256=_SHA,
            horizon_sessions=5,
        ),
        manifest_sha256="6" * 64,
        label_receipt_sha256=_SHA,
    )
    spec = _unchecked(
        LabelReconciliationSpec,
        reconciliation_key="8" * 64,
        experiment_key=_KEY,
        horizon_sessions=5,
        provider_validation_receipt_sha256=_SHA,
        label_manifest_sha256="0" * 64,
        label_reconciliation_config_sha256="2" * 64,
        dependency_fingerprint_sha256=_SHA,
        code_version="development-example/reconciliation-v1",
    )
    with pytest.raises(ValueError, match="horizon closure|identity drift"):
        make_label_reconciliation_run_plan(
            config=_config(), release=_release(), snapshot=_snapshot(),
            provider=_provider(), provider_validation=_validation(),
            experiment=_experiment(), labels=(label,),  # type: ignore[arg-type]
            specs=(spec,),  # type: ignore[arg-type]
        )
