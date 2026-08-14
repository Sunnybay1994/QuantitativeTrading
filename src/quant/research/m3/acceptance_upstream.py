"""G9C checks for the already-verified G0-G4 acceptance evidence."""

from __future__ import annotations

import math
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import NoReturn, cast

from quant.research.m3.acceptance import (
    AcceptanceEvidencePlanV1,
    AcceptanceIssueV1,
    GateName,
    GateResultV1,
    VerifiedAcceptanceSubject,
    VerifiedComparisonIdentityV1,
    build_acceptance_evidence_plan,
)
from quant.research.m3.config import LoadedM3Config
from quant.research.m3.folds import read_fold_plan_manifest
from quant.research.m3.labels import (
    read_experiment_identity_manifest,
    read_label_artifact_manifest,
    read_label_reconciliation_summary,
)
from quant.research.m3.provider import read_provider_manifest
from quant.research.m3.provider_validation import read_provider_validation_summary
from quant.research.m3.readiness_evidence import read_readiness_evidence_report
from quant.research.m3.run_state import (
    ArtifactDigest,
    VerifiedStageReceipt,
    path_for_artifact_digest,
    verify_stage_receipt_with_bytes,
)
from quant.research.m3.snapshot import read_snapshot_manifest

_CODE = "M3_ACCEPTANCE_UPSTREAM_INVALID"
_UPSTREAM_GATES: tuple[GateName, ...] = ("G0", "G1", "G2", "G3", "G4")


class M3AcceptanceUpstreamError(ValueError):
    """Stable, redacted public failure for invalid G9C caller inputs."""

    def __init__(self) -> None:
        super().__init__(_CODE)


def audit_acceptance_upstream(
    *,
    subject: VerifiedAcceptanceSubject,
    plan: AcceptanceEvidencePlanV1,
    config: LoadedM3Config,
    artifact_roots: Mapping[str, Path],
) -> tuple[GateResultV1, ...]:
    """Audit G0-G4 without scanning roots or reimplementing artifact formulas."""

    result: tuple[GateResultV1, ...] | None = None
    failed = False
    try:
        _validate_inputs(subject, plan, config, artifact_roots)
        issues: dict[GateName, list[AcceptanceIssueV1]] = {
            gate: [] for gate in _UPSTREAM_GATES
        }
        evidence: dict[GateName, list[ArtifactDigest]] = {
            gate: [] for gate in _UPSTREAM_GATES
        }
        receipts: dict[tuple[GateName, str], VerifiedStageReceipt] = {}
        invalid_gates: set[GateName] = set()

        for locator in plan.evidence:
            if locator.gate not in _UPSTREAM_GATES:
                continue
            gate = locator.gate
            try:
                root = artifact_roots[locator.root_alias]
                receipt_path = root.joinpath(
                    *PurePosixPath(locator.receipt_relative_path).parts
                )
                verified = verify_stage_receipt_with_bytes(
                    receipt_path=receipt_path,
                    artifact_roots=artifact_roots,
                )
                if verified is None:
                    raise ValueError
                receipt = verified.receipt
                if (
                    receipt.stage != locator.expected_stage
                    or receipt.scope != locator.expected_scope
                    or receipt.scope_key != locator.expected_scope_key
                ):
                    raise ValueError
                receipts[(gate, locator.node_id)] = verified
                evidence[gate].append(
                    ArtifactDigest(
                        locator.root_alias,
                        locator.receipt_relative_path,
                        len(verified.raw),
                        verified.sha256,
                    )
                )
            except Exception:
                invalid_gates.add(gate)
                issues[gate].append(
                    _issue(gate, "UPSTREAM_INVALID", f"node:{locator.node_id}")
                )

        semantic_checks = {
            "G0": lambda: _check_g0(
                subject,
                config,
                artifact_roots,
                receipts,
                evidence["G0"],
            ),
            "G1": lambda: _check_g1(
                subject,
                plan,
                config,
                artifact_roots,
                receipts,
                evidence["G1"],
            ),
            "G2": lambda: _check_g2(
                subject,
                plan,
                config,
                artifact_roots,
                receipts,
                evidence["G2"],
            ),
            "G3": lambda: _check_g3(
                subject, config, artifact_roots, receipts, evidence["G3"]
            ),
            "G4": lambda: _check_g4(
                subject,
                plan,
                config,
                artifact_roots,
                receipts,
                evidence["G4"],
            ),
        }
        for gate in _UPSTREAM_GATES:
            if gate in invalid_gates:
                continue
            try:
                issues[gate].extend(semantic_checks[gate]())
            except Exception:
                issues[gate].append(
                    _issue(gate, "UPSTREAM_INVALID", f"global:{gate.lower()}")
                )

        result = tuple(
            _gate_result(gate, issues[gate], evidence[gate])
            for gate in _UPSTREAM_GATES
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
    ):
        raise ValueError
    if build_acceptance_evidence_plan(subject=subject, config=config) != plan:
        raise ValueError
    required_aliases = {item.root_alias for item in plan.evidence}
    if not required_aliases.issubset(artifact_roots):
        raise ValueError


