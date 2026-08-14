"""M4-P4 execution service atomicity, recovery and hostile-boundary tests."""

from __future__ import annotations

import datetime as dt
import hashlib
import sqlite3
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest

import quant.execution.service as service_module
import quant.execution.risk_wire as risk_wire_module
from quant.backtest.a_share_execution import build_a_share_rule_config
from quant.backtest.connect_execution import build_connect_rule_config
from quant.backtest.costs import ExecutionCostPeriod, build_execution_cost_schedule
from quant.backtest.fx import FxRate, build_fx_snapshot
from quant.backtest.ledger import build_settlement_rule
from quant.backtest.ledger_adapter import (
    ExecutionLedgerContext,
    LedgerAdapterError,
    LedgerContextProvider,
    apply_ledger_callbacks,
    build_execution_ledger_context,
    decode_ledger_context,
)
from quant.backtest.ledger_wire import decode_ledger_state
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
    OrderCommand,
)
from quant.execution.gateways.contracts import (
    DispatchCertainty,
    GatewayCancelResult,
    GatewayDispatchResult,
)
from quant.execution.service import ExecutionService, ExecutionServiceError
from quant.execution.risk import DailyRiskCounters
from quant.execution.store import (
    ExecutionRepository,
    ExecutionStore,
    LEDGER_CHECKPOINT_KEY,
    OutboxDeliveryState,
    StoreError,
)
from quant.execution.wire import (
    decode_order_aggregate,
    decode_execution_event,
    decode_order_command,
    encode_order_aggregate,
    encode_execution_event,
)
from quant.execution.oms import reduce_order
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
        self.cancel_certainty = DispatchCertainty.SENT
        self.cancel_calls: list[tuple[str, int]] = []
        self.cancel_malformed = False
        self._cancel_source: OrderCommand | None = None

    def submit(self, *, command, dispatch_attempt: int, now: dt.datetime):
        self.calls.append((command.command_id, dispatch_attempt))
        self._cancel_source = command
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

    def cancel(self, *, command, dispatch_attempt: int, now: dt.datetime):
        self.cancel_calls.append((command.cancel_id, dispatch_attempt))
        assert self._cancel_source is not None
        if self.cancel_malformed:
            return object()
        callbacks: tuple[ExecutionEvent, ...] = ()
        if self.cancel_certainty is DispatchCertainty.SENT:
            accepted = build_execution_event(
                command=self._cancel_source,
                broker_order_id=command.broker_order_id,
                event_type=ExecutionEventType.CANCEL_ACCEPTED,
                occurred_at=now,
                cumulative_quantity=command.observed_filled_quantity,
                last_quantity=0,
                last_price=None,
                fees=(),
                reject_code=None,
            )
            cancelled = build_execution_event(
                command=self._cancel_source,
                broker_order_id=command.broker_order_id,
                event_type=ExecutionEventType.CANCELLED,
                occurred_at=now,
                cumulative_quantity=command.observed_filled_quantity,
                last_quantity=0,
                last_price=None,
                fees=(),
                reject_code=None,
            )
            callbacks = (accepted, cancelled)
        return GatewayCancelResult(
            cancel_id=command.cancel_id,
            dispatch_attempt=dispatch_attempt,
            certainty=self.cancel_certainty,
            callbacks=callbacks,
        )


class FixtureLedgerContextProvider:
    def context_for(self, command: OrderCommand) -> ExecutionLedgerContext:
        sessions = tuple(DAY + dt.timedelta(days=offset) for offset in range(4))
        rule = build_settlement_rule(
            selector="fixture-a-share-settlement-v1",
            market=command.intent.market,
            quote_currency=Currency.CNY,
            settlement_currency=Currency.CNY,
            effective_from=DAY,
            effective_to=None,
            trading_sessions=sessions,
            settlement_sessions=sessions,
            trading_calendar_source_identity=_hex("trading-calendar"),
            settlement_calendar_source_identity=_hex("settlement-calendar"),
            settlement_lag_sessions=0,
            sellable_lag_sessions=1,
            reuse_sell_receivables=False,
        )
        return build_execution_ledger_context(
            command=command, settlement_rule=rule, fx_snapshot=None
        )


def _trading_config(
    tmp_path: Path,
    *,
    frozen: str = "[]",
    manual: bool = False,
    max_cancels: int = 20,
):
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
max_cancels_per_day = {max_cancels}
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


def _service(
    store, gateway, clock, worker: str = "worker-1",
    provider: LedgerContextProvider | None = None,
) -> ExecutionService:
    service = ExecutionService(
        store=store,
        gateway=gateway,
        clock=clock,
        worker_id=worker,
        lease_duration=dt.timedelta(minutes=1),
        risk_counter_scope="paper-account",
        ledger_context_provider=provider or FixtureLedgerContextProvider(),
        cancel_gateway=gateway,
    )
    return service


def _stage(service: ExecutionService, tmp_path: Path, *, config=None, symbols=("600000.SH",)):
    targets, market, account = _inputs(symbols, cash="4000" if len(symbols) > 1 else "2000")
    return service.plan_and_stage(
        targets=targets,
        target_identity=_hex("targets"),
        market=market,
        account=account,
        planner_config=config or _planner_config(tmp_path),
    )


def _assert_detached(error: BaseException, *, token: str = "TOKEN") -> None:
    assert error.__cause__ is None
    assert error.__context__ is None
    assert error.__suppress_context__ is True
    assert token not in repr((error, error.args, vars(error)))


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
        counter = repo.get_scoped_daily_risk_counters(
            f"paper-account:{DAY.isoformat()}"
        )
        delivery = repo.get_outbox_delivery(first.staged_command_ids[0])
        receipts = repo.read_recovery_rows().risk_transition_receipts
    assert counter is not None and b'"order_count":1' in counter.payload
    assert len(receipts) == 1 and receipts[0].transition_kind == "ORDER"
    assert delivery is not None and delivery.state is OutboxDeliveryState.PENDING
    store.close()


def test_stage_missing_ledger_context_rolls_back_every_row(tmp_path: Path) -> None:
    class MissingProvider:
        def context_for(self, command: OrderCommand) -> ExecutionLedgerContext:
            del command
            raise RuntimeError("missing settlement context")

    store = _open(tmp_path)
    service = _service(
        store, FakeGateway(), MutableClock(), provider=MissingProvider()
    )
    with pytest.raises(
        ExecutionServiceError, match="^SERVICE_STAGE_WRITE_FAILED$"
    ) as error:
        _stage(service, tmp_path)
    _assert_detached(error.value)
    with store.transaction() as repo:
        rows = repo.read_recovery_rows()
        assert repo.get_execution_stage(_hex("missing")) is None
    assert rows.commands == rows.ledger_contexts == rows.ledger_entries == ()
    assert rows.ledger_checkpoints == () and rows.outbox_deliveries == ()
    store.close()


