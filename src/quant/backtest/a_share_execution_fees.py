"""A-share execution fee components."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from quant.domain import OrderSide
from quant.research.m3.contracts import AShareCostPeriod

from quant.backtest.a_share_execution_contracts import AShareFeeComponents

_CENT = Decimal("0.01")


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


def _fee_total(fees: AShareFeeComponents) -> Decimal:
    return fees.commission + fees.stamp_tax + fees.transfer_fee
