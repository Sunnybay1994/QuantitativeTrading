"""M4-P8 append-only soak evidence and conservative Gate contracts."""

from __future__ import annotations

import datetime as dt
import hashlib
import inspect
import json
import os
import shutil
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest

import quant.execution.soak as soak_module
from quant.execution.contracts import build_account_snapshot
from quant.execution.reconcile import (
    RecoveryResult,
    build_broker_snapshot,
    recover_local_state,
    reconcile,
)
from quant.execution.soak import (
    SoakError,
    SoakEvidenceKind,
    append_fault_drill,
    append_soak_session,
    build_soak_run,
    decide_soak_gate,
    expected_schedule_identity,
    verify_soak_evidence,
)
from quant.execution.store import ExecutionStore
from quant.reporting.execution_report import build_execution_report
from tests.unit.test_execution_report import _filled_inputs

UTC = dt.timezone.utc
DAY = dt.timedelta(days=1)


@pytest.mark.parametrize(
    "probe",
    (
        "import quant.backtest.event_simulator",
        "import quant.reporting.trading_metrics",
        "import quant.execution.soak",
        """
import sys
import quant.execution as execution
assert "quant.execution.soak" not in sys.modules
try:
    execution.not_a_public_symbol
except AttributeError:
    pass
else:
    raise AssertionError("unknown execution export did not raise AttributeError")
assert "quant.execution.soak" not in sys.modules
from quant.execution import SoakRunManifest
assert SoakRunManifest.__module__ == "quant.execution.soak"
assert "quant.execution.soak" in sys.modules
""",
    ),
    ids=(
        "event-simulator",
        "trading-metrics",
        "execution-soak",
        "execution-lazy-public-export",
    ),
)
def test_public_modules_import_in_fresh_interpreters(probe: str) -> None:
    project_root = Path(__file__).resolve().parents[2]
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=project_root,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


def _hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _dev_root(tmp_path: Path, name: str) -> Path:
    return (tmp_path / name / "artifacts" / "development_example" / "m4_p8").resolve()


def _anchor_root(root: Path) -> Path:
    return (root.parent / (root.name + "_anchors")).resolve()


def _anchor_dir(root: Path, manifest) -> Path:
    return _anchor_root(root) / manifest.run_id / "anchors"


def _runtime_ids(manifest) -> dict[str, str]:
    return {
        "source_identity": manifest.source_identity,
        "config_identity": manifest.config_identity,
        "gateway_identity": manifest.gateway_identity,
        "store_identity": manifest.store_identity,
        "account_identity": manifest.account_identity,
    }


def _manifest(
    root: Path,
    sessions: tuple[dt.date, ...],
    *,
    kind: SoakEvidenceKind = SoakEvidenceKind.DEVELOPMENT_EXAMPLE,
    started_at: dt.datetime | None = None,
):
    start = started_at or dt.datetime(2026, 8, 2, 8, tzinfo=UTC)
    return build_soak_run(
        root=root,
        anchor_root=_anchor_root(root),
        evidence_kind=kind,
        source_identity=_hex("m4-source"),
        config_identity=_hex("paper-config"),
        gateway_identity=_hex("paper-gateway"),
        store_identity=_hex("sqlite-store"),
        account_identity=_hex("account:irreversible"),
        expected_sessions=sessions,
        expected_schedule_identity=expected_schedule_identity(sessions),
        started_at=start,
    )


def _facts(tmp_path: Path, as_of: dt.datetime, name: str):
    store = ExecutionStore.open(
        f"sqlite:///soak-input/{name}.db", trusted_root=tmp_path
    )
    try:
        recovery = recover_local_state(store)
    finally:
        store.close()
    broker = build_broker_snapshot(
        source_identity=_hex("retained-eod-evidence:" + name),
        as_of=as_of,
        finality="END_OF_DAY",
        account=build_account_snapshot(as_of=as_of, positions=(), cash=()),
        orders=(),
        events=(),
    )
    reconciliation = reconcile(recovery, broker, as_of)
    report = build_execution_report(
        recovery=recovery,
        reconciliation=reconciliation,
        as_of=as_of,
    )
    return recovery, reconciliation, report


def _append(
    root: Path,
    manifest,
    session_date: dt.date,
    start: dt.datetime,
    facts,
):
    recovery, reconciliation, report = facts
    return append_soak_session(
        root=root,
        anchor_root=_anchor_root(root),
        manifest=manifest,
        session_date=session_date,
        invocation_started_at=start,
        invocation_completed_at=start + dt.timedelta(minutes=3),
        **_runtime_ids(manifest),
        recovery=recovery,
        reconciliation=reconciliation,
        execution_report=report,
    )


def _replace_closure_and_rehash_receipt(
    root: Path,
    manifest,
    original,
    replacement,
    replacement_facts: bytes,
):
    forged = replace(
        original,
        recovery_id=replacement.recovery_id,
        reconciliation_id=replacement.reconciliation_id,
        execution_report_id=replacement.execution_report_id,
        gate_passed=replacement.gate_passed,
        command_ids_sha256=replacement.command_ids_sha256,
        event_ids_sha256=replacement.event_ids_sha256,
        ledger_state_id=replacement.ledger_state_id,
        issue_codes=replacement.issue_codes,
        facts_sha256=hashlib.sha256(replacement_facts).hexdigest(),
    )
    invocation = soak_module._identity(
        "SoakInvocation",
        {
            "run_id": forged.run_id,
            "session_date": forged.session_date.isoformat(),
            "started_at": soak_module._time(forged.invocation_started_at),
            "completed_at": soak_module._time(forged.invocation_completed_at),
            "recovery_id": forged.recovery_id,
            "reconciliation_id": forged.reconciliation_id,
            "execution_report_id": forged.execution_report_id,
            **_runtime_ids(manifest),
        },
    )
    forged = replace(forged, invocation_identity=invocation)
    values = {name: getattr(forged, name) for name in soak_module._SESSION_FIELDS}
    forged = replace(
        forged,
        receipt_id=soak_module._identity(
            "SoakSessionReceipt", soak_module._session_payload_values(values)
        ),
    )
    session_dir = root / manifest.run_id / "sessions" / forged.session_date.isoformat()
    (session_dir / "facts.json").write_bytes(replacement_facts)
    (session_dir / "receipt.json").write_bytes(soak_module._encode_session(forged))
    return forged


