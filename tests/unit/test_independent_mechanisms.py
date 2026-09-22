import pytest

from quant.research.independent_mechanisms import turnover_breakdown


def test_deployment_diagnostic_preserves_original_turnover():
    full,ongoing=turnover_breakdown(1029017.9,996646.5,1000000,42)
    assert full==pytest.approx(3.0870537)
    assert ongoing==pytest.approx(.0971142)
    assert full>3  # The original gate must remain failed.


def test_invalid_turnover_rejected():
    with pytest.raises(ValueError):
        turnover_breakdown(100,200,100000,42)
