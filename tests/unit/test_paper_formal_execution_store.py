"""RUN-0B2G-F0 formal OMS ExecutionStore capability tests."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from quant.execution import paper_formal_broker_store as formal_broker
from quant.execution import paper_formal_execution_store as formal_oms
from quant.execution.session_barrier import (
    SessionBarrierClosureCapability,
    SessionBarrierError,
    transition_closing_to_closed,
    unpack_session_barrier_closure_capability,
)
from quant.execution.store import StoreError
from tests.unit.test_paper_formal_broker_store import NOW, _allow_chain, _chains
from tests.unit.test_paper_formal_gateway import _approved_bundle


def _full_chain(capability, chain):  # type: ignore[no-untyped-def]
    environment, policy, binding, account = chain
    layout = replace(
        environment.layout,
        root_identities=tuple(
            (name, "1" * 64 if name == "runtime" else identity)
            for name, identity in environment.layout.root_identities
        ),
        layout_identity="2" * 64,
    )
    environment = replace(
        environment, layout=layout, verification_identity="3" * 64
    )
    policy = replace(policy, policy_identity="4" * 64)
    binding = replace(
        binding,
        runtime_environment_identity=environment.verification_identity,
        execution_policy_identity=policy.policy_identity,
        binding_identity="5" * 64,
    )
    account = replace(
        account,
        runtime_environment_identity=environment.verification_identity,
        execution_policy_identity=policy.policy_identity,
        broker_binding_identity=binding.binding_identity,
        verification_identity="6" * 64,
    )
    broker = replace(
        capability,
        runtime_environment_identity=environment.verification_identity,
        runtime_layout_identity=layout.layout_identity,
        execution_policy_identity=policy.policy_identity,
        broker_binding_identity=binding.binding_identity,
        account_verification_identity=account.verification_identity,
        capability_identity="7" * 64,
    )
    return (environment, policy, binding, account), broker


def _allow_materialization(
    monkeypatch: pytest.MonkeyPatch, full, broker  # type: ignore[no-untyped-def]
) -> None:
    environment, policy, binding, account = full
    monkeypatch.setattr(
        formal_oms,
        "verify_existing_formal_paper_broker_store_capability",
        lambda **kwargs: kwargs["capability"],
    )
    monkeypatch.setattr(
        formal_oms, "verify_paper_runtime_environment", lambda **kwargs: environment
    )
    monkeypatch.setattr(
        formal_oms, "load_verified_paper_execution_policy", lambda **kwargs: policy
    )
    monkeypatch.setattr(
        formal_oms,
        "bind_verified_formal_paper_broker_policy",
        lambda **kwargs: binding,
    )
    monkeypatch.setattr(
        formal_oms,
        "load_verified_formal_paper_account_descriptor",
        lambda **kwargs: account,
    )
    monkeypatch.setattr(
        formal_oms, "open_verified_formal_paper_broker_store", lambda **kwargs: broker
    )


def _broker_only_setup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[object, tuple[object, ...]]:
    cold_raw, materialized_raw = _chains(tmp_path)
    cold = _approved_bundle(cold_raw)
    materialized = _approved_bundle(materialized_raw)
    _allow_chain(monkeypatch, materialized)
    capability = formal_broker.initialize_verified_formal_paper_broker_store(
        environment=cold[0],
        policy=cold[1],
        binding=cold[2],
        account=cold[3],
        now=NOW,
    )
    return capability, materialized


def test_initialize_fresh_verify_and_restart_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broker_only, chain = _broker_only_setup(tmp_path, monkeypatch)
    full, broker = _full_chain(broker_only, chain)
    _allow_materialization(monkeypatch, full, broker)

    capability = formal_oms.initialize_verified_formal_paper_execution_store(
        broker_store=broker_only,
        environment=chain[0],
        policy=chain[1],
        binding=chain[2],
        account=chain[3],
        now=NOW,
    )
    assert capability.environment is full[0]
    assert capability.broker_store is broker
    assert capability.store.schema_version() > 0
    assert capability.store.session_barrier_enabled()
    assert capability.broker_store.store.session_barrier_enabled()
    assert (
        capability.barrier_capability_identity
        == capability._session_barrier.capability_identity
    )
    assert capability.barrier_epoch == capability._session_barrier.barrier_epoch
    assert not hasattr(type(capability), "session_barrier")
    assert "session_barrier" not in getattr(type(capability), "__dataclass_fields__", {})
    with pytest.raises(AttributeError):
        _ = capability.session_barrier  # type: ignore[attr-defined]
    assert formal_oms.verify_existing_formal_paper_execution_store_capability(
        capability=capability, now=NOW
    ) is capability

    capability.store.close()
    reopened = formal_oms.open_verified_formal_paper_execution_store(
        environment=full[0],
        policy=full[1],
        binding=full[2],
        account=full[3],
        broker_store=broker,
        now=NOW,
    )
    assert reopened.store_identity == capability.store_identity
    assert reopened.store.session_barrier_enabled()
    assert reopened.broker_store.store.session_barrier_enabled()
    reopened.store.close()


def test_formal_closing_issues_closure_and_rejects_ordinary_writers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broker_only, chain = _broker_only_setup(tmp_path, monkeypatch)
    full, broker = _full_chain(broker_only, chain)
    _allow_materialization(monkeypatch, full, broker)
    capability = formal_oms.initialize_verified_formal_paper_execution_store(
        broker_store=broker_only,
        environment=chain[0],
        policy=chain[1],
        binding=chain[2],
        account=chain[3],
        now=NOW,
    )
    with capability.store.transaction():
        pass
    row, closure = formal_oms.transition_formal_session_barrier_to_closing(
        capability=capability, nonce="formal-close", now=NOW
    )
    assert row.state == "CLOSING"
    assert type(closure) is SessionBarrierClosureCapability
    unpacked = unpack_session_barrier_closure_capability(
        closure, capability=capability._session_barrier
    )
    assert unpacked.closure_identity == closure.closure_identity
    assert unpacked.close_token_identity == closure.close_token_identity
    assert row.close_token_identity == closure.close_token_identity
    with pytest.raises(Exception, match="BARRIER_STATE_CLOSING"):
        with capability.store.transaction():
            pass
    with pytest.raises(Exception, match="BARRIER_STATE_CLOSING"):
        capability.broker_store.store.verify_fresh()
        capability.broker_store.store.finalize_session(
            session_date=NOW.date(),
            finalized_at=NOW,
        )
    # Formal CLOSING→CLOSED helper exists (M4-B1B2) but only ever succeeds
    # under an active ``closing_to_closed`` terminal child minted from a held
    # ``hold_formal_terminal_closure`` context; without one it fails closed
    # and leaves the row in CLOSING (no bypass of the durable step sequence).
    with pytest.raises(formal_oms.FormalPaperExecutionStoreError):
        formal_oms.transition_formal_session_barrier_to_closed(
            capability=capability,
            closure=closure,
            terminal_successor_identity="a" * 64,
            now=NOW,
        )
    assert (
        capability.store.read_session_barrier_row().state  # type: ignore[union-attr]
        == "CLOSING"
    )
    # Closure has no write/transaction interface.
    assert not hasattr(closure, "transaction")
    assert not hasattr(closure, "write")
    assert "proof" not in repr(closure)
    assert closure.close_token_identity not in repr(closure)
    # CLOSING fresh verify remains zero-write.
    assert (
        formal_oms.verify_existing_formal_paper_execution_store_capability(
            capability=capability, now=NOW
        )
        is capability
    )
    capability.store.close()


def test_formal_closing_token_cannot_reach_closed_via_store_or_session_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broker_only, chain = _broker_only_setup(tmp_path, monkeypatch)
    full, broker = _full_chain(broker_only, chain)
    _allow_materialization(monkeypatch, full, broker)
    capability = formal_oms.initialize_verified_formal_paper_execution_store(
        broker_store=broker_only,
        environment=chain[0],
        policy=chain[1],
        binding=chain[2],
        account=chain[3],
        now=NOW,
    )
    row, closure = formal_oms.transition_formal_session_barrier_to_closing(
        capability=capability, nonce="formal-token-closed", now=NOW
    )
    token = row.close_token_identity or closure.close_token_identity
    assert token is not None and len(token) == 64

    with pytest.raises(StoreError, match="BARRIER_CLOSURE_REQUIRED"):
        capability.store.transition_session_barrier_to_closed(
            close_token_identity=token, now=NOW
        )

    # Reflection of the private live barrier still cannot raw-close under FORMAL.
    private_barrier = capability._session_barrier
    assert private_barrier.terminal_policy == "FORMAL_CLOSURE_ONLY"
    oms_conn = object.__getattribute__(capability.store, "_conn")
    with pytest.raises(SessionBarrierError, match="BARRIER_CLOSURE_REQUIRED"):
        transition_closing_to_closed(
            oms_conn,
            private_barrier,
            close_token_identity=token,
            now=NOW,
        )

    assert not hasattr(type(capability), "session_barrier")
    with pytest.raises(AttributeError):
        getattr(capability, "session_barrier")
    assert (
        formal_oms.verify_formal_session_barrier_closing_row(
            capability=capability, now=NOW
        ).state
        == "CLOSING"
    )
    capability.store.close()


def test_formal_initialize_write_exclusive_failure_no_capability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broker_only, chain = _broker_only_setup(tmp_path, monkeypatch)
    full, broker = _full_chain(broker_only, chain)
    _allow_materialization(monkeypatch, full, broker)
    root = chain[0].config.runtime_root

    def boom_write(path: Path, raw: bytes) -> None:
        del path, raw
        raise OSError("simulated exclusive write failure")

    monkeypatch.setattr(formal_oms, "_write_exclusive", boom_write)
    with pytest.raises(
        formal_oms.FormalPaperExecutionStoreError,
        match="^PAPER_FORMAL_EXECUTION_STORE_(INVALID|ROLLBACK_REQUIRED)$",
    ) as caught:
        formal_oms.initialize_verified_formal_paper_execution_store(
            broker_store=broker_only,
            environment=chain[0],
            policy=chain[1],
            binding=chain[2],
            account=chain[3],
            now=NOW,
        )
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    code = str(caught.value)
    if code.endswith("INVALID") and not root.exists():
        pass
    else:
        assert code.endswith("ROLLBACK_REQUIRED") or not root.exists()

    with pytest.raises(formal_oms.FormalPaperExecutionStoreError):
        formal_oms.open_verified_formal_paper_execution_store(
            environment=full[0],
            policy=full[1],
            binding=full[2],
            account=full[3],
            broker_store=broker,
            now=NOW,
        )


def test_formal_initialize_bind_failure_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broker_only, chain = _broker_only_setup(tmp_path, monkeypatch)
    full, broker = _full_chain(broker_only, chain)
    _allow_materialization(monkeypatch, full, broker)

    def boom_bind(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeError("simulated broker barrier bind failure")

    monkeypatch.setattr(formal_oms, "_bind_formal_broker_barrier", boom_bind)
    with pytest.raises(
        formal_oms.FormalPaperExecutionStoreError,
        match="^PAPER_FORMAL_EXECUTION_STORE_(INVALID|ROLLBACK_REQUIRED)$",
    ) as caught:
        formal_oms.initialize_verified_formal_paper_execution_store(
            broker_store=broker_only,
            environment=chain[0],
            policy=chain[1],
            binding=chain[2],
            account=chain[3],
            now=NOW,
        )
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert str(caught.value) in {
        "PAPER_FORMAL_EXECUTION_STORE_INVALID",
        "PAPER_FORMAL_EXECUTION_STORE_ROLLBACK_REQUIRED",
    }

    with pytest.raises(formal_oms.FormalPaperExecutionStoreError):
        formal_oms.open_verified_formal_paper_execution_store(
            environment=full[0],
            policy=full[1],
            binding=full[2],
            account=full[3],
            broker_store=broker,
            now=NOW,
        )


def test_formal_rollback_descriptor_identity_drift_not_deleted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§11 F3: descriptor replace/drift must not be unlinked; ROLLBACK_REQUIRED."""
    broker_only, chain = _broker_only_setup(tmp_path, monkeypatch)
    full, broker = _full_chain(broker_only, chain)
    _allow_materialization(monkeypatch, full, broker)
    root = chain[0].config.runtime_root
    descriptor_path = root / "execution-store-instance.json"

    def drift_descriptor_then_fail(*args: object, **kwargs: object) -> None:
        del args, kwargs
        # Identity was recorded immediately after _write_exclusive; replace inode.
        assert descriptor_path.exists()
        descriptor_path.unlink()
        descriptor_path.write_bytes(b'{"drifted":true}')
        raise RuntimeError("fail after descriptor drift")

    monkeypatch.setattr(
        formal_oms, "_bind_formal_broker_barrier", drift_descriptor_then_fail
    )
    with pytest.raises(
        formal_oms.FormalPaperExecutionStoreError,
        match="^PAPER_FORMAL_EXECUTION_STORE_ROLLBACK_REQUIRED$",
    ) as caught:
        formal_oms.initialize_verified_formal_paper_execution_store(
            broker_store=broker_only,
            environment=chain[0],
            policy=chain[1],
            binding=chain[2],
            account=chain[3],
            now=NOW,
        )
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert descriptor_path.exists()
    assert descriptor_path.read_bytes() == b'{"drifted":true}'


