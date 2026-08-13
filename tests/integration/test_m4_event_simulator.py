"""Small cross-module M4-B6 fixture smoke test."""

from quant.backtest.event_simulator import simulate_order_plans


def test_public_entry_is_module_importable() -> None:
    assert callable(simulate_order_plans)
