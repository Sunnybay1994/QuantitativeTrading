"""Formal G5B prediction artifact freshness and adversarial tests."""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import math
import os
import shutil
from dataclasses import asdict, replace
from datetime import date
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd  # type: ignore[import-untyped]
import polars as pl
import pytest

import quant.research.m3 as m3_public
import quant.research.m3.alignment as alignment_module
import quant.research.m3.model as model_module
import quant.research.m3.predictions as prediction_module
from quant.research.m3._artifact_publication import ArtifactPublication
from quant.research.m3.contracts import (
    InferenceSegment,
    ModelManifestV1,
    PredictionBuildSpec,
    PredictionUpstreamPaths,
    VerifiedModelArtifact,
    VerifiedPredictionArtifact,
)
from quant.research.m3.features import feature_schema_sha256
from quant.research.m3.model import (
    build_model_artifact,
    predict_fitted_model,
    verify_model_artifact,
)
from quant.research.m3.predictions import (
    build_development_example_prediction_artifact,
    build_prediction_artifact,
    normalize_prediction_scores,
    verify_prediction_artifact,
)
from quant.research.m3.run_state import publish_stage_receipt

_SUPPORT_SPEC = importlib.util.spec_from_file_location(
    "m3_formal_model_support_for_prediction",
    Path(__file__).with_name("test_m3_formal_model_artifact.py"),
)
assert _SUPPORT_SPEC is not None and _SUPPORT_SPEC.loader is not None
_SUPPORT = importlib.util.module_from_spec(_SUPPORT_SPEC)
_SUPPORT_SPEC.loader.exec_module(_SUPPORT)

_DEV_SUPPORT_SPEC = importlib.util.spec_from_file_location(
    "m3_development_prediction_support_for_r2",
    Path(__file__).with_name("test_m3_prediction_artifact.py"),
)
assert _DEV_SUPPORT_SPEC is not None and _DEV_SUPPORT_SPEC.loader is not None
_DEV_SUPPORT = importlib.util.module_from_spec(_DEV_SUPPORT_SPEC)
_DEV_SUPPORT_SPEC.loader.exec_module(_DEV_SUPPORT)


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    data = _SUPPORT._formal_alignment_bundle(tmp_path, monkeypatch)
    (
        _, feature_bundle, alignment, feature, label, folds, experiment,
        label_spec, alignment_spec, model_upstream, roots, common, calls,
    ) = data
    monkeypatch.setattr(
        model_module, "verify_alignment_artifact", lambda **_: alignment
    )
    model_root = common / "formal-model-for-prediction"
    model_root.mkdir()
    model_manifest = build_model_artifact(
        **_SUPPORT._build_kwargs(data, output_root=model_root)
    )
    model_receipt = (
        common / "receipts" / "model" / f"{alignment_spec.work_key}-g5b.json"
    )
    model_receipt.parent.mkdir(parents=True, exist_ok=True)
    publish_stage_receipt(
        receipt_path=model_receipt, stage="model", scope="WORK",
        scope_key=alignment_spec.work_key, artifact_roots=roots,
        inputs=_SUPPORT._model_inputs(data),
        outputs=_SUPPORT._model_outputs(model_root),
    )
    model_kwargs = _SUPPORT._verify_kwargs(
        data, root=model_root, receipt=model_receipt
    )
    model = verify_model_artifact(**model_kwargs)
    assert model.manifest == model_manifest

    feature_upstream = model_upstream.alignment_upstream_paths.feature_upstream_paths
    feature_receipt = model_upstream.alignment_upstream_paths.feature_receipt_path
    upstream = PredictionUpstreamPaths(
        model_receipt_path=model_receipt,
        model_upstream_paths=model_upstream,
        feature_receipt_path=feature_receipt,
        feature_upstream_paths=feature_upstream,
        fold_receipt_path=feature_upstream.fold_receipt_path,
    )
    spec = PredictionBuildSpec(
        experiment_key=experiment.manifest.experiment_key,
        work_key=model.manifest.work_key,
        fold=model.manifest.fold,
        horizon_sessions=cast(Any, model.manifest.horizon_sessions),
        model="lightgbm",
        model_version=model.manifest.model_version,
    )
    monkeypatch.setattr(
        alignment_module, "verify_feature_artifact", lambda **_: feature
    )
    kwargs = {
        name: value
        for name, value in model_kwargs.items()
        if name not in {"root", "receipt_path", "spec", "upstream_paths"}
    }
    kwargs.update(
        {
            "model": model,
            "model_spec": model_kwargs["spec"],
            "spec": spec,
            "upstream_paths": upstream,
        }
    )
    return {
        "data": data, "feature_bundle": feature_bundle, "common": common,
        "roots": roots, "calls": calls, "model": model, "feature": feature,
        "folds": folds, "experiment": experiment, "spec": spec,
        "upstream": upstream, "kwargs": kwargs,
    }


