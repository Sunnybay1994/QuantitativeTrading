"""Deterministic, evidence-only strategy candidate admission for M4-B8."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Literal, NoReturn

Segment = Literal["validation", "test"]
Comparison = Literal["MINIMUM", "MAXIMUM"]
AdmissionStatus = Literal["ADMIT", "REJECT"]

_HASH_VERSION = "m4-strategy-admission-v1"
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_HEX = frozenset("0123456789abcdef")


class StrategyAdmissionError(ValueError):
    """Stable fail-closed strategy-admission input error."""


def _fail(code: str) -> NoReturn:
    raise StrategyAdmissionError(code) from None


def _hex64(value: object) -> bool:
    return type(value) is str and len(value) == 64 and all(ch in _HEX for ch in value)


def _name(value: object) -> bool:
    return type(value) is str and _SAFE_NAME.fullmatch(value) is not None


def _finite(value: object) -> bool:
    return type(value) is float and math.isfinite(value)


def _identity(type_name: str, payload: object) -> str:
    raw = json.dumps(
        {"hash_version": _HASH_VERSION, "type": type_name, "payload": payload},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _float_wire(value: float) -> str:
    return value.hex()


@dataclass(frozen=True, slots=True)
class MetricObservation:
    """One finite metric observed for one candidate scenario."""

    name: str
    value: float

    def __post_init__(self) -> None:
        if not _name(self.name) or not _finite(self.value):
            _fail("ADMISSION_METRIC_INVALID")


@dataclass(frozen=True, slots=True)
class ScenarioEvidence:
    """Complete metric vector for one required scenario."""

    scenario_id: str
    metrics: tuple[MetricObservation, ...]

    def __post_init__(self) -> None:
        if (
            not _name(self.scenario_id)
            or type(self.metrics) is not tuple
            or not self.metrics
            or any(type(item) is not MetricObservation for item in self.metrics)
            or tuple(sorted(self.metrics, key=lambda item: item.name)) != self.metrics
            or len({item.name for item in self.metrics}) != len(self.metrics)
        ):
            _fail("ADMISSION_METRIC_SET_INVALID")


def _subject_payload(subject: StrategyCandidate) -> dict[str, object]:
    return {
        "candidate_id": subject.candidate_id,
        "segment": subject.segment,
        "snapshot_identity": subject.snapshot_identity,
        "window_identity": subject.window_identity,
        "rules_identity": subject.rules_identity,
        "costs_identity": subject.costs_identity,
        "scenarios": [
            {
                "scenario_id": scenario.scenario_id,
                "metrics": [
                    {"name": metric.name, "value": _float_wire(metric.value)}
                    for metric in scenario.metrics
                ],
            }
            for scenario in subject.scenarios
        ],
    }


@dataclass(frozen=True, slots=True)
class StrategyCandidate:
    """Identity-bound candidate evidence, independent of the future B7 type."""

    subject_identity: str
    candidate_id: str
    segment: Segment
    snapshot_identity: str
    window_identity: str
    rules_identity: str
    costs_identity: str
    scenarios: tuple[ScenarioEvidence, ...]

    def __post_init__(self) -> None:
        if (
            not _hex64(self.subject_identity)
            or not _name(self.candidate_id)
            or self.segment not in ("validation", "test")
            or any(
                not _hex64(value)
                for value in (
                    self.snapshot_identity,
                    self.window_identity,
                    self.rules_identity,
                    self.costs_identity,
                )
            )
            or type(self.scenarios) is not tuple
            or not self.scenarios
            or any(type(item) is not ScenarioEvidence for item in self.scenarios)
            or tuple(sorted(self.scenarios, key=lambda item: item.scenario_id))
            != self.scenarios
            or len({item.scenario_id for item in self.scenarios}) != len(self.scenarios)
            or self.subject_identity != _identity("StrategyCandidate", _subject_payload(self))
        ):
            _fail("ADMISSION_SUBJECT_INVALID")


def build_strategy_candidate(
    *,
    candidate_id: str,
    segment: Segment,
    snapshot_identity: str,
    window_identity: str,
    rules_identity: str,
    costs_identity: str,
    scenarios: tuple[ScenarioEvidence, ...],
) -> StrategyCandidate:
    """Canonicalize and identity-bind one candidate's complete evidence."""
    if (
        not _name(candidate_id)
        or segment not in ("validation", "test")
        or any(
            not _hex64(value)
            for value in (
                snapshot_identity,
                window_identity,
                rules_identity,
                costs_identity,
            )
        )
        or type(scenarios) is not tuple
        or not scenarios
        or any(type(item) is not ScenarioEvidence for item in scenarios)
    ):
        _fail("ADMISSION_SUBJECT_INVALID")
    ordered = tuple(sorted(scenarios, key=lambda item: item.scenario_id))
    provisional = StrategyCandidate.__new__(StrategyCandidate)
    values = {
        "candidate_id": candidate_id,
        "segment": segment,
        "snapshot_identity": snapshot_identity,
        "window_identity": window_identity,
        "rules_identity": rules_identity,
        "costs_identity": costs_identity,
        "scenarios": ordered,
    }
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    object.__setattr__(provisional, "subject_identity", "0" * 64)
    identity = _identity("StrategyCandidate", _subject_payload(provisional))
    return StrategyCandidate(subject_identity=identity, **values)  # type: ignore[arg-type]


