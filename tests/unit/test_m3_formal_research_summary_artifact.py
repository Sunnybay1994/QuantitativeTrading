"""Formal G6B research-summary artifact contract tests."""

from __future__ import annotations

import hashlib
import importlib.util
import math
from dataclasses import asdict, replace
from datetime import timedelta
from pathlib import Path
from typing import Any, cast

import polars as pl
import pytest

import quant.research.m3 as m3_public
import quant.research.m3.evaluate as summary_module
from quant.research.m3.contracts import (
    EvaluationSpec,
    FoldPlanManifestV1,
    PlannedFold,
    ResearchSummaryUpstreamPaths,
    VerifiedEvaluationArtifact,
    VerifiedFoldPlanArtifact,
    VerifiedResearchSummaryArtifact,
)
from quant.research.m3.evaluate import (
    EvaluationFreshVerificationContext,
    build_research_summary_artifact,
    verify_research_summary_artifact,
)
from quant.research.m3.run_state import publish_stage_receipt

_SUPPORT_SPEC = importlib.util.spec_from_file_location(
    "m3_formal_evaluation_support_for_summary",
    Path(__file__).with_name("test_m3_formal_evaluation_artifact.py"),
)
assert _SUPPORT_SPEC is not None and _SUPPORT_SPEC.loader is not None
_SUPPORT = importlib.util.module_from_spec(_SUPPORT_SPEC)
_SUPPORT_SPEC.loader.exec_module(_SUPPORT)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _shift_fold(source: PlannedFold, index: int) -> PlannedFold:
    delta = timedelta(days=366 * index)
    shifted = {
        name: tuple(day + delta for day in cast(tuple[Any, ...], getattr(source, name)))
        for name in (
            "train_dates",
            "train_validation_embargo_dates",
            "validation_dates",
            "validation_test_embargo_dates",
            "test_dates",
        )
    }
    return replace(
        source,
        name=f"fold_{index + 1:03d}",
        **shifted,
        train_label_available_by=source.train_label_available_by + delta,
        validation_label_available_by=source.validation_label_available_by + delta,
        planned_fold_sha256=hashlib.sha256(f"fold-{index}".encode()).hexdigest(),
    )


def _context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    base = _SUPPORT._evaluation_context(tmp_path, monkeypatch)
    _, _, _, template = _SUPPORT._build_publish_verify(base, "summary-template")
    kwargs = base["evaluation_kwargs"]
    planned = tuple(_shift_fold(kwargs["folds"].manifest.folds[0], i) for i in range(3))
    fold_manifest = replace(
        kwargs["folds"].manifest,
        folds=planned,
        signal_end=planned[-1].test_dates[-1],
    )
    folds = VerifiedFoldPlanArtifact(
        root=kwargs["folds"].root,
        manifest=cast(FoldPlanManifestV1, fold_manifest),
        manifest_sha256=hashlib.sha256(b"summary-fold-plan").hexdigest(),
        folds_receipt_sha256=kwargs["folds"].folds_receipt_sha256,
    )
    evaluations: list[VerifiedEvaluationArtifact] = []
    contexts: list[EvaluationFreshVerificationContext] = []
    receipts: list[Path] = []
    for index, fold in enumerate(planned):
        root = base["common"] / f"formal-evaluation-summary-{index}"
        root.mkdir()
        daily = template.daily.with_columns(
            pl.Series("as_of", list(fold.test_dates), dtype=pl.Date)
        )
        assert daily.height == len(fold.test_dates)
        for name, raw in (
            ("daily_ic.parquet", f"daily-{index}".encode()),
            ("metrics.json", f"metrics-{index}".encode()),
            ("evaluation_manifest.json", f"manifest-{index}".encode()),
        ):
            (root / name).write_bytes(raw)
        receipt = base["common"] / "receipts" / "evaluation" / f"g6b-{index}.json"
        receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_bytes(f"receipt-{index}".encode())
        manifest = replace(
            template.manifest,
            fold=fold.name,
            work_key=hashlib.sha256(f"work-{index}".encode()).hexdigest(),
            fold_plan_manifest_sha256=folds.manifest_sha256,
            evaluation_dates_sha256=summary_module._sha_dates(fold.test_dates),
            daily_sha256=hashlib.sha256(f"daily-{index}".encode()).hexdigest(),
            metrics_sha256=hashlib.sha256(f"metrics-{index}".encode()).hexdigest(),
        )
        metrics = replace(
            template.metrics,
            fold=fold.name,
            work_key=manifest.work_key,
            daily_sha256=manifest.daily_sha256,
        )
        evaluation = VerifiedEvaluationArtifact(
            root=root,
            daily=daily,
            metrics=metrics,
            manifest=manifest,
            manifest_sha256=_sha(root / "evaluation_manifest.json"),
            evaluation_receipt_sha256=_sha(receipt),
        )
        spec = replace(
            kwargs["spec"], fold=fold.name, work_key=manifest.work_key
        )
        contexts.append(
            EvaluationFreshVerificationContext(
                release=kwargs["release"], snapshot=kwargs["snapshot"],
                snapshot_spec=kwargs["snapshot_spec"], provider=kwargs["provider"],
                provider_spec=kwargs["provider_spec"], experiment=kwargs["experiment"],
                experiment_spec=kwargs["experiment_spec"], folds=folds,
                fold_spec=kwargs["fold_spec"], feature=kwargs["feature"],
                feature_spec=kwargs["feature_spec"], label=kwargs["label"],
                label_spec=kwargs["label_spec"], alignment=kwargs["alignment"],
                alignment_spec=kwargs["alignment_spec"], model=kwargs["model"],
                model_spec=kwargs["model_spec"], prediction=kwargs["prediction"],
                prediction_spec=kwargs["prediction_spec"],
                evaluation_spec=cast(EvaluationSpec, spec),
                evaluation_upstream_paths=kwargs["upstream_paths"],
            )
        )
        evaluations.append(evaluation)
        receipts.append(receipt)
    by_root = {item.root: item for item in evaluations}
    monkeypatch.setattr(
        summary_module,
        "verify_evaluation_artifact",
        lambda **call: by_root[call["root"]],
    )
    experiment_receipt = (
        kwargs["upstream_paths"].prediction_upstream_paths.feature_upstream_paths
        .fold_upstream_paths.experiment_receipt_path
    )
    return {
        "base": base,
        "evaluations": tuple(evaluations),
        "contexts": tuple(contexts),
        "experiment": kwargs["experiment"],
        "config": kwargs["config"],
        "upstream": ResearchSummaryUpstreamPaths(
            experiment_receipt_path=experiment_receipt,
            evaluation_receipt_paths=tuple(receipts),
        ),
        "roots": kwargs["artifact_roots"],
    }


