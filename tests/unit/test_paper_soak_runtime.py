"""Focused contracts for the minimal Windows PAPER session closer."""

from __future__ import annotations

import datetime as dt
import hashlib
import os
from dataclasses import fields
from pathlib import Path
from types import SimpleNamespace

import pytest

import quant.execution.paper_formal_broker_snapshot as broker_snapshot_module
import quant.execution.reconcile as reconcile_module
import quant.execution.soak as soak_module
import quant.execution.soak_runtime as runtime
from quant.execution.contracts import build_account_snapshot
from quant.execution.paper_formal_schedule import VerifiedFormalPaperSoakSchedule
from quant.execution.paper_formal_service import (
    VerifiedFormalPaperServiceComposition,
)
from quant.execution.paper_policy import VerifiedPaperExecutionPolicy
from quant.execution.paper_runtime import (
    FormalPaperRuntimeConfig,
    VerifiedPaperRuntimeEnvironment,
)
from quant.execution.reconcile import RecoveryIssue, RecoveryResult, recover_local_state
from quant.execution.store import ExecutionStore
from quant.reporting.execution_report import build_execution_report
from tests.unit.test_execution_report import _filled_inputs

UTC = dt.timezone.utc


def _hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class _StoreOpener:
    def __init__(self, store: object) -> None:
        self.store = store

    def open(self) -> object:
        return self.store


class _BrokerStoreProbe:
    def __init__(self, *, account: object, as_of: dt.datetime) -> None:
        self.account = account
        self.as_of = as_of
        self.marker: object | None = None
        self.record_calls = 0
        self.snapshot_calls = 0

    def read_session_finality(self, *, session_date: dt.date) -> object | None:
        del session_date
        return self.marker

    def all_commands(self) -> tuple[object, ...]:
        return ()

    def read_evidence_snapshot(
        self, *, session_date: dt.date
    ) -> tuple[object, tuple[()], tuple[()], dt.datetime, str, str]:
        del session_date
        self.snapshot_calls += 1
        finality = "INTRADAY" if self.marker is None else "END_OF_DAY"
        return (
            self.account,
            (),
            (),
            self.as_of,
            _hex("broker:" + finality),
            finality,
        )

    def record_zero_broker_command_session_finality(
        self,
        *,
        session_date: dt.date,
        finalized_at: dt.datetime,
        order_semantic_closure_identity: str,
    ) -> None:
        self.record_calls += 1
        self.marker = SimpleNamespace(
            schema_version="paper-zero-broker-command-session-finality-v1",
            session_date=session_date,
            finalized_at=finalized_at,
            order_semantic_closure_identity=order_semantic_closure_identity,
        )


class _ReportPort:
    def __init__(self, report: object) -> None:
        self.report = report
        self.calls = 0

    def build(self, **kwargs: object) -> object:
        del kwargs
        self.calls += 1
        return self.report


