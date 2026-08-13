"""G5A development LightGBM model artifact contract tests."""

from __future__ import annotations

import hashlib
import importlib.util
import inspect
import json
import math
import sys
from collections import OrderedDict, defaultdict
from dataclasses import replace
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import numpy as np
import pandas as pd
import pytest

import quant.research.m3 as m3_public
import quant.research.m3.model as model_module
from quant.research.m3.alignment import build_development_example_inference_segment
from quant.research.m3.config import load_m3_config
from quant.research.m3.contracts import (
    InferenceUpstreamPaths,
    LightgbmTrainingSpec,
    ModelUpstreamPaths,
)
from quant.research.m3.development_example import (
    VerifiedDevelopmentExampleModelArtifact,
)
from quant.research.m3.model import (
    build_development_example_model_artifact,
    build_lightgbm_training_spec,
    predict_development_example_fitted_model,
    verify_development_example_model_artifact,
)
from quant.research.m3.run_state import publish_stage_receipt

_ALIGNMENT_SUPPORT_SPEC = importlib.util.spec_from_file_location(
    "m3_alignment_test_support_for_model",
    Path(__file__).with_name("test_m3_alignment.py"),
)
assert _ALIGNMENT_SUPPORT_SPEC is not None and _ALIGNMENT_SUPPORT_SPEC.loader is not None
_ALIGNMENT_SUPPORT = importlib.util.module_from_spec(_ALIGNMENT_SUPPORT_SPEC)
_ALIGNMENT_SUPPORT_SPEC.loader.exec_module(_ALIGNMENT_SUPPORT)


class _FakeDataset:
    def __init__(
        self,
        data: Any,
        label: Any = None,
        *,
        feature_name: Any = "auto",
        **kwargs: Any,
    ) -> None:
        self.data = data
        self.label = label
        self.feature_name = feature_name
        self.kwargs = kwargs


class _FakeBooster:
    best_iteration = 2
    best_score = {"validation": {"l2": 0.25}}

    def __init__(self, *, model_file: str | None = None, calls: list[Any] | None = None) -> None:
        self.model_file = model_file
        self._calls = calls if calls is not None else []

    def save_model(
        self,
        filename: str,
        num_iteration: int | None = None,
        **kwargs: Any,
    ) -> None:
        self._calls.append(("save_model", filename, num_iteration, kwargs))
        Path(filename).write_bytes(b"fake-lightgbm-model\nbest_iteration=2\n")

    def predict(self, data: Any, *, num_iteration: int | None = None, **kwargs: Any) -> Any:
        self._calls.append(("predict", data, num_iteration, kwargs))
        return np.arange(len(data), dtype=np.float64) + 0.125


