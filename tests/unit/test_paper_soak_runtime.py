"""M4-B1B2: terminal-closure-driven Windows PAPER session closer contracts.

Exercises the real B1 anchored-lock terminal machinery end-to-end (formal
``FORMAL_CLOSURE_ONLY`` barrier, live closure, terminal context/children,
CLOSING→CLOSED) rather than mocking ``session_barrier``. Only the outer
composition/environment/policy/schedule/broker-store verification chains are
stubbed (matching the established pattern in ``test_paper_formal_service.py``
and ``test_paper_formal_broker_store.py``), since those are covered by their
own dedicated test suites.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest

from quant.execution import paper_formal_broker_snapshot as broker_snapshot_module
from quant.execution import paper_formal_execution_store as formal_oms
from quant.execution import paper_formal_service as formal_service
from quant.execution import soak as soak_module
from quant.execution import soak_runtime as runtime
from quant.execution.paper_formal_execution_store import (
    VerifiedFormalPaperExecutionStoreCapability,
)
from quant.execution.paper_formal_schedule import VerifiedFormalPaperSoakSchedule
from quant.execution.paper_formal_service import VerifiedFormalPaperServiceComposition
from quant.execution.paper_policy import VerifiedPaperExecutionPolicy
from quant.execution.paper_runtime import (
    FormalPaperRuntimeConfig,
    VerifiedPaperRuntimeEnvironment,
)
from quant.execution.reconcile import reconcile as real_reconcile
from quant.execution.session_barrier import build_session_barrier_capability
from quant.execution.store import ExecutionStore
from quant.reporting.execution_report import build_execution_report

UTC = dt.timezone.utc


def _hex(tag: str) -> str:
    return hashlib.sha256(tag.encode()).hexdigest()


class _BrokerStoreProbe:
    """Duck-typed ``PaperBrokerStore`` stand-in for the zero-command path."""

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
    """Real ``ExecutionReport`` builder driven by whatever recovery/reconciliation
    ``soak_runtime`` actually computed (not a canned constant)."""

    def __init__(self) -> None:
        self.calls = 0
        self.last_report: object | None = None

    def build(self, *, recovery: object, reconciliation: object, as_of: dt.datetime) -> object:
        self.calls += 1
        report = build_execution_report(
            recovery=recovery, reconciliation=reconciliation, as_of=as_of
        )
        self.last_report = report
        return report


def _runtime_inputs(tmp_path: Path, *, session_date: dt.date, now: dt.datetime):  # type: ignore[no-untyped-def]
    """Build one real barrier-backed formal OMS store already in CLOSING."""
    parent = (tmp_path / "paper-runtime").resolve()
    evidence_root = parent / "evidence"
    anchor_root = parent / "anchor"
    log_root = parent / "log"
    lock_root = parent / "lock"
    for path in (evidence_root, anchor_root, log_root, lock_root):
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

    barrier_cap = build_session_barrier_capability(
        barrier_epoch=_hex("epoch"),
        session_date=session_date,
        account_identity=_hex("account"),
        oms_store_identity=_hex("oms"),
        broker_store_identity=_hex("broker"),
        gateway_identity=_hex("gateway"),
        config_identity=_hex("config"),
        lock_root=lock_root,
        terminal_policy="FORMAL_CLOSURE_ONLY",
    )
    store = ExecutionStore.open(
        "sqlite:///oms.sqlite3",
        trusted_root=config.runtime_root.parent,
        session_barrier=barrier_cap,
        initialize_barrier=True,
        barrier_created_at=now - dt.timedelta(hours=8),
    )
    _row, _token, closure = store.transition_session_barrier_to_closing(
        nonce="m4-b1b2-soak", now=now - dt.timedelta(minutes=1)
    )

    from quant.execution.contracts import build_account_snapshot

    account_snapshot = build_account_snapshot(as_of=now, positions=(), cash=())
    broker_store = _BrokerStoreProbe(account=account_snapshot, as_of=now)
    broker_capability = SimpleNamespace(
        store=broker_store,
        session_date=session_date,
        gateway_identity=_hex("gateway"),
    )
    account = SimpleNamespace(session_date=session_date)
    binding = object()

    execution_store = object.__new__(VerifiedFormalPaperExecutionStoreCapability)
    object.__setattr__(execution_store, "store_identity", _hex("execution-store"))
    object.__setattr__(execution_store, "account_id", _hex("account"))
    object.__setattr__(execution_store, "gateway_identity", _hex("gateway"))
    object.__setattr__(execution_store, "environment", environment)
    object.__setattr__(execution_store, "policy", policy)
    object.__setattr__(execution_store, "binding", binding)
    object.__setattr__(execution_store, "account", account)
    object.__setattr__(execution_store, "broker_store", broker_capability)
    object.__setattr__(execution_store, "_store", store)
    object.__setattr__(execution_store, "_session_barrier", barrier_cap)
    object.__setattr__(execution_store, "_attestation", object())

    composition = object.__new__(VerifiedFormalPaperServiceComposition)
    object.__setattr__(composition, "composition_identity", _hex("composition"))
    object.__setattr__(
        composition, "execution_store_identity", execution_store.store_identity
    )
    object.__setattr__(composition, "gateway_identity", execution_store.gateway_identity)
    object.__setattr__(composition, "account_id", execution_store.account_id)
    object.__setattr__(composition, "ledger_provider_identity", _hex("ledger-provider"))
    object.__setattr__(composition, "store_opener", SimpleNamespace(open=lambda: store))
    object.__setattr__(composition, "_execution_store", execution_store)
    object.__setattr__(composition, "_ledger_provider", SimpleNamespace())

    schedule = object.__new__(VerifiedFormalPaperSoakSchedule)
    object.__setattr__(schedule, "schema_version", "formal-paper-soak-schedule-v1")
    object.__setattr__(schedule, "schedule_identity", _hex("schedule"))
    object.__setattr__(
        schedule,
        "expected_schedule_identity",
        soak_module.expected_schedule_identity((session_date,)),
    )
    object.__setattr__(
        schedule, "ledger_provider_identity", composition.ledger_provider_identity
    )
    object.__setattr__(
        schedule, "readiness_completed_at", now - dt.timedelta(days=1)
    )
    object.__setattr__(schedule, "not_before", session_date)
    object.__setattr__(schedule, "expected_sessions", (session_date,))
    object.__setattr__(schedule, "verified_at", now)
    object.__setattr__(schedule, "_provider", SimpleNamespace())

    return SimpleNamespace(
        environment=environment,
        policy=policy,
        composition=composition,
        schedule=schedule,
        session_date=session_date,
        now=now,
        closure=closure,
        store=store,
        broker_store=broker_store,
    )


def _allow_verification_bypass(
    monkeypatch: pytest.MonkeyPatch,
    *,
    formal_clock: list[dt.datetime] | None = None,
) -> None:
    """Bypass only the outer composition/environment/policy/schedule/broker
    verification chains (each covered by its own dedicated test suite); the
    B1 anchored-lock terminal machinery under test remains fully real.

    When ``formal_clock`` is provided, pin soak's ``_production_utc_now`` to that
    mutable test-owned clock so WINDOWS append/anchor ``_require_formal_now``
    matches the fixture ``now`` (5-minute production tolerance).
    """
    monkeypatch.setattr(
        runtime, "verify_existing_paper_runtime_preflight", lambda *a, **k: None
    )
    monkeypatch.setattr(
        runtime, "verify_existing_paper_execution_policy", lambda **kwargs: kwargs["policy"]
    )
    monkeypatch.setattr(
        runtime,
        "verify_existing_formal_paper_soak_schedule",
        lambda **kwargs: kwargs["schedule"],
    )
    monkeypatch.setattr(
        formal_service,
        "verify_existing_formal_paper_service_composition",
        lambda **kwargs: kwargs["composition"],
    )
    monkeypatch.setattr(
        formal_oms,
        "verify_existing_formal_paper_execution_store_capability",
        lambda **kwargs: kwargs["capability"],
    )
    monkeypatch.setattr(
        broker_snapshot_module,
        "_fresh_capability",
        lambda **kwargs: kwargs["store_capability"],
    )
    if formal_clock is not None:
        monkeypatch.setattr(
            soak_module, "_production_utc_now", lambda: formal_clock[0]
        )


class _PublicNarrowStepTrace:
    """Test-owned observation of public narrow APIs (no raw store/repo/conn)."""

    def __init__(self) -> None:
        self.reached: list[str] = []

    def note(self, step: str) -> None:
        self.reached.append(step)


def _install_public_narrow_step_trace(
    monkeypatch: pytest.MonkeyPatch, trace: _PublicNarrowStepTrace
) -> None:
    """Wrap soak_runtime's public imports to record durable-step progress."""
    real_finalize = runtime.finalize_and_query_formal_paper_broker_eod
    real_order = runtime.session_order_semantic_closure_identity
    real_reconcile = runtime.reconcile
    real_append = runtime.append_soak_session
    real_successor = runtime.compute_terminal_successor_identity

    def finalize(*args: object, **kwargs: object) -> object:
        trace.note("broker_finality")
        return real_finalize(*args, **kwargs)

    def order_closure(*args: object, **kwargs: object) -> object:
        trace.note("oms_order_closure")
        return real_order(*args, **kwargs)

    def reconcile_wrap(*args: object, **kwargs: object) -> object:
        trace.note("reconciliation")
        return real_reconcile(*args, **kwargs)

    def append_wrap(*args: object, **kwargs: object) -> object:
        trace.note("report_soak")
        return real_append(*args, **kwargs)

    def successor_wrap(*args: object, **kwargs: object) -> object:
        trace.note("terminal_successor")
        return real_successor(*args, **kwargs)

    monkeypatch.setattr(runtime, "finalize_and_query_formal_paper_broker_eod", finalize)
    monkeypatch.setattr(
        runtime, "session_order_semantic_closure_identity", order_closure
    )
    monkeypatch.setattr(runtime, "reconcile", reconcile_wrap)
    monkeypatch.setattr(runtime, "append_soak_session", append_wrap)
    monkeypatch.setattr(
        runtime, "compute_terminal_successor_identity", successor_wrap
    )


