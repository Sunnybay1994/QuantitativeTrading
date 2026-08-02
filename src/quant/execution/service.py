"""M4-P4 execution orchestration over the durable store and gateway protocol.

The service is deliberately synchronous.  Durable outbox leases provide the
restart and multi-worker boundary; scheduling/background execution belongs to
the caller.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Protocol

from quant.domain.enums import ExecutionMode
from quant.execution.contracts import (
    AccountSnapshot,
    OrderCommand,
    OrderPlan,
    VerifiedMarketSnapshot,
)
from quant.execution.gateways.contracts import (
    DispatchCertainty,
    GatewayTransport,
    validate_gateway_submit,
    verify_gateway_dispatch_result,
)
from quant.execution.oms import OrderAggregate, new_order_aggregate, reduce_order
from quant.execution.risk import (
    DailyRiskCounters,
    RiskDecision,
    RiskRuleResult,
    evaluate_pretrade,
)
from quant.execution.store import (
    ExecutionRepository,
    ExecutionStore,
    OutboxDelivery,
    OutboxDeliveryState,
    StoredRecord,
)
from quant.execution.wire import (
    WireError,
    decode_order_aggregate,
    decode_order_command,
    encode_execution_event,
    encode_order_aggregate,
    encode_order_command,
)
from quant.portfolio.order_planner import (
    OrderPlannerConfig,
    OrderPlanTarget,
    build_order_plan,
)

_SCOPE = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")
_HEX64 = frozenset("0123456789abcdef")
_STAGE_SCHEMA = "m4-execution-stage-v1"
_COUNTER_SCHEMA = "m4-daily-risk-counters-v1"

__all__ = [
    "DispatchItemResult",
    "DispatchResult",
    "ExecutionService",
    "ExecutionServiceError",
    "ServiceClock",
    "StagedExecution",
]


class ExecutionServiceError(ValueError):
    """Stable, path-free service error."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class ServiceClock(Protocol):
    """Injected UTC clock."""

    def now(self) -> dt.datetime:
        """Return the current timezone-aware UTC instant."""
        ...


@dataclass(frozen=True, slots=True)
class StagedExecution:
    """One durable plan/risk/outbox staging result."""

    plan: OrderPlan
    risk: RiskDecision
    staged_command_ids: tuple[str, ...]
    replayed: bool


@dataclass(frozen=True, slots=True)
class DispatchItemResult:
    """Sanitized observation for one claimed delivery."""

    outbox_key: str
    command_id: str
    dispatch_attempt: int
    certainty: DispatchCertainty | None
    callback_event_ids: tuple[str, ...]
    code: str


@dataclass(frozen=True, slots=True)
class DispatchResult:
    """One bounded dispatch pass."""

    claimed_count: int
    items: tuple[DispatchItemResult, ...]


