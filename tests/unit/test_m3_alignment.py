"""G4C development alignment and label-free inference contract tests."""

from __future__ import annotations

import hashlib
import importlib.util
import inspect
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd
import polars as pl
import pytest

import quant.research.m3 as m3_public
import quant.research.m3.alignment as alignment_module
from quant.research.m3.alignment import (
    build_alignment_artifact,
    build_development_example_alignment_artifact,
    build_development_example_inference_segment,
    build_inference_segment,
    load_development_example_supervised_segment,
    load_supervised_segment,
    verify_alignment_artifact,
    verify_development_example_alignment_artifact,
)
from quant.research.m3.contracts import (
    AlignmentBuildSpec,
    AlignmentUpstreamPaths,
    InferenceUpstreamPaths,
    VerifiedAlignmentArtifact,
    VerifiedExperimentIdentity,
    VerifiedFeatureArtifact,
    VerifiedFoldPlanArtifact,
    VerifiedLabelArtifact,
    VerifiedProviderArtifact,
    VerifiedSnapshotArtifact,
)
from quant.data.m3_release import VerifiedG1Release
from quant.research.m3.development_example import (
    VerifiedDevelopmentExampleAlignmentArtifact,
)
from quant.research.m3.labels import verify_development_example_label_artifact
from quant.research.m3.run_state import compute_work_key, publish_stage_receipt

_FEATURE_SUPPORT_SPEC = importlib.util.spec_from_file_location(
    "m3_feature_artifact_test_support",
    Path(__file__).with_name("test_m3_feature_artifact.py"),
)
assert _FEATURE_SUPPORT_SPEC is not None and _FEATURE_SUPPORT_SPEC.loader is not None
_FEATURE_SUPPORT = importlib.util.module_from_spec(_FEATURE_SUPPORT_SPEC)
_FEATURE_SUPPORT_SPEC.loader.exec_module(_FEATURE_SUPPORT)

_LABEL_SUPPORT_SPEC = importlib.util.spec_from_file_location(
    "m3_label_artifact_test_support_for_alignment",
    Path(__file__).with_name("test_m3_label_artifact.py"),
)
assert _LABEL_SUPPORT_SPEC is not None and _LABEL_SUPPORT_SPEC.loader is not None
_LABEL_SUPPORT = importlib.util.module_from_spec(_LABEL_SUPPORT_SPEC)
_LABEL_SUPPORT_SPEC.loader.exec_module(_LABEL_SUPPORT)


def _alignment_inputs(bundle: tuple[Any, ...], feature: Any, label: Any) -> list[tuple[str, Path]]:
    common = cast(Path, bundle[0])
    experiment = bundle[9]
    folds = bundle[11]
    feature_receipt = cast(Path, bundle[15])
    feature_upstream = bundle[13]
    return [
        ("root", feature.root / "feature_manifest.json"),
        ("root", feature_receipt),
        ("root", label.root / "label_manifest.json"),
        (
            "root",
            common
            / "receipts"
            / "development-labels"
            / f"{experiment.manifest.experiment_key}-h5.json",
        ),
        ("root", folds.root / "folds.json"),
        ("root", feature_upstream.fold_receipt_path),
        ("root", experiment.root / "experiment_manifest.json"),
    ]


def _alignment_outputs(root: Path) -> list[tuple[str, Path]]:
    return [
        ("root", root / name)
        for name in (
            "train.parquet",
            "validation.parquet",
            "diagnostics.parquet",
            "alignment_manifest.json",
        )
    ]


