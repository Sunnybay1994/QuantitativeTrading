from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import traceback
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, Literal

import pytest
import polars as pl
import quant.research.m3.labels as labels_module

from quant.data.m3_identity import clean_table_content_sha256
from quant.research.m3.contracts import (
    ExperimentIdentityManifestV1,
    ExperimentIdentitySpec,
    LabelBuildSpec,
)
from quant.research.m3.development_example import (
    VerifiedDevelopmentExampleLabelArtifact,
    compute_development_experiment_key,
    verify_development_example_g1_release,
)
from quant.research.m3.labels import (
    M3LabelArtifactError,
    build_development_example_label_artifact,
    build_label_artifact,
    verify_development_example_experiment_identity,
    verify_development_example_label_artifact,
)
from quant.research.m3.run_state import publish_stage_receipt, verify_stage_receipt

_SUPPORT_SPEC = importlib.util.spec_from_file_location(
    "m3_provider_validation_test_support",
    Path(__file__).with_name("test_m3_provider_validation.py"),
)
assert _SUPPORT_SPEC is not None and _SUPPORT_SPEC.loader is not None
_SUPPORT = importlib.util.module_from_spec(_SUPPORT_SPEC)
_SUPPORT_SPEC.loader.exec_module(_SUPPORT)


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode()


def _experiment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> tuple[Any, ...]:
    common, snapshot, provider, config, _, provider_receipt = (
        _SUPPORT._verified_provider(tmp_path, monkeypatch)
    )
    release = verify_development_example_g1_release(
        root=common / "development-example-g1"
    )
    dependency = hashlib.sha256(b"development-example-g3a-dependencies").hexdigest()
    spec = ExperimentIdentitySpec(
        scientific_config_sha256=config.scientific_config_sha256,
        dependency_fingerprint_sha256=dependency,
        code_version="development-example/g3a-experiment-v1",
    )
    key = compute_development_experiment_key(
        example_id=snapshot.example_id,
        snapshot_id=snapshot.manifest.snapshot_id,
        provider_receipt_sha256=provider.provider_receipt_sha256,
        scientific_config_sha256=config.scientific_config_sha256,
        code_version=spec.code_version,
        dependency_fingerprint_sha256=dependency,
    )
    manifest = ExperimentIdentityManifestV1(
        schema_version="m3-experiment-identity-v1",
        experiment_key=key,
        snapshot_id=snapshot.manifest.snapshot_id,
        snapshot_manifest_sha256=snapshot.manifest_sha256,
        provider_key=provider.manifest.provider_key,
        provider_manifest_sha256=provider.manifest_sha256,
        provider_receipt_sha256=provider.provider_receipt_sha256,
        scientific_config_sha256=config.scientific_config_sha256,
        dependency_fingerprint_sha256=dependency,
        code_version=spec.code_version,
    )
    root = common / "development-example-experiment"
    root.mkdir()
    manifest_path = root / "experiment_manifest.json"
    manifest_path.write_bytes(_canonical(asdict(manifest)))
    receipt = common / "receipts" / "development-experiment-identity" / f"{key}.json"
    receipt.parent.mkdir(parents=True)
    snapshot_receipt = (
        common / "receipts" / "development-snapshot"
        / f"{snapshot.request.snapshot_request_key}.json"
    )
    publish_stage_receipt(
        receipt_path=receipt,
        stage="development-experiment-identity",
        scope="EXPERIMENT",
        scope_key=key,
        artifact_roots={"root": common},
        inputs=[
            ("root", snapshot_receipt),
            ("root", snapshot.root / "manifest.json"),
            ("root", provider_receipt),
            ("root", provider.root / "provider_manifest.json"),
        ],
        outputs=[("root", manifest_path)],
    )
    experiment = verify_development_example_experiment_identity(
        experiment_root=root,
        experiment_receipt_path=receipt,
        snapshot=snapshot,
        provider=provider,
        config=config,
        spec=spec,
        artifact_roots={
            "root": common,
            "EXTERNAL_QLIB": common.parent / "external_qlib",
        },
    )
    return common, release, snapshot, provider, config, spec, experiment


def _label_spec(
    config: Any, experiment: Any, horizon: Literal[5, 10] = 5
) -> LabelBuildSpec:
    return LabelBuildSpec(
        experiment_key=experiment.manifest.experiment_key,
        experiment_manifest_sha256=experiment.manifest_sha256,
        horizon_sessions=horizon,
        benchmark="510300.SH",
        label_version=config.section("labels")["label_version"],
        label_build_code_version="development-example/g3a-label-v1",
    )


