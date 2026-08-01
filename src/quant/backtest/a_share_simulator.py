"""Deterministic single-scenario A-share account replay for M3 G7E."""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import cast

import polars as pl

from quant.backtest.a_share_execution import (
    AccountPosition,
    ExecutionRejection,
    PositionBook,
    allocate_buy_lots,
    build_open_execution_states,
    build_target_order_intents,
    execute_sell_intents,
)
from quant.backtest.corporate_actions import (
    EntitlementPosition,
    EntitlementPosting,
    capture_record_close_entitlements,
    mark_full_day_event_from_factor,
    recognize_ex_date_entitlements,
    settle_due_entitlements,
)
from quant.domain import (
    AShareCorporateActionPostingSchema,
    AShareDailyDiagnosticsSchema,
    AShareEntitlementSnapshotSchema,
    AShareSimulationNavSchema,
    AShareSimulationPositionSchema,
    AShareSimulationRejectionSchema,
    AShareSimulationTradeSchema,
    EntitlementLegState,
    EntitlementPostingType,
)
from quant.research.m3.contracts import AShareCostPeriod
from quant.research.m3.development_example import (
    VerifiedDevelopmentExampleAShareMarketFacts,
    VerifiedDevelopmentExampleBacktestPlanArtifact,
    VerifiedDevelopmentExampleTargetArtifact,
)


@dataclass(frozen=True)
class AShareSimulationResult:
    multiplier: Decimal
    nav: pl.DataFrame
    trades: pl.DataFrame
    positions: pl.DataFrame
    rejections: pl.DataFrame
    corporate_action_postings: pl.DataFrame
    daily_diagnostics: pl.DataFrame
    entitlements: pl.DataFrame

    def __post_init__(self) -> None:
        frames = (
            self.nav,
            self.trades,
            self.positions,
            self.rejections,
            self.corporate_action_postings,
            self.daily_diagnostics,
            self.entitlements,
        )
        if (
            type(self.multiplier) is not Decimal
            or not self.multiplier.is_finite()
            or self.multiplier <= 0
            or any(not isinstance(frame, pl.DataFrame) for frame in frames)
        ):
            raise ValueError("A-share simulation result invalid")


