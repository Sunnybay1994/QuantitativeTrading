"""RUN-0B2G-F0 formal OMS ExecutionStore capability tests."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from quant.execution import paper_formal_execution_store as formal_oms
from tests.unit.test_paper_formal_gateway import _setup
from tests.unit.test_paper_formal_broker_store import NOW


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


def test_initialize_fresh_verify_and_restart_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broker_only, chain = _setup(tmp_path, monkeypatch)
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
    reopened.store.close()


def test_no_clobber_and_closed_capability_fail_sanitized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broker_only, chain = _setup(tmp_path, monkeypatch)
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
    broker_only, chain = _setup(tmp_path, monkeypatch)

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