def _check_g0(
    subject: VerifiedAcceptanceSubject,
    config: LoadedM3Config,
    artifact_roots: Mapping[str, Path],
    receipts: Mapping[tuple[GateName, str], VerifiedStageReceipt],
    evidence: list[ArtifactDigest],
) -> list[AcceptanceIssueV1]:
    output: list[AcceptanceIssueV1] = []
    report = subject.readiness.report
    receipt = _receipt(receipts, "G0", "readiness-evidence")
    report_digest = _single_output(receipt, "readiness_report.json")
    evidence.append(report_digest)
    parsed_report = read_readiness_evidence_report(
        path_for_artifact_digest(report_digest, artifact_roots=artifact_roots)
    )
    if config.section("meta").get("enabled") is not True:
        output.append(_issue("G0", "CONFIG_DISABLED", "global:m3"))
    if any(item.severity == "ERROR" for item in report.issues):
        output.append(_issue("G0", "READINESS_ERROR", "global:m3"))
    runtime = subject.runtime
    if (
        receipt.sha256 != runtime.readiness_receipt_sha256
        or receipt.sha256 != subject.readiness.receipt_sha256
        or report_digest != subject.readiness.report_digest
        or parsed_report != report
        or report.full_config_sha256 != config.full_config_sha256
        or report.full_config_sha256 != runtime.full_config_sha256
        or report.code_version != runtime.code_version
        or report.dependency_fingerprint_sha256
        != runtime.dependency_fingerprint_sha256
        or report.provider_runtime_fingerprint_sha256
        != runtime.provider_runtime_fingerprint_sha256
        or subject.provider.manifest.qlib_version != "0.9.7"
    ):
        output.append(_issue("G0", "RUNTIME_IDENTITY_MISMATCH", "global:m3"))
    return output


