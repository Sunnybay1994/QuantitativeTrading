"""G6A development/example evaluation artifact adversarial contract tests."""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib
import importlib.util
import inspect
import json
import math
import sys
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, cast

import polars as pl
import pytest

from quant.research.m3.contracts import EvaluationSpec, EvaluationUpstreamPaths
from quant.research.m3.development_example import (
    VerifiedDevelopmentExampleEvaluationArtifact,
)
from quant.research.m3.evaluate import (
    _evaluate_daily_slices,
    _summarize_evaluation,
    build_development_example_evaluation_artifact,
    verify_development_example_evaluation_artifact,
)
from quant.research.m3.run_state import publish_stage_receipt

_PREDICTION_SUPPORT_SPEC = importlib.util.spec_from_file_location(
    "m3_prediction_test_support_for_evaluation",
    Path(__file__).with_name("test_m3_prediction_artifact.py"),
)
assert _PREDICTION_SUPPORT_SPEC is not None and _PREDICTION_SUPPORT_SPEC.loader is not None
_PREDICTION_SUPPORT = importlib.util.module_from_spec(_PREDICTION_SUPPORT_SPEC)
_PREDICTION_SUPPORT_SPEC.loader.exec_module(_PREDICTION_SUPPORT)

_STATUSES = (
    "NO_ELIGIBLE",
    "NO_LABELS",
    "NO_PREDICTIONS",
    "INSUFFICIENT_SYMBOLS",
    "BOTH_ZERO_VARIANCE",
    "SCORE_ZERO_VARIANCE",
    "LABEL_ZERO_VARIANCE",
    "COMPUTABLE",
)


def _keys(day: dt.date, symbols: tuple[str, ...]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "as_of": pl.Series([day] * len(symbols), dtype=pl.Date),
            "symbol": pl.Series(symbols, dtype=pl.String),
        }
    )


def _predictions(day: dt.date, symbols: tuple[str, ...], scores: tuple[float, ...]) -> pl.DataFrame:
    return _keys(day, symbols).with_columns(pl.Series("score", scores, dtype=pl.Float64))


def _labels(day: dt.date, symbols: tuple[str, ...], values: tuple[float, ...]) -> pl.DataFrame:
    return _keys(day, symbols).with_columns(pl.Series("relative_return", values, dtype=pl.Float64))


def _empty(extra: str | None = None) -> pl.DataFrame:
    columns: dict[str, pl.Series] = {
        "as_of": pl.Series([], dtype=pl.Date),
        "symbol": pl.Series([], dtype=pl.String),
    }
    if extra is not None:
        columns[extra] = pl.Series([], dtype=pl.Float64)
    return pl.DataFrame(columns)


@pytest.mark.parametrize(
    (
        "eligible_symbols",
        "scorable_symbols",
        "scores",
        "label_symbols",
        "returns",
        "minimum",
        "expected",
    ),
    [
        ((), (), (), (), (), 2, "NO_ELIGIBLE"),
        (("A",), (), (), (), (), 2, "NO_LABELS"),
        (("A",), (), (), ("A",), (0.1,), 2, "NO_PREDICTIONS"),
        (("A", "B"), ("A", "B"), (1.0, 2.0), ("A",), (0.1,), 2, "INSUFFICIENT_SYMBOLS"),
        (("A", "B"), ("A", "B"), (1.0, 1.0), ("A", "B"), (0.1, 0.1), 2, "BOTH_ZERO_VARIANCE"),
        (("A", "B"), ("A", "B"), (1.0, 1.0), ("A", "B"), (0.1, 0.2), 2, "SCORE_ZERO_VARIANCE"),
        (("A", "B"), ("A", "B"), (1.0, 2.0), ("A", "B"), (0.1, 0.1), 2, "LABEL_ZERO_VARIANCE"),
        (("A", "B"), ("A", "B"), (1.0, 2.0), ("A", "B"), (0.1, 0.2), 2, "COMPUTABLE"),
    ],
)
def test_all_eight_ic_statuses_follow_frozen_priority(
    eligible_symbols: tuple[str, ...],
    scorable_symbols: tuple[str, ...],
    scores: tuple[float, ...],
    label_symbols: tuple[str, ...],
    returns: tuple[float, ...],
    minimum: int,
    expected: str,
) -> None:
    day = dt.date(2025, 1, 2)
    daily = _evaluate_daily_slices(
        eligible=_keys(day, eligible_symbols),
        scorable=_keys(day, scorable_symbols),
        predictions=_predictions(day, scorable_symbols, scores),
        labels=_labels(day, label_symbols, returns),
        evaluation_dates=(day,),
        minimum_ic_symbols=minimum,
    )
    assert daily.item(0, "ic_status") == expected