def simulate_a_share_scenario(
    *,
    target: VerifiedDevelopmentExampleTargetArtifact,
    plan: VerifiedDevelopmentExampleBacktestPlanArtifact,
    facts: VerifiedDevelopmentExampleAShareMarketFacts,
    cost_periods: tuple[AShareCostPeriod, ...],
    multiplier: Decimal,
    initial_cash: Decimal,
) -> AShareSimulationResult:
    """Replay one verified development scenario without I/O or Qlib."""
    _validate_inputs(target, plan, facts, cost_periods, multiplier, initial_cash)
    sessions = plan.manifest.window.execution_dates
    sh_sessions = tuple(
        cast(
            list[dt.date],
            facts.calendar.filter(
                (pl.col("market") == "SH") & pl.col("is_open")
            ).sort("date")["date"].to_list(),
        )
    )
    cash = initial_cash
    positions: PositionBook = ()
    entitlement_positions: tuple[EntitlementPosition, ...] = ()
    posting_rows: list[dict[str, object]] = []
    nav_rows: list[dict[str, object]] = []
    trade_rows: list[dict[str, object]] = []
    position_rows: list[dict[str, object]] = []
    rejection_rows: list[dict[str, object]] = []
    diagnostic_rows: list[dict[str, object]] = []
    entitlement_rows: list[dict[str, object]] = []
    cumulative_commission = Decimal(0)
    cumulative_stamp = Decimal(0)
    cumulative_transfer = Decimal(0)
    cumulative_slippage = Decimal(0)
    previous_equity = initial_cash

    for date in sessions:
        positions = tuple(
            replace(
                item,
                sellable_quantity=item.quantity,
                unsettled_quantity=0,
            )
            for item in positions
            if item.quantity > 0
        )
        recognized = recognize_ex_date_entitlements(
            date=date, positions=entitlement_positions
        )
        entitlement_positions = recognized.positions
        posting_rows.extend(_posting_rows(recognized.postings))
        settled = settle_due_entitlements(date=date, positions=entitlement_positions)
        entitlement_positions = settled.positions
        posting_rows.extend(_posting_rows(settled.postings))
        cash += settled.cash_delta
        positions = _apply_settled_stock(
            positions=positions,
            settled=settled.settled_stock,
            date=date,
            facts=facts,
        )

        target_batch = plan.scheduled_targets.filter(pl.col("execution_date") == date)
        target_symbols = set(cast(list[str], target_batch["symbol"].to_list()))
        position_symbols = {item.symbol for item in positions if item.quantity > 0}
        symbols = tuple(sorted(target_symbols | position_symbols))
        open_states = build_open_execution_states(
            facts=facts, date=date, symbols=symbols
        )
        positions = _pretrade_marks(
            positions=positions,
            date=date,
            facts=facts,
            open_states=open_states,
        )
        cash_receivable, stock_receivable_value = _receivables(
            entitlement_positions, positions
        )
        pre_trade_equity = (
            cash
            + sum(
                (Decimal(item.quantity) * item.mark_price for item in positions),
                Decimal(0),
            )
            + cash_receivable
            + stock_receivable_value
        )
        complete_targets = _complete_targets(target_batch, positions)
        intents = build_target_order_intents(
            date=date,
            targets=complete_targets,
            positions=positions,
            open_states=open_states,
            pre_trade_equity=pre_trade_equity,
        )
        period = _cost_period(date, cost_periods)
        sells = tuple(intent for intent in intents if intent.side.value == "SELL")
        buys = tuple(intent for intent in intents if intent.side.value == "BUY")
        sold = execute_sell_intents(
            intents=sells,
            open_states=open_states,
            positions=positions,
            cash=cash,
            cost_period=period,
            price_tick=Decimal("0.01"),
        )
        allocation = allocate_buy_lots(
            intents=buys,
            open_states=open_states,
            positions=sold.positions,
            cash=sold.cash,
            cost_period=period,
            price_tick=Decimal("0.01"),
        )
        batch = allocation.batch
        cash = batch.cash
        positions = _close_marks(
            positions=batch.positions,
            date=date,
            facts=facts,
        )
        fills = sold.fills + batch.fills
        rejections = sold.rejections + batch.rejections
        for fill in fills:
            cumulative_commission += fill.fees.commission
            cumulative_stamp += fill.fees.stamp_tax
            cumulative_transfer += fill.fees.transfer_fee
            cumulative_slippage += fill.slippage_cost
            trade_rows.append({
                "date": date,
                "symbol": fill.symbol,
                "side": fill.side.value,
                "quantity": fill.quantity,
                "reference_open": float(fill.reference_open),
                "execution_price": float(fill.execution_price),
                "notional": float(fill.notional),
                "commission": float(fill.fees.commission),
                "stamp_tax": float(fill.fees.stamp_tax),
                "transfer_fee": float(fill.fees.transfer_fee),
                "total_fee": float(
                    fill.fees.commission
                    + fill.fees.stamp_tax
                    + fill.fees.transfer_fee
                ),
                "slippage_cost": float(fill.slippage_cost),
            })
        rejection_rows.extend(_rejection_rows(date, rejections))

        before_ids = {item.event_id for item in entitlement_positions}
        entitlement_positions = capture_record_close_entitlements(
            date=date,
            positions=entitlement_positions,
            total_quantities={item.symbol: item.quantity for item in positions},
            corporate_actions=facts.corporate_actions,
            sh_sessions=sh_sessions,
            terminal_valuation_date=plan.manifest.window.terminal_valuation_date,
        )
        captured = tuple(
            item for item in entitlement_positions if item.event_id not in before_ids
        )
        capture_postings = tuple(_capture_posting(date, item) for item in captured)
        posting_rows.extend(_posting_rows(capture_postings))
        cash_receivable, stock_receivable_value = _receivables(
            entitlement_positions, positions
        )
        market_value = sum(
            (Decimal(item.quantity) * item.mark_price for item in positions),
            Decimal(0),
        )
        equity = cash + market_value + cash_receivable + stock_receivable_value
        nav_rows.append({
            "date": date,
            "pre_trade_equity": float(pre_trade_equity),
            "cash": float(cash),
            "market_value": float(market_value),
            "cash_receivable": float(cash_receivable),
            "stock_receivable_value": float(stock_receivable_value),
            "equity": float(equity),
            "unit_nav": float(equity / initial_cash),
            "daily_return": float(equity / previous_equity - 1),
            "cumulative_commission": float(cumulative_commission),
            "cumulative_stamp_tax": float(cumulative_stamp),
            "cumulative_transfer_fee": float(cumulative_transfer),
            "cumulative_slippage_cost": float(cumulative_slippage),
        })
        previous_equity = equity
        target_by_symbol = {
            cast(str, row["symbol"]): cast(float, row["weight"])
            for row in complete_targets.iter_rows(named=True)
        }
        intent_by_symbol = {item.symbol: item for item in intents}
        for item in sorted(positions, key=lambda value: value.symbol):
            if item.quantity <= 0:
                continue
            intent = intent_by_symbol.get(item.symbol)
            target_quantity = (
                item.quantity
                if intent is None
                else intent.target_position_quantity
            )
            weight = target_by_symbol.get(item.symbol, 0.0)
            position_rows.append({
                "date": date,
                "symbol": item.symbol,
                "quantity": item.quantity,
                "sellable_quantity": item.sellable_quantity,
                "unsettled_quantity": item.unsettled_quantity,
                "mark_price": float(item.mark_price),
                "market_value": float(Decimal(item.quantity) * item.mark_price),
                "target_weight": weight,
                "target_quantity": target_quantity,
                "pending_exit": bool(weight == 0 and item.quantity > 0),
            })
        entitlement_rows.extend(
            _entitlement_rows(date, entitlement_positions, positions)
        )
        gross_notional = sum((fill.notional for fill in fills), Decimal(0))
        buy_notional = sum(
            (fill.notional for fill in fills if fill.side.value == "BUY"), Decimal(0)
        )
        sell_notional = gross_notional - buy_notional
        diagnostic_rows.append({
            "date": date,
            "n_target_symbols": len(target_symbols),
            "n_position_symbols": len(position_symbols),
            "n_order_intents": len(intents),
            "n_trades": len(fills),
            "n_rejections": len(rejections),
            "pre_trade_equity": float(pre_trade_equity),
            "gross_turnover": float(gross_notional / pre_trade_equity),
            "one_way_turnover": float(
                max(buy_notional, sell_notional) / pre_trade_equity
            ),
            "buy_allocation_lambda": (
                None
                if allocation.lambda_fraction is None
                else float(allocation.lambda_fraction)
            ),
            "cash_after": float(cash),
        })

    return AShareSimulationResult(
        multiplier=multiplier,
        nav=AShareSimulationNavSchema.validate(
            _frame(nav_rows, _NAV_SCHEMA, ("date",))
        ),
        trades=AShareSimulationTradeSchema.validate(
            _frame(trade_rows, _TRADE_SCHEMA, ("date", "symbol", "side"))
        ),
        positions=AShareSimulationPositionSchema.validate(
            _frame(position_rows, _POSITION_SCHEMA, ("date", "symbol"))
        ),
        rejections=AShareSimulationRejectionSchema.validate(_frame(
            rejection_rows, _REJECTION_SCHEMA, ("date", "symbol", "side", "reason")
        )),
        corporate_action_postings=AShareCorporateActionPostingSchema.validate(_frame(
            posting_rows, _POSTING_SCHEMA, ("date", "event_id", "posting_type")
        )),
        daily_diagnostics=AShareDailyDiagnosticsSchema.validate(
            _frame(diagnostic_rows, _DIAGNOSTIC_SCHEMA, ("date",))
        ),
        entitlements=AShareEntitlementSnapshotSchema.validate(
            _frame(entitlement_rows, _ENTITLEMENT_SCHEMA, ("date", "event_id"))
        ),
    )