def _build_and_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    *, horizon: Literal[5, 10] = 5,
) -> tuple[Any, ...]:
    common, release, snapshot, provider, config, identity_spec, experiment = (
        _experiment(tmp_path, monkeypatch)
    )
    spec = _label_spec(config, experiment, horizon=horizon)
    root = common / f"development-example-label-horizon={horizon}"
    root.mkdir()
    manifest = build_development_example_label_artifact(
        release=release, snapshot=snapshot, experiment=experiment,
        config=config, experiment_spec=identity_spec, spec=spec,
        output_root=root,
    )
    receipt = (
        common / "receipts" / "development-labels"
        / f"{experiment.manifest.experiment_key}-h{horizon}.json"
    )
    receipt.parent.mkdir(parents=True)
    paths = dict(release.artifact_paths)
    experiment_receipt = (
        common
        / "receipts"
        / "development-experiment-identity"
        / f"{experiment.manifest.experiment_key}.json"
    )
    snapshot_receipt = (
        common
        / "receipts"
        / "development-snapshot"
        / f"{snapshot.request.snapshot_request_key}.json"
    )
    publish_stage_receipt(
        receipt_path=receipt,
        stage="development-labels",
        scope="EXPERIMENT",
        scope_key=experiment.manifest.experiment_key,
        artifact_roots={"root": common},
        inputs=[
            ("root", experiment_receipt),
            ("root", experiment.root / "experiment_manifest.json"),
            ("root", release.release.manifest_path),
            ("root", paths["bar_1d.parquet"]),
            ("root", paths["benchmark_bar_1d.parquet"]),
            ("root", paths["eligible_keys.parquet"]),
            ("root", snapshot_receipt),
            ("root", snapshot.root / "manifest.json"),
            ("root", snapshot.session_calendar_path),
        ],
        outputs=[
            ("root", root / "labels.parquet"),
            ("root", root / "diagnostics.parquet"),
            ("root", root / "label_manifest.json"),
        ],
    )
    return (
        common, release, snapshot, provider, config, identity_spec, experiment,
        spec, root, receipt, manifest,
    )


@pytest.mark.parametrize("horizon", [5, 10])
def test_development_label_artifact_closed_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    horizon: Literal[5, 10],
) -> None:
    (
        common, release, snapshot, _, config, identity_spec, experiment, spec, root,
        receipt, manifest,
    ) = _build_and_receipt(tmp_path, monkeypatch, horizon=horizon)
    verified = verify_development_example_label_artifact(
        label_root=root, label_receipt_path=receipt, release=release,
        snapshot=snapshot, experiment=experiment, config=config,
        experiment_spec=identity_spec, spec=spec,
        artifact_roots={"root": common},
    )
    assert isinstance(verified, VerifiedDevelopmentExampleLabelArtifact)
    assert verified.release_kind == "development_example"
    assert verified.formal_gate_eligible is False
    assert verified.manifest == manifest
    assert verified.manifest.horizon_sessions == horizon
    assert verified.labels.height == manifest.success_count
    assert verified.diagnostics.height == manifest.diagnostics_row_count
    assert manifest.candidate_count == (
        manifest.success_count + manifest.diagnostic_count
    )
    assert set(path.name for path in root.iterdir()) == {
        "labels.parquet", "diagnostics.parquet", "label_manifest.json",
    }