def _receipt_inputs(context: dict[str, Any]) -> list[tuple[str, Path]]:
    paths = summary_module._formal_summary_receipt_inputs(
        context["evaluations"], context["experiment"], context["upstream"]
    )
    return [("root", path) for path in paths]


def _receipt_outputs(root: Path) -> list[tuple[str, Path]]:
    return [("root", root / name) for name in sorted(summary_module._SUMMARY_FILES)]


def test_summary_icir_is_recomputed_from_concatenated_daily_observations() -> None:
    values = (1.0, 2.0, 10.0, 12.0, -3.0, 4.0)
    daily = pl.DataFrame(
        {
            "as_of": pl.date_range(
                start=summary_module.dt.date(2026, 1, 1),
                end=summary_module.dt.date(2026, 1, 6),
                interval="1d", eager=True,
            ),
            **{
                name: [2] * len(values)
                for name in (
                    "n_eligible", "n_scorable", "n_predicted", "n_labeled",
                    "n_evaluated",
                )
            },
            **{
                name: [1.0] * len(values)
                for name in (
                    "feature_coverage", "prediction_coverage", "label_coverage",
                    "evaluation_coverage",
                )
            },
            "pearson_ic": values,
            "rank_ic": values,
            "ic_status": ["COMPUTABLE"] * len(values),
        },
        schema=summary_module._DAILY_SCHEMA,
    )
    metrics = summary_module._summarize_research(
        daily=daily, experiment_key="0" * 64, horizon_sessions=5,
        model="lightgbm", model_version="v1",
        folds=("fold_001", "fold_002", "fold_003"), daily_sha256="1" * 64,
    )
    mean = sum(values) / len(values)
    sample_std = math.sqrt(
        sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    )
    concatenated_icir = mean / sample_std
    fold_icirs = tuple(
        (sum(pair) / 2.0) / (abs(pair[1] - pair[0]) / math.sqrt(2.0))
        for pair in (values[:2], values[2:4], values[4:])
    )
    assert metrics.rank_icir == pytest.approx(concatenated_icir)
    assert metrics.rank_icir != pytest.approx(sum(fold_icirs) / len(fold_icirs))


