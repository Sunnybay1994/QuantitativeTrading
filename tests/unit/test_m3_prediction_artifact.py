"""G5B development prediction artifact adversarial contract tests."""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib
import importlib.util
import inspect
import json
import math
import os
import subprocess
import sys
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, cast

import polars as pl
import pandas as pd
import pytest

from quant.domain import PredictionScoreSchema
from quant.research.m3.contracts import PredictionBuildSpec, PredictionUpstreamPaths
from quant.research.m3.development_example import (
    VerifiedDevelopmentExamplePredictionArtifact,
)
from quant.research.m3.predictions import (
    build_development_example_prediction_artifact,
    normalize_prediction_scores,
    verify_development_example_prediction_artifact,
)
from quant.research.m3.run_state import publish_stage_receipt

_MODEL_SUPPORT_SPEC = importlib.util.spec_from_file_location(
    "m3_model_test_support_for_prediction",
    Path(__file__).with_name("test_m3_model_artifact.py"),
)
assert _MODEL_SUPPORT_SPEC is not None and _MODEL_SUPPORT_SPEC.loader is not None
_MODEL_SUPPORT = importlib.util.module_from_spec(_MODEL_SUPPORT_SPEC)
_MODEL_SUPPORT_SPEC.loader.exec_module(_MODEL_SUPPORT)


def _prediction_inputs(model_bundle: tuple[Any, ...]) -> list[tuple[str, Path]]:
    alignment_bundle, _, _, _, model_root, model_receipt, _, _ = model_bundle
    feature_bundle, feature, _, _, _, alignment_upstream, _, alignment_receipt, _ = (
        alignment_bundle
    )
    experiment = feature_bundle[9]
    folds = feature_bundle[11]
    fold_receipt = alignment_upstream.feature_upstream_paths.fold_receipt_path
    feature_receipt = alignment_upstream.feature_receipt_path
    return [
        ("root", cast(Path, model_root) / "model.metadata.json"),
        ("root", cast(Path, model_receipt)),
        ("root", feature.root / "feature_manifest.json"),
        ("root", feature_receipt),
        ("root", folds.root / "folds.json"),
        ("root", fold_receipt),
        ("root", experiment.root / "experiment_manifest.json"),
        ("root", cast(Path, alignment_receipt)),
    ]


def _prediction_outputs(root: Path) -> list[tuple[str, Path]]:
    return [
        ("root", root / "prediction_manifest.json"),
        ("root", root / "predictions.parquet"),
    ]


def _build_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Any, ...]:
    model_bundle = _MODEL_SUPPORT._build_model_bundle(tmp_path, monkeypatch)
    model = _MODEL_SUPPORT._verify(model_bundle)
    alignment_bundle = model_bundle[0]
    feature_bundle, feature, _, _, alignment_spec, alignment_upstream, _, _, _ = (
        alignment_bundle
    )
    common, roots = cast(Path, feature_bundle[0]), feature_bundle[1]
    config, experiment, folds = feature_bundle[7], feature_bundle[9], feature_bundle[11]
    spec = PredictionBuildSpec(
        experiment_key=experiment.manifest.experiment_key,
        work_key=alignment_spec.work_key,
        fold=alignment_spec.fold,
        horizon_sessions=alignment_spec.horizon_sessions,
        model="lightgbm",
        model_version=model.manifest.model_version,
    )
    root = common / f"development-example-predictions-{spec.work_key}"
    root.mkdir()
    manifest = build_development_example_prediction_artifact(
        model=model,
        feature=feature,
        folds=folds,
        experiment=experiment,
        config=config,
        spec=spec,
        output_root=root,
    )
    receipt = common / "receipts" / "development-predictions" / f"{spec.work_key}.json"
    receipt.parent.mkdir(parents=True)
    publish_stage_receipt(
        receipt_path=receipt,
        stage="development-predictions",
        scope="WORK",
        scope_key=spec.work_key,
        artifact_roots=roots,
        inputs=_prediction_inputs(model_bundle),
        outputs=_prediction_outputs(root),
    )
    upstream_paths = PredictionUpstreamPaths(
        model_receipt_path=cast(Path, model_bundle[5]),
        model_upstream_paths=model_bundle[3],
        feature_receipt_path=alignment_upstream.feature_receipt_path,
        feature_upstream_paths=alignment_upstream.feature_upstream_paths,
        fold_receipt_path=alignment_upstream.feature_upstream_paths.fold_receipt_path,
    )
    return model_bundle, model, spec, upstream_paths, root, receipt, manifest