def _development_build_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict[str, Any], Path]:
    model_bundle = _DEV_SUPPORT._MODEL_SUPPORT._build_model_bundle(
        tmp_path, monkeypatch
    )
    model = _DEV_SUPPORT._MODEL_SUPPORT._verify(model_bundle)
    alignment_bundle = model_bundle[0]
    feature_bundle, feature, _, _, alignment_spec, _, _, _, _ = alignment_bundle
    common = cast(Path, feature_bundle[0])
    config, experiment, folds = feature_bundle[7], feature_bundle[9], feature_bundle[11]
    spec = PredictionBuildSpec(
        experiment_key=experiment.manifest.experiment_key,
        work_key=alignment_spec.work_key,
        fold=alignment_spec.fold,
        horizon_sessions=alignment_spec.horizon_sessions,
        model="lightgbm", model_version=model.manifest.model_version,
    )
    return {
        "model": model, "feature": feature, "folds": folds,
        "experiment": experiment, "config": config, "spec": spec,
    }, common


def _inputs(context: dict[str, Any]) -> list[tuple[str, Path]]:
    model = context["model"]
    feature = context["feature"]
    folds = context["folds"]
    experiment = context["experiment"]
    upstream = context["upstream"]
    return [
        ("root", model.root / "model.metadata.json"),
        ("root", upstream.model_receipt_path),
        ("root", feature.root / "feature_manifest.json"),
        ("root", upstream.feature_receipt_path),
        ("root", folds.root / "folds.json"),
        ("root", upstream.fold_receipt_path),
        ("root", experiment.root / "experiment_manifest.json"),
        ("root", upstream.model_upstream_paths.alignment_receipt_path),
    ]


def _outputs(root: Path) -> list[tuple[str, Path]]:
    return [
        ("root", root / "prediction_manifest.json"),
        ("root", root / "predictions.parquet"),
    ]


def _build_and_publish(
    context: dict[str, Any], *, suffix: str = "base",
) -> tuple[Path, Path, Any]:
    root = context["common"] / f"formal-prediction-{suffix}"
    root.mkdir()
    manifest = build_prediction_artifact(
        **context["kwargs"], output_root=root
    )
    receipt = (
        context["common"] / "receipts" / "predictions"
        / f"{context['spec'].work_key}-{suffix}.json"
    )
    receipt.parent.mkdir(parents=True, exist_ok=True)
    publish_stage_receipt(
        receipt_path=receipt, stage="predictions", scope="WORK",
        scope_key=context["spec"].work_key,
        artifact_roots=context["roots"], inputs=_inputs(context),
        outputs=_outputs(root),
    )
    return root, receipt, manifest


def _verify(
    context: dict[str, Any], root: Path, receipt: Path,
) -> VerifiedPredictionArtifact:
    return verify_prediction_artifact(
        root=root, receipt_path=receipt, **context["kwargs"]
    )


