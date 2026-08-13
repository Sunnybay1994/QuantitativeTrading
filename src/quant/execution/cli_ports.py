"""Strict dependency ports and verified inputs for the PAPER operator CLI."""

from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from quant.domain.canonical_wire import canonical_json_bytes, utc_datetime_text
from quant.execution.config import trading_config_identity
from quant.execution.contracts import (
    AccountSnapshot,
    ExecutionEvent,
    VerifiedMarketSnapshot,
    build_account_snapshot_identity,
    build_execution_event_identity,
    build_verified_market_snapshot_identity,
)
from quant.execution.gateways.contracts import GatewayCancelTransport, GatewayTransport
from quant.execution.reconcile import (
    BrokerOrderObservation,
    BrokerSnapshotFinality,
)
from quant.execution.service import ExecutionService
from quant.execution.store import ExecutionStore
from quant.portfolio.order_planner import OrderPlanTarget, OrderPlannerConfig

_HEX = frozenset("0123456789abcdef")


class CliPortError(ValueError):
    """Stable failure raised when a dependency port returns untrusted data."""


@runtime_checkable
class CliClock(Protocol):
    def now(self) -> dt.datetime:
        """Return a timezone-aware UTC instant."""
        ...


@runtime_checkable
class StoreOpener(Protocol):
    def open(self) -> ExecutionStore:
        """Open the configured store under a trusted root."""
        ...


@runtime_checkable
class TargetLoader(Protocol):
    def load(self) -> VerifiedTargetLoad:
        """Load a receipt-backed target selection."""
        ...


@runtime_checkable
class PlanningLoader(Protocol):
    def load(self) -> VerifiedPlanningLoad:
        """Load market, account and configuration inputs."""
        ...


@runtime_checkable
class ServiceFactory(Protocol):
    def build(
        self,
        *,
        store: ExecutionStore,
        gateway: GatewayTransport,
        cancel_gateway: GatewayCancelTransport,
    ) -> ExecutionService:
        """Build the durable execution service."""
        ...


@runtime_checkable
class PaperGatewayFactory(Protocol):
    def identity(self) -> str:
        """Return the retained PAPER adapter identity without opening it."""
        ...

    def open(self) -> VerifiedPaperGateway:
        """Open a PAPER-only gateway and its retained identity."""
        ...


@runtime_checkable
class BrokerSnapshotPort(Protocol):
    def query_and_verify(self, *, gateway_identity: str) -> VerifiedBrokerEvidence:
        """Query PAPER state and verify its retained evidence."""
        ...


@dataclass(frozen=True, slots=True)
class VerifiedTargetLoad:
    target_identity: str
    receipt_identity: str
    targets: tuple[OrderPlanTarget, ...]
    verification_identity: str


@dataclass(frozen=True, slots=True)
class VerifiedPlanningLoad:
    market: VerifiedMarketSnapshot
    account: AccountSnapshot
    planner_config: OrderPlannerConfig
    verification_identity: str


@dataclass(frozen=True, slots=True)
class VerifiedPaperGateway:
    gateway_identity: str
    submit: GatewayTransport
    cancel: GatewayCancelTransport
    verification_identity: str


@dataclass(frozen=True, slots=True)
class VerifiedBrokerEvidence:
    source_identity: str
    gateway_identity: str
    as_of: dt.datetime
    finality: BrokerSnapshotFinality
    account: AccountSnapshot
    orders: tuple[BrokerOrderObservation, ...]
    events: tuple[ExecutionEvent, ...]
    verification_identity: str


@dataclass(frozen=True, slots=True)
class CliDependencies:
    store_opener: StoreOpener
    target_loader: TargetLoader
    planning_loader: PlanningLoader
    service_factory: ServiceFactory
    paper_gateway_factory: PaperGatewayFactory
    broker_snapshot_port: BrokerSnapshotPort
    clock: CliClock

    def __post_init__(self) -> None:
        values = (
            (self.store_opener, "open"),
            (self.target_loader, "load"),
            (self.planning_loader, "load"),
            (self.service_factory, "build"),
            (self.paper_gateway_factory, "open"),
            (self.paper_gateway_factory, "identity"),
            (self.broker_snapshot_port, "query_and_verify"),
            (self.clock, "now"),
        )
        if any(not callable(getattr(value, method, None)) for value, method in values):
            raise CliPortError("CLI_DEPENDENCIES_INVALID")