def test_zero_command_session_closes_end_to_end_via_real_terminal_machinery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = dt.datetime(2026, 8, 20, 16, 30, tzinfo=UTC)
    session_date = now.date()
    inputs = _runtime_inputs(tmp_path, session_date=session_date, now=now)
    formal_clock = [now]
    _allow_verification_bypass(monkeypatch, formal_clock=formal_clock)
    trace = _PublicNarrowStepTrace()
    _install_public_narrow_step_trace(monkeypatch, trace)
    port = _ReportPort()

    result = runtime.close_formal_paper_soak_session(
        environment=inputs.environment,
        policy=inputs.policy,
        composition=inputs.composition,
        schedule=inputs.schedule,
        session_date=session_date,
        now=now,
        report_port=port,
        closure=inputs.closure,
    )

    assert result.replayed is False
    assert port.calls == 1
    assert inputs.broker_store.record_calls == 1
    assert result.decision.status == "WAITING_FOR_SOAK_EVIDENCE"
    assert result.closed_row is not None
    assert result.closed_row.state == "CLOSED"
    assert result.terminal_successor_identity is not None
    assert inputs.store.read_session_barrier_row().state == "CLOSED"  # type: ignore[union-attr]
    # Public narrow chain observed under pinned formal clock (VALIDATION1 root cause).
    assert "broker_finality" in trace.reached
    assert "oms_order_closure" in trace.reached
    assert "reconciliation" in trace.reached
    assert "report_soak" in trace.reached
    assert "terminal_successor" in trace.reached

    # Zero-write, read-only replay using the exact same live closure.
    replay_now = now + dt.timedelta(minutes=1)
    formal_clock[0] = replay_now
    replayed = runtime.close_formal_paper_soak_session(
        environment=inputs.environment,
        policy=inputs.policy,
        composition=inputs.composition,
        schedule=inputs.schedule,
        session_date=session_date,
        now=replay_now,
        report_port=port,
        closure=inputs.closure,
    )
    assert replayed.replayed is True
    assert replayed.session_receipt == result.session_receipt
    assert replayed.terminal_successor_identity == result.terminal_successor_identity
    assert replayed.terminal_successor_identity is not None
    assert port.calls == 1
    assert inputs.broker_store.record_calls == 1

    inputs.store.close()


