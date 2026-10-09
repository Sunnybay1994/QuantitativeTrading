"""Shared A-share execution datatypes."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from typing import Literal, TypeAlias

from quant.domain import AShareBoard, ExecutionRejectReason, OrderSide
from quant.research.m3.contracts import AShareCostPeriod

_RULE_VERSION: Literal["sse_szse_limit_order_quantity_v1"] = (
    "sse_szse_limit_order_quantity_v1"
)


class AShareExecutionError(ValueError):
    """Stable fail-closed error for formal A-share execution projections."""

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