def test_four_denominators_and_label_missing_does_not_reduce_prediction_coverage() -> None:
    day = dt.date(2025, 1, 2)
    symbols = ("A", "B", "C", "D")
    daily = _evaluate_daily_slices(
        eligible=_keys(day, symbols),
        scorable=_keys(day, ("A", "B", "C")),
        predictions=_predictions(day, ("A", "B", "C"), (3.0, 2.0, 1.0)),
        labels=_labels(day, ("A", "B"), (0.3, 0.1)),
        evaluation_dates=(day,),
        minimum_ic_symbols=2,
    ).row(0, named=True)
    assert daily["n_eligible"] == 4
    assert daily["n_scorable"] == daily["n_predicted"] == 3
    assert daily["n_labeled"] == daily["n_evaluated"] == 2
    assert daily["feature_coverage"] == 3 / 4
    assert daily["prediction_coverage"] == 1.0
    assert daily["label_coverage"] == 1 / 2
    assert daily["evaluation_coverage"] == 1.0

    empty = _evaluate_daily_slices(
        eligible=_empty(),
        scorable=_empty(),
        predictions=_empty("score"),
        labels=_empty("relative_return"),
        evaluation_dates=(day,),
        minimum_ic_symbols=2,
    ).row(0, named=True)
    assert empty["feature_coverage"] is None
    assert empty["prediction_coverage"] is None
    assert empty["label_coverage"] is None
    assert empty["evaluation_coverage"] is None


@pytest.mark.parametrize(
    "mutation",
    ["scorable_outside", "prediction_missing", "label_outside", "evaluated_mismatch"],
)
def test_five_layer_set_invariants_fail_closed(mutation: str) -> None:
    day = dt.date(2025, 1, 2)
    eligible = _keys(day, ("A", "B"))
    scorable = _keys(day, ("A", "B"))
    predictions = _predictions(day, ("A", "B"), (1.0, 2.0))
    labels = _labels(day, ("A", "B"), (0.1, 0.2))
    if mutation == "scorable_outside":
        scorable = _keys(day, ("A", "C"))
        predictions = _predictions(day, ("A", "C"), (1.0, 2.0))
    elif mutation == "prediction_missing":
        predictions = _predictions(day, ("A",), (1.0,))
    elif mutation == "label_outside":
        labels = _labels(day, ("A", "C"), (0.1, 0.2))
    else:
        # A duplicate would make the evaluated relation a multiset rather than
        # the unique intersection required by the frozen contract.
        labels = pl.concat([labels, labels.slice(0, 1)])
    with pytest.raises(ValueError):
        _evaluate_daily_slices(
            eligible=eligible,
            scorable=scorable,
            predictions=predictions,
            labels=labels,
            evaluation_dates=(day,),
            minimum_ic_symbols=2,
        )


def test_minimum_boundary_average_ties_and_single_computable_day_icir_contract() -> None:
    day = dt.date(2025, 1, 2)
    symbols = ("A", "B", "C")
    exact = _evaluate_daily_slices(
        eligible=_keys(day, symbols),
        scorable=_keys(day, symbols),
        predictions=_predictions(day, symbols, (1.0, 1.0, 2.0)),
        labels=_labels(day, symbols, (1.0, 2.0, 3.0)),
        evaluation_dates=(day,),
        minimum_ic_symbols=3,
    ).row(0, named=True)
    assert exact["ic_status"] == "COMPUTABLE"
    assert exact["rank_ic"] == pytest.approx(math.sqrt(3.0) / 2.0)

    insufficient = _evaluate_daily_slices(
        eligible=_keys(day, symbols),
        scorable=_keys(day, symbols),
        predictions=_predictions(day, symbols, (1.0, 1.0, 2.0)),
        labels=_labels(day, symbols, (1.0, 2.0, 3.0)),
        evaluation_dates=(day,),
        minimum_ic_symbols=4,
    ).row(0, named=True)
    assert insufficient["ic_status"] == "INSUFFICIENT_SYMBOLS"
    assert insufficient["pearson_ic"] is None and insufficient["rank_ic"] is None


