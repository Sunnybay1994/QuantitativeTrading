"""Formal G5A native LightGBM model artifact contract tests."""

from __future__ import annotations

import hashlib
import importlib.util
import inspect
import json
import os
import shutil
import subprocess
import sys
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any, cast

import numpy as np
import polars as pl
import pytest

import quant.research.m3 as m3_public
import quant.research.m3._artifact_publication as publication_module
from quant.research.m3._artifact_publication import (
    ArtifactPublication,
    ArtifactPublicationError,
    ArtifactRollbackError,
)
import quant.research.m3.model as model_module
from quant.data.m3_release import VerifiedG1Release
from quant.research.m3.contracts import (
    InferenceSegment,
    ModelUpstreamPaths,
    VerifiedAlignmentArtifact,
    VerifiedModelArtifact,
    VerifiedProviderArtifact,
    VerifiedSnapshotArtifact,
)
from quant.research.m3.model import (
    build_lightgbm_training_spec,
    build_model_artifact,
    predict_fitted_model,
    verify_model_artifact,
)
from quant.research.m3.run_state import publish_stage_receipt

_MODEL_SUPPORT_SPEC = importlib.util.spec_from_file_location(
    "m3_development_model_support_for_formal",
    Path(__file__).with_name("test_m3_model_artifact.py"),
)
assert _MODEL_SUPPORT_SPEC is not None and _MODEL_SUPPORT_SPEC.loader is not None
_MODEL_SUPPORT = importlib.util.module_from_spec(_MODEL_SUPPORT_SPEC)
_MODEL_SUPPORT_SPEC.loader.exec_module(_MODEL_SUPPORT)
_ALIGNMENT_SUPPORT = _MODEL_SUPPORT._ALIGNMENT_SUPPORT


def test_r4_publication_lease_is_exclusive_and_anchors_root_entity(
    tmp_path: Path,
) -> None:
    root = tmp_path / "lease-root"
    moved = tmp_path / "lease-root-moved"
    root.mkdir()
    publication = ArtifactPublication(root)
    publication.__enter__()
    with pytest.raises(ArtifactPublicationError):
        with ArtifactPublication(root):
            raise AssertionError("second lease entered")

    if os.name == "nt":
        with pytest.raises(OSError):
            os.rename(root, moved)
        publication.write_bytes("owned.bin", b"owned")
        publication.commit({"owned.bin"})
        publication.__exit__(None, None, None)
        assert (root / "owned.bin").read_bytes() == b"owned"
        assert not moved.exists()
    else:
        os.rename(root, moved)
        root.mkdir()
        with pytest.raises(ArtifactPublicationError):
            publication.write_bytes("owned.bin", b"owned")
        publication.__exit__(None, None, None)
        assert not any(root.iterdir())
        assert not any(moved.iterdir())


