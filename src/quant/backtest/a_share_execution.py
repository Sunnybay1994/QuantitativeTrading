"""Pure A-share target-to-order and fee contracts for M3 G7D."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP
from fractions import Fraction
from typing import Literal, TypeAlias, cast

import polars as pl

from quant.domain import AShareBoard, ExecutionRejectReason, OrderSide, TargetWeightSchema
from quant.research.m3.contracts import AShareCostPeriod

_RULE_VERSION: Literal["sse_szse_limit_order_quantity_v1"] = (
    "sse_szse_limit_order_quantity_v1"
)
_CENT = Decimal("0.01")


@dataclass(frozen=True)
class AccountPosition:
    symbol: str
    quantity: int
    sellable_quantity: int
    unsettled_quantity: int
    mark_price: Decimal

    def __post_init__(self) -> None:
        if (
            type(self.symbol) is not str
            or not self.symbol.endswith((".SH", ".SZ"))
            or any(
                type(value) is not int or value < 0
                for value in (
                    self.quantity,
                    self.sellable_quantity,
                    self.unsettled_quantity,
                )
            )
            or self.sellable_quantity + self.unsettled_quantity != self.quantity
            or type(self.mark_price) is not Decimal
            or not self.mark_price.is_finite()
            or self.mark_price <= 0
        ):
            raise ValueError("account position invalid")


PositionBook: TypeAlias = tuple[AccountPosition, ...]


@dataclass(frozen=True)
class AShareFeeComponents:
    commission: Decimal
    stamp_tax: Decimal
    transfer_fee: Decimal

    def __post_init__(self) -> None:
        if any(
            type(value) is not Decimal or not value.is_finite() or value < 0
            for value in (self.commission, self.stamp_tax, self.transfer_fee)
        ):
            raise ValueError("A-share fees invalid")


@dataclass(frozen=True)
class AShareOrderQuantityRule:
    rule_version: Literal["sse_szse_limit_order_quantity_v1"]
    board: AShareBoard
    buy_min_quantity: int
    buy_increment: int
    sell_min_quantity: int
    sell_increment: int
    odd_lot_sell_policy: Literal[
        "MATCH_POSITION_REMAINDER", "FULL_BALANCE_BELOW_MIN"
    ]

    def __post_init__(self) -> None:
        if (
            self.rule_version != _RULE_VERSION
            or type(self.board) is not AShareBoard
            or any(
                type(value) is not int or value <= 0
                for value in (
                    self.buy_min_quantity,
                    self.buy_increment,
                    self.sell_min_quantity,
                    self.sell_increment,
                )
            )
            or self.odd_lot_sell_policy
            not in {"MATCH_POSITION_REMAINDER", "FULL_BALANCE_BELOW_MIN"}
        ):
            raise ValueError("A-share quantity rule invalid")


@dataclass(frozen=True)
class TargetOrderIntent:
    symbol: str
    side: OrderSide
    target_weight: Decimal
    target_notional: Decimal
    raw_target_quantity: int | None
    target_position_quantity: int | None
    requested_quantity: int | None
    quantity_rule: AShareOrderQuantityRule

    def __post_init__(self) -> None:
        quantities = (
            self.raw_target_quantity,
            self.target_position_quantity,
            self.requested_quantity,
        )
        if (
            type(self.symbol) is not str
            or type(self.side) is not OrderSide
            or any(
                type(value) is not Decimal or not value.is_finite() or value < 0
                for value in (self.target_weight, self.target_notional)
            )
            or any(value is not None and (type(value) is not int or value < 0) for value in quantities)
            or type(self.quantity_rule) is not AShareOrderQuantityRule
        ):
            raise ValueError("target order intent invalid")


@dataclass(frozen=True)
class ExecutionFill:
    symbol: str
    side: OrderSide
    quantity: int
    reference_open: Decimal
    execution_price: Decimal
    notional: Decimal
    fees: AShareFeeComponents
    slippage_cost: Decimal

    def __post_init__(self) -> None:
        if (
            type(self.side) is not OrderSide
            or type(self.quantity) is not int
            or self.quantity <= 0
            or any(
                type(value) is not Decimal or not value.is_finite() or value < 0
                for value in (
                    self.reference_open,
                    self.execution_price,
                    self.notional,
                    self.slippage_cost,
                )
            )
            or type(self.fees) is not AShareFeeComponents
        ):
            raise ValueError("execution fill invalid")


@dataclass(frozen=True)
class ExecutionRejection:
    symbol: str
    side: OrderSide
    reason: ExecutionRejectReason
    requested_quantity: int | None
    filled_quantity: int
    rejected_quantity: int | None
    rejected_notional: Decimal

    def __post_init__(self) -> None:
        if (
            type(self.side) is not OrderSide
            or type(self.reason) is not ExecutionRejectReason
            or type(self.filled_quantity) is not int
            or self.filled_quantity < 0
            or self.requested_quantity is not None
            and (type(self.requested_quantity) is not int or self.requested_quantity < 0)
            or self.rejected_quantity is not None
            and (type(self.rejected_quantity) is not int or self.rejected_quantity < 0)
            or self.requested_quantity is not None
            and self.rejected_quantity is not None
            and self.requested_quantity
            != self.filled_quantity + self.rejected_quantity
            or type(self.rejected_notional) is not Decimal
            or not self.rejected_notional.is_finite()
            or self.rejected_notional < 0
        ):
            raise ValueError("execution rejection invalid")


@dataclass(frozen=True)
class ExecutionBatch:
    cash: Decimal
    positions: PositionBook
    fills: tuple[ExecutionFill, ...]
    rejections: tuple[ExecutionRejection, ...]

    def __post_init__(self) -> None:
        if (
            type(self.cash) is not Decimal
            or not self.cash.is_finite()
            or self.cash < 0
            or any(type(item) is not AccountPosition for item in self.positions)
            or len({item.symbol for item in self.positions}) != len(self.positions)
            or any(type(item) is not ExecutionFill for item in self.fills)
            or any(type(item) is not ExecutionRejection for item in self.rejections)
        ):
            raise ValueError("execution batch invalid")


@dataclass(frozen=True)
class BuyAllocation:
    lambda_fraction: Fraction | None
    batch: ExecutionBatch

    def __post_init__(self) -> None:
        if (
            self.lambda_fraction is not None
            and (
                type(self.lambda_fraction) is not Fraction
                or not Fraction(0) <= self.lambda_fraction <= Fraction(1)
            )
            or type(self.batch) is not ExecutionBatch
        ):
            raise ValueError("buy allocation invalid")


def resolve_a_share_order_quantity_rule(
    *, symbol: str, date: dt.date
) -> AShareOrderQuantityRule:
    if type(symbol) is not str or type(date) is not dt.date:
        raise ValueError("A-share rule lookup invalid")
    prefix, suffix = symbol[:3], symbol[-3:]
    if len(symbol) != 9 or symbol[6] != ".":
        raise ValueError("A-share symbol invalid")
    if suffix == ".SH" and prefix in {"600", "601", "603", "605"}:
        board = AShareBoard.SSE_MAIN
    elif suffix == ".SH" and prefix in {"688", "689"}:
        if date < dt.date(2019, 7, 22):
            raise ValueError("STAR rule not effective")
        board = AShareBoard.SSE_STAR
    elif suffix == ".SZ" and prefix in {"000", "001", "002", "003"}:
        board = AShareBoard.SZSE_MAIN
    elif suffix == ".SZ" and prefix in {"300", "301"}:
        board = AShareBoard.SZSE_CHINEXT
    else:
        raise ValueError("unsupported A-share board")
    if board is AShareBoard.SSE_STAR:
        return AShareOrderQuantityRule(
            _RULE_VERSION, board, 200, 1, 200, 1, "FULL_BALANCE_BELOW_MIN"
        )
    return AShareOrderQuantityRule(
        _RULE_VERSION, board, 100, 100, 100, 100, "MATCH_POSITION_REMAINDER"
    )


def largest_valid_buy_quantity(
    *, requested_quantity: int, rule: AShareOrderQuantityRule
) -> int:
    _validate_quantity(requested_quantity)
    if type(rule) is not AShareOrderQuantityRule:
        raise ValueError("quantity rule invalid")
    if requested_quantity < rule.buy_min_quantity:
        return 0
    if rule.board is AShareBoard.SSE_STAR:
        return requested_quantity
    return requested_quantity - requested_quantity % rule.buy_increment


def largest_valid_sell_quantity(
    *, requested_quantity: int, position_quantity: int, rule: AShareOrderQuantityRule
) -> int:
    _validate_quantity(requested_quantity)
    _validate_quantity(position_quantity)
    if type(rule) is not AShareOrderQuantityRule:
        raise ValueError("sell quantity invalid")
    capped_quantity = min(requested_quantity, position_quantity)
    if capped_quantity == position_quantity:
        return capped_quantity
    if rule.board is AShareBoard.SSE_STAR:
        return capped_quantity if capped_quantity >= rule.sell_min_quantity else 0
    round_lot = capped_quantity - capped_quantity % rule.sell_increment
    remainder = position_quantity % rule.sell_increment
    odd_lot = 0
    if remainder and capped_quantity >= remainder:
        odd_lot = capped_quantity - (capped_quantity - remainder) % rule.sell_increment
    return max(round_lot, odd_lot)


def compute_a_share_fee_components(
    *, notional: Decimal, side: OrderSide, cost_period: AShareCostPeriod
) -> AShareFeeComponents:
    if (
        type(notional) is not Decimal
        or not notional.is_finite()
        or notional < 0
        or type(side) is not OrderSide
        or type(cost_period) is not AShareCostPeriod
    ):
        raise ValueError("fee inputs invalid")
    commission = max(
        notional * cost_period.commission_rate, cost_period.commission_min
    ).quantize(_CENT, rounding=ROUND_HALF_UP)
    stamp = (
        notional * cost_period.stamp_tax_sell
        if side is OrderSide.SELL
        else Decimal("0")
    ).quantize(_CENT, rounding=ROUND_HALF_UP)
    transfer = (notional * cost_period.transfer_fee).quantize(
        _CENT, rounding=ROUND_HALF_UP
    )
    return AShareFeeComponents(commission, stamp, transfer)


def build_target_order_intents(
    *,
    date: dt.date,
    targets: pl.DataFrame,
    positions: PositionBook,
    open_states: pl.DataFrame,
    pre_trade_equity: Decimal,
) -> tuple[TargetOrderIntent, ...]:
    if (
        type(date) is not dt.date
        or type(pre_trade_equity) is not Decimal
        or not pre_trade_equity.is_finite()
        or pre_trade_equity <= 0
    ):
        raise ValueError("target intent inputs invalid")
    clean = TargetWeightSchema.validate(targets)
    if clean["as_of"].n_unique() != 1 or clean["symbol"].n_unique() != clean.height:
        raise ValueError("target intent target domain invalid")
    _validate_open_states(open_states, date)
    if len({item.symbol for item in positions}) != len(positions):
        raise ValueError("position book duplicate symbols")
    by_position = {item.symbol: item for item in positions}
    by_open = {cast(str, row["symbol"]): row for row in open_states.iter_rows(named=True)}
    intents: list[TargetOrderIntent] = []
    for row in clean.sort("symbol").iter_rows(named=True):
        symbol = cast(str, row["symbol"])
        if symbol not in by_open:
            raise ValueError("target open state missing")
        rule = resolve_a_share_order_quantity_rule(symbol=symbol, date=date)
        position = by_position.get(symbol)
        current_quantity = 0 if position is None else position.quantity
        weight = Decimal(str(row["weight"]))
        target_notional = weight * pre_trade_equity
        state = by_open[symbol]
        open_value = state["open"]
        if open_value is None or not cast(bool, state["has_open"]):
            current_value = (
                Decimal("0")
                if position is None
                else Decimal(position.quantity) * position.mark_price
            )
            if target_notional == current_value:
                continue
            side = OrderSide.BUY if target_notional > current_value else OrderSide.SELL
            intents.append(
                TargetOrderIntent(
                    symbol, side, weight, target_notional, None, None, None, rule
                )
            )
            continue
        open_price = Decimal(str(open_value))
        if open_price <= 0:
            raise ValueError("target open price invalid")
        raw = int((target_notional / open_price).to_integral_value(rounding=ROUND_FLOOR))
        target_quantity = (
            0 if weight == 0 else largest_valid_buy_quantity(requested_quantity=raw, rule=rule)
        )
        lot_constrained_buy = (
            weight > 0 and raw > 0 and target_quantity == 0 and current_quantity == 0
        )
        if target_quantity == current_quantity and not lot_constrained_buy:
            continue
        side = (
            OrderSide.BUY
            if target_quantity > current_quantity or lot_constrained_buy
            else OrderSide.SELL
        )
        intents.append(
            TargetOrderIntent(
                symbol=symbol,
                side=side,
                target_weight=weight,
                target_notional=target_notional,
                raw_target_quantity=raw,
                target_position_quantity=target_quantity,
                requested_quantity=abs(target_quantity - current_quantity),
                quantity_rule=rule,
            )
        )
    return tuple(intents)


def _validate_quantity(value: int) -> None:
    if type(value) is not int or value < 0:
        raise ValueError("quantity invalid")


def _validate_open_states(frame: pl.DataFrame, date: dt.date) -> None:
    required = [
        "date", "symbol", "open", "has_open", "full_day_suspended",
        "partial_open_status", "has_price_limit", "up_limit", "down_limit",
        "buy_allowed", "sell_allowed", "reason",
    ]
    if (
        set(frame.columns) != set(required)
        or frame["symbol"].n_unique() != frame.height
        or any(day != date for day in frame["date"])
    ):
        raise ValueError("open execution states invalid")


__all__ = [
    "AShareBoard", "AShareFeeComponents", "AShareOrderQuantityRule",
    "AccountPosition", "BuyAllocation", "ExecutionBatch", "ExecutionFill",
    "ExecutionRejectReason", "ExecutionRejection", "PositionBook",
    "TargetOrderIntent", "build_target_order_intents",
    "compute_a_share_fee_components", "largest_valid_buy_quantity",
    "largest_valid_sell_quantity", "resolve_a_share_order_quantity_rule",
]
