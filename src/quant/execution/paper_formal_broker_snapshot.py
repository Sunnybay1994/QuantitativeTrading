"""Fresh, read-only broker evidence port for the formal PAPER store."""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from quant.execution.cli_ports import (
    VerifiedBrokerEvidence,
    build_verified_broker_evidence,
    verify_broker_evidence,
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
    from quant.execution.cli_ports import BrokerSnapshotPort


_HEX = frozenset("0123456789abcdef")


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


def _finalize_and_query_formal_paper_broker_eod(
    *,
    store_capability: VerifiedFormalPaperBrokerStoreCapability,
    environment: VerifiedPaperRuntimeEnvironment,
    policy: VerifiedPaperExecutionPolicy,
    binding: VerifiedFormalPaperBrokerPolicyBinding,
    account: VerifiedFormalPaperAccountDescriptor,
    session_date: dt.date,
    now: dt.datetime,
    gateway_identity: str,
    order_semantic_closure_identity: str,
) -> VerifiedBrokerEvidence:
    """Apply an exact broker marker after the caller proves OMS ORDER closure."""
    try:
        if (
            type(session_date) is not dt.date
            or not _utc(now)
            or type(gateway_identity) is not str
            or len(gateway_identity) != 64
            or not set(gateway_identity) <= _HEX
            or type(order_semantic_closure_identity) is not str
            or len(order_semantic_closure_identity) != 64
            or not set(order_semantic_closure_identity) <= _HEX
        ):
            raise ValueError
        capability = _fresh_capability(
            store_capability=store_capability,
            environment=environment,
            policy=policy,
            binding=binding,
            account=account,
            now=now,
        )
        if (
            capability.session_date != session_date
            or policy.session_date != session_date
            or capability.gateway_identity != gateway_identity
        ):
            raise ValueError
        store = capability.store
        if store.read_evidence_snapshot(session_date=session_date)[3] > now:
            raise ValueError
        session_commands = tuple(
            command
            for command in store.all_commands()
            if command.intent.session_date == session_date
        )
        marker = store.read_session_finality(session_date=session_date)
        if marker is None:
            if session_commands:
                store.finalize_session(session_date=session_date, finalized_at=now)
            else:
                store.record_zero_broker_command_session_finality(
                    session_date=session_date,
                    finalized_at=now,
                    order_semantic_closure_identity=order_semantic_closure_identity,
                )
        capability = _fresh_capability(
            store_capability=capability,
            environment=environment,
            policy=policy,
            binding=binding,
            account=account,
            now=now,
        )
        session_commands = tuple(
            command
            for command in capability.store.all_commands()
            if command.intent.session_date == session_date
        )
        marker = capability.store.read_session_finality(session_date=session_date)
        if (
            marker is None
            or marker.finalized_at > now
            or (
                marker.schema_version == "paper-session-finality-v1"
                and (
                    not session_commands
                    or marker.order_semantic_closure_identity is not None
                )
            )
            or (
                marker.schema_version
                == "paper-zero-broker-command-session-finality-v1"
                and (
                    session_commands
                    or marker.order_semantic_closure_identity
                    != order_semantic_closure_identity
                )
            )
        ):
            raise ValueError
        snapshot = capability.store.read_evidence_snapshot(
            session_date=session_date
        )
        account_snapshot, orders, events, as_of, source_identity, finality = snapshot
        if finality != "END_OF_DAY" or as_of > now:
            raise ValueError
        evidence = build_verified_broker_evidence(
            source_identity=source_identity,
            gateway_identity=gateway_identity,
            as_of=as_of,
            finality=finality,
            account=account_snapshot,
            orders=orders,
            events=events,
        )
        if verify_broker_evidence(evidence) is not evidence:
            raise ValueError
        return evidence
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


def _utc(value: object) -> bool:
    return (
        type(value) is dt.datetime
        and value.tzinfo is not None
        and value.utcoffset() == dt.timedelta(0)
    )


__all__ = [
    "FormalPaperBrokerSnapshotError",
    "open_verified_formal_paper_broker_snapshot_port",
]
