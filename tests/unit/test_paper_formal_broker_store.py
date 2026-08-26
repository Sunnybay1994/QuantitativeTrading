"""RUN-0B2E focused formal durable store capability tests."""

from __future__ import annotations

import datetime as dt
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from quant.backtest.costs import ExecutionCostPeriod, build_execution_cost_schedule
from quant.domain.enums import Currency, Market
from quant.execution.contracts import CashBalance, build_account_snapshot
from quant.execution import paper_formal_broker_store as formal
from quant.execution import paper_formal_broker_snapshot as formal_snapshot
from quant.execution import paper_account, paper_broker_binding, paper_policy, paper_runtime
from quant.execution import paper_broker_store as b1
from quant.execution.paper_broker_store import build_paper_account_descriptor

NOW = dt.datetime(2026, 8, 12, 10, tzinfo=dt.timezone.utc)


def _schedule():  # type: ignore[no-untyped-def]
    return build_execution_cost_schedule(
        selector="paper-cost-v1",
        periods=(
            ExecutionCostPeriod(
                Market.SH,
                dt.date(2026, 1, 1),
                None,
                Decimal("0.0003"),
                Decimal("5"),
                Decimal("0.0005"),
                Decimal("0.00001"),
                Currency.CNY,
            ),
        ),
    )


def _chains(tmp_path: Path):  # type: ignore[no-untyped-def]
    parent = tmp_path / "paper-parent"
    parent.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    config = paper_runtime.FormalPaperRuntimeConfig(
        source_path=project / "runtime.toml",
        source_file_identity="1" * 64,
        source_parent_identity="2" * 64,
        raw_sha256="3" * 64,
        schema_version="paper-runtime-config-v2",
        runtime_version="paper_runtime_v2",
        mode="PAPER_REAL_TIME",
        runtime_root=parent / "runtime",
        broker_root=parent / "broker",
        evidence_root=parent / "evidence",
        anchor_root=parent / "anchor",
        log_root=parent / "log",
        project_root=project,
        oms_sqlite_filename="oms.sqlite3",
        broker_sqlite_filename="broker.sqlite3",
        account_selector="formal_paper_a_share_v1",
        source_selector="formal_source_v1",
        policy_selector="paper_a_share_v1",
        expected_schedule_selector="formal_schedule_v1",
        config_identity="4" * 64,
    )
    cold_layout = paper_runtime.PaperRuntimeLayout(
        parent,
        config.runtime_root,
        config.broker_root,
        config.evidence_root,
        config.anchor_root,
        config.log_root,
        "5" * 64,
        (("runtime", "a" * 64), ("broker", "b" * 64), ("evidence", "c" * 64), ("anchor", "d" * 64), ("log", "e" * 64)),
        "6" * 64,
    )
    materialized_layout = replace(
        cold_layout,
        root_identities=tuple(
            (name, "f" * 64 if name == "broker" else identity)
            for name, identity in cold_layout.root_identities
        ),
        layout_identity="7" * 64,
    )
    cold_environment = paper_runtime.VerifiedPaperRuntimeEnvironment(
        "paper-runtime-environment-v2",
        config,
        cold_layout,
        object(),  # type: ignore[arg-type]
        NOW,
        "8" * 64,
        paper_runtime._EnvironmentAttestation(b"test"),
    )
    materialized_environment = replace(
        cold_environment,
        layout=materialized_layout,
        verification_identity="9" * 64,
    )
    schedule = _schedule()
    policy = paper_policy.VerifiedPaperExecutionPolicy(
        "paper-execution-policy-v1",
        "paper_a_share_v1",
        NOW.date(),
        project / "policy.toml",
        "a" * 64,
        "b" * 64,
        "c" * 64,
        object(),  # type: ignore[arg-type]
        "d" * 64,
        (Market.SH, Market.SZ),
        schedule,
        paper_policy.paper_execution_cost_schedule_identity(schedule),
        (),
        "a-share-v1",
        "adapter-v1",
        "fill-v1",
        "fault-v1",
        "finality-v1",
        "clock-v1",
        None,
        "e" * 64,
        NOW,
        paper_policy._PolicyAttestation(b"test"),
    )
    binding = paper_broker_binding.VerifiedFormalPaperBrokerPolicyBinding(
        "formal-paper-broker-policy-binding-v1",
        "formal-paper-simulation",
        NOW.date(),
        cold_environment.verification_identity,
        config.config_identity,
        policy.policy_identity,
        policy.adapter_policy_version,
        policy.fill_policy_version,
        policy.fault_policy_version,
        policy.finality_policy_version,
        policy.clock_policy_version,
        policy.cost_schedule_identity,
        None,
        "f" * 64,
        NOW,
        paper_broker_binding._BindingAttestation(b"test"),
    )
    materialized_binding = replace(
        binding,
        runtime_environment_identity=materialized_environment.verification_identity,
        binding_identity="0" * 64,
    )
    snapshot = build_account_snapshot(
        as_of=NOW,
        positions=(),
        cash=(
            CashBalance(
                Currency.CNY,
                Decimal("500000.00"),
                Decimal("500000.00"),
                Decimal("0.00"),
                Decimal("0.00"),
            ),
        ),
    )
    account_descriptor = build_paper_account_descriptor(
        account_label="FORMAL_PAPER_A_SHARE",
        created_at=NOW,
        base_currency=Currency.CNY,
        initial_snapshot=snapshot,
    )
    account = paper_account.VerifiedFormalPaperAccountDescriptor(
        "formal-paper-account-v1",
        "formal-paper-simulation",
        NOW.date(),
        "formal_paper_a_share_v1",
        project / "account.toml",
        "1" * 64,
        "2" * 64,
        "3" * 64,
        cold_environment.verification_identity,
        config.config_identity,
        policy.policy_identity,
        binding.binding_identity,
        account_descriptor,
        account_descriptor.account_id,
        account_descriptor.initial_snapshot_identity,
        account_descriptor.descriptor_identity,
        f"paper-{account_descriptor.account_id}",
        "4" * 64,
        NOW,
        paper_account._AccountAttestation(b"test"),
    )
    materialized_account = replace(
        account,
        runtime_environment_identity=materialized_environment.verification_identity,
        broker_binding_identity=materialized_binding.binding_identity,
        verification_identity="5" * 64,
    )
    return (
        (cold_environment, policy, binding, account),
        (materialized_environment, policy, materialized_binding, materialized_account),
    )