def _check_g1(
    subject: VerifiedAcceptanceSubject,
    plan: AcceptanceEvidencePlanV1,
    config: LoadedM3Config,
    artifact_roots: Mapping[str, Path],
    receipts: Mapping[tuple[GateName, str], VerifiedStageReceipt],
    evidence: list[ArtifactDigest],
) -> list[AcceptanceIssueV1]:
    output: list[AcceptanceIssueV1] = []
    manifest = subject.snapshot.manifest
    data = config.section("data")
    receipt = _receipt(receipts, "G1", "snapshot")
    manifest_digest = _single_output(receipt, "manifest.json")
    evidence.append(manifest_digest)
    parsed_manifest = read_snapshot_manifest(
        path_for_artifact_digest(manifest_digest, artifact_roots=artifact_roots)
    )
    if (
        receipt.sha256 != subject.snapshot.snapshot_receipt_sha256
        or manifest_digest.sha256 != subject.snapshot.manifest_sha256
        or parsed_manifest != manifest
        or manifest.snapshot_id != plan.snapshot_id
        or manifest.snapshot_config_sha256 != config.snapshot_config_sha256
        or manifest.g1_release_id != subject.readiness.report.g1_release_id
        or manifest.g1_release_manifest_sha256
        != subject.readiness.report.g1_release_manifest_sha256
    ):
        output.append(_issue("G1", "RELEASE_LINEAGE_INVALID", "global:snapshot"))
    if (
        manifest.source != data.get("source")
        or manifest.universe != data.get("universe")
        or manifest.signal_start != data.get("start_date")
        or manifest.signal_end != data.get("end_date")
        or manifest.history_start > manifest.signal_start
        or manifest.history_end < manifest.signal_end
        or manifest.session_start > manifest.signal_start
        or manifest.session_end < manifest.signal_end
        or manifest.staging_format != "parquet"
        or manifest.adjustment_formula_version != "qlib_yahoo_like_v1"
    ):
        output.append(_issue("G1", "SNAPSHOT_IDENTITY_INVALID", "global:snapshot"))
    return output


def _check_g2(
    subject: VerifiedAcceptanceSubject,
    plan: AcceptanceEvidencePlanV1,
    config: LoadedM3Config,
    artifact_roots: Mapping[str, Path],
    receipts: Mapping[tuple[GateName, str], VerifiedStageReceipt],
    evidence: list[ArtifactDigest],
) -> list[AcceptanceIssueV1]:
    output: list[AcceptanceIssueV1] = []
    provider = subject.provider.manifest
    validation = subject.provider_validation.summary
    provider_receipt = _receipt(receipts, "G2", "provider")
    validation_receipt = _receipt(receipts, "G2", "provider-validation")
    provider_digest = _single_output(provider_receipt, "provider_manifest.json")
    validation_digest = _single_output(
        validation_receipt, "provider_validation.json"
    )
    evidence.extend((provider_digest, validation_digest))
    parsed_provider = read_provider_manifest(
        path_for_artifact_digest(provider_digest, artifact_roots=artifact_roots)
    )
    parsed_validation = read_provider_validation_summary(
        path_for_artifact_digest(validation_digest, artifact_roots=artifact_roots)
    )
    if (
        provider_receipt.sha256 != subject.provider.provider_receipt_sha256
        or provider_digest.sha256 != subject.provider.manifest_sha256
        or parsed_provider != provider
        or provider.provider_key != plan.provider_key
        or provider.snapshot_id != subject.snapshot.manifest.snapshot_id
        or provider.snapshot_manifest_sha256 != subject.snapshot.manifest_sha256
        or provider.provider_config_sha256 != config.provider_config_sha256
        or provider.provider_runtime_fingerprint_sha256
        != subject.runtime.provider_runtime_fingerprint_sha256
        or provider.code_version != subject.runtime.code_version
        or provider.calendar_sha256
        != subject.snapshot.manifest.session_calendar_sha256
    ):
        output.append(_issue("G2", "PROVIDER_IDENTITY_INVALID", "global:provider"))
    mismatch_counts = (
        validation.missing_emitted_cell_count,
        validation.extra_cell_count,
        validation.duplicate_cell_count,
        validation.non_finite_emitted_cell_count,
        validation.emitted_mismatch_cell_count,
        validation.gap_finite_cell_count,
        validation.calendar_mismatch_count,
        validation.instrument_mismatch_count,
    )
    if (
        validation_receipt.sha256
        != subject.provider_validation.validation_receipt_sha256
        or validation_digest.sha256 != subject.provider_validation.summary_sha256
        or parsed_validation != validation
        or validation.provider_validation_key
        != subject.provider_validation.summary.provider_validation_key
        or validation.provider_key != provider.provider_key
        or validation.provider_receipt_sha256
        != subject.provider.provider_receipt_sha256
        or validation.provider_manifest_sha256 != subject.provider.manifest_sha256
        or validation.snapshot_id != subject.snapshot.manifest.snapshot_id
        or validation.provider_validation_config_sha256
        != config.provider_validation_config_sha256
        or validation.provider_runtime_fingerprint_sha256
        != subject.runtime.provider_runtime_fingerprint_sha256
        or validation.api_calendar_sha256 != provider.calendar_sha256
        or validation.api_instrument_ranges_sha256
        != provider.instrument_ranges_sha256
        or validation.emitted_key_count != 60
        or validation.emitted_comparison_count != 420
        or validation.gap_key_count <= 0
        or validation.gap_comparison_count != validation.gap_key_count * 7
        or validation.details_row_count
        != validation.emitted_comparison_count + validation.gap_comparison_count
        or any(mismatch_counts)
        or not validation.passed
    ):
        output.append(_issue("G2", "PROVIDER_VALIDATION_FAILED", "global:provider"))
    return output


