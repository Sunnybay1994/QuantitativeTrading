import pytest

from quant.research.reconcile_s0 import decompose_returns


def test_return_decomposition_reconciles_exactly() -> None:
    result = decompose_returns(
        index_return=0.10,
        etf_price_return=0.095,
        etf_gross_return=0.115,
        etf_net_return=0.11,
    )
    assert result["price_tracking_gap"] == pytest.approx(-0.005)
    assert result["dividend_and_lot_contribution"] == pytest.approx(0.02)
    assert result["cost_drag"] == pytest.approx(-0.005)
    assert result["net_gap_to_index"] == pytest.approx(0.01)
    assert result["decomposition_residual"] == pytest.approx(0.0)
