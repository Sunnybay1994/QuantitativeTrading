"""Formal PAPER composition of OMS store, gateway and ledger provider."""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import secrets
from dataclasses import dataclass, field
from contextlib import AbstractContextManager, contextmanager
from typing import Iterator, NoReturn, SupportsIndex

from quant.domain.canonical_wire import canonical_json_bytes, utc_datetime_text
from quant.execution.cli_ports import PaperGatewayFactory, ServiceFactory, StoreOpener
from quant.execution.gateways.contracts import GatewayCancelTransport, GatewayTransport
from quant.execution.paper_account import VerifiedFormalPaperAccountDescriptor
from quant.execution.paper_broker_binding import VerifiedFormalPaperBrokerPolicyBinding
from quant.execution.paper_formal_broker_store import (
    VerifiedFormalPaperBrokerStoreCapability,
)
from quant.execution.paper_formal_execution_store import (
    VerifiedFormalPaperExecutionStoreCapability,
    bind_formal_terminal_successor,
    hold_formal_terminal_closure,
    hold_formal_terminal_step,
    transition_formal_session_barrier_to_closed,
    verify_existing_formal_paper_execution_store_capability,
)
from quant.execution.paper_formal_gateway import (
    open_verified_formal_paper_gateway_factory,
)
from quant.execution.paper_formal_ledger import (
    VerifiedFormalPaperLedgerContextProvider,
    verify_existing_formal_paper_ledger_context_provider,
)
from quant.execution.paper_policy import VerifiedPaperExecutionPolicy
from quant.execution.paper_runtime import VerifiedPaperRuntimeEnvironment
from quant.execution.reconcile import RecoveryResult, recover_repository_state
from quant.execution.service import ExecutionService
from quant.execution.session_barrier import SessionBarrierRow
from quant.execution.store import ExecutionStore

_SCHEMA = "formal-paper-service-composition-v1"
_CLOSURE_VIEW_SCHEMA = "formal-paper-closure-view-v1"
_WORKER_ID = "formal-paper-worker-v1"
_LEASE = dt.timedelta(minutes=1)


class FormalPaperServiceError(ValueError):
    """Stable, sanitized formal PAPER service-composition failure."""

    def __init__(self) -> None:
        self.code = "PAPER_FORMAL_SERVICE_INVALID"
        super().__init__(self.code)

    @property
    def __context__(self) -> None:
        return None

    @__context__.setter
    def __context__(self, value: BaseException | None) -> None:
        del value


@dataclass(frozen=True, slots=True)
class _Attestation:
    token: bytes = field(repr=False, compare=False)

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        del protocol
        raise TypeError("formal PAPER service composition is process-local")


@dataclass(frozen=True, slots=True)
class VerifiedFormalPaperServiceComposition:
    """Process-local CLI composition inputs backed by one formal chain."""

    schema_version: str
    composition_identity: str
    execution_store_identity: str
    gateway_identity: str
    ledger_provider_identity: str
    account_id: str
    worker_id: str
    lease_seconds: int
    verified_at: dt.datetime
    store_opener: StoreOpener = field(repr=False, compare=False)
    gateway_factory: PaperGatewayFactory = field(repr=False, compare=False)
    service_factory: ServiceFactory = field(repr=False, compare=False)
    _execution_store: VerifiedFormalPaperExecutionStoreCapability = field(
        repr=False, compare=False
    )
    _ledger_provider: VerifiedFormalPaperLedgerContextProvider = field(
        repr=False, compare=False
    )
    _attestation: _Attestation = field(repr=False, compare=False)

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        del protocol
        raise TypeError("formal PAPER service composition is process-local")


@dataclass(frozen=True, slots=True)
class _ClosureViewAttestation:
    token: bytes = field(repr=False, compare=False)

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        del protocol
        raise TypeError("formal PAPER closure view is process-local")