def test_r4_publication_rejects_link_root_without_creating_lease(
    tmp_path: Path,
) -> None:
    real = tmp_path / "real-root"
    link = tmp_path / "link-root"
    real.mkdir()
    if os.name == "nt":
        result = subprocess.run(
            ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(real)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            pytest.skip("host does not permit junction creation")
    else:
        link.symlink_to(real, target_is_directory=True)
    with pytest.raises(ArtifactPublicationError):
        with ArtifactPublication(link):
            raise AssertionError("link root entered")
    assert not any(real.iterdir())
    if os.name == "nt":
        link.rmdir()
    else:
        link.unlink()
    assert not os.path.lexists(link)
    assert real.is_dir() and not any(real.iterdir())


def test_r4_deleted_lease_fails_closed_and_cannot_admit_second_builder(
    tmp_path: Path,
) -> None:
    root = tmp_path / "deleted-lease-root"
    root.mkdir()
    publication = ArtifactPublication(root)
    publication.__enter__()
    [marker] = tuple(root.iterdir())
    marker.unlink()
    with pytest.raises(ArtifactPublicationError):
        with ArtifactPublication(root):
            raise AssertionError("deleted lease admitted a second builder")
    with pytest.raises(ArtifactRollbackError):
        publication.__exit__(None, None, None)
    assert not any(root.iterdir())


def test_r4_replaced_owned_file_is_not_deleted_during_rollback(
    tmp_path: Path,
) -> None:
    root = tmp_path / "replaced-owned-file-root"
    root.mkdir()
    publication = ArtifactPublication(root)
    publication.__enter__()
    publication.write_bytes("owned.bin", b"owned")
    target = root / "owned.bin"
    target.unlink()
    target.write_bytes(b"competitor")
    with pytest.raises(ArtifactPublicationError):
        publication.commit({"owned.bin"})
    with pytest.raises(ArtifactRollbackError):
        publication.__exit__(None, None, None)
    assert target.read_bytes() == b"competitor"


def test_r2_publication_rechecks_current_root_before_open(tmp_path: Path) -> None:
    root = tmp_path / "r2-pre-open-root"
    moved = tmp_path / "r2-pre-open-root-moved"
    root.mkdir()
    writer_calls = 0

    def writer(_: Any) -> None:
        nonlocal writer_calls
        writer_calls += 1

    if os.name == "nt":
        with ArtifactPublication(root):
            with pytest.raises(OSError):
                os.rename(root, moved)
        assert writer_calls == 0 and not moved.exists() and not any(root.iterdir())
        return

    with pytest.raises(ArtifactPublicationError):
        with ArtifactPublication(root) as publication:
            os.rename(root, moved)
            root.mkdir()
            publication.write_stream("owned.bin", writer)
    assert writer_calls == 0
    assert not any(root.iterdir()) and not any(moved.iterdir())


def test_r2_publication_rechecks_root_after_open_before_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "r2-post-open-root"
    moved = tmp_path / "r2-post-open-root-moved"
    root.mkdir()
    writer_calls = 0

    with pytest.raises(ArtifactPublicationError):
        with ArtifactPublication(root) as publication:
            real_require = publication._require_current_root
            require_calls = 0

            def current_root() -> None:
                nonlocal require_calls
                require_calls += 1
                if require_calls == 2:
                    if os.name == "nt":
                        raise ArtifactPublicationError
                    os.rename(root, moved)
                    root.mkdir()
                real_require()

            def writer(_: Any) -> None:
                nonlocal writer_calls
                writer_calls += 1

            monkeypatch.setattr(publication, "_require_current_root", current_root)
            publication.write_stream("owned.bin", writer)
    assert writer_calls == 0
    assert not any(root.iterdir())
    if os.name == "nt":
        assert not moved.exists()
    else:
        assert not moved.exists() or not any(moved.iterdir())


def _formal_alignment_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> tuple[Any, ...]:
    calls = _MODEL_SUPPORT._install_fake_lightgbm(monkeypatch)
    bundle = _ALIGNMENT_SUPPORT._build_alignment_bundle(tmp_path, monkeypatch)
    development_alignment = _ALIGNMENT_SUPPORT._verify(bundle)
    feature_bundle, _, _, label_spec, alignment_spec, alignment_upstream, root, _, _ = (
        bundle
    )
    feature, label, folds, experiment = _ALIGNMENT_SUPPORT._formal_nominals(bundle)
    common, roots = cast(Path, feature_bundle[0]), feature_bundle[1]
    formal_alignment_receipt = (
        common / "receipts" / "alignment" / f"{alignment_spec.work_key}.json"
    )
    formal_alignment_receipt.parent.mkdir(parents=True)
    publish_stage_receipt(
        receipt_path=formal_alignment_receipt, stage="alignment", scope="WORK",
        scope_key=alignment_spec.work_key, artifact_roots=roots,
        inputs=_ALIGNMENT_SUPPORT._alignment_inputs(feature_bundle, feature, label),
        outputs=_ALIGNMENT_SUPPORT._alignment_outputs(root),
    )
    alignment = VerifiedAlignmentArtifact(
        root=development_alignment.root,
        manifest=development_alignment.manifest,
        manifest_sha256=development_alignment.manifest_sha256,
        alignment_receipt_sha256=hashlib.sha256(
            formal_alignment_receipt.read_bytes()
        ).hexdigest(),
    )
    upstream = ModelUpstreamPaths(
        alignment_receipt_path=formal_alignment_receipt,
        alignment_upstream_paths=alignment_upstream,
    )
    return (
        bundle, feature_bundle, alignment, feature, label, folds, experiment,
        label_spec, alignment_spec, upstream, roots, common, calls,
    )


def _model_inputs(data: tuple[Any, ...]) -> list[tuple[str, Path]]:
    (
        _, feature_bundle, alignment, feature, label, _, experiment, _, _,
        upstream, _, _, _,
    ) = data
    return [
        ("root", alignment.root / "alignment_manifest.json"),
        ("root", upstream.alignment_receipt_path),
        ("root", feature.root / "feature_manifest.json"),
        ("root", cast(Path, feature_bundle[15])),
        ("root", label.root / "label_manifest.json"),
        ("root", upstream.alignment_upstream_paths.label_receipt_path),
        ("root", experiment.root / "experiment_manifest.json"),
    ]


def _model_outputs(root: Path) -> list[tuple[str, Path]]:
    return [
        ("root", root / name)
        for name in ("model.txt", "model.metadata.json", "validation_curve.parquet")
    ]


def _formal_placeholders() -> tuple[Any, Any, Any]:
    return (
        cast(VerifiedG1Release, VerifiedG1Release.__new__(VerifiedG1Release)),
        cast(
            VerifiedSnapshotArtifact,
            VerifiedSnapshotArtifact.__new__(VerifiedSnapshotArtifact),
        ),
        cast(
            VerifiedProviderArtifact,
            VerifiedProviderArtifact.__new__(VerifiedProviderArtifact),
        ),
    )


def _verify_kwargs(
    data: tuple[Any, ...], *, root: Path, receipt: Path,
) -> dict[str, Any]:
    (
        _, feature_bundle, alignment, feature, label, folds, experiment,
        label_spec, alignment_spec, upstream, roots, _, _,
    ) = data
    (
        _, _, _, _, snapshot_spec, _, provider_spec, config, experiment_spec,
        _, fold_spec, _, feature_spec, _, _, _, _,
    ) = feature_bundle
    release, snapshot, provider = _formal_placeholders()
    return {
        "root": root, "receipt_path": receipt, "release": release,
        "snapshot": snapshot, "snapshot_spec": snapshot_spec,
        "provider": provider, "provider_spec": provider_spec,
        "experiment": experiment, "experiment_spec": experiment_spec,
        "folds": folds, "fold_spec": fold_spec, "feature": feature,
        "feature_spec": feature_spec, "label": label, "label_spec": label_spec,
        "alignment": alignment, "alignment_spec": alignment_spec,
        "config": config, "spec": build_lightgbm_training_spec(config),
        "upstream_paths": upstream, "artifact_roots": roots,
    }


def _build_kwargs(data: tuple[Any, ...], *, output_root: Path) -> dict[str, Any]:
    kwargs = _verify_kwargs(
        data, root=output_root / "unused-root", receipt=output_root / "unused-receipt"
    )
    del kwargs["root"]
    del kwargs["receipt_path"]
    kwargs["output_root"] = output_root
    return kwargs


def test_formal_model_exports_and_delayed_import() -> None:
    assert m3_public.build_model_artifact is build_model_artifact
    assert m3_public.verify_model_artifact is verify_model_artifact
    assert m3_public.predict_fitted_model is predict_fitted_model
    subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import quant.research.m3; "
            "assert 'lightgbm' not in sys.modules",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "test" not in inspect.signature(build_model_artifact).parameters


def test_formal_model_build_verify_predict_and_fresh_alignment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = _formal_alignment_bundle(tmp_path, monkeypatch)
    (
        _, feature_bundle, alignment, feature, label, _, experiment, _,
        alignment_spec, _, roots, common, calls,
    ) = data
    root = common / "formal-model"
    root.mkdir()
    fresh_calls: list[dict[str, Any]] = []

    def fresh_alignment(**kwargs: Any) -> VerifiedAlignmentArtifact:
        fresh_calls.append(kwargs)
        assert kwargs["receipt_path"] == data[9].alignment_receipt_path
        return alignment

    monkeypatch.setattr(model_module, "verify_alignment_artifact", fresh_alignment)
    manifest = build_model_artifact(**_build_kwargs(data, output_root=root))
    assert {path.name for path in root.iterdir()} == {
        "model.txt", "model.metadata.json", "validation_curve.parquet",
    }
    receipt = common / "receipts" / "model" / f"{alignment_spec.work_key}.json"
    receipt.parent.mkdir(parents=True)
    publish_stage_receipt(
        receipt_path=receipt, stage="model", scope="WORK",
        scope_key=alignment_spec.work_key, artifact_roots=roots,
        inputs=_model_inputs(data), outputs=_model_outputs(root),
    )
    verified = verify_model_artifact(**_verify_kwargs(data, root=root, receipt=receipt))
    assert type(verified) is VerifiedModelArtifact
    assert verified.manifest == manifest
    assert len(fresh_calls) == 2

    test_frame = pl.read_parquet(feature.root / "test.parquet")
    names = feature.manifest.schema.selected_names
    test_frame = test_frame.filter(
        pl.any_horizontal(pl.col(name).is_not_nan() for name in names)
    )
    index = _MODEL_SUPPORT.pd.MultiIndex.from_arrays(
        [test_frame["as_of"].to_list(), test_frame["symbol"].to_list()],
        names=["as_of", "symbol"],
    )
    inference = InferenceSegment(
        name="test",
        features=test_frame.select(*names).to_pandas().set_axis(index),
        metadata=test_frame.select("as_of", "symbol"),
    )
    scores = predict_fitted_model(model=verified, inference=inference)
    assert scores == tuple(np.arange(len(inference.features), dtype=np.float64) + 0.125)
    predict_call = next(item for item in reversed(calls) if item[0] == "predict")
    assert predict_call[2] == manifest.best_iteration


def test_formal_model_fresh_alignment_failures_are_stable_and_redacted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = _formal_alignment_bundle(tmp_path, monkeypatch)
    alignment = data[2]
    alignment_spec = data[8]
    roots = data[10]
    common = data[11]
    calls = data[-1]

    def install_hostile(error: Exception) -> None:
        def hostile(**_: object) -> None:
            raise error

        monkeypatch.setattr(model_module, "verify_alignment_artifact", hostile)

    train_calls_before = sum(item[0] == "train" for item in calls)
    for index, error_type in enumerate((ValueError, RuntimeError)):
        marker = f"C:/TOKEN_BUILD_{index}"
        output = common / f"formal-hostile-build-{index}"
        output.mkdir()
        install_hostile(error_type(marker))
        with pytest.raises(ValueError) as caught:
            build_model_artifact(**_build_kwargs(data, output_root=output))
        assert str(caught.value) == "M3_MODEL_ALIGNMENT_VERIFY_FAILED"
        assert caught.value.__cause__ is None
        assert caught.value.__context__ is None
        assert marker not in repr(caught.value)
        assert not any(output.iterdir())
    assert sum(item[0] == "train" for item in calls) == train_calls_before

    root = common / "formal-hostile-verify"
    root.mkdir()
    monkeypatch.setattr(
        model_module, "verify_alignment_artifact", lambda **_: alignment
    )
    build_model_artifact(**_build_kwargs(data, output_root=root))
    receipt = common / "receipts" / "model" / "hostile-verify.json"
    receipt.parent.mkdir(parents=True)
    publish_stage_receipt(
        receipt_path=receipt, stage="model", scope="WORK",
        scope_key=alignment_spec.work_key, artifact_roots=roots,
        inputs=_model_inputs(data), outputs=_model_outputs(root),
    )
    kwargs = _verify_kwargs(data, root=root, receipt=receipt)
    for index, error_type in enumerate((ValueError, RuntimeError)):
        marker = f"C:/TOKEN_VERIFY_{index}"
        install_hostile(error_type(marker))
        with pytest.raises(ValueError) as caught:
            verify_model_artifact(**kwargs)
        assert str(caught.value) == "M3_MODEL_ALIGNMENT_VERIFY_FAILED"
        assert caught.value.__cause__ is None
        assert caught.value.__context__ is None
        assert marker not in repr(caught.value)


def test_formal_model_rejects_kind_bundle_receipt_and_prediction_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = _formal_alignment_bundle(tmp_path, monkeypatch)
    bundle, feature_bundle, alignment, feature, label, _, experiment, _, alignment_spec, _, roots, common, _ = data
    output = common / "formal-kind-reject"
    output.mkdir()
    with pytest.raises(ValueError, match="formal model requires formal"):
        build_model_artifact(
            **{
                **_build_kwargs(data, output_root=output),
                "alignment": cast(Any, _ALIGNMENT_SUPPORT._verify(bundle)),
            }
        )
    assert not any(output.iterdir())

    copied_alignment_root = common / "copied-formal-alignment"
    shutil.copytree(alignment.root, copied_alignment_root)
    forged_alignment = replace(alignment, root=copied_alignment_root)
    stale_output = common / "formal-stale-reject"
    stale_output.mkdir()
    train_calls_before = sum(item[0] == "train" for item in data[-1])
    monkeypatch.setattr(
        model_module, "verify_alignment_artifact", lambda **_: forged_alignment
    )
    with pytest.raises(ValueError, match="alignment stale"):
        build_model_artifact(**_build_kwargs(data, output_root=stale_output))
    assert not any(stale_output.iterdir())
    assert sum(item[0] == "train" for item in data[-1]) == train_calls_before

    root = common / "formal-model-adversarial"
    root.mkdir()
    monkeypatch.setattr(
        model_module, "verify_alignment_artifact", lambda **_: alignment
    )
    build_model_artifact(**_build_kwargs(data, output_root=root))
    receipt = common / "receipts" / "model" / "adversarial.json"
    receipt.parent.mkdir(parents=True)
    publish_stage_receipt(
        receipt_path=receipt, stage="model", scope="WORK",
        scope_key=alignment_spec.work_key, artifact_roots=roots,
        inputs=_model_inputs(data), outputs=_model_outputs(root),
    )
    monkeypatch.setattr(
        model_module, "verify_alignment_artifact", lambda **_: alignment
    )
    kwargs = _verify_kwargs(data, root=root, receipt=receipt)
    verified = verify_model_artifact(**kwargs)
    with pytest.raises(ValueError, match="formal model verify requires formal"):
        verify_model_artifact(
            **{**kwargs, "alignment": _ALIGNMENT_SUPPORT._verify(bundle)}
        )

    monkeypatch.setattr(
        model_module, "verify_alignment_artifact", lambda **_: forged_alignment
    )
    with pytest.raises(ValueError, match="alignment stale"):
        verify_model_artifact(**kwargs)
    monkeypatch.setattr(
        model_module, "verify_alignment_artifact", lambda **_: alignment
    )
    for name in ("model.txt", "model.metadata.json", "validation_curve.parquet"):
        path = root / name
        original = path.read_bytes()
        path.write_bytes(original + b"drift")
        with pytest.raises(ValueError):
            verify_model_artifact(**kwargs)
        path.write_bytes(original)

    wrong_receipt = common / "receipts" / "model" / "wrong-stage.json"
    publish_stage_receipt(
        receipt_path=wrong_receipt, stage="development-model", scope="WORK",
        scope_key=alignment_spec.work_key, artifact_roots=roots,
        inputs=_model_inputs(data), outputs=_model_outputs(root),
    )
    with pytest.raises(ValueError, match="receipt closure"):
        verify_model_artifact(
            **{**kwargs, "receipt_path": wrong_receipt}
        )
    unknown_receipt = common / "receipts" / "model" / "unknown-field.json"
    receipt_payload = json.loads(receipt.read_bytes())
    receipt_payload["unknown"] = "drift"
    unknown_receipt.write_bytes(model_module._canonical_bytes(receipt_payload))
    with pytest.raises(ValueError):
        verify_model_artifact(
            **{**kwargs, "receipt_path": unknown_receipt}
        )

    valid_index = _MODEL_SUPPORT.pd.MultiIndex.from_tuples(
        [(date(2026, 1, 1), "x")],
        names=["as_of", "symbol"],
    )
    inference = InferenceSegment(
        name="test",
        features=cast(Any, _MODEL_SUPPORT.pd.DataFrame(
            [[1.0] * len(verified.manifest.selected_feature_names)],
            columns=verified.manifest.selected_feature_names,
            index=valid_index,
            dtype="float64",
        )),
        metadata=pl.DataFrame(
            {"as_of": [date(2026, 1, 1)], "symbol": ["x"]},
            schema={"as_of": pl.Date, "symbol": pl.String},
        ),
    )
    with pytest.raises(ValueError, match="schema drift"):
        predict_fitted_model(
            model=verified,
            inference=replace(
                inference,
                features=inference.features.astype("float32"),
            ),
        )
    lightgbm = cast(Any, sys.modules["lightgbm"])
    original_booster = lightgbm.Booster

    def non_finite_booster(*args: Any, **kwargs: Any) -> Any:
        booster = original_booster(*args, **kwargs)
        booster.predict = lambda *a, **k: np.array([np.inf])
        return booster

    lightgbm.Booster = non_finite_booster
    with pytest.raises(ValueError, match="output invalid"):
        predict_fitted_model(model=verified, inference=inference)


def test_formal_prediction_rejects_index_and_metadata_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = _formal_alignment_bundle(tmp_path, monkeypatch)
    alignment, common = data[2], data[11]
    monkeypatch.setattr(
        model_module, "verify_alignment_artifact", lambda **_: alignment
    )
    root = common / "formal-model-prediction-keys"
    root.mkdir()
    build_model_artifact(**_build_kwargs(data, output_root=root))
    receipt = common / "receipts" / "model" / "prediction-keys.json"
    receipt.parent.mkdir(parents=True, exist_ok=True)
    publish_stage_receipt(
        receipt_path=receipt, stage="model", scope="WORK",
        scope_key=alignment.manifest.work_key, artifact_roots=data[10],
        inputs=_model_inputs(data), outputs=_model_outputs(root),
    )
    verified = verify_model_artifact(
        **_verify_kwargs(data, root=root, receipt=receipt)
    )
    names = verified.manifest.selected_feature_names
    pd = _MODEL_SUPPORT.pd
    index = pd.MultiIndex.from_tuples(
        [
            (date(2026, 1, 1), "a"),
            (date(2026, 1, 2), "b"),
        ],
        names=["as_of", "symbol"],
    )
    features = pd.DataFrame(
        np.ones((2, len(names))), columns=names, index=index, dtype="float64"
    )
    metadata = pl.DataFrame(
        {
            "as_of": [date(2026, 1, 1), date(2026, 1, 2)],
            "symbol": ["a", "b"],
        },
        schema={"as_of": pl.Date, "symbol": pl.String},
    )
    valid = InferenceSegment(name="test", features=features, metadata=metadata)
    assert len(predict_fitted_model(model=verified, inference=valid)) == 2

    drifted = (
        replace(valid, features=features.set_axis(pd.Index([0, 1]))),
        replace(
            valid,
            features=features.set_axis(
                pd.MultiIndex.from_tuples(index.tolist(), names=["date", "symbol"])
            ),
        ),
        replace(valid, features=features.iloc[::-1]),
        replace(valid, features=pd.concat([features.iloc[:1], features.iloc[:1]])),
        replace(valid, metadata=metadata.select("symbol", "as_of")),
        replace(valid, metadata=metadata.reverse()),
        replace(valid, metadata=metadata.with_columns(pl.lit("z").alias("symbol"))),
        replace(valid, metadata=metadata.with_columns(pl.lit(1).alias("unknown"))),
    )
    for inference in drifted:
        with pytest.raises(ValueError, match="schema drift"):
            predict_fitted_model(model=verified, inference=inference)


def test_r2_copied_model_root_is_rejected_before_any_lightgbm_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = _formal_alignment_bundle(tmp_path, monkeypatch)
    alignment = data[2]
    common = data[11]
    roots = data[10]
    alignment_spec = data[8]
    monkeypatch.setattr(
        model_module, "verify_alignment_artifact", lambda **_: alignment
    )
    root = common / "formal-r2-preload-model"
    root.mkdir()
    build_model_artifact(**_build_kwargs(data, output_root=root))
    receipt = common / "receipts" / "model" / "formal-r2-preload.json"
    receipt.parent.mkdir(parents=True, exist_ok=True)
    publish_stage_receipt(
        receipt_path=receipt, stage="model", scope="WORK",
        scope_key=alignment_spec.work_key, artifact_roots=roots,
        inputs=_model_inputs(data), outputs=_model_outputs(root),
    )
    copied = common / "formal-r2-preload-model-copy"
    shutil.copytree(root, copied)
    lightgbm_calls = 0

    def hostile_lightgbm() -> Any:
        nonlocal lightgbm_calls
        lightgbm_calls += 1
        raise AssertionError("copied root reached LightGBM")

    monkeypatch.setattr(model_module, "_lightgbm", hostile_lightgbm)
    with pytest.raises(ValueError, match="receipt closure drift"):
        verify_model_artifact(
            **_verify_kwargs(data, root=copied, receipt=receipt)
        )
    assert lightgbm_calls == 0


def test_r4_formal_model_root_replacement_is_blocked_or_rolled_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = _formal_alignment_bundle(tmp_path, monkeypatch)
    alignment = data[2]
    common = data[11]
    root = common / "formal-r4-root-race"
    moved = common / "formal-r4-root-race-moved"
    root.mkdir()
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

    def attacking_fresh(**_: object) -> VerifiedAlignmentArtifact:
        nonlocal replacement_succeeded
        try:
            os.rename(root, moved)
            root.mkdir()
            replacement_succeeded = True
        except OSError:
            replacement_succeeded = False
        return alignment

    monkeypatch.setattr(
        model_module, "verify_alignment_artifact", attacking_fresh
    )
    if os.name == "nt":
        build_model_artifact(**_build_kwargs(data, output_root=root))
        assert not replacement_succeeded
        assert {path.name for path in root.iterdir()} == {
            "model.txt",
            "model.metadata.json",
            "validation_curve.parquet",
        }
        assert not moved.exists()
    else:
        with pytest.raises(ValueError, match="^M3_MODEL_ARTIFACT_INVALID$"):
            build_model_artifact(**_build_kwargs(data, output_root=root))
        assert replacement_succeeded
        assert writer_calls == 0
        assert not any(root.iterdir()) and not any(moved.iterdir())


def test_r4_second_model_builder_is_rejected_before_train(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = _formal_alignment_bundle(tmp_path, monkeypatch)
    alignment = data[2]
    common = data[11]
    calls = data[-1]
    root = common / "formal-r4-exclusive-lease"
    root.mkdir()
    nested_checked = False

    def fresh_with_nested_builder(**_: object) -> VerifiedAlignmentArtifact:
        nonlocal nested_checked
        if not nested_checked:
            nested_checked = True
            before = sum(item[0] == "train" for item in calls)
            with pytest.raises(
                ValueError, match="^M3_MODEL_ARTIFACT_INVALID$"
            ):
                build_model_artifact(**_build_kwargs(data, output_root=root))
            assert sum(item[0] == "train" for item in calls) == before
        return alignment

    monkeypatch.setattr(
        model_module, "verify_alignment_artifact", fresh_with_nested_builder
    )
    build_model_artifact(**_build_kwargs(data, output_root=root))
    assert nested_checked
    assert sum(item[0] == "train" for item in calls) == 1


def test_r4_model_three_file_writers_and_fsync_failures_rollback_exactly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = _formal_alignment_bundle(tmp_path, monkeypatch)
    alignment = data[2]
    common = data[11]
    monkeypatch.setattr(
        model_module, "verify_alignment_artifact", lambda **_: alignment
    )
    real_exclusive = model_module._write_exclusive
    real_parquet = model_module._write_parquet

    for target in ("model.txt", "validation_curve.parquet", "model.metadata.json"):
        for error_type in (ValueError, RuntimeError):
            output = common / f"r4-writer-{target}-{error_type.__name__}"
            output.mkdir()
            marker = f"PRIVATE_{target}_{error_type.__name__}"

            def hostile_exclusive(*args: Any, **kwargs: Any) -> None:
                if args[1] == target:
                    raise error_type(marker)
                real_exclusive(*args, **kwargs)

            def hostile_parquet(*args: Any, **kwargs: Any) -> None:
                if args[1] == target:
                    raise error_type(marker)
                real_parquet(*args, **kwargs)

            with monkeypatch.context() as patcher:
                patcher.setattr(
                    model_module, "_write_exclusive", hostile_exclusive
                )
                patcher.setattr(model_module, "_write_parquet", hostile_parquet)
                with pytest.raises(ValueError) as caught:
                    build_model_artifact(
                        **_build_kwargs(data, output_root=output)
                    )
            assert str(caught.value) == "M3_MODEL_ARTIFACT_INVALID"
            assert caught.value.__cause__ is None
            assert caught.value.__context__ is None
            assert marker not in repr(caught.value)
            assert not any(output.iterdir())

    real_fsync = publication_module.os.fsync
    for fail_at in (2, 3, 4):
        output = common / f"r4-fsync-{fail_at}"
        output.mkdir()
        calls = 0

        def hostile_fsync(descriptor: int) -> None:
            nonlocal calls
            calls += 1
            if calls == fail_at:
                raise OSError(f"PRIVATE_FSYNC_{fail_at}")
            real_fsync(descriptor)

        with monkeypatch.context() as patcher:
            patcher.setattr(publication_module.os, "fsync", hostile_fsync)
            with pytest.raises(ValueError) as caught:
                build_model_artifact(**_build_kwargs(data, output_root=output))
        assert str(caught.value) == "M3_MODEL_ARTIFACT_INVALID"
        assert caught.value.__cause__ is None
        assert caught.value.__context__ is None
        assert not any(output.iterdir())


def test_r4_model_temporary_save_failure_rolls_back_before_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = _formal_alignment_bundle(tmp_path, monkeypatch)
    alignment = data[2]
    common = data[11]
    output = common / "r4-temporary-save-failure"
    output.mkdir()
    monkeypatch.setattr(
        model_module, "verify_alignment_artifact", lambda **_: alignment
    )

    def hostile_save(**_: object) -> bytes:
        raise RuntimeError("PRIVATE_TEMP_MODEL")

    monkeypatch.setattr(
        model_module, "_save_model_to_temporary_bytes", hostile_save
    )
    with pytest.raises(ValueError) as caught:
        build_model_artifact(**_build_kwargs(data, output_root=output))
    assert str(caught.value) == "M3_MODEL_ARTIFACT_INVALID"
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert "PRIVATE_TEMP_MODEL" not in repr(caught.value)
    assert not any(output.iterdir())


def test_r4_temporary_model_save_empty_read_and_cleanup_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SaveFailure:
        def save_model(self, *_: object, **__: object) -> None:
            raise RuntimeError("PRIVATE_SAVE")

    class EmptyModel:
        def save_model(self, filename: str, **_: object) -> None:
            Path(filename).write_bytes(b"")

    for booster in (SaveFailure(), EmptyModel()):
        with pytest.raises(ArtifactPublicationError):
            model_module._save_model_to_temporary_bytes(
                booster=booster, best_iteration=1
            )

    class ValidModel:
        def save_model(self, filename: str, **_: object) -> None:
            Path(filename).write_bytes(b"model")

    real_read = Path.read_bytes

    def hostile_read(path: Path) -> bytes:
        if path.name == "model.txt":
            raise OSError("PRIVATE_READ")
        return real_read(path)

    with monkeypatch.context() as patcher:
        patcher.setattr(Path, "read_bytes", hostile_read)
        with pytest.raises(ArtifactPublicationError):
            model_module._save_model_to_temporary_bytes(
                booster=ValidModel(), best_iteration=1
            )

    class CleanupFailure:
        def __init__(self, **_: object) -> None:
            self.path = tmp_path / "hostile-temp-cleanup"

        def __enter__(self) -> str:
            self.path.mkdir()
            return str(self.path)

        def __exit__(self, *_: object) -> None:
            (self.path / "model.txt").unlink(missing_ok=True)
            self.path.rmdir()
            raise OSError("PRIVATE_CLEANUP")

    with monkeypatch.context() as patcher:
        patcher.setattr(
            model_module.tempfile, "TemporaryDirectory", CleanupFailure
        )
        with pytest.raises(ArtifactPublicationError):
            model_module._save_model_to_temporary_bytes(
                booster=ValidModel(), best_iteration=1
            )


def test_r4_model_rollback_failure_has_distinct_stable_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = _formal_alignment_bundle(tmp_path, monkeypatch)
    alignment = data[2]
    common = data[11]
    output = common / "r4-model-rollback-failure"
    output.mkdir()
    monkeypatch.setattr(
        model_module, "verify_alignment_artifact", lambda **_: alignment
    )
    real_unlink = publication_module.ArtifactPublication._unlink_entry

    def hostile_curve(*_: Any, **__: Any) -> None:
        raise RuntimeError("PRIVATE_CURVE_WRITE")

    def hostile_unlink(publication: Any, name: str) -> None:
        if name == "model.txt":
            raise PermissionError("PRIVATE_MODEL_ROLLBACK")
        real_unlink(publication, name)

    monkeypatch.setattr(model_module, "_write_parquet", hostile_curve)
    monkeypatch.setattr(
        publication_module.ArtifactPublication, "_unlink_entry", hostile_unlink
    )
    with pytest.raises(ValueError) as caught:
        build_model_artifact(**_build_kwargs(data, output_root=output))
    assert str(caught.value) == "M3_MODEL_ROLLBACK_FAILED"
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert "PRIVATE" not in repr(caught.value)
    assert {path.name for path in output.iterdir()} == {"model.txt"}


def test_native_lightgbm_train_save_load_predict_smoke(tmp_path: Path) -> None:
    lgb = model_module._lightgbm()
    x = np.array(
        [[0.0, 1.0], [1.0, 0.0], [2.0, 1.0], [3.0, 0.0]],
        dtype=np.float64,
    )
    y = np.array([0.0, 1.0, 2.0, 3.0], dtype=np.float64)
    dataset = lgb.Dataset(x, label=y, feature_name=["a", "b"])
    booster = lgb.train(
        {
            "objective": "regression", "metric": "l2", "device_type": "cpu",
            "deterministic": True, "force_col_wise": True, "num_threads": 1,
            "verbosity": -1, "min_data_in_leaf": 1,
        },
        dataset,
        num_boost_round=3,
        valid_sets=[dataset],
        valid_names=["validation"],
    )
    path = tmp_path / "native-smoke-model.txt"
    booster.save_model(str(path), num_iteration=3)
    loaded = lgb.Booster(model_file=str(path))
    scores = np.asarray(loaded.predict(x, num_iteration=3), dtype=np.float64)
    assert path.read_bytes() and scores.shape == (4,) and np.isfinite(scores).all()
    print("G5A_NATIVE_LIGHTGBM_PASS", lgb.__version__, 3, scores.shape[0])