class ExecutionService:
    """Compose planner, risk, durable outbox and a narrow gateway transport."""

    def __init__(
        self,
        *,
        store: ExecutionStore,
        gateway: GatewayTransport,
        clock: ServiceClock,
        worker_id: str,
        lease_duration: dt.timedelta,
        risk_counter_scope: str,
    ) -> None:
        if not isinstance(store, ExecutionStore):
            raise ExecutionServiceError("SERVICE_STORE_INVALID")
        if not isinstance(gateway, GatewayTransport):
            raise ExecutionServiceError("SERVICE_GATEWAY_INVALID")
        if not callable(getattr(clock, "now", None)):
            raise ExecutionServiceError("SERVICE_CLOCK_INVALID")
        if type(worker_id) is not str or _SCOPE.fullmatch(worker_id) is None:
            raise ExecutionServiceError("SERVICE_WORKER_ID_INVALID")
        if (
            type(lease_duration) is not dt.timedelta
            or lease_duration <= dt.timedelta(0)
        ):
            raise ExecutionServiceError("SERVICE_LEASE_INVALID")
        if type(risk_counter_scope) is not str or _SCOPE.fullmatch(risk_counter_scope) is None:
            raise ExecutionServiceError("SERVICE_COUNTER_SCOPE_INVALID")
        self._store = store
        self._gateway = gateway
        self._clock = clock
        self._worker_id = worker_id
        self._lease_duration = lease_duration
        self._risk_counter_scope = risk_counter_scope

    def plan_and_stage(
        self,
        *,
        targets: Sequence[OrderPlanTarget],
        target_identity: str,
        market: VerifiedMarketSnapshot,
        account: AccountSnapshot,
        planner_config: OrderPlannerConfig,
    ) -> StagedExecution:
        """Plan, risk-check and atomically stage commands exactly once per plan."""
        now = self._now()
        try:
            plan = build_order_plan(
                targets=targets,
                target_identity=target_identity,
                market=market,
                account=account,
                config=planner_config,
            )
        except Exception:
            raise ExecutionServiceError("SERVICE_PLANNING_FAILED") from None

        with self._store.transaction() as repo:
            existing = repo.get_execution_stage(plan.plan_id)
            if existing is not None:
                risk = _decode_stage(existing, plan, market.session_date, repo)
                return _staged(plan, risk, replayed=True)

            counter_key = f"{self._risk_counter_scope}:{market.session_date.isoformat()}"
            counter_row = repo.get_daily_risk_counters(counter_key)
            if counter_row is None:
                counters = DailyRiskCounters(
                    session_date=market.session_date,
                    order_count=0,
                    cancel_count=0,
                    buy_notional=Decimal(0),
                )
            else:
                counters = _decode_counter(counter_row, market.session_date)

            try:
                risk = evaluate_pretrade(
                    plan,
                    account,
                    market,
                    planner_config.trading_config,
                    counters,
                    now=now,
                )
            except Exception:
                raise ExecutionServiceError("SERVICE_RISK_FAILED") from None

            counter_payload = _encode_counter(risk.projected_counters)
            counter_identity = _digest(counter_payload)
            try:
                if counter_row is None:
                    repo.put_daily_risk_counters(
                        counter_key=counter_key,
                        identity=counter_identity,
                        payload=counter_payload,
                    )
                else:
                    repo.compare_and_set_daily_risk_counters(
                        counter_key=counter_key,
                        expected_identity=counter_row.identity,
                        identity=counter_identity,
                        payload=counter_payload,
                    )

                for command in risk.commands:
                    command_payload = encode_order_command(command)
                    aggregate = new_order_aggregate(command)
                    aggregate_payload = encode_order_aggregate(aggregate)
                    repo.put_command(
                        command_id=command.command_id,
                        identity=command.command_id,
                        payload=command_payload,
                    )
                    repo.put_order_aggregate(
                        command_id=command.command_id,
                        identity=_digest(aggregate_payload),
                        payload=aggregate_payload,
                    )
                    repo.put_outbox(
                        outbox_key=command.command_id,
                        identity=command.command_id,
                        payload=command_payload,
                    )
                    repo.put_outbox_delivery(
                        outbox_key=command.command_id,
                        command_id=command.command_id,
                        available_at=now,
                    )

                stage_payload = _encode_stage(risk)
                repo.put_execution_stage(
                    plan_id=plan.plan_id,
                    identity=_digest(stage_payload),
                    payload=stage_payload,
                )
            except ExecutionServiceError:
                raise
            except Exception:
                raise ExecutionServiceError("SERVICE_STAGE_WRITE_FAILED") from None
        return _staged(plan, risk, replayed=False)

    def dispatch_pending(self, *, limit: int) -> DispatchResult:
        """Claim and synchronously dispatch at most ``limit`` ready commands."""
        if type(limit) is not int or limit <= 0:
            raise ExecutionServiceError("SERVICE_DISPATCH_LIMIT_INVALID")
        claimed_at = self._now()
        lease_until = claimed_at + self._lease_duration
        try:
            with self._store.transaction() as repo:
                claimed = repo.claim_outbox_deliveries(
                    worker_id=self._worker_id,
                    now=claimed_at,
                    lease_until=lease_until,
                    limit=limit,
                )
        except Exception:
            raise ExecutionServiceError("SERVICE_CLAIM_FAILED") from None

        items: list[DispatchItemResult] = []
        for delivery in claimed:
            if self._now() >= lease_until:
                items.append(_dispatch_item(delivery, None, (), "LEASE_EXPIRED"))
                continue
            try:
                with self._store.transaction() as repo:
                    current = repo.get_outbox_delivery(delivery.outbox_key)
                    if not _same_lease(current, delivery, self._worker_id):
                        items.append(
                            _dispatch_item(delivery, None, (), "LEASE_LOST_BEFORE_DISPATCH")
                        )
                        continue
                    assert current is not None
                    command, _ = _load_command_and_aggregate(repo, current)
            except Exception:
                raise ExecutionServiceError("SERVICE_DURABLE_COMMAND_INVALID") from None

            # Re-read the clock after durable closure validation.  This is the
            # final enforceable fence before crossing the adapter boundary.
            dispatch_at = self._now()
            if current.lease_until is None or dispatch_at >= current.lease_until:
                items.append(
                    _dispatch_item(delivery, None, (), "LEASE_EXPIRED_BEFORE_DISPATCH")
                )
                continue
            try:
                validate_gateway_submit(command, delivery.attempt_count, dispatch_at)
            except Exception:
                raise ExecutionServiceError("SERVICE_DURABLE_COMMAND_INVALID") from None

            try:
                raw_result = self._gateway.submit(
                    command=command,
                    dispatch_attempt=delivery.attempt_count,
                    now=dispatch_at,
                )
            except Exception:
                items.append(self._mark_unknown(delivery, "GATEWAY_EXCEPTION"))
                continue

            observed_at = self._now()
            try:
                result = verify_gateway_dispatch_result(
                    command,
                    delivery.attempt_count,
                    observed_at,
                    raw_result,
                )
            except Exception:
                items.append(self._mark_unknown(delivery, "GATEWAY_RESULT_INVALID"))
                continue

            if observed_at >= lease_until:
                items.append(
                    _dispatch_item(
                        delivery,
                        result.certainty,
                        tuple(item.event_id for item in result.callbacks),
                        "LEASE_EXPIRED_AFTER_DISPATCH",
                    )
                )
                continue
            if result.certainty is DispatchCertainty.NOT_SENT:
                items.append(_dispatch_item(delivery, result.certainty, (), "NOT_SENT"))
                continue
            if result.certainty is DispatchCertainty.UNKNOWN:
                items.append(self._mark_unknown(delivery, "GATEWAY_UNKNOWN"))
                continue

            callback_ids = tuple(item.event_id for item in result.callbacks)
            try:
                with self._store.transaction() as repo:
                    current = repo.get_outbox_delivery(delivery.outbox_key)
                    if current is None:
                        raise ExecutionServiceError("SERVICE_DELIVERY_MISSING")
                    current_command, aggregate_row = _load_command_and_aggregate(repo, current)
                    aggregate = _decode_aggregate(aggregate_row, current_command)
                    updated = aggregate
                    for event in result.callbacks:
                        event_payload = encode_execution_event(event)
                        repo.put_event(
                            event_id=event.event_id,
                            command_id=event.command_id,
                            identity=event.event_id,
                            payload=event_payload,
                        )
                        updated = reduce_order(updated, current_command, event)
                    if updated != aggregate:
                        payload = encode_order_aggregate(updated)
                        repo.replace_order_aggregate(
                            command_id=current_command.command_id,
                            expected_identity=aggregate_row.identity,
                            identity=_digest(payload),
                            payload=payload,
                        )
                    repo.mark_outbox_sent(
                        outbox_key=delivery.outbox_key,
                        lease_owner=self._worker_id,
                        expected_attempt=delivery.attempt_count,
                        sent_at=observed_at,
                    )
            except Exception:
                items.append(
                    _dispatch_item(
                        delivery,
                        DispatchCertainty.SENT,
                        callback_ids,
                        "CALLBACK_TRANSACTION_FAILED",
                    )
                )
                continue
            items.append(
                _dispatch_item(delivery, DispatchCertainty.SENT, callback_ids, "SENT")
            )
        return DispatchResult(claimed_count=len(claimed), items=tuple(items))

    def _mark_unknown(self, delivery: object, error_code: str) -> DispatchItemResult:
        from quant.execution.store import OutboxDelivery

        if not isinstance(delivery, OutboxDelivery):
            raise ExecutionServiceError("SERVICE_DELIVERY_INVALID")
        at = self._now()
        if delivery.lease_until is None or at >= delivery.lease_until:
            return _dispatch_item(
                delivery, DispatchCertainty.UNKNOWN, (), "UNKNOWN_NOT_DURABLE"
            )
        try:
            with self._store.transaction() as repo:
                repo.mark_outbox_unknown(
                    outbox_key=delivery.outbox_key,
                    lease_owner=self._worker_id,
                    expected_attempt=delivery.attempt_count,
                    unknown_at=at,
                    error_code=error_code,
                )
        except Exception:
            return _dispatch_item(
                delivery, DispatchCertainty.UNKNOWN, (), "UNKNOWN_NOT_DURABLE"
            )
        return _dispatch_item(delivery, DispatchCertainty.UNKNOWN, (), "UNKNOWN")

    def _now(self) -> dt.datetime:
        value: object = None
        try:
            value = self._clock.now()
            if type(value) is not dt.datetime:
                raise TypeError
            assert isinstance(value, dt.datetime)
            if value.tzinfo is None or value.utcoffset() != dt.timedelta(0):
                raise ValueError
        except Exception:
            raise ExecutionServiceError("SERVICE_CLOCK_INVALID") from None
        return value