def test_label_consumer_resolves_experiment_receipt_from_distinct_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    common, release, snapshot, provider, config, identity_spec, original = (
        _experiment(tmp_path, monkeypatch)
    )
    experiment_artifacts = tmp_path / "development-example-experiment-artifacts"
    experiment_root = experiment_artifacts / "development-example-experiment"
    experiment_root.mkdir(parents=True)
    (experiment_root / "experiment_manifest.json").write_bytes(
        (original.root / "experiment_manifest.json").read_bytes()
    )
    experiment_receipt = (
        experiment_artifacts
        / "receipts"
        / "development-experiment-identity"
        / f"{original.manifest.experiment_key}.json"
    )
    experiment_receipt.parent.mkdir(parents=True)
    roots = {
        "root": common,
        "experiment": experiment_artifacts,
        "EXTERNAL_QLIB": common.parent / "external_qlib",
    }
    publish_stage_receipt(
        receipt_path=experiment_receipt,
        stage="development-experiment-identity",
        scope="EXPERIMENT",
        scope_key=original.manifest.experiment_key,
        artifact_roots=roots,
        inputs=[
            (
                "root",
                common / "receipts" / "development-snapshot"
                / f"{snapshot.request.snapshot_request_key}.json",
            ),
            ("root", snapshot.root / "manifest.json"),
            (
                "root",
                common / "receipts" / "development-provider"
                / f"{provider.manifest.provider_key}.json",
            ),
            ("root", provider.root / "provider_manifest.json"),
        ],
        outputs=[("experiment", experiment_root / "experiment_manifest.json")],
    )
    experiment = verify_development_example_experiment_identity(
        experiment_root=experiment_root,
        experiment_receipt_path=experiment_receipt,
        snapshot=snapshot,
        provider=provider,
        config=config,
        spec=identity_spec,
        artifact_roots=roots,
    )

    spec = _label_spec(config, experiment)
    label_root = common / "development-example-label-split-experiment"
    label_root.mkdir()
    build_development_example_label_artifact(
        release=release,
        snapshot=snapshot,
        experiment=experiment,
        config=config,
        experiment_spec=identity_spec,
        spec=spec,
        output_root=label_root,
    )
    label_receipt = (
        common / "receipts" / "development-labels"
        / f"{experiment.manifest.experiment_key}-split.json"
    )
    label_receipt.parent.mkdir(parents=True, exist_ok=True)
    paths = dict(release.artifact_paths)
    snapshot_receipt = (
        common / "receipts" / "development-snapshot"
        / f"{snapshot.request.snapshot_request_key}.json"
    )
    publish_stage_receipt(
        receipt_path=label_receipt,
        stage="development-labels",
        scope="EXPERIMENT",
        scope_key=experiment.manifest.experiment_key,
        artifact_roots=roots,
        inputs=[
            ("experiment", experiment_receipt),
            ("experiment", experiment.root / "experiment_manifest.json"),
            ("root", release.release.manifest_path),
            ("root", paths["bar_1d.parquet"]),
            ("root", paths["benchmark_bar_1d.parquet"]),
            ("root", paths["eligible_keys.parquet"]),
            ("root", snapshot_receipt),
            ("root", snapshot.root / "manifest.json"),
            ("root", snapshot.session_calendar_path),
        ],
        outputs=[
            ("root", label_root / "labels.parquet"),
            ("root", label_root / "diagnostics.parquet"),
            ("root", label_root / "label_manifest.json"),
        ],
    )
    verified = verify_development_example_label_artifact(
        label_root=label_root,
        label_receipt_path=label_receipt,
        release=release,
        snapshot=snapshot,
        experiment=experiment,
        config=config,
        experiment_spec=identity_spec,
        spec=spec,
        artifact_roots=roots,
    )
    assert verified.manifest.experiment_key == experiment.manifest.experiment_key


def test_artifact_root_inference_accepts_non_root_alias(tmp_path: Path) -> None:
    common = tmp_path / "common"
    nested = common / "snapshots" / "manifest.json"
    nested.parent.mkdir(parents=True)
    nested.write_bytes(b"x")
    assert labels_module._artifact_root_for(
        nested, artifact_roots={"ARTIFACTS": common}
    ) == common.resolve()
    digest = labels_module._digests(
        (nested,), artifact_roots={"ARTIFACTS": common}
    )
    assert digest[0].root_alias == "ARTIFACTS"


def test_formal_builder_rejects_development_nominal_before_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    common, release, snapshot, _, config, identity_spec, experiment = _experiment(
        tmp_path, monkeypatch
    )
    spec = _label_spec(config, experiment)
    output = common / "development-example-formal-label-rejection"
    output.mkdir()
    with pytest.raises(M3LabelArtifactError) as exc:
        build_label_artifact(
            release=release,  # type: ignore[arg-type]
            snapshot=snapshot,  # type: ignore[arg-type]
            experiment=experiment,  # type: ignore[arg-type]
            config=config, experiment_spec=identity_spec, spec=spec,
            output_root=output,
        )
    assert exc.value.code == "LABEL_ARTIFACT_INPUT_INVALID"
    assert not any(output.iterdir())


