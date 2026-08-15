"""M2-S2 immutable-run and unified-replay admission-core tests."""

from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import replace
from decimal import Decimal, localcontext
from pathlib import Path

import polars as pl
import pytest

import quant.research.s2_paper_admission as s2_module
from quant.backtest.event_simulator import (
    SimulationFillSpec,
    VerifiedSimulationResult,
    build_event_simulation_config,
    build_scheduled_order_plan,
    build_simulation_scenario_plans,
    simulate_order_plans,
)
from quant.data.m3_identity import clean_table_content_sha256
from quant.domain.enums import Market
from quant.portfolio.order_planner import OrderPlanTarget, build_order_plan
from quant.research.lightweight_run import (
    LightweightResearchRunV1,
    compute_code_sha256,
    dataframe_input_digest,
    publish_lightweight_research_run,
)
from quant.research.s2_paper_admission import (
    S2PaperAdmissionError,
    assess_s2_paper_admission,
    derive_s2_replay_context_identities,
)
from quant.research.strategy_admission import (
    MetricObservation,
    MetricThreshold,
    ScenarioEvidence,
    build_admission_context,
    build_admission_thresholds,
    build_strategy_candidate,
)
from tests.unit.test_event_simulator import (
    FRI,
    MON,
    TUE,
    _account,
    _actions,
    _at,
    _market,
    _planner,
    _rule,
)
from tests.unit.test_lightweight_research_run import _run