def _runtime_inputs(tmp_path: Path):  # type: ignore[no-untyped-def]
    recovery, reconciliation, _ = _filled_inputs(tmp_path)
    session_date = recovery.commands[0].intent.session_date
    evidence_as_of = reconciliation.as_of
    now = evidence_as_of + dt.timedelta(minutes=5)
    parent = (tmp_path / "paper-runtime").resolve()
    evidence_root = parent / "evidence"
    anchor_root = parent / "anchor"
    log_root = parent / "log"
    for path in (evidence_root, anchor_root, log_root):
        path.mkdir(parents=True)
    config = FormalPaperRuntimeConfig(
        source_path=(tmp_path / "runtime.toml").resolve(),
        source_file_identity=_hex("runtime-file"),
        source_parent_identity=_hex("runtime-parent"),
        raw_sha256=_hex("runtime-bytes"),
        schema_version="paper-runtime-config-v2",
        runtime_version="paper_runtime_v2",
        mode="PAPER_REAL_TIME_WINDOWS",
        runtime_root=parent / "runtime",
        broker_root=parent / "broker",
        evidence_root=evidence_root,
        anchor_root=anchor_root,
        log_root=log_root,
        project_root=tmp_path.resolve(),
        oms_sqlite_filename="oms.sqlite3",
        broker_sqlite_filename="broker.sqlite3",
        account_selector="formal-paper-account",
        source_selector="formal-paper-source",
        policy_selector="formal-paper-policy",
        expected_schedule_selector="formal-paper-schedule",
        config_identity=_hex("runtime-config"),
    )
    environment = object.__new__(VerifiedPaperRuntimeEnvironment)
    object.__setattr__(environment, "config", config)
    policy = object.__new__(VerifiedPaperExecutionPolicy)
    object.__setattr__(policy, "session_date", session_date)

    account_snapshot = build_account_snapshot(
        as_of=evidence_as_of, positions=(), cash=()
    )
    execution_store = SimpleNamespace()
    store = object()
    broker_store = _BrokerStoreProbe(account=account_snapshot, as_of=evidence_as_of)
    broker_capability = SimpleNamespace(
        store=broker_store,
        session_date=session_date,
        gateway_identity=_hex("gateway"),
    )
    account = SimpleNamespace(session_date=session_date)
    binding = object()
    execution_store.environment = environment
    execution_store.policy = policy
    execution_store.account = account
    execution_store.binding = binding
    execution_store.broker_store = broker_capability
    execution_store.store = store
    execution_store.store_identity = _hex("execution-store")
    execution_store.gateway_identity = _hex("gateway")
    execution_store.account_id = _hex("account")
    provider = SimpleNamespace(
        _execution_store=execution_store,
        provider_identity=_hex("ledger-provider"),
    )

    composition = object.__new__(VerifiedFormalPaperServiceComposition)
    object.__setattr__(
        composition, "execution_store_identity", execution_store.store_identity
    )
    object.__setattr__(composition, "gateway_identity", execution_store.gateway_identity)
    object.__setattr__(composition, "account_id", execution_store.account_id)
    object.__setattr__(composition, "ledger_provider_identity", provider.provider_identity)
    object.__setattr__(composition, "store_opener", _StoreOpener(store))
    object.__setattr__(composition, "_execution_store", execution_store)
    object.__setattr__(composition, "_ledger_provider", provider)

    schedule = object.__new__(VerifiedFormalPaperSoakSchedule)
    object.__setattr__(schedule, "schema_version", "formal-paper-soak-schedule-v1")
    object.__setattr__(schedule, "schedule_identity", _hex("schedule"))
    object.__setattr__(
        schedule,
        "expected_schedule_identity",
        soak_module.expected_schedule_identity((session_date,)),
    )
    object.__setattr__(schedule, "ledger_provider_identity", provider.provider_identity)
    object.__setattr__(
        schedule,
        "readiness_completed_at",
        evidence_as_of - dt.timedelta(days=1),
    )
    object.__setattr__(schedule, "not_before", session_date)
    object.__setattr__(schedule, "expected_sessions", (session_date,))
    object.__setattr__(schedule, "verified_at", now)
    object.__setattr__(schedule, "_provider", provider)

    report = build_execution_report(
        recovery=recovery,
        reconciliation=reconciliation,
        as_of=evidence_as_of,
    )
    return SimpleNamespace(
        environment=environment,
        policy=policy,
        composition=composition,
        schedule=schedule,
        session_date=session_date,
        now=now,
        recovery=recovery,
        reconciliation=reconciliation,
        report=report,
        broker_store=broker_store,
    )


def _allow_fresh_chain(
    monkeypatch: pytest.MonkeyPatch, inputs: SimpleNamespace
) -> None:
    monkeypatch.setattr(
        runtime, "verify_existing_paper_runtime_preflight", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        runtime,
        "verify_existing_paper_execution_policy",
        lambda **kwargs: kwargs["policy"],
    )
    monkeypatch.setattr(
        runtime,
        "verify_existing_formal_paper_service_composition",
        lambda **kwargs: kwargs["composition"],
    )
    monkeypatch.setattr(
        runtime,
        "verify_existing_formal_paper_soak_schedule",
        lambda **kwargs: kwargs["schedule"],
    )
    monkeypatch.setattr(
        runtime, "recover_local_state", lambda store: inputs.recovery
    )
    monkeypatch.setattr(
        runtime,
        "reconcile",
        lambda local, broker, as_of: inputs.reconciliation,
    )
    monkeypatch.setattr(
        broker_snapshot_module,
        "_fresh_capability",
        lambda **kwargs: kwargs["store_capability"],
    )
    monkeypatch.setattr(soak_module, "_production_utc_now", lambda: inputs.now)


def _remint_schedule(
    schedule: VerifiedFormalPaperSoakSchedule, *, verified_at: dt.datetime
) -> VerifiedFormalPaperSoakSchedule:
    reminted = object.__new__(VerifiedFormalPaperSoakSchedule)
    for item in fields(VerifiedFormalPaperSoakSchedule):
        if item.name == "_attestation":
            continue
        object.__setattr__(reminted, item.name, getattr(schedule, item.name))
    object.__setattr__(reminted, "verified_at", verified_at)
    return reminted