def _build_alignment_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Any, ...]:
    feature_bundle = _FEATURE_SUPPORT._build_feature_bundle(tmp_path, monkeypatch)
    (
        common,
        roots,
        release,
        snapshot,
        snapshot_spec,
        provider,
        provider_spec,
        config,
        experiment_spec,
        experiment,
        fold_spec,
        folds,
        feature_spec,
        feature_upstream_paths,
        _,
        feature_receipt,
        _,
    ) = feature_bundle
    feature = _FEATURE_SUPPORT._verify(feature_bundle)
    label_spec = _LABEL_SUPPORT._label_spec(config, experiment, horizon=5)
    label_root = common / "development-example-label-horizon=5"
    label_receipt = (
        common / "receipts" / "development-labels" / f"{experiment.manifest.experiment_key}-h5.json"
    )
    label = verify_development_example_label_artifact(
        label_root=label_root,
        label_receipt_path=label_receipt,
        release=release,
        snapshot=snapshot,
        experiment=experiment,
        config=config,
        experiment_spec=experiment_spec,
        spec=label_spec,
        artifact_roots=roots,
    )
    planned = folds.manifest.folds[0]
    work_key = compute_work_key(
        experiment_key=experiment.manifest.experiment_key,
        fold=planned.name,
        horizon=5,
    )
    spec = AlignmentBuildSpec(
        experiment_key=experiment.manifest.experiment_key,
        work_key=work_key,
        fold=planned.name,
        planned_fold_sha256=planned.planned_fold_sha256,
        horizon_sessions=5,
        feature_manifest_sha256=feature.manifest_sha256,
        label_manifest_sha256=label.manifest_sha256,
    )
    upstream_paths = AlignmentUpstreamPaths(
        feature_receipt_path=feature_receipt,
        feature_upstream_paths=feature_upstream_paths,
        label_receipt_path=label_receipt,
    )
    root = common / f"development-example-alignment-{planned.name}-h5"
    root.mkdir()
    manifest = build_development_example_alignment_artifact(
        feature=feature,
        label=label,
        folds=folds,
        experiment=experiment,
        config=config,
        spec=spec,
        output_root=root,
    )
    receipt = common / "receipts" / "development-alignment" / f"{work_key}.json"
    receipt.parent.mkdir(parents=True)
    publish_stage_receipt(
        receipt_path=receipt,
        stage="development-alignment",
        scope="WORK",
        scope_key=work_key,
        artifact_roots=roots,
        inputs=_alignment_inputs(feature_bundle, feature, label),
        outputs=_alignment_outputs(root),
    )
    return (
        feature_bundle,
        feature,
        label,
        label_spec,
        spec,
        upstream_paths,
        root,
        receipt,
        manifest,
    )


def _verify(bundle: tuple[Any, ...], *, receipt: Path | None = None) -> Any:
    (
        feature_bundle,
        feature,
        label,
        label_spec,
        spec,
        upstream_paths,
        root,
        default_receipt,
        _,
    ) = bundle
    (
        _,
        roots,
        release,
        snapshot,
        snapshot_spec,
        provider,
        provider_spec,
        config,
        experiment_spec,
        experiment,
        fold_spec,
        folds,
        feature_spec,
        _,
        _,
        _,
        _,
    ) = feature_bundle
    return verify_development_example_alignment_artifact(
        root=root,
        receipt_path=receipt or default_receipt,
        release=release,
        snapshot=snapshot,
        snapshot_spec=snapshot_spec,
        provider=provider,
        provider_spec=provider_spec,
        experiment=experiment,
        experiment_spec=experiment_spec,
        folds=folds,
        fold_spec=fold_spec,
        feature=feature,
        feature_spec=feature_spec,
        label=label,
        label_spec=label_spec,
        config=config,
        spec=spec,
        upstream_paths=upstream_paths,
        artifact_roots=roots,
    )


def _scorable(frame: pl.DataFrame, selected: tuple[str, ...]) -> pl.DataFrame:
    return frame.filter(
        pl.any_horizontal(
            pl.col(name).is_not_null() & pl.col(name).is_not_nan() for name in selected
        )
    )