def test_formal_summary_closed_loop_exact_folds_math_projection_and_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path, monkeypatch)
    root = context["base"]["common"] / "horizon=5"
    root.mkdir()
    manifest = build_research_summary_artifact(
        evaluations=context["evaluations"],
        evaluation_contexts=context["contexts"],
        experiment=context["experiment"], config=context["config"],
        horizon_sessions=5, upstream_paths=context["upstream"],
        artifact_roots=context["roots"], output_root=root,
    )
    receipt = context["base"]["common"] / "receipts" / "summary.json"
    publish_stage_receipt(
        receipt_path=receipt, stage="research-summary", scope="EXPERIMENT",
        scope_key=context["experiment"].manifest.experiment_key,
        artifact_roots=context["roots"], inputs=_receipt_inputs(context),
        outputs=_receipt_outputs(root),
    )
    verified = verify_research_summary_artifact(
        root=root, receipt_path=receipt,
        evaluations=context["evaluations"],
        evaluation_contexts=context["contexts"],
        experiment=context["experiment"], config=context["config"],
        horizon_sessions=5, upstream_paths=context["upstream"],
        artifact_roots=context["roots"],
    )
    assert type(verified) is VerifiedResearchSummaryArtifact
    assert verified.manifest == manifest
    assert verified.manifest.folds == ("fold_001", "fold_002", "fold_003")
    assert len(_receipt_inputs(context)) == 2 + 4 * 3
    assert len(_receipt_outputs(root)) == 4
    expected_fold_metrics = summary_module._build_formal_fold_metrics(
        context["evaluations"]
    )
    assert verified.fold_metrics.equals(expected_fold_metrics)
    expected_icir = summary_module._optional_icir(
        [
            float(value)
            for value in verified.daily.filter(pl.col("ic_status") == "COMPUTABLE")
            .get_column("rank_ic")
        ]
    )
    assert verified.metrics.rank_icir == expected_icir
    assert m3_public.EvaluationFreshVerificationContext is EvaluationFreshVerificationContext
    assert m3_public.build_research_summary_artifact is build_research_summary_artifact

    tampered_fold_metrics = verified.fold_metrics.with_columns(
        (pl.col("n_predicted") + 1).alias("n_predicted")
    )
    (root / "fold_metrics.parquet").write_bytes(
        summary_module._parquet_bytes(tampered_fold_metrics)
    )
    tampered_manifest = replace(
        verified.manifest,
        fold_metrics_sha256=_sha(root / "fold_metrics.parquet"),
    )
    (root / "manifest.json").write_bytes(
        summary_module._canonical_bytes(asdict(tampered_manifest))
    )
    resigned = context["base"]["common"] / "receipts" / "summary-resigned.json"
    publish_stage_receipt(
        receipt_path=resigned, stage="research-summary", scope="EXPERIMENT",
        scope_key=context["experiment"].manifest.experiment_key,
        artifact_roots=context["roots"], inputs=_receipt_inputs(context),
        outputs=_receipt_outputs(root),
    )
    with pytest.raises(ValueError, match="^M3_RESEARCH_SUMMARY_ARTIFACT_INVALID$"):
        verify_research_summary_artifact(
            root=root, receipt_path=resigned,
            evaluations=context["evaluations"],
            evaluation_contexts=context["contexts"],
            experiment=context["experiment"], config=context["config"],
            horizon_sessions=5, upstream_paths=context["upstream"],
            artifact_roots=context["roots"],
        )


def test_formal_summary_transaction_rolls_back_each_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path, monkeypatch)
    original = summary_module.ArtifactPublication.write_bytes
    for target in sorted(summary_module._SUMMARY_FILES):
        root = context["base"]["common"] / f"rollback-{target}" / "horizon=5"
        root.mkdir(parents=True)

        def hostile_write(self: Any, name: str, payload: bytes) -> None:
            if name == target:
                raise RuntimeError("PRIVATE_PATH TOKEN sentinel")
            original(self, name, payload)

        monkeypatch.setattr(
            summary_module.ArtifactPublication, "write_bytes", hostile_write
        )
        with pytest.raises(
            ValueError, match="^M3_RESEARCH_SUMMARY_ARTIFACT_INVALID$"
        ) as error:
            build_research_summary_artifact(
                evaluations=context["evaluations"],
                evaluation_contexts=context["contexts"],
                experiment=context["experiment"], config=context["config"],
                horizon_sessions=5, upstream_paths=context["upstream"],
                artifact_roots=context["roots"], output_root=root,
            )
        assert error.value.__cause__ is None and error.value.__context__ is None
        assert not any(root.iterdir())
        monkeypatch.setattr(
            summary_module.ArtifactPublication, "write_bytes", original
        )


@pytest.mark.parametrize("mutation", ["missing", "reordered", "wrong_horizon"])
def test_formal_summary_rejects_incomplete_order_and_horizon_before_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str,
) -> None:
    context = _context(tmp_path, monkeypatch)
    evaluations = context["evaluations"]
    contexts = context["contexts"]
    upstream = context["upstream"]
    horizon = 5
    if mutation == "missing":
        evaluations = evaluations[:-1]
        contexts = contexts[:-1]
        upstream = replace(upstream, evaluation_receipt_paths=upstream.evaluation_receipt_paths[:-1])
    elif mutation == "reordered":
        evaluations = (evaluations[1], evaluations[0], evaluations[2])
    else:
        horizon = 10
    root = context["base"]["common"] / f"bad-{mutation}" / f"horizon={horizon}"
    root.mkdir(parents=True)
    with pytest.raises(ValueError, match="^M3_RESEARCH_SUMMARY_ARTIFACT_INVALID$") as error:
        build_research_summary_artifact(
            evaluations=evaluations, evaluation_contexts=contexts,
            experiment=context["experiment"], config=context["config"],
            horizon_sessions=horizon, upstream_paths=upstream,
            artifact_roots=context["roots"], output_root=root,
        )
    assert error.value.__cause__ is None and error.value.__context__ is None
    assert not any(root.iterdir())