def test_label_manifest_and_receipt_wholesale_drift_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        common, release, snapshot, _, config, identity_spec, experiment, spec, root,
        _, manifest,
    ) = _build_and_receipt(tmp_path, monkeypatch)
    original_receipt = (
        common / "receipts" / "development-labels"
        / f"{experiment.manifest.experiment_key}-h5.json"
    )
    original_receipt.rename(common / "unused-original-label-receipt.json")
    payload = asdict(manifest)
    payload["bars_sha256"] = "0" * 64
    (root / "label_manifest.json").write_bytes(_canonical(payload))
    resigned = common / "receipts" / "development-labels" / "resigned-h5.json"
    paths = dict(release.artifact_paths)
    experiment_receipt = (
        common / "receipts" / "development-experiment-identity"
        / f"{experiment.manifest.experiment_key}.json"
    )
    snapshot_receipt = (
        common / "receipts" / "development-snapshot"
        / f"{snapshot.request.snapshot_request_key}.json"
    )
    publish_stage_receipt(
        receipt_path=resigned,
        stage="development-labels",
        scope="EXPERIMENT",
        scope_key=experiment.manifest.experiment_key,
        artifact_roots={"root": common},
        inputs=[
            ("root", experiment_receipt),
            ("root", experiment.root / "experiment_manifest.json"),
            ("root", release.release.manifest_path),
            ("root", paths["bar_1d.parquet"]),
            ("root", paths["benchmark_bar_1d.parquet"]),
            ("root", paths["eligible_keys.parquet"]),
            ("root", snapshot_receipt),
            ("root", snapshot.root / "manifest.json"),
            ("root", snapshot.session_calendar_path),
        ],
        outputs=[
            ("root", root / "labels.parquet"),
            ("root", root / "diagnostics.parquet"),
            ("root", root / "label_manifest.json"),
        ],
    )
    with pytest.raises(M3LabelArtifactError) as exc:
        verify_development_example_label_artifact(
            label_root=root, label_receipt_path=resigned, release=release,
            snapshot=snapshot, experiment=experiment, config=config,
            experiment_spec=identity_spec, spec=spec,
            artifact_roots={"root": common},
        )
    assert exc.value.code == "LABEL_ARTIFACT_IDENTITY_MISMATCH"


def test_label_tree_extra_entry_and_cross_horizon_spec_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        common, release, snapshot, _, config, identity_spec, experiment, spec, root,
        receipt, _,
    ) = _build_and_receipt(tmp_path, monkeypatch)
    (root / "UNDECLARED_EMPTY").mkdir()
    with pytest.raises(M3LabelArtifactError) as exc:
        verify_development_example_label_artifact(
            label_root=root, label_receipt_path=receipt, release=release,
            snapshot=snapshot, experiment=experiment, config=config,
            experiment_spec=identity_spec, spec=spec,
            artifact_roots={"root": common},
        )
    assert exc.value.code == "LABEL_ARTIFACT_IDENTITY_MISMATCH"
    wrong = LabelBuildSpec(
        experiment_key=spec.experiment_key,
        experiment_manifest_sha256=spec.experiment_manifest_sha256,
        horizon_sessions=10,
        benchmark=spec.benchmark,
        label_version=spec.label_version,
        label_build_code_version=spec.label_build_code_version,
    )
    with pytest.raises(M3LabelArtifactError):
        verify_development_example_label_artifact(
            label_root=root, label_receipt_path=receipt, release=release,
            snapshot=snapshot, experiment=experiment, config=config,
            experiment_spec=identity_spec, spec=wrong,
            artifact_roots={"root": common},
        )