def _formal_nominals(bundle: tuple[Any, ...]) -> tuple[Any, ...]:
    feature_bundle, feature, label, *_ = bundle
    experiment = feature_bundle[9]
    folds = feature_bundle[11]
    return (
        VerifiedFeatureArtifact(
            root=feature.root, manifest=feature.manifest,
            manifest_sha256=feature.manifest_sha256,
            feature_receipt_sha256=feature.feature_receipt_sha256,
        ),
        VerifiedLabelArtifact(
            root=label.root, labels=label.labels, diagnostics=label.diagnostics,
            manifest=label.manifest, manifest_sha256=label.manifest_sha256,
            label_receipt_sha256=label.label_receipt_sha256,
        ),
        VerifiedFoldPlanArtifact(
            root=folds.root, manifest=folds.manifest,
            manifest_sha256=folds.manifest_sha256,
            folds_receipt_sha256=folds.folds_receipt_sha256,
        ),
        VerifiedExperimentIdentity(
            root=experiment.root, manifest=experiment.manifest,
            manifest_sha256=experiment.manifest_sha256,
            experiment_receipt_sha256=experiment.experiment_receipt_sha256,
        ),
    )


def test_package_root_exports_alignment_without_heavy_imports() -> None:
    assert m3_public.AlignmentBuildSpec is AlignmentBuildSpec
    assert m3_public.AlignmentUpstreamPaths is AlignmentUpstreamPaths
    assert m3_public.VerifiedDevelopmentExampleAlignmentArtifact is not None
    assert not any(
        name == "qlib" or name.startswith(("qlib.", "lightgbm", "mlflow")) for name in sys.modules
    )
    parameters = inspect.signature(build_development_example_inference_segment).parameters
    forbidden = {"label", "labels", "label_artifact", "horizon", "cutoff"}
    assert forbidden.isdisjoint(parameters)
    formal_parameters = inspect.signature(build_inference_segment).parameters
    assert forbidden.isdisjoint(formal_parameters)
    assert m3_public.build_alignment_artifact is build_alignment_artifact
    assert m3_public.verify_alignment_artifact is verify_alignment_artifact
    assert m3_public.load_supervised_segment is load_supervised_segment
    assert m3_public.build_inference_segment is build_inference_segment


