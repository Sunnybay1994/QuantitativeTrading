import numpy as np
import pandas as pd
import polars as pl

from quant.factors.expressions import evaluate_expressions, required_history


def test_window_product_preserves_zero_sign_null_and_symbol_boundaries():
    values = [2., -3., 0., 4., None, -2., -4., 3.]
    panel = pl.DataFrame({"symbol": ["a"] * 8 + ["b"] * 8,
                          "trade_date": list(range(8)) * 2, "x": values + values[::-1]})
    actual = evaluate_expressions(panel, {"p": "ts_product(x, 3)"})["p"].to_numpy()
    expected = np.concatenate([
        pd.Series(v).rolling(3).apply(np.prod, raw=True).to_numpy()
        for v in (values, values[::-1])
    ])
    np.testing.assert_allclose(actual, expected, equal_nan=True)
    assert required_history("ts_product(delay(x, 2), 3)") == 4


def test_linear_decay_handles_integer_signals_with_missing_values():
    panel = pl.DataFrame({"symbol": ["a"] * 4 + ["b"] * 4,
                          "trade_date": list(range(4)) * 2,
                          "x": [1, 0, 1, 0, 0, None, 1, 1]})
    actual = evaluate_expressions(panel, {"d": "decay_linear(x, 2)"})["d"].to_numpy()
    np.testing.assert_allclose(actual, [np.nan, 1/3, 2/3, 1/3, np.nan, np.nan, np.nan, 1.], equal_nan=True)
