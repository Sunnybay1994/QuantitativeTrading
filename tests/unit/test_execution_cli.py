"""M4-P6 PAPER CLI contract and hostile-boundary tests."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import sqlite3
from pathlib import Path

from quant.execution.cli import main
from quant.execution.cli_ports import (
    CliDependencies,
    build_verified_broker_evidence,
    build_verified_paper_gateway,
    build_verified_planning_load,
    build_verified_target_load,
)
from quant.execution.contracts import build_account_snapshot
from quant.execution.reconcile import recover_local_state
from quant.execution.service import ExecutionService
from quant.execution.store import ExecutionStore, OutboxDeliveryState
from tests.unit.test_execution_service import (
    FakeGateway,
    FixtureLedgerContextProvider,
    MutableClock,
    _inputs,
    _planner_config,
)

NOW = dt.datetime(2026, 7, 19, 8, tzinfo=dt.UTC)


def _hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class StorePort:
    def __init__(self, store: ExecutionStore) -> None:
        self.store = store

    def open(self) -> ExecutionStore:
        return self.store


class ValueLoader:
    def __init__(self, value: object) -> None:
        self.value = value
        self.calls = 0

    def load(self):  # type: ignore[no-untyped-def]
        self.calls += 1
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


class GatewayFactory:
    def __init__(self, gateway: FakeGateway) -> None:
        self.gateway = gateway
        self.calls = 0

    def identity(self) -> str:
        return _hex("paper-gateway")

    def open(self):  # type: ignore[no-untyped-def]
        self.calls += 1
        return build_verified_paper_gateway(
            gateway_identity=_hex("paper-gateway"),
            submit=self.gateway,
            cancel=self.gateway,
        )


class ServiceFactory:
    def __init__(self, clock: MutableClock) -> None:
        self.clock = clock

    def build(self, *, store, gateway, cancel_gateway):  # type: ignore[no-untyped-def]
        return ExecutionService(
            store=store,
            gateway=gateway,
            cancel_gateway=cancel_gateway,
            clock=self.clock,
            worker_id="cli-worker",
            lease_duration=dt.timedelta(minutes=1),
            risk_counter_scope="paper-account",
            ledger_context_provider=FixtureLedgerContextProvider(),
        )


class InsertingServiceFactory(ServiceFactory):
    """Insert an unrelated command after confirmation but before exact claim."""

    def __init__(self, clock: MutableClock, target_load, planning_load) -> None:  # type: ignore[no-untyped-def]
        super().__init__(clock)
        self.target_load = target_load
        self.planning_load = planning_load

    def build(self, *, store, gateway, cancel_gateway):  # type: ignore[no-untyped-def]
        service = super().build(
            store=store, gateway=gateway, cancel_gateway=cancel_gateway
        )
        service.plan_and_stage(
            targets=self.target_load.targets,
            target_identity=_hex("concurrent-targets"),
            market=self.planning_load.market,
            account=self.planning_load.account,
            planner_config=self.planning_load.planner_config,
        )
        return service


class LockingServiceFactory(ServiceFactory):
    """Acquire an independent writer lock after fresh confirmation recovery."""

    def __init__(self, clock: MutableClock, db_path: Path) -> None:
        super().__init__(clock)
        self.db_path = db_path
        self.blocker: sqlite3.Connection | None = None

    def build(self, *, store, gateway, cancel_gateway):  # type: ignore[no-untyped-def]
        service = super().build(
            store=store, gateway=gateway, cancel_gateway=cancel_gateway
        )
        self.blocker = sqlite3.connect(self.db_path, timeout=0)
        self.blocker.execute("BEGIN IMMEDIATE")
        return service

    def close(self) -> None:
        if self.blocker is not None:
            self.blocker.rollback()
            self.blocker.close()
            self.blocker = None


class FailingClaimServiceFactory(ServiceFactory):
    """Fail the exact claim write after fresh confirmation recovery."""

    def build(self, *, store, gateway, cancel_gateway):  # type: ignore[no-untyped-def]
        service = super().build(
            store=store, gateway=gateway, cancel_gateway=cancel_gateway
        )
        store._conn.execute(  # noqa: SLF001 - fault injection at SQLite boundary
            """
            CREATE TRIGGER fail_exact_pending_claim
            BEFORE UPDATE OF state ON outbox_deliveries
            WHEN NEW.state = 'LEASED'
            BEGIN
                SELECT RAISE(ABORT, 'PRIVATE_TRIGGER_SENTINEL');
            END
            """
        )
        return service


class BrokerPort:
    def __init__(self, value: object) -> None:
        self.value = value
        self.calls = 0

    def query_and_verify(self, *, gateway_identity: str):  # type: ignore[no-untyped-def]
        self.calls += 1
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


def _deps(tmp_path: Path):  # type: ignore[no-untyped-def]
    store = ExecutionStore.open("sqlite:///cli/execution.db", trusted_root=tmp_path)
    clock = MutableClock(NOW)
    targets, market, account = _inputs(cash="2000")
    target_load = build_verified_target_load(
        target_identity=_hex("targets"),
        receipt_identity=_hex("target-receipt"),
        targets=targets,
    )
    planning_load = build_verified_planning_load(
        market=market,
        account=account,
        planner_config=_planner_config(tmp_path),
    )
    gateway = FakeGateway()
    gateway_factory = GatewayFactory(gateway)
    empty_account = build_account_snapshot(as_of=NOW, positions=(), cash=())
    evidence = build_verified_broker_evidence(
        source_identity=_hex("broker-evidence"),
        gateway_identity=_hex("paper-gateway"),
        as_of=NOW,
        finality="INTRADAY",
        account=empty_account,
        orders=(),
        events=(),
    )
    broker = BrokerPort(evidence)
    dependencies = CliDependencies(
        store_opener=StorePort(store),
        target_loader=ValueLoader(target_load),
        planning_loader=ValueLoader(planning_load),
        service_factory=ServiceFactory(clock),
        paper_gateway_factory=gateway_factory,
        broker_snapshot_port=broker,
        clock=clock,
    )
    return dependencies, store, gateway, gateway_factory, broker


def _json(capsys):  # type: ignore[no-untyped-def]
    captured = capsys.readouterr()
    assert captured.err == ""
    return json.loads(captured.out)


def test_exact_command_set_and_usage_are_stable_and_sanitized(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    dependencies, store, _, _, _ = _deps(tmp_path)
    try:
        for argv in (["live"], ["submit"], ["approve", "--yes"], ["inspect", "extra"]):
            assert main(argv, dependencies=dependencies) == 2
            captured = capsys.readouterr()
            assert captured.out == ""
            assert captured.err == "CLI_USAGE_INVALID\n"
    finally:
        store.close()


def test_inspect_is_read_only_and_prints_only_stable_issue_codes(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    dependencies, store, _, gateway_factory, broker = _deps(tmp_path)
    try:
        database = tmp_path / "cli" / "execution.db"
        before = database.read_bytes()
        assert main(["inspect"], dependencies=dependencies) == 0
        payload = _json(capsys)
        assert payload["action"] == "inspect"
        assert payload["code"] == "LOCAL_RECOVERY_COMPLETE"
        assert payload["issue_codes"] == []
        assert database.read_bytes() == before
        assert gateway_factory.calls == 0
        assert broker.calls == 0
    finally:
        store.close()


def test_plan_reproves_inputs_and_emits_content_addressed_challenge(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    dependencies, store, gateway, gateway_factory, _ = _deps(tmp_path)
    try:
        assert main(["plan"], dependencies=dependencies) == 0
        payload = _json(capsys)
        assert payload["status"] == "planned"
        assert set(payload["challenge"]) == {
            "schema_version", "action", "mode", "store_recovery_id", "subject_ids",
            "source_identities", "gateway_identity", "issued_at", "expires_at",
        }
        assert payload["challenge"]["mode"] == "PAPER"
        assert gateway_factory.calls == 0
        assert gateway.calls == []
    finally:
        store.close()


def test_approve_confirmation_fresh_recompute_and_replay_are_idempotent(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    dependencies, store, gateway, _, _ = _deps(tmp_path)
    try:
        assert main(["approve"], dependencies=dependencies) == 20
        first = _json(capsys)
        challenge = first["content_identity"]
        assert gateway.calls == []
        assert recover_local_state(store).commands == ()

        assert main(["approve", "--confirm-sha256", challenge], dependencies=dependencies) == 0
        staged = _json(capsys)
        assert staged["code"] == "APPROVAL_STAGED"
        recovered = recover_local_state(store)
        assert len(recovered.commands) == 1
        assert gateway.calls == []

        # The durable store changed, so the old approval cannot be replayed as a new challenge.
        assert main(["approve", "--confirm-sha256", challenge], dependencies=dependencies) == 20
        assert capsys.readouterr().err == "CONFIRMATION_DRIFT\n"
        assert len(recover_local_state(store).commands) == 1

        # A fresh post-completion challenge replays the durable stage receipt with no new command.
        assert main(["approve"], dependencies=dependencies) == 20
        replay = _json(capsys)["content_identity"]
        assert main(["approve", "--confirm-sha256", replay], dependencies=dependencies) == 0
        assert _json(capsys)["code"] == "APPROVAL_STAGED_REPLAY"
        assert len(recover_local_state(store).commands) == 1
    finally:
        store.close()


def test_submit_uses_exact_confirmed_set_and_rejects_cross_action_hash(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    dependencies, store, gateway, _, _ = _deps(tmp_path)
    try:
        assert main(["approve"], dependencies=dependencies) == 20
        approval = _json(capsys)["content_identity"]
        assert main(["approve", "--confirm-sha256", approval], dependencies=dependencies) == 0
        _json(capsys)

        assert main(["paper-submit"], dependencies=dependencies) == 20
        submit = _json(capsys)["content_identity"]
        assert gateway.calls == []
        assert main(["paper-submit", "--confirm-sha256", approval], dependencies=dependencies) == 20
        assert capsys.readouterr().err == "CONFIRMATION_DRIFT\n"
        assert gateway.calls == []

        assert main(["paper-submit", "--confirm-sha256", submit], dependencies=dependencies) == 0
        result = _json(capsys)
        assert result["code"] == "SUBMIT_COMPLETE"
        assert len(gateway.calls) == 1
        local = recover_local_state(store)
        assert local.deliveries[0].state is OutboxDeliveryState.SENT
        assert main(["paper-submit"], dependencies=dependencies) == 0
        assert _json(capsys)["code"] == "SUBMIT_ALREADY_COMPLETE"
        assert len(gateway.calls) == 1
    finally:
        store.close()


def test_submit_never_sends_command_inserted_after_confirmation_check(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    dependencies, store, gateway, _, _ = _deps(tmp_path)
    try:
        assert main(["approve"], dependencies=dependencies) == 20
        approval = _json(capsys)["content_identity"]
        assert main(["approve", "--confirm-sha256", approval], dependencies=dependencies) == 0
        _json(capsys)
        assert main(["paper-submit"], dependencies=dependencies) == 20
        submit = _json(capsys)["content_identity"]

        object.__setattr__(
            dependencies,
            "service_factory",
            InsertingServiceFactory(
                dependencies.clock,  # type: ignore[arg-type]
                dependencies.target_loader.load(),
                dependencies.planning_loader.load(),
            ),
        )
        assert main(
            ["paper-submit", "--confirm-sha256", submit], dependencies=dependencies
        ) == 20
        assert capsys.readouterr().err == "CONFIRMATION_DRIFT\n"
        local = recover_local_state(store)
        assert gateway.calls == []
        assert len(local.deliveries) == 2
        assert all(
            item.state is OutboxDeliveryState.PENDING for item in local.deliveries
        )
    finally:
        store.close()


def test_submit_maps_post_confirmation_writer_busy_to_retry(
    tmp_path: Path, capsys
) -> None:  # type: ignore[no-untyped-def]
    dependencies, store, gateway, _, _ = _deps(tmp_path)
    locking = LockingServiceFactory(
        dependencies.clock, tmp_path / "cli" / "execution.db"  # type: ignore[arg-type]
    )
    try:
        assert main(["approve"], dependencies=dependencies) == 20
        approval = _json(capsys)["content_identity"]
        assert main(
            ["approve", "--confirm-sha256", approval], dependencies=dependencies
        ) == 0
        _json(capsys)
        assert main(["paper-submit"], dependencies=dependencies) == 20
        submit = _json(capsys)["content_identity"]
        object.__setattr__(dependencies, "service_factory", locking)

        assert main(
            ["paper-submit", "--confirm-sha256", submit], dependencies=dependencies
        ) == 50
        assert capsys.readouterr().err == "EXECUTION_RETRY_REQUIRED\n"
        assert gateway.calls == []
    finally:
        locking.close()
        store.close()


def test_submit_maps_post_confirmation_claim_write_failure_to_retry(
    tmp_path: Path, capsys
) -> None:  # type: ignore[no-untyped-def]
    dependencies, store, gateway, _, _ = _deps(tmp_path)
    try:
        assert main(["approve"], dependencies=dependencies) == 20
        approval = _json(capsys)["content_identity"]
        assert main(
            ["approve", "--confirm-sha256", approval], dependencies=dependencies
        ) == 0
        _json(capsys)
        assert main(["paper-submit"], dependencies=dependencies) == 20
        submit = _json(capsys)["content_identity"]
        object.__setattr__(
            dependencies,
            "service_factory",
            FailingClaimServiceFactory(dependencies.clock),  # type: ignore[arg-type]
        )

        assert main(
            ["paper-submit", "--confirm-sha256", submit], dependencies=dependencies
        ) == 50
        assert capsys.readouterr().err == "EXECUTION_RETRY_REQUIRED\n"
        assert gateway.calls == []
        local = recover_local_state(store)
        assert len(local.deliveries) == 1
        assert local.deliveries[0].state is OutboxDeliveryState.PENDING
        assert local.deliveries[0].attempt_count == 0
    finally:
        store.close()


def test_cancel_only_crosses_durable_service_after_exact_confirmation(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    dependencies, store, gateway, _, _ = _deps(tmp_path)
    try:
        assert main(["approve"], dependencies=dependencies) == 20
        approval = _json(capsys)["content_identity"]
        assert main(["approve", "--confirm-sha256", approval], dependencies=dependencies) == 0
        _json(capsys)
        assert main(["paper-submit"], dependencies=dependencies) == 20
        submit = _json(capsys)["content_identity"]
        assert main(["paper-submit", "--confirm-sha256", submit], dependencies=dependencies) == 0
        _json(capsys)
        command_id = recover_local_state(store).commands[0].command_id

        assert main(["cancel", "--command-id", command_id], dependencies=dependencies) == 20
        cancel = _json(capsys)["content_identity"]
        assert gateway.cancel_calls == []
        assert main(
            ["cancel", "--command-id", command_id, "--confirm-sha256", cancel],
            dependencies=dependencies,
        ) == 0
        payload = _json(capsys)
        assert payload["code"] == "CANCEL_COMPLETE"
        assert len(gateway.cancel_calls) == 1

        assert main(["cancel", "--command-id", command_id], dependencies=dependencies) == 20
        replay = _json(capsys)["content_identity"]
        assert main(
            ["cancel", "--command-id", command_id, "--confirm-sha256", replay],
            dependencies=dependencies,
        ) == 0
        assert _json(capsys)["code"] == "CANCEL_ALREADY_COMPLETED"
        assert len(gateway.cancel_calls) == 1
    finally:
        store.close()


def test_reconcile_requires_verified_evidence_and_eod(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    dependencies, store, _, _, broker = _deps(tmp_path)
    try:
        assert main(["reconcile"], dependencies=dependencies) == 30
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == "RECONCILE_QUERY_REQUIRED\n"
        assert broker.calls == 1

        broker.value = RuntimeError("TOKEN=/secret/path/account正文")
        assert main(["reconcile"], dependencies=dependencies) == 10
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == "BROKER_EVIDENCE_INVALID\n"
        assert "TOKEN" not in captured.err
    finally:
        store.close()


def test_forged_loader_identity_and_secret_exception_are_detached(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    dependencies, store, _, _, _ = _deps(tmp_path)
    try:
        targets = dependencies.target_loader.load()
        object.__setattr__(targets, "verification_identity", "0" * 64)
        assert main(["plan"], dependencies=dependencies) == 10
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == "TARGET_IDENTITY_INVALID\n"

        dependencies.target_loader.value = RuntimeError("TOKEN=/secret/account正文")  # type: ignore[attr-defined]
        assert main(["plan"], dependencies=dependencies) == 10
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == "TARGET_IDENTITY_INVALID\n"
    finally:
        store.close()
