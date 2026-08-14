"""Formal deterministic PAPER policy adapters and durable gateway factory."""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from quant.execution.cli_ports import build_verified_paper_gateway
from quant.execution.contracts import CancelCommand, OrderCommand
from quant.execution.gateways.contracts import (
    DispatchCertainty,
    GatewayCancelResult,
    GatewayDispatchResult,
)
from quant.execution.gateways.paper import (
    PaperCancelPlan,
    PaperFill,
    PaperSubmitPlan,
)
from quant.execution.paper_account import VerifiedFormalPaperAccountDescriptor
from quant.execution.paper_broker_binding import (
    VerifiedFormalPaperBrokerPolicyBinding,
)
from quant.execution.paper_formal_broker_store import (
    VerifiedFormalPaperBrokerStoreCapability,
    verify_existing_formal_paper_broker_store_capability,
)
from quant.execution.paper_policy import VerifiedPaperExecutionPolicy
from quant.execution.paper_runtime import VerifiedPaperRuntimeEnvironment

if TYPE_CHECKING:
    from quant.execution.cli_ports import (
        PaperGatewayFactory,
        VerifiedPaperGateway,
    )
    from quant.execution.gateways.contracts import (
        GatewayCancelTransport,
        GatewayTransport,
    )

_FILL_POLICY_VERSION = "paper_deterministic_fill_v1"
_FAULT_POLICY_VERSION = "paper_controlled_fault_drills_v1"
_CLOCK_POLICY_VERSION = "utc_system_clock_v1"


class FormalPaperGatewayError(ValueError):
    """Stable, sanitized failure at the formal PAPER dispatch boundary."""

    def __init__(self) -> None:
        self.code = "PAPER_FORMAL_GATEWAY_INVALID"
        super().__init__(self.code)

    @property
    def __context__(self) -> None:
        return None

    @__context__.setter
    def __context__(self, value: BaseException | None) -> None:
        del value


class _DispatchClock:
    def event_time(self, *, operation_id: str, event_ordinal: int) -> dt.datetime:
        del operation_id, event_ordinal
        raise RuntimeError

    def event_time_for_dispatch(
        self,
        *,
        operation_id: str,
        event_ordinal: int,
        observed_at: dt.datetime,
    ) -> dt.datetime:
        del operation_id, event_ordinal
        return observed_at


class _FillPolicy:
    def plan_submit(self, *, command: OrderCommand) -> PaperSubmitPlan:
        return PaperSubmitPlan(
            fills=(
                PaperFill(
                    quantity=command.intent.quantity,
                    price=command.intent.limit_price,
                ),
            )
        )

    def plan_cancel(
        self, *, command: OrderCommand, cancel: CancelCommand
    ) -> PaperCancelPlan:
        del command, cancel
        return PaperCancelPlan(late_fills=(), confirm_cancel=True)


class _FaultPlan:
    def submit_certainty(
        self, *, command_id: str, dispatch_attempt: int
    ) -> DispatchCertainty:
        del command_id, dispatch_attempt
        return DispatchCertainty.SENT

    def cancel_certainty(
        self, *, cancel_id: str, dispatch_attempt: int
    ) -> DispatchCertainty:
        del cancel_id, dispatch_attempt
        return DispatchCertainty.SENT

    def duplicate_callback_ordinals(
        self, *, operation_id: str
    ) -> tuple[int, ...]:
        del operation_id
        return ()


class _FormalGatewayTransport:
    def __init__(
        self,
        *,
        factory: _VerifiedFormalPaperGatewayFactory,
        submit: GatewayTransport,
        cancel: GatewayCancelTransport,
    ) -> None:
        self._factory = factory
        self._submit = submit
        self._cancel = cancel

    def submit(
        self, *, command: OrderCommand, dispatch_attempt: int, now: dt.datetime
    ) -> GatewayDispatchResult:
        try:
            self._factory._fresh(now)
            return self._submit.submit(
                command=command, dispatch_attempt=dispatch_attempt, now=now
            )
        except Exception:
            pass
        raise FormalPaperGatewayError() from None

    def cancel(
        self, *, command: CancelCommand, dispatch_attempt: int, now: dt.datetime
    ) -> GatewayCancelResult:
        try:
            self._factory._fresh(now)
            return self._cancel.cancel(
                command=command, dispatch_attempt=dispatch_attempt, now=now
            )
        except Exception:
            pass
        raise FormalPaperGatewayError() from None