def test_formal_prediction_closed_loop_fresh_label_free_and_predict_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path, monkeypatch)
    counts = {"model": 0, "inference": 0, "predict": 0}
    real_model = prediction_module.verify_model_artifact
    real_inference = prediction_module.build_inference_segment
    real_predict = prediction_module.predict_fitted_model

    def counted_model(**kwargs: Any) -> Any:
        counts["model"] += 1
        return real_model(**kwargs)

    def counted_inference(**kwargs: Any) -> Any:
        counts["inference"] += 1
        assert "label" not in kwargs and "label_spec" not in kwargs
        return real_inference(**kwargs)

    def counted_predict(**kwargs: Any) -> tuple[float, ...]:
        counts["predict"] += 1
        return real_predict(**kwargs)

    monkeypatch.setattr(prediction_module, "verify_model_artifact", counted_model)
    monkeypatch.setattr(
        prediction_module, "build_inference_segment", counted_inference
    )
    monkeypatch.setattr(prediction_module, "predict_fitted_model", counted_predict)
    root, receipt, manifest = _build_and_publish(context)
    assert counts == {"model": 1, "inference": 1, "predict": 1}
    verified = _verify(context, root, receipt)
    assert counts == {"model": 2, "inference": 2, "predict": 2}
    assert type(verified) is VerifiedPredictionArtifact
    assert verified.manifest == manifest
    assert {path.name for path in root.iterdir()} == {
        "prediction_manifest.json", "predictions.parquet",
    }
    test = next(
        item for item in context["feature"].manifest.segments
        if item.name == "test"
    )
    assert manifest.n_predicted == manifest.n_scorable == test.n_scorable > 0
    assert manifest.n_scorable <= manifest.n_eligible
    assert verified.predictions.get_column("as_of").n_unique() > 1
    assert verified.prediction_receipt_sha256 == _sha(receipt)
    assert m3_public.build_prediction_artifact is build_prediction_artifact
    assert m3_public.verify_prediction_artifact is verify_prediction_artifact
    assert "label" not in importlib.import_module(
        "inspect"
    ).signature(alignment_module.build_inference_segment).parameters


def test_formal_prediction_rejects_copied_root_key_drift_and_hostile_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path, monkeypatch)
    output = context["common"] / "formal-prediction-copied-root"
    output.mkdir()
    copied_root = context["common"] / "copied-model"
    shutil.copytree(context["model"].root, copied_root)
    copied = replace(context["model"], root=copied_root.resolve(strict=True))
    calls = {"predict": 0}
    monkeypatch.setattr(
        prediction_module, "verify_model_artifact", lambda **_: copied
    )

    def forbidden_predict(**_: Any) -> tuple[float, ...]:
        calls["predict"] += 1
        raise AssertionError("predict must not run")

    monkeypatch.setattr(
        prediction_module, "predict_fitted_model", forbidden_predict
    )
    with pytest.raises(ValueError, match="^M3_PREDICTION_ARTIFACT_INVALID$"):
        build_prediction_artifact(**context["kwargs"], output_root=output)
    assert calls["predict"] == 0 and not any(output.iterdir())

    monkeypatch.setattr(
        prediction_module, "verify_model_artifact", lambda **_: context["model"]
    )
    real_inference = prediction_module.build_inference_segment

    def reversed_inference(**kwargs: Any) -> InferenceSegment:
        inference = real_inference(**kwargs)
        return replace(inference, metadata=inference.metadata.reverse())

    monkeypatch.setattr(
        prediction_module, "build_inference_segment", reversed_inference
    )
    with pytest.raises(ValueError, match="^M3_PREDICTION_ARTIFACT_INVALID$"):
        build_prediction_artifact(**context["kwargs"], output_root=output)
    assert calls["predict"] == 0 and not any(output.iterdir())

    marker = "C:/PRIVATE/TOKEN_G5B"

    def hostile(**_: Any) -> None:
        raise RuntimeError(marker)

    monkeypatch.setattr(prediction_module, "verify_model_artifact", hostile)
    with pytest.raises(ValueError) as caught:
        build_prediction_artifact(**context["kwargs"], output_root=output)
    assert str(caught.value) == "M3_PREDICTION_ARTIFACT_INVALID"
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert marker not in repr(caught.value) and not any(output.iterdir())


