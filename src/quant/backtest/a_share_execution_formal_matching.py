"""Compatibility shim for formal A-share matching."""

from quant.backtest.a_share_execution_formal_open import (
    AShareSessionExecutionTransition,
    build_formal_a_share_open_execution_states,
    resolve_formal_a_share_order_quantity_rule,
)
from quant.backtest.a_share_execution_formal_session import execute_formal_a_share_session

__all__ = [
    "AShareSessionExecutionTransition",
    "build_formal_a_share_open_execution_states",
    "execute_formal_a_share_session",
    "resolve_formal_a_share_order_quantity_rule",
]