def _context_payload(context: AdmissionContext) -> dict[str, object]:
    return {
        "segment": context.segment,
        "snapshot_identity": context.snapshot_identity,
        "window_identity": context.window_identity,
        "rules_identity": context.rules_identity,
        "costs_identity": context.costs_identity,
        "candidate_ids": list(context.candidate_ids),
        "scenario_ids": list(context.scenario_ids),
    }


@dataclass(frozen=True, slots=True)
class AdmissionContext:
    """The exact test-only comparison domain shared by all candidates."""

    context_identity: str
    segment: Segment
    snapshot_identity: str
    window_identity: str
    rules_identity: str
    costs_identity: str
    candidate_ids: tuple[str, ...]
    scenario_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            not _hex64(self.context_identity)
            or self.segment != "test"
            or any(
                not _hex64(value)
                for value in (
                    self.snapshot_identity,
                    self.window_identity,
                    self.rules_identity,
                    self.costs_identity,
                )
            )
            or type(self.candidate_ids) is not tuple
            or len(self.candidate_ids) < 2
            or any(not _name(item) for item in self.candidate_ids)
            or tuple(sorted(set(self.candidate_ids))) != self.candidate_ids
            or type(self.scenario_ids) is not tuple
            or not self.scenario_ids
            or any(not _name(item) for item in self.scenario_ids)
            or tuple(sorted(set(self.scenario_ids))) != self.scenario_ids
            or self.context_identity != _identity("AdmissionContext", _context_payload(self))
        ):
            _fail("ADMISSION_CONTEXT_INVALID")


def build_admission_context(
    *,
    segment: Segment,
    snapshot_identity: str,
    window_identity: str,
    rules_identity: str,
    costs_identity: str,
    candidate_ids: tuple[str, ...],
    scenario_ids: tuple[str, ...],
) -> AdmissionContext:
    """Build the closed candidate/scenario comparison context."""
    if (
        segment != "test"
        or any(
            not _hex64(value)
            for value in (
                snapshot_identity,
                window_identity,
                rules_identity,
                costs_identity,
            )
        )
        or type(candidate_ids) is not tuple
        or len(candidate_ids) < 2
        or any(not _name(item) for item in candidate_ids)
        or type(scenario_ids) is not tuple
        or not scenario_ids
        or any(not _name(item) for item in scenario_ids)
    ):
        _fail("ADMISSION_CONTEXT_INVALID")
    values = {
        "segment": segment,
        "snapshot_identity": snapshot_identity,
        "window_identity": window_identity,
        "rules_identity": rules_identity,
        "costs_identity": costs_identity,
        "candidate_ids": tuple(sorted(candidate_ids)),
        "scenario_ids": tuple(sorted(scenario_ids)),
    }
    provisional = AdmissionContext.__new__(AdmissionContext)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    object.__setattr__(provisional, "context_identity", "0" * 64)
    identity = _identity("AdmissionContext", _context_payload(provisional))
    return AdmissionContext(context_identity=identity, **values)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class MetricThreshold:
    """One explicit per-scenario admission threshold."""

    metric_name: str
    comparison: Comparison
    value: float

    def __post_init__(self) -> None:
        if (
            not _name(self.metric_name)
            or self.comparison not in ("MINIMUM", "MAXIMUM")
            or not _finite(self.value)
        ):
            _fail("ADMISSION_THRESHOLDS_INVALID")


def _thresholds_payload(thresholds: AdmissionThresholds) -> dict[str, object]:
    return {
        "ranking_metric": thresholds.ranking_metric,
        "rules": [
            {
                "metric_name": item.metric_name,
                "comparison": item.comparison,
                "value": _float_wire(item.value),
            }
            for item in thresholds.rules
        ],
    }


@dataclass(frozen=True, slots=True)
class AdmissionThresholds:
    """Identity-bound threshold set and deterministic ranking metric."""

    thresholds_identity: str
    ranking_metric: str
    rules: tuple[MetricThreshold, ...]

    def __post_init__(self) -> None:
        if (
            not _hex64(self.thresholds_identity)
            or not _name(self.ranking_metric)
            or type(self.rules) is not tuple
            or not self.rules
            or any(type(item) is not MetricThreshold for item in self.rules)
            or tuple(sorted(self.rules, key=lambda item: item.metric_name)) != self.rules
            or len({item.metric_name for item in self.rules}) != len(self.rules)
            or self.ranking_metric not in {item.metric_name for item in self.rules}
            or self.thresholds_identity
            != _identity("AdmissionThresholds", _thresholds_payload(self))
        ):
            _fail("ADMISSION_THRESHOLDS_INVALID")