def test_formal_rollback_unrecorded_wal_shm_not_deleted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§11/§12 F21: inject unrecorded WAL only after real ExecutionStore.close."""
    from quant.execution.store import ExecutionStore

    broker_only, chain = _broker_only_setup(tmp_path, monkeypatch)
    full, broker = _full_chain(broker_only, chain)
    _allow_materialization(monkeypatch, full, broker)
    root = chain[0].config.runtime_root
    wal = root / f"{chain[0].config.oms_sqlite_filename}-wal"

    def skip_sidecar_record(owned: object, db_path: object) -> None:
        del owned, db_path

    monkeypatch.setattr(formal_oms, "_record_owned_sidecars", skip_sidecar_record)

    real_close = ExecutionStore.close

    def close_then_inject_unrecorded_wal(self: ExecutionStore) -> None:
        real_close(self)
        if not wal.exists():
            wal.write_bytes(b"unrecorded-wal")

    monkeypatch.setattr(ExecutionStore, "close", close_then_inject_unrecorded_wal)

    def boom_bind(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeError("fail with unrecorded sidecar")

    monkeypatch.setattr(formal_oms, "_bind_formal_broker_barrier", boom_bind)
    with pytest.raises(
        formal_oms.FormalPaperExecutionStoreError,
        match="^PAPER_FORMAL_EXECUTION_STORE_ROLLBACK_REQUIRED$",
    ) as caught:
        formal_oms.initialize_verified_formal_paper_execution_store(
            broker_store=broker_only,
            environment=chain[0],
            policy=chain[1],
            binding=chain[2],
            account=chain[3],
            now=NOW,
        )
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert wal.exists()
    with pytest.raises(formal_oms.FormalPaperExecutionStoreError):
        formal_oms.open_verified_formal_paper_execution_store(
            environment=full[0],
            policy=full[1],
            binding=full[2],
            account=full[3],
            broker_store=broker,
            now=NOW,
        )


def test_formal_rollback_identity_closed_path_exact_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§11 F3: recorded identities with no drift still exact-rollback."""
    broker_only, chain = _broker_only_setup(tmp_path, monkeypatch)
    full, broker = _full_chain(broker_only, chain)
    _allow_materialization(monkeypatch, full, broker)
    root = chain[0].config.runtime_root

    def boom_bind(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeError("fail after identity-closed materialization")

    monkeypatch.setattr(formal_oms, "_bind_formal_broker_barrier", boom_bind)
    with pytest.raises(
        formal_oms.FormalPaperExecutionStoreError,
        match="^PAPER_FORMAL_EXECUTION_STORE_(INVALID|ROLLBACK_REQUIRED)$",
    ) as caught:
        formal_oms.initialize_verified_formal_paper_execution_store(
            broker_store=broker_only,
            environment=chain[0],
            policy=chain[1],
            binding=chain[2],
            account=chain[3],
            now=NOW,
        )
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    code = str(caught.value)
    if code.endswith("INVALID"):
        assert not root.exists()
    else:
        # Identity-closed cleanup removes the attempt root; otherwise REQUIRED.
        assert code.endswith("ROLLBACK_REQUIRED") or not root.exists()
    with pytest.raises(formal_oms.FormalPaperExecutionStoreError):
        formal_oms.open_verified_formal_paper_execution_store(
            environment=full[0],
            policy=full[1],
            binding=full[2],
            account=full[3],
            broker_store=broker,
            now=NOW,
        )


def test_no_clobber_and_closed_capability_fail_sanitized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broker_only, chain = _broker_only_setup(tmp_path, monkeypatch)
    full, broker = _full_chain(broker_only, chain)
    _allow_materialization(monkeypatch, full, broker)
    capability = formal_oms.initialize_verified_formal_paper_execution_store(
        broker_store=broker_only,
        environment=chain[0],
        policy=chain[1],
        binding=chain[2],
        account=chain[3],
        now=NOW,
    )
    with pytest.raises(
        formal_oms.FormalPaperExecutionStoreError,
        match="^PAPER_FORMAL_EXECUTION_STORE_ALREADY_EXISTS$",
    ):
        formal_oms.initialize_verified_formal_paper_execution_store(
            broker_store=broker_only,
            environment=chain[0],
            policy=chain[1],
            binding=chain[2],
            account=chain[3],
            now=NOW,
        )
    capability.store.close()
    with pytest.raises(
        formal_oms.FormalPaperExecutionStoreError,
        match="^PAPER_FORMAL_EXECUTION_STORE_STALE$",
    ) as caught:
        formal_oms.verify_existing_formal_paper_execution_store_capability(
            capability=capability, now=NOW
        )
    assert caught.value.__cause__ is None and caught.value.__context__ is None


def test_hostile_broker_verifier_rolls_back_owned_runtime_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broker_only, chain = _broker_only_setup(tmp_path, monkeypatch)

    def hostile(**kwargs):  # type: ignore[no-untyped-def]
        del kwargs
        raise RuntimeError("TOKEN/path")

    monkeypatch.setattr(
        formal_oms,
        "verify_existing_formal_paper_broker_store_capability",
        hostile,
    )
    with pytest.raises(
        formal_oms.FormalPaperExecutionStoreError,
        match="^PAPER_FORMAL_EXECUTION_STORE_INVALID$",
    ) as caught:
        formal_oms.initialize_verified_formal_paper_execution_store(
            broker_store=broker_only,
            environment=chain[0],
            policy=chain[1],
            binding=chain[2],
            account=chain[3],
            now=NOW,
        )
    assert not chain[0].config.runtime_root.exists()
    assert caught.value.__cause__ is None and caught.value.__context__ is None