@dataclass(frozen=True, slots=True)
class VerifiedFormalPaperClosureView:
    """Narrow attested read-only view for terminal closure (INFRA-007).

    Exposes only public identities and package-owned ports needed by
    ``soak_runtime`` to drive broker finality, OMS recovery/reconciliation and
    the terminal closure sequence. Never exposes raw ``ExecutionStore``,
    ``ExecutionRepository``, connection, or any commit/write surface; never
    exposes composition's private ``_execution_store``/``_ledger_provider``.
    """

    schema_version: str
    view_identity: str
    composition_identity: str
    execution_store_identity: str
    gateway_identity: str
    account_id: str
    ledger_provider_identity: str
    session_date: dt.date
    verified_at: dt.datetime
    _composition: VerifiedFormalPaperServiceComposition = field(
        repr=False, compare=False
    )
    _attestation: _ClosureViewAttestation = field(repr=False, compare=False)

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        del protocol
        raise TypeError("formal PAPER closure view is process-local")

    def recover_oms_under_terminal_child(
        self, *, terminal_child: object, step_kind: str
    ) -> RecoveryResult:
        """Fresh OMS recovery under a live terminal child; never yields a store.

        ``oms_recovery`` uses the committing transaction internally and returns
        only an immutable ``RecoveryResult``. Every other step uses rollback-only
        inspect internally; callers cannot upgrade the result to a write.
        """
        store = _closure_view_execution_store(self).store
        if step_kind == "oms_recovery":
            with store.transaction_under_terminal_child(
                terminal_child=terminal_child, step_kind="oms_recovery"
            ) as repo:
                return recover_repository_state(repo)
        with store.inspect_repository_under_terminal_child(
            terminal_child=terminal_child, step_kind=step_kind
        ) as repo:
            return recover_repository_state(repo)

    @contextmanager
    def recover_oms_when_barrier_closed(
        self,
    ) -> Iterator[tuple[RecoveryResult, SessionBarrierRow]]:
        """Fresh OMS recovery + CLOSED barrier row under rollback-only inspect.

        Yields immutable recovery facts and the exact ``SessionBarrierRow`` while
        the CLOSED inspect remains held (for lock-scoped evidence re-read). Never
        exposes repository, connection, or store to the caller.
        """
        store = _closure_view_execution_store(self).store
        with store.inspect_repository_when_barrier_closed() as repo:
            row = store.read_session_barrier_row()
            if type(row) is not SessionBarrierRow:
                raise FormalPaperServiceError()
            recovery = recover_repository_state(repo)
            yield recovery, row

    @property
    def broker_store(self) -> VerifiedFormalPaperBrokerStoreCapability:
        return _closure_view_execution_store(self).broker_store

    @property
    def binding(self) -> VerifiedFormalPaperBrokerPolicyBinding:
        return _closure_view_execution_store(self).binding

    @property
    def account(self) -> VerifiedFormalPaperAccountDescriptor:
        return _closure_view_execution_store(self).account

    @property
    def environment(self) -> VerifiedPaperRuntimeEnvironment:
        return _closure_view_execution_store(self).environment

    @property
    def policy(self) -> VerifiedPaperExecutionPolicy:
        return _closure_view_execution_store(self).policy

    def hold_terminal_closure(self, closure: object) -> AbstractContextManager[object]:
        """Hold the B1 anchored lock for one durable terminal closure sequence."""
        return hold_formal_terminal_closure(
            capability=_closure_view_execution_store(self),
            closure=closure,
            now=_utc_now(),
        )

    def hold_terminal_step(
        self, context: object, *, step_kind: str
    ) -> AbstractContextManager[object]:
        """Mint one single-step terminal child under an already-held context."""
        return hold_formal_terminal_step(
            context,
            capability=_closure_view_execution_store(self),
            step_kind=step_kind,  # type: ignore[arg-type]
        )

    def bind_terminal_successor(
        self, context: object, *, terminal_successor_identity: str
    ) -> str:
        """Bind the exact successor under the live ``terminal_successor`` child."""
        return bind_formal_terminal_successor(
            context,
            capability=_closure_view_execution_store(self),
            terminal_successor_identity=terminal_successor_identity,
        )

    def transition_to_closed(
        self,
        *,
        closure: object,
        terminal_successor_identity: str,
        now: dt.datetime,
    ) -> object:
        """Formal CLOSING → CLOSED under an active ``closing_to_closed`` child."""
        return transition_formal_session_barrier_to_closed(
            capability=_closure_view_execution_store(self),
            closure=closure,
            terminal_successor_identity=terminal_successor_identity,
            now=now,
        )