def test_experiment_manifest_key_and_receipt_wholesale_replacement_fails_spec(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    common, _, snapshot, provider, config, original_spec, experiment = _experiment(
        tmp_path, monkeypatch
    )
    old_receipt = (
        common / "receipts" / "development-experiment-identity"
        / f"{experiment.manifest.experiment_key}.json"
    )
    old_receipt.rename(common / "unused-original-experiment-receipt.json")
    replacement_dependency = hashlib.sha256(b"replacement-dependencies").hexdigest()
    replacement_code = "development-example/g3a-experiment-replacement"
    replacement_key = compute_development_experiment_key(
        example_id=snapshot.example_id,
        snapshot_id=snapshot.manifest.snapshot_id,
        provider_receipt_sha256=provider.provider_receipt_sha256,
        scientific_config_sha256=config.scientific_config_sha256,
        code_version=replacement_code,
        dependency_fingerprint_sha256=replacement_dependency,
    )
    payload = asdict(experiment.manifest)
    payload.update({
        "experiment_key": replacement_key,
        "dependency_fingerprint_sha256": replacement_dependency,
        "code_version": replacement_code,
    })
    manifest_path = experiment.root / "experiment_manifest.json"
    manifest_path.write_bytes(_canonical(payload))
    replacement_receipt = (
        common / "receipts" / "development-experiment-identity"
        / f"{replacement_key}.json"
    )
    snapshot_receipt = (
        common / "receipts" / "development-snapshot"
        / f"{snapshot.request.snapshot_request_key}.json"
    )
    provider_receipt = (
        common / "receipts" / "development-provider"
        / f"{provider.manifest.provider_key}.json"
    )
    publish_stage_receipt(
        receipt_path=replacement_receipt,
        stage="development-experiment-identity",
        scope="EXPERIMENT",
        scope_key=replacement_key,
        artifact_roots={"root": common},
        inputs=[
            ("root", snapshot_receipt),
            ("root", snapshot.root / "manifest.json"),
            ("root", provider_receipt),
            ("root", provider.root / "provider_manifest.json"),
        ],
        outputs=[("root", manifest_path)],
    )
    with pytest.raises(M3LabelArtifactError) as exc:
        verify_development_example_experiment_identity(
            experiment_root=experiment.root,
            experiment_receipt_path=replacement_receipt,
            snapshot=snapshot,
            provider=provider,
            config=config,
            spec=original_spec,
            artifact_roots={
                "root": common,
                "EXTERNAL_QLIB": common.parent / "external_qlib",
            },
        )
    assert exc.value.code == "LABEL_ARTIFACT_IDENTITY_MISMATCH"


def test_label_consumer_rejects_wholesale_experiment_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        common, release, snapshot, provider, config, trusted_spec, experiment,
        label_spec, label_root, label_receipt, _,
    ) = _build_and_receipt(tmp_path, monkeypatch)
    old_experiment_receipt = (
        common / "receipts" / "development-experiment-identity"
        / f"{experiment.manifest.experiment_key}.json"
    )
    old_experiment_receipt.rename(common / "unused-original-experiment.json")
    dependency = hashlib.sha256(b"forged-label-consumer-deps").hexdigest()
    code_version = "development-example/forged-label-consumer"
    replacement_key = compute_development_experiment_key(
        example_id=snapshot.example_id,
        snapshot_id=snapshot.manifest.snapshot_id,
        provider_receipt_sha256=provider.provider_receipt_sha256,
        scientific_config_sha256=config.scientific_config_sha256,
        code_version=code_version,
        dependency_fingerprint_sha256=dependency,
    )
    payload = asdict(experiment.manifest)
    payload.update({
        "experiment_key": replacement_key,
        "dependency_fingerprint_sha256": dependency,
        "code_version": code_version,
    })
    manifest_path = experiment.root / "experiment_manifest.json"
    manifest_raw = _canonical(payload)
    manifest_path.write_bytes(manifest_raw)
    manifest_sha = hashlib.sha256(manifest_raw).hexdigest()
    replacement_receipt = (
        common / "receipts" / "development-experiment-identity"
        / f"{replacement_key}.json"
    )
    snapshot_receipt = (
        common / "receipts" / "development-snapshot"
        / f"{snapshot.request.snapshot_request_key}.json"
    )
    provider_receipt = (
        common / "receipts" / "development-provider"
        / f"{provider.manifest.provider_key}.json"
    )
    publish_stage_receipt(
        receipt_path=replacement_receipt,
        stage="development-experiment-identity",
        scope="EXPERIMENT",
        scope_key=replacement_key,
        artifact_roots={"root": common},
        inputs=[
            ("root", snapshot_receipt),
            ("root", snapshot.root / "manifest.json"),
            ("root", provider_receipt),
            ("root", provider.root / "provider_manifest.json"),
        ],
        outputs=[("root", manifest_path)],
    )
    forged_experiment = replace(
        experiment,
        manifest=ExperimentIdentityManifestV1(**payload),
        manifest_sha256=manifest_sha,
        experiment_receipt_sha256=hashlib.sha256(
            replacement_receipt.read_bytes()
        ).hexdigest(),
    )
    label_receipt.rename(common / "unused-original-label.json")
    resigned_label_receipt = (
        common / "receipts" / "development-labels" / "forged-experiment.json"
    )
    paths = dict(release.artifact_paths)
    publish_stage_receipt(
        receipt_path=resigned_label_receipt,
        stage="development-labels",
        scope="EXPERIMENT",
        scope_key=replacement_key,
        artifact_roots={"root": common},
        inputs=[
            ("root", replacement_receipt),
            ("root", manifest_path),
            ("root", release.release.manifest_path),
            ("root", paths["bar_1d.parquet"]),
            ("root", paths["benchmark_bar_1d.parquet"]),
            ("root", paths["eligible_keys.parquet"]),
            ("root", snapshot_receipt),
            ("root", snapshot.root / "manifest.json"),
            ("root", snapshot.session_calendar_path),
        ],
        outputs=[
            ("root", label_root / "labels.parquet"),
            ("root", label_root / "diagnostics.parquet"),
            ("root", label_root / "label_manifest.json"),
        ],
    )
    forged_label_spec = replace(
        label_spec,
        experiment_key=replacement_key,
        experiment_manifest_sha256=manifest_sha,
    )
    with pytest.raises(M3LabelArtifactError) as exc:
        verify_development_example_label_artifact(
            label_root=label_root,
            label_receipt_path=resigned_label_receipt,
            release=release,
            snapshot=snapshot,
            experiment=forged_experiment,
            config=config,
            experiment_spec=trusted_spec,
            spec=forged_label_spec,
            artifact_roots={"root": common},
        )
    assert exc.value.code == "LABEL_ARTIFACT_IDENTITY_MISMATCH"


