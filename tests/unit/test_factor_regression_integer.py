import polars as pl
import pytest

from quant.factors.expressions import evaluate_expressions


@pytest.mark.parametrize("operator", ["ts_slope", "ts_resi", "ts_rsquare"])
def test_regression_on_integer_indicator_preserves_groups_and_nulls(operator):
    panel = pl.DataFrame({
        "symbol": ["a"] * 4 + ["b"] * 4,
        "trade_date": [1, 2, 3, 4] * 2,
        "close": [1., 2., 1., 3., 2., 1., 3., None],
    })
    result = evaluate_expressions(panel, {
        "value": f"{operator}(where(close > 1, 1, 0), 3)",
    })["value"].to_list()
    expected = {
        "ts_slope": [0., 0., 0.],
        "ts_resi": [-1 / 3, 1 / 3, 1 / 3],
        "ts_rsquare": [0., 0., 0.],
    }[operator]
    assert [result[i] for i in (0, 1, 4, 5, 7)] == [None] * 5
    assert [result[i] for i in (2, 3, 6)] == pytest.approx(expected)