class _Clock:
    def now(self) -> dt.datetime:
        return _utc_now()


class _FormalStoreOpener:
    def __init__(self, owner: _Owner) -> None:
        self._owner = owner

    def open(self) -> ExecutionStore:
        self._owner.fresh()
        return self._owner.execution_store.store


class _FormalServiceFactory:
    def __init__(self, owner: _Owner) -> None:
        self._owner = owner

    def build(
        self,
        *,
        store: ExecutionStore,
        gateway: GatewayTransport,
        cancel_gateway: GatewayCancelTransport,
    ) -> ExecutionService:
        try:
            self._owner.fresh()
            expected = self._owner.gateway_factory.open()
            if (
                store is not self._owner.execution_store.store
                or gateway is not expected.submit
                or cancel_gateway is not expected.cancel
            ):
                raise ValueError
            return ExecutionService(
                store=store,
                gateway=gateway,
                cancel_gateway=cancel_gateway,
                clock=self._owner.clock,
                worker_id=_WORKER_ID,
                lease_duration=_LEASE,
                risk_counter_scope=self._owner.execution_store.account.risk_counter_scope,
                ledger_context_provider=self._owner.ledger_provider,
            )
        except Exception:
            pass
        raise FormalPaperServiceError() from None


class _Owner:
    def __init__(
        self,
        *,
        execution_store: VerifiedFormalPaperExecutionStoreCapability,
        ledger_provider: VerifiedFormalPaperLedgerContextProvider,
        gateway_factory: PaperGatewayFactory,
    ) -> None:
        self.execution_store = execution_store
        self.ledger_provider = ledger_provider
        self.gateway_factory = gateway_factory
        self.clock = _Clock()

    def fresh(self) -> None:
        now = self.clock.now()
        store = verify_existing_formal_paper_execution_store_capability(
            capability=self.execution_store, now=now
        )
        provider = verify_existing_formal_paper_ledger_context_provider(
            provider=self.ledger_provider, now=now
        )
        if (
            store is not self.execution_store
            or provider is not self.ledger_provider
            or provider._execution_store is not store
            or not store.store.session_barrier_enabled()
            or not store.broker_store.store.session_barrier_enabled()
        ):
            raise FormalPaperServiceError()


class _Failure(Exception):
    pass