def _install_fake_lightgbm(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    calls: list[Any] = []
    module = ModuleType("lightgbm")
    module.__version__ = "4.6.0-test"
    module.Dataset = _FakeDataset

    def early_stopping(
        stopping_rounds: int,
        *,
        first_metric_only: bool = False,
        verbose: bool = True,
        min_delta: float = 0.0,
    ) -> tuple[Any, ...]:
        callback = (
            "early_stopping",
            stopping_rounds,
            first_metric_only,
            verbose,
            min_delta,
        )
        calls.append(callback)
        return callback

    def record_evaluation(evaluations: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        callback = ("record_evaluation", evaluations)
        calls.append(callback)
        return callback

    def train(
        params: dict[str, Any],
        train_set: _FakeDataset,
        *,
        num_boost_round: int,
        valid_sets: list[_FakeDataset],
        valid_names: list[str],
        callbacks: list[Any],
        **kwargs: Any,
    ) -> _FakeBooster:
        calls.append(
            (
                "train",
                params,
                train_set,
                num_boost_round,
                valid_sets,
                valid_names,
                callbacks,
                kwargs,
            )
        )
        for callback in callbacks:
            if isinstance(callback, tuple) and callback[0] == "record_evaluation":
                callback[1].update({"validation": {"l2": [0.5, 0.25, 0.4]}})
        return _FakeBooster(calls=calls)

    def load_booster(*, model_file: str) -> _FakeBooster:
        calls.append(("Booster", model_file))
        return _FakeBooster(model_file=model_file, calls=calls)

    module.early_stopping = early_stopping
    module.record_evaluation = record_evaluation
    module.train = train
    module.Booster = load_booster
    monkeypatch.setitem(sys.modules, "lightgbm", module)
    return calls


def _model_inputs(alignment_bundle: tuple[Any, ...]) -> list[tuple[str, Path]]:
    feature_bundle, feature, label, _, _, _, _, alignment_receipt, _ = alignment_bundle
    experiment = feature_bundle[9]
    feature_receipt = cast(Path, feature_bundle[15])
    label_receipt = alignment_bundle[5].label_receipt_path
    alignment_root = cast(Path, alignment_bundle[6])
    return [
        ("root", alignment_root / "alignment_manifest.json"),
        ("root", cast(Path, alignment_receipt)),
        ("root", feature.root / "feature_manifest.json"),
        ("root", feature_receipt),
        ("root", label.root / "label_manifest.json"),
        ("root", label_receipt),
        ("root", experiment.root / "experiment_manifest.json"),
    ]


def _model_outputs(root: Path) -> list[tuple[str, Path]]:
    return [
        ("root", root / name)
        for name in ("model.txt", "validation_curve.parquet", "model.metadata.json")
    ]


def _build_model_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Any, ...]:
    calls = _install_fake_lightgbm(monkeypatch)
    alignment_bundle = _ALIGNMENT_SUPPORT._build_alignment_bundle(tmp_path, monkeypatch)
    alignment = _ALIGNMENT_SUPPORT._verify(alignment_bundle)
    feature_bundle, feature, label, label_spec, alignment_spec, alignment_upstream, _, _, _ = (
        alignment_bundle
    )
    common, roots = cast(Path, feature_bundle[0]), feature_bundle[1]
    config, experiment = feature_bundle[7], feature_bundle[9]
    spec = build_lightgbm_training_spec(config)
    root = common / f"development-example-model-{alignment_spec.work_key}"
    root.mkdir()
    manifest = build_development_example_model_artifact(
        alignment=alignment,
        feature=feature,
        label=label,
        experiment=experiment,
        config=config,
        spec=spec,
        output_root=root,
    )
    receipt = common / "receipts" / "development-model" / f"{alignment_spec.work_key}.json"
    receipt.parent.mkdir(parents=True)
    publish_stage_receipt(
        receipt_path=receipt,
        stage="development-model",
        scope="WORK",
        scope_key=alignment_spec.work_key,
        artifact_roots=roots,
        inputs=_model_inputs(alignment_bundle),
        outputs=_model_outputs(root),
    )
    upstream_paths = ModelUpstreamPaths(
        alignment_receipt_path=cast(Path, alignment_bundle[7]),
        alignment_upstream_paths=alignment_upstream,
    )
    return (
        alignment_bundle,
        alignment,
        spec,
        upstream_paths,
        root,
        receipt,
        manifest,
        calls,
    )


def _verify(bundle: tuple[Any, ...], *, spec: Any = None, receipt: Path | None = None) -> Any:
    alignment_bundle, alignment, default_spec, upstream_paths, root, default_receipt, _, _ = (
        bundle
    )
    feature_bundle, feature, label, label_spec, alignment_spec, _, _, _, _ = alignment_bundle
    (
        _, roots, release, snapshot, snapshot_spec, provider, provider_spec,
        config, experiment_spec, experiment, fold_spec, folds, feature_spec,
        _, _, _, _,
    ) = feature_bundle
    return verify_development_example_model_artifact(
        root=root,
        receipt_path=receipt or default_receipt,
        alignment=alignment,
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
        alignment_spec=alignment_spec,
        spec=spec or default_spec,
        upstream_paths=upstream_paths,
        artifact_roots=roots,
    )


def test_package_root_exports_model_contract_without_lightgbm() -> None:
    assert m3_public.LightgbmTrainingSpec is LightgbmTrainingSpec
    assert m3_public.ModelUpstreamPaths is ModelUpstreamPaths
    assert m3_public.VerifiedDevelopmentExampleModelArtifact is not None
    assert "lightgbm" not in sys.modules
    assert "test" not in inspect.signature(
        build_development_example_model_artifact
    ).parameters


def test_training_spec_is_exact_sorted_and_controls_are_separate(
) -> None:
    config = load_m3_config(
        Path(__file__).parents[2] / "configs" / "research" / "m3_qlib_example.toml"
    )
    spec = build_lightgbm_training_spec(config)
    params = dict(spec.booster_params)
    assert tuple(name for name, _ in spec.booster_params) == tuple(sorted(params))
    assert params == {
        "bagging_fraction": 0.9,
        "bagging_freq": 1,
        "bagging_seed": 20260712,
        "data_random_seed": 20260712,
        "deterministic": True,
        "device_type": "cpu",
        "feature_fraction": 0.9,
        "feature_fraction_seed": 20260712,
        "force_col_wise": True,
        "learning_rate": 0.05,
        "max_depth": -1,
        "metric": "l2",
        "num_leaves": 31,
        "num_threads": 4,
        "objective": "regression",
        "seed": 20260712,
    }
    assert spec.model_version == "alpha158_lgb_v1"
    assert spec.num_boost_round == 500
    assert spec.early_stopping_rounds == 50
    assert spec.early_stopping_min_delta == 0.0
    assert not {"num_boost_round", "early_stopping_rounds", "early_stopping_min_delta"} & params.keys()


def test_training_frames_allow_nan_and_reject_leakage_or_numeric_drift() -> None:
    train_index = pd.MultiIndex.from_tuples(
        [(pd.Timestamp("2026-01-05"), "000001.SZ"), (pd.Timestamp("2026-01-06"), "600000.SH")],
        names=["as_of", "symbol"],
    )
    validation_index = pd.MultiIndex.from_tuples(
        [(pd.Timestamp("2026-02-02"), "000001.SZ")],
        names=["as_of", "symbol"],
    )
    train_x = pd.DataFrame(
        {"ALPHA001": [np.nan, 1.0], "ALPHA002": [2.0, 3.0]},
        index=train_index,
        dtype="float64",
    )
    validation_x = pd.DataFrame(
        {"ALPHA001": [4.0], "ALPHA002": [5.0]},
        index=validation_index,
        dtype="float64",
    )
    train_y = pd.Series([0.1, 0.2], index=train_index, dtype="float64")
    validation_y = pd.Series([0.3], index=validation_index, dtype="float64")
    model_module._validate_training_frames(train_x, train_y, validation_x, validation_y)

    invalid_inputs = (
        (train_x.replace({1.0: np.inf}), train_y, validation_x, validation_y),
        (train_x, train_y.replace({0.1: np.nan}), validation_x, validation_y),
        (train_x, train_y, validation_x[["ALPHA002", "ALPHA001"]], validation_y),
        (train_x.astype("float32"), train_y, validation_x, validation_y),
        (
            train_x,
            train_y,
            validation_x.set_axis(pd.Index([0])),
            validation_y.set_axis(pd.Index([0])),
        ),
        (
            pd.concat([train_x.iloc[:1], train_x.iloc[:1]]),
            pd.concat([train_y.iloc[:1], train_y.iloc[:1]]),
            validation_x,
            validation_y,
        ),
        (train_x, train_y, validation_x.set_axis(train_index[:1]), validation_y.set_axis(train_index[:1])),
    )
    for args in invalid_inputs:
        with pytest.raises(ValueError):
            model_module._validate_training_frames(*args)


def test_model_build_uses_only_validation_l2_and_preserves_nan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_load = model_module.load_development_example_supervised_segment

    def load_with_one_nan(**kwargs: Any) -> Any:
        segment = real_load(**kwargs)
        if segment.name != "train":
            return segment
        features = segment.features.copy()
        features.iloc[0, 0] = np.nan
        return replace(segment, features=features)

    monkeypatch.setattr(
        model_module,
        "load_development_example_supervised_segment",
        load_with_one_nan,
    )
    bundle = _build_model_bundle(tmp_path, monkeypatch)
    _, _, spec, _, root, _, manifest, calls = bundle
    train_call = next(item for item in calls if item[0] == "train")
    _, params, train_set, rounds, valid_sets, valid_names, callbacks, kwargs = train_call
    assert params == dict(spec.booster_params)
    assert rounds == spec.num_boost_round
    assert valid_names == ["validation"]
    assert len(valid_sets) == 1 and valid_sets[0] is not train_set
    assert kwargs == {}
    assert any(item[0] == "early_stopping" for item in callbacks)
    assert any(item[0] == "record_evaluation" for item in callbacks)
    assert np.isnan(np.asarray(train_set.data, dtype=np.float64)).any()
    assert not np.isinf(np.asarray(train_set.data, dtype=np.float64)).any()
    assert np.isfinite(np.asarray(train_set.label, dtype=np.float64)).all()
    assert list(train_set.data.columns) == list(manifest.selected_feature_names)
    assert list(valid_sets[0].data.columns) == list(manifest.selected_feature_names)
    assert all(dtype == np.dtype("float64") for dtype in train_set.data.dtypes)
    assert all(dtype == np.dtype("float64") for dtype in valid_sets[0].data.dtypes)
    assert train_set.data.index.is_unique and valid_sets[0].data.index.is_unique
    assert train_set.data.index.intersection(valid_sets[0].data.index).empty
    assert manifest.best_iteration == 2
    assert manifest.best_validation_l2 == 0.25
    assert manifest.lightgbm_version == "4.6.0-test"


def test_model_builder_accepts_native_lightgbm_best_score_mappings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class NativeMappingBooster(_FakeBooster):
        best_score = defaultdict(
            OrderedDict,
            {"validation": OrderedDict({"l2": np.float64(0.25)})},
        )

    calls = _install_fake_lightgbm(monkeypatch)
    lightgbm = cast(Any, sys.modules["lightgbm"])
    real_train = lightgbm.train

    def native_mapping_train(*args: Any, **kwargs: Any) -> NativeMappingBooster:
        real_train(*args, **kwargs)
        return NativeMappingBooster(calls=calls)

    lightgbm.train = native_mapping_train
    alignment_bundle = _ALIGNMENT_SUPPORT._build_alignment_bundle(tmp_path, monkeypatch)
    alignment = _ALIGNMENT_SUPPORT._verify(alignment_bundle)
    feature_bundle, feature, label, _, _, _, _, _, _ = alignment_bundle
    config, experiment = feature_bundle[7], feature_bundle[9]
    output_root = tmp_path / "native-mapping-model"
    output_root.mkdir()

    manifest = build_development_example_model_artifact(
        alignment=alignment,
        feature=feature,
        label=label,
        experiment=experiment,
        config=config,
        spec=build_lightgbm_training_spec(config),
        output_root=output_root,
    )

    assert manifest.best_validation_l2 == 0.25
    assert {path.name for path in output_root.iterdir()} == {
        "model.txt",
        "validation_curve.parquet",
        "model.metadata.json",
    }


def test_model_closed_loop_receipt_and_prediction_uses_best_iteration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _build_model_bundle(tmp_path, monkeypatch)
    verified = _verify(bundle)
    alignment_bundle, _, _, _, root, receipt, built_manifest, calls = bundle
    feature_bundle, feature, _, _, _, _, _, _, _ = alignment_bundle
    (
        _, roots, release, snapshot, snapshot_spec, provider, provider_spec,
        config, experiment_spec, experiment, fold_spec, folds, feature_spec,
        feature_upstream, _, feature_receipt, _,
    ) = feature_bundle
    assert isinstance(verified, VerifiedDevelopmentExampleModelArtifact)
    assert verified.release_kind == "development_example"
    assert verified.formal_gate_eligible is False
    assert verified.manifest == built_manifest
    assert verified.model_receipt_sha256 == hashlib.sha256(receipt.read_bytes()).hexdigest()

    payload = json.loads(receipt.read_bytes())
    outputs = {item["relative_path"]: item["sha256"] for item in payload["outputs"]}
    for _, path in _model_outputs(root):
        relative = path.relative_to(cast(Path, feature_bundle[0])).as_posix()
        assert outputs[relative] == hashlib.sha256(path.read_bytes()).hexdigest()

    inference = build_development_example_inference_segment(
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
            feature_receipt_path=feature_receipt,
            feature_upstream_paths=feature_upstream,
        ),
        artifact_roots=roots,
    )
    scores = predict_development_example_fitted_model(model=verified, inference=inference)
    assert scores == tuple(np.arange(len(inference.features), dtype=np.float64) + 0.125)
    predict_call = next(item for item in reversed(calls) if item[0] == "predict")
    assert predict_call[2] == verified.manifest.best_iteration


