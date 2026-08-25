"""RUN-0B2F-S2 formal policy adapter and durable dispatch tests."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from quant.domain.enums import Currency, ExecutionMode, Market, OrderSide
from quant.execution import paper_formal_broker_store as formal_store
from quant.execution import paper_formal_execution_store as formal_oms
from quant.execution import paper_formal_gateway as formal_gateway
from quant.execution.contracts import build_order_command, build_order_intent
from quant.execution.gateways.paper import PaperGatewayError
from tests.unit.test_paper_formal_broker_store import NOW, _allow_chain, _chains


def _hex(label: str) -> str:
    import hashlib

    return hashlib.sha256(label.encode()).hexdigest()


def _approved_bundle(bundle: tuple[object, ...]) -> tuple[object, ...]:
    environment, policy, binding, account = bundle
    policy = replace(
        policy,
        fill_policy_version="paper_deterministic_fill_v1",
        fault_policy_version="paper_controlled_fault_drills_v1",
        clock_policy_version="utc_system_clock_v1",
        policy_identity=_hex("approved-policy"),
    )
    binding = replace(
        binding,
        runtime_environment_identity=environment.verification_identity,
        execution_policy_identity=policy.policy_identity,
        fill_policy_version=policy.fill_policy_version,
        fault_policy_version=policy.fault_policy_version,
        clock_policy_version=policy.clock_policy_version,
        binding_identity=_hex(f"binding-{environment.verification_identity}"),
    )
    account = replace(
        account,
        runtime_environment_identity=environment.verification_identity,
        execution_policy_identity=policy.policy_identity,
        broker_binding_identity=binding.binding_identity,
        verification_identity=_hex(f"account-{environment.verification_identity}"),
    )
    return environment, policy, binding, account


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


def _setup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[object, tuple[object, ...]]:
    cold_raw, materialized_raw = _chains(tmp_path)
    cold = _approved_bundle(cold_raw)
    materialized = _approved_bundle(materialized_raw)
    _allow_chain(monkeypatch, materialized)
    broker_only = formal_store.initialize_verified_formal_paper_broker_store(
        environment=cold[0],
        policy=cold[1],
        binding=cold[2],
        account=cold[3],
        now=NOW,
    )
    full, broker = _full_chain(broker_only, materialized)
    _allow_materialization(monkeypatch, full, broker)
    oms = formal_oms.initialize_verified_formal_paper_execution_store(
        broker_store=broker_only,
        environment=materialized[0],
        policy=materialized[1],
        binding=materialized[2],
        account=materialized[3],
        now=NOW,
    )
    assert oms.store.session_barrier_enabled()
    assert oms.broker_store.store.session_barrier_enabled()
    # Test-owned exact verifier for positive gateway fixtures only (not production).
    monkeypatch.setattr(
        formal_gateway,
        "verify_existing_formal_paper_broker_store_capability",
        lambda **kwargs: kwargs["capability"],
    )
    return oms.broker_store, full


def _command():  # type: ignore[no-untyped-def]
    intent = build_order_intent(
        plan_id=_hex("plan"),
        symbol="600000.SH",
        market=Market.SH,
        side=OrderSide.BUY,
        quantity=100,
        limit_price=Decimal("10.50"),
        quote_currency=Currency.CNY,
        session_date=NOW.date(),
        generated_at=NOW,
        target_identity=_hex("target"),
        market_snapshot_id=_hex("market"),
        account_snapshot_id=_hex("account"),
        config_identity=_hex("config"),
        connect_route=None,
    )
    return build_order_command(intent=intent, mode=ExecutionMode.PAPER)


def test_formal_submit_is_full_limit_fill_dispatch_anchored_and_retained(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capability, chain = _setup(tmp_path, monkeypatch)
    calls = 0
    original = formal_gateway._DispatchClock.event_time_for_dispatch

    def counted(self, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        return original(self, **kwargs)

    monkeypatch.setattr(
        formal_gateway._DispatchClock, "event_time_for_dispatch", counted
    )
    factory = formal_gateway.open_verified_formal_paper_gateway_factory(
        store_capability=capability,
        environment=chain[0],
        policy=chain[1],
        binding=chain[2],
        account=chain[3],
        now=NOW,
    )
    gateway = factory.open()
    assert factory.open() is gateway
    command = _command()
    first = gateway.submit.submit(command=command, dispatch_attempt=1, now=NOW)

    assert factory.identity() == capability.gateway_identity
    assert [item.event_type.value for item in first.callbacks] == [
        "ACCEPTED",
        "FILL",
    ]
    assert {item.occurred_at for item in first.callbacks} == {NOW}
    assert first.callbacks[-1].last_quantity == command.intent.quantity
    assert first.callbacks[-1].last_price == command.intent.limit_price
    assert [item.code for item in first.callbacks[-1].fees] == [
        "COMMISSION",
        "STAMP_TAX",
        "TRANSFER_FEE",
    ]
    assert calls == 2

    retained = gateway.submit.submit(command=command, dispatch_attempt=1, now=NOW)
    assert retained == first
    assert calls == 2


def test_unsupported_policy_and_hostile_fresh_verifier_are_sanitized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capability, chain = _setup(tmp_path, monkeypatch)
    unsupported = replace(chain[1], fill_policy_version="fill-v2")
    with pytest.raises(
        formal_gateway.FormalPaperGatewayError,
        match="^PAPER_FORMAL_GATEWAY_INVALID$",
    ) as selector_error:
        formal_gateway.open_verified_formal_paper_gateway_factory(
            store_capability=capability,
            environment=chain[0],
            policy=unsupported,
            binding=chain[2],
            account=chain[3],
            now=NOW,
        )
    assert selector_error.value.__cause__ is None
    assert selector_error.value.__context__ is None

    def hostile(**kwargs):  # type: ignore[no-untyped-def]
        del kwargs
        try:
            raise ValueError("TOKEN/path")
        except ValueError as exc:
            raise RuntimeError("hostile") from exc

    monkeypatch.setattr(
        formal_gateway,
        "verify_existing_formal_paper_broker_store_capability",
        hostile,
    )
    with pytest.raises(
        formal_gateway.FormalPaperGatewayError,
        match="^PAPER_FORMAL_GATEWAY_INVALID$",
    ) as hostile_error:
        formal_gateway.open_verified_formal_paper_gateway_factory(
            store_capability=capability,
            environment=chain[0],
            policy=chain[1],
            binding=chain[2],
            account=chain[3],
            now=NOW,
        )
    assert hostile_error.value.__cause__ is None
    assert hostile_error.value.__context__ is None


def test_closed_store_fails_at_dispatch_and_default_cancel_plan_is_exact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capability, chain = _setup(tmp_path, monkeypatch)
    factory = formal_gateway.open_verified_formal_paper_gateway_factory(
        store_capability=capability,
        environment=chain[0],
        policy=chain[1],
        binding=chain[2],
        account=chain[3],
        now=NOW,
    )
    gateway = factory.open()
    plan = formal_gateway._FillPolicy().plan_cancel(
        command=_command(), cancel=object()  # type: ignore[arg-type]
    )
    assert plan.late_fills == () and plan.confirm_cancel is True

    capability.store.close()
    with pytest.raises(
        formal_gateway.FormalPaperGatewayError,
        match="^PAPER_FORMAL_GATEWAY_INVALID$",
    ):
        gateway.submit.submit(command=_command(), dispatch_attempt=1, now=NOW)


def test_unbound_broker_formal_gateway_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cold_raw, materialized_raw = _chains(tmp_path)
    cold = _approved_bundle(cold_raw)
    materialized = _approved_bundle(materialized_raw)
    _allow_chain(monkeypatch, materialized)
    unbound = formal_store.initialize_verified_formal_paper_broker_store(
        environment=cold[0],
        policy=cold[1],
        binding=cold[2],
        account=cold[3],
        now=NOW,
    )
    assert unbound.store.session_barrier_enabled() is False
    # Exact verifier returns this capability; rejection must be enabled()==False.
    monkeypatch.setattr(
        formal_gateway,
        "verify_existing_formal_paper_broker_store_capability",
        lambda **kwargs: kwargs["capability"],
    )
    with pytest.raises(
        formal_gateway.FormalPaperGatewayError,
        match="^PAPER_FORMAL_GATEWAY_INVALID$",
    ):
        formal_gateway.open_verified_formal_paper_gateway_factory(
            store_capability=unbound,
            environment=cold[0],
            policy=cold[1],
            binding=cold[2],
            account=cold[3],
            now=NOW,
        )


def test_legacy_clock_path_keeps_ordinal_timestamps() -> None:
    from tests.unit.test_paper_gateway import _Policy, _command as legacy_command, _gateway, _time
    from quant.execution.gateways.paper import PaperFill, PaperSubmitPlan

    gateway, _, _, _ = _gateway(
        policy=_Policy(
            PaperSubmitPlan(fills=(PaperFill(100, Decimal("10.40")),))
        )
    )
    result = gateway.submit(
        command=legacy_command(), dispatch_attempt=1, now=_time(9)
    )
    assert [item.occurred_at for item in result.callbacks] == [_time(1), _time(2)]
    assert result.callbacks[0].occurred_at != result.callbacks[1].occurred_at
    assert PaperGatewayError is not None
