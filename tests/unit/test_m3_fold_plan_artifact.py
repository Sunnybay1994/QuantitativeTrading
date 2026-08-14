"""G4A strict FoldPlan artifact contracts on the development example path."""

from __future__ import annotations

import importlib.util
import hashlib
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

import quant.research.m3 as m3_public
import quant.research.m3.folds as folds_module
import quant.research.m3.provider as provider_module
from quant.research.m3.contracts import (
    FoldPlanBuildSpec,
    FoldPlanUpstreamPaths,
    ProviderBuildSpec,
    SnapshotBuildSpec,
)
from quant.research.m3.development_example import (
    VerifiedDevelopmentExampleFoldPlanArtifact,
)
from quant.research.m3.folds import (
    M3FoldPlanError,
    build_development_example_temporal_fold_plan,
    build_temporal_fold_plan,
    read_fold_plan_manifest,
    select_development_example_supervised_labels,
    verify_development_example_fold_plan_artifact,
)
from quant.research.m3.fetch_qlib_tool import build_qlib_dump_tool_spec
from quant.research.m3.labels import verify_development_example_label_artifact
from quant.research.m3.run_state import publish_stage_receipt

_SUPPORT_SPEC = importlib.util.spec_from_file_location(
    "m3_label_artifact_test_support",
    Path(__file__).with_name("test_m3_label_artifact.py"),
)
assert _SUPPORT_SPEC is not None and _SUPPORT_SPEC.loader is not None
_SUPPORT = importlib.util.module_from_spec(_SUPPORT_SPEC)
_SUPPORT_SPEC.loader.exec_module(_SUPPORT)


def test_package_root_exports_verified_fold_contract_without_heavy_imports() -> None:
    assert m3_public.VerifiedFoldPlanArtifact is not None
    assert not hasattr(m3_public, "make_temporal_folds")
    assert not hasattr(m3_public, "TemporalFold")
    assert not any(
        name == "qlib" or name.startswith(("qlib.", "lightgbm", "mlflow"))
        for name in sys.modules
    )


def _fold_spec(config: Any, snapshot: Any, experiment: Any) -> FoldPlanBuildSpec:
    walk = config.section("walk_forward")
    horizons = config.section("labels")["horizons_sessions"]
    return FoldPlanBuildSpec(
        experiment_key=experiment.manifest.experiment_key,
        experiment_manifest_sha256=experiment.manifest_sha256,
        snapshot_id=snapshot.manifest.snapshot_id,
        snapshot_manifest_sha256=snapshot.manifest_sha256,
        signal_start=snapshot.request.signal_start,
        signal_end=snapshot.request.signal_end,
        train_sessions=walk["train_sessions"],
        validation_sessions=walk["validation_sessions"],
        test_sessions=walk["test_sessions"],
        step_sessions=walk["step_sessions"],
        embargo_sessions=walk["embargo_sessions"],
        max_horizon_sessions=max(horizons),
    )


def _snapshot_spec(config: Any, snapshot: Any) -> SnapshotBuildSpec:
    return SnapshotBuildSpec(
        snapshot_request_key=snapshot.request.snapshot_request_key,
        config_version=snapshot.manifest.config_version,
        snapshot_config_sha256=config.snapshot_config_sha256,
        code_version=snapshot.request.code_version,
        history_start=snapshot.request.history_start,
        history_end=snapshot.request.history_end,
        staging_schema_version=snapshot.manifest.staging_schema_version,
        adjustment_formula_version="qlib_yahoo_like_v1",
    )


def _provider_spec(config: Any, snapshot: Any, provider: Any) -> ProviderBuildSpec:
    return ProviderBuildSpec(
        snapshot_id=snapshot.manifest.snapshot_id,
        snapshot_manifest_sha256=snapshot.manifest_sha256,
        provider_key=provider.manifest.provider_key,
        provider_config_sha256=config.provider_config_sha256,
        dump_tool=build_qlib_dump_tool_spec(config),
        qlib_version="0.9.7",
        code_version=provider.manifest.code_version,
        runtime_fingerprint=provider_module.build_provider_runtime_fingerprint(),
        fields=("open", "high", "low", "close", "vwap", "volume", "factor"),
        frequency="day",
        dump_contract_version="m3-qlib-dump-all-v1",
    )