def test_existing_checkpoint_rejects_second_account_without_side_effects(
    tmp_path: Path,
) -> None:
    store = _open(tmp_path)
    service = _service(store, FakeGateway(), MutableClock())
    _stage(service, tmp_path)
    targets, market, second_account = _inputs(cash="3000")
    with store.transaction() as repo:
        rows_before = repo.read_recovery_rows()
        counter_before = repo.get_scoped_daily_risk_counters(
            f"paper-account:{DAY.isoformat()}"
        )
    with pytest.raises(
        ExecutionServiceError, match="^SERVICE_LEDGER_ACCOUNT_MISMATCH$"
    ) as error:
        service.plan_and_stage(
            targets=targets, target_identity=_hex("second-targets"),
            market=market, account=second_account,
            planner_config=_planner_config(tmp_path),
        )
    _assert_detached(error.value)
    with store.transaction() as repo:
        assert repo.read_recovery_rows() == rows_before
        assert repo.get_scoped_daily_risk_counters(
            f"paper-account:{DAY.isoformat()}"
        ) == counter_before
    store.close()

    reopened = _open(tmp_path)
    with pytest.raises(
        ExecutionServiceError, match="^SERVICE_LEDGER_ACCOUNT_MISMATCH$"
    ) as restarted_error:
        _service(reopened, FakeGateway(), MutableClock()).plan_and_stage(
            targets=targets, target_identity=_hex("second-targets"),
            market=market, account=second_account,
            planner_config=_planner_config(tmp_path),
        )
    _assert_detached(restarted_error.value)
    with reopened.transaction() as repo:
        assert repo.read_recovery_rows() == rows_before
    reopened.close()


def test_adapter_and_checkpoint_hostile_payload_errors_are_detached(
    tmp_path: Path,
) -> None:
    with pytest.raises(LedgerAdapterError, match="^LEDGER_CONTEXT_INVALID$") as parsed:
        decode_ledger_context(b"TOKEN")
    _assert_detached(parsed.value)
    with pytest.raises(LedgerAdapterError, match="^LEDGER_CONTEXT_INVALID$") as domain:
        build_execution_ledger_context(
            command=cast(Any, "TOKEN"),
            settlement_rule=cast(Any, "TOKEN"),
            fx_snapshot=None,
        )
    _assert_detached(domain.value)

    store = _open(tmp_path, "hostile-checkpoint")
    service = _service(store, FakeGateway(), MutableClock())
    _stage(service, tmp_path)
    inner = store._conn  # noqa: SLF001 - hostile persisted wire injection
    assert inner is not None
    inner.execute(
        "UPDATE ledger_checkpoints SET payload = ? WHERE checkpoint_key = ?",
        (b"TOKEN", LEDGER_CHECKPOINT_KEY),
    )
    targets, market, account = _inputs()
    with pytest.raises(
        ExecutionServiceError, match="^SERVICE_STAGE_WRITE_FAILED$"
    ) as checkpoint:
        service.plan_and_stage(
            targets=targets, target_identity=_hex("different-targets"),
            market=market, account=account,
            planner_config=_planner_config(tmp_path),
        )
    _assert_detached(checkpoint.value)
    store.close()


def test_legacy_staged_command_missing_context_fails_closed(tmp_path: Path) -> None:
    store = _open(tmp_path)
    service = _service(store, FakeGateway(), MutableClock())
    staged = _stage(service, tmp_path)
    inner = store._conn  # noqa: SLF001 - simulate an upgraded v3 staged row
    assert inner is not None
    inner.execute(
        "DELETE FROM ledger_contexts WHERE command_id = ?",
        (staged.staged_command_ids[0],),
    )
    with pytest.raises(
        ExecutionServiceError, match="^LEGACY_LEDGER_CONTEXT_MISSING$"
    ):
        _stage(service, tmp_path)
    store.close()


def test_p4_service_fixture_wire_bytes_remain_frozen(tmp_path: Path) -> None:
    store = _open(tmp_path)
    gateway = FakeGateway()
    staged = _stage(_service(store, gateway, MutableClock()), tmp_path)
    command_id = staged.staged_command_ids[0]
    with store.transaction() as repo:
        delivery = repo.get_outbox_delivery(command_id)
        aggregate = repo.get_order_aggregate(command_id)
    assert delivery is not None and aggregate is not None
    command = decode_order_command(delivery.payload)
    event = gateway.submit(command=command, dispatch_attempt=1, now=NOW).callbacks[0]
    assert (
        hashlib.sha256(delivery.payload).hexdigest(),
        hashlib.sha256(aggregate.payload).hexdigest(),
        hashlib.sha256(encode_execution_event(event)).hexdigest(),
    ) == (
        "7a8a797d89c8736c35846bda6f2636a6fa2795892646389cf8ae12c956d103e5",
        "c6e6c8b39119092d3fd7fafd3e11ec3d303f24e70e1f472701c4884804ad08a7",
        "98c52676f5e9165f9d59cfcb11f578df88bb59ab621f4955254926586c7fddac",
    )
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
                "scoped_daily_risk_counters",
                "commands",
                "order_aggregates",
                "outbox",
                "outbox_deliveries",
                "execution_stages",
                "ledger_contexts",
                "ledger_checkpoints",
                "risk_transition_receipts",
            )
        )
    assert counts == (0, 0, 0, 0, 0, 0, 0, 0, 0)
    store.close()


def test_order_receipt_write_failure_rolls_back_every_staged_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _open(tmp_path, "order-receipt-failure")
    service = _service(store, FakeGateway(), MutableClock())

    def fail_receipt(self, **kwargs):
        del self, kwargs
        raise RuntimeError("TOKEN receipt failure /host/path SELECT")

    monkeypatch.setattr(
        ExecutionRepository, "put_risk_transition_receipt", fail_receipt
    )
    with pytest.raises(
        ExecutionServiceError, match="^SERVICE_STAGE_WRITE_FAILED$"
    ) as error:
        _stage(service, tmp_path)
    _assert_detached(error.value)
    database = tmp_path / "order-receipt-failure" / "execution.db"
    with sqlite3.connect(database) as connection:
        counts = {
            table: connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in (
                "scoped_daily_risk_counters", "commands", "order_aggregates", "outbox",
                "outbox_deliveries", "execution_stages", "ledger_contexts",
                "ledger_checkpoints", "risk_transition_receipts",
            )
        }
    assert set(counts.values()) == {0}
    store.close()