def _check_g3(
    subject: VerifiedAcceptanceSubject,
    config: LoadedM3Config,
    artifact_roots: Mapping[str, Path],
    receipts: Mapping[tuple[GateName, str], VerifiedStageReceipt],
    evidence: list[ArtifactDigest],
) -> list[AcceptanceIssueV1]:
    output: list[AcceptanceIssueV1] = []
    by_horizon: dict[int, tuple[VerifiedComparisonIdentityV1, ...]] = {}
    for horizon in sorted({item.horizon for item in subject.comparisons}):
        by_horizon[horizon] = tuple(
            item for item in subject.comparisons if item.horizon == horizon
        )
    validation_config = config.section("validation")
    label_validation = cast(
        Mapping[str, object], validation_config.get("labels")
    )
    for horizon, comparisons in by_horizon.items():
        logical_subject = f"horizon:{horizon}"
        label_node = f"labels.h{horizon}"
        reconciliation_node = f"label-reconciliation.h{horizon}"
        try:
            label_receipt = _receipt(receipts, "G3", label_node)
            reconciliation_receipt = _receipt(
                receipts, "G3", reconciliation_node
            )
            if len({item.label_manifest_sha256 for item in comparisons}) != 1 or len(
                {item.label_receipt_sha256 for item in comparisons}
            ) != 1 or len(
                {item.label_reconciliation_key for item in comparisons}
            ) != 1:
                raise ValueError
            comparison = comparisons[0]
            label_digest = _single_output(
                label_receipt, "label_manifest.json"
            )
            reconciliation_digest = _single_output(
                reconciliation_receipt, "reconciliation.json"
            )
            evidence.extend((label_digest, reconciliation_digest))
            label_manifest = read_label_artifact_manifest(
                path_for_artifact_digest(
                    label_digest, artifact_roots=artifact_roots
                )
            )
            reconciliation = read_label_reconciliation_summary(
                path_for_artifact_digest(
                    reconciliation_digest, artifact_roots=artifact_roots
                )
            )
            if (
                label_receipt.sha256 != comparison.label_receipt_sha256
                or label_digest.sha256 != comparison.label_manifest_sha256
                or label_manifest.horizon_sessions != horizon
                or label_manifest.benchmark != config.section("data").get("benchmark")
                or label_manifest.experiment_key
                != subject.experiment.manifest.experiment_key
                or label_manifest.experiment_manifest_sha256
                != subject.experiment.manifest_sha256
                or label_manifest.snapshot_id != subject.snapshot.manifest.snapshot_id
                or label_manifest.snapshot_manifest_sha256
                != subject.snapshot.manifest_sha256
                or label_manifest.g1_release_id
                != subject.readiness.report.g1_release_id
                or label_manifest.g1_release_manifest_sha256
                != subject.readiness.report.g1_release_manifest_sha256
            ):
                output.append(
                    _issue("G3", "LABEL_IDENTITY_INVALID", logical_subject)
                )
            expected_errors = (
                (
                    reconciliation.expression_direct_max_abs_error,
                    reconciliation.expression_direct_p99_abs_error,
                    reconciliation.qlib_expression_atol,
                ),
                (
                    reconciliation.benchmark_max_abs_error,
                    reconciliation.benchmark_p99_abs_error,
                    reconciliation.benchmark_return_atol,
                ),
                (
                    reconciliation.raw_label_max_abs_error,
                    reconciliation.raw_label_p99_abs_error,
                    reconciliation.label_return_atol,
                ),
                (
                    reconciliation.relative_label_max_abs_error,
                    reconciliation.relative_label_p99_abs_error,
                    reconciliation.label_return_atol,
                ),
            )
            if (
                reconciliation.reconciliation_key
                != comparison.label_reconciliation_key
                or reconciliation.experiment_key
                != subject.experiment.manifest.experiment_key
                or reconciliation.horizon_sessions != horizon
                or reconciliation.provider_validation_receipt_sha256
                != subject.provider_validation.validation_receipt_sha256
                or reconciliation.label_manifest_sha256
                != comparison.label_manifest_sha256
                or reconciliation.label_reconciliation_config_sha256
                != config.label_reconciliation_config_sha256
                or reconciliation.dependency_fingerprint_sha256
                != subject.runtime.dependency_fingerprint_sha256
                or reconciliation.code_version != subject.runtime.code_version
                or reconciliation.qlib_expression_atol
                != label_validation.get("qlib_expression_atol")
                or reconciliation.benchmark_return_atol
                != label_validation.get("benchmark_return_atol")
                or reconciliation.label_return_atol
                != label_validation.get("label_return_atol")
                or any(
                    count != 0
                    for count in (
                        reconciliation.missing_key_count,
                        reconciliation.extra_key_count,
                        reconciliation.duplicate_key_count,
                        reconciliation.non_finite_count,
                    )
                )
                or not reconciliation.passed
                or any(
                    not math.isfinite(value)
                    or value < 0.0
                    or value > tolerance
                    for maximum, percentile, tolerance in expected_errors
                    for value in (maximum, percentile)
                )
            ):
                output.append(
                    _issue("G3", "LABEL_RECONCILIATION_FAILED", logical_subject)
                )
        except Exception:
            output.append(_issue("G3", "UPSTREAM_INVALID", f"node:{label_node}"))
    return output