def test_formal_prediction_no_clobber_receipt_and_resigned_score_tamper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path, monkeypatch)
    root, receipt, _ = _build_and_publish(context)
    _verify(context, root, receipt)
    before = {path.name: path.read_bytes() for path in root.iterdir()}
    with pytest.raises(ValueError, match="^M3_PREDICTION_ARTIFACT_INVALID$"):
        build_prediction_artifact(**context["kwargs"], output_root=root)
    assert {path.name: path.read_bytes() for path in root.iterdir()} == before

    decoy = context["common"] / "formal-prediction-decoy.txt"
    decoy.write_text("not-an-input", encoding="utf-8")
    extra_receipt = (
        context["common"] / "receipts" / "predictions" / "extra-input.json"
    )
    publish_stage_receipt(
        receipt_path=extra_receipt, stage="predictions", scope="WORK",
        scope_key=context["spec"].work_key,
        artifact_roots=context["roots"],
        inputs=[*_inputs(context), ("root", decoy)], outputs=_outputs(root),
    )
    with pytest.raises(ValueError, match="^M3_PREDICTION_ARTIFACT_INVALID$"):
        _verify(context, root, extra_receipt)

    predictions_path = root / "predictions.parquet"
    predictions = pl.read_parquet(predictions_path)
    changed = normalize_prediction_scores(
        predictions.drop("rank").with_columns((pl.col("score") + 7.0).alias("score"))
    )
    changed.write_parquet(
        predictions_path, compression="zstd", compression_level=3,
        statistics=True, row_group_size=65536, use_pyarrow=False,
    )
    manifest_path = root / "prediction_manifest.json"
    payload = json.loads(manifest_path.read_bytes())
    payload["predictions_sha256"] = _sha(predictions_path)
    payload["prediction_keys_sha256"] = prediction_module.prediction_keys_sha256(
        changed
    )
    manifest_path.write_bytes(_canonical(payload))
    receipt.unlink()
    publish_stage_receipt(
        receipt_path=receipt, stage="predictions", scope="WORK",
        scope_key=context["spec"].work_key,
        artifact_roots=context["roots"], inputs=_inputs(context),
        outputs=_outputs(root),
    )
    with pytest.raises(ValueError, match="^M3_PREDICTION_ARTIFACT_INVALID$"):
        _verify(context, root, receipt)


def test_formal_prediction_rejects_subclass_and_nonfinite_scores(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path, monkeypatch)
    output = context["common"] / "formal-prediction-adversarial"
    output.mkdir()

    class ModelSubclass(VerifiedModelArtifact):
        pass

    disguised = ModelSubclass(
        root=context["model"].root, manifest=context["model"].manifest,
        manifest_sha256=context["model"].manifest_sha256,
        model_receipt_sha256=context["model"].model_receipt_sha256,
    )
    with pytest.raises(ValueError, match="^M3_PREDICTION_ARTIFACT_INVALID$"):
        build_prediction_artifact(
            **{**context["kwargs"], "model": disguised}, output_root=output
        )
    assert not any(output.iterdir())

    monkeypatch.setattr(
        prediction_module, "verify_model_artifact", lambda **_: context["model"]
    )
    monkeypatch.setattr(
        prediction_module, "predict_fitted_model",
        lambda **_: (math.inf,) * next(
            item.n_scorable for item in context["feature"].manifest.segments
            if item.name == "test"
        ),
    )
    with pytest.raises(ValueError, match="^M3_PREDICTION_ARTIFACT_INVALID$"):
        build_prediction_artifact(**context["kwargs"], output_root=output)
    assert not any(output.iterdir())


def test_r2_formal_writers_rollback_value_and_runtime_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path, monkeypatch)
    for stage in ("parquet", "manifest"):
        for error_type in (ValueError, RuntimeError):
            output = context["common"] / f"formal-r2-{stage}-{error_type.__name__}"
            output.mkdir()
            marker = f"PRIVATE_{stage}_{error_type.__name__}"

            def hostile(*_: Any, **__: Any) -> None:
                raise error_type(marker)

            with monkeypatch.context() as patcher:
                patcher.setattr(
                    prediction_module,
                    "_write_parquet" if stage == "parquet" else "_write_exclusive",
                    hostile,
                )
                with pytest.raises(ValueError) as caught:
                    build_prediction_artifact(
                        **context["kwargs"], output_root=output
                    )
            assert str(caught.value) == "M3_PREDICTION_ARTIFACT_INVALID"
            assert caught.value.__cause__ is None
            assert caught.value.__context__ is None
            assert marker not in repr(caught.value)
            assert not any(output.iterdir())


