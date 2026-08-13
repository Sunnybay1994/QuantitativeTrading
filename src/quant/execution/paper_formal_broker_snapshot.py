"""Fresh, read-only broker evidence port for the formal PAPER store."""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

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
    from quant.execution.cli_ports import BrokerSnapshotPort, VerifiedBrokerEvidence


class FormalPaperBrokerSnapshotError(ValueError):
    """Stable, sanitized failure at the formal broker evidence boundary."""

    def __init__(self) -> None:
        self.code = "PAPER_FORMAL_BROKER_SNAPSHOT_INVALID"
        super().__init__(self.code)

    @property
    def __context__(self) -> None:
        return None

    @__context__.setter
    def __context__(self, value: BaseException | None) -> None:
        del value


class _VerifiedFormalPaperBrokerSnapshotPort:
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

    def query_and_verify(self, *, gateway_identity: str) -> VerifiedBrokerEvidence:
        try:
            from quant.execution.gateways.paper_durable import (
                DurablePaperBrokerSnapshotPort,
            )

            capability = _fresh_capability(
                store_capability=self._store_capability,
                environment=self._environment,
                policy=self._policy,
                binding=self._binding,
                account=self._account,
                now=self._now,
            )
            if gateway_identity != capability.gateway_identity:
                raise ValueError
            return DurablePaperBrokerSnapshotPort(
                store=capability.store
            ).query_and_verify(gateway_identity=gateway_identity)
        except Exception:
            pass
        raise FormalPaperBrokerSnapshotError() from None


def open_verified_formal_paper_broker_snapshot_port(
    *,
    store_capability: VerifiedFormalPaperBrokerStoreCapability,
    environment: VerifiedPaperRuntimeEnvironment,
    policy: VerifiedPaperExecutionPolicy,
    binding: VerifiedFormalPaperBrokerPolicyBinding,
    account: VerifiedFormalPaperAccountDescriptor,
    now: dt.datetime,
) -> BrokerSnapshotPort:
    """Open a read-only port after fresh-verifying the complete formal chain."""
    try:
        _fresh_capability(
            store_capability=store_capability,
            environment=environment,
            policy=policy,
            binding=binding,
            account=account,
            now=now,
        )
        return _VerifiedFormalPaperBrokerSnapshotPort(
            store_capability=store_capability,
            environment=environment,
            policy=policy,
            binding=binding,
            account=account,
            now=now,
        )
    except Exception:
        pass
    raise FormalPaperBrokerSnapshotError() from None


def _fresh_capability(
    *,
    store_capability: VerifiedFormalPaperBrokerStoreCapability,
    environment: VerifiedPaperRuntimeEnvironment,
    policy: VerifiedPaperExecutionPolicy,
    binding: VerifiedFormalPaperBrokerPolicyBinding,
    account: VerifiedFormalPaperAccountDescriptor,
    now: dt.datetime,
) -> VerifiedFormalPaperBrokerStoreCapability:
    if type(store_capability) is not VerifiedFormalPaperBrokerStoreCapability:
        raise TypeError
    verified = verify_existing_formal_paper_broker_store_capability(
        capability=store_capability,
        environment=environment,
        policy=policy,
        binding=binding,
        account=account,
        now=now,
    )
    if type(verified) is not VerifiedFormalPaperBrokerStoreCapability:
        raise TypeError
    if verified is not store_capability:
        raise ValueError
    return verified


__all__ = [
    "FormalPaperBrokerSnapshotError",
    "open_verified_formal_paper_broker_snapshot_port",
]