def _create_api():  # type: ignore[no-untyped-def]
    key = secrets.token_bytes(32)

    def token(value: VerifiedFormalPaperServiceComposition) -> bytes:
        return hmac.new(
            key, canonical_json_bytes(_payload(value)), hashlib.sha256
        ).digest()

    def valid(value: VerifiedFormalPaperServiceComposition) -> bool:
        try:
            return type(value._attestation) is _Attestation and hmac.compare_digest(
                value._attestation.token, token(value)
            )
        except Exception:
            return False

    def open_verified_formal_paper_service_composition(
        *,
        execution_store: VerifiedFormalPaperExecutionStoreCapability,
        ledger_provider: VerifiedFormalPaperLedgerContextProvider,
        now: dt.datetime,
    ) -> VerifiedFormalPaperServiceComposition:
        try:
            timestamp = _utc(now)
            store = verify_existing_formal_paper_execution_store_capability(
                capability=execution_store, now=timestamp
            )
            provider = verify_existing_formal_paper_ledger_context_provider(
                provider=ledger_provider, now=timestamp
            )
            if store is not execution_store or provider._execution_store is not store:
                raise _Failure
            gateway_factory = open_verified_formal_paper_gateway_factory(
                store_capability=store.broker_store,
                environment=store.environment,
                policy=store.policy,
                binding=store.binding,
                account=store.account,
                now=timestamp,
            )
            gateway = gateway_factory.open()
            owner = _Owner(
                execution_store=store,
                ledger_provider=provider,
                gateway_factory=gateway_factory,
            )
            store_opener = _FormalStoreOpener(owner)
            service_factory = _FormalServiceFactory(owner)
            stable = {
                "schema_version": _SCHEMA,
                "execution_store_identity": store.store_identity,
                "gateway_identity": gateway.gateway_identity,
                "ledger_provider_identity": provider.provider_identity,
                "account_id": store.account_id,
                "worker_id": _WORKER_ID,
                "lease_seconds": int(_LEASE.total_seconds()),
            }
            value = VerifiedFormalPaperServiceComposition(
                schema_version=_SCHEMA,
                composition_identity=_digest(stable),
                execution_store_identity=store.store_identity,
                gateway_identity=gateway.gateway_identity,
                ledger_provider_identity=provider.provider_identity,
                account_id=store.account_id,
                worker_id=_WORKER_ID,
                lease_seconds=int(_LEASE.total_seconds()),
                verified_at=timestamp,
                store_opener=store_opener,
                gateway_factory=gateway_factory,
                service_factory=service_factory,
                _execution_store=store,
                _ledger_provider=provider,
                _attestation=_Attestation(b""),
            )
            object.__setattr__(value, "_attestation", _Attestation(token(value)))
            if not valid(value):
                raise _Failure
            return value
        except Exception:
            pass
        raise FormalPaperServiceError() from None

    def verify_existing_formal_paper_service_composition(
        *, composition: VerifiedFormalPaperServiceComposition, now: dt.datetime
    ) -> VerifiedFormalPaperServiceComposition:
        try:
            timestamp = _utc(now)
            if (
                type(composition) is not VerifiedFormalPaperServiceComposition
                or not valid(composition)
                or timestamp < composition.verified_at
            ):
                raise _Failure
            store = verify_existing_formal_paper_execution_store_capability(
                capability=composition._execution_store, now=timestamp
            )
            provider = verify_existing_formal_paper_ledger_context_provider(
                provider=composition._ledger_provider, now=timestamp
            )
            gateway = composition.gateway_factory.open()
            if (
                store is not composition._execution_store
                or provider is not composition._ledger_provider
                or provider._execution_store is not store
                or gateway.gateway_identity != composition.gateway_identity
                or composition.composition_identity != _digest(_stable(composition))
            ):
                raise _Failure
            return composition
        except Exception:
            pass
        raise FormalPaperServiceError() from None

    return (
        open_verified_formal_paper_service_composition,
        verify_existing_formal_paper_service_composition,
    )


(
    open_verified_formal_paper_service_composition,
    verify_existing_formal_paper_service_composition,
) = _create_api()
del _create_api


def _create_closure_view_api():  # type: ignore[no-untyped-def]
    key = secrets.token_bytes(32)

    def token(value: VerifiedFormalPaperClosureView) -> bytes:
        return hmac.new(
            key, canonical_json_bytes(_closure_view_payload(value)), hashlib.sha256
        ).digest()

    def valid(value: VerifiedFormalPaperClosureView) -> bool:
        try:
            return type(value._attestation) is _ClosureViewAttestation and (
                hmac.compare_digest(value._attestation.token, token(value))
            )
        except Exception:
            return False

    def open_formal_paper_closure_view(
        *,
        composition: VerifiedFormalPaperServiceComposition,
        now: dt.datetime,
    ) -> VerifiedFormalPaperClosureView:
        try:
            timestamp = _utc(now)
            verified = verify_existing_formal_paper_service_composition(
                composition=composition, now=timestamp
            )
            if verified is not composition:
                raise _Failure
            execution_store = composition._execution_store
            stable = {
                "schema_version": _CLOSURE_VIEW_SCHEMA,
                "composition_identity": composition.composition_identity,
                "execution_store_identity": execution_store.store_identity,
                "gateway_identity": execution_store.gateway_identity,
                "account_id": execution_store.account_id,
                "ledger_provider_identity": composition.ledger_provider_identity,
                "session_date": execution_store.policy.session_date.isoformat(),
            }
            view = VerifiedFormalPaperClosureView(
                schema_version=_CLOSURE_VIEW_SCHEMA,
                view_identity=_digest(stable),
                composition_identity=composition.composition_identity,
                execution_store_identity=execution_store.store_identity,
                gateway_identity=execution_store.gateway_identity,
                account_id=execution_store.account_id,
                ledger_provider_identity=composition.ledger_provider_identity,
                session_date=execution_store.policy.session_date,
                verified_at=timestamp,
                _composition=composition,
                _attestation=_ClosureViewAttestation(b""),
            )
            object.__setattr__(view, "_attestation", _ClosureViewAttestation(token(view)))
            if not valid(view):
                raise _Failure
            return view
        except Exception:
            pass
        raise FormalPaperServiceError() from None

    def verify_existing_formal_paper_closure_view(
        *, view: VerifiedFormalPaperClosureView, now: dt.datetime
    ) -> VerifiedFormalPaperClosureView:
        try:
            timestamp = _utc(now)
            if (
                type(view) is not VerifiedFormalPaperClosureView
                or not valid(view)
                or timestamp < view.verified_at
            ):
                raise _Failure
            composition = verify_existing_formal_paper_service_composition(
                composition=view._composition, now=timestamp
            )
            if composition is not view._composition:
                raise _Failure
            execution_store = composition._execution_store
            if (
                composition.composition_identity != view.composition_identity
                or execution_store.store_identity != view.execution_store_identity
                or execution_store.gateway_identity != view.gateway_identity
                or execution_store.account_id != view.account_id
                or composition.ledger_provider_identity != view.ledger_provider_identity
                or execution_store.policy.session_date != view.session_date
                or view.view_identity != _digest(_closure_view_stable(view))
            ):
                raise _Failure
            return view
        except Exception:
            pass
        raise FormalPaperServiceError() from None

    return (
        open_formal_paper_closure_view,
        verify_existing_formal_paper_closure_view,
    )


