import datetime as dt

import pytest

from quant.backtest import AShareCostModel, DailyMarketState, execution_reject_reason
from quant.domain.enums import ExecutionRejectReason, OrderSide


def test_a_share_costs_apply_transfer_fee_both_sides_and_stamp_on_sell() -> None:
    costs = AShareCostModel(
        commission_rate=0.00025,
        commission_min=5.0,
        stamp_tax_sell=0.0005,
        transfer_fee=0.00001,
        slippage=0.001,
        effective_from=dt.date(2023, 8, 28),
    )
    assert costs.fee(100_000.0, dt.date(2026, 1, 2), "BUY") == pytest.approx(26.0)
    assert costs.fee(100_000.0, dt.date(2026, 1, 2), "SELL") == pytest.approx(76.0)


@pytest.mark.parametrize(
    ("side", "state", "reason"),
    [
        (OrderSide.BUY, DailyMarketState(suspended=True), ExecutionRejectReason.SUSPENDED),
        (
            OrderSide.BUY,
            DailyMarketState(at_upper_limit=True),
            ExecutionRejectReason.BUY_AT_UPPER_LIMIT,
        ),
        (
            OrderSide.SELL,
            DailyMarketState(at_lower_limit=True),
            ExecutionRejectReason.SELL_AT_LOWER_LIMIT,
        ),
    ],
)
def test_market_state_rejects_unfillable_orders(
    side: OrderSide,
    state: DailyMarketState,
    reason: ExecutionRejectReason,
) -> None:
    assert execution_reject_reason(
        side=side,
        quantity=100,
        settled_quantity=100,
        state=state,
        enforce_t_plus_one=True,
    ) is reason


def test_t_plus_one_uses_settled_quantity_not_total_position() -> None:
    reason = execution_reject_reason(
        side=OrderSide.SELL,
        quantity=200,
        settled_quantity=100,
        state=DailyMarketState(),
        enforce_t_plus_one=True,
    )
    assert reason is ExecutionRejectReason.T_PLUS_ONE
    assert execution_reject_reason(
        side=OrderSide.SELL,
        quantity=200,
        settled_quantity=100,
        state=DailyMarketState(),
        enforce_t_plus_one=False,
    ) is None