def _validate_inputs(
    target: object,
    plan: object,
    facts: object,
    periods: object,
    multiplier: object,
    initial_cash: object,
) -> None:
    if (
        type(target) is not VerifiedDevelopmentExampleTargetArtifact
        or type(plan) is not VerifiedDevelopmentExampleBacktestPlanArtifact
        or type(facts) is not VerifiedDevelopmentExampleAShareMarketFacts
        or type(periods) is not tuple
        or not periods
        or any(type(period) is not AShareCostPeriod for period in periods)
        or type(multiplier) is not Decimal
        or not multiplier.is_finite()
        or multiplier <= 0
        or type(initial_cash) is not Decimal
        or not initial_cash.is_finite()
        or initial_cash <= 0
    ):
        raise ValueError("A-share simulation inputs invalid")
    assert isinstance(target, VerifiedDevelopmentExampleTargetArtifact)
    assert isinstance(plan, VerifiedDevelopmentExampleBacktestPlanArtifact)
    assert isinstance(facts, VerifiedDevelopmentExampleAShareMarketFacts)
    if (
        target.example_id != plan.example_id
        or target.example_id != facts.example_id
        or plan.manifest.target_manifest_sha256 != target.manifest_sha256
        or plan.manifest.g1_release_id != facts.identity.g1_release_id
        or plan.manifest.g1_release_manifest_sha256
        != facts.identity.g1_release_manifest_sha256
    ):
        raise ValueError("A-share simulation identity mismatch")
    previous_end: dt.date | None = None
    for index, period in enumerate(cast(tuple[AShareCostPeriod, ...], periods)):
        if index and (
            previous_end is None
            or period.effective_from != previous_end + dt.timedelta(days=1)
        ):
            raise ValueError("A-share cost periods not contiguous")
        if (period.effective_to is None) != (index == len(periods) - 1):
            raise ValueError("A-share cost periods not closed")
        previous_end = period.effective_to