def test_single_computable_day_has_null_icir() -> None:
    day = dt.date(2025, 1, 2)
    symbols = ("A", "B")
    daily = _evaluate_daily_slices(
        eligible=_keys(day, symbols),
        scorable=_keys(day, symbols),
        predictions=_predictions(day, symbols, (1.0, 2.0)),
        labels=_labels(day, symbols, (0.1, 0.2)),
        evaluation_dates=(day,),
        minimum_ic_symbols=2,
    )

    class _Manifest:
        model = "lightgbm"
        model_version = "test-version"

    class _Prediction:
        manifest = _Manifest()

    metrics = _summarize_evaluation(
        daily=daily,
        prediction=cast(Any, _Prediction()),
        spec=EvaluationSpec(
            experiment_key="a" * 64,
            work_key="b" * 64,
            fold="fold_000",
            horizon_sessions=5,
            minimum_ic_symbols=2,
        ),
        daily_sha256="c" * 64,
    )
    assert metrics.n_computable_dates == 1
    assert metrics.pearson_icir is None
    assert metrics.rank_icir is None


def _evaluation_inputs(prediction_bundle: tuple[Any, ...]) -> list[tuple[str, Path]]:
    model_bundle = prediction_bundle[0]
    alignment_bundle = model_bundle[0]
    feature_bundle, feature, label, _, _, alignment_upstream, _, _, _ = alignment_bundle
    release, experiment, folds = feature_bundle[2], feature_bundle[9], feature_bundle[11]
    prediction_root, prediction_receipt = (
        cast(Path, prediction_bundle[4]),
        cast(Path, prediction_bundle[5]),
    )
    return [
        ("root", release.release.manifest_path),
        ("root", feature.root / "feature_manifest.json"),
        ("root", alignment_upstream.feature_receipt_path),
        ("root", prediction_root / "prediction_manifest.json"),
        ("root", prediction_receipt),
        ("root", label.root / "label_manifest.json"),
        ("root", alignment_upstream.label_receipt_path),
        ("root", folds.root / "folds.json"),
        ("root", alignment_upstream.feature_upstream_paths.fold_receipt_path),
        ("root", experiment.root / "experiment_manifest.json"),
    ]


def _evaluation_outputs(root: Path) -> list[tuple[str, Path]]:
    return [
        ("root", root / "daily_ic.parquet"),
        ("root", root / "metrics.json"),
        ("root", root / "evaluation_manifest.json"),
    ]


def _build_bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, ...]:
    prediction_bundle = _PREDICTION_SUPPORT._build_bundle(tmp_path, monkeypatch)
    prediction = _PREDICTION_SUPPORT._verify(prediction_bundle)
    model_bundle, model, prediction_spec, prediction_upstream, _, _, _ = prediction_bundle
    alignment_bundle = model_bundle[0]
    feature_bundle, feature, label, label_spec, alignment_spec, alignment_upstream, _, _, _ = (
        alignment_bundle
    )
    common, roots = cast(Path, feature_bundle[0]), feature_bundle[1]
    config, experiment, folds = feature_bundle[7], feature_bundle[9], feature_bundle[11]
    minimum = config.section("evaluation")["minimum_ic_symbols"]
    assert type(minimum) is int
    spec = EvaluationSpec(
        experiment_key=experiment.manifest.experiment_key,
        work_key=prediction_spec.work_key,
        fold=prediction_spec.fold,
        horizon_sessions=prediction_spec.horizon_sessions,
        minimum_ic_symbols=minimum,
    )
    root = common / f"development-example-evaluation-{spec.work_key}"
    root.mkdir()
    manifest = build_development_example_evaluation_artifact(
        release=feature_bundle[2],
        feature=feature,
        prediction=prediction,
        label=label,
        folds=folds,
        experiment=experiment,
        config=config,
        spec=spec,
        output_root=root,
    )
    receipt = common / "receipts" / "development-evaluation" / f"{spec.work_key}.json"
    receipt.parent.mkdir(parents=True)
    publish_stage_receipt(
        receipt_path=receipt,
        stage="development-evaluation",
        scope="WORK",
        scope_key=spec.work_key,
        artifact_roots=roots,
        inputs=_evaluation_inputs(prediction_bundle),
        outputs=_evaluation_outputs(root),
    )
    upstream = EvaluationUpstreamPaths(
        prediction_receipt_path=cast(Path, prediction_bundle[5]),
        prediction_upstream_paths=prediction_upstream,
        label_receipt_path=alignment_upstream.label_receipt_path,
        feature_receipt_path=alignment_upstream.feature_receipt_path,
        fold_receipt_path=alignment_upstream.feature_upstream_paths.fold_receipt_path,
    )
    return prediction_bundle, prediction, spec, upstream, root, receipt, manifest


