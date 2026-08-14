"""Formal G6A evaluation artifact contract tests."""

from __future__ import annotations

import hashlib
import importlib.util
import math
import os
from dataclasses import replace
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import polars as pl
import pytest

import quant.research.m3 as m3_public
import quant.research.m3._artifact_publication as publication_module
import quant.research.m3.evaluate as evaluation_module
from quant.data.m3_release import VerifiedG1Release
from quant.research.m3.contracts import (
    EvaluationSpec,
    EvaluationUpstreamPaths,
    VerifiedEvaluationArtifact,
    VerifiedPredictionArtifact,
)
from quant.research.m3.evaluate import (
    _evaluate_daily_slices,
    _optional_icir,
    build_evaluation_artifact,
    verify_evaluation_artifact,
)
from quant.research.m3.run_state import publish_stage_receipt

_SUPPORT_SPEC = importlib.util.spec_from_file_location(
    "m3_formal_prediction_support_for_evaluation",
    Path(__file__).with_name("test_m3_formal_prediction_artifact.py"),
)
assert _SUPPORT_SPEC is not None and _SUPPORT_SPEC.loader is not None
_SUPPORT = importlib.util.module_from_spec(_SUPPORT_SPEC)
_SUPPORT_SPEC.loader.exec_module(_SUPPORT)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _formal_release(context: dict[str, Any]) -> VerifiedG1Release:
    release = context["kwargs"]["release"]
    development = context["feature_bundle"][2]
    object.__setattr__(release, "artifact_paths", development.artifact_paths)
    object.__setattr__(
        release,
        "release",
        SimpleNamespace(manifest_path=development.release.manifest_path),
    )
    return cast(VerifiedG1Release, release)


def _evaluation_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    context = _SUPPORT._context(tmp_path, monkeypatch)
    prediction_root, prediction_receipt, _ = _SUPPORT._build_and_publish(context)
    prediction = _SUPPORT._verify(context, prediction_root, prediction_receipt)
    kwargs = dict(context["kwargs"])
    release = _formal_release(context)
    label = kwargs["label"]
    upstream = EvaluationUpstreamPaths(
        prediction_receipt_path=prediction_receipt,
        prediction_upstream_paths=context["upstream"],
        label_receipt_path=context["upstream"].model_upstream_paths
        .alignment_upstream_paths.label_receipt_path,
        feature_receipt_path=context["upstream"].feature_receipt_path,
        fold_receipt_path=context["upstream"].fold_receipt_path,
    )
    minimum = kwargs["config"].section("evaluation")["minimum_ic_symbols"]
    spec = EvaluationSpec(
        experiment_key=prediction.manifest.experiment_key,
        work_key=prediction.manifest.work_key,
        fold=prediction.manifest.fold,
        horizon_sessions=cast(Any, prediction.manifest.horizon_sessions),
        minimum_ic_symbols=minimum,
    )
    kwargs.update(
        release=release, prediction=prediction,
        prediction_spec=context["spec"], spec=spec, upstream_paths=upstream,
    )
    monkeypatch.setattr(
        evaluation_module, "verify_prediction_artifact", lambda **_: prediction
    )
    monkeypatch.setattr(
        evaluation_module, "verify_label_artifact", lambda **_: label
    )
    return {
        **context, "evaluation_kwargs": kwargs, "prediction": prediction,
        "prediction_receipt": prediction_receipt, "release": release,
        "label": label, "evaluation_spec": spec, "evaluation_upstream": upstream,
    }


def _inputs(context: dict[str, Any]) -> list[tuple[str, Path]]:
    kwargs = context["evaluation_kwargs"]
    release, feature = kwargs["release"], kwargs["feature"]
    prediction, label = kwargs["prediction"], kwargs["label"]
    folds, experiment = kwargs["folds"], kwargs["experiment"]
    upstream = kwargs["upstream_paths"]
    experiment_receipt = (
        upstream.prediction_upstream_paths.feature_upstream_paths
        .fold_upstream_paths.experiment_receipt_path
    )
    return [
        ("root", release.release.manifest_path),
        ("root", dict(release.artifact_paths)["eligible_keys.parquet"]),
        ("root", feature.root / "feature_manifest.json"),
        ("root", upstream.feature_receipt_path),
        ("root", feature.root / "coverage.parquet"),
        ("root", feature.root / "test.parquet"),
        ("root", prediction.root / "prediction_manifest.json"),
        ("root", upstream.prediction_receipt_path),
        ("root", prediction.root / "predictions.parquet"),
        ("root", label.root / "label_manifest.json"),
        ("root", upstream.label_receipt_path),
        ("root", label.root / "labels.parquet"),
        ("root", label.root / "diagnostics.parquet"),
        ("root", folds.root / "folds.json"),
        ("root", upstream.fold_receipt_path),
        ("root", experiment.root / "experiment_manifest.json"),
        ("root", experiment_receipt),
    ]