def test_alignment_closed_loop_one_to_one_cutoff_and_loaders(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _build_alignment_bundle(tmp_path, monkeypatch)
    verified = _verify(bundle)
    feature_bundle, feature, label, _, _, _, root, _, built_manifest = bundle
    folds = feature_bundle[11]
    planned = folds.manifest.folds[0]
    selected = feature.manifest.schema.selected_names

    assert isinstance(verified, VerifiedDevelopmentExampleAlignmentArtifact)
    assert verified.release_kind == "development_example"
    assert verified.formal_gate_eligible is False
    assert verified.manifest == built_manifest
    assert tuple(item.name for item in verified.manifest.segments) == (
        "train",
        "validation",
    )

    for name, cutoff in (
        ("train", planned.train_label_available_by),
        ("validation", planned.validation_label_available_by),
    ):
        output = pl.read_parquet(root / f"{name}.parquet")
        assert output.columns == [
            "as_of",
            "symbol",
            *selected,
            "relative_return",
        ]
        keys = output.select(["as_of", "symbol"])
        assert keys.rows() == keys.sort(["as_of", "symbol"]).rows()
        assert output.select(["as_of", "symbol"]).is_duplicated().sum() == 0
        assert output.get_column("relative_return").is_finite().all()
        assert output.select(
            pl.any_horizontal(
                pl.col(column).is_not_null() & pl.col(column).is_not_nan() for column in selected
            ).all()
        ).item()

        feature_rows = _scorable(
            pl.read_parquet(feature.root / f"{name}.parquet"),
            selected,
        )
        labels = label.labels.filter(pl.col("horizon_sessions") == 5)
        joined = feature_rows.join(labels, on=["as_of", "symbol"], how="inner")
        expected = (
            joined.filter(pl.col("available_as_of") <= cutoff)
            .select(["as_of", "symbol"])
            .sort(["as_of", "symbol"])
        )
        assert output.select(["as_of", "symbol"]).equals(expected)

        segment_manifest = next(item for item in verified.manifest.segments if item.name == name)
        assert segment_manifest.n_feature_scorable == feature_rows.height
        assert segment_manifest.n_label_joined == joined.height
        assert segment_manifest.n_cutoff_dropped == joined.height - expected.height
        assert segment_manifest.n_final == output.height

        loaded = load_development_example_supervised_segment(
            alignment=verified,
            segment=cast(Any, name),
        )
        assert loaded.name == name
        assert list(loaded.features.columns) == list(selected)
        assert loaded.features.shape == (output.height, len(selected))
        assert isinstance(loaded.labels, pd.Series)
        assert loaded.labels.name == "relative_return"
        assert loaded.metadata.columns == ["as_of", "symbol"]
        np.testing.assert_allclose(loaded.features.to_numpy(), output.select(selected).to_numpy())
        np.testing.assert_allclose(
            loaded.labels.to_numpy(), output.get_column("relative_return").to_numpy()
        )
        assert loaded.metadata.equals(output.select(["as_of", "symbol"]))

    diagnostics = pl.read_parquet(root / "diagnostics.parquet")
    assert diagnostics.height == verified.manifest.diagnostics_row_count
    assert diagnostics.columns == ["segment", "as_of", "symbol", "reason"]
    missing = diagnostics.filter(pl.col("reason") == "MISSING_LABEL")
    assert missing.height > 0
    expected_missing = 0
    for name in ("train", "validation"):
        scorable = _scorable(
            pl.read_parquet(feature.root / f"{name}.parquet"),
            selected,
        )
        label_keys = label.labels.filter(pl.col("horizon_sessions") == 5).select(
            ["as_of", "symbol"]
        )
        expected_missing += scorable.join(label_keys, on=["as_of", "symbol"], how="anti").height
    assert missing.height == expected_missing


def test_formal_alignment_verify_load_and_label_free_inference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _build_alignment_bundle(tmp_path, monkeypatch)
    feature_bundle, _, _, label_spec, spec, upstream, _, _, _ = bundle
    formal_feature, formal_label, formal_folds, formal_experiment = _formal_nominals(
        bundle
    )
    (
        common, roots, _, _, snapshot_spec, _, provider_spec, config,
        experiment_spec, _, fold_spec, _, feature_spec, _, _, _, _,
    ) = feature_bundle
    root = common / "formal-alignment"
    root.mkdir()
    manifest = build_alignment_artifact(
        feature=formal_feature, label=formal_label, folds=formal_folds,
        experiment=formal_experiment, config=config, spec=spec, output_root=root,
    )
    receipt = common / "receipts" / "alignment" / f"{spec.work_key}.json"
    receipt.parent.mkdir(parents=True)
    publish_stage_receipt(
        receipt_path=receipt, stage="alignment", scope="WORK",
        scope_key=spec.work_key, artifact_roots=roots,
        inputs=_alignment_inputs(feature_bundle, formal_feature, formal_label),
        outputs=_alignment_outputs(root),
    )

    release = cast(VerifiedG1Release, VerifiedG1Release.__new__(VerifiedG1Release))
    snapshot = cast(
        VerifiedSnapshotArtifact,
        VerifiedSnapshotArtifact.__new__(VerifiedSnapshotArtifact),
    )
    provider = cast(
        VerifiedProviderArtifact,
        VerifiedProviderArtifact.__new__(VerifiedProviderArtifact),
    )
    fresh_calls = {"feature": 0, "label": 0}

    def fresh_feature(**kwargs: Any) -> VerifiedFeatureArtifact:
        fresh_calls["feature"] += 1
        assert kwargs["root"] == formal_feature.root
        assert kwargs["receipt_path"] == upstream.feature_receipt_path
        return formal_feature

    def fresh_label(**kwargs: Any) -> VerifiedLabelArtifact:
        fresh_calls["label"] += 1
        assert kwargs["label_root"] == formal_label.root
        assert kwargs["label_receipt_path"] == upstream.label_receipt_path
        return formal_label

    monkeypatch.setattr(alignment_module, "verify_feature_artifact", fresh_feature)
    monkeypatch.setattr(alignment_module, "verify_label_artifact", fresh_label)
    verified = verify_alignment_artifact(
        root=root, receipt_path=receipt, release=release, snapshot=snapshot,
        snapshot_spec=snapshot_spec, provider=provider, provider_spec=provider_spec,
        experiment=formal_experiment, experiment_spec=experiment_spec,
        folds=formal_folds, fold_spec=fold_spec, feature=formal_feature,
        feature_spec=feature_spec, label=formal_label, label_spec=label_spec,
        config=config, spec=spec, upstream_paths=upstream, artifact_roots=roots,
    )
    assert type(verified) is VerifiedAlignmentArtifact
    assert verified.manifest == manifest
    assert fresh_calls == {"feature": 1, "label": 1}
    loaded = load_supervised_segment(alignment=verified, segment="train")
    assert loaded.name == "train" and not loaded.features.empty

    def label_forbidden(**_: Any) -> Any:
        raise AssertionError("formal inference crossed label verifier")

    monkeypatch.setattr(alignment_module, "verify_label_artifact", label_forbidden)
    real_read = pl.read_parquet
    touched: list[str] = []

    def audited_read(source: Any, *args: Any, **kwargs: Any) -> pl.DataFrame:
        name = Path(source).name if isinstance(source, (str, Path)) else "<buffer>"
        touched.append(name)
        if name in {"labels.parquet", "diagnostics.parquet"}:
            raise AssertionError("formal inference crossed label parquet")
        return real_read(source, *args, **kwargs)

    monkeypatch.setattr(pl, "read_parquet", audited_read)
    inference = build_inference_segment(
        release=release, snapshot=snapshot, snapshot_spec=snapshot_spec,
        provider=provider, provider_spec=provider_spec,
        experiment=formal_experiment, experiment_spec=experiment_spec,
        folds=formal_folds, fold_spec=fold_spec, feature=formal_feature,
        feature_spec=feature_spec, config=config,
        fold_name=formal_folds.manifest.folds[0].name,
        upstream_paths=InferenceUpstreamPaths(
            feature_receipt_path=cast(Path, feature_bundle[15]),
            feature_upstream_paths=feature_bundle[13],
        ), artifact_roots=roots,
    )
    expected = _scorable(
        real_read(formal_feature.root / "test.parquet"),
        formal_feature.manifest.schema.selected_names,
    )
    assert inference.metadata.equals(expected.select("as_of", "symbol"))
    assert fresh_calls == {"feature": 2, "label": 1}
    assert "labels.parquet" not in touched and "diagnostics.parquet" not in touched


def test_formal_builder_rejects_development_capabilities_before_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _build_alignment_bundle(tmp_path, monkeypatch)
    feature_bundle, feature, label, _, spec, _, _, _, _ = bundle
    output = cast(Path, feature_bundle[0]) / "formal-cross-kind-reject"
    output.mkdir()
    with pytest.raises(ValueError, match="formal alignment requires formal"):
        build_alignment_artifact(
            feature=cast(Any, feature), label=cast(Any, label),
            folds=cast(Any, feature_bundle[11]),
            experiment=cast(Any, feature_bundle[9]), config=feature_bundle[7],
            spec=spec, output_root=output,
        )
    assert not any(output.iterdir())

    formal_feature, formal_label, formal_folds, formal_experiment = _formal_nominals(
        bundle
    )
    del formal_feature
    release = cast(VerifiedG1Release, VerifiedG1Release.__new__(VerifiedG1Release))
    snapshot = cast(
        VerifiedSnapshotArtifact,
        VerifiedSnapshotArtifact.__new__(VerifiedSnapshotArtifact),
    )
    provider = cast(
        VerifiedProviderArtifact,
        VerifiedProviderArtifact.__new__(VerifiedProviderArtifact),
    )
    with pytest.raises(ValueError, match="formal alignment verify requires formal"):
        verify_alignment_artifact(
            root=output, receipt_path=cast(Path, bundle[7]), release=release,
            snapshot=snapshot, snapshot_spec=feature_bundle[4], provider=provider,
            provider_spec=feature_bundle[6], experiment=formal_experiment,
            experiment_spec=feature_bundle[8], folds=formal_folds,
            fold_spec=feature_bundle[10], feature=cast(Any, feature),
            feature_spec=feature_bundle[12], label=formal_label,
            label_spec=bundle[3], config=feature_bundle[7], spec=spec,
            upstream_paths=bundle[5], artifact_roots=feature_bundle[1],
        )


def test_inference_is_label_free_and_keeps_scorable_rows_without_future_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _build_alignment_bundle(tmp_path, monkeypatch)
    feature_bundle, feature, label, _, _, _, _, _, _ = bundle
    (
        _,
        roots,
        release,
        snapshot,
        snapshot_spec,
        provider,
        provider_spec,
        config,
        experiment_spec,
        experiment,
        fold_spec,
        folds,
        feature_spec,
        feature_upstream_paths,
        _,
        _,
        _,
    ) = feature_bundle
    selected = feature.manifest.schema.selected_names
    expected = _scorable(pl.read_parquet(feature.root / "test.parquet"), selected)
    label_keys = label.labels.filter(pl.col("horizon_sessions") == 5).select(["as_of", "symbol"])
    # Simulate the real serving boundary where the last scorable key has no
    # future exit yet.  This label view is audit-only and is never supplied to
    # the inference API.
    retained_key = expected.select(["as_of", "symbol"]).tail(1)
    label_keys = label_keys.join(retained_key, on=["as_of", "symbol"], how="anti")
    without_exit = expected.join(label_keys, on=["as_of", "symbol"], how="anti")
    assert without_exit.select(["as_of", "symbol"]).equals(retained_key)

    real_read = pl.read_parquet
    touched: list[str] = []

    def audited_read(source: Any, *args: Any, **kwargs: Any) -> pl.DataFrame:
        name = Path(source).name if isinstance(source, (str, Path)) else "<buffer>"
        touched.append(name)
        if name in {"labels.parquet", "diagnostics.parquet"}:
            raise AssertionError("inference crossed the label boundary")
        return real_read(source, *args, **kwargs)

    monkeypatch.setattr(pl, "read_parquet", audited_read)
    inferred = build_development_example_inference_segment(
        release=release,
        snapshot=snapshot,
        snapshot_spec=snapshot_spec,
        provider=provider,
        provider_spec=provider_spec,
        experiment=experiment,
        experiment_spec=experiment_spec,
        folds=folds,
        fold_spec=fold_spec,
        feature=feature,
        feature_spec=feature_spec,
        config=config,
        fold_name=folds.manifest.folds[0].name,
        upstream_paths=InferenceUpstreamPaths(
            feature_receipt_path=cast(Path, feature_bundle[15]),
            feature_upstream_paths=feature_upstream_paths,
        ),
        artifact_roots=roots,
    )
    assert inferred.name == "test"
    assert list(inferred.features.columns) == list(selected)
    assert inferred.metadata.equals(expected.select(["as_of", "symbol"]))
    np.testing.assert_allclose(inferred.features.to_numpy(), expected.select(selected).to_numpy())
    assert "labels.parquet" not in touched
    assert "diagnostics.parquet" not in touched


@pytest.mark.parametrize(
    "mutate",
    [
        lambda spec: replace(spec, work_key="0" * 64),
        lambda spec: replace(spec, horizon_sessions=10),
        lambda spec: replace(spec, feature_manifest_sha256="1" * 64),
        lambda spec: replace(spec, label_manifest_sha256="2" * 64),
        lambda spec: replace(spec, planned_fold_sha256="3" * 64),
    ],
)
def test_alignment_rejects_work_horizon_schema_or_identity_drift_without_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutate: Any,
) -> None:
    bundle = _build_alignment_bundle(tmp_path, monkeypatch)
    feature_bundle, feature, label, _, spec, _, _, _, _ = bundle
    common, _, _, _, _, _, _, config, _, experiment, _, folds, _, _, _, _, _ = feature_bundle
    output = (
        common
        / f"development-example-alignment-reject-{hashlib.sha256(repr(mutate).encode()).hexdigest()[:8]}"
    )
    output.mkdir()
    with pytest.raises(ValueError):
        build_development_example_alignment_artifact(
            feature=feature,
            label=label,
            folds=folds,
            experiment=experiment,
            config=config,
            spec=mutate(spec),
            output_root=output,
        )
    assert not any(output.iterdir())


