"""G6B development/example cross-fold research-summary adversarial tests."""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib
import json
import math
import sys
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, cast

import polars as pl
import pytest

from quant.research.m3.config import load_m3_config
from quant.research.m3.contracts import (
    EvaluationManifestV1,
    EvaluationMetricsV1,
    ExperimentIdentityManifestV1,
    ResearchSummaryUpstreamPaths,
)
from quant.research.m3.development_example import (
    VerifiedDevelopmentExampleEvaluationArtifact,
    VerifiedDevelopmentExampleExperimentIdentity,
    VerifiedDevelopmentExampleResearchSummaryArtifact,
)
from quant.research.m3.evaluate import (
    build_development_example_research_summary_artifact,
    verify_development_example_research_summary_artifact,
)
from quant.research.m3.run_state import publish_stage_receipt

_HEX = "a" * 64
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
_FOLD_METRICS_COLUMNS = (
    "fold",
    "n_dates",
    "n_computable_dates",
    "n_eligible",
    "n_scorable",
    "n_predicted",
    "n_labeled",
    "n_evaluated",
    "feature_coverage",
    "prediction_coverage",
    "label_coverage",
    "evaluation_coverage",
    "pearson_ic_mean",
    "rank_ic_mean",
    "pearson_icir",
    "rank_icir",
    "status_count_no_eligible",
    "status_count_no_labels",
    "status_count_no_predictions",
    "status_count_insufficient_symbols",
    "status_count_both_zero_variance",
    "status_count_score_zero_variance",
    "status_count_label_zero_variance",
    "status_count_computable",
)
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
    "ic_status": pl.String,
}


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _icir(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return None if variance == 0.0 else mean / math.sqrt(variance)


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _daily(rows: list[dict[str, object]]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=_DAILY_SCHEMA).sort("as_of")


def _metrics(
    *,
    daily: pl.DataFrame,
    experiment_key: str,
    work_key: str,
    fold: str,
    horizon: int,
    model: str,
    model_version: str,
    daily_sha256: str,
) -> EvaluationMetricsV1:
    totals = {
        name: int(daily.get_column(name).sum())
        for name in (
            "n_eligible",
            "n_scorable",
            "n_predicted",
            "n_labeled",
            "n_evaluated",
        )
    }
    computable = daily.filter(pl.col("ic_status") == "COMPUTABLE")
    pearsons = cast(list[float], computable.get_column("pearson_ic").to_list())
    ranks = cast(list[float], computable.get_column("rank_ic").to_list())
    status_values = daily.get_column("ic_status").to_list()
    return EvaluationMetricsV1(
        schema_version="m3-evaluation-metrics-v1",
        experiment_key=experiment_key,
        work_key=work_key,
        fold=fold,
        horizon_sessions=horizon,
        model=model,
        model_version=model_version,
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
        pearson_ic_mean=sum(pearsons) / len(pearsons) if pearsons else None,
        rank_ic_mean=sum(ranks) / len(ranks) if ranks else None,
        pearson_icir=_icir(pearsons),
        rank_icir=_icir(ranks),
        status_counts=tuple((status, status_values.count(status)) for status in _STATUSES),
        daily_sha256=daily_sha256,
    )


def _write_parquet(frame: pl.DataFrame, path: Path) -> None:
    frame.write_parquet(
        path,
        compression="zstd",
        compression_level=3,
        statistics=True,
        row_group_size=65536,
        data_page_size=1048576,
    )


def _make_evaluation(
    *,
    common: Path,
    example_id: str,
    experiment_key: str,
    fold: str,
    horizon: int,
    model: str,
    model_version: str,
    daily: pl.DataFrame,
) -> tuple[VerifiedDevelopmentExampleEvaluationArtifact, Path]:
    work_key = hashlib.sha256(
        f"{experiment_key}|{fold}|{horizon}|{model}|{model_version}".encode()
    ).hexdigest()
    root = common / f"development-example-evaluation-{fold}-h{horizon}"
    root.mkdir()
    daily_path = root / "daily_ic.parquet"
    _write_parquet(daily, daily_path)
    metrics = _metrics(
        daily=daily,
        experiment_key=experiment_key,
        work_key=work_key,
        fold=fold,
        horizon=horizon,
        model=model,
        model_version=model_version,
        daily_sha256=_sha(daily_path),
    )
    metrics_path = root / "metrics.json"
    metrics_path.write_bytes(_canonical(asdict(metrics)))
    manifest = EvaluationManifestV1(
        schema_version="m3-evaluation-artifact-v1",
        experiment_key=experiment_key,
        work_key=work_key,
        prediction_manifest_sha256=hashlib.sha256(f"prediction-{work_key}".encode()).hexdigest(),
        label_manifest_sha256=hashlib.sha256(f"label-{horizon}".encode()).hexdigest(),
        feature_manifest_sha256=hashlib.sha256(f"feature-{fold}".encode()).hexdigest(),
        fold_plan_manifest_sha256=hashlib.sha256(b"fold-plan").hexdigest(),
        eligible_keys_sha256=hashlib.sha256(b"eligible").hexdigest(),
        evaluation_dates_sha256=hashlib.sha256(
            _canonical([day.isoformat() for day in daily.get_column("as_of")])
        ).hexdigest(),
        scientific_config_sha256=_CONFIG.scientific_config_sha256,
        fold=fold,
        horizon_sessions=horizon,
        model=model,
        model_version=model_version,
        daily_sha256=_sha(daily_path),
        metrics_sha256=_sha(metrics_path),
    )
    manifest_path = root / "evaluation_manifest.json"
    manifest_path.write_bytes(_canonical(asdict(manifest)))
    receipt = common / "receipts" / "development-evaluation" / f"{work_key}.json"
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_bytes(_canonical({"fixture": "development-evaluation", "work_key": work_key}))
    verified = VerifiedDevelopmentExampleEvaluationArtifact(
        release_kind="development_example",
        formal_gate_eligible=False,
        example_id=example_id,
        root=root,
        daily=daily,
        metrics=metrics,
        manifest=manifest,
        manifest_sha256=_sha(manifest_path),
        evaluation_receipt_sha256=_sha(receipt),
    )
    return verified, receipt


def _fold_rows(start: dt.date, ics: tuple[float | None, ...]) -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    for offset, ic in enumerate(ics):
        day = start + dt.timedelta(days=offset)
        computable = ic is not None
        n_labeled = 4 if computable else 0
        rows.append(
            {
                "as_of": day,
                "n_eligible": 4,
                "n_scorable": 4,
                "n_predicted": 4,
                "n_labeled": n_labeled,
                "n_evaluated": n_labeled,
                "feature_coverage": 1.0,
                "prediction_coverage": 1.0,
                "label_coverage": 1.0 if computable else 0.0,
                "evaluation_coverage": 1.0 if computable else None,
                "pearson_ic": ic,
                "rank_ic": ic,
                "ic_status": "COMPUTABLE" if computable else "NO_LABELS",
            }
        )
    return _daily(rows)


_CONFIG = load_m3_config(
    Path(__file__).parents[2] / "configs" / "research" / "m3_qlib_example.toml"
)


def _context(tmp_path: Path, *, identity_seed: str = "one") -> dict[str, Any]:
    common = tmp_path / f"development-example-summary-context-{identity_seed}"
    common.mkdir(parents=True)
    experiment_key = hashlib.sha256(f"experiment-{identity_seed}".encode()).hexdigest()
    example_id = "development-example-" + hashlib.sha256(
        f"example-{identity_seed}".encode()
    ).hexdigest()
    experiment_root = common / "development-example-experiment"
    experiment_root.mkdir()
    experiment_manifest = ExperimentIdentityManifestV1(
        schema_version="m3-experiment-identity-v1",
        experiment_key=experiment_key,
        snapshot_id=hashlib.sha256(f"snapshot-{identity_seed}".encode()).hexdigest(),
        snapshot_manifest_sha256=_HEX,
        provider_key=hashlib.sha256(f"provider-{identity_seed}".encode()).hexdigest(),
        provider_manifest_sha256=_HEX,
        provider_receipt_sha256=_HEX,
        scientific_config_sha256=_CONFIG.scientific_config_sha256,
        dependency_fingerprint_sha256=_HEX,
        code_version="development-example/g6b-test-v1",
    )
    experiment_manifest_path = experiment_root / "experiment_manifest.json"
    experiment_manifest_path.write_bytes(_canonical(asdict(experiment_manifest)))
    experiment_receipt = (
        common / "receipts" / "development-experiment-identity" / f"{experiment_key}.json"
    )
    experiment_receipt.parent.mkdir(parents=True)
    experiment_receipt.write_bytes(
        _canonical({"fixture": "development-experiment", "experiment_key": experiment_key})
    )
    experiment = VerifiedDevelopmentExampleExperimentIdentity(
        release_kind="development_example",
        formal_gate_eligible=False,
        example_id=example_id,
        root=experiment_root,
        manifest=experiment_manifest,
        manifest_sha256=_sha(experiment_manifest_path),
        experiment_receipt_sha256=_sha(experiment_receipt),
    )
    first, first_receipt = _make_evaluation(
        common=common,
        example_id=example_id,
        experiment_key=experiment_key,
        fold="fold_001",
        horizon=5,
        model="lightgbm",
        model_version="fixture-v1",
        daily=_fold_rows(dt.date(2025, 1, 2), (1.0, -1.0)),
    )
    second, second_receipt = _make_evaluation(
        common=common,
        example_id=example_id,
        experiment_key=experiment_key,
        fold="fold_002",
        horizon=5,
        model="lightgbm",
        model_version="fixture-v1",
        daily=_fold_rows(dt.date(2025, 1, 6), (0.5, None)),
    )
    roots = {"root": common}
    return {
        "common": common,
        "roots": roots,
        "experiment": experiment,
        "experiment_receipt": experiment_receipt,
        "evaluations": (first, second),
        "evaluation_receipts": (first_receipt, second_receipt),
    }


def _summary_inputs(context: dict[str, Any]) -> list[tuple[str, Path]]:
    experiment = context["experiment"]
    result = [
        ("root", experiment.root / "experiment_manifest.json"),
        ("root", context["experiment_receipt"]),
    ]
    for evaluation, receipt in sorted(
        zip(context["evaluations"], context["evaluation_receipts"], strict=True),
        key=lambda item: item[0].manifest.fold,
    ):
        result.extend(
            [
                ("root", evaluation.root / "daily_ic.parquet"),
                ("root", evaluation.root / "metrics.json"),
                ("root", evaluation.root / "evaluation_manifest.json"),
                ("root", receipt),
            ]
        )
    return result


def _summary_outputs(root: Path) -> list[tuple[str, Path]]:
    return [
        ("root", root / "daily_ic.parquet"),
        ("root", root / "fold_metrics.parquet"),
        ("root", root / "metrics.json"),
        ("root", root / "manifest.json"),
    ]


def _build(context: dict[str, Any], *, suffix: str = "base") -> tuple[Path, Path, Any]:
    root = context["common"] / f"development-example-research-summary-{suffix}"
    root.mkdir()
    manifest = build_development_example_research_summary_artifact(
        evaluations=tuple(reversed(context["evaluations"])),
        experiment=context["experiment"],
        config=_CONFIG,
        horizon_sessions=5,
        output_root=root,
    )
    receipt = (
        context["common"]
        / "receipts"
        / "development-research-summary"
        / f"{context['experiment'].manifest.experiment_key}-{suffix}.json"
    )
    receipt.parent.mkdir(parents=True, exist_ok=True)
    publish_stage_receipt(
        receipt_path=receipt,
        stage="development-research-summary",
        scope="EXPERIMENT",
        scope_key=context["experiment"].manifest.experiment_key,
        artifact_roots=context["roots"],
        inputs=_summary_inputs(context),
        outputs=_summary_outputs(root),
    )
    return root, receipt, manifest


def _verify(
    context: dict[str, Any],
    root: Path,
    receipt: Path,
    *,
    evaluations: tuple[Any, ...] | None = None,
) -> VerifiedDevelopmentExampleResearchSummaryArtifact:
    upstream = ResearchSummaryUpstreamPaths(
        experiment_receipt_path=context["experiment_receipt"],
        evaluation_receipt_paths=tuple(context["evaluation_receipts"]),
    )
    return verify_development_example_research_summary_artifact(
        root=root,
        receipt_path=receipt,
        evaluations=evaluations or context["evaluations"],
        experiment=context["experiment"],
        config=_CONFIG,
        horizon_sessions=5,
        upstream_paths=upstream,
        artifact_roots=context["roots"],
    )


def test_two_fold_summary_sorts_folds_recomputes_daily_metrics_and_identity(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    root, receipt, manifest = _build(context)
    verified = _verify(context, root, receipt)
    assert isinstance(verified, VerifiedDevelopmentExampleResearchSummaryArtifact)
    assert verified.release_kind == "development_example"
    assert verified.formal_gate_eligible is False
    assert verified.example_id == context["experiment"].example_id
    assert verified.manifest == manifest
    assert verified.manifest.folds == ("fold_001", "fold_002")
    assert verified.fold_metrics.get_column("fold").to_list() == ["fold_001", "fold_002"]
    dates = verified.daily.get_column("as_of").to_list()
    assert dates == sorted(dates) and len(dates) == len(set(dates)) == 4

    metrics = verified.metrics
    assert metrics.n_dates == 4 and metrics.n_computable_dates == 3
    assert metrics.n_eligible == metrics.n_scorable == metrics.n_predicted == 16
    assert metrics.n_labeled == metrics.n_evaluated == 12
    assert metrics.feature_coverage == metrics.prediction_coverage == 1.0
    assert metrics.label_coverage == 12 / 16
    assert metrics.evaluation_coverage == 1.0
    values = [1.0, -1.0, 0.5]
    assert metrics.pearson_ic_mean == pytest.approx(sum(values) / len(values))
    assert metrics.rank_ic_mean == pytest.approx(sum(values) / len(values))
    assert metrics.pearson_icir == pytest.approx(cast(float, _icir(values)))
    assert metrics.rank_icir == pytest.approx(cast(float, _icir(values)))
    fold_icirs = verified.fold_metrics.get_column("rank_icir").to_list()
    assert fold_icirs == [0.0, None]
    assert metrics.rank_icir != 0.0

    assert tuple(verified.fold_metrics.columns) == _FOLD_METRICS_COLUMNS
    for name, dtype in verified.fold_metrics.schema.items():
        if name == "fold":
            assert dtype == pl.String
        elif name.startswith("n_") or name.startswith("status_count_"):
            assert dtype == pl.Int64
        else:
            assert dtype == pl.Float64
    assert manifest.daily_sha256 == _sha(root / "daily_ic.parquet")
    assert manifest.fold_metrics_sha256 == _sha(root / "fold_metrics.parquet")
    assert verified.summary_receipt_sha256 == _sha(receipt)


@pytest.mark.parametrize("drift", ["overlap", "horizon", "model", "experiment"])
def test_summary_rejects_overlap_and_cross_identity_mix(
    tmp_path: Path, drift: str
) -> None:
    context = _context(tmp_path)
    first, second = context["evaluations"]
    if drift == "overlap":
        changed = replace(
            second,
            daily=second.daily.with_columns(first.daily.get_column("as_of")),
        )
    elif drift == "horizon":
        changed = replace(
            second,
            metrics=replace(second.metrics, horizon_sessions=10),
            manifest=replace(second.manifest, horizon_sessions=10),
        )
    elif drift == "model":
        changed = replace(
            second,
            metrics=replace(second.metrics, model="linear"),
            manifest=replace(second.manifest, model="linear"),
        )
    else:
        changed = replace(
            second,
            metrics=replace(second.metrics, experiment_key="f" * 64),
            manifest=replace(second.manifest, experiment_key="f" * 64),
        )
    root = context["common"] / f"development-example-summary-drift-{drift}"
    root.mkdir()
    with pytest.raises(ValueError):
        build_development_example_research_summary_artifact(
            evaluations=(first, changed),
            experiment=context["experiment"],
            config=_CONFIG,
            horizon_sessions=5,
            output_root=root,
        )
    assert not any(root.iterdir())


def test_summary_no_clobber_exact_receipt_and_every_output_tamper(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    root, receipt, _ = _build(context)
    before = {path.name: path.read_bytes() for path in root.iterdir()}
    with pytest.raises(ValueError):
        build_development_example_research_summary_artifact(
            evaluations=context["evaluations"],
            experiment=context["experiment"],
            config=_CONFIG,
            horizon_sessions=5,
            output_root=root,
        )
    assert {path.name: path.read_bytes() for path in root.iterdir()} == before

    for _, target in [*_summary_outputs(root), ("root", receipt)]:
        original = target.read_bytes()
        target.write_bytes(original + b"drift")
        with pytest.raises(ValueError):
            _verify(context, root, receipt)
        target.write_bytes(original)
        _verify(context, root, receipt)

    decoy = context["common"] / "summary-decoy.json"
    decoy.write_text("{}", encoding="utf-8")
    extra_receipt = (
        context["common"] / "receipts" / "development-research-summary" / "extra.json"
    )
    publish_stage_receipt(
        receipt_path=extra_receipt,
        stage="development-research-summary",
        scope="EXPERIMENT",
        scope_key=context["experiment"].manifest.experiment_key,
        artifact_roots=context["roots"],
        inputs=[*_summary_inputs(context), ("root", decoy)],
        outputs=_summary_outputs(root),
    )
    with pytest.raises(ValueError):
        _verify(context, root, extra_receipt)


def test_whole_summary_bundle_from_other_experiment_is_rejected(
    tmp_path: Path,
) -> None:
    first_context = _context(tmp_path / "first", identity_seed="first")
    second_context = _context(tmp_path / "second", identity_seed="second")
    first_root, first_receipt, _ = _build(first_context)
    second_root, second_receipt, _ = _build(second_context)
    for _, first_path in _summary_outputs(first_root):
        first_path.write_bytes((second_root / first_path.name).read_bytes())
    first_receipt.write_bytes(second_receipt.read_bytes())
    with pytest.raises(ValueError):
        _verify(first_context, first_root, first_receipt)


def test_summary_core_import_does_not_load_heavy_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in tuple(sys.modules):
        if name in {"qlib", "lightgbm", "mlflow"} or name.startswith(
            ("qlib.", "lightgbm.", "mlflow.")
        ):
            monkeypatch.delitem(sys.modules, name, raising=False)
    importlib.reload(importlib.import_module("quant.research.m3.evaluate"))
    assert not any(
        name in {"qlib", "lightgbm", "mlflow"}
        or name.startswith(("qlib.", "lightgbm.", "mlflow."))
        for name in sys.modules
    )
