"""RUN-0B2E focused formal durable store capability tests."""

from __future__ import annotations

import datetime as dt
import sys
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
SESSION = NOW.date()


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


def _assert_store_error(error: formal.FormalPaperBrokerStoreError, code: str) -> None:
    assert error.code == code
    assert str(error) == code
    assert error.__cause__ is None
    assert error.__context__ is None


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
        (
            ("runtime", "a" * 64),
            ("broker", "b" * 64),
            ("evidence", "c" * 64),
            ("anchor", "d" * 64),
            ("log", "e" * 64),
        ),
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
    materialized_policy = replace(policy, policy_identity="1" * 64)
    materialized_binding = replace(
        binding,
        runtime_environment_identity=materialized_environment.verification_identity,
        execution_policy_identity=materialized_policy.policy_identity,
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
        execution_policy_identity=materialized_policy.policy_identity,
        broker_binding_identity=materialized_binding.binding_identity,
        verification_identity="5" * 64,
    )
    return (
        (cold_environment, policy, binding, account),
        (
            materialized_environment,
            materialized_policy,
            materialized_binding,
            materialized_account,
        ),
    )


def _allow_chain(
    monkeypatch: pytest.MonkeyPatch, materialized: tuple[object, ...]
) -> None:
    environment, policy, binding, account = materialized
    monkeypatch.setattr(
        formal, "verify_existing_paper_runtime_preflight", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        formal,
        "verify_existing_paper_execution_policy",
        lambda **kwargs: kwargs["policy"],
    )
    monkeypatch.setattr(
        formal,
        "verify_existing_formal_paper_broker_policy_binding",
        lambda **kwargs: kwargs["binding"],
    )
    monkeypatch.setattr(
        formal,
        "verify_existing_formal_paper_account_descriptor",
        lambda **kwargs: kwargs["capability"],
    )
    monkeypatch.setattr(
        formal, "verify_paper_runtime_environment", lambda **kwargs: environment
    )
    monkeypatch.setattr(
        formal, "load_verified_paper_execution_policy", lambda **kwargs: policy
    )
    monkeypatch.setattr(
        formal, "bind_verified_formal_paper_broker_policy", lambda **kwargs: binding
    )
    monkeypatch.setattr(
        formal,
        "load_verified_formal_paper_account_descriptor",
        lambda **kwargs: account,
    )


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
    assert (
        formal.verify_existing_formal_paper_broker_store_capability(
            capability=capability,
            environment=materialized[0],
            policy=materialized[1],
            binding=materialized[2],
            account=materialized[3],
            now=NOW,
        )
        is capability
    )
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


def test_canonical_cost_identity_positive_on_formal_descriptor(
    tmp_path: Path,
) -> None:
    _, materialized = _chains(tmp_path)
    schedule = materialized[1].execution_cost_schedule
    canonical = paper_policy.paper_execution_cost_schedule_identity(schedule)
    assert materialized[1].cost_schedule_identity == canonical
    assert materialized[2].cost_schedule_identity == canonical
    descriptor = b1.build_formal_paper_broker_policy_descriptor(
        policy=materialized[1], binding=materialized[2]
    )
    assert descriptor.cost_schedule_identity == canonical
    assert descriptor.cost_schedule_identity != b1._digest(b1._cost_payload(schedule))


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