def test_label_builder_rejects_nonempty_output_and_never_imports_qlib(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    common, release, snapshot, _, config, identity_spec, experiment = _experiment(
        tmp_path, monkeypatch
    )
    before = {
        name for name in sys.modules if name == "qlib" or name.startswith("qlib.")
    }
    output = common / "development-example-label-nonempty"
    output.mkdir()
    (output / "decoy.txt").write_text("x", encoding="utf-8")
    with pytest.raises(M3LabelArtifactError) as exc:
        build_development_example_label_artifact(
            release=release, snapshot=snapshot, experiment=experiment,
            config=config, experiment_spec=identity_spec,
            spec=_label_spec(config, experiment),
            output_root=output,
        )
    after = {
        name for name in sys.modules if name == "qlib" or name.startswith("qlib.")
    }
    assert exc.value.code == "LABEL_ARTIFACT_INPUT_INVALID"
    assert before == after
    assert {path.name for path in output.iterdir()} == {"decoy.txt"}


def test_label_receipt_missing_direct_bar_input_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        common, release, snapshot, _, config, identity_spec, experiment, spec, root,
        _, _,
    ) = _build_and_receipt(tmp_path, monkeypatch)
    paths = dict(release.artifact_paths)
    experiment_receipt = (
        common / "receipts" / "development-experiment-identity"
        / f"{experiment.manifest.experiment_key}.json"
    )
    snapshot_receipt = (
        common / "receipts" / "development-snapshot"
        / f"{snapshot.request.snapshot_request_key}.json"
    )
    incomplete = common / "receipts" / "development-labels" / "missing-bar.json"
    publish_stage_receipt(
        receipt_path=incomplete,
        stage="development-labels",
        scope="EXPERIMENT",
        scope_key=experiment.manifest.experiment_key,
        artifact_roots={"root": common},
        inputs=[
            ("root", experiment_receipt),
            ("root", experiment.root / "experiment_manifest.json"),
            ("root", release.release.manifest_path),
            ("root", paths["benchmark_bar_1d.parquet"]),
            ("root", paths["eligible_keys.parquet"]),
            ("root", snapshot_receipt),
            ("root", snapshot.root / "manifest.json"),
            ("root", snapshot.session_calendar_path),
        ],
        outputs=[
            ("root", root / "labels.parquet"),
            ("root", root / "diagnostics.parquet"),
            ("root", root / "label_manifest.json"),
        ],
    )
    with pytest.raises(M3LabelArtifactError) as exc:
        verify_development_example_label_artifact(
            label_root=root,
            label_receipt_path=incomplete,
            release=release,
            snapshot=snapshot,
            experiment=experiment,
            config=config,
            experiment_spec=identity_spec,
            spec=spec,
            artifact_roots={"root": common},
        )
    assert exc.value.code == "LABEL_ARTIFACT_IDENTITY_MISMATCH"