def test_r2_development_writers_share_transactional_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    kwargs, common = _development_build_context(tmp_path, monkeypatch)
    for stage in ("parquet", "manifest"):
        for error_type in (ValueError, RuntimeError):
            output = common / f"development-r2-{stage}-{error_type.__name__}"
            output.mkdir()
            marker = f"DEV_PRIVATE_{stage}_{error_type.__name__}"

            def hostile(*_: Any, **__: Any) -> None:
                raise error_type(marker)

            with monkeypatch.context() as patcher:
                patcher.setattr(
                    prediction_module,
                    "_write_parquet" if stage == "parquet" else "_write_exclusive",
                    hostile,
                )
                with pytest.raises(ValueError) as caught:
                    build_development_example_prediction_artifact(
                        **kwargs, output_root=output
                    )
            assert str(caught.value) == "M3_PREDICTION_ARTIFACT_INVALID"
            assert caught.value.__cause__ is None
            assert caught.value.__context__ is None
            assert marker not in repr(caught.value)
            assert not any(output.iterdir())


@pytest.mark.parametrize(
    ("target_name", "sentinel"),
    [
        ("predictions.parquet", b"PARQUET_COMPETITOR"),
        ("prediction_manifest.json", b"MANIFEST_COMPETITOR"),
    ],
)
def test_r2_concurrent_exclusive_create_never_clobbers_or_deletes_competitor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    target_name: str, sentinel: bytes,
) -> None:
    context = _context(tmp_path, monkeypatch)
    output = context["common"] / f"formal-r2-race-{target_name}"
    output.mkdir()
    target = output / target_name
    real_predict = prediction_module.predict_fitted_model

    def racing_predict(**kwargs: Any) -> tuple[float, ...]:
        target.write_bytes(sentinel)
        return real_predict(**kwargs)

    monkeypatch.setattr(
        prediction_module, "predict_fitted_model", racing_predict
    )
    with pytest.raises(ValueError) as caught:
        build_prediction_artifact(**context["kwargs"], output_root=output)
    assert str(caught.value) == "M3_PREDICTION_ROLLBACK_FAILED"
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert target.read_bytes() == sentinel
    assert {path.name for path in output.iterdir()} == {target_name}


def test_r2_rollback_unlink_failure_has_distinct_stable_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path, monkeypatch)
    output = context["common"] / "formal-r2-rollback-unlink"
    output.mkdir()
    real_unlink = prediction_module.ArtifactPublication._unlink_entry
    marker = "PRIVATE_ROLLBACK_UNLINK"

    def manifest_failure(*_: Any, **__: Any) -> None:
        raise RuntimeError("PRIVATE_MANIFEST_WRITER")

    def hostile_unlink(publication: Any, name: str) -> None:
        if name == "predictions.parquet":
            raise PermissionError(marker)
        real_unlink(publication, name)

    monkeypatch.setattr(prediction_module, "_write_exclusive", manifest_failure)
    monkeypatch.setattr(
        prediction_module.ArtifactPublication, "_unlink_entry", hostile_unlink
    )
    with pytest.raises(ValueError) as caught:
        build_prediction_artifact(**context["kwargs"], output_root=output)
    assert str(caught.value) == "M3_PREDICTION_ROLLBACK_FAILED"
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert marker not in repr(caught.value)
    assert {path.name for path in output.iterdir()} == {"predictions.parquet"}