def _write_public_formal_runtime_config(tmp_path: Path, *, mode: str) -> tuple[Path, Path]:
    parent = tmp_path / "paper-parent"
    parent.mkdir()
    roots = tuple(
        parent / name for name in ("runtime", "broker", "evidence", "anchor", "log")
    )
    project_root = paper_runtime._actual_project_root()
    config_parent = tmp_path / "config-parent"
    config_parent.mkdir()
    config_path = config_parent / "runtime.toml"
    config_path.write_text(
        f"""
[meta]
schema_version = "paper-runtime-config-v2"
runtime_version = "paper_runtime_v2"
mode = "{mode}"

[paths]
runtime_root = "{roots[0].as_posix()}"
broker_root = "{roots[1].as_posix()}"
evidence_root = "{roots[2].as_posix()}"
anchor_root = "{roots[3].as_posix()}"
log_root = "{roots[4].as_posix()}"
project_root = "{project_root.as_posix()}"

[store]
oms_sqlite_filename = "oms.sqlite3"
broker_sqlite_filename = "broker.sqlite3"

[selectors]
account_selector = "formal_paper_a_share_v1"
source_selector = "formal_source_v1"
policy_selector = "paper_a_share_v1"
expected_schedule_selector = "formal_schedule_v1"
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return config_path, roots[1]


def _public_cold_chain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[
    paper_runtime.VerifiedPaperRuntimeEnvironment,
    paper_policy.VerifiedPaperExecutionPolicy,
    paper_broker_binding.VerifiedFormalPaperBrokerPolicyBinding,
    paper_account.VerifiedFormalPaperAccountDescriptor,
]:
    """Real public cold chain; environment identity changes on materialization."""
    monkeypatch.setattr(
        paper_runtime, "_system_temp_root", lambda: tmp_path / "other-temp"
    )
    if sys.platform == "win32":
        monkeypatch.setenv("CONDA_PREFIX", r"D:\Miniforge3")
        monkeypatch.setenv("CONDA_DEFAULT_ENV", "base")
        mode = "PAPER_REAL_TIME_WINDOWS"
    else:
        mode = "PAPER_REAL_TIME"
    config_path, _broker = _write_public_formal_runtime_config(tmp_path, mode=mode)
    config = paper_runtime.load_paper_runtime_config(config_path.resolve())
    assert type(config) is paper_runtime.FormalPaperRuntimeConfig
    environment = paper_runtime.verify_paper_runtime_environment(config=config, now=NOW)
    policy = paper_policy.load_verified_paper_execution_policy(
        environment=environment, session_date=SESSION, now=NOW
    )
    binding = paper_broker_binding.bind_verified_formal_paper_broker_policy(
        environment=environment, policy=policy, now=NOW
    )
    account = paper_account.load_verified_formal_paper_account_descriptor(
        environment=environment, policy=policy, binding=binding, now=NOW
    )
    return environment, policy, binding, account


def _reload_public_materialized(
    environment: paper_runtime.VerifiedPaperRuntimeEnvironment,
    *,
    session_date: dt.date,
) -> tuple[
    paper_runtime.VerifiedPaperRuntimeEnvironment,
    paper_policy.VerifiedPaperExecutionPolicy,
    paper_broker_binding.VerifiedFormalPaperBrokerPolicyBinding,
    paper_account.VerifiedFormalPaperAccountDescriptor,
]:
    materialized_environment = paper_runtime.verify_paper_runtime_environment(
        config=environment.config, now=NOW
    )
    materialized_policy = paper_policy.load_verified_paper_execution_policy(
        environment=materialized_environment, session_date=session_date, now=NOW
    )
    materialized_binding = paper_broker_binding.bind_verified_formal_paper_broker_policy(
        environment=materialized_environment,
        policy=materialized_policy,
        now=NOW,
    )
    materialized_account = paper_account.load_verified_formal_paper_account_descriptor(
        environment=materialized_environment,
        policy=materialized_policy,
        binding=materialized_binding,
        now=NOW,
    )
    return (
        materialized_environment,
        materialized_policy,
        materialized_binding,
        materialized_account,
    )


def test_public_chain_cold_materialization_changes_identity_and_returns_fresh_capability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Real public chain: cold≠materialized identities; initializer still succeeds."""
    cold_environment, cold_policy, cold_binding, cold_account = _public_cold_chain(
        tmp_path, monkeypatch
    )
    cold_env_identity = cold_environment.verification_identity
    cold_policy_identity = cold_policy.policy_identity
    cold_binding_identity = cold_binding.binding_identity
    cold_account_identity = cold_account.verification_identity
    cold_broker_identity = dict(cold_environment.layout.root_identities)["broker"]
    assert not cold_environment.config.broker_root.exists()
    assert len(cold_broker_identity) == 64
    assert all(character in "0123456789abcdef" for character in cold_broker_identity)
    assert cold_policy.cost_schedule_identity == (
        paper_policy.paper_execution_cost_schedule_identity(
            cold_policy.execution_cost_schedule
        )
    )

    capability = formal.initialize_verified_formal_paper_broker_store(
        environment=cold_environment,
        policy=cold_policy,
        binding=cold_binding,
        account=cold_account,
        now=NOW,
    )
    (
        materialized_environment,
        materialized_policy,
        materialized_binding,
        materialized_account,
    ) = _reload_public_materialized(cold_environment, session_date=SESSION)

    assert cold_environment.config.broker_root.is_dir()
    assert cold_env_identity != materialized_environment.verification_identity
    assert cold_policy_identity != materialized_policy.policy_identity
    assert cold_binding_identity != materialized_binding.binding_identity
    assert cold_account_identity != materialized_account.verification_identity
    assert capability.broker_root_identity != cold_broker_identity
    assert capability.broker_root_identity == dict(
        materialized_environment.layout.root_identities
    )["broker"]
    assert (
        capability.runtime_environment_identity
        == materialized_environment.verification_identity
    )
    assert capability.execution_policy_identity == materialized_policy.policy_identity
    assert capability.broker_binding_identity == materialized_binding.binding_identity
    assert (
        capability.account_verification_identity
        == materialized_account.verification_identity
    )
    assert capability.runtime_environment_identity != cold_env_identity
    assert capability.execution_policy_identity != cold_policy_identity
    assert (
        formal.verify_existing_formal_paper_broker_store_capability(
            capability=capability,
            environment=materialized_environment,
            policy=materialized_policy,
            binding=materialized_binding,
            account=materialized_account,
            now=NOW,
        )
        is capability
    )
    reopened = formal.open_verified_formal_paper_broker_store(
        environment=materialized_environment,
        policy=materialized_policy,
        binding=materialized_binding,
        account=materialized_account,
        now=NOW,
    )
    assert reopened.gateway_identity == capability.gateway_identity
    assert reopened.runtime_environment_identity == (
        materialized_environment.verification_identity
    )
    reopened.store.close()
    capability.store.close()


def test_public_chain_final_capability_does_not_reuse_cold_objects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cold_environment, cold_policy, cold_binding, cold_account = _public_cold_chain(
        tmp_path, monkeypatch
    )
    cold_broker_identity = dict(cold_environment.layout.root_identities)["broker"]
    assert not cold_environment.config.broker_root.exists()
    capability = formal.initialize_verified_formal_paper_broker_store(
        environment=cold_environment,
        policy=cold_policy,
        binding=cold_binding,
        account=cold_account,
        now=NOW,
    )
    (
        materialized_environment,
        materialized_policy,
        materialized_binding,
        materialized_account,
    ) = _reload_public_materialized(cold_environment, session_date=SESSION)
    assert cold_environment.config.broker_root.is_dir()
    assert capability.runtime_environment_identity != (
        cold_environment.verification_identity
    )
    assert capability.execution_policy_identity != cold_policy.policy_identity
    assert capability.broker_binding_identity != cold_binding.binding_identity
    assert capability.account_verification_identity != (
        cold_account.verification_identity
    )
    assert capability.broker_root_identity != cold_broker_identity
    assert capability.account_id == materialized_account.account_id
    assert (
        capability.store.account_descriptor
        == materialized_account.account_descriptor
    )
    assert capability.runtime_layout_identity == (
        materialized_environment.layout.layout_identity
    )
    with pytest.raises(formal.FormalPaperBrokerStoreError) as caught:
        formal.verify_existing_formal_paper_broker_store_capability(
            capability=capability,
            environment=cold_environment,
            policy=cold_policy,
            binding=cold_binding,
            account=cold_account,
            now=NOW,
        )
    _assert_store_error(caught.value, "PAPER_FORMAL_STORE_ENVIRONMENT_INVALID")
    capability.store.close()
    del materialized_policy, materialized_binding


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", "hostile-policy-schema"),
        ("raw_sha256", "f" * 64),
        ("selector", "paper_a_share_v1_hostile"),
        ("session_date", dt.date(2026, 1, 2)),
        ("source_path", Path("/hostile/policy.toml")),
        ("source_file_identity", "f" * 64),
        ("source_parent_identity", "f" * 64),
        ("adapter_policy_version", "hostile-adapter"),
        ("fill_policy_version", "hostile-fill"),
        ("fault_policy_version", "hostile-fault"),
        ("finality_policy_version", "hostile-finality"),
        ("clock_policy_version", "hostile-clock"),
        ("cost_schedule_identity", "f" * 64),
        ("trading_config_identity", "f" * 64),
        ("trading_config", object()),
        ("supported_markets", (Market.SH,)),
        ("a_share_rule_selector", "hostile-a-share"),
        (
            "minimum_order_notionals",
            "SENTINEL_NONEMPTY_NOTIONAL",
        ),
        (
            "execution_cost_schedule",
            "SENTINEL_HOSTILE_SCHEDULE",
        ),
    ],
)
def test_economic_policy_drift_rejects_cold_materialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
) -> None:
    from quant.execution.contracts import build_money_amount

    cold, materialized = _chains(tmp_path)
    if value == "SENTINEL_NONEMPTY_NOTIONAL":
        value = (build_money_amount(Currency.CNY, Decimal("1.00")),)
    elif value == "SENTINEL_HOSTILE_SCHEDULE":
        value = build_execution_cost_schedule(
            selector="hostile-cost-v1",
            periods=(
                ExecutionCostPeriod(
                    Market.SH,
                    dt.date(2026, 1, 1),
                    None,
                    Decimal("0.0004"),
                    Decimal("5"),
                    Decimal("0.0005"),
                    Decimal("0.00001"),
                    Currency.CNY,
                ),
            ),
        )
    drifted = replace(materialized[1], **{field: value})
    # Keep joins closed so the failure is purely economic.
    closed_binding = replace(
        materialized[2], execution_policy_identity=drifted.policy_identity
    )
    closed_account = replace(
        materialized[3],
        execution_policy_identity=drifted.policy_identity,
        broker_binding_identity=closed_binding.binding_identity,
    )
    _allow_chain(
        monkeypatch, (materialized[0], drifted, closed_binding, closed_account)
    )
    with pytest.raises(formal.FormalPaperBrokerStoreError) as caught:
        formal.initialize_verified_formal_paper_broker_store(
            environment=cold[0],
            policy=cold[1],
            binding=cold[2],
            account=cold[3],
            now=NOW,
        )
    _assert_store_error(caught.value, "PAPER_FORMAL_STORE_STALE")
    assert not cold[0].config.broker_root.exists()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", "hostile-binding-schema"),
        ("session_date", dt.date(2026, 1, 2)),
        ("runtime_config_identity", "f" * 64),
        ("adapter_policy_version", "hostile-adapter"),
        ("fill_policy_version", "hostile-fill"),
        ("fault_policy_version", "hostile-fault"),
        ("finality_policy_version", "hostile-finality"),
        ("clock_policy_version", "hostile-clock"),
        ("cost_schedule_identity", "f" * 64),
    ],
)
def test_economic_binding_drift_rejects_cold_materialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
) -> None:
    cold, materialized = _chains(tmp_path)
    drifted_binding = replace(materialized[2], **{field: value})
    closed_account = replace(
        materialized[3],
        broker_binding_identity=drifted_binding.binding_identity,
        execution_policy_identity=materialized[1].policy_identity,
    )
    _allow_chain(
        monkeypatch,
        (materialized[0], materialized[1], drifted_binding, closed_account),
    )
    with pytest.raises(formal.FormalPaperBrokerStoreError) as caught:
        formal.initialize_verified_formal_paper_broker_store(
            environment=cold[0],
            policy=cold[1],
            binding=cold[2],
            account=cold[3],
            now=NOW,
        )
    _assert_store_error(caught.value, "PAPER_FORMAL_STORE_STALE")
    assert not cold[0].config.broker_root.exists()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", "hostile-account-schema"),
        ("selector", "formal_paper_a_share_hostile"),
        ("source_path", Path("/hostile/account.toml")),
        ("source_file_identity", "f" * 64),
        ("source_parent_identity", "f" * 64),
        ("raw_sha256", "f" * 64),
        ("runtime_config_identity", "f" * 64),
        ("risk_counter_scope", "hostile-scope"),
        ("initial_snapshot_identity", "f" * 64),
    ],
)
def test_economic_account_field_drift_rejects_cold_materialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
) -> None:
    cold, materialized = _chains(tmp_path)
    drifted_account = replace(materialized[3], **{field: value})
    _allow_chain(
        monkeypatch,
        (materialized[0], materialized[1], materialized[2], drifted_account),
    )
    with pytest.raises(formal.FormalPaperBrokerStoreError) as caught:
        formal.initialize_verified_formal_paper_broker_store(
            environment=cold[0],
            policy=cold[1],
            binding=cold[2],
            account=cold[3],
            now=NOW,
        )
    _assert_store_error(caught.value, "PAPER_FORMAL_STORE_STALE")
    assert not cold[0].config.broker_root.exists()