def _check_g4(
    subject: VerifiedAcceptanceSubject,
    plan: AcceptanceEvidencePlanV1,
    config: LoadedM3Config,
    artifact_roots: Mapping[str, Path],
    receipts: Mapping[tuple[GateName, str], VerifiedStageReceipt],
    evidence: list[ArtifactDigest],
) -> list[AcceptanceIssueV1]:
    output: list[AcceptanceIssueV1] = []
    experiment = subject.experiment.manifest
    folds = subject.folds.manifest
    experiment_receipt = _receipt(receipts, "G4", "experiment")
    folds_receipt = _receipt(receipts, "G4", "folds")
    experiment_digest = _single_output(
        experiment_receipt, "experiment_manifest.json"
    )
    folds_digest = _single_output(folds_receipt, "folds.json")
    evidence.extend((experiment_digest, folds_digest))
    parsed_experiment = read_experiment_identity_manifest(
        path_for_artifact_digest(experiment_digest, artifact_roots=artifact_roots)
    )
    parsed_folds = read_fold_plan_manifest(
        path_for_artifact_digest(folds_digest, artifact_roots=artifact_roots)
    )
    if (
        experiment_receipt.sha256
        != subject.experiment.experiment_receipt_sha256
        or experiment_digest.sha256 != subject.experiment.manifest_sha256
        or parsed_experiment != experiment
        or experiment.experiment_key != plan.experiment_key
        or experiment.snapshot_id != subject.snapshot.manifest.snapshot_id
        or experiment.snapshot_manifest_sha256 != subject.snapshot.manifest_sha256
        or experiment.provider_key != subject.provider.manifest.provider_key
        or experiment.provider_manifest_sha256 != subject.provider.manifest_sha256
        or experiment.provider_receipt_sha256
        != subject.provider.provider_receipt_sha256
        or experiment.scientific_config_sha256 != config.scientific_config_sha256
        or experiment.dependency_fingerprint_sha256
        != subject.runtime.dependency_fingerprint_sha256
        or experiment.code_version != subject.runtime.code_version
    ):
        output.append(_issue("G4", "EXPERIMENT_IDENTITY_INVALID", "global:experiment"))
    all_dates = tuple(
        day
        for fold in folds.folds
        for segment in (
            fold.train_dates,
            fold.train_validation_embargo_dates,
            fold.validation_dates,
            fold.validation_test_embargo_dates,
            fold.test_dates,
        )
        for day in segment
    )
    test_dates = tuple(day for fold in folds.folds for day in fold.test_dates)
    expected_horizons = cast(tuple[int, ...], config.section("labels")["horizons_sessions"])
    if (
        folds_receipt.sha256 != subject.folds.folds_receipt_sha256
        or folds_digest.sha256 != subject.folds.manifest_sha256
        or parsed_folds != folds
        or folds.experiment_key != experiment.experiment_key
        or folds.experiment_manifest_sha256 != subject.experiment.manifest_sha256
        or folds.snapshot_id != subject.snapshot.manifest.snapshot_id
        or folds.snapshot_manifest_sha256 != subject.snapshot.manifest_sha256
        or folds.session_calendar_sha256
        != subject.snapshot.manifest.session_calendar_sha256
        or folds.scientific_config_sha256 != config.scientific_config_sha256
        or folds.signal_start != subject.snapshot.manifest.signal_start
        or folds.signal_end != subject.snapshot.manifest.signal_end
        or folds.max_horizon_sessions != max(expected_horizons)
        or any(
            day < folds.signal_start or day > folds.signal_end for day in all_dates
        )
        or len(test_dates) != len(set(test_dates))
    ):
        output.append(_issue("G4", "FOLD_PLAN_INVALID", "global:folds"))
    return output