def build_admission_thresholds(
    *, ranking_metric: str, rules: tuple[MetricThreshold, ...]
) -> AdmissionThresholds:
    """Canonicalize explicit thresholds; values never come from candidates."""
    if (
        not _name(ranking_metric)
        or type(rules) is not tuple
        or not rules
        or any(type(item) is not MetricThreshold for item in rules)
    ):
        _fail("ADMISSION_THRESHOLDS_INVALID")
    ordered = tuple(sorted(rules, key=lambda item: item.metric_name))
    provisional = AdmissionThresholds.__new__(AdmissionThresholds)
    object.__setattr__(provisional, "thresholds_identity", "0" * 64)
    object.__setattr__(provisional, "ranking_metric", ranking_metric)
    object.__setattr__(provisional, "rules", ordered)
    identity = _identity("AdmissionThresholds", _thresholds_payload(provisional))
    return AdmissionThresholds(identity, ranking_metric, ordered)


@dataclass(frozen=True, slots=True)
class MetricCheck:
    candidate_id: str
    scenario_id: str
    metric_name: str
    observed: float
    comparison: Comparison
    threshold: float
    passed: bool


@dataclass(frozen=True, slots=True)
class CandidateAdmissionEvidence:
    candidate_id: str
    subject_identity: str
    passed: bool
    worst_case_ranking_value: float
    checks: tuple[MetricCheck, ...]


def _decision_payload(decision: AdmissionDecision) -> dict[str, object]:
    return {
        "status": decision.status,
        "code": decision.code,
        "selected_candidate_id": decision.selected_candidate_id,
        "context_identity": decision.context_identity,
        "thresholds_identity": decision.thresholds_identity,
        "evidence": [
            {
                "candidate_id": item.candidate_id,
                "subject_identity": item.subject_identity,
                "passed": item.passed,
                "worst_case_ranking_value": _float_wire(
                    item.worst_case_ranking_value
                ),
                "checks": [
                    {
                        "candidate_id": check.candidate_id,
                        "scenario_id": check.scenario_id,
                        "metric_name": check.metric_name,
                        "observed": _float_wire(check.observed),
                        "comparison": check.comparison,
                        "threshold": _float_wire(check.threshold),
                        "passed": check.passed,
                    }
                    for check in item.checks
                ],
            }
            for item in decision.evidence
        ],
    }


@dataclass(frozen=True, slots=True)
class AdmissionDecision:
    """Evidence-only result. It has no deployment or execution capability."""

    decision_identity: str
    status: AdmissionStatus
    code: str
    selected_candidate_id: str | None
    context_identity: str
    thresholds_identity: str
    evidence: tuple[CandidateAdmissionEvidence, ...]

    def __post_init__(self) -> None:
        if (
            not _hex64(self.decision_identity)
            or self.status not in ("ADMIT", "REJECT")
            or not _name(self.code)
            or (self.selected_candidate_id is not None and not _name(self.selected_candidate_id))
            or not _hex64(self.context_identity)
            or not _hex64(self.thresholds_identity)
            or type(self.evidence) is not tuple
            or not self.evidence
            or self.decision_identity != _identity("AdmissionDecision", _decision_payload(self))
        ):
            _fail("ADMISSION_DECISION_INVALID")


