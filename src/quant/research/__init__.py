"""Research orchestration, lightweight runs, and evidence-only admission."""

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
from quant.research.lightweight_run import (
    LightweightResearchRunV1,
    ResearchFoldV1,
    ResearchInputDigestV1,
    ResearchOutputDigestV1,
    compute_code_sha256,
    dataframe_input_digest,
    publish_lightweight_research_run,
)

__all__ = [
    "AdmissionContext",
    "AdmissionDecision",
    "AdmissionThresholds",
    "LightweightResearchRunV1",
    "MetricObservation",
    "MetricThreshold",
    "ResearchFoldV1",
    "ResearchInputDigestV1",
    "ResearchOutputDigestV1",
    "ScenarioEvidence",
    "StrategyAdmissionError",
    "StrategyCandidate",
    "build_admission_context",
    "build_admission_thresholds",
    "build_strategy_candidate",
    "compare_strategy_candidates",
    "compute_code_sha256",
    "dataframe_input_digest",
    "publish_lightweight_research_run",
]