def test_alignment_no_clobber_and_rejects_formal_development_mix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _build_alignment_bundle(tmp_path, monkeypatch)
    feature_bundle, feature, label, _, spec, _, root, _, _ = bundle
    _, _, _, _, _, _, _, config, _, experiment, _, folds, _, _, _, _, _ = feature_bundle
    before = {path.name: path.read_bytes() for path in root.iterdir()}
    with pytest.raises(ValueError):
        build_development_example_alignment_artifact(
            feature=feature,
            label=label,
            folds=folds,
            experiment=experiment,
            config=config,
            spec=spec,
            output_root=root,
        )
    assert {path.name: path.read_bytes() for path in root.iterdir()} == before

    formal_shape = VerifiedFeatureArtifact(
        root=feature.root,
        manifest=feature.manifest,
        manifest_sha256=feature.manifest_sha256,
        feature_receipt_sha256=feature.feature_receipt_sha256,
    )
    output = cast(Path, feature_bundle[0]) / "development-example-alignment-cross-kind"
    output.mkdir()
    with pytest.raises((TypeError, ValueError, AttributeError)):
        build_development_example_alignment_artifact(
            feature=cast(Any, formal_shape),
            label=label,
            folds=folds,
            experiment=experiment,
            config=config,
            spec=spec,
            output_root=output,
        )
    assert not any(output.iterdir())


