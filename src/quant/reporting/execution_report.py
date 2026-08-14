"""Deterministic, redacted PAPER execution reporting over verified M4 facts."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from dataclasses import dataclass
from decimal import Decimal

from quant.backtest.ledger import LedgerState
from quant.domain.enums import (
    Currency,
    ExecutionEventType,
    Market,
    OrderSide,
    OrderStatus,
)
from quant.execution.contracts import (
    build_execution_event_identity,
    build_order_command_identity,
)
from quant.execution.oms import OrderAggregate, new_order_aggregate, reduce_order
from quant.execution.reconcile import RecoveryResult, ReconciliationResult
from quant.execution.risk_wire import (
    DurableOrderRiskDecision,
    DurableRiskTransitionReceipt,
    verify_risk_receipt_semantic_closure,
)

_SCHEMA = "m4-execution-report-v1"
_HEX = frozenset("0123456789abcdef")
_FILL_TYPES = frozenset({ExecutionEventType.PARTIAL_FILL, ExecutionEventType.FILL})
_CODE = re.compile(r"^[A-Z][A-Z0-9_.-]{0,79}$")
_SYMBOL = re.compile(r"^[0-9A-Z][0-9A-Z.]{0,31}$")


class ExecutionReportError(ValueError):
    """Stable, path-free failure for hostile or inconsistent report inputs."""


@dataclass(frozen=True, slots=True)
class ExecutionOrderLine:
    command_id: str
    symbol: str
    market: str
    side: str
    requested_quantity: int
    filled_quantity: int
    status: str
    broker_order_identity: str | None


@dataclass(frozen=True, slots=True)
class ExecutionFillLine:
    event_id: str
    command_id: str
    event_type: str
    cumulative_quantity: int
    last_quantity: int
    last_price: str | None
    fees: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class ExecutionPositionLine:
    symbol: str
    market: str
    quantity: int
    sellable_quantity: int
    avg_cost_currency: str
    avg_cost: str


@dataclass(frozen=True, slots=True)
class ExecutionCashLine:
    currency: str
    settled: str
    available: str
    receivable: str
    payable: str


@dataclass(frozen=True, slots=True)
class ExecutionRiskLine:
    plan_id: str
    rule: str
    accepted: bool
    code: str
    subject_identity: str


@dataclass(frozen=True, slots=True)
class ExecutionDifferenceLine:
    code: str
    action: str
    subject_identity: str
    local_identity: str | None
    broker_identity: str | None


@dataclass(frozen=True, slots=True)
class ExecutionReportTotals:
    commands: int
    orders: int
    fills: int
    positions: int
    cash_balances: int
    risk_events: int
    differences: int


@dataclass(frozen=True, slots=True)
class ExecutionReport:
    report_id: str
    as_of: dt.datetime
    recovery_id: str
    reconciliation_id: str
    local_disposition: str
    reconciliation_disposition: str
    gate_passed: bool
    checkpoint_id: str | None
    orders: tuple[ExecutionOrderLine, ...]
    fills: tuple[ExecutionFillLine, ...]
    positions: tuple[ExecutionPositionLine, ...]
    cash: tuple[ExecutionCashLine, ...]
    risk_events: tuple[ExecutionRiskLine, ...]
    differences: tuple[ExecutionDifferenceLine, ...]
    totals: ExecutionReportTotals

    def __post_init__(self) -> None:
        valid = False
        try:
            valid = _valid_report(self) and self.report_id == _report_identity(self)
        except Exception:
            pass
        if not valid:
            raise ExecutionReportError("EXECUTION_REPORT_INVALID") from None


def build_execution_report(
    *,
    recovery: RecoveryResult,
    reconciliation: ReconciliationResult,
    as_of: dt.datetime,
) -> ExecutionReport:
    """Build one content-addressed, redacted EOD operations view with zero I/O."""
    report: ExecutionReport | None = None
    try:
        checked_recovery = _verify_recovery(recovery)
        checked_reconciliation = _verify_reconciliation(reconciliation)
        if (
            not _utc(as_of)
            or checked_reconciliation.as_of != as_of
            or checked_reconciliation.local_recovery_id
            != checked_recovery.recovery_id
        ):
            raise ValueError

        command_ids = tuple(item.command_id for item in checked_recovery.commands)
        if command_ids != tuple(sorted(set(command_ids))):
            raise ValueError
        for command in checked_recovery.commands:
            if build_order_command_identity(command) != command.command_id:
                raise ValueError
        commands = {item.command_id: item for item in checked_recovery.commands}
        aggregate_ids = tuple(
            item.command_id for item in checked_recovery.order_aggregates
        )
        if aggregate_ids != tuple(sorted(set(aggregate_ids))):
            raise ValueError
        aggregates = {
            item.command_id: _verify_aggregate(item)
            for item in checked_recovery.order_aggregates
        }
        if set(commands) != set(aggregates):
            raise ValueError

        order_lines = tuple(
            sorted(
                (
                    ExecutionOrderLine(
                        command_id=command_id,
                        symbol=command.intent.symbol,
                        market=command.intent.market.value,
                        side=command.intent.side.value,
                        requested_quantity=command.intent.quantity,
                        filled_quantity=aggregates[command_id].filled_quantity,
                        status=aggregates[command_id].status.value,
                        broker_order_identity=_optional_text_identity(
                            aggregates[command_id].broker_order_id
                        ),
                    )
                    for command_id, command in commands.items()
                ),
                key=lambda item: item.command_id,
            )
        )

        fill_lines: list[ExecutionFillLine] = []
        event_ids = tuple(item.event_id for item in checked_recovery.events)
        if event_ids != tuple(sorted(set(event_ids))):
            raise ValueError
        events_by_id = {item.event_id: item for item in checked_recovery.events}
        for event in checked_recovery.events:
            if build_execution_event_identity(event) != event.event_id:
                raise ValueError
            if event.command_id not in commands:
                raise ValueError
            if event.event_type in _FILL_TYPES:
                fee_totals: dict[str, Decimal] = {}
                for fee in event.fees:
                    currency = fee.amount.currency.value
                    fee_totals[currency] = (
                        fee_totals.get(currency, Decimal(0)) + fee.amount.amount
                    )
                fill_lines.append(
                    ExecutionFillLine(
                        event_id=event.event_id,
                        command_id=event.command_id,
                        event_type=event.event_type.value,
                        cumulative_quantity=event.cumulative_quantity,
                        last_quantity=event.last_quantity,
                        last_price=None if event.last_price is None else str(event.last_price),
                        fees=tuple(
                            (currency, str(amount))
                            for currency, amount in sorted(fee_totals.items())
                        ),
                    )
                )

        applied_event_ids: list[str] = []
        for command_id, command in commands.items():
            aggregate = aggregates[command_id]
            projected = new_order_aggregate(command)
            for event_id in aggregate.applied_event_ids:
                projected_event = events_by_id.get(event_id)
                if projected_event is None or projected_event.command_id != command_id:
                    raise ValueError
                projected = reduce_order(projected, command, projected_event)
                applied_event_ids.append(event_id)
            if projected != aggregate:
                raise ValueError
        if tuple(sorted(applied_event_ids)) != event_ids:
            raise ValueError

        checkpoint = _verify_checkpoint(checked_recovery.checkpoint)
        positions = () if checkpoint is None else tuple(
            ExecutionPositionLine(
                symbol=item.symbol,
                market=item.market.value,
                quantity=item.quantity,
                sellable_quantity=item.sellable_quantity,
                avg_cost_currency=item.avg_cost.currency.value,
                avg_cost=str(item.avg_cost.amount),
            )
            for item in checkpoint.positions
        )
        cash = () if checkpoint is None else tuple(
            ExecutionCashLine(
                currency=item.currency.value,
                settled=str(item.settled),
                available=str(item.available),
                receivable=str(item.receivable),
                payable=str(item.payable),
            )
            for item in checkpoint.cash
        )

        verify_risk_receipt_semantic_closure(
            receipts=checked_recovery.risk_receipts,
            commands=checked_recovery.commands,
            cancel_commands=checked_recovery.cancel_commands,
        )
        risk_lines = _build_risk_lines(checked_recovery.risk_receipts)
        difference_lines = tuple(
            ExecutionDifferenceLine(
                code=item.code,
                action=item.action,
                subject_identity=_text_identity(item.subject),
                local_identity=item.local_identity,
                broker_identity=item.broker_identity,
            )
            for item in checked_reconciliation.differences
        )
        totals = ExecutionReportTotals(
            commands=len(commands),
            orders=len(order_lines),
            fills=len(fill_lines),
            positions=len(positions),
            cash_balances=len(cash),
            risk_events=len(risk_lines),
            differences=len(difference_lines),
        )
        values = {
            "as_of": as_of,
            "recovery_id": checked_recovery.recovery_id,
            "reconciliation_id": checked_reconciliation.reconciliation_id,
            "local_disposition": checked_recovery.disposition,
            "reconciliation_disposition": checked_reconciliation.disposition,
            "gate_passed": checked_reconciliation.gate_passed,
            "checkpoint_id": None if checkpoint is None else checkpoint.state_id,
            "orders": order_lines,
            "fills": tuple(sorted(fill_lines, key=lambda item: item.event_id)),
            "positions": positions,
            "cash": cash,
            "risk_events": risk_lines,
            "differences": difference_lines,
            "totals": totals,
        }
        provisional = ExecutionReport.__new__(ExecutionReport)
        object.__setattr__(provisional, "report_id", "0" * 64)
        for name, value in values.items():
            object.__setattr__(provisional, name, value)
        report = ExecutionReport(report_id=_report_identity(provisional), **values)  # type: ignore[arg-type]
    except Exception:
        pass
    if report is None:
        raise ExecutionReportError("EXECUTION_REPORT_INVALID") from None
    return report


def encode_execution_report(report: ExecutionReport) -> bytes:
    """Encode a verified report as platform-independent canonical JSON bytes."""
    encoded: bytes | None = None
    try:
        if type(report) is not ExecutionReport:
            raise ValueError
        checked = ExecutionReport(
            report_id=report.report_id,
            as_of=report.as_of,
            recovery_id=report.recovery_id,
            reconciliation_id=report.reconciliation_id,
            local_disposition=report.local_disposition,
            reconciliation_disposition=report.reconciliation_disposition,
            gate_passed=report.gate_passed,
            checkpoint_id=report.checkpoint_id,
            orders=report.orders,
            fills=report.fills,
            positions=report.positions,
            cash=report.cash,
            risk_events=report.risk_events,
            differences=report.differences,
            totals=report.totals,
        )
        encoded = _canonical(
            {"schema_version": _SCHEMA, "report_id": checked.report_id, **_payload(checked)}
        )
    except Exception:
        pass
    if encoded is None:
        raise ExecutionReportError("EXECUTION_REPORT_INVALID") from None
    return encoded


def _verify_recovery(value: object) -> RecoveryResult:
    if type(value) is not RecoveryResult:
        raise ValueError
    assert isinstance(value, RecoveryResult)
    return RecoveryResult(
        recovery_id=value.recovery_id,
        disposition=value.disposition,
        commands=value.commands,
        events=value.events,
        order_aggregates=value.order_aggregates,
        deliveries=value.deliveries,
        cancel_commands=value.cancel_commands,
        cancel_deliveries=value.cancel_deliveries,
        cancel_event_links=value.cancel_event_links,
        ledger_entries=value.ledger_entries,
        ledger_contexts=value.ledger_contexts,
        checkpoint=value.checkpoint,
        issues=value.issues,
        risk_receipts=value.risk_receipts,
    )


def _verify_reconciliation(value: object) -> ReconciliationResult:
    if type(value) is not ReconciliationResult:
        raise ValueError
    assert isinstance(value, ReconciliationResult)
    return ReconciliationResult(
        reconciliation_id=value.reconciliation_id,
        local_recovery_id=value.local_recovery_id,
        broker_snapshot_id=value.broker_snapshot_id,
        as_of=value.as_of,
        gate_passed=value.gate_passed,
        disposition=value.disposition,
        differences=value.differences,
    )


def _verify_aggregate(value: object) -> OrderAggregate:
    if type(value) is not OrderAggregate:
        raise ValueError
    assert isinstance(value, OrderAggregate)
    return OrderAggregate(
        command_id=value.command_id,
        status=value.status,
        filled_quantity=value.filled_quantity,
        broker_order_id=value.broker_order_id,
        reject_code=value.reject_code,
        applied_event_ids=value.applied_event_ids,
        command_quantity=value.command_quantity,
        last_event_at=value.last_event_at,
    )


def _verify_checkpoint(value: object) -> LedgerState | None:
    if value is None:
        return None
    if type(value) is not LedgerState:
        raise ValueError
    assert isinstance(value, LedgerState)
    return LedgerState(
        state_id=value.state_id,
        origin_account_snapshot_id=value.origin_account_snapshot_id,
        as_of_date=value.as_of_date,
        positions=value.positions,
        cash=value.cash,
        pending=value.pending,
        trading_credits=value.trading_credits,
        entitlements=value.entitlements,
        applied_event_ids=value.applied_event_ids,
        applied_actions=value.applied_actions,
        command_projections=value.command_projections,
    )


def _build_risk_lines(
    receipts: object,
) -> tuple[ExecutionRiskLine, ...]:
    if type(receipts) is not tuple:
        raise ValueError
    lines: list[ExecutionRiskLine] = []
    for receipt in receipts:
        if type(receipt) is not DurableRiskTransitionReceipt:
            raise ValueError
        if receipt.transition_kind == "CANCEL":
            continue
        decision = receipt.decision
        if type(decision) is not DurableOrderRiskDecision:
            raise ValueError
        for result in decision.rule_results:
            if (
                type(result.rule) is not str
                or not result.rule
                or type(result.accepted) is not bool
                or type(result.code) is not str
                or not result.code
                or type(result.subject) is not str
                or not result.subject
            ):
                raise ValueError
            lines.append(
                ExecutionRiskLine(
                    plan_id=decision.plan_id,
                    rule=result.rule,
                    accepted=result.accepted,
                    code=result.code,
                    subject_identity=_text_identity(result.subject),
                )
            )
    return tuple(
        sorted(lines, key=lambda item: (item.plan_id, item.rule, item.code, item.subject_identity))
    )


def _payload(report: ExecutionReport) -> dict[str, object]:
    return {
        "as_of": report.as_of.isoformat(),
        "recovery_id": report.recovery_id,
        "reconciliation_id": report.reconciliation_id,
        "local_disposition": report.local_disposition,
        "reconciliation_disposition": report.reconciliation_disposition,
        "gate_passed": report.gate_passed,
        "checkpoint_id": report.checkpoint_id,
        "orders": [_line(item) for item in report.orders],
        "fills": [_line(item) for item in report.fills],
        "positions": [_line(item) for item in report.positions],
        "cash": [_line(item) for item in report.cash],
        "risk_events": [_line(item) for item in report.risk_events],
        "differences": [_line(item) for item in report.differences],
        "totals": _line(report.totals),
    }


def _valid_report(report: ExecutionReport) -> bool:
    dispositions = {"READY", "QUERY_REQUIRED", "MANUAL_REQUIRED"}
    actions = {"AUTOMATIC_RETRY", "QUERY_REQUIRED", "MANUAL_REQUIRED"}
    if (
        not _hex64(report.report_id)
        or not _utc(report.as_of)
        or not _hex64(report.recovery_id)
        or not _hex64(report.reconciliation_id)
        or report.local_disposition not in dispositions
        or report.reconciliation_disposition not in dispositions
        or type(report.gate_passed) is not bool
        or (report.checkpoint_id is not None and not _hex64(report.checkpoint_id))
        or type(report.orders) is not tuple
        or type(report.fills) is not tuple
        or type(report.positions) is not tuple
        or type(report.cash) is not tuple
        or type(report.risk_events) is not tuple
        or type(report.differences) is not tuple
        or type(report.totals) is not ExecutionReportTotals
    ):
        return False
    if report.orders != tuple(sorted(report.orders, key=lambda item: item.command_id)):
        return False
    if report.fills != tuple(sorted(report.fills, key=lambda item: item.event_id)):
        return False
    if report.positions != tuple(
        sorted(report.positions, key=lambda item: (item.market, item.symbol))
    ):
        return False
    if report.cash != tuple(sorted(report.cash, key=lambda item: item.currency)):
        return False
    if report.risk_events != tuple(
        sorted(
            report.risk_events,
            key=lambda item: (item.plan_id, item.rule, item.code, item.subject_identity),
        )
    ):
        return False
    if any(
        type(item) is not ExecutionOrderLine
        or not _hex64(item.command_id)
        or not _safe_symbol(item.symbol)
        or item.market not in {value.value for value in Market}
        or item.side not in {value.value for value in OrderSide}
        or not _non_negative_int(item.requested_quantity)
        or item.requested_quantity == 0
        or not _non_negative_int(item.filled_quantity)
        or item.filled_quantity > item.requested_quantity
        or item.status not in {value.value for value in OrderStatus}
        or (item.broker_order_identity is not None and not _hex64(item.broker_order_identity))
        for item in report.orders
    ):
        return False
    if any(
        type(item) is not ExecutionFillLine
        or not _hex64(item.event_id)
        or not _hex64(item.command_id)
        or item.event_type not in {value.value for value in _FILL_TYPES}
        or not _non_negative_int(item.cumulative_quantity)
        or not _non_negative_int(item.last_quantity)
        or item.last_quantity == 0
        or item.last_price is None
        or not _decimal_text(item.last_price)
        or type(item.fees) is not tuple
        or any(
            type(fee) is not tuple
            or len(fee) != 2
            or fee[0] not in {value.value for value in Currency}
            or not _decimal_text(fee[1])
            for fee in item.fees
        )
        for item in report.fills
    ):
        return False
    if any(
        type(item) is not ExecutionPositionLine
        or not _safe_symbol(item.symbol)
        or item.market not in {value.value for value in Market}
        or not _non_negative_int(item.quantity)
        or not _non_negative_int(item.sellable_quantity)
        or item.sellable_quantity > item.quantity
        or item.avg_cost_currency not in {value.value for value in Currency}
        or not _decimal_text(item.avg_cost)
        for item in report.positions
    ):
        return False
    if any(
        type(item) is not ExecutionCashLine
        or item.currency not in {value.value for value in Currency}
        or any(
            not _decimal_text(value)
            for value in (item.settled, item.available, item.receivable, item.payable)
        )
        for item in report.cash
    ):
        return False
    if any(
        type(item) is not ExecutionRiskLine
        or not _hex64(item.plan_id)
        or not _safe_code(item.rule)
        or type(item.accepted) is not bool
        or not _safe_code(item.code)
        or not _hex64(item.subject_identity)
        for item in report.risk_events
    ):
        return False
    if any(
        type(item) is not ExecutionDifferenceLine
        or not _safe_code(item.code)
        or item.action not in actions
        or not _hex64(item.subject_identity)
        or (item.local_identity is not None and not _hex64(item.local_identity))
        or (item.broker_identity is not None and not _hex64(item.broker_identity))
        for item in report.differences
    ):
        return False
    expected = ExecutionReportTotals(
        commands=len(report.orders),
        orders=len(report.orders),
        fills=len(report.fills),
        positions=len(report.positions),
        cash_balances=len(report.cash),
        risk_events=len(report.risk_events),
        differences=len(report.differences),
    )
    return report.totals == expected and report.gate_passed == (not report.differences)


def _decimal_text(value: object) -> bool:
    if type(value) is not str:
        return False
    valid = False
    try:
        parsed = Decimal(value)
        valid = parsed.is_finite() and value == str(parsed)
    except Exception:
        pass
    return valid


def _non_negative_int(value: object) -> bool:
    return type(value) is int and value >= 0


def _safe_code(value: object) -> bool:
    return type(value) is str and _CODE.fullmatch(value) is not None


def _safe_symbol(value: object) -> bool:
    return type(value) is str and _SYMBOL.fullmatch(value) is not None


def _line(value: object) -> dict[str, object]:
    names = value.__dataclass_fields__  # type: ignore[attr-defined]
    return {name: getattr(value, name) for name in names}


def _report_identity(report: ExecutionReport) -> str:
    return hashlib.sha256(_canonical({"schema_version": _SCHEMA, **_payload(report)})).hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _text_identity(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _optional_text_identity(value: str | None) -> str | None:
    return None if value is None else _text_identity(value)


def _hex64(value: object) -> bool:
    return type(value) is str and len(value) == 64 and set(value).issubset(_HEX)


def _utc(value: object) -> bool:
    return (
        type(value) is dt.datetime
        and value.tzinfo is not None
        and value.utcoffset() == dt.timedelta(0)
    )


__all__ = [
    "ExecutionCashLine",
    "ExecutionDifferenceLine",
    "ExecutionFillLine",
    "ExecutionOrderLine",
    "ExecutionPositionLine",
    "ExecutionReport",
    "ExecutionReportError",
    "ExecutionReportTotals",
    "ExecutionRiskLine",
    "build_execution_report",
    "encode_execution_report",
]