class _VerifiedFormalPaperGatewayFactory:
    def __init__(
        self,
        *,
        store_capability: VerifiedFormalPaperBrokerStoreCapability,
        environment: VerifiedPaperRuntimeEnvironment,
        policy: VerifiedPaperExecutionPolicy,
        binding: VerifiedFormalPaperBrokerPolicyBinding,
        account: VerifiedFormalPaperAccountDescriptor,
        now: dt.datetime,
    ) -> None:
        self._store_capability = store_capability
        self._environment = environment
        self._policy = policy
        self._binding = binding
        self._account = account
        self._now = now
        self._opened: VerifiedPaperGateway | None = None

    def _fresh(
        self, now: dt.datetime
    ) -> VerifiedFormalPaperBrokerStoreCapability:
        return _fresh_capability(
            store_capability=self._store_capability,
            environment=self._environment,
            policy=self._policy,
            binding=self._binding,
            account=self._account,
            now=now,
        )

    def identity(self) -> str:
        try:
            return self._fresh(self._now).gateway_identity
        except Exception:
            pass
        raise FormalPaperGatewayError() from None

    def open(self) -> VerifiedPaperGateway:
        try:
            if self._opened is not None:
                self._fresh(self._now)
                return self._opened
            from quant.execution.gateways.paper_durable import (
                DurablePaperGatewayFactory,
            )

            capability = self._fresh(self._now)
            durable = DurablePaperGatewayFactory._from_formal(
                store=capability.store,
                policy=self._policy,
                binding=self._binding,
                clock=_DispatchClock(),
                fill_policy=_FillPolicy(),
                fault_plan=_FaultPlan(),
            ).open()
            if durable.gateway_identity != capability.gateway_identity:
                raise ValueError
            transport = _FormalGatewayTransport(
                factory=self, submit=durable.submit, cancel=durable.cancel
            )
            opened = build_verified_paper_gateway(
                gateway_identity=capability.gateway_identity,
                submit=transport,
                cancel=transport,
            )
            self._opened = opened
            return opened
        except Exception:
            pass
        raise FormalPaperGatewayError() from None


def open_verified_formal_paper_gateway_factory(
    *,
    store_capability: VerifiedFormalPaperBrokerStoreCapability,
    environment: VerifiedPaperRuntimeEnvironment,
    policy: VerifiedPaperExecutionPolicy,
    binding: VerifiedFormalPaperBrokerPolicyBinding,
    account: VerifiedFormalPaperAccountDescriptor,
    now: dt.datetime,
) -> PaperGatewayFactory:
    """Open the only formal deterministic policy/fault/clock adapter factory."""
    try:
        _fresh_capability(
            store_capability=store_capability,
            environment=environment,
            policy=policy,
            binding=binding,
            account=account,
            now=now,
        )
        return _VerifiedFormalPaperGatewayFactory(
            store_capability=store_capability,
            environment=environment,
            policy=policy,
            binding=binding,
            account=account,
            now=now,
        )
    except Exception:
        pass
    raise FormalPaperGatewayError() from None


def _fresh_capability(
    *,
    store_capability: VerifiedFormalPaperBrokerStoreCapability,
    environment: VerifiedPaperRuntimeEnvironment,
    policy: VerifiedPaperExecutionPolicy,
    binding: VerifiedFormalPaperBrokerPolicyBinding,
    account: VerifiedFormalPaperAccountDescriptor,
    now: dt.datetime,
) -> VerifiedFormalPaperBrokerStoreCapability:
    if (
        type(store_capability) is not VerifiedFormalPaperBrokerStoreCapability
        or type(environment) is not VerifiedPaperRuntimeEnvironment
        or type(policy) is not VerifiedPaperExecutionPolicy
        or type(binding) is not VerifiedFormalPaperBrokerPolicyBinding
        or type(account) is not VerifiedFormalPaperAccountDescriptor
        or type(now) is not dt.datetime
        or now.tzinfo is None
        or now.utcoffset() != dt.timedelta(0)
        or policy.fill_policy_version != _FILL_POLICY_VERSION
        or policy.fault_policy_version != _FAULT_POLICY_VERSION
        or policy.clock_policy_version != _CLOCK_POLICY_VERSION
        or binding.fill_policy_version != _FILL_POLICY_VERSION
        or binding.fault_policy_version != _FAULT_POLICY_VERSION
        or binding.clock_policy_version != _CLOCK_POLICY_VERSION
    ):
        raise TypeError
    verified = verify_existing_formal_paper_broker_store_capability(
        capability=store_capability,
        environment=environment,
        policy=policy,
        binding=binding,
        account=account,
        now=now,
    )
    if (
        type(verified) is not VerifiedFormalPaperBrokerStoreCapability
        or verified is not store_capability
    ):
        raise ValueError
    return verified


__all__ = [
    "FormalPaperGatewayError",
    "open_verified_formal_paper_gateway_factory",
]