def test_r2_real_copied_model_root_is_rejected_before_lightgbm_for_g5b(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path, monkeypatch)
    root, receipt, _ = _build_and_publish(context, suffix="copied-root-base")
    copied_root = context["common"] / "formal-r2-copied-model"
    shutil.copytree(context["model"].root, copied_root)
    copied = replace(context["model"], root=copied_root.resolve(strict=True))
    copied_kwargs = {**context["kwargs"], "model": copied}
    output = context["common"] / "formal-r2-copied-model-output"
    output.mkdir()
    lightgbm_calls = 0

    def hostile_lightgbm() -> Any:
        nonlocal lightgbm_calls
        lightgbm_calls += 1
        raise AssertionError("LightGBM must not load for copied root")

    monkeypatch.setattr(model_module, "_lightgbm", hostile_lightgbm)
    with pytest.raises(ValueError, match="^M3_PREDICTION_ARTIFACT_INVALID$"):
        build_prediction_artifact(**copied_kwargs, output_root=output)
    assert lightgbm_calls == 0 and not any(output.iterdir())
    with pytest.raises(ValueError, match="^M3_PREDICTION_ARTIFACT_INVALID$"):
        verify_prediction_artifact(
            root=root, receipt_path=receipt, **copied_kwargs
        )
    assert lightgbm_calls == 0


def test_r3_formal_prediction_root_replacement_is_blocked_or_rolled_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path, monkeypatch)
    output = context["common"] / "formal-r3-root-race"
    moved = context["common"] / "formal-r3-root-race-moved"
    output.mkdir()
    real_predict = prediction_module.predict_fitted_model
    replacement_succeeded = False
    writer_calls = 0
    real_write_stream = ArtifactPublication.write_stream

    def counted_write_stream(
        self: ArtifactPublication, name: str, writer: Any,
    ) -> None:
        def counted(stream: Any) -> object:
            nonlocal writer_calls
            writer_calls += 1
            return writer(stream)

        real_write_stream(self, name, counted)

    monkeypatch.setattr(ArtifactPublication, "write_stream", counted_write_stream)

    def attacking_predict(**kwargs: Any) -> tuple[float, ...]:
        nonlocal replacement_succeeded
        try:
            os.rename(output, moved)
            output.mkdir()
            replacement_succeeded = True
        except OSError:
            replacement_succeeded = False
        return real_predict(**kwargs)

    monkeypatch.setattr(
        prediction_module, "predict_fitted_model", attacking_predict
    )
    if os.name == "nt":
        build_prediction_artifact(**context["kwargs"], output_root=output)
        assert not replacement_succeeded
        assert {path.name for path in output.iterdir()} == {
            "predictions.parquet",
            "prediction_manifest.json",
        }
        assert not moved.exists()
    else:
        with pytest.raises(
            ValueError, match="^M3_PREDICTION_ARTIFACT_INVALID$"
        ):
            build_prediction_artifact(**context["kwargs"], output_root=output)
        assert replacement_succeeded
        assert writer_calls == 0
        assert not any(output.iterdir()) and not any(moved.iterdir())


def test_r3_development_prediction_root_replacement_is_blocked_or_rolled_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    kwargs, common = _development_build_context(tmp_path, monkeypatch)
    output = common / "development-r3-root-race"
    moved = common / "development-r3-root-race-moved"
    output.mkdir()
    real_predict = prediction_module.predict_development_example_fitted_model
    replacement_succeeded = False

    def attacking_predict(**predict_kwargs: Any) -> tuple[float, ...]:
        nonlocal replacement_succeeded
        try:
            os.rename(output, moved)
            output.mkdir()
            replacement_succeeded = True
        except OSError:
            replacement_succeeded = False
        return real_predict(**predict_kwargs)

    monkeypatch.setattr(
        prediction_module,
        "predict_development_example_fitted_model",
        attacking_predict,
    )
    if os.name == "nt":
        build_development_example_prediction_artifact(
            **kwargs, output_root=output
        )
        assert not replacement_succeeded
        assert {path.name for path in output.iterdir()} == {
            "predictions.parquet",
            "prediction_manifest.json",
        }
        assert not moved.exists()
    else:
        with pytest.raises(
            ValueError, match="^M3_PREDICTION_ARTIFACT_INVALID$"
        ):
            build_development_example_prediction_artifact(
                **kwargs, output_root=output
            )
        assert replacement_succeeded
        assert not any(output.iterdir()) and not any(moved.iterdir())


