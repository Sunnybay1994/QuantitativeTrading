"""M4-B8 deterministic strategy-admission contract tests."""

from __future__ import annotations

import math

import pytest

from quant.research.strategy_admission import (
    AdmissionContext,
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


def _hex(tag: str) -> str:
    import hashlib

    return hashlib.sha256(tag.encode()).hexdigest()


def _scenario(name: str, *, return_: float, drawdown: float) -> ScenarioEvidence:
    return ScenarioEvidence(
        name,
        tuple(
            sorted(
                (
                    MetricObservation("return", return_),
                    MetricObservation("max_drawdown", drawdown),
                ),
                key=lambda item: item.name,
            )
        ),
    )


def _context(*, segment: str = "test") -> AdmissionContext:
    return build_admission_context(
        segment=segment,  # type: ignore[arg-type]
        snapshot_identity=_hex("snapshot"),
        window_identity=_hex("window"),
        rules_identity=_hex("rules"),
        costs_identity=_hex("costs"),
        candidate_ids=("alpha", "beta"),
        scenario_ids=("base", "stress"),
    )


def _candidate(
    candidate_id: str,
    *,
    segment: str = "test",
    snapshot: str | None = None,
    window: str | None = None,
    rules: str | None = None,
    costs: str | None = None,
    scenarios: tuple[ScenarioEvidence, ...] | None = None,
) -> StrategyCandidate:
    return build_strategy_candidate(
        candidate_id=candidate_id,
        segment=segment,  # type: ignore[arg-type]
        snapshot_identity=snapshot or _hex("snapshot"),
        window_identity=window or _hex("window"),
        rules_identity=rules or _hex("rules"),
        costs_identity=costs or _hex("costs"),
        scenarios=scenarios
        or (
            _scenario("base", return_=0.20, drawdown=0.10),
            _scenario("stress", return_=0.08, drawdown=0.15),
        ),
    )


def _thresholds():
    return build_admission_thresholds(
        ranking_metric="return",
        rules=(
            MetricThreshold("max_drawdown", "MAXIMUM", 0.20),
            MetricThreshold("return", "MINIMUM", 0.05),
        ),
    )


def test_unique_worst_case_winner_emits_evidence_only() -> None:
    from quant.research import compare_strategy_candidates as public_compare

    assert public_compare is compare_strategy_candidates
    alpha = _candidate("alpha")
    beta = _candidate(
        "beta",
        scenarios=(
            _scenario("base", return_=0.30, drawdown=0.09),
            _scenario("stress", return_=0.04, drawdown=0.16),
        ),
    )
    decision = compare_strategy_candidates((beta, alpha), _context(), _thresholds())
    assert decision.status == "ADMIT"
    assert decision.code == "UNIQUE_THRESHOLD_WINNER"
    assert decision.selected_candidate_id == "alpha"
    assert tuple(item.candidate_id for item in decision.evidence) == ("alpha", "beta")
    assert len(decision.evidence[0].checks) == 4
    assert decision.evidence[0].worst_case_ranking_value == 0.08
    assert decision.evidence[1].passed is False
    assert not hasattr(decision, "deploy")


@pytest.mark.parametrize(
    "field,value",
    [
        ("snapshot", _hex("other-snapshot")),
        ("window", _hex("other-window")),
        ("rules", _hex("other-rules")),
        ("costs", _hex("other-costs")),
    ],
)
def test_all_comparison_identities_must_match(field: str, value: str) -> None:
    with pytest.raises(StrategyAdmissionError, match="^ADMISSION_CONTEXT_MISMATCH$"):
        compare_strategy_candidates(
            (
                _candidate("alpha"),
                _candidate(
                    "beta",
                    snapshot=value if field == "snapshot" else None,
                    window=value if field == "window" else None,
                    rules=value if field == "rules" else None,
                    costs=value if field == "costs" else None,
                ),
            ),
            _context(),
            _thresholds(),
        )


def test_missing_candidate_fails_closed() -> None:
    with pytest.raises(
        StrategyAdmissionError, match="^ADMISSION_CANDIDATE_SET_INVALID$"
    ):
        compare_strategy_candidates((_candidate("alpha"),), _context(), _thresholds())


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_non_finite_metric_never_becomes_zero(value: float) -> None:
    with pytest.raises(StrategyAdmissionError, match="^ADMISSION_METRIC_INVALID$"):
        MetricObservation("return", value)


def test_validation_and_test_subjects_cannot_mix() -> None:
    with pytest.raises(StrategyAdmissionError, match="^ADMISSION_CONTEXT_MISMATCH$"):
        compare_strategy_candidates(
            (_candidate("alpha"), _candidate("beta", segment="validation")),
            _context(segment="test"),
            _thresholds(),
        )


def test_validation_only_candidates_cannot_be_admitted() -> None:
    with pytest.raises(StrategyAdmissionError, match="^ADMISSION_CONTEXT_INVALID$"):
        compare_strategy_candidates(
            (
                _candidate("alpha", segment="validation"),
                _candidate("beta", segment="validation"),
            ),
            _context(segment="validation"),
            _thresholds(),
        )


def test_missing_stress_scenario_cannot_cherry_pick_best_case() -> None:
    cherry_picked = _candidate(
        "beta", scenarios=(_scenario("base", return_=0.50, drawdown=0.01),)
    )
    with pytest.raises(
        StrategyAdmissionError, match="^ADMISSION_SCENARIO_SET_INVALID$"
    ):
        compare_strategy_candidates(
            (_candidate("alpha"), cherry_picked), _context(), _thresholds()
        )


def test_tie_and_no_passing_candidate_are_explicit_rejections() -> None:
    alpha = _candidate("alpha")
    beta = _candidate("beta")
    tied = compare_strategy_candidates((alpha, beta), _context(), _thresholds())
    assert (tied.status, tied.code, tied.selected_candidate_id) == (
        "REJECT",
        "RANKING_TIE",
        None,
    )

    impossible = build_admission_thresholds(
        ranking_metric="return",
        rules=(
            MetricThreshold("max_drawdown", "MAXIMUM", 0.01),
            MetricThreshold("return", "MINIMUM", 0.90),
        ),
    )
    rejected = compare_strategy_candidates((alpha, beta), _context(), impossible)
    assert (rejected.status, rejected.code, rejected.selected_candidate_id) == (
        "REJECT",
        "NO_CANDIDATE_PASSED",
        None,
    )


def test_threshold_identity_is_explicit_and_tampering_is_reproved() -> None:
    original = _thresholds()
    changed = build_admission_thresholds(
        ranking_metric="return",
        rules=(
            MetricThreshold("max_drawdown", "MAXIMUM", 0.20),
            MetricThreshold("return", "MINIMUM", 0.06),
        ),
    )
    assert changed.thresholds_identity != original.thresholds_identity

    subject = _candidate("alpha")
    object.__setattr__(subject.scenarios[0].metrics[0], "value", 999.0)
    with pytest.raises(StrategyAdmissionError, match="^ADMISSION_SUBJECT_INVALID$"):
        compare_strategy_candidates(
            (subject, _candidate("beta")), _context(), original
        )