def _verify(
    bundle: tuple[Any, ...],
    *,
    spec: Any = None,
    receipt: Path | None = None,
) -> VerifiedDevelopmentExampleEvaluationArtifact:
    prediction_bundle, prediction, default_spec, upstream, root, default_receipt, _ = bundle
    model_bundle, model, prediction_spec, _, _, _, _ = prediction_bundle
    alignment_bundle = model_bundle[0]
    feature_bundle, feature, label, label_spec, alignment_spec, _, _, _, _ = alignment_bundle
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
        "feature": feature,
        "feature_spec": feature_spec,
        "label": label,
        "label_spec": label_spec,
        "alignment": model_bundle[1],
        "alignment_spec": alignment_spec,
        "model": model,
        "model_spec": model_bundle[2],
        "prediction": prediction,
        "prediction_spec": prediction_spec,
        "config": config,
        "spec": spec or default_spec,
        "upstream_paths": upstream,
        "artifact_roots": roots,
    }
    parameters = inspect.signature(verify_development_example_evaluation_artifact).parameters
    return verify_development_example_evaluation_artifact(
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


def test_evaluation_bundle_closes_full_fold_dates_counts_metrics_and_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = _build_bundle(tmp_path, monkeypatch)
    verified = _verify(bundle)
    prediction_bundle, _, spec, _, root, receipt, manifest = bundle
    folds = prediction_bundle[0][0][0][11]
    fold = next(item for item in folds.manifest.folds if item.name == spec.fold)

    assert isinstance(verified, VerifiedDevelopmentExampleEvaluationArtifact)
    assert verified.release_kind == "development_example"
    assert verified.formal_gate_eligible is False
    assert verified.manifest == manifest
    assert verified.daily.get_column("as_of").to_list() == list(fold.test_dates)
    assert verified.daily.columns == [
        "as_of",
        "n_eligible",
        "n_scorable",
        "n_predicted",
        "n_labeled",
        "n_evaluated",
        "feature_coverage",
        "prediction_coverage",
        "label_coverage",
        "evaluation_coverage",
        "pearson_ic",
        "rank_ic",
        "ic_status",
    ]
    metrics = verified.metrics
    assert metrics.n_dates == len(fold.test_dates)
    assert metrics.n_computable_dates == dict(metrics.status_counts)["COMPUTABLE"]
    assert tuple(name for name, _ in metrics.status_counts) == _STATUSES
    assert sum(count for _, count in metrics.status_counts) == metrics.n_dates
    assert type(metrics.n_dates) is int
    assert metrics.feature_coverage == metrics.n_scorable / metrics.n_eligible
    assert metrics.prediction_coverage == metrics.n_predicted / metrics.n_scorable
    assert metrics.label_coverage == metrics.n_labeled / metrics.n_eligible
    assert metrics.evaluation_coverage == metrics.n_evaluated / metrics.n_labeled
    if metrics.n_computable_dates == 1:
        assert metrics.pearson_icir is None
        assert metrics.rank_icir is None
    assert (
        manifest.daily_sha256
        == hashlib.sha256((root / "daily_ic.parquet").read_bytes()).hexdigest()
    )
    assert verified.evaluation_receipt_sha256 == hashlib.sha256(receipt.read_bytes()).hexdigest()
    assert (root / "evaluation_manifest.json").read_bytes() == _canonical(asdict(manifest))


def test_evaluation_identity_no_clobber_output_receipt_and_json_tamper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = _build_bundle(tmp_path, monkeypatch)
    prediction_bundle, _, spec, _, root, receipt, _ = bundle
    before = {path.name: path.read_bytes() for path in root.iterdir()}
    model_bundle = prediction_bundle[0]
    alignment_bundle = model_bundle[0]
    feature_bundle, feature, label, _, _, _, _, _, _ = alignment_bundle
    with pytest.raises(ValueError):
        build_development_example_evaluation_artifact(
            release=feature_bundle[2],
            feature=feature,
            prediction=bundle[1],
            label=label,
            folds=feature_bundle[11],
            experiment=feature_bundle[9],
            config=feature_bundle[7],
            spec=spec,
            output_root=root,
        )
    assert {path.name: path.read_bytes() for path in root.iterdir()} == before

    with pytest.raises(ValueError):
        _verify(bundle, spec=replace(spec, work_key="f" * 64))

    for path in (*_evaluation_outputs(root), ("root", receipt)):
        target = path[1]
        original = target.read_bytes()
        target.write_bytes(original + b"drift")
        with pytest.raises(ValueError):
            _verify(bundle)
        target.write_bytes(original)
        _verify(bundle)

    metrics_path = root / "metrics.json"
    original_metrics = metrics_path.read_bytes()
    payload = json.loads(original_metrics)
    payload["n_dates"] = 1.0
    metrics_path.write_bytes(_canonical(payload))
    receipt.unlink()
    publish_stage_receipt(
        receipt_path=receipt,
        stage="development-evaluation",
        scope="WORK",
        scope_key=spec.work_key,
        artifact_roots=feature_bundle[1],
        inputs=_evaluation_inputs(prediction_bundle),
        outputs=_evaluation_outputs(root),
    )
    with pytest.raises(ValueError):
        _verify(bundle)

    payload = json.loads(original_metrics)
    payload["pearson_ic_mean"] = math.nan
    metrics_path.write_text(
        json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=True
        ),
        encoding="utf-8",
    )
    receipt.unlink()
    publish_stage_receipt(
        receipt_path=receipt,
        stage="development-evaluation",
        scope="WORK",
        scope_key=spec.work_key,
        artifact_roots=feature_bundle[1],
        inputs=_evaluation_inputs(prediction_bundle),
        outputs=_evaluation_outputs(root),
    )
    with pytest.raises(ValueError):
        _verify(bundle)