def test_r3_second_prediction_builder_is_rejected_before_predict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path, monkeypatch)
    output = context["common"] / "formal-r3-exclusive-lease"
    output.mkdir()
    real_predict = prediction_module.predict_fitted_model
    predict_calls = 0
    nested_checked = False

    def predict_with_nested_builder(**kwargs: Any) -> tuple[float, ...]:
        nonlocal predict_calls, nested_checked
        predict_calls += 1
        if not nested_checked:
            nested_checked = True
            with pytest.raises(
                ValueError, match="^M3_PREDICTION_ARTIFACT_INVALID$"
            ):
                build_prediction_artifact(
                    **context["kwargs"], output_root=output
                )
            assert predict_calls == 1
        return real_predict(**kwargs)

    monkeypatch.setattr(
        prediction_module, "predict_fitted_model", predict_with_nested_builder
    )
    build_prediction_artifact(**context["kwargs"], output_root=output)
    assert nested_checked and predict_calls == 1


def test_public_predict_uses_real_saved_native_lightgbm(tmp_path: Path) -> None:
    lgb = model_module._lightgbm()
    values = np.array(
        [[0.0, 1.0], [1.0, 0.0], [2.0, 1.0], [3.0, 0.0]],
        dtype=np.float64,
    )
    labels = np.array([0.0, 1.0, 2.0, 3.0], dtype=np.float64)
    dataset = lgb.Dataset(values, label=labels, feature_name=["a", "b"])
    booster = lgb.train(
        {
            "objective": "regression", "metric": "l2", "device_type": "cpu",
            "deterministic": True, "force_col_wise": True, "num_threads": 1,
            "verbosity": -1, "min_data_in_leaf": 1,
        },
        dataset, num_boost_round=3, valid_sets=[dataset],
        valid_names=["validation"],
    )
    root = tmp_path / "native-formal-model"
    root.mkdir()
    model_path = root / "model.txt"
    booster.save_model(str(model_path), num_iteration=3)
    curve_path = root / "validation_curve.parquet"
    pl.DataFrame(
        {"iteration": [1, 2, 3], "validation_l2": [1.0, 0.5, 0.25]},
        schema={"iteration": pl.Int64, "validation_l2": pl.Float64},
    ).write_parquet(curve_path)
    manifest = ModelManifestV1(
        schema_version="m3-lightgbm-model-v1", experiment_key="1" * 64,
        work_key="2" * 64, snapshot_id="3" * 64,
        provider_receipt_sha256="4" * 64, fold="fold_001",
        horizon_sessions=5, model="lightgbm", model_version="native-test-v1",
        alignment_manifest_sha256="5" * 64,
        feature_manifest_sha256="6" * 64,
        label_manifest_sha256="7" * 64,
        input_feature_schema_sha256="8" * 64,
        selected_feature_names=("a", "b"),
        selected_feature_schema_sha256=feature_schema_sha256(names=("a", "b")),
        params_sha256="9" * 64, train_row_keys_sha256="a" * 64,
        validation_row_keys_sha256="b" * 64, train_matrix_sha256="c" * 64,
        validation_matrix_sha256="d" * 64, train_labels_sha256="e" * 64,
        validation_labels_sha256="f" * 64, lightgbm_version=lgb.__version__,
        best_iteration=3, best_validation_l2=0.25,
        model_sha256=_sha(model_path), validation_curve_sha256=_sha(curve_path),
    )
    metadata_path = root / "model.metadata.json"
    metadata_path.write_bytes(_canonical(asdict(manifest)))
    model = VerifiedModelArtifact(
        root=root, manifest=manifest, manifest_sha256=_sha(metadata_path),
        model_receipt_sha256="0" * 64,
    )
    dates = [date(2025, 1, 2)] * 2 + [date(2025, 1, 3)] * 2
    symbols = ["600001.SH", "600002.SH", "600001.SH", "600002.SH"]
    index = pd.MultiIndex.from_arrays(
        [dates, symbols], names=["as_of", "symbol"]
    )
    inference = InferenceSegment(
        name="test",
        features=pd.DataFrame(values, columns=["a", "b"], index=index),
        metadata=pl.DataFrame(
            {"as_of": dates, "symbol": symbols},
            schema={"as_of": pl.Date, "symbol": pl.String},
        ),
    )
    scores = predict_fitted_model(model=model, inference=inference)
    assert len(scores) == 4 and all(math.isfinite(value) for value in scores)