def test_order_exact_replay_rejects_missing_transition_receipt(tmp_path: Path) -> None:
    store = _open(tmp_path, "order-missing-receipt")
    service = _service(store, FakeGateway(), MutableClock())
    first = _stage(service, tmp_path)
    inner = store._conn  # noqa: SLF001 - hostile upgraded legacy fixture
    assert inner is not None
    inner.execute(
        "DELETE FROM risk_transition_receipts WHERE transition_kind='ORDER' "
        "AND subject_id=?",
        (first.plan.plan_id,),
    )
    with pytest.raises(
        ExecutionServiceError, match="^SERVICE_RISK_RECEIPT_INVALID$"
    ) as error:
        _stage(service, tmp_path)
    _assert_detached(error.value)
    store.close()


def test_order_exact_replay_rejects_whole_rehashed_wrong_counter_scope(
    tmp_path: Path,
) -> None:
    store = _open(tmp_path, "order-wrong-scope")
    service = _service(store, FakeGateway(), MutableClock())
    staged = _stage(service, tmp_path)
    with store.transaction() as repo:
        row = repo.get_risk_transition_receipt(
            transition_kind="ORDER", subject_id=staged.plan.plan_id
        )
    assert row is not None
    original = risk_wire_module.decode_risk_receipt(row.payload)
    resigned = risk_wire_module._build(  # noqa: SLF001 - adversarial re-sign fixture
        kind="ORDER",
        sequence=original.sequence,
        previous_receipt_id=original.previous_receipt_id,
        subject_id=original.subject_id,
        risk_counter_key=f"other-scope:{DAY.isoformat()}",
        predecessor_counters=DailyRiskCounters(DAY, 0, 0, Decimal(0)),
        decision=original.decision,
    )
    payload = risk_wire_module.encode_risk_receipt(resigned)
    inner = store._conn  # noqa: SLF001 - coordinated offline closure replacement
    assert inner is not None
    inner.execute(
        "UPDATE risk_transition_receipts SET receipt_id=?, risk_counter_key=?, "
        "predecessor_counter_identity=?, projected_counter_identity=?, payload=? "
        "WHERE transition_kind='ORDER' AND subject_id=?",
        (
            resigned.receipt_id,
            resigned.risk_counter_key,
            resigned.predecessor_counter_identity,
            resigned.projected_counter_identity,
            payload,
            staged.plan.plan_id,
        ),
    )
    with pytest.raises(
        ExecutionServiceError, match="^SERVICE_RISK_RECEIPT_INVALID$"
    ) as error:
        _stage(service, tmp_path)
    _assert_detached(error.value)
    store.close()


def test_order_service_preserves_tx_busy_and_fresh_retry(tmp_path: Path) -> None:
    first = _open(tmp_path, "order-service-busy")
    second = _open(tmp_path, "order-service-busy")
    service = _service(second, FakeGateway(), MutableClock())
    try:
        with first.transaction() as locked_repo:
            with pytest.raises(StoreError, match="^TX_BUSY$") as busy:
                _stage(service, tmp_path)
            assert busy.value.__cause__ is busy.value.__context__ is None
            locked_rows = locked_repo.read_recovery_rows()
            assert locked_rows.commands == locked_rows.risk_transition_receipts == ()
            assert locked_rows.risk_counter_rows == ()
        staged = _stage(service, tmp_path)
        assert not staged.replayed
        with second.transaction() as repo:
            rows = repo.read_recovery_rows()
        assert len(rows.risk_transition_receipts) == len(rows.commands) == 1
    finally:
        second.close()
        first.close()


def test_order_replay_rejects_current_counter_tail_drift(tmp_path: Path) -> None:
    store = _open(tmp_path, "order-counter-tail-drift")
    service = _service(store, FakeGateway(), MutableClock())
    _stage(service, tmp_path)
    payload = service_module._encode_counter(  # noqa: SLF001 - hostile store drift
        DailyRiskCounters(DAY, 0, 0, Decimal(0))
    )
    inner = store._conn  # noqa: SLF001 - hostile store drift
    assert inner is not None
    inner.execute(
        "UPDATE scoped_daily_risk_counters SET identity=?, payload=? WHERE counter_key=?",
        (
            hashlib.sha256(payload).hexdigest(),
            payload,
            f"paper-account:{DAY.isoformat()}",
        ),
    )
    with pytest.raises(
        ExecutionServiceError, match="^SERVICE_RISK_RECEIPT_INVALID$"
    ) as error:
        _stage(service, tmp_path)
    _assert_detached(error.value)
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
        recovery = repo.read_recovery_rows()
    assert delivery is not None and delivery.state is OutboxDeliveryState.SENT
    assert aggregate is not None and b'"status":"FILLED"' in aggregate.payload
    assert recovery.ledger_entries
    assert recovery.ledger_checkpoints[0].last_entry_id in {
        item.key for item in recovery.ledger_entries
    }
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
        recovery = repo.read_recovery_rows()
    assert aggregate is not None
    assert aggregate.payload.count(result.items[0].callback_event_ids[0].encode()) == 1
    assert len({item.key for item in recovery.ledger_entries}) == len(
        recovery.ledger_entries
    )
    command = decode_order_command(recovery.commands[0].payload)
    event = decode_execution_event(recovery.events[0].payload, command=command)
    context = decode_ledger_context(recovery.ledger_contexts[0].payload)
    checkpoint = decode_ledger_state(recovery.ledger_checkpoints[0].payload)
    replay = apply_ledger_callbacks(
        state=checkpoint,
        command=command,
        callbacks=(event,),
        context=context,
    )
    assert replay.state == checkpoint and replay.entries == ()
    store.close()