def _verify(
    bundle: tuple[Any, ...],
    *,
    model: Any = None,
    feature: Any = None,
    spec: Any = None,
    receipt: Path | None = None,
) -> VerifiedDevelopmentExamplePredictionArtifact:
    model_bundle, default_model, default_spec, upstream_paths, root, default_receipt, _ = (
        bundle
    )
    alignment_bundle = model_bundle[0]
    feature_bundle, default_feature, label, label_spec, alignment_spec, _, _, _, _ = (
        alignment_bundle
    )
    (
        _, roots, release, snapshot, snapshot_spec, provider, provider_spec,
        config, experiment_spec, experiment, fold_spec, folds, feature_spec,
        _, _, _, _,
    ) = feature_bundle
    kwargs = {
        "root": root,
        "receipt_path": receipt or default_receipt,
        "release": release,
        "snapshot": snapshot,
        "snapshot_spec": snapshot_spec,
        "provider": provider,
        "provider_spec": provider_spec,
        "experiment": experiment,
        "experiment_spec": experiment_spec,
        "folds": folds,
        "fold_spec": fold_spec,
        "feature": feature or default_feature,
        "feature_spec": feature_spec,
        "label": label,
        "label_spec": label_spec,
        "alignment": model_bundle[1],
        "alignment_spec": alignment_spec,
        "model": model or default_model,
        "model_spec": model_bundle[2],
        "config": config,
        "spec": spec or default_spec,
        "upstream_paths": upstream_paths,
        "artifact_roots": roots,
    }
    parameters = inspect.signature(
        verify_development_example_prediction_artifact
    ).parameters
    return verify_development_example_prediction_artifact(
        **{name: value for name, value in kwargs.items() if name in parameters}
    )


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def test_normalizer_ties_are_score_desc_symbol_asc_and_model_is_identity() -> None:
    frame = pl.DataFrame(
        {
            "as_of": ["2025-01-02"] * 6,
            "symbol": ["600002.SH", "600001.SH", "600003.SH"] * 2,
            "score": [0.5, 0.5, 0.7, 0.5, 0.5, 0.7],
            "model": ["lightgbm"] * 3 + ["linear"] * 3,
            "model_version": ["same-version"] * 6,
            "dataset_snapshot_id": ["snapshot"] * 6,
            "fold": ["fold-0"] * 6,
            "horizon_sessions": [5] * 6,
        }
    ).with_columns(pl.col("as_of").str.to_date())

    ranked = normalize_prediction_scores(frame)

    for model in ("lightgbm", "linear"):
        group = ranked.filter(pl.col("model") == model).sort("rank")
        assert group.get_column("symbol").to_list() == [
            "600003.SH",
            "600001.SH",
            "600002.SH",
        ]
        assert group.get_column("rank").to_list() == [1, 2, 3]
    assert PredictionScoreSchema.validate(ranked).equals(ranked)


@pytest.mark.parametrize("score", [math.nan, math.inf, -math.inf])
def test_normalizer_rejects_non_finite_scores(score: float) -> None:
    frame = pl.DataFrame(
        {
            "as_of": ["2025-01-02"],
            "symbol": ["600000.SH"],
            "score": [score],
            "model": ["lightgbm"],
            "model_version": ["v1"],
            "dataset_snapshot_id": ["snapshot"],
            "fold": ["fold-0"],
            "horizon_sessions": [5],
        }
    ).with_columns(pl.col("as_of").str.to_date())
    with pytest.raises(ValueError):
        normalize_prediction_scores(frame)