@pytest.mark.parametrize(
    "relative_path",
    ["train.parquet", "validation.parquet", "diagnostics.parquet"],
)
def test_alignment_verifier_rejects_output_bytes_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    relative_path: str,
) -> None:
    bundle = _build_alignment_bundle(tmp_path, monkeypatch)
    root = cast(Path, bundle[6])
    path = root / relative_path
    path.write_bytes(path.read_bytes() + b"drift")
    with pytest.raises(ValueError):
        _verify(bundle)


def test_alignment_receipt_requires_exact_direct_closure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _build_alignment_bundle(tmp_path, monkeypatch)
    feature_bundle, feature, label, _, spec, _, root, _, _ = bundle
    common, roots = cast(Path, feature_bundle[0]), feature_bundle[1]
    decoy = common / "alignment-decoy.txt"
    decoy.write_text("not a direct alignment input", encoding="utf-8")
    bad_receipt = common / "receipts" / "development-alignment" / "extra-input.json"
    publish_stage_receipt(
        receipt_path=bad_receipt,
        stage="development-alignment",
        scope="WORK",
        scope_key=spec.work_key,
        artifact_roots=roots,
        inputs=[*_alignment_inputs(feature_bundle, feature, label), ("root", decoy)],
        outputs=_alignment_outputs(root),
    )
    with pytest.raises(ValueError):
        _verify(bundle, receipt=bad_receipt)


def test_alignment_manifest_or_receipt_bytes_are_bound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _build_alignment_bundle(tmp_path, monkeypatch)
    verified = _verify(bundle)
    root, receipt = cast(Path, bundle[6]), cast(Path, bundle[7])
    payload = json.loads(receipt.read_bytes())
    outputs = {entry["relative_path"]: entry["sha256"] for entry in payload["outputs"]}
    for _, path in _alignment_outputs(root):
        relative = path.relative_to(cast(Path, bundle[0][0])).as_posix()
        assert outputs[relative] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert verified.alignment_receipt_sha256 == hashlib.sha256(receipt.read_bytes()).hexdigest()


def test_alignment_public_error_does_not_leak_output_path(tmp_path: Path) -> None:
    secret = "TOKEN_DO_NOT_LEAK_ALIGNMENT_9137"
    with pytest.raises(ValueError) as caught:
        alignment_module.read_alignment_manifest(tmp_path / secret / "alignment_manifest.json")
    assert secret not in str(caught.value)
    assert secret not in repr(caught.value)
