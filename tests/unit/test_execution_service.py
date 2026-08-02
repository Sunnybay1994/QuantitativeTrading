"""M4-P4 execution service atomicity, recovery and hostile-boundary tests."""

from __future__ import annotations

import datetime as dt
import hashlib
import sqlite3
from decimal import Decimal
from pathlib import Path

import pytest

from quant.backtest.a_share_execution import build_a_share_rule_config
from quant.backtest.connect_execution import build_connect_rule_config
from quant.backtest.costs import ExecutionCostPeriod, build_execution_cost_schedule
from quant.backtest.fx import FxRate, build_fx_snapshot
from quant.domain.enums import (
    ConnectRoute,
    Currency,
    ExecutionEventType,
    Market,
)
from quant.execution.config import load_trading_config
from quant.execution.contracts import (
    build_account_snapshot,
    build_cash_balance,
    build_execution_event,
    build_money_amount,
    build_symbol_market_state,
    build_verified_market_snapshot,
    ExecutionEvent,
)
from quant.execution.gateways.contracts import (
    DispatchCertainty,
    GatewayDispatchResult,
)
from quant.execution.service import ExecutionService, ExecutionServiceError
from quant.execution.store import (
    ExecutionRepository,
    ExecutionStore,
    OutboxDeliveryState,
)
from quant.portfolio.order_planner import (
    OrderPlanTarget,
    build_order_planner_config,
)

UTC = dt.timezone.utc
DAY = dt.date(2026, 7, 20)
NOW = dt.datetime(2026, 7, 19, 8, tzinfo=UTC)


