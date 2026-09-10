"""Small, non-executable expression language for daily factor panels.

Windows count exchange sessions on a padded panel; null observations are never
skipped. Ranks use average ties on [0, 1]. No forward shifts are permitted.
"""

from __future__ import annotations

import ast
import operator
from collections.abc import Callable
from functools import reduce

import numpy as np
import polars as pl


_BINARY: dict[type[ast.operator], Callable] = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Pow: operator.pow,
}
_COMPARE: dict[type[ast.cmpop], Callable] = {
    ast.Gt: operator.gt, ast.GtE: operator.ge, ast.Lt: operator.lt,
    ast.LtE: operator.le, ast.Eq: operator.eq, ast.NotEq: operator.ne,
}
_ROLLING = {
    "ts_mean": "rolling_mean", "ts_sum": "rolling_sum", "ts_std": "rolling_std",
    "ts_min": "rolling_min", "ts_max": "rolling_max",
}
_UNARY = {"abs", "log", "exp", "sign", "sqrt", "rank", "scale"}
_WINDOW = set(_ROLLING) | {
    "ts_rank", "ts_corr", "ts_cov", "ts_argmax", "ts_argmin", "decay_linear",
    "delay", "delta", "ts_std0", "ts_skew", "ts_slope", "ts_rsquare", "ts_resi", "ts_quantile", "ts_product",
}


def _window(node: ast.AST) -> int:
    if not isinstance(node, ast.Constant) or type(node.value) is not int or node.value < 1:
        raise ValueError("Windows/lags must be positive integer constants")
    return node.value


def required_history(expression: str) -> int:
    """Return the number of preceding sessions needed, including nested windows."""
    def visit(node: ast.AST) -> int:
        if isinstance(node, (ast.Constant, ast.Name)):
            return 0
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            return visit(node.operand)
        if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
            return max(visit(node.left), visit(node.right))
        if isinstance(node, ast.Compare) and len(node.ops) == 1 and type(node.ops[0]) in _COMPARE:
            return max(visit(node.left), visit(node.comparators[0]))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords:
            name = node.func.id
            if name in _WINDOW:
                n = _window(node.args[-1])
                return max(visit(arg) for arg in node.args[:-1]) + (
                    n if name in {"delay", "delta"} else n - 1
                )
            if name in _UNARY | {"where", "ind_neutralize"}:
                return max(visit(arg) for arg in node.args)
        raise ValueError(f"Unsupported factor expression: {ast.dump(node)}")
    return visit(ast.parse(expression, mode="eval").body)