def _cost_period(
    date: dt.date, periods: tuple[AShareCostPeriod, ...]
) -> AShareCostPeriod:
    matches = tuple(
        period
        for period in periods
        if period.effective_from <= date
        and (period.effective_to is None or date <= period.effective_to)
    )
    if len(matches) != 1:
        raise ValueError("A-share cost period missing")
    return matches[0]


def _complete_targets(frame: pl.DataFrame, positions: PositionBook) -> pl.DataFrame:
    targets = frame.drop("execution_date")
    present = set(cast(list[str], targets["symbol"].to_list()))
    missing = sorted(
        item.symbol for item in positions if item.quantity > 0 and item.symbol not in present
    )
    if not missing:
        return targets.sort("symbol")
    first = targets.row(0, named=True)
    additions = pl.DataFrame([
        {
            "as_of": first["as_of"],
            "strategy": first["strategy"],
            "strategy_version": first["strategy_version"],
            "symbol": symbol,
            "weight": 0.0,
        }
        for symbol in missing
    ]).with_columns(pl.col("as_of").cast(pl.Date))
    return pl.concat([targets, additions], how="vertical").sort("symbol")


def _pretrade_marks(
    *,
    positions: PositionBook,
    date: dt.date,
    facts: VerifiedDevelopmentExampleAShareMarketFacts,
    open_states: pl.DataFrame,
) -> PositionBook:
    states = {cast(str, row["symbol"]): row for row in open_states.iter_rows(named=True)}
    result: list[AccountPosition] = []
    for item in positions:
        state = states[item.symbol]
        if state["has_open"]:
            mark = Decimal(str(state["open"]))
        elif state["full_day_suspended"]:
            reconciliation = facts.corporate_action_reconciliation.filter(
                (pl.col("symbol") == item.symbol)
                & (pl.col("effective_date") == date)
            )
            mark = item.mark_price
            if reconciliation.height == 1:
                mark = mark_full_day_event_from_factor(
                    previous_mark=mark,
                    actual_factor_ratio=Decimal(
                        str(reconciliation.item(0, "actual_factor_ratio"))
                    ),
                )
            elif reconciliation.height > 1:
                raise ValueError("corporate action reconciliation not unique")
        else:
            raise ValueError("held position opening fact missing")
        result.append(replace(item, mark_price=mark))
    return tuple(result)


def _close_marks(
    *,
    positions: PositionBook,
    date: dt.date,
    facts: VerifiedDevelopmentExampleAShareMarketFacts,
) -> PositionBook:
    result: list[AccountPosition] = []
    for item in positions:
        if item.quantity <= 0:
            continue
        bars = facts.bars.filter(
            (pl.col("symbol") == item.symbol) & (pl.col("trade_date") == date)
        )
        suspensions = facts.suspensions.filter(
            (pl.col("symbol") == item.symbol)
            & (pl.col("trade_date") == date)
            & (pl.col("suspension_scope") == "FULL_DAY")
        )
        if bars.height == 1:
            mark = Decimal(str(bars.item(0, "close")))
        elif suspensions.height == 1:
            mark = item.mark_price
        else:
            raise ValueError("held position closing fact missing")
        result.append(replace(item, mark_price=mark))
    return tuple(result)