def _outputs(root: Path) -> list[tuple[str, Path]]:
    return [
        ("root", root / name)
        for name in ("daily_ic.parquet", "metrics.json", "evaluation_manifest.json")
    ]


def _build_publish_verify(context: dict[str, Any], suffix: str = "base") -> Any:
    kwargs = context["evaluation_kwargs"]
    root = context["common"] / f"formal-evaluation-{suffix}"
    root.mkdir()
    manifest = build_evaluation_artifact(**kwargs, output_root=root)
    receipt = (
        context["common"] / "receipts" / "evaluation"
        / f"{kwargs['spec'].work_key}-{suffix}.json"
    )
    receipt.parent.mkdir(parents=True, exist_ok=True)
    publish_stage_receipt(
        receipt_path=receipt, stage="evaluation", scope="WORK",
        scope_key=kwargs["spec"].work_key,
        artifact_roots=kwargs["artifact_roots"], inputs=_inputs(context),
        outputs=_outputs(root),
    )
    verified = verify_evaluation_artifact(
        root=root, receipt_path=receipt, **kwargs
    )
    return root, receipt, manifest, verified


def test_formal_evaluation_closed_loop_five_layers_and_exact_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _evaluation_context(tmp_path, monkeypatch)
    root, receipt, manifest, verified = _build_publish_verify(context)
    assert type(verified) is VerifiedEvaluationArtifact
    assert verified.manifest == manifest
    assert verified.evaluation_receipt_sha256 == _sha(receipt)
    assert len(_inputs(context)) == len({path.resolve() for _, path in _inputs(context)}) == 17
    assert {path.name for path in root.iterdir()} == {
        "daily_ic.parquet", "metrics.json", "evaluation_manifest.json",
    }
    daily = verified.daily
    assert daily.get_column("as_of").n_unique() == daily.height > 1
    assert verified.metrics.n_predicted == verified.metrics.n_scorable
    assert verified.metrics.prediction_coverage == 1.0
    assert sum(count for _, count in verified.metrics.status_counts) == daily.height
    assert m3_public.build_evaluation_artifact is build_evaluation_artifact
    assert m3_public.verify_evaluation_artifact is verify_evaluation_artifact


def test_formal_evaluation_rejects_kind_path_receipt_and_wholesale_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _evaluation_context(tmp_path, monkeypatch)
    kwargs = context["evaluation_kwargs"]
    output = context["common"] / "formal-evaluation-rejections"
    output.mkdir()

    class PredictionSubclass(VerifiedPredictionArtifact):
        pass

    prediction = kwargs["prediction"]
    disguised = PredictionSubclass(
        root=prediction.root, predictions=prediction.predictions,
        manifest=prediction.manifest, manifest_sha256=prediction.manifest_sha256,
        prediction_receipt_sha256=prediction.prediction_receipt_sha256,
    )
    with pytest.raises(ValueError, match="^M3_EVALUATION_ARTIFACT_INVALID$"):
        build_evaluation_artifact(
            **{**kwargs, "prediction": disguised}, output_root=output
        )
    assert not any(output.iterdir())

    copied_receipt = context["common"] / "copied-feature-receipt.json"
    copied_receipt.write_bytes(kwargs["upstream_paths"].feature_receipt_path.read_bytes())
    bad_paths = replace(
        kwargs["upstream_paths"], feature_receipt_path=copied_receipt
    )
    with pytest.raises(ValueError, match="^M3_EVALUATION_ARTIFACT_INVALID$"):
        build_evaluation_artifact(
            **{**kwargs, "upstream_paths": bad_paths}, output_root=output
        )
    assert not any(output.iterdir())

    root, receipt, _, _ = _build_publish_verify(context, "receipt")
    decoy = context["common"] / "decoy.txt"
    decoy.write_text("extra", encoding="utf-8")
    extra = receipt.with_name("extra.json")
    publish_stage_receipt(
        receipt_path=extra, stage="evaluation", scope="WORK",
        scope_key=kwargs["spec"].work_key,
        artifact_roots=kwargs["artifact_roots"],
        inputs=[*_inputs(context), ("root", decoy)], outputs=_outputs(root),
    )
    with pytest.raises(ValueError, match="^M3_EVALUATION_ARTIFACT_INVALID$"):
        verify_evaluation_artifact(root=root, receipt_path=extra, **kwargs)

    daily_path = root / "daily_ic.parquet"
    changed = pl.read_parquet(daily_path).with_columns(
        (pl.col("n_evaluated") + 1).alias("n_evaluated")
    )
    changed.write_parquet(
        daily_path, compression="zstd", compression_level=3, statistics=True,
        row_group_size=65536, use_pyarrow=False,
    )
    receipt.unlink()
    publish_stage_receipt(
        receipt_path=receipt, stage="evaluation", scope="WORK",
        scope_key=kwargs["spec"].work_key,
        artifact_roots=kwargs["artifact_roots"], inputs=_inputs(context),
        outputs=_outputs(root),
    )
    with pytest.raises(ValueError, match="^M3_EVALUATION_ARTIFACT_INVALID$"):
        verify_evaluation_artifact(root=root, receipt_path=receipt, **kwargs)


