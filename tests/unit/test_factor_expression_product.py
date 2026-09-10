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


def test_correlation_treats_ulp_price_variations_as_a_constant_window():
    panel = pl.DataFrame({"symbol": ["a"] * 6, "trade_date": list(range(6)),
                          "x": [123., 122., 121., 120.1805425, 120.18054250000002, 120.1805425],
                          "y": [56., 55.5, 55., 54.5629068, 53.920281625, 53.53186545]})
    actual = evaluate_expressions(panel, {"corr": "ts_corr(x, y, 3)", "cov": "ts_cov(x, y, 3)"})
    assert actual["corr"][-1] is None and actual["cov"][-1] == 0
    # Preserve relative variation in genuinely tiny signals.
    small = panel.with_columns(pl.Series("x", [1e-18, 2e-18, 3e-18, 4e-18, 5e-18, 6e-18]))
    assert evaluate_expressions(small, {"corr": "ts_corr(x, y, 3)"})["corr"][-1] is not None