def _allow_chain(
    monkeypatch: pytest.MonkeyPatch, materialized: tuple[object, ...]
) -> None:
    environment, policy, binding, account = materialized
    monkeypatch.setattr(formal, "verify_existing_paper_runtime_preflight", lambda *args, **kwargs: None)
    monkeypatch.setattr(formal, "verify_existing_paper_execution_policy", lambda **kwargs: kwargs["policy"])
    monkeypatch.setattr(formal, "verify_existing_formal_paper_broker_policy_binding", lambda **kwargs: kwargs["binding"])
    monkeypatch.setattr(formal, "verify_existing_formal_paper_account_descriptor", lambda **kwargs: kwargs["capability"])
    monkeypatch.setattr(formal, "verify_paper_runtime_environment", lambda **kwargs: environment)
    monkeypatch.setattr(formal, "load_verified_paper_execution_policy", lambda **kwargs: policy)
    monkeypatch.setattr(formal, "bind_verified_formal_paper_broker_policy", lambda **kwargs: binding)
    monkeypatch.setattr(formal, "load_verified_formal_paper_account_descriptor", lambda **kwargs: account)


def test_cold_initialize_existing_and_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cold, materialized = _chains(tmp_path)
    _allow_chain(monkeypatch, materialized)
    capability = formal.initialize_verified_formal_paper_broker_store(
        environment=cold[0], policy=cold[1], binding=cold[2], account=cold[3], now=NOW
    )
    assert capability.classification == "formal-paper-simulation"
    assert capability.account_id == materialized[3].account_id
    assert capability.store.account_descriptor == materialized[3].account_descriptor
    assert formal.verify_existing_formal_paper_broker_store_capability(
        capability=capability,
        environment=materialized[0],
        policy=materialized[1],
        binding=materialized[2],
        account=materialized[3],
        now=NOW,
    ) is capability
    reopened = formal.open_verified_formal_paper_broker_store(
        environment=materialized[0],
        policy=materialized[1],
        binding=materialized[2],
        account=materialized[3],
        now=NOW,
    )
    assert reopened.gateway_identity == capability.gateway_identity
    reopened.store.close()
    capability.store.close()


