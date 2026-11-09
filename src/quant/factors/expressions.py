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

from quant.factors.rolling_stable import rolling_moment


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
        if isinstance(node, ast.Name):
            from quant.factors.liquidity_comovement import SIGNALS, CONTROLS
            if node.id in (*SIGNALS, *CONTROLS):
                # Raw adapter loads 61 months; daily carry needs the prior month.
                return 32
            if node.id in {'industry_momentum_6m', 'industry_leader_return_1m', 'industry_return_1m'}:
                # The separate monthly reader freezes six full months of members/weights.
                return 32
            if node.id in {'turnover_reference_gain_260w_skip1w', 'turnover_reference_gain_x_turnover_260w_skip1w',
                    'turnover_reference_equal_price_gain_260w', 'turnover_reference_mean_turnover_52w',
                    'turnover_reference_long_return_156w_skip52w'}:
                # Dedicated thin input reads retain all 260 weeks; the daily grid needs prior-month carry.
                return 32
            if node.id in {'return_seasonality_ann_y2_5','return_seasonality_nann_y2_5','return_seasonality_amn_y2_5'}:
                # Daily carry needs the prior completed publication month. The
                # dedicated endpoint reader separately loads exact M-60 prices.
                return 32
            # Intrinsic windows remain additive when a consumer nests another window.
            return {"market_beta_60_vs_510300": 60, "downside_beta_60_vs_510300": 60,
                    "amihud_illiquidity_monthly": 62, "free_float_turnover_level_monthly": 62,
                    "free_float_turnover_abnormal_12m": 400, "alpha101_007_cny_amount_gate": 66,
                    "amihud_illiquidity_monthly_calendar80_v1": 62,
                    "free_float_turnover_level_monthly_calendar80_v1": 62,
                    "free_float_turnover_abnormal_12m_calendar80_v1": 400,
                    "price_delay_d1_52w_skip1m": 400,
                    "price_delay_d2_52w_skip1m": 400,
                    "price_delay_d3_52w_skip1m": 400,
                    "statement_ear3_market_proxy_120d": 200,
                    "statement_abvol3_stable_shares_120d": 200,
                    "sue_decay_tau20": 32, "sue_decay_tau40": 32, "sue_mad8": 32,
                    "rsue8": 32, "sue_prelim": 32, "sue_prelim_r5_v1": 32,
                    "max_daily_return_20_size_turnover_residual": 20, "ivol_ff3_60": 100}.get(node.id, 0)
        if isinstance(node, ast.Constant):
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

    def __init__(self, panel: pl.DataFrame, *, window_skew: bool = False):
        self.window_skew=window_skew
        self.frame = panel.sort("symbol", "trade_date").lazy()
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
            if name in {"ts_mean", "ts_sum", "ts_std", "ts_std0"}:
                return rolling_moment(x, n, name)
            if name in _ROLLING:
                return getattr(x, _ROLLING[name])(window_size=n, min_samples=n).over("symbol")
            if name == "ts_skew":
                if n < 3:
                    raise ValueError("Skewness requires at least three sessions")
                if self.window_skew:
                    return rolling_moment(x,n,name)
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
                return rolling_moment(x, n, name)
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
                y = self._node(args[1])
                # Arithmetic paths can make the same price differ by one ULP.
                # Use the ranking precision for the constant-window decision.
                stable_x, stable_y = x.round_sig_figs(10), y.round_sig_figs(10)
                x_range = (stable_x.rolling_max(n, min_samples=n) - stable_x.rolling_min(n, min_samples=n)).over("symbol")
                y_range = (stable_y.rolling_max(n, min_samples=n) - stable_y.rolling_min(n, min_samples=n)).over("symbol")
                result = rolling_moment(x, n, name, y)
                # Snap ULP noise so later cross-sectional ranks match stable ties:
                # near-zero, and near ±1 (pandas rolling corr for short windows).
                cleaned = pl.when(result.abs() <= 1e-12).then(0.0).otherwise(result)
                if name == "ts_corr":
                    clipped = cleaned.clip(-1, 1)
                    snapped = (
                        pl.when((1.0 - clipped.abs()) <= 1e-3)
                        .then(pl.when(clipped >= 0).then(1.0).otherwise(-1.0))
                        .otherwise(clipped)
                    )
                    return pl.when((x_range > 0) & (y_range > 0)).then(snapped)
                return pl.when(x_range.is_not_null() & y_range.is_not_null()).then(
                    pl.when((x_range == 0) | (y_range == 0)).then(0.0).otherwise(cleaned)
                )
            if name == "decay_linear":
                weights = [float(i) for i in range(1, n + 1)]
                complete = x.is_not_null().cast(pl.Int32).rolling_sum(n, min_samples=n).over("symbol") == n
                return pl.when(complete).then(
                    x.cast(pl.Float64).fill_null(0).rolling_sum(n, weights=weights, min_samples=n).over("symbol") / sum(weights)
                )
            if name in {"ts_argmax", "ts_argmin"}:
                # First extremum, one-based index from the oldest observation.
                # Round like ts_rank so ULP noise cannot move the first-tie index.
                x = x.round_sig_figs(10)
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


def evaluate_expressions(panel: pl.DataFrame, expressions: dict[str, str], *, window_skew: bool = False) -> pl.DataFrame:
    """Evaluate on a unique, padded (symbol, trade_date) panel."""
    if panel.select(pl.struct("symbol", "trade_date").is_duplicated().any()).item():
        raise ValueError("Duplicate factor input keys")
    ordered = panel.sort("symbol", "trade_date")
    output = ordered.select("symbol", "trade_date")
    items = list(expressions.items())
    # A single 321-factor plan overflows the native Windows stack. Each group
    # shares its subexpressions, while bounding the optimizer's plan depth.
    for first in range(0, len(items), 64):
        engine = ExpressionEngine(ordered,window_skew=window_skew)
        columns = {name: engine.compile(expr) for name, expr in items[first:first + 64]}
        values = engine.frame.select(
            "symbol", "trade_date",
            *[pl.when(expr.is_finite()).then(expr).cast(pl.Float64).alias(name)
              for name, expr in columns.items()],
        ).collect().drop("symbol", "trade_date")
        output = output.hstack(values)
    return output