def test_callback_failure_rolls_back_events_aggregate_and_sent_mark(tmp_path: Path) -> None:
    store = _open(tmp_path)
    gateway = FakeGateway()
    gateway.illegal_callback_sequence = True
    service = _service(store, gateway, MutableClock())
    staged = _stage(service, tmp_path)
    with store.transaction() as repo:
        checkpoint_before = repo.get_ledger_checkpoint("paper-shadow-primary-v1")
    result = service.dispatch_pending(limit=1)
    assert result.items[0].code == "CALLBACK_TRANSACTION_FAILED"
    with store.transaction() as repo:
        delivery = repo.get_outbox_delivery(staged.staged_command_ids[0])
        aggregate = repo.get_order_aggregate(staged.staged_command_ids[0])
        events = tuple(repo.get_event(event_id) for event_id in result.items[0].callback_event_ids)
        checkpoint_after = repo.get_ledger_checkpoint("paper-shadow-primary-v1")
        recovery = repo.read_recovery_rows()
    assert delivery is not None and delivery.state is OutboxDeliveryState.LEASED
    assert aggregate is not None and b'"status":"CREATED"' in aggregate.payload
    assert events == (None, None)
    assert checkpoint_after == checkpoint_before
    assert recovery.ledger_entries == ()
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
        recovery = repo.read_recovery_rows()
    assert delivery is not None
    if certainty is DispatchCertainty.NOT_SENT:
        assert result.items[0].code == "NOT_SENT"
        assert delivery.state is OutboxDeliveryState.LEASED
    else:
        assert result.items[0].code == "UNKNOWN"
        assert delivery.state is OutboxDeliveryState.UNKNOWN
    assert recovery.ledger_entries == ()
    store.close()


def test_second_ledger_entry_failure_rolls_back_callback_transaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _open(tmp_path)
    gateway = FakeGateway()
    gateway.partial_then_fill = True
    service = _service(store, gateway, MutableClock())
    staged = _stage(service, tmp_path)
    with store.transaction() as repo:
        checkpoint_before = repo.get_ledger_checkpoint("paper-shadow-primary-v1")
    real_put = ExecutionRepository.put_ledger_entry
    calls = 0

    def fail_second(self: ExecutionRepository, **kwargs: Any) -> bool:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("hostile second entry")
        return real_put(self, **kwargs)

    monkeypatch.setattr(ExecutionRepository, "put_ledger_entry", fail_second)
    result = service.dispatch_pending(limit=1)
    assert result.items[0].code == "CALLBACK_TRANSACTION_FAILED"
    with store.transaction() as repo:
        delivery = repo.get_outbox_delivery(staged.staged_command_ids[0])
        aggregate = repo.get_order_aggregate(staged.staged_command_ids[0])
        checkpoint_after = repo.get_ledger_checkpoint("paper-shadow-primary-v1")
        recovery = repo.read_recovery_rows()
    assert delivery is not None and delivery.state is OutboxDeliveryState.LEASED
    assert aggregate is not None and b'"status":"CREATED"' in aggregate.payload
    assert recovery.events == () and recovery.ledger_entries == ()
    assert checkpoint_after == checkpoint_before
    store.close()


@pytest.mark.parametrize(
    "failing_method", ["replace_ledger_checkpoint", "mark_outbox_sent"]
)
def test_final_callback_writes_roll_back_the_entire_transaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failing_method: str,
) -> None:
    store = _open(tmp_path, failing_method)
    gateway = FakeGateway()
    gateway.partial_then_fill = True
    service = _service(store, gateway, MutableClock())
    staged = _stage(service, tmp_path)
    with store.transaction() as repo:
        aggregate_before = repo.get_order_aggregate(staged.staged_command_ids[0])
        checkpoint_before = repo.get_ledger_checkpoint(LEDGER_CHECKPOINT_KEY)

    def fail_final(self: ExecutionRepository, **kwargs: Any) -> bool:
        del self, kwargs
        raise RuntimeError("hostile final write TOKEN")

    monkeypatch.setattr(ExecutionRepository, failing_method, fail_final)
    result = service.dispatch_pending(limit=1)
    assert result.items[0].code == "CALLBACK_TRANSACTION_FAILED"
    assert "TOKEN" not in repr(result)
    with store.transaction() as repo:
        delivery = repo.get_outbox_delivery(staged.staged_command_ids[0])
        aggregate_after = repo.get_order_aggregate(staged.staged_command_ids[0])
        checkpoint_after = repo.get_ledger_checkpoint(LEDGER_CHECKPOINT_KEY)
        recovery = repo.read_recovery_rows()
    assert delivery is not None and delivery.state is OutboxDeliveryState.LEASED
    assert aggregate_after == aggregate_before
    assert checkpoint_after == checkpoint_before
    assert recovery.events == () and recovery.ledger_entries == ()
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


def _stage_submitted_order(
    tmp_path: Path,
    *,
    gateway: FakeGateway | None = None,
    name: str = "cancel-db",
) -> tuple[ExecutionStore, FakeGateway, ExecutionService, str]:
    store = _open(tmp_path, name)
    transport = gateway or FakeGateway()
    service = _service(store, transport, MutableClock())
    staged = _stage(service, tmp_path)
    dispatched = service.dispatch_commands(command_ids=staged.staged_command_ids)
    assert dispatched.items[0].code == "SENT"
    return store, transport, service, staged.staged_command_ids[0]


def test_stage_cancel_is_atomic_and_replay_counts_once(tmp_path: Path) -> None:
    store, gateway, service, command_id = _stage_submitted_order(tmp_path)
    config = _trading_config(tmp_path)
    first = service.stage_cancel(command_id=command_id, trading_config=config)
    second = service.stage_cancel(command_id=command_id, trading_config=config)

    assert first.replayed is False
    assert second.replayed is True
    assert second.cancel == first.cancel
    assert gateway.cancel_calls == []
    with store.transaction() as repo:
        counter = repo.get_scoped_daily_risk_counters(
            f"paper-account:{DAY.isoformat()}"
        )
        delivery = repo.get_cancel_delivery(first.cancel.cancel_id)
        rows = repo.read_recovery_rows()
    assert counter is not None and b'"cancel_count":1' in counter.payload
    assert delivery is not None and delivery.state is OutboxDeliveryState.PENDING
    assert len(rows.cancel_commands) == len(rows.cancel_deliveries) == 1
    assert tuple(item.transition_kind for item in rows.risk_transition_receipts) == (
        "ORDER", "CANCEL",
    )
    store.close()