class ExpressionEngine:
    """Compile AST nodes into materialized Polars stages, never Python eval."""

    def __init__(self, panel: pl.DataFrame):
        self.frame = panel.lazy()
        self.fields = set(panel.columns)
        self.cache: dict[str, str] = {}

    def compile(self, expression: str) -> pl.Expr:
        required_history(expression)
        return self._node(ast.parse(expression, mode="eval").body)

    def _node(self, node: ast.AST) -> pl.Expr:
        key = ast.dump(node)
        if key in self.cache:
            return pl.col(self.cache[key])
        if isinstance(node, ast.Constant) and type(node.value) in {int, float}:
            return pl.lit(node.value)
        if isinstance(node, ast.Name) and node.id in self.fields and not node.id.startswith("_"):
            return pl.col(node.id)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            expr = self._node(node.operand)
            expr = -expr if isinstance(node.op, ast.USub) else expr
        elif isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
            left, right = self._node(node.left), self._node(node.right)
            expr = _BINARY[type(node.op)](left, right)
            if isinstance(node.op, ast.Div):
                expr = pl.when(right != 0).then(expr)
        elif isinstance(node, ast.Compare) and len(node.ops) == 1 and type(node.ops[0]) in _COMPARE:
            expr = _COMPARE[type(node.ops[0])](self._node(node.left), self._node(node.comparators[0]))
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords:
            expr = self._call(node.func.id, node.args)
        else:
            raise ValueError(f"Unsupported field or syntax: {ast.dump(node)}")
        # Staging permits rank(delta(...)) and ts_corr(rank(...), ...) without
        # nesting a window expression inside another window expression.
        if not isinstance(node, ast.Compare):
            expr = pl.when(expr.is_finite()).then(expr)
        name = f"_expr_{len(self.cache)}"
        self.frame = self.frame.with_columns(expr.alias(name))
        self.cache[key] = name
        return pl.col(name)

    def _call(self, name: str, args: list[ast.expr]) -> pl.Expr:
        arity = 3 if name in {"ts_corr", "ts_cov", "where", "ts_quantile"} else (
            1 if name in _UNARY else 2
        )
        if len(args) != arity:
            raise ValueError(f"{name} requires {arity} arguments")
        x = self._node(args[0])
        if name in _WINDOW:
            n = _window(args[-1])
            if name in _ROLLING:
                return getattr(x, _ROLLING[name])(window_size=n, min_samples=n).over("symbol")
            if name == "ts_std0":
                return x.rolling_std(n, min_samples=n, ddof=0).over("symbol")
            if name == "ts_skew":
                if n < 3:
                    raise ValueError("Skewness requires at least three sessions")
                return x.rolling_skew(n, min_samples=n, bias=False).over("symbol")
            if name == "ts_product":
                return reduce(operator.mul, (x.shift(lag).over("symbol") for lag in range(n)))
            if name == "ts_quantile":
                probability = args[1]
                if (not isinstance(probability, ast.Constant)
                        or isinstance(probability.value, bool)
                        or not isinstance(probability.value, (int, float))
                        or not 0 <= probability.value <= 1):
                    raise ValueError("Quantile must be a constant probability in [0, 1]")
                return x.rolling_quantile(
                    float(probability.value), interpolation="linear", window_size=n, min_samples=n,
                ).over("symbol")
            if name in {"ts_slope", "ts_rsquare", "ts_resi"}:
                if n < 2:
                    raise ValueError("Regression requires at least two sessions")
                centered_time = [i - (n - 1) / 2 for i in range(n)]
                time_ss = n * (n * n - 1) / 12
                complete = x.is_not_null().cast(pl.Int32).rolling_sum(n, min_samples=n).over("symbol") == n
                # Weighted kernels cannot consume nulls. The separate complete
                # window mask prevents the zero placeholders from becoming data.
                slope = x.fill_null(0).rolling_sum(
                    n, weights=centered_time, min_samples=n,
                ).over("symbol") / time_ss
                if name == "ts_slope":
                    result = slope
                elif name == "ts_resi":
                    result = x - x.rolling_mean(n, min_samples=n).over("symbol") - slope * (n - 1) / 2
                else:
                    variance = x.rolling_var(n, min_samples=n, ddof=1).over("symbol")
                    # Match Qlib's undefined-R² guard for near-constant prices.
                    result = pl.when(variance > 2e-5 ** 2).then(
                        (slope ** 2 * time_ss / ((n - 1) * variance)).clip(0, 1)
                    )
                return pl.when(complete).then(result)
            if name == "delay":
                return x.shift(n).over("symbol")
            if name == "delta":
                return x - x.shift(n).over("symbol")
            if name == "ts_rank":
                if n < 2:
                    raise ValueError("ts_rank needs at least two sessions")
                x = x.round_sig_figs(10)
                complete = x.is_not_null().cast(pl.Int32).rolling_sum(n, min_samples=n).over("symbol") == n
                return pl.when(complete).then(
                    (x.rolling_rank(n, min_samples=n).over("symbol") - 1) / (n - 1)
                )
            if name in {"ts_corr", "ts_cov"}:
                if n < 2:
                    return pl.lit(None, dtype=pl.Float64)
                fn = pl.rolling_corr if name == "ts_corr" else pl.rolling_cov
                y = self._node(args[1])
                # Arithmetic paths can make the same price differ by one ULP.
                # Use the ranking precision for the constant-window decision.
                stable_x, stable_y = x.round_sig_figs(10), y.round_sig_figs(10)
                x_range = (stable_x.rolling_max(n, min_samples=n) - stable_x.rolling_min(n, min_samples=n)).over("symbol")
                y_range = (stable_y.rolling_max(n, min_samples=n) - stable_y.rolling_min(n, min_samples=n)).over("symbol")
                result = fn(x, y, window_size=n, min_samples=n, ddof=1).over("symbol")
                if name == "ts_corr":
                    return pl.when((x_range > 0) & (y_range > 0)).then(result.clip(-1, 1))
                return pl.when(x_range.is_not_null() & y_range.is_not_null()).then(
                    pl.when((x_range == 0) | (y_range == 0)).then(0.0).otherwise(result)
                )
            if name == "decay_linear":
                weights = [float(i) for i in range(1, n + 1)]
                complete = x.is_not_null().cast(pl.Int32).rolling_sum(n, min_samples=n).over("symbol") == n
                return pl.when(complete).then(
                    x.cast(pl.Float64).fill_null(0).rolling_sum(n, weights=weights, min_samples=n).over("symbol") / sum(weights)
                )
            if name in {"ts_argmax", "ts_argmin"}:
                # First extremum, one-based index from the oldest observation.
                maximum = name == "ts_argmax"
                def positions(series: pl.Series) -> pl.Series:
                    values = series.cast(pl.Float64).to_numpy()
                    result = np.full(len(values), np.nan)
                    if len(values) >= n:
                        windows = np.lib.stride_tricks.sliding_window_view(values, n)
                        complete = np.isfinite(windows).all(axis=1)
                        index = windows.argmax(axis=1) if maximum else windows.argmin(axis=1)
                        result[n - 1:] = np.where(complete, index + 1, np.nan)
                    return pl.Series(result, nan_to_null=True)
                return x.map_batches(positions, return_dtype=pl.Float64).over("symbol")
        if name == "rank":
            # Numerical ties should not depend on summation order in prior kernels.
            x = x.round_sig_figs(10)
            count = x.count().over("trade_date")
            return pl.when(count >= 2).then((x.rank("average").over("trade_date") - 1) / (count - 1))
        if name == "scale":
            total = x.abs().sum().over("trade_date")
            return pl.when(total > 0).then(x / total)
        if name == "ind_neutralize":
            group = args[1]
            if not isinstance(group, ast.Name) or group.id not in self.fields:
                raise ValueError("ind_neutralize requires a supplied PIT industry field")
            return pl.when(pl.col(group.id).is_not_null()).then(
                x - x.mean().over("trade_date", group.id)
            )
        if name == "where":
            return pl.when(x.is_not_null()).then(
                pl.when(x).then(self._node(args[1])).otherwise(self._node(args[2]))
            )
        if name in {"abs", "sign", "sqrt", "log", "exp"}:
            expr = getattr(x, name)()
            if name == "log":
                return pl.when(x > 0).then(expr)
            if name == "sqrt":
                return pl.when(x >= 0).then(expr)
            return expr
        raise ValueError(f"Unknown factor operator: {name}")


def evaluate_expressions(panel: pl.DataFrame, expressions: dict[str, str]) -> pl.DataFrame:
    """Evaluate on a unique, padded (symbol, trade_date) panel."""
    if panel.select(pl.struct("symbol", "trade_date").is_duplicated().any()).item():
        raise ValueError("Duplicate factor input keys")
    ordered = panel.sort("symbol", "trade_date")
    output = ordered.select("symbol", "trade_date")
    items = list(expressions.items())
    # A single 321-factor plan overflows the native Windows stack. Each group
    # shares its subexpressions, while bounding the optimizer's plan depth.
    for first in range(0, len(items), 64):
        engine = ExpressionEngine(ordered)
        columns = {name: engine.compile(expr) for name, expr in items[first:first + 64]}
        values = engine.frame.select(
            "symbol", "trade_date",
            *[pl.when(expr.is_finite()).then(expr).cast(pl.Float64).alias(name)
              for name, expr in columns.items()],
        ).collect().drop("symbol", "trade_date")
        output = output.hstack(values)
    return output