def _apply_settled_stock(
    *,
    positions: PositionBook,
    settled: tuple[tuple[str, int], ...],
    date: dt.date,
    facts: VerifiedDevelopmentExampleAShareMarketFacts,
) -> PositionBook:
    by_symbol = {item.symbol: item for item in positions}
    for symbol, quantity in settled:
        current = by_symbol.get(symbol)
        if current is None:
            bars = facts.bars.filter(
                (pl.col("symbol") == symbol) & (pl.col("trade_date") == date)
            )
            if bars.height != 1:
                raise ValueError("settled stock mark missing")
            by_symbol[symbol] = AccountPosition(
                symbol=symbol,
                quantity=quantity,
                sellable_quantity=quantity,
                unsettled_quantity=0,
                mark_price=Decimal(str(bars.item(0, "open"))),
            )
        else:
            by_symbol[symbol] = replace(
                current,
                quantity=current.quantity + quantity,
                sellable_quantity=current.sellable_quantity + quantity,
            )
    return tuple(sorted(by_symbol.values(), key=lambda item: item.symbol))


def _receivables(
    entitlements: tuple[EntitlementPosition, ...], positions: PositionBook
) -> tuple[Decimal, Decimal]:
    marks = {item.symbol: item.mark_price for item in positions}
    cash = sum(
        (
            item.cash_entitlement_gross
            for item in entitlements
            if item.cash_state is EntitlementLegState.RECOGNIZED
        ),
        Decimal(0),
    )
    stock = sum(
        (
            Decimal(item.stock_entitlement) * marks[item.symbol]
            for item in entitlements
            if item.stock_state is EntitlementLegState.RECOGNIZED
        ),
        Decimal(0),
    )
    return cash, stock


def _capture_posting(date: dt.date, item: EntitlementPosition) -> EntitlementPosting:
    return EntitlementPosting(
        date=date,
        event_id=item.event_id,
        symbol=item.symbol,
        posting_type=EntitlementPostingType.CAPTURE,
        cash_amount=Decimal(0),
        stock_quantity=item.record_quantity,
        cash_rounding_delta=Decimal(0),
        cash_state_before=EntitlementLegState.ABSENT,
        cash_state_after=item.cash_state,
        stock_state_before=EntitlementLegState.ABSENT,
        stock_state_after=item.stock_state,
    )


def _posting_rows(postings: tuple[EntitlementPosting, ...]) -> list[dict[str, object]]:
    return [
        {
            "date": item.date,
            "event_id": item.event_id,
            "symbol": item.symbol,
            "posting_type": item.posting_type.value,
            "cash_amount": float(item.cash_amount),
            "stock_quantity": item.stock_quantity,
            "cash_rounding_delta": float(item.cash_rounding_delta),
            "cash_state_before": item.cash_state_before.value,
            "cash_state_after": item.cash_state_after.value,
            "stock_state_before": item.stock_state_before.value,
            "stock_state_after": item.stock_state_after.value,
        }
        for item in postings
    ]


def _rejection_rows(
    date: dt.date, rejections: tuple[ExecutionRejection, ...]
) -> list[dict[str, object]]:
    return [
        {
            "date": date,
            "symbol": item.symbol,
            "side": item.side.value,
            "reason": item.reason.value,
            "requested_quantity": item.requested_quantity,
            "filled_quantity": item.filled_quantity,
            "rejected_quantity": item.rejected_quantity,
            "rejected_notional": float(item.rejected_notional),
        }
        for item in rejections
    ]


def _entitlement_rows(
    date: dt.date,
    entitlements: tuple[EntitlementPosition, ...],
    positions: PositionBook,
) -> list[dict[str, object]]:
    marks = {item.symbol: item.mark_price for item in positions}
    rows: list[dict[str, object]] = []
    for item in entitlements:
        if (
            item.cash_state in {EntitlementLegState.SETTLED, EntitlementLegState.NOT_APPLICABLE}
            and item.stock_state
            in {EntitlementLegState.SETTLED, EntitlementLegState.NOT_APPLICABLE}
        ):
            continue
        cash_receivable = (
            item.cash_entitlement_gross
            if item.cash_state is EntitlementLegState.RECOGNIZED
            else Decimal(0)
        )
        stock_receivable = (
            item.stock_entitlement
            if item.stock_state is EntitlementLegState.RECOGNIZED
            else 0
        )
        rows.append({
            "date": date,
            "event_id": item.event_id,
            "symbol": item.symbol,
            "record_quantity": item.record_quantity,
            "cash_entitlement_gross": float(item.cash_entitlement_gross),
            "stock_entitlement": item.stock_entitlement,
            "cash_state": item.cash_state.value,
            "stock_state": item.stock_state.value,
            "cash_receivable": float(cash_receivable),
            "stock_receivable": stock_receivable,
            "stock_receivable_value": float(
                Decimal(stock_receivable) * marks.get(item.symbol, Decimal(0))
            ),
        })
    return rows


