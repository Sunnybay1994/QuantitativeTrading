"""Research orchestration and evidence-only admission interfaces."""

from quant.research.strategy_admission import (
    AdmissionContext,
    AdmissionDecision,
    AdmissionThresholds,
    MetricObservation,
    MetricThreshold,
    ScenarioEvidence,
    StrategyAdmissionError,
    StrategyCandidate,
    build_admission_context,
    build_admission_thresholds,
    build_strategy_candidate,
    compare_strategy_candidates,
)

__all__ = [
    "AdmissionContext",
    "AdmissionDecision",
    "AdmissionThresholds",
    "MetricObservation",
    "MetricThreshold",
    "ScenarioEvidence",
    "StrategyAdmissionError",
    "StrategyCandidate",
    "build_admission_context",
    "build_admission_thresholds",
    "build_strategy_candidate",
    "compare_strategy_candidates",
]