def test_cancel_exact_replay_rejects_whole_rehashed_wrong_counter_scope(
    tmp_path: Path,
) -> None:
    store, _, service, command_id = _stage_submitted_order(
        tmp_path, name="cancel-wrong-scope"
    )
    staged = service.stage_cancel(
        command_id=command_id, trading_config=_trading_config(tmp_path)
    )
    with store.transaction() as repo:
        row = repo.get_risk_transition_receipt(
            transition_kind="CANCEL", subject_id=staged.cancel.cancel_id
        )
    assert row is not None
    original = risk_wire_module.decode_risk_receipt(row.payload)
    resigned = risk_wire_module._build(  # noqa: SLF001 - adversarial re-sign fixture
        kind="CANCEL",
        sequence=original.sequence,
        previous_receipt_id=original.previous_receipt_id,
        subject_id=original.subject_id,
        risk_counter_key=f"other-scope:{DAY.isoformat()}",
        predecessor_counters=DailyRiskCounters(DAY, 0, 0, Decimal(0)),
        decision=original.decision,
    )
    payload = risk_wire_module.encode_risk_receipt(resigned)
    inner = store._conn  # noqa: SLF001 - coordinated offline closure replacement
    assert inner is not None
    inner.execute(
        "UPDATE risk_transition_receipts SET receipt_id=?, risk_counter_key=?, "
        "predecessor_counter_identity=?, projected_counter_identity=?, payload=? "
        "WHERE transition_kind='CANCEL' AND subject_id=?",
        (
            resigned.receipt_id,
            resigned.risk_counter_key,
            resigned.predecessor_counter_identity,
            resigned.projected_counter_identity,
            payload,
            staged.cancel.cancel_id,
        ),
    )
    with pytest.raises(
        ExecutionServiceError, match="^SERVICE_RISK_RECEIPT_INVALID$"
    ) as error:
        service.stage_cancel(
            command_id=command_id, trading_config=_trading_config(tmp_path)
        )
    _assert_detached(error.value)
    store.close()


def test_cancel_service_preserves_tx_busy_and_fresh_retry(tmp_path: Path) -> None:
    first, _, _, command_id = _stage_submitted_order(
        tmp_path, name="cancel-service-busy"
    )
    second = _open(tmp_path, "cancel-service-busy")
    service = _service(second, FakeGateway(), MutableClock())
    try:
        with first.transaction() as locked_repo:
            with pytest.raises(StoreError, match="^TX_BUSY$") as busy:
                service.stage_cancel(
                    command_id=command_id, trading_config=_trading_config(tmp_path)
                )
            assert busy.value.__cause__ is busy.value.__context__ is None
            locked_rows = locked_repo.read_recovery_rows()
            assert locked_rows.cancel_commands == locked_rows.cancel_deliveries == ()
            assert tuple(
                item.transition_kind for item in locked_rows.risk_transition_receipts
            ) == ("ORDER",)
            assert b'"cancel_count":0' in locked_rows.risk_counter_rows[0].payload
        staged = service.stage_cancel(
            command_id=command_id, trading_config=_trading_config(tmp_path)
        )
        assert not staged.replayed
        with second.transaction() as repo:
            rows = repo.read_recovery_rows()
        assert tuple(item.transition_kind for item in rows.risk_transition_receipts) == (
            "ORDER", "CANCEL",
        )
    finally:
        second.close()
        first.close()


def test_cancel_receipt_failure_rolls_back_counter_cancel_and_delivery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, _, service, command_id = _stage_submitted_order(
        tmp_path, name="cancel-receipt-rollback"
    )

    def fail_cancel_receipt(self, **kwargs):
        del self, kwargs
        raise RuntimeError("TOKEN hostile receipt write")

    monkeypatch.setattr(
        ExecutionRepository, "put_risk_transition_receipt", fail_cancel_receipt
    )
    with pytest.raises(ExecutionServiceError, match="^CANCEL_STAGE_FAILED$") as error:
        service.stage_cancel(
            command_id=command_id, trading_config=_trading_config(tmp_path)
        )
    _assert_detached(error.value)
    with store.transaction() as repo:
        counter = repo.get_scoped_daily_risk_counters(
            f"paper-account:{DAY.isoformat()}"
        )
        rows = repo.read_recovery_rows()
    assert counter is not None and b'"cancel_count":0' in counter.payload
    assert rows.cancel_commands == rows.cancel_deliveries == ()
    assert tuple(item.transition_kind for item in rows.risk_transition_receipts) == (
        "ORDER",
    )
    store.close()


def test_dispatch_cancel_commits_callbacks_oms_links_and_terminal_state(
    tmp_path: Path,
) -> None:
    store, gateway, service, command_id = _stage_submitted_order(
        tmp_path, name="cancel-sent"
    )
    staged = service.stage_cancel(
        command_id=command_id, trading_config=_trading_config(tmp_path)
    )
    result = service.dispatch_cancel(cancel_id=staged.cancel.cancel_id)

    assert result.code == "SENT"
    assert result.certainty is DispatchCertainty.SENT
    assert len(result.callback_event_ids) == 2
    assert gateway.cancel_calls == [(staged.cancel.cancel_id, 1)]
    with store.transaction() as repo:
        delivery = repo.get_cancel_delivery(staged.cancel.cancel_id)
        aggregate = repo.get_order_aggregate(command_id)
        rows = repo.read_recovery_rows()
    assert delivery is not None and delivery.state is OutboxDeliveryState.SENT
    assert aggregate is not None and b'"status":"CANCELLED"' in aggregate.payload
    assert {item.event_id for item in rows.cancel_event_links} == set(
        result.callback_event_ids
    )
    store.close()


def test_dispatch_cancel_not_sent_is_explicitly_retryable(tmp_path: Path) -> None:
    gateway = FakeGateway()
    gateway.cancel_certainty = DispatchCertainty.NOT_SENT
    store, _, service, command_id = _stage_submitted_order(
        tmp_path, gateway=gateway, name="cancel-not-sent"
    )
    staged = service.stage_cancel(
        command_id=command_id, trading_config=_trading_config(tmp_path)
    )
    first = service.dispatch_cancel(cancel_id=staged.cancel.cancel_id)
    second = service.dispatch_cancel(cancel_id=staged.cancel.cancel_id)

    assert first.code == second.code == "NOT_SENT"
    assert gateway.cancel_calls == [
        (staged.cancel.cancel_id, 1),
        (staged.cancel.cancel_id, 2),
    ]
    with store.transaction() as repo:
        delivery = repo.get_cancel_delivery(staged.cancel.cancel_id)
    assert delivery is not None
    assert delivery.state is OutboxDeliveryState.PENDING
    assert delivery.attempt_count == 2
    store.close()


