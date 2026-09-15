"""Read-only S2 evidence assessment for human PAPER-candidate admission."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from dataclasses import dataclass
from decimal import Context, ROUND_HALF_EVEN, localcontext
from pathlib import Path
from typing import Literal, NoReturn, cast

from quant.backtest.event_simulator import (
    VerifiedSimulationResult,
    verify_simulation_result_identity,
)
from quant.research.lightweight_run import verify_lightweight_research_run
from quant.research.strategy_admission import (
    AdmissionContext,
    AdmissionThresholds,
    StrategyCandidate,
    compare_strategy_candidates,
)

S2PaperAdmissionStatus = Literal[
    "REJECTED", "RESEARCH_ONLY", "ELIGIBLE_FOR_HUMAN_ADMISSION"
]

_HASH_VERSION = "m2-s2-paper-admission-v1"
_HEX = frozenset("0123456789abcdef")
_SAFE_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")
_DECIMAL_CONTEXT = Context(prec=28, rounding=ROUND_HALF_EVEN)


class S2PaperAdmissionError(ValueError):
    """Stable, payload-free failure for invalid S2 evidence."""


def _invalid() -> NoReturn:
    raise S2PaperAdmissionError("S2_PAPER_ADMISSION_INVALID") from None


@dataclass(frozen=True, slots=True)
class S2ReplayContextIdentities:
    """B8 context identities derived only from a proven B6 replay closure."""

    snapshot_identity: str
    window_identity: str
    rules_identity: str
    costs_identity: str
    scenario_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            any(
                not _hex64(value)
                for value in (
                    self.snapshot_identity,
                    self.window_identity,
                    self.rules_identity,
                    self.costs_identity,
                )
            )
            or type(self.scenario_ids) is not tuple
            or not self.scenario_ids
            or tuple(sorted(set(self.scenario_ids))) != self.scenario_ids
        ):
            _invalid()


@dataclass(frozen=True, slots=True)
class S2PaperAdmissionDecision:
    """Auditable decision only; this object conveys no execution capability."""

    decision_id: str
    source_run_id: str
    status: S2PaperAdmissionStatus
    code: str
    replay_result_id: str | None
    admission_decision_identity: str | None
    checks: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            not _hex64(self.decision_id)
            or not _hex64(self.source_run_id)
            or self.status
            not in {"REJECTED", "RESEARCH_ONLY", "ELIGIBLE_FOR_HUMAN_ADMISSION"}
            or type(self.code) is not str
            or _SAFE_CODE.fullmatch(self.code) is None
            or (
                self.replay_result_id is not None
                and not _hex64(self.replay_result_id)
            )
            or (
                self.admission_decision_identity is not None
                and not _hex64(self.admission_decision_identity)
            )
            or type(self.checks) is not tuple
            or not self.checks
            or any(
                type(item) is not str or _SAFE_CODE.fullmatch(item) is None
                for item in self.checks
            )
            or len(set(self.checks)) != len(self.checks)
            or self.decision_id != _decision_identity(self)
        ):
            _invalid()


def derive_s2_replay_context_identities(
    replay_result: VerifiedSimulationResult,
) -> S2ReplayContextIdentities:
    """Verify B6 replay bytes in memory and derive its exact B8 context binding."""
    failed = False
    derived: S2ReplayContextIdentities | None = None
    try:
        with localcontext(_DECIMAL_CONTEXT):
            proven = verify_simulation_result_identity(replay_result)
            derived = _derive_replay_context(proven)
    except Exception:
        failed = True
    if failed or derived is None:
        _invalid()
    return derived


def assess_s2_paper_admission(
    *,
    run_root: Path,
    replay_result: VerifiedSimulationResult | None,
    admission_subjects: tuple[StrategyCandidate, ...] | None,
    admission_context: AdmissionContext | None,
    admission_thresholds: AdmissionThresholds | None,
) -> S2PaperAdmissionDecision:
    """Freshly assess immutable run, replay, and B8 evidence without publishing."""
    failed = False
    decision: S2PaperAdmissionDecision | None = None
    try:
        decision = _assess_s2_paper_admission(
            run_root=run_root,
            replay_result=replay_result,
            admission_subjects=admission_subjects,
            admission_context=admission_context,
            admission_thresholds=admission_thresholds,
        )
    except Exception:
        failed = True
    if failed or decision is None:
        _invalid()
    return decision


def _assess_s2_paper_admission(
    *,
    run_root: Path,
    replay_result: VerifiedSimulationResult | None,
    admission_subjects: tuple[StrategyCandidate, ...] | None,
    admission_context: AdmissionContext | None,
    admission_thresholds: AdmissionThresholds | None,
) -> S2PaperAdmissionDecision:
    run = verify_lightweight_research_run(run_root=run_root)
    base_checks = ("SOURCE_RUN_VERIFIED",)
    if run.conclusion == "REJECTED":
        return _decision(
            source_run_id=run.run_id,
            status="REJECTED",
            code="SOURCE_RUN_REJECTED",
            replay_result_id=None,
            admission_decision_identity=None,
            checks=(*base_checks, "SOURCE_CONCLUSION_REJECTED"),
        )
    if run.conclusion != "RESEARCH_ONLY":
        return _decision(
            source_run_id=run.run_id,
            status="REJECTED",
            code="SOURCE_CANDIDATE_SELF_ATTESTATION_REJECTED",
            replay_result_id=None,
            admission_decision_identity=None,
            checks=(*base_checks, "SOURCE_SELF_ATTESTATION_REJECTED"),
        )

    evidence = (
        replay_result,
        admission_subjects,
        admission_context,
        admission_thresholds,
    )
    present = tuple(item is not None for item in evidence)
    if not any(present):
        return _decision(
            source_run_id=run.run_id,
            status="RESEARCH_ONLY",
            code="ADMISSION_EVIDENCE_NOT_PROVIDED",
            replay_result_id=None,
            admission_decision_identity=None,
            checks=(*base_checks, "SOURCE_RESEARCH_ONLY", "EVIDENCE_ABSENT"),
        )
    if not all(present):
        raise ValueError("partial S2 evidence")
    if (
        type(replay_result) is not VerifiedSimulationResult
        or type(admission_subjects) is not tuple
        or any(type(item) is not StrategyCandidate for item in admission_subjects)
        or type(admission_context) is not AdmissionContext
        or type(admission_thresholds) is not AdmissionThresholds
    ):
        raise ValueError("invalid S2 evidence types")

    with localcontext(_DECIMAL_CONTEXT):
        proven_replay = verify_simulation_result_identity(replay_result)
        derived = _derive_replay_context(proven_replay)
    if (
        admission_context.snapshot_identity != derived.snapshot_identity
        or admission_context.window_identity != derived.window_identity
        or admission_context.rules_identity != derived.rules_identity
        or admission_context.costs_identity != derived.costs_identity
        or admission_context.scenario_ids != derived.scenario_ids
    ):
        raise ValueError("admission context is not replay-derived")
    if not any(item.candidate_id == run.run_id for item in admission_subjects):
        raise ValueError("source candidate missing")

    for scenario in proven_replay.replay_inputs.plans:
        if not scenario.scheduled_plans:
            raise ValueError("scenario has no scheduled plan")
        if any(
            scheduled.plan.target_identity != run.run_id
            for scheduled in scenario.scheduled_plans
        ):
            raise ValueError("replay target does not bind source run")

    with localcontext(_DECIMAL_CONTEXT):
        admission = compare_strategy_candidates(
            admission_subjects, admission_context, admission_thresholds
        )
    common_checks = (
        *base_checks,
        "SOURCE_RESEARCH_ONLY",
        "REPLAY_IDENTITY_VERIFIED",
        "REPLAY_TARGET_BOUND",
        "REPLAY_CONTEXT_DERIVED",
        "ADMISSION_RECOMPUTED",
    )
    has_forward_target = any(
        item.relative_path == "target_weights.parquet" for item in run.outputs
    )
    # B8 proves only the identity and comparison of caller-supplied metric values.
    # Until a public contract binds those metrics to this proven replay (or to a
    # verified B7 result), neither ADMIT nor REJECT is an admission fact.
    return _decision(
        source_run_id=run.run_id,
        status="RESEARCH_ONLY",
        code="ADMISSION_METRICS_PROVENANCE_UNBOUND",
        replay_result_id=proven_replay.result_id,
        admission_decision_identity=admission.decision_identity,
        checks=(
            *common_checks,
            "FORWARD_TARGET_PRESENT" if has_forward_target else "FORWARD_TARGET_MISSING",
            "ADMISSION_METRICS_UNBOUND",
        ),
    )


def _derive_replay_context(
    replay: VerifiedSimulationResult,
) -> S2ReplayContextIdentities:
    inputs = replay.replay_inputs
    config = inputs.config
    scenario_ids = tuple(item.scenario_id for item in inputs.plans)
    if (
        not scenario_ids
        or scenario_ids != tuple(sorted(set(scenario_ids)))
        or any(not item.scheduled_plans for item in inputs.plans)
    ):
        raise ValueError("invalid replay scenarios")
    return S2ReplayContextIdentities(
        snapshot_identity=_identity(
            "S2ReplaySnapshotContext",
            {"market_snapshot_ids": replay.market_snapshot_ids},
        ),
        window_identity=_identity(
            "S2ReplayWindowContext",
            {
                "event_sessions": config.event_sessions,
                "terminal_date": config.terminal_date,
            },
        ),
        rules_identity=_identity(
            "S2ReplayRulesContext",
            {
                "config_id": config.config_id,
                "settlement_rule_ids": tuple(
                    item.rule_id for item in config.settlement_rules
                ),
                "corporate_actions_sha256": config.corporate_actions_sha256,
                "sh_sessions": config.sh_sessions,
            },
        ),
        costs_identity=_identity(
            "S2ReplayCostsContext",
            {
                "planner_config_ids": tuple(
                    item.config_identity for item in config.planner_configs
                )
            },
        ),
        scenario_ids=scenario_ids,
    )


def _decision(
    *,
    source_run_id: str,
    status: S2PaperAdmissionStatus,
    code: str,
    replay_result_id: str | None,
    admission_decision_identity: str | None,
    checks: tuple[str, ...],
) -> S2PaperAdmissionDecision:
    provisional = S2PaperAdmissionDecision.__new__(S2PaperAdmissionDecision)
    values = {
        "source_run_id": source_run_id,
        "status": status,
        "code": code,
        "replay_result_id": replay_result_id,
        "admission_decision_identity": admission_decision_identity,
        "checks": checks,
    }
    object.__setattr__(provisional, "decision_id", "0" * 64)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    decision_id = _decision_identity(provisional)
    return S2PaperAdmissionDecision(decision_id=decision_id, **values)  # type: ignore[arg-type]


def _decision_identity(decision: S2PaperAdmissionDecision) -> str:
    return _identity(
        "S2PaperAdmissionDecision",
        {
            "source_run_id": decision.source_run_id,
            "status": decision.status,
            "code": decision.code,
            "replay_result_id": decision.replay_result_id,
            "admission_decision_identity": decision.admission_decision_identity,
            "checks": decision.checks,
        },
    )


def _identity(type_name: str, payload: object) -> str:
    raw = json.dumps(
        {
            "hash_version": _HASH_VERSION,
            "type": type_name,
            "payload": _canonical(payload),
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _canonical(value: object) -> object:
    if type(value) is dt.date:
        return value.isoformat()
    if isinstance(value, tuple):
        return [_canonical(item) for item in value]
    if type(value) is list:
        return [_canonical(item) for item in cast(list[object], value)]
    if type(value) is dict:
        mapping = cast(dict[object, object], value)
        if any(type(key) is not str for key in mapping):
            raise ValueError("invalid identity mapping")
        return {cast(str, key): _canonical(child) for key, child in mapping.items()}
    if type(value) in {str, int, bool} or value is None:
        return value
    raise ValueError("invalid identity value")


def _hex64(value: object) -> bool:
    return type(value) is str and len(value) == 64 and all(char in _HEX for char in value)


__all__ = [
    "S2PaperAdmissionDecision",
    "S2PaperAdmissionError",
    "S2PaperAdmissionStatus",
    "S2ReplayContextIdentities",
    "assess_s2_paper_admission",
    "derive_s2_replay_context_identities",
]
