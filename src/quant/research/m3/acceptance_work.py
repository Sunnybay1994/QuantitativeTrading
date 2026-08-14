"""G9D work-scoped acceptance checks for formal G5-G7 evidence."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import NoReturn, cast

from quant.backtest.a_share_plan import (
    G7_A_SHARE_ORDER_QUANTITY_RULE_VERSION,
    read_backtest_plan_manifest,
)
from quant.backtest.a_share_reporting import (
    backtest_artifact_output_relative_paths,
    read_backtest_bundle_manifest,
    read_backtest_metrics,
    read_backtest_scenario_manifest,
    verify_backtest_artifact,
)
from quant.research.m3.acceptance import (
    AcceptanceEvidencePlanV1,
    AcceptanceIssueV1,
    GateName,
    GateResultV1,
    VerifiedAcceptanceSubject,
    VerifiedComparisonIdentityV1,
    build_acceptance_evidence_plan,
)
from quant.research.m3.alignment import read_alignment_manifest
from quant.research.m3.config import LoadedM3Config
from quant.research.m3.contracts import (
    AlignmentManifestV1,
    BacktestBundleManifestV1,
    BacktestMetricsV1,
    BacktestPlanManifestV1,
    EvaluationManifestV1,
    EvaluationMetricsV1,
    FeatureManifestV1,
    ModelManifestV1,
    PredictionManifestV1,
    TargetManifestV1,
)
from quant.research.m3.evaluate import (
    read_evaluation_manifest,
    read_evaluation_metrics,
    read_research_summary_manifest,
    read_research_summary_metrics,
)
from quant.research.m3.features import read_feature_manifest
from quant.research.m3.formal_cli_resolve import resolve_formal_backtest_cli_inputs
from quant.research.m3.model import read_model_manifest
from quant.research.m3.predictions import read_prediction_manifest
from quant.research.m3.reproducibility import verify_formal_reproducibility_artifact
from quant.research.m3.run_state import (
    ArtifactDigest,
    VerifiedStageReceipt,
    path_for_artifact_digest,
    verify_stage_receipt_with_bytes,
)
from quant.research.m3.targets import read_target_manifest

_CODE = "M3_ACCEPTANCE_WORK_INVALID"
_WORK_GATES: tuple[GateName, ...] = ("G5", "G6", "G7")
_REQUIRED_METRICS = (
    "evaluation.test_rank_ic",
    "evaluation.test_rank_icir",
    "backtest.1p0x.test_net_excess_return",
    "backtest.1p0x.test_turnover",
    "backtest.1p0x.test_max_drawdown",
)


class M3AcceptanceWorkError(ValueError):
    """Stable, redacted public failure for invalid G9D caller inputs."""

    def __init__(self) -> None:
        super().__init__(_CODE)


@dataclass(frozen=True)
class _WorkEvidence:
    comparison: VerifiedComparisonIdentityV1
    feature: FeatureManifestV1
    feature_sha256: str
    alignment: AlignmentManifestV1
    alignment_sha256: str
    model: ModelManifestV1
    model_sha256: str
    prediction: PredictionManifestV1
    prediction_sha256: str


@dataclass(frozen=True)
class _EvaluationEvidence:
    manifest: EvaluationManifestV1
    manifest_sha256: str
    receipt_sha256: str
    metrics: EvaluationMetricsV1


def audit_acceptance_work(
    *,
    subject: VerifiedAcceptanceSubject,
    plan: AcceptanceEvidencePlanV1,
    config: LoadedM3Config,
    artifact_roots: Mapping[str, Path],
) -> tuple[GateResultV1, ...]:
    """Audit every formal fold/horizon work for G5-G7."""

    result: tuple[GateResultV1, ...] | None = None
    failed = False
    try:
        _validate_inputs(subject, plan, config, artifact_roots)
        issues: dict[GateName, list[AcceptanceIssueV1]] = {
            gate: [] for gate in _WORK_GATES
        }
        evidence: dict[GateName, list[ArtifactDigest]] = {
            gate: [] for gate in _WORK_GATES
        }
        receipts, locators, invalid = _verify_receipts(
            plan, artifact_roots, issues, evidence
        )

        work_evidence: dict[tuple[str, int], _WorkEvidence] = {}
        for comparison in subject.comparisons:
            key = (comparison.fold, comparison.horizon)
            work_subject = _work_subject(comparison)
            if "G5" in invalid:
                issues["G5"].append(_issue("G5", "UPSTREAM_INVALID", work_subject))
                continue
            try:
                work_evidence[key] = _check_g5_work(
                    subject=subject,
                    comparison=comparison,
                    config=config,
                    artifact_roots=artifact_roots,
                    receipts=receipts,
                    locators=locators,
                    evidence=evidence["G5"],
                )
            except Exception:
                issues["G5"].append(_issue("G5", "WORK_INVALID", work_subject))

        evaluations: dict[tuple[str, int], _EvaluationEvidence] = {}
        for comparison in subject.comparisons:
            key = (comparison.fold, comparison.horizon)
            work_subject = _work_subject(comparison)
            upstream = work_evidence.get(key)
            if "G6" in invalid:
                issues["G6"].append(_issue("G6", "UPSTREAM_INVALID", work_subject))
            elif upstream is None:
                issues["G6"].append(_issue("G6", "DEPENDENCY_INVALID", work_subject))
            else:
                try:
                    evaluations[key] = _check_g6_work(
                        subject=subject,
                        upstream=upstream,
                        config=config,
                        artifact_roots=artifact_roots,
                        receipts=receipts,
                        evidence=evidence["G6"],
                    )
                except Exception:
                    issues["G6"].append(_issue("G6", "WORK_INVALID", work_subject))

        if "G6" not in invalid:
            for horizon in _horizons(config):
                try:
                    _check_g6_summary(
                        subject=subject,
                        horizon=horizon,
                        evaluations=evaluations,
                        config=config,
                        artifact_roots=artifact_roots,
                        receipts=receipts,
                        evidence=evidence["G6"],
                    )
                except Exception:
                    issues["G6"].append(
                        _issue("G6", "SUMMARY_INVALID", f"horizon:h{horizon}")
                    )

        for comparison in subject.comparisons:
            key = (comparison.fold, comparison.horizon)
            work_subject = _work_subject(comparison)
            upstream = work_evidence.get(key)
            evaluation = evaluations.get(key)
            if "G7" in invalid:
                issues["G7"].append(_issue("G7", "UPSTREAM_INVALID", work_subject))
            elif upstream is None or evaluation is None:
                issues["G7"].append(_issue("G7", "DEPENDENCY_INVALID", work_subject))
            else:
                try:
                    _check_g7_work(
                        subject=subject,
                        upstream=upstream,
                        evaluation=evaluation,
                        config=config,
                        artifact_roots=artifact_roots,
                        receipts=receipts,
                        locators=locators,
                        evidence=evidence["G7"],
                    )
                except Exception:
                    issues["G7"].append(_issue("G7", "WORK_INVALID", work_subject))

        result = tuple(
            _gate_result(gate, issues[gate], evidence[gate]) for gate in _WORK_GATES
        )
    except Exception:
        failed = True
    if failed or result is None:
        _fail()
    return result


def _validate_inputs(
    subject: object,
    plan: object,
    config: object,
    artifact_roots: object,
) -> None:
    if (
        type(subject) is not VerifiedAcceptanceSubject
        or type(plan) is not AcceptanceEvidencePlanV1
        or type(config) is not LoadedM3Config
        or not isinstance(artifact_roots, Mapping)
        or not artifact_roots
        or any(
            type(alias) is not str or not isinstance(root, Path)
            for alias, root in artifact_roots.items()
        )
        or build_acceptance_evidence_plan(subject=subject, config=config) != plan
    ):
        raise ValueError
    acceptance = config.section("acceptance")
    required = acceptance.get("required_metrics")
    if type(required) is not tuple or required != _REQUIRED_METRICS:
        raise ValueError
    backtest = cast(Mapping[str, object], config.section("backtest")["a_share"])
    if (
        tuple(cast(Sequence[object], backtest["friction_multipliers"]))
        != (0.5, 1.0, 2.0)
        or backtest.get("execution_price_rounding")
        != "BUY_CEIL_SELL_FLOOR_TICK_V1"
        or backtest.get("fee_rounding") != "EACH_COMPONENT_HALF_UP_CENT_V1"
        or backtest.get("cash_settlement_rounding") != "HALF_UP_CENT_V1"
        or backtest.get("annualization_sessions") != 252
        or config.section("costs").get("scaled_components")
        != ("commission_rate", "commission_min", "slippage")
    ):
        raise ValueError


def _verify_receipts(
    plan: AcceptanceEvidencePlanV1,
    artifact_roots: Mapping[str, Path],
    issues: dict[GateName, list[AcceptanceIssueV1]],
    evidence: dict[GateName, list[ArtifactDigest]],
) -> tuple[
    dict[tuple[GateName, str], VerifiedStageReceipt],
    dict[tuple[GateName, str], object],
    set[GateName],
]:
    receipts: dict[tuple[GateName, str], VerifiedStageReceipt] = {}
    locators: dict[tuple[GateName, str], object] = {}
    invalid: set[GateName] = set()
    for locator in plan.evidence:
        if locator.gate not in _WORK_GATES:
            continue
        key = (locator.gate, locator.node_id)
        locators[key] = locator
        try:
            root = artifact_roots[locator.root_alias]
            receipt_path = root.joinpath(
                *PurePosixPath(locator.receipt_relative_path).parts
            )
            verified = verify_stage_receipt_with_bytes(
                receipt_path=receipt_path, artifact_roots=artifact_roots
            )
            if verified is None or (
                verified.receipt.stage != locator.expected_stage
                or verified.receipt.scope != locator.expected_scope
                or verified.receipt.scope_key != locator.expected_scope_key
            ):
                raise ValueError
            receipts[key] = verified
            evidence[locator.gate].append(
                ArtifactDigest(
                    locator.root_alias,
                    locator.receipt_relative_path,
                    len(verified.raw),
                    verified.sha256,
                )
            )
        except Exception:
            invalid.add(locator.gate)
            issues[locator.gate].append(
                _issue(locator.gate, "UPSTREAM_INVALID", f"node:{locator.node_id}")
            )
    return receipts, locators, invalid


def _check_g5_work(
    *,
    subject: VerifiedAcceptanceSubject,
    comparison: VerifiedComparisonIdentityV1,
    config: LoadedM3Config,
    artifact_roots: Mapping[str, Path],
    receipts: Mapping[tuple[GateName, str], VerifiedStageReceipt],
    locators: Mapping[tuple[GateName, str], object],
    evidence: list[ArtifactDigest],
) -> _WorkEvidence:
    feature_receipt = _receipt(receipts, "G5", f"features.{comparison.fold}")
    alignment_receipt = _receipt(
        receipts, "G5", f"alignment.{comparison.fold}.h{comparison.horizon}"
    )
    model_receipt = _receipt(
        receipts, "G5", f"train.{comparison.fold}.h{comparison.horizon}"
    )
    prediction_receipt = _receipt(
        receipts, "G5", f"predictions.{comparison.fold}.h{comparison.horizon}"
    )
    repro_receipt = _receipt(
        receipts, "G5", f"reproducibility.{comparison.fold}.h{comparison.horizon}"
    )
    feature_digest = _output(feature_receipt, "feature_manifest.json")
    alignment_digest = _output(alignment_receipt, "alignment_manifest.json")
    model_digest = _output(model_receipt, "model.metadata.json")
    prediction_digest = _output(prediction_receipt, "prediction_manifest.json")
    feature = read_feature_manifest(_path(feature_digest, artifact_roots))
    alignment = read_alignment_manifest(_path(alignment_digest, artifact_roots))
    model = read_model_manifest(_path(model_digest, artifact_roots))
    prediction = read_prediction_manifest(_path(prediction_digest, artifact_roots))
    experiment_key = subject.experiment.manifest.experiment_key
    if (
        feature_receipt.sha256 != comparison.feature_receipt_sha256
        or alignment_receipt.sha256 != comparison.alignment_receipt_sha256
        or repro_receipt.sha256 != comparison.reproducibility_receipt_sha256
        or feature.experiment_key != experiment_key
        or feature.fold != comparison.fold
        or feature.snapshot_id != subject.snapshot.manifest.snapshot_id
        or feature.provider_key != subject.provider.manifest.provider_key
        or feature.scientific_config_sha256 != config.scientific_config_sha256
        or alignment.experiment_key != experiment_key
        or alignment.work_key != comparison.work_key
        or alignment.fold != comparison.fold
        or alignment.horizon_sessions != comparison.horizon
        or alignment.feature_manifest_sha256 != feature_digest.sha256
        or alignment.label_manifest_sha256 != comparison.label_manifest_sha256
        or model.experiment_key != experiment_key
        or model.work_key != comparison.work_key
        or model.fold != comparison.fold
        or model.horizon_sessions != comparison.horizon
        or model.alignment_manifest_sha256 != alignment_digest.sha256
        or model.feature_manifest_sha256 != feature_digest.sha256
        or model.label_manifest_sha256 != comparison.label_manifest_sha256
        or prediction.experiment_key != experiment_key
        or prediction.work_key != comparison.work_key
        or prediction.fold != comparison.fold
        or prediction.horizon_sessions != comparison.horizon
        or prediction.model_manifest_sha256 != model_digest.sha256
        or prediction.model_sha256 != model.model_sha256
        or prediction.feature_manifest_sha256 != feature_digest.sha256
        or prediction.selected_feature_schema_sha256
        != model.selected_feature_schema_sha256
        or prediction.snapshot_id != subject.snapshot.manifest.snapshot_id
        or prediction.n_predicted != prediction.n_scorable
    ):
        raise ValueError
    repro_digest = _output(repro_receipt, "reproducibility.json")
    locator = cast(object, locators[("G5", f"reproducibility.{comparison.fold}.h{comparison.horizon}")])
    receipt_relative = cast(str, getattr(locator, "receipt_relative_path"))
    receipt_root_alias = cast(str, getattr(locator, "root_alias"))
    verified_repro = verify_formal_reproducibility_artifact(
        root=_path(repro_digest, artifact_roots).parent,
        receipt_path=artifact_roots[receipt_root_alias].joinpath(
            *PurePosixPath(receipt_relative).parts
        ),
        artifact_roots=artifact_roots,
        comparison_key=comparison.comparison_key,
        score_atol=cast(float, config.section("acceptance")["reproducibility_score_atol"]),
        metric_atol=cast(float, config.section("acceptance")["reproducibility_metric_atol"]),
        code_version=subject.runtime.code_version,
        dependency_fingerprint_sha256=subject.runtime.dependency_fingerprint_sha256,
        python_executable_sha256=comparison.python_executable_sha256,
    )
    if verified_repro.comparison_key != comparison.comparison_key:
        raise ValueError
    evidence.extend((feature_digest, alignment_digest, model_digest, prediction_digest, repro_digest))
    return _WorkEvidence(
        comparison,
        feature,
        feature_digest.sha256,
        alignment,
        alignment_digest.sha256,
        model,
        model_digest.sha256,
        prediction,
        prediction_digest.sha256,
    )


def _check_g6_work(
    *,
    subject: VerifiedAcceptanceSubject,
    upstream: _WorkEvidence,
    config: LoadedM3Config,
    artifact_roots: Mapping[str, Path],
    receipts: Mapping[tuple[GateName, str], VerifiedStageReceipt],
    evidence: list[ArtifactDigest],
) -> _EvaluationEvidence:
    comparison = upstream.comparison
    receipt = _receipt(
        receipts, "G6", f"evaluation.{comparison.fold}.h{comparison.horizon}"
    )
    manifest_digest = _output(receipt, "evaluation_manifest.json")
    metrics_digest = _output(receipt, "metrics.json")
    manifest = read_evaluation_manifest(_path(manifest_digest, artifact_roots))
    metrics = read_evaluation_metrics(_path(metrics_digest, artifact_roots))
    if (
        manifest.experiment_key != subject.experiment.manifest.experiment_key
        or manifest.work_key != comparison.work_key
        or manifest.fold != comparison.fold
        or manifest.horizon_sessions != comparison.horizon
        or manifest.prediction_manifest_sha256 != upstream.prediction_sha256
        or manifest.label_manifest_sha256 != comparison.label_manifest_sha256
        or manifest.feature_manifest_sha256 != upstream.feature_sha256
        or manifest.fold_plan_manifest_sha256 != subject.folds.manifest_sha256
        or manifest.scientific_config_sha256 != config.scientific_config_sha256
        or manifest.metrics_sha256 != metrics_digest.sha256
        or metrics.experiment_key != manifest.experiment_key
        or metrics.work_key != manifest.work_key
        or metrics.fold != manifest.fold
        or metrics.horizon_sessions != manifest.horizon_sessions
        or metrics.model != manifest.model
        or metrics.model_version != manifest.model_version
    ):
        raise ValueError
    acceptance = config.section("acceptance")
    thresholds = (
        (metrics.feature_coverage, "minimum_feature_coverage"),
        (metrics.prediction_coverage, "minimum_prediction_coverage"),
        (metrics.label_coverage, "minimum_label_coverage"),
        (metrics.evaluation_coverage, "minimum_evaluation_coverage"),
    )
    if any(
        value is None or value < cast(float, acceptance[name])
        for value, name in thresholds
    ):
        raise ValueError
    if (
        metrics.n_dates <= 0
        or metrics.n_computable_dates / metrics.n_dates
        < cast(float, acceptance["minimum_computable_ic_date_ratio"])
        or not _finite(metrics.rank_ic_mean)
        or not _finite(metrics.rank_icir)
    ):
        raise ValueError
    evidence.extend((manifest_digest, metrics_digest))
    return _EvaluationEvidence(
        manifest, manifest_digest.sha256, receipt.sha256, metrics
    )


def _check_g6_summary(
    *,
    subject: VerifiedAcceptanceSubject,
    horizon: int,
    evaluations: Mapping[tuple[str, int], _EvaluationEvidence],
    config: LoadedM3Config,
    artifact_roots: Mapping[str, Path],
    receipts: Mapping[tuple[GateName, str], VerifiedStageReceipt],
    evidence: list[ArtifactDigest],
) -> None:
    model_version = cast(
        str, cast(Mapping[str, object], config.section("model")["lightgbm"])["model_version"]
    )
    node = f"summary.h{horizon}.lightgbm.{model_version}"
    receipt = _receipt(receipts, "G6", node)
    manifest_digest = _output(receipt, "manifest.json")
    metrics_digest = _output(receipt, "metrics.json")
    manifest = read_research_summary_manifest(_path(manifest_digest, artifact_roots))
    metrics = read_research_summary_metrics(_path(metrics_digest, artifact_roots))
    folds = tuple(item.name for item in subject.folds.manifest.folds)
    ordered = tuple(evaluations[(fold, horizon)] for fold in folds)
    if (
        manifest.experiment_key != subject.experiment.manifest.experiment_key
        or manifest.horizon_sessions != horizon
        or manifest.model != "lightgbm"
        or manifest.model_version != model_version
        or manifest.scientific_config_sha256 != config.scientific_config_sha256
        or manifest.folds != folds
        or manifest.evaluation_manifest_sha256s
        != tuple(item.manifest_sha256 for item in ordered)
        or manifest.evaluation_receipt_sha256s
        != tuple(item.receipt_sha256 for item in ordered)
        or manifest.metrics_sha256 != metrics_digest.sha256
        or metrics.experiment_key != manifest.experiment_key
        or metrics.horizon_sessions != horizon
        or metrics.folds != folds
    ):
        raise ValueError
    evidence.extend((manifest_digest, metrics_digest))


def _check_g7_work(
    *,
    subject: VerifiedAcceptanceSubject,
    upstream: _WorkEvidence,
    evaluation: _EvaluationEvidence,
    config: LoadedM3Config,
    artifact_roots: Mapping[str, Path],
    receipts: Mapping[tuple[GateName, str], VerifiedStageReceipt],
    locators: Mapping[tuple[GateName, str], object],
    evidence: list[ArtifactDigest],
) -> None:
    comparison = upstream.comparison
    suffix = f"{comparison.fold}.h{comparison.horizon}"
    target_receipt = _receipt(receipts, "G7", f"targets.{suffix}")
    plan_receipt = _receipt(receipts, "G7", f"backtest-plan.{suffix}")
    backtest_receipt = _receipt(receipts, "G7", f"backtest.{suffix}")
    target_digest = _output(target_receipt, "target_manifest.json")
    plan_digest = _output(plan_receipt, "manifest.json")
    target = read_target_manifest(_path(target_digest, artifact_roots))
    backtest_plan = read_backtest_plan_manifest(_path(plan_digest, artifact_roots))
    if (
        target.experiment_key != subject.experiment.manifest.experiment_key
        or target.experiment_manifest_sha256 != subject.experiment.manifest_sha256
        or target.work_key != comparison.work_key
        or target.g1_release_id != subject.readiness.report.g1_release_id
        or target.g1_release_manifest_sha256
        != subject.readiness.report.g1_release_manifest_sha256
        or target.scientific_config_sha256 != config.scientific_config_sha256
        or target.prediction_manifest_sha256 != upstream.prediction_sha256
        or target.feature_manifest_sha256 != upstream.feature_sha256
        or target.fold_plan_manifest_sha256 != subject.folds.manifest_sha256
        or target.snapshot_id != subject.snapshot.manifest.snapshot_id
        or target.fold != comparison.fold
        or target.horizon_sessions != comparison.horizon
        or backtest_plan.experiment_key != target.experiment_key
        or backtest_plan.work_key != comparison.work_key
        or backtest_plan.target_manifest_sha256 != target_digest.sha256
        or backtest_plan.target_receipt_sha256 != target_receipt.sha256
        or backtest_plan.g1_release_id != target.g1_release_id
        or backtest_plan.g1_release_manifest_sha256 != target.g1_release_manifest_sha256
        or backtest_plan.scientific_config_sha256 != config.scientific_config_sha256
        or backtest_plan.fold_plan_manifest_sha256 != subject.folds.manifest_sha256
        or backtest_plan.fold != comparison.fold
        or backtest_plan.horizon_sessions != comparison.horizon
        or backtest_plan.order_quantity_rule_version
        != G7_A_SHARE_ORDER_QUANTITY_RULE_VERSION
    ):
        raise ValueError
    outputs = _backtest_outputs(backtest_receipt)
    bundle_digest = outputs["backtest_manifest.json"]
    metrics_digest = outputs["backtest_metrics.json"]
    bundle = read_backtest_bundle_manifest(_path(bundle_digest, artifact_roots))
    metrics = read_backtest_metrics(_path(metrics_digest, artifact_roots))
    scenarios = tuple(
        read_backtest_scenario_manifest(
            _path(outputs[f"{name}/manifest.json"], artifact_roots)
        )
        for name in ("0p5x", "1p0x", "2p0x")
    )
    _check_backtest_identity(
        subject=subject,
        comparison=comparison,
        target=target,
        target_sha256=target_digest.sha256,
        plan=backtest_plan,
        plan_sha256=plan_digest.sha256,
        bundle=bundle,
        bundle_metrics=metrics,
        metrics_sha256=metrics_digest.sha256,
        scenarios=scenarios,
        outputs=outputs,
        config=config,
    )
    locator = locators[("G7", f"backtest.{suffix}")]
    receipt_path = artifact_roots[cast(str, getattr(locator, "root_alias"))].joinpath(
        *PurePosixPath(cast(str, getattr(locator, "receipt_relative_path"))).parts
    )
    _fresh_verify_backtest(
        subject=subject,
        comparison=comparison,
        config=config,
        artifact_roots=artifact_roots,
        root=_path(bundle_digest, artifact_roots).parent,
        receipt_path=receipt_path,
        target=target,
        target_sha256=target_digest.sha256,
        plan=backtest_plan,
        plan_sha256=plan_digest.sha256,
        bundle=bundle,
        bundle_sha256=bundle_digest.sha256,
        metrics=metrics,
        receipt_sha256=backtest_receipt.sha256,
    )
    one = next(item for item in metrics.scenarios if item.scenario == "1p0x")
    required_values = (
        evaluation.metrics.rank_ic_mean,
        evaluation.metrics.rank_icir,
        one.test_net_excess_return,
        one.test_turnover,
        one.test_max_drawdown,
    )
    if any(not _finite(value) for value in required_values):
        raise ValueError
    if len(backtest_receipt.receipt.inputs) != 21:
        raise ValueError
    evidence.extend((target_digest, plan_digest, *outputs.values()))


def _fresh_verify_backtest(
    *,
    subject: VerifiedAcceptanceSubject,
    comparison: VerifiedComparisonIdentityV1,
    config: LoadedM3Config,
    artifact_roots: Mapping[str, Path],
    root: Path,
    receipt_path: Path,
    target: TargetManifestV1,
    target_sha256: str,
    plan: BacktestPlanManifestV1,
    plan_sha256: str,
    bundle: BacktestBundleManifestV1,
    bundle_sha256: str,
    metrics: BacktestMetricsV1,
    receipt_sha256: str,
) -> None:
    raw_config_sha256 = config.raw_config_sha256
    if type(raw_config_sha256) is not str:
        raise ValueError
    matches = tuple(
        item
        for item in subject.readiness.receipt.inputs
        if item.sha256 == raw_config_sha256
        and PurePosixPath(item.relative_path).parts
        and PurePosixPath(item.relative_path).parts[0] == "configs"
    )
    if len(matches) != 1:
        raise ValueError
    config_digest = matches[0]
    project_root = artifact_roots[config_digest.root_alias]
    config_relative = PurePosixPath(config_digest.relative_path)
    resolution = resolve_formal_backtest_cli_inputs(
        project_root=project_root,
        config=config,
        config_relative=config_relative,
        snapshot_id=subject.snapshot.manifest.snapshot_id,
        fold=comparison.fold,
        horizon=comparison.horizon,
    )
    if resolution.work_key != comparison.work_key:
        raise ValueError
    verified = verify_backtest_artifact(
        root=root,
        receipt_path=receipt_path,
        target=resolution.target,
        plan=resolution.plan,
        release=resolution.release,
        experiment=resolution.experiment,
        config=config,
        fresh_context=resolution.fresh_context,
        artifact_roots=artifact_roots,
    )
    if (
        resolution.target.manifest != target
        or resolution.target.manifest_sha256 != target_sha256
        or resolution.plan.manifest != plan
        or resolution.plan.manifest_sha256 != plan_sha256
        or verified.manifest != bundle
        or verified.manifest_sha256 != bundle_sha256
        or verified.metrics != metrics
        or verified.backtest_receipt_sha256 != receipt_sha256
    ):
        raise ValueError


def _check_backtest_identity(
    *,
    subject: VerifiedAcceptanceSubject,
    comparison: VerifiedComparisonIdentityV1,
    target: TargetManifestV1,
    target_sha256: str,
    plan: BacktestPlanManifestV1,
    plan_sha256: str,
    bundle: BacktestBundleManifestV1,
    bundle_metrics: BacktestMetricsV1,
    metrics_sha256: str,
    scenarios: tuple[object, ...],
    outputs: Mapping[str, ArtifactDigest],
    config: LoadedM3Config,
) -> None:
    scenario_values = cast(tuple[object, ...], scenarios)
    if (
        bundle.experiment_key != subject.experiment.manifest.experiment_key
        or bundle.experiment_manifest_sha256 != subject.experiment.manifest_sha256
        or bundle.work_key != comparison.work_key
        or bundle.scientific_config_sha256 != config.scientific_config_sha256
        or bundle.target_manifest_sha256 != target_sha256
        or bundle.backtest_plan_manifest_sha256 != plan_sha256
        or bundle.g1_release_id != target.g1_release_id
        or bundle.g1_release_manifest_sha256 != target.g1_release_manifest_sha256
        or bundle.order_quantity_rule_version
        != G7_A_SHARE_ORDER_QUANTITY_RULE_VERSION
        or bundle.common_target_manifest_sha256 != target_sha256
        or bundle.backtest_metrics_sha256 != metrics_sha256
        or bundle_metrics.experiment_key != bundle.experiment_key
        or bundle_metrics.work_key != bundle.work_key
    ):
        raise ValueError
    market_facts: set[str] = set()
    scenario_hashes: list[tuple[str, str]] = []
    for value in scenario_values:
        scenario = cast(object, value)
        name = cast(str, getattr(scenario, "scenario"))
        market_facts.add(cast(str, getattr(scenario, "input_market_facts_sha256")))
        digest = outputs[f"{name}/manifest.json"]
        scenario_hashes.append((name, digest.sha256))
        if (
            getattr(scenario, "experiment_key") != bundle.experiment_key
            or getattr(scenario, "work_key") != comparison.work_key
            or getattr(scenario, "scientific_config_sha256")
            != config.scientific_config_sha256
            or getattr(scenario, "target_manifest_sha256") != target_sha256
            or getattr(scenario, "backtest_plan_manifest_sha256") != plan_sha256
            or getattr(scenario, "g1_release_id") != target.g1_release_id
            or getattr(scenario, "g1_release_manifest_sha256")
            != target.g1_release_manifest_sha256
            or getattr(scenario, "fold") != comparison.fold
            or getattr(scenario, "horizon_sessions") != comparison.horizon
            or getattr(scenario, "order_quantity_rule_version")
            != G7_A_SHARE_ORDER_QUANTITY_RULE_VERSION
            or getattr(scenario, "metrics_sha256")
            != outputs[f"{name}/metrics.json"].sha256
        ):
            raise ValueError
    if (
        tuple(scenario_hashes) != bundle.scenario_manifest_sha256s
        or len(market_facts) != 1
        or next(iter(market_facts)) != bundle.common_market_facts_sha256
    ):
        raise ValueError


def _backtest_outputs(receipt: VerifiedStageReceipt) -> dict[str, ArtifactDigest]:
    expected = backtest_artifact_output_relative_paths()
    result: dict[str, ArtifactDigest] = {}
    for digest in receipt.receipt.outputs:
        matches = tuple(
            name
            for name in expected
            if digest.relative_path == name
            or digest.relative_path.endswith(f"/{name}")
        )
        if len(matches) != 1 or matches[0] in result:
            raise ValueError
        result[matches[0]] = digest
    if tuple(sorted(result)) != expected:
        raise ValueError
    return result


def _receipt(
    receipts: Mapping[tuple[GateName, str], VerifiedStageReceipt],
    gate: GateName,
    node: str,
) -> VerifiedStageReceipt:
    value = receipts.get((gate, node))
    if type(value) is not VerifiedStageReceipt:
        raise ValueError
    return value


def _output(receipt: VerifiedStageReceipt, suffix: str) -> ArtifactDigest:
    matches = tuple(
        item
        for item in receipt.receipt.outputs
        if item.relative_path == suffix
        or item.relative_path.endswith(f"/{suffix}")
    )
    if len(matches) != 1:
        raise ValueError
    return matches[0]


def _path(digest: ArtifactDigest, roots: Mapping[str, Path]) -> Path:
    return path_for_artifact_digest(digest, artifact_roots=roots)


def _horizons(config: LoadedM3Config) -> tuple[int, ...]:
    value = config.section("labels")["horizons_sessions"]
    if type(value) is not tuple or not value:
        raise ValueError
    return cast(tuple[int, ...], value)


def _finite(value: object) -> bool:
    return type(value) is float and math.isfinite(value)


def _work_subject(comparison: VerifiedComparisonIdentityV1) -> str:
    return f"work:{comparison.fold}.h{comparison.horizon}"


def _issue(gate: GateName, code: str, subject: str) -> AcceptanceIssueV1:
    return AcceptanceIssueV1(gate=gate, code=code, subject=subject, evidence=())


def _gate_result(
    gate: GateName,
    issues: list[AcceptanceIssueV1],
    evidence: list[ArtifactDigest],
) -> GateResultV1:
    canonical_issues = tuple(
        sorted(set(issues), key=lambda item: (item.gate, item.code, item.subject))
    )
    canonical_evidence = tuple(
        sorted(set(evidence), key=lambda item: (item.root_alias, item.relative_path))
    )
    return GateResultV1(
        gate=gate,
        status="FAIL" if canonical_issues else "PASS",
        issues=canonical_issues,
        evidence=canonical_evidence,
    )


def _fail() -> NoReturn:
    try:
        raise M3AcceptanceWorkError()
    except M3AcceptanceWorkError as error:
        error.__cause__ = None
        error.__context__ = None
        raise error from None


__all__ = ["M3AcceptanceWorkError", "audit_acceptance_work"]