def compare_strategy_candidates(
    subjects: tuple[StrategyCandidate, ...],
    common_context: AdmissionContext,
    thresholds: AdmissionThresholds,
) -> AdmissionDecision:
    """Compare complete candidate evidence and return a non-deploying decision."""
    if (
        type(subjects) is not tuple
        or any(type(item) is not StrategyCandidate for item in subjects)
        or type(common_context) is not AdmissionContext
        or type(thresholds) is not AdmissionThresholds
    ):
        _fail("ADMISSION_INPUT_INVALID")
    # Reconstruct each frozen contract so object.__setattr__ tampering cannot pass.
    AdmissionContext(**{name: getattr(common_context, name) for name in common_context.__slots__})
    for rule in thresholds.rules:
        MetricThreshold(rule.metric_name, rule.comparison, rule.value)
    AdmissionThresholds(**{name: getattr(thresholds, name) for name in thresholds.__slots__})
    ordered = tuple(sorted(subjects, key=lambda item: item.candidate_id))
    for item in ordered:
        for scenario in item.scenarios:
            ScenarioEvidence(
                scenario.scenario_id,
                tuple(MetricObservation(metric.name, metric.value) for metric in scenario.metrics),
            )
        StrategyCandidate(**{name: getattr(item, name) for name in item.__slots__})
    if tuple(item.candidate_id for item in ordered) != common_context.candidate_ids:
        _fail("ADMISSION_CANDIDATE_SET_INVALID")

    required_scenarios = common_context.scenario_ids
    required_metrics = tuple(item.metric_name for item in thresholds.rules)
    context_values = (
        common_context.segment,
        common_context.snapshot_identity,
        common_context.window_identity,
        common_context.rules_identity,
        common_context.costs_identity,
    )
    evidence: list[CandidateAdmissionEvidence] = []
    rule_by_name = {item.metric_name: item for item in thresholds.rules}
    ranking_rule = rule_by_name[thresholds.ranking_metric]
    for subject in ordered:
        if (
            subject.segment,
            subject.snapshot_identity,
            subject.window_identity,
            subject.rules_identity,
            subject.costs_identity,
        ) != context_values:
            _fail("ADMISSION_CONTEXT_MISMATCH")
        if tuple(item.scenario_id for item in subject.scenarios) != required_scenarios:
            _fail("ADMISSION_SCENARIO_SET_INVALID")
        checks: list[MetricCheck] = []
        ranking_values: list[float] = []
        for scenario in subject.scenarios:
            if tuple(item.name for item in scenario.metrics) != required_metrics:
                _fail("ADMISSION_METRIC_SET_INVALID")
            for metric in scenario.metrics:
                rule = rule_by_name[metric.name]
                passed = (
                    metric.value >= rule.value
                    if rule.comparison == "MINIMUM"
                    else metric.value <= rule.value
                )
                checks.append(
                    MetricCheck(
                        subject.candidate_id,
                        scenario.scenario_id,
                        metric.name,
                        metric.value,
                        rule.comparison,
                        rule.value,
                        passed,
                    )
                )
                if metric.name == thresholds.ranking_metric:
                    ranking_values.append(metric.value)
        worst = (
            min(ranking_values)
            if ranking_rule.comparison == "MINIMUM"
            else max(ranking_values)
        )
        evidence.append(
            CandidateAdmissionEvidence(
                subject.candidate_id,
                subject.subject_identity,
                all(item.passed for item in checks),
                worst,
                tuple(checks),
            )
        )

    passing = tuple(item for item in evidence if item.passed)
    selected: str | None = None
    status: AdmissionStatus = "REJECT"
    if not passing:
        code = "NO_CANDIDATE_PASSED"
    else:
        best_value = (
            max(item.worst_case_ranking_value for item in passing)
            if ranking_rule.comparison == "MINIMUM"
            else min(item.worst_case_ranking_value for item in passing)
        )
        winners = tuple(
            item for item in passing if item.worst_case_ranking_value == best_value
        )
        if len(winners) != 1:
            code = "RANKING_TIE"
        else:
            status = "ADMIT"
            code = "UNIQUE_THRESHOLD_WINNER"
            selected = winners[0].candidate_id
    provisional = AdmissionDecision.__new__(AdmissionDecision)
    provisional_values = (
        ("decision_identity", "0" * 64),
        ("status", status),
        ("code", code),
        ("selected_candidate_id", selected),
        ("context_identity", common_context.context_identity),
        ("thresholds_identity", thresholds.thresholds_identity),
        ("evidence", tuple(evidence)),
    )
    for name, value in provisional_values:
        object.__setattr__(provisional, name, value)
    identity = _identity("AdmissionDecision", _decision_payload(provisional))
    return AdmissionDecision(
        identity,
        status,
        code,
        selected,
        common_context.context_identity,
        thresholds.thresholds_identity,
        tuple(evidence),
    )


def assess(
    *,
    nav: object,
    one: dict,
    two: dict,
    benchmarks: dict,
    model: dict,
    windows: list[dict],
) -> dict:
    """D1 unified portfolio assessment entry — wraps multifactor_assessment.

    M4 evidence-compare APIs above remain unchanged. Callers of portfolio
    admission should prefer this function over importing assess_model directly.
    """
    from quant.domain.assessment_schema import validate_assessment
    from quant.reporting.multifactor_assessment import assess_model

    result = assess_model(nav=nav, one=one, two=two, benchmarks=benchmarks, model=model, windows=windows)
    return validate_assessment(result)


__all__ = [
    "AdmissionContext",
    "AdmissionDecision",
    "AdmissionThresholds",
    "CandidateAdmissionEvidence",
    "MetricCheck",
    "MetricObservation",
    "MetricThreshold",
    "ScenarioEvidence",
    "StrategyAdmissionError",
    "StrategyCandidate",
    "assess",
    "build_admission_context",
    "build_admission_thresholds",
    "build_strategy_candidate",
    "compare_strategy_candidates",
]