def test_economic_account_descriptor_drift_rejects_cold_materialization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cold, materialized = _chains(tmp_path)
    drifted_descriptor = replace(
        materialized[3].account_descriptor, account_label="HOSTILE"
    )
    drifted_account = replace(
        materialized[3],
        account_descriptor=drifted_descriptor,
        account_id=drifted_descriptor.account_id,
        descriptor_identity=drifted_descriptor.descriptor_identity,
    )
    _allow_chain(
        monkeypatch,
        (materialized[0], materialized[1], materialized[2], drifted_account),
    )
    with pytest.raises(formal.FormalPaperBrokerStoreError) as caught:
        formal.initialize_verified_formal_paper_broker_store(
            environment=cold[0],
            policy=cold[1],
            binding=cold[2],
            account=cold[3],
            now=NOW,
        )
    _assert_store_error(caught.value, "PAPER_FORMAL_STORE_STALE")
    assert not cold[0].config.broker_root.exists()


def test_ae1_new_env_reusing_cold_policy_binding_account_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AE-1: env identities change but loaders reuse cold policy/binding/account."""
    cold, materialized = _chains(tmp_path)
    _allow_chain(
        monkeypatch, (materialized[0], cold[1], cold[2], cold[3])
    )
    with pytest.raises(formal.FormalPaperBrokerStoreError) as caught:
        formal.initialize_verified_formal_paper_broker_store(
            environment=cold[0],
            policy=cold[1],
            binding=cold[2],
            account=cold[3],
            now=NOW,
        )
    _assert_store_error(caught.value, "PAPER_FORMAL_STORE_STALE")
    assert not cold[0].config.broker_root.exists()


def test_ae1_patched_env_text_keeps_cold_execution_policy_identity_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AE-1 variant: binding/account env text updated; execution_policy stays cold."""
    cold, materialized = _chains(tmp_path)
    hostile_policy = cold[1]
    hostile_binding = replace(
        cold[2],
        runtime_environment_identity=materialized[0].verification_identity,
        binding_identity=materialized[2].binding_identity,
    )
    hostile_account = replace(
        cold[3],
        runtime_environment_identity=materialized[0].verification_identity,
        broker_binding_identity=hostile_binding.binding_identity,
        verification_identity=materialized[3].verification_identity,
    )
    _allow_chain(
        monkeypatch,
        (materialized[0], hostile_policy, hostile_binding, hostile_account),
    )
    with pytest.raises(formal.FormalPaperBrokerStoreError) as caught:
        formal.initialize_verified_formal_paper_broker_store(
            environment=cold[0],
            policy=cold[1],
            binding=cold[2],
            account=cold[3],
            now=NOW,
        )
    _assert_store_error(caught.value, "PAPER_FORMAL_STORE_STALE")
    assert not cold[0].config.broker_root.exists()