def _hex(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _publish_run(
    tmp_path: Path,
    *,
    conclusion: str = "RESEARCH_ONLY",
    forward_target: bool = True,
) -> tuple[Path, LightweightResearchRunV1]:
    source = tmp_path / "source.py"
    source.write_text("pass\n", encoding="utf-8")
    code_sha256 = compute_code_sha256(
        project_root=tmp_path, relative_paths=("source.py",)
    )
    frame = pl.DataFrame({
        "symbol": ["510300.SH"],
        "trade_date": [dt.date(2026, 7, 10)],
        "close": [4.1],
    })
    digest = dataframe_input_digest(
        name="prices",
        frame=frame,
        sort_by=("trade_date", "symbol"),
        date_column="trade_date",
    )
    run = replace(_run(digest, code_sha256), conclusion=conclusion)
    output_name = "target_weights.parquet" if forward_target else "test_targets.parquet"
    root, published, _ = publish_lightweight_research_run(
        artifact_root=tmp_path / "artifacts",
        run=run,
        output_payloads={output_name: b"parquet", "report.json": b"{}"},
    )
    return root, published


def _replay(target_identity: str) -> VerifiedSimulationResult:
    planner = _planner()
    account = _account()
    first = _market(FRI)
    snapshots = (first, _market(MON), _market(TUE))
    plan = build_order_plan(
        targets=(OrderPlanTarget("600000.SH", Market.SH, None, Decimal("1")),),
        target_identity=target_identity,
        market=first,
        account=account,
        config=planner,
    )
    intent = plan.intents[0]
    scheduled = build_scheduled_order_plan(
        plan=plan,
        planned_account=account,
        session_date=FRI,
        signal_known_at=_at(FRI, 0, 30),
        session_close_at=_at(FRI, 7),
        fills=(
            SimulationFillSpec(
                intent.intent_id,
                _at(FRI, 2),
                intent.quantity,
                intent.quantity,
                Decimal("10"),
            ),
        ),
    )
    scenario = build_simulation_scenario_plans(
        scenario_id="base", scheduled_plans=(scheduled,)
    )
    actions = _actions()
    config = build_event_simulation_config(
        event_sessions=(FRI, MON, TUE),
        terminal_date=TUE,
        planner_configs=(planner,),
        settlement_rules=(_rule(),),
        corporate_actions=actions,
        corporate_actions_sha256=clean_table_content_sha256(
            table_name="corporate_action_ledger", frame=actions
        ),
        sh_sessions=(FRI, MON, TUE),
    )
    return simulate_order_plans((scenario,), snapshots, account, config)


def _evidence(
    run_id: str,
    replay: VerifiedSimulationResult,
    *,
    source_return: float = 0.2,
    baseline_return: float = 0.1,
):
    derived = derive_s2_replay_context_identities(replay)
    candidate_ids = tuple(sorted((run_id, "baseline")))
    context = build_admission_context(
        segment="test",
        snapshot_identity=derived.snapshot_identity,
        window_identity=derived.window_identity,
        rules_identity=derived.rules_identity,
        costs_identity=derived.costs_identity,
        candidate_ids=candidate_ids,
        scenario_ids=derived.scenario_ids,
    )

    def subject(candidate_id: str, return_: float):
        return build_strategy_candidate(
            candidate_id=candidate_id,
            segment="test",
            snapshot_identity=derived.snapshot_identity,
            window_identity=derived.window_identity,
            rules_identity=derived.rules_identity,
            costs_identity=derived.costs_identity,
            scenarios=(
                ScenarioEvidence(
                    "base",
                    (
                        MetricObservation("drawdown", 0.1),
                        MetricObservation("return", return_),
                    ),
                ),
            ),
        )

    subjects = (
        subject("baseline", baseline_return),
        subject(run_id, source_return),
    )
    thresholds = build_admission_thresholds(
        ranking_metric="return",
        rules=(
            MetricThreshold("drawdown", "MAXIMUM", 0.2),
            MetricThreshold("return", "MINIMUM", 0.0),
        ),
    )
    return subjects, context, thresholds


def _assess(root: Path, replay: VerifiedSimulationResult, evidence):
    subjects, context, thresholds = evidence
    return assess_s2_paper_admission(
        run_root=root,
        replay_result=replay,
        admission_subjects=subjects,
        admission_context=context,
        admission_thresholds=thresholds,
    )


def _assert_invalid(operation) -> None:
    with pytest.raises(
        S2PaperAdmissionError, match="^S2_PAPER_ADMISSION_INVALID$"
    ) as caught:
        operation()
    assert caught.value.__cause__ is None and caught.value.__context__ is None


def test_source_status_and_missing_evidence_are_explicit(tmp_path) -> None:
    root, run = _publish_run(tmp_path)
    decision = assess_s2_paper_admission(
        run_root=root,
        replay_result=None,
        admission_subjects=None,
        admission_context=None,
        admission_thresholds=None,
    )
    assert decision.source_run_id == run.run_id
    assert decision.status == "RESEARCH_ONLY"
    assert decision.code == "ADMISSION_EVIDENCE_NOT_PROVIDED"


@pytest.mark.parametrize(
    ("conclusion", "code"),
    [
        ("REJECTED", "SOURCE_RUN_REJECTED"),
        ("PAPER_CANDIDATE", "SOURCE_CANDIDATE_SELF_ATTESTATION_REJECTED"),
    ],
)
def test_source_rejection_or_candidate_self_attestation_cannot_advance(
    tmp_path, conclusion: str, code: str
) -> None:
    root, _ = _publish_run(tmp_path, conclusion=conclusion)
    decision = assess_s2_paper_admission(
        run_root=root,
        replay_result=None,
        admission_subjects=None,
        admission_context=None,
        admission_thresholds=None,
    )
    assert decision.status == "REJECTED" and decision.code == code


def test_real_replay_and_pretty_unbound_metrics_remain_research_only(tmp_path) -> None:
    root, run = _publish_run(tmp_path)
    replay = _replay(run.run_id)
    decision = _assess(root, replay, _evidence(run.run_id, replay))
    assert decision.status == "RESEARCH_ONLY"
    assert decision.code == "ADMISSION_METRICS_PROVENANCE_UNBOUND"
    assert decision.replay_result_id == replay.result_id
    assert decision.admission_decision_identity is not None
    assert "ADMISSION_METRICS_UNBOUND" in decision.checks


def test_historical_test_targets_remain_research_only_after_full_recompute(
    tmp_path,
) -> None:
    root, run = _publish_run(tmp_path, forward_target=False)
    replay = _replay(run.run_id)
    decision = _assess(root, replay, _evidence(run.run_id, replay))
    assert decision.status == "RESEARCH_ONLY"
    assert decision.code == "ADMISSION_METRICS_PROVENANCE_UNBOUND"
    assert "FORWARD_TARGET_MISSING" in decision.checks
    assert "ADMISSION_METRICS_UNBOUND" in decision.checks
    assert decision.admission_decision_identity is not None


def test_partial_forged_or_other_target_evidence_fails_closed(tmp_path) -> None:
    root, run = _publish_run(tmp_path)
    replay = _replay(run.run_id)
    subjects, context, thresholds = _evidence(run.run_id, replay)

    _assert_invalid(
        lambda: assess_s2_paper_admission(
            run_root=root,
            replay_result=replay,
            admission_subjects=subjects,
            admission_context=None,
            admission_thresholds=thresholds,
        )
    )
    forged = replace(replay, result_id="0" * 64)
    _assert_invalid(lambda: _assess(root, forged, (subjects, context, thresholds)))

    other_replay = _replay(_hex("another-target"))
    other_evidence = _evidence(run.run_id, other_replay)
    _assert_invalid(lambda: _assess(root, other_replay, other_evidence))


def test_context_mismatch_and_missing_source_candidate_fail_closed(tmp_path) -> None:
    root, run = _publish_run(tmp_path)
    replay = _replay(run.run_id)
    subjects, context, thresholds = _evidence(run.run_id, replay)
    mismatched = build_admission_context(
        segment="test",
        snapshot_identity=_hex("other-snapshot"),
        window_identity=context.window_identity,
        rules_identity=context.rules_identity,
        costs_identity=context.costs_identity,
        candidate_ids=context.candidate_ids,
        scenario_ids=context.scenario_ids,
    )
    _assert_invalid(lambda: _assess(root, replay, (subjects, mismatched, thresholds)))
    _assert_invalid(
        lambda: _assess(root, replay, ((subjects[0],), context, thresholds))
    )


@pytest.mark.parametrize(
    ("source_return", "baseline_return"),
    [
        (-0.1, -0.2),
        (0.1, 0.2),
    ],
)
def test_unbound_b8_reject_or_other_winner_cannot_reject_source(
    tmp_path, source_return: float, baseline_return: float
) -> None:
    root, run = _publish_run(tmp_path)
    replay = _replay(run.run_id)
    evidence = _evidence(
        run.run_id,
        replay,
        source_return=source_return,
        baseline_return=baseline_return,
    )
    decision = _assess(root, replay, evidence)
    assert decision.status == "RESEARCH_ONLY"
    assert decision.code == "ADMISSION_METRICS_PROVENANCE_UNBOUND"
    assert "ADMISSION_METRICS_UNBOUND" in decision.checks


def test_tuple_order_decimal_context_and_source_tree_do_not_change_decision(
    tmp_path,
) -> None:
    root, run = _publish_run(tmp_path)
    replay = _replay(run.run_id)
    evidence = _evidence(run.run_id, replay)
    before = {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }
    direct = _assess(root, replay, evidence)
    subjects, context, thresholds = evidence
    with localcontext() as decimal_context:
        decimal_context.prec = 7
        reordered = _assess(root, replay, (tuple(reversed(subjects)), context, thresholds))
    after = {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }
    assert reordered == direct
    assert after == before


@pytest.mark.parametrize("target", ["replay", "admission"])
def test_hostile_dependency_exception_graph_is_detached(
    tmp_path, monkeypatch: pytest.MonkeyPatch, target: str
) -> None:
    root, run = _publish_run(tmp_path)
    replay = _replay(run.run_id)
    evidence = _evidence(run.run_id, replay)

    class HostileError(Exception):
        pass

    hostile = HostileError(str(root / "secret-account"))
    hostile.__cause__ = hostile
    hostile.__context__ = hostile

    def fail(*_args, **_kwargs):
        raise hostile

    attribute = (
        "verify_simulation_result_identity"
        if target == "replay"
        else "compare_strategy_candidates"
    )
    monkeypatch.setattr(s2_module, attribute, fail)
    _assert_invalid(lambda: _assess(root, replay, evidence))


def test_module_has_no_publish_deploy_or_order_capability() -> None:
    public_names = set(s2_module.__all__)
    assert not any(
        fragment in name.lower()
        for name in public_names
        for fragment in ("publish", "deploy", "order", "gateway")
    )