def test_dispatch_cancel_malformed_result_becomes_durable_unknown(
    tmp_path: Path,
) -> None:
    gateway = FakeGateway()
    gateway.cancel_malformed = True
    store, _, service, command_id = _stage_submitted_order(
        tmp_path, gateway=gateway, name="cancel-unknown"
    )
    staged = service.stage_cancel(
        command_id=command_id, trading_config=_trading_config(tmp_path)
    )
    result = service.dispatch_cancel(cancel_id=staged.cancel.cancel_id)

    assert result.code == "CANCEL_DELIVERY_UNKNOWN"
    assert result.certainty is DispatchCertainty.UNKNOWN
    with store.transaction() as repo:
        delivery = repo.get_cancel_delivery(staged.cancel.cancel_id)
    assert delivery is not None
    assert delivery.state is OutboxDeliveryState.UNKNOWN
    assert delivery.last_error_code == "CANCEL_RESULT_INVALID"
    with pytest.raises(
        ExecutionServiceError, match="^CANCEL_DELIVERY_NOT_CLAIMABLE$"
    ):
        service.dispatch_cancel(cancel_id=staged.cancel.cancel_id)
    assert len(gateway.cancel_calls) == 1
    store.close()


def test_cancel_started_attempt_crossing_lease_is_unknown_and_never_reclaimed(
    tmp_path: Path,
) -> None:
    clock = MutableClock()

    class LeaseCrossingGateway(FakeGateway):
        def cancel(self, *, command, dispatch_attempt: int, now: dt.datetime):
            result = super().cancel(
                command=command, dispatch_attempt=dispatch_attempt, now=now
            )
            clock.value += dt.timedelta(minutes=2)
            return object() if result is not None else result

    gateway = LeaseCrossingGateway()
    store = _open(tmp_path, "cancel-crossed-lease")
    service = _service(store, gateway, clock)
    staged_order = _stage(service, tmp_path)
    assert service.dispatch_commands(
        command_ids=staged_order.staged_command_ids
    ).items[0].code == "SENT"
    staged = service.stage_cancel(
        command_id=staged_order.staged_command_ids[0],
        trading_config=_trading_config(tmp_path),
    )

    first = service.dispatch_cancel(cancel_id=staged.cancel.cancel_id)
    assert first.code == "CANCEL_DELIVERY_UNKNOWN"
    with store.transaction() as repo:
        delivery = repo.get_cancel_delivery(staged.cancel.cancel_id)
    assert delivery is not None
    assert delivery.state is OutboxDeliveryState.UNKNOWN
    assert delivery.attempt_count == 1
    assert delivery.last_error_code == "CANCEL_RESULT_INVALID"
    with pytest.raises(
        ExecutionServiceError, match="^CANCEL_DELIVERY_NOT_CLAIMABLE$"
    ):
        service.dispatch_cancel(cancel_id=staged.cancel.cancel_id)
    assert gateway.cancel_calls == [(staged.cancel.cancel_id, 1)]
    store.close()