def _drifted_recovery(recovery: RecoveryResult) -> RecoveryResult:
    drifted = object.__new__(RecoveryResult)
    for item in fields(RecoveryResult):
        object.__setattr__(drifted, item.name, getattr(recovery, item.name))
    object.__setattr__(
        drifted,
        "issues",
        (RecoveryIssue("RECOVERY_TEST_DRIFT", "exact-session", "MANUAL_REQUIRED"),),
    )
    object.__setattr__(drifted, "disposition", "MANUAL_REQUIRED")
    object.__setattr__(
        drifted, "recovery_id", reconcile_module._recovery_identity(drifted)
    )
    drifted.__post_init__()
    return drifted


def test_zero_broker_command_session_closes_and_replays_exactly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = _runtime_inputs(tmp_path)
    _allow_fresh_chain(monkeypatch, inputs)
    port = _ReportPort(inputs.report)
    first = runtime.close_formal_paper_soak_session(
        environment=inputs.environment,
        policy=inputs.policy,
        composition=inputs.composition,
        schedule=inputs.schedule,
        session_date=inputs.session_date,
        now=inputs.now,
        report_port=port,
    )
    replay_now = inputs.now + dt.timedelta(minutes=1)
    reminted_schedule = _remint_schedule(inputs.schedule, verified_at=replay_now)
    monkeypatch.setattr(soak_module, "_production_utc_now", lambda: replay_now)
    second = runtime.close_formal_paper_soak_session(
        environment=inputs.environment,
        policy=inputs.policy,
        composition=inputs.composition,
        schedule=reminted_schedule,
        session_date=inputs.session_date,
        now=replay_now,
        report_port=port,
    )

    assert first.replayed is False
    assert second.replayed is True
    assert second.session_receipt == first.session_receipt
    assert second.evidence == first.evidence
    assert first.decision.status == "WAITING_FOR_SOAK_EVIDENCE"
    assert port.calls == 1
    assert inputs.broker_store.record_calls == 1
    assert inputs.broker_store.snapshot_calls == 4


def test_oms_recovery_drift_before_append_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = _runtime_inputs(tmp_path)
    _allow_fresh_chain(monkeypatch, inputs)
    sequence = iter((inputs.recovery, _drifted_recovery(inputs.recovery)))
    monkeypatch.setattr(runtime, "recover_local_state", lambda store: next(sequence))
    port = _ReportPort(inputs.report)

    with pytest.raises(runtime.FormalPaperSoakSessionError):
        runtime.close_formal_paper_soak_session(
            environment=inputs.environment,
            policy=inputs.policy,
            composition=inputs.composition,
            schedule=inputs.schedule,
            session_date=inputs.session_date,
            now=inputs.now,
            report_port=port,
        )

    assert port.calls == 0


def test_forged_marker_without_order_receipt_cannot_form_session_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = _runtime_inputs(tmp_path)
    _allow_fresh_chain(monkeypatch, inputs)
    empty_store = ExecutionStore.open("sqlite:///empty.db", trusted_root=tmp_path)
    try:
        empty = recover_local_state(empty_store)
    finally:
        empty_store.close()
    monkeypatch.setattr(runtime, "recover_local_state", lambda store: empty)
    inputs.broker_store.marker = SimpleNamespace(
        schema_version="paper-zero-broker-command-session-finality-v1",
        session_date=inputs.session_date,
        finalized_at=inputs.now,
        order_semantic_closure_identity="f" * 64,
    )

    with pytest.raises(runtime.FormalPaperSoakSessionError) as caught:
        runtime.close_formal_paper_soak_session(
            environment=inputs.environment,
            policy=inputs.policy,
            composition=inputs.composition,
            schedule=inputs.schedule,
            session_date=inputs.session_date,
            now=inputs.now,
            report_port=_ReportPort(inputs.report),
        )

    assert inputs.broker_store.snapshot_calls == 0
    assert caught.value.__cause__ is None and caught.value.__context__ is None


def test_session_lock_is_nonblocking_and_stably_sanitized(tmp_path: Path) -> None:
    root = (tmp_path / "log").resolve()
    root.mkdir()
    descriptor = runtime._acquire_session_lock(root)
    try:
        with pytest.raises(runtime.FormalPaperSoakSessionError) as caught:
            runtime._acquire_session_lock(root)
        assert caught.value.__cause__ is None and caught.value.__context__ is None
    finally:
        runtime._release_lock(descriptor)
        (root / runtime._LOCK_NAME).stat()
        os.close(descriptor)