def test_infra_007_and_f2_f3_source_contracts() -> None:
    # Implementation lives under legacy/; the public module is a thin shim.
    from pathlib import Path

    source = Path("legacy/quant/execution/soak_runtime.py").read_text(encoding="utf-8")
    assert "_finalize_and_query_formal_paper_broker_eod" not in source
    assert "_session_order_semantic_closure_identity" not in source
    assert "recover_local_state" not in source
    assert "recover_repository_state" not in source
    assert "._execution_store" not in source
    assert "._ledger_provider" not in source
    assert "._session_barrier" not in source
    assert "_hold_session_lock" not in source
    assert "_acquire_session_lock" not in source
    assert "soak-runtime-zero-order-closure-v1" not in source
    assert "SoakSessionOrderSemanticClosureZero" not in source
    assert not hasattr(runtime, "_hold_session_lock")
    assert not hasattr(runtime, "_acquire_session_lock")
    assert not hasattr(runtime, "_release_lock")
    assert "finalize_and_query_formal_paper_broker_eod" in source
    assert "session_order_semantic_closure_identity" in source
    assert "recover_oms_under_terminal_child" in source
    assert "recover_oms_when_barrier_closed" in source
    assert "open_oms_store" not in source
    assert "inspect_oms_under_terminal_child" not in source
    assert "inspect_oms_when_closed" not in source
    assert "transaction_under_terminal_child" not in source
    assert 'step_kind="oms_recovery"' in source
    # F4: evidence before/existing must be established only under hold_terminal_closure.
    hold_idx = source.index("with view.hold_terminal_closure")
    before_idx = source.index("_verified_windows_evidence(", hold_idx)
    assert before_idx > hold_idx