def _paper_decision_evidence(
    manifest,
    *,
    complete: bool,
    blocked: bool = False,
):
    selected_dates = manifest.expected_sessions if complete else manifest.expected_sessions[:1]
    sessions = []
    for index, session_date in enumerate(selected_dates):
        started_at = dt.datetime.combine(session_date, dt.time(8), tzinfo=UTC)
        completed_at = started_at + dt.timedelta(minutes=1)
        issue_codes = ("SOAK_TEST_SESSION_BLOCKED",) if blocked and index == 0 else ()
        values = {
            "schema_version": "m4-soak-session-v1",
            "run_id": manifest.run_id,
            "session_date": session_date,
            "invocation_started_at": started_at,
            "invocation_completed_at": completed_at,
            "invocation_identity": soak_module._identity(
                "SoakInvocation",
                {
                    "run_id": manifest.run_id,
                    "session_date": session_date.isoformat(),
                    "started_at": soak_module._time(started_at),
                    "completed_at": soak_module._time(completed_at),
                    "recovery_id": _hex(f"recovery:{session_date}"),
                    "reconciliation_id": _hex(f"reconciliation:{session_date}"),
                    "execution_report_id": _hex(f"report:{session_date}"),
                    **_runtime_ids(manifest),
                },
            ),
            "recovery_id": _hex(f"recovery:{session_date}"),
            "reconciliation_id": _hex(f"reconciliation:{session_date}"),
            "execution_report_id": _hex(f"report:{session_date}"),
            "gate_passed": not issue_codes,
            "command_ids_sha256": _hex(f"commands:{session_date}"),
            "event_ids_sha256": _hex(f"events:{session_date}"),
            "ledger_state_id": None,
            "issue_codes": issue_codes,
            "facts_sha256": _hex(f"facts:{session_date}"),
        }
        receipt_id = soak_module._identity(
            "SoakSessionReceipt", soak_module._session_payload_values(values)
        )
        sessions.append(
            soak_module.SoakSessionReceipt(receipt_id=receipt_id, **values)
        )
    faults = []
    if complete:
        for drill in sorted(manifest.required_fault_drills):
            started_at = sessions[-1].invocation_completed_at + dt.timedelta(minutes=1)
            completed_at = started_at + dt.timedelta(minutes=1)
            values = {
                "schema_version": "m4-fault-drill-v1",
                "run_id": manifest.run_id,
                "drill": drill,
                "started_at": started_at,
                "completed_at": completed_at,
                "before_recovery_id": _hex(f"before:{drill}"),
                "after_recovery_id": _hex(f"after:{drill}"),
                "affected_subject_ids": (),
                "economic_effect_ids_sha256": _hex(f"effects:{drill}"),
                "outcome": "PASS",
                "stable_codes": (),
                "before_facts_sha256": _hex(f"before-facts:{drill}"),
                "after_facts_sha256": _hex(f"after-facts:{drill}"),
            }
            receipt_id = soak_module._identity(
                "FaultDrillReceipt", soak_module._fault_payload_values(values)
            )
            faults.append(
                soak_module.FaultDrillReceipt(receipt_id=receipt_id, **values)
            )
    terminal_anchor_id = _hex(
        f"terminal:{manifest.run_id}:{len(sessions)}:{len(faults)}"
    )
    evidence_id = soak_module._identity(
        "VerifiedSoakEvidence",
        {
            "run_id": manifest.run_id,
            "receipt_ids": tuple(item.receipt_id for item in sessions),
            "fault_receipt_ids": tuple(item.receipt_id for item in faults),
            "terminal_anchor_id": terminal_anchor_id,
        },
    )
    return soak_module.VerifiedPaperSoakEvidence(
        evidence_id,
        manifest,
        tuple(sessions),
        tuple(faults),
        terminal_anchor_id,
    )


def test_development_identity_path_and_manifest_are_unmistakable(tmp_path: Path) -> None:
    root = tmp_path / "artifacts" / "development_example" / "m4_p8"
    sessions = (dt.date(2026, 8, 3), dt.date(2026, 8, 4))
    first = _manifest(root, sessions)
    second = _manifest(root, sessions)

    assert first == second
    assert first.evidence_kind is SoakEvidenceKind.DEVELOPMENT_EXAMPLE
    assert not first.formal_gate_eligible
    path = root / first.run_id / "manifest.json"
    payload = path.read_bytes()
    decoded = json.loads(payload)
    assert decoded["evidence_kind"] == "development_example"
    assert decoded["formal_gate_eligible"] is False
    assert str(root).encode() not in payload
    assert b"account:irreversible" not in payload


def test_session_recomputes_closure_summaries_and_is_append_only(tmp_path: Path) -> None:
    root = _dev_root(tmp_path, "development")
    date = dt.date(2026, 8, 3)
    manifest = _manifest(root, (date,))
    as_of = dt.datetime(2026, 8, 3, 8, tzinfo=UTC)
    facts = _facts(tmp_path, as_of, "append")
    start = as_of + dt.timedelta(minutes=1)

    first = _append(root, manifest, date, start, facts)
    second = _append(root, manifest, date, start, facts)
    assert first == second
    assert first.gate_passed and not first.issue_codes
    assert first.command_ids_sha256 == first.event_ids_sha256
    assert first.ledger_state_id is None

    with pytest.raises(SoakError, match="^SOAK_APPEND_CONFLICT$") as error:
        _append(root, manifest, date, start + dt.timedelta(seconds=1), facts)
    assert error.value.__cause__ is None and error.value.__context__ is None


def test_each_session_rejects_source_config_gateway_store_or_account_drift(
    tmp_path: Path,
) -> None:
    date = dt.date(2026, 8, 3)
    as_of = dt.datetime(2026, 8, 3, 8, tzinfo=UTC)
    facts = _facts(tmp_path, as_of, "identity-drift")
    for field in (
        "source_identity",
        "config_identity",
        "gateway_identity",
        "store_identity",
        "account_identity",
    ):
        root = _dev_root(tmp_path, field)
        manifest = _manifest(root, (date,))
        identities = _runtime_ids(manifest)
        identities[field] = _hex("drift:" + field)
        with pytest.raises(SoakError, match="^SOAK_SESSION_INVALID$"):
            append_soak_session(
                root=root,
                anchor_root=_anchor_root(root),
                manifest=manifest,
                session_date=date,
                invocation_started_at=as_of,
                invocation_completed_at=as_of + dt.timedelta(minutes=1),
                **identities,
                recovery=facts[0],
                reconciliation=facts[1],
                execution_report=facts[2],
            )


def test_filled_session_recomputes_command_event_and_ledger_summaries(
    tmp_path: Path,
) -> None:
    root = _dev_root(tmp_path, "filled")
    date = dt.date(2026, 8, 3)
    observed = dt.datetime(2026, 8, 3, 8, tzinfo=UTC)
    manifest = _manifest(root, (date,))
    recovery, reconciliation, _ = _filled_inputs(tmp_path)
    report = build_execution_report(
        recovery=recovery,
        reconciliation=reconciliation,
        as_of=reconciliation.as_of,
    )
    receipt = _append(
        root, manifest, date, observed, (recovery, reconciliation, report)
    )
    assert receipt.gate_passed
    assert receipt.command_ids_sha256 != receipt.event_ids_sha256
    assert receipt.ledger_state_id == recovery.checkpoint.state_id  # type: ignore[union-attr]
    verified = verify_soak_evidence(
        root=root, anchor_root=_anchor_root(root), manifest=manifest
    )
    assert verified.sessions == (receipt,)
    facts_path = root / manifest.run_id / "sessions" / date.isoformat() / "facts.json"
    retained = json.loads(facts_path.read_bytes())["recovery"]
    assert retained["schema_version"] == "m4-soak-recovery-facts-v2"
    assert len(retained["risk_receipts"]) == len(recovery.risk_receipts) == 1


@pytest.mark.parametrize("mutation", ["missing", "extra", "receipt_bytes"])
def test_retained_risk_receipt_schema_and_bytes_are_exact(
    tmp_path: Path, mutation: str
) -> None:
    recovery, _, _ = _filled_inputs(tmp_path)
    raw = json.loads(
        soak_module._encode_recovery_facts(
            recovery, schema=soak_module._RECOVERY_FACTS_SCHEMA
        )
    )
    if mutation == "missing":
        raw.pop("risk_receipts")
    elif mutation == "extra":
        raw["legacy_risk_decisions"] = []
    else:
        wire = json.loads(bytes.fromhex(raw["risk_receipts"][0]))
        wire["receipt_id"] = "f" * 64
        raw["risk_receipts"][0] = soak_module._canonical(wire).hex()
    with pytest.raises((ValueError, soak_module.SoakError)):
        soak_module._decode_recovery_facts(
            raw, schema=soak_module._RECOVERY_FACTS_SCHEMA
        )