def test_forged_nested_snapshot_bundle_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    common, _, snapshot, provider, config, identity_spec, experiment = _experiment(
        tmp_path, monkeypatch
    )
    forged_manifest = replace(snapshot.manifest, config_version="forged-in-memory")
    forged_snapshot = replace(snapshot, manifest=forged_manifest)
    receipt = (
        common / "receipts" / "development-experiment-identity"
        / f"{experiment.manifest.experiment_key}.json"
    )
    with pytest.raises(M3LabelArtifactError) as exc:
        verify_development_example_experiment_identity(
            experiment_root=experiment.root,
            experiment_receipt_path=receipt,
            snapshot=forged_snapshot,
            provider=provider,
            config=config,
            spec=identity_spec,
            artifact_roots={
                "root": common,
                "EXTERNAL_QLIB": common.parent / "external_qlib",
            },
        )
    assert exc.value.code == "LABEL_ARTIFACT_IDENTITY_MISMATCH"


def test_forged_nested_snapshot_request_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    common, _, snapshot, provider, config, identity_spec, experiment = _experiment(
        tmp_path, monkeypatch
    )
    forged_start = snapshot.request.signal_start + dt.timedelta(days=1)
    assert forged_start <= snapshot.request.signal_end
    forged_request = replace(snapshot.request, signal_start=forged_start)
    forged_snapshot = replace(snapshot, request=forged_request)
    receipt = (
        common / "receipts" / "development-experiment-identity"
        / f"{experiment.manifest.experiment_key}.json"
    )
    with pytest.raises(M3LabelArtifactError) as exc:
        verify_development_example_experiment_identity(
            experiment_root=experiment.root,
            experiment_receipt_path=receipt,
            snapshot=forged_snapshot,
            provider=provider,
            config=config,
            spec=identity_spec,
            artifact_roots={
                "root": common,
                "EXTERNAL_QLIB": common.parent / "external_qlib",
            },
        )
    assert exc.value.code == "LABEL_ARTIFACT_IDENTITY_MISMATCH"


def test_experiment_extra_entry_is_rejected_by_label_consumer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        common, release, snapshot, _, config, identity_spec, experiment, spec, root,
        receipt, _,
    ) = _build_and_receipt(tmp_path, monkeypatch)
    (experiment.root / "undeclared.txt").write_text("x", encoding="utf-8")
    with pytest.raises(M3LabelArtifactError) as exc:
        verify_development_example_label_artifact(
            label_root=root,
            label_receipt_path=receipt,
            release=release,
            snapshot=snapshot,
            experiment=experiment,
            config=config,
            experiment_spec=identity_spec,
            spec=spec,
            artifact_roots={"root": common},
        )
    assert exc.value.code == "LABEL_ARTIFACT_IDENTITY_MISMATCH"


def test_regular_reader_rejects_atomic_path_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "target.bin"
    replacement = tmp_path / "replacement.bin"
    target.write_bytes(b"original")
    replacement.write_bytes(b"replaced")
    original_check = labels_module._reject_parent_links
    calls = 0
    replacement_blocked = False

    def replace_after_open(path: Path) -> None:
        nonlocal calls, replacement_blocked
        original_check(path)
        calls += 1
        if calls == 2:
            try:
                os.replace(replacement, target)
            except PermissionError:
                replacement_blocked = True

    monkeypatch.setattr(labels_module, "_reject_parent_links", replace_after_open)
    if os.name == "nt":
        assert labels_module._read_regular(target) == b"original"
        assert replacement_blocked is True
    else:
        with pytest.raises(ValueError, match="identity changed"):
            labels_module._read_regular(target)


def test_regular_reader_rejects_hardlink(tmp_path: Path) -> None:
    target = tmp_path / "target.bin"
    alias = tmp_path / "alias.bin"
    target.write_bytes(b"linked")
    os.link(target, alias)
    with pytest.raises(ValueError, match="link count"):
        labels_module._read_regular(target)


def test_regular_reader_rejects_symlink_when_supported(tmp_path: Path) -> None:
    target = tmp_path / "target.bin"
    alias = tmp_path / "alias.bin"
    target.write_bytes(b"linked")
    try:
        alias.symlink_to(target)
    except OSError:
        pytest.skip("platform does not permit test symlink creation")
    with pytest.raises((OSError, ValueError)):
        labels_module._read_regular(alias)


