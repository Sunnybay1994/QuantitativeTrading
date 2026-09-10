import pytest

from quant.data.align_etf_history import alignment_scale


def test_prepend_preserves_boundary_dividend_return_and_internal_ratios() -> None:
    scale = alignment_scale(previous_adjusted=200, previous_close=100,
                            next_adjusted=102, next_close=102, next_dividend=3)
    assert 102 / (200 * scale) - 1 == pytest.approx(0.05)
    assert (200 * scale) / (180 * scale) == pytest.approx(200 / 180)


def test_bad_anchor_does_not_publish_a_scale() -> None:
    with pytest.raises(ValueError):
        alignment_scale(previous_adjusted=0, previous_close=100,
                        next_adjusted=102, next_close=102, next_dividend=0)