def test_formal_evaluation_transaction_rollback_and_hostile_redaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _evaluation_context(tmp_path, monkeypatch)
    kwargs = context["evaluation_kwargs"]
    real_write = publication_module.ArtifactPublication.write_bytes
    for fail_at, name in enumerate(
        ("daily_ic.parquet", "metrics.json", "evaluation_manifest.json"), start=1
    ):
        output = context["common"] / f"formal-evaluation-write-fail-{fail_at}"
        output.mkdir()
        calls = {"n": 0}

        def hostile_write(self: Any, filename: str, raw: bytes) -> None:
            calls["n"] += 1
            if calls["n"] == fail_at:
                raise RuntimeError(f"C:/PRIVATE/{name}")
            real_write(self, filename, raw)

        monkeypatch.setattr(
            publication_module.ArtifactPublication, "write_bytes", hostile_write
        )
        with pytest.raises(ValueError) as caught:
            build_evaluation_artifact(**kwargs, output_root=output)
        assert str(caught.value) == "M3_EVALUATION_ARTIFACT_INVALID"
        assert caught.value.__cause__ is None and caught.value.__context__ is None
        assert not any(output.iterdir())
    monkeypatch.setattr(
        publication_module.ArtifactPublication, "write_bytes", real_write
    )

    output = context["common"] / "formal-evaluation-hostile-fresh"
    output.mkdir()

    def hostile(**_: Any) -> None:
        raise RuntimeError("C:/PRIVATE/TOKEN_G6A")

    monkeypatch.setattr(evaluation_module, "verify_prediction_artifact", hostile)
    with pytest.raises(ValueError) as caught:
        build_evaluation_artifact(**kwargs, output_root=output)
    assert str(caught.value) == "M3_EVALUATION_ARTIFACT_INVALID"
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert "TOKEN_G6A" not in repr(caught.value) and not any(output.iterdir())


def test_r2_formal_evaluation_rejects_fresh_and_math_root_replacement_before_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _evaluation_context(tmp_path, monkeypatch)
    kwargs = context["evaluation_kwargs"]
    label = context["label"]
    real_write_stream = publication_module.ArtifactPublication.write_stream
    real_parquet_bytes = evaluation_module._parquet_bytes

    for mode in ("fresh", "math"):
        output = context["common"] / f"formal-evaluation-r2-{mode}-root"
        moved = context["common"] / f"formal-evaluation-r2-{mode}-root-moved"
        output.mkdir()
        writer_calls = 0

        def counted_write_stream(
            self: Any, name: str, writer: Any,
        ) -> None:
            def counted(stream: Any) -> object:
                nonlocal writer_calls
                writer_calls += 1
                return writer(stream)

            real_write_stream(self, name, counted)

        def replace_root() -> None:
            os.rename(output, moved)
            output.mkdir()

        def fresh_attack(**_: Any) -> Any:
            replace_root()
            return label

        def math_attack(frame: pl.DataFrame) -> bytes:
            raw = real_parquet_bytes(frame)
            replace_root()
            return raw

        monkeypatch.setattr(
            publication_module.ArtifactPublication,
            "write_stream",
            counted_write_stream,
        )
        monkeypatch.setattr(
            evaluation_module,
            "verify_label_artifact",
            fresh_attack if mode == "fresh" else lambda **_: label,
        )
        monkeypatch.setattr(
            evaluation_module,
            "_parquet_bytes",
            math_attack if mode == "math" else real_parquet_bytes,
        )
        with pytest.raises(ValueError, match="^M3_EVALUATION_ARTIFACT_INVALID$"):
            build_evaluation_artifact(**kwargs, output_root=output)
        assert writer_calls == 0
        assert not any(output.iterdir())
        if os.name == "nt":
            assert not moved.exists()
        else:
            assert not any(moved.iterdir())