def test_schema_key_and_rank_groups_include_model() -> None:
    base = pl.DataFrame(
        {
            "as_of": ["2025-01-02", "2025-01-02"],
            "symbol": ["600000.SH", "600000.SH"],
            "score": [1.0, 2.0],
            "rank": [1, 1],
            "model": ["lightgbm", "linear"],
            "model_version": ["v1", "v1"],
            "dataset_snapshot_id": ["snapshot", "snapshot"],
            "fold": ["fold-0", "fold-0"],
            "horizon_sessions": [5, 5],
        }
    ).with_columns(pl.col("as_of").str.to_date())
    assert PredictionScoreSchema.validate(base).height == 2
    with pytest.raises(Exception):
        PredictionScoreSchema.validate(pl.concat([base, base.slice(0, 1)]))


def test_package_and_strategy_import_do_not_load_lightgbm() -> None:
    # Subprocess only: in-process reload replaces ml_topk and breaks later
    # consumers holding pre-reload callables.
    script = """
import sys
for name in list(sys.modules):
    if name == "lightgbm" or name.startswith("lightgbm."):
        del sys.modules[name]
import quant.research.m3 as m3_public
import quant.strategies.ml_topk as strategy
assert m3_public.PredictionBuildSpec is not None
assert strategy.normalize_prediction_scores is not None
assert not any(name == "lightgbm" or name.startswith("lightgbm.") for name in sys.modules)
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parents[2]),
        env={**os.environ, "PYTHONPATH": "src"},
    )
    assert completed.returncode == 0, completed.stderr


def test_prediction_closed_loop_is_full_test_and_label_independent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _build_bundle(tmp_path, monkeypatch)
    verified = _verify(bundle)
    model_bundle, _, _, _, root, receipt, manifest = bundle
    alignment_bundle = model_bundle[0]
    feature = alignment_bundle[1]
    test_entry = next(item for item in feature.manifest.segments if item.name == "test")
    predictions = pl.read_parquet(root / "predictions.parquet")

    assert verified.manifest == manifest
    assert predictions.height == test_entry.n_scorable
    assert manifest.n_predicted == manifest.n_scorable == test_entry.n_scorable > 0
    assert predictions.get_column("as_of").n_unique() > 1
    assert manifest.predictions_sha256 == hashlib.sha256(
        (root / "predictions.parquet").read_bytes()
    ).hexdigest()
    assert verified.prediction_receipt_sha256 == hashlib.sha256(receipt.read_bytes()).hexdigest()

    label = alignment_bundle[2]
    future_missing = replace(
        label,
        labels=label.labels.filter(
            pl.col("as_of") < label.labels.get_column("as_of").max()
        ),
    )
    assert future_missing.labels.height < label.labels.height
    assert "label" not in inspect.signature(
        build_development_example_prediction_artifact
    ).parameters
    # G5B consumes feature test rows, never label rows; an existing artifact remains valid.
    assert _verify(bundle).predictions.equals(predictions)


@pytest.mark.parametrize("mutation", ["missing", "extra"])
def test_builder_rejects_prediction_count_drift_before_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    model_bundle = _MODEL_SUPPORT._build_model_bundle(tmp_path, monkeypatch)
    verified_model = _MODEL_SUPPORT._verify(model_bundle)
    alignment_bundle = model_bundle[0]
    feature_bundle, feature, _, _, alignment_spec, _, _, _, _ = alignment_bundle
    common, config, experiment, folds = (
        cast(Path, feature_bundle[0]), feature_bundle[7], feature_bundle[9], feature_bundle[11]
    )
    prediction_module = importlib.import_module("quant.research.m3.predictions")
    real_predict = prediction_module.predict_development_example_fitted_model

    def drifted_predict(*args: Any, **kwargs: Any) -> tuple[float, ...]:
        values = tuple(real_predict(*args, **kwargs))
        if mutation == "missing":
            return values[:-1]
        if mutation == "extra":
            return (*values, 9.0)
        raise AssertionError(mutation)

    monkeypatch.setattr(
        prediction_module,
        "predict_development_example_fitted_model",
        drifted_predict,
    )
    spec = PredictionBuildSpec(
        experiment_key=experiment.manifest.experiment_key,
        work_key=alignment_spec.work_key,
        fold=alignment_spec.fold,
        horizon_sessions=5,
        model="lightgbm",
        model_version=verified_model.manifest.model_version,
    )
    root = common / f"development-example-prediction-drift-{mutation}"
    root.mkdir()
    with pytest.raises(ValueError):
        build_development_example_prediction_artifact(
            model=verified_model,
            feature=feature,
            folds=folds,
            experiment=experiment,
            config=config,
            spec=spec,
            output_root=root,
        )
    assert not any(root.iterdir())


@pytest.mark.parametrize("mutation", ["missing", "extra", "duplicate", "outside"])
def test_builder_rejects_inference_key_set_drift_before_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    model_bundle = _MODEL_SUPPORT._build_model_bundle(tmp_path, monkeypatch)
    verified_model = _MODEL_SUPPORT._verify(model_bundle)
    alignment_bundle = model_bundle[0]
    feature_bundle, feature, _, _, alignment_spec, _, _, _, _ = alignment_bundle
    common, config, experiment, folds = (
        cast(Path, feature_bundle[0]), feature_bundle[7], feature_bundle[9], feature_bundle[11]
    )
    prediction_module = importlib.import_module("quant.research.m3.predictions")
    real_loader = prediction_module.build_development_example_inference_segment

    def drifted_loader(*args: Any, **kwargs: Any) -> Any:
        inference = real_loader(*args, **kwargs)
        features = inference.features.copy()
        metadata = inference.metadata.clone()
        if mutation == "missing":
            return replace(
                inference,
                features=features.iloc[:-1].copy(),
                metadata=metadata.slice(0, metadata.height - 1),
            )
        if mutation == "extra":
            extra_features = features.iloc[[-1]].copy()
            last_date = cast(pd.Timestamp, features.index[-1][0])
            extra_features.index = pd.MultiIndex.from_tuples(
                [(last_date, "600999.SH")], names=features.index.names
            )
            extra_metadata = metadata.slice(-1, 1).with_columns(
                pl.lit("600999.SH").alias("symbol")
            )
            return replace(
                inference,
                features=pd.concat([features, extra_features]),
                metadata=pl.concat([metadata, extra_metadata]),
            )
        if mutation == "duplicate":
            duplicate = metadata.with_columns(
                pl.when(pl.int_range(0, pl.len()) == 1)
                .then(pl.col("symbol").first())
                .otherwise(pl.col("symbol"))
                .alias("symbol")
            )
            return replace(inference, metadata=duplicate)
        outside = metadata.with_columns(
            pl.when(pl.int_range(0, pl.len()) == 0)
            .then(pl.col("as_of") + dt.timedelta(days=3650))
            .otherwise(pl.col("as_of"))
            .alias("as_of")
        )
        return replace(inference, metadata=outside)

    monkeypatch.setattr(
        prediction_module,
        "build_development_example_inference_segment",
        drifted_loader,
    )
    spec = PredictionBuildSpec(
        experiment_key=experiment.manifest.experiment_key,
        work_key=alignment_spec.work_key,
        fold=alignment_spec.fold,
        horizon_sessions=5,
        model="lightgbm",
        model_version=verified_model.manifest.model_version,
    )
    root = common / f"development-example-prediction-key-drift-{mutation}"
    root.mkdir()
    with pytest.raises(ValueError):
        build_development_example_prediction_artifact(
            model=verified_model,
            feature=feature,
            folds=folds,
            experiment=experiment,
            config=config,
            spec=spec,
            output_root=root,
        )
    assert not any(root.iterdir())


def test_prediction_rejects_lineage_mix_and_no_clobber(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _build_bundle(tmp_path, monkeypatch)
    model_bundle, model, spec, _, root, _, _ = bundle
    feature = model_bundle[0][1]
    before = {path.name: path.read_bytes() for path in root.iterdir()}
    feature_bundle = model_bundle[0][0]
    config, experiment, folds = feature_bundle[7], feature_bundle[9], feature_bundle[11]

    with pytest.raises(ValueError):
        build_development_example_prediction_artifact(
            model=model,
            feature=feature,
            folds=folds,
            experiment=experiment,
            config=config,
            spec=spec,
            output_root=root,
        )
    assert {path.name: path.read_bytes() for path in root.iterdir()} == before

    with pytest.raises(ValueError):
        _verify(bundle, spec=replace(spec, model_version="lineage-drift"))
    with pytest.raises(ValueError):
        _verify(
            bundle,
            model=replace(
                model,
                manifest=replace(model.manifest, work_key="0" * 64),
            ),
        )


def test_prediction_verifier_rejects_every_output_and_receipt_tamper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _build_bundle(tmp_path, monkeypatch)
    root, receipt = cast(Path, bundle[4]), cast(Path, bundle[5])
    for path in (root / "predictions.parquet", root / "prediction_manifest.json", receipt):
        original = path.read_bytes()
        path.write_bytes(original + b"drift")
        with pytest.raises(ValueError):
            _verify(bundle)
        path.write_bytes(original)
        _verify(bundle)


def test_wholesale_prediction_bundle_from_other_work_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_path, second_path = tmp_path / "first", tmp_path / "second"
    first_path.mkdir()
    second_path.mkdir()
    first = _build_bundle(first_path, monkeypatch)
    second = _build_bundle(second_path, monkeypatch)
    first_root, second_root = cast(Path, first[4]), cast(Path, second[4])
    first_receipt = cast(Path, first[5])
    second_manifest_path = second_root / "prediction_manifest.json"
    second_payload = json.loads(second_manifest_path.read_bytes())
    second_payload["work_key"] = "f" * 64
    second_manifest_path.write_bytes(_canonical(second_payload))
    second_receipt = cast(Path, second[5])
    second_receipt.unlink()
    publish_stage_receipt(
        receipt_path=second_receipt,
        stage="development-predictions",
        scope="WORK",
        scope_key="f" * 64,
        artifact_roots=second[0][0][0][1],
        inputs=_prediction_inputs(second[0]),
        outputs=_prediction_outputs(second_root),
    )
    for name in ("predictions.parquet", "prediction_manifest.json"):
        (first_root / name).write_bytes((second_root / name).read_bytes())
    first_receipt.write_bytes(second_receipt.read_bytes())
    with pytest.raises(ValueError):
        _verify(first)


def test_prediction_manifest_is_canonical_and_receipt_exact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _build_bundle(tmp_path, monkeypatch)
    model_bundle, _, _, _, root, _, manifest = bundle
    assert (root / "prediction_manifest.json").read_bytes() == _canonical(asdict(manifest))
    common, roots = cast(Path, model_bundle[0][0][0]), model_bundle[0][0][1]
    decoy = common / "prediction-decoy.txt"
    decoy.write_text("not an input", encoding="utf-8")
    receipt = common / "receipts" / "development-predictions" / "extra.json"
    publish_stage_receipt(
        receipt_path=receipt,
        stage="development-predictions",
        scope="WORK",
        scope_key=bundle[2].work_key,
        artifact_roots=roots,
        inputs=[*_prediction_inputs(model_bundle), ("root", decoy)],
        outputs=_prediction_outputs(root),
    )
    with pytest.raises(ValueError):
        _verify(bundle, receipt=receipt)