def _build_verified_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> tuple[Any, ...]:
    (
        common, release, snapshot, provider, config, identity_spec, experiment,
        label_spec, label_root, label_receipt, _,
    ) = _SUPPORT._build_and_receipt(tmp_path, monkeypatch, horizon=5)
    roots = {
        "root": common,
        "EXTERNAL_QLIB": common.parent / "external_qlib",
    }
    label = verify_development_example_label_artifact(
        label_root=label_root,
        label_receipt_path=label_receipt,
        release=release,
        snapshot=snapshot,
        experiment=experiment,
        config=config,
        experiment_spec=identity_spec,
        spec=label_spec,
        artifact_roots=roots,
    )
    spec = _fold_spec(config, snapshot, experiment)
    snapshot_spec = _snapshot_spec(config, snapshot)
    provider_spec = _provider_spec(config, snapshot, provider)
    root = common / "development-example-fold-plan"
    root.mkdir()
    manifest = build_development_example_temporal_fold_plan(
        snapshot=snapshot,
        experiment=experiment,
        config=config,
        spec=spec,
        output_root=root,
    )
    receipt = (
        common
        / "receipts"
        / "development-folds"
        / f"{experiment.manifest.experiment_key}.json"
    )
    receipt.parent.mkdir(parents=True)
    snapshot_receipt = (
        common
        / "receipts"
        / "development-snapshot"
        / f"{snapshot.request.snapshot_request_key}.json"
    )
    experiment_receipt = (
        common
        / "receipts"
        / "development-experiment-identity"
        / f"{experiment.manifest.experiment_key}.json"
    )
    request_path = (
        common
        / "snapshot-requests"
        / f"{snapshot.request.snapshot_request_key}.json"
    )
    upstream_paths = FoldPlanUpstreamPaths(
        snapshot_request_path=request_path,
        snapshot_receipt_path=snapshot_receipt,
        provider_dump_tool_path=common.parent / "external_qlib" / "dump_bin.py",
        provider_receipt_path=(
            common / "receipts" / "development-provider"
            / f"{provider.manifest.provider_key}.json"
        ),
        experiment_receipt_path=experiment_receipt,
    )
    publish_stage_receipt(
        receipt_path=receipt,
        stage="development-folds",
        scope="EXPERIMENT",
        scope_key=experiment.manifest.experiment_key,
        artifact_roots=roots,
        inputs=[
            ("root", request_path),
            ("root", snapshot.root / "manifest.json"),
            ("root", snapshot_receipt),
            ("root", snapshot.session_calendar_path),
            ("root", experiment.root / "experiment_manifest.json"),
            ("root", experiment_receipt),
        ],
        outputs=[("root", root / "folds.json")],
    )
    folds = verify_development_example_fold_plan_artifact(
        root=root,
        receipt_path=receipt,
        release=release,
        snapshot=snapshot,
        snapshot_spec=snapshot_spec,
        provider=provider,
        provider_spec=provider_spec,
        experiment=experiment,
        experiment_spec=identity_spec,
        config=config,
        spec=spec,
        upstream_paths=upstream_paths,
        artifact_roots=roots,
    )
    return (
        common, roots, release, snapshot, snapshot_spec, provider, provider_spec,
        config, identity_spec, experiment, label_spec, label_root, label_receipt,
        label, spec, upstream_paths, root, receipt, manifest, folds,
    )