def _frame(
    rows: list[dict[str, object]],
    schema: Mapping[str, pl.DataType | type[pl.DataType]],
    sort_by: tuple[str, ...],
) -> pl.DataFrame:
    frame = pl.DataFrame(rows, schema=schema)
    return frame.sort(*sort_by) if frame.height else frame


_NAV_SCHEMA = {
    "date": pl.Date, "pre_trade_equity": pl.Float64, "cash": pl.Float64,
    "market_value": pl.Float64, "cash_receivable": pl.Float64,
    "stock_receivable_value": pl.Float64, "equity": pl.Float64,
    "unit_nav": pl.Float64, "daily_return": pl.Float64,
    "cumulative_commission": pl.Float64, "cumulative_stamp_tax": pl.Float64,
    "cumulative_transfer_fee": pl.Float64, "cumulative_slippage_cost": pl.Float64,
}
_TRADE_SCHEMA = {
    "date": pl.Date, "symbol": pl.Utf8, "side": pl.Utf8, "quantity": pl.Int64,
    "reference_open": pl.Float64, "execution_price": pl.Float64,
    "notional": pl.Float64, "commission": pl.Float64, "stamp_tax": pl.Float64,
    "transfer_fee": pl.Float64, "total_fee": pl.Float64,
    "slippage_cost": pl.Float64,
}
_POSITION_SCHEMA = {
    "date": pl.Date, "symbol": pl.Utf8, "quantity": pl.Int64,
    "sellable_quantity": pl.Int64, "unsettled_quantity": pl.Int64,
    "mark_price": pl.Float64, "market_value": pl.Float64,
    "target_weight": pl.Float64, "target_quantity": pl.Int64,
    "pending_exit": pl.Boolean,
}
_REJECTION_SCHEMA = {
    "date": pl.Date, "symbol": pl.Utf8, "side": pl.Utf8, "reason": pl.Utf8,
    "requested_quantity": pl.Int64, "filled_quantity": pl.Int64,
    "rejected_quantity": pl.Int64, "rejected_notional": pl.Float64,
}
_POSTING_SCHEMA = {
    "date": pl.Date, "event_id": pl.Utf8, "symbol": pl.Utf8,
    "posting_type": pl.Utf8, "cash_amount": pl.Float64,
    "stock_quantity": pl.Int64, "cash_rounding_delta": pl.Float64,
    "cash_state_before": pl.Utf8, "cash_state_after": pl.Utf8,
    "stock_state_before": pl.Utf8, "stock_state_after": pl.Utf8,
}
_DIAGNOSTIC_SCHEMA = {
    "date": pl.Date, "n_target_symbols": pl.Int64, "n_position_symbols": pl.Int64,
    "n_order_intents": pl.Int64, "n_trades": pl.Int64, "n_rejections": pl.Int64,
    "pre_trade_equity": pl.Float64, "gross_turnover": pl.Float64,
    "one_way_turnover": pl.Float64, "buy_allocation_lambda": pl.Float64,
    "cash_after": pl.Float64,
}
_ENTITLEMENT_SCHEMA = {
    "date": pl.Date, "event_id": pl.Utf8, "symbol": pl.Utf8,
    "record_quantity": pl.Int64, "cash_entitlement_gross": pl.Float64,
    "stock_entitlement": pl.Int64, "cash_state": pl.Utf8,
    "stock_state": pl.Utf8, "cash_receivable": pl.Float64,
    "stock_receivable": pl.Int64, "stock_receivable_value": pl.Float64,
}

__all__ = ["AShareSimulationResult", "simulate_a_share_scenario"]