def build_verified_target_load(
    *,
    target_identity: str,
    receipt_identity: str,
    targets: tuple[OrderPlanTarget, ...],
) -> VerifiedTargetLoad:
    """Bind receipt identity and canonical target values into one proof."""
    if not _hex64(target_identity) or not _hex64(receipt_identity):
        raise CliPortError("CLI_TARGET_INVALID")
    if type(targets) is not tuple or any(type(item) is not OrderPlanTarget for item in targets):
        raise CliPortError("CLI_TARGET_INVALID")
    try:
        reproved_targets = tuple(
            OrderPlanTarget(
                symbol=item.symbol,
                market=item.market,
                connect_route=item.connect_route,
                target_weight=item.target_weight,
            )
            for item in targets
        )
    except Exception:
        raise CliPortError("CLI_TARGET_INVALID") from None
    if targets != reproved_targets:
        raise CliPortError("CLI_TARGET_INVALID")
    if targets != tuple(sorted(targets, key=_target_key)) or len(
        {(item.market, item.symbol, item.connect_route) for item in targets}
    ) != len(targets):
        raise CliPortError("CLI_TARGET_INVALID")
    payload: dict[str, object] = {
        "receipt_identity": receipt_identity,
        "target_identity": target_identity,
        "targets": [
            {
                "connect_route": None if item.connect_route is None else item.connect_route.value,
                "market": item.market.value,
                "symbol": item.symbol,
                "target_weight": str(item.target_weight),
            }
            for item in targets
        ],
    }
    return VerifiedTargetLoad(
        target_identity=target_identity,
        receipt_identity=receipt_identity,
        targets=targets,
        verification_identity=_digest(payload),
    )


def verify_target_load(value: VerifiedTargetLoad) -> VerifiedTargetLoad:
    if type(value) is not VerifiedTargetLoad:
        raise CliPortError("CLI_TARGET_INVALID")
    expected = build_verified_target_load(
        target_identity=value.target_identity,
        receipt_identity=value.receipt_identity,
        targets=value.targets,
    )
    if value != expected:
        raise CliPortError("CLI_TARGET_INVALID")
    return value


def build_verified_planning_load(
    *,
    market: VerifiedMarketSnapshot,
    account: AccountSnapshot,
    planner_config: OrderPlannerConfig,
) -> VerifiedPlanningLoad:
    """Re-prove all planning identities with their production builders."""
    try:
        market_id = build_verified_market_snapshot_identity(market)
        account_id = build_account_snapshot_identity(account)
        trading_id = trading_config_identity(planner_config.trading_config)
        # Re-running the dataclass proof rejects a forged composed config identity.
        OrderPlannerConfig(
            config_identity=planner_config.config_identity,
            trading_config=planner_config.trading_config,
            a_share_rule_config=planner_config.a_share_rule_config,
            connect_rule_configs=planner_config.connect_rule_configs,
            execution_cost_schedule=planner_config.execution_cost_schedule,
            fx_snapshot=planner_config.fx_snapshot,
            minimum_order_notionals=planner_config.minimum_order_notionals,
        )
    except Exception:
        raise CliPortError("CLI_PLANNING_INPUT_INVALID") from None
    payload: dict[str, object] = {
        "account_snapshot_id": account_id,
        "market_snapshot_id": market_id,
        "planner_config_identity": planner_config.config_identity,
        "trading_config_identity": trading_id,
    }
    return VerifiedPlanningLoad(market, account, planner_config, _digest(payload))


def verify_planning_load(value: VerifiedPlanningLoad) -> VerifiedPlanningLoad:
    if type(value) is not VerifiedPlanningLoad:
        raise CliPortError("CLI_PLANNING_INPUT_INVALID")
    expected = build_verified_planning_load(
        market=value.market,
        account=value.account,
        planner_config=value.planner_config,
    )
    if value != expected:
        raise CliPortError("CLI_PLANNING_INPUT_INVALID")
    return value


def build_verified_paper_gateway(
    *, gateway_identity: str, submit: GatewayTransport, cancel: GatewayCancelTransport
) -> VerifiedPaperGateway:
    """Bind structural PAPER transports to a retained adapter identity."""
    if (
        not _hex64(gateway_identity)
        or not isinstance(submit, GatewayTransport)
        or not isinstance(cancel, GatewayCancelTransport)
    ):
        raise CliPortError("CLI_GATEWAY_INVALID")
    proof = _digest({"gateway_identity": gateway_identity, "mode": "PAPER"})
    return VerifiedPaperGateway(gateway_identity, submit, cancel, proof)