def test_ae2_forged_cold_layout_after_mkdir_fails_environment_invalid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Hostile materialization loaders reuse cold layout; real preflight rejects."""
    cold_environment, cold_policy, cold_binding, cold_account = _public_cold_chain(
        tmp_path, monkeypatch
    )
    assert not cold_environment.config.broker_root.exists()
    monkeypatch.setattr(
        formal,
        "verify_paper_runtime_environment",
        lambda **kwargs: cold_environment,
    )
    monkeypatch.setattr(
        formal,
        "load_verified_paper_execution_policy",
        lambda **kwargs: cold_policy,
    )
    monkeypatch.setattr(
        formal,
        "bind_verified_formal_paper_broker_policy",
        lambda **kwargs: cold_binding,
    )
    monkeypatch.setattr(
        formal,
        "load_verified_formal_paper_account_descriptor",
        lambda **kwargs: cold_account,
    )
    with pytest.raises(formal.FormalPaperBrokerStoreError) as caught:
        formal.initialize_verified_formal_paper_broker_store(
            environment=cold_environment,
            policy=cold_policy,
            binding=cold_binding,
            account=cold_account,
            now=NOW,
        )
    _assert_store_error(caught.value, "PAPER_FORMAL_STORE_ENVIRONMENT_INVALID")
    assert not cold_environment.config.broker_root.exists()


@pytest.mark.parametrize(
    "break_join",
    [
        "binding_runtime_environment",
        "binding_runtime_config",
        "binding_execution_policy",
        "account_runtime_environment",
        "account_runtime_config",
        "account_execution_policy",
        "account_broker_binding",
        "policy_identity_unchanged",
        "binding_identity_unchanged",
        "account_verification_unchanged",
    ],
)
def test_materialized_chain_join_or_derived_freshness_mismatch_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, break_join: str
) -> None:
    cold, materialized = _chains(tmp_path)
    environment, policy, binding, account = materialized
    if break_join == "binding_runtime_environment":
        binding = replace(binding, runtime_environment_identity="dead" * 16)
    elif break_join == "binding_runtime_config":
        binding = replace(binding, runtime_config_identity="dead" * 16)
    elif break_join == "binding_execution_policy":
        binding = replace(binding, execution_policy_identity="dead" * 16)
    elif break_join == "account_runtime_environment":
        account = replace(account, runtime_environment_identity="dead" * 16)
    elif break_join == "account_runtime_config":
        account = replace(account, runtime_config_identity="dead" * 16)
    elif break_join == "account_execution_policy":
        account = replace(account, execution_policy_identity="dead" * 16)
    elif break_join == "account_broker_binding":
        account = replace(account, broker_binding_identity="dead" * 16)
    elif break_join == "policy_identity_unchanged":
        policy = replace(policy, policy_identity=cold[1].policy_identity)
        binding = replace(
            binding, execution_policy_identity=policy.policy_identity
        )
        account = replace(
            account, execution_policy_identity=policy.policy_identity
        )
    elif break_join == "binding_identity_unchanged":
        binding = replace(binding, binding_identity=cold[2].binding_identity)
        account = replace(
            account, broker_binding_identity=binding.binding_identity
        )
    else:
        account = replace(
            account, verification_identity=cold[3].verification_identity
        )
    _allow_chain(monkeypatch, (environment, policy, binding, account))
    with pytest.raises(formal.FormalPaperBrokerStoreError) as caught:
        formal.initialize_verified_formal_paper_broker_store(
            environment=cold[0],
            policy=cold[1],
            binding=cold[2],
            account=cold[3],
            now=NOW,
        )
    _assert_store_error(caught.value, "PAPER_FORMAL_STORE_STALE")
    assert not cold[0].config.broker_root.exists()


def test_unchanged_layout_identity_across_materialization_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cold, materialized = _chains(tmp_path)
    # Keep physical broker root present so _require_materialized passes; only
    # freeze verification/layout identities to the cold values.
    hostile_environment = replace(
        materialized[0],
        layout=replace(
            materialized[0].layout,
            layout_identity=cold[0].layout.layout_identity,
        ),
        verification_identity=cold[0].verification_identity,
    )
    hostile_binding = replace(
        materialized[2],
        runtime_environment_identity=hostile_environment.verification_identity,
    )
    hostile_account = replace(
        materialized[3],
        runtime_environment_identity=hostile_environment.verification_identity,
        broker_binding_identity=hostile_binding.binding_identity,
    )
    _allow_chain(
        monkeypatch,
        (hostile_environment, materialized[1], hostile_binding, hostile_account),
    )
    with pytest.raises(formal.FormalPaperBrokerStoreError) as caught:
        formal.initialize_verified_formal_paper_broker_store(
            environment=cold[0],
            policy=cold[1],
            binding=cold[2],
            account=cold[3],
            now=NOW,
        )
    _assert_store_error(caught.value, "PAPER_FORMAL_STORE_STALE")
    assert not cold[0].config.broker_root.exists()


def test_final_capability_binds_fresh_materialized_identities_not_cold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cold, materialized = _chains(tmp_path)
    _allow_chain(monkeypatch, materialized)
    capability = formal.initialize_verified_formal_paper_broker_store(
        environment=cold[0], policy=cold[1], binding=cold[2], account=cold[3], now=NOW
    )
    assert capability.runtime_environment_identity == (
        materialized[0].verification_identity
    )
    assert capability.execution_policy_identity == materialized[1].policy_identity
    assert capability.broker_binding_identity == materialized[2].binding_identity
    assert capability.account_verification_identity == (
        materialized[3].verification_identity
    )
    assert capability.runtime_environment_identity != cold[0].verification_identity
    assert capability.execution_policy_identity != cold[1].policy_identity
    assert capability.broker_binding_identity != cold[2].binding_identity
    assert capability.account_verification_identity != cold[3].verification_identity
    assert (
        formal.verify_existing_formal_paper_broker_store_capability(
            capability=capability,
            environment=materialized[0],
            policy=materialized[1],
            binding=materialized[2],
            account=materialized[3],
            now=NOW,
        )
        is capability
    )
    capability.store.close()


def test_cross_session_and_cross_account_capability_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cold, materialized = _chains(tmp_path)
    _allow_chain(monkeypatch, materialized)
    capability = formal.initialize_verified_formal_paper_broker_store(
        environment=cold[0], policy=cold[1], binding=cold[2], account=cold[3], now=NOW
    )
    other_session_policy = replace(materialized[1], session_date=dt.date(2026, 8, 13))
    with pytest.raises(formal.FormalPaperBrokerStoreError):
        formal.verify_existing_formal_paper_broker_store_capability(
            capability=capability,
            environment=materialized[0],
            policy=other_session_policy,
            binding=materialized[2],
            account=materialized[3],
            now=NOW,
        )
    other_account = replace(materialized[3], account_id="0" * 64)
    with pytest.raises(formal.FormalPaperBrokerStoreError):
        formal.verify_existing_formal_paper_broker_store_capability(
            capability=capability,
            environment=materialized[0],
            policy=materialized[1],
            binding=materialized[2],
            account=other_account,
            now=NOW,
        )
    wrong_root = replace(
        materialized[0],
        layout=replace(
            materialized[0].layout,
            root_identities=(
                ("runtime", "a" * 64),
                ("broker", "wrong-root-identity"),
                ("evidence", "c" * 64),
                ("anchor", "d" * 64),
                ("log", "e" * 64),
            ),
            layout_identity="wrong-layout",
        ),
    )
    with pytest.raises(formal.FormalPaperBrokerStoreError):
        formal.verify_existing_formal_paper_broker_store_capability(
            capability=capability,
            environment=wrong_root,
            policy=materialized[1],
            binding=materialized[2],
            account=materialized[3],
            now=NOW,
        )
    capability.store.close()


def test_preexisting_broker_root_and_separation_conflict_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cold, materialized = _chains(tmp_path)
    _allow_chain(monkeypatch, materialized)
    cold[0].config.broker_root.mkdir()
    with pytest.raises(formal.FormalPaperBrokerStoreError) as exists:
        formal.initialize_verified_formal_paper_broker_store(
            environment=cold[0],
            policy=cold[1],
            binding=cold[2],
            account=cold[3],
            now=NOW,
        )
    _assert_store_error(exists.value, "PAPER_FORMAL_STORE_ALREADY_EXISTS")

    sep = tmp_path / "sep"
    sep.mkdir()
    cold2, materialized2 = _chains(sep)
    _allow_chain(monkeypatch, materialized2)
    nested = replace(
        cold2[0].config,
        oms_sqlite_filename="nested.sqlite3",
        runtime_root=cold2[0].config.broker_root / "inside",
    )
    nested_environment = replace(cold2[0], config=nested)
    with pytest.raises(formal.FormalPaperBrokerStoreError) as separation:
        formal.initialize_verified_formal_paper_broker_store(
            environment=nested_environment,
            policy=cold2[1],
            binding=cold2[2],
            account=cold2[3],
            now=NOW,
        )
    _assert_store_error(separation.value, "PAPER_FORMAL_STORE_SEPARATION_INVALID")


def test_partial_sibling_and_symlink_broker_root_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cold, materialized = _chains(tmp_path)
    _allow_chain(monkeypatch, materialized)
    cold[0].config.broker_root.mkdir()
    (cold[0].config.broker_root / "unauthorized.partial").write_bytes(b"foreign")
    with pytest.raises(formal.FormalPaperBrokerStoreError) as partial:
        formal.initialize_verified_formal_paper_broker_store(
            environment=cold[0],
            policy=cold[1],
            binding=cold[2],
            account=cold[3],
            now=NOW,
        )
    _assert_store_error(partial.value, "PAPER_FORMAL_STORE_ALREADY_EXISTS")
    assert (cold[0].config.broker_root / "unauthorized.partial").read_bytes() == (
        b"foreign"
    )

    link = tmp_path / "link"
    link.mkdir()
    cold2, materialized2 = _chains(link)
    _allow_chain(monkeypatch, materialized2)
    target = tmp_path / "link-target"
    target.mkdir()
    try:
        cold2[0].config.broker_root.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks unavailable")
    with pytest.raises(formal.FormalPaperBrokerStoreError) as caught:
        formal.initialize_verified_formal_paper_broker_store(
            environment=cold2[0],
            policy=cold2[1],
            binding=cold2[2],
            account=cold2[3],
            now=NOW,
        )
    assert caught.value.code in {
        "PAPER_FORMAL_STORE_ALREADY_EXISTS",
        "PAPER_FORMAL_STORE_LAYOUT_INVALID",
        "PAPER_FORMAL_STORE_INVALID",
    }


def test_rollback_preserves_unknown_wal_after_formal_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cold, materialized = _chains(tmp_path)
    _allow_chain(monkeypatch, materialized)
    original = b1.initialize_paper_broker_store

    def inject_wal_then_fail(**kwargs):  # type: ignore[no-untyped-def]
        store = original(**kwargs)
        root = Path(store.descriptor.resolved_root)
        (root / "broker.sqlite3-wal").write_bytes(b"foreign-wal")
        store.close()
        raise RuntimeError("fail after formal bytes")

    monkeypatch.setattr(formal, "initialize_paper_broker_store", inject_wal_then_fail)
    with pytest.raises(formal.FormalPaperBrokerStoreError) as caught:
        formal.initialize_verified_formal_paper_broker_store(
            environment=cold[0],
            policy=cold[1],
            binding=cold[2],
            account=cold[3],
            now=NOW,
        )
    _assert_store_error(caught.value, "PAPER_FORMAL_STORE_ROLLBACK_REQUIRED")
    assert cold[0].config.broker_root.exists()
    assert (cold[0].config.broker_root / "broker.sqlite3-wal").read_bytes() == (
        b"foreign-wal"
    )


def test_compare_failure_before_store_bytes_rolls_back_empty_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cold, materialized = _chains(tmp_path)
    drifted = replace(materialized[1], raw_sha256="a" * 64)
    _allow_chain(
        monkeypatch, (materialized[0], drifted, materialized[2], materialized[3])
    )
    with pytest.raises(formal.FormalPaperBrokerStoreError) as caught:
        formal.initialize_verified_formal_paper_broker_store(
            environment=cold[0],
            policy=cold[1],
            binding=cold[2],
            account=cold[3],
            now=NOW,
        )
    _assert_store_error(caught.value, "PAPER_FORMAL_STORE_STALE")
    assert not cold[0].config.broker_root.exists()


def test_public_loader_wrappers_and_wrong_return_types_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cold, materialized = _chains(tmp_path)
    _allow_chain(monkeypatch, materialized)

    monkeypatch.setattr(
        formal,
        "verify_paper_runtime_environment",
        lambda **kwargs: object(),
    )
    with pytest.raises(formal.FormalPaperBrokerStoreError) as wrong_type:
        formal.initialize_verified_formal_paper_broker_store(
            environment=cold[0],
            policy=cold[1],
            binding=cold[2],
            account=cold[3],
            now=NOW,
        )
    _assert_store_error(wrong_type.value, "PAPER_FORMAL_STORE_ENVIRONMENT_INVALID")
    assert not cold[0].config.broker_root.exists()

    stale_env_root = tmp_path / "stale-env"
    stale_env_root.mkdir()
    cold2, _materialized2 = _chains(stale_env_root)
    # Allow cold existing-chain once; leave public preflight active for the
    # post-mkdir materialized `_verify_existing_chain` against forged cold layout.
    real_preflight = paper_runtime.verify_existing_paper_runtime_preflight
    preflight_calls = {"count": 0}

    def preflight_cold_then_real(*args, **kwargs):  # type: ignore[no-untyped-def]
        preflight_calls["count"] += 1
        if preflight_calls["count"] == 1:
            return None
        return real_preflight(*args, **kwargs)

    monkeypatch.setattr(
        formal, "verify_existing_paper_runtime_preflight", preflight_cold_then_real
    )
    monkeypatch.setattr(
        formal,
        "verify_existing_paper_execution_policy",
        lambda **kwargs: kwargs["policy"],
    )
    monkeypatch.setattr(
        formal,
        "verify_existing_formal_paper_broker_policy_binding",
        lambda **kwargs: kwargs["binding"],
    )
    monkeypatch.setattr(
        formal,
        "verify_existing_formal_paper_account_descriptor",
        lambda **kwargs: kwargs["capability"],
    )
    monkeypatch.setattr(
        formal,
        "verify_paper_runtime_environment",
        lambda **kwargs: cold2[0],
    )
    monkeypatch.setattr(
        formal,
        "load_verified_paper_execution_policy",
        lambda **kwargs: cold2[1],
    )
    monkeypatch.setattr(
        formal,
        "bind_verified_formal_paper_broker_policy",
        lambda **kwargs: cold2[2],
    )
    monkeypatch.setattr(
        formal,
        "load_verified_formal_paper_account_descriptor",
        lambda **kwargs: cold2[3],
    )
    with pytest.raises(formal.FormalPaperBrokerStoreError) as stale_env:
        formal.initialize_verified_formal_paper_broker_store(
            environment=cold2[0],
            policy=cold2[1],
            binding=cold2[2],
            account=cold2[3],
            now=NOW,
        )
    _assert_store_error(stale_env.value, "PAPER_FORMAL_STORE_ENVIRONMENT_INVALID")
    assert not cold2[0].config.broker_root.exists()
    assert preflight_calls["count"] >= 2

    policy_wrapper = tmp_path / "policy-wrapper"
    policy_wrapper.mkdir()
    cold3, materialized3 = _chains(policy_wrapper)
    _allow_chain(monkeypatch, materialized3)
    monkeypatch.setattr(
        formal,
        "load_verified_paper_execution_policy",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("HOSTILE_POLICY")),
    )
    with pytest.raises(formal.FormalPaperBrokerStoreError) as policy_wrap:
        formal.initialize_verified_formal_paper_broker_store(
            environment=cold3[0],
            policy=cold3[1],
            binding=cold3[2],
            account=cold3[3],
            now=NOW,
        )
    _assert_store_error(policy_wrap.value, "PAPER_FORMAL_STORE_INVALID")
    assert "HOSTILE" not in str(policy_wrap.value)
    assert not cold3[0].config.broker_root.exists()


def test_legacy_initializer_open_verify_error_codes_do_not_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cold, materialized = _chains(tmp_path)
    _allow_chain(monkeypatch, materialized)
    capability = formal.initialize_verified_formal_paper_broker_store(
        environment=cold[0], policy=cold[1], binding=cold[2], account=cold[3], now=NOW
    )
    assert capability.classification == "formal-paper-simulation"
    assert (
        formal.verify_existing_formal_paper_broker_store_capability(
            capability=capability,
            environment=materialized[0],
            policy=materialized[1],
            binding=materialized[2],
            account=materialized[3],
            now=NOW,
        )
        is capability
    )
    reopened = formal.open_verified_formal_paper_broker_store(
        environment=materialized[0],
        policy=materialized[1],
        binding=materialized[2],
        account=materialized[3],
        now=NOW,
    )
    assert reopened.account_id == capability.account_id
    reopened.store.close()
    capability.store.close()

    missing_root = tmp_path / "missing"
    missing_root.mkdir()
    cold_missing, materialized_missing = _chains(missing_root)
    _allow_chain(monkeypatch, materialized_missing)
    with pytest.raises(formal.FormalPaperBrokerStoreError) as missing:
        formal.open_verified_formal_paper_broker_store(
            environment=materialized_missing[0],
            policy=materialized_missing[1],
            binding=materialized_missing[2],
            account=materialized_missing[3],
            now=NOW,
        )
    _assert_store_error(missing.value, "PAPER_FORMAL_STORE_NOT_FOUND")

    again = tmp_path / "again"
    again.mkdir()
    cold2, materialized2 = _chains(again)
    _allow_chain(monkeypatch, materialized2)
    cold2[0].config.broker_root.mkdir()
    with pytest.raises(formal.FormalPaperBrokerStoreError) as exists:
        formal.initialize_verified_formal_paper_broker_store(
            environment=cold2[0],
            policy=cold2[1],
            binding=cold2[2],
            account=cold2[3],
            now=NOW,
        )
    _assert_store_error(exists.value, "PAPER_FORMAL_STORE_ALREADY_EXISTS")