def _receipt(
    receipts: Mapping[tuple[GateName, str], VerifiedStageReceipt],
    gate: GateName,
    node_id: str,
) -> VerifiedStageReceipt:
    value = receipts.get((gate, node_id))
    if type(value) is not VerifiedStageReceipt:
        raise ValueError
    return value


def _single_output(receipt: VerifiedStageReceipt, filename: str) -> ArtifactDigest:
    matches = tuple(
        item
        for item in receipt.receipt.outputs
        if PurePosixPath(item.relative_path).name == filename
    )
    if len(matches) != 1:
        raise ValueError
    return matches[0]


def _issue(gate: GateName, code: str, subject: str) -> AcceptanceIssueV1:
    return AcceptanceIssueV1(gate, code, subject, ())


def _gate_result(
    gate: GateName,
    issues: list[AcceptanceIssueV1],
    evidence: list[ArtifactDigest],
) -> GateResultV1:
    canonical_issues = tuple(
        sorted(
            {(item.gate, item.code, item.subject): item for item in issues}.values(),
            key=lambda item: (item.gate, item.code, item.subject),
        )
    )
    canonical_evidence = tuple(
        sorted(
            {
                (item.root_alias, item.relative_path): item for item in evidence
            }.values(),
            key=lambda item: (item.root_alias, item.relative_path),
        )
    )
    return GateResultV1(
        gate,
        "FAIL" if canonical_issues else "PASS",
        canonical_issues,
        canonical_evidence,
    )


def _fail() -> NoReturn:
    try:
        raise M3AcceptanceUpstreamError()
    except M3AcceptanceUpstreamError as error:
        error.__cause__ = None
        error.__context__ = None
        raise error from None


__all__ = [
    "M3AcceptanceUpstreamError",
    "audit_acceptance_upstream",
]