def _same_lease(
    current: OutboxDelivery | None,
    claimed: OutboxDelivery,
    worker_id: str,
) -> bool:
    """Return whether the claimed attempt is still owned by this worker."""
    return (
        current is not None
        and current.state is OutboxDeliveryState.LEASED
        and current.lease_owner == worker_id
        and current.attempt_count == claimed.attempt_count
        and current.lease_until == claimed.lease_until
    )


def _staged(plan: OrderPlan, risk: RiskDecision, *, replayed: bool) -> StagedExecution:
    return StagedExecution(
        plan=plan,
        risk=risk,
        staged_command_ids=tuple(item.command_id for item in risk.commands),
        replayed=replayed,
    )


def _dispatch_item(
    delivery: object,
    certainty: DispatchCertainty | None,
    callbacks: tuple[str, ...],
    code: str,
) -> DispatchItemResult:
    from quant.execution.store import OutboxDelivery

    assert isinstance(delivery, OutboxDelivery)
    return DispatchItemResult(
        outbox_key=delivery.outbox_key,
        command_id=delivery.command_id,
        dispatch_attempt=delivery.attempt_count,
        certainty=certainty,
        callback_event_ids=callbacks,
        code=code,
    )


def _load_command_and_aggregate(
    repo: ExecutionRepository, delivery: object
) -> tuple[OrderCommand, StoredRecord]:
    from quant.execution.store import OutboxDelivery

    if not isinstance(delivery, OutboxDelivery):
        raise ExecutionServiceError("SERVICE_DELIVERY_INVALID")
    if (
        delivery.outbox_key != delivery.command_id
        or delivery.identity != delivery.command_id
    ):
        raise ExecutionServiceError("SERVICE_DELIVERY_CLOSURE_INVALID")
    command = _decode_command(delivery.payload)
    if command.command_id != delivery.command_id:
        raise ExecutionServiceError("SERVICE_DELIVERY_CLOSURE_INVALID")
    row = repo.get_command(delivery.command_id)
    aggregate = repo.get_order_aggregate(delivery.command_id)
    if (
        row is None
        or aggregate is None
        or row.key != delivery.command_id
        or row.identity != delivery.command_id
        or row.payload != delivery.payload
    ):
        raise ExecutionServiceError("SERVICE_DELIVERY_CLOSURE_INVALID")
    _decode_aggregate(aggregate, command)
    return command, aggregate