def verify_paper_gateway(value: VerifiedPaperGateway) -> VerifiedPaperGateway:
    if type(value) is not VerifiedPaperGateway:
        raise CliPortError("CLI_GATEWAY_INVALID")
    expected = build_verified_paper_gateway(
        gateway_identity=value.gateway_identity, submit=value.submit, cancel=value.cancel
    )
    if value.verification_identity != expected.verification_identity:
        raise CliPortError("CLI_GATEWAY_INVALID")
    return value


def build_verified_broker_evidence(
    *,
    source_identity: str,
    gateway_identity: str,
    as_of: dt.datetime,
    finality: BrokerSnapshotFinality,
    account: AccountSnapshot,
    orders: tuple[BrokerOrderObservation, ...],
    events: tuple[ExecutionEvent, ...],
) -> VerifiedBrokerEvidence:
    """Build the retained-evidence proof accepted from the broker query port."""
    try:
        if not _hex64(source_identity) or not _hex64(gateway_identity) or not _utc(as_of):
            raise ValueError
        if finality not in {"INTRADAY", "END_OF_DAY"}:
            raise ValueError
        account_id = build_account_snapshot_identity(account)
        event_ids = [build_execution_event_identity(item) for item in events]
        if type(orders) is not tuple or type(events) is not tuple:
            raise ValueError
        reproved_orders = tuple(
            BrokerOrderObservation(
                broker_order_id=item.broker_order_id,
                command_id=item.command_id,
                status=item.status,
                cumulative_quantity=item.cumulative_quantity,
                observed_event_ids=item.observed_event_ids,
            )
            for item in orders
        )
        if reproved_orders != orders:
            raise ValueError
    except Exception:
        raise CliPortError("CLI_BROKER_EVIDENCE_INVALID") from None
    payload: dict[str, object] = {
        "account_snapshot_id": account_id,
        "as_of": utc_datetime_text(as_of),
        "event_ids": event_ids,
        "finality": finality,
        "gateway_identity": gateway_identity,
        "orders": [
            {
                "broker_order_id_sha256": hashlib.sha256(
                    item.broker_order_id.encode("utf-8")
                ).hexdigest(),
                "command_id": item.command_id,
                "cumulative_quantity": item.cumulative_quantity,
                "observed_event_ids": list(item.observed_event_ids),
                "status": item.status.value,
            }
            for item in orders
        ],
        "source_identity": source_identity,
    }
    return VerifiedBrokerEvidence(
        source_identity,
        gateway_identity,
        as_of,
        finality,
        account,
        orders,
        events,
        _digest(payload),
    )


def verify_broker_evidence(value: VerifiedBrokerEvidence) -> VerifiedBrokerEvidence:
    if type(value) is not VerifiedBrokerEvidence:
        raise CliPortError("CLI_BROKER_EVIDENCE_INVALID")
    expected = build_verified_broker_evidence(
        source_identity=value.source_identity,
        gateway_identity=value.gateway_identity,
        as_of=value.as_of,
        finality=value.finality,
        account=value.account,
        orders=value.orders,
        events=value.events,
    )
    if value != expected:
        raise CliPortError("CLI_BROKER_EVIDENCE_INVALID")
    return value


def _target_key(value: OrderPlanTarget) -> tuple[str, str, str]:
    return (
        value.market.value,
        value.symbol,
        "" if value.connect_route is None else value.connect_route.value,
    )


def _digest(value: dict[str, object]) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _hex64(value: object) -> bool:
    return type(value) is str and len(value) == 64 and all(char in _HEX for char in value)


def _utc(value: object) -> bool:
    return (
        type(value) is dt.datetime
        and value.tzinfo is not None
        and value.utcoffset() == dt.timedelta(0)
    )


__all__ = [
    "BrokerSnapshotPort",
    "CliClock",
    "CliDependencies",
    "CliPortError",
    "PaperGatewayFactory",
    "PlanningLoader",
    "ServiceFactory",
    "StoreOpener",
    "TargetLoader",
    "VerifiedBrokerEvidence",
    "VerifiedPaperGateway",
    "VerifiedPlanningLoad",
    "VerifiedTargetLoad",
    "build_verified_broker_evidence",
    "build_verified_paper_gateway",
    "build_verified_planning_load",
    "build_verified_target_load",
    "verify_broker_evidence",
    "verify_paper_gateway",
    "verify_planning_load",
    "verify_target_load",
]