@pytest.mark.skipif(os.name != "nt", reason="Windows junction contract")
def test_shared_receipt_verifier_rejects_unused_windows_junction_root(
    tmp_path: Path,
) -> None:
    safe = tmp_path / "safe"
    safe.mkdir()
    artifact = safe / "artifact.bin"
    artifact.write_bytes(b"artifact")
    receipt = safe / "receipt.json"
    publish_stage_receipt(
        receipt_path=receipt,
        stage="labels",
        scope="EXPERIMENT",
        scope_key="1" * 64,
        artifact_roots={"safe": safe},
        inputs=[],
        outputs=[("safe", artifact)],
    )
    target = tmp_path / "junction-target"
    target.mkdir()
    junction = tmp_path / "junction"
    created = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(target)],
        check=False,
        capture_output=True,
        text=True,
    )
    if created.returncode != 0:
        pytest.skip("Windows junction creation unavailable")
    try:
        assert junction.is_junction()
        with pytest.raises(ValueError, match="reparse|root"):
            verify_stage_receipt(
                receipt_path=receipt,
                artifact_roots={"safe": safe, "unused": junction},
            )
    finally:
        junction.rmdir()
    assert target.is_dir()


def test_output_shrink_with_resigned_manifest_and_receipt_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        common, release, snapshot, _, config, identity_spec, experiment, spec, root,
        _, manifest,
    ) = _build_and_receipt(tmp_path, monkeypatch)
    labels_path = root / "labels.parquet"
    labels = pl.read_parquet(labels_path)
    assert labels.height > 1
    shrunk = labels.head(labels.height - 1)
    shrunk.write_parquet(labels_path)
    payload = asdict(manifest)
    payload.update({
        "labels_sha256": clean_table_content_sha256(
            table_name="m3_label_artifact_labels", frame=shrunk
        ),
        "labels_row_count": shrunk.height,
        "label_key_sha256": labels_module._key_hash(
            shrunk,
            ("as_of", "symbol", "benchmark", "horizon_sessions", "label_version"),
        ),
        "candidate_count": manifest.candidate_count - 1,
        "success_count": manifest.success_count - 1,
    })
    (root / "label_manifest.json").write_bytes(_canonical(payload))
    paths = dict(release.artifact_paths)
    experiment_receipt = (
        common / "receipts" / "development-experiment-identity"
        / f"{experiment.manifest.experiment_key}.json"
    )
    snapshot_receipt = (
        common / "receipts" / "development-snapshot"
        / f"{snapshot.request.snapshot_request_key}.json"
    )
    resigned = common / "receipts" / "development-labels" / "shrunk.json"
    publish_stage_receipt(
        receipt_path=resigned,
        stage="development-labels",
        scope="EXPERIMENT",
        scope_key=experiment.manifest.experiment_key,
        artifact_roots={"root": common},
        inputs=[
            ("root", experiment_receipt),
            ("root", experiment.root / "experiment_manifest.json"),
            ("root", release.release.manifest_path),
            ("root", paths["bar_1d.parquet"]),
            ("root", paths["benchmark_bar_1d.parquet"]),
            ("root", paths["eligible_keys.parquet"]),
            ("root", snapshot_receipt),
            ("root", snapshot.root / "manifest.json"),
            ("root", snapshot.session_calendar_path),
        ],
        outputs=[
            ("root", labels_path),
            ("root", root / "diagnostics.parquet"),
            ("root", root / "label_manifest.json"),
        ],
    )
    with pytest.raises(M3LabelArtifactError) as exc:
        verify_development_example_label_artifact(
            label_root=root, label_receipt_path=resigned, release=release,
            snapshot=snapshot, experiment=experiment, config=config,
            experiment_spec=identity_spec, spec=spec,
            artifact_roots={"root": common},
        )
    assert exc.value.code == "LABEL_ARTIFACT_IDENTITY_MISMATCH"


def test_public_error_hides_sensitive_path_from_normal_traceback(tmp_path: Path) -> None:
    secret = "TOKEN_DO_NOT_LEAK_7429"
    with pytest.raises(M3LabelArtifactError) as caught:
        labels_module.read_experiment_identity_manifest(
            tmp_path / secret / "manifest.json"
        )
    error = caught.value
    rendered = "".join(traceback.format_exception(error))
    assert secret not in str(error)
    assert secret not in repr(error)
    assert secret not in rendered
    assert error.__cause__ is None
    assert error.__context__ is None
    assert error.__suppress_context__ is True