def test_sessions_must_follow_verified_schedule_and_monotonic_time(tmp_path: Path) -> None:
    root = _dev_root(tmp_path, "schedule")
    dates = (dt.date(2026, 8, 3), dt.date(2026, 8, 4))
    manifest = _manifest(root, dates)
    first_time = dt.datetime(2026, 8, 3, 9, tzinfo=UTC)
    second_time = dt.datetime(2026, 8, 4, 9, tzinfo=UTC)
    first_facts = _facts(tmp_path, first_time, "schedule-first")
    second_facts = _facts(tmp_path, second_time, "schedule-second")

    with pytest.raises(SoakError, match="^SOAK_SESSION_INVALID$"):
        _append(root, manifest, dates[1], second_time, second_facts)
    _append(root, manifest, dates[0], first_time, first_facts)
    with pytest.raises(SoakError, match="^SOAK_SESSION_INVALID$"):
        _append(root, manifest, dates[1], first_time, second_facts)
    _append(root, manifest, dates[1], second_time, second_facts)


def test_forged_p5_or_p7_identity_fails_closed_without_context(tmp_path: Path) -> None:
    root = _dev_root(tmp_path, "hostile")
    date = dt.date(2026, 8, 3)
    manifest = _manifest(root, (date,))
    as_of = dt.datetime(2026, 8, 3, 8, tzinfo=UTC)
    recovery, reconciliation, report = _facts(tmp_path, as_of, "hostile")
    forged = replace(recovery)
    object.__setattr__(forged, "recovery_id", "f" * 64)

    with pytest.raises(SoakError, match="^SOAK_SESSION_INVALID$") as error:
        append_soak_session(
            root=root,
            anchor_root=_anchor_root(root),
            manifest=manifest,
            session_date=date,
            invocation_started_at=as_of + dt.timedelta(minutes=1),
            invocation_completed_at=as_of + dt.timedelta(minutes=2),
            **_runtime_ids(manifest),
            recovery=forged,
            reconciliation=reconciliation,
            execution_report=report,
        )
    assert error.value.__cause__ is None and error.value.__context__ is None


def test_fault_outcome_is_recomputed_not_supplied(tmp_path: Path) -> None:
    root = _dev_root(tmp_path, "fault")
    date = dt.date(2026, 8, 3)
    started = dt.datetime(2026, 8, 3, 8, tzinfo=UTC)
    manifest = _manifest(root, (date,))
    recovery, _, _ = _facts(tmp_path, started, "fault")

    duplicate = append_fault_drill(
        root=root,
        anchor_root=_anchor_root(root),
        manifest=manifest,
        drill="duplicate_callback_idempotent",
        started_at=started,
        completed_at=started + dt.timedelta(minutes=1),
        **_runtime_ids(manifest),
        before_recovery=recovery,
        after_recovery=recovery,
        affected_subject_ids=(),
    )
    assert duplicate.outcome == "PASS"
    assert not duplicate.stable_codes

    exact_submit = append_fault_drill(
        root=root,
        anchor_root=_anchor_root(root),
        manifest=manifest,
        drill="stage_exit_recovery_exact_submit",
        started_at=started,
        completed_at=started + dt.timedelta(minutes=1),
        **_runtime_ids(manifest),
        before_recovery=recovery,
        after_recovery=recovery,
        affected_subject_ids=(),
    )
    assert exact_submit.outcome == "BLOCKED"
    assert exact_submit.stable_codes == ("SOAK_DRILL_EXACT_SUBMIT_NOT_PROVEN",)

    pass_root = _dev_root(tmp_path, "fault-pass")
    pass_manifest = _manifest(pass_root, (date,))
    filled_recovery, _, _ = _filled_inputs(tmp_path)
    proven = append_fault_drill(
        root=pass_root,
        anchor_root=_anchor_root(pass_root),
        manifest=pass_manifest,
        drill="stage_exit_recovery_exact_submit",
        started_at=started,
        completed_at=started + dt.timedelta(minutes=1),
        **_runtime_ids(pass_manifest),
        before_recovery=recovery,
        after_recovery=filled_recovery,
        affected_subject_ids=tuple(
            item.command_id for item in filled_recovery.commands
        ),
    )
    assert proven.outcome == "PASS"
    assert proven.economic_effect_ids_sha256 != duplicate.economic_effect_ids_sha256
    assert verify_soak_evidence(
        root=root, anchor_root=_anchor_root(root), manifest=manifest
    ).fault_drills == (
        duplicate,
        exact_submit,
    )
    assert verify_soak_evidence(
        root=pass_root,
        anchor_root=_anchor_root(pass_root),
        manifest=pass_manifest,
    ).fault_drills == (proven,)


def test_development_evidence_never_returns_pass(tmp_path: Path) -> None:
    root = _dev_root(tmp_path, "dev-gate")
    dates = (dt.date(2026, 8, 3), dt.date(2026, 9, 1))
    started = dt.datetime(2026, 8, 2, 8, tzinfo=UTC)
    manifest = _manifest(root, dates, started_at=started)
    first_time = dt.datetime(2026, 8, 3, 8, tzinfo=UTC)
    last_time = dt.datetime(2026, 9, 1, 8, tzinfo=UTC)
    _append(root, manifest, dates[0], first_time, _facts(tmp_path, first_time, "dev-1"))
    _append(root, manifest, dates[1], last_time, _facts(tmp_path, last_time, "dev-2"))

    verified = verify_soak_evidence(
        root=root, anchor_root=_anchor_root(root), manifest=manifest
    )
    decision = decide_soak_gate(
        verified, root=root, anchor_root=_anchor_root(root), as_of=last_time + DAY
    )
    assert decision.status == "WAITING_FOR_SOAK_EVIDENCE"
    assert "SOAK_DEVELOPMENT_NOT_GATE_ELIGIBLE" in decision.stable_codes
    assert not decision.missing_sessions
    assert decision.last_observed_at is not None
    assert decision.first_observed_at is not None
    assert decision.last_observed_at - decision.first_observed_at >= dt.timedelta(days=28)