def test_eight_status_priority_ties_and_icir_math() -> None:
    d = [date(2026, 1, index) for index in range(1, 10)]
    eligible_rows: list[dict[str, object]] = []
    scorable_rows: list[dict[str, object]] = []
    prediction_rows: list[dict[str, object]] = []
    label_rows: list[dict[str, object]] = []
    symbols = ("A", "B", "C")
    for index, day in enumerate(d):
        if index == 0:
            continue
        for symbol_index, symbol in enumerate(symbols):
            eligible_rows.append({"as_of": day, "symbol": symbol})
            if index not in {1, 2}:
                scorable_rows.append({"as_of": day, "symbol": symbol})
                prediction_rows.append({
                    "as_of": day, "symbol": symbol,
                    "score": float(
                        0 if index == 8 and symbol == "B"
                        else symbol_index if index not in {4, 5} else 1
                    ),
                })
            if index != 1:
                label_rows.append({
                    "as_of": day, "symbol": symbol,
                    "relative_return": float(
                        symbol_index if index not in {4, 6} else 1
                    ),
                })
    # Day 2 hits NO_LABELS before NO_PREDICTIONS; day 3 has labels but no scores.
    label_rows[:] = [row for row in label_rows if row["as_of"] != d[1]]
    label_rows[:] = [
        row for row in label_rows
        if row["as_of"] != d[3] or row["symbol"] == "A"
    ]
    daily = _evaluate_daily_slices(
        eligible=pl.DataFrame(eligible_rows, schema={"as_of": pl.Date, "symbol": pl.Utf8}),
        scorable=pl.DataFrame(scorable_rows, schema={"as_of": pl.Date, "symbol": pl.Utf8}),
        predictions=pl.DataFrame(
            prediction_rows,
            schema={"as_of": pl.Date, "symbol": pl.Utf8, "score": pl.Float64},
        ),
        labels=pl.DataFrame(
            label_rows,
            schema={"as_of": pl.Date, "symbol": pl.Utf8, "relative_return": pl.Float64},
        ),
        evaluation_dates=tuple(d), minimum_ic_symbols=2,
    )
    assert daily.get_column("ic_status").to_list() == [
        "NO_ELIGIBLE", "NO_LABELS", "NO_PREDICTIONS", "INSUFFICIENT_SYMBOLS",
        "BOTH_ZERO_VARIANCE", "SCORE_ZERO_VARIANCE",
        "LABEL_ZERO_VARIANCE", "COMPUTABLE",
        "COMPUTABLE",
    ]
    computable = daily.filter(pl.col("ic_status") == "COMPUTABLE")
    tied_ic = math.sqrt(3.0) / 2.0
    assert computable.get_column("pearson_ic").to_list() == pytest.approx(
        [1.0, tied_ic]
    )
    assert computable.get_column("rank_ic").to_list() == pytest.approx(
        [1.0, tied_ic]
    )
    assert all(
        value is None
        for value in daily.filter(pl.col("ic_status") != "COMPUTABLE")
        .get_column("pearson_ic")
    )
    assert math.isfinite(float(computable[0, "pearson_ic"]))
    expected_icir = ((1.0 + tied_ic) / 2.0) / (
        abs(1.0 - tied_ic) / math.sqrt(2.0)
    )
    assert _optional_icir([1.0, tied_ic]) == pytest.approx(expected_icir)
    assert _optional_icir([1.0]) is None
    assert _optional_icir([1.0, 1.0]) is None