def test_cancel_late_fill_between_arm_and_crossing_is_detected_before_gateway(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, gateway, service, command_id = _stage_submitted_order(
        tmp_path, name="cancel-late-fill"
    )
    late_store = _open(tmp_path, "cancel-late-fill")
    staged = service.stage_cancel(
        command_id=command_id, trading_config=_trading_config(tmp_path)
    )
    original_transaction = ExecutionStore.transaction
    calls = 0

    @contextmanager
    def intercept_transaction(self: ExecutionStore):
        nonlocal calls
        if self is store:
            calls += 1
            if calls == 3:
                with original_transaction(late_store) as repo:
                    command_row = repo.get_command(command_id)
                    aggregate_row = repo.get_order_aggregate(command_id)
                    assert command_row is not None and aggregate_row is not None
                    command = decode_order_command(command_row.payload)
                    aggregate = decode_order_aggregate(
                        aggregate_row.payload, command=command
                    )
                    quantity = command.intent.quantity // 2
                    event = build_execution_event(
                        command=command,
                        broker_order_id="PAPER-1",
                        event_type=ExecutionEventType.PARTIAL_FILL,
                        occurred_at=NOW,
                        cumulative_quantity=quantity,
                        last_quantity=quantity,
                        last_price=command.intent.limit_price,
                        fees=(),
                        reject_code=None,
                    )
                    repo.put_event(
                        event_id=event.event_id,
                        command_id=command_id,
                        identity=event.event_id,
                        payload=encode_execution_event(event),
                    )
                    updated = reduce_order(aggregate, command, event)
                    payload = encode_order_aggregate(updated)
                    repo.replace_order_aggregate(
                        command_id=command_id,
                        expected_identity=aggregate_row.identity,
                        identity=hashlib.sha256(payload).hexdigest(),
                        payload=payload,
                    )
        with original_transaction(self) as repo:
            yield repo

    monkeypatch.setattr(ExecutionStore, "transaction", intercept_transaction)
    result = service.dispatch_cancel(cancel_id=staged.cancel.cancel_id)

    assert result.certainty is DispatchCertainty.UNKNOWN
    assert result.code == "CANCEL_SNAPSHOT_DRIFT"
    assert gateway.cancel_calls == []
    with original_transaction(store) as repo:
        delivery = repo.get_cancel_delivery(staged.cancel.cancel_id)
    assert delivery is not None and delivery.state is OutboxDeliveryState.UNKNOWN
    assert delivery.last_error_code == "CANCEL_SNAPSHOT_DRIFT"
    late_store.close()
    store.close()


def test_cancel_callback_transaction_failure_is_explicit_and_durable_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, gateway, service, command_id = _stage_submitted_order(
        tmp_path, name="cancel-callback-failure"
    )
    staged = service.stage_cancel(
        command_id=command_id, trading_config=_trading_config(tmp_path)
    )

    def fail_link(self: ExecutionRepository, **kwargs: Any) -> bool:
        del self, kwargs
        raise RuntimeError("TOKEN callback path")

    monkeypatch.setattr(ExecutionRepository, "put_cancel_event_link", fail_link)
    result = service.dispatch_cancel(cancel_id=staged.cancel.cancel_id)

    assert result.code == "CANCEL_CALLBACK_TRANSACTION_FAILED"
    assert result.certainty is DispatchCertainty.UNKNOWN
    assert "TOKEN" not in repr(result)
    with store.transaction() as repo:
        delivery = repo.get_cancel_delivery(staged.cancel.cancel_id)
        rows = repo.read_recovery_rows()
    assert delivery is not None and delivery.state is OutboxDeliveryState.UNKNOWN
    assert delivery.last_error_code == "CANCEL_CALLBACK_TRANSACTION_FAILED"
    assert rows.cancel_event_links == ()
    assert gateway.cancel_calls == [(staged.cancel.cancel_id, 1)]
    store.close()


def test_cancel_gateway_input_validation_fails_before_adapter_with_clear_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, gateway, service, command_id = _stage_submitted_order(
        tmp_path, name="cancel-gateway-input"
    )
    staged = service.stage_cancel(
        command_id=command_id, trading_config=_trading_config(tmp_path)
    )

    def reject_input(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeError("TOKEN invalid adapter input")

    monkeypatch.setattr(service_module, "validate_gateway_cancel", reject_input)
    result = service.dispatch_cancel(cancel_id=staged.cancel.cancel_id)

    assert result.code == "CANCEL_GATEWAY_INPUT_INVALID"
    assert result.certainty is DispatchCertainty.UNKNOWN
    assert gateway.cancel_calls == []
    with store.transaction() as repo:
        delivery = repo.get_cancel_delivery(staged.cancel.cancel_id)
    assert delivery is not None and delivery.state is OutboxDeliveryState.UNKNOWN
    assert delivery.last_error_code == "CANCEL_GATEWAY_INPUT_INVALID"
    store.close()


def test_stage_cancel_limit_rejection_has_zero_partial_writes(tmp_path: Path) -> None:
    store = _open(tmp_path, "cancel-limit")
    gateway = FakeGateway()
    service = _service(store, gateway, MutableClock())
    staged_orders = _stage(
        service, tmp_path, symbols=("600000.SH", "000001.SZ")
    )
    dispatched = service.dispatch_commands(
        command_ids=tuple(sorted(staged_orders.staged_command_ids))
    )
    assert all(item.code == "SENT" for item in dispatched.items)
    config = _trading_config(tmp_path, max_cancels=1)
    service.stage_cancel(
        command_id=staged_orders.staged_command_ids[0], trading_config=config
    )
    with pytest.raises(ExecutionServiceError, match="^CANCEL_LIMIT_EXCEEDED$"):
        service.stage_cancel(
            command_id=staged_orders.staged_command_ids[1], trading_config=config
        )
    with store.transaction() as repo:
        counter = repo.get_scoped_daily_risk_counters(
            f"paper-account:{DAY.isoformat()}"
        )
        rows = repo.read_recovery_rows()
    assert counter is not None and b'"cancel_count":1' in counter.payload
    assert len(rows.cancel_commands) == len(rows.cancel_deliveries) == 1
    store.close()


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


def test_dispatch_commands_calls_only_the_exact_selected_allowlist(
    tmp_path: Path,
) -> None:
    store = _open(tmp_path)
    gateway = FakeGateway()
    service = _service(store, gateway, MutableClock())
    staged = _stage(
        service,
        tmp_path,
        symbols=("600000.SH", "000001.SZ", "600519.SH"),
    )
    ordered = tuple(sorted(staged.staged_command_ids))
    unselected, selected = ordered[0], ordered[1:]
    with store.transaction() as repo:
        before = repo.get_outbox_delivery(unselected)
    result = service.dispatch_commands(command_ids=selected)
    with store.transaction() as repo:
        after = repo.get_outbox_delivery(unselected)
    assert result.claimed_count == 2
    assert tuple(command_id for command_id, _ in gateway.calls) == selected
    assert before == after
    assert after is not None and after.state is OutboxDeliveryState.PENDING
    store.close()


@pytest.mark.parametrize("blocked_state", ["SENT", "UNKNOWN", "LEASED", "BROKEN"])
def test_dispatch_commands_is_all_or_nothing_for_unclaimable_member(
    tmp_path: Path, blocked_state: str,
) -> None:
    store = _open(tmp_path)
    gateway = FakeGateway()
    service = _service(store, gateway, MutableClock())
    staged = _stage(service, tmp_path, symbols=("600000.SH", "000001.SZ"))
    command_ids = tuple(sorted(staged.staged_command_ids))
    terminal_id = command_ids[1]
    if blocked_state == "BROKEN":
        store.close()
        with sqlite3.connect(tmp_path / "db" / "execution.db") as conn:
            conn.execute("DELETE FROM outbox WHERE outbox_key = ?", (terminal_id,))
        store = _open(tmp_path)
        service = _service(store, gateway, MutableClock())
    else:
        with store.transaction() as repo:
            claimed = repo.claim_selected_outbox_deliveries(
                command_ids=(terminal_id,),
                worker_id="terminal-worker",
                now=NOW,
                lease_until=NOW + dt.timedelta(minutes=1),
            )[0]
            if blocked_state == "SENT":
                repo.mark_outbox_sent(
                    outbox_key=terminal_id,
                    lease_owner="terminal-worker",
                    expected_attempt=claimed.attempt_count,
                    sent_at=NOW + dt.timedelta(seconds=1),
                )
            elif blocked_state == "UNKNOWN":
                repo.mark_outbox_unknown(
                    outbox_key=terminal_id,
                    lease_owner="terminal-worker",
                    expected_attempt=claimed.attempt_count,
                    unknown_at=NOW + dt.timedelta(seconds=1),
                    error_code="FIXTURE_UNKNOWN",
                )
    with pytest.raises(
        ExecutionServiceError, match="^SERVICE_SELECTED_CLAIM_FAILED$"
    ) as error:
        service.dispatch_commands(command_ids=command_ids)
    _assert_detached(error.value)
    with store.transaction() as repo:
        ready = repo.get_outbox_delivery(command_ids[0])
    assert ready is not None and ready.state is OutboxDeliveryState.PENDING
    assert ready.attempt_count == 0
    assert gateway.calls == []
    store.close()


@pytest.mark.parametrize(
    "command_ids",
    [
        (),
        tuple(reversed(sorted((_hex("a"), _hex("b"))))),
        (_hex("duplicate"), _hex("duplicate")),
        ("TOKEN/C:/hostile",),
        (cast(str, object()),),
    ],
)
def test_dispatch_commands_rejects_malformed_selection_without_context(
    tmp_path: Path, command_ids: tuple[str, ...]
) -> None:
    store = _open(tmp_path)
    gateway = FakeGateway()
    service = _service(store, gateway, MutableClock())
    with pytest.raises(
        ExecutionServiceError, match="^SERVICE_COMMAND_SELECTION_INVALID$"
    ) as error:
        service.dispatch_commands(command_ids=command_ids)
    _assert_detached(error.value)
    assert gateway.calls == []
    store.close()


def test_dispatch_commands_rejects_missing_canonical_id_without_context(
    tmp_path: Path,
) -> None:
    store = _open(tmp_path)
    gateway = FakeGateway()
    service = _service(store, gateway, MutableClock())
    missing = (_hex("missing-canonical-command"),)
    with pytest.raises(
        ExecutionServiceError, match="^SERVICE_SELECTED_CLAIM_FAILED$"
    ) as error:
        service.dispatch_commands(command_ids=missing)
    _assert_detached(error.value)
    assert missing[0] not in repr((error.value, error.value.args, vars(error.value)))
    assert gateway.calls == []
    store.close()


def test_dispatch_commands_same_exact_set_has_at_most_one_winner(
    tmp_path: Path,
) -> None:
    first_store = _open(tmp_path)
    second_store = _open(tmp_path)
    first_gateway = FakeGateway()
    second_gateway = FakeGateway()
    first = _service(first_store, first_gateway, MutableClock(), "worker-1")
    second = _service(second_store, second_gateway, MutableClock(), "worker-2")
    staged = _stage(first, tmp_path, symbols=("600000.SH", "000001.SZ"))
    command_ids = tuple(sorted(staged.staged_command_ids))
    assert first.dispatch_commands(command_ids=command_ids).claimed_count == 2
    with pytest.raises(ExecutionServiceError, match="SERVICE_SELECTED_CLAIM_FAILED"):
        second.dispatch_commands(command_ids=command_ids)
    assert len(first_gateway.calls) == 2
    assert second_gateway.calls == []
    first_store.close()
    second_store.close()


def test_dispatch_exact_pending_commands_sends_complete_global_set(
    tmp_path: Path,
) -> None:
    store = _open(tmp_path)
    gateway = FakeGateway()
    service = _service(store, gateway, MutableClock())
    staged = _stage(service, tmp_path, symbols=("600000.SH", "000001.SZ"))
    command_ids = tuple(sorted(staged.staged_command_ids))
    result = service.dispatch_exact_pending_commands(command_ids=command_ids)
    assert result.claimed_count == 2
    assert tuple(command_id for command_id, _ in gateway.calls) == command_ids
    store.close()


def test_dispatch_exact_pending_commands_rejects_concurrent_extra_without_send(
    tmp_path: Path,
) -> None:
    store = _open(tmp_path)
    gateway = FakeGateway()
    service = _service(store, gateway, MutableClock())
    staged = _stage(service, tmp_path, symbols=("600000.SH",))
    confirmed_ids = tuple(sorted(staged.staged_command_ids))
    concurrent = _stage(service, tmp_path, symbols=("000001.SZ",))
    with pytest.raises(
        ExecutionServiceError, match="^SERVICE_EXACT_PENDING_SET_DRIFT$"
    ) as error:
        service.dispatch_exact_pending_commands(command_ids=confirmed_ids)
    _assert_detached(error.value)
    assert gateway.calls == []
    all_ids = tuple(sorted((*confirmed_ids, *concurrent.staged_command_ids)))
    with store.transaction() as repo:
        deliveries = tuple(
            repo.get_outbox_delivery(command_id) for command_id in all_ids
        )
    assert all(
        item is not None
        and item.state is OutboxDeliveryState.PENDING
        and item.attempt_count == 0
        for item in deliveries
    )
    store.close()


def test_dispatch_exact_pending_commands_same_set_has_at_most_one_winner(
    tmp_path: Path,
) -> None:
    first_store = _open(tmp_path)
    second_store = _open(tmp_path)
    first_gateway = FakeGateway()
    second_gateway = FakeGateway()
    first = _service(first_store, first_gateway, MutableClock(), "exact-worker-1")
    second = _service(second_store, second_gateway, MutableClock(), "exact-worker-2")
    staged = _stage(first, tmp_path, symbols=("600000.SH", "000001.SZ"))
    command_ids = tuple(sorted(staged.staged_command_ids))
    assert first.dispatch_exact_pending_commands(command_ids=command_ids).claimed_count == 2
    with pytest.raises(
        ExecutionServiceError, match="^SERVICE_EXACT_PENDING_SET_DRIFT$"
    ):
        second.dispatch_exact_pending_commands(command_ids=command_ids)
    assert len(first_gateway.calls) == 2
    assert second_gateway.calls == []
    first_store.close()
    second_store.close()


def test_dispatch_exact_pending_commands_preserves_writer_busy_as_retry(
    tmp_path: Path,
) -> None:
    store = _open(tmp_path)
    gateway = FakeGateway()
    service = _service(store, gateway, MutableClock())
    staged = _stage(service, tmp_path, symbols=("600000.SH",))
    command_ids = tuple(sorted(staged.staged_command_ids))
    blocker = sqlite3.connect(tmp_path / "db" / "execution.db", timeout=0)
    try:
        blocker.execute("BEGIN IMMEDIATE")
        with pytest.raises(
            ExecutionServiceError, match="^SERVICE_EXACT_PENDING_WRITE_FAILED$"
        ) as error:
            service.dispatch_exact_pending_commands(command_ids=command_ids)
        _assert_detached(error.value)
        assert gateway.calls == []
    finally:
        blocker.rollback()
        blocker.close()
        store.close()


def test_dispatch_exact_pending_commands_preserves_claim_write_failure_as_retry(
    tmp_path: Path,
) -> None:
    store = _open(tmp_path)
    gateway = FakeGateway()
    service = _service(store, gateway, MutableClock())
    staged = _stage(service, tmp_path, symbols=("600000.SH",))
    command_ids = tuple(sorted(staged.staged_command_ids))
    store._conn.execute(  # noqa: SLF001 - fault injection at SQLite boundary
        """
        CREATE TRIGGER fail_exact_pending_claim
        BEFORE UPDATE OF state ON outbox_deliveries
        WHEN NEW.state = 'LEASED'
        BEGIN
            SELECT RAISE(ABORT, 'PRIVATE_TRIGGER_SENTINEL');
        END
        """
    )
    try:
        with pytest.raises(
            ExecutionServiceError, match="^SERVICE_EXACT_PENDING_WRITE_FAILED$"
        ) as error:
            service.dispatch_exact_pending_commands(command_ids=command_ids)
        _assert_detached(error.value)
        assert gateway.calls == []
        with store.transaction() as repo:
            delivery = repo.get_outbox_delivery(command_ids[0])
        assert delivery is not None
        assert delivery.state is OutboxDeliveryState.PENDING
        assert delivery.attempt_count == 0
    finally:
        store.close()