def test_formal_snapshot_port_fresh_verifies_each_query(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cold, materialized = _chains(tmp_path)
    _allow_chain(monkeypatch, materialized)
    capability = formal.initialize_verified_formal_paper_broker_store(
        environment=cold[0], policy=cold[1], binding=cold[2], account=cold[3], now=NOW
    )
    original = formal_snapshot.verify_existing_formal_paper_broker_store_capability
    calls = 0

    def counted(**kwargs):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        return original(**kwargs)

    monkeypatch.setattr(
        formal_snapshot,
        "verify_existing_formal_paper_broker_store_capability",
        counted,
    )
    port = formal_snapshot.open_verified_formal_paper_broker_snapshot_port(
        store_capability=capability,
        environment=materialized[0],
        policy=materialized[1],
        binding=materialized[2],
        account=materialized[3],
        now=NOW,
    )
    evidence = port.query_and_verify(gateway_identity=capability.gateway_identity)
    assert calls == 2
    assert evidence.gateway_identity == capability.gateway_identity
    assert evidence.account == materialized[3].account_descriptor.initial_snapshot
    assert evidence.orders == () and evidence.events == ()
    assert evidence.finality == "INTRADAY"
    capability.store.close()


def test_formal_snapshot_port_rejects_wrong_identity_and_hostile_fresh_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cold, materialized = _chains(tmp_path)
    _allow_chain(monkeypatch, materialized)
    capability = formal.initialize_verified_formal_paper_broker_store(
        environment=cold[0], policy=cold[1], binding=cold[2], account=cold[3], now=NOW
    )
    port = formal_snapshot.open_verified_formal_paper_broker_snapshot_port(
        store_capability=capability,
        environment=materialized[0],
        policy=materialized[1],
        binding=materialized[2],
        account=materialized[3],
        now=NOW,
    )
    with pytest.raises(formal_snapshot.FormalPaperBrokerSnapshotError) as caught:
        port.query_and_verify(gateway_identity="0" * 64)
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    monkeypatch.setattr(
        formal_snapshot,
        "verify_existing_formal_paper_broker_store_capability",
        lambda **kwargs: (_ for _ in ()).throw(
            RuntimeError("HOSTILE_FORMAL_SNAPSHOT_MARKER")
        ),
    )
    with pytest.raises(formal_snapshot.FormalPaperBrokerSnapshotError) as hostile:
        port.query_and_verify(gateway_identity=capability.gateway_identity)
    assert hostile.value.__cause__ is None and hostile.value.__context__ is None
    assert "HOSTILE" not in str(hostile.value)
    capability.store.close()


def test_exact_eod_mutation_helper_is_not_a_public_formal_api() -> None:
    assert "_finalize_and_query_formal_paper_broker_eod" not in (
        formal_snapshot.__all__
    )
    assert not hasattr(
        formal_snapshot, "finalize_and_query_verified_formal_paper_broker_eod"
    )


def test_failed_initialization_removes_only_owned_empty_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cold, materialized = _chains(tmp_path)
    _allow_chain(monkeypatch, materialized)
    monkeypatch.setattr(
        formal,
        "initialize_paper_broker_store",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("hostile")),
    )
    with pytest.raises(formal.FormalPaperBrokerStoreError) as caught:
        formal.initialize_verified_formal_paper_broker_store(
            environment=cold[0],
            policy=cold[1],
            binding=cold[2],
            account=cold[3],
            now=NOW,
        )
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert not cold[0].config.broker_root.exists()


def test_closed_and_forged_capabilities_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cold, materialized = _chains(tmp_path)
    _allow_chain(monkeypatch, materialized)
    capability = formal.initialize_verified_formal_paper_broker_store(
        environment=cold[0], policy=cold[1], binding=cold[2], account=cold[3], now=NOW
    )
    forged = replace(capability, account_id="0" * 64)
    with pytest.raises(formal.FormalPaperBrokerStoreError):
        formal.verify_existing_formal_paper_broker_store_capability(
            capability=forged,
            environment=materialized[0],
            policy=materialized[1],
            binding=materialized[2],
            account=materialized[3],
            now=NOW,
        )
    capability.store.close()
    with pytest.raises(formal.FormalPaperBrokerStoreError):
        formal.verify_existing_formal_paper_broker_store_capability(
            capability=capability,
            environment=materialized[0],
            policy=materialized[1],
            binding=materialized[2],
            account=materialized[3],
            now=NOW,
        )


def test_legacy_broker_local_cost_identity_rejected_by_formal_descriptor(
    tmp_path: Path,
) -> None:
    _, materialized = _chains(tmp_path)
    schedule = materialized[1].execution_cost_schedule
    legacy_identity = b1._digest(b1._cost_payload(schedule))
    canonical = paper_policy.paper_execution_cost_schedule_identity(schedule)
    assert legacy_identity != canonical
    assert materialized[1].cost_schedule_identity == canonical
    stale_policy = replace(materialized[1], cost_schedule_identity=legacy_identity)
    stale_binding = replace(materialized[2], cost_schedule_identity=legacy_identity)
    with pytest.raises(b1.PaperBrokerStoreError, match="^PAPER_BROKER_POLICY_INVALID$"):
        b1.build_formal_paper_broker_policy_descriptor(
            policy=stale_policy, binding=stale_binding
        )


