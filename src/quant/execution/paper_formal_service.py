"""Formal PAPER composition of OMS store, gateway and ledger provider."""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import secrets
from dataclasses import dataclass, field
from typing import NoReturn, SupportsIndex

from quant.domain.canonical_wire import canonical_json_bytes, utc_datetime_text
from quant.execution.cli_ports import PaperGatewayFactory, ServiceFactory, StoreOpener
from quant.execution.gateways.contracts import GatewayCancelTransport, GatewayTransport
from quant.execution.paper_formal_execution_store import (
    VerifiedFormalPaperExecutionStoreCapability,
    verify_existing_formal_paper_execution_store_capability,
)
from quant.execution.paper_formal_gateway import (
    open_verified_formal_paper_gateway_factory,
)
from quant.execution.paper_formal_ledger import (
    VerifiedFormalPaperLedgerContextProvider,
    verify_existing_formal_paper_ledger_context_provider,
)
from quant.execution.service import ExecutionService
from quant.execution.store import ExecutionStore

_SCHEMA = "formal-paper-service-composition-v1"
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
    "VerifiedFormalPaperServiceComposition",
    "open_verified_formal_paper_service_composition",
    "verify_existing_formal_paper_service_composition",
]