def test_development_fold_plan_closed_loop_and_embargo_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = {
        name for name in sys.modules
        if name == "qlib" or name.startswith(("qlib.", "lightgbm", "mlflow"))
    }
    (
        _, roots, release, snapshot, snapshot_spec, provider, provider_spec,
        config, identity_spec, experiment, label_spec, _, label_receipt, label,
        spec, upstream_paths, root, receipt, manifest, folds,
    ) = _build_verified_bundle(tmp_path, monkeypatch)

    assert isinstance(folds, VerifiedDevelopmentExampleFoldPlanArtifact)
    assert folds.release_kind == "development_example"
    assert folds.formal_gate_eligible is False
    assert folds.manifest == manifest
    assert read_fold_plan_manifest(root / "folds.json") == manifest
    assert len(manifest.folds) == 2
    first, second = manifest.folds
    assert first.name == "fold_001" and second.name == "fold_002"
    assert len(first.train_validation_embargo_dates) == 10
    assert len(first.validation_test_embargo_dates) == 10
    assert first.train_label_available_by == first.train_validation_embargo_dates[-1]
    assert first.validation_label_available_by == first.validation_test_embargo_dates[-1]
    assert set(first.test_dates).isdisjoint(second.test_dates)
    assert first.train_dates[0] == snapshot.request.signal_start
    assert second.test_dates[-1] == snapshot.request.signal_end
    assert max(day for fold in manifest.folds for day in fold.test_dates) <= (
        snapshot.request.signal_end
    )

    selected = select_development_example_supervised_labels(
        label=label,
        folds=folds,
        release=release,
        snapshot=snapshot,
        snapshot_spec=snapshot_spec,
        provider=provider,
        provider_spec=provider_spec,
        experiment=experiment,
        experiment_spec=identity_spec,
        config=config,
        label_spec=label_spec,
        fold_spec=spec,
        label_receipt_path=label_receipt,
        folds_receipt_path=receipt,
        upstream_paths=upstream_paths,
        artifact_roots=roots,
        fold_name="fold_001",
        segment="train",
    )
    assert selected.height > 0
    assert set(selected.get_column("as_of").to_list()) <= set(first.train_dates)
    assert selected.get_column("available_as_of").max() <= first.train_label_available_by
    after = {
        name for name in sys.modules
        if name == "qlib" or name.startswith(("qlib.", "lightgbm", "mlflow"))
    }
    assert before == after


def test_fold_plan_nominal_spec_json_and_receipt_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        common, roots, release, snapshot, snapshot_spec, provider, provider_spec,
        config, identity_spec, experiment, _, _, _, _, spec, upstream_paths,
        root, _, _, _,
    ) = _build_verified_bundle(tmp_path, monkeypatch)

    formal_output = common / "development-example-formal-fold-rejection"
    formal_output.mkdir()
    with pytest.raises(M3FoldPlanError) as caught:
        build_temporal_fold_plan(
            snapshot=snapshot,  # type: ignore[arg-type]
            experiment=experiment,  # type: ignore[arg-type]
            config=config,
            spec=spec,
            output_root=formal_output,
        )
    assert caught.value.code == "FOLD_PLAN_INPUT_INVALID"
    assert not any(formal_output.iterdir())

    wrong_output = common / "development-example-wrong-fold-spec"
    wrong_output.mkdir()
    with pytest.raises(M3FoldPlanError):
        build_development_example_temporal_fold_plan(
            snapshot=snapshot,
            experiment=experiment,
            config=config,
            spec=replace(spec, train_sessions=3),
            output_root=wrong_output,
        )
    assert not any(wrong_output.iterdir())

    raw = (root / "folds.json").read_bytes()
    (root / "folds.json").write_bytes(raw + b"\r\n")
    with pytest.raises(M3FoldPlanError) as noncanonical:
        read_fold_plan_manifest(root / "folds.json")
    assert noncanonical.value.code == "FOLD_PLAN_INPUT_INVALID"
    (root / "folds.json").write_bytes(raw)

    decoy = common / "decoy-fold-input.txt"
    decoy.write_text("not a direct input", encoding="utf-8")
    bad_receipt = common / "receipts" / "development-folds" / "extra-input.json"
    snapshot_receipt = (
        common / "receipts" / "development-snapshot"
        / f"{snapshot.request.snapshot_request_key}.json"
    )
    experiment_receipt = (
        common / "receipts" / "development-experiment-identity"
        / f"{experiment.manifest.experiment_key}.json"
    )
    request_path = (
        common / "snapshot-requests"
        / f"{snapshot.request.snapshot_request_key}.json"
    )
    publish_stage_receipt(
        receipt_path=bad_receipt,
        stage="development-folds",
        scope="EXPERIMENT",
        scope_key=experiment.manifest.experiment_key,
        artifact_roots=roots,
        inputs=[
            ("root", request_path),
            ("root", snapshot.root / "manifest.json"),
            ("root", snapshot_receipt),
            ("root", snapshot.session_calendar_path),
            ("root", experiment.root / "experiment_manifest.json"),
            ("root", experiment_receipt),
            ("root", decoy),
        ],
        outputs=[("root", root / "folds.json")],
    )
    with pytest.raises(M3FoldPlanError) as closure:
        verify_development_example_fold_plan_artifact(
            root=root,
            receipt_path=bad_receipt,
            release=release,
            snapshot=snapshot,
            snapshot_spec=snapshot_spec,
            provider=provider,
            provider_spec=provider_spec,
            experiment=experiment,
            experiment_spec=identity_spec,
            config=config,
            spec=spec,
            upstream_paths=upstream_paths,
            artifact_roots=roots,
        )
    assert closure.value.code == "FOLD_PLAN_IDENTITY_MISMATCH"