def test_transaction_under_terminal_child_rejects_non_oms_recovery_steps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = dt.datetime(2026, 8, 20, 16, 30, tzinfo=UTC)
    inputs = _runtime_inputs(tmp_path, session_date=now.date(), now=now)
    _allow_verification_bypass(monkeypatch)
    from quant.execution.paper_formal_execution_store import hold_formal_terminal_closure
    from quant.execution.paper_formal_execution_store import hold_formal_terminal_step
    from quant.execution.store import StoreError

    execution_store = inputs.composition._execution_store
    with hold_formal_terminal_closure(
        capability=execution_store, closure=inputs.closure, now=now
    ) as context:
        with hold_formal_terminal_step(
            context, capability=execution_store, step_kind="broker_finality"
        ) as child:
            with pytest.raises(StoreError, match="BARRIER_TERMINAL_STEP_INVALID"):
                with inputs.store.transaction_under_terminal_child(
                    terminal_child=child, step_kind="broker_finality"
                ):
                    pass
    inputs.store.close()


def test_closure_view_wrong_step_recovery_is_immutable_and_non_writable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from quant.execution.paper_formal_service import open_formal_paper_closure_view
    from quant.execution.reconcile import RecoveryResult
    from quant.execution.store import ExecutionRepository

    now = dt.datetime(2026, 8, 20, 16, 30, tzinfo=UTC)
    inputs = _runtime_inputs(tmp_path, session_date=now.date(), now=now)
    _allow_verification_bypass(monkeypatch)
    view = open_formal_paper_closure_view(composition=inputs.composition, now=now)
    assert not hasattr(view, "open_oms_store")
    assert not hasattr(view, "inspect_oms_under_terminal_child")
    assert not hasattr(view, "inspect_oms_when_closed")

    with view.hold_terminal_closure(inputs.closure) as context:
        with view.hold_terminal_step(context, step_kind="broker_finality") as child:
            recovery = view.recover_oms_under_terminal_child(
                terminal_child=child, step_kind="broker_finality"
            )
            assert type(recovery) is RecoveryResult
            assert not hasattr(recovery, "_conn")
            assert not hasattr(recovery, "commit")
            assert not hasattr(recovery, "execute")
            forged = object.__new__(ExecutionRepository)
            assert not hasattr(forged, "_conn") or getattr(forged, "_conn", None) is None
            before_row = inputs.store.read_session_barrier_row()
            # Wrong-step path must not persist barrier/OMS writes via the returned object.
            assert inputs.store.read_session_barrier_row() == before_row
    inputs.store.close()


def test_close_requires_live_closure_and_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = dt.datetime(2026, 8, 20, 16, 30, tzinfo=UTC)
    inputs = _runtime_inputs(tmp_path, session_date=now.date(), now=now)
    _allow_verification_bypass(monkeypatch)

    with pytest.raises(runtime.FormalPaperSoakSessionError) as caught:
        runtime.close_formal_paper_soak_session(
            environment=inputs.environment,
            policy=inputs.policy,
            composition=inputs.composition,
            schedule=inputs.schedule,
            session_date=now.date(),
            now=now,
            report_port=_ReportPort(),
            closure=None,
        )
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert inputs.store.read_session_barrier_row().state == "CLOSING"  # type: ignore[union-attr]
    inputs.store.close()