def test_formal_policy_descriptor_and_b1_owned_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, materialized = _chains(tmp_path)
    descriptor = b1.build_formal_paper_broker_policy_descriptor(
        policy=materialized[1], binding=materialized[2]
    )
    assert descriptor.classification == "formal-paper-simulation"
    root = tmp_path / "rollback-broker"
    root.mkdir()
    account_descriptor = materialized[3].account_descriptor
    original = b1._exclusive_write
    calls = 0

    def fail_before_descriptor(path: Path, payload: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("hostile descriptor fault")
        original(path, payload)

    monkeypatch.setattr(b1, "_exclusive_write", fail_before_descriptor)
    with pytest.raises(b1.PaperBrokerStoreError) as caught:
        b1.initialize_paper_broker_store(
            root=root,
            database_filename="broker.sqlite3",
            oms_store_path=tmp_path / "runtime" / "oms.sqlite3",
            account=account_descriptor,
            policy=descriptor,
            created_at=account_descriptor.created_at,
        )
    assert caught.value.code == "PAPER_BROKER_INITIALIZE_FAILED"
    assert tuple(root.iterdir()) == ()


def test_rehashed_development_descriptor_cannot_impersonate_formal_source(
    tmp_path: Path,
) -> None:
    _, materialized = _chains(tmp_path)
    assert not hasattr(b1, "_FORMAL_POLICY_DESCRIPTORS")
    schedule = _schedule()
    development = b1.build_paper_broker_policy_descriptor(
        adapter_policy_version=materialized[1].adapter_policy_version,
        fill_policy_version=materialized[1].fill_policy_version,
        fault_policy_version=materialized[1].fault_policy_version,
        finality_policy_version=materialized[1].finality_policy_version,
        cost_schedule=schedule,
        fx_snapshot=None,
    )
    body = {
        "adapter_policy_version": development.adapter_policy_version,
        "classification": "formal-paper-simulation",
        "cost_schedule_identity": development.cost_schedule_identity,
        "fault_policy_version": development.fault_policy_version,
        "fill_policy_version": development.fill_policy_version,
        "finality_policy_version": development.finality_policy_version,
        "fx_snapshot_identity": development.fx_snapshot_identity,
        "schema_version": development.schema_version,
    }
    forged = replace(
        development,
        classification="formal-paper-simulation",
        descriptor_identity=b1._digest(body),
    )
    root = tmp_path / "forged-formal"
    root.mkdir()
    with pytest.raises(b1.PaperBrokerStoreError, match="PAPER_BROKER_POLICY_INVALID"):
        b1.initialize_paper_broker_store(
            root=root,
            database_filename="broker.sqlite3",
            oms_store_path=tmp_path / "runtime" / "oms.sqlite3",
            account=materialized[3].account_descriptor,
            policy=forged,
            created_at=materialized[3].account_descriptor.created_at,
        )
    assert tuple(root.iterdir()) == ()

    issued = b1.build_formal_paper_broker_policy_descriptor(
        policy=materialized[1], binding=materialized[2]
    )
    same_value_clone = replace(issued)
    assert same_value_clone == issued and same_value_clone is not issued
    clone_root = tmp_path / "cloned-formal"
    clone_root.mkdir()
    with pytest.raises(b1.PaperBrokerStoreError, match="PAPER_BROKER_POLICY_INVALID"):
        b1.initialize_paper_broker_store(
            root=clone_root,
            database_filename="broker.sqlite3",
            oms_store_path=tmp_path / "runtime" / "oms.sqlite3",
            account=materialized[3].account_descriptor,
            policy=same_value_clone,
            created_at=materialized[3].account_descriptor.created_at,
        )
    assert tuple(clone_root.iterdir()) == ()


def test_b1_rollback_preserves_unknown_concurrent_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, materialized = _chains(tmp_path)
    descriptor = b1.build_formal_paper_broker_policy_descriptor(
        policy=materialized[1], binding=materialized[2]
    )
    root = tmp_path / "rollback-concurrent"
    root.mkdir()
    original = b1._exclusive_write
    calls = 0

    def inject_foreign_then_fail(path: Path, payload: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            (root / "foreign.concurrent").write_bytes(b"external")
            raise OSError("hostile descriptor fault")
        original(path, payload)

    monkeypatch.setattr(b1, "_exclusive_write", inject_foreign_then_fail)
    with pytest.raises(b1.PaperBrokerStoreError) as caught:
        b1.initialize_paper_broker_store(
            root=root,
            database_filename="broker.sqlite3",
            oms_store_path=tmp_path / "runtime" / "oms.sqlite3",
            account=materialized[3].account_descriptor,
            policy=descriptor,
            created_at=materialized[3].account_descriptor.created_at,
        )
    assert caught.value.code == "PAPER_BROKER_ROLLBACK_REQUIRED"
    assert (root / "foreign.concurrent").read_bytes() == b"external"
    assert (root / "initial-account.json").exists()