def test_fold_plan_rejects_weak_upstream_receipts_and_supports_explicit_roots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        common, roots, release, snapshot, snapshot_spec, provider, provider_spec,
        config, identity_spec, experiment, _, _, _, _, spec, upstream_paths,
        root, original_receipt, _, folds,
    ) = _build_verified_bundle(tmp_path, monkeypatch)
    overlap_roots = {
        **roots,
        "SNAPSHOT": snapshot.root,
        "FOLDS": root,
    }
    overlap_receipt = (
        common / "receipts" / "development-folds" / "overlap-roots.json"
    )
    publish_stage_receipt(
        receipt_path=overlap_receipt,
        stage="development-folds",
        scope="EXPERIMENT",
        scope_key=experiment.manifest.experiment_key,
        artifact_roots=overlap_roots,
        inputs=[
            ("root", upstream_paths.snapshot_request_path),
            ("SNAPSHOT", snapshot.root / "manifest.json"),
            ("root", upstream_paths.snapshot_receipt_path),
            ("SNAPSHOT", snapshot.session_calendar_path),
            ("root", experiment.root / "experiment_manifest.json"),
            ("root", upstream_paths.experiment_receipt_path),
        ],
        outputs=[("FOLDS", root / "folds.json")],
    )
    overlap = verify_development_example_fold_plan_artifact(
        root=root,
        receipt_path=overlap_receipt,
        release=release,
        snapshot=snapshot,
        snapshot_spec=snapshot_spec,
        provider=provider,
        provider_spec=provider_spec,
        experiment=experiment,
        experiment_spec=identity_spec,
        config=config,
        spec=spec,
        upstream_paths=upstream_paths,
        artifact_roots=overlap_roots,
    )
    assert overlap.manifest == folds.manifest

    weak_snapshot_receipt = (
        common / "receipts" / "development-snapshot" / "weak.json"
    )
    publish_stage_receipt(
        receipt_path=weak_snapshot_receipt,
        stage="development-snapshot",
        scope="SNAPSHOT",
        scope_key=snapshot.request.snapshot_request_key,
        artifact_roots=roots,
        inputs=[("root", release.release.manifest_path)],
        outputs=[
            ("root", upstream_paths.snapshot_request_path),
            ("root", snapshot.root / "manifest.json"),
            ("root", snapshot.session_calendar_path),
            *(("root", path) for path in snapshot.staging_paths),
        ],
    )
    weak_snapshot = replace(
        snapshot,
        snapshot_receipt_sha256=hashlib.sha256(
            weak_snapshot_receipt.read_bytes()
        ).hexdigest(),
    )
    with pytest.raises(M3FoldPlanError):
        verify_development_example_fold_plan_artifact(
            root=root,
            receipt_path=original_receipt,
            release=release,
            snapshot=weak_snapshot,
            snapshot_spec=snapshot_spec,
            provider=provider,
            provider_spec=provider_spec,
            experiment=experiment,
            experiment_spec=identity_spec,
            config=config,
            spec=spec,
            upstream_paths=replace(
                upstream_paths, snapshot_receipt_path=weak_snapshot_receipt
            ),
            artifact_roots=roots,
        )

    tool_path = upstream_paths.provider_dump_tool_path
    original_tool_raw = tool_path.read_bytes()
    tool_path.write_bytes(b"forged dump tool bytes")
    forged_provider_receipt = (
        common / "receipts" / "development-provider" / "forged-tool.json"
    )
    publish_stage_receipt(
        receipt_path=forged_provider_receipt,
        stage="development-provider",
        scope="PROVIDER",
        scope_key=provider.manifest.provider_key,
        artifact_roots=roots,
        inputs=[
            ("root", upstream_paths.snapshot_request_path),
            ("root", upstream_paths.snapshot_receipt_path),
            ("root", snapshot.root / "manifest.json"),
            ("root", snapshot.session_calendar_path),
            *(("root", path) for path in snapshot.staging_paths),
            ("EXTERNAL_QLIB", tool_path),
        ],
        outputs=[
            ("root", provider.root / "provider_manifest.json"),
            *(("root", provider.root / item.relative_path) for item in provider.manifest.files),
        ],
    )
    forged_provider = replace(
        provider,
        provider_receipt_sha256=hashlib.sha256(
            forged_provider_receipt.read_bytes()
        ).hexdigest(),
    )
    with pytest.raises(M3FoldPlanError):
        verify_development_example_fold_plan_artifact(
            root=root,
            receipt_path=original_receipt,
            release=release,
            snapshot=snapshot,
            snapshot_spec=snapshot_spec,
            provider=forged_provider,
            provider_spec=provider_spec,
            experiment=experiment,
            experiment_spec=identity_spec,
            config=config,
            spec=spec,
            upstream_paths=replace(
                upstream_paths, provider_receipt_path=forged_provider_receipt
            ),
            artifact_roots=roots,
        )
    tool_path.write_bytes(original_tool_raw)

    weak_experiment_receipt = (
        common / "receipts" / "development-experiment-identity" / "weak.json"
    )
    publish_stage_receipt(
        receipt_path=weak_experiment_receipt,
        stage="development-experiment-identity",
        scope="EXPERIMENT",
        scope_key=experiment.manifest.experiment_key,
        artifact_roots=roots,
        inputs=[
            ("root", upstream_paths.snapshot_receipt_path),
            ("root", snapshot.root / "manifest.json"),
        ],
        outputs=[("root", experiment.root / "experiment_manifest.json")],
    )
    weak_experiment = replace(
        experiment,
        experiment_receipt_sha256=hashlib.sha256(
            weak_experiment_receipt.read_bytes()
        ).hexdigest(),
    )
    with pytest.raises(M3FoldPlanError):
        verify_development_example_fold_plan_artifact(
            root=root,
            receipt_path=original_receipt,
            release=release,
            snapshot=snapshot,
            snapshot_spec=snapshot_spec,
            provider=provider,
            provider_spec=provider_spec,
            experiment=weak_experiment,
            experiment_spec=identity_spec,
            config=config,
            spec=spec,
            upstream_paths=replace(
                upstream_paths, experiment_receipt_path=weak_experiment_receipt
            ),
            artifact_roots=roots,
        )


def test_rebuild_and_reader_reject_non_session_boundary_and_strict_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        _, _, _, snapshot, _, _, _, config, _, experiment, _, _, _, _, spec,
        _, root, _, _, _,
    ) = _build_verified_bundle(tmp_path, monkeypatch)
    weekend = snapshot.request.signal_start.replace(day=10)
    with pytest.raises(ValueError, match="boundary"):
        folds_module._rebuild_fold_manifest(
            snapshot=snapshot,
            experiment=experiment,
            config=config,
            spec=replace(spec, signal_start=weekend),
        )

    path = root / "folds.json"
    raw = path.read_bytes()
    path.write_bytes(b"\xef\xbb\xbf" + raw)
    with pytest.raises(M3FoldPlanError):
        read_fold_plan_manifest(path)
    payload = json.loads(raw)
    payload["unknown"] = True
    path.write_bytes(json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode())
    with pytest.raises(M3FoldPlanError):
        read_fold_plan_manifest(path)