def _hex(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


class MutableClock:
    def __init__(self, value: dt.datetime = NOW) -> None:
        self.value = value

    def now(self) -> dt.datetime:
        return self.value


class FakeGateway:
    def __init__(self, certainty: DispatchCertainty = DispatchCertainty.SENT) -> None:
        self.certainty = certainty
        self.calls: list[tuple[str, int]] = []
        self.raise_secret = False
        self.malformed = False
        self.partial_then_fill = False
        self.duplicate_callback = False
        self.illegal_callback_sequence = False

    def submit(self, *, command, dispatch_attempt: int, now: dt.datetime):
        self.calls.append((command.command_id, dispatch_attempt))
        if self.raise_secret:
            raise RuntimeError("secret adapter context")
        if self.malformed:
            return object()
        callbacks: tuple[ExecutionEvent, ...] = ()
        if self.certainty is DispatchCertainty.SENT:
            accepted = build_execution_event(
                command=command,
                broker_order_id="PAPER-1",
                event_type=ExecutionEventType.ACCEPTED,
                occurred_at=now,
                cumulative_quantity=0,
                last_quantity=0,
                last_price=None,
                fees=(),
                reject_code=None,
            )
            callbacks = (accepted,)
            if self.partial_then_fill:
                half = command.intent.quantity // 2
                partial = build_execution_event(
                    command=command,
                    broker_order_id="PAPER-1",
                    event_type=ExecutionEventType.PARTIAL_FILL,
                    occurred_at=now,
                    cumulative_quantity=half,
                    last_quantity=half,
                    last_price=command.intent.limit_price,
                    fees=(),
                    reject_code=None,
                )
                fill = build_execution_event(
                    command=command,
                    broker_order_id="PAPER-1",
                    event_type=ExecutionEventType.FILL,
                    occurred_at=now,
                    cumulative_quantity=command.intent.quantity,
                    last_quantity=command.intent.quantity - half,
                    last_price=command.intent.limit_price,
                    fees=(),
                    reject_code=None,
                )
                callbacks = (accepted, partial, fill)
            if self.duplicate_callback:
                callbacks = callbacks + (callbacks[-1],)
            if self.illegal_callback_sequence:
                second = build_execution_event(
                    command=command,
                    broker_order_id="PAPER-2",
                    event_type=ExecutionEventType.ACCEPTED,
                    occurred_at=now,
                    cumulative_quantity=0,
                    last_quantity=0,
                    last_price=None,
                    fees=(),
                    reject_code=None,
                )
                callbacks = (accepted, second)
        return GatewayDispatchResult(
            command_id=command.command_id,
            dispatch_attempt=dispatch_attempt,
            certainty=self.certainty,
            callbacks=callbacks,
        )


def _trading_config(tmp_path: Path, *, frozen: str = "[]", manual: bool = False):
    path = tmp_path / "trading.toml"
    path.write_text(
        f"""
[meta]
schema_version = "trading-config-v1"
[execution]
mode = "PAPER"
auto_trade = false
manual_approval = {str(manual).lower()}
sell_only = false
frozen_symbols = {frozen}
[rules]
a_share_rule_selector = "a_share_execution_rules_v1"
hk_connect_rule_selector = "hk_connect_execution_rules_v1"
fee_schedule_selector = "a_share_research_cost_schedule_v1"
fx_schedule_selector = "cny_hkd_fx_schedule_v1"
[data]
snapshot_max_age_seconds = 86400
[store]
sqlite_uri = "sqlite:///artifacts/trading/execution.db"
[[risk.limits]]
effective_from = 2016-01-01
max_order_notional = 1000000.0
max_symbol_weight = 1.0
max_gross_exposure = 2.0
max_daily_notional = 5000000.0
max_orders_per_day = 50
max_cancels_per_day = 20
""",
        encoding="utf-8",
    )
    return load_trading_config(path)


def _planner_config(tmp_path: Path, *, frozen: str = "[]", manual: bool = False):
    trading = _trading_config(tmp_path, frozen=frozen, manual=manual)
    schedule = build_execution_cost_schedule(
        selector="a_share_research_cost_schedule_v1",
        periods=tuple(
            ExecutionCostPeriod(
                market=market,
                effective_from=dt.date(2026, 1, 1),
                effective_to=dt.date(2026, 12, 31),
                commission_rate=Decimal("0.0003"),
                commission_min=Decimal("5"),
                stamp_tax_sell=Decimal("0.0005"),
                transfer_fee=Decimal("0.00001"),
                settlement_currency=Currency.CNY,
            )
            for market in (Market.HK, Market.SH, Market.SZ)
        ),
    )
    return build_order_planner_config(
        trading_config=trading,
        a_share_rule_config=build_a_share_rule_config(
            selector="a_share_execution_rules_v1",
            effective_from=dt.date(2020, 8, 24),
            effective_to=None,
        ),
        connect_rule_configs=tuple(
            build_connect_rule_config(
                selector="hk_connect_execution_rules_v1",
                route=route,
                effective_from=dt.date(2026, 1, 1),
                effective_to=dt.date(2026, 12, 31),
            )
            for route in (ConnectRoute.SH_CONNECT, ConnectRoute.SZ_CONNECT)
        ),
        execution_cost_schedule=schedule,
        fx_snapshot=build_fx_snapshot(
            selector="cny_hkd_fx_schedule_v1",
            session_date=DAY,
            observed_at=NOW - dt.timedelta(hours=1),
            expires_at=NOW + dt.timedelta(hours=1),
            rates=(FxRate(Currency.HKD, Currency.CNY, Decimal("0.9")),),
        ),
        minimum_order_notionals=(build_money_amount(Currency.CNY, Decimal("1")),),
    )


def _state(symbol: str):
    market = Market.SH if symbol.endswith(".SH") else Market.SZ
    return build_symbol_market_state(
        symbol=symbol,
        market=market,
        session_date=DAY,
        quote_currency=Currency.CNY,
        reference_price=Decimal("10"),
        limit_up=Decimal("11"),
        limit_down=Decimal("9"),
        suspended=False,
        board_lot=100,
        tick_size=Decimal("0.01"),
        rule_version="a_share_execution_rules_v1",
    )


def _inputs(symbols: tuple[str, ...] = ("600000.SH",), *, cash: str = "2000"):
    states = tuple(_state(symbol) for symbol in symbols)
    market = build_verified_market_snapshot(
        as_of=NOW,
        session_date=DAY,
        states=states,
        connect_contexts=(),
        calendar_identity=_hex("calendar"),
        source_identity=_hex("source"),
    )
    balance = build_cash_balance(
        currency=Currency.CNY,
        settled=Decimal(cash),
        available=Decimal(cash),
        receivable=Decimal(0),
        payable=Decimal(0),
    )
    account = build_account_snapshot(as_of=NOW, positions=(), cash=(balance,))
    weight = Decimal(1) / len(symbols)
    targets = tuple(
        OrderPlanTarget(
            symbol=symbol,
            market=state.market,
            connect_route=None,
            target_weight=weight,
        )
        for symbol, state in zip(symbols, states, strict=True)
    )
    return targets, market, account


def _open(tmp_path: Path, name: str = "db") -> ExecutionStore:
    return ExecutionStore.open(f"sqlite:///{name}/execution.db", trusted_root=tmp_path)


def _service(store, gateway, clock, worker: str = "worker-1") -> ExecutionService:
    return ExecutionService(
        store=store,
        gateway=gateway,
        clock=clock,
        worker_id=worker,
        lease_duration=dt.timedelta(minutes=1),
        risk_counter_scope="paper-account",
    )


def _stage(service: ExecutionService, tmp_path: Path, *, config=None, symbols=("600000.SH",)):
    targets, market, account = _inputs(symbols, cash="4000" if len(symbols) > 1 else "2000")
    return service.plan_and_stage(
        targets=targets,
        target_identity=_hex("targets"),
        market=market,
        account=account,
        planner_config=config or _planner_config(tmp_path),
    )


def test_plan_stage_is_atomic_and_replay_does_not_double_count(tmp_path: Path) -> None:
    store = _open(tmp_path)
    gateway = FakeGateway()
    service = _service(store, gateway, MutableClock())
    first = _stage(service, tmp_path)
    second = _stage(service, tmp_path)

    assert first.replayed is False
    assert second.replayed is True
    assert second.risk == first.risk
    assert len(first.staged_command_ids) == 1
    with store.transaction() as repo:
        counter = repo.get_daily_risk_counters(f"paper-account:{DAY.isoformat()}")
        delivery = repo.get_outbox_delivery(first.staged_command_ids[0])
    assert counter is not None and b'"order_count":1' in counter.payload
    assert delivery is not None and delivery.state is OutboxDeliveryState.PENDING
    store.close()


def test_partial_approval_only_stages_approved_command(tmp_path: Path) -> None:
    store = _open(tmp_path)
    service = _service(store, FakeGateway(), MutableClock())
    config = _planner_config(tmp_path, frozen='["000001.SZ"]')
    result = _stage(service, tmp_path, config=config, symbols=("600000.SH", "000001.SZ"))
    assert len(result.plan.intents) == 2
    assert len(result.risk.approved_intent_ids) == 1
    assert len(result.staged_command_ids) == 1
    store.close()


def test_stage_write_failure_rolls_back_counter_command_and_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _open(tmp_path)
    service = _service(store, FakeGateway(), MutableClock())

    def fail_delivery(self, **kwargs):
        del self, kwargs
        raise RuntimeError("hostile write failure with TOKEN")

    monkeypatch.setattr(ExecutionRepository, "put_outbox_delivery", fail_delivery)
    with pytest.raises(ExecutionServiceError, match="^SERVICE_STAGE_WRITE_FAILED$"):
        _stage(service, tmp_path)
    database = tmp_path / "db" / "execution.db"
    with sqlite3.connect(database) as conn:
        counts = tuple(
            conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in (
                "daily_risk_counters",
                "commands",
                "order_aggregates",
                "outbox",
                "outbox_deliveries",
                "execution_stages",
            )
        )
    assert counts == (0, 0, 0, 0, 0, 0)
    store.close()


def test_restart_restores_stage_and_counter_from_canonical_bytes(tmp_path: Path) -> None:
    store = _open(tmp_path)
    first = _stage(_service(store, FakeGateway(), MutableClock()), tmp_path)
    store.close()
    reopened = _open(tmp_path)
    replay = _stage(_service(reopened, FakeGateway(), MutableClock()), tmp_path)
    assert replay.replayed and replay.risk == first.risk
    reopened.close()


def test_sent_callbacks_and_aggregate_commit_in_one_transaction(tmp_path: Path) -> None:
    store = _open(tmp_path)
    gateway = FakeGateway()
    gateway.partial_then_fill = True
    service = _service(store, gateway, MutableClock())
    staged = _stage(service, tmp_path)
    result = service.dispatch_pending(limit=1)
    assert result.items[0].code == "SENT"
    assert len(result.items[0].callback_event_ids) == 3
    with store.transaction() as repo:
        delivery = repo.get_outbox_delivery(staged.staged_command_ids[0])
        aggregate = repo.get_order_aggregate(staged.staged_command_ids[0])
    assert delivery is not None and delivery.state is OutboxDeliveryState.SENT
    assert aggregate is not None and b'"status":"FILLED"' in aggregate.payload
    store.close()


def test_exact_duplicate_callback_is_idempotent(tmp_path: Path) -> None:
    store = _open(tmp_path)
    gateway = FakeGateway()
    gateway.duplicate_callback = True
    service = _service(store, gateway, MutableClock())
    staged = _stage(service, tmp_path)
    result = service.dispatch_pending(limit=1)
    assert result.items[0].code == "SENT"
    assert len(result.items[0].callback_event_ids) == 2
    with store.transaction() as repo:
        aggregate = repo.get_order_aggregate(staged.staged_command_ids[0])
    assert aggregate is not None
    assert aggregate.payload.count(result.items[0].callback_event_ids[0].encode()) == 1
    store.close()


def test_callback_failure_rolls_back_events_aggregate_and_sent_mark(tmp_path: Path) -> None:
    store = _open(tmp_path)
    gateway = FakeGateway()
    gateway.illegal_callback_sequence = True
    service = _service(store, gateway, MutableClock())
    staged = _stage(service, tmp_path)
    result = service.dispatch_pending(limit=1)
    assert result.items[0].code == "CALLBACK_TRANSACTION_FAILED"
    with store.transaction() as repo:
        delivery = repo.get_outbox_delivery(staged.staged_command_ids[0])
        aggregate = repo.get_order_aggregate(staged.staged_command_ids[0])
        events = tuple(repo.get_event(event_id) for event_id in result.items[0].callback_event_ids)
    assert delivery is not None and delivery.state is OutboxDeliveryState.LEASED
    assert aggregate is not None and b'"status":"CREATED"' in aggregate.payload
    assert events == (None, None)
    store.close()


@pytest.mark.parametrize("certainty", [DispatchCertainty.NOT_SENT, DispatchCertainty.UNKNOWN])
def test_certainty_states_have_distinct_durable_results(
    tmp_path: Path, certainty: DispatchCertainty
) -> None:
    store = _open(tmp_path)
    service = _service(store, FakeGateway(certainty), MutableClock())
    staged = _stage(service, tmp_path)
    result = service.dispatch_pending(limit=1)
    with store.transaction() as repo:
        delivery = repo.get_outbox_delivery(staged.staged_command_ids[0])
    assert delivery is not None
    if certainty is DispatchCertainty.NOT_SENT:
        assert result.items[0].code == "NOT_SENT"
        assert delivery.state is OutboxDeliveryState.LEASED
    else:
        assert result.items[0].code == "UNKNOWN"
        assert delivery.state is OutboxDeliveryState.UNKNOWN
    store.close()


def test_adapter_exception_and_malformed_result_are_sanitized_unknown(
    tmp_path: Path,
) -> None:
    for name, malformed in (("exception", False), ("malformed", True)):
        store = _open(tmp_path, name)
        gateway = FakeGateway()
        gateway.raise_secret = not malformed
        gateway.malformed = malformed
        service = _service(store, gateway, MutableClock())
        staged = _stage(service, tmp_path)
        result = service.dispatch_pending(limit=1)
        with store.transaction() as repo:
            delivery = repo.get_outbox_delivery(staged.staged_command_ids[0])
        assert result.items[0].code == "UNKNOWN"
        assert "secret" not in repr(result)
        assert delivery is not None and delivery.state is OutboxDeliveryState.UNKNOWN
        store.close()


def test_dual_worker_lease_and_expiry_fence_attempts(tmp_path: Path) -> None:
    first_store = _open(tmp_path)
    second_store = _open(tmp_path)
    clock = MutableClock()
    first_gateway = FakeGateway(DispatchCertainty.NOT_SENT)
    second_gateway = FakeGateway(DispatchCertainty.SENT)
    first = _service(first_store, first_gateway, clock, "worker-1")
    second = _service(second_store, second_gateway, clock, "worker-2")
    _stage(first, tmp_path)
    assert first.dispatch_pending(limit=1).claimed_count == 1
    assert second.dispatch_pending(limit=1).claimed_count == 0
    clock.value += dt.timedelta(minutes=2)
    claimed = second.dispatch_pending(limit=1)
    assert claimed.items[0].dispatch_attempt == 2
    assert claimed.items[0].code == "SENT"
    first_store.close()
    second_store.close()


def test_manual_approval_stage_has_receipt_but_no_delivery(tmp_path: Path) -> None:
    store = _open(tmp_path)
    service = _service(store, FakeGateway(), MutableClock())
    staged = _stage(service, tmp_path, config=_planner_config(tmp_path, manual=True))
    assert staged.risk.requires_manual_approval
    assert staged.risk.approved_intent_ids
    assert staged.staged_command_ids == ()
    assert service.dispatch_pending(limit=1).claimed_count == 0
    store.close()


def test_invalid_clock_and_limit_are_stable_and_adapter_not_called(tmp_path: Path) -> None:
    store = _open(tmp_path)
    gateway = FakeGateway()

    class BadClock:
        def now(self):
            raise RuntimeError("host path and token")

    service = _service(store, gateway, BadClock())
    with pytest.raises(ExecutionServiceError, match="^SERVICE_CLOCK_INVALID$"):
        service.dispatch_pending(limit=1)
    with pytest.raises(ExecutionServiceError, match="^SERVICE_DISPATCH_LIMIT_INVALID$"):
        _service(store, gateway, MutableClock()).dispatch_pending(limit=True)
    assert gateway.calls == []
    store.close()


def test_stage_and_command_wire_do_not_claim_to_embed_order_plan(tmp_path: Path) -> None:
    store = _open(tmp_path)
    staged = _stage(_service(store, FakeGateway(), MutableClock()), tmp_path)
    with store.transaction() as repo:
        stage = repo.get_execution_stage(staged.plan.plan_id)
        command = repo.get_command(staged.staged_command_ids[0])
    assert stage is not None and b'"schema_version":"m4-execution-stage-v1"' in stage.payload
    assert command is not None and b'"schema_version":"m4-order-command-v1"' in command.payload
    assert b'"intents"' not in stage.payload
    assert b'"decisions"' not in stage.payload
    assert b'"intent"' in command.payload
    store.close()


def test_hostile_durable_payload_fails_before_adapter_and_is_sanitized(tmp_path: Path) -> None:
    store = _open(tmp_path)
    gateway = FakeGateway()
    service = _service(store, gateway, MutableClock())
    staged = _stage(service, tmp_path)
    command_id = staged.staged_command_ids[0]
    database = tmp_path / "db" / "execution.db"
    with sqlite3.connect(database) as conn:
        conn.execute(
            "UPDATE commands SET payload = ? WHERE command_id = ?",
            (b'{"hostile":"TOKEN C:/secret"}', command_id),
        )
    with pytest.raises(
        ExecutionServiceError, match="^SERVICE_DURABLE_COMMAND_INVALID$"
    ) as caught:
        service.dispatch_pending(limit=1)
    assert caught.value.__cause__ is None
    assert "TOKEN" not in repr(caught.value)
    assert gateway.calls == []
    store.close()


def test_lease_expiring_during_durable_load_never_calls_adapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import quant.execution.service as service_module

    store = _open(tmp_path)
    clock = MutableClock()
    gateway = FakeGateway()
    service = _service(store, gateway, clock)
    _stage(service, tmp_path)
    original = service_module._load_command_and_aggregate

    def expire_during_load(repo, delivery):
        loaded = original(repo, delivery)
        clock.value += dt.timedelta(minutes=2)
        return loaded

    monkeypatch.setattr(service_module, "_load_command_and_aggregate", expire_during_load)
    result = service.dispatch_pending(limit=1)
    assert result.items[0].code == "LEASE_EXPIRED_BEFORE_DISPATCH"
    assert gateway.calls == []
    store.close()


def test_unknown_crossing_lease_is_reported_as_non_durable_window(
    tmp_path: Path,
) -> None:
    class SlowUnknownGateway(FakeGateway):
        def submit(self, *, command, dispatch_attempt: int, now: dt.datetime):
            result = super().submit(
                command=command, dispatch_attempt=dispatch_attempt, now=now
            )
            clock.value += dt.timedelta(minutes=2)
            return result

    store = _open(tmp_path)
    clock = MutableClock()
    gateway = SlowUnknownGateway(DispatchCertainty.UNKNOWN)
    service = _service(store, gateway, clock)
    _stage(service, tmp_path)
    first = service.dispatch_pending(limit=1)
    assert first.items[0].code == "LEASE_EXPIRED_AFTER_DISPATCH"
    assert first.items[0].certainty is DispatchCertainty.UNKNOWN
    second = service.dispatch_pending(limit=1)
    assert second.items[0].dispatch_attempt == 2
    assert gateway.calls[0][0] == gateway.calls[1][0]
    store.close()