(
    open_formal_paper_closure_view,
    verify_existing_formal_paper_closure_view,
) = _create_closure_view_api()
del _create_closure_view_api


def _closure_view_execution_store(
    view: VerifiedFormalPaperClosureView,
) -> VerifiedFormalPaperExecutionStoreCapability:
    """Fresh-verify the view and composition; never cache the extracted capability."""
    try:
        timestamp = _utc_now()
        verified = verify_existing_formal_paper_closure_view(view=view, now=timestamp)
        if verified is not view:
            raise _Failure
        composition = verify_existing_formal_paper_service_composition(
            composition=view._composition, now=timestamp
        )
        if composition is not view._composition:
            raise _Failure
        return composition._execution_store
    except Exception:
        pass
    raise FormalPaperServiceError() from None


def _closure_view_stable(value: VerifiedFormalPaperClosureView) -> dict[str, object]:
    return {
        "schema_version": value.schema_version,
        "composition_identity": value.composition_identity,
        "execution_store_identity": value.execution_store_identity,
        "gateway_identity": value.gateway_identity,
        "account_id": value.account_id,
        "ledger_provider_identity": value.ledger_provider_identity,
        "session_date": value.session_date.isoformat(),
    }


def _closure_view_payload(value: VerifiedFormalPaperClosureView) -> dict[str, object]:
    return {
        **_closure_view_stable(value),
        "verified_at": utc_datetime_text(value.verified_at),
    }


def _stable(value: VerifiedFormalPaperServiceComposition) -> dict[str, object]:
    return {
        "schema_version": value.schema_version,
        "execution_store_identity": value.execution_store_identity,
        "gateway_identity": value.gateway_identity,
        "ledger_provider_identity": value.ledger_provider_identity,
        "account_id": value.account_id,
        "worker_id": value.worker_id,
        "lease_seconds": value.lease_seconds,
    }


def _payload(value: VerifiedFormalPaperServiceComposition) -> dict[str, object]:
    return {**_stable(value), "verified_at": utc_datetime_text(value.verified_at)}


def _digest(value: dict[str, object]) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _utc(value: dt.datetime) -> dt.datetime:
    if type(value) is not dt.datetime or value.tzinfo is None or value.utcoffset() != dt.timedelta(0):
        raise _Failure
    return value


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


__all__ = [
    "FormalPaperServiceError",
    "VerifiedFormalPaperClosureView",
    "VerifiedFormalPaperServiceComposition",
    "open_formal_paper_closure_view",
    "open_verified_formal_paper_service_composition",
    "verify_existing_formal_paper_closure_view",
    "verify_existing_formal_paper_service_composition",
]
