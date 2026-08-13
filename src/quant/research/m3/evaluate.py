"""预测指标：按日 Rank IC / Pearson IC 与汇总。不 import Qlib/MLflow。"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, fields
from functools import wraps
from pathlib import Path
from typing import Any, Callable, ParamSpec, TypeVar, cast

import polars as pl

from quant.domain import ForwardReturnLabelSchema, PredictionScoreSchema
from quant.research.m3.alignment import _read_feature_segment, _scorable_expression
from quant.research.m3.config import LoadedM3Config
from quant.research.m3.contracts import (
    AlignmentBuildSpec,
    EvaluationManifestV1,
    EvaluationMetricsV1,
    EvaluationSpec,
    EvaluationUpstreamPaths,
    ExperimentIdentitySpec,
    FeatureBuildSpec,
    FoldPlanBuildSpec,
    IcStatus,
    LabelBuildSpec,
    LightgbmTrainingSpec,
    PredictionBuildSpec,
    ProviderBuildSpec,
    ResearchSummaryManifestV1,
    ResearchSummaryMetricsV1,
    ResearchSummaryUpstreamPaths,
    SnapshotBuildSpec,
)
from quant.research.m3.development_example import (
    VerifiedDevelopmentExampleAlignmentArtifact,
    VerifiedDevelopmentExampleEvaluationArtifact,
    VerifiedDevelopmentExampleExperimentIdentity,
    VerifiedDevelopmentExampleFeatureArtifact,
    VerifiedDevelopmentExampleFoldPlanArtifact,
    VerifiedDevelopmentExampleG1Release,
    VerifiedDevelopmentExampleLabelArtifact,
    VerifiedDevelopmentExampleModelArtifact,
    VerifiedDevelopmentExamplePredictionArtifact,
    VerifiedDevelopmentExampleProviderArtifact,
    VerifiedDevelopmentExampleResearchSummaryArtifact,
    VerifiedDevelopmentExampleSnapshotArtifact,
)
from quant.research.m3.predictions import (
    verify_development_example_prediction_artifact,
)
from quant.research.m3.run_state import (
    ArtifactDigest,
    path_for_artifact_digest,
    verify_stage_receipt_with_bytes,
)

_IDENTITY_COLS = (
    "model",
    "model_version",
    "dataset_snapshot_id",
    "fold",
    "horizon_sessions",
)


def rank_ic_by_date(
    predictions: pl.DataFrame,
    labels: pl.DataFrame,
    *,
    evaluation_dates: Sequence[dt.date],
) -> pl.DataFrame:
    """按 evaluation_dates 计算截面 Pearson IC 与 Spearman Rank IC。

    每次只接受一个预测身份切片；零方差截面记为不可计算，不得静默填 0。
    日期域由 ``evaluation_dates`` 冻结：区间外预测拒绝；区间外 labels 不影响输出。
    """
    _assert_evaluation_dates(evaluation_dates)
    eval_set = set(evaluation_dates)

    _assert_unique_prediction_keys(predictions)
    _assert_unique_label_keys(labels)
    predictions = PredictionScoreSchema.validate(predictions)
    labels = ForwardReturnLabelSchema.validate(labels)
    _assert_single_prediction_slice(predictions)

    pred_dates = set(predictions.get_column("as_of").unique().to_list())
    outside = sorted(pred_dates - eval_set)
    if outside:
        raise ValueError(
            "predictions 存在 evaluation_dates 之外的日期: "
            + ", ".join(d.isoformat() for d in outside)
        )

    horizon = int(predictions.get_column("horizon_sessions").unique().to_list()[0])
    labels_h = labels.filter(
        (pl.col("horizon_sessions") == horizon)
        & pl.col("as_of").is_in(list(evaluation_dates))
    )
    expected_by_date = (
        labels_h.group_by("as_of")
        .agg(pl.len().alias("n_expected_labels"))
        .sort("as_of")
    )

    joined = (
        predictions.select("as_of", "symbol", "score", "horizon_sessions")
        .join(
            labels_h.select("as_of", "symbol", "relative_return", "horizon_sessions"),
            on=["as_of", "symbol", "horizon_sessions"],
            how="inner",
        )
        .sort(["as_of", "symbol"])
    )

    expected_map = {
        row["as_of"]: int(row["n_expected_labels"])
        for row in expected_by_date.iter_rows(named=True)
    }

    rows: list[dict[str, object]] = []
    for as_of in evaluation_dates:
        group = joined.filter(pl.col("as_of") == as_of)
        scores = group.get_column("score").to_list() if not group.is_empty() else []
        rets = (
            group.get_column("relative_return").to_list() if not group.is_empty() else []
        )
        n_matched = len(scores)
        n_expected = expected_map.get(as_of, 0)
        pearson = _pearson(scores, rets) if n_matched else None
        spearman = _spearman(scores, rets) if n_matched else None
        computable = pearson is not None and spearman is not None
        reason = _incomputable_reason(
            computable=computable,
            n_expected=n_expected,
            n_matched=n_matched,
            pearson=pearson,
            spearman=spearman,
        )
        rows.append(
            {
                "as_of": as_of,
                "n_expected_labels": n_expected,
                "n_matched_predictions": n_matched,
                "n_symbols": n_matched,
                "pearson_ic": pearson,
                "rank_ic": spearman,
                "computable": computable,
                "incomputable_reason": reason,
            }
        )

    return pl.DataFrame(rows).sort("as_of")


def summarize_prediction_metrics(daily_ic: pl.DataFrame) -> dict[str, float]:
    """汇总 IC/ICIR、覆盖率与可计算日比例。"""
    if daily_ic.is_empty():
        return {
            "pearson_ic_mean": float("nan"),
            "rank_ic_mean": float("nan"),
            "pearson_icir": float("nan"),
            "rank_icir": float("nan"),
            "n_dates": 0.0,
            "n_computable_dates": 0.0,
            "n_zero_variance_dates": 0.0,
            "mean_daily_symbols": float("nan"),
            "prediction_coverage": float("nan"),
            "computable_date_ratio": float("nan"),
        }

    computable = daily_ic.filter(pl.col("computable"))
    n_dates = float(daily_ic.height)
    n_computable = float(computable.height)
    if "incomputable_reason" in daily_ic.columns:
        n_zero_var = float(
            daily_ic.filter(pl.col("incomputable_reason") == "zero_variance").height
        )
    else:
        n_zero_var = float(daily_ic.filter(~pl.col("computable")).height)
    matched = float(daily_ic.get_column("n_matched_predictions").sum())
    expected = float(daily_ic.get_column("n_expected_labels").sum())

    pearson_vals = [
        v for v in computable.get_column("pearson_ic").to_list() if v is not None
    ]
    rank_vals = [
        v for v in computable.get_column("rank_ic").to_list() if v is not None
    ]

    return {
        "pearson_ic_mean": _mean(pearson_vals),
        "rank_ic_mean": _mean(rank_vals),
        "pearson_icir": _icir(pearson_vals),
        "rank_icir": _icir(rank_vals),
        "n_dates": n_dates,
        "n_computable_dates": n_computable,
        "n_zero_variance_dates": n_zero_var,
        "mean_daily_symbols": _as_float(daily_ic.get_column("n_symbols").mean()),
        "prediction_coverage": matched / expected if expected else float("nan"),
        "computable_date_ratio": n_computable / n_dates if n_dates else float("nan"),
    }


def _assert_evaluation_dates(evaluation_dates: Sequence[dt.date]) -> None:
    if not evaluation_dates:
        raise ValueError("evaluation_dates 不得为空")
    if len(evaluation_dates) != len(set(evaluation_dates)):
        raise ValueError("evaluation_dates 必须唯一")
    if list(evaluation_dates) != sorted(evaluation_dates):
        raise ValueError("evaluation_dates 必须严格升序")
    for i in range(1, len(evaluation_dates)):
        if evaluation_dates[i] <= evaluation_dates[i - 1]:
            raise ValueError("evaluation_dates 必须严格升序")


def _incomputable_reason(
    *,
    computable: bool,
    n_expected: int,
    n_matched: int,
    pearson: float | None,
    spearman: float | None,
) -> str | None:
    if computable:
        return None
    # 无标签日不得记为零方差，即使 matched>0
    if n_expected == 0:
        return "insufficient_coverage"
    if n_matched < 2:
        return "insufficient_coverage"
    if pearson is None or spearman is None:
        return "zero_variance"
    return "insufficient_coverage"


def _assert_single_prediction_slice(predictions: pl.DataFrame) -> None:
    keys = predictions.select(list(_IDENTITY_COLS)).unique()
    if keys.height != 1:
        raise ValueError(
            "predictions 必须只包含一个 "
            "(model,model_version,dataset_snapshot_id,fold,horizon_sessions) 切片"
        )


def _assert_unique_prediction_keys(predictions: pl.DataFrame) -> None:
    key_cols = ["as_of", "symbol", *_IDENTITY_COLS]
    dup = predictions.group_by(key_cols).len().filter(pl.col("len") > 1)
    if not dup.is_empty():
        raise ValueError("predictions 存在重复键")


def _assert_unique_label_keys(labels: pl.DataFrame) -> None:
    dup = (
        labels.group_by("as_of", "symbol", "horizon_sessions")
        .len()
        .filter(pl.col("len") > 1)
    )
    if not dup.is_empty():
        raise ValueError("labels 存在重复键")


def _as_float(value: object) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    return float("nan")


def _mean(values: list[float]) -> float:
    if not values:
        return float("nan")
    return sum(values) / len(values)


def _icir(values: list[float]) -> float:
    if len(values) < 2:
        return float("nan")
    mean = _mean(values)
    var = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    std = math.sqrt(var)
    if std == 0.0:
        return float("nan")
    return mean / std


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 2:
        return None
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    den_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs))
    den_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys))
    if den_x == 0.0 or den_y == 0.0:
        return None
    return num / (den_x * den_y)


def _spearman(xs: list[float], ys: list[float]) -> float | None:
    return _pearson(_average_ranks(xs), _average_ranks(ys))


def _average_ranks(values: list[float]) -> list[float]:
    indexed = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(indexed):
        j = i
        while j + 1 < len(indexed) and indexed[j + 1][1] == indexed[i][1]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[indexed[k][0]] = avg_rank
        i = j + 1
    return ranks


_EVALUATION_FILES = {
    "daily_ic.parquet",
    "evaluation_manifest.json",
    "metrics.json",
}
_IC_STATUSES: tuple[IcStatus, ...] = (
    "NO_ELIGIBLE",
    "NO_LABELS",
    "NO_PREDICTIONS",
    "INSUFFICIENT_SYMBOLS",
    "BOTH_ZERO_VARIANCE",
    "SCORE_ZERO_VARIANCE",
    "LABEL_ZERO_VARIANCE",
    "COMPUTABLE",
)
_P = ParamSpec("_P")
_T = TypeVar("_T")


def _evaluation_boundary(function: Callable[_P, _T]) -> Callable[_P, _T]:
    @wraps(function)
    def wrapped(*args: _P.args, **kwargs: _P.kwargs) -> _T:
        try:
            return function(*args, **kwargs)
        except ValueError:
            raise
        except Exception:
            raise ValueError("M3_EVALUATION_ARTIFACT_INVALID") from None

    return wrapped


_DAILY_SCHEMA = {
    "as_of": pl.Date,
    "n_eligible": pl.Int64,
    "n_scorable": pl.Int64,
    "n_predicted": pl.Int64,
    "n_labeled": pl.Int64,
    "n_evaluated": pl.Int64,
    "feature_coverage": pl.Float64,
    "prediction_coverage": pl.Float64,
    "label_coverage": pl.Float64,
    "evaluation_coverage": pl.Float64,
    "pearson_ic": pl.Float64,
    "rank_ic": pl.Float64,
    "ic_status": pl.Utf8,
}


def build_evaluation_spec(
    *,
    prediction: VerifiedDevelopmentExamplePredictionArtifact,
    config: LoadedM3Config,
) -> EvaluationSpec:
    section = config.section("evaluation")
    minimum = section.get("minimum_ic_symbols")
    if type(minimum) is not int:
        raise ValueError("evaluation minimum_ic_symbols invalid")
    return EvaluationSpec(
        experiment_key=prediction.manifest.experiment_key,
        work_key=prediction.manifest.work_key,
        fold=prediction.manifest.fold,
        horizon_sessions=cast(Any, prediction.manifest.horizon_sessions),
        minimum_ic_symbols=minimum,
    )


def build_development_example_evaluation_artifact(
    *,
    release: VerifiedDevelopmentExampleG1Release,
    feature: VerifiedDevelopmentExampleFeatureArtifact,
    prediction: VerifiedDevelopmentExamplePredictionArtifact,
    label: VerifiedDevelopmentExampleLabelArtifact,
    folds: VerifiedDevelopmentExampleFoldPlanArtifact,
    experiment: VerifiedDevelopmentExampleExperimentIdentity,
    config: LoadedM3Config,
    spec: EvaluationSpec,
    output_root: Path,
) -> EvaluationManifestV1:
    """Build one deterministic work-scoped evaluation artifact."""
    _validate_evaluation_identity(
        release, feature, prediction, label, folds, experiment, config, spec
    )
    _require_empty_directory(output_root)
    planned = next(item for item in folds.manifest.folds if item.name == spec.fold)
    dates = planned.test_dates
    eligible = _eligible_test_keys(release, dates)
    scorable = _scorable_test_keys(feature)
    predictions = prediction.predictions.select("as_of", "symbol", "score")
    labels = (
        label.labels.filter(
            (pl.col("horizon_sessions") == spec.horizon_sessions)
            & pl.col("as_of").is_in(list(dates))
        )
        .select("as_of", "symbol", "relative_return")
        .sort("as_of", "symbol")
    )
    daily = _evaluate_daily_slices(
        eligible=eligible,
        scorable=scorable,
        predictions=predictions,
        labels=labels,
        evaluation_dates=dates,
        minimum_ic_symbols=spec.minimum_ic_symbols,
    )
    if int(daily.get_column("n_eligible").sum()) == 0:
        raise ValueError("evaluation has no eligible rows")
    if int(daily.get_column("n_labeled").sum()) == 0:
        raise ValueError("evaluation has no labeled rows")
    daily_path = output_root / "daily_ic.parquet"
    _write_parquet(daily, daily_path)
    daily_sha = _file_sha(daily_path)
    metrics = _summarize_evaluation(
        daily=daily,
        prediction=prediction,
        spec=spec,
        daily_sha256=daily_sha,
    )
    metrics_path = output_root / "metrics.json"
    _write_exclusive(metrics_path, _canonical_bytes(asdict(metrics)))
    manifest = EvaluationManifestV1(
        schema_version="m3-evaluation-artifact-v1",
        experiment_key=spec.experiment_key,
        work_key=spec.work_key,
        prediction_manifest_sha256=prediction.manifest_sha256,
        label_manifest_sha256=label.manifest_sha256,
        feature_manifest_sha256=feature.manifest_sha256,
        fold_plan_manifest_sha256=folds.manifest_sha256,
        eligible_keys_sha256=prediction.manifest.eligibility_sha256,
        evaluation_dates_sha256=_sha_dates(dates),
        scientific_config_sha256=config.scientific_config_sha256,
        fold=spec.fold,
        horizon_sessions=spec.horizon_sessions,
        model=prediction.manifest.model,
        model_version=prediction.manifest.model_version,
        daily_sha256=daily_sha,
        metrics_sha256=_file_sha(metrics_path),
    )
    _write_exclusive(
        output_root / "evaluation_manifest.json",
        _canonical_bytes(asdict(manifest)),
    )
    return manifest


@_evaluation_boundary
def verify_development_example_evaluation_artifact(
    *,
    root: Path,
    receipt_path: Path,
    release: VerifiedDevelopmentExampleG1Release,
    snapshot: VerifiedDevelopmentExampleSnapshotArtifact,
    snapshot_spec: SnapshotBuildSpec,
    provider: VerifiedDevelopmentExampleProviderArtifact,
    provider_spec: ProviderBuildSpec,
    experiment: VerifiedDevelopmentExampleExperimentIdentity,
    experiment_spec: ExperimentIdentitySpec,
    folds: VerifiedDevelopmentExampleFoldPlanArtifact,
    fold_spec: FoldPlanBuildSpec,
    feature: VerifiedDevelopmentExampleFeatureArtifact,
    feature_spec: FeatureBuildSpec,
    label: VerifiedDevelopmentExampleLabelArtifact,
    label_spec: LabelBuildSpec,
    alignment: VerifiedDevelopmentExampleAlignmentArtifact,
    alignment_spec: AlignmentBuildSpec,
    model: VerifiedDevelopmentExampleModelArtifact,
    model_spec: LightgbmTrainingSpec,
    prediction: VerifiedDevelopmentExamplePredictionArtifact,
    prediction_spec: PredictionBuildSpec,
    config: LoadedM3Config,
    spec: EvaluationSpec,
    upstream_paths: EvaluationUpstreamPaths,
    artifact_roots: Mapping[str, Path],
) -> VerifiedDevelopmentExampleEvaluationArtifact:
    """Freshly verify the full lineage and one development evaluation bundle."""
    fresh_prediction = verify_development_example_prediction_artifact(
        root=prediction.root,
        receipt_path=upstream_paths.prediction_receipt_path,
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
        alignment=alignment,
        alignment_spec=alignment_spec,
        model=model,
        model_spec=model_spec,
        spec=prediction_spec,
        upstream_paths=upstream_paths.prediction_upstream_paths,
        config=config,
        artifact_roots=artifact_roots,
    )
    if not _same_verified_prediction(fresh_prediction, prediction):
        raise ValueError("evaluation prediction stale")
    _validate_evaluation_identity(
        release, feature, prediction, label, folds, experiment, config, spec
    )
    if (
        not root.is_dir()
        or root.is_symlink()
        or {item.name for item in os.scandir(root)} != _EVALUATION_FILES
    ):
        raise ValueError("evaluation tree closure drift")

    raw_manifest = (root / "evaluation_manifest.json").read_bytes()
    manifest = read_evaluation_manifest(root / "evaluation_manifest.json")
    daily = _read_evaluation_daily(root / "daily_ic.parquet")
    metrics = read_evaluation_metrics(root / "metrics.json")
    planned = next(item for item in folds.manifest.folds if item.name == spec.fold)
    expected_daily = _evaluate_daily_slices(
        eligible=_eligible_test_keys(release, planned.test_dates),
        scorable=_scorable_test_keys(feature),
        predictions=prediction.predictions.select("as_of", "symbol", "score"),
        labels=label.labels.filter(
            (pl.col("horizon_sessions") == spec.horizon_sessions)
            & pl.col("as_of").is_in(list(planned.test_dates))
        )
        .select("as_of", "symbol", "relative_return")
        .sort("as_of", "symbol"),
        evaluation_dates=planned.test_dates,
        minimum_ic_symbols=spec.minimum_ic_symbols,
    )
    if not daily.equals(expected_daily):
        raise ValueError("evaluation daily content drift")
    expected_metrics = _summarize_evaluation(
        daily=daily,
        prediction=prediction,
        spec=spec,
        daily_sha256=_file_sha(root / "daily_ic.parquet"),
    )
    if metrics != expected_metrics:
        raise ValueError("evaluation metrics/content drift")
    expected_manifest = EvaluationManifestV1(
        schema_version="m3-evaluation-artifact-v1",
        experiment_key=spec.experiment_key,
        work_key=spec.work_key,
        prediction_manifest_sha256=prediction.manifest_sha256,
        label_manifest_sha256=label.manifest_sha256,
        feature_manifest_sha256=feature.manifest_sha256,
        fold_plan_manifest_sha256=folds.manifest_sha256,
        eligible_keys_sha256=prediction.manifest.eligibility_sha256,
        evaluation_dates_sha256=_sha_dates(planned.test_dates),
        scientific_config_sha256=config.scientific_config_sha256,
        fold=spec.fold,
        horizon_sessions=spec.horizon_sessions,
        model=prediction.manifest.model,
        model_version=prediction.manifest.model_version,
        daily_sha256=_file_sha(root / "daily_ic.parquet"),
        metrics_sha256=_file_sha(root / "metrics.json"),
    )
    if manifest != expected_manifest:
        raise ValueError("evaluation manifest/content drift")

    verified_receipt = verify_stage_receipt_with_bytes(
        receipt_path=receipt_path, artifact_roots=artifact_roots
    )
    if verified_receipt is None:
        raise ValueError("evaluation receipt missing")
    receipt = verified_receipt.receipt
    inputs = _evaluation_receipt_inputs(
        release, feature, prediction, label, folds, experiment, upstream_paths
    )
    outputs = tuple(root / name for name in sorted(_EVALUATION_FILES))
    if (
        receipt.stage != "development-evaluation"
        or receipt.scope != "WORK"
        or receipt.scope_key != spec.work_key
        or not _digest_paths_equal(receipt.inputs, inputs, artifact_roots)
        or not _digest_paths_equal(receipt.outputs, outputs, artifact_roots)
    ):
        raise ValueError("evaluation receipt closure drift")
    return VerifiedDevelopmentExampleEvaluationArtifact(
        release_kind="development_example",
        formal_gate_eligible=False,
        example_id=prediction.example_id,
        root=root.resolve(strict=True),
        daily=daily,
        metrics=metrics,
        manifest=manifest,
        manifest_sha256=hashlib.sha256(raw_manifest).hexdigest(),
        evaluation_receipt_sha256=verified_receipt.sha256,
    )


def _evaluate_daily_slices(
    *,
    eligible: pl.DataFrame,
    scorable: pl.DataFrame,
    predictions: pl.DataFrame,
    labels: pl.DataFrame,
    evaluation_dates: tuple[dt.date, ...],
    minimum_ic_symbols: int,
) -> pl.DataFrame:
    """Rebuild five key layers and compute daily IC with explicit status."""
    _assert_evaluation_dates(evaluation_dates)
    if type(minimum_ic_symbols) is not int or minimum_ic_symbols < 2:
        raise ValueError("minimum_ic_symbols invalid")
    eligible = _validated_keys(eligible, value_column=None, name="eligible")
    scorable = _validated_keys(scorable, value_column=None, name="scorable")
    predictions = _validated_keys(predictions, value_column="score", name="predictions")
    labels = _validated_keys(labels, value_column="relative_return", name="labels")
    date_set = set(evaluation_dates)
    for name, frame in (
        ("eligible", eligible),
        ("scorable", scorable),
        ("predictions", predictions),
        ("labels", labels),
    ):
        if set(frame.get_column("as_of").to_list()) - date_set:
            raise ValueError(f"evaluation {name} date outside fold")
    eligible_keys = _key_set(eligible)
    scorable_keys = _key_set(scorable)
    prediction_keys = _key_set(predictions)
    label_keys = _key_set(labels)
    if not scorable_keys <= eligible_keys:
        raise ValueError("evaluation scorable not subset eligible")
    if prediction_keys != scorable_keys:
        raise ValueError("evaluation predicted differs from scorable")
    if not label_keys <= eligible_keys:
        raise ValueError("evaluation labeled not subset eligible")
    joined = predictions.join(labels, on=["as_of", "symbol"], how="inner")
    rows: list[dict[str, object]] = []
    for day in evaluation_dates:
        e = _day_count(eligible, day)
        s = _day_count(scorable, day)
        p = _day_count(predictions, day)
        lab = _day_count(labels, day)
        evaluated = joined.filter(pl.col("as_of") == day).sort("symbol")
        n_eval = evaluated.height
        scores = [float(value) for value in evaluated.get_column("score")]
        returns = [float(value) for value in evaluated.get_column("relative_return")]
        status = _daily_status(
            n_eligible=e,
            n_labeled=lab,
            n_predicted=p,
            n_evaluated=n_eval,
            minimum_ic_symbols=minimum_ic_symbols,
            scores=scores,
            returns=returns,
        )
        pearson = _pearson(scores, returns) if status == "COMPUTABLE" else None
        rank_ic = _spearman(scores, returns) if status == "COMPUTABLE" else None
        if status == "COMPUTABLE" and (pearson is None or rank_ic is None):
            raise ValueError("evaluation computable IC missing")
        rows.append(
            {
                "as_of": day,
                "n_eligible": e,
                "n_scorable": s,
                "n_predicted": p,
                "n_labeled": lab,
                "n_evaluated": n_eval,
                "feature_coverage": _ratio(s, e),
                "prediction_coverage": _ratio(p, s),
                "label_coverage": _ratio(lab, e),
                "evaluation_coverage": _ratio(n_eval, lab),
                "pearson_ic": pearson,
                "rank_ic": rank_ic,
                "ic_status": status,
            }
        )
    return pl.DataFrame(rows, schema=_DAILY_SCHEMA).sort("as_of")


def _daily_status(
    *,
    n_eligible: int,
    n_labeled: int,
    n_predicted: int,
    n_evaluated: int,
    minimum_ic_symbols: int,
    scores: list[float],
    returns: list[float],
) -> IcStatus:
    if n_eligible == 0:
        return "NO_ELIGIBLE"
    if n_labeled == 0:
        return "NO_LABELS"
    if n_predicted == 0:
        return "NO_PREDICTIONS"
    if n_evaluated < minimum_ic_symbols:
        return "INSUFFICIENT_SYMBOLS"
    score_zero = min(scores) == max(scores)
    label_zero = min(returns) == max(returns)
    if score_zero and label_zero:
        return "BOTH_ZERO_VARIANCE"
    if score_zero:
        return "SCORE_ZERO_VARIANCE"
    if label_zero:
        return "LABEL_ZERO_VARIANCE"
    return "COMPUTABLE"


def _summarize_evaluation(
    *,
    daily: pl.DataFrame,
    prediction: VerifiedDevelopmentExamplePredictionArtifact,
    spec: EvaluationSpec,
    daily_sha256: str,
) -> EvaluationMetricsV1:
    totals = {
        name: int(daily.get_column(name).sum())
        for name in ("n_eligible", "n_scorable", "n_predicted", "n_labeled", "n_evaluated")
    }
    computable = daily.filter(pl.col("ic_status") == "COMPUTABLE")
    pearsons = [float(value) for value in computable.get_column("pearson_ic")]
    ranks = [float(value) for value in computable.get_column("rank_ic")]
    status_counter = Counter(cast(list[str], daily.get_column("ic_status").to_list()))
    return EvaluationMetricsV1(
        schema_version="m3-evaluation-metrics-v1",
        experiment_key=spec.experiment_key,
        work_key=spec.work_key,
        fold=spec.fold,
        horizon_sessions=spec.horizon_sessions,
        model=prediction.manifest.model,
        model_version=prediction.manifest.model_version,
        n_dates=daily.height,
        n_computable_dates=computable.height,
        n_eligible=totals["n_eligible"],
        n_scorable=totals["n_scorable"],
        n_predicted=totals["n_predicted"],
        n_labeled=totals["n_labeled"],
        n_evaluated=totals["n_evaluated"],
        feature_coverage=_ratio(totals["n_scorable"], totals["n_eligible"]),
        prediction_coverage=_ratio(totals["n_predicted"], totals["n_scorable"]),
        label_coverage=_ratio(totals["n_labeled"], totals["n_eligible"]),
        evaluation_coverage=_ratio(totals["n_evaluated"], totals["n_labeled"]),
        pearson_ic_mean=_optional_mean(pearsons),
        rank_ic_mean=_optional_mean(ranks),
        pearson_icir=_optional_icir(pearsons),
        rank_icir=_optional_icir(ranks),
        status_counts=tuple((status, status_counter.get(status, 0)) for status in _IC_STATUSES),
        daily_sha256=daily_sha256,
    )


def read_evaluation_metrics(path: Path) -> EvaluationMetricsV1:
    raw = path.read_bytes()
    payload = _strict_json_object(raw)
    if set(payload) != {field.name for field in fields(EvaluationMetricsV1)}:
        raise ValueError("evaluation metrics fields drift")
    raw_counts = payload.get("status_counts")
    if type(raw_counts) is not list or any(
        type(item) is not list or len(item) != 2 for item in raw_counts
    ):
        raise ValueError("evaluation status_counts invalid")
    payload["status_counts"] = tuple(
        (cast(Any, item[0]), cast(Any, item[1])) for item in raw_counts
    )
    metrics = EvaluationMetricsV1(**cast(Any, payload))
    if raw != _canonical_bytes(asdict(metrics)):
        raise ValueError("evaluation metrics non-canonical")
    return metrics


def read_evaluation_manifest(path: Path) -> EvaluationManifestV1:
    raw = path.read_bytes()
    payload = _strict_json_object(raw)
    if set(payload) != {field.name for field in fields(EvaluationManifestV1)}:
        raise ValueError("evaluation manifest fields drift")
    manifest = EvaluationManifestV1(**cast(Any, payload))
    if raw != _canonical_bytes(asdict(manifest)):
        raise ValueError("evaluation manifest non-canonical")
    return manifest


_SUMMARY_FILES = {
    "daily_ic.parquet",
    "fold_metrics.parquet",
    "manifest.json",
    "metrics.json",
}
_FOLD_METRICS_SCHEMA = {
    "fold": pl.Utf8,
    "n_dates": pl.Int64,
    "n_computable_dates": pl.Int64,
    "n_eligible": pl.Int64,
    "n_scorable": pl.Int64,
    "n_predicted": pl.Int64,
    "n_labeled": pl.Int64,
    "n_evaluated": pl.Int64,
    "feature_coverage": pl.Float64,
    "prediction_coverage": pl.Float64,
    "label_coverage": pl.Float64,
    "evaluation_coverage": pl.Float64,
    "pearson_ic_mean": pl.Float64,
    "rank_ic_mean": pl.Float64,
    "pearson_icir": pl.Float64,
    "rank_icir": pl.Float64,
    "status_count_no_eligible": pl.Int64,
    "status_count_no_labels": pl.Int64,
    "status_count_no_predictions": pl.Int64,
    "status_count_insufficient_symbols": pl.Int64,
    "status_count_both_zero_variance": pl.Int64,
    "status_count_score_zero_variance": pl.Int64,
    "status_count_label_zero_variance": pl.Int64,
    "status_count_computable": pl.Int64,
}


def build_development_example_research_summary_artifact(
    *,
    evaluations: Sequence[VerifiedDevelopmentExampleEvaluationArtifact],
    experiment: VerifiedDevelopmentExampleExperimentIdentity,
    config: LoadedM3Config,
    horizon_sessions: int,
    output_root: Path,
) -> ResearchSummaryManifestV1:
    """Build a deterministic, experiment-scoped cross-fold research summary."""
    ordered = _validate_summary_inputs(
        evaluations, experiment, config, horizon_sessions
    )
    _require_empty_directory(output_root)
    daily = pl.concat([item.daily for item in ordered]).sort("as_of")
    _assert_summary_dates(daily)
    fold_metrics = _build_fold_metrics(ordered)
    daily_path = output_root / "daily_ic.parquet"
    fold_metrics_path = output_root / "fold_metrics.parquet"
    _write_parquet(daily, daily_path)
    _write_parquet(fold_metrics, fold_metrics_path)
    daily_sha = _file_sha(daily_path)
    metrics = _summarize_research(
        daily=daily,
        experiment_key=experiment.manifest.experiment_key,
        horizon_sessions=horizon_sessions,
        model=ordered[0].manifest.model,
        model_version=ordered[0].manifest.model_version,
        folds=tuple(item.manifest.fold for item in ordered),
        daily_sha256=daily_sha,
    )
    metrics_path = output_root / "metrics.json"
    _write_exclusive(metrics_path, _canonical_bytes(asdict(metrics)))
    manifest = ResearchSummaryManifestV1(
        schema_version="m3-research-summary-v1",
        experiment_key=experiment.manifest.experiment_key,
        horizon_sessions=horizon_sessions,
        model=ordered[0].manifest.model,
        model_version=ordered[0].manifest.model_version,
        scientific_config_sha256=config.scientific_config_sha256,
        folds=tuple(item.manifest.fold for item in ordered),
        evaluation_manifest_sha256s=tuple(item.manifest_sha256 for item in ordered),
        evaluation_receipt_sha256s=tuple(
            item.evaluation_receipt_sha256 for item in ordered
        ),
        test_dates_sha256=_sha_dates(
            tuple(cast(list[dt.date], daily.get_column("as_of").to_list()))
        ),
        daily_sha256=daily_sha,
        fold_metrics_sha256=_file_sha(fold_metrics_path),
        metrics_sha256=_file_sha(metrics_path),
    )
    _write_exclusive(output_root / "manifest.json", _canonical_bytes(asdict(manifest)))
    return manifest


@_evaluation_boundary
def verify_development_example_research_summary_artifact(
    *,
    root: Path,
    receipt_path: Path,
    evaluations: Sequence[VerifiedDevelopmentExampleEvaluationArtifact],
    experiment: VerifiedDevelopmentExampleExperimentIdentity,
    config: LoadedM3Config,
    horizon_sessions: int,
    upstream_paths: ResearchSummaryUpstreamPaths,
    artifact_roots: Mapping[str, Path],
) -> VerifiedDevelopmentExampleResearchSummaryArtifact:
    ordered = _validate_summary_inputs(
        evaluations, experiment, config, horizon_sessions
    )
    if len(upstream_paths.evaluation_receipt_paths) != len(ordered):
        raise ValueError("research summary receipt path count drift")
    _fresh_verify_summary_upstreams(
        ordered, experiment, upstream_paths
    )
    if (
        not root.is_dir()
        or root.is_symlink()
        or {item.name for item in os.scandir(root)} != _SUMMARY_FILES
    ):
        raise ValueError("research summary tree closure drift")
    raw_manifest = (root / "manifest.json").read_bytes()
    manifest = read_research_summary_manifest(root / "manifest.json")
    metrics = read_research_summary_metrics(root / "metrics.json")
    daily = _read_evaluation_daily(root / "daily_ic.parquet")
    fold_metrics = _read_fold_metrics(root / "fold_metrics.parquet")
    expected_daily = pl.concat([item.daily for item in ordered]).sort("as_of")
    _assert_summary_dates(expected_daily)
    expected_fold_metrics = _build_fold_metrics(ordered)
    if not daily.equals(expected_daily) or not fold_metrics.equals(expected_fold_metrics):
        raise ValueError("research summary table content drift")
    expected_metrics = _summarize_research(
        daily=daily,
        experiment_key=experiment.manifest.experiment_key,
        horizon_sessions=horizon_sessions,
        model=ordered[0].manifest.model,
        model_version=ordered[0].manifest.model_version,
        folds=tuple(item.manifest.fold for item in ordered),
        daily_sha256=_file_sha(root / "daily_ic.parquet"),
    )
    if metrics != expected_metrics:
        raise ValueError("research summary metrics/content drift")
    expected_manifest = ResearchSummaryManifestV1(
        schema_version="m3-research-summary-v1",
        experiment_key=experiment.manifest.experiment_key,
        horizon_sessions=horizon_sessions,
        model=ordered[0].manifest.model,
        model_version=ordered[0].manifest.model_version,
        scientific_config_sha256=config.scientific_config_sha256,
        folds=tuple(item.manifest.fold for item in ordered),
        evaluation_manifest_sha256s=tuple(item.manifest_sha256 for item in ordered),
        evaluation_receipt_sha256s=tuple(
            item.evaluation_receipt_sha256 for item in ordered
        ),
        test_dates_sha256=_sha_dates(
            tuple(cast(list[dt.date], daily.get_column("as_of").to_list()))
        ),
        daily_sha256=_file_sha(root / "daily_ic.parquet"),
        fold_metrics_sha256=_file_sha(root / "fold_metrics.parquet"),
        metrics_sha256=_file_sha(root / "metrics.json"),
    )
    if manifest != expected_manifest:
        raise ValueError("research summary manifest/content drift")
    verified_receipt = verify_stage_receipt_with_bytes(
        receipt_path=receipt_path, artifact_roots=artifact_roots
    )
    if verified_receipt is None:
        raise ValueError("research summary receipt missing")
    receipt = verified_receipt.receipt
    inputs = _summary_receipt_inputs(ordered, experiment, upstream_paths)
    outputs = tuple(root / name for name in sorted(_SUMMARY_FILES))
    if (
        receipt.stage != "development-research-summary"
        or receipt.scope != "EXPERIMENT"
        or receipt.scope_key != experiment.manifest.experiment_key
        or not _digest_paths_equal(receipt.inputs, inputs, artifact_roots)
        or not _digest_paths_equal(receipt.outputs, outputs, artifact_roots)
    ):
        raise ValueError("research summary receipt closure drift")
    return VerifiedDevelopmentExampleResearchSummaryArtifact(
        release_kind="development_example",
        formal_gate_eligible=False,
        example_id=experiment.example_id,
        root=root.resolve(strict=True),
        daily=daily,
        fold_metrics=fold_metrics,
        metrics=metrics,
        manifest=manifest,
        manifest_sha256=hashlib.sha256(raw_manifest).hexdigest(),
        summary_receipt_sha256=verified_receipt.sha256,
    )


def read_research_summary_metrics(path: Path) -> ResearchSummaryMetricsV1:
    raw = path.read_bytes()
    payload = _strict_json_object(raw)
    if set(payload) != {field.name for field in fields(ResearchSummaryMetricsV1)}:
        raise ValueError("research summary metrics fields drift")
    raw_counts = payload.get("status_counts")
    raw_folds = payload.get("folds")
    if (
        type(raw_counts) is not list
        or any(type(item) is not list or len(item) != 2 for item in raw_counts)
        or type(raw_folds) is not list
    ):
        raise ValueError("research summary metrics nested fields invalid")
    payload["status_counts"] = tuple(
        (cast(Any, item[0]), cast(Any, item[1])) for item in raw_counts
    )
    payload["folds"] = tuple(cast(list[str], raw_folds))
    metrics = ResearchSummaryMetricsV1(**cast(Any, payload))
    if raw != _canonical_bytes(asdict(metrics)):
        raise ValueError("research summary metrics non-canonical")
    return metrics


def read_research_summary_manifest(path: Path) -> ResearchSummaryManifestV1:
    raw = path.read_bytes()
    payload = _strict_json_object(raw)
    if set(payload) != {field.name for field in fields(ResearchSummaryManifestV1)}:
        raise ValueError("research summary manifest fields drift")
    for name in (
        "folds", "evaluation_manifest_sha256s", "evaluation_receipt_sha256s"
    ):
        value = payload.get(name)
        if type(value) is not list:
            raise ValueError("research summary manifest nested fields invalid")
        payload[name] = tuple(cast(list[str], value))
    manifest = ResearchSummaryManifestV1(**cast(Any, payload))
    if raw != _canonical_bytes(asdict(manifest)):
        raise ValueError("research summary manifest non-canonical")
    return manifest


def _validate_summary_inputs(
    evaluations: Sequence[VerifiedDevelopmentExampleEvaluationArtifact],
    experiment: VerifiedDevelopmentExampleExperimentIdentity,
    config: LoadedM3Config,
    horizon_sessions: int,
) -> tuple[VerifiedDevelopmentExampleEvaluationArtifact, ...]:
    if (
        not isinstance(evaluations, Sequence)
        or len(evaluations) < 2
        or any(
            type(item) is not VerifiedDevelopmentExampleEvaluationArtifact
            for item in evaluations
        )
        or type(experiment) is not VerifiedDevelopmentExampleExperimentIdentity
        or type(config) is not LoadedM3Config
        or type(horizon_sessions) is not int
        or horizon_sessions not in {5, 10}
    ):
        raise ValueError("research summary inputs invalid")
    ordered = tuple(sorted(evaluations, key=lambda item: item.manifest.fold))
    first = ordered[0]
    if (
        len({item.manifest.fold for item in ordered}) != len(ordered)
        or len({item.example_id for item in ordered} | {experiment.example_id}) != 1
        or config.scientific_config_sha256
        != experiment.manifest.scientific_config_sha256
        or any(
            item.manifest.experiment_key != experiment.manifest.experiment_key
            or item.manifest.horizon_sessions != horizon_sessions
            or item.manifest.model != first.manifest.model
            or item.manifest.model_version != first.manifest.model_version
            or item.manifest.scientific_config_sha256
            != config.scientific_config_sha256
            for item in ordered
        )
    ):
        raise ValueError("research summary identity drift")
    dates: list[dt.date] = []
    for item in ordered:
        item_dates = cast(list[dt.date], item.daily.get_column("as_of").to_list())
        if len(item_dates) != len(set(item_dates)):
            raise ValueError("research summary evaluation dates invalid")
        dates.extend(item_dates)
    if len(dates) != len(set(dates)):
        raise ValueError("research summary fold dates overlap")
    return ordered


def _assert_summary_dates(daily: pl.DataFrame) -> None:
    if daily.columns != list(_DAILY_SCHEMA) or daily.schema != _DAILY_SCHEMA:
        raise ValueError("research summary daily schema drift")
    dates = cast(list[dt.date], daily.get_column("as_of").to_list())
    if not dates or dates != sorted(dates) or len(dates) != len(set(dates)):
        raise ValueError("research summary dates drift")


def _build_fold_metrics(
    evaluations: Sequence[VerifiedDevelopmentExampleEvaluationArtifact],
) -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    status_columns: dict[IcStatus, str] = {
        "NO_ELIGIBLE": "status_count_no_eligible",
        "NO_LABELS": "status_count_no_labels",
        "NO_PREDICTIONS": "status_count_no_predictions",
        "INSUFFICIENT_SYMBOLS": "status_count_insufficient_symbols",
        "BOTH_ZERO_VARIANCE": "status_count_both_zero_variance",
        "SCORE_ZERO_VARIANCE": "status_count_score_zero_variance",
        "LABEL_ZERO_VARIANCE": "status_count_label_zero_variance",
        "COMPUTABLE": "status_count_computable",
    }
    for item in evaluations:
        metrics = item.metrics
        row: dict[str, object] = {
            "fold": item.manifest.fold,
            **{
                name: getattr(metrics, name)
                for name in tuple(_FOLD_METRICS_SCHEMA)[1:16]
            },
        }
        counts = dict(metrics.status_counts)
        row.update({column: counts[status] for status, column in status_columns.items()})
        rows.append(row)
    frame = pl.DataFrame(rows, schema=_FOLD_METRICS_SCHEMA).sort("fold")
    if frame.get_column("fold").to_list() != sorted(frame.get_column("fold").to_list()):
        raise ValueError("research summary fold order drift")
    return frame


def _read_fold_metrics(path: Path) -> pl.DataFrame:
    frame = pl.read_parquet(path)
    if (
        frame.columns != list(_FOLD_METRICS_SCHEMA)
        or frame.schema != _FOLD_METRICS_SCHEMA
        or frame.height < 2
        or frame.get_column("fold").to_list()
        != sorted(frame.get_column("fold").to_list())
        or frame.get_column("fold").n_unique() != frame.height
    ):
        raise ValueError("research summary fold metrics drift")
    return frame


def _summarize_research(
    *,
    daily: pl.DataFrame,
    experiment_key: str,
    horizon_sessions: int,
    model: str,
    model_version: str,
    folds: tuple[str, ...],
    daily_sha256: str,
) -> ResearchSummaryMetricsV1:
    totals = {
        name: int(daily.get_column(name).sum())
        for name in (
            "n_eligible", "n_scorable", "n_predicted", "n_labeled", "n_evaluated"
        )
    }
    computable = daily.filter(pl.col("ic_status") == "COMPUTABLE")
    pearsons = [float(value) for value in computable.get_column("pearson_ic")]
    ranks = [float(value) for value in computable.get_column("rank_ic")]
    status_counter = Counter(cast(list[str], daily.get_column("ic_status").to_list()))
    return ResearchSummaryMetricsV1(
        schema_version="m3-research-summary-metrics-v1",
        experiment_key=experiment_key,
        horizon_sessions=horizon_sessions,
        model=model,
        model_version=model_version,
        folds=folds,
        n_dates=daily.height,
        n_computable_dates=computable.height,
        n_eligible=totals["n_eligible"],
        n_scorable=totals["n_scorable"],
        n_predicted=totals["n_predicted"],
        n_labeled=totals["n_labeled"],
        n_evaluated=totals["n_evaluated"],
        feature_coverage=_ratio(totals["n_scorable"], totals["n_eligible"]),
        prediction_coverage=_ratio(totals["n_predicted"], totals["n_scorable"]),
        label_coverage=_ratio(totals["n_labeled"], totals["n_eligible"]),
        evaluation_coverage=_ratio(totals["n_evaluated"], totals["n_labeled"]),
        pearson_ic_mean=_optional_mean(pearsons),
        rank_ic_mean=_optional_mean(ranks),
        pearson_icir=_optional_icir(pearsons),
        rank_icir=_optional_icir(ranks),
        status_counts=tuple(
            (status, status_counter.get(status, 0)) for status in _IC_STATUSES
        ),
        daily_sha256=daily_sha256,
    )


def _fresh_verify_summary_upstreams(
    evaluations: Sequence[VerifiedDevelopmentExampleEvaluationArtifact],
    experiment: VerifiedDevelopmentExampleExperimentIdentity,
    upstream_paths: ResearchSummaryUpstreamPaths,
) -> None:
    if (
        not upstream_paths.experiment_receipt_path.is_file()
        or _file_sha(upstream_paths.experiment_receipt_path)
        != experiment.experiment_receipt_sha256
    ):
        raise ValueError("research summary experiment receipt stale")
    for item, receipt_path in zip(
        evaluations, upstream_paths.evaluation_receipt_paths, strict=True
    ):
        if (
            not receipt_path.is_file()
            or _file_sha(receipt_path) != item.evaluation_receipt_sha256
            or read_evaluation_manifest(item.root / "evaluation_manifest.json")
            != item.manifest
            or read_evaluation_metrics(item.root / "metrics.json") != item.metrics
            or not _read_evaluation_daily(item.root / "daily_ic.parquet").equals(item.daily)
        ):
            raise ValueError("research summary evaluation stale")


def _summary_receipt_inputs(
    evaluations: Sequence[VerifiedDevelopmentExampleEvaluationArtifact],
    experiment: VerifiedDevelopmentExampleExperimentIdentity,
    upstream_paths: ResearchSummaryUpstreamPaths,
) -> tuple[Path, ...]:
    paths = [
        experiment.root / "experiment_manifest.json",
        upstream_paths.experiment_receipt_path,
    ]
    for item, receipt_path in zip(
        evaluations, upstream_paths.evaluation_receipt_paths, strict=True
    ):
        paths.extend(
            (
                item.root / "daily_ic.parquet",
                item.root / "metrics.json",
                item.root / "evaluation_manifest.json",
                receipt_path,
            )
        )
    return tuple(paths)


def _read_evaluation_daily(path: Path) -> pl.DataFrame:
    frame = pl.read_parquet(path)
    if frame.columns != list(_DAILY_SCHEMA) or frame.schema != _DAILY_SCHEMA:
        raise ValueError("evaluation daily schema drift")
    if frame.height == 0 or frame.get_column("as_of").to_list() != sorted(
        frame.get_column("as_of").to_list()
    ):
        raise ValueError("evaluation daily date drift")
    if frame.get_column("as_of").n_unique() != frame.height:
        raise ValueError("evaluation daily duplicate dates")
    if any(value not in _IC_STATUSES for value in frame.get_column("ic_status")):
        raise ValueError("evaluation daily status drift")
    return frame


def _evaluation_receipt_inputs(
    release: VerifiedDevelopmentExampleG1Release,
    feature: VerifiedDevelopmentExampleFeatureArtifact,
    prediction: VerifiedDevelopmentExamplePredictionArtifact,
    label: VerifiedDevelopmentExampleLabelArtifact,
    folds: VerifiedDevelopmentExampleFoldPlanArtifact,
    experiment: VerifiedDevelopmentExampleExperimentIdentity,
    upstream_paths: EvaluationUpstreamPaths,
) -> tuple[Path, ...]:
    return (
        release.release.manifest_path,
        feature.root / "feature_manifest.json",
        upstream_paths.feature_receipt_path,
        prediction.root / "prediction_manifest.json",
        upstream_paths.prediction_receipt_path,
        label.root / "label_manifest.json",
        upstream_paths.label_receipt_path,
        folds.root / "folds.json",
        upstream_paths.fold_receipt_path,
        experiment.root / "experiment_manifest.json",
    )


def _same_verified_prediction(
    left: VerifiedDevelopmentExamplePredictionArtifact,
    right: VerifiedDevelopmentExamplePredictionArtifact,
) -> bool:
    return (
        left.release_kind == right.release_kind
        and left.formal_gate_eligible == right.formal_gate_eligible
        and left.example_id == right.example_id
        and left.root == right.root
        and left.predictions.equals(right.predictions)
        and left.manifest == right.manifest
        and left.manifest_sha256 == right.manifest_sha256
        and left.prediction_receipt_sha256 == right.prediction_receipt_sha256
    )


def _digest_paths_equal(
    digests: tuple[ArtifactDigest, ...],
    paths: Sequence[Path],
    roots: Mapping[str, Path],
) -> bool:
    if len(digests) != len(paths):
        return False
    actual = tuple(
        sorted(
            os.path.normcase(os.path.abspath(path_for_artifact_digest(item, artifact_roots=roots)))
            for item in digests
        )
    )
    expected = tuple(sorted(os.path.normcase(os.path.abspath(path)) for path in paths))
    return actual == expected and len(set(actual)) == len(actual)


def _validate_evaluation_identity(
    release: VerifiedDevelopmentExampleG1Release,
    feature: VerifiedDevelopmentExampleFeatureArtifact,
    prediction: VerifiedDevelopmentExamplePredictionArtifact,
    label: VerifiedDevelopmentExampleLabelArtifact,
    folds: VerifiedDevelopmentExampleFoldPlanArtifact,
    experiment: VerifiedDevelopmentExampleExperimentIdentity,
    config: LoadedM3Config,
    spec: EvaluationSpec,
) -> None:
    example_ids = {
        release.manifest.example_id,
        feature.example_id,
        prediction.example_id,
        label.example_id,
        folds.example_id,
        experiment.example_id,
    }
    if len(example_ids) != 1:
        raise ValueError("evaluation development identity mismatch")
    planned = next((item for item in folds.manifest.folds if item.name == spec.fold), None)
    if (
        planned is None
        or build_evaluation_spec(prediction=prediction, config=config) != spec
        or prediction.manifest.feature_manifest_sha256 != feature.manifest_sha256
        or prediction.manifest.eligibility_sha256
        != next(
            item for item in feature.manifest.segments if item.name == "test"
        ).eligible_keys_sha256
        or prediction.manifest.experiment_key != experiment.manifest.experiment_key
        or label.manifest.experiment_key != experiment.manifest.experiment_key
        or label.manifest.horizon_sessions != spec.horizon_sessions
        or feature.manifest.planned_fold_sha256 != planned.planned_fold_sha256
        or config.scientific_config_sha256 != experiment.manifest.scientific_config_sha256
    ):
        raise ValueError("evaluation identity/config drift")


def _eligible_test_keys(
    release: VerifiedDevelopmentExampleG1Release,
    dates: tuple[dt.date, ...],
) -> pl.DataFrame:
    path = dict(release.artifact_paths)["eligible_keys.parquet"]
    frame = (
        pl.read_parquet(path)
        .select("as_of", "symbol")
        .filter(pl.col("as_of").is_in(list(dates)))
        .sort("as_of", "symbol")
    )
    return _validated_keys(frame, value_column=None, name="eligible")


def _scorable_test_keys(
    feature: VerifiedDevelopmentExampleFeatureArtifact,
) -> pl.DataFrame:
    names = feature.manifest.schema.selected_names
    frame = (
        _read_feature_segment(feature, "test")
        .filter(_scorable_expression(names))
        .select("as_of", "symbol")
        .sort("as_of", "symbol")
    )
    return _validated_keys(frame, value_column=None, name="scorable")


def _validated_keys(
    frame: pl.DataFrame,
    *,
    value_column: str | None,
    name: str,
) -> pl.DataFrame:
    expected = ["as_of", "symbol", *(() if value_column is None else (value_column,))]
    if not isinstance(frame, pl.DataFrame) or frame.columns != expected:
        raise ValueError(f"evaluation {name} schema drift")
    if frame.schema["as_of"] != pl.Date or frame.schema["symbol"] != pl.Utf8:
        raise ValueError(f"evaluation {name} dtype drift")
    if value_column is not None and (
        frame.schema[value_column] != pl.Float64
        or not frame.get_column(value_column).is_finite().all()
    ):
        raise ValueError(f"evaluation {name} value invalid")
    ordered = frame.sort("as_of", "symbol")
    if ordered.select("as_of", "symbol").n_unique() != ordered.height:
        raise ValueError(f"evaluation {name} duplicate keys")
    return ordered


def _key_set(frame: pl.DataFrame) -> set[tuple[dt.date, str]]:
    return set(cast(list[tuple[dt.date, str]], frame.select("as_of", "symbol").rows()))


def _day_count(frame: pl.DataFrame, day: dt.date) -> int:
    return frame.filter(pl.col("as_of") == day).height


def _ratio(numerator: int, denominator: int) -> float | None:
    return float(numerator / denominator) if denominator else None


def _optional_mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _optional_icir(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    if variance == 0.0:
        return None
    return mean / math.sqrt(variance)


def _sha_dates(dates: tuple[dt.date, ...]) -> str:
    return hashlib.sha256(_canonical_bytes([day.isoformat() for day in dates])).hexdigest()


def _strict_json_object(raw: bytes) -> dict[str, object]:
    def hook(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    value = json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=hook,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("non-finite JSON")),
    )
    if type(value) is not dict or raw != _canonical_bytes(value):
        raise ValueError("non-canonical JSON")
    return value


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require_empty_directory(path: Path) -> None:
    if not path.is_dir() or path.is_symlink() or any(path.iterdir()):
        raise ValueError("evaluation output must be an empty real directory")


def _write_exclusive(path: Path, raw: bytes) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
        0o644,
    )
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _write_parquet(frame: pl.DataFrame, path: Path) -> None:
    frame.write_parquet(
        path,
        compression="zstd",
        compression_level=3,
        statistics=True,
        row_group_size=65536,
        use_pyarrow=False,
    )