def _canonical(payload: Mapping[str, object]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _parse(payload: bytes) -> dict[str, object]:
    if type(payload) is not bytes:
        raise ExecutionServiceError("SERVICE_PAYLOAD_INVALID")
    value: object = None
    try:
        value = json.loads(payload.decode("utf-8"))
    except Exception:
        pass
    if type(value) is not dict or _canonical(value) != payload:
        raise ExecutionServiceError("SERVICE_PAYLOAD_INVALID")
    return value


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _exact_keys(value: object, keys: set[str]) -> dict[str, object]:
    if type(value) is not dict or set(value) != keys:
        raise ExecutionServiceError("SERVICE_PAYLOAD_INVALID")
    return value


def _str(value: object) -> str:
    if type(value) is not str or not value:
        raise ExecutionServiceError("SERVICE_PAYLOAD_INVALID")
    return value


def _bool(value: object) -> bool:
    if type(value) is not bool:
        raise ExecutionServiceError("SERVICE_PAYLOAD_INVALID")
    return value


def _int(value: object, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ExecutionServiceError("SERVICE_PAYLOAD_INVALID")
    return value


def _decimal(value: object, *, optional: bool = False) -> Decimal | None:
    if value is None and optional:
        return None
    if type(value) is not str:
        raise ExecutionServiceError("SERVICE_PAYLOAD_INVALID")
    parsed: Decimal | None = None
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        pass
    if parsed is None or not parsed.is_finite() or format(parsed, "f") != value:
        raise ExecutionServiceError("SERVICE_PAYLOAD_INVALID")
    return parsed


def _date(value: object) -> dt.date:
    parsed: dt.date | None = None
    try:
        if type(value) is str:
            parsed = dt.date.fromisoformat(value)
    except ValueError:
        pass
    if parsed is None or parsed.isoformat() != value:
        raise ExecutionServiceError("SERVICE_PAYLOAD_INVALID")
    return parsed


def _datetime(value: object) -> dt.datetime:
    parsed: dt.datetime | None = None
    try:
        if type(value) is str and value.endswith("Z"):
            parsed = dt.datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        pass
    if parsed is None or _datetime_text(parsed) != value:
        raise ExecutionServiceError("SERVICE_PAYLOAD_INVALID")
    return parsed


def _datetime_text(value: dt.datetime) -> str:
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _enum(cls: type[object], value: object) -> object:
    if type(value) is not str:
        raise ExecutionServiceError("SERVICE_PAYLOAD_INVALID")
    try:
        return cls(value)  # type: ignore[call-arg]
    except (TypeError, ValueError):
        raise ExecutionServiceError("SERVICE_PAYLOAD_INVALID") from None


def _decode_command(payload: bytes) -> OrderCommand:
    try:
        return decode_order_command(payload)
    except WireError:
        raise ExecutionServiceError("SERVICE_PAYLOAD_INVALID") from None


def _encode_counter(counter: DailyRiskCounters) -> bytes:
    return _canonical(
        {"counter": counter.to_persistable_dict(), "schema_version": _COUNTER_SCHEMA}
    )


def _decode_counter(record: StoredRecord, session_date: dt.date) -> DailyRiskCounters:
    root = _exact_keys(_parse(record.payload), {"schema_version", "counter"})
    raw = _exact_keys(
        root["counter"], {"session_date", "order_count", "cancel_count", "buy_notional"}
    )
    if root["schema_version"] != _COUNTER_SCHEMA or record.identity != _digest(record.payload):
        raise ExecutionServiceError("SERVICE_COUNTER_INVALID")
    try:
        counter = DailyRiskCounters(
            session_date=_date(raw["session_date"]),
            order_count=_int(raw["order_count"]),
            cancel_count=_int(raw["cancel_count"]),
            buy_notional=_decimal(raw["buy_notional"]),  # type: ignore[arg-type]
        )
    except Exception:
        raise ExecutionServiceError("SERVICE_COUNTER_INVALID") from None
    if counter.session_date != session_date or _encode_counter(counter) != record.payload:
        raise ExecutionServiceError("SERVICE_COUNTER_INVALID")
    return counter


def _encode_stage(risk: RiskDecision) -> bytes:
    return _canonical(
        {
            "accepted": risk.accepted,
            "approved_intent_ids": list(risk.approved_intent_ids),
            "command_ids": [item.command_id for item in risk.commands],
            "plan_id": risk.plan_id,
            "projected_counters": risk.projected_counters.to_persistable_dict(),
            "requires_manual_approval": risk.requires_manual_approval,
            "rule_results": [
                {
                    "accepted": item.accepted,
                    "code": item.code,
                    "detail": item.detail,
                    "rule": item.rule,
                    "subject": item.subject,
                }
                for item in risk.rule_results
            ],
            "schema_version": _STAGE_SCHEMA,
        }
    )


def _decode_stage(
    record: StoredRecord,
    plan: OrderPlan,
    session_date: dt.date,
    repo: ExecutionRepository,
) -> RiskDecision:
    root = _exact_keys(
        _parse(record.payload),
        {
            "schema_version", "accepted", "approved_intent_ids", "command_ids",
            "plan_id", "projected_counters", "requires_manual_approval", "rule_results",
        },
    )
    if (
        root["schema_version"] != _STAGE_SCHEMA
        or root["plan_id"] != plan.plan_id
        or record.key != plan.plan_id
        or record.identity != _digest(record.payload)
    ):
        raise ExecutionServiceError("SERVICE_STAGE_INVALID")
    if type(root["approved_intent_ids"]) is not list or type(root["command_ids"]) is not list:
        raise ExecutionServiceError("SERVICE_STAGE_INVALID")
    approved = tuple(_str(item) for item in root["approved_intent_ids"])
    command_ids = tuple(_str(item) for item in root["command_ids"])
    intents = {item.intent_id: item for item in plan.intents}
    intent_ids = set(intents)
    if len(set(approved)) != len(approved) or not set(approved) <= intent_ids:
        raise ExecutionServiceError("SERVICE_STAGE_INVALID")
    commands: list[OrderCommand] = []
    for command_id in command_ids:
        row = repo.get_command(command_id)
        if row is None or row.key != command_id or row.identity != command_id:
            raise ExecutionServiceError("SERVICE_STAGE_INVALID")
        command = _decode_command(row.payload)
        if (
            command.intent.intent_id not in approved
            or command.intent.plan_id != plan.plan_id
            or command.intent != intents[command.intent.intent_id]
            or command.mode is not ExecutionMode.PAPER
        ):
            raise ExecutionServiceError("SERVICE_STAGE_INVALID")
        commands.append(command)
    if (
        len({item.command_id for item in commands}) != len(commands)
        or commands
        and tuple(item.intent.intent_id for item in commands) != approved
    ):
        raise ExecutionServiceError("SERVICE_STAGE_INVALID")
    raw_counters = _exact_keys(
        root["projected_counters"],
        {"session_date", "order_count", "cancel_count", "buy_notional"},
    )
    counters = DailyRiskCounters(
        session_date=_date(raw_counters["session_date"]),
        order_count=_int(raw_counters["order_count"]),
        cancel_count=_int(raw_counters["cancel_count"]),
        buy_notional=_decimal(raw_counters["buy_notional"]),  # type: ignore[arg-type]
    )
    raw_rules = root["rule_results"]
    if type(raw_rules) is not list:
        raise ExecutionServiceError("SERVICE_STAGE_INVALID")
    rules: list[RiskRuleResult] = []
    for item in raw_rules:
        raw = _exact_keys(item, {"rule", "accepted", "code", "subject", "detail"})
        rules.append(
            RiskRuleResult(
                rule=_str(raw["rule"]),
                accepted=_bool(raw["accepted"]),
                code=_str(raw["code"]),
                subject=_str(raw["subject"]),
                detail=_str(raw["detail"]),
            )
        )
    risk = RiskDecision(
        accepted=_bool(root["accepted"]),
        plan_id=plan.plan_id,
        rule_results=tuple(rules),
        approved_intent_ids=approved,
        commands=tuple(commands),
        projected_counters=counters,
        requires_manual_approval=_bool(root["requires_manual_approval"]),
    )
    if (
        counters.session_date != session_date
        or bool(commands) and risk.requires_manual_approval
        or plan.intents and risk.accepted != bool(approved)
        or _encode_stage(risk) != record.payload
    ):
        raise ExecutionServiceError("SERVICE_STAGE_INVALID")
    return risk


def _decode_aggregate(record: StoredRecord, command: OrderCommand) -> OrderAggregate:
    if record.identity != _digest(record.payload):
        raise ExecutionServiceError("SERVICE_AGGREGATE_INVALID")
    try:
        return decode_order_aggregate(record.payload, command=command)
    except WireError:
        raise ExecutionServiceError("SERVICE_AGGREGATE_INVALID") from None