@pytest.mark.parametrize(
    "mutate",
    [
        lambda spec: replace(spec, num_boost_round=True),
        lambda spec: replace(spec, early_stopping_rounds=500),
        lambda spec: replace(spec, early_stopping_min_delta=math.inf),
        lambda spec: replace(spec, booster_params=spec.booster_params + (("seed", 9),)),
    ],
)
def test_model_rejects_invalid_training_specs(
    mutate: Any,
) -> None:
    config = load_m3_config(
        Path(__file__).parents[2] / "configs" / "research" / "m3_qlib_example.toml"
    )
    spec = build_lightgbm_training_spec(config)
    with pytest.raises(ValueError):
        mutate(spec)


def test_model_builder_rejects_config_drift_control_params_missing_seed_and_gpu(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_lightgbm(monkeypatch)
    alignment_bundle = _ALIGNMENT_SUPPORT._build_alignment_bundle(tmp_path, monkeypatch)
    alignment = _ALIGNMENT_SUPPORT._verify(alignment_bundle)
    feature_bundle, feature, label, _, _, _, _, _, _ = alignment_bundle
    common, config, experiment = cast(Path, feature_bundle[0]), feature_bundle[7], feature_bundle[9]
    valid = build_lightgbm_training_spec(config)
    invalid = (
        replace(valid, model_version="drift"),
        replace(
            valid,
            booster_params=tuple(
                sorted((*valid.booster_params, ("num_boost_round", 7)))
            ),
        ),
        replace(
            valid,
            booster_params=tuple(
                item for item in valid.booster_params if item[0] != "bagging_seed"
            ),
        ),
        replace(
            valid,
            booster_params=tuple(
                (name, "gpu" if name == "device_type" else value)
                for name, value in valid.booster_params
            ),
        ),
    )
    for index, spec in enumerate(invalid):
        output = common / f"model-reject-{index}"
        output.mkdir()
        with pytest.raises(ValueError):
            build_development_example_model_artifact(
                alignment=alignment,
                feature=feature,
                label=label,
                experiment=experiment,
                config=config,
                spec=spec,
                output_root=output,
            )
        assert not any(output.iterdir())

    lightgbm = cast(Any, sys.modules["lightgbm"])
    real_train = lightgbm.train

    def inconsistent_train(*args: Any, **kwargs: Any) -> _FakeBooster:
        booster = cast(_FakeBooster, real_train(*args, **kwargs))
        booster.best_score = {"validation": {"l2": 0.25000000000000006}}
        return booster

    lightgbm.train = inconsistent_train
    output = common / "model-reject-best-score-drift"
    output.mkdir()
    with pytest.raises(ValueError):
        build_development_example_model_artifact(
            alignment=alignment,
            feature=feature,
            label=label,
            experiment=experiment,
            config=config,
            spec=valid,
            output_root=output,
        )
    assert not any(output.iterdir())


def test_model_no_clobber_and_cross_work_or_horizon_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _build_model_bundle(tmp_path, monkeypatch)
    alignment_bundle, alignment, spec, _, root, _, _, _ = bundle
    feature_bundle, feature, label, _, _, _, _, _, _ = alignment_bundle
    config, experiment = feature_bundle[7], feature_bundle[9]
    before = {path.name: path.read_bytes() for path in root.iterdir()}
    with pytest.raises(ValueError):
        build_development_example_model_artifact(
            alignment=alignment,
            feature=feature,
            label=label,
            experiment=experiment,
            config=config,
            spec=spec,
            output_root=root,
        )
    assert {path.name: path.read_bytes() for path in root.iterdir()} == before

    with pytest.raises(ValueError):
        _verify(bundle, spec=replace(spec, model_version="cross-work"))
    drifted_alignment = replace(
        alignment,
        manifest=replace(alignment.manifest, horizon_sessions=10),
    )
    drifted_bundle = (bundle[0], drifted_alignment, *bundle[2:])
    with pytest.raises(ValueError):
        _verify(drifted_bundle)


def test_model_verifier_rejects_any_output_tamper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _build_model_bundle(tmp_path, monkeypatch)
    for relative_path in ("model.txt", "validation_curve.parquet", "model.metadata.json"):
        path = cast(Path, bundle[4]) / relative_path
        original = path.read_bytes()
        path.write_bytes(original + b"drift")
        with pytest.raises(ValueError):
            _verify(bundle)
        path.write_bytes(original)
        _verify(bundle)


def test_model_receipt_requires_exact_direct_closure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _build_model_bundle(tmp_path, monkeypatch)
    alignment_bundle, _, _, _, root, _, _, _ = bundle
    feature_bundle = alignment_bundle[0]
    common, roots = cast(Path, feature_bundle[0]), feature_bundle[1]
    decoy = common / "model-decoy.txt"
    decoy.write_text("not a model input", encoding="utf-8")
    receipt = common / "receipts" / "development-model" / "extra-input.json"
    publish_stage_receipt(
        receipt_path=receipt,
        stage="development-model",
        scope="WORK",
        scope_key=alignment_bundle[4].work_key,
        artifact_roots=roots,
        inputs=[*_model_inputs(alignment_bundle), ("root", decoy)],
        outputs=_model_outputs(root),
    )
    with pytest.raises(ValueError):
        _verify(bundle, receipt=receipt)