def test_wholesale_evaluation_bundle_from_other_work_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first_path, second_path = tmp_path / "first", tmp_path / "second"
    first_path.mkdir()
    second_path.mkdir()
    first = _build_bundle(first_path, monkeypatch)
    second = _build_bundle(second_path, monkeypatch)
    first_root, second_root = cast(Path, first[4]), cast(Path, second[4])
    first_receipt, second_receipt = cast(Path, first[5]), cast(Path, second[5])
    foreign_work_key = "f" * 64
    metrics_path = second_root / "metrics.json"
    metrics_payload = json.loads(metrics_path.read_bytes())
    metrics_payload["work_key"] = foreign_work_key
    metrics_path.write_bytes(_canonical(metrics_payload))
    manifest_path = second_root / "evaluation_manifest.json"
    manifest_payload = json.loads(manifest_path.read_bytes())
    manifest_payload["work_key"] = foreign_work_key
    manifest_payload["metrics_sha256"] = hashlib.sha256(metrics_path.read_bytes()).hexdigest()
    manifest_path.write_bytes(_canonical(manifest_payload))
    second_receipt.unlink()
    publish_stage_receipt(
        receipt_path=second_receipt,
        stage="development-evaluation",
        scope="WORK",
        scope_key=foreign_work_key,
        artifact_roots=second[0][0][0][0][1],
        inputs=_evaluation_inputs(second[0]),
        outputs=_evaluation_outputs(second_root),
    )
    for filename in ("daily_ic.parquet", "metrics.json", "evaluation_manifest.json"):
        (first_root / filename).write_bytes((second_root / filename).read_bytes())
    first_receipt.write_bytes(second_receipt.read_bytes())
    with pytest.raises(ValueError):
        _verify(first)


def test_evaluation_import_does_not_load_qlib_lightgbm_or_mlflow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in tuple(sys.modules):
        if name in {"qlib", "lightgbm", "mlflow"} or name.startswith(
            ("qlib.", "lightgbm.", "mlflow.")
        ):
            monkeypatch.delitem(sys.modules, name, raising=False)
    importlib.reload(importlib.import_module("quant.research.m3.evaluate"))
    assert not any(
        name in {"qlib", "lightgbm", "mlflow"} or name.startswith(("qlib.", "lightgbm.", "mlflow."))
        for name in sys.modules
    )
