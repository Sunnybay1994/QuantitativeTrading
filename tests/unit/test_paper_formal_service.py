from __future__ import annotations

import datetime as dt
import hashlib
from types import SimpleNamespace

import pytest

from quant.execution.cli_ports import build_verified_paper_gateway
from quant.execution.gateways.contracts import (
    DispatchCertainty,
    GatewayCancelResult,
    GatewayDispatchResult,
)
from quant.execution.paper_formal_execution_store import (
    VerifiedFormalPaperExecutionStoreCapability,
)
from quant.execution.paper_formal_ledger import (
    VerifiedFormalPaperLedgerContextProvider,
)
from quant.execution import paper_formal_service as formal
from quant.execution.service import ExecutionService
from quant.execution.store import ExecutionStore

NOW = dt.datetime(2026, 8, 10, 1, tzinfo=dt.timezone.utc)


def _hex(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


class _Transport:
    def submit(self, *, command, dispatch_attempt: int, now: dt.datetime):  # type: ignore[no-untyped-def]
        return GatewayDispatchResult(
            command.command_id, dispatch_attempt, DispatchCertainty.SENT, ()
        )

    def cancel(self, *, command, dispatch_attempt: int, now: dt.datetime):  # type: ignore[no-untyped-def]
        return GatewayCancelResult(
            command.cancel_id, dispatch_attempt, DispatchCertainty.SENT, ()
        )


class _GatewayFactory:
    def __init__(self) -> None:
        transport = _Transport()
        self.gateway = build_verified_paper_gateway(
            gateway_identity=_hex("gateway"), submit=transport, cancel=transport
        )

    def identity(self) -> str:
        return self.gateway.gateway_identity

    def open(self):  # type: ignore[no-untyped-def]
        return self.gateway


def _inputs(tmp_path):  # type: ignore[no-untyped-def]
    store = ExecutionStore.open("sqlite:///oms.sqlite3", trusted_root=tmp_path)
    capability = object.__new__(VerifiedFormalPaperExecutionStoreCapability)
    object.__setattr__(capability, "store_identity", _hex("store"))
    object.__setattr__(capability, "account_id", _hex("account"))
    object.__setattr__(capability, "_store", store)
    object.__setattr__(capability, "broker_store", SimpleNamespace())
    object.__setattr__(capability, "environment", SimpleNamespace())
    object.__setattr__(capability, "policy", SimpleNamespace())
    object.__setattr__(capability, "binding", SimpleNamespace())
    object.__setattr__(
        capability,
        "account",
        SimpleNamespace(risk_counter_scope="paper-formal-account"),
    )
    provider = object.__new__(VerifiedFormalPaperLedgerContextProvider)
    object.__setattr__(provider, "provider_identity", _hex("provider"))
    object.__setattr__(provider, "_execution_store", capability)
    return capability, provider


def test_composition_builds_only_with_retained_store_and_gateway(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    capability, provider = _inputs(tmp_path)
    gateway_factory = _GatewayFactory()
    monkeypatch.setattr(formal, "_utc_now", lambda: NOW)
    monkeypatch.setattr(
        formal,
        "verify_existing_formal_paper_execution_store_capability",
        lambda *, capability, now: capability,
    )
    monkeypatch.setattr(
        formal,
        "verify_existing_formal_paper_ledger_context_provider",
        lambda *, provider, now: provider,
    )
    monkeypatch.setattr(
        formal,
        "open_verified_formal_paper_gateway_factory",
        lambda **kwargs: gateway_factory,
    )
    composition = formal.open_verified_formal_paper_service_composition(
        execution_store=capability, ledger_provider=provider, now=NOW
    )
    gateway = composition.gateway_factory.open()
    opened_store = composition.store_opener.open()
    service = composition.service_factory.build(
        store=opened_store,
        gateway=gateway.submit,
        cancel_gateway=gateway.cancel,
    )
    assert type(service) is ExecutionService
    assert composition.worker_id == "formal-paper-worker-v1"
    assert composition.lease_seconds == 60
    assert (
        formal.verify_existing_formal_paper_service_composition(
            composition=composition, now=NOW
        )
        is composition
    )

    other = ExecutionStore.open("sqlite:///other.sqlite3", trusted_root=tmp_path)
    with pytest.raises(formal.FormalPaperServiceError) as caught:
        composition.service_factory.build(
            store=other, gateway=gateway.submit, cancel_gateway=gateway.cancel
        )
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    other.close()
    opened_store.close()


def test_hostile_fresh_verifier_is_sanitized(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    capability, provider = _inputs(tmp_path)

    def hostile(**kwargs: object) -> object:
        del kwargs
        raise RuntimeError("TOKEN=/hostile/path")

    monkeypatch.setattr(
        formal,
        "verify_existing_formal_paper_execution_store_capability",
        hostile,
    )
    with pytest.raises(formal.FormalPaperServiceError) as caught:
        formal.open_verified_formal_paper_service_composition(
            execution_store=capability, ledger_provider=provider, now=NOW
        )
    assert str(caught.value) == "PAPER_FORMAL_SERVICE_INVALID"
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    capability.store.close()