def test_formal_empty_session_order_closure_uses_canonical_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§10 supersede: true zero-command + no orphan ORDER is Zero success, not MISSING."""
    root = (tmp_path / "explicit-formal-root").resolve()
    started = dt.datetime(2026, 8, 9, 8, tzinfo=UTC)
    date = started.date()
    clock = [started]
    monkeypatch.setattr(soak_module, "_production_utc_now", lambda: clock[0])
    manifest = _manifest(
        root,
        (date,),
        kind=SoakEvidenceKind.PAPER_REAL_TIME,
        started_at=started,
    )
    observed = started
    clock[0] = observed + dt.timedelta(minutes=3)
    facts = _facts(tmp_path, observed, "formal")
    zero = soak_module.session_order_semantic_closure_identity(
        facts[0], session_date=date
    )
    assert len(zero) == 64
    _append(root, manifest, date, observed, facts)

    verified = verify_soak_evidence(
        root=root, anchor_root=_anchor_root(root), manifest=manifest
    )
    decision = decide_soak_gate(
        verified, root=root, anchor_root=_anchor_root(root), as_of=clock[0]
    )
    assert "SOAK_SESSION_ORDER_RECEIPT_MISSING" not in verified.sessions[0].issue_codes
    assert "SOAK_SESSION_ORDER_RECEIPT_INVALID" not in verified.sessions[0].issue_codes
    assert "SOAK_SESSION_BLOCKED" not in decision.stable_codes
    assert decision.status == "WAITING_FOR_SOAK_EVIDENCE"


def test_orphan_order_receipt_for_session_without_commands_is_invalid(
    tmp_path: Path,
) -> None:
    from decimal import Decimal

    import quant.execution.reconcile as reconcile_module
    import quant.execution.risk_wire as risk_wire
    from quant.execution.risk import DailyRiskCounters
    from quant.execution.risk_wire import DurableOrderRiskDecision

    recovery, _, _ = _filled_inputs(tmp_path)
    command_date = recovery.commands[0].intent.session_date
    orphan_date = command_date + DAY
    old = recovery.risk_receipts[0]
    decision = old.decision
    assert type(decision) is DurableOrderRiskDecision
    new_decision = replace(
        decision,
        projected_counters=replace(
            decision.projected_counters, session_date=orphan_date
        ),
    )
    new_receipt = risk_wire._build(
        kind="ORDER",
        sequence=old.sequence,
        previous_receipt_id=old.previous_receipt_id,
        subject_id=old.subject_id,
        risk_counter_key=old.risk_counter_key,
        predecessor_counters=DailyRiskCounters(
            session_date=orphan_date,
            order_count=0,
            cancel_count=0,
            buy_notional=Decimal(0),
        ),
        decision=new_decision,
    )
    object.__setattr__(recovery, "risk_receipts", (new_receipt,))
    object.__setattr__(
        recovery, "recovery_id", reconcile_module._recovery_identity(recovery)
    )
    with pytest.raises(SoakError, match="^SOAK_SESSION_ORDER_RECEIPT_INVALID$"):
        soak_module.session_order_semantic_closure_identity(
            recovery, session_date=orphan_date
        )


def test_nonzero_session_commands_without_order_receipts_are_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recovery, _, _ = _filled_inputs(tmp_path)
    session_date = recovery.commands[0].intent.session_date
    stripped = RecoveryResult.__new__(RecoveryResult)
    for name in recovery.__dataclass_fields__:
        value = () if name == "risk_receipts" else getattr(recovery, name)
        object.__setattr__(stripped, name, value)
    monkeypatch.setattr(soak_module, "_prove_recovery", lambda value: value)
    monkeypatch.setattr(
        soak_module, "verify_risk_receipt_semantic_closure", lambda **kwargs: None
    )
    with pytest.raises(SoakError, match="^SOAK_SESSION_ORDER_RECEIPT_MISSING$"):
        soak_module.session_order_semantic_closure_identity(
            stripped, session_date=session_date
        )


def test_windows_scope_manifest_wait_block_and_complete_decisions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = (tmp_path / "explicit-windows-formal-root").resolve()
    started = dt.datetime(2026, 8, 1, 8, tzinfo=UTC)
    dates = (dt.date(2026, 8, 2), dt.date(2026, 8, 31))
    clock = [started]
    monkeypatch.setattr(soak_module, "_production_utc_now", lambda: clock[0])
    manifest = _manifest(
        root,
        dates,
        kind=SoakEvidenceKind.PAPER_REAL_TIME_WINDOWS,
        started_at=started,
    )
    assert manifest.evidence_kind is SoakEvidenceKind.PAPER_REAL_TIME_WINDOWS
    assert manifest.formal_gate_eligible is False
    assert json.loads((root / manifest.run_id / "manifest.json").read_bytes())[
        "evidence_kind"
    ] == "paper_real_time_windows"

    incomplete = _paper_decision_evidence(manifest, complete=False)
    monkeypatch.setattr(soak_module, "verify_soak_evidence", lambda **kwargs: incomplete)
    clock[0] = incomplete.sessions[-1].invocation_completed_at
    waiting = decide_soak_gate(
        incomplete,
        root=root,
        anchor_root=_anchor_root(root),
        as_of=clock[0],
    )
    assert waiting.status == "WAITING_FOR_SOAK_EVIDENCE"
    assert "SOAK_WINDOWS_NOT_FORMAL_GATE_ELIGIBLE" in waiting.stable_codes

    complete = _paper_decision_evidence(manifest, complete=True)
    monkeypatch.setattr(soak_module, "verify_soak_evidence", lambda **kwargs: complete)
    clock[0] = complete.sessions[-1].invocation_completed_at
    passed = decide_soak_gate(
        complete,
        root=root,
        anchor_root=_anchor_root(root),
        as_of=clock[0],
    )
    assert passed.status == "PASS_WINDOWS_SCOPE"
    assert passed.stable_codes == ("SOAK_WINDOWS_NOT_FORMAL_GATE_ELIGIBLE",)

    blocked_evidence = _paper_decision_evidence(
        manifest, complete=True, blocked=True
    )
    monkeypatch.setattr(
        soak_module, "verify_soak_evidence", lambda **kwargs: blocked_evidence
    )
    blocked = decide_soak_gate(
        blocked_evidence,
        root=root,
        anchor_root=_anchor_root(root),
        as_of=clock[0],
    )
    assert blocked.status == "BLOCKED"
    assert blocked.stable_codes == (
        "SOAK_SESSION_BLOCKED",
        "SOAK_WINDOWS_NOT_FORMAL_GATE_ELIGIBLE",
    )

    forged = replace(passed, status="PASS")
    values = {
        field: getattr(forged, field)
        for field in forged.__dataclass_fields__
        if field != "decision_id"
    }
    forged = replace(
        forged,
        decision_id=soak_module._identity(
            "SoakGateDecision", soak_module._decision_payload_values(values)
        ),
    )
    with pytest.raises(ValueError):
        soak_module._prove_gate_decision(forged, manifest)


def test_windows_manifest_rejects_rehashed_formal_eligibility_forgery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = dt.datetime(2026, 8, 16, 0, tzinfo=UTC)
    monkeypatch.setattr(soak_module, "_production_utc_now", lambda: now)
    root = (tmp_path / "windows-eligibility-forgery").resolve()
    manifest = _manifest(
        root,
        (now.date(),),
        kind=SoakEvidenceKind.PAPER_REAL_TIME_WINDOWS,
        started_at=now,
    )
    forged = replace(manifest, formal_gate_eligible=True)
    values = {
        field: getattr(forged, field)
        for field in forged.__dataclass_fields__
        if field != "run_id"
    }
    forged = replace(
        forged,
        run_id=soak_module._identity(
            "SoakRunManifest", soak_module._manifest_payload_values(values)
        ),
    )

    with pytest.raises(ValueError):
        soak_module._prove_manifest(forged)


def test_linux_complete_decision_remains_exact_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = (tmp_path / "linux-formal-complete").resolve()
    started = dt.datetime(2026, 8, 1, 8, tzinfo=UTC)
    dates = (dt.date(2026, 8, 2), dt.date(2026, 8, 31))
    clock = [started]
    monkeypatch.setattr(soak_module, "_production_utc_now", lambda: clock[0])
    manifest = _manifest(
        root,
        dates,
        kind=SoakEvidenceKind.PAPER_REAL_TIME,
        started_at=started,
    )
    complete = _paper_decision_evidence(manifest, complete=True)
    monkeypatch.setattr(soak_module, "verify_soak_evidence", lambda **kwargs: complete)
    clock[0] = complete.sessions[-1].invocation_completed_at

    decision = decide_soak_gate(
        complete,
        root=root,
        anchor_root=_anchor_root(root),
        as_of=clock[0],
    )

    assert manifest.formal_gate_eligible is True
    assert decision.status == "PASS"
    assert decision.stable_codes == ()


def test_corrupt_or_rehashed_receipt_is_rejected(tmp_path: Path) -> None:
    root = _dev_root(tmp_path, "corrupt")
    date = dt.date(2026, 8, 3)
    observed = dt.datetime(2026, 8, 3, 8, tzinfo=UTC)
    manifest = _manifest(root, (date,))
    receipt = _append(root, manifest, date, observed, _facts(tmp_path, observed, "corrupt"))
    path = root / manifest.run_id / "sessions" / date.isoformat() / "receipt.json"
    forged = replace(receipt, invocation_identity="f" * 64)
    values = {
        name: getattr(forged, name) for name in soak_module._SESSION_FIELDS
    }
    forged = replace(
        forged,
        receipt_id=soak_module._identity(
            "SoakSessionReceipt", soak_module._session_payload_values(values)
        ),
    )
    path.write_bytes(soak_module._encode_session(forged))

    with pytest.raises(SoakError, match="^SOAK_EVIDENCE_INVALID$") as error:
        verify_soak_evidence(
            root=root, anchor_root=_anchor_root(root), manifest=manifest
        )
    assert error.value.__cause__ is None and error.value.__context__ is None
    assert receipt.receipt_id != forged.receipt_id


def test_unexpected_receipt_entry_is_not_silently_ignored(tmp_path: Path) -> None:
    root = _dev_root(tmp_path, "unexpected")
    date = dt.date(2026, 8, 3)
    manifest = _manifest(root, (date,))
    run_dir = root / manifest.run_id
    rogue = run_dir / "sessions" / "2099-01-01"
    rogue.parent.mkdir(parents=True, exist_ok=True)
    rogue.write_bytes(b"{}")

    with pytest.raises(SoakError, match="^SOAK_EVIDENCE_INVALID$"):
        verify_soak_evidence(
            root=root, anchor_root=_anchor_root(root), manifest=manifest
        )


def test_non_utc_and_hostile_schedule_inputs_are_stably_rejected(tmp_path: Path) -> None:
    root = _dev_root(tmp_path, "invalid")
    dates = (dt.date(2026, 8, 3),)
    with pytest.raises(SoakError, match="^SOAK_RUN_INVALID$") as error:
        build_soak_run(
            root=root,
            anchor_root=_anchor_root(root),
            evidence_kind=SoakEvidenceKind.DEVELOPMENT_EXAMPLE,
            source_identity=_hex("TOKEN C:/private"),
            config_identity=_hex("config"),
            gateway_identity=_hex("gateway"),
            store_identity=_hex("store"),
            account_identity=_hex("account"),
            expected_sessions=dates,
            expected_schedule_identity="f" * 64,
            started_at=dt.datetime(2026, 8, 2, 8),
        )
    assert error.value.__cause__ is None and error.value.__context__ is None
    assert "TOKEN" not in str(error.value) and "private" not in str(error.value)


def test_recovery_type_is_exact_not_subclass(tmp_path: Path) -> None:
    root = _dev_root(tmp_path, "exact-type")
    date = dt.date(2026, 8, 3)
    manifest = _manifest(root, (date,))
    as_of = dt.datetime(2026, 8, 3, 8, tzinfo=UTC)
    recovery, reconciliation, report = _facts(tmp_path, as_of, "exact-type")

    class HostileRecovery(RecoveryResult):
        pass

    hostile = HostileRecovery(
        recovery.recovery_id,
        recovery.disposition,
        recovery.commands,
        recovery.events,
        recovery.order_aggregates,
        recovery.deliveries,
        recovery.cancel_commands,
        recovery.cancel_deliveries,
        recovery.cancel_event_links,
        recovery.ledger_entries,
        recovery.ledger_contexts,
        recovery.checkpoint,
        recovery.issues,
    )
    with pytest.raises(SoakError, match="^SOAK_SESSION_INVALID$"):
        append_soak_session(
            root=root,
            anchor_root=_anchor_root(root),
            manifest=manifest,
            session_date=date,
            invocation_started_at=as_of,
            invocation_completed_at=as_of + dt.timedelta(minutes=1),
            **_runtime_ids(manifest),
            recovery=hostile,
            reconciliation=reconciliation,
            execution_report=report,
        )


def test_linux_formal_clock_rejects_backdated_single_process_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = dt.datetime(2026, 8, 9, 8, tzinfo=UTC)
    monkeypatch.setattr(soak_module, "_production_utc_now", lambda: now)
    root = (tmp_path / "formal-clock").resolve()
    dates = (dt.date(2026, 8, 3), dt.date(2026, 9, 1))
    with pytest.raises(SoakError, match="^SOAK_RUN_INVALID$") as error:
        _manifest(
            root,
            dates,
            kind=SoakEvidenceKind.PAPER_REAL_TIME,
            started_at=now - dt.timedelta(days=29),
        )
    assert error.value.__cause__ is None and error.value.__context__ is None


def test_exact_persisted_formal_manifest_reopens_after_clock_advance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started = dt.datetime(2026, 8, 9, 8, tzinfo=UTC)
    clock = [started]
    monkeypatch.setattr(soak_module, "_production_utc_now", lambda: clock[0])
    root = (tmp_path / "formal-manifest-reopen").resolve()
    manifest = _manifest(
        root,
        (started.date(),),
        kind=SoakEvidenceKind.PAPER_REAL_TIME_WINDOWS,
        started_at=started,
    )

    clock[0] = started + dt.timedelta(days=7)
    reopened = _manifest(
        root,
        (started.date(),),
        kind=SoakEvidenceKind.PAPER_REAL_TIME_WINDOWS,
        started_at=started,
    )

    assert reopened == manifest


def test_session_order_receipt_identity_rejects_old_date(tmp_path: Path) -> None:
    recovery, _, _ = _filled_inputs(tmp_path)
    session_date = recovery.commands[0].intent.session_date

    identity = soak_module._session_order_semantic_closure_identity(
        recovery, session_date=session_date
    )
    assert len(identity) == 64
    # Different session_date with no commands and no orphan ORDER receipts yields
    # the package-owned zero-command identity (distinct from the nonzero digest).
    zero = soak_module.session_order_semantic_closure_identity(
        recovery, session_date=session_date + DAY
    )
    assert len(zero) == 64
    assert zero != identity


def test_session_order_zero_command_identity_is_package_owned_ssot(
    tmp_path: Path,
) -> None:
    recovery, _, _ = _filled_inputs(tmp_path)
    session_date = recovery.commands[0].intent.session_date + DAY
    public = soak_module.session_order_semantic_closure_identity(
        recovery, session_date=session_date
    )
    private = soak_module._session_order_semantic_closure_identity(
        recovery, session_date=session_date
    )
    assert public == private
    assert len(public) == 64
    assert "soak-runtime-zero-order-closure-v1" not in inspect.getsource(soak_module)
    assert "SoakSessionOrderSemanticClosureZero" in inspect.getsource(soak_module)


def test_manifest_is_bound_to_original_physical_root(tmp_path: Path) -> None:
    date = dt.date(2026, 8, 3)
    source_root = _dev_root(tmp_path, "source-root")
    manifest = _manifest(source_root, (date,))
    observed = dt.datetime(2026, 8, 3, 8, tzinfo=UTC)
    _append(source_root, manifest, date, observed, _facts(tmp_path, observed, "copy"))
    target_root = _dev_root(tmp_path, "target-root")
    shutil.copytree(source_root, target_root)

    with pytest.raises(SoakError, match="^SOAK_EVIDENCE_INVALID$") as error:
        verify_soak_evidence(
            root=target_root,
            anchor_root=_anchor_root(source_root),
            manifest=manifest,
        )
    assert error.value.__cause__ is None and error.value.__context__ is None


def test_facts_only_and_receipt_plus_facts_whole_rehash_fail_closed(
    tmp_path: Path,
) -> None:
    date = dt.date(2026, 8, 3)
    observed = dt.datetime(2026, 8, 3, 8, tzinfo=UTC)

    facts_root = _dev_root(tmp_path, "facts-only")
    facts_manifest = _manifest(facts_root, (date,))
    _append(
        facts_root,
        facts_manifest,
        date,
        observed,
        _facts(tmp_path, observed, "facts-only"),
    )
    facts_path = facts_root / facts_manifest.run_id / "sessions" / date.isoformat() / "facts.json"
    facts_raw = json.loads(facts_path.read_bytes())
    facts_raw["recovery"]["recovery_id"] = "f" * 64
    facts_path.write_bytes(soak_module._canonical(facts_raw))
    with pytest.raises(SoakError, match="^SOAK_EVIDENCE_INVALID$"):
        verify_soak_evidence(
            root=facts_root,
            anchor_root=_anchor_root(facts_root),
            manifest=facts_manifest,
        )

    whole_root = _dev_root(tmp_path, "whole-rehash")
    whole_manifest = _manifest(whole_root, (date,))
    receipt = _append(
        whole_root,
        whole_manifest,
        date,
        observed,
        _facts(tmp_path, observed, "whole-rehash"),
    )
    session_dir = whole_root / whole_manifest.run_id / "sessions" / date.isoformat()
    facts_raw = json.loads((session_dir / "facts.json").read_bytes())
    facts_raw["recovery"]["recovery_id"] = "e" * 64
    encoded_facts = soak_module._canonical(facts_raw)
    (session_dir / "facts.json").write_bytes(encoded_facts)
    forged = replace(
        receipt,
        recovery_id="e" * 64,
        facts_sha256=hashlib.sha256(encoded_facts).hexdigest(),
    )
    invocation = soak_module._identity(
        "SoakInvocation",
        {
            "run_id": forged.run_id,
            "session_date": forged.session_date.isoformat(),
            "started_at": soak_module._time(forged.invocation_started_at),
            "completed_at": soak_module._time(forged.invocation_completed_at),
            "recovery_id": forged.recovery_id,
            "reconciliation_id": forged.reconciliation_id,
            "execution_report_id": forged.execution_report_id,
            **_runtime_ids(whole_manifest),
        },
    )
    forged = replace(forged, invocation_identity=invocation)
    values = {name: getattr(forged, name) for name in soak_module._SESSION_FIELDS}
    forged = replace(
        forged,
        receipt_id=soak_module._identity(
            "SoakSessionReceipt", soak_module._session_payload_values(values)
        ),
    )
    (session_dir / "receipt.json").write_bytes(soak_module._encode_session(forged))
    with pytest.raises(SoakError, match="^SOAK_EVIDENCE_INVALID$") as error:
        verify_soak_evidence(
            root=whole_root,
            anchor_root=_anchor_root(whole_root),
            manifest=whole_manifest,
        )
    assert error.value.__cause__ is None and error.value.__context__ is None


@pytest.mark.parametrize("mutation", ["missing", "extra", "swapped"])
def test_session_sidecar_exact_set_is_enforced(tmp_path: Path, mutation: str) -> None:
    date = dt.date(2026, 8, 3)
    observed = dt.datetime(2026, 8, 3, 8, tzinfo=UTC)
    root = _dev_root(tmp_path, "sidecar-" + mutation)
    manifest = _manifest(root, (date,))
    _append(root, manifest, date, observed, _facts(tmp_path, observed, mutation))
    session_dir = root / manifest.run_id / "sessions" / date.isoformat()
    if mutation == "missing":
        (session_dir / "facts.json").unlink()
    elif mutation == "extra":
        (session_dir / "unknown.json").write_bytes(b"{}")
    else:
        receipt = (session_dir / "receipt.json").read_bytes()
        facts = (session_dir / "facts.json").read_bytes()
        (session_dir / "receipt.json").write_bytes(facts)
        (session_dir / "facts.json").write_bytes(receipt)
    with pytest.raises(SoakError, match="^SOAK_EVIDENCE_INVALID$"):
        verify_soak_evidence(
            root=root, anchor_root=_anchor_root(root), manifest=manifest
        )


@pytest.mark.parametrize("mutation", ["missing", "extra", "swapped"])
def test_fault_sidecar_exact_set_is_enforced(tmp_path: Path, mutation: str) -> None:
    date = dt.date(2026, 8, 3)
    observed = dt.datetime(2026, 8, 3, 8, tzinfo=UTC)
    root = _dev_root(tmp_path, "fault-sidecar-" + mutation)
    manifest = _manifest(root, (date,))
    recovery, _, _ = _facts(tmp_path, observed, mutation)
    append_fault_drill(
        root=root,
        anchor_root=_anchor_root(root),
        manifest=manifest,
        drill="duplicate_callback_idempotent",
        started_at=observed,
        completed_at=observed + dt.timedelta(minutes=1),
        **_runtime_ids(manifest),
        before_recovery=recovery,
        after_recovery=recovery,
        affected_subject_ids=(),
    )
    fault_dir = root / manifest.run_id / "faults" / "duplicate_callback_idempotent"
    if mutation == "missing":
        (fault_dir / "before_facts.json").unlink()
    elif mutation == "extra":
        (fault_dir / "unknown.json").write_bytes(b"{}")
    else:
        before = (fault_dir / "before_facts.json").read_bytes()
        after = (fault_dir / "after_facts.json").read_bytes()
        (fault_dir / "before_facts.json").write_bytes(after + b" ")
        (fault_dir / "after_facts.json").write_bytes(before)
    with pytest.raises(SoakError, match="^SOAK_EVIDENCE_INVALID$"):
        verify_soak_evidence(
            root=root, anchor_root=_anchor_root(root), manifest=manifest
        )


@pytest.mark.parametrize("mutation", ["event_link", "ledger_wire", "report_wire"])
def test_retained_semantic_wire_drift_fails_after_whole_rehash(
    tmp_path: Path, mutation: str
) -> None:
    root = _dev_root(tmp_path, "semantic-" + mutation)
    date = dt.date(2026, 8, 3)
    observed = dt.datetime(2026, 8, 3, 8, tzinfo=UTC)
    manifest = _manifest(root, (date,))
    recovery, reconciliation, _ = _filled_inputs(tmp_path)
    report = build_execution_report(
        recovery=recovery,
        reconciliation=reconciliation,
        as_of=reconciliation.as_of,
    )
    receipt = _append(root, manifest, date, observed, (recovery, reconciliation, report))
    session_dir = root / manifest.run_id / "sessions" / date.isoformat()
    facts = json.loads((session_dir / "facts.json").read_bytes())
    forged_report_id = receipt.execution_report_id
    if mutation == "event_link":
        wire = json.loads(bytes.fromhex(facts["recovery"]["events"][0]))
        wire["command_id"] = "f" * 64
        facts["recovery"]["events"][0] = soak_module._canonical(wire).hex()
    elif mutation == "ledger_wire":
        wire = json.loads(bytes.fromhex(facts["recovery"]["ledger_entries"][0]))
        wire["entry_id"] = "f" * 64
        facts["recovery"]["ledger_entries"][0] = soak_module._canonical(wire).hex()
    else:
        wire = json.loads(bytes.fromhex(facts["execution_report_wire"]))
        wire["totals"]["commands"] += 1
        payload = {key: value for key, value in wire.items() if key != "report_id"}
        forged_report_id = hashlib.sha256(soak_module._canonical(payload)).hexdigest()
        wire["report_id"] = forged_report_id
        facts["execution_report_wire"] = soak_module._canonical(wire).hex()
    encoded_facts = soak_module._canonical(facts)
    (session_dir / "facts.json").write_bytes(encoded_facts)
    forged = replace(
        receipt,
        facts_sha256=hashlib.sha256(encoded_facts).hexdigest(),
        execution_report_id=forged_report_id,
    )
    invocation = soak_module._identity(
        "SoakInvocation",
        {
            "run_id": forged.run_id,
            "session_date": forged.session_date.isoformat(),
            "started_at": soak_module._time(forged.invocation_started_at),
            "completed_at": soak_module._time(forged.invocation_completed_at),
            "recovery_id": forged.recovery_id,
            "reconciliation_id": forged.reconciliation_id,
            "execution_report_id": forged.execution_report_id,
            **_runtime_ids(manifest),
        },
    )
    forged = replace(forged, invocation_identity=invocation)
    values = {name: getattr(forged, name) for name in soak_module._SESSION_FIELDS}
    forged = replace(
        forged,
        receipt_id=soak_module._identity(
            "SoakSessionReceipt", soak_module._session_payload_values(values)
        ),
    )
    (session_dir / "receipt.json").write_bytes(soak_module._encode_session(forged))
    with pytest.raises(SoakError, match="^SOAK_EVIDENCE_INVALID$") as error:
        verify_soak_evidence(
            root=root, anchor_root=_anchor_root(root), manifest=manifest
        )
    assert error.value.__cause__ is None and error.value.__context__ is None


def test_independent_anchor_rejects_fully_valid_closure_substitution(
    tmp_path: Path,
) -> None:
    date = dt.date(2026, 8, 3)
    observed = dt.datetime(2026, 8, 3, 8, tzinfo=UTC)
    root = _dev_root(tmp_path, "anchor-original")
    manifest = _manifest(root, (date,))
    original = _append(
        root, manifest, date, observed, _facts(tmp_path, observed, "anchor-empty")
    )
    original_verified = verify_soak_evidence(
        root=root, anchor_root=_anchor_root(root), manifest=manifest
    )

    replacement_root = _dev_root(tmp_path, "anchor-replacement")
    replacement_manifest = _manifest(replacement_root, (date,))
    recovery, reconciliation, _ = _filled_inputs(tmp_path)
    report = build_execution_report(
        recovery=recovery,
        reconciliation=reconciliation,
        as_of=reconciliation.as_of,
    )
    replacement = _append(
        replacement_root,
        replacement_manifest,
        date,
        observed,
        (recovery, reconciliation, report),
    )
    replacement_facts = (
        replacement_root
        / replacement_manifest.run_id
        / "sessions"
        / date.isoformat()
        / "facts.json"
    ).read_bytes()
    forged = _replace_closure_and_rehash_receipt(
        root, manifest, original, replacement, replacement_facts
    )
    assert forged.recovery_id != original.recovery_id

    with pytest.raises(SoakError, match="^SOAK_EVIDENCE_INVALID$") as error:
        verify_soak_evidence(
            root=root, anchor_root=_anchor_root(root), manifest=manifest
        )
    assert error.value.__cause__ is None and error.value.__context__ is None
    with pytest.raises(SoakError, match="^SOAK_APPEND_CONFLICT$"):
        _append(
            root,
            manifest,
            date,
            observed,
            (recovery, reconciliation, report),
        )
    anchor_path = _anchor_dir(root, manifest) / "0000000001.json"
    anchor_raw = json.loads(anchor_path.read_bytes())
    anchor_raw["receipt_id"] = forged.receipt_id
    anchor_raw["facts_digests"] = [forged.facts_sha256]
    values = {name: anchor_raw[name] for name in soak_module._ANCHOR_FIELDS}
    values["facts_digests"] = tuple(values["facts_digests"])
    values["anchored_at"] = soak_module._parse_time(values["anchored_at"])
    anchor_raw["anchor_id"] = soak_module._identity(
        "SoakAppendAnchor", soak_module._anchor_payload_values(values)
    )
    with pytest.raises(SoakError, match="^SOAK_APPEND_CONFLICT$"):
        soak_module._write_once(anchor_path, soak_module._canonical(anchor_raw))
    anchor_path.write_bytes(soak_module._canonical(anchor_raw))
    with pytest.raises(SoakError, match="^SOAK_GATE_INPUT_INVALID$"):
        decide_soak_gate(
            original_verified,
            root=root,
            anchor_root=_anchor_root(root),
            as_of=observed + DAY,
        )


def test_crash_before_anchor_recovers_only_exact_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _dev_root(tmp_path, "anchor-crash")
    date = dt.date(2026, 8, 3)
    observed = dt.datetime(2026, 8, 3, 8, tzinfo=UTC)
    manifest = _manifest(root, (date,))
    facts = _facts(tmp_path, observed, "anchor-crash")
    real_append_anchor = soak_module._append_anchor
    monkeypatch.setattr(
        soak_module,
        "_append_anchor",
        lambda **_: (_ for _ in ()).throw(SoakError("SOAK_APPEND_CONFLICT")),
    )
    with pytest.raises(SoakError, match="^SOAK_APPEND_CONFLICT$"):
        _append(root, manifest, date, observed, facts)
    assert not _anchor_dir(root, manifest).exists()

    monkeypatch.setattr(soak_module, "_append_anchor", real_append_anchor)
    receipt = _append(root, manifest, date, observed, facts)
    assert len(tuple(_anchor_dir(root, manifest).iterdir())) == 1
    assert _append(root, manifest, date, observed, facts) == receipt
    assert len(tuple(_anchor_dir(root, manifest).iterdir())) == 1
    with pytest.raises(SoakError, match="^SOAK_APPEND_CONFLICT$"):
        recovery, reconciliation, _ = _filled_inputs(tmp_path)
        report = build_execution_report(
            recovery=recovery,
            reconciliation=reconciliation,
            as_of=reconciliation.as_of,
        )
        _append(
            root,
            manifest,
            date,
            observed,
            (recovery, reconciliation, report),
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "delete", "extra", "swap", "gap", "predecessor", "digest", "receipt",
        "duplicate_key",
    ],
)
def test_anchor_chain_mutations_fail_closed(tmp_path: Path, mutation: str) -> None:
    root = _dev_root(tmp_path, "anchor-mutation-" + mutation)
    dates = (dt.date(2026, 8, 3), dt.date(2026, 8, 4))
    manifest = _manifest(root, dates)
    for index, date in enumerate(dates):
        observed = dt.datetime.combine(date, dt.time(8), tzinfo=UTC)
        _append(root, manifest, date, observed, _facts(tmp_path, observed, f"anchor-{mutation}-{index}"))
    directory = _anchor_dir(root, manifest)
    first = directory / "0000000001.json"
    second = directory / "0000000002.json"
    if mutation == "delete":
        second.unlink()
    elif mutation == "extra":
        (directory / "0000000003.json").write_bytes(second.read_bytes())
    elif mutation == "swap":
        first_bytes, second_bytes = first.read_bytes(), second.read_bytes()
        first.write_bytes(second_bytes)
        second.write_bytes(first_bytes)
    elif mutation == "gap":
        second.rename(directory / "0000000003.json")
    elif mutation != "duplicate_key":
        raw = json.loads(second.read_bytes())
        if mutation == "predecessor":
            raw["previous_anchor_id"] = "f" * 64
        elif mutation == "receipt":
            raw["receipt_id"] = "f" * 64
        else:
            raw["facts_digests"] = ["f" * 64]
        values = {name: raw[name] for name in soak_module._ANCHOR_FIELDS}
        values["facts_digests"] = tuple(values["facts_digests"])
        values["anchored_at"] = soak_module._parse_time(values["anchored_at"])
        raw["anchor_id"] = soak_module._identity(
            "SoakAppendAnchor", soak_module._anchor_payload_values(values)
        )
        second.write_bytes(soak_module._canonical(raw))
    else:
        first_raw = json.loads(first.read_bytes())
        second_raw = json.loads(second.read_bytes())
        duplicate = dict(first_raw)
        duplicate["sequence"] = 3
        duplicate["previous_anchor_id"] = second_raw["anchor_id"]
        duplicate["anchored_at"] = soak_module._time(
            soak_module._parse_time(second_raw["anchored_at"])
            + dt.timedelta(microseconds=1)
        )
        values = {name: duplicate[name] for name in soak_module._ANCHOR_FIELDS}
        values["facts_digests"] = tuple(values["facts_digests"])
        values["anchored_at"] = soak_module._parse_time(values["anchored_at"])
        duplicate["anchor_id"] = soak_module._identity(
            "SoakAppendAnchor", soak_module._anchor_payload_values(values)
        )
        (directory / "0000000003.json").write_bytes(
            soak_module._canonical(duplicate)
        )
    with pytest.raises(SoakError, match="^SOAK_EVIDENCE_INVALID$") as error:
        verify_soak_evidence(
            root=root, anchor_root=_anchor_root(root), manifest=manifest
        )
    assert error.value.__cause__ is None and error.value.__context__ is None


def test_anchor_root_copy_and_symlink_are_rejected(tmp_path: Path) -> None:
    root = _dev_root(tmp_path, "anchor-copy-source")
    date = dt.date(2026, 8, 3)
    observed = dt.datetime(2026, 8, 3, 8, tzinfo=UTC)
    manifest = _manifest(root, (date,))
    _append(root, manifest, date, observed, _facts(tmp_path, observed, "anchor-copy"))
    copied = (tmp_path / "copied-anchor-root").resolve()
    shutil.copytree(_anchor_root(root), copied)
    with pytest.raises(SoakError, match="^SOAK_EVIDENCE_INVALID$"):
        verify_soak_evidence(root=root, anchor_root=copied, manifest=manifest)

    link = _anchor_dir(root, manifest) / "0000000002.json"
    try:
        link.symlink_to(_anchor_dir(root, manifest) / "0000000001.json")
    except OSError:
        pytest.skip("host does not permit symlink creation")
    with pytest.raises(SoakError, match="^SOAK_EVIDENCE_INVALID$"):
        verify_soak_evidence(
            root=root, anchor_root=_anchor_root(root), manifest=manifest
        )


@pytest.mark.parametrize("relation", ["same", "ancestor", "descendant"])
def test_anchor_root_must_be_an_independent_absolute_domain(
    tmp_path: Path, relation: str
) -> None:
    root = _dev_root(tmp_path, "anchor-relation-" + relation)
    if relation == "same":
        anchor_root = root
    elif relation == "ancestor":
        anchor_root = root.parent
    else:
        anchor_root = root / "anchors"
    dates = (dt.date(2026, 8, 3),)
    with pytest.raises(SoakError, match="^SOAK_RUN_INVALID$") as error:
        build_soak_run(
            root=root,
            anchor_root=anchor_root,
            evidence_kind=SoakEvidenceKind.DEVELOPMENT_EXAMPLE,
            source_identity=_hex("source"),
            config_identity=_hex("config"),
            gateway_identity=_hex("gateway"),
            store_identity=_hex("store"),
            account_identity=_hex("account"),
            expected_sessions=dates,
            expected_schedule_identity=expected_schedule_identity(dates),
            started_at=dt.datetime(2026, 8, 2, 8, tzinfo=UTC),
        )
    assert error.value.__cause__ is None and error.value.__context__ is None


def test_decision_fresh_rejects_disk_drift_and_stale_capability(tmp_path: Path) -> None:
    root = _dev_root(tmp_path, "anchor-toctou")
    date = dt.date(2026, 8, 3)
    observed = dt.datetime(2026, 8, 3, 8, tzinfo=UTC)
    manifest = _manifest(root, (date,))
    recovery, _, _ = _facts(tmp_path, observed, "anchor-toctou")
    _append(root, manifest, date, observed, _facts(tmp_path, observed, "anchor-toctou-session"))
    verified = verify_soak_evidence(
        root=root, anchor_root=_anchor_root(root), manifest=manifest
    )
    append_fault_drill(
        root=root,
        anchor_root=_anchor_root(root),
        manifest=manifest,
        drill="duplicate_callback_idempotent",
        started_at=observed,
        completed_at=observed + dt.timedelta(minutes=1),
        **_runtime_ids(manifest),
        before_recovery=recovery,
        after_recovery=recovery,
        affected_subject_ids=(),
    )
    with pytest.raises(SoakError, match="^SOAK_GATE_INPUT_INVALID$") as error:
        decide_soak_gate(
            verified,
            root=root,
            anchor_root=_anchor_root(root),
            as_of=observed + DAY,
        )
    assert error.value.__cause__ is None and error.value.__context__ is None

    fresh = verify_soak_evidence(
        root=root, anchor_root=_anchor_root(root), manifest=manifest
    )
    (root / manifest.run_id / "sessions" / date.isoformat() / "facts.json").unlink()
    with pytest.raises(SoakError, match="^SOAK_EVIDENCE_INVALID$"):
        decide_soak_gate(
            fresh,
            root=root,
            anchor_root=_anchor_root(root),
            as_of=observed + DAY,
        )

    anchor_root = _dev_root(tmp_path, "anchor-toctou-anchor")
    anchor_manifest = _manifest(anchor_root, (date,))
    _append(
        anchor_root,
        anchor_manifest,
        date,
        observed,
        _facts(tmp_path, observed, "anchor-toctou-anchor"),
    )
    anchor_verified = verify_soak_evidence(
        root=anchor_root,
        anchor_root=_anchor_root(anchor_root),
        manifest=anchor_manifest,
    )
    (_anchor_dir(anchor_root, anchor_manifest) / "0000000001.json").unlink()
    with pytest.raises(SoakError, match="^SOAK_EVIDENCE_INVALID$"):
        decide_soak_gate(
            anchor_verified,
            root=anchor_root,
            anchor_root=_anchor_root(anchor_root),
            as_of=observed + DAY,
        )


def test_concurrent_different_next_anchors_do_not_fork(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _dev_root(tmp_path, "anchor-concurrent")
    date = dt.date(2026, 8, 3)
    observed = dt.datetime(2026, 8, 3, 8, tzinfo=UTC)
    manifest = _manifest(root, (date,))
    recovery, _, _ = _facts(tmp_path, observed, "anchor-concurrent")
    original_read = soak_module._read_anchor_chain
    barrier = threading.Barrier(2)
    calls = 0
    lock = threading.Lock()

    def synchronized_read(anchor_root: Path, checked_manifest):
        nonlocal calls
        result = original_read(anchor_root, checked_manifest)
        with lock:
            calls += 1
            wait = calls <= 2
        if wait:
            barrier.wait(timeout=10)
        return result

    monkeypatch.setattr(soak_module, "_read_anchor_chain", synchronized_read)

    def write(drill: str):
        return append_fault_drill(
            root=root,
            anchor_root=_anchor_root(root),
            manifest=manifest,
            drill=drill,
            started_at=observed,
            completed_at=observed + dt.timedelta(minutes=1),
            **_runtime_ids(manifest),
            before_recovery=recovery,
            after_recovery=recovery,
            affected_subject_ids=(),
        )

    drills = ("duplicate_callback_idempotent", "completed_actions_idempotent")
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(write, drill) for drill in drills]
    outcomes: list[object] = []
    for future in futures:
        try:
            outcomes.append(future.result())
        except SoakError as error:
            outcomes.append(error)
    assert sum(not isinstance(item, SoakError) for item in outcomes) == 1
    failed_index = next(
        index for index, item in enumerate(outcomes) if isinstance(item, SoakError)
    )
    assert str(outcomes[failed_index]) == "SOAK_APPEND_CONFLICT"
    monkeypatch.setattr(soak_module, "_read_anchor_chain", original_read)
    write(drills[failed_index])
    anchors = soak_module._read_anchor_chain(_anchor_root(root), manifest)
    assert tuple(item.sequence for item in anchors) == (1, 2)
    assert len({item.previous_anchor_id for item in anchors[1:]}) == 1
    verify_soak_evidence(
        root=root, anchor_root=_anchor_root(root), manifest=manifest
    )