def test_forged_closure_object_is_rejected_and_barrier_stays_closing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = dt.datetime(2026, 8, 20, 16, 30, tzinfo=UTC)
    inputs = _runtime_inputs(tmp_path, session_date=now.date(), now=now)
    _allow_verification_bypass(monkeypatch)

    with pytest.raises(runtime.FormalPaperSoakSessionError) as caught:
        runtime.close_formal_paper_soak_session(
            environment=inputs.environment,
            policy=inputs.policy,
            composition=inputs.composition,
            schedule=inputs.schedule,
            session_date=now.date(),
            now=now,
            report_port=_ReportPort(),
            closure=object(),
        )
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert inputs.store.read_session_barrier_row().state == "CLOSING"  # type: ignore[union-attr]
    inputs.store.close()


def test_wrong_type_composition_fails_closed_without_touching_barrier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = dt.datetime(2026, 8, 20, 16, 30, tzinfo=UTC)
    inputs = _runtime_inputs(tmp_path, session_date=now.date(), now=now)
    _allow_verification_bypass(monkeypatch)

    with pytest.raises(runtime.FormalPaperSoakSessionError):
        runtime.close_formal_paper_soak_session(
            environment=inputs.environment,
            policy=inputs.policy,
            composition=object(),  # type: ignore[arg-type]
            schedule=inputs.schedule,
            session_date=now.date(),
            now=now,
            report_port=_ReportPort(),
            closure=inputs.closure,
        )
    assert inputs.store.read_session_barrier_row().state == "CLOSING"  # type: ignore[union-attr]
    inputs.store.close()


def test_mid_sequence_failure_stays_closing_and_resumes_on_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fail-closed: an injected reconciliation failure never rolls back to
    OPEN; a retry with the same closure resumes and completes idempotently."""
    now = dt.datetime(2026, 8, 20, 16, 30, tzinfo=UTC)
    session_date = now.date()
    inputs = _runtime_inputs(tmp_path, session_date=session_date, now=now)
    formal_clock = [now]
    _allow_verification_bypass(monkeypatch, formal_clock=formal_clock)
    port = _ReportPort()
    first_trace = _PublicNarrowStepTrace()
    _install_public_narrow_step_trace(monkeypatch, first_trace)

    def hostile_reconcile(local: object, broker: object, as_of: dt.datetime) -> object:
        first_trace.note("reconciliation_injected_failure")
        raise RuntimeError("INJECTED_RECONCILE_FAILURE")

    monkeypatch.setattr(runtime, "reconcile", hostile_reconcile)
    with pytest.raises(runtime.FormalPaperSoakSessionError):
        runtime.close_formal_paper_soak_session(
            environment=inputs.environment,
            policy=inputs.policy,
            composition=inputs.composition,
            schedule=inputs.schedule,
            session_date=session_date,
            now=now,
            report_port=port,
            closure=inputs.closure,
        )
    assert port.calls == 0
    assert inputs.store.read_session_barrier_row().state == "CLOSING"  # type: ignore[union-attr]
    # Broker finality (step 1) already durably recorded despite the failure.
    assert inputs.broker_store.record_calls == 1
    assert "broker_finality" in first_trace.reached
    assert "report_soak" not in first_trace.reached
    assert "reconciliation_injected_failure" in first_trace.reached

    retry_trace = _PublicNarrowStepTrace()
    _install_public_narrow_step_trace(monkeypatch, retry_trace)

    def reconcile_observed(*args: object, **kwargs: object) -> object:
        retry_trace.note("reconciliation")
        return real_reconcile(*args, **kwargs)

    monkeypatch.setattr(runtime, "reconcile", reconcile_observed)
    retry_now = now + dt.timedelta(seconds=5)
    formal_clock[0] = retry_now
    result = runtime.close_formal_paper_soak_session(
        environment=inputs.environment,
        policy=inputs.policy,
        composition=inputs.composition,
        schedule=inputs.schedule,
        session_date=session_date,
        now=retry_now,
        report_port=port,
        closure=inputs.closure,
    )
    assert result.replayed is False
    assert port.calls == 1
    # Resume did not re-record a second broker finality marker.
    assert inputs.broker_store.record_calls == 1
    assert result.closed_row.state == "CLOSED"  # type: ignore[union-attr]
    assert "broker_finality" in retry_trace.reached
    assert "reconciliation" in retry_trace.reached
    assert "report_soak" in retry_trace.reached
    assert "terminal_successor" in retry_trace.reached
    inputs.store.close()
